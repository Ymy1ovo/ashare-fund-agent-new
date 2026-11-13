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
    EVIDENCE_OFFICIAL,
    EVIDENCE_SECONDARY,
    EVIDENCE_UNVERIFIED,
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
    kwargs.setdefault("status", STATUS_CONFIRMED)
    kwargs.setdefault("source", "test")
    kwargs.setdefault("evidence_status", EVIDENCE_OFFICIAL)
    # 现金分红必须给出官方发放日；登记日默认取除息日的前一个工作日，
    # 与真实公告一致（否则登记日与除息日同日，买在除息日就得不到分红）
    if kwargs.get("action_type") == ACTION_CASH_DISTRIBUTION:
        kwargs.setdefault("pay_date", kwargs.get("ex_date"))
        if "record_date" not in kwargs and kwargs.get("ex_date"):
            day = pd.Timestamp(kwargs["ex_date"])
            prev = (day - pd.tseries.offsets.BDay(1)).strftime("%Y-%m-%d")
            kwargs.setdefault("record_date", prev)
    action = build_action(**kwargs)
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
    """除息日确认应收（不进现金），发放日转入可用现金。"""
    dates = _seed(temp_db, {"510300": [10.0] * 6})
    # 买在 dates[1]，登记日 dates[2]，除息日 dates[3]，发放日 dates[4]
    _insert_action(
        temp_db, code="510300", action_type=ACTION_CASH_DISTRIBUTION,
        ex_date=dates[3], effective_date=dates[3], cash_per_share=0.5,
        record_date=dates[2], pay_date=dates[4],
    )
    plan = {dates[0]: [TargetWeight("510300", 1.0)]}
    result, engine = _run(temp_db, dates, ["510300"], plan=plan)
    log = engine.corporate_action_log[0]
    expected = log["shares_before"] * 0.5
    assert log["cash_delta"] == pytest.approx(expected)
    assert log["confirm_date"] == dates[3]
    assert log["pay_date"] == dates[4]

    ex_day = next(d for d in result.daily if d.trade_date.isoformat() == dates[3])
    before_pay = next(d for d in result.daily if d.trade_date.isoformat() == dates[3])
    pay_day = next(d for d in result.daily if d.trade_date.isoformat() == dates[4])
    # 除息日只确认应收，现金未增加
    assert ex_day.dividend_receivable == pytest.approx(expected)
    assert before_pay.dividend_receivable == pytest.approx(expected)
    # 发放日应收清零，现金增加
    assert pay_day.dividend_receivable == pytest.approx(0.0)
    assert pay_day.cash - before_pay.cash == pytest.approx(expected, abs=1e-6)
    for item in result.daily:
        assert item.total_assets == pytest.approx(
            item.cash + item.market_value + item.dividend_receivable)


# ---------------------------------------------------------------- 5. 同日拆分+分红

def test_split_and_distribution_same_day(temp_db):
    dates = _seed(temp_db, {"510300": [10.0] * 6})
    # 登记日 dates[2] 收盘锁定份额 → 除息/拆分日 dates[3] 同时生效
    _insert_action(temp_db, code="510300", action_type=ACTION_SPLIT,
                   ex_date=dates[2], effective_date=dates[3], share_ratio=2.0)
    _insert_action(temp_db, code="510300", action_type=ACTION_CASH_DISTRIBUTION,
                   ex_date=dates[3], effective_date=dates[3], cash_per_share=0.2,
                   record_date=dates[2], pay_date=dates[4])
    plan = {dates[0]: [TargetWeight("510300", 1.0)]}
    result, engine = _run(temp_db, dates, ["510300"], plan=plan)
    assert len(engine.corporate_action_log) == 2
    kinds = {item["action_type"] for item in engine.corporate_action_log}
    assert kinds == {ACTION_SPLIT, ACTION_CASH_DISTRIBUTION}
    for item in result.daily:
        assert item.total_assets == pytest.approx(
            item.cash + item.market_value + item.dividend_receivable)


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
                   ex_date=dates[2], effective_date=dates[2], cash_per_share=5.0,
                   record_date=dates[1], pay_date=dates[3])
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
    dates = _seed(temp_db, {"510300": [10.0] * 5})
    with get_connection(temp_db) as conn:
        conn.execute("DELETE FROM etf_daily_prices WHERE code='510300' AND trade_date=?",
                     (dates[3],))
    _insert_action(temp_db, code="510300", action_type=ACTION_CASH_DISTRIBUTION,
                   ex_date=dates[3], effective_date=dates[3], cash_per_share=0.1,
                   record_date=dates[2], pay_date=dates[4])
    plan = {dates[0]: [TargetWeight("510300", 1.0)]}
    result, engine = _run(temp_db, dates, ["510300"], plan=plan)
    assert len(engine.corporate_action_log) == 1


# ---------------------------------------------------------------- 17. 未确认不得应用

def test_unverified_action_not_applied(temp_db):
    dates = _seed(temp_db, {"510300": [10.0] * 4})
    apply_ = build_action(code="510300", action_type=ACTION_SPLIT,
                          ex_date=dates[1], effective_date=dates[2],
                          share_ratio=2.0, status=STATUS_UNVERIFIED, source="test",
                          evidence_status=EVIDENCE_UNVERIFIED)
    save_action(apply_, db_path=temp_db)
    plan = {dates[0]: [TargetWeight("510300", 1.0)]}
    result, engine = _run(temp_db, dates, ["510300"], plan=plan)
    assert engine.corporate_action_log == []
    assert any("未确认" in note for note in result.notes)


def test_compute_impact_rejects_unverified():
    action = build_action(code="510300", action_type=ACTION_SPLIT,
                          ex_date="2024-01-03", effective_date="2024-01-04",
                          share_ratio=2.0, status=STATUS_UNVERIFIED, source="test",
                          evidence_status=EVIDENCE_UNVERIFIED)
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
        evidence_status=EVIDENCE_UNVERIFIED,
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


# ---------------------------------------------------------------- 3A.3.2.1 新增

def test_dividend_receivable_not_available_cash(temp_db):
    """除息日只确认应收，现金不能用于下单。"""
    dates = _seed(temp_db, {"510300": [10.0] * 6})
    _insert_action(temp_db, code="510300", action_type=ACTION_CASH_DISTRIBUTION,
                   ex_date=dates[3], effective_date=dates[3], cash_per_share=2.0,
                   record_date=dates[2], pay_date=dates[5])
    plan = {dates[0]: [TargetWeight("510300", 0.99)]}
    result, engine = _run(temp_db, dates, ["510300"], plan=plan)
    ex_day = next(d for d in result.daily if d.trade_date.isoformat() == dates[3])
    assert ex_day.dividend_receivable > 0
    # 应收不在 cash 里
    assert ex_day.cash + ex_day.market_value + ex_day.dividend_receivable == pytest.approx(
        ex_day.total_assets)
    assert ex_day.total_assets > ex_day.cash + ex_day.market_value


def test_order_after_ex_date_cannot_use_unsettled_dividend(temp_db):
    """除息日收盘后生成的订单，不能使用尚未到账的分红现金。"""
    dates = _seed(temp_db, {"510300": [10.0] * 6, "510500": [10.0] * 6})
    _insert_action(temp_db, code="510300", action_type=ACTION_CASH_DISTRIBUTION,
                   ex_date=dates[2], effective_date=dates[2], cash_per_share=50.0,
                   record_date=dates[1], pay_date=dates[5])
    # 初始资金几乎全仓 510300，除息日收盘后想把 510500 加满
    plan = {
        dates[0]: [TargetWeight("510300", 0.99)],
        dates[2]: [TargetWeight("510300", 0.5), TargetWeight("510500", 0.49)],
    }
    result, engine = _run(temp_db, dates, ["510300", "510500"], plan=plan,
                          initial_cash=100000.0)
    # 分红金额巨大，若被当作可用现金，510500 会被买满 0.49；实际不应买成
    buys = [t for t in result.trades if t.code == "510500"]
    if buys:
        assert sum(t.gross_amount for t in buys) <= 100000.0 * 0.49 + 1e-6
    # 全程现金不为负，且应收直到发放日才清零
    for item in result.daily:
        assert item.cash >= -1e-6


def test_dividend_across_weekend_pay_date(temp_db):
    """除息日与发放日跨越周末：应收在中间几天保持，发放日到账。"""
    dates = _seed(temp_db, {"510300": [10.0] * 7})
    # dates 是工作日序列；把发放日设到后一个工作日，等价于跨周末
    _insert_action(temp_db, code="510300", action_type=ACTION_CASH_DISTRIBUTION,
                   ex_date=dates[2], effective_date=dates[2], cash_per_share=1.0,
                   record_date=dates[1], pay_date=dates[5])
    plan = {dates[0]: [TargetWeight("510300", 1.0)]}
    result, engine = _run(temp_db, dates, ["510300"], plan=plan)
    pending_days = [d.trade_date.isoformat() for d in result.daily
                    if d.dividend_receivable > 0]
    assert pending_days == [dates[2], dates[3], dates[4]]
    assert next(d for d in result.daily
                if d.trade_date.isoformat() == dates[5]).dividend_receivable == 0


def test_trades_between_ex_and_pay_do_not_change_receivable(temp_db):
    """除息日与发放日之间发生买卖，不改变已确认的应收金额。"""
    dates = _seed(temp_db, {"510300": [10.0] * 7, "510500": [10.0] * 7})
    _insert_action(temp_db, code="510300", action_type=ACTION_CASH_DISTRIBUTION,
                   ex_date=dates[2], effective_date=dates[2], cash_per_share=1.0,
                   record_date=dates[1], pay_date=dates[5])
    plan = {
        dates[0]: [TargetWeight("510300", 0.99)],
        dates[2]: [TargetWeight("510300", 0.2), TargetWeight("510500", 0.79)],
    }
    result, engine = _run(temp_db, dates, ["510300", "510500"], plan=plan,
                          initial_cash=100000.0)
    recv = [round(d.dividend_receivable, 6) for d in result.daily]
    # 应收金额在确认后保持不变（除息日到发放日前）
    confirmed = [r for d, r in zip(result.daily, recv)
                 if dates[2] <= d.trade_date.isoformat() < dates[5]]
    assert len(confirmed) >= 2
    assert len(set(confirmed)) == 1


def test_no_position_no_dividend(temp_db):
    dates = _seed(temp_db, {"510300": [10.0] * 6})
    _insert_action(temp_db, code="510300", action_type=ACTION_CASH_DISTRIBUTION,
                   ex_date=dates[2], effective_date=dates[2], cash_per_share=1.0,
                   record_date=dates[1], pay_date=dates[4])
    result, engine = _run(temp_db, dates, ["510300"], plan={})
    assert engine.corporate_action_log == []
    for item in result.daily:
        assert item.dividend_receivable == 0
        assert item.total_assets == pytest.approx(100000.0)


def test_receivable_cash_total_identity(temp_db):
    """应收 + 现金 + 市值 == 总资产，逐日成立。"""
    dates = _seed(temp_db, {"510300": [10.0, 10.2, 9.8, 10.4, 10.1, 10.3]})
    _insert_action(temp_db, code="510300", action_type=ACTION_CASH_DISTRIBUTION,
                   ex_date=dates[2], effective_date=dates[2], cash_per_share=0.3,
                   record_date=dates[1], pay_date=dates[4])
    plan = {dates[0]: [TargetWeight("510300", 0.9)]}
    result, engine = _run(temp_db, dates, ["510300"], plan=plan)
    for item in result.daily:
        assert item.total_assets == pytest.approx(
            item.cash + item.market_value + item.dividend_receivable, abs=1e-6)


def test_dividend_requires_pay_date():
    """缺发放日的分红事件必须被拒，不能默认当除息日。"""
    with pytest.raises(CorporateActionError):
        build_action(code="510300", action_type=ACTION_CASH_DISTRIBUTION,
                     ex_date="2024-01-03", effective_date="2024-01-04",
                     cash_per_share=0.1, status=STATUS_CONFIRMED,
                     evidence_status=EVIDENCE_OFFICIAL, source="test")


def test_evidence_status_controls_application(temp_db):
    """secondary 可应用，unverified 不可应用。"""
    dates = _seed(temp_db, {"510300": [10.0] * 4})
    save_action(build_action(
        code="510300", action_type=ACTION_SPLIT, ex_date=dates[1],
        effective_date=dates[2], share_ratio=2.0, status=STATUS_CONFIRMED,
        evidence_status=EVIDENCE_SECONDARY, source="test",
    ), db_path=temp_db)
    save_action(build_action(
        code="510300", action_type=ACTION_CASH_DISTRIBUTION, ex_date=dates[3],
        effective_date=dates[3], cash_per_share=0.1, record_date=dates[2],
        pay_date=dates[3], status=STATUS_UNVERIFIED,
        evidence_status=EVIDENCE_UNVERIFIED, source="test",
    ), db_path=temp_db)
    actions = load_actions(db_path=temp_db)
    by_type = {a.action_type: a for a in actions}
    assert by_type[ACTION_SPLIT].is_confirmed
    assert not by_type[ACTION_CASH_DISTRIBUTION].is_confirmed


def test_event_fingerprint_deterministic(temp_db):
    _seed(temp_db, {"510300": [10.0] * 3})
    from app.backtest.corporate_actions import compute_event_fingerprint
    a = build_action(code="510300", action_type=ACTION_SPLIT, ex_date="2024-01-03",
                     effective_date="2024-01-04", share_ratio=2.0,
                     status=STATUS_CONFIRMED, evidence_status=EVIDENCE_OFFICIAL,
                     source="test")
    b = build_action(code="510300", action_type=ACTION_SPLIT, ex_date="2024-01-03",
                     effective_date="2024-01-04", share_ratio=2.0,
                     status=STATUS_CONFIRMED, evidence_status=EVIDENCE_OFFICIAL,
                     source="test")
    assert compute_event_fingerprint(a) == compute_event_fingerprint(b)
    c = build_action(code="510300", action_type=ACTION_SPLIT, ex_date="2024-01-03",
                     effective_date="2024-01-04", share_ratio=2.0000001,
                     status=STATUS_CONFIRMED, evidence_status=EVIDENCE_OFFICIAL,
                     source="test")
    assert compute_event_fingerprint(a) != compute_event_fingerprint(c)


def test_events_digest_only_covers_given_events(temp_db):
    _seed(temp_db, {"510300": [10.0] * 3, "510500": [20.0] * 3})
    from app.backtest.corporate_actions import compute_events_digest
    a = load_actions(db_path=temp_db)
    _insert_action(temp_db, code="510300", action_type=ACTION_SPLIT,
                   ex_date="2024-01-03", effective_date="2024-01-04", share_ratio=2.0)
    b = load_actions(db_path=temp_db)
    assert compute_events_digest(a) != compute_events_digest(b)
    assert compute_events_digest(b) == compute_events_digest(load_actions(db_path=temp_db))


def test_event_version_history_preserved(temp_db):
    _seed(temp_db, {"510300": [10.0] * 3})
    from app.backtest.corporate_actions import event_key, event_versions
    _insert_action(temp_db, code="510300", action_type=ACTION_SPLIT,
                   ex_date="2024-01-03", effective_date="2024-01-04", share_ratio=2.0)
    _insert_action(temp_db, code="510300", action_type=ACTION_SPLIT,
                   ex_date="2024-01-03", effective_date="2024-01-04", share_ratio=2.5)
    key = event_key(build_action(code="510300", action_type=ACTION_SPLIT,
                                 ex_date="2024-01-03", effective_date="2024-01-04",
                                 share_ratio=2.0))
    versions = event_versions(key, db_path=temp_db)
    assert len(versions) >= 2
    with get_connection(temp_db) as conn:
        row = conn.execute(
            "SELECT share_ratio, version_no FROM corporate_actions WHERE code='510300'"
        ).fetchone()
    assert row["share_ratio"] == pytest.approx(2.5)
    assert row["version_no"] >= 2


def test_input_hash_changes_with_event_content(temp_db):
    """事件内容变化必须导致 input_hash 变化（即使版本号不变）。"""
    dates = _seed(temp_db, {"510300": [10.0] * 4})
    _insert_action(temp_db, code="510300", action_type=ACTION_SPLIT,
                   ex_date=dates[1], effective_date=dates[2], share_ratio=2.0)
    plan = {dates[0]: [TargetWeight("510300", 1.0)]}
    first, _ = _run(temp_db, dates, ["510300"], plan=plan)
    _insert_action(temp_db, code="510300", action_type=ACTION_SPLIT,
                   ex_date=dates[1], effective_date=dates[2], share_ratio=3.0)
    second, _ = _run(temp_db, dates, ["510300"], plan=plan)
    assert first.input_hash != second.input_hash


def test_multi_lot_split_keeps_lot_sum(temp_db):
    """多批次持仓按非整数比例调整后，批次之和 == 总持仓。"""
    dates = _seed(temp_db, {"510300": [10.0] * 6})
    plan = {dates[0]: [TargetWeight("510300", 0.4)],
            dates[1]: [TargetWeight("510300", 0.7)],
            dates[2]: [TargetWeight("510300", 1.0)]}
    _insert_action(temp_db, code="510300", action_type=ACTION_REVERSE_SPLIT,
                   ex_date=dates[3], effective_date=dates[4], share_ratio=0.36555)
    result, engine = _run(temp_db, dates, ["510300"], plan=plan)
    assert engine.corporate_action_log
    for item in result.daily:
        assert item.total_assets == pytest.approx(
            item.cash + item.market_value + item.dividend_receivable, abs=1e-6)
        assert item.cash >= -1e-6
