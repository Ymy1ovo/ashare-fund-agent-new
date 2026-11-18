"""阶段3A.3.2.3.6.1：缺陷 A（明细落库）与缺陷 B（regime 凭证）回归测试。"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.backtest.corporate_actions import ACTION_CASH_DISTRIBUTION
from app.database.db import get_connection, init_db
from app.replay import registry
from app.replay.runner import effective_db_path, replay_backtest
from app.replay.registry import (
    REASON_MISSING_DETAILS,
    REASON_REGIME_INCOMPLETE,
    STATUS_SUCCESS,
    complete_supersession,
    find_success,
    list_supersessions,
    start_supersession,
    success_map,
)
from tests.test_corporate_actions import _insert_action, _seed


# ---------------------------------------------------------------- 缺陷 A

def _indicator_version() -> str:
    from app.validation.config import ValidationConfig

    return ValidationConfig().indicator_version


def _seed_market(db_path, *, n_days=80, code="510300"):
    """造一个能真跑出公司行为明细的市场库：行情 + 指标 + 分红事件。"""
    prices = {code: [10.0 + i * 0.05 for i in range(n_days)]}
    dates = _seed(db_path, prices)
    with get_connection(db_path) as conn:
        snapshot = conn.execute(
            "SELECT adjustment_snapshot_id FROM etf_daily_prices "
            "WHERE code=? LIMIT 1", (code,)).fetchone()[0]
        for day, close in zip(dates, prices[code]):
            conn.execute(
                "INSERT INTO etf_indicator_daily "
                "(etf_code, trade_date, adjustment_snapshot_id, "
                " calculation_version, run_id, adjusted_close, ma5, ma20, "
                " quality_status, created_at) "
                "VALUES (?, ?, ?, ?, 'fix-run', ?, ?, ?, 'valid', "
                "'2024-01-01T00:00:00')",
                (code, day, snapshot, _indicator_version(), close,
                 close - 0.5, close - 1.0),
            )
    _insert_action(
        db_path, code=code, action_type=ACTION_CASH_DISTRIBUTION,
        ex_date=dates[60], effective_date=dates[60],
        cash_per_share=0.2, record_date=dates[59], pay_date=dates[62],
    )
    return dates


def _insert_bh_source(db_path, run_id, *, start, end, code="510300"):
    """写一条 buy_and_hold 的历史源记录，参数全部 recorded。"""
    config = {
        "weights": {}, "start_date": start, "end_date": end,
        "initial_cash": 1_000_000.0, "execution_price": "open",
        "costs": {"commission_rate": 0.00025, "min_commission": 5.0,
                  "slippage_bps": 5.0, "slippage_fixed": 0.0,
                  "stamp_duty_rate": 0.0, "transfer_fee_rate": 0.0},
        "max_defer_days": 3, "risk_free_rate": 0.0, "annualization": 252,
        "rebalance_tolerance": 0.02, "cash_shortfall_policy": "reduce",
        "allow_partial_fill": False, "instrument_overrides": {},
        "lot_size_override": None,
    }
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO backtest_runs (run_id, strategy_name, strategy_version, "
            "config_json, initial_cash, start_date, end_date, etf_codes, "
            "indicator_version, snapshot_ids, input_hash, summary_json, created_at, "
            "accounting_version, evidence_version, run_scope) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, "buy_and_hold", "1.0.0", json.dumps(config), 1_000_000.0,
             start, end, json.dumps([code]), None, json.dumps({"510300": 1}),
             "hash_src", json.dumps({}), "2024-01-01T00:00:00",
             "legacy_corporate_action_accepting", "ca-evidence-v1", "standalone"),
        )


def _regime_fixture(temp_db, vid):
    """造一个 regime 可用的环境：280 天行情 + 指标 + validation 记录。

    OOS 从第 120 个交易日起，保证 MA20 预热足够、样本量过 MIN_REGIME_SAMPLES。
    """
    from app.backtest.strategies.ma_trend import MovingAverageTrendStrategy
    from app.validation import audit
    from app.validation.config import ValidationConfig
    from tests.test_replay_3a3_2_3_1 import _insert_validation

    # OOS 需超过 REGIME_MA_WINDOW(250) 个交易日，否则预热序列
    # 全部 unclassified、build_regime_series 直接抛 RegimeError。
    dates = _seed_market(temp_db, n_days=600)
    cfg = ValidationConfig(
        is_start=dates[0], is_end=dates[99],
        oos_start=dates[100], oos_end=dates[-1],
        ma_window_grid=(5,), pool_mode="representative",
        regime_ma_window=20,
    )
    _insert_validation(temp_db, vid,
                       is_start=cfg.is_start, is_end=cfg.is_end,
                       oos_start=cfg.oos_start, oos_end=cfg.oos_end,
                       grid=cfg.ma_window_grid)
    audit.init_audit_schema(temp_db)
    split = SimpleNamespace(oos_start=cfg.oos_start, oos_end=cfg.oos_end)
    oos_cfg = cfg.build_backtest_config(cfg.oos_start, cfg.oos_end)
    strategy = MovingAverageTrendStrategy(ma_window=5)
    return cfg, split, oos_cfg, strategy


def test_effective_db_path_defaults_to_settings():
    from app.config import settings

    assert effective_db_path(None) == settings.database_path


def test_effective_db_path_keeps_explicit(tmp_path):
    db = tmp_path / "x.db"
    assert effective_db_path(db) == db


def test_replay_backtest_writes_corporate_action_details(temp_db):
    """缺陷 A 回归：重放必须把公司行为应用与分红应收明细写进同一个库。"""
    dates = _seed_market(temp_db)
    _insert_bh_source(temp_db, "src_bh_1", start=dates[0], end=dates[-1])

    out = replay_backtest("src_bh_1", db_path=temp_db)
    assert out.status == STATUS_SUCCESS, out.reason

    with get_connection(temp_db) as conn:
        apps = conn.execute(
            "SELECT action_id, code, action_type, shares_before, shares_after, "
            "cash_delta FROM corporate_action_applications WHERE run_id=? "
            "ORDER BY action_id", (out.replay_id,)).fetchall()
        recvs = conn.execute(
            "SELECT action_id, code, ex_date, pay_date, shares_at_ex, "
            "cash_per_share, amount, status FROM dividend_receivables "
            "WHERE run_id=? ORDER BY action_id", (out.replay_id,)).fetchall()
        run = conn.execute(
            "SELECT run_id FROM backtest_runs WHERE run_id=?",
            (out.replay_id,)).fetchone()

    assert run is not None, "回测记录必须落库"
    assert len(apps) == 1, f"公司行为应用明细应为 1 条，实际 {len(apps)}"
    assert len(recvs) == 1, f"分红应收明细应为 1 条，实际 {len(recvs)}"
    assert apps[0]["cash_delta"] == pytest.approx(recvs[0]["amount"])
    assert recvs[0]["status"] == "settled"


def test_replay_backtest_details_not_cross_database(temp_db, tmp_path):
    """明细、记录、attempt 必须全在同一个库，不出现跨库写入。"""
    dates = _seed_market(temp_db)
    _insert_bh_source(temp_db, "src_bh_2", start=dates[0], end=dates[-1])

    other = tmp_path / "other.db"
    init_db(db_path=other)

    out = replay_backtest("src_bh_2", db_path=temp_db)
    assert out.status == STATUS_SUCCESS, out.reason

    with get_connection(temp_db) as conn:
        n_app = conn.execute(
            "SELECT COUNT(*) FROM corporate_action_applications WHERE run_id=?",
            (out.replay_id,)).fetchone()[0]
        n_att = conn.execute(
            "SELECT COUNT(*) FROM replay_attempts WHERE attempt_id=?",
            (out.attempt_id,)).fetchone()[0]
    with get_connection(other) as conn:
        other_app = conn.execute(
            "SELECT COUNT(*) FROM corporate_action_applications WHERE run_id=?",
            (out.replay_id,)).fetchone()[0] if conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
            "AND name='corporate_action_applications'").fetchone()[0] else 0

    assert n_app >= 1
    assert n_att == 1
    assert other_app == 0, "不得把明细写到另一个库"


# ---------------------------------------------------------------- 缺陷 B

def test_regime_registers_evidence_before_link(temp_db, monkeypatch):
    """缺陷 B 回归：register_run_evidence 必须先于 register_backtest。"""
    from app.validation import audit, runner as vrunner

    order: list[str] = []
    real_evidence = audit.register_run_evidence
    real_link = audit.register_backtest

    def spy_evidence(*a, **kw):
        order.append("evidence")
        return real_evidence(*a, **kw)

    def spy_link(*a, **kw):
        order.append("link")
        return real_link(*a, **kw)

    monkeypatch.setattr(audit, "register_run_evidence", spy_evidence)
    monkeypatch.setattr(audit, "register_backtest", spy_link)

    cfg, split, oos_cfg, strategy = _regime_fixture(temp_db, "val_regime_1")
    ctx, token = audit.bind("val_regime_1")
    try:
        payload = vrunner._build_regime_payload(
            cfg, split, oos_cfg, strategy, ["510300"], temp_db)
    finally:
        audit.reset(token)

    assert order[:2] == ["evidence", "link"], f"登记顺序错误：{order}"
    assert payload["labels_available"] is True, payload.get("error")

    with get_connection(temp_db) as conn:
        n_link = conn.execute(
            "SELECT COUNT(*) FROM validation_backtest_runs "
            "WHERE validation_id='val_regime_1' AND run_role='regime_grouping'"
        ).fetchone()[0]
        n_evidence = conn.execute(
            "SELECT COUNT(*) FROM backtest_runs WHERE run_scope='validation_internal'"
        ).fetchone()[0]
    assert n_link == 1, "regime_grouping 关联必须登记成功"
    assert n_evidence >= 1, "存在性凭证必须落库"


def test_regime_missing_validation_id_fails(temp_db):
    """没有 validation_id 时 regime 必须失败，不能返回正常统计。"""
    from app.validation import audit, runner as vrunner

    cfg, split, oos_cfg, strategy = _regime_fixture(temp_db, "val_unused")
    with pytest.raises(audit.AuditError):
        vrunner._build_regime_payload(
            cfg, split, oos_cfg, strategy, ["510300"], temp_db)


def test_regime_evidence_failure_propagates(temp_db, monkeypatch):
    """凭证登记失败必须向外抛，不能降级成 unavailable。"""
    from app.validation import audit, runner as vrunner

    def boom(*a, **kw):
        raise audit.AuditError("模拟凭证登记失败")

    monkeypatch.setattr(audit, "register_run_evidence", boom)

    cfg, split, oos_cfg, strategy = _regime_fixture(temp_db, "val_regime_2")
    ctx, token = audit.bind("val_regime_2")
    try:
        with pytest.raises(audit.AuditError):
            vrunner._build_regime_payload(
                cfg, split, oos_cfg, strategy, ["510300"], temp_db)
    finally:
        audit.reset(token)


def test_regime_link_failure_propagates(temp_db, monkeypatch):
    """关联登记失败同样必须向外抛。"""
    from app.validation import audit, runner as vrunner

    def boom(*a, **kw):
        raise audit.AuditError("模拟关联登记失败")

    monkeypatch.setattr(audit, "register_backtest", boom)

    cfg, split, oos_cfg, strategy = _regime_fixture(temp_db, "val_regime_3")
    ctx, token = audit.bind("val_regime_3")
    try:
        with pytest.raises(audit.AuditError):
            vrunner._build_regime_payload(
                cfg, split, oos_cfg, strategy, ["510300"], temp_db)
    finally:
        audit.reset(token)


def test_regime_stats_persisted_and_audit_passes(temp_db):
    """正常路径：regime 统计落库，audit_completeness 不再报 regime 缺失。"""
    from app.validation import audit, runner as vrunner

    cfg, split, oos_cfg, strategy = _regime_fixture(temp_db, "val_regime_4")
    ctx, token = audit.bind("val_regime_4")
    try:
        payload = vrunner._build_regime_payload(
            cfg, split, oos_cfg, strategy, ["510300"], temp_db)
    finally:
        audit.reset(token)

    assert payload["labels_available"] is True, payload.get("error")
    audit.save_regime_stats("val_regime_4", payload, db_path=temp_db)
    with get_connection(temp_db) as conn:
        statuses = [r[0] for r in conn.execute(
            "SELECT status FROM validation_regime_stats WHERE validation_id=?",
            ("val_regime_4",))]
    assert len(statuses) == 4
    assert any(x != "unavailable" for x in statuses), \
        f"regime 统计不得全部 unavailable：{statuses}"

    problems = audit.audit_completeness("val_regime_4", db_path=temp_db)["problems"]
    assert not any("regime_grouping" in p for p in problems), problems


# ---------------------------------------------------------------- 追加式失效

def test_supersession_marks_old_attempt_without_touching_it(temp_db):
    """失效标记是追加式的：旧 attempt 行原样保留，只新增关系记录。"""
    _seed_market(temp_db)
    _insert_bh_source(temp_db, "src_bh_3",
                      start="2024-01-02", end="2024-06-28")
    out = replay_backtest("src_bh_3", db_path=temp_db)
    assert out.status == STATUS_SUCCESS

    with get_connection(temp_db) as conn:
        before = dict(conn.execute(
            "SELECT * FROM replay_attempts WHERE attempt_id=?",
            (out.attempt_id,)).fetchone())

    sid = start_supersession(
        "backtest", "src_bh_3",
        superseded_attempt_id=out.attempt_id,
        reason=REASON_MISSING_DETAILS, db_path=temp_db)

    with get_connection(temp_db) as conn:
        after = dict(conn.execute(
            "SELECT * FROM replay_attempts WHERE attempt_id=?",
            (out.attempt_id,)).fetchone())

    assert before == after, "旧 attempt 任何字段都不得被修改"
    assert after["status"] == STATUS_SUCCESS, "原执行状态必须保留"

    rows = list_supersessions("backtest", db_path=temp_db)
    assert len(rows) == 1
    assert rows[0]["supersession_id"] == sid
    assert rows[0]["superseded_record_id"] == out.replay_id
    assert rows[0]["reason"] == REASON_MISSING_DETAILS
    assert rows[0]["replacement_attempt_id"] is None


def test_superseded_attempt_not_counted_as_success(temp_db):
    """被取代的旧结果不得再算成功重放。"""
    _seed_market(temp_db)
    _insert_bh_source(temp_db, "src_bh_4",
                      start="2024-01-02", end="2024-06-28")
    out = replay_backtest("src_bh_4", db_path=temp_db)
    assert find_success("backtest", "src_bh_4", temp_db) == out.replay_id

    start_supersession("backtest", "src_bh_4",
                       superseded_attempt_id=out.attempt_id,
                       reason=REASON_MISSING_DETAILS, db_path=temp_db)

    assert find_success("backtest", "src_bh_4", temp_db) is None
    assert "src_bh_4" not in success_map("backtest", temp_db)


def test_superseded_replay_can_run_again_without_force(temp_db):
    """旧结果被取代后，重新执行不需要 force。"""
    dates = _seed_market(temp_db)
    _insert_bh_source(temp_db, "src_bh_5", start=dates[0], end=dates[-1])
    first = replay_backtest("src_bh_5", db_path=temp_db)
    assert first.status == STATUS_SUCCESS

    start_supersession("backtest", "src_bh_5",
                       superseded_attempt_id=first.attempt_id,
                       reason=REASON_MISSING_DETAILS, db_path=temp_db)

    second = replay_backtest("src_bh_5", db_path=temp_db)
    assert second.status == STATUS_SUCCESS, second.reason
    assert second.attempt_id != first.attempt_id
    assert second.replay_id != first.replay_id

    rows = list_supersessions("backtest", db_path=temp_db)
    assert rows[0]["replacement_attempt_id"] == second.attempt_id
    assert rows[0]["replacement_record_id"] == second.replay_id
    assert rows[0]["completed_at"] is not None


def test_supersession_idempotent(temp_db):
    """同一 attempt 重复标记返回同一个 supersession_id，不产生重复关系。"""
    _seed_market(temp_db)
    _insert_bh_source(temp_db, "src_bh_6",
                      start="2024-01-02", end="2024-06-28")
    out = replay_backtest("src_bh_6", db_path=temp_db)

    a = start_supersession("backtest", "src_bh_6",
                           superseded_attempt_id=out.attempt_id,
                           reason=REASON_MISSING_DETAILS, db_path=temp_db)
    b = start_supersession("backtest", "src_bh_6",
                           superseded_attempt_id=out.attempt_id,
                           reason=REASON_MISSING_DETAILS, db_path=temp_db)
    assert a == b
    assert len(list_supersessions(db_path=temp_db)) == 1


def test_both_reasons_recorded_for_validation(temp_db):
    """validation 用 regime_audit_incomplete 作为失效原因。"""
    assert REASON_REGIME_INCOMPLETE == "regime_audit_incomplete"
    assert REASON_MISSING_DETAILS == "missing_corporate_action_details"
