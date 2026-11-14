"""阶段3A.3.2.3.1 历史记录重放体系测试。

覆盖：盘点分类、参数忠实性、缺参数拒绝猜测、源→重放关联、
幂等、强制重跑、单条失败隔离、历史记录不被覆盖、指纹不变。
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from app.database.db import get_connection
from app.replay.manifest import (
    BACKTEST,
    CLASS_CURRENT_FORMAL,
    CLASS_LEGACY,
    CLASS_NON_REPLAYABLE,
    CLASS_REPLAYED,
    CLASS_UNKNOWN_LEGACY,
    VALIDATION,
    ReplayError,
    backtest_manifest,
    resolve_validation_config,
    summarize,
    validation_manifest,
)
from app.replay.registry import (
    STATUS_FAILED,
    STATUS_SKIPPED,
    STATUS_SUCCESS,
    finish_attempt,
    find_success,
    init_replay_schema,
    list_attempts,
    start_attempt,
    success_map,
)
from app.replay.runner import (
    build_backtest_config,
    build_validation_config,
    load_backtest_source,
    pending_sources,
    replay_backtest,
    replay_many,
    replay_validation,
)
from tests.test_corporate_actions import _seed


# ---------------------------------------------------------------- 脚手架

def _insert_backtest(db_path, run_id, *, strategy="buy_and_hold",
                     start="2024-01-02", end="2024-01-05",
                     accounting="legacy_corporate_action_accounting",
                     config=None, codes=("510300",), ma_window=None,
                     summary_extra=None, indicator_version=None):
    payload = {
        "start_date": start, "end_date": end, "initial_cash": 100000.0,
        "execution_price": "open", "max_defer_days": 3, "risk_free_rate": 0.0,
        "annualization": 252, "rebalance_tolerance": 0.02,
        "cash_shortfall_policy": "reduce", "allow_partial_fill": False,
        "costs": {"commission_rate": 0.00025, "min_commission": 5.0,
                  "slippage_bps": 5.0, "slippage_fixed": 0.0,
                  "stamp_duty_rate": 0.0, "transfer_fee_rate": 0.0},
        "instrument_overrides": {}, "lot_size_override": None,
        "strategy_params": {},
    }
    if ma_window is not None:
        payload["strategy_params"]["ma_window"] = ma_window
    if config is not None:
        payload = config
    summary = {"performance": {}, "reconciliation": {"ok": True}}
    summary.update(summary_extra or {})
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO backtest_runs (run_id, strategy_name, strategy_version, "
            "config_json, initial_cash, start_date, end_date, etf_codes, "
            "indicator_version, snapshot_ids, input_hash, summary_json, created_at, "
            "accounting_version, evidence_version) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, strategy, "1.0.0", json.dumps(payload), payload["initial_cash"],
             start, end, json.dumps(list(codes)), indicator_version,
             json.dumps({code: 1 for code in codes}), "src" + run_id[:6],
             json.dumps(summary), "2026-11-10T00:00:00", accounting, "ca-evidence-v1"),
        )


def _insert_validation(db_path, vid, *, is_start="2024-01-02", is_end="2024-01-05",
                       oos_start="2024-01-08", oos_end="2024-01-12",
                       codes=("510300",), grid=(5, 20),
                       accounting="legacy_corporate_action_accounting",
                       status="success", config_hash=None):
    from app.validation.storage import init_validation_schema

    init_validation_schema(db_path)
    # 建表后需要再跑一次迁移补上 accounting_version / legacy_flag 列
    from app.database.db import init_db

    init_db(db_path=db_path)
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO validation_runs (validation_id, strategy_name, strategy_version, "
            "config_hash, input_hash, etf_codes, excluded_codes, ma_window_grid, "
            "is_start, is_end, oos_start, oos_end, walkforward_config, benchmark_config, "
            "stress_config, status, conclusion, summary_json, error_message, created_at, "
            "finished_at, accounting_version, legacy_flag) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (vid, "ma_trend", "1.0.0", config_hash or "deadbeef", "hash" + vid[:4],
             json.dumps(list(codes)), "[]", json.dumps(list(grid)),
             is_start, is_end, oos_start, oos_end, "{}", "{}", "{}", status,
             "不通过", "{}", None, "2026-11-10T00:00:00", "2026-11-10T00:10:00",
             accounting, "legacy_corporate_action_accounting"),
        )


# ---------------------------------------------------------------- 盘点分类

def test_manifest_counts_backtests(temp_db):
    _insert_backtest(temp_db, "bt_legacy_bh", strategy="buy_and_hold")
    _insert_backtest(temp_db, "bt_legacy_ma", strategy="ma_trend")  # 缺 ma_window
    _insert_backtest(temp_db, "bt_formal", strategy="buy_and_hold",
                     accounting="ca-v2-receivable")
    _insert_backtest(temp_db, "bt_unknown", strategy="buy_and_hold",
                     accounting=None)

    records = {item["source_id"]: item for item in backtest_manifest(db_path=temp_db)}
    assert records["bt_legacy_bh"]["classification"] == CLASS_LEGACY
    assert records["bt_legacy_ma"]["classification"] == CLASS_NON_REPLAYABLE
    assert "ma_window" in " ".join(records["bt_legacy_ma"]["missing_params"])
    assert records["bt_formal"]["classification"] == CLASS_CURRENT_FORMAL
    assert records["bt_unknown"]["classification"] == CLASS_UNKNOWN_LEGACY

    summary = summarize(list(records.values()))
    assert summary["total"] == 4
    assert summary["sum_matches_total"] is True
    assert summary["pending_replay"] == 1


def test_manifest_marks_replayed(temp_db):
    _insert_backtest(temp_db, "bt_legacy_bh", strategy="buy_and_hold")
    init_replay_schema(db_path=temp_db)
    attempt = start_attempt(BACKTEST, "bt_legacy_bh", db_path=temp_db)
    finish_attempt(attempt, STATUS_SUCCESS, replay_record_id="newrun01", db_path=temp_db)

    successes = success_map(BACKTEST, db_path=temp_db)
    records = {item["source_id"]: item for item in
               backtest_manifest(db_path=temp_db, successes=successes)}
    assert records["bt_legacy_bh"]["classification"] == CLASS_REPLAYED
    assert records["bt_legacy_bh"]["replay_record_id"] == "newrun01"
    assert summarize(list(records.values()))["already_replayed"] == 1


def test_manifest_reports_missing_params_explicitly(temp_db):
    config = {
        "start_date": "2024-01-02", "end_date": "2024-01-05",
        "initial_cash": 100000.0, "strategy_params": {"ma_window": 20},
    }
    _insert_backtest(temp_db, "bt_partial", strategy="ma_trend", config=config)
    item = backtest_manifest(db_path=temp_db)[0]
    assert item["classification"] == CLASS_NON_REPLAYABLE
    assert "config:costs" in item["missing_params"]
    assert item["params_source"]["ma_window"] == "recorded"


def test_manifest_rejects_validation_with_unproven_hash(temp_db):
    _insert_validation(temp_db, "val_bad", config_hash="deadbeef")
    item = validation_manifest(db_path=temp_db)[0]
    assert item["classification"] == CLASS_NON_REPLAYABLE
    assert item["params_proof"] == "missing"
    assert "config_hash" in item["params_proof_reason"]


def test_manifest_proves_validation_hash_when_it_matches(temp_db):
    """config_hash 能复现时，参数被证明并可重放。"""
    from app.validation.config import ValidationConfig

    grid = (5, 20)
    cfg = ValidationConfig(
        is_start="2024-01-02", is_end="2024-01-05",
        oos_start="2024-01-08", oos_end="2024-01-12",
        ma_window_grid=grid, pool_mode="representative",
    )
    _insert_validation(temp_db, "val_ok", grid=grid, config_hash=cfg.params_hash())
    item = validation_manifest(db_path=temp_db)[0]
    assert item["params_proof"] == "proven"
    assert item["classification"] == CLASS_LEGACY
    assert item["resolved_params"]["ma_window_grid"] == [5, 20]
    assert build_validation_config(item).params_hash() == cfg.params_hash()


def test_manifest_flags_failed_validation_as_non_replayable(temp_db):
    from app.validation.config import ValidationConfig

    grid = (5, 20)
    cfg = ValidationConfig(
        is_start="2024-01-02", is_end="2024-01-05",
        oos_start="2024-01-08", oos_end="2024-01-12",
        ma_window_grid=grid, pool_mode="representative",
    )
    _insert_validation(temp_db, "val_fail", grid=grid,
                       config_hash=cfg.params_hash(), status="failed")
    item = validation_manifest(db_path=temp_db)[0]
    assert item["classification"] == CLASS_NON_REPLAYABLE
    assert any(flag.startswith("source_status") for flag in item["missing_params"])


# ---------------------------------------------------------------- 缺失源记录

def test_missing_backtest_source_raises(temp_db):
    with pytest.raises(ReplayError, match="不存在"):
        load_backtest_source("nope", db_path=temp_db)


def test_missing_validation_source_raises(temp_db):
    with pytest.raises(ReplayError, match="不存在"):
        replay_validation("nope", db_path=temp_db)


# ---------------------------------------------------------------- 参数忠实性

def test_backtest_config_follows_source_not_defaults(temp_db):
    """源记录参数与当前默认值不同时，必须沿用源记录。"""
    config = {
        "start_date": "2024-01-02", "end_date": "2024-01-04",
        "initial_cash": 250000.0, "execution_price": "close",
        "max_defer_days": 1, "risk_free_rate": 0.02, "annualization": 244,
        "rebalance_tolerance": 0.07, "cash_shortfall_policy": "reject",
        "allow_partial_fill": True,
        "costs": {"commission_rate": 0.001, "min_commission": 1.5,
                  "slippage_bps": 12.0, "slippage_fixed": 0.01,
                  "stamp_duty_rate": 0.0005, "transfer_fee_rate": 0.00001},
        "instrument_overrides": {}, "lot_size_override": 10,
        "strategy_params": {"ma_window": 7},
    }
    _insert_backtest(temp_db, "bt_custom", strategy="ma_trend", config=config)
    source = load_backtest_source("bt_custom", db_path=temp_db)
    built = build_backtest_config(source)
    assert built.start_date == "2024-01-02"
    assert built.end_date == "2024-01-04"
    assert built.initial_cash == 250000.0
    assert built.execution_price == "close"
    assert built.max_defer_days == 1
    assert built.risk_free_rate == 0.02
    assert built.annualization == 244
    assert built.rebalance_tolerance == 0.07
    assert built.cash_shortfall_policy == "reject"
    assert built.allow_partial_fill is True
    assert built.lot_size_override == 10
    assert built.costs.commission_rate == 0.001
    assert built.costs.min_commission == 1.5
    assert built.costs.slippage_bps == 12.0
    assert built.costs.stamp_duty_rate == 0.0005
    # 重放必须打开公司行为，源记录关闭也不能继承
    assert built.apply_corporate_actions is True


def test_backtest_config_refuses_missing_ma_window(temp_db):
    _insert_backtest(temp_db, "bt_no_window", strategy="ma_trend")
    source = load_backtest_source("bt_no_window", db_path=temp_db)
    with pytest.raises(ReplayError, match="ma_window"):
        build_backtest_config(source)


def test_validation_config_refuses_unproven_hash(temp_db):
    _insert_validation(temp_db, "val_bad", config_hash="deadbeef")
    source = validation_manifest(db_path=temp_db)[0]
    with pytest.raises(ReplayError, match="参数不可证明"):
        build_validation_config(source)


# ---------------------------------------------------------------- 执行与幂等

def _seed_replayable_backtest(temp_db):
    """构造一条参数完整、可以真的跑起来的 legacy 回测源记录。"""
    dates = _seed(temp_db, {"510300": [10.0] * 6})
    _insert_backtest(
        temp_db, "bt_runnable", strategy="buy_and_hold",
        start=dates[0], end=dates[-1],
        config={
            "start_date": dates[0], "end_date": dates[-1],
            "initial_cash": 100000.0, "execution_price": "open",
            "max_defer_days": 3, "risk_free_rate": 0.0, "annualization": 252,
            "rebalance_tolerance": 0.02, "cash_shortfall_policy": "reduce",
            "allow_partial_fill": False,
            "costs": {"commission_rate": 0.00025, "min_commission": 5.0,
                      "slippage_bps": 5.0, "slippage_fixed": 0.0,
                      "stamp_duty_rate": 0.0, "transfer_fee_rate": 0.0},
            "instrument_overrides": {}, "lot_size_override": None,
            "strategy_params": {},
        },
    )
    return dates


def test_replay_creates_new_record_and_registers_link(temp_db):
    _seed_replayable_backtest(temp_db)
    outcome = replay_backtest("bt_runnable", db_path=temp_db)
    assert outcome.status == STATUS_SUCCESS
    assert outcome.replay_id and outcome.replay_id != "bt_runnable"

    source_exists = True
    with get_connection(temp_db) as conn:
        old = conn.execute(
            "SELECT accounting_version FROM backtest_runs WHERE run_id='bt_runnable'"
        ).fetchone()
        new = conn.execute(
            "SELECT summary_json FROM backtest_runs WHERE run_id=?",
            (outcome.replay_id,),
        ).fetchone()
        attempts = conn.execute(
            "SELECT * FROM replay_attempts WHERE source_record_id='bt_runnable'"
        ).fetchall()
    assert old and old[0] == "legacy_corporate_action_accounting"
    summary = json.loads(new[0])
    assert summary["accounting_basis"] == "formal_receivable"
    assert summary["formal_valuation"] is True
    assert len(attempts) == 1
    row = dict(attempts[0])
    assert row["status"] == STATUS_SUCCESS
    assert row["replay_record_id"] == outcome.replay_id
    assert row["source_input_hash"] == "srcbt_run"
    assert row["replay_input_hash"] == outcome.extra["input_hash"]
    assert row["source_accounting_version"] == "legacy_corporate_action_accounting"
    assert row["replay_accounting_version"] == "formal_receivable"
    assert row["replay_timestamp"]

    # 新记录必须带上会计版本标记，否则盘点会把它判成 unknown_legacy
    with get_connection(temp_db) as conn:
        stamped = conn.execute(
            "SELECT accounting_version FROM backtest_runs WHERE run_id=?",
            (outcome.replay_id,),
        ).fetchone()[0]
    assert stamped == "ca-v2-receivable"


def test_replay_is_idempotent_without_force(temp_db):
    _seed_replayable_backtest(temp_db)
    first = replay_backtest("bt_runnable", db_path=temp_db)
    second = replay_backtest("bt_runnable", db_path=temp_db)
    assert first.status == STATUS_SUCCESS
    assert second.status == STATUS_SKIPPED
    assert second.replay_id == first.replay_id
    with get_connection(temp_db) as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM replay_attempts WHERE source_record_id='bt_runnable'"
        ).fetchone()[0]
    assert total == 1  # 跳过不写新 attempt


def test_replay_force_creates_second_record(temp_db):
    _seed_replayable_backtest(temp_db)
    first = replay_backtest("bt_runnable", db_path=temp_db)
    second = replay_backtest("bt_runnable", force=True, db_path=temp_db)
    assert second.status == STATUS_SUCCESS
    assert second.replay_id != first.replay_id
    with get_connection(temp_db) as conn:
        runs = conn.execute(
            "SELECT COUNT(*) FROM backtest_runs WHERE run_id IN (?,?,?)",
            ("bt_runnable", first.replay_id, second.replay_id),
        ).fetchone()[0]
        attempts = conn.execute(
            "SELECT COUNT(*) FROM replay_attempts WHERE source_record_id='bt_runnable'"
        ).fetchone()[0]
    assert runs == 3  # 源记录仍在
    assert attempts == 2


def test_replay_skips_non_replayable_source_without_creating_record(temp_db):
    dates = _seed(temp_db, {"510300": [10.0] * 4})
    _insert_backtest(temp_db, "bt_nowindow", strategy="ma_trend",
                     start=dates[0], end=dates[-1])
    outcome = replay_backtest("bt_nowindow", db_path=temp_db)
    assert outcome.status == STATUS_FAILED
    assert "ma_window" in outcome.reason
    with get_connection(temp_db) as conn:
        runs = conn.execute("SELECT COUNT(*) FROM backtest_runs").fetchone()[0]
        row = conn.execute(
            "SELECT status FROM replay_attempts WHERE source_record_id='bt_nowindow'"
        ).fetchone()
    assert runs == 1  # 只有源记录
    assert row[0] == STATUS_FAILED


def test_replay_many_isolates_single_failure(temp_db):
    _seed_replayable_backtest(temp_db)
    _insert_backtest(temp_db, "bt_broken", strategy="ma_trend")
    outcomes = replay_many(BACKTEST, ["bt_broken", "bt_runnable"], db_path=temp_db)
    by_source = {item.source_id: item for item in outcomes}
    assert by_source["bt_broken"].status == STATUS_FAILED
    assert by_source["bt_runnable"].status == STATUS_SUCCESS


def test_replay_resumes_after_interruption(temp_db):
    """中断后重跑：已成功的跳过，未做的继续做完。"""
    _seed_replayable_backtest(temp_db)
    _insert_backtest(temp_db, "bt_broken", strategy="ma_trend")

    # 第一次只处理前一条，模拟中断
    first = replay_many(BACKTEST, ["bt_runnable"], db_path=temp_db)
    assert first[0].status == STATUS_SUCCESS
    assert find_success(BACKTEST, "bt_runnable", db_path=temp_db) == first[0].replay_id

    # 恢复：全部待重放里，已成功的被跳过，失败的记录仍失败但不阻断
    targets = ["bt_runnable", "bt_broken"]
    second = replay_many(BACKTEST, targets, db_path=temp_db)
    by_source = {item.source_id: item for item in second}
    assert by_source["bt_runnable"].status == STATUS_SKIPPED
    assert by_source["bt_broken"].status == STATUS_FAILED
    with get_connection(temp_db) as conn:
        attempts = conn.execute(
            "SELECT COUNT(*) FROM replay_attempts WHERE source_record_id='bt_runnable'"
        ).fetchone()[0]
    assert attempts == 1


def test_history_rows_not_overwritten_by_replay(temp_db):
    dates = _seed_replayable_backtest(temp_db)
    with get_connection(temp_db) as conn:
        before = dict(conn.execute(
            "SELECT * FROM backtest_runs WHERE run_id='bt_runnable'"
        ).fetchone() or {})
    replay_backtest("bt_runnable", db_path=temp_db)
    with get_connection(temp_db) as conn:
        after = dict(conn.execute(
            "SELECT * FROM backtest_runs WHERE run_id='bt_runnable'"
        ).fetchone() or {})
    assert before == after


# ---------------------------------------------------------------- 非正式口径

def test_replay_refuses_non_formal_result(temp_db, monkeypatch):
    """重放拿到的若不是正式口径，必须记为失败，不得写正式记录。"""
    dates = _seed_replayable_backtest(temp_db)

    import app.backtest.engine as engine_mod

    class _FakeResult:
        run_id = "fake0001"
        accounting_basis = "disabled_non_official"
        formal_valuation = False
        daily: list = []
        trades: list = []
        orders: list = []
        initial_cash = 100000.0
        input_hash = "fakehash"

    class _FakeEngine:
        corporate_action_digest = None

        def __init__(self, *args, **kwargs):
            pass

        def run(self, *args, **kwargs):
            return _FakeResult()

    monkeypatch.setattr(engine_mod, "BacktestEngine", _FakeEngine)
    outcome = replay_backtest("bt_runnable", db_path=temp_db)
    assert outcome.status == STATUS_FAILED
    assert "不是正式口径" in outcome.reason
    with get_connection(temp_db) as conn:
        runs = conn.execute("SELECT COUNT(*) FROM backtest_runs").fetchone()[0]
    assert runs == 1


def test_pending_sources_lists_only_legacy(temp_db):
    _insert_backtest(temp_db, "bt_legacy_bh", strategy="buy_and_hold")
    _insert_backtest(temp_db, "bt_formal", strategy="buy_and_hold",
                     accounting="ca-v2-receivable")
    _insert_backtest(temp_db, "bt_ma", strategy="ma_trend")
    targets = pending_sources(BACKTEST, db_path=temp_db)
    assert targets == ["bt_legacy_bh"]
