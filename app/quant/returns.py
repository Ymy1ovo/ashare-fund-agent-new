"""收益率指标。

统一使用前复权收盘价 adjusted_close；n 日收益要求窗口内 n+1 个交易日价格全部有效，
否则返回 NaN，不用缺失值或前值填充。
"""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd


def compute_returns(
    frame: pd.DataFrame,
    windows: Iterable[int] = (1, 5, 10, 20, 60, 120, 250),
    *,
    annualization: int = 252,
) -> pd.DataFrame:
    close = pd.to_numeric(frame.get("adjusted_close"), errors="coerce")
    close = close.where(close > 0)
    out = pd.DataFrame(index=frame.index)

    for window in windows:
        window = int(window)
        if window < 1:
            raise ValueError("收益率窗口必须为正整数")
        ratio = close / close.shift(window) - 1
        complete = close.rolling(window + 1, min_periods=window + 1).count() == window + 1
        out[f"return_{window}d"] = ratio.where(complete)

    # 扩展 CAGR：时间分母使用交易日索引的实际跨度，而不是有效价格个数。
    # 例如 100、缺失、110、120 的指数是 252/3，不是 252/2。
    positions = np.arange(len(close), dtype=float)
    valid = close.notna() & (close > 0)
    valid_positions = np.flatnonzero(valid.to_numpy())
    if len(valid_positions) == 0:
        out["cagr"] = float("nan")
    else:
        first_pos = int(valid_positions[0])
        first_close = float(close.iloc[first_pos])
        elapsed = positions - first_pos
        safe_elapsed = np.where(elapsed > 0, elapsed, np.nan)
        cagr = (close / first_close) ** (annualization / safe_elapsed) - 1
        out["cagr"] = cagr.where(valid & (elapsed > 0))
    return out
