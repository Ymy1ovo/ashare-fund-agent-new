"""阶段3A.3.2.3.4：validation 内部回测审计追溯测试。

每条都核实数据库最终状态，不只看返回值。
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.backtest.api import ACCOUNTING_DISABLED, ACCOUNTING_FORMAL
from app.database.db import get_connection
from app.validation import audit
from app.validation.audit import (
    AuditError,
    audit_completeness,
    audit_coverage,
    audit_trace,
    init_audit_schema,
    list_backtest_runs,
    list_regime_stats,
    persist_sparse_details,
    register_backtest,
    save_regime_stats,
)
from tests.test_replay_3a3_2_3_1 import _insert_validation
from app.validation.config import ValidationConfig


# ---------------------------------------------------------------- 脚手架

def _cfg(**overrides):
    base = dict(is_start="2024-01-02", is_end="2024-01-05",
                oos_start="2024-01-08", oos_end="2024-01-12",
                ma_window_grid=(5, 20), pool_mode="representative")
    base.update(overrides)
    return ValidationConfig(**base)


def _seed_validation(temp_db, vid="val_audit", **overrides):
    cfg = _cfg(**overrides)
    _insert_validation(temp_db, vid, grid=cfg.ma_window_grid,
                       config_hash=cfg.params_hash())
    init_audit_schema(temp_db)
    return cfg


def _result(run_id="run001", *, basis=ACCOUNTING_FORMAL, formal=True,
            digest="digest01", codes=("510300",)):
    return SimpleNamespace(
        run_id=run_id, accounting_basis=basis, formal_valuation=formal,
        strategy_name="ma_trend", strategy_version="1.0.0",
        indicator_version="v1.0.2-30b821a1af15", initial_cash=1_000_000.0,
        codes=list(codes), input_hash="ih" + run_id[-3:],
        corporate_action_digest=digest, corporate_action_log=[],
        daily=[], trades=[], orders=[],
        config=SimpleNamespace(start_date="2024-01-02",
                               end_date="2024-01-05",
                               strategy_params={"ma_window": 20}),
    )


def _evidence(temp_db, run_id, **overrides):
    """内部回测必须先有存在性凭证，才能登记关联。

    测试走 `register_run_evidence()` 同一入口，保证「凭证 ⇔ 真跑过」。
    """
    audit.register_run_evidence(_result(run_id, **overrides), db_path=temp_db)
    return run_id


def _count(temp_db, table, where="1=1", params=()):
    with get_connection(temp_db) as conn:
        return conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {where}", params
        ).fetchone()[0]


# ---------------------------------------------------------------- 表结构

def test_audit_tables_created(temp_db):
    init_audit_schema(temp_db)
    with get_connection(temp_db) as conn:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "validation_backtest_runs" in names
    assert "validation_regime_stats" in names


def test_unique_constraint_on_validation_and_run(temp_db):
    _seed_validation(temp_db)
    _evidence(temp_db, "dup01")
    audit.register_backtest(_result("dup01"), role=audit.ROLE_OOS,
                            validation_id="val_audit", db_path=temp_db)
    with pytest.raises(AuditError, match="已登记过"):
        audit.register_backtest(_result("dup01"), role=audit.ROLE_OOS,
                                validation_id="val_audit", db_path=temp_db)
    assert _count(temp_db, "validation_backtest_runs") == 1


# ---------------------------------------------------------------- 异常 1/2

def test_audit_trace_validation_not_found(temp_db):
    init_audit_schema(temp_db)
    payload = audit_trace("no_such_validation", db_path=temp_db)
    assert payload["found"] is False
    assert payload["audit_status"] == "validation_not_found"
    assert payload["links"] == []


def test_ghost_run_cannot_be_registered(temp_db):
    """不存在的 run_id 不能登记，更不能被判定为 complete。"""
    _seed_validation(temp_db)
    with pytest.raises(AuditError, match="在 backtest_runs 中不存在"):
        audit.register_backtest(_result("ghost_run"), role=audit.ROLE_OOS,
                                validation_id="val_audit", db_path=temp_db)
    assert _count(temp_db, "validation_backtest_runs") == 0
    assert _count(temp_db, "backtest_runs", "run_id='ghost_run'") == 0
    payload = audit_trace("val_audit", db_path=temp_db)
    assert payload["audit_status"] == "unavailable_legacy"
    assert payload["audit_status"] != "complete"


def test_ghost_run_in_table_marked_incomplete(temp_db):
    """即使关联表被人为塞进一条 success，缺凭证也必须判 incomplete。"""
    _seed_validation(temp_db)
    with get_connection(temp_db) as conn:
        conn.execute(
            "INSERT INTO validation_backtest_runs "
            "(validation_id, backtest_run_id, run_role, scenario_key, "
            " accounting_basis, formal_valuation, status, created_at, "
            " applied_action_count, receivable_count, receivable_amount, "
            " settled_count, settled_amount) "
            "VALUES ('val_audit','ghost_run','out_of_sample','ma20',"
            "'formal_receivable',1,'success','2026-01-01T00:00:00',0,0,0.0,0,0.0)"
        )
    payload = audit_trace("val_audit", db_path=temp_db)
    # 全部 run 都没凭证 = 存量记录状态；关键是不能判 complete
    assert payload["audit_status"] in ("incomplete", "unavailable_legacy_evidence")
    assert payload["audit_status"] != "complete"
    assert payload["problems"]
    assert payload["links"][0]["run_exists"] is False


# ---------------------------------------------------------------- 异常 3/4

def test_same_validation_many_runs(temp_db):
    _seed_validation(temp_db)
    for idx, role in enumerate((audit.ROLE_IN_SAMPLE, audit.ROLE_OOS,
                                audit.ROLE_BENCHMARK)):
        _evidence(temp_db, f"multi{idx}")
        audit.register_backtest(_result(f"multi{idx}"), role=role,
                                scenario_key=f"s{idx}",
                                validation_id="val_audit", db_path=temp_db)
    runs = list_backtest_runs("val_audit", db_path=temp_db)
    assert len(runs) == 3
    assert [r["run_role"] for r in runs] == [
        audit.ROLE_IN_SAMPLE, audit.ROLE_OOS, audit.ROLE_BENCHMARK]


def test_same_run_registered_under_two_validations(temp_db):
    """同一 run_id 挂到两个 validation 下：允许（不同父），但审计各自独立。"""
    _seed_validation(temp_db, "val_a")
    _seed_validation(temp_db, "val_b")
    _evidence(temp_db, "shared1")
    audit.register_backtest(_result("shared1"), role=audit.ROLE_OOS,
                            validation_id="val_a", db_path=temp_db)
    _evidence(temp_db, "shared1")
    audit.register_backtest(_result("shared1"), role=audit.ROLE_OOS,
                            validation_id="val_b", db_path=temp_db)
    assert len(list_backtest_runs("val_a", db_path=temp_db)) == 1
    assert len(list_backtest_runs("val_b", db_path=temp_db)) == 1


# ---------------------------------------------------------------- 异常 5/6/7

def test_missing_formal_flag_rejected(temp_db):
    _seed_validation(temp_db)
    with pytest.raises(AuditError, match="formal_valuation"):
        audit.register_backtest(_result("noformal", formal=None),
                                role=audit.ROLE_OOS,
                                validation_id="val_audit", db_path=temp_db)
    assert _count(temp_db, "validation_backtest_runs") == 0


@pytest.mark.parametrize("formal", [1, 0, "yes", [1], 1.0, {"a": 1}])
def test_non_boolean_formal_rejected(temp_db, formal):
    _seed_validation(temp_db)
    with pytest.raises(AuditError, match="formal_valuation"):
        audit.register_backtest(_result("badbool", formal=formal),
                                role=audit.ROLE_OOS,
                                validation_id="val_audit", db_path=temp_db)
    assert _count(temp_db, "validation_backtest_runs") == 0


@pytest.mark.parametrize("basis", [ACCOUNTING_DISABLED, "unknown_legacy",
                                   None, "", "ca-v2-receivable"])
def test_non_formal_basis_rejected(temp_db, basis):
    _seed_validation(temp_db)
    with pytest.raises(AuditError, match="会计口径"):
        audit.register_backtest(_result("badbasis", basis=basis),
                                role=audit.ROLE_OOS,
                                validation_id="val_audit", db_path=temp_db)
    assert _count(temp_db, "validation_backtest_runs") == 0


# ---------------------------------------------------------------- 异常 8

def test_event_load_failure_leaves_validation_failed(temp_db, monkeypatch):
    """验证中途事件加载失败 → validation 失败，已登记痕迹保留且判 incomplete。"""
    import app.validation.runner as vrunner

    _seed_validation(temp_db)
    _evidence(temp_db, "partial1")
    audit.register_backtest(_result("partial1"), role=audit.ROLE_OOS,
                            validation_id="val_audit", db_path=temp_db)

    def _boom(*a, **kw):
        raise RuntimeError("corporate_actions 读取失败")

    monkeypatch.setattr(vrunner, "run_validation", _boom)
    from app.replay.runner import replay_validation
    outcome = replay_validation("val_audit", db_path=temp_db)
    assert outcome.status == "failed"
    payload = audit_trace("val_audit", db_path=temp_db)
    assert payload["backtest_run_count"] >= 1


# ---------------------------------------------------------------- 异常 9/10

def test_missing_application_and_receivable_marked_not_fabricated(temp_db):
    """明细缺失时计数为 0，但要能看出「确实没有」而不是「伪造有」。"""
    _seed_validation(temp_db)
    _evidence(temp_db, "empty01")
    audit.register_backtest(_result("empty01"), role=audit.ROLE_OOS,
                            validation_id="val_audit", db_path=temp_db)
    link = audit_trace("val_audit", db_path=temp_db)["links"][0]
    assert link["application_count"] == 0
    assert link["receivable_amount"] == 0.0
    assert link["settled_count"] == 0
    assert link["unsettled_count"] == 0


# ---------------------------------------------------------------- 异常 11/12

def test_duplicate_receivable_not_double_counted(temp_db):
    """同一 run 的应收行只按库内实际行数统计；重复写入会被唯一约束挡住。"""
    _seed_validation(temp_db)
    _evidence(temp_db, "recv01")
    audit.register_backtest(_result("recv01"), role=audit.ROLE_OOS,
                            validation_id="val_audit", db_path=temp_db)
    from app.backtest.corporate_actions import (
        ACTION_CASH_DISTRIBUTION, load_actions, save_receivable,
    )
    from tests.test_corporate_actions import _insert_action

    _insert_action(temp_db, code="510300",
                   action_type=ACTION_CASH_DISTRIBUTION,
                   ex_date="2024-01-04", effective_date="2024-01-04",
                   cash_per_share=0.5, record_date="2024-01-03",
                   pay_date="2024-01-05")
    built = load_actions(start="2024-01-01", end="2024-12-31", db_path=temp_db)[0]
    save_receivable(run_id="recv01", action=built, shares=1000, amount=500.0,
                    db_path=temp_db)
    save_receivable(run_id="recv01", action=built, shares=1000, amount=500.0,
                    db_path=temp_db)
    link = audit_trace("val_audit", db_path=temp_db)["links"][0]
    assert link["receivable_count"] == 1
    assert link["receivable_amount"] == pytest.approx(500.0)


def test_duplicate_settlement_does_not_change_amount(temp_db):
    _seed_validation(temp_db)
    _evidence(temp_db, "recv02")
    audit.register_backtest(_result("recv02"), role=audit.ROLE_OOS,
                            validation_id="val_audit", db_path=temp_db)
    from app.backtest.corporate_actions import (
        ACTION_CASH_DISTRIBUTION, load_actions, save_receivable,
        settle_receivable,
    )
    from tests.test_corporate_actions import _insert_action

    _insert_action(temp_db, code="510300",
                   action_type=ACTION_CASH_DISTRIBUTION,
                   ex_date="2024-01-04", effective_date="2024-01-04",
                   cash_per_share=0.5, record_date="2024-01-03",
                   pay_date="2024-01-05")
    built = load_actions(start="2024-01-01", end="2024-12-31", db_path=temp_db)[0]
    save_receivable(run_id="recv02", action=built, shares=1000, amount=500.0,
                    db_path=temp_db)
    settle_receivable(run_id="recv02", action_id=built.action_id, db_path=temp_db)
    settle_receivable(run_id="recv02", action_id=built.action_id, db_path=temp_db)
    link = audit_trace("val_audit", db_path=temp_db)["links"][0]
    assert link["receivable_count"] == 1
    assert link["settled_count"] == 1
    assert link["settled_amount"] == pytest.approx(500.0)
    assert link["unsettled_count"] == 0


# ---------------------------------------------------------------- 异常 13/14

def test_regime_insufficient_sample_persisted(temp_db):
    _seed_validation(temp_db)
    payload = {
        "labels_available": True,
        "proxy_code": "510300",
        "min_samples": 20,
        "stats": {
            "bull": {"status": "insufficient_sample", "total_days": 5,
                     "valid_days": 3, "missing_days": 2, "samples": 3,
                     "reason": "有效日收益 3 < 20"},
            "bear": {"status": "ok", "total_days": 100, "valid_days": 95,
                     "missing_days": 5, "samples": 95,
                     "cumulative_return": 0.12, "mean_daily_return": 0.001,
                     "annualized_volatility": 0.18, "win_rate": 0.55},
            "range": {"status": "ok", "total_days": 80, "valid_days": 78,
                      "missing_days": 2, "samples": 78,
                      "cumulative_return": 0.05},
            "unclassified": {"status": "ok", "total_days": 10,
                             "valid_days": 9, "missing_days": 1,
                             "samples": 9, "cumulative_return": -0.01},
        },
    }
    written = save_regime_stats("val_audit", payload, db_path=temp_db)
    assert written == 4
    rows = {r["regime_label"]: r for r in list_regime_stats("val_audit",
                                                            db_path=temp_db)}
    assert rows["bull"]["status"] == "insufficient_sample"
    assert rows["bull"]["reason"] == "有效日收益 3 < 20"
    assert rows["bull"]["cumulative_return"] is None
    assert rows["bear"]["samples"] == 95
    assert rows["unclassified"]["total_days"] == 10
    assert rows["unclassified"]["cumulative_return"] == pytest.approx(-0.01)


def test_regime_missing_day_kept_apart(temp_db):
    """missing_days 必须单独保存，不与 valid_days 合并。"""
    _seed_validation(temp_db)
    save_regime_stats("val_audit", {
        "proxy_code": "510300", "min_samples": 20,
        "stats": {"bull": {"status": "ok", "total_days": 100,
                           "valid_days": 90, "missing_days": 10,
                           "samples": 90, "cumulative_return": 0.1}},
    }, db_path=temp_db)
    row = [r for r in list_regime_stats("val_audit", db_path=temp_db)
           if r["regime_label"] == "bull"][0]
    assert row["total_days"] == 100
    assert row["valid_days"] == 90
    assert row["missing_days"] == 10


def test_regime_absent_label_marked_unavailable_not_fabricated(temp_db):
    _seed_validation(temp_db)
    save_regime_stats("val_audit", {"proxy_code": "510300",
                                    "stats": {"bull": {"status": "ok"}}},
                      db_path=temp_db)
    rows = {r["regime_label"]: r for r in list_regime_stats("val_audit",
                                                            db_path=temp_db)}
    assert rows["bear"]["status"] == "unavailable"
    assert rows["bear"]["cumulative_return"] is None
    assert "未产生统计" in rows["bear"]["reason"]


# ---------------------------------------------------------------- 异常 15/17

def test_partial_validation_marked_incomplete(temp_db):
    """只登记了一部分角色 → coverage 不完整。"""
    _seed_validation(temp_db)
    _evidence(temp_db, "p1")
    audit.register_backtest(_result("p1"), role=audit.ROLE_OOS,
                            validation_id="val_audit", db_path=temp_db)
    coverage = audit_coverage("val_audit", db_path=temp_db)
    assert coverage["complete"] is False
    assert audit.ROLE_IN_SAMPLE in coverage["roles_absent"]
    assert audit.ROLE_BENCHMARK in coverage["roles_absent"]


def test_failed_run_marks_audit_incomplete(temp_db):
    _seed_validation(temp_db)
    _evidence(temp_db, "ok_run")
    audit.register_backtest(_result("ok_run"), role=audit.ROLE_OOS,
                            validation_id="val_audit", db_path=temp_db)
    _evidence(temp_db, "bad_run")
    audit.register_backtest(_result("bad_run"), role=audit.ROLE_BENCHMARK,
                            validation_id="val_audit", status="failed",
                            reason="模拟失败", db_path=temp_db)
    payload = audit_trace("val_audit", db_path=temp_db)
    assert payload["audit_status"] == "incomplete"


# ---------------------------------------------------------------- 异常 16

def test_register_without_validation_id_raises(temp_db):
    init_audit_schema(temp_db)
    with pytest.raises(AuditError, match="缺少 validation_id"):
        register_backtest(_result("noparent"), role=audit.ROLE_OOS,
                          db_path=temp_db)
    assert _count(temp_db, "validation_backtest_runs") == 0


def test_register_without_run_id_raises(temp_db):
    _seed_validation(temp_db)
    broken = _result("x")
    broken.run_id = None
    with pytest.raises(AuditError, match="run_id"):
        register_backtest(broken, role=audit.ROLE_OOS,
                          validation_id="val_audit", db_path=temp_db)
    assert _count(temp_db, "validation_backtest_runs") == 0


# ---------------------------------------------------------------- 异常 18

def test_legacy_record_audit_unavailable(temp_db):
    _seed_validation(temp_db)
    payload = audit_trace("val_audit", db_path=temp_db)
    assert payload["audit_status"] == "unavailable_legacy"
    assert payload["links"] == []
    assert any("无内部回测登记" in p for p in payload["problems"])


# ---------------------------------------------------------------- 异常 19/20

def test_repeated_query_returns_same_result(temp_db):
    _seed_validation(temp_db)
    _evidence(temp_db, "q1")
    audit.register_backtest(_result("q1"), role=audit.ROLE_OOS,
                            validation_id="val_audit", db_path=temp_db)
    first = audit_trace("val_audit", db_path=temp_db)
    second = audit_trace("val_audit", db_path=temp_db)
    assert first == second
    assert first["backtest_run_count"] == 1


def test_repeated_regime_write_idempotent(temp_db):
    _seed_validation(temp_db)
    payload = {"proxy_code": "510300", "min_samples": 20,
               "stats": {"bull": {"status": "ok", "total_days": 10,
                                  "valid_days": 9, "missing_days": 1,
                                  "samples": 9, "cumulative_return": 0.02}}}
    save_regime_stats("val_audit", payload, db_path=temp_db)
    save_regime_stats("val_audit", payload, db_path=temp_db)
    rows = list_regime_stats("val_audit", db_path=temp_db)
    assert len(rows) == 4  # 四个标签各一行，未重复插入
    bull = [r for r in rows if r["regime_label"] == "bull"][0]
    assert bull["total_days"] == 10


# ---------------------------------------------------------------- 场景键与副本库

def test_scenario_key_falls_back_to_context(temp_db):
    """调用点漏传 scenario_key 时，从审计上下文取，不丢场景信息。"""
    _seed_validation(temp_db)
    with audit.audit_scope(audit.ROLE_STRESS_COST, "cost_plus_50",
                           validation_id="val_audit"):
        _evidence(temp_db, "ctx01")
        audit.register_backtest(_result("ctx01"), role=audit.ROLE_STRESS_COST,
                                db_path=temp_db)
    rows = list_backtest_runs("val_audit", db_path=temp_db)
    assert rows[0]["scenario_key"] == "cost_plus_50"


def test_audit_db_path_redirects_registration(temp_db, tmp_path):
    """sparse 场景跑在副本库上，但审计登记必须写主库。"""
    from app.validation.runner import _run_backtest

    _seed_validation(temp_db)
    copy_db = tmp_path / "copy.db"
    from app.database.db import init_db
    init_db(db_path=copy_db)

    class _FakeEngine:
        def __init__(self, cfg, strategy, db_path=None):
            self.db_path = db_path

        def run(self, codes, indicator_version=None):
            return _result("sparse_run", basis=ACCOUNTING_FORMAL, formal=True)

    import app.validation.runner as vrunner
    original_engine = vrunner.BacktestEngine
    original_perf = vrunner.compute_performance
    original_payload = vrunner._metrics_payload
    vrunner.BacktestEngine = _FakeEngine
    vrunner.compute_performance = lambda *a, **kw: {}
    vrunner._metrics_payload = lambda *a, **kw: {}
    try:
        with audit.audit_scope(audit.ROLE_STRESS_SPARSE, "sparse_data",
                               validation_id="val_audit"):
            vrunner._run_backtest(
                SimpleNamespace(annualization=252, risk_free_rate=0.0,
                                start_date="2024-01-02", end_date="2024-01-05",
                                strategy_params={}),
                None, ["510300"], None, copy_db, audit_db_path=temp_db,
                audit_note="明细在副本库",
            )
    finally:
        vrunner.BacktestEngine = original_engine
        vrunner.compute_performance = original_perf
        vrunner._metrics_payload = original_payload

    rows = list_backtest_runs("val_audit", db_path=temp_db)
    assert len(rows) == 1
    assert rows[0]["run_role"] == audit.ROLE_STRESS_SPARSE
    assert rows[0]["scenario_key"] == "sparse_data"
    assert "副本库" in (rows[0]["reason"] or "")


def test_sparse_detail_persisted_and_reconciled(temp_db, tmp_path):
    """sparse 明细从副本库复制到主库审计区，逐条对账通过。"""
    from app.backtest.corporate_actions import (
        ACTION_CASH_DISTRIBUTION, load_actions, save_receivable,
    )
    from tests.test_corporate_actions import _insert_action
    from app.database.db import init_db

    _seed_validation(temp_db)
    copy_db = tmp_path / "sparse_copy.db"
    init_db(db_path=copy_db)
    _insert_action(copy_db, code="510300",
                   action_type=ACTION_CASH_DISTRIBUTION,
                   ex_date="2024-01-04", effective_date="2024-01-04",
                   cash_per_share=0.5, record_date="2024-01-03",
                   pay_date="2024-01-05")
    built = load_actions(start="2024-01-01", end="2024-12-31",
                         db_path=copy_db)[0]
    save_receivable(run_id="sparse_run", action=built, shares=1000,
                    amount=500.0, db_path=copy_db)

    _evidence(temp_db, "sparse_run")
    audit.register_backtest(
        _result("sparse_run"), role=audit.ROLE_STRESS_SPARSE,
        scenario_key="sparse_data", validation_id="val_audit",
        db_path=temp_db, detail_db_path=copy_db,
        detail_location=audit.DETAIL_EXTERNAL_MISSING,
        reason="明细在副本库",
    )
    persisted = audit.persist_sparse_details(
        "val_audit", "sparse_run", copy_db, db_path=temp_db)
    assert persisted["ok"] is True
    assert persisted["application_count"] == 0
    assert persisted["receivable_count"] == 1
    assert persisted["receivable_amount"] == pytest.approx(500.0)

    audit.mark_sparse_detail_location(
        "val_audit", "sparse_run",
        location=audit.DETAIL_SPARSE_TABLE, note="已复制到主库审计区",
        applied=0, receivable_count=1, receivable_amount=500.0,
        db_path=temp_db,
    )

    with get_connection(temp_db) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM audit_sparse_receivables "
            "WHERE validation_id='val_audit' AND run_id='sparse_run'"
        ).fetchone()[0]
    assert n == 1

    rows = list_backtest_runs("val_audit", db_path=temp_db)
    assert rows[0]["detail_location"] == audit.DETAIL_SPARSE_TABLE
    assert rows[0]["receivable_count"] == 1


# ---------------------------------------------------------------- 完整性数量校验

def test_completeness_detects_missing_grid_cell(temp_db):
    """缺一个网格档位 → 不完整，并指出缺哪个。"""
    _seed_validation(temp_db)
    for window in (5,):  # 配置是 (5, 20)，故意只登记 5
        _evidence(temp_db, f"g{window}")
        audit.register_backtest(_result(f"g{window}"),
                                role=audit.ROLE_IN_SAMPLE,
                                scenario_key=f"ma{window}",
                                validation_id="val_audit", db_path=temp_db)
    result = audit.audit_completeness("val_audit", db_path=temp_db)
    assert result["complete"] is False
    assert any("MA20 未登记" in p for p in result["problems"])


def test_completeness_ok_when_all_cells_present(temp_db):
    _seed_validation(temp_db)
    for window in (5, 20):
        _evidence(temp_db, f"g{window}")
        audit.register_backtest(_result(f"g{window}"),
                                role=audit.ROLE_IN_SAMPLE,
                                scenario_key=f"ma{window}",
                                validation_id="val_audit", db_path=temp_db)
    for role, scen in ((audit.ROLE_OOS, "ma20"),
                       (audit.ROLE_REGIME, "510300")):
        _evidence(temp_db, f"{role}1")
        audit.register_backtest(_result(f"{role}1"), role=role,
                                scenario_key=scen,
                                validation_id="val_audit", db_path=temp_db)
    # 基准与压力、WF 在 scaffold 里没有对应记录，按「未登记」判不完整
    result = audit.audit_completeness("val_audit", db_path=temp_db)
    assert result["complete"] is False
    assert any("benchmark 未登记" in p for p in result["problems"])


def test_completeness_reports_failed_run_reason(temp_db):
    _seed_validation(temp_db)
    _evidence(temp_db, "g5")
    audit.register_backtest(_result("g5"), role=audit.ROLE_IN_SAMPLE,
                            scenario_key="ma5", validation_id="val_audit",
                            db_path=temp_db)
    _evidence(temp_db, "g20")
    audit.register_backtest(_result("g20"), role=audit.ROLE_IN_SAMPLE,
                            scenario_key="ma20", validation_id="val_audit",
                            status="failed", reason="database is locked",
                            db_path=temp_db)
    result = audit.audit_completeness("val_audit", db_path=temp_db)
    assert result["complete"] is False
    assert any("database is locked" in p for p in result["problems"])


def test_external_detail_missing_marked_incomplete(temp_db):
    """明细登记在外部副本、主库查不到时，必须判 incomplete，不能当完整。"""
    _seed_validation(temp_db)
    _evidence(temp_db, "ext_run")
    audit.register_backtest(
        _result("ext_run"), role=audit.ROLE_STRESS_SPARSE,
        scenario_key="sparse_data", validation_id="val_audit",
        db_path=temp_db, detail_db_path=temp_db,
        detail_location=audit.DETAIL_EXTERNAL_MISSING,
        reason="明细在稀疏副本库",
    )
    with get_connection(temp_db) as conn:
        conn.execute(
            "UPDATE validation_backtest_runs SET applied_action_count=31, "
            "receivable_count=23, receivable_amount=12728.18 "
            "WHERE backtest_run_id='ext_run'"
        )
    payload = audit_trace("val_audit", db_path=temp_db)
    assert payload["audit_status"] == "incomplete"
    assert any("查不到任何逐笔明细" in p for p in payload["problems"])
    assert payload["links"][0]["detail_location"] == audit.DETAIL_EXTERNAL_MISSING


def test_main_db_detail_reported_as_main(temp_db):
    _seed_validation(temp_db)
    _evidence(temp_db, "main_run")
    audit.register_backtest(_result("main_run"), role=audit.ROLE_OOS,
                            validation_id="val_audit", db_path=temp_db)
    link = audit_trace("val_audit", db_path=temp_db)["links"][0]
    assert link["detail_location"] == audit.DETAIL_MAIN_DB
    assert link["detail_note"] is None


# ---------------------------------------------------------------- regime 指标补齐

def test_regime_stats_exposes_risk_metrics():
    """regime_stats 必须给出 Sharpe/Sortino/CAGR/回撤，口径与绩效函数一致。"""
    import datetime as dt
    from app.validation.regime import REGIME_BULL, REGIME_BEAR, regime_stats

    series, labels = {}, {}
    base = dt.date(2024, 1, 1)
    for i in range(60):
        day = base + dt.timedelta(days=i)
        series[day] = 0.004 if i % 4 else -0.003
        labels[day] = REGIME_BULL
    payload = regime_stats(series, labels)[REGIME_BULL]
    assert payload["status"] == "ok"
    assert payload["sharpe_ratio"] is not None
    assert payload["sortino_ratio"] is not None
    assert payload["cagr"] is not None
    assert payload["max_drawdown"] is not None
    assert payload["max_drawdown"] <= 0
    assert payload["cagr"] > 0


def test_regime_insufficient_sample_has_no_metrics():
    import datetime as dt
    from app.validation.regime import REGIME_BEAR, regime_stats

    series, labels = {}, {}
    base = dt.date(2024, 1, 1)
    for i in range(3):
        day = base + dt.timedelta(days=i)
        series[day] = 0.001
        labels[day] = REGIME_BEAR
    payload = regime_stats(series, labels)[REGIME_BEAR]
    assert payload["status"] == "insufficient_sample"
    assert "sharpe_ratio" not in payload
    assert "cagr" not in payload
    assert payload["reason"]


def test_regime_metrics_persisted_after_save(temp_db):
    _seed_validation(temp_db)
    import datetime as dt
    from app.validation.regime import REGIME_BULL, regime_stats

    series, labels = {}, {}
    base = dt.date(2024, 1, 1)
    for i in range(60):
        day = base + dt.timedelta(days=i)
        series[day] = 0.002 if i % 5 else -0.001
        labels[day] = REGIME_BULL
    payload = {"proxy_code": "510300", "min_samples": 20,
               "stats": regime_stats(series, labels)}
    save_regime_stats("val_audit", payload, db_path=temp_db)
    rows = {r["regime_label"]: r for r in list_regime_stats("val_audit",
                                                            db_path=temp_db)}
    bull = rows["bull"]
    assert bull["sharpe_ratio"] is not None
    assert bull["sortino_ratio"] is not None
    assert bull["cagr"] is not None
    assert bull["max_drawdown"] is not None


# ---------------------------------------------------------------- 3A.3.2.3.4.1 反向测试

def test_register_rejects_missing_validation(temp_db):
    """不存在的 validation_id 不能登记。"""
    _seed_validation(temp_db)
    _evidence(temp_db, "orphan_run")
    with pytest.raises(AuditError, match="validation_id=no_such_val 不存在"):
        audit.register_backtest(_result("orphan_run"), role=audit.ROLE_OOS,
                                validation_id="no_such_val", db_path=temp_db)
    assert _count(temp_db, "validation_backtest_runs") == 0


def test_register_rejects_empty_run_id(temp_db):
    _seed_validation(temp_db)
    broken = _result("x")
    broken.run_id = "   "
    with pytest.raises(AuditError, match="有效 run_id"):
        audit.register_backtest(broken, role=audit.ROLE_OOS,
                                validation_id="val_audit", db_path=temp_db)
    assert _count(temp_db, "validation_backtest_runs") == 0


def test_register_rejects_user_run_as_internal(temp_db):
    """用户直接跑的回测（standalone）不能被当作内部回测登记。"""
    _seed_validation(temp_db)
    # 模拟用户直接跑出来的回测凭证（run_scope 默认 standalone）
    with get_connection(temp_db) as conn:
        conn.execute(
            "INSERT INTO backtest_runs "
            "(run_id, strategy_name, strategy_version, config_json, initial_cash, "
            " start_date, end_date, etf_codes, indicator_version, snapshot_ids, "
            " input_hash, summary_json, created_at, run_scope) "
            "VALUES ('user_run','ma_trend','1.0.0','{}',1000000.0,"
            "'2024-01-02','2024-01-05','[]',NULL,'{}','deadbeef','{}',"
            "'2026-01-01T00:00:00','standalone')"
        )
    result = _result("user_run")
    with pytest.raises(AuditError, match="用户回测记录"):
        audit.register_backtest(result, role=audit.ROLE_OOS,
                                validation_id="val_audit", db_path=temp_db)
    assert _count(temp_db, "validation_backtest_runs") == 0


def test_register_rejects_non_formal_basis_before_evidence(temp_db):
    """口径非正式时连凭证都不写。"""
    _seed_validation(temp_db)
    with pytest.raises(AuditError, match="会计口径非正式"):
        audit.register_run_evidence(
            _result("bad_evi", basis="disabled_non_official"), db_path=temp_db)
    assert _count(temp_db, "backtest_runs", "run_id='bad_evi'") == 0


def test_validation_failed_status_not_complete(temp_db):
    _seed_validation(temp_db)
    with get_connection(temp_db) as conn:
        conn.execute("UPDATE validation_runs SET status='failed' "
                     "WHERE validation_id='val_audit'")
    result = audit.audit_completeness("val_audit", db_path=temp_db)
    assert result["complete"] is False
    assert result["audit_status"] != "complete"


def test_trace_and_completeness_agree(temp_db):
    """audit_trace 与 audit_completeness 的结论必须一致。"""
    _seed_validation(temp_db)
    for window in (5, 20):
        _evidence(temp_db, f"g{window}")
        audit.register_backtest(_result(f"g{window}"),
                                role=audit.ROLE_IN_SAMPLE,
                                scenario_key=f"ma{window}",
                                validation_id="val_audit", db_path=temp_db)
    trace = audit_trace("val_audit", db_path=temp_db)
    checklist = audit.audit_completeness("val_audit", db_path=temp_db)
    assert (trace["audit_status"] == "complete") == checklist["complete"]
    assert trace["completeness"]["complete"] == checklist["complete"]
    assert trace["problems"] == checklist["problems"]


def test_register_before_evidence_fails(temp_db):
    """没有存在性凭证时不允许登记关联。"""
    _seed_validation(temp_db)
    with pytest.raises(AuditError, match="在 backtest_runs 中不存在"):
        audit.register_backtest(_result("no_evi"), role=audit.ROLE_OOS,
                                validation_id="val_audit", db_path=temp_db)
    assert _count(temp_db, "validation_backtest_runs") == 0


def test_sparse_copy_removed_only_after_reconcile(temp_db, tmp_path):
    """对账失败时副本必须保留，且不留半条明细。"""
    from app.database.db import init_db

    workdir = tmp_path / "val_sparse_test"
    workdir.mkdir(parents=True, exist_ok=True)
    copy_db = workdir / "sparse_market.db"
    init_db(db_path=copy_db)
    _seed_validation(temp_db)

    # 副本里没有该 run 的明细 → 复制 0 条，对账通过；这不是失败场景。
    ok = audit.persist_sparse_details("val_audit", "ghost_sparse", copy_db,
                                      db_path=temp_db)
    assert ok["ok"] is True
    assert ok["application_count"] == 0

    # 真正的失败场景：副本不存在
    with pytest.raises(AuditError, match="副本库不存在"):
        audit.persist_sparse_details("val_audit", "ghost_sparse",
                                     workdir / "missing.db", db_path=temp_db)
    assert copy_db.exists(), "对账失败时不得删除副本"


def test_sparse_reconcile_detects_amount_mismatch(temp_db, tmp_path):
    """金额不一致必须被对账抓住。"""
    from app.database.db import init_db

    workdir = tmp_path / "val_sparse_amt"
    workdir.mkdir(parents=True, exist_ok=True)
    copy_db = workdir / "sparse_market.db"
    init_db(db_path=copy_db)
    _seed_validation(temp_db)

    from app.backtest.corporate_actions import ACTION_CASH_DISTRIBUTION
    from tests.test_corporate_actions import _insert_action

    action_id = _insert_action(
        copy_db, code="510300", action_type=ACTION_CASH_DISTRIBUTION,
        ex_date="2024-01-04", effective_date="2024-01-04",
        cash_per_share=0.5, record_date="2024-01-03",
        pay_date="2024-01-05",
    )
    with get_connection(copy_db) as conn:
        conn.execute(
            "INSERT INTO dividend_receivables "
            "(run_id, action_id, code, record_date, ex_date, pay_date, "
            " shares_at_ex, cash_per_share, amount, status, created_at) "
            "VALUES ('amt_run', ?, '510300', '2024-01-03', '2024-01-04', "
            "'2024-01-05', 1000, 0.5, 500.0, 'pending', '2024-01-04T00:00:00')",
            (action_id,),
        )
    # 先正常复制一次
    first = audit.persist_sparse_details("val_audit", "amt_run", copy_db,
                                         db_path=temp_db)
    assert first["receivable_amount"] == pytest.approx(500.0)
    # 篡改主库金额后再复制：主库已有行不会被覆盖，但副本仍一致
    with get_connection(temp_db) as conn:
        conn.execute("UPDATE audit_sparse_receivables SET amount=999.0 "
                     "WHERE run_id='amt_run'")
    with pytest.raises(AuditError, match="receivable_amount"):
        audit.persist_sparse_details("val_audit", "amt_run", copy_db,
                                     db_path=temp_db)


def test_sparse_detail_copy_idempotent(temp_db, tmp_path):
    """同一明细重复复制不产生重复行。"""
    from app.database.db import init_db

    workdir = tmp_path / "val_sparse_idem"
    workdir.mkdir(parents=True, exist_ok=True)
    copy_db = workdir / "sparse_market.db"
    init_db(db_path=copy_db)
    _seed_validation(temp_db)

    from app.backtest.corporate_actions import ACTION_SPLIT
    from tests.test_corporate_actions import _insert_action

    action_id = _insert_action(
        copy_db, code="510300", action_type=ACTION_SPLIT,
        ex_date="2024-01-04", effective_date="2024-01-04",
        share_ratio=2.0, fractional_policy="truncate",
    )
    with get_connection(copy_db) as conn:
        conn.execute(
            "INSERT INTO corporate_action_applications "
            "(run_id, action_id, code, effective_date, action_type, "
            " shares_before, shares_after, cash_delta, fractional_cash, "
            " applied_at, receivable_amount, cash_paid_amount, "
            " fractional_shares, disposed_cost_basis, realized_pnl, official_ratio) "
            "VALUES ('idem_run', ?, '510300', '2024-01-04', 'split', "
            " 1000, 2000, 0.0, 0.0, '2024-01-04T00:00:00', 0.0, 0.0, "
            " 0.0, 0.0, 0.0, 2.0)",
            (action_id,),
        )
    for _ in range(3):
        audit.persist_sparse_details("val_audit", "idem_run", copy_db,
                                     db_path=temp_db)
    with get_connection(temp_db) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM audit_sparse_applications "
            "WHERE validation_id='val_audit' AND run_id='idem_run'"
        ).fetchone()[0]
    assert n == 1


def test_event_version_linkage_present(temp_db):
    """事件版本可追溯时标 available，缺版本时标 version_unavailable。"""
    from app.backtest.corporate_actions import (
        ACTION_CASH_DISTRIBUTION, load_actions, save_receivable,
    )
    from tests.test_corporate_actions import _insert_action

    _seed_validation(temp_db)
    _insert_action(temp_db, code="510300",
                   action_type=ACTION_CASH_DISTRIBUTION,
                   ex_date="2024-01-04", effective_date="2024-01-04",
                   cash_per_share=0.5, record_date="2024-01-03",
                   pay_date="2024-01-05")
    built = load_actions(start="2024-01-01", end="2024-12-31",
                         db_path=temp_db)[0]
    save_receivable(run_id="ver_run", action=built, shares=1000,
                    amount=500.0, db_path=temp_db)
    _evidence(temp_db, "ver_run")
    audit.register_backtest(_result("ver_run"), role=audit.ROLE_OOS,
                            validation_id="val_audit", db_path=temp_db)
    link = audit_trace("val_audit", db_path=temp_db)["links"][0]
    assert link["events"], "应收事件必须出现在追溯结果里"
    item = link["events"][0]
    assert item["version_status"] in ("available", "version_unavailable")
    if item["version_status"] == "version_unavailable":
        assert item["action_id"] in link["versions_unavailable"]
        payload = audit_trace("val_audit", db_path=temp_db)
        assert payload["audit_status"] != "complete"


def test_regime_write_failure_marks_validation_failed(temp_db, monkeypatch):
    """regime 落库失败 → validation failed，已登记的关联保留。"""
    import app.validation.runner as vrunner

    _seed_validation(temp_db)
    _evidence(temp_db, "pre_run")
    audit.register_backtest(_result("pre_run"), role=audit.ROLE_OOS,
                            validation_id="val_audit", db_path=temp_db)

    def _boom(*a, **kw):
        raise RuntimeError("disk I/O error")

    monkeypatch.setattr(audit, "save_regime_stats", _boom)

    with get_connection(temp_db) as conn:
        conn.execute("UPDATE validation_runs SET status='failed' "
                     "WHERE validation_id='val_audit'")
    result = audit.audit_completeness("val_audit", db_path=temp_db)
    assert result["complete"] is False
    # 已登记的关联不能被删
    assert len(list_backtest_runs("val_audit", db_path=temp_db)) == 1


def test_audit_completeness_does_not_recurse(temp_db):
    """audit_completeness 不得反向调用 audit_trace（否则无限递归）。"""
    import inspect

    source = inspect.getsource(audit.audit_completeness)
    body = source.split('"""')[2] if source.count('"""') >= 2 else source
    assert "audit_trace(" not in body, "audit_completeness 不得调用 audit_trace"


# ================================================================
# 阶段3A.3.2.3.4.1.1：原子事务 / 逐字段对账 / WF / 压力 / 版本
# ================================================================

def _make_sparse_copy(tmp_path, name, *, run_id, action_type, **action_kwargs):
    """在稀疏副本库里造一条公司行为事件。返回 (copy_db, action_id)。"""
    from app.database.db import init_db as _init
    from tests.test_corporate_actions import _insert_action

    workdir = tmp_path / name
    workdir.mkdir(parents=True, exist_ok=True)
    copy_db = workdir / "sparse_market.db"
    _init(db_path=copy_db)
    action_id = _insert_action(copy_db, code="510300",
                               action_type=action_type, **action_kwargs)
    return copy_db, action_id


def _insert_app(copy_db, run_id, action_id, **overrides):
    fields = {
        "run_id": run_id, "action_id": action_id, "code": "510300",
        "effective_date": "2024-01-04", "action_type": "split",
        "shares_before": 1000, "shares_after": 2000, "cash_delta": 0.0,
        "fractional_cash": 0.0, "applied_at": "2024-01-04T00:00:00",
        "receivable_amount": 0.0, "cash_paid_amount": 0.0,
        "fractional_shares": 0.0, "disposed_cost_basis": 0.0,
        "realized_pnl": 0.0, "official_ratio": 2.0,
    }
    fields.update(overrides)
    with get_connection(copy_db) as conn:
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        conn.execute(
            f"INSERT INTO corporate_action_applications ({cols}) "
            f"VALUES ({marks})", list(fields.values()))


def _insert_recv(copy_db, run_id, action_id, **overrides):
    fields = {
        "run_id": run_id, "action_id": action_id, "code": "510300",
        "record_date": "2024-01-03", "ex_date": "2024-01-04",
        "pay_date": "2024-01-05", "shares_at_ex": 1000,
        "cash_per_share": 0.5, "amount": 500.0, "status": "pending",
        "created_at": "2024-01-04T00:00:00",
    }
    fields.update(overrides)
    with get_connection(copy_db) as conn:
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        conn.execute(
            f"INSERT INTO dividend_receivables ({cols}) VALUES ({marks})",
            list(fields.values()))


def _sparse_rows(temp_db, vid, run_id):
    with get_connection(temp_db) as conn:
        apps = conn.execute(
            "SELECT * FROM audit_sparse_applications "
            "WHERE validation_id=? AND run_id=?", (vid, run_id)).fetchall()
        recvs = conn.execute(
            "SELECT * FROM audit_sparse_receivables "
            "WHERE validation_id=? AND run_id=?", (vid, run_id)).fetchall()
    return [dict(r) for r in apps], [dict(r) for r in recvs]


def test_sparse_success_path_returns_dict(temp_db, tmp_path):
    """成功路径的 data_copy 必须是 dict（上一轮尾随逗号导致 tuple）。"""
    from app.validation.runner import _run_data_stress
    from app.validation.stress import build_scenarios

    _seed_validation(temp_db)
    vid = "val_audit"
    scenario = next(s for s in build_scenarios(["sparse_data"])
                    if s.key == "sparse_data")
    config = ValidationConfig(is_start="2024-01-02", is_end="2024-01-05",
                              oos_start="2024-01-08", oos_end="2024-01-12",
                              ma_window_grid=(5,), pool_mode="representative")
    split = type("S", (), {"oos_start": "2024-01-08",
                           "oos_end": "2024-01-12"})()

    row = _run_data_stress(scenario, config, split, ["510300"], 5, temp_db,
                           validation_id=vid)
    assert isinstance(row, dict), "返回值必须是 dict"
    assert "status" in row
    if row.get("status") == "success":
        assert isinstance(row["data_copy"], dict)
        assert "copy_path" in row["data_copy"]


@pytest.mark.parametrize("field,value", [
    ("code", "159999"),
    ("shares_before", 999),
    ("shares_after", 2001),
    ("cash_delta", 1.5),
    ("fractional_cash", 0.25),
    ("applied_at", "2024-01-05T00:00:00"),
    ("receivable_amount", 88.0),
    ("cash_paid_amount", 77.0),
    ("fractional_shares", 0.5),
    ("disposed_cost_basis", 12.0),
    ("realized_pnl", 3.0),
    ("official_ratio", 3.0),
    ("action_type", "reverse_split"),
    ("effective_date", "2024-01-09"),
])
def test_application_field_tamper_detected(temp_db, tmp_path, field, value):
    """应用明细任一日志字段被篡改，对账必须失败并整体回滚。"""
    from app.backtest.corporate_actions import ACTION_SPLIT

    _seed_validation(temp_db)
    vid = "val_audit"
    copy_db, action_id = _make_sparse_copy(
        tmp_path, "val_sparse_tamper", run_id="tamper_run",
        action_type=ACTION_SPLIT, ex_date="2024-01-04",
        effective_date="2024-01-04", share_ratio=2.0,
        fractional_policy="truncate")
    _insert_app(copy_db, "tamper_run", action_id)

    # 先正常复制一次
    persist_sparse_details(vid, "tamper_run", copy_db, db_path=temp_db)
    apps, _ = _sparse_rows(temp_db, vid, "tamper_run")
    assert len(apps) == 1

    # 篡改主库该字段
    with get_connection(temp_db) as conn:
        conn.execute(
            f"UPDATE audit_sparse_applications SET {field}=? "
            "WHERE validation_id=? AND run_id=?",
            (value, vid, "tamper_run"))

    with pytest.raises(AuditError, match=field):
        persist_sparse_details(vid, "tamper_run", copy_db, db_path=temp_db)

    # 回滚后主库仍是篡改前的值（本次插入没有改动它）
    apps_after, _ = _sparse_rows(temp_db, vid, "tamper_run")
    assert len(apps_after) == 1
    assert apps_after[0][field] == value


@pytest.mark.parametrize("field,value", [
    ("code", "159999"),
    ("record_date", "2024-01-02"),
    ("ex_date", "2024-01-03"),
    ("pay_date", "2024-01-08"),
    ("shares_at_ex", 999),
    ("cash_per_share", 0.6),
    ("amount", 600.0),
    ("status", "settled"),
    ("settled_at", "2024-01-05T00:00:00"),
])
def test_receivable_field_tamper_detected(temp_db, tmp_path, field, value):
    """应收明细任一字段被篡改，对账必须失败。"""
    from app.backtest.corporate_actions import ACTION_CASH_DISTRIBUTION

    _seed_validation(temp_db)
    vid = "val_audit"
    copy_db, action_id = _make_sparse_copy(
        tmp_path, "val_sparse_recv", run_id="recv_run",
        action_type=ACTION_CASH_DISTRIBUTION, ex_date="2024-01-04",
        effective_date="2024-01-04", cash_per_share=0.5,
        record_date="2024-01-03", pay_date="2024-01-05")
    _insert_recv(copy_db, "recv_run", action_id)

    persist_sparse_details(vid, "recv_run", copy_db, db_path=temp_db)
    _, recvs = _sparse_rows(temp_db, vid, "recv_run")
    assert len(recvs) == 1

    with get_connection(temp_db) as conn:
        conn.execute(
            f"UPDATE audit_sparse_receivables SET {field}=? "
            "WHERE validation_id=? AND run_id=?", (value, vid, "recv_run"))

    with pytest.raises(AuditError, match=field):
        persist_sparse_details(vid, "recv_run", copy_db, db_path=temp_db)


def test_reconcile_failure_rolls_back_whole_transaction(temp_db, tmp_path):
    """对账失败时本次插入整体回滚，主库不留半条新行。"""
    from app.backtest.corporate_actions import ACTION_CASH_DISTRIBUTION

    _seed_validation(temp_db)
    vid = "val_audit"
    copy_db, action_id = _make_sparse_copy(
        tmp_path, "val_sparse_rb", run_id="rb_run",
        action_type=ACTION_CASH_DISTRIBUTION, ex_date="2024-01-04",
        effective_date="2024-01-04", cash_per_share=0.5,
        record_date="2024-01-03", pay_date="2024-01-05")
    _insert_recv(copy_db, "rb_run", action_id)

    # 人为让主库已有一行金额错误（模拟历史脏数据）
    persist_sparse_details(vid, "rb_run", copy_db, db_path=temp_db)
    with get_connection(temp_db) as conn:
        conn.execute(
            "UPDATE audit_sparse_receivables SET amount=999.0 "
            "WHERE validation_id=? AND run_id=?", (vid, "rb_run"))

    # 再追加一条新应收到副本，然后重试：插入新行 + 对账失败 → 整体回滚
    _insert_recv(copy_db, "rb_run", action_id + 1, amount=700.0,
                 cash_per_share=0.7)
    with get_connection(copy_db) as conn:
        conn.execute(
            "UPDATE corporate_actions SET action_id=? WHERE action_id=?",
            (action_id + 1, action_id))
    # 上面这步只是让事件表能对应到新 action_id，实际构造见下
    with pytest.raises(AuditError):
        persist_sparse_details(vid, "rb_run", copy_db, db_path=temp_db)

    _, recvs = _sparse_rows(temp_db, vid, "rb_run")
    assert len(recvs) == 1, "失败后不得留下新增行"
    assert recvs[0]["amount"] == pytest.approx(999.0)


def test_sparse_persist_idempotent_three_times(temp_db, tmp_path):
    """同一明细连跑三次，行数恒为 1。"""
    from app.backtest.corporate_actions import ACTION_SPLIT

    _seed_validation(temp_db)
    vid = "val_audit"
    copy_db, action_id = _make_sparse_copy(
        tmp_path, "val_sparse_idem2", run_id="idem2_run",
        action_type=ACTION_SPLIT, ex_date="2024-01-04",
        effective_date="2024-01-04", share_ratio=2.0,
        fractional_policy="truncate")
    _insert_app(copy_db, "idem2_run", action_id)

    for _ in range(3):
        persist_sparse_details(vid, "idem2_run", copy_db, db_path=temp_db)
    apps, _ = _sparse_rows(temp_db, vid, "idem2_run")
    assert len(apps) == 1


def test_sparse_detail_keeps_version_and_fingerprint(temp_db, tmp_path):
    """sparse 明细必须保留事件版本号与 event_fingerprint。"""
    from app.backtest.corporate_actions import ACTION_CASH_DISTRIBUTION

    _seed_validation(temp_db)
    vid = "val_audit"
    copy_db, action_id = _make_sparse_copy(
        tmp_path, "val_sparse_ver", run_id="ver_run",
        action_type=ACTION_CASH_DISTRIBUTION, ex_date="2024-01-04",
        effective_date="2024-01-04", cash_per_share=0.5,
        record_date="2024-01-03", pay_date="2024-01-05")
    _insert_recv(copy_db, "ver_run", action_id)

    with get_connection(copy_db) as conn:
        expect = conn.execute(
            "SELECT version_no, event_fingerprint FROM corporate_actions "
            "WHERE action_id=?", (action_id,)).fetchone()

    persist_sparse_details(vid, "ver_run", copy_db, db_path=temp_db)
    _, recvs = _sparse_rows(temp_db, vid, "ver_run")
    assert recvs[0]["version_no"] == expect["version_no"]
    assert recvs[0]["event_fingerprint"] == expect["event_fingerprint"]


def test_sparse_persist_requires_event_row(temp_db, tmp_path):
    """副本里查不到事件行 → 版本不可追溯 → 对账失败，不留行。"""
    from app.database.db import init_db as _init

    _seed_validation(temp_db)
    vid = "val_audit"
    workdir = tmp_path / "val_sparse_noev"
    workdir.mkdir(parents=True, exist_ok=True)
    copy_db = workdir / "sparse_market.db"
    _init(db_path=copy_db)

    with get_connection(copy_db) as conn:
        conn.execute(
            "INSERT INTO corporate_action_applications "
            "(run_id, action_id, code, effective_date, action_type, "
            " shares_before, shares_after, cash_delta, fractional_cash, "
            " applied_at, receivable_amount, cash_paid_amount, "
            " fractional_shares, disposed_cost_basis, realized_pnl, official_ratio) "
            "VALUES ('noev_run', 999, '510300', '2024-01-04', 'split', "
            " 1000, 2000, 0.0, 0.0, '2024-01-04T00:00:00', 0.0, 0.0, "
            " 0.0, 0.0, 0.0, 2.0)")

    with pytest.raises(AuditError, match="版本不可追溯"):
        persist_sparse_details(vid, "noev_run", copy_db, db_path=temp_db)
    apps, _ = _sparse_rows(temp_db, vid, "noev_run")
    assert apps == []


# ---------------------------------------------------------------- 版本严格匹配

def test_version_exact_match_no_fallback(temp_db):
    """最新版本存在但历史版本不存在时，不得回退到最新版本。"""
    from app.backtest.corporate_actions import (
        ACTION_CASH_DISTRIBUTION, load_actions, save_receivable,
    )
    from tests.test_corporate_actions import _insert_action

    _seed_validation(temp_db)
    _insert_action(temp_db, code="510300",
                   action_type=ACTION_CASH_DISTRIBUTION,
                   ex_date="2024-01-04", effective_date="2024-01-04",
                   cash_per_share=0.5, record_date="2024-01-03",
                   pay_date="2024-01-05")
    built = load_actions(start="2024-01-01", end="2024-12-31",
                         db_path=temp_db)[0]
    save_receivable(run_id="vfb_run", action=built, shares=1000,
                    amount=500.0, db_path=temp_db)
    _evidence(temp_db, "vfb_run")
    audit.register_backtest(_result("vfb_run"), role=audit.ROLE_OOS,
                            validation_id="val_audit", db_path=temp_db)

    # 删掉该事件的精确版本行，只留另一个版本号
    with get_connection(temp_db) as conn:
        key = f"{built.code}|{built.action_type}|{built.ex_date}"
        conn.execute(
            "DELETE FROM corporate_action_versions WHERE action_key=?",
            (key,))
        conn.execute(
            "INSERT INTO corporate_action_versions "
            "(action_key, version_no, code, action_type, ex_date, "
            " effective_date, source, evidence_status, data_version, "
            " snapshot_json, created_at) "
            "VALUES (?, 99, ?, ?, ?, ?, 'test', 'official_confirmed', 'ca-v1', "
            "'{}', '2024-01-04T00:00:00')",
            (key, built.code, built.action_type, built.ex_date,
             built.effective_date.isoformat()))

    payload = audit_trace("val_audit", db_path=temp_db)
    link = payload["links"][0]
    item = link["events"][0]
    assert item["version_status"] == "version_unavailable", \
        "精确版本缺失时必须标 version_unavailable，不得回退到版本 99"
    assert item.get("version") is None
    assert built.action_id in link["versions_unavailable"]
    assert payload["audit_status"] != "complete"


def test_version_number_none_marked_unavailable(temp_db):
    """事件 version_no 为空时不得视为有版本。"""
    conn = get_connection
    assert audit._version_of(
        type("C", (), {"execute": lambda self, *a, **k: type(
            "R", (), {"fetchone": lambda self: None})()})(),
        {"version_no": None, "code": "510300",
         "action_type": "split", "ex_date": "2024-01-04"},
    ) is None


# ---------------------------------------------------------------- WF 完整性

def test_wf_missing_train_window_incomplete(temp_db):
    """缺训练窗口 → 不完整。"""
    _seed_validation(temp_db)
    vid = "val_audit"
    with get_connection(temp_db) as conn:
        conn.execute(
            "INSERT INTO validation_windows (validation_id, window_index, "
            "train_start, train_end, test_start, test_end, train_days, "
            "test_days, selected_param, status, created_at) "
            "VALUES (?, 0, '2023-01-02', '2023-12-29', '2024-01-02', "
            "'2024-06-28', 240, 120, 20, 'success', '2024-01-01T00:00:00')",
            (vid,))
        conn.execute(
            "UPDATE validation_runs SET walkforward_config=? "
            "WHERE validation_id=?", (json.dumps({"wf_grid": [5, 20, 60]}), vid))

    _evidence(temp_db, "w0_ma20")
    audit.register_backtest(_result("w0_ma20"), role=audit.ROLE_WF_TEST,
                            scenario_key="w0-ma20",
                            validation_id=vid, db_path=temp_db)

    result = audit_completeness(vid, db_path=temp_db)
    assert result["complete"] is False
    assert any("训练窗口 w0" in p for p in result["problems"])


def test_wf_missing_test_window_incomplete(temp_db):
    """缺测试窗口 → 不完整。"""
    _seed_validation(temp_db)
    vid = "val_audit"
    with get_connection(temp_db) as conn:
        conn.execute(
            "INSERT INTO validation_windows (validation_id, window_index, "
            "train_start, train_end, test_start, test_end, train_days, "
            "test_days, selected_param, status, created_at) "
            "VALUES (?, 0, '2023-01-02', '2023-12-29', '2024-01-02', "
            "'2024-06-28', 240, 120, 20, 'success', '2024-01-01T00:00:00')",
            (vid,))
        conn.execute(
            "UPDATE validation_runs SET walkforward_config=? "
            "WHERE validation_id=?", (json.dumps({"wf_grid": [20]}), vid))

    _evidence(temp_db, "w0_train_ma20")
    audit.register_backtest(_result("w0_train_ma20"),
                            role=audit.ROLE_WF_TRAIN, scenario_key="w0-ma20",
                            validation_id=vid, db_path=temp_db)

    result = audit_completeness(vid, db_path=temp_db)
    assert result["complete"] is False
    assert any("测试窗口 w0" in p for p in result["problems"])


def test_wf_failed_train_window_incomplete(temp_db):
    """训练窗口执行失败 → 不完整，并给出原因。"""
    _seed_validation(temp_db)
    vid = "val_audit"
    with get_connection(temp_db) as conn:
        conn.execute(
            "INSERT INTO validation_windows (validation_id, window_index, "
            "train_start, train_end, test_start, test_end, train_days, "
            "test_days, selected_param, status, created_at) "
            "VALUES (?, 0, '2023-01-02', '2023-12-29', '2024-01-02', "
            "'2024-06-28', 240, 120, 20, 'success', '2024-01-01T00:00:00')",
            (vid,))
        conn.execute(
            "UPDATE validation_runs SET walkforward_config=? "
            "WHERE validation_id=?", (json.dumps({"wf_grid": [20]}), vid))

    _evidence(temp_db, "wt_fail")
    audit.register_backtest(_result("wt_fail"), role=audit.ROLE_WF_TRAIN,
                            scenario_key="w0-ma20", validation_id=vid,
                            status="failed", reason="样本不足",
                            db_path=temp_db)
    _evidence(temp_db, "w0_test")
    audit.register_backtest(_result("w0_test"), role=audit.ROLE_WF_TEST,
                            scenario_key="w0-ma20", validation_id=vid,
                            db_path=temp_db)

    result = audit_completeness(vid, db_path=temp_db)
    assert result["complete"] is False
    assert any("样本不足" in p for p in result["problems"])


def test_wf_insufficient_window_incomplete(temp_db):
    """窗口数据不足未执行 → 不完整。"""
    _seed_validation(temp_db)
    vid = "val_audit"
    with get_connection(temp_db) as conn:
        conn.execute(
            "INSERT INTO validation_windows (validation_id, window_index, "
            "train_start, train_end, test_start, test_end, train_days, "
            "test_days, selected_param, status, created_at) "
            "VALUES (?, 0, '2023-01-02', '2023-01-10', '2024-01-02', "
            "'2024-01-05', 7, 4, NULL, 'insufficient_data', "
            "'2024-01-01T00:00:00')", (vid,))
    _evidence(temp_db, "any_run")
    audit.register_backtest(_result("any_run"), role=audit.ROLE_OOS,
                            validation_id=vid, db_path=temp_db)
    result = audit_completeness(vid, db_path=temp_db)
    assert result["complete"] is False
    joined = "；".join(result["problems"])
    assert ("数据不足" in joined or "窗口 w0" in joined), joined


# ---------------------------------------------------------------- 压力状态

def _seed_stress(temp_db, vid, key, status, reason=None):
    with get_connection(temp_db) as conn:
        conn.execute(
            "INSERT INTO validation_stress (validation_id, scenario_key, "
            "scenario_name, is_hypothetical, status, reason, created_at) "
            "VALUES (?,?,?,0,?,?,'2024-01-01T00:00:00')",
            (vid, key, key, status, reason))


def test_stress_success_but_execution_failed_incomplete(temp_db):
    """场景登记 success 但回测执行 failed → 不完整。"""
    _seed_validation(temp_db)
    vid = "val_audit"
    _seed_stress(temp_db, vid, "base", "success")
    _evidence(temp_db, "st_run")
    audit.register_backtest(_result("st_run"), role=audit.ROLE_STRESS_COST,
                            scenario_key="base", validation_id=vid,
                            status="failed", reason="回测崩溃",
                            db_path=temp_db)
    result = audit_completeness(vid, db_path=temp_db)
    assert result["complete"] is False
    assert any("回测执行状态为 failed" in p for p in result["problems"])


def test_stress_scenario_without_run_incomplete(temp_db):
    """场景未登记关联回测 → 不完整。"""
    _seed_validation(temp_db)
    vid = "val_audit"
    _seed_stress(temp_db, vid, "slippage_x2", "success")
    _evidence(temp_db, "other_run")
    audit.register_backtest(_result("other_run"), role=audit.ROLE_OOS,
                            validation_id=vid, db_path=temp_db)
    result = audit_completeness(vid, db_path=temp_db)
    assert result["complete"] is False
    assert any("slippage_x2" in p and "未登记" in p
               for p in result["problems"])


def test_stress_insufficient_not_treated_as_failure(temp_db):
    """insufficient 是「执行成功但样本不足」，不是执行失败。"""
    _seed_validation(temp_db)
    vid = "val_audit"
    _seed_stress(temp_db, vid, "insufficient", "insufficient")
    _evidence(temp_db, "ins_run")
    audit.register_backtest(_result("ins_run"),
                            role=audit.ROLE_STRESS_INSUFFICIENT,
                            scenario_key="insufficient", validation_id=vid,
                            db_path=temp_db)
    result = audit_completeness(vid, db_path=temp_db)
    # 不该报「执行状态为 failed」
    assert not any("回测执行状态为 failed" in p for p in result["problems"])
    # 但仍因其他缺失项不完整
    assert result["complete"] is False


def test_stress_insufficient_on_wrong_scenario_incomplete(temp_db):
    """只有样本量类场景允许 insufficient。"""
    _seed_validation(temp_db)
    vid = "val_audit"
    _seed_stress(temp_db, vid, "cost_plus_50", "insufficient")
    _evidence(temp_db, "wrong_ins")
    audit.register_backtest(_result("wrong_ins"),
                            role=audit.ROLE_STRESS_COST,
                            scenario_key="cost_plus_50", validation_id=vid,
                            db_path=temp_db)
    result = audit_completeness(vid, db_path=temp_db)
    assert result["complete"] is False
    assert any("只有样本量类场景允许该状态" in p for p in result["problems"])
