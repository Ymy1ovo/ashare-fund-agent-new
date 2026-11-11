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
    warmup_days: int = 0
    first_day: date | None = None
    last_day: date | None = None

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
            "unclassified_days": counts.get(REGIME_UNCLASSIFIED, 0),
            "output_days": len(self.labels),
            "warmup_days": self.warmup_days,
            "first_day": self.first_day.isoformat() if self.first_day else None,
            "last_day": self.last_day.isoformat() if self.last_day else None,
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
    output_start: date | None = None,
) -> RegimeSeries:
    """构造市场环境序列。

    参数
    ----
    close: 代理标的收盘价，索引为交易日；可包含 OOS 之前的预热数据。
    output_start: 若给出，只输出该日期及之后的分类结果。
        预热数据仅参与 MA 计算，不进入 labels，保证 OOS 之前的日期不会
        因为使用 OOS 数据而被分类，也不会污染 OOS 绩效统计。

    MA 使用 rolling(window).mean()，min_periods=window：
    样本不足时不产生 MA，该日标记 unclassified，不用部分数据凑分类。
    """
    if close is None or close.empty:
        raise RegimeError(f"{code} 没有可用收盘价，无法分类市场环境")
    series = pd.to_numeric(close, errors="coerce").sort_index()
    # 统一索引为 date，避免 Timestamp 与 date 比较报错
    if isinstance(series.index, pd.DatetimeIndex):
        series.index = series.index.date
    rolling = series.rolling(window=ma_window, min_periods=ma_window).mean()
    deviation = series / rolling - 1

    result = RegimeSeries(code=code, ma_window=ma_window)
    unclassified = 0
    warmup_days = 0
    for day, value in deviation.items():
        day_value = day.date() if hasattr(day, "date") else day
        if output_start is not None and day_value < output_start:
            warmup_days += 1
            continue
        if pd.isna(value):
            result.labels[day_value] = REGIME_UNCLASSIFIED
            result.deviations[day_value] = None
            unclassified += 1
            continue
        number = float(value)
        result.deviations[day_value] = number
        result.labels[day_value] = classify_deviation(number)

    result.warmup_days = warmup_days
    if result.labels:
        ordered_days = sorted(result.labels)
        result.first_day = ordered_days[0]
        result.last_day = ordered_days[-1]
    if warmup_days:
        result.notes.append(
            f"{code} 使用 {warmup_days} 个预热交易日计算 MA{ma_window}，"
            f"预热数据不计入输出区间"
        )
    if unclassified:
        result.notes.append(
            f"{code} 有 {unclassified} 个交易日因 MA{ma_window} 样本不足标记 unclassified，"
            f"未强行归类"
        )
    if not any(label != REGIME_UNCLASSIFIED for label in result.labels.values()):
        raise RegimeError(f"{code} 全部日期样本不足，无法形成任何市场环境分类")
    return result


def regime_stats(
    daily_returns: "pd.Series | dict[date, float | None]",
    labels: dict[date, str],
    *,
    min_samples: int = MIN_REGIME_SAMPLES,
) -> dict[str, dict]:
    """按市场环境统计策略日收益表现。

    输入必须是「原始交易日索引上的日收益序列」，缺失日保留 NaN，
    不得在调用前 dropna，否则会把跨缺失日收益当成单日收益。

    每个环境同时记录：
    - total_days：该环境下 OOS 交易日总数
    - valid_days：有有效单日收益的天数
    - missing_days：因缺失行情没有有效日收益的天数
    - status：ok / insufficient_sample
    """
    if isinstance(daily_returns, pd.Series):
        series = pd.to_numeric(daily_returns, errors="coerce")
        if not isinstance(series.index, pd.DatetimeIndex):
            series.index = pd.DatetimeIndex([pd.Timestamp(day) for day in series.index])
        by_label: dict[str, list[tuple]] = {}
        for stamp, value in series.items():
            day = stamp.date() if hasattr(stamp, "date") else stamp
            by_label.setdefault(labels.get(day, REGIME_UNCLASSIFIED), []).append((day, value))
    else:
        by_label = {}
        for day, value in daily_returns.items():
            by_label.setdefault(labels.get(day, REGIME_UNCLASSIFIED), []).append((day, value))

    payload: dict[str, dict] = {}
    for label in (REGIME_BULL, REGIME_BEAR, REGIME_RANGE, REGIME_UNCLASSIFIED):
        entries = by_label.get(label, [])
        values = [
            float(value) for _, value in entries
            if value is not None and not pd.isna(value)
        ]
        entry: dict = {
            "total_days": len(entries),
            "valid_days": len(values),
            "missing_days": len(entries) - len(values),
            "samples": len(values),
        }
        if len(values) < min_samples:
            entry["status"] = "insufficient_sample"
            entry["reason"] = f"有效日收益 {len(values)} < {min_samples}"
            payload[label] = entry
            continue
        series_values = pd.Series(values)
        mean = float(series_values.mean())
        std = float(series_values.std(ddof=1)) if len(values) > 1 else float("nan")
        entry.update(
            {
                "status": "ok",
                "mean_daily_return": mean,
                "cumulative_return": float((1 + series_values).prod() - 1),
                "annualized_volatility": (
                    std * (252 ** 0.5) if std == std else None
                ),
                "win_rate": float((series_values > 0).mean()),
                "note": (
                    "累计收益按有效日收益复合，缺失日不计入；"
                    "不代表连续交易日收益"
                ),
            }
        )
        payload[label] = entry
    return payload
