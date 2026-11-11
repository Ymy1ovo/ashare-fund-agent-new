from __future__ import annotations

from types import SimpleNamespace

import app.database.db as db_module
import app.main as main_module
from fastapi.testclient import TestClient
from tests.conftest import make_pool_record


def _price(date: str, close: float) -> dict:
    return {
        "code": "510300",
        "trade_date": date,
        "open": close - 0.01,
        "high": close + 0.02,
        "low": close - 0.02,
        "close": close,
        "volume": 1000,
        "amount": 100000,
        "adjusted_close": close - 0.005,
        "adjustment_type": "qfq",
        "quality_status": "valid",
        "quality_notes": None,
        "source": "test",
        "collected_at": "2024-01-03T15:00:00",
    }


def test_api_summary_and_detail(temp_db, monkeypatch) -> None:
    monkeypatch.setattr(main_module, "settings", SimpleNamespace(database_path=temp_db))
    db_module.replace_etf_pool([make_pool_record()], db_path=temp_db)
    db_module.upsert_daily_prices([_price("2024-01-02", 1.0), _price("2024-01-03", 1.2)], db_path=temp_db)

    with TestClient(main_module.app) as client:
        summary = client.get("/api/market-data/summary")
        assert summary.status_code == 200
        payload = summary.json()
        assert payload["etf_total"] == 1
        assert payload["etf_ingested"] == 1
        assert payload["total_records"] == 2
        assert payload["coverage"][0]["start_date"] == "2024-01-02"
        assert payload["coverage"][0]["end_date"] == "2024-01-03"
        assert payload["adjustment"]["current_snapshot_etfs"] == 0
        assert payload["adjustment"]["mixed_snapshot_etfs"] == 0
        assert "adjustment_status" in payload["coverage"][0]

        detail = client.get(
            "/api/market-data/510300",
            params={"start_date": "2024-01-02", "end_date": "2024-01-03", "limit": 1, "offset": 1},
        )
        assert detail.status_code == 200
        body = detail.json()
        assert body["total"] == 2
        assert body["limit"] == 1
        assert body["offset"] == 1
        assert len(body["records"]) == 1
        assert body["records"][0]["trade_date"] == "2024-01-03"
        assert body["records"][0]["adjusted_close"] == 1.195
        assert "adjustment_snapshot_id" in body["records"][0]

        adjustment_runs = client.get("/api/adjustment/runs")
        assert adjustment_runs.status_code == 200
        assert adjustment_runs.json() == []


def test_api_rejects_bad_query(temp_db, monkeypatch) -> None:
    monkeypatch.setattr(main_module, "settings", SimpleNamespace(database_path=temp_db))
    db_module.replace_etf_pool([make_pool_record()], db_path=temp_db)
    with TestClient(main_module.app) as client:
        assert client.get("/api/market-data/abc").status_code == 400
        assert (
            client.get(
                "/api/market-data/510300",
                params={"start_date": "2024/01/01"},
            ).status_code
            == 400
        )
        assert (
            client.get(
                "/api/market-data/510300",
                params={"start_date": "2024-01-03", "end_date": "2024-01-02"},
            ).status_code
            == 400
        )
        assert client.get("/api/market-data/999999").status_code == 404
        assert client.get("/api/market-data/510300", params={"limit": 0}).status_code == 422
