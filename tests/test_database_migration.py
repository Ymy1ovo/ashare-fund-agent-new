from __future__ import annotations

import sqlite3

import app.database.db as db_module
from tests.conftest import make_pool_record


OLD_SCHEMA = """
CREATE TABLE data_source_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interface_name TEXT NOT NULL,
    function_name TEXT NOT NULL,
    params_json TEXT NOT NULL,
    status TEXT NOT NULL,
    row_count INTEGER,
    columns_json TEXT,
    start_date TEXT,
    end_date TEXT,
    error_message TEXT,
    tested_at TEXT NOT NULL
);
CREATE TABLE etf_pool (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    fund_type TEXT,
    tracking_index TEXT,
    established_date TEXT,
    listing_date TEXT,
    listing_date_source TEXT,
    last_trade_date TEXT,
    history_rows INTEGER,
    latest_price REAL,
    data_source TEXT NOT NULL,
    source_tested_at TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE etf_daily_prices (
    code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    amount REAL,
    source TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    PRIMARY KEY (code, trade_date)
);
"""


def _price(code: str = "510300", trade_date: str = "2024-01-02", close: float = 1.0) -> dict:
    return {
        "code": code,
        "trade_date": trade_date,
        "open": 1.0,
        "high": 1.1,
        "low": 0.9,
        "close": close,
        "volume": 100,
        "amount": 1000,
        "adjusted_close": None,
        "adjustment_type": "none",
        "quality_status": "valid",
        "quality_notes": None,
        "source": "test",
        "collected_at": "2024-01-03T15:00:00",
    }


def test_migrate_old_schema_preserves_data(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "old.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(OLD_SCHEMA)
        conn.execute(
            "INSERT INTO data_source_tests "
            "(interface_name, function_name, params_json, status, row_count, columns_json, tested_at) "
            "VALUES ('old', 'old_fn', '{}', 'success', 1, '[]', '2024-01-01T00:00:00')"
        )
        conn.execute(
            "INSERT INTO etf_daily_prices "
            "(code, trade_date, open, high, low, close, volume, amount, source, collected_at) "
            "VALUES ('510300', '2024-01-02', 1, 1, 1, 1, 100, 1000, 'old', '2024-01-02T15:00:00')"
        )

    monkeypatch.setattr(db_module, "settings", type("S", (), {"database_path": db_path})())
    db_module.init_db(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        test_cols = {row[1] for row in conn.execute("PRAGMA table_info(data_source_tests)")}
        price_cols = {row[1] for row in conn.execute("PRAGMA table_info(etf_daily_prices)")}
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"quality_status", "quality_issues_json"} <= test_cols
        assert {
            "adjusted_close",
            "adjustment_type",
            "adjustment_snapshot_id",
            "adjustment_collected_at",
            "adjustment_source",
            "adjustment_coverage_start",
            "adjustment_coverage_end",
            "quality_status",
            "quality_notes",
        } <= price_cols
        assert {
            "adjustment_runs",
            "etf_adjustment_snapshots",
            "trade_calendar",
            "indicator_runs",
            "etf_indicator_daily",
        } <= tables
        assert conn.execute("SELECT COUNT(*) FROM data_source_tests").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM etf_daily_prices").fetchone()[0] == 1
        old_quality = conn.execute("SELECT quality_status FROM data_source_tests").fetchone()[0]
        assert old_quality == "legacy"


def test_upsert_is_idempotent_and_preserves_existing_adjusted(temp_db) -> None:
    db_module.replace_etf_pool([make_pool_record()], db_path=temp_db)
    db_module.upsert_daily_prices([_price(close=1.0)], db_path=temp_db)
    db_module.upsert_daily_prices([_price(close=1.0)], db_path=temp_db)
    assert db_module.count_prices_for_code("510300", db_path=temp_db) == 1

    adjusted_row = _price(trade_date="2024-01-03", close=1.2)
    adjusted_row["adjusted_close"] = 1.1
    db_module.upsert_daily_prices([adjusted_row], db_path=temp_db)
    # 空 adjusted_close 不应覆盖已存在的复权价。
    db_module.upsert_daily_prices([adjusted_row | {"adjusted_close": None}], db_path=temp_db)

    rows = db_module.get_market_prices("510300", db_path=temp_db)
    assert len(rows) == 2
    assert rows[-1]["close"] == 1.2
    assert rows[-1]["adjusted_close"] == 1.1


def test_empty_upsert_does_not_delete(temp_db) -> None:
    db_module.upsert_daily_prices([_price()], db_path=temp_db)
    assert db_module.upsert_daily_prices([], db_path=temp_db) == 0
    assert db_module.count_prices_for_code("510300", db_path=temp_db) == 1
