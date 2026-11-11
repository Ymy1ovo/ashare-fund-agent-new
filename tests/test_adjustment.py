from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from app.data.processors.adjustment import refresh_adjusted_prices
from app.data.processors.ingest import run_ingest
from app.database.db import (
    count_prices_for_code,
    get_adjustment_summary,
    get_current_adjustment_snapshot,
    get_market_prices,
    replace_etf_pool,
    upsert_raw_daily_prices,
)
from tests.conftest import make_pool_record


def _raw_row(code: str, trade_date: str, close: float) -> dict:
    return {
        "code": code,
        "trade_date": trade_date,
        "open": close - 0.01,
        "high": close + 0.02,
        "low": close - 0.02,
        "close": close,
        "volume": 1000,
        "amount": 100000,
        "quality_status": "valid",
        "quality_notes": None,
        "source": "test-raw",
        "collected_at": "2026-11-09T15:00:00",
    }


def _qfq_frame(rows: list[tuple[str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "日期": [row[0] for row in rows],
            "开盘": [row[1] - 0.01 for row in rows],
            "最高": [row[1] + 0.02 for row in rows],
            "最低": [row[1] - 0.02 for row in rows],
            "收盘": [row[1] for row in rows],
            "成交量": [1000] * len(rows),
            "成交额": [100000] * len(rows),
        }
    )


class FakeQfqProvider:
    def __init__(self, frames: dict[str, pd.DataFrame], fail: set[str] | None = None) -> None:
        self.frames = frames
        self.fail = fail or set()

    def fetch_qfq_history(self, code, start_date, end_date):
        if code in self.fail:
            raise RuntimeError("fake qfq failure")
        return self.frames.get(code, pd.DataFrame()).copy()


class FakeRawProvider:
    def __init__(self, frames: dict[str, pd.DataFrame], fail: set[str] | None = None) -> None:
        self.frames = frames
        self.fail = fail or set()

    def fetch_history(self, code, start_date, end_date, adjust=""):
        if code in self.fail:
            raise RuntimeError("fake raw failure")
        return self.frames.get(code, pd.DataFrame()).copy()


def _seed(codes: list[str], rows: list[dict]) -> None:
    replace_etf_pool([make_pool_record(code, f"ETF{code}") for code in codes])
    upsert_raw_daily_prices(rows)


def test_full_refresh_updates_adjusted_and_keeps_raw_ohlc(temp_db) -> None:
    _seed(
        ["510300"],
        [_raw_row("510300", "2024-01-02", 1.0), _raw_row("510300", "2024-01-03", 1.1)],
    )
    before = get_market_prices("510300")
    provider = FakeQfqProvider({"510300": _qfq_frame([("2024-01-02", 0.9), ("2024-01-03", 1.0)])})
    result = refresh_adjusted_prices(["510300"], provider, today=date(2024, 1, 4))
    assert result.status == "success"
    assert result.success_codes == 1

    after = get_market_prices("510300")
    assert len(after) == 2
    for old, new in zip(before, after):
        assert (old["open"], old["high"], old["low"], old["close"]) == (
            new["open"],
            new["high"],
            new["low"],
            new["close"],
        )
    assert [row["adjusted_close"] for row in after] == [0.9, 1.0]
    assert len({row["adjustment_snapshot_id"] for row in after}) == 1
    snapshot = get_current_adjustment_snapshot("510300")
    assert snapshot is not None and snapshot["status"] == "success"
    assert snapshot["collected_at"] == after[0]["adjustment_collected_at"]
    assert snapshot["coverage_start"] == "2024-01-02"
    assert snapshot["coverage_end"] == "2024-01-03"


def test_refresh_uses_new_basis_and_retires_old_snapshot(temp_db) -> None:
    _seed(["510300"], [_raw_row("510300", "2024-01-02", 1.0), _raw_row("510300", "2024-01-03", 1.1)])
    first = refresh_adjusted_prices(
        ["510300"],
        FakeQfqProvider({"510300": _qfq_frame([("2024-01-02", 0.9), ("2024-01-03", 1.0)])}),
        today=date(2024, 1, 4),
    )
    old_snapshot_id = get_current_adjustment_snapshot("510300")["id"]
    second = refresh_adjusted_prices(
        ["510300"],
        FakeQfqProvider({"510300": _qfq_frame([("2024-01-02", 0.7), ("2024-01-03", 0.8)])}),
        today=date(2024, 1, 4),
    )
    assert second.run_id != first.run_id
    current = get_current_adjustment_snapshot("510300")
    assert current["id"] != old_snapshot_id
    rows = get_market_prices("510300")
    assert [row["adjusted_close"] for row in rows] == [0.7, 0.8]
    assert {row["adjustment_snapshot_id"] for row in rows} == {current["id"]}


def test_refresh_failure_and_empty_preserve_old_snapshot(temp_db) -> None:
    _seed(["510300"], [_raw_row("510300", "2024-01-02", 1.0), _raw_row("510300", "2024-01-03", 1.1)])
    first = refresh_adjusted_prices(
        ["510300"],
        FakeQfqProvider({"510300": _qfq_frame([("2024-01-02", 0.9), ("2024-01-03", 1.0)])}),
        today=date(2024, 1, 4),
    )
    assert first.status == "success"
    old = get_current_adjustment_snapshot("510300")
    before = get_market_prices("510300")

    failed = refresh_adjusted_prices(
        ["510300"], FakeQfqProvider({}, fail={"510300"}), today=date(2024, 1, 4)
    )
    assert failed.failed_codes == 1
    assert get_current_adjustment_snapshot("510300")["id"] == old["id"]
    assert get_market_prices("510300") == before

    empty = refresh_adjusted_prices(
        ["510300"], FakeQfqProvider({"510300": pd.DataFrame()}), today=date(2024, 1, 4)
    )
    assert empty.empty_codes == 1
    assert get_current_adjustment_snapshot("510300")["id"] == old["id"]
    assert get_market_prices("510300") == before


def test_partial_refresh_is_isolated_and_marks_missing(temp_db) -> None:
    _seed(
        ["510300", "510301"],
        [
            _raw_row("510300", "2024-01-02", 1.0),
            _raw_row("510300", "2024-01-03", 1.1),
            _raw_row("510301", "2024-01-02", 2.0),
        ],
    )
    provider = FakeQfqProvider(
        {
            "510300": _qfq_frame([("2024-01-02", 0.9)]),
            "510301": _qfq_frame([("2024-01-02", 1.8)]),
        }
    )
    result = refresh_adjusted_prices(["510300", "510301"], provider, today=date(2024, 1, 4))
    assert result.partial_codes == 1
    assert result.success_codes == 1

    rows = get_market_prices("510300")
    assert rows[0]["adjusted_close"] == 0.9
    assert rows[1]["adjusted_close"] is None
    assert len({row["adjustment_snapshot_id"] for row in rows}) == 1
    assert rows[1]["adjustment_snapshot_id"] == rows[0]["adjustment_snapshot_id"]
    snap = get_current_adjustment_snapshot("510300")
    assert snap["status"] == "partial"
    assert snap["missing_rows"] == 1


def test_refresh_is_repeatable_without_duplicate_prices(temp_db) -> None:
    _seed(["510300"], [_raw_row("510300", "2024-01-02", 1.0), _raw_row("510300", "2024-01-03", 1.1)])
    provider = FakeQfqProvider({"510300": _qfq_frame([("2024-01-02", 0.9), ("2024-01-03", 1.0)])})
    refresh_adjusted_prices(["510300"], provider, today=date(2024, 1, 4))
    refresh_adjusted_prices(["510300"], provider, today=date(2024, 1, 4))
    assert count_prices_for_code("510300") == 2
    assert get_adjustment_summary()["mixed_snapshot_etfs"] == 0


def test_raw_sync_does_not_touch_adjusted_fields(temp_db) -> None:
    _seed(["510300"], [_raw_row("510300", "2024-01-02", 1.0)])
    refresh_adjusted_prices(
        ["510300"],
        FakeQfqProvider({"510300": _qfq_frame([("2024-01-02", 0.9)])}),
        today=date(2024, 1, 3),
    )
    old = get_market_prices("510300")[0]

    raw_frame = pd.DataFrame(
        {
            "日期": ["2024-01-02", "2024-01-03"],
            "开盘": [0.99, 1.09],
            "最高": [1.02, 1.12],
            "最低": [0.98, 1.08],
            "收盘": [1.0, 1.1],
            "成交量": [1000, 1000],
            "成交额": [100000, 100000],
        }
    )
    result = run_ingest(
        ["510300"],
        FakeRawProvider({"510300": raw_frame}),
        mode="sync",
        today=date(2024, 1, 4),
    )
    assert result.success_codes == 1
    rows = get_market_prices("510300")
    assert rows[0]["adjusted_close"] == old["adjusted_close"]
    assert rows[0]["adjustment_snapshot_id"] == old["adjustment_snapshot_id"]
    assert rows[1]["adjusted_close"] is None
    assert rows[1]["adjustment_snapshot_id"] is None
