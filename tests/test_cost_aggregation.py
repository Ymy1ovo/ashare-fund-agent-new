"""阶段3A.2.1.1.2.1.1 专项测试：绩效总交易成本口径。

核心：total_cost 必须包含佣金 + 印花税 + 过户费 + 滑点，
而 total_commission 只含佣金、total_slippage 只含滑点。
"""
from __future__ import annotations

from datetime import date

import pytest

from app.backtest.metrics import Performance, compute_performance
from app.backtest.models import DailySnapshot, Trade


def _trade(
    trade_id: int = 1,
    order_id: int = 1,
    side: str = "sell",
    gross: float = 1000.0,
    commission: float = 0.0,
    stamp_tax: float = 0.0,
    transfer_fee: float = 0.0,
    slippage: float = 0.0,
    realized: float = 0.0,
) -> Trade:
    return Trade(
        trade_id=trade_id, order_id=order_id, code="510300", side=side,
        trade_date=date(2024, 1, 3), quantity=100, price=gross / 100.0,
        gross_amount=gross, commission=commission, stamp_tax=stamp_tax,
        transfer_fee=transfer_fee, slippage_cost=slippage,
        realized_pnl=realized, cash_after=1_000_000.0,
    )


def _daily(navs: list[float]) -> list[DailySnapshot]:
    out = []
    for index, nav in enumerate(navs):
        day = date(2024, 1, 2) + __import__("datetime").timedelta(days=index)
        out.append(DailySnapshot(
            trade_date=day, cash=nav * 1000, market_value=0.0,
            total_assets=nav * 1000, nav=nav, positions={}, prices={},
            price_status={},
        ))
    return out


def _perf(trades: list[Trade]) -> Performance:
    return compute_performance(_daily([1.0, 1.01, 1.02, 1.03]), trades, [],
                               1_000_000.0)


# ==================================================== 场景 A

def test_scenario_a_total_cost_includes_taxes_and_slippage() -> None:
    """场景A：commission 6 + stamp 10 + transfer 0.2 + slippage 2 = 18.2。"""
    trade = _trade(commission=6.0, stamp_tax=10.0, transfer_fee=0.2, slippage=2.0)
    perf = _perf([trade])

    assert perf.total_commission == pytest.approx(6.0)
    assert perf.total_stamp_tax == pytest.approx(10.0)
    assert perf.total_transfer_fee == pytest.approx(0.2)
    assert perf.total_slippage == pytest.approx(2.0)
    assert perf.total_trade_fees == pytest.approx(16.2)
    assert perf.total_cost == pytest.approx(18.2), "总成本必须含税费与滑点"
    assert perf.total_cost == pytest.approx(
        perf.total_trade_fees + perf.total_slippage
    )


def test_scenario_a_old_formula_would_undercount() -> None:
    """回归：旧公式 total_commission + slippage 会漏掉税费。"""
    trade = _trade(commission=6.0, stamp_tax=10.0, transfer_fee=0.2, slippage=2.0)
    perf = _perf([trade])

    old_formula = perf.total_commission + perf.total_slippage   # = 8.0
    assert old_formula == pytest.approx(8.0)
    assert perf.total_cost == pytest.approx(18.2)
    assert perf.total_cost - old_formula == pytest.approx(10.2), (
        "旧公式漏掉的正是印花税 + 过户费"
    )


# ==================================================== 场景 B

def test_scenario_b_zero_tax_compat() -> None:
    """场景B：税费为 0 时，total_cost = 佣金 + 滑点，兼容旧配置。"""
    trade = _trade(commission=5.0, stamp_tax=0.0, transfer_fee=0.0, slippage=1.0)
    perf = _perf([trade])

    assert perf.total_commission == pytest.approx(5.0)
    assert perf.total_stamp_tax == pytest.approx(0.0)
    assert perf.total_transfer_fee == pytest.approx(0.0)
    assert perf.total_cost == pytest.approx(6.0)


# ==================================================== 场景 C

def test_scenario_c_mixed_buy_sell_trades() -> None:
    """场景C：多笔买卖混合，总成本 = 所有费用 + 所有滑点。"""
    trades = [
        _trade(1, 1, "buy", 10_000, commission=5.0, transfer_fee=0.10, slippage=3.0),
        _trade(2, 2, "sell", 12_000, commission=5.0, stamp_tax=6.0,
               transfer_fee=0.12, slippage=4.0),
        _trade(3, 3, "buy", 8_000, commission=5.0, transfer_fee=0.08, slippage=2.5),
    ]
    perf = _perf(trades)

    assert perf.total_commission == pytest.approx(15.0)
    assert perf.total_stamp_tax == pytest.approx(6.0)
    assert perf.total_transfer_fee == pytest.approx(0.30)
    assert perf.total_slippage == pytest.approx(9.5)
    assert perf.total_trade_fees == pytest.approx(21.30)
    assert perf.total_cost == pytest.approx(30.80)

    # 与逐笔累加一致
    manual = sum(t.total_fees + t.slippage_cost for t in trades)
    assert perf.total_cost == pytest.approx(manual)


# ==================================================== 场景 D

def test_scenario_d_all_zero_cost() -> None:
    """场景D：所有费用为 0 → total_cost = 0。"""
    trade = _trade(commission=0.0, stamp_tax=0.0, transfer_fee=0.0, slippage=0.0)
    perf = _perf([trade])
    assert perf.total_commission == 0.0
    assert perf.total_slippage == 0.0
    assert perf.total_cost == 0.0


def test_no_trades_zero_cost() -> None:
    perf = compute_performance(_daily([1.0, 1.01]), [], [], 1_000_000.0)
    assert perf.total_cost == 0.0
    assert perf.total_commission == 0.0
    assert perf.total_slippage == 0.0


# ==================================================== 场景 E

def test_scenario_e_multi_fill_uses_trade_total_fees() -> None:
    """场景E：同一订单多次部分成交，total_cost 用 total_fees 而非 commission。"""
    trades = [
        _trade(1, 1, "sell", 10_000, commission=5.0, stamp_tax=5.0,
               transfer_fee=0.10, slippage=2.0),
        _trade(2, 1, "sell", 10_000, commission=1.0, stamp_tax=5.0,
               transfer_fee=0.10, slippage=2.0),
    ]
    perf = _perf(trades)

    assert perf.total_commission == pytest.approx(6.0), "佣金 5 + 1"
    assert perf.total_stamp_tax == pytest.approx(10.0)
    assert perf.total_transfer_fee == pytest.approx(0.20)
    assert perf.total_slippage == pytest.approx(4.0)
    assert perf.total_trade_fees == pytest.approx(16.20)
    assert perf.total_cost == pytest.approx(20.20), "16.20 + 4.0"

    # 若误用 commission 当全部费用会得到 6 + 4 = 10.0
    wrong = perf.total_commission + perf.total_slippage
    assert wrong == pytest.approx(10.0)
    assert perf.total_cost > wrong, "漏计税费会被低估"


# ==================================================== 字段语义

def test_total_commission_only_commission() -> None:
    """total_commission 只统计佣金，不含税费。"""
    trade = _trade(commission=3.0, stamp_tax=100.0, transfer_fee=50.0, slippage=1.0)
    perf = _perf([trade])
    assert perf.total_commission == pytest.approx(3.0)
    assert perf.total_commission < perf.total_trade_fees


def test_total_slippage_only_slippage() -> None:
    """total_slippage 只统计滑点，不混入费用。"""
    trade = _trade(commission=50.0, stamp_tax=50.0, transfer_fee=50.0, slippage=2.0)
    perf = _perf([trade])
    assert perf.total_slippage == pytest.approx(2.0)


def test_total_cost_components_additive() -> None:
    """total_cost = commission + stamp + transfer + slippage。"""
    trade = _trade(commission=7.0, stamp_tax=11.0, transfer_fee=0.3, slippage=1.5)
    perf = _perf([trade])
    assert perf.total_cost == pytest.approx(
        perf.total_commission + perf.total_stamp_tax
        + perf.total_transfer_fee + perf.total_slippage
    )


def test_performance_as_dict_contains_new_fields() -> None:
    """Performance.as_dict() 必须暴露新增成本字段。"""
    trade = _trade(commission=1.0, stamp_tax=2.0, transfer_fee=0.5, slippage=0.5)
    payload = _perf([trade]).as_dict()
    for key in ("total_cost", "total_commission", "total_slippage",
                "total_stamp_tax", "total_transfer_fee", "total_trade_fees"):
        assert key in payload, f"缺少字段 {key}"
    assert payload["total_cost"] == pytest.approx(4.0)


def test_report_renders_separate_cost_lines() -> None:
    """报告必须分别列出佣金、税费、滑点与总成本。"""
    from app.backtest.engine import BacktestResult
    from app.backtest.report import render_report

    from app.backtest.config import BacktestConfig

    trade = _trade(commission=6.0, stamp_tax=10.0, transfer_fee=0.2, slippage=2.0)
    perf = _perf([trade])
    daily = _daily([1.0, 1.01, 1.02, 1.03])
    result = BacktestResult(
        run_id="test",
        config=BacktestConfig(start_date="2024-01-02", end_date="2024-01-05"),
        strategy_name="t", strategy_version="1",
        codes=["510300"], indicator_version=None, snapshot_ids={}, rules={},
        daily=daily, orders=[], trades=[trade], initial_cash=1_000_000.0,
        input_hash="x",
    )
    text = render_report(result, perf)
    assert "佣金合计" in text
    assert "印花税合计" in text
    assert "过户费合计" in text
    assert "总成本（费用+滑点）" in text
    assert "18.20" in text, "报告应展示正确的总成本"


# ==================================================== 历史语义兼容

def test_cost_semantics_legacy_vs_new() -> None:
    """新旧记录的成本口径必须可区分。"""
    from app.backtest.api import (
        COST_SEMANTICS,
        cost_semantics_of,
        describe_cost_semantics,
    )

    legacy = {"performance": {"total_cost": 100.0}}
    assert cost_semantics_of(legacy) == "legacy"
    desc = describe_cost_semantics(legacy)
    assert desc["includes_taxes"] is False
    assert "均为 0" in desc["note"], "必须说明历史税率为 0 的前提"

    new = {"cost_semantics": COST_SEMANTICS}
    assert cost_semantics_of(new) == COST_SEMANTICS
    assert describe_cost_semantics(new)["includes_taxes"] is True


def test_cost_semantics_empty_summary() -> None:
    from app.backtest.api import cost_semantics_of

    assert cost_semantics_of(None) == "legacy"
    assert cost_semantics_of({}) == "legacy"


def test_new_run_summary_tagged(temp_db) -> None:
    """新回测写入 summary 时必须带 cost_semantics 标记。"""
    import json
    import sqlite3

    from app.backtest.config import BacktestConfig
    from app.backtest.engine import BacktestEngine
    from app.backtest.metrics import compute_performance
    from app.backtest.storage import save_result
    from app.backtest.strategies.buy_and_hold import BuyAndHoldStrategy
    from tests.test_backtest_integration import _seed_market

    dates = _seed_market(temp_db, {"510300": [10.0, 10.5, 11.0]})
    cfg = BacktestConfig(start_date=dates[0], end_date=dates[-1], initial_cash=100_000)
    result = BacktestEngine(cfg, BuyAndHoldStrategy(), db_path=temp_db).run(
        ["510300"], indicator_version=None
    )
    perf = compute_performance(result.daily, result.trades, result.orders,
                               result.initial_cash)
    save_result(result, perf, db_path=temp_db)

    with sqlite3.connect(temp_db) as conn:
        row = conn.execute(
            "SELECT summary_json FROM backtest_runs WHERE run_id=?", (result.run_id,)
        ).fetchone()
    summary = json.loads(row[0])
    assert summary.get("cost_semantics"), "新记录必须标记成本口径"
    assert "taxes" in summary["cost_semantics"]
