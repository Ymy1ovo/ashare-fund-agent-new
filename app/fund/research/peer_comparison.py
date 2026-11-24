"""阶段3B-6.0.4 场外基金同类比较与超额收益验证边界。

**本模块只做研究性描述与稳健性分析，不产生排名、不建议买卖。**

三条铁律：

1. **公平窗口**：成立时间不同的基金不能直接比「成立以来收益」。
   必须用共同历史区间，或按自然日滚动窗口，且端点必须精确命中净值。
2. **基准阻断**：指数收益口径为 ``unknown`` 时，
   ``excess_return_status`` 必须是 ``not_available``，
   **不得**用同类相对表现冒充超额收益，也不得把同类排名说成 Alpha。
3. **缺口不跨越**：沿用 3B-5.x 的 ``MAX_GAP_DAYS_FOR_RETURN``，
   超过阈值的缺口内不计算相邻收益，不填充、不插值、不当 0 收益。
"""
from __future__ import annotations

from datetime import date, timedelta

from app.fund.research.data_access import (
    MAX_GAP_DAYS_FOR_RETURN, NavSeries, load_nav_series,
)
from app.fund.research.quality import LEVEL_A, LEVEL_B, LEVEL_C, LEVEL_D

# ---------------------------------------------------------------- 状态常量
EXCESS_NOT_AVAILABLE = "not_available"
EXCESS_INSUFFICIENT = "insufficient_data"

PEER_COMPARABLE = "comparable"
PEER_DESCRIPTIVE_ONLY = "descriptive_only"
PEER_EXCLUDED = "excluded"

# 运行窗口（自然日）
WINDOW_1Y = 365
WINDOW_3Y = 1095
WINDOW_5Y = 1826

# 滚动窗口最小可接受样本（个独立滚动窗口）
MIN_ROLLING_WINDOWS = 5


# ---------------------------------------------------------------- 窗口工具
def series_span(series: NavSeries, *, field_name: str = "acc_nav") -> dict:
    """序列的有效跨度：只统计该字段非空且为正的点。"""
    pts = [(p.d, getattr(p, field_name)) for p in series.points]
    pts = [(d, v) for d, v in pts if v is not None and v > 0]
    if not pts:
        return {"date_min": None, "date_max": None, "valid_points": 0,
                "span_days": 0}
    dmin, dmax = pts[0][0], pts[-1][0]
    return {"date_min": dmin.isoformat(), "date_max": dmax.isoformat(),
            "valid_points": len(pts), "span_days": (dmax - dmin).days}


def common_window(spans: list[dict]) -> dict:
    """多只基金的**共同历史区间**。

    只保留所有基金都有有效数据的交集；任一基金跨度过短则整体不可比。
    """
    valid = [s for s in spans if s.get("date_min") and s.get("date_max")]
    if len(valid) < 2:
        return {"status": EXCESS_INSUFFICIENT,
                "reason": f"有效跨度不足 2 只（实际 {len(valid)}）",
                "date_min": None, "date_max": None, "fund_count": len(valid)}
    dmin = max(s["date_min"] for s in valid)
    dmax = min(s["date_max"] for s in valid)
    if dmin >= dmax:
        return {"status": EXCESS_INSUFFICIENT,
                "reason": "交集为空：没有共同的历史区间",
                "date_min": None, "date_max": None, "fund_count": len(valid)}
    days = (date.fromisoformat(dmax) - date.fromisoformat(dmin)).days
    return {"status": "ok", "reason": None, "date_min": dmin, "date_max": dmax,
            "span_days": days, "fund_count": len(valid),
            "dropped_funds": [s for s in spans if s not in valid]}


def value_on(series: NavSeries, target_iso: str,
             *, field_name: str = "acc_nav") -> float | None:
    """取指定日期的净值，**必须精确命中**，不向前后找。"""
    t = date.fromisoformat(target_iso)
    for p in series.points:
        if p.d == t:
            v = getattr(p, field_name)
            return v if (v is not None and v > 0) else None
    return None


def has_gap_between(series: NavSeries, start_iso: str, end_iso: str) -> bool:
    """区间内是否有超阈值缺口（跨越即不可算）。"""
    for g in series.quality.gaps:
        if g["to"] < start_iso or g["from"] > end_iso:
            continue
        return True
    return False


# ---------------------------------------------------------------- 区间收益
def window_return(series: NavSeries, start_iso: str, end_iso: str,
                  *, field_name: str = "acc_nav") -> dict:
    """区间累计收益。缺口跨越、端点缺失一律 insufficient_data。"""
    if has_gap_between(series, start_iso, end_iso):
        gaps = [g for g in series.quality.gaps
                if not (g["to"] < start_iso or g["from"] > end_iso)]
        return {"value": None, "status": "insufficient_data",
                "reason": f"区间内存在 {len(gaps)} 处超阈值缺口，不跨越计算",
                "start_date": start_iso, "end_date": end_iso,
                "gap_count": len(gaps)}
    v0 = value_on(series, start_iso, field_name=field_name)
    v1 = value_on(series, end_iso, field_name=field_name)
    if v0 is None or v1 is None:
        return {"value": None, "status": "insufficient_data",
                "reason": ("起点净值缺失" if v0 is None else "终点净值缺失"),
                "start_date": start_iso, "end_date": end_iso}
    days = (date.fromisoformat(end_iso) - date.fromisoformat(start_iso)).days
    return {"value": round(v1 / v0 - 1, 8), "status": "ok", "reason": None,
            "start_date": start_iso, "end_date": end_iso,
            "span_days": days, "field": field_name}


def annualized_from_return(total_return: float | None, days: int) -> dict:
    """按自然日年化。不足 1 年不年化（返回 None，避免外推）。"""
    if total_return is None or days <= 0:
        return {"value": None, "status": "insufficient_data",
                "reason": "收益或区间无效"}
    if days < 365:
        return {"value": None, "status": "insufficient_data",
                "reason": f"区间仅 {days} 天，不足 1 年不年化",
                "basis": "natural_days"}
    years = days / 365.0
    try:
        ann = (1 + total_return) ** (1 / years) - 1
    except (ValueError, ZeroDivisionError, OverflowError):
        return {"value": None, "status": "insufficient_data",
                "reason": "年化计算失败（收益异常）", "basis": "natural_days"}
    return {"value": round(ann, 8), "status": "ok", "reason": None,
            "basis": "natural_days", "years": round(years, 4)}


# ---------------------------------------------------------------- 滚动窗口
def rolling_windows(series: NavSeries, *, window_days: int,
                    field_name: str = "acc_nav",
                    step_days: int = 30) -> dict:
    """滚动窗口收益序列。

    每 ``step_days`` 自然日起一个窗口，端点必须精确命中，缺口跨越跳过。
    """
    pts = [(p.d, getattr(p, field_name)) for p in series.points]
    pts = [(d, v) for d, v in pts if v is not None and v > 0]
    if len(pts) < 2:
        return {"status": "insufficient_data", "reason": "有效净值不足 2 条",
                "windows": [], "valid_count": 0, "skipped_count": 0}

    index = {d: v for d, v in pts}
    first, last = pts[0][0], pts[-1][0]
    results = []
    skipped = 0
    cur = first
    while cur + timedelta(days=window_days) <= last:
        end = cur + timedelta(days=window_days)
        if end not in index or cur not in index:
            skipped += 1
        elif has_gap_between(series, cur.isoformat(), end.isoformat()):
            skipped += 1
        else:
            results.append({
                "start_date": cur.isoformat(), "end_date": end.isoformat(),
                "return": round(index[end] / index[cur] - 1, 8)})
        cur += timedelta(days=step_days)

    if len(results) < MIN_ROLLING_WINDOWS:
        return {"status": "insufficient_data",
                "reason": (f"有效滚动窗口仅 {len(results)} 个，"
                           f"不足 {MIN_ROLLING_WINDOWS} 个"
                           f"（跳过 {skipped} 个）"),
                "windows": results, "valid_count": len(results),
                "skipped_count": skipped}

    rets = sorted(r["return"] for r in results)
    n = len(rets)
    positive = sum(1 for r in rets if r > 0)
    median = (rets[n // 2] if n % 2 else (rets[n // 2 - 1] + rets[n // 2]) / 2)
    return {
        "status": "ok", "reason": None,
        "window_days": window_days, "step_days": step_days,
        "windows": results, "valid_count": n, "skipped_count": skipped,
        "positive_ratio": round(positive / n, 6),
        "median_return": round(median, 8),
        "min_return": round(rets[0], 8),
        "max_return": round(rets[-1], 8),
        "spread": round(rets[-1] - rets[0], 8),
    }


def best_window_dependency(rolling: dict) -> dict:
    """最佳单一窗口依赖度。

    若最佳窗口收益显著高于中位数，说明整体优势可能依赖单个短期窗口。
    """
    if rolling.get("status") != "ok":
        return {"status": "insufficient_data",
                "reason": rolling.get("reason")}
    best = max(rolling["windows"], key=lambda r: r["return"])
    med = rolling["median_return"]
    excess = best["return"] - med
    # 判定阈值：最佳窗口高出中位数 2 倍区间宽度以上 → 高度依赖
    high_dependency = bool(rolling["spread"] > 0
                           and excess > rolling["spread"] * 0.5)
    return {
        "status": "ok",
        "best_window": best,
        "median_return": med,
        "excess_over_median": round(excess, 8),
        "high_dependency": high_dependency,
        "note": ("整体优势可能主要来自单一窗口，需谨慎解读"
                 if high_dependency else "窗口分布相对均匀"),
    }


def exclude_best_window(rolling: dict) -> dict:
    """剔除最佳窗口后的结果，检验结论是否稳健。"""
    if rolling.get("status") != "ok" or rolling["valid_count"] < 2:
        return {"status": "insufficient_data",
                "reason": rolling.get("reason") or "窗口不足"}
    wins = sorted(rolling["windows"], key=lambda r: r["return"])
    trimmed = wins[:-1]
    if not trimmed:
        return {"status": "insufficient_data", "reason": "剔除后无剩余窗口"}
    rets = [r["return"] for r in trimmed]
    return {
        "status": "ok",
        "remaining_count": len(trimmed),
        "median_return": round(sorted(rets)[len(rets) // 2], 8),
        "positive_ratio": round(sum(1 for r in rets if r > 0) / len(rets), 6),
        "changed_sign_from_positive_to_non_positive": (
            rolling["positive_ratio"] > 0.5
            and sum(1 for r in rets if r > 0) / len(rets) <= 0.5),
    }
