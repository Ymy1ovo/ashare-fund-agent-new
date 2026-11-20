"""阶段3B-4.2 关键历史数据正式入库：清盘事件 + 费率阶梯。

数据来源（只读，不重新采集）：
- 生命周期事件：reports/phase3B4_1_1_types_evidence_calibration.json（权威）
- 费率阶梯：reports/phase3B4_1_1_historical_roster_fee_audit.json 的 fee_audit

严格边界：
- 只入 41 个场外结构本体，2 只场内 ETF（511000 / 511050）排除；
- 证据等级如实保存（清盘 B、费率 C），不虚标；
- 原始费率与平台优惠费率分列，平台名固定 eastmoney；
- 历史生效时间无证据时 NULL，不拿抓取日期冒充；
- 缺失费率为 NULL，不用 0 代替；`---` 不当 0；
- alipay_purchasable 保持 unknown，不由结构推断。

幂等键：
- 生命周期：event_fingerprint = f"life:{announcement_id}:{fund_code_primary}"
- 费率：唯一索引 uq_fund_fee_natural（share_class_id, fee_type, tier_order,
  COALESCE(effective_from,'__na__')）
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from app.fund.migration_3b4_2 import ensure_3b4_2_schema
from app.fund.repo_base import get_conn, now_iso

ROOT = Path(__file__).resolve().parents[2]
CALIBRATION_JSON = ROOT / "reports" / "phase3B4_1_1_types_evidence_calibration.json"
ROSTER_JSON = ROOT / "reports" / "phase3B4_1_1_historical_roster_fee_audit.json"

# 场内 ETF：不得入场外研究样本
ONSHORE_ETF_CODES = ("511000", "511050")

# 场外结构范围
OFFMARKET_STRUCTURES = ("ordinary_open_ended", "etf_linked", "lof")

LIFECYCLE_SOURCE = "dfcfw.announcement.calibrated"
FEE_SOURCE = "fundf10.eastmoney.com"
FEE_PLATFORM = "eastmoney"

# 每条清盘记录必须写进 detail 的来源声明
DISCLAIMER = ("来源为东方财富转载，未经基金管理人官网或交易所官网逐条回源验证，"
              "证据等级B。")


@dataclass
class IngestStat:
    planned: int = 0
    inserted: int = 0
    skipped_existing: int = 0
    excluded: int = 0
    failed: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "planned": self.planned,
            "inserted": self.inserted,
            "skipped_existing": self.skipped_existing,
            "excluded": self.excluded,
            "failed": self.failed,
            "by_type": dict(self.by_type),
            "notes": list(self.notes),
            "conflicts": list(self.conflicts),
        }


# ---------------------------------------------------------------- 读数据源
def load_calibration(path: Path = CALIBRATION_JSON) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_fee_audit(path: Path = ROSTER_JSON) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))["fee_audit"]


def select_offmarket_events(calibration: dict) -> tuple[list[dict], list[dict]]:
    """拆成 (场外结构事件, 被排除的场内 ETF)。"""
    off, excluded = [], []
    for rec in calibration["calibration"]:
        structure = rec.get("product_structure")
        codes = rec.get("codes_in_event") or []
        if structure in OFFMARKET_STRUCTURES and not (
                set(codes) & set(ONSHORE_ETF_CODES)):
            off.append(rec)
        else:
            excluded.append(rec)
    return off, excluded


# ---------------------------------------------------------------- 生命周期
def lifecycle_fingerprint(announcement_id: str, fund_code: str) -> str:
    return f"life:{announcement_id}:{fund_code}"


def _pick_primary_code(codes: list[str]) -> str:
    """多份额代码里挑主代码。

    规则：优先 6 位纯数字且不以 9 开头；否则取排序后第一个。
    绝不把多个份额代码写成多个基金本体。
    """
    if not codes:
        return ""
    cand = sorted(c for c in codes if c.isdigit() and len(c) == 6)
    return cand[0] if cand else sorted(codes)[0]


def _ensure_master(conn, code: str, name: str, structure: str,
                   company: str | None, now: str) -> int:
    """按主代码幂等取/建基金本体，返回 fund_id。

    清盘基金本体：lifecycle_status='terminated'（终止已发生，有公告依据）。
    只补最小字段，不伪造成立日期与清盘日期。
    """
    row = conn.execute(
        "SELECT fund_id FROM fund_master WHERE fund_code_primary=?", (code,)).fetchone()
    if row:
        return int(row["fund_id"])
    cur = conn.execute(
        """INSERT INTO fund_master
           (fund_code_primary, fund_name, fund_full_name, fund_company,
            lifecycle_status, needs_review, source, ingested_at, data_version)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (code, name, name, company, "terminated",
         1,                       # 类型兜底未细分股/债 → 待人工复核
         LIFECYCLE_SOURCE, now, "fund-v1"))
    fid = int(cur.lastrowid)
    # 主代码 → is_primary=1（每个本体恰好一个）
    conn.execute(
        """INSERT OR IGNORE INTO fund_share_classes
           (fund_id, share_class_code, share_class_name, share_class_type,
            is_primary, source, ingested_at)
           VALUES (?,?,?,?,?,?,?)""",
        (fid, code, name, "plain", 1, LIFECYCLE_SOURCE, now))
    return fid


class ShareOwnershipError(RuntimeError):
    """份额代码已被其他基金本体占用。

    绝不静默重新关联，也不直接覆盖——抛错交上层记录冲突。
    """

    def __init__(self, code: str, expected_fund_id: int, actual_fund_id: int) -> None:
        self.code = code
        self.expected_fund_id = expected_fund_id
        self.actual_fund_id = actual_fund_id
        super().__init__(
            f"份额代码 {code} 已属于 fund_id={actual_fund_id}，"
            f"与传入的 fund_id={expected_fund_id} 不一致")


def _ensure_share(conn, fund_id: int, code: str, name: str, now: str,
                  *, is_primary: int = 0) -> int:
    """幂等登记非主份额。

    - 已存在且 fund_id 一致：直接返回，不改归属；
    - 已存在但 fund_id 不一致：抛 ShareOwnershipError，不静默重连；
    - 不存在：以 is_primary=0 新建（主份额只由 _ensure_master 创建）。
    """
    row = conn.execute(
        "SELECT share_class_id, fund_id FROM fund_share_classes "
        "WHERE share_class_code=?", (code,)).fetchone()
    if row:
        if int(row["fund_id"]) != int(fund_id):
            raise ShareOwnershipError(code, fund_id, int(row["fund_id"]))
        return int(row["share_class_id"])
    cur = conn.execute(
        """INSERT INTO fund_share_classes
           (fund_id, share_class_code, share_class_name, share_class_type,
            is_primary, source, ingested_at)
           VALUES (?,?,?,?,?,?,?)""",
        (fund_id, code, name, "plain", is_primary, LIFECYCLE_SOURCE, now))
    return int(cur.lastrowid)


def _guess_company(rec: dict) -> str | None:
    """从公告标题抽基金管理人。抽不到返回 None，不猜。"""
    title = rec.get("announcement_title") or ""
    import re
    m = re.search(r"^([\u4e00-\u9fa5]{2,20}基金(?:管理)?(?:有限公司|股份有限公司))", title)
    if m:
        return m.group(1)
    m = re.search(r"^([\u4e00-\u9fa5]{2,12})(?:基金管理)", title)
    if m:
        return m.group(1) + "基金管理有限公司"
    return None


def ingest_lifecycle(db_path: Path | None = None,
                     calibration: dict | None = None) -> dict:
    """把 41 个场外结构清盘事件写入 fund_lifecycle_events。"""
    calibration = calibration if calibration is not None else load_calibration()
    off, excluded = select_offmarket_events(calibration)
    stat = IngestStat(planned=len(off), excluded=len(excluded))
    now = now_iso()
    ensure_3b4_2_schema(db_path)

    excluded_detail = []
    for rec in excluded:
        excluded_detail.append({
            "codes": rec.get("codes_in_event"),
            "name": rec.get("fund_entity"),
            "structure": rec.get("product_structure"),
            "reason": "场内 ETF，不属于场外研究样本",
        })

    with get_conn(db_path) as conn:
        for rec in off:
            codes = list(rec.get("codes_in_event") or [])
            primary = _pick_primary_code(codes)
            ann_id = rec.get("announcement_id") or ""
            fp = lifecycle_fingerprint(ann_id, primary)

            exists = conn.execute(
                "SELECT event_id FROM fund_lifecycle_events WHERE event_fingerprint=?",
                (fp,)).fetchone()
            if exists:
                stat.skipped_existing += 1
                continue

            try:
                company = _guess_company(rec)
                fid = _ensure_master(conn, primary, rec["fund_entity"],
                                     rec.get("product_structure") or "unknown",
                                     company, now)
                # 其余份额代码也登记为份额，但不新建本体
                for other in codes:
                    if other != primary:
                        # 非主份额：is_primary=0
                        _ensure_share(conn, fid, other, rec["fund_entity"], now,
                                      is_primary=0)

                detail = json.dumps({
                    "fund_entity": rec.get("fund_entity"),
                    "fund_entity_old": rec.get("fund_entity_old"),
                    "product_structure": rec.get("product_structure"),
                    "investment_type": rec.get("investment_type"),
                    "name_source": rec.get("name_source"),
                    "evidence_reason": rec.get("evidence_reason"),
                    "alipay_purchasable": rec.get("alipay_purchasable", "unknown"),
                    "alipay_evidence": rec.get("alipay_evidence", "not_obtainable"),
                    "announcement_title": rec.get("announcement_title"),
                    "doc_format": rec.get("doc_format"),
                    "disclaimer": DISCLAIMER,
                }, ensure_ascii=False)

                conn.execute(
                    """INSERT INTO fund_lifecycle_events
                       (fund_id, event_type, event_date, announcement_date,
                        announcement_url, detail, successor_fund_id,
                        evidence_level, source, ingested_at,
                        announcement_id, product_structure, fund_codes,
                        event_fingerprint, fetched_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (fid, "terminated",
                     rec.get("event_date"),          # 无证据则 NULL，不猜
                     rec.get("announcement_date"),
                     rec.get("announcement_url"),
                     detail, None,
                     "B",                            # 本轮校准等级
                     LIFECYCLE_SOURCE, now,
                     ann_id,
                     rec.get("product_structure"),
                     ",".join(codes),
                     fp,
                     now))
                stat.inserted += 1
                et = rec.get("product_structure") or "unknown"
                stat.by_type[et] = stat.by_type.get(et, 0) + 1
            except ShareOwnershipError as exc:
                stat.failed += 1
                stat.conflicts.append({
                    "code": exc.code,
                    "expected_fund_id": exc.expected_fund_id,
                    "actual_fund_id": exc.actual_fund_id,
                })
                stat.notes.append(f"{primary} 冲突: {exc}")
            except Exception as exc:  # noqa: BLE001
                stat.failed += 1
                stat.notes.append(f"{primary} 失败: {type(exc).__name__}: {exc}")

    return {"stat": stat.as_dict(), "excluded": excluded_detail}


# ---------------------------------------------------------------- 费率
def _fee_rows_for_sample(sample: dict) -> list[dict]:
    """把一只基金的费率审计结果摊平成待入库行。"""
    code = sample["code"]
    rows: list[dict] = []

    # 年化费率：管理/托管/销售服务
    annual = sample.get("annual_fees") or {}
    for ftype, key in (("management", "management_fee"),
                       ("custody", "custody_fee"),
                       ("sales_service", "sales_service_fee")):
        rate = annual.get(key)
        rows.append({
            "fee_type": ftype, "tier_order": 0,
            "lower_bound": None, "upper_bound": None,
            "lower_inclusive": None, "upper_inclusive": None,
            "lower_inferred": None,
            "holding_days_min": None, "holding_days_max": None,
            "holding_days_min_inclusive": None,
            "holding_days_max_inclusive": None,
            "holding_days_min_inferred": None,
            "rate_original": rate, "rate_platform": None,
            "platform_name": None,
            "is_annual": 1,
            "holding_days_basis": None,
            "detail": ("页面未提供该费率字段（---），保持 NULL，不当 0"
                       if rate is None else None),
        })

    # 申购阶梯（金额区间）
    for i, t in enumerate(sample.get("purchase_tiers") or []):
        rows.append({
            "fee_type": "purchase", "tier_order": i,
            "lower_bound": t.get("lower_bound"),
            "upper_bound": t.get("upper_bound"),
            "lower_inclusive": (1 if t.get("lower_inclusive") else 0)
                               if t.get("lower_inclusive") is not None else None,
            "upper_inclusive": (1 if t.get("upper_inclusive") else 0)
                               if t.get("upper_inclusive") is not None else None,
            "lower_inferred": 1 if t.get("lower_inferred") else 0,
            "holding_days_min": None, "holding_days_max": None,
            "holding_days_min_inclusive": None,
            "holding_days_max_inclusive": None,
            "holding_days_min_inferred": None,
            "rate_original": t.get("original_rate"),
            "rate_platform": t.get("platform_rate"),
            "platform_name": FEE_PLATFORM if t.get("platform_rate") is not None else None,
            "is_annual": 0,
            "holding_days_basis": None,
            "detail": t.get("condition_text"),
        })

    # 赎回阶梯（持有天数区间）
    for i, t in enumerate(sample.get("redeem_tiers") or []):
        rows.append({
            "fee_type": "redemption", "tier_order": i,
            "lower_bound": None, "upper_bound": None,
            "lower_inclusive": None, "upper_inclusive": None,
            "lower_inferred": None,
            "holding_days_min": t.get("holding_days_min"),
            "holding_days_max": t.get("holding_days_max"),
            "holding_days_min_inclusive": (1 if t.get("min_inclusive") else 0)
                                           if t.get("min_inclusive") is not None else None,
            "holding_days_max_inclusive": (1 if t.get("max_inclusive") else 0)
                                           if t.get("max_inclusive") is not None else None,
            "holding_days_min_inferred": 1 if t.get("min_inferred") else 0,
            "rate_original": t.get("rate"),
            "rate_platform": None,
            "platform_name": None,
            "is_annual": 0,
            # 自然日 / 交易日：原始合同未明确，保持 NULL 不猜
            "holding_days_basis": None,
            "detail": t.get("condition_text"),
        })
    return rows


def ingest_fees(db_path: Path | None = None,
                fee_audit: dict | None = None) -> dict:
    """把 12 只基金费率阶梯写入 fund_fee_rules。"""
    fee_audit = fee_audit if fee_audit is not None else load_fee_audit()
    samples = fee_audit.get("samples") or []
    stat = IngestStat()
    now = now_iso()
    fetched_at = _calibration_fetched_at()
    ensure_3b4_2_schema(db_path)

    planned = 0
    with get_conn(db_path) as conn:
        for sample in samples:
            code = sample["code"]
            row = conn.execute(
                "SELECT share_class_id FROM fund_share_classes WHERE share_class_code=?",
                (code,)).fetchone()
            if row is None:
                stat.failed += 1
                stat.notes.append(f"{code} 无对应份额，跳过（不新建份额）")
                continue
            sc_id = int(row["share_class_id"])
            rows = _fee_rows_for_sample(sample)
            url = _fee_source_url(code)
            for r in rows:
                r["_source_url"] = url
            planned += len(rows)
            for r in rows:
                exists = conn.execute(
                    """SELECT fee_rule_id FROM fund_fee_rules
                       WHERE share_class_id=? AND fee_type=? AND tier_order=?
                         AND COALESCE(effective_from,'__na__')='__na__'""",
                    (sc_id, r["fee_type"], r["tier_order"])).fetchone()
                if exists:
                    stat.skipped_existing += 1
                    continue
                try:
                    conn.execute(
                        """INSERT INTO fund_fee_rules
                           (share_class_id, fee_type, tier_order,
                            lower_bound, upper_bound, rate,
                            holding_days_min, holding_days_max,
                            effective_from, effective_to,
                            source, evidence_level, ingested_at,
                            lower_inclusive, upper_inclusive, lower_inferred,
                            holding_days_min_inclusive, holding_days_max_inclusive,
                            holding_days_min_inferred,
                            rate_original, rate_platform, platform_name,
                            is_annual, holding_days_basis,
                            source_name, source_url, fetched_at, detail)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (sc_id, r["fee_type"], r["tier_order"],
                         r["lower_bound"], r["upper_bound"],
                         r["rate_original"],       # 兼容旧列：用原始费率
                         r["holding_days_min"], r["holding_days_max"],
                         None, None,               # effective_from/to：无证据保持 NULL
                         FEE_SOURCE, "C", now,
                         r["lower_inclusive"], r["upper_inclusive"], r["lower_inferred"],
                         r["holding_days_min_inclusive"],
                         r["holding_days_max_inclusive"],
                         r["holding_days_min_inferred"],
                         r["rate_original"], r["rate_platform"], r["platform_name"],
                         r["is_annual"], r["holding_days_basis"],
                         "天天基金F10费率页", r["_source_url"], fetched_at,
                         r["detail"]))
                    stat.inserted += 1
                    ft = r["fee_type"]
                    stat.by_type[ft] = stat.by_type.get(ft, 0) + 1
                except Exception as exc:  # noqa: BLE001
                    stat.failed += 1
                    stat.notes.append(
                        f"{code}/{r['fee_type']}/{r['tier_order']} 失败: "
                        f"{type(exc).__name__}: {exc}")
    stat.planned = planned
    return {"stat": stat.as_dict()}


def _calibration_fetched_at() -> str | None:
    """抓取日期来自 3B-4.1 的 JSON，不重新采集。"""
    try:
        data = json.loads(ROSTER_JSON.read_text(encoding="utf-8"))
        return data.get("generated_at")
    except Exception:  # noqa: BLE001
        return None


def _fee_source_url(code: str) -> str:
    return f"http://fundf10.eastmoney.com/jjfl_{code}.html"


def run_all(db_path: Path | None = None) -> dict:
    """完整导入：迁移 → 生命周期 → 费率。"""
    migration = ensure_3b4_2_schema(db_path)
    life = ingest_lifecycle(db_path)
    fees = ingest_fees(db_path)
    return {"migration_added": migration, "lifecycle": life, "fees": fees}
