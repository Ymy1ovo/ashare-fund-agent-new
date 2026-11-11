from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.database.db import get_connection, replace_etf_pool
from app.main import app
from tests.conftest import make_pool_record


def _seed(temp_db):
    replace_etf_pool([make_pool_record("510300", "沪深300ETF"), make_pool_record("510500", "中证500ETF")], db_path=temp_db)
    with get_connection(temp_db) as conn:
        conn.execute(
            "INSERT INTO adjustment_runs (started_at, status, total_codes, success_codes) "
            "VALUES ('2024-01-01T00:00:00', 'success', 2, 2)"
        )
        run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for code in ("510300", "510500"):
            conn.execute(
                "INSERT INTO etf_adjustment_snapshots "
                "(run_id, code, status, collected_at, source, coverage_start, coverage_end, "
                "matched_start, matched_end, raw_rows, qfq_rows, matched_rows, missing_rows, is_current, created_at) "
                "VALUES (?, ?, 'success', '2024-01-01T00:00:00', 'test', '2024-01-02', '2024-01-03', "
                "'2024-01-02', '2024-01-03', 2, 2, 2, 0, 1, '2024-01-01T00:00:00')",
                (run_id, code),
            )
            snapshot = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                "INSERT INTO indicator_runs "
                "(run_id, etf_code, start_date, end_date, indicator_config, adjustment_snapshot_id, status, "
                "valid_rows, missing_rows, calculation_version, summary_json, quality_json, created_at) "
                "VALUES (?, ?, '2024-01-02', '2024-01-03', ?, ?, 'success', 2, 0, 'vtest', ?, ?, '2024-01-03T00:00:00')",
                (
                    f"run-{code}",
                    code,
                    json.dumps({"enabled": ["returns"], "risk_free_rate": 0.0}),
                    snapshot,
                    json.dumps({"interval_return": 0.1, "cagr": 0.1}),
                    json.dumps({"issues": [], "coverage": {"return_1d": {"valid_rows": 1, "total_rows": 2, "coverage": 0.5}}}),
                ),
            )
            for index, (day, value) in enumerate((("2024-01-02", None), ("2024-01-03", 0.1))):
                conn.execute(
                    "INSERT INTO etf_indicator_daily "
                    "(etf_code, trade_date, adjustment_snapshot_id, calculation_version, run_id, adjusted_close, "
                    "return_1d, return_20d, ma20, rsi6, quality_status, quality_reasons, created_at) "
                    "VALUES (?, ?, ?, 'vtest', ?, 10.0, ?, ?, 10.0, 50.0, 'valid', NULL, '2024-01-03T00:00:00')",
                    (code, day, snapshot, f"run-{code}", value, 0.2),
                )


def test_indicator_detail_and_errors(temp_db) -> None:
    _seed(temp_db)
    client = TestClient(app)
    response = client.get("/api/indicators/510300?indicators=return_1d,ma20")
    assert response.status_code == 200
    payload = response.json()
    assert payload["etf_code"] == "510300"
    assert payload["version"] == "vtest"
    assert payload["stale"] is False
    assert payload["total"] == 2
    assert set(payload["data"][0]) >= {"trade_date", "return_1d", "ma20", "quality_status"}
    assert payload["data"][1]["return_1d"] == 0.1

    assert client.get("/api/indicators/510300?start_date=bad").status_code == 400
    assert client.get("/api/indicators/510300?indicators=no_such").status_code == 400
    assert client.get("/api/indicators/999999").status_code == 404
    assert client.get("/api/indicators/510300?version=nope").status_code == 404
    assert client.get("/api/indicators/510300/latest").status_code == 200

    with get_connection(temp_db) as conn:
        old = conn.execute(
            "SELECT id FROM etf_adjustment_snapshots WHERE code='510300' AND is_current=1"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO etf_adjustment_snapshots "
            "(run_id, code, status, collected_at, source, coverage_start, coverage_end, "
            "matched_start, matched_end, raw_rows, qfq_rows, matched_rows, missing_rows, is_current, created_at) "
            "VALUES (1, '510300', 'success', '2024-01-04T00:00:00', 'test', '2024-01-02', '2024-01-03', "
            "'2024-01-02', '2024-01-03', 2, 2, 2, 0, 0, '2024-01-04T00:00:00')"
        )
        new = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("UPDATE etf_adjustment_snapshots SET is_current=0 WHERE id=?", (old,))
        conn.execute("UPDATE etf_adjustment_snapshots SET is_current=1 WHERE id=?", (new,))
    stale = client.get("/api/indicators/510300").json()
    assert stale["stale"] is True
    assert stale["snapshot_is_current"] is False


def test_indicator_overview_and_ranking(temp_db) -> None:
    _seed(temp_db)
    client = TestClient(app)
    overview = client.get("/api/indicators/overview")
    assert overview.status_code == 200
    assert overview.json()["total"] == 2
    ranking = client.get("/api/indicators/ranking?metric=return_20d&limit=1")
    assert ranking.status_code == 200
    assert ranking.json()["items"][0]["etf_code"] in {"510300", "510500"}
    assert "不构成投资建议" in ranking.json()["disclaimer"]
    assert client.get("/api/indicators/ranking?metric=no_such").status_code == 400
