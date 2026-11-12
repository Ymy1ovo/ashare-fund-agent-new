"""阶段3A.3.1 研究脚本与归因口径的专项测试。

只测计算口径，不跑完整回测；所有样本都是内存构造的小数据。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd
import pytest

from app.research import attribution as attr


@dataclass
class FakeSnapshot:
    trade_date: date
    cash: float
    market_value: float
    total_assets: float
    nav: float
    positions: dict = field(default_factory=dict)
    prices: dict = field(default_factory=dict)
    price_status: dict = field(default_factory=dict)


@dataclass
class FakeTrade:
    trade_id: int
    order_id: int
    code: str
    side: str
    trade_date: date
    quantity: int
    price: float
    gross_amount: float
    commission: float = 0.0
    slippage_cost: float = 0.0
    realized_pnl: float = 0.0
    holding_days: float = 0.0
    cash_after: float = 0.0
    stamp_tax: float = 0.0
    transfer_fee: float = 0.0

    @property
    def total_fees(self) -> float:
        return self.commission + self.stamp_tax + self.transfer_fee


def _snapshot(day, cash, positions, prices):
    market = sum(qty * prices[code] for code, qty in positions.items() if qty > 0)
    total = cash + market
    return FakeSnapshot(
        trade_date=day, cash=cash, market_value=market, total_assets=total,
        nav=total / 1_000_000.0, positions=dict(positions), prices=dict(prices),
    )


# ---------------------------------------------------------- 净值分解恒等式

def test_decomposition_identity_holds_with_buy():
    """买入日：数量变化 + 价格变化 + 费用，必须与净资产变动完全一致。"""
    d0 = date(2025, 1, 2)
    d1 = date(2025, 1, 3)
    daily = [
        _snapshot(d0, 10000.0, {}, {"AAA": 10.0}),
        _snapshot(d1, 10000.0 - 1000.0 - 5.0, {"AAA": 100}, {"AAA": 10.5}),
    ]
    trades = [
        FakeTrade(1, 1, "AAA", "buy", d1, 100, 10.0, 1000.0, commission=5.0),
    ]
    result = attr.decompose_nav(daily, trades)
    assert result["identity_ok"] is True
    assert result["max_abs_residual"] < 1e-6
    totals = result["totals"]
    # 持有收益 0（前一日空仓），执行价差 = 100 × (10.5 - 10.0) = 50
    assert totals["exec_gap"] == pytest.approx(50.0, abs=1e-6)
    assert totals["fees"] == pytest.approx(5.0, abs=1e-6)
    assert totals["delta_total_assets"] == pytest.approx(45.0, abs=1e-6)


def test_decomposition_handles_same_day_buy_and_sell():
    """同一天同一标的既有买入又有卖出时，不能用混合均价（会引入残差）。"""
    d0 = date(2025, 1, 2)
    d1 = date(2025, 1, 3)
    daily = [
        _snapshot(d0, 5000.0, {"AAA": 500}, {"AAA": 10.0}),
        _snapshot(d1, 5000.0 - 1000 - 5 + 300*11.2 - 5, {"AAA": 800}, {"AAA": 11.0}),
    ]
    trades = [
        FakeTrade(1, 1, "AAA", "buy", d1, 100, 10.0, 1000.0, commission=5.0),
        FakeTrade(2, 2, "AAA", "sell", d1, 300, 11.2, 300 * 11.2, commission=5.0),
    ]
    result = attr.decompose_nav(daily, trades)
    assert result["identity_ok"] is True, result["rows"]
    assert result["max_abs_residual"] < 1e-6


def test_decomposition_flags_missing_price_anomaly():
    d0 = date(2025, 1, 2)
    d1 = date(2025, 1, 3)
    daily = [
        _snapshot(d0, 0.0, {"AAA": 100}, {"AAA": 10.0}),
        FakeSnapshot(date(2025, 1, 3), 0.0, 1050.0, 1050.0, 0.00105,
                     positions={"AAA": 100}, prices={}),
    ]
    result = attr.decompose_nav(daily, [])
    assert result["anomaly_count"] >= 1


# ---------------------------------------------------------- 成本拆分

def test_cost_breakdown_sums_four_components_without_double_count():
    trades = [
        FakeTrade(1, 1, "AAA", "buy", date(2025, 1, 2), 100, 10.0, 1000.0,
                  commission=5.0, slippage_cost=2.5, stamp_tax=0.0, transfer_fee=0.1),
        FakeTrade(2, 2, "AAA", "sell", date(2025, 1, 6), 100, 11.0, 1100.0,
                  commission=5.0, slippage_cost=3.0, stamp_tax=1.1, transfer_fee=0.11),
    ]
    result = attr.cost_breakdown(trades, initial_cash=10000.0, gross_profit=500.0)
    assert result["commission"] == pytest.approx(10.0)
    assert result["stamp_tax"] == pytest.approx(1.1)
    assert result["transfer_fee"] == pytest.approx(0.21)
    assert result["slippage"] == pytest.approx(5.5)
    assert result["trade_fees"] == pytest.approx(11.31)
    assert result["total_cost"] == pytest.approx(16.81)
    # 滑点不能重复计入费用
    assert result["trade_fees"] + result["slippage"] == pytest.approx(result["total_cost"])
    assert result["buy"]["trade_count"] == 1
    assert result["sell"]["trade_count"] == 1


def test_cost_breakdown_ratios_are_none_when_denominator_zero():
    result = attr.cost_breakdown([], initial_cash=0.0, gross_profit=None)
    assert result["total_cost"] == 0.0
    assert result["cost_over_initial_cash"] is None
    assert result["cost_over_gross_profit"] is None


# ---------------------------------------------------------- 行为统计

def test_trade_behaviour_counts_and_exposure():
    d0 = date(2025, 1, 2)
    daily = [
        _snapshot(d0, 1000.0, {"AAA": 100}, {"AAA": 10.0}),
        _snapshot(d0 + timedelta(days=1), 2000.0, {}, {"AAA": 10.0}),
        _snapshot(d0 + timedelta(days=2), 2000.0, {}, {"AAA": 10.0}),
    ]
    trades = [
        FakeTrade(1, 1, "AAA", "buy", d0, 100, 10.0, 1000.0, commission=5.0,
                  holding_days=0.0),
        FakeTrade(2, 2, "AAA", "sell", d0 + timedelta(days=1), 100, 10.0, 1000.0,
                  commission=5.0, holding_days=1.0),
    ]
    result = attr.trade_behaviour(daily, trades)
    assert result["buy_count"] == 1
    assert result["sell_count"] == 1
    assert result["longest_flat_run"] == 2
    assert result["flat_days"] == 2
    assert result["holding_within_5_days"] == 1
    assert result["per_code_trades"] == {"AAA": 2}


# ---------------------------------------------------------- 回撤与风险

def test_drawdown_profile_reports_trough_and_recovery():
    index = pd.DatetimeIndex(["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"])
    nav = pd.Series([1.0, 1.2, 0.9, 1.2], index=index)
    result = attr.drawdown_profile(nav)
    assert result["max_drawdown"] == pytest.approx(-0.25)
    assert result["peak_date"] == "2025-01-03"
    assert result["trough_date"] == "2025-01-06"
    assert result["recovered"] is True
    assert result["recovery_date"] == "2025-01-07"


def test_drawdown_profile_marks_unrecovered():
    index = pd.DatetimeIndex(["2025-01-02", "2025-01-03"])
    nav = pd.Series([1.2, 0.9], index=index)
    result = attr.drawdown_profile(nav)
    assert result["recovered"] is False
    assert result["recovery_date"] is None
    assert "未恢复" in result["recovery_status"]


# ---------------------------------------------------------- 价格断点

def test_detect_price_breakpoints_finds_split_like_jump():
    rows = [
        {"code": "AAA", "trade_date": "2025-03-18", "close": 10.5, "adjusted_close": 105.0},
        {"code": "AAA", "trade_date": "2025-03-19", "close": 105.0, "adjusted_close": 105.0},
    ]
    breaks = attr.detect_price_breakpoints(rows)
    assert len(breaks) == 1
    assert breaks[0]["trade_date"] == "2025-03-19"
    assert breaks[0]["implied_ratio"] == pytest.approx(10.0, abs=1e-3)


def test_detect_price_breakpoints_ignores_normal_days():
    rows = [
        {"code": "AAA", "trade_date": "2025-03-18", "close": 10.0, "adjusted_close": 10.0},
        {"code": "AAA", "trade_date": "2025-03-19", "close": 10.2, "adjusted_close": 10.19},
    ]
    assert attr.detect_price_breakpoints(rows) == []


def test_contamination_estimate_deducts_fake_gain():
    d0 = date(2025, 3, 18)
    d1 = date(2025, 3, 19)
    daily = [
        _snapshot(d0, 0.0, {"AAA": 1000}, {"AAA": 10.0}),
        _snapshot(d1, 0.0, {"AAA": 1000}, {"AAA": 105.0}),
    ]
    breaks = [{
        "code": "AAA", "trade_date": "2025-03-19",
        "prev_close": 10.0, "close": 105.0,
        "prev_adjusted": 105.0, "adjusted": 105.0,
        "raw_return": 9.5, "adjusted_return": 0.0, "gap": 9.5,
        "implied_ratio": 10.5,
    }]
    result = attr.contamination_estimate(daily, breaks, initial_cash=10000.0)
    # 前一交易日持仓 1000 份 × 10 元 × (10.5-1) = 95000 元虚增
    assert result["cumulative_fake_amount"] == pytest.approx(95000.0, rel=1e-9)
    assert result["estimated"]["total_return"] < result["observed"]["total_return"]


def test_contamination_estimate_no_breaks_is_noop():
    daily = [
        _snapshot(date(2025, 1, 2), 1000.0, {"AAA": 100}, {"AAA": 10.0}),
        _snapshot(date(2025, 1, 3), 1000.0, {"AAA": 100}, {"AAA": 10.0}),
    ]
    result = attr.contamination_estimate(daily, [], initial_cash=2000.0)
    assert result["cumulative_fake_amount"] == 0.0
    assert result["observed"]["total_return"] == pytest.approx(
        result["estimated"]["total_return"]
    )


# ---------------------------------------------------------- 环境归因

def test_regime_attribution_groups_by_existing_labels():
    d0 = date(2025, 1, 2)
    daily = [
        _snapshot(d0, 0.0, {"AAA": 100}, {"AAA": 10.0}),
        _snapshot(d0 + timedelta(days=1), 0.0, {"AAA": 100}, {"AAA": 11.0}),
        _snapshot(d0 + timedelta(days=2), 0.0, {"AAA": 100}, {"AAA": 9.0}),
    ]
    labels = {
        d0: "bull",
        d0 + timedelta(days=1): "bull",
        d0 + timedelta(days=2): "bear",
    }
    trades = [FakeTrade(1, 1, "AAA", "buy", d0, 100, 10.0, 1000.0, commission=5.0)]
    result = attr.regime_attribution(daily, labels, trades)
    assert result["regimes"]["bull"]["days"] == 2
    assert result["regimes"]["bear"]["days"] == 1
    assert result["regimes"]["bear"]["trades"] == 0
    assert result["regimes"]["bull"]["buy_count"] == 1
    assert result["regimes"]["range"]["status"] == "no_data"


# ---------------------------------------------------------- 集中度

def test_concentration_profile_reports_effective_n():
    d0 = date(2025, 1, 2)
    daily = [
        _snapshot(d0, 0.0, {"AAA": 50, "BBB": 50}, {"AAA": 10.0, "BBB": 10.0}),
        _snapshot(d0 + timedelta(days=1), 0.0, {"AAA": 100}, {"AAA": 10.0}),
    ]
    result = attr.concentration_profile(daily)
    assert result["days_with_single_holding"] == 1
    assert result["holdings"]["max"] == 2
    assert result["max_weight"]["max"] == pytest.approx(1.0)
    assert result["effective_n"] is not None
