"""回测引擎单元测试：人工构造行情，不依赖真实数据库。"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from app.backtest.config import BacktestConfig, CostConfig
from app.backtest.execution import Quote, available_date, fill_price, limit_blocked
from app.backtest.config import rule_for
from app.backtest.portfolio import Portfolio, PortfolioError
from app.backtest.strategies.base import StrategyContext, TargetWeight


def _quote(open_=10.0, high=10.5, low=9.5, close=10.0, volume=100000, prev=10.0) -> Quote:
    return Quote(
        trade_date=date(2024, 1, 2), open=open_, high=high, low=low,
        close=close, volume=volume, prev_close=prev,
    )


def _rule(code="510300", category="宽基指数ETF"):
    return rule_for(code, category)


def test_initial_cash_and_nav() -> None:
    portfolio = Portfolio(initial_cash=100000)
    assert portfolio.cash == 100000
    snap = portfolio.snapshot(date(2024, 1, 2), {}, nav_base=100000, previous_nav=None)
    assert snap.total_assets == 100000
    assert snap.nav == 1.0
    assert snap.daily_return is None


def test_buy_updates_cash_position_and_value() -> None:
    portfolio = Portfolio(initial_cash=100000)
    portfolio.apply_buy("510300", 1000, 10.0, fee=5.0, trade_date=date(2024, 1, 2),
                        available_date=date(2024, 1, 3))
    assert portfolio.cash == pytest.approx(100000 - 10000 - 5.0)
    assert portfolio.quantity("510300") == 1000
    assert portfolio.market_value({"510300": 10.5}) == pytest.approx(10500)
    snap = portfolio.snapshot(date(2024, 1, 2), {"510300": 10.5}, 100000, None)
    assert snap.total_assets == pytest.approx(100000 - 10005 + 10500)
    assert snap.nav == pytest.approx(snap.total_assets / 100000)


def test_sell_realizes_pnl_and_deducts_fee() -> None:
    portfolio = Portfolio(initial_cash=100000)
    portfolio.apply_buy("510300", 1000, 10.0, fee=5.0, trade_date=date(2024, 1, 2),
                        available_date=date(2024, 1, 3))
    realized = portfolio.apply_sell("510300", 1000, 11.0, fee=5.0, trade_date=date(2024, 1, 5))
    # 成本 10.005/股，卖出 11.0，扣 5 元费用
    assert realized == pytest.approx(1000 * (11.0 - 10.005) - 5.0)
    assert portfolio.cash == pytest.approx(100000 - 10005 + 11000 - 5.0)
    assert portfolio.quantity("510300") == 0


def test_commission_minimum_and_slippage() -> None:
    config = BacktestConfig(start_date="2024-01-01", end_date="2024-12-31")
    quote = _quote()
    rule = _rule()
    price, blocked = fill_price(quote, "buy", rule, config)
    assert blocked is None
    # 5bp 滑点：10.0 * 1.0005
    assert price == pytest.approx(10.005)
    from app.backtest.costs import commission, slippage_cost
    assert commission(1000.0, config.costs) == pytest.approx(5.0)  # 最低佣金
    assert commission(1_000_000, config.costs) == pytest.approx(250.0)
    assert slippage_cost(10.0, price, 1000, "buy") == pytest.approx(5.0)


def test_cash_shortfall_rejected_or_reduced() -> None:
    from app.backtest.broker import Broker
    from app.backtest.models import Order

    calendar = [date(2024, 1, 2), date(2024, 1, 3)]
    # 1500 元只够买 100 股（10.005*100+5），下单 1000 股应被缩减而不是透支。
    config = BacktestConfig(start_date="2024-01-01", end_date="2024-12-31", initial_cash=1500)
    broker = Broker(config=config, calendar=calendar)
    portfolio = Portfolio(initial_cash=1500)
    order = Order(order_id=1, code="510300", side="buy", signal_date=date(2024, 1, 2),
                  order_date=date(2024, 1, 2), quantity=1000)
    result = broker.execute(order, _quote(), _rule(), portfolio, date(2024, 1, 3))
    assert result.filled is True
    assert result.order.filled_quantity == 100
    assert result.order.reason == "reduced_by_cash"
    assert portfolio.cash >= -1e-6

    # 现金连一手都买不起时必须拒绝，不能成交负数或透支。
    tiny = Portfolio(initial_cash=500)
    small = Order(order_id=2, code="510300", side="buy", signal_date=date(2024, 1, 2),
                  order_date=date(2024, 1, 2), quantity=1000)
    rejected = broker.execute(small, _quote(), _rule(), tiny, date(2024, 1, 3))
    assert rejected.filled is False
    assert rejected.reason == "insufficient_cash"
    assert tiny.cash == 500


def test_cash_shortfall_reject_policy() -> None:
    from app.backtest.broker import Broker
    from app.backtest.models import Order

    config = BacktestConfig(start_date="2024-01-01", end_date="2024-12-31",
                            initial_cash=100, cash_shortfall_policy="reject")
    broker = Broker(config=config, calendar=[date(2024, 1, 3)])
    order = Order(order_id=1, code="510300", side="buy", signal_date=date(2024, 1, 2),
                  order_date=date(2024, 1, 2), quantity=1000)
    result = broker.execute(order, _quote(), _rule(), Portfolio(initial_cash=100), date(2024, 1, 3))
    assert result.filled is False
    assert result.reason == "insufficient_cash"


def test_cannot_sell_more_than_available() -> None:
    portfolio = Portfolio(initial_cash=100000)
    with pytest.raises(PortfolioError):
        portfolio.apply_sell("510300", 100, 10.0, fee=5.0, trade_date=date(2024, 1, 3))


def test_t_plus_one_not_sellable_same_day() -> None:
    portfolio = Portfolio(initial_cash=100000)
    portfolio.apply_buy("510300", 1000, 10.0, fee=5.0, trade_date=date(2024, 1, 2),
                        available_date=date(2024, 1, 3))
    assert portfolio.available("510300", date(2024, 1, 2)) == 0
    assert portfolio.available("510300", date(2024, 1, 3)) == 1000
    with pytest.raises(PortfolioError):
        portfolio.apply_sell("510300", 100, 10.5, fee=5.0, trade_date=date(2024, 1, 2))


def test_t0_rule_allows_same_day_sell() -> None:
    calendar = [date(2024, 1, 2), date(2024, 1, 3)]
    rule = rule_for("513100", "跨境ETF")
    assert rule.settlement_days == 0
    assert available_date(date(2024, 1, 2), rule, calendar) == date(2024, 1, 2)


def test_zero_volume_cannot_fill() -> None:
    from app.backtest.broker import Broker
    from app.backtest.models import Order

    config = BacktestConfig(start_date="2024-01-01", end_date="2024-12-31")
    broker = Broker(config=config, calendar=[date(2024, 1, 3)])
    order = Order(order_id=1, code="510300", side="buy", signal_date=date(2024, 1, 2),
                  order_date=date(2024, 1, 2), quantity=100)
    result = broker.execute(order, _quote(volume=0), _rule(), Portfolio(initial_cash=100000), date(2024, 1, 3))
    assert result.filled is False
    assert result.reason == "zero_volume"
    assert result.deferred is True


def test_missing_quote_cannot_fill() -> None:
    from app.backtest.broker import Broker
    from app.backtest.models import Order

    config = BacktestConfig(start_date="2024-01-01", end_date="2024-12-31")
    broker = Broker(config=config, calendar=[date(2024, 1, 3)])
    order = Order(order_id=1, code="510300", side="buy", signal_date=date(2024, 1, 2),
                  order_date=date(2024, 1, 2), quantity=100)
    quote = _quote(open_=float("nan"))
    result = broker.execute(order, quote, _rule(), Portfolio(initial_cash=100000), date(2024, 1, 3))
    assert result.filled is False
    assert result.reason.startswith("invalid_")


def test_price_limit_blocks_buy_at_limit_up() -> None:
    rule = _rule()
    quote = _quote(open_=11.0, high=11.0, low=11.0, close=11.0, prev=10.0)
    reason = limit_blocked(quote, rule, "buy", 11.0)
    assert reason == "limit_up_blocked"
    assert limit_blocked(quote, rule, "sell", 11.0) is None
