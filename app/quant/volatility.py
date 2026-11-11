"""波动率、回撤与 ATR 指标。"""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from app.quant.momentum import _wilder_average


def max_drawdown(values: pd.Series) -> float:
    """区间最大回撤；没有有效值或没有峰值时返回 NaN。"""
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return float("nan")
    peaks = clean.cummax()
    drawdowns = clean / peaks - 1
    return float(drawdowns.min())


def _rolling_max_drawdown(values: np.ndarray) -> float:
    if np.isnan(values).any():
        return float("nan")
    peaks = np.maximum.accumulate(values)
    return float(np.min(values / peaks - 1))


def rolling_max_drawdown(series: pd.Series, window: int) -> pd.Series:
    window = int(window)
    if window < 1:
        raise ValueError("回撤窗口必须为正整数")
    return series.rolling(window, min_periods=window).apply(_rolling_max_drawdown, raw=True)


def compute_volatility(
    frame: pd.DataFrame,
    *,
    vol_windows: Iterable[int] = (20, 60, 120),
    mdd_windows: Iterable[int] = (20, 60, 120),
    atr_period: int = 14,
    annualization: int = 252,
    ddof: int = 1,
) -> pd.DataFrame:
    close = pd.to_numeric(frame.get("adjusted_close"), errors="coerce")
    close = close.where(close > 0)
    daily_returns = close.pct_change(fill_method=None)
    out = pd.DataFrame(index=frame.index)
    for window in vol_windows:
        window = int(window)
        out[f"volatility_{window}d"] = (
            daily_returns.rolling(window, min_periods=window).std(ddof=ddof)
            * np.sqrt(annualization)
        )
    for window in mdd_windows:
        window = int(window)
        out[f"max_drawdown_{window}d"] = rolling_max_drawdown(close, window)
    # 扩展最大回撤：截至当日，只使用当日及之前的数据，不使用未来峰值。
    out["max_drawdown_all"] = (close / close.cummax(skipna=True) - 1).where(close.notna())

    if "adjusted_high" in frame.columns and "adjusted_low" in frame.columns:
        high = pd.to_numeric(frame["adjusted_high"], errors="coerce")
        low = pd.to_numeric(frame["adjusted_low"], errors="coerce")
        prev_close = close.shift(1)
        tr = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        out[f"atr{atr_period}"] = _wilder_average(tr, int(atr_period))
    else:
        out[f"atr{atr_period}"] = np.nan
    return out
