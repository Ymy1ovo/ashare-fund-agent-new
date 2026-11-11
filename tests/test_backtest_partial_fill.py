"""阶段3A.1.1：部分成交专项测试。

全部使用人工构造数据，不依赖网络与真实行情库。
覆盖：部分成交后剩余被拒/延期/回测结束、多次部分成交、完全未成交拒绝、
已完成订单禁止重复撮合、状态不倒退、买入现金不足、费用一致性。
"""
from __future__ import annotations

from datetime import date

import pytest

from app.backtest.broker import Broker, append_reason
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


def _broker(config, days=5):
    return Broker(config=config, calendar=[date(2024, 1, d) for d in range(3, 3 + days)])


def _order(quantity=1000, side="buy", oid=1):
    return Order(order_id=oid, code="510300", side=side,
                 signal_date=date(2024, 1, 2), order_date=date(2024, 1, 2),
                 quantity=quantity)


# ------------------------------------------------------- 原有测试（保留）

def test_buy_reduced_by_cash_is_partial_not_filled() -> None:
    config = BacktestConfig(
        start_date="2024-01-01", end_date="2024-12-31",
        initial_cash=1500, cash_shortfall_policy="reduce",
    )
    broker = _broker(config)
    portfolio = Portfolio(initial_cash=1500)
    order = _order(1000)
    result = broker.execute(order, _quote(), _rule(), portfolio, date(2024, 1, 3))
    assert result.filled is True
    assert order.status == "partial", "只成交 100 股不能标记为 filled"
    assert order.filled_quantity == 100
    assert order.remaining_quantity == 900
    assert result.trade.quantity == 100


def test_partial_buy_remaining_is_not_double_counted() -> None:
    config = BacktestConfig(start_date="2024-01-01", end_date="2024-12-31", initial_cash=1500)
    broker = _broker(config)
    portfolio = Portfolio(initial_cash=1500)
    order = _order(1000)
    broker.execute(order, _quote(), _rule(), portfolio, date(2024, 1, 3))
    first_filled = order.filled_quantity
    broker.execute(order, _quote(), _rule(), portfolio, date(2024, 1, 4))
    assert order.filled_quantity <= 1000
    assert order.filled_quantity >= first_filled
    assert order.remaining_quantity == 1000 - order.filled_quantity


def test_partial_sell_keeps_partial_status() -> None:
    """卖出只能成交可卖数量时，状态必须是 partial 而不是 filled。"""
    config = BacktestConfig(
        start_date="2024-01-01", end_date="2024-12-31",
        initial_cash=100000, allow_partial_fill=True,
    )
    broker = _broker(config)
    portfolio = Portfolio(initial_cash=100000)
    portfolio.apply_buy("510300", 300, 10.0, fee=5.0, trade_date=date(2024, 1, 2),
                        available_date=date(2024, 1, 3))
    order = _order(500, side="sell")
    result = broker.execute(order, _quote(), _rule(), portfolio, date(2024, 1, 3))
    assert result.filled is True
    assert order.filled_quantity == 300
    assert order.remaining_quantity == 200
    assert order.status == "partial"
    assert portfolio.quantity("510300") == 0


def test_sell_rejected_when_partial_not_allowed() -> None:
    config = BacktestConfig(
        start_date="2024-01-01", end_date="2024-12-31",
        initial_cash=100000, allow_partial_fill=False,
    )
    broker = _broker(config, days=1)
    portfolio = Portfolio(initial_cash=100000)
    portfolio.apply_buy("510300", 300, 10.0, fee=5.0, trade_date=date(2024, 1, 2),
                        available_date=date(2024, 1, 3))
    order = _order(500, side="sell")
    result = broker.execute(order, _quote(), _rule(), portfolio, date(2024, 1, 3))
    assert result.filled is False
    assert result.reason == "insufficient_position"
    assert portfolio.quantity("510300") == 300
    assert order.status == "rejected"
    assert order.filled_quantity == 0


def test_remaining_quantity_property_never_negative() -> None:
    order = _order(100)
    order.filled_quantity = 100
    assert order.remaining_quantity == 0
    order.filled_quantity = 150
    assert order.remaining_quantity == 0


def test_fee_only_on_filled_quantity() -> None:
    config = BacktestConfig(start_date="2024-01-01", end_date="2024-12-31", initial_cash=1500)
    broker = _broker(config, days=1)
    portfolio = Portfolio(initial_cash=1500)
    order = _order(1000)
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
    from app.database.db import get_connection
    from tests.test_backtest_integration import _FixedStrategy, _seed_market

    dates = _seed_market(temp_db, {"510300": [10.0, 10.0, 10.0, 10.0, 10.0]})
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
    with get_connection(temp_db) as conn:
        bad = conn.execute(
            "SELECT t.order_id AS oid, SUM(t.quantity) AS q, MAX(o.quantity) AS original "
            "FROM backtest_trades t JOIN backtest_orders o "
            "ON t.run_id=o.run_id AND t.order_id=o.order_id "
            "GROUP BY t.order_id HAVING q > original"
        ).fetchall()
    assert not bad, f"存在超额成交：{bad}"


# ------------------------------------------------- 3A.1.1 新增专项测试

def test_partial_then_remainder_rejected_keeps_partial() -> None:
    """测试1：部分成交后剩余因资金不足被拒，状态必须是 partial。"""
    config = BacktestConfig(
        start_date="2024-01-01", end_date="2024-12-31",
        initial_cash=4010, cash_shortfall_policy="reduce",
    )
    broker = _broker(config)
    portfolio = Portfolio(initial_cash=4010)
    order = _order(1000)

    first = broker.execute(order, _quote(), _rule(), portfolio, date(2024, 1, 3))
    assert first.filled is True
    assert order.filled_quantity == 400
    assert order.remaining_quantity == 600
    assert order.status == "partial"

    second = broker.execute(order, _quote(), _rule(), portfolio, date(2024, 1, 4))
    assert second.filled is False
    assert second.reason == "insufficient_cash"
    assert order.filled_quantity == 400, "被拒后已成交数量必须保持不变"
    assert order.remaining_quantity == 600
    assert order.status == "partial", "已有成交的订单不能变成 rejected"
    assert "insufficient_cash" in (order.reason or "")
    assert portfolio.cash >= -1e-6


def test_partial_then_defer_then_fill_remainder() -> None:
    """测试2：部分成交 → 零成交量延期 → 成交剩余，最终 filled 且不重复成交。"""
    config = BacktestConfig(
        start_date="2024-01-01", end_date="2024-12-31",
        initial_cash=100000, allow_partial_fill=True,
    )
    broker = _broker(config)
    portfolio = Portfolio(initial_cash=100000)
    portfolio.apply_buy("510300", 400, 10.0, fee=5.0, trade_date=date(2024, 1, 2),
                        available_date=date(2024, 1, 3))
    portfolio.apply_buy("510300", 600, 10.0, fee=5.0, trade_date=date(2024, 1, 2),
                        available_date=date(2024, 1, 4))
    order = _order(1000, side="sell")

    first = broker.execute(order, _quote(), _rule(), portfolio, date(2024, 1, 3))
    assert first.filled is True
    assert order.filled_quantity == 400
    assert order.status == "partial"

    deferred = broker.execute(order, _quote(volume=0), _rule(), portfolio, date(2024, 1, 4))
    assert deferred.filled is False
    assert deferred.deferred is True
    assert order.status == "partial", "延期不能让 partial 倒退"
    assert order.filled_quantity == 400

    last = broker.execute(order, _quote(), _rule(), portfolio, date(2024, 1, 5))
    assert last.filled is True
    assert last.trade.quantity == 600
    assert order.filled_quantity == 1000
    assert order.remaining_quantity == 0
    assert order.status == "filled"
    assert order.filled_quantity <= order.quantity


def test_partial_order_unfinished_at_backtest_end(temp_db) -> None:
    """测试3：部分成交后直到回测结束都补不齐，状态必须保留 partial。"""
    from app.backtest.engine import BacktestEngine
    from app.backtest.strategies.base import TargetWeight
    from app.database.db import get_connection
    from tests.test_backtest_integration import _FixedStrategy, _seed_market

    dates = _seed_market(temp_db, {"510300": [10.0, 10.5, 10.5, 10.5, 10.5]})
    with get_connection(temp_db) as conn:
        conn.execute(
            "UPDATE etf_daily_prices SET volume=0 WHERE code=? AND trade_date>=?",
            ("510300", dates[2]),
        )
    strategy = _FixedStrategy({dates[0]: [TargetWeight("510300", 1.0)]})
    config = BacktestConfig(
        start_date=dates[0], end_date=dates[-1],
        initial_cash=2000, cash_shortfall_policy="reduce", max_defer_days=5,
    )
    result = BacktestEngine(config, strategy, db_path=temp_db).run(
        ["510300"], indicator_version=None
    )
    assert len(result.trades) == 1
    order = result.orders[0]
    assert order.filled_quantity == 100
    assert order.remaining_quantity == 100
    assert order.status == "partial", "回测结束时不能变成 unfilled / rejected / filled"


def test_multiple_partial_fills_sum_to_quantity() -> None:
    """测试4：300 + 200 + 500 三次部分成交，累计恰为原始委托量。"""
    config = BacktestConfig(
        start_date="2024-01-01", end_date="2024-12-31",
        initial_cash=100000, allow_partial_fill=True,
    )
    broker = _broker(config)
    portfolio = Portfolio(initial_cash=100000)
    for qty, avail in ((300, date(2024, 1, 3)), (200, date(2024, 1, 4)),
                       (500, date(2024, 1, 5))):
        portfolio.apply_buy("510300", qty, 10.0, fee=5.0,
                            trade_date=date(2024, 1, 2), available_date=avail)

    order = _order(1000, side="sell")
    trades = []
    for day in (3, 4, 5):
        result = broker.execute(order, _quote(), _rule(), portfolio, date(2024, 1, day))
        assert result.filled is True
        trades.append(result.trade)

    assert [t.quantity for t in trades] == [300, 200, 500]
    assert sum(t.quantity for t in trades) == 1000
    assert order.filled_quantity == 1000
    assert order.remaining_quantity == 0
    assert order.status == "filled"
    assert order.filled_quantity <= order.quantity
    assert order.fee == pytest.approx(sum(t.commission for t in trades))
    assert order.slippage_cost == pytest.approx(sum(t.slippage_cost for t in trades))


def test_full_rejection_has_zero_fill() -> None:
    """测试5：完全未成交的拒绝。"""
    config = BacktestConfig(
        start_date="2024-01-01", end_date="2024-12-31",
        initial_cash=500, cash_shortfall_policy="reduce",
    )
    broker = _broker(config)
    portfolio = Portfolio(initial_cash=500)
    order = _order(1000)
    result = broker.execute(order, _quote(), _rule(), portfolio, date(2024, 1, 3))
    assert result.filled is False
    assert result.reason == "insufficient_cash"
    assert order.filled_quantity == 0
    assert order.remaining_quantity == 1000
    assert order.status == "rejected"
    assert order.fee == 0.0
    assert portfolio.cash == 500


def test_completed_order_cannot_be_filled_again() -> None:
    """测试6：已完成订单禁止重复撮合。"""
    config = BacktestConfig(
        start_date="2024-01-01", end_date="2024-12-31",
        initial_cash=100000, cash_shortfall_policy="reduce",
    )
    broker = _broker(config)
    portfolio = Portfolio(initial_cash=100000)
    order = _order(1000)

    first = broker.execute(order, _quote(), _rule(), portfolio, date(2024, 1, 3))
    assert first.filled is True
    assert order.status == "filled"
    cash_after = portfolio.cash
    quantity_after = portfolio.quantity("510300")
    fee_after = order.fee
    slip_after = order.slippage_cost
    trades_after = broker._trade_seq

    again = broker.execute(order, _quote(), _rule(), portfolio, date(2024, 1, 4))
    assert again.filled is False
    assert again.trade is None
    assert again.reason == "already_fully_filled"
    assert order.filled_quantity == 1000
    assert order.status == "filled"
    assert portfolio.cash == pytest.approx(cash_after), "不得重复扣减现金"
    assert portfolio.quantity("510300") == quantity_after, "不得重复增加持仓"
    assert order.fee == pytest.approx(fee_after), "不得重复收取费用"
    assert order.slippage_cost == pytest.approx(slip_after)
    assert broker._trade_seq == trades_after, "不得产生新的成交记录"


def test_partial_status_never_regresses_through_lifecycle() -> None:
    """测试7：延期 → 剩余被拒 → 回测结束，状态与累计成交始终正确。"""
    config = BacktestConfig(
        start_date="2024-01-01", end_date="2024-12-31",
        initial_cash=4010, cash_shortfall_policy="reduce",
    )
    broker = _broker(config)
    portfolio = Portfolio(initial_cash=4010)
    order = _order(1000)

    broker.execute(order, _quote(), _rule(), portfolio, date(2024, 1, 3))
    assert order.status == "partial"
    assert order.filled_quantity == 400

    broker.execute(order, _quote(volume=0), _rule(), portfolio, date(2024, 1, 4))
    assert order.status == "partial"
    assert order.filled_quantity == 400

    broker.execute(order, _quote(), _rule(), portfolio, date(2024, 1, 5))
    assert order.status == "partial"
    assert order.filled_quantity == 400
    assert order.remaining_quantity == 600

    order.sync_status(terminal="unfilled")
    assert order.status == "partial", "终态收敛不能覆盖已有成交"
    assert order.filled_quantity == 400
    assert order.remaining_quantity == 600


def test_buy_partial_with_cash_shortfall_keeps_books_sane() -> None:
    """测试8：买入只买得起一部分，现金不透支、费用只按实际成交收。"""
    config = BacktestConfig(
        start_date="2024-01-01", end_date="2024-12-31",
        initial_cash=4010, cash_shortfall_policy="reduce",
    )
    broker = _broker(config)
    portfolio = Portfolio(initial_cash=4010)
    order = _order(1000)

    result = broker.execute(order, _quote(), _rule(), portfolio, date(2024, 1, 3))
    assert result.filled is True
    assert result.trade.quantity == 400
    assert order.filled_quantity == 400
    assert order.remaining_quantity == 600
    assert order.status == "partial"

    expected_gross = 400 * result.trade.price
    expected_fee = max(expected_gross * config.costs.commission_rate, config.costs.min_commission)
    assert result.trade.commission == pytest.approx(expected_fee)
    assert order.fee == pytest.approx(expected_fee)
    assert portfolio.cash == pytest.approx(4010 - expected_gross - expected_fee)
    assert portfolio.cash >= 0
    assert portfolio.quantity("510300") == 400


def test_fee_equals_sum_of_trades_across_partial_fills() -> None:
    """费用一致性：订单累计费用 == 各笔实际成交费用之和。"""
    config = BacktestConfig(
        start_date="2024-01-01", end_date="2024-12-31",
        initial_cash=4010, cash_shortfall_policy="reduce",
    )
    broker = _broker(config)
    portfolio = Portfolio(initial_cash=4010)
    order = _order(1000)

    first = broker.execute(order, _quote(), _rule(), portfolio, date(2024, 1, 3))
    portfolio.cash += 10000
    second = broker.execute(order, _quote(), _rule(), portfolio, date(2024, 1, 4))

    assert first.filled is True and second.filled is True
    assert order.filled_quantity == 1000
    assert order.status == "filled"
    assert order.fee == pytest.approx(first.trade.commission + second.trade.commission)
    assert order.slippage_cost == pytest.approx(
        first.trade.slippage_cost + second.trade.slippage_cost
    )
    assert portfolio.total_fees == pytest.approx(order.fee)


def test_append_reason_is_idempotent() -> None:
    """原因拼接不重复追加，便于审计。"""
    assert append_reason(None, "a") == "a"
    assert append_reason("x", "a") == "x;a"
    assert append_reason("x;a", "a") == "x;a"
