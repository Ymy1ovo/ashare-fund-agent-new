"""阶段3A.3.2.3.4：审计查询 API 测试。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.validation import audit
from app.validation.audit import (
    ROLE_BENCHMARK, ROLE_OOS, init_audit_schema, save_regime_stats,
)
from app.validation.config import ValidationConfig
from tests.test_replay_3a3_2_3_1 import _insert_validation
from tests.test_validation_audit_3a3_2_3_4 import _result


client = TestClient(app)


def _seed(temp_db, vid="api_val"):
    cfg = ValidationConfig(is_start="2024-01-02", is_end="2024-01-05",
                           oos_start="2024-01-08", oos_end="2024-01-12",
                           ma_window_grid=(5, 20), pool_mode="representative")
    _insert_validation(temp_db, vid, grid=cfg.ma_window_grid,
                       config_hash=cfg.params_hash())
    init_audit_schema(temp_db)
    return vid


def test_audit_endpoint_404_for_unknown(temp_db):
    resp = client.get("/api/validations/no_such_val/audit")
    assert resp.status_code == 404
    assert "不存在" in resp.json()["detail"]


def test_backtest_runs_endpoint_404_for_unknown(temp_db):
    assert client.get("/api/validations/no_such_val/backtest-runs").status_code == 404


def test_regime_endpoint_404_for_unknown(temp_db):
    assert client.get("/api/validations/no_such_val/regime").status_code == 404


def test_audit_endpoint_returns_legacy_marker(temp_db):
    vid = _seed(temp_db)
    resp = client.get(f"/api/validations/{vid}/audit")
    assert resp.status_code == 200
    body = resp.json()
    assert body["audit_status"] == "unavailable_legacy"
    assert body["links"] == []


def test_audit_endpoint_returns_full_chain(temp_db):
    vid = _seed(temp_db)
    audit.register_run_evidence(_result("api_run_a"), db_path=temp_db)
    audit.register_backtest(_result("api_run_a"), role=ROLE_OOS,
                            validation_id=vid, db_path=temp_db)
    audit.register_run_evidence(_result("api_run_b"), db_path=temp_db)
    audit.register_backtest(_result("api_run_b"), role=ROLE_BENCHMARK,
                            validation_id=vid, db_path=temp_db)
    resp = client.get(f"/api/validations/{vid}/audit")
    assert resp.status_code == 200
    body = resp.json()
    # 只有 2 次回测，缺样本内/WF/压力，因此必须不完整
    assert body["audit_status"] == "incomplete"
    assert body["problems"], "不完整时必须给出具体原因"
    assert body["backtest_run_count"] == 2
    assert body["role_counts"][ROLE_OOS] == 1
    assert body["role_counts"][ROLE_BENCHMARK] == 1
    # 两条 run 都存在且被标记为真实存在
    assert all(link["run_exists"] for link in body["links"])


def test_backtest_runs_endpoint_lists_runs(temp_db):
    vid = _seed(temp_db)
    audit.register_run_evidence(_result("api_run_a"), db_path=temp_db)
    audit.register_backtest(_result("api_run_a"), role=ROLE_OOS,
                            validation_id=vid, db_path=temp_db)
    audit.register_run_evidence(_result("api_run_b"), db_path=temp_db)
    audit.register_backtest(_result("api_run_b"), role=ROLE_BENCHMARK,
                            validation_id=vid, db_path=temp_db)
    resp = client.get(f"/api/validations/{vid}/backtest-runs")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2
    assert {item["run_role"] for item in items} == {ROLE_OOS, ROLE_BENCHMARK}


def test_regime_endpoint_lists_stats(temp_db):
    vid = _seed(temp_db)
    save_regime_stats(vid, {
        "proxy_code": "510300", "min_samples": 20,
        "stats": {"bull": {"status": "ok", "total_days": 10, "valid_days": 9,
                           "missing_days": 1, "samples": 9,
                           "cumulative_return": 0.02},
                  "bear": {"status": "insufficient_sample", "total_days": 3,
                           "valid_days": 2, "missing_days": 1, "samples": 2,
                           "reason": "有效日收益 2 < 20"},
                  "range": {"status": "ok", "total_days": 20, "valid_days": 20,
                            "missing_days": 0, "samples": 20},
                  "unclassified": {"status": "ok", "total_days": 4,
                                   "valid_days": 4, "missing_days": 0,
                                   "samples": 4}},
    }, db_path=temp_db)
    resp = client.get(f"/api/validations/{vid}/regime")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 4
    assert {item["regime_label"] for item in items} == {
        "bull", "bear", "range", "unclassified"}
    bear = [i for i in items if i["regime_label"] == "bear"][0]
    assert bear["status"] == "insufficient_sample"
    assert bear["cumulative_return"] is None
