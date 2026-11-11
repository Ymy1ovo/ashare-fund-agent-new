"""回测引擎集成测试：临时 SQLite + 人工行情，验证时序、账本、无未来函数。"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from app.backtest.config import BacktestConfig
from app.backtest.engine import BacktestEngine
from app.backtest.strategies.base import StrategyContext, TargetWeight
from app.database.db import get_connection


def _seed_market(db_path, prices, *, start="2024-01-02", skip_dates=(), snapshot_id=None):
    """写入交易日历、观察池、行情、快照。prices 长度决定交易日数。"""
    dates = pd.bdate_range(start, periods=len(next(iter(prices.values()))))
    date_strs = [d.date().isoformat() for d in dates]
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO adjustment_runs (started_at, finished_at, status, total_codes, success_codes) "
            "VALUES ('2024-01-01T00:00:00','2024-01-01T00:00:01','success',?,?)",
            (len(prices), len(prices)),
        )
        run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for code in prices:
            conn.execute(
                "INSERT OR IGNORE INTO etf_pool (code, name, category, fund_type, data_source, "
                "source_tested_at, status) VALUES (?,?,?,'指数型-股票','test','2024-01-01','active')",
                (code, "测试" + code, "宽基指数ETF"),
            )
            conn.execute(
                "INSERT INTO etf_adjustment_snapshots "
                "(run_id, code, status, collected_at, source, coverage_start, coverage_end, "
                "matched_start, matched_end, raw_rows, qfq_rows, matched_rows, missing_rows, "
                "is_current, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
                (run_id, code, "success", "2024-01-01T00:00:00", "test",
                 date_strs[0], date_strs[-1], date_strs[0], date_strs[-1],
                 len(date_strs), len(date_strs), len(date_strs), 0, "2024-01-01T00:00:00"),
            )
            snapshot = snapshot_id or conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            for day, close in zip(date_strs, prices[code]):
                if day in skip_dates:
                    continue
                open_price = close * 0.99
                conn.execute(
                    "INSERT INTO etf_daily_prices "
                    "(code, trade_date, open, high, low, close, volume, amount, "
                    "adjusted_close, adjustment_type, quality_status, source, collected_at, "
                    "adjustment_snapshot_id, adjustment_collected_at, adjustment_source, "
                    "adjustment_coverage_start, adjustment_coverage_end) "
                    "VALUES (?,?,?,?,?,?,?,?,?,'qfq','valid','test','2024-01-01T00:00:00',"
                    "?,'2024-01-01T00:00:00','test',?,?)",
                    (code, day, open_price, close * 1.01, close * 0.98, close,
                     close * 1000, close * 1000000, close, snapshot,
                     date_strs[0], date_strs[-1]),
                )
        conn.executemany(
            "INSERT OR IGNORE INTO trade_calendar (trade_date) VALUES (?)",
            [(day,) for day in date_strs],
        )
    return date_strs


class _FixedStrategy:
    """按预设日期返回固定目标权重，便于断言时序。"""

    name = "fixed"
    version = "1.0.0"

    def __init__(self, plan):
        self.plan = plan
        self.calls = []

    def target_weights(self, context):
        key = context.signal_date.isoformat()
        self.calls.append(key)
        # 未出现在 plan 中的日期返回 None（无意见），避免清仓
        return self.plan.get(key)


def test_buy_signal_executes_next_day_open(temp_db):
    dates = _seed_market(temp_db, {"510300": [10.0, 11.0, 12.0, 13.0]})
    strategy = _FixedStrategy({dates[0]: [TargetWeight("510300", 1.0)]})
    config = BacktestConfig(start_date=dates[0], end_date=dates[-1], initial_cash=100000)
    result = BacktestEngine(config, strategy, db_path=temp_db).run(["510300"], indicator_version=None)
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.trade_date.isoformat() == dates[1]
    # 次日开盘 = 11.0*0.99，再加 5bp 滑点，且不高于当日 high
    assert trade.price == pytest.approx(11.0 * 0.99 * 1.0005, rel=1e-6)


def test_signal_day_not_traded_same_day(temp_db):
    dates = _seed_market(temp_db, {"510300": [10.0, 11.0, 12.0]})
    strategy = _FixedStrategy({dates[1]: [TargetWeight("510300", 1.0)]})
    config = BacktestConfig(start_date=dates[0], end_date=dates[-1])
    result = BacktestEngine(config, strategy, db_path=temp_db).run(["510300"], indicator_version=None)
    assert result.trades[0].trade_date.isoformat() == dates[2]
    for trade in result.trades:
        order = next(o for o in result.orders if o.order_id == trade.order_id)
        assert trade.trade_date > order.signal_date


def test_no_lookahead_when_future_prices_change(temp_db):
    dates = _seed_market(temp_db, {"510300": [10.0, 11.0, 12.0, 13.0, 14.0]})
    cutoff = dates[2]
    strategy = _FixedStrategy({dates[0]: [TargetWeight("510300", 1.0)]})
    config = BacktestConfig(start_date=dates[0], end_date=cutoff)
    first = BacktestEngine(config, strategy, db_path=temp_db).run(["510300"], indicator_version=None)
    with get_connection(temp_db) as conn:
        conn.execute(
            "UPDATE etf_daily_prices SET close=close*3, open=open*3, high=high*3, low=low*3 "
            "WHERE code='510300' AND trade_date > ?", (cutoff,),
        )
    second = BacktestEngine(config, strategy, db_path=temp_db).run(["510300"], indicator_version=None)
    assert [item.nav for item in first.daily] == pytest.approx([item.nav for item in second.daily])


def test_zero_volume_defers_then_fills(temp_db):
    dates = _seed_market(temp_db, {"510300": [10.0, 11.0, 12.0, 13.0]})
    with get_connection(temp_db) as conn:
        conn.execute("UPDATE etf_daily_prices SET volume=0 WHERE code='510300' AND trade_date=?",
                     (dates[1],))
    strategy = _FixedStrategy({dates[0]: [TargetWeight("510300", 1.0)]})
    config = BacktestConfig(start_date=dates[0], end_date=dates[-1], max_defer_days=3)
    result = BacktestEngine(config, strategy, db_path=temp_db).run(["510300"], indicator_version=None)
    assert result.trades[0].trade_date.isoformat() == dates[2]
    deferred_order = next(o for o in result.orders if o.side == "buy")
    assert deferred_order.deferred_days >= 1


def test_zero_volume_expires_after_max_defer(temp_db):
    dates = _seed_market(temp_db, {"510300": [10.0, 11.0, 12.0]})
    with get_connection(temp_db) as conn:
        conn.execute("UPDATE etf_daily_prices SET volume=0 WHERE code='510300' AND trade_date>=?",
                     (dates[1],))
    strategy = _FixedStrategy({dates[0]: [TargetWeight("510300", 1.0)]})
    config = BacktestConfig(start_date=dates[0], end_date=dates[-1], max_defer_days=0)
    result = BacktestEngine(config, strategy, db_path=temp_db).run(["510300"], indicator_version=None)
    assert not result.trades
    assert any(order.status == "expired" for order in result.orders)


def test_multi_etf_rebalance_and_reconcile(temp_db):
    dates = _seed_market(temp_db, {"510300": [10.0] * 4, "510500": [20.0] * 4})
    strategy = _FixedStrategy({
        dates[0]: [TargetWeight("510300", 0.5), TargetWeight("510500", 0.5)],
    })
    config = BacktestConfig(start_date=dates[0], end_date=dates[-1], initial_cash=100000)
    result = BacktestEngine(config, strategy, db_path=temp_db).run(
        ["510300", "510500"], indicator_version=None
    )
    from app.backtest.metrics import reconcile
    check = reconcile(result.daily, result.trades, result.initial_cash)
    assert check["ok"], check["errors"]
    assert len(result.trades) == 2
    for item in result.daily:
        assert item.total_assets == pytest.approx(item.cash + item.market_value)


def test_same_day_order_sequence_is_deterministic(temp_db):
    dates = _seed_market(temp_db, {"510300": [10.0] * 4, "510500": [20.0] * 4})
    strategy = _FixedStrategy({
        dates[0]: [TargetWeight("510500", 0.5), TargetWeight("510300", 0.5)],
    })
    config = BacktestConfig(start_date=dates[0], end_date=dates[-1], initial_cash=100000)
    first = BacktestEngine(config, strategy, db_path=temp_db).run(
        ["510300", "510500"], indicator_version=None)
    second = BacktestEngine(config, strategy, db_path=temp_db).run(
        ["510300", "510500"], indicator_version=None)
    assert [(t.code, t.trade_date, t.quantity, t.price) for t in first.trades] == \
           [(t.code, t.trade_date, t.quantity, t.price) for t in second.trades]
    assert first.input_hash == second.input_hash


def test_parameter_change_changes_hash(temp_db):
    dates = _seed_market(temp_db, {"510300": [10.0] * 4})
    strategy = _FixedStrategy({dates[0]: [TargetWeight("510300", 1.0)]})
    base = BacktestConfig(start_date=dates[0], end_date=dates[-1], initial_cash=100000)
    other = BacktestConfig(start_date=dates[0], end_date=dates[-1], initial_cash=200000)
    a = BacktestEngine(base, strategy, db_path=temp_db).run(["510300"], indicator_version=None)
    b = BacktestEngine(other, strategy, db_path=temp_db).run(["510300"], indicator_version=None)
    assert a.input_hash != b.input_hash


def test_snapshot_mix_is_rejected(temp_db):
    from app.backtest.data import BacktestDataError
    dates = _seed_market(temp_db, {"510300": [10.0] * 4})
    with get_connection(temp_db) as conn:
        conn.execute(
            "INSERT INTO etf_adjustment_snapshots "
            "(run_id, code, status, collected_at, source, coverage_start, coverage_end, "
            "matched_start, matched_end, raw_rows, qfq_rows, matched_rows, missing_rows, "
            "is_current, created_at) VALUES (1,'510300','success','2024-01-01T00:00:00','test',"
            "?,?,?,?,4,4,4,0,0,'2024-01-01T00:00:00')",
            (dates[0], dates[-1], dates[0], dates[-1]),
        )
        other = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("UPDATE etf_daily_prices SET adjustment_snapshot_id=? "
                     "WHERE code='510300' AND trade_date=?", (other, dates[1]))
    with pytest.raises(BacktestDataError):
        BacktestEngine(
            BacktestConfig(start_date=dates[0], end_date=dates[-1]),
            _FixedStrategy({}),
            db_path=temp_db,
        ).run(["510300"], indicator_version=None)
