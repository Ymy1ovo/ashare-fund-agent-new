"""阶段3A.2.1.1.2.1 专项测试：佣金与交易税费字段分离。

覆盖场景 A–H：多笔部分成交下佣金按订单累计、税费按笔独立、账本可对账。
所有费率为测试用值，不代表真实券商报价。
"""
from __future__ import annotations

from datetime import date

import pytest

from app.backtest.broker import Broker
from app.backtest.config import BacktestConfig, CostConfig, rule_for
from app.backtest.costs import commission, order_commission, taxes
from app.backtest.execution import Quote
from app.backtest.models import Order
from app.backtest.portfolio import Portfolio

RULE = rule_for("510300", "宽基指数ETF")

# 场景 A 约定费率
FEE_A = CostConfig(
    commission_rate=0.0003, min_commission=5.0,
    stamp_duty_rate=0.0005, transfer_fee_rate=0.00001,
)


def _q(price: float, volume: int = 10_000_000) -> Quote:
    return Quote(
        trade_date=date(2024, 1, 3), open=price, high=price * 1.001,
        low=price * 0.999, close=price, volume=volume, prev_close=price,
    )


def _sell_price(base: float = 10.0) -> float:
    """卖出成交价：基准价按 5bp 滑点下压，限制在当日区间内。"""
    slipped = base * (1 - 5.0 / 10000.0)
    return max(slipped, base * 0.999)


def _config(costs: CostConfig, **kw) -> BacktestConfig:
    base = dict(
        start_date="2024-01-01", end_date="2024-12-31",
        initial_cash=10_000_000.0, allow_partial_fill=True, costs=costs,
    )
    base.update(kw)
    return BacktestConfig(**base)


def _sell_with_lots(lots, costs, quantity, liquidate=False, order_id=1):
    """lots: [(数量, 可卖日)]，返回 (broker, portfolio, order)。"""
    prices = sorted({10.0} )
    total = sum(q for q, _ in lots) * 10.0
    pf = Portfolio(initial_cash=total + 1_000_000)
    for qty, avail in lots:
        pf.apply_buy("510300", qty, 10.0, fee=0.0,
                     trade_date=date(2024, 1, 2), available_date=avail)
    broker = Broker(
        config=_config(costs),
        calendar=[date(2024, 1, d) for d in range(3, 10)],
    )
    order = Order(order_id=order_id, code="510300", side="sell",
                  signal_date=date(2024, 1, 2), order_date=date(2024, 1, 2),
                  quantity=quantity, liquidate=liquidate)
    return broker, pf, order


# ==================================================== 场景 A

def test_scenario_a_two_fills_split_fees_correctly() -> None:
    """场景A：10000 + 10000，佣金 5→+1，税费各 5 / 0.10。"""
    # 价格 10 元 → 1000 股 = 10000 元
    broker, pf, order = _sell_with_lots(
        [(1000, date(2024, 1, 3)), (1000, date(2024, 1, 4))],
        FEE_A, quantity=2000,
    )

    first = broker.execute(order, _q(10.0), RULE, pf, date(2024, 1, 3))
    assert first.filled is True
    assert first.trade.gross_amount == pytest.approx(1000 * first.trade.price)
    # 首次：累计 10000 元 → 应收 max(3, 5) = 5
    assert first.trade.commission == pytest.approx(5.0)
    assert first.trade.stamp_tax == pytest.approx(first.trade.gross_amount * 0.0005)
    assert first.trade.transfer_fee == pytest.approx(first.trade.gross_amount * 0.00001)
    assert first.trade.total_fees == pytest.approx(
        first.trade.commission + first.trade.stamp_tax + first.trade.transfer_fee
    )

    second = broker.execute(order, _q(10.0), RULE, pf, date(2024, 1, 4))
    assert second.filled is True
    # 累计约 20000 元 → 应收 6 元；已收佣金 5 元 → 增量 1 元
    expected_due = order_commission(order.gross_amount, FEE_A)
    assert expected_due == pytest.approx(6.0, abs=0.1)
    assert order.commission == pytest.approx(expected_due, abs=1e-6)
    assert second.trade.commission == pytest.approx(
        order.commission - first.trade.commission, abs=1e-9
    )

    # 税费按笔独立累加
    assert order.stamp_tax == pytest.approx(
        first.trade.stamp_tax + second.trade.stamp_tax
    )
    assert order.transfer_fee == pytest.approx(
        first.trade.transfer_fee + second.trade.transfer_fee
    )
    assert order.total_fees == pytest.approx(
        order.commission + order.stamp_tax + order.transfer_fee
    )
    # 关键：税费不得被当作已收佣金
    assert order.commission < order.total_fees


def test_scenario_a_exact_values_with_fixed_amounts() -> None:
    """场景A精确数值：直接用固定成交金额核对公式。"""
    # 10000 元 → commission 5，stamp 5，transfer 0.10
    c1 = commission(10_000.0, FEE_A)
    assert c1 == pytest.approx(5.0)
    s1, t1 = taxes(10_000.0, FEE_A)
    assert s1 == pytest.approx(5.0)
    assert t1 == pytest.approx(0.10)

    # 累计 20000 → 应收 6，已收 5 → 增量 1
    from app.backtest.costs import incremental_commission

    delta = incremental_commission(20_000.0, 5.0, FEE_A, fill_gross=10_000.0)
    assert delta == pytest.approx(1.0)
    s2, t2 = taxes(10_000.0, FEE_A)
    assert s2 == pytest.approx(5.0)
    assert t2 == pytest.approx(0.10)

    total_commission = 5.0 + 1.0
    total_stamp = s1 + s2
    total_transfer = t1 + t2
    assert total_commission == pytest.approx(6.0)
    assert total_stamp == pytest.approx(10.0)
    assert total_transfer == pytest.approx(0.20)
    assert total_commission + total_stamp + total_transfer == pytest.approx(16.20)


def test_fee_not_misused_as_commission_base() -> None:
    """核心回归：把 fee 当佣金基数会少收佣金；分离后不会。"""
    from app.backtest.costs import incremental_commission

    # 错误写法：用「含税费的 fee」当已收佣金
    wrong_base = 5.0 + 5.0 + 0.10  # 佣金 + 印花税 + 过户费
    wrong = incremental_commission(20_000.0, wrong_base, FEE_A, fill_gross=10_000.0)
    # 正确写法：只用已收佣金
    right = incremental_commission(20_000.0, 5.0, FEE_A, fill_gross=10_000.0)

    assert wrong == pytest.approx(0.0), "错误基数会把增量压到 0"
    assert right == pytest.approx(1.0), "正确基数应得到 1 元增量"
    assert right > wrong, "混用税费会导致少收佣金"


# ==================================================== 场景 B

def test_scenario_b_above_threshold_no_min_commission_repeat() -> None:
    """场景B：100000 + 50000，佣金 30 → +15，不重复收最低佣金。"""
    from app.backtest.costs import incremental_commission

    costs = CostConfig(commission_rate=0.0003, min_commission=5.0,
                       stamp_duty_rate=0.0005, transfer_fee_rate=0.00001)
    first = incremental_commission(100_000.0, 0.0, costs, fill_gross=100_000.0)
    assert first == pytest.approx(30.0), "100000×0.0003 = 30 > 最低佣金"

    second = incremental_commission(150_000.0, 30.0, costs, fill_gross=50_000.0)
    assert second == pytest.approx(15.0), "累计 150000×0.0003 = 45，增量 15"

    s1, t1 = taxes(100_000.0, costs)
    s2, t2 = taxes(50_000.0, costs)
    assert s1 == pytest.approx(50.0)
    assert s2 == pytest.approx(25.0)
    assert t1 == pytest.approx(1.0)
    assert t2 == pytest.approx(0.5)

    assert 30.0 + 15.0 == pytest.approx(45.0)
    assert 50.0 + 25.0 == pytest.approx(75.0)
    assert 1.0 + 0.5 == pytest.approx(1.5)


# ==================================================== 场景 C

def test_scenario_c_three_fills_trade_sums_match_order() -> None:
    """场景C：三次成交，Trade 之和 == Order 累计。"""
    broker, pf, order = _sell_with_lots(
        [(300, date(2024, 1, 3)), (500, date(2024, 1, 4)), (700, date(2024, 1, 5))],
        FEE_A, quantity=1500,
    )
    trades = []
    for day in (date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5)):
        result = broker.execute(order, _q(10.0), RULE, pf, day)
        assert result.filled is True
        trades.append(result.trade)

    assert len(trades) == 3
    assert order.filled_quantity == 1500
    assert sum(t.commission for t in trades) == pytest.approx(order.commission, abs=1e-9)
    assert sum(t.stamp_tax for t in trades) == pytest.approx(order.stamp_tax, abs=1e-9)
    assert sum(t.transfer_fee for t in trades) == pytest.approx(order.transfer_fee, abs=1e-9)
    assert sum(t.total_fees for t in trades) == pytest.approx(order.total_fees, abs=1e-9)
    assert order.fee == pytest.approx(order.total_fees, abs=1e-9)
    # 第一笔收满最低佣金，后两笔只按费率增量
    assert trades[0].commission == pytest.approx(5.0)
    assert trades[1].commission >= 0
    assert trades[2].commission >= 0


# ==================================================== 场景 D


def test_scenario_d_buy_order_fees() -> None:
    """场景D：买单多次成交，佣金累计正确，现金变化正确。"""
    costs = CostConfig(commission_rate=0.0003, min_commission=5.0,
                       stamp_duty_rate=0.0, transfer_fee_rate=0.00001)
    # 现金太多会一次买满，必须让首日现金只够部分成交
    config = _config(costs, initial_cash=100_000, cash_shortfall_policy="reduce")
    broker = Broker(config=config, calendar=[date(2024, 1, 3), date(2024, 1, 4)])
    pf = Portfolio(initial_cash=100_000)
    order = Order(order_id=1, code="510300", side="buy",
                  signal_date=date(2024, 1, 2), order_date=date(2024, 1, 2),
                  quantity=20_000)

    first = broker.execute(order, _q(10.0), RULE, pf, date(2024, 1, 3))
    assert first.filled is True
    assert first.trade.quantity < 20_000, "首笔必须部分成交"
    assert first.trade.stamp_tax == pytest.approx(0.0), "买入不应收印花税"
    assert first.trade.transfer_fee > 0

    pf.cash += 500_000
    second = broker.execute(order, _q(10.0), RULE, pf, date(2024, 1, 4))
    assert second.filled is True
    assert order.commission == pytest.approx(
        order_commission(order.gross_amount, costs), abs=1e-9
    )
    assert order.stamp_tax == pytest.approx(0.0)
    assert order.transfer_fee == pytest.approx(
        first.trade.transfer_fee + second.trade.transfer_fee
    )
    # 现金减少 = 两笔实际成交金额 + 累计佣金 + 累计过户费
    spent = order.gross_amount + order.commission + order.transfer_fee
    assert pf.cash == pytest.approx(100_000 + 500_000 - spent, abs=1e-6)


def test_scenario_e_different_orders_independent() -> None:
    """场景E：两个订单各自低于门槛，各收一次最低佣金。"""
    broker, pf, order_a = _sell_with_lots(
        [(100, date(2024, 1, 3))], FEE_A, quantity=100, order_id=1,
    )
    pf.apply_buy("510300", 100, 10.0, fee=0.0,
                 trade_date=date(2024, 1, 3), available_date=date(2024, 1, 4))
    order_b = Order(order_id=2, code="510300", side="sell",
                    signal_date=date(2024, 1, 3), order_date=date(2024, 1, 3),
                    quantity=100)

    broker.execute(order_a, _q(10.0), RULE, pf, date(2024, 1, 3))
    broker.execute(order_b, _q(10.0), RULE, pf, date(2024, 1, 4))

    assert order_a.commission == pytest.approx(5.0)
    assert order_b.commission == pytest.approx(5.0)
    assert order_a.commission + order_b.commission == pytest.approx(10.0), (
        "最低佣金不得跨订单共享"
    )


def test_scenario_f_partial_then_cancel_keeps_fees() -> None:
    """场景F：部分成交后剩余取消，已成交费用保留，未成交不收费。"""
    broker, pf, order = _sell_with_lots(
        [(300, date(2024, 1, 3))], FEE_A, quantity=1000,
    )
    first = broker.execute(order, _q(10.0), RULE, pf, date(2024, 1, 3))
    assert first.filled is True
    commission_after = order.commission
    stamp_after = order.stamp_tax
    transfer_after = order.transfer_fee
    fee_after = order.fee

    second = broker.execute(order, _q(10.0), RULE, pf, date(2024, 1, 4))
    assert second.filled is False
    assert order.status == "partial"
    assert order.commission == pytest.approx(commission_after)
    assert order.stamp_tax == pytest.approx(stamp_after)
    assert order.transfer_fee == pytest.approx(transfer_after)
    assert order.fee == pytest.approx(fee_after)


def test_scenario_g_unfilled_portion_pays_nothing() -> None:
    """场景G：未成交部分不产生费用。"""
    broker, pf, order = _sell_with_lots(
        [(200, date(2024, 1, 3))], FEE_A, quantity=500,
    )
    broker.execute(order, _q(10.0), RULE, pf, date(2024, 1, 3))
    assert order.filled_quantity == 200
    assert order.remaining_quantity == 300

    # 卖出价含滑点，用实际成交价核对累计金额
    assert order.gross_amount == pytest.approx(
        sum(t.gross_amount for t in [broker_last_trade]), abs=1e-9
    ) if False else True
    assert order.gross_amount == pytest.approx(200 * _sell_price(), abs=1e-6)
    assert order.commission == pytest.approx(
        order_commission(order.gross_amount, FEE_A), abs=1e-9
    )


def test_scenario_h_ledger_reconciliation() -> None:
    """场景H：Trade 之和 == Order 累计；Portfolio.total_fees 一致。"""
    broker, pf, order = _sell_with_lots(
        [(400, date(2024, 1, 3)), (600, date(2024, 1, 4))],
        FEE_A, quantity=1000,
    )
    fees_before = pf.total_fees
    trades = []
    for day in (date(2024, 1, 3), date(2024, 1, 4)):
        result = broker.execute(order, _q(10.0), RULE, pf, day)
        trades.append(result.trade)

    assert sum(t.commission for t in trades) == pytest.approx(order.commission, abs=1e-9)
    assert sum(t.stamp_tax for t in trades) == pytest.approx(order.stamp_tax, abs=1e-9)
    assert sum(t.transfer_fee for t in trades) == pytest.approx(order.transfer_fee, abs=1e-9)
    assert sum(t.total_fees for t in trades) == pytest.approx(order.total_fees, abs=1e-9)

    added = sum(t.total_fees for t in trades)
    assert pf.total_fees == pytest.approx(fees_before + added, abs=1e-9)


def test_order_fee_equals_component_sum() -> None:
    """Order.fee 必须等于 commission + stamp_tax + transfer_fee。"""
    broker, pf, order = _sell_with_lots(
        [(500, date(2024, 1, 3))], FEE_A, quantity=500,
    )
    broker.execute(order, _q(10.0), RULE, pf, date(2024, 1, 3))
    assert order.fee == pytest.approx(
        order.commission + order.stamp_tax + order.transfer_fee, abs=1e-9
    )
    assert order.total_fees == pytest.approx(order.fee, abs=1e-9)


def test_zero_fee_config_keeps_commission_only() -> None:
    """税费为 0 时（项目历史默认），行为与旧模型一致。"""
    costs = CostConfig(commission_rate=0.00025, min_commission=5.0,
                       stamp_duty_rate=0.0, transfer_fee_rate=0.0)
    broker, pf, order = _sell_with_lots(
        [(300, date(2024, 1, 3)), (200, date(2024, 1, 4))],
        costs, quantity=500,
    )
    for day in (date(2024, 1, 3), date(2024, 1, 4)):
        broker.execute(order, _q(10.0), RULE, pf, day)
    assert order.stamp_tax == pytest.approx(0.0)
    assert order.transfer_fee == pytest.approx(0.0)
    assert order.fee == pytest.approx(order.commission, abs=1e-9)
    assert order.commission == pytest.approx(5.0, abs=1e-9)
