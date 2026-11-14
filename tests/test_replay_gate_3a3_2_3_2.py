"""阶段3A.3.2.3.2：重放失败闸门专项测试。

每条都核实**数据库最终状态**，而不只是断言函数抛了异常。
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.backtest.api import ACCOUNTING_FORMAL
from app.database.db import get_connection
from app.replay.manifest import BACKTEST, VALIDATION, ReplayError
from app.replay.registry import (
    STATUS_FAILED,
    STATUS_SKIPPED,
    STATUS_SUCCESS,
    find_success,
    init_replay_schema,
    list_attempts,
)
from app.replay.runner import (
    build_validation_config,
    replay_backtest,
    replay_validation,
)
from app.validation.config import ValidationConfig
from tests.test_replay_3a3_2_3_1 import _insert_backtest, _insert_validation
from tests.test_corporate_actions import _seed


# ---------------------------------------------------------------- 脚手架

def _known_config(**overrides) -> ValidationConfig:
    base = dict(
        is_start="2024-01-02", is_end="2024-01-05",
        oos_start="2024-01-08", oos_end="2024-01-12",
        ma_window_grid=(5, 20), pool_mode="representative",
    )
    base.update(overrides)
    return ValidationConfig(**base)


def _seed_validation(temp_db, vid="src_val", **overrides):
    cfg = _known_config(**overrides)
    _insert_validation(temp_db, vid, grid=cfg.ma_window_grid,
                       config_hash=cfg.params_hash())
    return cfg


def _attempts(db_path, kind=None):
    return [a for a in list_attempts(limit=100, db_path=db_path)
            if kind is None or a["record_kind"] == kind]


def _count(db_path, table, where="1=1", params=()):
    with get_connection(db_path) as conn:
        return conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {where}", params
        ).fetchone()[0]


def _fake_validation(monkeypatch, *, validation_id, acct, row_exists=True,
                     raise_exc=None):
    """替换 run_validation，并伪造「重放后回查」的结果。

    不替换数据库连接：只 monkeypatch `_fetch_validation_record` 这一个返回点，
    其余读写仍走真实库，避免测试自身污染 schema。
    """
    import app.validation.runner as vrunner
    import app.replay.runner as runner_mod

    class _Result:
        status = "success"
        conclusion = "不通过"
        codes = ["510300"]

    result = _Result()
    result.validation_id = validation_id

    def _run(cfg, **kwargs):
        if raise_exc is not None:
            raise raise_exc
        return result

    monkeypatch.setattr(vrunner, "run_validation", _run)

    def _fetch(vid, *, db_path=None):
        if not row_exists:
            return None
        return ("replayhash", acct)

    monkeypatch.setattr(runner_mod, "_fetch_validation_record", _fetch)


# ---------------------------------------------------------------- 异常场景 1

def test_source_validation_missing_raises(temp_db):
    """原始 validation 记录不存在 → 抛错，且不写 attempt。"""
    with pytest.raises(ReplayError, match="不存在"):
        replay_validation("no_such_id", db_path=temp_db)
    assert _attempts(temp_db) == []


# ---------------------------------------------------------------- 异常场景 2

def test_source_validation_params_missing(temp_db):
    """原始参数不可证明 → failed，且不产生新 validation 记录。"""
    _insert_validation(temp_db, "src_bad", config_hash="deadbeef")
    before = _count(temp_db, "validation_runs")
    outcome = replay_validation("src_bad", db_path=temp_db)
    assert outcome.status == STATUS_FAILED
    assert "参数不可证明" in outcome.reason
    assert _count(temp_db, "validation_runs") == before
    rows = _attempts(temp_db, VALIDATION)
    assert len(rows) == 1 and rows[0]["status"] == STATUS_FAILED
    assert rows[0]["reason"]


# ---------------------------------------------------------------- 异常场景 3

def test_unknown_strategy_version_cannot_be_proven(temp_db):
    """策略版本不在已知字段集里 → config_hash 无法复现 → non_replayable。"""
    _insert_validation(temp_db, "src_ver", config_hash=_known_config().params_hash())
    with get_connection(temp_db) as conn:
        conn.execute("UPDATE validation_runs SET strategy_version='9.9.9' "
                     "WHERE validation_id='src_ver'")
    outcome = replay_validation("src_ver", db_path=temp_db)
    assert outcome.status == STATUS_FAILED
    assert "参数不可证明" in outcome.reason


# ---------------------------------------------------------------- 异常场景 4

def test_corporate_action_load_failure_aborts_replay(temp_db, monkeypatch):
    """公司行为事件表读取失败 → 重放失败，不写正式记录。"""
    import app.backtest.corporate_actions as ca

    dates = _seed(temp_db, {"510300": [10.0] * 6})
    _insert_backtest(temp_db, "bt_ca", strategy="buy_and_hold",
                     start=dates[0], end=dates[-1],
                     config={
                         "start_date": dates[0], "end_date": dates[-1],
                         "initial_cash": 100000.0, "execution_price": "open",
                         "max_defer_days": 3, "risk_free_rate": 0.0,
                         "annualization": 252, "rebalance_tolerance": 0.02,
                         "cash_shortfall_policy": "reduce",
                         "allow_partial_fill": False,
                         "costs": {"commission_rate": 0.00025,
                                   "min_commission": 5.0, "slippage_bps": 5.0,
                                   "slippage_fixed": 0.0, "stamp_duty_rate": 0.0,
                                   "transfer_fee_rate": 0.0},
                         "instrument_overrides": {}, "lot_size_override": None,
                         "strategy_params": {},
                     })

    def _boom(**kwargs):
        raise RuntimeError("no such table: corporate_actions")

    monkeypatch.setattr(ca, "load_actions", _boom)
    before = _count(temp_db, "backtest_runs")
    outcome = replay_backtest("bt_ca", db_path=temp_db)
    assert outcome.status == STATUS_FAILED
    assert _count(temp_db, "backtest_runs") == before
    rows = _attempts(temp_db, BACKTEST)
    assert rows[0]["status"] == STATUS_FAILED
    assert "CorporateActionLoadError" in rows[0]["reason"] or rows[0]["reason"]


# ---------------------------------------------------------------- 异常场景 5

def test_missing_new_validation_record_fails(temp_db, monkeypatch):
    """新 validation 记录查不到 → 不得登记成功。"""
    _seed_validation(temp_db)
    _fake_validation(monkeypatch, validation_id="ghost_record", acct=None,
                     row_exists=False)
    before = _count(temp_db, "validation_runs")
    outcome = replay_validation("src_val", db_path=temp_db)
    assert outcome.status == STATUS_FAILED
    assert "查不到新 validation 记录" in outcome.reason
    assert _count(temp_db, "validation_runs") == before
    rows = _attempts(temp_db, VALIDATION)
    assert rows[0]["status"] == STATUS_FAILED
    assert rows[0]["replay_record_id"] == "ghost_record"


# ---------------------------------------------------------------- 异常场景 6

def test_new_record_accounting_version_none_fails(temp_db, monkeypatch):
    """新记录 accounting_version 为 None → 不得登记成功。"""
    _seed_validation(temp_db)
    _fake_validation(monkeypatch, validation_id="rec_none", acct=None,
                     row_exists=True)
    outcome = replay_validation("src_val", db_path=temp_db)
    assert outcome.status == STATUS_FAILED
    assert "会计版本异常" in outcome.reason
    assert _attempts(temp_db, VALIDATION)[0]["status"] == STATUS_FAILED
    assert find_success(VALIDATION, "src_val", db_path=temp_db) is None


# ---------------------------------------------------------------- 异常场景 7

def test_new_record_accounting_version_empty_fails(temp_db, monkeypatch):
    """新记录 accounting_version 为空字符串 → 不得登记成功。"""
    _seed_validation(temp_db)
    _fake_validation(monkeypatch, validation_id="rec_empty", acct="")
    outcome = replay_validation("src_val", db_path=temp_db)
    assert outcome.status == STATUS_FAILED
    assert "会计版本异常" in outcome.reason
    assert _attempts(temp_db, VALIDATION)[0]["status"] == STATUS_FAILED
    assert find_success(VALIDATION, "src_val", db_path=temp_db) is None


# ---------------------------------------------------------------- 异常场景 8

@pytest.mark.parametrize("acct", [
    "legacy_corporate_action_accounting",
    "ca-v1",
    "ca-v9-unknown",
    "CA-V2-RECEIVABLE",
])
def test_new_record_legacy_or_unknown_version_fails(temp_db, monkeypatch, acct):
    """旧版本 / 未知版本 / 大小写变体一律拒绝。"""
    _seed_validation(temp_db)
    _fake_validation(monkeypatch, validation_id="rec_old", acct=acct,
                     row_exists=True)
    outcome = replay_validation("src_val", db_path=temp_db)
    assert outcome.status == STATUS_FAILED
    assert "会计版本异常" in outcome.reason
    assert find_success(VALIDATION, "src_val", db_path=temp_db) is None


# ---------------------------------------------------------------- 异常场景 9

@pytest.mark.parametrize("formal", [1, 0, "yes", "True", [1], (1,), {"a": 1}, 1.0])
def test_backtest_non_boolean_formal_valuation_fails(temp_db, monkeypatch, formal):
    """backtest 闸门对非布尔 formal_valuation 必须拒绝。"""
    import app.backtest.engine as engine_mod
    import app.backtest.storage as storage_mod

    dates = _seed(temp_db, {"510300": [10.0] * 6})
    _insert_backtest(temp_db, "bt_gate", strategy="buy_and_hold",
                     start=dates[0], end=dates[-1],
                     config={
                         "start_date": dates[0], "end_date": dates[-1],
                         "initial_cash": 100000.0, "execution_price": "open",
                         "max_defer_days": 3, "risk_free_rate": 0.0,
                         "annualization": 252, "rebalance_tolerance": 0.02,
                         "cash_shortfall_policy": "reduce",
                         "allow_partial_fill": False,
                         "costs": {"commission_rate": 0.00025,
                                   "min_commission": 5.0, "slippage_bps": 5.0,
                                   "slippage_fixed": 0.0, "stamp_duty_rate": 0.0,
                                   "transfer_fee_rate": 0.0},
                         "instrument_overrides": {}, "lot_size_override": None,
                         "strategy_params": {},
                     })

    called = {"save": False}

    def _save(*a, **k):
        called["save"] = True
        return {}

    monkeypatch.setattr(storage_mod, "save_result", _save)
    import app.replay.runner as runner_mod
    monkeypatch.setattr(runner_mod, "save_result", _save, raising=False)

    class _Engine:
        corporate_action_digest = "d"

        def __init__(self, *a, **k):
            pass

        def run(self, *a, **k):
            return SimpleNamespace(
                run_id="fake_bt", accounting_basis=ACCOUNTING_FORMAL,
                formal_valuation=formal, daily=[], trades=[], orders=[],
                initial_cash=100000.0, input_hash="h", snapshot_ids={},
                rules={}, config=None, notes=[], codes=[],
            )

    monkeypatch.setattr(engine_mod, "BacktestEngine", _Engine)
    outcome = replay_backtest("bt_gate", db_path=temp_db)
    assert outcome.status == STATUS_FAILED
    assert "不是正式口径" in outcome.reason
    assert called["save"] is False
    assert _count(temp_db, "backtest_runs", "run_id='fake_bt'") == 0


def test_backtest_non_formal_basis_rejected(temp_db, monkeypatch):
    """accounting_basis 非 formal_receivable → 拒绝，即便 bool 为 True。"""
    import app.backtest.engine as engine_mod
    import app.backtest.storage as storage_mod

    dates = _seed(temp_db, {"510300": [10.0] * 6})
    _insert_backtest(temp_db, "bt_basis", strategy="buy_and_hold",
                     start=dates[0], end=dates[-1],
                     config={
                         "start_date": dates[0], "end_date": dates[-1],
                         "initial_cash": 100000.0, "execution_price": "open",
                         "max_defer_days": 3, "risk_free_rate": 0.0,
                         "annualization": 252, "rebalance_tolerance": 0.02,
                         "cash_shortfall_policy": "reduce",
                         "allow_partial_fill": False,
                         "costs": {"commission_rate": 0.00025,
                                   "min_commission": 5.0, "slippage_bps": 5.0,
                                   "slippage_fixed": 0.0, "stamp_duty_rate": 0.0,
                                   "transfer_fee_rate": 0.0},
                         "instrument_overrides": {}, "lot_size_override": None,
                         "strategy_params": {},
                     })
    called = {"save": False}
    monkeypatch.setattr(storage_mod, "save_result",
                        lambda *a, **k: called.__setitem__("save", True) or {})

    class _Engine:
        corporate_action_digest = "d"

        def __init__(self, *a, **k):
            pass

        def run(self, *a, **k):
            return SimpleNamespace(
                run_id="fake_basis",
                accounting_basis="disabled_non_official",
                formal_valuation=True, daily=[], trades=[], orders=[],
                initial_cash=100000.0, input_hash="h", snapshot_ids={},
                rules={}, config=None, notes=[], codes=[],
            )

    monkeypatch.setattr(engine_mod, "BacktestEngine", _Engine)
    outcome = replay_backtest("bt_basis", db_path=temp_db)
    assert outcome.status == STATUS_FAILED
    assert called["save"] is False


# ---------------------------------------------------------------- 异常场景 10

def test_save_failure_leaves_no_success_attempt(temp_db, monkeypatch):
    """新记录保存失败 → failed，且库里没有新记录。"""
    import app.backtest.engine as engine_mod
    import app.backtest.storage as storage_mod

    dates = _seed(temp_db, {"510300": [10.0] * 6})
    _insert_backtest(temp_db, "bt_savefail", strategy="buy_and_hold",
                     start=dates[0], end=dates[-1],
                     config={
                         "start_date": dates[0], "end_date": dates[-1],
                         "initial_cash": 100000.0, "execution_price": "open",
                         "max_defer_days": 3, "risk_free_rate": 0.0,
                         "annualization": 252, "rebalance_tolerance": 0.02,
                         "cash_shortfall_policy": "reduce",
                         "allow_partial_fill": False,
                         "costs": {"commission_rate": 0.00025,
                                   "min_commission": 5.0, "slippage_bps": 5.0,
                                   "slippage_fixed": 0.0, "stamp_duty_rate": 0.0,
                                   "transfer_fee_rate": 0.0},
                         "instrument_overrides": {}, "lot_size_override": None,
                         "strategy_params": {},
                     })

    def _explode(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(storage_mod, "save_result", _explode)
    before = _count(temp_db, "backtest_runs")
    outcome = replay_backtest("bt_savefail", db_path=temp_db)
    assert outcome.status == STATUS_FAILED
    assert "disk full" in outcome.reason
    assert _count(temp_db, "backtest_runs") == before
    rows = _attempts(temp_db, BACKTEST)
    assert rows[0]["status"] == STATUS_FAILED
    assert find_success(BACKTEST, "bt_savefail", db_path=temp_db) is None


# ---------------------------------------------------------------- 异常场景 11

def test_finish_attempt_failure_does_not_fake_success(temp_db, monkeypatch):
    """状态更新失败 → 库里不会出现 success 行。"""
    import app.replay.runner as runner_mod

    _seed_validation(temp_db)
    cfg = _known_config()

    class _Result:
        validation_id = "rec_ok"
        status = "success"
        conclusion = "通过"
        codes = ["510300"]

    import app.validation.runner as vrunner
    monkeypatch.setattr(vrunner, "run_validation", lambda c, **kw: _Result())

    def _boom(*a, **k):
        raise OSError("cannot write")

    monkeypatch.setattr(runner_mod, "finish_attempt", _boom)
    with pytest.raises(OSError):
        replay_validation("src_val", db_path=temp_db)
    # 没有 success 行，attempt 仍是 running
    assert find_success(VALIDATION, "src_val", db_path=temp_db) is None
    rows = _attempts(temp_db, VALIDATION)
    assert rows and all(r["status"] != STATUS_SUCCESS for r in rows)


# ---------------------------------------------------------------- 异常场景 12 & 13

def _real_backtest_source(temp_db):
    dates = _seed(temp_db, {"510300": [10.0] * 6})
    _insert_backtest(temp_db, "bt_idem", strategy="buy_and_hold",
                     start=dates[0], end=dates[-1],
                     config={
                         "start_date": dates[0], "end_date": dates[-1],
                         "initial_cash": 100000.0, "execution_price": "open",
                         "max_defer_days": 3, "risk_free_rate": 0.0,
                         "annualization": 252, "rebalance_tolerance": 0.02,
                         "cash_shortfall_policy": "reduce",
                         "allow_partial_fill": False,
                         "costs": {"commission_rate": 0.00025,
                                   "min_commission": 5.0, "slippage_bps": 5.0,
                                   "slippage_fixed": 0.0, "stamp_duty_rate": 0.0,
                                   "transfer_fee_rate": 0.0},
                         "instrument_overrides": {}, "lot_size_override": None,
                         "strategy_params": {},
                     })
    return dates


def test_repeat_replay_does_not_duplicate_success(temp_db):
    """同一 source 重复执行：第二次 skipped，success 行恒为 1。"""
    _real_backtest_source(temp_db)
    first = replay_backtest("bt_idem", db_path=temp_db)
    assert first.status == STATUS_SUCCESS
    second = replay_backtest("bt_idem", db_path=temp_db)
    third = replay_backtest("bt_idem", db_path=temp_db)
    assert second.status == STATUS_SKIPPED
    assert third.status == STATUS_SKIPPED
    assert second.replay_id == first.replay_id

    rows = _attempts(temp_db, BACKTEST)
    assert len(rows) == 1
    assert sum(1 for r in rows if r["status"] == STATUS_SUCCESS) == 1
    assert _count(temp_db, "backtest_runs", "run_id=?", (first.replay_id,)) == 1


def test_no_duplicate_corporate_action_booking_on_repeat(temp_db):
    """重复执行不改变已生成新记录的应收/分红数据。"""
    dates = _seed(temp_db, {"510300": [10.0] * 6})
    _insert_backtest(temp_db, "bt_ca2", strategy="buy_and_hold",
                     start=dates[0], end=dates[-1],
                     config={
                         "start_date": dates[0], "end_date": dates[-1],
                         "initial_cash": 100000.0, "execution_price": "open",
                         "max_defer_days": 3, "risk_free_rate": 0.0,
                         "annualization": 252, "rebalance_tolerance": 0.02,
                         "cash_shortfall_policy": "reduce",
                         "allow_partial_fill": False,
                         "costs": {"commission_rate": 0.00025,
                                   "min_commission": 5.0, "slippage_bps": 5.0,
                                   "slippage_fixed": 0.0, "stamp_duty_rate": 0.0,
                                   "transfer_fee_rate": 0.0},
                         "instrument_overrides": {}, "lot_size_override": None,
                         "strategy_params": {},
                     })
    first = replay_backtest("bt_ca2", db_path=temp_db)
    with get_connection(temp_db) as conn:
        apps_before = conn.execute(
            "SELECT COUNT(*) FROM corporate_action_applications WHERE run_id=?",
            (first.replay_id,)).fetchone()[0]
        nav_before = conn.execute(
            "SELECT COUNT(*) FROM backtest_daily_nav WHERE run_id=?",
            (first.replay_id,)).fetchone()[0]
    replay_backtest("bt_ca2", db_path=temp_db)
    with get_connection(temp_db) as conn:
        apps_after = conn.execute(
            "SELECT COUNT(*) FROM corporate_action_applications WHERE run_id=?",
            (first.replay_id,)).fetchone()[0]
        nav_after = conn.execute(
            "SELECT COUNT(*) FROM backtest_daily_nav WHERE run_id=?",
            (first.replay_id,)).fetchone()[0]
    assert apps_before == apps_after == 0
    assert nav_before == nav_after


# ---------------------------------------------------------------- 异常场景 14

def test_interrupted_replay_not_reported_as_success(temp_db):
    """中断留下的 running attempt 不会被当成成功。"""
    _seed_validation(temp_db)
    init_replay_schema(db_path=temp_db)
    from app.replay.registry import start_attempt

    start_attempt(VALIDATION, "src_val", db_path=temp_db)
    assert find_success(VALIDATION, "src_val", db_path=temp_db) is None
    rows = _attempts(temp_db, VALIDATION)
    assert rows[0]["status"] == "running"
    assert rows[0]["replay_record_id"] is None


def test_history_untouched_after_failed_replay(temp_db, monkeypatch):
    """失败重放后源记录整行不变。"""
    _seed_validation(temp_db)
    with get_connection(temp_db) as conn:
        before = dict(conn.execute(
            "SELECT * FROM validation_runs WHERE validation_id='src_val'"
        ).fetchone())

    _fake_validation(monkeypatch, validation_id="ghost", acct=None,
                     row_exists=False)
    replay_validation("src_val", db_path=temp_db)

    with get_connection(temp_db) as conn:
        after = dict(conn.execute(
            "SELECT * FROM validation_runs WHERE validation_id='src_val'"
        ).fetchone())
    assert before == after


# ---------------------------------------------------------------- 口径标记与降级

def test_replay_stamps_accounting_version_on_new_record(temp_db, monkeypatch):
    """重放成功后新记录必须带 ca-v2-receivable 标记。

    `save_validation_run()` 的 INSERT 不含该列；不补标记，新记录天生为
    NULL，重放永远过不了闸门——3A.3.2.3.3 第一次真实重放就是这样失败的。
    """
    _seed_validation(temp_db)

    import app.replay.runner as runner_mod
    import app.validation.runner as vrunner
    from app.validation.storage import save_validation_run, init_validation_schema
    from app.validation.storage import ValidationRecord

    init_validation_schema(temp_db)

    def _run(cfg, **kwargs):
        rec = ValidationRecord(
            validation_id="realnew01",
            strategy_name="ma_trend", strategy_version="1.0.0",
            config_hash="h", eth_codes=["510300"], ma_window_grid=[5],
            is_start="2024-01-02", is_end="2024-01-05",
            oos_start="2024-01-08", oos_end="2024-01-12",
            status="success", conclusion="不通过", input_hash="ih",
        )
        save_validation_run(rec, db_path=temp_db)
        return SimpleNamespace(validation_id="realnew01", status="success",
                               conclusion="不通过", codes=["510300"])

    monkeypatch.setattr(vrunner, "run_validation", _run)
    outcome = replay_validation("src_val", db_path=temp_db)
    assert outcome.status == STATUS_SUCCESS
    with get_connection(temp_db) as conn:
        acct = conn.execute(
            "SELECT accounting_version FROM validation_runs WHERE validation_id='realnew01'"
        ).fetchone()[0]
    assert acct == "ca-v2-receivable"
    assert find_success(VALIDATION, "src_val", db_path=temp_db) == "realnew01"


def test_failed_gate_downgrades_orphan_record(temp_db, monkeypatch):
    """闸门失败时，刚建出来的记录必须被降级为 failed，不能留假 success。"""
    _seed_validation(temp_db)

    import app.replay.runner as runner_mod
    import app.validation.runner as vrunner
    from app.validation.storage import init_validation_schema, save_validation_run
    from app.validation.storage import ValidationRecord

    init_validation_schema(temp_db)

    def _run(cfg, **kwargs):
        rec = ValidationRecord(
            validation_id="orphan01",
            strategy_name="ma_trend", strategy_version="1.0.0",
            config_hash="h", eth_codes=["510300"], ma_window_grid=[5],
            is_start="2024-01-02", is_end="2024-01-05",
            oos_start="2024-01-08", oos_end="2024-01-12",
            status="success", conclusion="通过", input_hash="ih",
        )
        save_validation_run(rec, db_path=temp_db)
        return SimpleNamespace(validation_id="orphan01", status="success",
                               conclusion="通过", codes=["510300"])

    monkeypatch.setattr(vrunner, "run_validation", _run)
    # 让回查拿到 None，模拟「记录没落库」
    monkeypatch.setattr(runner_mod, "_fetch_validation_record",
                        lambda vid, *, db_path=None: None)
    # 但降级需要真实库，故只伪造回查不伪造标记写入
    outcome = replay_validation("src_val", db_path=temp_db)
    assert outcome.status == STATUS_FAILED
    with get_connection(temp_db) as conn:
        row = conn.execute(
            "SELECT status, accounting_version FROM validation_runs "
            "WHERE validation_id='orphan01'"
        ).fetchone()
    assert row is not None
    assert row[0] == "failed"
    assert row[1] == "ca-v2-receivable"
    assert find_success(VALIDATION, "src_val", db_path=temp_db) is None
