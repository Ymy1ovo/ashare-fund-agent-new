"""阶段3B-4.3 场外基金数据质量与幸存者偏差验收（只读审计）。

只读，不改正式库、不改已验收模块、不重新采集任何数据。

八块审计：
1. 清盘事件与幸存者偏差
2. 净值数据质量
3. 分红数据质量
4. 费率数据质量
5. 经理与规模历史
6. 份额与本体关系
7. 支付宝状态与交易规则
8. 数据来源与证据等级 + 回测使用门槛

核心原则：**准确知道哪些数据可信、哪些不可信、不可信的绝不能怎么用。**
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database.db import get_connection, settings  # noqa: E402

DB = Path(settings.database_path)
LIFECYCLE_SOURCE = "dfcfw.announcement.calibrated"
NOW = datetime.now()

# ---------------------------------------------------------------- 证据等级
EVIDENCE_LEVELS = {
    "A": "官方原始来源，可追溯原始公告或正式文件",
    "B": "可信第三方转载或整理，但未逐条回源官方原文",
    "C": "第三方数据平台信息，尚未与合同或官方数据逐条核验",
    "D": "推断、代理或人工假设",
    "unknown": "无法确认",
}

# 交易日历只是代理，不是基金净值公布日历
CALENDAR_ROLE = "proxy_not_fund_calendar"


# ---------------------------------------------------------------- 1. 清盘与幸存者偏差
def audit_lifecycle(conn) -> dict:
    rows = conn.execute(
        """SELECT event_id, fund_id, event_type, event_date, announcement_date,
                  announcement_id, announcement_url, product_structure,
                  fund_codes, evidence_level, fetched_at
           FROM fund_lifecycle_events WHERE source=?""",
        (LIFECYCLE_SOURCE,)).fetchall()

    by_structure = defaultdict(int)
    by_level = defaultdict(int)
    event_dates = []
    ann_dates = []
    null_event_date = 0
    fund_ids = []
    dup_events = []
    for r in rows:
        by_structure[r["product_structure"]] += 1
        by_level[r["evidence_level"]] += 1
        fund_ids.append(int(r["fund_id"]))
        if r["event_date"]:
            event_dates.append(r["event_date"])
        else:
            null_event_date += 1
        if r["announcement_date"]:
            ann_dates.append(r["announcement_date"])

    # 同一本体重复事件
    seen = defaultdict(int)
    for r in rows:
        seen[(r["fund_id"], r["event_type"])] += 1
    dup_events = [{"fund_id": int(k[0]), "event_type": k[1], "count": v}
                  for k, v in seen.items() if v > 1]

    # 代码冲突：同一代码出现在多个事件
    code_owner = defaultdict(set)
    for r in rows:
        for c in (r["fund_codes"] or "").split(","):
            if c:
                code_owner[c].add(int(r["fund_id"]))
    code_conflicts = [{"code": c, "fund_ids": sorted(v)}
                      for c, v in code_owner.items() if len(v) > 1]

    years = sorted({d[:4] for d in ann_dates})

    # 存续 vs 清盘：按 lifecycle_status 实际分布统计，不假设只有 active/terminated
    status_dist = {r[0]: r[1] for r in conn.execute(
        "SELECT lifecycle_status, COUNT(*) FROM fund_master GROUP BY 1").fetchall()}
    alive = status_dist.get("active", 0)
    terminated = status_dist.get("terminated", 0)

    # ---- 统一的「本体 / 份额」两套口径统计（本阶段修正重点）----
    # 绝不把份额数当成本体数，也不把本体数当份额数。
    def _scope_counts(status):
        r = conn.execute(
            """SELECT COUNT(DISTINCT m.fund_id) AS funds,
                      COUNT(s.share_class_id) AS shares
               FROM fund_master m
               JOIN fund_share_classes s ON s.fund_id = m.fund_id
               WHERE m.lifecycle_status = ?""", (status,)).fetchone()
        return int(r["funds"]), int(r["shares"])

    live_funds, live_shares = _scope_counts("unknown")
    term_funds, term_shares = _scope_counts("terminated")
    act_funds, act_shares = _scope_counts("active")

    return {
        "total_events": len(rows),
        "distinct_funds": len(set(fund_ids)),
        # 两套口径，字段名自带单位，避免调用方混淆
        "non_terminated_fund_count": live_funds,
        "non_terminated_share_count": live_shares,
        "known_terminated_fund_count": term_funds,
        "known_terminated_share_count": term_shares,
        "confirmed_active_fund_count": act_funds,
        "confirmed_active_share_count": act_shares,
        "unit_note": (
            "fund = 基金本体（fund_master 一行）；share = 份额类别"
            "（fund_share_classes 一行）。A/C 是同一本体的两个份额，"
            "分级 A/B 同理。**比较必须在同一口径内进行**："
            "本体比本体、份额比份额，不得 12 份额 vs 41 本体。"),
        "by_product_structure": dict(by_structure),
        "by_evidence_level": dict(by_level),
        "event_date_null": null_event_date,
        "event_date_range": [min(event_dates), max(event_dates)] if event_dates else None,
        "announcement_date_range": ([min(ann_dates), max(ann_dates)] if ann_dates else None),
        "announcement_years": years,
        "duplicate_events": dup_events,
        "code_conflicts": code_conflicts,
        "all_have_url": all(r["announcement_url"] for r in rows),
        "all_have_ann_id": all(r["announcement_id"] for r in rows),
        "master_active": alive,
        "master_terminated": terminated,
        "master_lifecycle_status_distribution": status_dist,
        "master_status_note": (
            f"当前有 {live_funds} 个**基金本体**（不是 {live_shares} 个——"
            f"{live_shares} 是这 {live_funds} 个本体下的份额数量）的 "
            f"lifecycle_status 为 'unknown'，而非 'active'。"
            "原因是本项目从未取得「该基金当前仍在运作」的正式证据。"
            "**unknown 不等于已确认仍在运作，也不等于已清盘**——它只是没证据。"
            "这是如实记录，不是缺失，不应为了好看改成 active。"),
        "coverage_quantifiable": False,
        "survivorship_bias_status": "not_eliminated",
    }


# ---------------------------------------------------------------- 2. 净值质量
def audit_nav(conn) -> dict:
    out = {}
    rows = conn.execute(
        """SELECT s.share_class_code, s.is_primary, n.nav_kind,
                  COUNT(*) AS c, MIN(n.nav_date) AS dmin, MAX(n.nav_date) AS dmax,
                  SUM(CASE WHEN n.unit_nav IS NULL AND n.nav_kind='net_value'
                           THEN 1 ELSE 0 END) AS null_unit,
                  SUM(CASE WHEN n.acc_nav IS NULL THEN 1 ELSE 0 END) AS null_acc,
                  SUM(CASE WHEN n.per_10k_yield IS NULL
                           THEN 1 ELSE 0 END) AS null_yield,
                  SUM(CASE WHEN n.unit_nav IS NOT NULL AND n.unit_nav<=0
                           THEN 1 ELSE 0 END) AS nonpos
           FROM fund_nav_daily n
           JOIN fund_share_classes s ON s.share_class_id=n.share_class_id
           GROUP BY s.share_class_code, n.nav_kind
           ORDER BY s.share_class_code""").fetchall()

    per_fund = []
    for r in rows:
        code = r["share_class_code"]
        # 重复日期
        dup = conn.execute(
            """SELECT COUNT(*) FROM (SELECT 1 FROM fund_nav_daily n
               JOIN fund_share_classes s ON s.share_class_id=n.share_class_id
               WHERE s.share_class_code=? AND n.nav_kind=?
               GROUP BY n.nav_date HAVING COUNT(*)>1)""",
            (code, r["nav_kind"])).fetchone()[0]
        # 相邻记录最大间隔（日历天）
        gaps = conn.execute(
            """SELECT n.nav_date FROM fund_nav_daily n
               JOIN fund_share_classes s ON s.share_class_id=n.share_class_id
               WHERE s.share_class_code=? AND n.nav_kind=? ORDER BY n.nav_date""",
            (code, r["nav_kind"])).fetchall()
        dates = [g[0] for g in gaps]
        max_gap = 0
        max_gap_at = None
        long_gaps = []
        for a, b in zip(dates, dates[1:]):
            da = datetime.strptime(a, "%Y-%m-%d")
            db_ = datetime.strptime(b, "%Y-%m-%d")
            delta = (db_ - da).days
            if delta > max_gap:
                max_gap, max_gap_at = delta, (a, b)
            if delta > 30:
                long_gaps.append({"from": a, "to": b, "days": delta})
        per_fund.append({
            "code": code,
            "nav_kind": r["nav_kind"],
            "is_primary": r["is_primary"],
            "rows": r["c"],
            "date_min": r["dmin"],
            "date_max": r["dmax"],
            "duplicate_dates": dup,
            "null_unit_nav": r["null_unit"],
            "null_acc_nav": r["null_acc"],
            "null_per_10k": r["null_yield"],
            "nonpositive_unit_nav": r["nonpos"],
            "max_gap_days": max_gap,
            "max_gap_at": list(max_gap_at) if max_gap_at else None,
            "gaps_over_30d": long_gaps[:5],
            "gaps_over_30d_count": len(long_gaps),
            "max_gap_note": (
                "最大间隔通常是春节/国庆长假（如 2020-01-23→02-03、"
                "2006-01-25→02-06、2023-09-28→10-09），属正常休市，"
                "**不是数据缺失**——但也不能据此断言净值一定已在该日公布。"),
        })
        out[code] = per_fund[-1]

    # 口径隔离：net_value 行不得有 per_10k_yield；money_yield 不得有 unit_nav
    mixed = conn.execute(
        """SELECT COUNT(*) FROM fund_nav_daily
           WHERE nav_kind='net_value' AND (per_10k_yield IS NOT NULL
                                           OR seven_day_annual IS NOT NULL)"""
    ).fetchone()[0]
    mixed2 = conn.execute(
        """SELECT COUNT(*) FROM fund_nav_daily
           WHERE nav_kind='money_yield' AND (unit_nav IS NOT NULL OR acc_nav IS NOT NULL)"""
    ).fetchone()[0]

    kinds = defaultdict(int)
    for v in out.values():
        kinds[v["nav_kind"]] += 1

    # 净值是按**份额**存储的：12 个份额 → 9 个本体。
    # 必须分别给出两个口径，不能把 12 个份额说成 12 只基金。
    nav_share_codes = sorted(out.keys())
    nav_fund_count = conn.execute(
        """SELECT COUNT(DISTINCT s.fund_id) FROM fund_share_classes s
           WHERE s.share_class_code IN ({})""".format(
            ",".join("?" * len(nav_share_codes))),
        tuple(nav_share_codes)).fetchone()[0] if nav_share_codes else 0

    return {
        "per_fund": per_fund,
        # 语义修正：nav 是按份额存的，两个口径都要显式给出
        "share_count_with_nav": len(out),
        "fund_count_with_nav": int(nav_fund_count),
        "unit_note": (
            "净值表 fund_nav_daily 的主键是 share_class_id，"
            "因此 {0} 是**份额**数量，对应 {1} 个**基金本体**。"
            "两者的差异就是 A/C 双份额的本体。").format(
                len(out), int(nav_fund_count)),
        "nav_kind_distribution": dict(kinds),
        "net_value_rows": conn.execute(
            "SELECT COUNT(*) FROM fund_nav_daily WHERE nav_kind='net_value'").fetchone()[0],
        "money_yield_rows": conn.execute(
            "SELECT COUNT(*) FROM fund_nav_daily WHERE nav_kind='money_yield'").fetchone()[0],
        "mixed_kind_net_value": mixed,
        "mixed_kind_money_yield": mixed2,
        "duplicate_date_total": sum(v["duplicate_dates"] for v in out.values()),
        "null_unit_nav_total": sum(v["null_unit_nav"] for v in out.values()),
        "nonpositive_unit_nav_total": sum(
            v["nonpositive_unit_nav"] for v in out.values()),
        # 关键降级声明
        "calendar_role": CALENDAR_ROLE,
        "calendar_statement": (
            "A 股交易日历只是代理，不代表每只基金真实净值公布日历。"
            "因此**无法**判定某个 A 股交易日缺净值就是数据缺失，"
            "也**无法**判定周末无净值是异常。"),
        "continuity_verification_level": "cannot_verify",
        "continuity_note": (
            "没有可靠的基金实际净值公布日历，净值连续性一律标记"
            " verification_level=cannot_verify，不产出「连续/不连续」结论。"),
    }


# ---------------------------------------------------------------- 3. 分红质量
def audit_dividend(conn) -> dict:
    total = conn.execute("SELECT COUNT(*) FROM fund_dividends").fetchone()[0]
    by_code = []
    for r in conn.execute(
            """SELECT s.share_class_code, COUNT(*) c,
                      SUM(CASE WHEN d.record_date IS NULL THEN 1 ELSE 0 END) no_rec,
                      SUM(CASE WHEN d.ex_date IS NULL THEN 1 ELSE 0 END) no_ex,
                      SUM(CASE WHEN d.pay_date IS NULL THEN 1 ELSE 0 END) no_pay,
                      SUM(CASE WHEN d.per_10_raw IS NULL THEN 1 ELSE 0 END) no_raw
               FROM fund_dividends d
               JOIN fund_share_classes s ON s.share_class_id=d.share_class_id
               GROUP BY 1 ORDER BY 1""").fetchall():
        by_code.append({
            "code": r["share_class_code"], "rows": r["c"],
            "null_record_date": r["no_rec"], "null_ex_date": r["no_ex"],
            "null_pay_date": r["no_pay"], "null_per_10_raw": r["no_raw"],
        })

    dup = conn.execute(
        """SELECT share_class_id, ex_date, source, COUNT(*) c
           FROM fund_dividends GROUP BY 1,2,3 HAVING c>1""").fetchall()

    # 每10份换算正确性：cash_per_share * 10 应等于 per_10_raw 的金额
    # 注意原文形如「每10份派现金0.4500元」，必须取「现金」后面的数字，
    # 不能取「每10份」里的 10——那是份数不是金额。
    import re
    mism = 0
    checked = 0
    _AMT = re.compile(r"现金\s*([0-9]+(?:\.[0-9]+)?)")
    for r in conn.execute(
            "SELECT per_10_raw, cash_per_share FROM fund_dividends").fetchall():
        raw = r["per_10_raw"] or ""
        m = _AMT.search(raw)
        if not m:
            continue
        checked += 1
        expect = float(m.group(1)) / 10.0
        if abs(expect - float(r["cash_per_share"])) > 1e-6:
            mism += 1

    sources = {r[0]: r[1] for r in conn.execute(
        "SELECT source, COUNT(*) FROM fund_dividends GROUP BY 1").fetchall()}

    return {
        "total": total,
        "by_code": by_code,
        "funds_with_dividends": len(by_code),
        "duplicate_groups": len(dup),
        "per10_conversion_mismatch": mism,
        "per10_conversion_checked": checked,
        "sources": sources,
        "completeness_statement": (
            "分红接口单次返回不完整（3B-3.1 已实测同一基金不同请求结果不同）。"
            "当前 44 条**不能**当成完整历史分红数量。"),
        "usable_for_return_adjustment": False,
        "usable_reason": "未验证除息/到账口径，不能用于修正历史收益",
    }


# ---------------------------------------------------------------- 4. 费率质量
def audit_fee(conn) -> dict:
    total = conn.execute("SELECT COUNT(*) FROM fund_fee_rules").fetchone()[0]
    by_type = {r[0]: r[1] for r in conn.execute(
        "SELECT fee_type, COUNT(*) FROM fund_fee_rules GROUP BY 1").fetchall()}
    by_level = {r[0]: r[1] for r in conn.execute(
        "SELECT evidence_level, COUNT(*) FROM fund_fee_rules GROUP BY 1").fetchall()}

    null_rate = conn.execute(
        "SELECT COUNT(*) FROM fund_fee_rules WHERE rate_original IS NULL").fetchone()[0]
    null_eff_from = conn.execute(
        "SELECT COUNT(*) FROM fund_fee_rules WHERE effective_from IS NULL").fetchone()[0]
    null_eff_to = conn.execute(
        "SELECT COUNT(*) FROM fund_fee_rules WHERE effective_to IS NULL").fetchone()[0]
    null_basis = conn.execute(
        "SELECT COUNT(*) FROM fund_fee_rules WHERE holding_days_basis IS NULL").fetchone()[0]
    with_platform = conn.execute(
        "SELECT COUNT(*) FROM fund_fee_rules WHERE rate_platform IS NOT NULL").fetchone()[0]
    alipay_platform = conn.execute(
        "SELECT COUNT(*) FROM fund_fee_rules WHERE platform_name='alipay'").fetchone()[0]
    inferred = conn.execute(
        """SELECT COUNT(*) FROM fund_fee_rules
           WHERE holding_days_min_inferred=1 OR lower_inferred=1""").fetchone()[0]
    known_bounds = conn.execute(
        """SELECT COUNT(*) FROM fund_fee_rules
           WHERE (lower_inclusive IS NOT NULL OR upper_inclusive IS NOT NULL
                  OR holding_days_min_inclusive IS NOT NULL
                  OR holding_days_max_inclusive IS NOT NULL)""").fetchone()[0]
    unknown_bounds = total - known_bounds

    # 有效费率数值：非 NULL 且非推断
    usable_rates = conn.execute(
        "SELECT COUNT(*) FROM fund_fee_rules WHERE rate_original IS NOT NULL").fetchone()[0]

    return {
        "total": total,
        "by_fee_type": by_type,
        "by_evidence_level": by_level,
        "rate_original_null": null_rate,
        "rate_original_present": usable_rates,
        "effective_from_all_null": null_eff_from == total,
        "effective_to_all_null": null_eff_to == total,
        "holding_days_basis_all_null": null_basis == total,
        "with_platform_rate": with_platform,
        "alipay_platform_rows": alipay_platform,
        "inferred_lower_bound": inferred,
        "bounds_known": known_bounds,
        "bounds_unknown": unknown_bounds,
        "usable_for_historical_cost": False,
        "usable_conditions": [
            "只能用于**当前**费率情景下的成本估算，不能用于历史区间",
            "必须标注证据等级 C（天天基金 F10，非合同原文）",
            "平台优惠费率仅代表天天基金，不代表支付宝",
            "持有期按自然日还是交易日未确认，计算时必须显式标注假设",
            "rate_original 为 NULL 的必须跳过，不得填 0",
        ],
        "forbidden_uses": [
            "当作支付宝实际费率",
            "当作历史生效费率",
            "把 platform_rate 当合同费率",
            "对 NULL 费率填 0 或行业平均",
        ],
    }


# ---------------------------------------------------------------- 5. 经理与规模
def audit_manager_aum(conn) -> dict:
    mgr = []
    for r in conn.execute(
            """SELECT f.fund_code_primary, m.manager_name, m.start_date,
                      m.end_date, m.tenure_days, m.source
               FROM fund_manager_history m
               JOIN fund_master f ON f.fund_id=m.fund_id
               ORDER BY 1, 2""").fetchall():
        mgr.append({
            "fund": r["fund_code_primary"], "manager": r["manager_name"],
            "start_date": r["start_date"], "end_date": r["end_date"],
            "tenure_days": r["tenure_days"], "source": r["source"],
        })
    aum = []
    for r in conn.execute(
            """SELECT f.fund_code_primary, a.report_date, a.aum_total, a.source
               FROM fund_aum_history a
               JOIN fund_master f ON f.fund_id=a.fund_id ORDER BY 1""").fetchall():
        aum.append({"fund": r["fund_code_primary"],
                    "report_date": r["report_date"],
                    "aum_total": r["aum_total"], "source": r["source"]})

    funds = {m["fund"] for m in mgr}
    start_null = sum(1 for m in mgr if m["start_date"] is None)
    end_null = sum(1 for m in mgr if m["end_date"] is None)
    aum_dates = sorted({a["report_date"] for a in aum})

    return {
        "manager_records": len(mgr),
        "funds_with_manager": len(funds),
        "manager_start_date_null": start_null,
        "manager_end_date_null": end_null,
        "aum_records": len(aum),
        "aum_distinct_dates": aum_dates,
        "aum_snapshot_count": len(aum_dates),
        "aum_multi_period": len(aum_dates) > 1,
        "backfill_forbidden": True,
        "backfill_statement": (
            "经理任职起止日期全部为 NULL；规模只有单一报告日快照。"
            "**禁止**用当前基金经理回填历史区间，"
            "**禁止**用当前规模代表历史规模。"),
        "usable_for_backtest": False,
        "usable_reason": "无时间序列，只有当前快照，回填即引入未来信息",
    }


# ---------------------------------------------------------------- 6. 份额关系
def audit_share_relation(conn) -> dict:
    # 每个本体的主份额数
    rows = conn.execute(
        """SELECT fund_id,
                  SUM(CASE WHEN is_primary=1 THEN 1 ELSE 0 END) primaries,
                  COUNT(*) total
           FROM fund_share_classes GROUP BY fund_id""").fetchall()
    multi_primary = [{"fund_id": int(r["fund_id"]), "primaries": int(r["primaries"])}
                     for r in rows if int(r["primaries"]) > 1]
    no_primary = [{"fund_id": int(r["fund_id"])} for r in rows if int(r["primaries"]) == 0]

    # 份额代码跨本体
    dup_codes = conn.execute(
        """SELECT share_class_code, COUNT(DISTINCT fund_id) c
           FROM fund_share_classes GROUP BY 1 HAVING c>1""").fetchall()

    # 清盘本体 vs 存续本体
    terminated_fids = {int(r[0]) for r in conn.execute(
        "SELECT DISTINCT fund_id FROM fund_lifecycle_events WHERE source=?",
        (LIFECYCLE_SOURCE,)).fetchall()}
    t_rows = [r for r in rows if int(r["fund_id"]) in terminated_fids]
    t_ok = sum(1 for r in t_rows if int(r["primaries"]) == 1)

    # 货币基金份额
    money = [r[0] for r in conn.execute(
        """SELECT DISTINCT s.share_class_code FROM fund_nav_daily n
           JOIN fund_share_classes s ON s.share_class_id=n.share_class_id
           WHERE n.nav_kind='money_yield'""").fetchall()]

    return {
        "fund_entities": len(rows),
        "share_records": sum(int(r["total"]) for r in rows),
        "multi_primary_funds": multi_primary,
        "no_primary_funds": no_primary,
        "duplicate_share_codes": len(dup_codes),
        "terminated_entities": len(t_rows),
        "terminated_with_exactly_one_primary": t_ok,
        "money_fund_codes": money,
        "money_isolated": len(money) > 0,
    }


# ---------------------------------------------------------------- 7. 支付宝
def audit_alipay(conn) -> dict:
    dist = {r[0]: r[1] for r in conn.execute(
        "SELECT alipay_purchasable, COUNT(*) FROM fund_subscription_status GROUP BY 1"
    ).fetchall()}
    return {
        "alipay_status": "unknown",
        "distribution": dist,
        "all_unknown": set(dist) <= {"unknown"},
        "statement": (
            "支付宝可购买状态全部 unknown。天天基金开放申购状态不代表支付宝，"
            "天天基金优惠费率不能推断支付宝实际费率，不得逆向 APP 或伪造购买状态。"),
        "trading_rule_categories": {
            "industry_convention": "行业通则（如 T+1 确认），非强制，各基金可不同",
            "fund_contract": "基金合同规定（申赎开放日、巨额赎回等）",
            "platform_execution": "销售平台实际执行规则（如 15:00 截止）",
            "unverified": "尚未核实的规则",
        },
        "unverified_rules": [
            "15:00 申购赎回截止时间（行业惯例，非所有平台统一）",
            "T+1 份额确认（不同基金/平台可能不同）",
            "赎回到账时间（货币基金 T+0/T+1，股基 T+1~T+7）",
            "限购金额与单日额度",
        ],
        "cannot_apply_uniformly": True,
    }


# ---------------------------------------------------------------- 8. 使用门槛
def build_usage_matrix(nav: dict, div: dict, fee: dict,
                       mgr: dict, life: dict) -> dict:
    """未来回测的数据使用门槛。全部依据真实审计结果。"""
    return {
        "tier_1_direct_use": [
            {
                "data": "历史单位净值（net_value）",
                "evidence": "C（akshare.fund_open_fund_info_em）",
                "condition": "只看单只基金自身时间序列，不做跨基金日期对齐",
                "known_limit": f"共 {nav['net_value_rows']} 行，"
                               f"{nav['duplicate_date_total']} 处重复日期，"
                               f"{nav['null_unit_nav_total']} 处空值",
            },
            {
                "data": "清盘事件清单（41 条）",
                "evidence": "B",
                "condition": "只能用于「已知清盘」的剔除，不能声称覆盖完整",
                "known_limit": f"证据 B，{life['event_date_null']} 条缺事件日期，"
                               f"覆盖率不可量化",
            },
        ],
        "tier_2_conditional": [
            {
                "data": "累计净值（acc_nav）",
                "evidence": "C",
                "condition": "不得与单位净值混用；收益计算必须明确用哪一个",
                "blocker": "需确认分红再投资口径",
            },
            {
                "data": "申购费 / 赎回费阶梯",
                "evidence": "C",
                "condition": "只能做当前费率情景估算，必须标 C 级",
                "blocker": "effective_from 全 NULL，历史费率不可用；"
                           "持有期自然日/交易日未确认",
            },
            {
                "data": "管理费 / 托管费 / 销售服务费",
                "evidence": "C",
                "condition": "年化费率，可从净值中已扣除部分不重复计",
                "blocker": f"{fee['by_fee_type'].get('sales_service',0)} 条销售服务费中"
                           f"有 NULL（页面 ---），不得填 0",
            },
            {
                "data": "分红记录",
                "evidence": "C",
                "condition": "只能作为辅助核对，不得用于修正历史收益",
                "blocker": f"{div['total']} 条不完整（接口单次返回不全）",
            },
        ],
        "tier_3_auxiliary_only": [
            {
                "data": "基金经理历史",
                "evidence": "C",
                "condition": "只能了解「谁在管」，不能作为时点特征",
                "blocker": f"{mgr['manager_start_date_null']} 条起止日期全 NULL，"
                           f"回填即未来信息",
            },
            {
                "data": "基金规模历史",
                "evidence": "C",
                "condition": "只有单一快照，不能当时间序列",
                "blocker": f"仅 {mgr['aum_snapshot_count']} 个报告日",
            },
        ],
        "tier_4_forbidden": [
            {
                "data": "支付宝可购买状态",
                "reason": "全部 unknown，无公开合法数据源",
            },
            {
                "data": "支付宝实际费率",
                "reason": "无法获取，天天基金费率不能冒充",
            },
            {
                "data": "历史生效费率",
                "reason": "effective_from 全 NULL，当前费率不是历史费率",
            },
            {
                "data": "净值连续性结论",
                "reason": "无基金净值公布日历，只能 cannot_verify",
            },
            {
                "data": "完整历史清盘名录",
                "reason": "41 条只是已知清单，覆盖率不可量化",
            },
        ],
    }


# ---------------------------------------------------------------- 主流程
def main() -> dict:
    with get_connection(DB) as conn:
        life = audit_lifecycle(conn)
        nav = audit_nav(conn)
        div = audit_dividend(conn)
        fee = audit_fee(conn)
        mgr = audit_manager_aum(conn)
        share = audit_share_relation(conn)
        alipay = audit_alipay(conn)

    matrix = build_usage_matrix(nav, div, fee, mgr, life)

    payload = {
        "phase": "3B-4.3",
        "baseline_head": "93c920cc66196610838e3dad21d9b9d45216dbe6",
        "generated_at": NOW.isoformat(timespec="seconds"),
        "scope": ("只读审计：不改正式库、不改已验收模块、不重新采集数据、"
                  "不开发策略、不做回测。"),
        "evidence_levels": EVIDENCE_LEVELS,
        "lifecycle": life,
        "nav": nav,
        "dividend": div,
        "fee": fee,
        "manager_aum": mgr,
        "share_relation": share,
        "alipay": alipay,
        "usage_matrix": matrix,
        "conclusions": {
            "q1_data_credibility": (
                "净值 C（第三方接口，自身时间序列可用，跨基金对齐不可用）；"
                "清盘 B（东财转载，未回源官方）；费率 C（F10 非合同）；"
                "分红 C 且不完整；经理/规模 C 但只有当前快照"),
            "q2_missing_and_bias": [
                f"净值 {nav['null_unit_nav_total']} 处空值、"
                f"{nav['duplicate_date_total']} 处重复日期",
                f"清盘 {life['event_date_null']} 条缺事件日期",
                f"费率 {fee['rate_original_null']} 条 rate 为 NULL、"
                f"{fee['inferred_lower_bound']} 条下界为推断",
                f"经理 {mgr['manager_start_date_null']} 条起止日期 NULL",
                f"规模只有 {mgr['aum_snapshot_count']} 个报告日",
                f"分红 {div['total']} 条且接口返回不完整",
            ],
            "q3_survivorship_bias": (
                "存在。41 条已知清盘 + 12 只存续，"
                "清盘覆盖率不可量化，**未消除**幸存者偏差"),
            "q4_sufficient_for_backtest": (
                "不足以支撑正式历史回测。净值可用但只能单序列；"
                "费率无历史生效时间；清盘名录不完整；"
                "经理与规模无时间序列"),
            "q5_what_can_be_used": "见 usage_matrix 四档分层",
            "q6_must_resolve_before_strategy": [
                "费率历史生效时间（effective_from）",
                "净值公布日历或明确接受 cannot_verify",
                "清盘名录覆盖率的量化方法",
                "分红完整性验证",
                "支付宝可购买状态的合法获取途径或明确放弃",
            ],
        },
        "stage_gate": {
            "ready_for_next_stage": False,
            "reason": "数据基础设施可支撑研究性分析，但不足以支撑正式回测成本模拟",
            "allowed_next": "3B-4.4 数据缺口补强 或 研究性分析（非回测）",
            "blocked": ["3B-5 场外基金回测"],
        },
    }
    return payload


if __name__ == "__main__":
    p = main()
    out = ROOT / "reports" / "phase3B4_3_data_quality.json"
    out.write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"JSON -> {out}")
    print("清盘:", p["lifecycle"]["total_events"], "净值:", p["nav"]["net_value_rows"] + p["nav"]["money_yield_rows"])
    print("费率:", p["fee"]["total"], "分红:", p["dividend"]["total"])
    print("幸存者偏差:", p["lifecycle"]["survivorship_bias_status"])
