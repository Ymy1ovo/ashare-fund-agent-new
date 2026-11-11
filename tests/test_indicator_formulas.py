from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from app.quant.momentum import compute_macd, compute_rsi
from app.quant.returns import compute_returns
from app.quant.risk import compute_risk, daily_return_series, summarize_range
from app.quant.trend import compute_trend, ema_with_reset
from app.quant.volatility import compute_volatility, max_drawdown, rolling_max_drawdown


def frame(prices, **extra):
    index = pd.date_range("2024-01-01", periods=len(prices), freq="B")
    data = {"adjusted_close": prices}
    data.update(extra)
    return pd.DataFrame(data, index=index)


def test_returns_and_insufficient_windows() -> None:
    result = compute_returns(frame([100.0, 110.0, 121.0]), windows=(1, 5))
    assert result["return_1d"].iloc[0] != result["return_1d"].iloc[0]
    assert result["return_1d"].iloc[1] == pytest.approx(0.1)
    assert result["return_1d"].iloc[2] == pytest.approx(0.1)
    assert result["return_5d"].isna().all()


def test_cagr_uses_elapsed_trading_days_not_valid_count() -> None:
    # 100、缺失、110、120：实际跨 3 个交易日间隔，年化指数必须是 252/3。
    data = frame([100.0, np.nan, 110.0, 120.0])
    result = compute_returns(data, windows=(1,), annualization=252)
    expected = (120.0 / 100.0) ** (252 / 3) - 1
    assert result["cagr"].iloc[-1] == pytest.approx(expected)
    summary = summarize_range(data, annualization=252)
    assert summary["elapsed_trading_intervals"] == 3
    assert summary["span_trading_days"] == 4
    assert summary["missing_trading_days"] == 1
    assert summary["cagr"] == pytest.approx(expected)


def test_cagr_without_missing_keeps_old_definition() -> None:
    data = frame([100.0, 110.0, 120.0])
    result = compute_returns(data, windows=(1,), annualization=252)
    expected = (120.0 / 100.0) ** (252 / 2) - 1
    assert result["cagr"].iloc[-1] == pytest.approx(expected)
    assert summarize_range(data)["cagr"] == pytest.approx(expected)


def test_ema_resets_after_missing_and_does_not_use_old_state() -> None:
    prices = [100.0, 101.0, 102.0, np.nan, 110.0, 111.0, 112.0, 113.0]
    data = frame(prices)
    ema = ema_with_reset(data["adjusted_close"], span=2)
    # 断点前与原定义一致。
    assert ema.iloc[1] == pytest.approx(1.0 / 3.0 * 100.0 + 2.0 / 3.0 * 101.0)
    assert ema.iloc[2] == pytest.approx(1.0 / 3.0 * ema.iloc[1] + 2.0 / 3.0 * 102.0)
    # 缺失日无输出；之后重新积累，不能沿用旧状态。
    assert np.isnan(ema.iloc[3])
    assert np.isnan(ema.iloc[4])
    assert ema.iloc[5] == pytest.approx(1.0 / 3.0 * 110.0 + 2.0 / 3.0 * 111.0)


def test_ema_prefix_does_not_change_when_future_changes() -> None:
    data = frame([100.0, 101.0, 102.0, np.nan, 110.0, 111.0, 112.0, 113.0])
    before = compute_trend(data, ma_windows=(2,), ema_spans=(2,))["ema2"].iloc[:5].copy()
    changed = data.copy()
    changed.loc[changed.index[5]:, "adjusted_close"] = [999.0, 998.0, 997.0]
    after = compute_trend(changed, ma_windows=(2,), ema_spans=(2,))["ema2"].iloc[:5].copy()
    pd.testing.assert_series_equal(before, after)


def test_moving_average_and_ema() -> None:
    result = compute_trend(frame([1.0, 2.0, 3.0, 4.0]), ma_windows=(2, 3), ema_spans=(2,))
    assert result["ma2"].tolist()[1:] == pytest.approx([1.5, 2.5, 3.5])
    assert result["ma3"].tolist()[2:] == pytest.approx([2.0, 3.0])
    expected_ema2 = pd.Series([1.0, 2.0, 3.0, 4.0]).ewm(span=2, adjust=False, min_periods=2).mean()
    assert result["ema2"].tolist()[1:] == pytest.approx(expected_ema2.tolist()[1:])


def test_rsi_wilder_hand_example() -> None:
    result = compute_rsi(frame([1.0, 2.0, 1.0, 2.0, 3.0]), periods=(2,))
    # 前两个涨跌各 1：RSI=50；之后平均涨幅 .75/.875，平均跌幅 .25/.125。
    assert result["rsi2"].iloc[2] == pytest.approx(50.0)
    assert result["rsi2"].iloc[3] == pytest.approx(75.0)
    assert result["rsi2"].iloc[4] == pytest.approx(87.5)


def test_rsi_monotonic_is_100_and_constant_is_50() -> None:
    up = compute_rsi(frame(list(range(1, 9))), periods=(6,))
    assert up["rsi6"].iloc[6] == pytest.approx(100.0)
    flat = compute_rsi(frame([5.0] * 8), periods=(6,))
    assert flat["rsi6"].iloc[6] == pytest.approx(50.0)


def test_macd_standard_definition() -> None:
    prices = pd.Series(np.linspace(1.0, 2.0, 80))
    data = frame(prices.tolist())
    result = compute_macd(data)
    fast = ema_with_reset(data["adjusted_close"], 12)
    slow = ema_with_reset(data["adjusted_close"], 26)
    dif = fast - slow
    dea = ema_with_reset(dif, 9)
    assert result["macd_dif"].dropna().iloc[-1] == pytest.approx(dif.dropna().iloc[-1])
    assert result["macd_hist"].dropna().iloc[-1] == pytest.approx(2 * (dif - dea).dropna().iloc[-1])


def test_macd_resets_after_missing_and_requires_reaccumulation() -> None:
    prices = [100.0 + index * 0.5 for index in range(80)]
    prices[30] = np.nan
    data = frame(prices)
    result = compute_macd(data)
    assert np.isnan(result["macd_dif"].iloc[30])
    assert np.isnan(result["macd_dea"].iloc[30])
    # EMA26 在断点后需要 26 个连续有效价格，DEA 再需要 9 个。
    assert result["macd_dif"].iloc[31:56].isna().all()
    assert not np.isnan(result["macd_dif"].iloc[56])
    assert result["macd_dea"].iloc[31:64].isna().all()
    assert not np.isnan(result["macd_dea"].iloc[64])

    before = result["macd_dif"].iloc[:30].copy()
    changed = data.copy()
    changed.loc[changed.index[31]:, "adjusted_close"] *= 2
    after = compute_macd(changed)["macd_dif"].iloc[:30].copy()
    pd.testing.assert_series_equal(before, after)


def test_volatility_uses_ddof_1_and_annualization() -> None:
    data = frame([100.0, 110.0, 99.0])
    result = compute_volatility(data, vol_windows=(2,), mdd_windows=(3,), annualization=252, ddof=1)
    expected = pd.Series([0.1, -0.1]).std(ddof=1) * np.sqrt(252)
    assert result["volatility_2d"].iloc[-1] == pytest.approx(expected)


def test_max_drawdown_hand_example() -> None:
    data = frame([100.0, 120.0, 90.0, 110.0])
    assert max_drawdown(data["adjusted_close"]) == pytest.approx(-0.25)
    rolling = rolling_max_drawdown(data["adjusted_close"], 3)
    assert rolling.iloc[2] == pytest.approx(-0.25)
    assert rolling.iloc[3] == pytest.approx(-0.25)
    full = compute_volatility(data, vol_windows=(2,), mdd_windows=(3,))
    # 扩展回撤是“截至当日”的回撤，最后一日已从 90 反弹到 110。
    assert full["max_drawdown_all"].iloc[-1] == pytest.approx(-1 / 12)
    assert full["max_drawdown_all"].iloc[2] == pytest.approx(-0.25)


def test_atr_hand_example() -> None:
    # 第 2 天 TR=max(2, |11-10|, |9-10|)=2；第 3 天 TR=max(2, |12-11|, |10-11|)=2。
    data = frame(
        [10.0, 11.0, 12.0],
        adjusted_open=[10.0, 10.0, 11.0],
        adjusted_high=[10.5, 11.0, 12.0],
        adjusted_low=[9.5, 9.0, 10.0],
    )
    result = compute_volatility(data, vol_windows=(2,), mdd_windows=(2,), atr_period=2)
    assert result["atr2"].iloc[1] == pytest.approx(1.5)
    assert result["atr2"].iloc[2] == pytest.approx(1.75)


def test_risk_ratios_and_no_infinity() -> None:
    data = frame([100.0, 110.0, 99.0, 105.0])
    result = compute_risk(data, risk_window=3, annualization=252, risk_free_rate=0.0)
    assert "sharpe_ratio" in result
    flat = compute_risk(frame([100.0] * 5), risk_window=3)
    assert flat["sharpe_ratio"].isna().all()
    assert flat["calmar_ratio"].isna().all()


def test_summary_uses_only_requested_range() -> None:
    data = frame([100.0, 110.0, 99.0, 105.0])
    summary = summarize_range(data.iloc[:3])
    assert summary["trading_days"] == 3
    assert summary["interval_return"] == pytest.approx(-0.01)
    assert summary["max_drawdown"] == pytest.approx(-0.1)
    assert math.isfinite(summary["annualized_volatility"])


def test_risk_summary_continuous_series_keeps_old_result() -> None:
    data = frame([100.0, 101.0, 102.0, 103.0])
    returns = daily_return_series(data)
    assert returns.notna().sum() == 3
    summary = summarize_range(data, annualization=252)
    expected_vol = returns.dropna().std(ddof=1) * np.sqrt(252)
    assert summary["daily_return_observations"] == 3
    assert summary["annualized_volatility"] == pytest.approx(expected_vol)
    assert summary["cagr"] == pytest.approx((103.0 / 100.0) ** (252 / 3) - 1)


def test_risk_summary_does_not_treat_gap_return_as_single_day() -> None:
    data = frame([100.0, np.nan, 110.0, 120.0])
    returns = daily_return_series(data)
    # 100->110 跨缺口，不能作为普通单日收益；只有 110->120 是真实相邻日收益。
    assert np.isnan(returns.iloc[2])
    assert returns.notna().sum() == 1
    summary = summarize_range(data)
    assert summary["elapsed_trading_intervals"] == 3
    assert summary["missing_trading_days"] == 1
    assert summary["daily_return_observations"] == 1
    assert summary["annualized_volatility"] is None
    assert summary["sharpe_ratio"] is None
    assert summary["sortino_ratio"] is None


def test_risk_summary_consecutive_missing_keeps_sample_count() -> None:
    data = frame([100.0, np.nan, np.nan, 120.0, 121.0])
    returns = daily_return_series(data)
    assert np.isnan(returns.iloc[3])
    assert returns.iloc[4] == pytest.approx(1 / 120)
    assert returns.notna().sum() == 1
    summary = summarize_range(data)
    assert summary["valid_price_days"] == 3
    assert summary["span_trading_days"] == 5
    assert summary["elapsed_trading_intervals"] == 4
    assert summary["missing_trading_days"] == 2
    assert summary["daily_return_observations"] == 1
    assert summary["annualized_volatility"] is None


def test_risk_future_data_does_not_change_past_values() -> None:
    data = frame([100.0, np.nan, 110.0, 120.0, 118.0, 119.0])
    before = compute_risk(data, risk_window=2, annualization=252)
    changed = data.copy()
    changed.loc[changed.index[4]:, "adjusted_close"] = [999.0, 998.0]
    after = compute_risk(changed, risk_window=2, annualization=252)
    pd.testing.assert_frame_equal(before.iloc[:4], after.iloc[:4])


def test_summary_and_compute_risk_share_missing_return_dates() -> None:
    data = frame([100.0, np.nan, 110.0, 120.0, 121.0])
    returns = daily_return_series(data)
    summary = summarize_range(data)
    assert summary["daily_return_observations"] == int(returns.notna().sum())
    # compute_risk 内部使用同一日收益序列；有缺口的滚动窗口不应算出波动率。
    risk = compute_risk(data, risk_window=2)
    assert risk["sharpe_ratio"].iloc[:3].isna().all()
