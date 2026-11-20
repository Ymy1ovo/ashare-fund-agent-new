"""净值型 / 货币型基金指标计算层。

全部指标返回 {"value": ..., "status": ..., "reason": ..., ...} 结构。
status 取值：
- ok                 正常算出
- insufficient_data  样本不足 / 窗口起点无可用净值
- not_available      字段缺失，本引擎不支持
- not_applicable     该指标不适用于此类基金（如货币基金算回撤）

铁律：
1. 窗口按**真实自然日**计算，不用「过去 20 条记录」冒充 1 个月。
2. 窗口端点必须**恰好命中**某条净值；命不中就返回 insufficient_data，
   不向前后找最近值伪装。
3. 不跨越超过 MAX_GAP_DAYS_FOR_RETURN 的缺口计算相邻收益。
4. 不把缺失日收益填 0。
5. 无风险利率缺失时不输出常规 Sharpe（可输出 zero_hurdle_sharpe 并明示）。
6. 年化因子在没有确认频率/连续性时返回未年化 + 标记。
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta

from app.fund.research.data_access import MAX_GAP_DAYS_FOR_RETURN, NavSeries

# 年化参照值：仅在确认是逐交易日频率后才使用**观测频率**年化。
# 不使用固定的 252（那是美股惯例），而是从实际数据密度推导，
# 避免把「假设的交易日数」当成事实。
TRADING_DAYS_PER_YEAR_REFERENCE = 252

# 窗口定义（自然日近似月）
WINDOWS = {
    "ret_1m": ("近 1 月", 30),
    "ret_3m": ("近 3 月", 91),
    "ret_6m": ("近 6 月", 182),
    "ret_12m": ("近 12 月", 365),
    "ret_36m": ("近 36 月", 1095),
}

# 端点容差：0 天 = 必须精确命中
EXACT = 0


def _ok(value, **extra) -> dict:
    d = {"value": value, "status": "ok", "reason": None}
    d.update(extra)
    return d


def _na(reason: str, status: str = "insufficient_data", **extra) -> dict:
    d = {"value": None, "status": status, "reason": reason}
    d.update(extra)
    return d


def _pct(x: float | None) -> float | None:
    return None if x is None else round(x * 100, 6)


# ---------------------------------------------------------------- 窗口收益
def _window_return(series: NavSeries, days: int, *, field_name: str) -> dict:
    """按自然日窗口算收益。端点必须精确命中。"""
    if not series.points:
        return _na("no_nav_data")
    last = series.points[-1]
    end_date = last.d
    start_target = end_date - timedelta(days=days)

    # 起点必须精确存在且该字段有值
    start_val = None
    start_date = None
    for p in series.points:
        if p.d == start_target:
            start_val = getattr(p, field_name)
            start_date = p.nav_date
            break
    if start_val is None:
        return _na(
            f"窗口起点 {start_target.isoformat()} 无可用 {field_name}（不向前后找替代值）",
            status="insufficient_data")

    end_val = getattr(last, field_name)
    if end_val is None:
        return _na(f"终点 {last.nav_date} 无可用 {field_name}")

    # 区间内是否有超阈值缺口
    end_iso = end_date.isoformat()
    gaps = [g for g in series.quality.gaps
            if g["from"] >= start_date and g["to"] <= end_iso]
    if gaps:
        return _na(
            f"区间内存在 {len(gaps)} 处超过 {MAX_GAP_DAYS_FOR_RETURN} 天的缺口，"
            "不跨越缺口计算收益", status="insufficient_data",
            gaps=gaps[:3])

    ret = end_val / start_val - 1.0
    return _ok(round(ret, 6), value_pct=_pct(ret),
               start_date=start_date, end_date=last.nav_date,
               start_value=start_val, end_value=end_val,
               window_days=days, field=field_name)


# ---------------------------------------------------------------- 年化收益
def _annualized(series: NavSeries, *, field_name: str) -> dict:
    """成立以来年化：按实际自然日间隔。"""
    if len(series.points) < 2:
        return _na("净值记录少于 2 条")
    first, last = series.points[0], series.points[-1]
    v0 = getattr(first, field_name)
    v1 = getattr(last, field_name)
    if v0 is None or v1 is None or v0 <= 0:
        return _na(f"{field_name} 缺失或非正")
    span_days = (last.d - first.d).days
    if span_days < 365:
        return _na(f"实际跨度仅 {span_days} 天，不足 1 年不输出年化")
    total = v1 / v0
    if total <= 0:
        return _na("累计净值非正，无法年化")
    years = span_days / 365.25
    ann = total ** (1.0 / years) - 1.0
    return _ok(round(ann, 6), value_pct=_pct(ann),
               span_days=span_days, years=round(years, 4),
               method="自然日间隔复合年化", field=field_name)


# ---------------------------------------------------------------- 日收益序列
def _daily_returns(series: NavSeries, *, field_name: str) -> tuple[list[tuple[date, float, int]], list[dict]]:
    """返回 [(date, return, gap_days)]，跳过跨缺口与缺失值。"""
    out = []
    skipped = []
    for a, b in zip(series.points, series.points[1:]):
        gap = (b.d - a.d).days
        va = getattr(a, field_name)
        vb = getattr(b, field_name)
        if va is None or vb is None or va <= 0:
            skipped.append({"date": b.nav_date, "reason": "missing_value"})
            continue
        if gap > MAX_GAP_DAYS_FOR_RETURN:
            skipped.append({"date": b.nav_date, "reason": f"gap_{gap}d",
                            "from": a.nav_date})
            continue
        out.append((b.d, vb / va - 1.0, gap))
    return out, skipped


def _gap_profile(rets: list[tuple[date, float, int]]) -> dict:
    """间隔结构画像。

    交易日频率的基金，间隔绝大多数是 1 天（连续交易日），
    其余是 2~4 天（周末）或 5~15 天（长假）。
    只有「1 天间隔占多数 + 无超阈值缺口」才算确认了交易日频率。
    """
    if not rets:
        return {"one_day_ratio": 0.0, "weekend_ratio": 0.0,
                "holiday_ratio": 0.0, "irregular_ratio": 1.0, "n": 0}
    n = len(rets)
    one = sum(1 for _, _, g in rets if g == 1)
    weekend = sum(1 for _, _, g in rets if 2 <= g <= 4)
    holiday = sum(1 for _, _, g in rets if 5 <= g <= MAX_GAP_DAYS_FOR_RETURN)
    irregular = sum(1 for _, _, g in rets if g > MAX_GAP_DAYS_FOR_RETURN)
    return {
        "n": n,
        "one_day_ratio": round(one / n, 4),
        "weekend_ratio": round(weekend / n, 4),
        "holiday_ratio": round(holiday / n, 4),
        "irregular_ratio": round(irregular / n, 4),
    }


def _annualization_profile(series: NavSeries, rets: list[tuple[date, float, int]]) -> dict:
    """判断能否年化，并给出观测频率。

    年化必要条件：
    1. 1 天间隔占比 ≥ 60%（证明是逐交易日公布，不是周频/月频）；
    2. 无超过阈值（15 天）的缺口；
    3. 跨度 ≥ 365 天（能估出稳定的年度频率）。

    满足后用**观测到的年频**（有效点数 / 年数）年化，不硬套 252。
    """
    prof = _gap_profile(rets)
    prof["gap_count_over_threshold"] = series.quality.gap_count_over_threshold
    if not rets:
        prof.update({"can_annualize": False,
                     "blocked_reason": "无有效收益点"})
        return prof

    span_days = (rets[-1][0] - rets[0][0]).days
    years = span_days / 365.25 if span_days else 0
    observed = (len(rets) / years) if years > 0 else None
    prof["span_days"] = span_days
    prof["observed_per_year"] = round(observed, 2) if observed else None

    reasons = []
    if prof["one_day_ratio"] < 0.60:
        reasons.append(f"1 天间隔占比仅 {prof['one_day_ratio']:.1%}，"
                       "无法确认为逐交易日公布频率")
    if prof["gap_count_over_threshold"] > 0:
        reasons.append(f"存在 {prof['gap_count_over_threshold']} 处超过 "
                       f"{MAX_GAP_DAYS_FOR_RETURN} 天的缺口")
    if span_days < 365:
        reasons.append(f"跨度仅 {span_days} 天，不足 1 年")

    if reasons:
        prof.update({"can_annualize": False,
                     "blocked_reason": "；".join(reasons)})
    else:
        prof.update({
            "can_annualize": True,
            "blocked_reason": None,
            "annualization_factor": round(observed, 2),
            "annualization_basis": (
                f"观测频率：{len(rets)} 个有效日收益 / {years:.2f} 年 "
                f"≈ {observed:.1f} 次/年；1 天间隔占比 {prof['one_day_ratio']:.1%}，"
                "无超阈值缺口 → 确认为逐交易日公布，按观测频率年化"
                f"（参考值 252，实际用 {observed:.1f}）"),
        })
    return prof


# ---------------------------------------------------------------- 波动率
def _volatility(series: NavSeries, *, field_name: str) -> dict:
    rets, skipped = _daily_returns(series, field_name=field_name)
    if len(rets) < 30:
        return _na(f"有效收益点数 {len(rets)} 不足 30")

    prof = _annualization_profile(series, rets)
    values = [r for _, r, _ in rets]
    mean = sum(values) / len(values)
    var = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
    sd = math.sqrt(var)

    result = {
        "sample_size": len(values),
        "skipped_points": len(skipped),
        "daily_vol": round(sd, 8),
        "gap_profile": {k: prof[k] for k in
                        ("one_day_ratio", "weekend_ratio", "holiday_ratio",
                         "irregular_ratio")},
        "observed_per_year": prof.get("observed_per_year"),
    }
    if prof["can_annualize"]:
        factor = prof["annualization_factor"]
        ann = sd * math.sqrt(factor)
        result.update({
            "value": round(ann, 6),
            "value_pct": _pct(ann),
            "status": "ok",
            "reason": None,
            "annualized": True,
            "annualization_factor": factor,
            "annualization_basis": prof["annualization_basis"],
        })
    else:
        result.update({
            "value": round(sd, 8),
            "value_pct": _pct(sd),
            "status": "ok",
            "reason": None,
            "annualized": False,
            "annualization_blocked_reason": (
                prof["blocked_reason"]
                + "；只输出未年化日波动，不乘任何年化因子"),
        })
    return result


def _downside_volatility(series: NavSeries, *, field_name: str) -> dict:
    rets, _ = _daily_returns(series, field_name=field_name)
    if len(rets) < 30:
        return _na(f"有效收益点数 {len(rets)} 不足 30")
    downs = [r for _, r, _ in rets if r < 0]
    if not downs:
        return _na("区间内无负收益样本，下行波动率无定义",
                   status="not_applicable")
    mean_d = sum(downs) / len(downs)
    var = sum((x - mean_d) ** 2 for x in downs) / max(len(downs) - 1, 1)
    dv = math.sqrt(var)
    prof = _annualization_profile(series, rets)
    out = {"sample_size": len(downs),
           "daily_downside_vol": round(dv, 8)}
    if prof["can_annualize"]:
        factor = prof["annualization_factor"]
        out.update({"value": round(dv * math.sqrt(factor), 6),
                    "value_pct": _pct(dv * math.sqrt(factor)),
                    "status": "ok", "reason": None, "annualized": True,
                    "annualization_factor": factor,
                    "annualization_basis": prof["annualization_basis"]})
    else:
        out.update({"value": round(dv, 8), "value_pct": _pct(dv),
                    "status": "ok", "reason": None, "annualized": False,
                    "annualization_blocked_reason": (
                        prof["blocked_reason"] + "；不年化")})
    return out


# ---------------------------------------------------------------- 最大回撤
def _max_drawdown(series: NavSeries, *, field_name: str) -> dict:
    pts = [(p.d, getattr(p, field_name)) for p in series.points]
    pts = [(d, v) for d, v in pts if v is not None and v > 0]
    if len(pts) < 2:
        return _na("有效净值点不足 2 条")

    peak = pts[0][1]
    peak_date = pts[0][0]
    worst = 0.0
    worst_info = None
    for d, v in pts[1:]:
        if v > peak:
            peak, peak_date = v, d
            continue
        dd = 1 - v / peak
        if dd > worst:
            worst = dd
            worst_info = {"peak_value": peak, "peak_date": peak_date.isoformat(),
                          "trough_value": v, "trough_date": d.isoformat()}

    # 修复时间：从谷底恢复到前高
    recovery = _na("无回撤")
    if worst_info:
        trough_d = datetime.strptime(worst_info["trough_date"], "%Y-%m-%d").date()
        peak_v = worst_info["peak_value"]
        recovered_at = None
        for d, v in pts:
            if d > trough_d and v >= peak_v:
                recovered_at = d
                break
        if recovered_at is None:
            recovery = {"value": (max(pts[-1][0], trough_d) - trough_d).days,
                        "status": "ongoing",
                        "reason": "尚未恢复至前高，标记 ongoing，不能当作已修复",
                        "trough_date": trough_d.isoformat(),
                        "days_elapsed": (pts[-1][0] - trough_d).days}
        else:
            recovery = _ok((recovered_at - trough_d).days,
                           unit="自然日", trough_date=trough_d.isoformat(),
                           recovered_date=recovered_at.isoformat(),
                           status="ok")

    gaps_in_range = series.quality.gap_count_over_threshold
    return _ok(round(worst, 6), value_pct=_pct(worst),
               detail=worst_info, recovery=recovery,
               gap_count_over_threshold=gaps_in_range,
               caveat=("净值连续性 cannot_verify；若区间存在缺口，"
                       "最大回撤可能被低估") if gaps_in_range else
                      "净值连续性 cannot_verify，回撤为可观测区间内的保守估计")


# ---------------------------------------------------------------- 风险调整指标
def _risk_adjusted(series: NavSeries, *, field_name: str) -> dict:
    """Sharpe / Sortino / Calmar。

    无风险利率本项目**没有可靠数据源**，因此：
    - 不输出常规 sharpe；
    - 输出 zero_hurdle_sharpe 并明确命名与含义。
    """
    vol = _volatility(series, field_name=field_name)
    ann = _annualized(series, field_name=field_name)
    mdd = _max_drawdown(series, field_name=field_name)

    out = {
        "sharpe": _na("无风险利率无可靠数据源，不输出常规 Sharpe",
                      status="not_available",
                      note="避免把 0 冒充真实无风险利率"),
        "zero_hurdle_sharpe": _na("暂不可算"),
        "sortino": _na("无风险利率缺失，不输出常规 Sortino",
                       status="not_available"),
        "calmar": _na("暂不可算"),
    }

    # zero_hurdle_sharpe：分子用年化收益，分母用年化波动（若可年化）
    if vol.get("annualized") and ann.get("status") == "ok" and vol["value"]:
        z = ann["value"] / vol["value"]
        out["zero_hurdle_sharpe"] = {
            "value": round(z, 6), "status": "ok", "reason": None,
            "definition": "(年化收益 - 0) / 年化波动率",
            "warning": ("这是**零门槛** Sharpe，把无风险利率当作 0 计算；"
                        "**不是**常规无风险利率口径的 Sharpe，"
                        "不可与外部报告的 Sharpe 直接比较"),
        }
    else:
        reasons = []
        if not vol.get("annualized"):
            reasons.append("波动率无法年化")
        if ann.get("status") != "ok":
            reasons.append("年化收益不可算")
        out["zero_hurdle_sharpe"] = _na("；".join(reasons) or "数据不足",
                                        status="insufficient_data")

    # Calmar = 年化收益 / 最大回撤
    if ann.get("status") == "ok" and mdd.get("status") == "ok" and mdd["value"]:
        out["calmar"] = _ok(round(ann["value"] / mdd["value"], 6),
                            definition="年化收益 / 最大回撤",
                            caveat="最大回撤与年化收益口径依赖净值连续性")
    else:
        reasons = []
        if ann.get("status") != "ok":
            reasons.append("年化收益不可算")
        if mdd.get("status") != "ok" or not mdd.get("value"):
            reasons.append("最大回撤为 0 或不可算")
        out["calmar"] = _na("；".join(reasons) or "数据不足")

    return out


# ---------------------------------------------------------------- 滚动稳定性
def _rolling_stability(series: NavSeries, *, field_name: str,
                       window_days: int = 90) -> dict:
    """滚动 window_days 自然日窗口的正收益比例。"""
    pts = [(p.d, getattr(p, field_name)) for p in series.points]
    pts = [(d, v) for d, v in pts if v is not None and v > 0]
    if len(pts) < 10:
        return _na("有效净值点不足 10 条")

    index = {d: v for d, v in pts}
    wins = 0
    total = 0
    for i, (d, v) in enumerate(pts):
        target = d - timedelta(days=window_days)
        if target in index:
            total += 1
            if v / index[target] - 1 > 0:
                wins += 1
    if total < 5:
        return _na(f"可观测滚动窗口仅 {total} 个，不足 5 个")
    ratio = wins / total
    return _ok(round(ratio, 4), value_pct=_pct(ratio),
               window_days=window_days, samples=total,
               note="窗口端点必须精确命中净值，不向前后取近似值")


# ---------------------------------------------------------------- 主入口（净值型）
def compute_nav_indicators(series: NavSeries, *,
                           field_name: str = "acc_nav") -> dict:
    """净值型基金指标。field_name 默认 acc_nav（含分红再投资代理）。"""
    q = series.quality
    base = {
        "code": series.code,
        "nav_kind": series.nav_kind,
        "return_field": field_name,
        "return_field_note": (
            "acc_nav 是累计净值，含分红再投资，作为总回报代理；"
            "unit_nav 是不含分红的单位净值，**不能**直接当总回报"
            if field_name == "acc_nav" else
            "unit_nav 不含分红，仅作单位净值观察，不是总回报"),
        "sample_size": len(series.points),
        "date_min": q.date_min,
        "date_max": q.date_max,
        "continuity_verification": q.continuity_verification,
        "dividend_repair_used": False,
        "dividend_repair_note": (
            "分红记录不完整（3B-4.4 已核验），**未**用分红数据修复历史收益；"
            "收益全部基于 acc_nav 原值"),
    }

    rets = {}
    for key, (label, days) in WINDOWS.items():
        r = _window_return(series, days, field_name=field_name)
        r["label"] = label
        rets[key] = r
    rets["ret_since_inception"] = _window_return(
        series, (series.points[-1].d - series.points[0].d).days,
        field_name=field_name) if series.points else _na("no_nav_data")
    rets["ret_since_inception"]["label"] = "成立以来收益"

    base["returns"] = rets
    base["annualized_return"] = _annualized(series, field_name=field_name)
    base["risk"] = {
        "max_drawdown": _max_drawdown(series, field_name=field_name),
        "volatility": _volatility(series, field_name=field_name),
        "downside_volatility": _downside_volatility(series, field_name=field_name),
    }
    base["risk_adjusted"] = _risk_adjusted(series, field_name=field_name)
    base["stability"] = {
        "rolling_positive_ratio_90d": _rolling_stability(
            series, field_name=field_name, window_days=90),
    }
    base["not_computed"] = {
        "excess_return": "无基准收益序列，禁止计算超额收益",
        "style_stability": "无持仓数据，无法计算风格稳定性",
        "information_ratio": "无基准序列",
        "beta": "无基准序列",
    }
    return base


# ---------------------------------------------------------------- 货币基金
def _money_stats(money: dict) -> dict:
    """货币基金实际统计：累计万份收益、7日年化区间统计。

    注意口径：
    - 每万份收益是「元/万份/日」的金额，累加得到区间累计金额，**不是**收益率；
    - 折算成收益率需要除以 10000，这里同时给出折算值并标注。
    """
    from app.database.db import get_connection

    with get_connection() as conn:
        rows = [dict(r) for r in conn.execute(
            """SELECT nav_date, per_10k_yield, seven_day_annual
               FROM fund_nav_daily
               WHERE share_class_id=? AND nav_kind='money_yield'
               ORDER BY nav_date""",
            (money["share_class_id"],)).fetchall()]
    if not rows:
        return {"status": "insufficient_data", "reason": "无货币收益记录"}

    vals = [(r["nav_date"], r["per_10k_yield"]) for r in rows
            if r["per_10k_yield"] is not None]
    sevens = [(r["nav_date"], r["seven_day_annual"]) for r in rows
              if r["seven_day_annual"] is not None]

    out = {"rows": len(rows),
           "date_min": rows[0]["nav_date"], "date_max": rows[-1]["nav_date"]}

    if vals:
        total = sum(v for _, v in vals)
        out["per_10k_yield"] = {
            "status": "ok",
            "sample_days": len(vals),
            "cumulative_per_10k": round(total, 6),
            "cumulative_as_return": round(total / 10000.0, 8),
            "cumulative_as_return_pct": round(total / 10000.0 * 100, 6),
            "mean_per_day": round(total / len(vals), 8),
            "min": round(min(v for _, v in vals), 6),
            "max": round(max(v for _, v in vals), 6),
            "unit": "元/万份/日",
            "definition": ("累计万份收益 = Σ 每日每万份收益；"
                           "累计收益率 ≈ 累计金额 / 10000，"
                           "这是**近似折算**，未考虑复利与再投资"),
            "warning": "这是金额累加，不是净值、不是官方累计收益",
        }

    if sevens:
        sv = [v for _, v in sevens]
        out["seven_day_annual"] = {
            "status": "ok",
            "sample_days": len(sv),
            "latest": round(sv[-1], 6),
            "latest_date": sevens[-1][0],
            "mean": round(sum(sv) / len(sv), 6),
            "min": round(min(sv), 6),
            "max": round(max(sv), 6),
            "unit": "%",
            "warning": ("7日年化是滚动换算的**参考值**，"
                        "不是已实现收益，也不是承诺收益"),
        }

    # 近 1 年 / 近 3 年的万份收益累计（按自然日回溯）
    from datetime import datetime, timedelta
    last_d = datetime.strptime(rows[-1]["nav_date"], "%Y-%m-%d").date()
    for label, days in (("近1年", 365), ("近3年", 1095)):
        cutoff = (last_d - timedelta(days=days)).isoformat()
        seg = [v for d, v in vals if d >= cutoff]
        out[f"cumulative_per_10k_{label}"] = (
            {"status": "ok", "sample_days": len(seg),
             "value": round(sum(seg), 6),
             "as_return_pct": round(sum(seg) / 10000.0 * 100, 6)}
            if seg else {"status": "insufficient_data", "reason": f"{label}无数据"})

    out["not_applicable"] = {
        "max_drawdown": "货币基金用每万份收益口径，不计算净值型最大回撤",
        "volatility": "同上，不计算净值型波动率",
        "sharpe": "同上",
        "unit_nav_returns": "不使用单位净值",
    }
    return out


def compute_money_indicators(money: dict) -> dict:
    """货币基金独立口径：每万份收益 / 7日年化，绝不当净值用。"""
    if not money or not money.get("rows"):
        return {"code": money.get("code") if money else None,
                "status": "insufficient_data",
                "reason": "无货币收益数据"}

    stats = _money_stats(money)

    return {"stats": stats,
        "code": money["code"],
        "nav_kind": "money_yield",
        "rows": money["rows"],
        "date_min": money["date_min"],
        "date_max": money["date_max"],
        "continuity_verification": money["continuity_verification"],
        "uses_unit_nav": False,
        "nav_based_indicators": {
            "status": "not_applicable",
            "reason": ("货币基金不使用 unit_nav / acc_nav，"
                       "**不得**计算净值型收益、回撤、波动率"),
        },
        "per_10k_yield": {
            "label": "每万份收益（元/万份）",
            "unit": "元/万份/日",
            "null_count": money["null_per_10k"],
            "note": "这是每日每万份收益金额，**不是收益率、不是净值**",
            "usable_for_net_value_comparison": False,
        },
        "seven_day_annual": {
            "label": "7日年化收益率",
            "unit": "%",
            "null_count": money["null_seven_day"],
            "note": "年化换算后的**参考值**，不是已实现收益",
            "usable_for_net_value_comparison": False,
        },
        "max_gap_days": money["max_gap_days"],
        "gap_count_over_threshold": money["gap_count_over_threshold"],
        "comparison_rule": "只能与其他货币基金比较，禁止与净值型基金同榜",
    }
