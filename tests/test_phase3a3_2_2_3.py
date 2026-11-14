"""阶段3A.3.2.2.3：非正式口径持久化与异常路径测试。

全部走真实 Engine / 存储 / API 路径，不测孤立数学函数。
"""
from __future__ import annotations

import sqlite3

import pytest

import app.backtest.corporate_actions as ca
from app.backtest.api import (
    ACCOUNTING_DISABLED,
    ACCOUNTING_FORMAL,
    ACCOUNTING_UNKNOWN,
    accounting_basis_of,
    formal_valuation_of,
    get_run,
    is_formal_run,
    list_runs,
)
from app.backtest.config import BacktestConfig
from app.backtest.engine import BacktestEngine, CorporateActionLoadError
from app.backtest.metrics import compute_performance
from app.backtest.storage import save_result
from app.backtest.strategies.base import TargetWeight
from tests.test_corporate_actions import ACTION_SPLIT, _insert_action, _run, _seed


class _Fixed:
    name = "fixed"
    version = "1.0.0"

    def __init__(self, plan):
        self.plan = plan

    def target_weights(self, context):
        return self.plan.get(context.signal_date.isoformat())


def _plan(dates, weight=0.5):
    return {dates[0]: [TargetWeight("510300", weight)]}


def _engine(temp_db, dates, plan):
    cfg = BacktestConfig(start_date=dates[0], end_date=dates[-1],
                         initial_cash=100000.0)
    return cfg, BacktestEngine(cfg, _Fixed(plan), db_path=temp_db)


# ------------------------------------------------ 问题1：SQL 执行异常必须中止

def test_sql_execution_error_raises_load_error(temp_db, monkeypatch):
    """load_actions 执行 SQL 抛错 → Engine 必须抛 CorporateActionLoadError。"""
    dates = _seed(temp_db, {"510300": [10.0] * 4})

    def _boom(**kwargs):
        raise sqlite3.OperationalError("database disk image is malformed")

    monkeypatch.setattr(ca, "load_actions", _boom)
    cfg, engine = _engine(temp_db, dates, {})
    with pytest.raises(CorporateActionLoadError, match="公司行为事件加载失败"):
        engine.run(["510300"], indicator_version=None)


def test_deserialization_error_raises_load_error(temp_db):
    """事件行反序列化失败（日期非法）→ Engine 必须抛 CorporateActionLoadError。

    走真实 load_actions → action_from_row 路径，不 monkeypatch。
    """
    dates = _seed(temp_db, {"510300": [10.0] * 4})
    conn = sqlite3.connect(temp_db)
    conn.execute(
        "INSERT INTO corporate_actions "
        "(code, action_type, ex_date, effective_date, share_ratio, source, status, "
        " data_version, created_at, updated_at, evidence_status, fractional_policy) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("510300", "split", "not-a-date", dates[2], 2.0, "test", "confirmed",
         "ca-v1", "x", "x", "official_confirmed", "truncate"),
    )
    conn.commit()
    conn.close()

    cfg, engine = _engine(temp_db, dates, {})
    with pytest.raises(CorporateActionLoadError, match="公司行为事件加载失败"):
        engine.run(["510300"], indicator_version=None)


def test_load_failure_leaves_no_successful_record(temp_db, monkeypatch):
    """异常发生后不得留下可用于正式评价的回测记录。"""
    from app.database.db import get_connection

    dates = _seed(temp_db, {"510300": [10.0] * 4})

    def _boom(**kwargs):
        raise sqlite3.OperationalError("no such table: corporate_actions")

    monkeypatch.setattr(ca, "load_actions", _boom)
    cfg, engine = _engine(temp_db, dates, _plan(dates))
    with pytest.raises(CorporateActionLoadError):
        engine.run(["510300"], indicator_version=None)

    with get_connection(temp_db) as conn:
        runs = conn.execute("SELECT COUNT(*) FROM backtest_runs").fetchone()[0]
        nav = conn.execute("SELECT COUNT(*) FROM backtest_daily_nav").fetchone()[0]
        apps = conn.execute(
            "SELECT COUNT(*) FROM corporate_action_applications").fetchone()[0]
    assert runs == 0
    assert nav == 0
    assert apps == 0
    assert list_runs(db_path=temp_db) == []


def test_validation_digest_load_failure_raises(temp_db, monkeypatch):
    """验证层原来把加载失败退化成 digest='unavailable'，现在必须抛错。"""
    from app.validation.config import ValidationConfig
    from app.validation.runner import ValidationError, _events_digest_for

    _seed(temp_db, {"510300": [10.0] * 4})

    def _boom(**kwargs):
        raise sqlite3.OperationalError("no such table: corporate_actions")

    monkeypatch.setattr(ca, "load_actions", _boom)
    with pytest.raises(ValidationError, match="事件加载失败"):
        _events_digest_for(ValidationConfig(), ["510300"], db_path=temp_db)


# ------------------------------------------------ 问题2：非正式口径持久化

def test_non_formal_result_persists_both_fields(temp_db):
    """apply_corporate_actions=False 的结果保存后，两个口径字段必须完整保留。"""
    dates = _seed(temp_db, {"510300": [10.0] * 4})
    _insert_action(temp_db, code="510300", action_type=ACTION_SPLIT,
                   ex_date=dates[1], effective_date=dates[2], share_ratio=2.0,
                   fractional_policy="truncate")
    result, engine = _run(temp_db, dates, ["510300"], plan=_plan(dates),
                          apply_corporate_actions=False)
    perf = compute_performance(result.daily, result.trades, result.orders,
                               result.initial_cash)
    saved = save_result(result, perf, db_path=temp_db)
    assert saved["accounting_basis"] == ACCOUNTING_DISABLED
    assert saved["formal_valuation"] is False

    detail = get_run(result.run_id, db_path=temp_db)
    summary = detail["summary_json"]
    assert summary["accounting_basis"] == ACCOUNTING_DISABLED
    assert summary["formal_valuation"] is False
    # 顶层副本同样可见，调用方无需钻进 summary_json
    assert detail["accounting_basis"] == ACCOUNTING_DISABLED
    assert detail["formal_valuation"] is False
    assert is_formal_run(summary) is False

    rows = list_runs(db_path=temp_db)
    assert len(rows) == 1
    assert rows[0]["accounting_basis"] == ACCOUNTING_DISABLED
    assert rows[0]["formal_valuation"] is False


def test_formal_result_persists_formal_basis(temp_db):
    """正式口径回测的持久化结果不发生非预期变化。"""
    dates = _seed(temp_db, {"510300": [10.0] * 4})
    result, engine = _run(temp_db, dates, ["510300"], plan=_plan(dates))
    assert result.accounting_basis == ACCOUNTING_FORMAL
    assert result.formal_valuation is True
    perf = compute_performance(result.daily, result.trades, result.orders,
                               result.initial_cash)
    saved = save_result(result, perf, db_path=temp_db)
    assert saved["accounting_basis"] == ACCOUNTING_FORMAL
    assert saved["formal_valuation"] is True
    assert saved["reconciliation"]["ok"] is True

    detail = get_run(result.run_id, db_path=temp_db)
    summary = detail["summary_json"]
    assert summary["accounting_basis"] == ACCOUNTING_FORMAL
    assert summary["formal_valuation"] is True
    assert summary["performance"] == _perf_dict(perf)
    assert summary["cost_semantics"] == "commission+taxes+slippage"
    assert is_formal_run(summary) is True


def test_legacy_record_without_fields_is_not_formal(temp_db):
    """没有口径字段的历史记录不得被当成正式结果。"""
    from app.database.db import get_connection

    dates = _seed(temp_db, {"510300": [10.0] * 4})
    with get_connection(temp_db) as conn:
        conn.execute(
            "INSERT INTO backtest_runs (run_id, strategy_name, strategy_version, "
            "config_json, initial_cash, start_date, end_date, etf_codes, "
            "indicator_version, snapshot_ids, input_hash, summary_json, created_at) "
            "VALUES ('legacy0001','ma_trend','1.0.0','{}',100000.0,?,?,'[]',NULL,'{}',"
            "'deadbeef','{\"cost_semantics\":\"legacy\"}','2024-01-01T00:00:00')",
            (dates[0], dates[-1]),
        )
    detail = get_run("legacy0001", db_path=temp_db)
    assert detail["accounting_basis"] == ACCOUNTING_UNKNOWN
    assert detail["formal_valuation"] is False
    assert is_formal_run(detail["summary_json"]) is False
    rows = list_runs(db_path=temp_db)
    assert rows[0]["formal_valuation"] is False


def test_accounting_basis_helpers_fail_closed():
    assert accounting_basis_of(None) == ACCOUNTING_UNKNOWN
    assert formal_valuation_of(None) is False
    assert accounting_basis_of({}) == ACCOUNTING_UNKNOWN
    assert formal_valuation_of({"accounting_basis": ACCOUNTING_DISABLED}) is False
    assert formal_valuation_of({"formal_valuation": True}) is True
    assert is_formal_run({"accounting_basis": ACCOUNTING_DISABLED,
                          "formal_valuation": True}) is False
    assert is_formal_run({"accounting_basis": ACCOUNTING_FORMAL,
                          "formal_valuation": True}) is True


# ------------------------------------------------ 问题3：非正式口径不得进入正式评价

def test_non_formal_backtest_rejected_by_validation(temp_db):
    """验证层必须拒绝非正式口径的回测结果。"""
    from app.validation.runner import ValidationError, _run_backtest

    dates = _seed(temp_db, {"510300": [10.0] * 4})
    cfg = BacktestConfig(start_date=dates[0], end_date=dates[-1],
                         initial_cash=100000.0, apply_corporate_actions=False)
    with pytest.raises(ValidationError, match="非正式会计口径"):
        _run_backtest(cfg, _Fixed(_plan(dates)), ["510300"], None, temp_db)


def test_validation_config_keeps_corporate_actions_on():
    """验证配置构建出的回测配置必须保持公司行为开启（默认正式口径）。"""
    from app.validation.config import ValidationConfig

    cfg = ValidationConfig().build_backtest_config("2024-01-02", "2024-01-05")
    assert cfg.apply_corporate_actions is True


def _perf_dict(performance):
    return performance.as_dict()


# ------------------------------------------------ 问题2补充：不得伪造正式性

def test_missing_basis_is_persisted_as_unknown_not_formal(temp_db):
    """结果对象缺少口径字段时不得默认为正式。"""
    dates = _seed(temp_db, {"510300": [10.0] * 4})
    result, engine = _run(temp_db, dates, ["510300"], plan=_plan(dates))
    result.accounting_basis = None
    result.formal_valuation = True
    perf = compute_performance(result.daily, result.trades, result.orders,
                               result.initial_cash)
    saved = save_result(result, perf, db_path=temp_db)
    assert saved["accounting_basis"] == ACCOUNTING_UNKNOWN
    assert saved["formal_valuation"] is False


def test_disabled_basis_forces_non_formal_even_if_flag_true(temp_db):
    """口径为非正式时，formal_valuation 即使被置 True 也必须落盘为 False。"""
    dates = _seed(temp_db, {"510300": [10.0] * 4})
    result, engine = _run(temp_db, dates, ["510300"], plan=_plan(dates))
    result.accounting_basis = ACCOUNTING_DISABLED
    result.formal_valuation = True
    perf = compute_performance(result.daily, result.trades, result.orders,
                               result.initial_cash)
    saved = save_result(result, perf, db_path=temp_db)
    assert saved["accounting_basis"] == ACCOUNTING_DISABLED
    assert saved["formal_valuation"] is False
