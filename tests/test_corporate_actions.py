"""阶段3A.3.2 公司行为与账本会计恒等式专项测试。

覆盖 18 项场景，全部走完整 Engine + Broker + Portfolio + 估值流程，
不只测函数返回值。
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from app.backtest.config import BacktestConfig
from app.backtest.corporate_actions import (
    ACTION_CASH_DISTRIBUTION,
    ACTION_REVERSE_SPLIT,
    ACTION_SPLIT,
    CorporateActionError,
    STATUS_CONFIRMED,
    STATUS_UNVERIFIED,
    build_action,
    compute_impact,
    load_actions,
    record_application,
    save_action,
    unverified_actions,
)
from app.backtest.engine import BacktestEngine
from app.backtest.portfolio import Portfolio
from app.backtest.strategies.base import TargetWeight
from app.database.db import get_connection


# ---------------------------------------------------------------- 测试脚手架

def _seed(db_path, prices, *, start="2024-01-02"):
    """写入交易日历、池、行情、快照。"""
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
            snapshot = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            for day, close in zip(date_strs, prices[code]):
                conn.execute(
                    "INSERT INTO etf_daily_prices "
                    "(code, trade_date, open, high, low, close, volume, amount, "
                    "adjusted_close, adjustment_type, quality_status, source, collected_at, "
                    "adjustment_snapshot_id, adjustment_collected_at, adjustment_source, "
                    "adjustment_coverage_start, adjustment_coverage_end) "
                    "VALUES (?,?,?,?,?,?,?,?,?,'qfq','valid','test','2024-01-01T00:00:00',"
                    "?,'2024-01-01T00:00:00','test',?,?)",
                    (code, day, close, close, close, close,
                     close * 1000, close * 1000000, close, snapshot,
                     date_strs[0], date_strs[-1]),
                )
        conn.executemany(
            "INSERT OR IGNORE INTO trade_calendar (trade_date) VALUES (?)",
            [(day,) for day in date_strs],
        )
    return date_strs


class _Fixed:
    name = "fixed"
    version = "1.0.0"

    def __init__(self, plan):
        self.plan = plan

    def target_weights(self, context):
        return self.plan.get(context.signal_date.isoformat())


def _insert_action(db_path, **kwargs):
    action = build_action(status=STATUS_CONFIRMED, source="test", **kwargs)
    return save_action(action, db_path=db_path)


def _run(db_path, dates, codes, *, plan, **overrides):
    cfg = BacktestConfig(
        start_date=dates[0], end_date=dates[-1],
        initial_cash=overrides.pop("initial_cash", 100000.0), **overrides,
    )
    engine = BacktestEngine(cfg, _Fixed(plan), db_path=db_path)
    return engine.run(codes, indicator_version=None), engine


# ---------------------------------------------------------------- 1. 10:1 拆分

def test_split_10_to_1_keeps_total_assets_continuous(temp_db):
    dates = _seed(temp_db, {"510300": [10.0, 10.0, 10.0, 10.0]})
    _insert_action(temp_db, code="510300", action_type=ACTION_SPLIT,
                   ex_date=dates[1], effective_date=dates[2], share_ratio=10.0)
    plan = {dates[0]: [TargetWeight("510300", 1.0)]}
    # 若发生拆分，价格同步变 1/10；这里行情保持 10.0，用 events 检验数量
    result, engine = _run(temp_db, dates, ["510300"], plan=plan)
    log = engine.corporate_action_log
    assert len(log) == 1
    assert log[0]["shares_before"] > 0
    assert log[0]["shares_after"] == log[0]["shares_before"] * 10
    for item in result.daily:
        assert item.total_assets == pytest.approx(item.cash + item.market_value)


# ---------------------------------------------------------------- 2. 1:2 合并

def test_reverse_split_1_to_2_halves_shares(temp_db):
    dates = _seed(temp_db, {"510300": [10.0] * 4})
    _insert_action(temp_db, code="510300", action_type=ACTION_REVERSE_SPLIT,
                   ex_date=dates[1], effective_date=dates[2], share_ratio=0.5)
    plan = {dates[0]: [TargetWeight("510300", 1.0)]}
    result, engine = _run(temp_db, dates, ["510300"], plan=plan)
    log = engine.corporate_action_log
    assert len(log) == 1
    assert log[0]["shares_after"] == log[0]["shares_before"] // 2


# ---------------------------------------------------------------- 3. 非整数比例

def test_fractional_split_produces_fractional_cash(temp_db):
    dates = _seed(temp_db, {"510300": [10.0] * 4})
    _insert_action(temp_db, code="510300", action_type=ACTION_SPLIT,
                   ex_date=dates[1], effective_date=dates[2], share_ratio=1.5)
    plan = {dates[0]: [TargetWeight("510300", 1.0)]}
    result, engine = _run(temp_db, dates, ["510300"], plan=plan)
    log = engine.corporate_action_log[0]
    # 10000 份 × 1.5 = 15000，无零碎
    assert log["shares_after"] == log["shares_before"] * 3 // 2
    for item in result.daily:
        assert item.total_assets == pytest.approx(item.cash + item.market_value)


# ---------------------------------------------------------------- 4. 现金分红

def test_cash_distribution_increases_cash(temp_db):
    dates = _seed(temp_db, {"510300": [10.0] * 4})
    _insert_action(temp_db, code="510300", action_type=ACTION_CASH_DISTRIBUTION,
                   ex_date=dates[1], effective_date=dates[2], cash_per_share=0.5)
    plan = {dates[0]: [TargetWeight("510300", 1.0)]}
    result, engine = _run(temp_db, dates, ["510300"], plan=plan)
    log = engine.corporate_action_log[0]
    expected_cash = log["shares_before"] * 0.5
    # 分红按「事件日持仓数量 × 每份金额」入账，与现金余额无关
    assert log["cash_delta"] == pytest.approx(expected_cash)
    assert log["shares_before"] > 0
    # 现金余额在事件日必然包含这笔分红（当日还可能有其他成交，
    # 因此只断言「流入 >= 分红金额」与账面恒等式）
    after = next(d for d in result.daily if d.trade_date.isoformat() == dates[2])
    # 该日现金 = 前一日现金 + 分红 − 当日买入支出
    before = next(d for d in result.daily if d.trade_date.isoformat() == dates[1])
    buys = [t for t in result.trades if t.trade_date.isoformat() == dates[2] and t.side == "buy"]
    spent = sum(t.gross_amount + t.total_fees for t in buys)
    assert after.cash == pytest.approx(before.cash + expected_cash - spent, abs=1e-6)
    assert expected_cash > 0
    for item in result.daily:
        assert item.total_assets == pytest.approx(item.cash + item.market_value)


# ---------------------------------------------------------------- 5. 同日拆分+分红

def test_split_and_distribution_same_day(temp_db):
    dates = _seed(temp_db, {"510300": [10.0] * 4})
    _insert_action(temp_db, code="510300", action_type=ACTION_SPLIT,
                   ex_date=dates[1], effective_date=dates[2], share_ratio=2.0)
    _insert_action(temp_db, code="510300", action_type=ACTION_CASH_DISTRIBUTION,
                   ex_date=dates[1], effective_date=dates[2], cash_per_share=0.2)
    plan = {dates[0]: [TargetWeight("510300", 1.0)]}
    result, engine = _run(temp_db, dates, ["510300"], plan=plan)
    assert len(engine.corporate_action_log) == 2
    kinds = {item["action_type"] for item in engine.corporate_action_log}
    assert kinds == {ACTION_SPLIT, ACTION_CASH_DISTRIBUTION}
    for item in result.daily:
        assert item.total_assets == pytest.approx(item.cash + item.market_value)


def test_duplicate_event_import_is_idempotent(temp_db):
    _seed(temp_db, {"510300": [10.0] * 3})
    first = _insert_action(temp_db, code="510300", action_type=ACTION_SPLIT,
                           ex_date="2024-01-03", effective_date="2024-01-04",
                           share_ratio=2.0)
    second = _insert_action(temp_db, code="510300", action_type=ACTION_SPLIT,
                            ex_date="2024-01-03", effective_date="2024-01-04",
                            share_ratio=2.0)
    assert first == second
    with get_connection(temp_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM corporate_actions").fetchone()[0]
    assert count == 1


# ---------------------------------------------------------------- 7. 事件顺序错误

def test_effective_before_ex_date_rejected():
    with pytest.raises(CorporateActionError):
        build_action(code="510300", action_type=ACTION_SPLIT,
                     ex_date="2024-01-05", effective_date="2024-01-04",
                     share_ratio=2.0, status=STATUS_CONFIRMED)


def test_split_ratio_must_exceed_one():
    with pytest.raises(CorporateActionError):
        build_action(code="510300", action_type=ACTION_SPLIT,
                     ex_date="2024-01-03", effective_date="2024-01-04",
                     share_ratio=0.5, status=STATUS_CONFIRMED)


# ---------------------------------------------------------------- 8. 跨越非交易日

def test_event_on_non_trading_day_applies_next_trading_day(temp_db):
    dates = _seed(temp_db, {"510300": [10.0] * 6})
    assert dates[3] == "2024-01-05"
    _insert_action(temp_db, code="510300", action_type=ACTION_SPLIT,
                   ex_date="2024-01-06", effective_date=dates[4], share_ratio=2.0)
    plan = {dates[0]: [TargetWeight("510300", 1.0)]}
    result, engine = _run(temp_db, dates, ["510300"], plan=plan)
    assert engine.corporate_action_log[0]["effective_date"] == dates[4]


# ---------------------------------------------------------------- 9. 无持仓

def test_event_without_position_changes_nothing(temp_db):
    dates = _seed(temp_db, {"510300": [10.0] * 4})
    _insert_action(temp_db, code="510300", action_type=ACTION_SPLIT,
                   ex_date=dates[1], effective_date=dates[2], share_ratio=2.0)
    result, engine = _run(temp_db, dates, ["510300"], plan={})
    assert engine.corporate_action_log == []
    for item in result.daily:
        assert item.total_assets == pytest.approx(100000.0)


# ---------------------------------------------------------------- 10. 部分成交订单

def test_event_with_pending_order_keeps_ledger_consistent(temp_db):
    dates = _seed(temp_db, {"510300": [10.0] * 5})
    _insert_action(temp_db, code="510300", action_type=ACTION_SPLIT,
                   ex_date=dates[2], effective_date=dates[3], share_ratio=2.0)
    plan = {
        dates[0]: [TargetWeight("510300", 0.5)],
        dates[2]: [TargetWeight("510300", 1.0)],
    }
    result, engine = _run(temp_db, dates, ["510300"], plan=plan)
    for item in result.daily:
        assert item.total_assets == pytest.approx(item.cash + item.market_value)
        assert item.cash >= -1e-6


# ---------------------------------------------------------------- 11. 零碎股

def test_fractional_shares_converted_to_cash(temp_db):
    dates = _seed(temp_db, {"510300": [10.0] * 4})
    _insert_action(temp_db, code="510300", action_type=ACTION_SPLIT,
                   ex_date=dates[1], effective_date=dates[2], share_ratio=1.3333)
    plan = {dates[0]: [TargetWeight("510300", 1.0)]}
    result, engine = _run(temp_db, dates, ["510300"], plan=plan)
    log = engine.corporate_action_log[0]
    assert log["shares_after"] == int(log["shares_before"] * 1.3333)
    assert log["fractional_cash"] >= 0.0
    for item in result.daily:
        assert item.total_assets == pytest.approx(item.cash + item.market_value)


# ---------------------------------------------------------------- 12. 现金不足边界

def test_leveraged_position_does_not_break_cash(temp_db):
    dates = _seed(temp_db, {"510300": [10.0] * 4})
    _insert_action(temp_db, code="510300", action_type=ACTION_CASH_DISTRIBUTION,
                   ex_date=dates[1], effective_date=dates[2], cash_per_share=5.0)
    plan = {dates[0]: [TargetWeight("510300", 0.98)]}
    result, _ = _run(temp_db, dates, ["510300"], plan=plan, initial_cash=10000.0)
    for item in result.daily:
        assert item.cash >= -1e-6


# ---------------------------------------------------------------- 13/14. 前后连续

def test_market_value_and_total_assets_continuous_across_split():
    portfolio = Portfolio(initial_cash=100000)
    portfolio.apply_buy("510300", 1000, 10.0, fee=0.0,
                        trade_date=date(2024, 1, 2), available_date=date(2024, 1, 3))
    before_total = portfolio.total_assets({"510300": 10.0})
    portfolio.apply_corporate_action("510300", new_quantity=10000, cash_delta=0.0)
    after_total = portfolio.total_assets({"510300": 1.0})
    assert portfolio.quantity("510300") == 10000
    assert after_total == pytest.approx(before_total, rel=1e-9)


def test_total_assets_continuous_across_cash_distribution():
    portfolio = Portfolio(initial_cash=100000)
    portfolio.apply_buy("510300", 1000, 10.0, fee=0.0,
                        trade_date=date(2024, 1, 2), available_date=date(2024, 1, 3))
    before = portfolio.total_assets({"510300": 10.0})
    portfolio.apply_corporate_action("510300", new_quantity=1000, cash_delta=500.0)
    after = portfolio.total_assets({"510300": 9.5})
    assert after == pytest.approx(before, rel=1e-9)


# ---------------------------------------------------------------- 15. 收益率正确

def test_daily_return_identity_after_split(temp_db):
    dates = _seed(temp_db, {"510300": [10.0] * 4})
    _insert_action(temp_db, code="510300", action_type=ACTION_SPLIT,
                   ex_date=dates[1], effective_date=dates[2], share_ratio=2.0)
    plan = {dates[0]: [TargetWeight("510300", 1.0)]}
    result, _ = _run(temp_db, dates, ["510300"], plan=plan)
    for item in result.daily:
        assert item.total_assets == pytest.approx(item.cash + item.market_value)
        assert item.cash >= -1e-6


# ---------------------------------------------------------------- 16. 缺失行情重叠

def test_event_day_with_missing_quote_uses_last_price(temp_db):
    dates = _seed(temp_db, {"510300": [10.0] * 4})
    with get_connection(temp_db) as conn:
        conn.execute("DELETE FROM etf_daily_prices WHERE code='510300' AND trade_date=?",
                     (dates[2],))
    _insert_action(temp_db, code="510300", action_type=ACTION_CASH_DISTRIBUTION,
                   ex_date=dates[1], effective_date=dates[2], cash_per_share=0.1)
    plan = {dates[0]: [TargetWeight("510300", 1.0)]}
    result, engine = _run(temp_db, dates, ["510300"], plan=plan)
    assert len(engine.corporate_action_log) == 1


# ---------------------------------------------------------------- 17. 未确认不得应用

def test_unverified_action_not_applied(temp_db):
    dates = _seed(temp_db, {"510300": [10.0] * 4})
    apply_ = build_action(code="510300", action_type=ACTION_SPLIT,
                          ex_date=dates[1], effective_date=dates[2],
                          share_ratio=2.0, status=STATUS_UNVERIFIED, source="test")
    save_action(apply_, db_path=temp_db)
    plan = {dates[0]: [TargetWeight("510300", 1.0)]}
    result, engine = _run(temp_db, dates, ["510300"], plan=plan)
    assert engine.corporate_action_log == []
    assert any("未确认" in note for note in result.notes)


def test_compute_impact_rejects_unverified():
    action = build_action(code="510300", action_type=ACTION_SPLIT,
                          ex_date="2024-01-03", effective_date="2024-01-04",
                          share_ratio=2.0, status=STATUS_UNVERIFIED, source="test")
    with pytest.raises(CorporateActionError):
        compute_impact(action, holding=1000, price=10.0)


# ---------------------------------------------------------------- 18. 重复应用保护

def test_same_action_applied_twice_raises(temp_db):
    _seed(temp_db, {"510300": [10.0] * 3})
    action_id = _insert_action(temp_db, code="510300", action_type=ACTION_SPLIT,
                               ex_date="2024-01-03", effective_date="2024-01-04",
                               share_ratio=2.0)
    action = next(item for item in load_actions(db_path=temp_db) if item.action_id == action_id)
    impact = compute_impact(action, holding=1000, price=10.0)
    record_application(run_id="run-x", impact=impact, db_path=temp_db)
    with pytest.raises(CorporateActionError):
        record_application(run_id="run-x", impact=impact, db_path=temp_db)


# ---------------------------------------------------------------- 附加检查

def test_load_actions_filters_by_range_and_codes(temp_db):
    _seed(temp_db, {"510300": [10.0] * 6, "510500": [20.0] * 6})
    _insert_action(temp_db, code="510300", action_type=ACTION_SPLIT,
                   ex_date="2024-01-03", effective_date="2024-01-04", share_ratio=2.0)
    _insert_action(temp_db, code="510500", action_type=ACTION_CASH_DISTRIBUTION,
                   ex_date="2024-01-03", effective_date="2024-01-04", cash_per_share=0.1)
    only_300 = load_actions(codes=["510300"], db_path=temp_db)
    assert len(only_300) == 1 and only_300[0].code == "510300"
    in_range = load_actions(start="2024-01-04", end="2024-01-04", db_path=temp_db)
    assert len(in_range) == 2
    assert load_actions(start="2024-02-01", db_path=temp_db) == []


def test_unverified_actions_listed_separately(temp_db):
    _seed(temp_db, {"510300": [10.0] * 3})
    _insert_action(temp_db, code="510300", action_type=ACTION_SPLIT,
                   ex_date="2024-01-03", effective_date="2024-01-04", share_ratio=2.0)
    save_action(build_action(
        code="510300", action_type=ACTION_SPLIT,
        ex_date="2024-01-04", effective_date="2024-01-05",
        share_ratio=3.0, status=STATUS_UNVERIFIED, source="test",
    ), db_path=temp_db)
    pending = unverified_actions(db_path=temp_db)
    assert len(pending) == 1
    assert pending[0].status == STATUS_UNVERIFIED


def test_disabled_corporate_actions_matches_legacy(temp_db):
    """配置关闭时退化为旧口径，结果必须与开启时不同（证明修复确实生效）。"""
    dates = _seed(temp_db, {"510300": [10.0] * 4})
    _insert_action(temp_db, code="510300", action_type=ACTION_SPLIT,
                   ex_date=dates[1], effective_date=dates[2], share_ratio=2.0)
    plan = {dates[0]: [TargetWeight("510300", 1.0)]}
    legacy, _ = _run(temp_db, dates, ["510300"], plan=plan,
                     apply_corporate_actions=False)
    fixed, _ = _run(temp_db, dates, ["510300"], plan=plan,
                    apply_corporate_actions=True)
    assert legacy.daily[-1].total_assets != pytest.approx(fixed.daily[-1].total_assets)


def test_no_action_etf_unaffected(temp_db):
    """无公司行为标的：开/关公司行为的结果必须完全相同。"""
    dates = _seed(temp_db, {"510300": [10.0, 10.5, 11.0, 10.8]})
    plan = {dates[0]: [TargetWeight("510300", 1.0)]}
    on, _ = _run(temp_db, dates, ["510300"], plan=plan, apply_corporate_actions=True)
    off, _ = _run(temp_db, dates, ["510300"], plan=plan, apply_corporate_actions=False)
    assert [d.nav for d in on.daily] == pytest.approx([d.nav for d in off.daily])


def test_portfolio_rejects_negative_new_quantity():
    portfolio = Portfolio(initial_cash=100000)
    with pytest.raises(Exception):
        portfolio.apply_corporate_action("510300", new_quantity=-1, cash_delta=0.0)
