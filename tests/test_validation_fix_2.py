"""阶段3A.2.1.1 专项测试。

覆盖：碎股卖出根因与修复、全池压力测试、指纹 v3、MA250 预热有效价格计数。
全部使用人工构造数据或临时数据库，不触碰正式库。
"""
from __future__ import annotations

from datetime import date

import pytest

from app.backtest.broker import Broker
from app.backtest.config import BacktestConfig, rule_for
from app.backtest.costs import round_lot, sell_quantity
from app.backtest.execution import Quote
from app.backtest.models import Order
from app.backtest.portfolio import Portfolio


def _quote(open_=10.0, volume=1_000_000):
    return Quote(
        trade_date=date(2024, 1, 3), open=open_, high=open_ * 1.02,
        low=open_ * 0.98, close=open_, volume=volume, prev_close=10.0,
    )


def _low_price_quote(price=0.3738, volume=1_000_000):
    """低价 ETF 的真实报价：prev_close 与价格同量级，避免触发跌停拦截。"""
    return Quote(
        trade_date=date(2024, 1, 3), open=price, high=price * 1.01,
        low=price * 0.99, close=price, volume=volume, prev_close=price,
    )


def _rule(code="510300", category="宽基指数ETF"):
    return rule_for(code, category)


def _config(**kwargs):
    base = dict(
        start_date="2024-01-01", end_date="2024-12-31",
        initial_cash=100000.0, allow_partial_fill=True,
    )
    base.update(kwargs)
    return BacktestConfig(**base)


def _portfolio_holding(quantity: int, price: float = 10.0, cash: float = 100000.0,
                       available_date: date = date(2024, 1, 3)):
    portfolio = Portfolio(initial_cash=cash + quantity * price + 5.0)
    portfolio.apply_buy("510300", quantity, price, fee=5.0,
                        trade_date=date(2024, 1, 2), available_date=available_date)
    return portfolio


def _sell_order(quantity: int) -> Order:
    return Order(order_id=1, code="510300", side="sell",
                 signal_date=date(2024, 1, 2), order_date=date(2024, 1, 2),
                 quantity=quantity)


# ============================================ 任务1：碎股卖出

def test_sell_quantity_uses_whole_lots_when_enough() -> None:
    """可卖数量足够一手时，按整手申报，不留碎股。"""
    assert sell_quantity(130399.7, 130400, 100) == 130300
    assert sell_quantity(73101.2, 73101, 100) == 73100
    assert sell_quantity(175799.9, 175800, 100) == 175700


def test_sell_quantity_allows_odd_only_when_below_one_lot() -> None:
    """可卖数量不足一手时，允许整笔卖出零股。"""
    assert sell_quantity(50, 50, 100) == 50
    assert sell_quantity(99, 99, 100) == 99
    assert sell_quantity(1, 1, 100) == 1


def test_sell_quantity_never_exceeds_available() -> None:
    for raw, avail in ((1000, 300), (5000, 120), (100, 0), (0, 100)):
        assert sell_quantity(raw, avail, 100) <= avail


def test_sell_quantity_zero_inputs() -> None:
    assert sell_quantity(0, 100, 100) == 0
    assert sell_quantity(-5, 100, 100) == 0
    assert sell_quantity(100, 0, 100) == 0


def test_odd_lot_never_produced_from_full_lots() -> None:
    """根因回归：整手持仓卖出后不得留下 1 股。"""
    held = 130400
    raw = held - 0.3          # 策略按权重算出 130399.7
    quantity = sell_quantity(raw, held, 100)
    assert quantity % 100 == 0, f"卖出 {quantity} 非整手，会留下 {held - quantity} 股"
    assert held - quantity >= 0


def test_normal_whole_lot_sell_full_fill() -> None:
    """A. 正常整手卖出。"""
    config = _config()
    broker = Broker(config=config, calendar=[date(2024, 1, 3)])
    portfolio = _portfolio_holding(1000)
    cash_before = portfolio.cash
    order = _sell_order(1000)

    result = broker.execute(order, _quote(), _rule(), portfolio, date(2024, 1, 3))
    assert result.filled is True
    assert result.trade.quantity == 1000
    assert result.trade.commission == pytest.approx(5.0)
    assert portfolio.quantity("510300") == 0
    assert order.status == "filled"
    assert order.filled_quantity == 1000
    assert order.remaining_quantity == 0
    assert portfolio.cash > cash_before


def test_odd_lot_holding_sold_in_one_shot() -> None:
    """B. 不足标准申报单位的剩余持仓一次性卖出。"""
    config = _config()
    broker = Broker(config=config, calendar=[date(2024, 1, 3)])
    portfolio = Portfolio(initial_cash=100000)
    portfolio.apply_buy("510300", 500, 10.0, fee=5.0,
                        trade_date=date(2024, 1, 2), available_date=date(2024, 1, 3))
    portfolio.apply_buy("510300", 37, 10.0, fee=5.0,
                        trade_date=date(2024, 1, 2), available_date=date(2024, 1, 3))
    assert portfolio.quantity("510300") == 537

    # 可卖 537 股，超过一手 → 按整手卖 500，剩 37 股（零股只能整笔清）
    order = _sell_order(537)
    result = broker.execute(order, _quote(), _rule(), portfolio, date(2024, 1, 3))
    assert result.filled is True
    assert result.trade.quantity == 500
    assert portfolio.quantity("510300") == 37
    assert order.status == "partial"
    assert order.remaining_quantity == 37

    # 剩余 37 股不足一手 → 允许整笔清掉
    clear = _sell_order(37)
    cleared = broker.execute(clear, _quote(), _rule(), portfolio, date(2024, 1, 3))
    assert cleared.filled is True
    assert cleared.trade.quantity == 37
    assert portfolio.quantity("510300") == 0, "零股必须一次清掉，不留残量"
    assert clear.status == "filled"


def test_sell_proceeds_below_min_commission_rejected_when_cash_short() -> None:
    """C. 卖出成交金额低于最低佣金且现金不够补差 → 拒单，不制造负现金。"""
    config = _config()
    broker = Broker(config=config, calendar=[date(2024, 1, 3)])
    portfolio = Portfolio(initial_cash=100000)
    portfolio.apply_buy("512010", 1, 0.3738, fee=0.0,
                        trade_date=date(2024, 1, 2), available_date=date(2024, 1, 3))
    portfolio.cash = 3.99  # 模拟现金接近耗尽

    order = Order(order_id=1, code="512010", side="sell",
                  signal_date=date(2024, 1, 2), order_date=date(2024, 1, 2),
                  quantity=1)
    result = broker.execute(order, _low_price_quote(), _rule("512010"),
                            portfolio, date(2024, 1, 3))
    assert result.filled is False
    assert result.reason == "sell_proceeds_below_fee"
    assert order.status == "rejected"
    assert portfolio.cash == pytest.approx(3.99), "不得出现负现金"
    assert portfolio.quantity("512010") == 1, "持仓保持不变"


def test_sell_proceeds_below_fee_allowed_when_cash_covers() -> None:
    """D. 卖出金额低于最低佣金但现金足够补差 → 正常成交。"""
    config = _config()
    broker = Broker(config=config, calendar=[date(2024, 1, 3)])
    portfolio = Portfolio(initial_cash=100000)
    portfolio.apply_buy("512010", 1, 0.3738, fee=0.0,
                        trade_date=date(2024, 1, 2), available_date=date(2024, 1, 3))
    portfolio.cash = 20.0  # 现金足够覆盖 5 元最低佣金

    order = Order(order_id=1, code="512010", side="sell",
                  signal_date=date(2024, 1, 2), order_date=date(2024, 1, 2),
                  quantity=1)
    result = broker.execute(order, _low_price_quote(), _rule("512010"),
                            portfolio, date(2024, 1, 3))
    assert result.filled is True
    assert result.trade.quantity == 1
    assert result.trade.commission == pytest.approx(5.0)
    # 现金 = 20 + 1×0.3738(含滑点后价格) - 5
    assert portfolio.cash > 0
    assert portfolio.quantity("512010") == 0


def test_min_commission_per_fill_not_per_share() -> None:
    """F. 最低佣金按每笔成交收取，不按股数叠加。"""
    from app.backtest.costs import commission
    from app.backtest.config import CostConfig

    costs = CostConfig(commission_rate=0.00025, min_commission=5.0)
    assert commission(1000.0, costs) == pytest.approx(5.0)
    assert commission(1_000_000.0, costs) == pytest.approx(250.0)
    assert commission(0.0, costs) == pytest.approx(0.0)


def test_multiple_sell_orders_each_pay_commission() -> None:
    """E/F. 多笔卖出订单各自计算最低佣金。"""
    config = _config()
    broker = Broker(config=config, calendar=[date(2024, 1, 3), date(2024, 1, 4)])
    portfolio = _portfolio_holding(200)
    fees = []
    for index, day in enumerate((date(2024, 1, 3), date(2024, 1, 4)), start=1):
        order = Order(order_id=index, code="510300", side="sell",
                      signal_date=date(2024, 1, 2), order_date=date(2024, 1, 2),
                      quantity=100)
        result = broker.execute(order, _quote(), _rule(), portfolio, day)
        assert result.filled is True
        fees.append(result.trade.commission)
    assert fees == [pytest.approx(5.0), pytest.approx(5.0)], "每笔订单各收一次最低佣金"
    assert portfolio.quantity("510300") == 0


def test_cash_and_position_consistency_after_sell() -> None:
    """H/I. 现金与持仓更新一致，卖完不留残量。"""
    config = _config()
    broker = Broker(config=config, calendar=[date(2024, 1, 3)])
    portfolio = _portfolio_holding(1237)
    cash_before = portfolio.cash
    order = _sell_order(1237)

    result = broker.execute(order, _quote(), _rule(), portfolio, date(2024, 1, 3))
    assert result.filled is True
    trade = result.trade
    assert trade.quantity == 1200, "超过一手时按整手申报"
    expected_cash = cash_before + trade.gross_amount - trade.commission
    assert portfolio.cash == pytest.approx(expected_cash)
    assert portfolio.quantity("510300") == 37
    assert order.remaining_quantity == 37
    assert order.filled_quantity + order.remaining_quantity == order.quantity


def test_no_negative_cash_across_many_odd_sells() -> None:
    """J. 大量零股卖出的极端场景下现金不得为负。"""
    config = _config(initial_cash=100000)
    broker = Broker(config=config, calendar=[date(2024, 1, d) for d in range(3, 12)])
    portfolio = Portfolio(initial_cash=100000)
    portfolio.apply_buy("510300", 500, 10.0, fee=5.0,
                        trade_date=date(2024, 1, 2), available_date=date(2024, 1, 3))
    portfolio.cash = 3.0  # 现金极低

    for index in range(1, 6):
        order = _sell_order(100)
        broker.execute(order, _quote(), _rule(), portfolio, date(2024, 1, 3))
        assert portfolio.cash >= -1e-6, f"第 {index} 次卖出后现金为负：{portfolio.cash}"


def test_partial_fill_keeps_remaining_and_fee_aligned() -> None:
    """E/G. 部分成交后剩余数量与费用一致。"""
    config = _config()
    broker = Broker(config=config, calendar=[date(2024, 1, 3), date(2024, 1, 4)])
    portfolio = Portfolio(initial_cash=100000)
    portfolio.apply_buy("510300", 300, 10.0, fee=5.0,
                        trade_date=date(2024, 1, 2), available_date=date(2024, 1, 3))
    order = _sell_order(500)

    first = broker.execute(order, _quote(), _rule(), portfolio, date(2024, 1, 3))
    assert first.filled is True
    assert order.filled_quantity == 300
    assert order.remaining_quantity == 200
    assert order.status == "partial"
    assert order.fee == pytest.approx(first.trade.commission)

    second = broker.execute(order, _quote(), _rule(), portfolio, date(2024, 1, 4))
    assert second.filled is False
    assert order.status == "partial"
    assert order.filled_quantity == 300
    assert order.fee == pytest.approx(first.trade.commission), "未成交不产生费用"


# ============================================ 任务3：指纹 v3

def _v3_rows():
    return [
        ("510300", "2024-01-02", 10.0, 10.5, 9.5, 10.2, 100000.0, 1020000.0, 10.2,
         "qfq", 1, "2024-01-01", "2024-12-31"),
        ("510300", "2024-01-03", 10.2, 10.8, 10.1, 10.6, 120000.0, 1272000.0, 10.6,
         "qfq", 1, "2024-01-01", "2024-12-31"),
    ]


def test_fingerprint_v3_version_and_fields() -> None:
    from app.validation.fingerprint import FIELD_LIST, FINGERPRINT_VERSION

    assert FINGERPRINT_VERSION == "market-fingerprint-v3"
    assert "adjustment_type" in FIELD_LIST
    assert "adjusted_close" in FIELD_LIST
    assert "adjustment_snapshot_id" in FIELD_LIST


def test_fingerprint_v3_detects_adjustment_type_change() -> None:
    from app.validation.fingerprint import FIELD_LIST, fingerprint_from_rows

    baseline = fingerprint_from_rows(_v3_rows())["sha256"]
    rows = [list(row) for row in _v3_rows()]
    rows[0][FIELD_LIST.index("adjustment_type")] = "hfq"
    changed = fingerprint_from_rows([tuple(r) for r in rows])["sha256"]
    assert changed != baseline, "adjustment_type 变化必须改变指纹"


def test_fingerprint_v3_detects_coverage_change() -> None:
    from app.validation.fingerprint import FIELD_LIST, fingerprint_from_rows

    baseline = fingerprint_from_rows(_v3_rows())["sha256"]
    for field in ("adjustment_coverage_start", "adjustment_coverage_end"):
        rows = [list(row) for row in _v3_rows()]
        rows[0][FIELD_LIST.index(field)] = "2023-01-01"
        assert fingerprint_from_rows([tuple(r) for r in rows])["sha256"] != baseline, (
            f"{field} 变化必须改变指纹"
        )


def test_fingerprint_v3_missing_field_encoding_stable() -> None:
    """缺失调整类型与覆盖日期使用确定性编码，重复计算结果一致。"""
    from app.validation.fingerprint import fingerprint_from_rows, serialize_row

    row_a = ("510300", "2024-01-02", 10.0, 10.5, 9.5, 10.2, 100.0, 1000.0, 10.2,
             None, 1, None, None)
    row_b = ("510300", "2024-01-02", 10.0, 10.5, 9.5, 10.2, 100.0, 1000.0, 10.2,
             "", 1, "", "")
    assert serialize_row(row_a) == serialize_row(row_b)
    assert fingerprint_from_rows([row_a])["sha256"] == fingerprint_from_rows([row_b])["sha256"]


def test_fingerprint_v3_row_order_independent() -> None:
    from app.validation.fingerprint import fingerprint_from_rows

    rows = _v3_rows()
    assert fingerprint_from_rows(rows)["sha256"] == fingerprint_from_rows(
        list(reversed(rows))
    )["sha256"]


def test_fingerprint_v3_reproducible() -> None:
    from app.validation.fingerprint import fingerprint_from_rows

    assert fingerprint_from_rows(_v3_rows())["sha256"] == fingerprint_from_rows(
        _v3_rows()
    )["sha256"]


def test_fingerprint_v2_not_misread_as_v3() -> None:
    """v2 指纹与 v3 指纹必须可区分（哈希输入含版本前缀）。"""
    from app.validation.fingerprint import (
        LEGACY_FINGERPRINT_VERSIONS,
        compute_fingerprint,
        serialize_row,
    )

    assert "market-fingerprint-v2" in LEGACY_FINGERPRINT_VERSIONS
    rows = _v3_rows()
    v3_sha, _ = compute_fingerprint(rows)
    assert v3_sha != "394024221c09d310f520e3e39cdd83faca944b7f5f89e3eec0a2c0835b92084a", (
        "v3 指纹不能与 v2 全库指纹相同"
    )


def test_input_hash_includes_fingerprint_version() -> None:
    from app.validation.config import ValidationConfig
    from app.validation.fingerprint import FINGERPRINT_VERSION, fingerprint_from_rows
    from app.validation.runner import _input_hash

    config = ValidationConfig(
        is_start="2021-01-01", is_end="2021-12-31",
        oos_start="2022-01-01", oos_end="2022-12-31",
        pool_mode="all",
    )
    fp = fingerprint_from_rows(_v3_rows())
    hash_v3 = _input_hash(config, ["510300"], fp)
    # 模拟旧版本指纹
    legacy = dict(fp, algorithm="market-fingerprint-v2")
    hash_v2 = _input_hash(config, ["510300"], legacy)
    assert hash_v3 != hash_v2, "指纹版本必须参与 input_hash"
    assert FINGERPRINT_VERSION == "market-fingerprint-v3"


# ============================================ 任务4：MA250 预热有效计数

def test_warmup_counts_valid_prices_only(temp_db) -> None:
    """250 条记录中有空价格时，不能报告预热成功。"""
    import sqlite3

    from app.validation.runner import _load_regime_warmup

    with sqlite3.connect(temp_db) as conn:
        conn.execute(
            "INSERT INTO etf_pool (code, name, category, fund_type, data_source, "
            "source_tested_at, status) VALUES ('510300','t','宽基指数ETF','x','t','2024-01-01','active')"
        )
        # 300 条记录，其中 60 条 adjusted_close 与 close 都为空（真正的无效记录）
        for index in range(300):
            day = f"2023-{1 + index // 28:02d}-{1 + index % 28:02d}"
            if index < 60:
                conn.execute(
                    "INSERT OR IGNORE INTO etf_daily_prices "
                    "(code, trade_date, open, high, low, close, volume, amount, "
                    "adjusted_close, adjustment_type, quality_status, source, collected_at) "
                    "VALUES ('510300',?,10,10.5,9.5,NULL,1000,10000,NULL,'qfq','valid','t','2024-01-01')",
                    (day,),
                )
            else:
                conn.execute(
                    "INSERT OR IGNORE INTO etf_daily_prices "
                    "(code, trade_date, open, high, low, close, volume, amount, "
                    "adjusted_close, adjustment_type, quality_status, source, collected_at) "
                    "VALUES ('510300',?,10,10.5,9.5,10,1000,10000,?,'qfq','valid','t','2024-01-01')",
                    (day, 10.0 + index * 0.01),
                )
    result = _load_regime_warmup("510300", "2025-01-02", db_path=temp_db)
    assert result["db_rows"] > result["valid_prices"], (
        f"空价格必须被排除：db_rows={result['db_rows']}, valid={result['valid_prices']}"
    )
    assert result["invalid_prices"] >= 1


def test_warmup_excludes_non_positive_prices(temp_db) -> None:
    """价格为 0 或负数不能算作有效预热数据。"""
    import sqlite3

    from app.validation.runner import _load_regime_warmup

    with sqlite3.connect(temp_db) as conn:
        conn.execute(
            "INSERT INTO etf_pool (code, name, category, fund_type, data_source, "
            "source_tested_at, status) VALUES ('510300','t','宽基指数ETF','x','t','2024-01-01','active')"
        )
        for index, price in enumerate((10.0, 0.0, -1.0, 10.5)):
            conn.execute(
                "INSERT OR IGNORE INTO etf_daily_prices "
                "(code, trade_date, open, high, low, close, volume, amount, "
                "adjusted_close, adjustment_type, quality_status, source, collected_at) "
                "VALUES ('510300',?,10,10.5,9.5,10,1000,10000,?,'qfq','valid','t','2024-01-01')",
                (f"2024-01-0{index + 1}", price),
            )
    result = _load_regime_warmup("510300", "2025-01-02", db_path=temp_db)
    assert result["valid_prices"] == 2, "0 与负数不得计入有效价格"
    assert result["invalid_prices"] == 2


def test_warmup_excludes_oos_data(temp_db) -> None:
    """OOS 之后的数据不能参与预热。"""
    import sqlite3

    from app.validation.runner import _load_regime_warmup

    with sqlite3.connect(temp_db) as conn:
        conn.execute(
            "INSERT INTO etf_pool (code, name, category, fund_type, data_source, "
            "source_tested_at, status) VALUES ('510300','t','宽基指数ETF','x','t','2024-01-01','active')"
        )
        for day in ("2024-12-30", "2024-12-31", "2025-01-02", "2025-01-03"):
            conn.execute(
                "INSERT OR IGNORE INTO etf_daily_prices "
                "(code, trade_date, open, high, low, close, volume, amount, "
                "adjusted_close, adjustment_type, quality_status, source, collected_at) "
                "VALUES ('510300',?,10,10.5,9.5,10,1000,10000,10,'qfq','valid','t','2024-01-01')",
                (day,),
            )
    result = _load_regime_warmup("510300", "2025-01-02", db_path=temp_db)
    assert result["db_rows"] == 2, "只能取 OOS 起点之前的记录"
    assert result["last"] == "2024-12-31"


def test_warmup_250_valid_days_ok(temp_db) -> None:
    """250 个有效交易日满足预热需求。"""
    import sqlite3

    from app.validation.runner import _load_regime_warmup

    with sqlite3.connect(temp_db) as conn:
        conn.execute(
            "INSERT INTO etf_pool (code, name, category, fund_type, data_source, "
            "source_tested_at, status) VALUES ('510300','t','宽基指数ETF','x','t','2024-01-01','active')"
        )
        for index in range(250):
            day = f"202{index // 100 + 1}-{1 + (index % 100) // 28:02d}-{1 + index % 28:02d}"
            conn.execute(
                "INSERT OR IGNORE INTO etf_daily_prices "
                "(code, trade_date, open, high, low, close, volume, amount, "
                "adjusted_close, adjustment_type, quality_status, source, collected_at) "
                "VALUES ('510300',?,10,10.5,9.5,10,1000,10000,?,'qfq','valid','t','2024-01-01')",
                (day, 10.0 + index * 0.01),
            )
    result = _load_regime_warmup("510300", "2030-01-01", db_path=temp_db)
    assert result["valid_prices"] == 250
    assert result["valid_prices"] >= 250, "250 个有效价格满足预热需求"


def test_warmup_249_valid_days_partial(temp_db) -> None:
    """249 个有效交易日不满足预热需求。"""
    import sqlite3

    from app.validation.runner import _load_regime_warmup

    with sqlite3.connect(temp_db) as conn:
        conn.execute(
            "INSERT INTO etf_pool (code, name, category, fund_type, data_source, "
            "source_tested_at, status) VALUES ('510300','t','宽基指数ETF','x','t','2024-01-01','active')"
        )
        for index in range(249):
            day = f"202{index // 100 + 1}-{1 + (index % 100) // 28:02d}-{1 + index % 28:02d}"
            conn.execute(
                "INSERT OR IGNORE INTO etf_daily_prices "
                "(code, trade_date, open, high, low, close, volume, amount, "
                "adjusted_close, adjustment_type, quality_status, source, collected_at) "
                "VALUES ('510300',?,10,10.5,9.5,10,1000,10000,?,'qfq','valid','t','2024-01-01')",
                (day, 10.0 + index * 0.01),
            )
    result = _load_regime_warmup("510300", "2030-01-01", db_path=temp_db)
    assert result["valid_prices"] == 249
    assert result["valid_prices"] < 250, "249 不足以满足 MA250"
