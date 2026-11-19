"""第一批真实数据导入：基金本体/份额、净值、分红、状态、经理、规模。

数据源只用 3B-3 已审计通过的 AKShare 接口：
- ak.fund_name_em                         全量代码表
- ak.fund_individual_basic_info_xq        基本信息
- ak.fund_open_fund_info_em               净值 / 分红 / 拆分
- ak.fund_money_fund_info_em              货币基金收益
- ak.fund_purchase_em                     申购赎回状态（当日快照）

严格不做的事：
- 不填行业平均费率（费率保持 NULL）；
- 不用当前日期伪造经理任职起点；
- 不推测清盘日期；
- 不把天天基金申购状态当成支付宝可购买状态（alipay_purchasable 恒 unknown）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.fund.models import (
    AumRecord, DataQualityRecord, DividendRecord, FundMasterRecord,
    FundShareClassRecord, LifecycleEventRecord, ManagerRecord, NavRecord,
    SubscriptionStatusRecord,
)
from app.fund.normalize import (
    base_fund_name, detect_share_class_type, is_money_fund,
    parse_cash_per_share, to_float, to_iso_date,
)
from app.fund.repo_base import now_iso
from app.fund.repo_nav import NavRepository
from app.fund.repo_quality import QualityRepository
from app.fund.repo_status import StatusRepository
from app.fund.repository import FundRepository

SOURCE_NAME_EM = "akshare.fund_name_em"
SOURCE_BASIC_XQ = "akshare.fund_individual_basic_info_xq"
SOURCE_NAV = "akshare.fund_open_fund_info_em"
SOURCE_MONEY = "akshare.fund_money_fund_info_em"
SOURCE_PURCHASE = "akshare.fund_purchase_em"


def _pause(sec: float = 0.25) -> None:
    time.sleep(sec)


@dataclass
class IngestStats:
    master_inserted: int = 0
    master_updated: int = 0
    share_inserted: int = 0
    share_updated: int = 0
    nav_written: int = 0
    money_written: int = 0
    dividend_written: int = 0
    status_written: int = 0
    manager_written: int = 0
    aum_written: int = 0
    lifecycle_written: int = 0
    quality_written: int = 0
    skipped: int = 0
    errors: list = field(default_factory=list)

    def as_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "errors"}
        d["error_count"] = len(self.errors)
        d["errors"] = self.errors[:20]
        return d


class FundIngestor:
    """把 AKShare 数据写进场外基金表。所有外部调用可注入，便于 Mock 测试。"""

    def __init__(self, db_path: Path | None = None, *,
                 fetch_name_table: Callable | None = None,
                 fetch_basic: Callable | None = None,
                 fetch_nav: Callable | None = None,
                 fetch_money: Callable | None = None,
                 fetch_fund_dividends: Callable | None = None,
                 fetch_purchase: Callable | None = None) -> None:
        self.db_path = db_path
        self.funds = FundRepository(db_path)
        self.nav = NavRepository(db_path)
        self.status = StatusRepository(db_path)
        self.quality = QualityRepository(db_path)
        self._fetch_name_table = fetch_name_table or _default_name_table
        self._fetch_basic = fetch_basic or _default_basic
        self._fetch_nav = fetch_nav or _default_nav
        self._fetch_money = fetch_money or _default_money
        self._fetch_div = fetch_fund_dividends or _default_dividends
        self._fetch_purchase = fetch_purchase or _default_purchase

    # ------------------------------------------------------------ 基金本体
    def ingest_master_and_share(self, *, name_row: dict,
                                basic: dict | None = None,
                                stats: IngestStats | None = None) -> tuple[int, int]:
        """写入一只基金的 master + share_class，返回 (fund_id, share_class_id)。"""
        stats = stats or IngestStats()
        ts = now_iso()
        code = str(name_row["fund_code"])
        name = str(name_row["fund_name"])
        fund_type = name_row.get("fund_type")

        # 本体归属：优先用名称去后缀；无法可靠归属时标记 needs_review。
        base = base_fund_name(name)
        needs_review = 0 if base else 1

        basic = basic or {}
        master = FundMasterRecord(
            fund_code_primary=code,
            fund_name=base or name,
            source=SOURCE_NAME_EM if not basic else SOURCE_BASIC_XQ,
            ingested_at=ts,
            fund_full_name=basic.get("full_name"),
            fund_company=basic.get("company"),
            custodian=basic.get("custodian"),
            fund_type_l1=fund_type,
            fund_type_l2=basic.get("fund_type"),
            invest_scope=basic.get("invest_scope"),
            benchmark=basic.get("benchmark"),
            # 成立日期未知就留 NULL，不填今天
            established_date=to_iso_date(basic.get("established")),
            terminated_date=None,
            lifecycle_status="unknown",
            is_index_fund=1 if fund_type and "指数" in str(fund_type) else None,
            tracking_index=None,
            needs_review=needs_review,
            source_updated_at=ts,
        )
        fund_id = self.funds.upsert_master(master)

        share = FundShareClassRecord(
            share_class_code=code,
            share_class_name=name,
            source=SOURCE_NAME_EM,
            ingested_at=ts,
            share_class_type=detect_share_class_type(name),
            is_primary=1,
            source_updated_at=ts,
        )
        sc_id = self.funds.upsert_share_class(fund_id, share)

        # 成立日若有值，写一条 established 事件（不伪造，只记录已知事实）
        if master.established_date:
            self.funds.add_lifecycle_event(fund_id, LifecycleEventRecord(
                event_type="established",
                source=master.source,
                ingested_at=ts,
                event_date=master.established_date,
                detail="成立日期来自基本信息接口",
                evidence_level="third_party",
            ))
            stats.lifecycle_written += 1

        stats.master_inserted += 1
        stats.share_inserted += 1
        return fund_id, sc_id

    # ------------------------------------------------------------ 批量归属
    def ingest_fund_group(self, members: list[dict], *,
                          basics: dict | None = None,
                          stats: IngestStats | None = None) -> dict:
        """把同一基金本体的多个份额代码写成 1 个 master + N 个 share_class。

        members: [{"fund_code","fund_name","fund_type"}, ...]（同一本体）
        归属依据只是「去掉份额后缀后的名称一致」——这是**弱依据**，
        因此：
          - 组内成员数 > 1 且基础名一致 → 归为同一本体；
          - 基础名为空或组内基础名不一致 → 每个成员各成一个本体并标 needs_review=1，
            不强行合并。
        主代码优先取 A 类（或后缀最小者），其余作为附属份额。
        """
        stats = stats or IngestStats()
        basics = basics or {}
        ts = now_iso()

        if not members:
            return {"fund_id": None, "share_ids": {}, "merged": False}

        bases = [base_fund_name(m["fund_name"]) or "" for m in members]
        uniq_bases = {b for b in bases if b}
        can_merge = bool(len(members) > 1 and len(uniq_bases) == 1)

        if not can_merge:
            # 单成员 = 天然独立本体；多成员但基础名不一致 = 无法可靠归属，
            # 各自独立成体并标 needs_review，绝不强行合并。
            out = {"fund_id": None, "share_ids": {}, "merged": False,
                   "needs_review": len(members) > 1}
            last_fid = None
            for m in members:
                fid, sid = self.ingest_master_and_share(
                    name_row=m, basic=basics.get(m["fund_code"]), stats=stats)
                out["share_ids"][m["fund_code"]] = sid
                last_fid = fid
            out["fund_id"] = last_fid
            return out

        base = next(iter(uniq_bases))
        # 主成员：A 类优先，其次代码最小
        def _rank(m):
            t = detect_share_class_type(m["fund_name"])
            return (0 if t == "A" else 1 if t == "plain" else 2, m["fund_code"])
        ordered = sorted(members, key=_rank)
        primary = ordered[0]

        basic = basics.get(primary["fund_code"]) or {}
        fund_type = primary.get("fund_type")
        master = FundMasterRecord(
            fund_code_primary=primary["fund_code"],
            fund_name=base,
            source=SOURCE_BASIC_XQ if basic else SOURCE_NAME_EM,
            ingested_at=ts,
            fund_full_name=basic.get("full_name"),
            fund_company=basic.get("company"),
            custodian=basic.get("custodian"),
            fund_type_l1=fund_type,
            fund_type_l2=basic.get("type"),
            invest_scope=basic.get("invest_scope"),
            benchmark=basic.get("benchmark"),
            established_date=to_iso_date(basic.get("established")),
            terminated_date=None,
            lifecycle_status="unknown",
            is_index_fund=1 if fund_type and "指数" in str(fund_type) else None,
            tracking_index=None,
            needs_review=0,
            source_updated_at=ts,
        )
        fund_id = self.funds.upsert_master(master)
        stats.master_inserted += 1

        if master.established_date:
            self.funds.add_lifecycle_event(fund_id, LifecycleEventRecord(
                event_type="established", source=master.source, ingested_at=ts,
                event_date=master.established_date,
                detail="成立日期来自基本信息接口", evidence_level="third_party"))
            stats.lifecycle_written += 1

        share_ids = {}
        for i, m in enumerate(ordered):
            sid = self.funds.upsert_share_class(fund_id, FundShareClassRecord(
                share_class_code=m["fund_code"],
                share_class_name=m["fund_name"],
                source=SOURCE_NAME_EM,
                ingested_at=ts,
                share_class_type=detect_share_class_type(m["fund_name"]),
                is_primary=1 if i == 0 else 0,
                source_updated_at=ts,
            ))
            share_ids[m["fund_code"]] = sid
            stats.share_inserted += 1

        return {"fund_id": fund_id, "share_ids": share_ids, "merged": True,
                "needs_review": False, "base_name": base,
                "primary_code": primary["fund_code"]}

    # ------------------------------------------------------------ 净值
    def ingest_nav(self, code: str, sc_id: int, *,
                   is_money: bool, stats: IngestStats | None = None) -> dict:
        """导入单只基金的净值。货币基金走独立分支，不伪装成单位净值。"""
        stats = stats or IngestStats()
        ts = now_iso()

        if is_money:
            rows = self._fetch_money(code) or []
            recs = []
            for r in rows:
                per10k = to_float(r.get("per_10k_yield"))
                if per10k is None:
                    continue
                recs.append(NavRecord(
                    nav_date=to_iso_date(r.get("nav_date")) or "",
                    nav_kind="money_yield",
                    per_10k_yield=per10k,
                    seven_day_annual=to_float(r.get("seven_day_annual")),
                    source=SOURCE_MONEY,
                    ingested_at=ts,
                ))
            recs = [x for x in recs if x.nav_date]
            res = self.nav.upsert_nav_batch(sc_id, recs)
            stats.money_written += res["inserted"] + res["updated"]
            return {"kind": "money_yield", **res, "rows": len(recs)}

        unit_rows = self._fetch_nav(code, "unit") or []
        acc_rows = self._fetch_nav(code, "acc") or []

        unit_map = {}
        for r in unit_rows:
            d = to_iso_date(r.get("nav_date"))
            v = to_float(r.get("unit_nav"))
            if d and v is not None:
                unit_map[d] = v
        acc_map = {}
        for r in acc_rows:
            d = to_iso_date(r.get("nav_date"))
            v = to_float(r.get("acc_nav"))
            if d and v is not None:
                acc_map[d] = v

        # 两个接口日期不一致：不丢弃，取并集并把缺口记进数据质量表
        all_dates = sorted(set(unit_map) | set(acc_map))
        recs = []
        unit_only, acc_only = [], []
        for d in all_dates:
            u = unit_map.get(d)
            a = acc_map.get(d)
            if u is not None and a is None:
                unit_only.append(d)
            elif u is None and a is not None:
                acc_only.append(d)
            # unit_nav 必须非空才写入净净值行（DDL 约束）
            if u is None:
                continue
            recs.append(NavRecord(
                nav_date=d, nav_kind="net_value",
                unit_nav=u, acc_nav=a,
                source=SOURCE_NAV, ingested_at=ts,
            ))

        res = self.nav.upsert_nav_batch(sc_id, recs)
        stats.nav_written += res["inserted"] + res["updated"]

        # 留痕：日期不匹配
        if unit_only or acc_only:
            detail = (f"单位净值独有 {len(unit_only)} 日，累计净值独有 {len(acc_only)} 日；"
                      f"示例 单位独有={unit_only[:3]} 累计独有={acc_only[:3]}")
            cur = self.quality.record(DataQualityRecord(
                table_name="fund_nav_daily",
                record_key=f"{code}:date_mismatch",
                check_name="unit_acc_date_mismatch",
                status="mismatch",
                detail=detail,
                severity="warning",
                checked_at=ts,
            ))
            stats.quality_written += 1

        return {"kind": "net_value", **res,
                "rows": len(recs),
                "unit_only_dates": len(unit_only),
                "acc_only_dates": len(acc_only)}

    # ------------------------------------------------------------ 分红
    def ingest_dividends(self, code: str, sc_id: int, *,
                         stats: IngestStats | None = None) -> dict:
        stats = stats or IngestStats()
        ts = now_iso()
        rows = self._fetch_div(code) or []
        recs = []
        for r in rows:
            ex = to_iso_date(r.get("ex_date"))
            raw = r.get("per_10_raw")
            cash = parse_cash_per_share(raw)
            if not ex or cash is None:
                continue
            recs.append(DividendRecord(
                ex_date=ex,
                cash_per_share=cash,
                per_10_raw=str(raw),
                record_date=to_iso_date(r.get("record_date")),
                pay_date=to_iso_date(r.get("pay_date")),
                source=SOURCE_NAV,
                ingested_at=ts,
            ))
        res = self.nav.upsert_dividend_batch(sc_id, recs)
        stats.dividend_written += res["inserted"] + res["updated"]

        # 归一化结果与原始值一起留痕，便于日后核对是否算错
        if recs:
            self.quality.record(DataQualityRecord(
                table_name="fund_dividends",
                record_key=f"{code}:normalized",
                check_name="cash_per_share_normalized",
                status="ok",
                detail=f"{len(recs)} 条分红已按「每10份/10」归一化，原始文本已保留",
                severity="info",
                checked_at=ts,
            ))
            stats.quality_written += 1
        return res

    # ------------------------------------------------------------ 状态
    def ingest_status(self, code: str, sc_id: int, *, purchase_row: dict | None,
                      stats: IngestStats | None = None) -> dict:
        """保存当日申购赎回状态快照。

        alipay_purchasable 恒为 unknown —— 天天基金状态不能冒充支付宝状态。
        """
        stats = stats or IngestStats()
        if not purchase_row:
            return {"written": 0}
        ts = now_iso()
        as_of = to_iso_date(purchase_row.get("as_of")) or ts[:10]
        self.status.save_subscription_status(sc_id, SubscriptionStatusRecord(
            as_of_date=as_of,
            source=SOURCE_PURCHASE,
            ingested_at=ts,
            purchase_status=purchase_row.get("purchase_status"),
            redeem_status=purchase_row.get("redeem_status"),
            daily_limit=to_float(purchase_row.get("daily_limit")),
            min_purchase=to_float(purchase_row.get("min_purchase")),
            next_open_date=to_iso_date(purchase_row.get("next_open_date")),
            alipay_purchasable="unknown",
        ))
        stats.status_written += 1

        # 费率未知：明确记录，绝不填行业平均
        self.quality.record(DataQualityRecord(
            table_name="fund_fee_rules",
            record_key=f"{code}:redemption_fee",
            check_name="redemption_fee_missing",
            status="missing",
            detail="当前数据源无赎回费阶梯字段，按规定保持 NULL，未填行业平均值",
            severity="warning",
            checked_at=ts,
        ))
        stats.quality_written += 1
        return {"written": 1}

    # ------------------------------------------------------------ 经理/规模
    def ingest_manager(self, code: str, fund_id: int, *, managers: list[dict] | None,
                       stats: IngestStats | None = None) -> int:
        stats = stats or IngestStats()
        ts = now_iso()
        n = 0
        for m in (managers or []):
            name = (m.get("manager_name") or "").strip()
            if not name:
                continue
            self.funds.add_manager(fund_id, ManagerRecord(
                manager_name=name,
                source=SOURCE_BASIC_XQ,
                ingested_at=ts,
                company=m.get("company"),
                # 起止日期未知一律 NULL，不用今天伪造
                start_date=to_iso_date(m.get("start_date")),
                end_date=to_iso_date(m.get("end_date")),
            ))
            n += 1
        stats.manager_written += n
        if n:
            self.quality.record(DataQualityRecord(
                table_name="fund_manager_history",
                record_key=f"{code}:tenure",
                check_name="manager_tenure_unknown",
                status="missing",
                detail="接口只给现任经理，任职起止日期无数据源，按 NULL 保存",
                severity="info",
                checked_at=ts,
            ))
            stats.quality_written += 1
        return n

    def ingest_aum(self, code: str, fund_id: int, *, aum_total: float | None,
                   report_date: str | None, stats: IngestStats | None = None) -> int:
        stats = stats or IngestStats()
        if aum_total is None:
            return 0
        ts = now_iso()
        self.funds.add_aum(
            AumRecord(report_date=report_date or ts[:10], source=SOURCE_BASIC_XQ,
                      ingested_at=ts, aum_total=aum_total, aum_unit="CNY"),
            fund_id=fund_id)
        stats.aum_written += 1
        return 1


# ---------------------------------------------------------------- 默认抓取器
def _default_name_table():
    import akshare as ak
    df = ak.fund_name_em()
    return [{"fund_code": str(r["基金代码"]), "fund_name": str(r["基金简称"]),
             "fund_type": str(r["基金类型"])} for _, r in df.iterrows()]


def _default_basic(code: str) -> dict:
    import akshare as ak
    df = ak.fund_individual_basic_info_xq(symbol=code)
    kv = {str(r["item"]): str(r["value"]) for _, r in df.iterrows()}
    return {
        "name": kv.get("基金名称"),
        "full_name": kv.get("基金全称"),
        "established": kv.get("成立时间"),
        "scale": kv.get("最新规模"),
        "company": kv.get("基金公司"),
        "manager": kv.get("基金经理"),
        "type": kv.get("基金类型"),
        "benchmark": kv.get("业绩比较基准"),
        "custodian": kv.get("托管银行"),
        "invest_scope": kv.get("投资目标"),
    }


def _default_nav(code: str, kind: str) -> list[dict]:
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


def _default_money(code: str) -> list[dict]:
    import akshare as ak
    df = ak.fund_money_fund_info_em(symbol=code)
    return [{"nav_date": r["净值日期"],
             "per_10k_yield": r["每万份收益"],
             "seven_day_annual": r["7日年化收益率"]}
            for _, r in df.iterrows()]


def _default_dividends(code: str) -> list[dict]:
    import akshare as ak
    df = ak.fund_open_fund_info_em(symbol=code, indicator="分红送配详情")
    return [{"record_date": r.get("权益登记日"), "ex_date": r.get("除息日"),
             "pay_date": r.get("分红发放日"), "per_10_raw": r.get("每10份分红")}
            for _, r in df.iterrows()]


def _default_purchase():
    import akshare as ak
    df = ak.fund_purchase_em()
    return {str(r["基金代码"]): {
        "purchase_status": r.get("申购状态"),
        "redeem_status": r.get("赎回状态"),
        "min_purchase": r.get("购买起点"),
        "daily_limit": r.get("日累计限定金额"),
        "next_open_date": r.get("下一开放日"),
    } for _, r in df.iterrows()}
