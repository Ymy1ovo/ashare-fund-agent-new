"""阶段3A.2.1.1.2 专项测试。

覆盖：订单累计佣金模型、零碎股完整清仓、统一收益样本统计口径。
"""
from __future__ import annotations

from datetime import date

import pytest

from app.backtest.broker import Broker
from app.backtest.config import BacktestConfig, CostConfig, rule_for
from app.backtest.costs import (
    commission,
    incremental_commission,
    order_commission,
    sell_quantity,
)
from app.backtest.execution import Quote
from app.backtest.models import Order
from app.backtest.portfolio import Portfolio


def _q(price=10.0, volume=1_000_000):
    return Quote(
        trade_date=date(2024, 1, 3), open=price, high=price * 1.02,
        low=price * 0.98, close=price, volume=volume, prev_close=price,
    )


RULE = rule_for("510300", "宽基指数ETF")


def _config(**kwargs):
    base = dict(
        start_date="2024-01-01", end_date="2024-12-31",
        initial_cash=1_000_000.0, allow_partial_fill=True,
    )
    base.update(kwargs)
    return BacktestConfig(**base)


def _portfolio_with(holdings, price=10.0):
    total = sum(holdings) * price
    pf = Portfolio(initial_cash=total + 50_000)
    for qty in holdings:
        pf.apply_buy("510300", qty, price, fee=5.0,
                     trade_date=date(2024, 1, 2), available_date=date(2024, 1, 3))
    return pf


def _portfolio_staged(batches, price=10.0):
    """batches: [(数量, 可卖日), ...]，用于制造分日可卖的多次成交。"""
    total = sum(qty for qty, _ in batches) * price
    pf = Portfolio(initial_cash=total + 50_000)
    for qty, avail in batches:
        pf.apply_buy("510300", qty, price, fee=5.0,
                     trade_date=date(2024, 1, 2), available_date=avail)
    return pf


def _sell(order_id=1, quantity=100, liquidate=False):
    return Order(order_id=order_id, code="510300", side="sell",
                 signal_date=date(2024, 1, 2), order_date=date(2024, 1, 2),
                 quantity=quantity, liquidate=liquidate)


# ==================================================== 任务1：订单累计佣金

def test_order_commission_uses_cumulative_amount() -> None:
    """订单累计佣金 = max(累计金额 × 费率, 最低佣金)。"""
    costs = CostConfig(commission_rate=0.00025, min_commission=5.0)
    assert order_commission(1000.0, costs) == pytest.approx(5.0)
    assert order_commission(1_000_000.0, costs) == pytest.approx(250.0)
    assert order_commission(0.0, costs) == pytest.approx(0.0)


def test_incremental_commission_only_charges_difference() -> None:
    """增量佣金 = 累计应收 - 已收。"""
    costs = CostConfig(commission_rate=0.00025, min_commission=5.0)
    # 第一次成交 3000 元 → 应收 5.0，已收 0 → 增量 5.0
    first = incremental_commission(3000.0, 0.0, costs, fill_gross=3000.0)
    assert first == pytest.approx(5.0)
    # 第二次成交 2000 元 → 累计 5000 元，应收仍 5.0 → 增量 0
    second = incremental_commission(5000.0, 5.0, costs, fill_gross=2000.0)
    assert second == pytest.approx(0.0)
    # 累计到 100 万元 → 应收 250，已收 5 → 增量 245
    third = incremental_commission(1_000_000.0, 5.0, costs, fill_gross=995_000.0)
    assert third == pytest.approx(245.0)


def test_per_fill_model_charges_each_fill() -> None:
    """per_fill 模型每笔都收最低佣金，用于对比。"""
    costs = CostConfig(commission_rate=0.00025, min_commission=5.0)
    first = incremental_commission(3000.0, 0.0, costs, fill_gross=3000.0,
                                   model="per_fill")
    second = incremental_commission(5000.0, 5.0, costs, fill_gross=2000.0,
                                    model="per_fill")
    assert first == pytest.approx(5.0)
    assert second == pytest.approx(5.0)


def test_invalid_commission_model_rejected() -> None:
    costs = CostConfig(commission_rate=0.00025, min_commission=5.0)
    with pytest.raises(ValueError, match="未知的 min_commission_model"):
        incremental_commission(1000.0, 0.0, costs, fill_gross=1000.0, model="weird")


def test_same_order_two_fills_charge_min_commission_once() -> None:
    """测试1：同一订单 300 + 200 两次成交，最低佣金只收一次。"""
    config = _config()
    broker = Broker(config=config, calendar=[date(2024, 1, 3), date(2024, 1, 4)])
    pf = _portfolio_staged([(300, date(2024, 1, 3)), (200, date(2024, 1, 4))])
    order = _sell(quantity=500)

    first = broker.execute(order, _q(), RULE, pf, date(2024, 1, 3))
    assert first.filled is True
    assert first.trade.quantity == 300
    fee_after_first = order.fee
    assert fee_after_first == pytest.approx(5.0), "第一次应收满最低佣金"

    second = broker.execute(order, _q(), RULE, pf, date(2024, 1, 4))
    assert second.filled is True
    total_filled = order.filled_quantity
    # 累计金额 = 500 × 10.00x ≈ 5002.5 元 → 费率 0.025% = 1.25 元 < 5 元
    assert order.fee == pytest.approx(5.0), "第二次不应再收最低佣金"
    assert order.gross_amount == pytest.approx(second.trade.gross_amount + first.trade.gross_amount)
    assert pf.quantity("510300") == 0


def test_same_order_three_fills_commission_increments() -> None:
    """测试2：同一订单三次成交，每次增量正确、总额等于应收。"""
    config = _config()
    broker = Broker(config=config, calendar=[
        date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5),
    ])
    pf = _portfolio_staged([
        (100, date(2024, 1, 3)), (100, date(2024, 1, 4)), (100, date(2024, 1, 5)),
    ])
    order = _sell(quantity=300)

    fees = []
    for day in (date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5)):
        result = broker.execute(order, _q(), RULE, pf, day)
        assert result.filled is True
        fees.append(result.trade.commission)

    assert fees[0] == pytest.approx(5.0), "第一笔收满最低佣金"
    assert sum(fees) == pytest.approx(order.fee), "各笔佣金之和 == 订单累计 fee"
    expected = order_commission(order.gross_amount, config.costs)
    assert order.fee == pytest.approx(expected)


def test_fee_above_minimum_only_rate_after_threshold() -> None:
    """测试3：首笔已超最低门槛，后续只按费率增加。"""
    config = _config()
    broker = Broker(config=config, calendar=[date(2024, 1, 3), date(2024, 1, 4)])
    # 首笔金额 4 万元 → 佣金 10 元 > 5 元
    pf = _portfolio_staged([(4000, date(2024, 1, 3)), (4000, date(2024, 1, 4))])
    order = _sell(quantity=8000)

    first = broker.execute(order, _q(), RULE, pf, date(2024, 1, 3))
    assert first.trade.commission > 5.0
    first_fee = order.fee

    second = broker.execute(order, _q(), RULE, pf, date(2024, 1, 4))
    assert second.filled is True
    # 累计应收 - 已收
    expected_total = order_commission(order.gross_amount, config.costs)
    assert order.fee == pytest.approx(expected_total)
    assert order.fee > first_fee


def test_different_orders_each_pay_min_commission() -> None:
    """测试4：不同订单各收一次最低佣金，不共享额度。"""
    config = _config()
    broker = Broker(config=config, calendar=[date(2024, 1, 3), date(2024, 1, 4)])
    pf = _portfolio_with([300, 300])
    order_a = _sell(order_id=1, quantity=300)
    order_b = _sell(order_id=2, quantity=300)

    broker.execute(order_a, _q(), RULE, pf, date(2024, 1, 3))
    broker.execute(order_b, _q(), RULE, pf, date(2024, 1, 4))
    assert order_a.fee == pytest.approx(5.0)
    assert order_b.fee == pytest.approx(5.0)
    assert pf.quantity("510300") == 0


def test_partial_then_cancelled_fee_not_refunded() -> None:
    """测试5：部分成交后剩余被取消，已收佣金不回退。"""
    config = _config()
    broker = Broker(config=config, calendar=[date(2024, 1, 3), date(2024, 1, 4)])
    pf = _portfolio_with([300])
    order = _sell(quantity=500)

    first = broker.execute(order, _q(), RULE, pf, date(2024, 1, 3))
    assert first.filled is True
    assert order.filled_quantity == 300
    fee_after = order.fee
    assert fee_after == pytest.approx(5.0)

    # 第二天没有可卖持仓 → 剩余被拒
    second = broker.execute(order, _q(), RULE, pf, date(2024, 1, 4))
    assert second.filled is False
    assert order.status == "partial"
    assert order.fee == pytest.approx(fee_after), "已收佣金不回退"


def test_zero_fill_order_pays_nothing() -> None:
    """测试6：完全未成交佣金为 0。"""
    config = _config(initial_cash=100)
    broker = Broker(config=config, calendar=[date(2024, 1, 3)])
    pf = Portfolio(initial_cash=100)
    order = Order(order_id=1, code="510300", side="buy",
                  signal_date=date(2024, 1, 2), order_date=date(2024, 1, 2),
                  quantity=1000)
    result = broker.execute(order, _q(), RULE, pf, date(2024, 1, 3))
    assert result.filled is False
    assert order.fee == 0.0
    assert order.filled_quantity == 0


def test_buy_order_multi_fill_commission() -> None:
    """测试7（买入）：同一买单多次部分成交，最低佣金只收一次。"""
    config = _config(initial_cash=20_000, cash_shortfall_policy="reduce")
    broker = Broker(config=config, calendar=[date(2024, 1, 3), date(2024, 1, 4)])
    pf = Portfolio(initial_cash=20_000)
    order = Order(order_id=1, code="510300", side="buy",
                  signal_date=date(2024, 1, 2), order_date=date(2024, 1, 2),
                  quantity=5000)

    first = broker.execute(order, _q(), RULE, pf, date(2024, 1, 3))
    assert first.filled is True
    assert first.trade.commission == pytest.approx(5.0)
    fee_first = order.fee

    pf.cash += 50_000
    second = broker.execute(order, _q(), RULE, pf, date(2024, 1, 4))
    assert second.filled is True
    expected_total = order_commission(order.gross_amount, config.costs)
    assert order.fee == pytest.approx(expected_total)
    assert order.fee >= fee_first


def test_sell_order_multi_fill_commission() -> None:
    """测试7（卖出）：同一卖单多次部分成交，最低佣金只收一次。"""
    config = _config()
    broker = Broker(config=config, calendar=[date(2024, 1, 3), date(2024, 1, 4)])
    pf = _portfolio_with([250, 250])
    order = _sell(quantity=500)

    broker.execute(order, _q(), RULE, pf, date(2024, 1, 3))
    broker.execute(order, _q(), RULE, pf, date(2024, 1, 4))
    assert order.filled_quantity == 500
    assert order.fee == pytest.approx(order_commission(order.gross_amount, config.costs))


def test_trade_fees_sum_equals_order_fee() -> None:
    """测试8：成交记录 commission 之和等于订单累计 fee。"""
    config = _config()
    broker = Broker(config=config, calendar=[
        date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5),
    ])
    pf = _portfolio_staged([
        (100, date(2024, 1, 3)), (100, date(2024, 1, 4)), (100, date(2024, 1, 5)),
    ])
    order = _sell(quantity=300)

    trades = []
    for day in (date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5)):
        result = broker.execute(order, _q(), RULE, pf, day)
        trades.append(result.trade)
    assert sum(t.commission for t in trades) == pytest.approx(order.fee)


def test_portfolio_total_fees_equals_sum_of_trades() -> None:
    """测试9：Portfolio.total_fees 等于所有成交费用之和。"""
    config = _config()
    broker = Broker(config=config, calendar=[date(2024, 1, 3), date(2024, 1, 4)])
    pf = _portfolio_staged([(300, date(2024, 1, 3)), (200, date(2024, 1, 4))])
    initial_fees = pf.total_fees
    order = _sell(quantity=500)

    trades = []
    for day in (date(2024, 1, 3), date(2024, 1, 4)):
        result = broker.execute(order, _q(), RULE, pf, day)
        if result.trade:
            trades.append(result.trade)
    added = sum(t.commission for t in trades)
    assert pf.total_fees == pytest.approx(initial_fees + added)


def test_completed_order_cannot_add_more_fee() -> None:
    """测试10：已完成订单重复撮合不加成交也不加佣金。"""
    config = _config()
    broker = Broker(config=config, calendar=[date(2024, 1, 3), date(2024, 1, 4)])
    pf = _portfolio_with([300])
    order = _sell(quantity=300)

    broker.execute(order, _q(), RULE, pf, date(2024, 1, 3))
    fee_after = order.fee
    again = broker.execute(order, _q(), RULE, pf, date(2024, 1, 4))
    assert again.filled is False
    assert again.trade is None
    assert order.fee == pytest.approx(fee_after)
    assert order.filled_quantity == 300


def test_stamp_duty_and_transfer_fee_separate_from_min_commission() -> None:
    """印花税、过户费独立计算，不参与最低佣金取 max。"""
    from app.backtest.costs import taxes

    costs = CostConfig(
        commission_rate=0.00025, min_commission=5.0,
        stamp_duty_rate=0.001, transfer_fee_rate=0.00001,
    )
    gross = 1000.0
    base_commission = commission(gross, costs)
    assert base_commission == pytest.approx(5.0), "最低佣金只作用于佣金本身"
    stamp, transfer = taxes(gross, costs)
    assert stamp == pytest.approx(1.0)
    assert transfer == pytest.approx(0.01)
    assert base_commission + stamp + transfer == pytest.approx(6.01)


# ==================================================== 任务2：零碎股完整清仓

def test_sell_quantity_liquidate_merges_odd_lot() -> None:
    """清仓：整手与零股合并成一笔，一次卖完。"""
    assert sell_quantity(130399.7, 130400, 100, liquidate=True) == 130400
    assert sell_quantity(537, 537, 100, liquidate=True) == 537
    assert sell_quantity(1237, 1237, 100, liquidate=True) == 1237
    assert sell_quantity(99, 99, 100, liquidate=True) == 99
    assert sell_quantity(100, 100, 100, liquidate=True) == 100


def test_sell_quantity_partial_reduce_uses_whole_lots() -> None:
    """部分减仓：按整手，剩余持仓保留。"""
    assert sell_quantity(500, 1237, 100, liquidate=False) == 500
    assert sell_quantity(130399.7, 130400, 100, liquidate=False) == 130300


def test_sell_quantity_below_one_lot_partial() -> None:
    """部分减仓时若可卖不足一手，允许整笔卖出该零股。"""
    assert sell_quantity(37, 37, 100, liquidate=False) == 37
    assert sell_quantity(99, 99, 100, liquidate=False) == 99


def test_sell_quantity_never_exceeds_available() -> None:
    for raw, avail, liq in (
        (5000, 300, False), (5000, 120, True), (100, 0, True), (0, 100, False),
    ):
        assert sell_quantity(raw, avail, 100, liquidate=liq) <= avail


def test_liquidate_130400_no_residue() -> None:
    """持仓 130400，策略算出 130399.7 清仓 → 不残留 1 份。"""
    config = _config()
    broker = Broker(config=config, calendar=[date(2024, 1, 3)])
    pf = _portfolio_with([130_000, 400])
    order = _sell(quantity=130_400, liquidate=True)

    result = broker.execute(order, _q(), RULE, pf, date(2024, 1, 3))
    assert result.filled is True
    assert result.trade.quantity == 130_400
    assert pf.quantity("510300") == 0, "清仓后不得残留任何份额"
    assert order.remaining_quantity == 0


def test_liquidate_537_full_clear() -> None:
    config = _config()
    broker = Broker(config=config, calendar=[date(2024, 1, 3)])
    pf = _portfolio_with([537])
    order = _sell(quantity=537, liquidate=True)
    broker.execute(order, _q(), RULE, pf, date(2024, 1, 3))
    assert pf.quantity("510300") == 0


def test_liquidate_1237_full_clear() -> None:
    config = _config()
    broker = Broker(config=config, calendar=[date(2024, 1, 3)])
    pf = _portfolio_with([1237])
    order = _sell(quantity=1237, liquidate=True)
    broker.execute(order, _q(), RULE, pf, date(2024, 1, 3))
    assert pf.quantity("510300") == 0


def test_partial_reduce_1237_keeps_737() -> None:
    """持仓 1237 只卖 500 → 剩 737。"""
    config = _config()
    broker = Broker(config=config, calendar=[date(2024, 1, 3)])
    pf = _portfolio_with([1237])
    order = _sell(quantity=500, liquidate=False)
    broker.execute(order, _q(), RULE, pf, date(2024, 1, 3))
    assert pf.quantity("510300") == 737


def test_partial_reduce_537_then_clear_37() -> None:
    """持仓 537 卖 500 剩 37，37 必须能一次清掉。"""
    config = _config()
    broker = Broker(config=config, calendar=[date(2024, 1, 3), date(2024, 1, 4)])
    pf = _portfolio_with([537])
    first = _sell(order_id=1, quantity=500, liquidate=False)
    broker.execute(first, _q(), RULE, pf, date(2024, 1, 3))
    assert pf.quantity("510300") == 37

    clear = _sell(order_id=2, quantity=37, liquidate=True)
    result = broker.execute(clear, _q(), RULE, pf, date(2024, 1, 4))
    assert result.filled is True
    assert result.trade.quantity == 37
    assert pf.quantity("510300") == 0


def test_liquidate_99_and_100() -> None:
    for qty in (99, 100):
        config = _config()
        broker = Broker(config=config, calendar=[date(2024, 1, 3)])
        pf = _portfolio_with([qty])
        order = _sell(quantity=qty, liquidate=True)
        result = broker.execute(order, _q(), RULE, pf, date(2024, 1, 3))
        assert result.trade.quantity == qty
        assert pf.quantity("510300") == 0


def test_no_tiny_residual_orders_from_float_error() -> None:
    """浮点误差不得生成 1 份、2 份的残余订单。"""
    config = _config()
    broker = Broker(config=config, calendar=[date(2024, 1, 3)])
    pf = _portfolio_with([130_400])
    # 策略典型输出：权重 × 数量产生 x.9999 或 x.0001
    for raw in (130_399.7, 130_400.0001, 130_399.9999):
        pf_qty = pf.quantity("510300")
        qty = sell_quantity(raw, pf_qty, 100, liquidate=True)
        assert qty == pf_qty, f"raw={raw} 时清仓数量应为全部持仓 {pf_qty}，实际 {qty}"


def test_t_plus_one_still_enforced_on_liquidate() -> None:
    """清仓仍受 T+1 可卖约束，只卖当日可卖部分。"""
    config = _config()
    broker = Broker(config=config, calendar=[date(2024, 1, 3), date(2024, 1, 4)])
    pf = Portfolio(initial_cash=100_000)
    pf.apply_buy("510300", 300, 10.0, fee=5.0,
                 trade_date=date(2024, 1, 2), available_date=date(2024, 1, 3))
    pf.apply_buy("510300", 200, 10.0, fee=5.0,
                 trade_date=date(2024, 1, 2), available_date=date(2024, 1, 4))
    order = _sell(quantity=500, liquidate=True)

    first = broker.execute(order, _q(), RULE, pf, date(2024, 1, 3))
    assert first.trade.quantity == 300, "当日只能卖 T+1 可卖部分"
    assert pf.quantity("510300") == 200

    second = broker.execute(order, _q(), RULE, pf, date(2024, 1, 4))
    assert second.trade.quantity == 200
    assert pf.quantity("510300") == 0
    assert order.filled_quantity <= order.quantity


def test_ledger_consistency_after_liquidation() -> None:
    """清仓后现金、持仓、订单、成交账本一致。"""
    config = _config()
    broker = Broker(config=config, calendar=[date(2024, 1, 3)])
    pf = _portfolio_with([1237])
    cash_before = pf.cash
    order = _sell(quantity=1237, liquidate=True)

    result = broker.execute(order, _q(), RULE, pf, date(2024, 1, 3))
    trade = result.trade
    assert trade.quantity == order.filled_quantity == 1237
    assert pf.cash == pytest.approx(
        cash_before + trade.gross_amount - trade.commission
    )
    assert pf.cash >= 0
    assert order.fee == pytest.approx(trade.commission)
    assert order.remaining_quantity == 0


# ==================================================== 任务3：统一统计口径

def _make_daily(navs, statuses=None, codes=("510300",)):
    """构造每日快照，用于检验统计口径。"""
    from app.backtest.models import DailySnapshot

    daily = []
    for index, nav in enumerate(navs):
        day = date(2024, 1, 2) + __import__("datetime").timedelta(days=index)
        price_status = {code: "ok" for code in codes}
        if statuses and index < len(statuses):
            price_status = {code: statuses[index] for code in codes}
        daily.append(
            DailySnapshot(
                trade_date=day, cash=nav * 1000, market_value=0.0,
                total_assets=nav * 1000, nav=nav,
                positions={code: 100 for code in codes},
                prices={code: 10.0 for code in codes},
                price_status=price_status,
            )
        )
    return daily


def test_return_sample_stats_identity_holds() -> None:
    """统计口径必须可加总：快照 = 首日 + 缺口 + 缺净值 + 有效。"""
    from app.backtest.metrics import return_sample_stats

    navs = [1.00, 1.01, 1.02, 1.03, 1.04]
    # 第 3 天（index=2）持仓缺价
    statuses = ["ok", "ok", "stale_price", "ok", "ok"]
    stats = return_sample_stats(_make_daily(navs, statuses))
    assert stats["identity_holds"] is True
    assert stats["nav_days"] == 5
    assert stats["first_day"] == 1
    assert stats["held_price_gap"] >= 1
    assert (
        stats["first_day"] + stats["held_price_gap"]
        + stats["prior_day_price_gap"] + stats["missing_nav"]
        + stats["valid_return_days"] == stats["nav_days"]
    )


def test_return_sample_stats_no_gap_all_valid() -> None:
    """无缺口时有效收益 = 快照 - 1（首日）。"""
    from app.backtest.metrics import return_sample_stats

    navs = [1.00, 1.01, 1.02, 1.03]
    stats = return_sample_stats(_make_daily(navs))
    assert stats["nav_days"] == 4
    assert stats["first_day"] == 1
    assert stats["valid_return_days"] == 3
    assert stats["excluded_days"] == 0
    assert stats["identity_holds"] is True


def test_return_sample_stats_empty() -> None:
    from app.backtest.metrics import return_sample_stats

    stats = return_sample_stats([])
    assert stats["nav_days"] == 0
    assert stats["valid_return_days"] == 0
    assert stats["identity_holds"] is True


def test_return_sample_stats_definition_tagged() -> None:
    """统计口径必须有版本标签，便于报告标注。"""
    from app.backtest.metrics import return_sample_stats

    stats = return_sample_stats(_make_daily([1.0, 1.1]))
    assert stats["definition"] == "return-sample-stats-v1"


def test_sparse_evaluation_requires_additive_counts() -> None:
    """不可加总的口径必须判失败。"""
    from app.validation.stress import evaluate_sparse_result

    # 1 + 190 + 0 + 256 = 447 → 可加总，应通过
    good = evaluate_sparse_result(
        daily_rows=447, valid_return_days=256, gap_days_excluded=190,
        first_day_skipped=1, missing_nav_days=0,
    )
    assert good["status"] == "success", good["problems"]

    # 1 + 190 + 0 + 269 = 460 != 447 → 不可加总，必须判失败
    bad = evaluate_sparse_result(
        daily_rows=447, valid_return_days=269, gap_days_excluded=190,
        first_day_skipped=1, missing_nav_days=0,
    )
    assert bad["status"] == "failed"
    assert any("不可加总" in p for p in bad["problems"])
