"""研究数据读取与质量审计层（只读）。

原则：
- 只读，不写库。
- 不填补缺失值，不跨越缺口算收益。
- 不能确认就标 cannot_verify，不臆断。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from app.database.db import get_connection
from app.fund.research.classification import (
    classify_fund, index_scope, is_offmarket_pool, peer_group_key,
)

# 连续缺口阈值（自然日）：超过即标记断档，收益计算不得跨越
MAX_GAP_DAYS_FOR_RETURN = 15


@dataclass
class NavPoint:
    nav_date: str
    unit_nav: float | None
    acc_nav: float | None

    @property
    def d(self) -> date:
        return datetime.strptime(self.nav_date, "%Y-%m-%d").date()


@dataclass
class QualityReport:
    """单份额净值质量审计结果。"""
    code: str
    nav_kind: str
    rows: int = 0
    date_min: str | None = None
    date_max: str | None = None
    duplicate_dates: int = 0
    out_of_order: int = 0
    null_unit: int = 0
    null_acc: int = 0
    nonpositive_unit: int = 0
    max_gap_days: int = 0
    max_gap_at: tuple[str, str] | None = None
    gap_count_over_threshold: int = 0
    gaps: list[dict] = field(default_factory=list)
    acc_equals_unit_ratio: float | None = None
    has_dividend_effect: bool = False
    acc_usable_as_total_return: bool = False
    continuity_verification: str = "cannot_verify"
    quality_flags: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "nav_kind": self.nav_kind,
            "rows": self.rows,
            "date_min": self.date_min,
            "date_max": self.date_max,
            "duplicate_dates": self.duplicate_dates,
            "out_of_order": self.out_of_order,
            "null_unit": self.null_unit,
            "null_acc": self.null_acc,
            "nonpositive_unit": self.nonpositive_unit,
            "max_gap_days": self.max_gap_days,
            "max_gap_at": list(self.max_gap_at) if self.max_gap_at else None,
            "gap_count_over_threshold": self.gap_count_over_threshold,
            "gaps_sample": self.gaps[:5],
            "acc_equals_unit_ratio": self.acc_equals_unit_ratio,
            "has_dividend_effect": self.has_dividend_effect,
            "acc_usable_as_total_return": self.acc_usable_as_total_return,
            "continuity_verification": self.continuity_verification,
            "quality_flags": self.quality_flags,
        }


@dataclass
class NavSeries:
    code: str
    share_class_id: int
    fund_id: int
    share_class_name: str
    nav_kind: str
    points: list[NavPoint]
    quality: QualityReport

    # ---------- 查询工具 ----------
    def dates(self) -> list[date]:
        return [p.d for p in self.points]

    def value_at_or_none(self, target: date, *, field_name: str = "acc_nav",
                         tolerance_days: int = 0) -> tuple[float | None, str | None]:
        """精确（或 tolerance 内）取值。取不到返回 (None, None)，不向前后找伪装。"""
        best = None
        for p in self.points:
            delta = abs((p.d - target).days)
            if delta == 0:
                v = getattr(p, field_name)
                return (v, p.nav_date) if v is not None else (None, None)
            if tolerance_days and delta <= tolerance_days:
                if best is None or delta < best[0]:
                    v = getattr(p, field_name)
                    if v is not None:
                        best = (delta, v, p.nav_date)
        if best:
            return best[1], best[2]
        return None, None


def _to_float(v):
    return None if v is None else float(v)


def audit_nav_series(code: str, share_class_id: int, fund_id: int,
                     share_class_name: str, nav_kind: str,
                     rows: list[dict]) -> NavSeries:
    """把原始行转成 NavSeries 并做质量审计。rows 需按 nav_date 升序或乱序均可。"""
    q = QualityReport(code=code, nav_kind=nav_kind)
    q.rows = len(rows)
    if not rows:
        q.quality_flags.append("no_data")
        return NavSeries(code, share_class_id, fund_id, share_class_name,
                         nav_kind, [], q)

    dates = [r["nav_date"] for r in rows]
    # 乱序检查（原始顺序是否升序）
    q.out_of_order = sum(1 for a, b in zip(dates, dates[1:]) if a > b)

    seen: dict[str, int] = {}
    for d in dates:
        seen[d] = seen.get(d, 0) + 1
    q.duplicate_dates = sum(1 for v in seen.values() if v > 1)

    points: list[NavPoint] = []
    for r in rows:
        unit = _to_float(r["unit_nav"])
        acc = _to_float(r["acc_nav"])
        if unit is None:
            q.null_unit += 1
        if acc is None:
            q.null_acc += 1
        if unit is not None and unit <= 0:
            q.nonpositive_unit += 1
        points.append(NavPoint(nav_date=r["nav_date"], unit_nav=unit, acc_nav=acc))

    # 去重后排序（保留首条，标注 dup）
    uniq: dict[str, NavPoint] = {}
    for p in points:
        uniq.setdefault(p.nav_date, p)
    points = sorted(uniq.values(), key=lambda p: p.nav_date)

    q.date_min = points[0].nav_date
    q.date_max = points[-1].nav_date

    # 相邻缺口
    gaps = []
    for a, b in zip(points, points[1:]):
        delta = (b.d - a.d).days
        if delta > q.max_gap_days:
            q.max_gap_days = delta
            q.max_gap_at = (a.nav_date, b.nav_date)
        if delta > MAX_GAP_DAYS_FOR_RETURN:
            gaps.append({"from": a.nav_date, "to": b.nav_date, "days": delta})
    q.gaps = gaps
    q.gap_count_over_threshold = len(gaps)

    # acc 与 unit 相等比例 → 判断累计净值是否真含分红
    if points:
        same = sum(1 for p in points
                   if p.unit_nav is not None and p.acc_nav is not None
                   and abs(p.acc_nav - p.unit_nav) < 1e-9)
        q.acc_equals_unit_ratio = round(same / len(points), 4)
        q.has_dividend_effect = q.acc_equals_unit_ratio < 0.999
        # 累计净值在这批数据里确实体现了分红（非全等），可作总回报代理，
        # 但连续性仍是 cannot_verify，因此只标「代理可用」不标「已验证」。
        q.acc_usable_as_total_return = (
            q.null_acc == 0 and q.has_dividend_effect)

    if q.duplicate_dates:
        q.quality_flags.append("duplicate_dates")
    if q.out_of_order:
        q.quality_flags.append("out_of_order")
    if q.null_unit:
        q.quality_flags.append("null_unit_nav")
    if q.null_acc:
        q.quality_flags.append("null_acc_nav")
    if q.nonpositive_unit:
        q.quality_flags.append("nonpositive_unit_nav")
    if q.gap_count_over_threshold:
        q.quality_flags.append("gaps_over_threshold")

    # 连续性永远 cannot_verify（没有真实基金公布日历）
    q.continuity_verification = "cannot_verify"

    return NavSeries(code, share_class_id, fund_id, share_class_name,
                     nav_kind, points, q)


def load_nav_series(db_path: Path | None = None, *,
                    code: str | None = None,
                    nav_kind: str = "net_value") -> NavSeries | None:
    """读取单份额净值序列。"""
    with get_connection(db_path) as conn:
        if code:
            row = conn.execute(
                """SELECT share_class_id, fund_id, share_class_code,
                          share_class_name FROM fund_share_classes
                   WHERE share_class_code=?""", (code,)).fetchone()
        else:
            row = None
        if row is None:
            return None
        rows = [dict(r) for r in conn.execute(
            """SELECT nav_date, unit_nav, acc_nav FROM fund_nav_daily
               WHERE share_class_id=? AND nav_kind=? ORDER BY nav_date""",
            (int(row["share_class_id"]), nav_kind)).fetchall()]
    return audit_nav_series(row["share_class_code"], int(row["share_class_id"]),
                            int(row["fund_id"]), row["share_class_name"],
                            nav_kind, rows)


def load_money_series(db_path: Path | None = None, *,
                      code: str) -> dict:
    """货币基金：每万份收益 + 7日年化，独立口径。"""
    with get_connection(db_path) as conn:
        row = conn.execute(
            """SELECT share_class_id, fund_id, share_class_code, share_class_name
               FROM fund_share_classes WHERE share_class_code=?""", (code,)).fetchone()
        if row is None:
            return {}
        rows = [dict(r) for r in conn.execute(
            """SELECT nav_date, per_10k_yield, seven_day_annual
               FROM fund_nav_daily
               WHERE share_class_id=? AND nav_kind='money_yield'
               ORDER BY nav_date""", (int(row["share_class_id"]),)).fetchall()]
    dates = [r["nav_date"] for r in rows]
    gaps = []
    max_gap = 0
    for a, b in zip(dates, dates[1:]):
        da = datetime.strptime(a, "%Y-%m-%d")
        db_ = datetime.strptime(b, "%Y-%m-%d")
        delta = (db_ - da).days
        if delta > max_gap:
            max_gap = delta
        if delta > MAX_GAP_DAYS_FOR_RETURN:
            gaps.append({"from": a, "to": b, "days": delta})
    return {
        "code": row["share_class_code"],
        "share_class_id": int(row["share_class_id"]),
        "fund_id": int(row["fund_id"]),
        "share_class_name": row["share_class_name"],
        "nav_kind": "money_yield",
        "rows": len(rows),
        "date_min": dates[0] if dates else None,
        "date_max": dates[-1] if dates else None,
        "null_per_10k": sum(1 for r in rows if r["per_10k_yield"] is None),
        "null_seven_day": sum(1 for r in rows if r["seven_day_annual"] is None),
        "max_gap_days": max_gap,
        "gap_count_over_threshold": len(gaps),
        "gaps_sample": gaps[:5],
        "continuity_verification": "cannot_verify",
        # 货币基金不使用 unit_nav / acc_nav
        "uses_unit_nav": False,
    }


def load_fee_info(db_path: Path | None = None, *, code: str) -> dict:
    """费率信息：区分有生效日 / 无生效日；不假设 0，不用 unknown 冒充数值。"""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT share_class_id FROM fund_share_classes WHERE share_class_code=?",
            (code,)).fetchone()
        if row is None:
            return {"available": False, "reason": "share_class_not_found"}
        sid = int(row["share_class_id"])
        rows = [dict(r) for r in conn.execute(
            """SELECT fee_type, tier_order, rate_original, rate_platform,
                      platform_name, is_annual, effective_from, effective_to,
                      evidence_level, announcement_id, detail
               FROM fund_fee_rules WHERE share_class_id=?
               ORDER BY fee_type, tier_order""", (sid,)).fetchall()]

    annual = {}
    for r in rows:
        if not r["is_annual"]:
            continue
        annual[r["fee_type"]] = {
            "rate_original": r["rate_original"],
            "effective_from": r["effective_from"],
            "evidence_level": r["evidence_level"],
            "announcement_id": r["announcement_id"],
            # 无生效日 → 只能当前情景
            "usable_for_current_scenario": r["rate_original"] is not None,
            "usable_for_historical": r["effective_from"] is not None,
            "status": ("ok" if r["rate_original"] is not None
                       else "not_available"),
        }

    purchase = [r for r in rows if r["fee_type"] == "purchase"]
    redemption = [r for r in rows if r["fee_type"] == "redemption"]

    def summarize(tiers, kind):
        if not tiers:
            return {"available": False, "reason": f"no_{kind}_tiers",
                    "usable_for_historical": False,
                    "usable_for_current_scenario": False}
        with_rate = [t for t in tiers if t["rate_original"] is not None]
        with_eff = [t for t in tiers if t["effective_from"]]
        return {
            "available": True,
            "tier_count": len(tiers),
            "tiers_with_rate": len(with_rate),
            "tiers_with_effective_from": len(with_eff),
            "usable_for_current_scenario": bool(with_rate),
            "usable_for_historical": len(with_eff) == len(tiers) and bool(tiers),
            "holding_days_basis": "unknown",
            "platform_note": "平台优惠费率仅代表天天基金，不代表支付宝",
        }

    return {
        "available": bool(rows),
        "annual_fees": annual,
        "purchase_fee": summarize(purchase, "purchase"),
        "redemption_fee": summarize(redemption, "redemption"),
        "alipay_fee": {"status": "unknown",
                       "reason": "支付宝实际费率无公开合法数据源"},
        "evidence_note": "年化费率 C 级；有公告生效日的记 A-（经公告库转发）",
    }


def load_universe(db_path: Path | None = None, *, include_terminated: bool = False,
                  include_onshore_etf: bool = False) -> list[dict]:
    """加载基金研究池（默认只含场外、不含场内 ETF）。

    每个元素是**份额**级记录，带本体信息与分类结果。
    """
    with get_connection(db_path) as conn:
        sql = """
            SELECT m.fund_id, m.fund_code_primary, m.fund_name, m.fund_company,
                   m.fund_type_l1, m.fund_type_l2, m.is_index_fund,
                   m.tracking_index, m.benchmark, m.established_date,
                   m.lifecycle_status,
                   s.share_class_id, s.share_class_code, s.share_class_name,
                   s.is_primary
            FROM fund_master m
            JOIN fund_share_classes s ON s.fund_id = m.fund_id
        """
        where = []
        if not include_terminated:
            where.append("m.lifecycle_status <> 'terminated'")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY m.fund_code_primary, s.share_class_code"
        rows = [dict(r) for r in conn.execute(sql).fetchall()]

    out = []
    for r in rows:
        c = classify_fund(r)
        in_pool = is_offmarket_pool(c, r["fund_code_primary"])
        if not include_onshore_etf and not in_pool:
            continue
        pg = peer_group_key(c, r["fund_name"], r["benchmark"],
                            tracking_index=r["tracking_index"])
        out.append({
            "fund_id": int(r["fund_id"]),
            "fund_code": r["fund_code_primary"],
            "fund_name": r["fund_name"],
            "fund_company": r["fund_company"],
            "fund_type_l1": r["fund_type_l1"],
            "fund_type_l2": r["fund_type_l2"],
            "benchmark": r["benchmark"],
            "tracking_index": r["tracking_index"],
            "established_date": r["established_date"],
            "lifecycle_status": r["lifecycle_status"],
            "share_class_id": int(r["share_class_id"]),
            "share_code": r["share_class_code"],
            "share_name": r["share_class_name"],
            "is_primary": r["is_primary"],
            **c,
            "index_scope": index_scope(r["fund_name"]),
            "peer_group": pg,
        })
    return out
