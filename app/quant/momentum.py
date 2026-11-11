"""动量指标：Wilder RSI 与标准 MACD。"""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from app.quant.trend import ema_with_reset


def _wilder_average(values: pd.Series, period: int) -> pd.Series:
    """Wilder 平滑：前 period 个有效值取 SMA，之后按 (n-1)/n 递推。

    遇到无效值或日期缺口时重置，不用前值填补。
    """
    period = int(period)
    if period < 1:
        raise ValueError("Wilder 周期必须为正整数")
    array = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    out = np.full(array.shape, np.nan, dtype=float)
    seed: list[float] = []
    average: float | None = None
    for index, value in enumerate(array):
        if not np.isfinite(value):
            seed = []
            average = None
            continue
        if average is None:
            seed.append(float(value))
            if len(seed) < period:
                continue
            average = float(np.mean(seed))
            seed = []
            out[index] = average
        else:
            average = ((period - 1) * average + float(value)) / period
            out[index] = average
    return pd.Series(out, index=values.index)


def compute_rsi(frame: pd.DataFrame, periods: Iterable[int] = (6, 12, 24)) -> pd.DataFrame:
    close = pd.to_numeric(frame.get("adjusted_close"), errors="coerce")
    close = close.where(close > 0)
    delta = close.diff()
    gains = delta.clip(lower=0)
    losses = (-delta).clip(lower=0)
    out = pd.DataFrame(index=frame.index)
    for period in periods:
        period = int(period)
        avg_gain = _wilder_average(gains, period)
        avg_loss = _wilder_average(losses, period)
        rsi = 100 - 100 / (1 + avg_gain / avg_loss)
        # 平均跌幅为 0：有涨幅时 RSI=100，无涨无跌时 RSI=50。
        zero_loss = avg_loss.eq(0)
        rsi = rsi.where(~zero_loss, np.where(avg_gain > 0, 100.0, 50.0))
        rsi = rsi.where(avg_gain.notna() & avg_loss.notna())
        out[f"rsi{period}"] = rsi
    return out


def compute_macd(
    frame: pd.DataFrame,
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    close = pd.to_numeric(frame.get("adjusted_close"), errors="coerce")
    close = close.where(close > 0)
    ema_fast = ema_with_reset(close, int(fast), min_periods=int(fast))
    ema_slow = ema_with_reset(close, int(slow), min_periods=int(slow))
    dif = ema_fast - ema_slow
    # DIF 在 EMA26 就绪前及断点处为 NaN；DEA 同样重置并重新积累 signal 个有效值。
    dea = ema_with_reset(dif, int(signal), min_periods=int(signal))
    hist = 2 * (dif - dea)
    return pd.DataFrame(
        {
            "macd_dif": dif,
            "macd_dea": dea,
            "macd_hist": hist,
        },
        index=frame.index,
    )
