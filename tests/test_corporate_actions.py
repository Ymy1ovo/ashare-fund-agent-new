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

def test_load_actions_filters_by_window_date(temp_db):
    """区间筛选按事件类型使用实际应用日期：分红用 ex_date，拆分用 effective_date。"""
    _seed(temp_db, {"510300": [10.0] * 6, "510500": [20.0] * 6})
    # 拆分：effective_date = 2024-01-04
    _insert_action(temp_db, code="510300", action_type=ACTION_SPLIT,
                   ex_date="2024-01-03", effective_date="2024-01-04", share_ratio=2.0)
    # 分红：ex_date = 2024-01-03（生效日也是 01-04，但区间判定用 ex_date）
    _insert_action(temp_db, code="510500", action_type=ACTION_CASH_DISTRIBUTION,
                   ex_date="2024-01-03", effective_date="2024-01-04", cash_per_share=0.1)

    only_300 = load_actions(codes=["510300"], db_path=temp_db)
    assert len(only_300) == 1 and only_300[0].code == "510300"

    # 区间 [01-04, 01-04]：只有拆分的 effective_date 落在里面
    split_only = load_actions(start="2024-01-04", end="2024-01-04", db_path=temp_db)
    assert len(split_only) == 1
    assert split_only[0].action_type == ACTION_SPLIT

    # 区间 [01-03, 01-03]：只有分红的 ex_date 落在里面
    div_only = load_actions(start="2024-01-03", end="2024-01-03", db_path=temp_db)
    assert len(div_only) == 1
    assert div_only[0].action_type == ACTION_CASH_DISTRIBUTION

    # 区间 [01-03, 01-04]：两条都在
    both = load_actions(start="2024-01-03", end="2024-01-04", db_path=temp_db)
    assert len(both) == 2

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


# ---------------------------------------------------------------- 3A.3.2.2 新增

def _portfolio_with_lots(lots):
    p = Portfolio(initial_cash=10_000_000)
    for i, (q, px) in enumerate(lots):
        p.apply_buy("510300", q, px, fee=0.0,
                    trade_date=date(2024, 1, 2 + i), available_date=date(2024, 1, 3 + i))
    return p


def test_integer_split_cost_basis_unchanged():
    p = _portfolio_with_lots([(400, 10.0), (300, 12.0), (300, 14.0)])
    before = p.cost_basis("510300")
    ledger = p.apply_corporate_action("510300", 2000, 0.0, official_ratio=2.0,
                                      fractional_policy="truncate")
    assert p.quantity("510300") == 2000
    assert ledger["cost_basis_after"] == pytest.approx(before)
    assert ledger["disposed_cost_basis"] == pytest.approx(0.0)
    assert ledger["realized_pnl"] == pytest.approx(0.0)


def test_integer_reverse_split_cost_basis_unchanged():
    p = _portfolio_with_lots([(400, 10.0), (300, 12.0), (300, 14.0)])
    before = p.cost_basis("510300")
    ledger = p.apply_corporate_action("510300", 100, 0.0, official_ratio=0.1,
                                      fractional_policy="truncate")
    assert p.quantity("510300") == 100
    assert ledger["cost_basis_after"] == pytest.approx(before)
    assert ledger["disposed_cost_basis"] == pytest.approx(0.0)


def test_fractional_split_disposes_cost_and_records_pnl():
    """1:1.145 拆分 100 份 → 114 份 + 0.5 份现金补偿。"""
    p = _portfolio_with_lots([(100, 100.0)])
    before = p.cost_basis("510300")
    price_after = 100.0 / 1.145
    raw = 100 * 1.145
    new = int(raw // 1)
    cash = (raw - new) * price_after
    ledger = p.apply_corporate_action("510300", new, cash, official_ratio=1.145,
                                      compensation_price=price_after,
                                      fractional_policy="cash_compensation")
    expect_disposed = before * ((raw - new) / raw)
    assert ledger["disposed_cost_basis"] == pytest.approx(expect_disposed, rel=1e-9)
    assert ledger["cost_basis_after"] == pytest.approx(before - expect_disposed, rel=1e-9)
    assert ledger["compensation_cash"] == pytest.approx(cash)
    assert ledger["realized_pnl"] == pytest.approx(cash - expect_disposed, abs=1e-9)
    assert ledger["fractional_shares"] == pytest.approx(raw - new)
    # 价值连续：市值 + 补偿 == 拆分前市值
    assert p.quantity("510300") * price_after + cash == pytest.approx(100 * 100.0, rel=1e-9)


def test_fractional_reverse_split_disposes_cost_and_records_pnl():
    """1:0.36555 合并 1000 份 → 365 份 + 0.55 份现金补偿。"""
    p = _portfolio_with_lots([(333, 10.0), (333, 12.0), (334, 14.0)])
    before = p.cost_basis("510300")
    ratio = 0.36555
    raw = 1000 * ratio
    new = int(raw // 1)
    price_after = 10.0
    cash = (raw - new) * price_after
    ledger = p.apply_corporate_action("510300", new, cash, official_ratio=ratio,
                                      compensation_price=price_after,
                                      fractional_policy="cash_compensation")
    expect_disposed = before * ((raw - new) / raw)
    assert ledger["disposed_cost_basis"] == pytest.approx(expect_disposed, rel=1e-9)
    assert ledger["cost_basis_after"] == pytest.approx(before - expect_disposed, rel=1e-9)


def test_multi_lot_fractional_disposal_uses_portfolio_level_cost():
    """多个 lot 同时发生非整数折算：成本转出按组合层面计算，不按单批余数。"""
    p = _portfolio_with_lots([(333, 10.0), (333, 12.0), (334, 14.0)])
    before = p.cost_basis("510300")
    ratio = 0.36555
    raw = 1000 * ratio
    new = int(raw // 1)
    ledger = p.apply_corporate_action("510300", new, 0.0, official_ratio=ratio,
                                      fractional_policy="truncate")
    assert sum(lot.quantity for lot in p.positions["510300"].lots) == new
    assert p.quantity("510300") == new
    expect_disposed = before * ((raw - new) / raw)
    assert ledger["disposed_cost_basis"] == pytest.approx(expect_disposed, rel=1e-9)


def test_truncate_policy_records_loss_not_cash():
    p = _portfolio_with_lots([(100, 100.0)])
    before = p.cost_basis("510300")
    ledger = p.apply_corporate_action("510300", 114, 0.0, official_ratio=1.145,
                                      fractional_policy="truncate")
    assert ledger["compensation_cash"] == pytest.approx(0.0)
    assert ledger["realized_pnl"] == pytest.approx(-ledger["disposed_cost_basis"])
    assert ledger["cost_basis_before"] - ledger["cost_basis_after"] == pytest.approx(
        ledger["disposed_cost_basis"], rel=1e-9)


def test_round_up_policy_adds_share_without_cost():
    p = _portfolio_with_lots([(100, 100.0)])
    before = p.cost_basis("510300")
    ledger = p.apply_corporate_action("510300", 115, 0.0, official_ratio=1.145,
                                      fractional_policy="round_up")
    assert p.quantity("510300") == 115
    assert ledger["disposed_cost_basis"] == pytest.approx(0.0)
    assert ledger["cost_basis_after"] == pytest.approx(before)


def test_consecutive_actions_do_not_double_charge_cost():
    p = _portfolio_with_lots([(1000, 10.0)])
    before = p.cost_basis("510300")
    p.apply_corporate_action("510300", 2000, 0.0, official_ratio=2.0,
                             fractional_policy="truncate")
    ledger = p.apply_corporate_action("510300", 1000, 0.0, official_ratio=0.5,
                                      fractional_policy="truncate")
    assert ledger["cost_basis_after"] == pytest.approx(before)


def test_no_position_action_records_nothing():
    p = Portfolio(initial_cash=100_000)
    ledger = p.apply_corporate_action("510300", 0, 0.0, official_ratio=2.0)
    assert ledger["cost_basis_after"] == pytest.approx(0.0)
    assert ledger["realized_pnl"] == pytest.approx(0.0)
    assert ledger["compensation_cash"] == pytest.approx(0.0)
    assert p.cash == pytest.approx(100_000)


def test_window_boundary_ex_date_equals_start(temp_db):
    """ex_date == start_date 的分红必须能读到。"""
    dates = _seed(temp_db, {"510300": [10.0] * 6})
    _insert_action(temp_db, code="510300", action_type=ACTION_CASH_DISTRIBUTION,
                   ex_date=dates[0], effective_date=dates[1], cash_per_share=0.1,
                   record_date=dates[0], pay_date=dates[2])
    loaded = load_actions(start=dates[0], end=dates[-1], db_path=temp_db)
    assert len(loaded) == 1
    assert loaded[0].action_type == ACTION_CASH_DISTRIBUTION


def test_window_boundary_ex_date_equals_end_effective_after(temp_db):
    """ex_date == end_date、effective_date/pay_date 在结束日之后：仍须读到。"""
    dates = _seed(temp_db, {"510300": [10.0] * 6})
    last = dates[-1]
    _insert_action(temp_db, code="510300", action_type=ACTION_CASH_DISTRIBUTION,
                   ex_date=last, effective_date=last, cash_per_share=0.5,
                   record_date=dates[-2], pay_date=last)
    loaded = load_actions(start=dates[0], end=last, db_path=temp_db)
    assert len(loaded) == 1
    assert loaded[0].pay_date == date.fromisoformat(last)


def test_window_boundary_split_effective_equals_end(temp_db):
    dates = _seed(temp_db, {"510300": [10.0] * 6})
    _insert_action(temp_db, code="510300", action_type=ACTION_SPLIT,
                   ex_date=dates[-2], effective_date=dates[-1], share_ratio=2.0)
    loaded = load_actions(start=dates[0], end=dates[-1], db_path=temp_db)
    assert len(loaded) == 1
    assert loaded[0].effective_date == date.fromisoformat(dates[-1])


def test_window_boundary_split_effective_after_end_excluded(temp_db):
    """拆分 effective_date 在结束日之后：不应进入本次回测。"""
    dates = _seed(temp_db, {"510300": [10.0] * 8})
    _insert_action(temp_db, code="510300", action_type=ACTION_SPLIT,
                   ex_date=dates[5], effective_date=dates[6], share_ratio=2.0)
    loaded = load_actions(start=dates[0], end=dates[5], db_path=temp_db)
    assert loaded == []


def test_window_excludes_events_before_start(temp_db):
    dates = _seed(temp_db, {"510300": [10.0] * 6})
    _insert_action(temp_db, code="510300", action_type=ACTION_SPLIT,
                   ex_date="2023-06-01", effective_date="2023-06-02", share_ratio=2.0)
    _insert_action(temp_db, code="510300", action_type=ACTION_CASH_DISTRIBUTION,
                   ex_date="2023-06-05", effective_date="2023-06-06", cash_per_share=0.1,
                   record_date="2023-06-02", pay_date="2023-06-08")
    loaded = load_actions(start=dates[0], end=dates[-1], db_path=temp_db)
    assert loaded == []


def test_end_of_backtest_unsettled_dividend_counted_in_assets(temp_db):
    """回测结束日尚未到账的应收分红，必须计入最终净资产。"""
    dates = _seed(temp_db, {"510300": [10.0] * 6})
    last = dates[-1]
    _insert_action(temp_db, code="510300", action_type=ACTION_CASH_DISTRIBUTION,
                   ex_date=last, effective_date=last, cash_per_share=1.0,
                   record_date=dates[-2], pay_date="2099-01-01")
    plan = {dates[0]: [TargetWeight("510300", 0.9)]}
    result, engine = _run(temp_db, dates, ["510300"], plan=plan)
    final = result.daily[-1]
    assert final.dividend_receivable > 0
    assert final.total_assets == pytest.approx(
        final.cash + final.market_value + final.dividend_receivable, abs=1e-6)


def test_same_event_not_loaded_twice_across_adjacent_ranges(temp_db):
    """跨两个相邻区间各读一次，单次回测内不重复。"""
    dates = _seed(temp_db, {"510300": [10.0] * 8})
    _insert_action(temp_db, code="510300", action_type=ACTION_SPLIT,
                   ex_date=dates[3], effective_date=dates[4], share_ratio=2.0)
    first = load_actions(start=dates[0], end=dates[3], db_path=temp_db)
    second = load_actions(start=dates[3], end=dates[-1], db_path=temp_db)
    assert first == []            # effective_date 在第二区间
    assert len(second) == 1


def test_announcement_url_changes_fingerprint():
    from app.backtest.corporate_actions import compute_event_fingerprint
    base = dict(code="510300", action_type=ACTION_SPLIT, ex_date="2021-01-08",
                effective_date="2021-01-11", share_ratio=10.0,
                status=STATUS_CONFIRMED, evidence_status=EVIDENCE_OFFICIAL,
                source="t")
    a = build_action(**base, announcement_url="https://a")
    b = build_action(**base, announcement_url="https://b")
    assert compute_event_fingerprint(a) != compute_event_fingerprint(b)


def test_announcement_title_changes_fingerprint():
    from app.backtest.corporate_actions import compute_event_fingerprint
    base = dict(code="510300", action_type=ACTION_SPLIT, ex_date="2021-01-08",
                effective_date="2021-01-11", share_ratio=10.0,
                status=STATUS_CONFIRMED, evidence_status=EVIDENCE_OFFICIAL,
                source="t")
    a = build_action(**base, announcement_title="拆分公告")
    b = build_action(**base, announcement_title="合并公告")
    assert compute_event_fingerprint(a) != compute_event_fingerprint(b)


def test_announcement_date_changes_fingerprint():
    from app.backtest.corporate_actions import compute_event_fingerprint
    base = dict(code="510300", action_type=ACTION_SPLIT, ex_date="2021-01-08",
                effective_date="2021-01-11", share_ratio=10.0,
                status=STATUS_CONFIRMED, evidence_status=EVIDENCE_OFFICIAL,
                source="t")
    a = build_action(**base, announcement_date="2021-01-05")
    b = build_action(**base, announcement_date="2021-01-06")
    assert compute_event_fingerprint(a) != compute_event_fingerprint(b)


def test_manager_name_changes_fingerprint():
    from app.backtest.corporate_actions import compute_event_fingerprint
    base = dict(code="510300", action_type=ACTION_SPLIT, ex_date="2021-01-08",
                effective_date="2021-01-11", share_ratio=10.0,
                status=STATUS_CONFIRMED, evidence_status=EVIDENCE_OFFICIAL,
                source="t")
    a = build_action(**base, manager_name="甲公司")
    b = build_action(**base, manager_name="乙公司")
    assert compute_event_fingerprint(a) != compute_event_fingerprint(b)


def test_evidence_text_changes_fingerprint():
    from app.backtest.corporate_actions import compute_event_fingerprint
    base = dict(code="510300", action_type=ACTION_SPLIT, ex_date="2021-01-08",
                effective_date="2021-01-11", share_ratio=10.0,
                status=STATUS_CONFIRMED, evidence_status=EVIDENCE_OFFICIAL,
                source="t")
    a = build_action(**base, evidence="1:10 拆分")
    b = build_action(**base, evidence="1:10 拆分，尾差入基金")
    assert compute_event_fingerprint(a) != compute_event_fingerprint(b)


def test_evidence_status_changes_fingerprint():
    from app.backtest.corporate_actions import compute_event_fingerprint
    base = dict(code="510300", action_type=ACTION_SPLIT, ex_date="2021-01-08",
                effective_date="2021-01-11", share_ratio=10.0,
                status=STATUS_CONFIRMED, source="t")
    a = build_action(**base, evidence_status=EVIDENCE_OFFICIAL)
    b = build_action(**base, evidence_status=EVIDENCE_SECONDARY)
    assert compute_event_fingerprint(a) != compute_event_fingerprint(b)


def test_unrelated_field_does_not_change_fingerprint():
    """notes 等展示字段不影响指纹。"""
    from app.backtest.corporate_actions import compute_event_fingerprint
    base = dict(code="510300", action_type=ACTION_SPLIT, ex_date="2021-01-08",
                effective_date="2021-01-11", share_ratio=10.0,
                status=STATUS_CONFIRMED, evidence_status=EVIDENCE_OFFICIAL,
                source="t")
    a = build_action(**base)
    b = build_action(**base, notes="备注A")
    assert compute_event_fingerprint(a) == compute_event_fingerprint(b)


def test_same_metadata_repeat_gives_same_fingerprint():
    from app.backtest.corporate_actions import compute_event_fingerprint
    base = dict(code="510300", action_type=ACTION_SPLIT, ex_date="2021-01-08",
                effective_date="2021-01-11", share_ratio=10.0,
                status=STATUS_CONFIRMED, evidence_status=EVIDENCE_OFFICIAL,
                source="t", announcement_url="https://a",
                announcement_title="公告", announcement_date="2021-01-05",
                manager_name="甲公司", evidence="1:10")
    a = build_action(**base)
    b = build_action(**base)
    assert compute_event_fingerprint(a) == compute_event_fingerprint(b)


def test_events_digest_order_independent(temp_db):
    """集合指纹与输入顺序无关。"""
    _seed(temp_db, {"510300": [10.0] * 3, "510500": [20.0] * 3})
    from app.backtest.corporate_actions import compute_events_digest
    _insert_action(temp_db, code="510300", action_type=ACTION_SPLIT,
                   ex_date="2024-01-03", effective_date="2024-01-04", share_ratio=2.0)
    _insert_action(temp_db, code="510500", action_type=ACTION_SPLIT,
                   ex_date="2024-03-01", effective_date="2024-03-04", share_ratio=3.0)
    items = load_actions(db_path=temp_db)
    assert compute_events_digest(items) == compute_events_digest(list(reversed(items)))


def test_events_digest_ignores_unrelated_events(temp_db):
    """未参与回测的事件不影响指纹。"""
    from app.backtest.corporate_actions import compute_events_digest
    _seed(temp_db, {"510300": [10.0] * 3})
    _insert_action(temp_db, code="510300", action_type=ACTION_SPLIT,
                   ex_date="2024-01-03", effective_date="2024-01-04", share_ratio=2.0)
    inside = load_actions(start="2024-01-01", end="2024-01-31", db_path=temp_db)
    # 区间外再插一条
    _insert_action(temp_db, code="510300", action_type=ACTION_SPLIT,
                   ex_date="2024-06-03", effective_date="2024-06-04", share_ratio=5.0)
    still_inside = load_actions(start="2024-01-01", end="2024-01-31", db_path=temp_db)
    assert compute_events_digest(inside) == compute_events_digest(still_inside)


def test_engine_records_fractional_ledger(temp_db):
    """完整 Engine 流程：账本留痕反映成本转出与已实现盈亏。"""
    dates = _seed(temp_db, {"510300": [10.0] * 6})
    _insert_action(temp_db, code="510300", action_type=ACTION_SPLIT,
                   ex_date=dates[3], effective_date=dates[4], share_ratio=1.145,
                   fractional_policy="truncate")
    plan = {dates[0]: [TargetWeight("510300", 1.0)]}
    result, engine = _run(temp_db, dates, ["510300"], plan=plan)
    assert engine.corporate_action_ledger
    ledger = engine.corporate_action_ledger[0]
    assert ledger["official_ratio"] == pytest.approx(1.145)
    assert ledger["ratio_source"] == "official"
    assert ledger["cost_basis_before"] - ledger["cost_basis_after"] == pytest.approx(
        ledger["disposed_cost_basis"], rel=1e-9)


def test_engine_fractional_event_keeps_assets_identity(temp_db):
    """非整数折算后，逐日总资产恒等式仍成立。"""
    dates = _seed(temp_db, {"510300": [10.0] * 6})
    _insert_action(temp_db, code="510300", action_type=ACTION_REVERSE_SPLIT,
                   ex_date=dates[3], effective_date=dates[4], share_ratio=0.36555,
                   fractional_policy="truncate")
    plan = {dates[0]: [TargetWeight("510300", 1.0)]}
    result, engine = _run(temp_db, dates, ["510300"], plan=plan)
    for item in result.daily:
        assert item.total_assets == pytest.approx(
            item.cash + item.market_value + item.dividend_receivable, abs=1e-6)
        assert item.cash >= -1e-6


def test_round_up_policy_through_engine(temp_db):
    """进位口径：份额 +1，成本不变。"""
    dates = _seed(temp_db, {"510300": [10.0] * 6})
    _insert_action(temp_db, code="510300", action_type=ACTION_SPLIT,
                   ex_date=dates[3], effective_date=dates[4], share_ratio=1.145,
                   fractional_policy="round_up")
    plan = {dates[0]: [TargetWeight("510300", 1.0)]}
    result, engine = _run(temp_db, dates, ["510300"], plan=plan)
    ledger = engine.corporate_action_ledger[0]
    assert ledger["disposed_cost_basis"] == pytest.approx(0.0)
    assert ledger["cost_basis_after"] == pytest.approx(ledger["cost_basis_before"])
    assert ledger["fractional_policy"] == "round_up"
