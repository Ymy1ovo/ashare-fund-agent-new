"""阶段3B-6.0.4 同类比较引擎。

在已有 ``analyze_universe`` 基础上做**同类层面的研究性分析**：

- 组内共同历史区间比较（公平窗口）
- 滚动窗口稳定性
- 组内差异度量
- 超额收益阻断判定

**不产出排名、不给买卖建议。** 结论一律带证据强弱说明。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.fund.research.data_access import load_nav_series, load_universe
from app.fund.research.excess_return import (
    evaluate_excess_return, peer_relative_note,
)
from app.fund.research.peer_comparison import (
    PEER_COMPARABLE, PEER_DESCRIPTIVE_ONLY, PEER_EXCLUDED,
    annualized_from_return, best_window_dependency, common_window,
    exclude_best_window, rolling_windows, series_span, window_return,
    WINDOW_1Y, WINDOW_3Y, WINDOW_5Y,
)
from app.fund.research.quality import (
    LEVEL_A, LEVEL_B, LEVEL_C, LEVEL_D, grade_peer_comparison,
)

# 可验证组判定：基准族已知
_VERIFIABLE_UNKNOWN_FAMILY = ("unknown", "", None)


def is_verifiable_group(peer_key: str) -> bool:
    """组键是否可验证（基准族已知，或属于独立的债券/货币类型组）。"""
    parts = peer_key.split("|")
    pc = parts[0]
    if pc in ("bond_pure", "bond_mixed", "money_market"):
        # 债券/货币按产品类型隔离，但久期等细分未知
        return pc == "money_market"
    return parts[-1] not in _VERIFIABLE_UNKNOWN_FAMILY


def group_usability(peer_key: str, member_count: int) -> dict:
    """组级可用性判定。"""
    verifiable = is_verifiable_group(peer_key)
    if member_count < 2:
        return {"status": PEER_EXCLUDED,
                "reason": f"组内仅 {member_count} 个本体，无法做同类比较",
                "verifiable": verifiable}
    if not verifiable:
        return {"status": PEER_DESCRIPTIVE_ONLY,
                "reason": ("组内基准族不可验证（unknown），"
                           "只能做描述性观察，不能声称同类可比"),
                "verifiable": False}
    if member_count < 5:
        return {"status": PEER_DESCRIPTIVE_ONLY,
                "reason": f"组内 {member_count} 个本体，样本偏小（<5）",
                "verifiable": True}
    return {"status": PEER_COMPARABLE, "reason": None, "verifiable": True}


def group_quality_grade(peer_key: str, member_count: int,
                        peer_ctx: dict | None = None) -> dict:
    """组级质量等级。

    **唯一权威来源**是 ``quality.grade_peer_comparison``，
    本模块不再自建「状态→等级」映射表，避免报告口径不一致
    （3B-6.0.4 曾因自建映射把 ``bond_pure|unknown`` 错标为 C）。
    """
    ctx = {"peer_key": peer_key, "member_count": member_count}
    if peer_ctx:
        ctx.update({
            "grouping_source": peer_ctx.get("grouping_source"),
            "benchmark_confidence": peer_ctx.get("benchmark_confidence"),
            "verifiable_group": peer_ctx.get("verifiable_group"),
            "index_scope": peer_ctx.get("index_scope"),
        })
    return grade_peer_comparison(ctx)


def analyze_group(db_path: Path | None, peer_key: str,
                  fund_ids: list[int]) -> dict:
    """单个同类组的完整分析。"""
    universe = load_universe(db_path)
    by_fund = {}
    for e in universe:
        by_fund.setdefault(e["fund_id"], e)

    usability = group_usability(peer_key, len(fund_ids))
    first_entry = by_fund.get(fund_ids[0]) if fund_ids else None
    peer_ctx = (first_entry or {}).get("peer_group") or {}
    quality = group_quality_grade(peer_key, len(fund_ids), peer_ctx)
    result = {
        "peer_key": peer_key,
        "member_count": len(fund_ids),
        "usability": usability,
        "quality_grade": {
            "quality_level": quality.get("quality_level"),
            "status": quality.get("status"),
            "value": quality.get("value"),
            "reason": quality.get("reason"),
            "limitation": quality.get("limitation"),
        },
        "funds": [],
        "common_window": None,
        "rolling": {},
        "group_dispersion": None,
        "excess_return_status": "not_available",
        "excess_return_reason": None,
        "peer_relative_note": peer_relative_note(),
    }

    if usability["status"] == PEER_EXCLUDED:
        return result

    # 货币基金：独立口径（每万份收益 / 7日年化），
    # 绝不参与净值型共同区间与滚动收益计算
    if peer_key == "money_market":
        result["metric_basis"] = "money_yield"
        result["metric_note"] = (
            "货币基金使用每万份收益与 7 日年化，"
            "**不与净值型基金混算**，因此无共同净值区间")
        result["funds"] = _money_members(db_path, fund_ids)
        result["excess_return_reason"] = (
            "货币基金以短端利率为参照，库内无对应基准序列且无风险利率未接入")
        return result

    # 逐只取净值序列与跨度
    entries = []
    for fid in fund_ids:
        e = by_fund.get(fid)
        if not e:
            continue
        series = load_nav_series(db_path, code=e["share_code"])
        if series is None:
            continue
        span = series_span(series)
        entries.append({"fund_id": fid, "share_code": e["share_code"],
                        "fund_name": e["fund_name"],
                        "product_class": e["product_class"],
                        "peer_group": e["peer_group"],
                        "nav_rows": len(series.points), "span": span,
                        "series": series})

    spans = [x["span"] for x in entries]
    cw = common_window(spans)
    result["common_window"] = cw

    if cw["status"] == "ok":
        returns = []
        for x in entries:
            r = window_return(x["series"], cw["date_min"], cw["date_max"])
            ann = annualized_from_return(r.get("value"), cw.get("span_days") or 0)
            returns.append({**{k: x[k] for k in
                               ("fund_id", "share_code", "fund_name")},
                            "window_return": r, "annualized": ann})
            x["window_return"] = r
        result["common_window"]["fund_returns"] = returns
        ok_vals = [r["window_return"]["value"] for r in returns
                   if r["window_return"]["status"] == "ok"]
        if len(ok_vals) >= 2:
            result["group_dispersion"] = {
                "count": len(ok_vals),
                "min": round(min(ok_vals), 8),
                "max": round(max(ok_vals), 8),
                "spread": round(max(ok_vals) - min(ok_vals), 8),
                "median": round(sorted(ok_vals)[len(ok_vals) // 2], 8),
                "note": "仅为区间收益离散度，不是超额收益",
            }

    # 滚动窗口（对每只基金）
    for x in entries:
        r1 = rolling_windows(x["series"], window_days=WINDOW_1Y)
        r3 = rolling_windows(x["series"], window_days=WINDOW_3Y)
        result["rolling"][x["share_code"]] = {
            "fund_id": x["fund_id"], "fund_name": x["fund_name"],
            "window_1y": _slim(r1),
            "window_3y": _slim(r3),
            "best_window_dependency_1y": best_window_dependency(r1),
            "exclude_best_1y": exclude_best_window(r1),
        }

    # 超额收益：当前必然不可算
    ex = evaluate_excess_return({
        "benchmark_index_codes": [],
        "index_bases": {},
        "composite": None,
    })
    result["excess_return_status"] = ex["excess_return_status"]
    result["excess_return_reason"] = ex["reason"]

    result["funds"] = [{
        "fund_id": x["fund_id"], "share_code": x["share_code"],
        "fund_name": x["fund_name"], "product_class": x["product_class"],
        "nav_rows": x["nav_rows"], "date_min": x["span"]["date_min"],
        "date_max": x["span"]["date_max"],
        "valid_points": x["span"]["valid_points"],
    } for x in entries]
    return result


def _money_members(db_path, fund_ids: list[int]) -> list[dict]:
    """货币基金成员列表（独立口径，只报覆盖不报净值指标）。"""
    from app.database.db import get_connection

    out = []
    with get_connection(db_path) as conn:
        for fid in fund_ids:
            row = conn.execute(
                "SELECT fund_code_primary, fund_name FROM fund_master "
                "WHERE fund_id=?", (fid,)).fetchone()
            if not row:
                continue
            stat = conn.execute(
                "SELECT COUNT(*), MIN(nav_date), MAX(nav_date) "
                "FROM fund_nav_daily d "
                "JOIN fund_share_classes sc ON sc.share_class_id=d.share_class_id "
                "WHERE sc.fund_id=? AND d.nav_kind='money_yield'",
                (fid,)).fetchone()
            out.append({
                "fund_id": fid, "fund_code": row[0], "fund_name": row[1],
                "yield_rows": stat[0],
                "date_min": stat[1], "date_max": stat[2],
                "metric_basis": "money_yield",
            })
    return out


def _slim(r: dict) -> dict:
    """滚动窗口结果瘦身（去掉逐窗口明细，只留摘要）。"""
    return {k: v for k, v in r.items() if k != "windows"}


def analyze_all_groups(db_path: Path | None = None) -> dict:
    """全部同类组分析。"""
    from app.fund.research.engine import analyze_universe

    uni = analyze_universe(db_path)
    groups = uni["peer_analysis"]["groups"]

    out = []
    summary = {PEER_COMPARABLE: 0, PEER_DESCRIPTIVE_ONLY: 0, PEER_EXCLUDED: 0}
    for key, v in sorted(groups.items(), key=lambda x: -x[1]["member_count"]):
        g = analyze_group(db_path, key, v["fund_ids"])
        out.append(g)
        summary[g["usability"]["status"]] += 1

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "group_count": len(out),
        "summary_by_usability": summary,
        "groups": out,
        "gate": {
            "ready_for_research_analysis": True,
            "ready_for_backtest": False,
            "ready_for_formal_ranking": False,
        },
    }
