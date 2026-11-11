"""绩效统计测试：人工净值序列，手工核对公式。"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from app.backtest.metrics import compute_performance, max_drawdown, reconcile, yearly_table
from app.backtest.models import DailySnapshot, Trade


def _series(values):
    start = date(2024, 1, 2)
    return [
        DailySnapshot(
            trade_date=start + timedelta(days=index),
            cash=0.0,
            market_value=value,
            total_assets=value,
            nav=value / 100.0,
        )
        for index, value in enumerate(values)
    ]


def _trade(tid, side, pnl=0.0, holding=5.0, gross=1000.0, commission=5.0, slippage=1.0):
    return Trade(
        trade_id=tid, order_id=tid, code="510300", side=side,
        trade_date=date(2024, 1, 3), quantity=100, price=10.0,
        gross_amount=gross, commission=commission, slippage_cost=slippage,
        realized_pnl=pnl, holding_days=holding, cash_after=0.0,
    )


def test_max_drawdown_hand_example():
    nav = [100.0, 120.0, 90.0, 110.0]
    series = _series(nav)
    import pandas as pd
    prices = pd.Series([item.nav for item in series])
    assert max_drawdown(prices) == pytest.approx(-0.25)


def test_total_return_and_cagr_use_trading_span():
    daily = _series([100.0, 110.0, 121.0])
    perf = compute_performance(daily, [], [], 100.0, annualization=252)
    assert perf.total_return == pytest.approx(0.21)
    expected_cagr = (1.21) ** (252 / 2) - 1
    assert perf.cagr == pytest.approx(expected_cagr)


def test_volatility_and_sharpe_with_missing_return_day():
    daily = _series([100.0, 100.0, 100.0])
    daily[1].nav = float("nan")
    perf = compute_performance(daily, [], [], 100.0)
    # 只剩 1 个有效日收益，不足以计算标准差
    assert perf.annualized_volatility is None
    assert perf.sharpe_ratio is None


def test_win_rate_and_profit_loss_ratio():
    trades = [_trade(1, "sell", pnl=100.0), _trade(2, "sell", pnl=-50.0),
              _trade(3, "sell", pnl=300.0)]
    perf = compute_performance(_series([100.0, 110.0]), trades, [], 100.0)
    assert perf.win_rate == pytest.approx(2 / 3)
    assert perf.profit_loss_ratio == pytest.approx(200.0 / 50.0)


def test_trade_cost_and_turnover():
    trades = [_trade(1, "sell", gross=10000.0, commission=5.0, slippage=2.0),
              _trade(2, "buy", gross=10000.0, commission=5.0, slippage=2.0)]
    perf = compute_performance(_series([100.0, 100.0]), trades, [], 100.0)
    assert perf.total_commission == pytest.approx(10.0)
    assert perf.total_slippage == pytest.approx(4.0)
    assert perf.trade_count == 2
    assert perf.turnover is not None


def test_yearly_table():
    daily = _series([100.0, 110.0])
    daily[1].trade_date = date(2025, 1, 2)
    flat = [item.nav for item in daily]
    daily[0].nav = 1.0
    daily[1].nav = 1.1
    rows = yearly_table(daily)
    assert len(rows) == 2
    assert rows[0]["year"] == 2024
    assert rows[1]["return"] == pytest.approx(0.1)


def test_reconcile_detects_mismatch():
    daily = _series([100.0])
    daily[0].cash = 60.0
    daily[0].market_value = 30.0
    daily[0].total_assets = 90.0
    check = reconcile(daily, [], 100.0)
    assert check["ok"] is False
    assert any("现金推演" in error or "总资产" in error for error in check["errors"])
