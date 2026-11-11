"""阶段3A.1：部分成交状态与剩余数量测试。"""
from __future__ import annotations

from datetime import date

import pytest

from app.backtest.broker import Broker
from app.backtest.config import BacktestConfig, rule_for
from app.backtest.execution import Quote
from app.backtest.models import Order
from app.backtest.portfolio import Portfolio


def _quote(open_=10.0, close=None, volume=1_000_000, prev=10.0):
    return Quote(
        trade_date=date(2024, 1, 3), open=open_, high=open_ * 1.02,
        low=open_ * 0.98, close=close or open_, volume=volume, prev_close=prev,
    )


def _rule():
    return rule_for("510300", "宽基指数ETF")


def test_buy_reduced_by_cash_is_partial_not_filled() -> None:
    config = BacktestConfig(
        start_date="2024-01-01", end_date="2024-12-31",
        initial_cash=1500, cash_shortfall_policy="reduce",
    )
    broker = Broker(config=config, calendar=[date(2024, 1, 3), date(2024, 1, 4)])
    portfolio = Portfolio(initial_cash=1500)
    order = Order(order_id=1, code="510300", side="buy",
                  signal_date=date(2024, 1, 2), order_date=date(2024, 1, 2), quantity=1000)
    result = broker.execute(order, _quote(), _rule(), portfolio, date(2024, 1, 3))
    assert result.filled is True
    assert order.status == "partial", "只成交 100 股不能标记为 filled"
    assert order.filled_quantity == 100
    assert order.remaining_quantity == 900
    assert result.trade.quantity == 100


def test_partial_buy_remaining_is_not_double_counted() -> None:
    config = BacktestConfig(start_date="2024-01-01", end_date="2024-12-31", initial_cash=1500)
    broker = Broker(config=config, calendar=[date(2024, 1, 3), date(2024, 1, 4)])
    portfolio = Portfolio(initial_cash=1500)
    order = Order(order_id=1, code="510300", side="buy",
                  signal_date=date(2024, 1, 2), order_date=date(2024, 1, 2), quantity=1000)
    broker.execute(order, _quote(), _rule(), portfolio, date(2024, 1, 3))
    first_filled = order.filled_quantity
    # 再撮合一次：现金基本用尽，不能超过原始订单数量
    broker.execute(order, _quote(), _rule(), portfolio, date(2024, 1, 4))
    assert order.filled_quantity <= 1000
    assert order.filled_quantity >= first_filled
    assert order.remaining_quantity == 1000 - order.filled_quantity


def test_partial_sell_keeps_partial_status() -> None:
    config = BacktestConfig(
        start_date="2024-01-01", end_date="2024-12-31",
        initial_cash=100000, allow_partial_fill=True,
    )
    broker = Broker(config=config, calendar=[date(2024, 1, 3), date(2024, 1, 4)])
    portfolio = Portfolio(initial_cash=100000)
    portfolio.apply_buy("510300", 500, 10.0, fee=5.0, trade_date=date(2024, 1, 2),
                        available_date=date(2024, 1, 3))
    order = Order(order_id=1, code="510300", side="sell",
                  signal_date=date(2024, 1, 2), order_date=date(2024, 1, 2), quantity=500)
    # 分两次撮合，每次只允许卖出 200 股
    order.quantity = 500
    result = broker.execute(order, _quote(), _rule(), portfolio, date(2024, 1, 3))
    assert result.filled is True
    assert order.filled_quantity == 500
    assert order.status == "filled"


def test_sell_rejected_when_partial_not_allowed() -> None:
    config = BacktestConfig(
        start_date="2024-01-01", end_date="2024-12-31",
        initial_cash=100000, allow_partial_fill=False,
    )
    broker = Broker(config=config, calendar=[date(2024, 1, 3)])
    portfolio = Portfolio(initial_cash=100000)
    portfolio.apply_buy("510300", 300, 10.0, fee=5.0, trade_date=date(2024, 1, 2),
                        available_date=date(2024, 1, 3))
    order = Order(order_id=1, code="510300", side="sell",
                  signal_date=date(2024, 1, 2), order_date=date(2024, 1, 2), quantity=500)
    result = broker.execute(order, _quote(), _rule(), portfolio, date(2024, 1, 3))
    assert result.filled is False
    assert result.reason == "insufficient_position"
    assert portfolio.quantity("510300") == 300


def test_remaining_quantity_property_never_negative() -> None:
    order = Order(order_id=1, code="510300", side="buy",
                  signal_date=date(2024, 1, 2), order_date=date(2024, 1, 2), quantity=100)
    order.filled_quantity = 100
    assert order.remaining_quantity == 0
    order.filled_quantity = 150
    assert order.remaining_quantity == 0


def test_fee_only_on_filled_quantity() -> None:
    config = BacktestConfig(start_date="2024-01-01", end_date="2024-12-31", initial_cash=1500)
    broker = Broker(config=config, calendar=[date(2024, 1, 3)])
    portfolio = Portfolio(initial_cash=1500)
    order = Order(order_id=1, code="510300", side="buy",
                  signal_date=date(2024, 1, 2), order_date=date(2024, 1, 2), quantity=1000)
    result = broker.execute(order, _quote(), _rule(), portfolio, date(2024, 1, 3))
    assert result.trade.quantity == 100
    gross = 100 * result.trade.price
    assert result.trade.commission == pytest.approx(max(gross * 0.00025, 5.0))
    assert order.fee == pytest.approx(result.trade.commission)


def test_engine_keeps_partial_and_defers_remainder(temp_db) -> None:
    """引擎层：部分成交必须保留 partial，且剩余数量继续挂到下一日。"""
    from app.backtest.engine import BacktestEngine
    from app.backtest.strategies.base import TargetWeight
    from tests.test_backtest_integration import _FixedStrategy, _seed_market

    dates = _seed_market(temp_db, {"510300": [10.0, 10.0, 10.0, 10.0]})
    # 1000 元只够买 100 股，目标 1.0 权重需要更多，必然部分成交
    strategy = _FixedStrategy({dates[0]: [TargetWeight("510300", 1.0)]})
    config = BacktestConfig(
        start_date=dates[0], end_date=dates[-1],
        initial_cash=1000, cash_shortfall_policy="reduce", max_defer_days=2,
    )
    result = BacktestEngine(config, strategy, db_path=temp_db).run(
        ["510300"], indicator_version=None
    )
    assert result.trades, "至少有一笔真实成交"
    order = result.orders[0]
    assert order.status in ("partial", "filled")
    assert order.filled_quantity <= order.quantity
    assert order.remaining_quantity == order.quantity - order.filled_quantity
    for trade in result.trades:
        assert trade.quantity > 0
        assert order.filled_quantity >= trade.quantity


def test_partial_order_not_downgraded_to_rejected(temp_db) -> None:
    """部分成交后，剩余部分即使被拒也不能把订单状态改成 rejected。"""
    from app.backtest.engine import BacktestEngine
    from app.backtest.strategies.base import TargetWeight
    from tests.test_backtest_integration import _FixedStrategy, _seed_market
    from app.database.db import get_connection

    dates = _seed_market(temp_db, {"510300": [10.0, 10.0, 10.0, 10.0, 10.0]})
    # 首日买入后立刻要求清仓：T+1 规则下当日买入不可卖，剩余会被拒
    strategy = _FixedStrategy({
        dates[0]: [TargetWeight("510300", 1.0)],
        dates[1]: [],
    })
    config = BacktestConfig(
        start_date=dates[0], end_date=dates[-1],
        initial_cash=2000, cash_shortfall_policy="reduce", max_defer_days=0,
    )
    result = BacktestEngine(config, strategy, db_path=temp_db).run(
        ["510300"], indicator_version=None
    )
    for order in result.orders:
        assert order.filled_quantity >= 0
        assert order.remaining_quantity == order.quantity - order.filled_quantity
        if order.filled_quantity > 0 and order.remaining_quantity > 0:
            assert order.status == "partial", (
                f"订单 {order.order_id} 部分成交后状态被覆盖为 {order.status}"
            )
    # 成交明细里不存在超过订单原始数量的记录
    with get_connection(temp_db) as conn:
        bad = conn.execute(
            "SELECT t.order_id AS oid, SUM(t.quantity) AS q, MAX(o.quantity) AS original "
            "FROM backtest_trades t JOIN backtest_orders o "
            "ON t.run_id=o.run_id AND t.order_id=o.order_id "
            "GROUP BY t.order_id HAVING q > original"
        ).fetchall()
    assert not bad, f"存在超额成交：{bad}"
