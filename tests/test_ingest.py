from __future__ import annotations

from datetime import date

import pandas as pd

from app.data.processors.ingest import run_ingest
from app.database.db import (
    count_prices_for_code,
    get_latest_trade_date,
    get_market_prices,
    get_sync_details,
    replace_etf_pool,
)
from tests.conftest import make_pool_record


def _frame(rows: list[tuple[str, float]], adjust: str = "") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "日期": [row[0] for row in rows],
            "开盘": [row[1] * (0.9 if adjust else 1.0) for row in rows],
            "最高": [row[1] * 1.05 for row in rows],
            "最低": [row[1] * 0.95 for row in rows],
            "收盘": [row[1] * (0.9 if adjust else 1.0) for row in rows],
            "成交量": [100] * len(rows),
            "成交额": [1000] * len(rows),
        }
    )


class FakeProvider:
    def __init__(self, data: dict[str, list[tuple[str, float]]], fail: set[str] | None = None) -> None:
        self.data = data
        self.fail = fail or set()

    def fetch_history(self, code, start_date, end_date, adjust=""):
        if code in self.fail:
            raise RuntimeError("fake source failure")
        rows = self.data.get(code, [])
        return _frame(rows, adjust=adjust)


def _seed_pool(temp_db, codes: list[str]) -> None:
    replace_etf_pool([make_pool_record(code, f"ETF{code}") for code in codes], db_path=temp_db)


def test_failure_isolation_and_empty_protection(temp_db) -> None:
    _seed_pool(temp_db, ["510300", "510301", "510302"])
    provider = FakeProvider(
        {
            "510300": [("2024-01-02", 1.0), ("2024-01-03", 1.1)],
            "510301": [],
            "510302": [("2024-01-02", 2.0)],
        },
        fail={"510302"},
    )
    result = run_ingest(
        ["510300", "510301", "510302"],
        provider,
        mode="full",
        db_path=temp_db,
        today=date(2024, 1, 4),
    )
    assert result.status == "partial"
    assert result.success_codes == 1
    assert result.empty_codes == 1
    assert result.failed_codes == 1
    assert count_prices_for_code("510300", db_path=temp_db) == 2
    assert count_prices_for_code("510301", db_path=temp_db) == 0
    assert count_prices_for_code("510302", db_path=temp_db) == 0
    details = get_sync_details(result.run_id, db_path=temp_db)
    assert {row["status"] for row in details} == {"success", "empty", "failed"}


def test_incremental_sync_appends_without_duplicates(temp_db) -> None:
    _seed_pool(temp_db, ["510300"])
    first = FakeProvider({"510300": [("2024-01-02", 1.0)]})
    result1 = run_ingest(
        ["510300"], first, mode="full", db_path=temp_db, today=date(2024, 1, 4)
    )
    assert result1.success_codes == 1
    assert count_prices_for_code("510300", db_path=temp_db) == 1

    second = FakeProvider({"510300": [("2024-01-02", 1.0), ("2024-01-03", 1.1)]})
    result2 = run_ingest(
        ["510300"], second, mode="sync", db_path=temp_db, today=date(2024, 1, 4)
    )
    assert result2.success_codes == 1
    assert count_prices_for_code("510300", db_path=temp_db) == 2
    assert get_latest_trade_date("510300", db_path=temp_db) == "2024-01-03"
    assert len(get_market_prices("510300", db_path=temp_db)) == 2


def test_empty_sync_does_not_overwrite_existing(temp_db) -> None:
    _seed_pool(temp_db, ["510300"])
    run_ingest(
        ["510300"],
        FakeProvider({"510300": [("2024-01-02", 1.0), ("2024-01-03", 1.1)]}),
        mode="full",
        db_path=temp_db,
        today=date(2024, 1, 4),
    )
    before = get_market_prices("510300", db_path=temp_db)
    result = run_ingest(
        ["510300"],
        FakeProvider({"510300": []}),
        mode="sync",
        db_path=temp_db,
        today=date(2024, 1, 4),
    )
    after = get_market_prices("510300", db_path=temp_db)
    assert result.empty_codes == 1
    assert result.rows_written == 0
    assert before == after


def test_anomaly_rows_are_stored_with_suspect_status(temp_db) -> None:
    _seed_pool(temp_db, ["510300"])
    bad = pd.DataFrame(
        {
            "日期": ["2024-01-02"],
            "开盘": [1.0],
            "最高": [0.8],
            "最低": [1.1],
            "收盘": [1.0],
            "成交量": [100],
            "成交额": [1000],
        }
    )

    class OneFrameProvider:
        def fetch_history(self, code, start_date, end_date, adjust=""):
            return bad.copy()

    result = run_ingest(
        ["510300"], OneFrameProvider(), mode="full", db_path=temp_db, today=date(2024, 1, 3)
    )
    assert result.success_codes == 1
    rows = get_market_prices("510300", db_path=temp_db)
    assert rows[0]["quality_status"] == "suspect"
