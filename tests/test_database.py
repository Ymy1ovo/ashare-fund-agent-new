from __future__ import annotations

import sqlite3

import app.database.db as db_module


def test_init_db_creates_tables(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(db_module, "settings", type("S", (), {"database_path": db_path})())
    db_module.init_db(db_path=db_path)
    with sqlite3.connect(db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "data_source_tests",
        "etf_pool",
        "etf_daily_prices",
        "sync_runs",
        "sync_details",
        "adjustment_runs",
        "etf_adjustment_snapshots",
        "trade_calendar",
        "indicator_runs",
        "etf_indicator_daily",
    } <= tables
