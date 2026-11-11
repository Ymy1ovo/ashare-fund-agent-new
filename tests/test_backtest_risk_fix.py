"""阶段3A.1：Sharpe/Sortino 口径与缺失行情识别测试。"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from app.backtest.metrics import (
    compute_performance,
    held_price_gap_days,
    risk_return_series,
)
from app.backtest.models import DailySnapshot


def _snap(day, nav, positions=None, price_status=None):
    return DailySnapshot(
        trade_date=day,
        cash=0.0,
        market_value=nav * 100,
        total_assets=nav * 100,
        nav=nav,
        positions=positions or {},
        price_status=price_status or {},
    )


def _series(navs, positions=None, status=None):
    start = date(2024, 1, 2)
    return [
        _snap(start + timedelta(days=index), value,
              positions=positions or {}, price_status=status or {})
        for index, value in enumerate(navs)
    ]


def test_sharpe_uses_mean_daily_excess_not_cagr() -> None:
    navs = [100.0, 101.0, 100.5, 102.0, 101.5, 103.0]
    daily = _series(navs)
    perf = compute_performance(daily, [], [], 100.0, annualization=252, risk_free_rate=0.0)
    returns = np.array([0.01, -0.0049505, 0.0149254, -0.0049020, 0.0147783])
    expected_sharpe = returns.mean() * 252 / (returns.std(ddof=1) * np.sqrt(252))
    assert perf.sharpe_ratio == pytest.approx(expected_sharpe, rel=1e-4)
    # 与旧口径（CAGR 当分子）必须不同
    old_style = (perf.cagr or 0) / (perf.annualized_volatility or 1)
    assert abs(perf.sharpe_ratio - old_style) > 1e-6


def test_sortino_uses_downside_deviation_of_excess() -> None:
    navs = [100.0, 102.0, 101.0, 103.0, 100.0]
    daily = _series(navs)
    perf = compute_performance(daily, [], [], 100.0, annualization=252)
    # 用精确净值推算日收益，避免手写小数带来的舍入差
    exact = np.array([
        navs[i] / navs[i - 1] - 1 for i in range(1, len(navs))
    ])
    downside = np.minimum(exact, 0.0)
    expected_dd = float(np.sqrt(np.mean(downside ** 2)) * np.sqrt(252))
    expected_sortino = exact.mean() * 252 / expected_dd
    assert perf.downside_deviation == pytest.approx(expected_dd, rel=1e-9)
    assert perf.sortino_ratio == pytest.approx(expected_sortino, rel=1e-9)


def test_risk_free_rate_is_converted_to_daily() -> None:
    daily = _series([100.0, 100.5, 101.0])
    perf = compute_performance(daily, [], [], 100.0, annualization=252, risk_free_rate=0.03)
    expected_daily = (1.03) ** (1 / 252) - 1
    assert perf.daily_rf == pytest.approx(expected_daily, rel=1e-9)
    assert perf.mean_daily_excess == pytest.approx(
        perf.mean_daily_return - expected_daily, rel=1e-9
    )


def test_zero_volatility_returns_none_not_infinity() -> None:
    daily = _series([100.0, 100.0, 100.0])
    perf = compute_performance(daily, [], [], 100.0)
    assert perf.sharpe_ratio is None
    assert perf.annualized_volatility == pytest.approx(0.0)


def test_held_gap_day_excludes_return_from_risk_stats() -> None:
    daily = _series(
        [100.0, 101.0, 101.0, 102.0],
        positions={"510300": 1000},
        status={"510300": "ok"},
    )
    daily[1].price_status = {"510300": "stale_price"}
    nav, returns, statuses = risk_return_series(daily)
    assert len(returns) == 1, "缺口日与缺口次日都不能作为单日收益样本"
    assert statuses[1]["return_status"] == "held_price_gap"
    assert statuses[2]["return_status"] == "prior_day_price_gap"


def test_unheld_gap_does_not_affect_portfolio_risk() -> None:
    daily = _series(
        [100.0, 101.0, 102.0],
        positions={"510300": 1000},
        status={"510300": "ok", "510500": "stale_price"},
    )
    gaps = held_price_gap_days(daily)
    assert gaps == set(), "未持仓 ETF 缺行情不影响组合"
    _, returns, _ = risk_return_series(daily)
    assert len(returns) == 2


def test_no_position_day_uses_cash_return() -> None:
    daily = _series([100.0, 100.0, 100.0], positions={}, status={})
    _, returns, statuses = risk_return_series(daily)
    assert len(returns) == 2
    assert all(item["return_status"] == "ok" for item in statuses[1:])


def test_gap_is_not_compressed_into_single_day_return() -> None:
    daily = _series(
        [100.0, 120.0, 121.0, 122.0],
        positions={"510300": 1000},
        status={"510300": "ok"},
    )
    daily[1].price_status = {"510300": "stale_price"}
    _, returns, statuses = risk_return_series(daily)
    # 第 2 日缺口：当日与次日都不代表真实单日收益，
    # 100 -> 121 的跨缺口涨幅不能压成单日 21%。
    assert statuses[1]["return_status"] == "held_price_gap"
    assert statuses[2]["return_status"] == "prior_day_price_gap"
    assert len(returns) == 1
    assert returns.iloc[0] == pytest.approx(122.0 / 121.0 - 1, rel=1e-9)


def test_max_drawdown_uses_valuation_nav_and_warns() -> None:
    daily = _series(
        [100.0, 90.0, 95.0],
        positions={"510300": 1000},
        status={"510300": "ok"},
    )
    daily[1].price_status = {"510300": "stale_price"}
    perf = compute_performance(daily, [], [], 100.0)
    assert perf.max_drawdown == pytest.approx(-0.1)
    assert perf.nav_days_with_price_gaps == 1
    assert perf.gap_return_days_excluded == 2
    assert any("估值不完整" in note for note in perf.notes)
