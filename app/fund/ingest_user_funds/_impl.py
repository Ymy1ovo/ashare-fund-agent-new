"""阶段3B-5.3 用户自选场外基金受控数据接入 V1.0。

与「查询」完全分离：3B-5.2 的 `--code` 永远只读，本模块是唯一的写入入口。

流程：
  校验代码 → 取基本信息 → 判定产品结构/场外范围 → 取份额 → 取净值/货币收益
  → 质量审计 → 写来源/采集时间/证据等级 → 输出结果

硬边界：
- 不抓支付宝内部接口、不逆向 APP、不用来源不明数据；
- 不填 0、不用当前日期伪造成立日、不用平台观测日期冒充报告期；
- 支付宝可购买状态恒 unknown；天天基金费率不冒充支付宝费率；
- 每只基金接入前后记录行数与指纹；重复接入幂等；失败不留半成品。
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from app.config import settings
from app.database.db import get_connection
from app.fund.models import (
    DividendRecord, FundMasterRecord, FundShareClassRecord, NavRecord,
)
from app.fund.normalize import (
    base_fund_name, detect_share_class_type, is_money_fund,
    parse_cash_per_share, to_float, to_iso_date,
)
from app.fund.repo_base import now_iso
from app.fund.repo_nav import NavRepository
from app.fund.repo_quality import QualityRepository
from app.fund.repository import FundRepository
from app.fund.research.classification import (
    ONSHORE_ETF_CODES, classify_fund, is_offmarket_pool,
)

# 数据源（只用于 3B-3 已审计通过的 AKShare 接口）
SOURCE_BASIC = "akshare.fund_individual_basic_info_xq"
SOURCE_NAV = "akshare.fund_open_fund_info_em"
SOURCE_MONEY = "akshare.fund_money_fund_info_em"
SOURCE_DIVIDEND = "akshare.fund_open_fund_info_em"

EVIDENCE_THIRD_PARTY = "third_party"
EVIDENCE_PLATFORM = "platform_observation"

# 接入状态
ST_INGESTED = "ingested"
ST_ALREADY_PRESENT = "already_present"
ST_NOT_FOUND = "not_found"
ST_INVALID_CODE = "invalid_code"
ST_EXCLUDED = "excluded_product"
ST_FAILED = "failed"
ST_TIMEOUT = "timeout"

MAX_GAP_DAYS = 15


# ---------------------------------------------------------------- 指纹工具
_FP_TABLES = (
    "fund_master", "fund_share_classes", "fund_nav_daily", "fund_dividends",
    "fund_manager_history", "fund_aum_history", "fund_fee_rules",
    "fund_subscription_status", "fund_lifecycle_events", "fund_data_quality",
)

_FP_ORDER = {
    "fund_master": ("fund_id",),
    "fund_share_classes": ("share_class_id",),
    "fund_nav_daily": ("share_class_id", "nav_date", "nav_kind"),
    "fund_dividends": ("dividend_id",),
    "fund_manager_history": ("manager_id",),
    "fund_aum_history": ("aum_id",),
    "fund_fee_rules": ("fee_rule_id",),
    "fund_subscription_status": ("status_id",),
    "fund_lifecycle_events": ("event_id",),
    "fund_data_quality": ("quality_id",),
}

# 采集时间类列不参与内容指纹：每次写入都会变，计入会误判「内容变了」
_FP_SKIP_COLUMNS = {"ingested_at", "fetched_at", "checked_at",
                    "source_updated_at"}


def _stable_value(v):
    """把单个值序列化成**带类型标签的 JSON 值**，保留类型区分。

    返回 (type_tag, payload) 二元组，配合 json.dumps 做无歧义编码：
    - NULL / bool / int / float / bytes / str 互不混淆；
    - payload 是字符串/数字本身，由 JSON 负责转义，不依赖分隔符。
    """
    if v is None:
        return ("null", None)
    if isinstance(v, bool):
        return ("bool", int(v))
    if isinstance(v, int):
        return ("int", v)
    if isinstance(v, float):
        # repr 保精度；nan/inf 用字符串承载，避免 JSON 非法
        if math.isnan(v):
            return ("float", "nan")
        if math.isinf(v):
            return ("float", "inf" if v > 0 else "-inf")
        return ("float", repr(v))
    if isinstance(v, bytes):
        return ("bytes", v.hex())
    return ("str", str(v))


def _encode_row(values) -> bytes:
    """把一行值编码成**无歧义**的稳定字节串。

    用 JSON 数组承载 [[type, value], ...]：
    JSON 会转义引号、反斜杠、换行与竖线等字符，
    因此 `("a|b", "c")` 与 `("a", "b|c")` 必然产生不同字节串。
    同时保留 NULL / int / float / str / bytes 的类型标签。
    """
    return json.dumps([list(_stable_value(v)) for v in values],
                      ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _table_digest(conn, table: str) -> tuple[str, int]:
    """单表**真实内容指纹**：逐行逐列稳定序列化后 SHA256。"""
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    if not cols:
        return hashlib.sha256(b"@no-table").hexdigest(), 0
    use_cols = [c for c in cols if c not in _FP_SKIP_COLUMNS]
    order = [c for c in _FP_ORDER.get(table, ()) if c in cols]
    order_sql = (" ORDER BY " + ", ".join(order)) if order else ""
    sql = "SELECT " + ", ".join(use_cols) + f" FROM {table}{order_sql}"

    h = hashlib.sha256()
    h.update(("@cols:" + ",".join(use_cols)).encode())
    n = 0
    for row in conn.execute(sql):
        h.update(_encode_row([row[i] for i in range(len(use_cols))]))
        n += 1
    return h.hexdigest(), n


def db_fingerprint(db_path: Path | None = None) -> dict:
    """**真实内容指纹**，覆盖全部 fund_* 表。

    旧实现只汇总行数与字段文本长度，无法识别「同长度内容变化」。
    现在逐行逐列稳定序列化后算 SHA256，因此
    行数不变、字段长度不变、只改一个值，指纹也会变。
    """
    p = Path(db_path or settings.database_path)
    tables: dict[str, dict] = {}
    with get_connection(p) as conn:
        for t in _FP_TABLES:
            digest, rows = _table_digest(conn, t)
            tables[t] = {"rows": rows, "sha256": digest}

    total = hashlib.sha256()
    for t in _FP_TABLES:
        total.update(f"@{t}:{tables[t]['rows']}:{tables[t]['sha256']};".encode())

    return {
        "row_counts": {t: tables[t]["rows"] for t in _FP_TABLES},
        "table_digests": tables,
        "total_rows": sum(tables[t]["rows"] for t in _FP_TABLES),
        "sha256": total.hexdigest(),
        "algorithm": "sha256(stable_serialized_rows)",
        "note": ("真实内容指纹：逐行逐列稳定序列化后 SHA256；覆盖全部 fund_* 表；"
                 "排除 ingested_at 等采集时间列"),
    }


def backup_database(db_path: Path | None = None, tag: str = "3b5_3") -> Path:
    """接入前备份。"""
    src = Path(db_path or settings.database_path)
    d = src.parent / "backups"
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = d / f"fund_agent_before_{tag}_{stamp}.db"
    s = sqlite3.connect(str(src))
    t = sqlite3.connect(str(dst))
    try:
        s.backup(t)
    finally:
        t.close()
        s.close()
    return dst


# ---------------------------------------------------------------- 默认抓取器
def _fetch_basic_default(code: str) -> dict:
    import akshare as ak
    df = ak.fund_individual_basic_info_xq(symbol=code)
    kv = {str(r["item"]).strip(): str(r["value"]).strip()
          for _, r in df.iterrows()}
    return {
        "name": kv.get("基金名称"),
        "full_name": kv.get("基金全称"),
        "established": kv.get("成立时间"),
        "company": kv.get("基金公司"),
        "manager": kv.get("基金经理"),
        "type": kv.get("基金类型"),
        "benchmark": kv.get("业绩比较基准"),
        "custodian": kv.get("托管银行"),
        "invest_scope": kv.get("投资目标"),
    }


def _fetch_nav_default(code: str, kind: str) -> list[dict]:
    import akshare as ak
    if kind == "unit":
        df = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")
        return [{"nav_date": r["净值日期"], "unit_nav": r["单位净值"]}
                for _, r in df.iterrows()]
    if kind == "acc":
        df = ak.fund_open_fund_info_em(symbol=code, indicator="累计净值走势")
        return [{"nav_date": r["净值日期"], "acc_nav": r["累计净值"]}
                for _, r in df.iterrows()]
    return []


def _fetch_money_default(code: str) -> list[dict]:
    import akshare as ak
    df = ak.fund_money_fund_info_em(symbol=code)
    return [{"nav_date": r["净值日期"],
             "per_10k_yield": r["每万份收益"],
             "seven_day_annual": r["7日年化收益率"]}
            for _, r in df.iterrows()]


def _fetch_dividend_default(code: str) -> list[dict]:
    import akshare as ak
    try:
        df = ak.fund_open_fund_info_em(symbol=code, indicator="分红送配详情")
    except Exception:
        return []
    if df is None or len(df) == 0:
        return []
    return [{"record_date": r.get("权益登记日"), "ex_date": r.get("除息日"),
             "pay_date": r.get("分红发放日"),
             "per_10_raw": r.get("每10份分红")}
            for _, r in df.iterrows()]


# ---------------------------------------------------------------- 结果
@dataclass
class IngestResult:
    code: str
    status: str
    reason: str = ""
    fund_id: int | None = None
    share_ids: list[int] = field(default_factory=list)
    share_codes: list[str] = field(default_factory=list)
    product_class: str | None = None
    investment_subtype: str | None = None
    nav_kind: str | None = None
    nav_rows_written: int = 0
    nav_rows_total: int = 0
    dividend_rows: int = 0
    date_min: str | None = None
    date_max: str | None = None
    quality: dict = field(default_factory=dict)
    fingerprint_before: dict | None = None
    fingerprint_after: dict | None = None
    sources: list[str] = field(default_factory=list)
    evidence_levels: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "code": self.code, "status": self.status, "reason": self.reason,
            "fund_id": self.fund_id,
            "share_ids": self.share_ids, "share_codes": self.share_codes,
            "product_class": self.product_class,
            "investment_subtype": self.investment_subtype,
            "nav_kind": self.nav_kind,
            "nav_rows_written": self.nav_rows_written,
            "nav_rows_total": self.nav_rows_total,
            "dividend_rows": self.dividend_rows,
            "date_min": self.date_min, "date_max": self.date_max,
            "quality": self.quality,
            "fingerprint_before": self.fingerprint_before,
            "fingerprint_after": self.fingerprint_after,
            "sources": sorted(set(self.sources)),
            "evidence_levels": sorted(set(self.evidence_levels)),
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------- 质量审计
def audit_new_nav(db_path: Path | None, share_class_id: int,
                  *, nav_kind: str = "net_value",
                  conn: "sqlite3.Connection | None" = None) -> dict:
    """接入后质量审计（只读）。

    conn 非空时复用该连接（在同一事务内读取，能看到未提交的写入）。
    """
    if conn is not None:
        rows = [dict(r) for r in conn.execute(
            """SELECT nav_date, unit_nav, acc_nav, per_10k_yield FROM fund_nav_daily
               WHERE share_class_id=? AND nav_kind=? ORDER BY nav_date""",
            (share_class_id, nav_kind)).fetchall()]
    else:
        with get_connection(db_path) as own:
            rows = [dict(r) for r in own.execute(
                """SELECT nav_date, unit_nav, acc_nav, per_10k_yield FROM fund_nav_daily
                   WHERE share_class_id=? AND nav_kind=? ORDER BY nav_date""",
                (share_class_id, nav_kind)).fetchall()]
    if not rows:
        return {"rows": 0, "status": "no_data", "nav_kind": nav_kind,
                "continuity_verification": "cannot_verify"}

    dates = [r["nav_date"] for r in rows]
    gaps = []
    max_gap = 0
    for a, b in zip(dates, dates[1:]):
        da = datetime.strptime(a, "%Y-%m-%d")
        db_ = datetime.strptime(b, "%Y-%m-%d")
        delta = (db_ - da).days
        max_gap = max(max_gap, delta)
        if delta > MAX_GAP_DAYS:
            gaps.append({"from": a, "to": b, "days": delta})

    if nav_kind == "net_value":
        null_unit = sum(1 for r in rows if r["unit_nav"] is None)
        null_acc = sum(1 for r in rows if r["acc_nav"] is None)
        nonpositive = sum(1 for r in rows
                          if r["unit_nav"] is not None and r["unit_nav"] <= 0)
        same = sum(1 for r in rows
                   if r["unit_nav"] is not None and r["acc_nav"] is not None
                   and abs(r["acc_nav"] - r["unit_nav"]) < 1e-9)
        acc_ratio = round(same / len(rows), 4)
        has_div_effect = acc_ratio < 0.999
    else:
        null_unit = null_acc = nonpositive = 0
        acc_ratio = None
        has_div_effect = None

    return {
        "rows": len(rows),
        "status": "ok",
        "nav_kind": nav_kind,
        "date_min": dates[0], "date_max": dates[-1],
        "duplicate_dates": 0,  # DDL UNIQUE 约束保证
        "out_of_order": 0,     # SQL ORDER BY
        "null_unit_nav": null_unit,
        "null_acc_nav": null_acc,
        "nonpositive_unit_nav": nonpositive,
        "max_gap_days": max_gap,
        "gap_count_over_15d": len(gaps),
        "gaps_sample": gaps[:5],
        "acc_equals_unit_ratio": acc_ratio,
        "has_dividend_effect": has_div_effect,
        "continuity_verification": "cannot_verify",
        "continuity_note": ("无真实基金净值公布日历；"
                            "不使用 A 股交易日历代理，连续性只能 cannot_verify"),
    }


# ---------------------------------------------------------------- 接入器
class UserFundIngestor:
    """单基金受控接入。所有外部访问可注入，便于测试。"""

    _tx: "sqlite3.Connection | None" = None

    def __init__(self, db_path: Path | None = None, *,
                 fetch_basic: Callable[[str], dict] | None = None,
                 fetch_nav: Callable[[str, str], list[dict]] | None = None,
                 fetch_money: Callable[[str], list[dict]] | None = None,
                 fetch_dividend: Callable[[str], list[dict]] | None = None,
                 timeout_sec: float = 60.0):
        self.db_path = db_path
        self.funds = FundRepository(db_path)
        self.nav = NavRepository(db_path)
        self.quality = QualityRepository(db_path)
        self._basic = fetch_basic or _fetch_basic_default
        self._nav = fetch_nav or _fetch_nav_default
        self._money = fetch_money or _fetch_money_default
        self._div = fetch_dividend or _fetch_dividend_default
        self.timeout_sec = timeout_sec

    # ---------- 预检 ----------
    def precheck(self, code: str) -> tuple[str, str]:
        import re
        if not re.match(r"^[0-9]{6}$", str(code or "").strip()):
            return ST_INVALID_CODE, f"代码格式非法（要求 6 位数字）：{code}"
        if code in ONSHORE_ETF_CODES:
            return ST_EXCLUDED, "场内 ETF 不进入场外基金数据层"
        return ST_INGESTED, ""

    # ---------- 主流程 ----------
    # ---------- 事务辅助 ----------
    def _open_tx(self):
        """打开接入专用连接，并关闭 SQLite 自动提交，由本类掌控事务边界。

        必须在 BEGIN IMMEDIATE **之前**启用外键约束：
        SQLite 默认 foreign_keys=OFF，若不显式开启，
        写入不存在的 fund_id 也不会被拒绝，等于放弃了引用完整性保护。

        这里**只**改本连接的 PRAGMA，不触碰项目全局连接行为。
        若开启失败立即报错，绝不带着未启用的外键继续接入。
        """
        p = Path(self.db_path or settings.database_path)
        conn = sqlite3.connect(str(p), timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.execute("PRAGMA busy_timeout = 5000")

        # ① 先开外键
        conn.execute("PRAGMA foreign_keys = ON")
        # ② 读回确认（PRAGMA 可能被静默忽略）
        enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        if int(enabled) != 1:
            conn.close()
            raise RuntimeError(
                "接入事务连接未能启用外键约束（PRAGMA foreign_keys 返回 "
                f"{enabled!r}）；拒绝继续接入，避免写入失去引用完整性保护")

        # ③ 再开事务
        conn.execute("BEGIN IMMEDIATE")
        return conn

    def _commit_tx(self) -> None:
        if self._tx is not None:
            self._tx.execute("COMMIT")
            self._tx.close()
            self._tx = None

    def _rollback_tx(self) -> None:
        if self._tx is not None:
            try:
                self._tx.execute("ROLLBACK")
            except Exception:
                pass
            self._tx.close()
            self._tx = None

    def ingest_one(self, code: str, *,
                   allow_update: bool = True) -> IngestResult:
        """公开入口：保证写入阶段是**真正的单基金原子事务**。

        写入阶段任一异常 → 整只基金 ROLLBACK，并如实返回 failed，
        **不**用「捕获异常后继续返回成功」掩盖写入失败。
        """
        self._tx = None
        try:
            return self._ingest_impl(code, allow_update=allow_update)
        except Exception as exc:
            self._rollback_tx()
            res = IngestResult(code=str(code or "").strip(), status=ST_FAILED)
            res.reason = (f"写入失败，事务已回滚，未留下半成品："
                          f"{type(exc).__name__}: {exc}")
            try:
                res.fingerprint_after = db_fingerprint(self.db_path)
            except Exception:
                pass
            return res
        finally:
            # 任何遗漏的未提交事务都不允许悬挂
            if self._tx is not None:
                self._rollback_tx()

    def _ingest_impl(self, code: str, *,
                     allow_update: bool = True) -> IngestResult:
        code = str(code or "").strip()
        res = IngestResult(code=code, status=ST_INGESTED)

        st, why = self.precheck(code)
        if st != ST_INGESTED:
            res.status, res.reason = st, why
            return res

        res.fingerprint_before = db_fingerprint(self.db_path)

        # 已存在则直接返回（幂等）
        existing = self._existing_fund(code)
        if existing is not None:
            res.status = ST_ALREADY_PRESENT
            res.reason = "该代码已在库中，未重复写入（幂等）"
            res.fund_id = existing["fund_id"]
            res.share_ids = existing["share_ids"]
            res.share_codes = existing["share_codes"]
            res.product_class = existing["product_class"]
            res.fingerprint_after = db_fingerprint(self.db_path)
            res.quality = (audit_new_nav(self.db_path, existing["share_ids"][0])
                           if existing["share_ids"] else {})
            res.nav_rows_total = res.quality.get("rows", 0)
            res.nav_kind = (res.quality.get("nav_kind")
                            or ("money_yield"
                                if existing["product_class"] == "money_market"
                                else "net_value"))
            res.date_min = res.quality.get("date_min")
            res.date_max = res.quality.get("date_max")
            return res

        # 外部取数（失败不留半成品：先全部取到内存，再一次性写）
        try:
            basic = self._basic(code) or {}
        except Exception as exc:
            res.status = (ST_TIMEOUT if "timeout" in type(exc).__name__.lower()
                          else ST_FAILED)
            res.reason = f"基本信息获取失败：{type(exc).__name__}: {exc}"
            res.fingerprint_after = db_fingerprint(self.db_path)
            return res

        name = basic.get("name") or ""
        if not name:
            res.status = ST_NOT_FOUND
            res.reason = f"接口未返回该代码的基本信息（{code} 可能不存在）"
            res.fingerprint_after = db_fingerprint(self.db_path)
            return res

        # 产品分类（用与 3B-5.x 相同的规则，不按名称猜跟踪指数）
        row = {"fund_name": name,
               "fund_full_name": basic.get("full_name"),
               "fund_type_l1": basic.get("type"),
               "fund_type_l2": basic.get("type"), "is_index_fund":
               (1 if basic.get("type") and "指数" in str(basic.get("type"))
                else None)}
        cls = classify_fund(row)

        if not is_offmarket_pool(cls, code):
            res.status = ST_EXCLUDED
            res.reason = (f"产品分类 {cls['product_class']} 不属于场外默认范围"
                          f"（{cls['basis']}）")
            res.product_class = cls["product_class"]
            res.fingerprint_after = db_fingerprint(self.db_path)
            return res

        money = cls["product_class"] == "money_market" or is_money_fund(name)

        # 先把数据全取到内存
        try:
            if money:
                nav_rows = self._money(code) or []
            else:
                unit = self._nav(code, "unit") or []
                acc = self._nav(code, "acc") or []
                nav_rows = {"unit": unit, "acc": acc}
            div_rows = [] if money else (self._div(code) or [])
        except Exception as exc:
            res.status = (ST_TIMEOUT if "timeout" in type(exc).__name__.lower()
                          else ST_FAILED)
            res.reason = f"净值获取失败：{type(exc).__name__}: {exc}"
            res.fingerprint_after = db_fingerprint(self.db_path)
            return res

        # 无任何净值 → 不写入，标记无数据
        has_nav = (bool(nav_rows) if money
                   else bool(nav_rows.get("unit") or nav_rows.get("acc")))
        if not has_nav:
            res.status = ST_FAILED
            res.reason = "接口未返回任何净值/货币收益记录；不写入半成品"
            res.fingerprint_after = db_fingerprint(self.db_path)
            return res

        # ---- 写入阶段：先开启真实事务，所有写入共用同一 conn ----
        # 任一环节异常 → 整体 ROLLBACK，不留新建本体/份额/净值/分红/质量记录。
        ts = now_iso()
        self._tx = self._open_tx()
        conn = self._tx
        res.sources.append(SOURCE_BASIC)
        res.evidence_levels.append(EVIDENCE_THIRD_PARTY)
        # ---- A/C/E 归组：基础名相同 → 挂到已存在本体，不新建重复本体 ----
        base_name = base_fund_name(name) or name
        existing_fund_id, entity_reason = self._find_same_entity(
            base_name, basic.get("company"))
        if existing_fund_id is not None:
            share = FundShareClassRecord(
                share_class_code=code,
                share_class_name=name,
                source=SOURCE_BASIC,
                ingested_at=ts,
                share_class_type=detect_share_class_type(name),
                is_primary=0,   # 后接入的份额不是主份额
                source_updated_at=ts,
            )
            sc_id = self.funds.upsert_share_class(existing_fund_id, share, conn=conn)
            res.fund_id = existing_fund_id
            res.share_ids = [sc_id]
            res.share_codes = [code]
            res.product_class = cls["product_class"]
            res.investment_subtype = cls["investment_subtype"]
            res.sources.extend([SOURCE_BASIC, SOURCE_NAV if not money else SOURCE_MONEY])
            res.evidence_levels.append(EVIDENCE_THIRD_PARTY)
            res.warnings.append(entity_reason +
                                "（A/C/E 同一组合，表现不重复计数）")

            written = 0
            if money:
                recs = []
                for r in nav_rows:
                    p10 = to_float(r.get("per_10k_yield"))
                    d = to_iso_date(r.get("nav_date"))
                    if p10 is None or not d:
                        continue
                    recs.append(NavRecord(
                        nav_date=d, nav_kind="money_yield", per_10k_yield=p10,
                        seven_day_annual=to_float(r.get("seven_day_annual")),
                        source=SOURCE_MONEY, ingested_at=ts))
                st_nav = self.nav.upsert_nav_batch(sc_id, recs, conn=conn)
                written = st_nav["inserted"] + st_nav["updated"]
                res.nav_kind = "money_yield"
            else:
                unit_map, acc_map = {}, {}
                for r in nav_rows.get("unit") or []:
                    d = to_iso_date(r.get("nav_date"))
                    v = to_float(r.get("unit_nav"))
                    if d and v is not None:
                        unit_map[d] = v
                for r in nav_rows.get("acc") or []:
                    d = to_iso_date(r.get("nav_date"))
                    v = to_float(r.get("acc_nav"))
                    if d and v is not None:
                        acc_map[d] = v
                recs = [NavRecord(nav_date=d, nav_kind="net_value",
                                  unit_nav=unit_map[d], acc_nav=acc_map.get(d),
                                  source=SOURCE_NAV, ingested_at=ts)
                        for d in sorted(unit_map)]
                st_nav = self.nav.upsert_nav_batch(sc_id, recs, conn=conn)
                written = st_nav["inserted"] + st_nav["updated"]
                res.nav_kind = "net_value"

            res.nav_rows_written = written
            res.quality = audit_new_nav(self.db_path, sc_id,
                                        nav_kind=res.nav_kind, conn=conn)
            res.nav_rows_total = res.quality.get("rows", 0)
            res.date_min = res.quality.get("date_min")
            res.date_max = res.quality.get("date_max")
            self._commit_tx()
            res.fingerprint_after = db_fingerprint(self.db_path)
            res.status = ST_INGESTED
            res.reason = "接入成功（归入已存在本体）"
            return res

        # 未自动归组时保留判定说明，供人工核验
        if any(k in entity_reason for k in ("人工核验", "不一致", "不自动归组")):
            res.warnings.append(entity_reason)

        master = FundMasterRecord(
            fund_code_primary=code,
            fund_name=base_name,
            source=SOURCE_BASIC,
            ingested_at=ts,
            fund_full_name=basic.get("full_name"),
            fund_company=basic.get("company"),
            custodian=basic.get("custodian"),
            fund_type_l1=basic.get("type"),
            fund_type_l2=basic.get("type"),
            invest_scope=basic.get("invest_scope"),
            benchmark=basic.get("benchmark"),
            established_date=to_iso_date(basic.get("established")),
            terminated_date=None,
            lifecycle_status="unknown",
            is_index_fund=row["is_index_fund"],
            tracking_index=None,
            needs_review=0,
            source_updated_at=ts,
        )
        fund_id = self.funds.upsert_master(master, conn=conn)
        res.fund_id = fund_id

        share = FundShareClassRecord(
            share_class_code=code,
            share_class_name=name,
            source=SOURCE_BASIC,
            ingested_at=ts,
            share_class_type=detect_share_class_type(name),
            is_primary=1,
            source_updated_at=ts,
        )
        sc_id = self.funds.upsert_share_class(fund_id, share, conn=conn)
        res.share_ids = [sc_id]
        res.share_codes = [code]
        res.product_class = cls["product_class"]
        res.investment_subtype = cls["investment_subtype"]

        # 净值
        written = 0
        if money:
            recs = []
            for r in nav_rows:
                p10 = to_float(r.get("per_10k_yield"))
                if p10 is None:
                    continue  # 空值不填 0
                d = to_iso_date(r.get("nav_date"))
                if not d:
                    continue
                recs.append(NavRecord(
                    nav_date=d, nav_kind="money_yield",
                    per_10k_yield=p10,
                    seven_day_annual=to_float(r.get("seven_day_annual")),
                    source=SOURCE_MONEY, ingested_at=ts))
            st_nav = self.nav.upsert_nav_batch(sc_id, recs, conn=conn)
            written = st_nav["inserted"] + st_nav["updated"]
            res.nav_kind = "money_yield"
            res.sources.append(SOURCE_MONEY)
        else:
            unit_map, acc_map = {}, {}
            for r in nav_rows.get("unit") or []:
                d = to_iso_date(r.get("nav_date"))
                v = to_float(r.get("unit_nav"))
                if d and v is not None:
                    unit_map[d] = v
            for r in nav_rows.get("acc") or []:
                d = to_iso_date(r.get("nav_date"))
                v = to_float(r.get("acc_nav"))
                if d and v is not None:
                    acc_map[d] = v
            recs = []
            for d in sorted(unit_map):
                recs.append(NavRecord(
                    nav_date=d, nav_kind="net_value",
                    unit_nav=unit_map[d], acc_nav=acc_map.get(d),
                    source=SOURCE_NAV, ingested_at=ts))
            st_nav = self.nav.upsert_nav_batch(sc_id, recs, conn=conn)
            written = st_nav["inserted"] + st_nav["updated"]
            res.nav_kind = "net_value"
            res.sources.append(SOURCE_NAV)

        res.nav_rows_written = written

        # 分红（仅净值型；空值跳过）
        if div_rows:
            drecs = []
            for r in div_rows:
                cash = parse_cash_per_share(r.get("per_10_raw"))
                if cash is None:
                    continue
                drecs.append(DividendRecord(
                    ex_date=to_iso_date(r.get("ex_date")) or "",
                    cash_per_share=cash,
                    per_10_raw=str(r.get("per_10_raw") or ""),
                    record_date=to_iso_date(r.get("record_date")),
                    pay_date=to_iso_date(r.get("pay_date")),
                    source=SOURCE_DIVIDEND, ingested_at=ts))
            drecs = [x for x in drecs if x.ex_date]
            if drecs:
                dr = self.nav.upsert_dividend_batch(sc_id, drecs, conn=conn)
                res.dividend_rows = dr.get("inserted", 0)
                res.sources.append(SOURCE_DIVIDEND)

        # 质量审计（在同一事务内读取，能看到尚未提交的写入）
        res.quality = audit_new_nav(self.db_path, sc_id,
                                    nav_kind=res.nav_kind, conn=conn)
        res.nav_rows_total = res.quality.get("rows", 0)
        res.date_min = res.quality.get("date_min")
        res.date_max = res.quality.get("date_max")

        # 质量留痕（不删除历史，只追加）
        if res.quality.get("gap_count_over_15d"):
            from app.fund.models import DataQualityRecord
            self.quality.record(DataQualityRecord(
                table_name="fund_nav_daily",
                record_key=f"{code}:gap",
                check_name="nav_gap_over_15d",
                status="warning",
                detail=f"接入时发现 {res.quality['gap_count_over_15d']} 处 >15 天缺口",
                severity="warning",
                checked_at=ts,
            ), conn=conn)
            res.warnings.append(
                f"存在 {res.quality['gap_count_over_15d']} 处 >15 天缺口，"
                "不得视为连续历史")

        # 全部写入成功 → 提交
        self._commit_tx()
        res.fingerprint_after = db_fingerprint(self.db_path)
        res.status = ST_INGESTED
        res.reason = "接入成功"
        return res

    def _find_same_entity(self, base_name: str,
                          company: str | None) -> tuple[int | None, str]:
        """按**基础名 + 基金公司**查找已存在本体，用于 A/C/E 归组。

        收紧规则（3B-5.3.1）：
        1. 基础名必须**完全一致**，不做模糊匹配；
        2. 双方公司信息必须**均非空且完全一致**才允许自动归组；
        3. 任一方公司缺失 → **不合并**，标记需人工核验；
        4. 公司不一致 → 绝不合并。

        返回 (fund_id | None, 判定说明)。
        """
        if not base_name:
            return None, "基础名为空，不自动归组"

        name_norm = base_name.strip()
        company_norm = (company or "").strip()

        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                """SELECT fund_id, fund_name, fund_company FROM fund_master
                   WHERE lifecycle_status <> 'terminated'""").fetchall()

        same_name = [r for r in rows
                     if (r["fund_name"] or "").strip() == name_norm]
        if not same_name:
            return None, f"库内无同名本体「{name_norm}」，不自动归组"

        if not company_norm:
            return None, (f"库内有同名本体 {len(same_name)} 个，但本次接入"
                          "公司信息缺失，按规则不自动归组，需人工核验")

        matched = [r for r in same_name
                   if (r["fund_company"] or "").strip() == company_norm]
        if matched:
            return int(matched[0]["fund_id"]), (
                f"基础名「{name_norm}」+ 公司「{company_norm}」完全一致 → "
                f"归入 fund_id={int(matched[0]['fund_id'])}")

        missing = [r for r in same_name if not (r["fund_company"] or "").strip()]
        if missing:
            return None, ("库内有同名本体但库内公司信息缺失"
                          f"（fund_id={int(missing[0]['fund_id'])}），"
                          "按规则不自动归组，需人工核验")

        return None, (f"同名本体 {len(same_name)} 个，但基金公司不一致"
                      f"（本次「{company_norm}」），绝不自动归组")

    def _existing_fund(self, code: str) -> dict | None:
        with get_connection(self.db_path) as conn:
            r = conn.execute(
                """SELECT m.fund_id, m.fund_name, m.fund_full_name,
                          m.fund_type_l1, m.is_index_fund
                   FROM fund_share_classes s
                   JOIN fund_master m ON m.fund_id=s.fund_id
                   WHERE s.share_class_code=?""", (code,)).fetchone()
            if r is None:
                return None
            fund_id = int(r["fund_id"])
            shares = conn.execute(
                """SELECT share_class_id, share_class_code
                   FROM fund_share_classes WHERE fund_id=?
                   ORDER BY share_class_code""", (fund_id,)).fetchall()
        cls = classify_fund({"fund_name": r["fund_name"],
                             "fund_full_name": r["fund_full_name"],
                             "fund_type_l1": r["fund_type_l1"],
                             "is_index_fund": r["is_index_fund"]})
        return {
            "fund_id": fund_id,
            "share_ids": [int(x["share_class_id"]) for x in shares],
            "share_codes": [x["share_class_code"] for x in shares],
            "product_class": cls["product_class"],
        }


# ---------------------------------------------------------------- 批量
def ingest_many(codes: list[str], db_path: Path | None = None, *,
                ingestor: UserFundIngestor | None = None) -> dict:
    """批量接入：单只失败不影响其他。"""
    ing = ingestor or UserFundIngestor(db_path)
    before = db_fingerprint(db_path)
    results = []
    seen = set()
    for c in codes:
        if c in seen:
            results.append({"code": c, "status": "duplicate_skipped",
                            "reason": "同批次重复代码，已跳过"})
            continue
        seen.add(c)
        try:
            results.append(ing.ingest_one(c).as_dict())
        except Exception as exc:
            results.append({"code": c, "status": ST_FAILED,
                            "reason": f"{type(exc).__name__}: {exc}"})
    after = db_fingerprint(db_path)
    summary = {}
    for r in results:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    return {
        "phase": "3B-5.3",
        "requested": codes,
        "result_count": len(results),
        "status_summary": summary,
        "fingerprint_before": before,
        "fingerprint_after": after,
        "results": results,
        "gate": gate(),
    }


def gate() -> dict:
    return {
        "ready_for_research_analysis": True,
        "ready_for_backtest": False,
        "ready_for_formal_ranking": False,
        "reason": "受控数据接入可用；正式回测与真实排名仍不具备条件",
    }
