"""风险收益指标与区间摘要。"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from app.quant.volatility import max_drawdown, rolling_max_drawdown


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    result = numerator / denominator
    return result.where(np.isfinite(result))


def daily_return_series(frame: pd.DataFrame) -> pd.Series:
    """按交易日索引计算真实单日收益，缺失日保留 NaN。

    不在 dropna 后计算 pct_change；跨缺口的收益不会被伪装成单日收益。
    """
    close = pd.to_numeric(frame.get("adjusted_close"), errors="coerce")
    close = close.where(close > 0)
    return close.pct_change(fill_method=None)


def compute_risk(
    frame: pd.DataFrame,
    *,
    risk_window: int = 252,
    annualization: int = 252,
    risk_free_rate: float = 0.0,
) -> pd.DataFrame:
    """计算滚动风险收益指标。

    - 年化收益：risk_window 个交易日的区间年化。
    - 波动率：日收益标准差（ddof=1）× sqrt(annualization)。
    - 夏普：年化收益减无风险利率后除以年化波动率。
    - 索提诺：下行波动率 = sqrt(mean(min(日超额收益, 0)^2)) × sqrt(annualization)。
    - Calmar：年化收益 / abs(risk_window 最大回撤)。
    任一分母为 0 或非有限值时返回 NaN，不输出无穷大。
    """
    risk_window = int(risk_window)
    if risk_window < 2:
        raise ValueError("risk_window 必须 >= 2")
    close = pd.to_numeric(frame.get("adjusted_close"), errors="coerce")
    close = close.where(close > 0)
    returns = daily_return_series(frame)
    daily_rf = (1 + risk_free_rate) ** (1 / annualization) - 1
    excess = returns - daily_rf
    downside = excess.clip(upper=0)

    # 滚动年化收益需要 window 个收益区间，且价格完整。
    complete = close.rolling(risk_window + 1, min_periods=risk_window + 1).count() == risk_window + 1
    ann_return = (close / close.shift(risk_window)) ** (annualization / risk_window) - 1
    ann_return = ann_return.where(complete)
    ann_vol = returns.rolling(risk_window, min_periods=risk_window).std(ddof=1) * np.sqrt(annualization)
    downside_vol = (
        downside.pow(2).rolling(risk_window, min_periods=risk_window).mean().pow(0.5)
        * np.sqrt(annualization)
    )
    mdd = rolling_max_drawdown(close, risk_window)

    sharpe = _safe_ratio(ann_return - risk_free_rate, ann_vol)
    sortino = _safe_ratio(ann_return - risk_free_rate, downside_vol)
    calmar = _safe_ratio(ann_return, mdd.abs())
    return pd.DataFrame(
        {
            "sharpe_ratio": sharpe,
            "sortino_ratio": sortino,
            "calmar_ratio": calmar,
        },
        index=frame.index,
    )


def summarize_range(
    frame: pd.DataFrame,
    *,
    annualization: int = 252,
    risk_free_rate: float = 0.0,
) -> dict[str, Any]:
    """基于请求区间内有效前复权收盘价生成摘要。"""
    raw_close = pd.to_numeric(frame.get("adjusted_close"), errors="coerce")
    raw_close = raw_close.where(raw_close > 0)
    valid_mask = raw_close.notna()
    valid_positions = np.flatnonzero(valid_mask.to_numpy())
    close = raw_close.dropna()
    first_pos = int(valid_positions[0]) if len(valid_positions) else None
    last_pos = int(valid_positions[-1]) if len(valid_positions) else None
    # 使用 frame 的交易日索引位置差，而不是有效价格个数；缺失日计入跨度。
    span_intervals = (last_pos - first_pos) if first_pos is not None else None
    result: dict[str, Any] = {
        "trading_days": int(len(close)),
        "span_trading_days": int(span_intervals + 1) if span_intervals is not None else 0,
        "elapsed_trading_intervals": int(span_intervals) if span_intervals is not None else None,
        "valid_price_days": int(len(close)),
        "missing_trading_days": (
            int(span_intervals + 1 - len(close)) if span_intervals is not None else 0
        ),
        "daily_return_observations": 0,
        "first_valid_date": close.index[0].date().isoformat() if len(close) else None,
        "last_valid_date": close.index[-1].date().isoformat() if len(close) else None,
        "interval_return": None,
        "cagr": None,
        "annualized_volatility": None,
        "max_drawdown": None,
        "sharpe_ratio": None,
        "sortino_ratio": None,
        "calmar_ratio": None,
        "risk_free_rate": float(risk_free_rate),
        "annualization": int(annualization),
        "std_ddof": 1,
    }
    if len(close) < 2:
        return result

    first = float(close.iloc[0])
    last = float(close.iloc[-1])
    effective_days = int(span_intervals)
    interval_return = last / first - 1
    cagr = (last / first) ** (annualization / effective_days) - 1
    # 关键：在原始交易日索引上计算 pct_change；只删除由缺口产生的 NaN，
    # 不把跨缺口的收益压缩成普通单日收益。
    returns = daily_return_series(frame).dropna()
    result["daily_return_observations"] = int(len(returns))
    annual_vol = (
        float(returns.std(ddof=1) * np.sqrt(annualization)) if len(returns) > 1 else float("nan")
    )
    mdd = max_drawdown(close) if len(close) > 1 else float("nan")
    daily_rf = (1 + risk_free_rate) ** (1 / annualization) - 1
    downside = (returns - daily_rf).clip(upper=0)
    downside_vol = (
        float(np.sqrt(np.mean(np.square(downside.to_numpy()))) * np.sqrt(annualization))
        if len(returns) > 1
        else float("nan")
    )
    sharpe = (cagr - risk_free_rate) / annual_vol if annual_vol and np.isfinite(annual_vol) else float("nan")
    sortino = (
        (cagr - risk_free_rate) / downside_vol
        if downside_vol and np.isfinite(downside_vol)
        else float("nan")
    )
    calmar = cagr / abs(mdd) if mdd and np.isfinite(mdd) else float("nan")
    for key, value in (
        ("interval_return", interval_return),
        ("cagr", cagr),
        ("annualized_volatility", annual_vol),
        ("max_drawdown", mdd),
        ("sharpe_ratio", sharpe),
        ("sortino_ratio", sortino),
        ("calmar_ratio", calmar),
    ):
        result[key] = None if value is None or not math.isfinite(float(value)) else float(value)
    return result
