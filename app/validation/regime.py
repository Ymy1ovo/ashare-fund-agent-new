"""市场环境分类。

只用 T 日及之前的数据判断 T 日状态，不使用未来信息。
参考标的为沪深300ETF（数据库无独立指数表，报告中明确标注为 ETF 代理）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from app.validation.config import (
    MIN_REGIME_SAMPLES,
    REGIME_BEAR_THRESHOLD,
    REGIME_BULL_THRESHOLD,
    REGIME_MA_WINDOW,
)

REGIME_BULL = "bull"
REGIME_BEAR = "bear"
REGIME_RANGE = "range"
REGIME_UNCLASSIFIED = "unclassified"


class RegimeError(RuntimeError):
    """市场环境分类无法进行。"""


@dataclass
class RegimeSeries:
    """一只代理标的的环境序列。"""

    code: str
    ma_window: int
    labels: dict[date, str] = field(default_factory=dict)
    deviations: dict[date, float | None] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def label_at(self, day: date) -> str:
        return self.labels.get(day, REGIME_UNCLASSIFIED)

    def summary(self) -> dict:
        counts: dict[str, int] = {}
        for label in self.labels.values():
            counts[label] = counts.get(label, 0) + 1
        return {
            "code": self.code,
            "ma_window": self.ma_window,
            "counts": counts,
            "classified_days": sum(
                count for label, count in counts.items() if label != REGIME_UNCLASSIFIED
            ),
            "notes": self.notes,
        }


def classify_deviation(deviation: float | None) -> str:
    """按相对 MA 的偏离度分类。"""
    if deviation is None or pd.isna(deviation):
        return REGIME_UNCLASSIFIED
    if deviation > REGIME_BULL_THRESHOLD:
        return REGIME_BULL
    if deviation < REGIME_BEAR_THRESHOLD:
        return REGIME_BEAR
    return REGIME_RANGE


def build_regime_series(
    close: pd.Series,
    *,
    code: str,
    ma_window: int = REGIME_MA_WINDOW,
) -> RegimeSeries:
    """构造市场环境序列。

    MA 使用 rolling(window).mean()，min_periods=window：
    样本不足时不产生 MA，因此该日标记 unclassified，不用部分数据凑出一个分类。
    """
    if close is None or close.empty:
        raise RegimeError(f"{code} 没有可用收盘价，无法分类市场环境")
    series = pd.to_numeric(close, errors="coerce").sort_index()
    rolling = series.rolling(window=ma_window, min_periods=ma_window).mean()
    deviation = series / rolling - 1

    result = RegimeSeries(code=code, ma_window=ma_window)
    unclassified = 0
    for day, value in deviation.items():
        if pd.isna(value):
            result.labels[day] = REGIME_UNCLASSIFIED
            result.deviations[day] = None
            unclassified += 1
            continue
        number = float(value)
        result.deviations[day] = number
        result.labels[day] = classify_deviation(number)

    if unclassified:
        result.notes.append(
            f"{code} 有 {unclassified} 个交易日因 MA{ma_window} 样本不足标记 unclassified，"
            f"未强行归类"
        )
    if not any(label != REGIME_UNCLASSIFIED for label in result.labels.values()):
        raise RegimeError(f"{code} 全部日期样本不足，无法形成任何市场环境分类")
    return result


def regime_stats(
    daily_returns: dict[date, float | None],
    labels: dict[date, str],
    *,
    min_samples: int = MIN_REGIME_SAMPLES,
) -> dict[str, dict]:
    """按市场环境统计策略日收益表现。

    只统计有可用日收益的日期；样本不足的环境标记 insufficient_sample。
    """
    buckets: dict[str, list[float]] = {}
    for day, value in daily_returns.items():
        if value is None or pd.isna(value):
            continue
        bucket = labels.get(day, REGIME_UNCLASSIFIED)
        buckets.setdefault(bucket, []).append(float(value))

    payload: dict[str, dict] = {}
    for label in (REGIME_BULL, REGIME_BEAR, REGIME_RANGE, REGIME_UNCLASSIFIED):
        values = buckets.get(label, [])
        entry: dict = {"samples": len(values)}
        if len(values) < min_samples:
            entry["status"] = "insufficient_sample"
            entry["reason"] = f"样本 {len(values)} < {min_samples}"
            payload[label] = entry
            continue
        series = pd.Series(values)
        mean = float(series.mean())
        std = float(series.std(ddof=1)) if len(values) > 1 else float("nan")
        entry.update(
            {
                "status": "ok",
                "mean_daily_return": mean,
                "cumulative_return": float((1 + series).prod() - 1),
                "annualized_volatility": (
                    std * (252 ** 0.5) if std == std else None
                ),
                "win_rate": float((series > 0).mean()),
            }
        )
        payload[label] = entry
    return payload
