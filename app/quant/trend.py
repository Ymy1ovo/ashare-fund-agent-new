"""趋势类指标：移动平均与指数移动平均。"""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd


def ema_with_reset(series: pd.Series, span: int, min_periods: int | None = None) -> pd.Series:
    """连续区间内与 pandas ewm(adjust=False) 等价，遇到无效/缺失值重置。

    缺失日输出 NaN；重新积累满 min_periods 个连续有效观察后才再次输出。
    这样不会把缺失日当作价格不变，也不会沿用断点前的平滑状态。
    """
    span = int(span)
    min_periods = int(min_periods if min_periods is not None else span)
    if span < 1 or min_periods < 1:
        raise ValueError("EMA span/min_periods 必须为正整数")
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    out = np.full(values.shape, np.nan, dtype=float)
    alpha = 2.0 / (span + 1.0)
    state: float | None = None
    count = 0
    for index, value in enumerate(values):
        if not np.isfinite(value):
            state = None
            count = 0
            continue
        if state is None:
            state = float(value)
            count = 1
        else:
            state = alpha * float(value) + (1.0 - alpha) * state
            count += 1
        if count >= min_periods:
            out[index] = state
    return pd.Series(out, index=series.index)


def compute_trend(
    frame: pd.DataFrame,
    ma_windows: Iterable[int] = (5, 10, 20, 30, 60, 120, 250),
    ema_spans: Iterable[int] = (12, 26),
) -> pd.DataFrame:
    close = pd.to_numeric(frame.get("adjusted_close"), errors="coerce")
    close = close.where(close > 0)
    out = pd.DataFrame(index=frame.index)
    for window in ma_windows:
        window = int(window)
        if window < 1:
            raise ValueError("均线窗口必须为正整数")
        out[f"ma{window}"] = close.rolling(window, min_periods=window).mean()
    for span in ema_spans:
        span = int(span)
        if span < 1:
            raise ValueError("EMA 周期必须为正整数")
        # 历史不足或遇到缺失断点时重新积累，不用旧状态跨缺口。
        out[f"ema{span}"] = ema_with_reset(close, span, min_periods=span)
    return out
