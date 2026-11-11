from __future__ import annotations

from datetime import date

import pandas as pd

from app.data.processors.market_data import latest_record, prepare_history


def _raw(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_prepare_history_sorts_and_merges_adjusted() -> None:
    raw = _raw(
        [
            {"日期": "2024-01-03", "开盘": 1.0, "最高": 1.2, "最低": 0.9, "收盘": 1.1, "成交量": 10, "成交额": 11},
            {"日期": "2024-01-02", "开盘": 0.9, "最高": 1.0, "最低": 0.8, "收盘": 0.95, "成交量": 9, "成交额": 9},
            {"日期": "bad-date", "开盘": 1, "最高": 1, "最低": 1, "收盘": 1, "成交量": 1, "成交额": 1},
            {"日期": "2024-01-04", "开盘": 1.1, "最高": 1.2, "最低": 1.0, "收盘": -1, "成交量": 1, "成交额": 1},
        ]
    )
    qfq = _raw(
        [
            {"日期": "2024-01-03", "收盘": 1.05},
            {"日期": "2024-01-02", "收盘": 0.91},
        ]
    )
    prepared = prepare_history(
        "510300",
        raw,
        qfq,
        source="test",
        collected_at="2024-01-04T15:00:00",
        today=date(2024, 1, 5),
    )
    assert prepared.data["trade_date"].is_monotonic_increasing
    assert len(prepared.data) == 2
    assert prepared.data.iloc[-1]["close"] == 1.1
    assert prepared.data.iloc[-1]["adjusted_close"] == 1.05
    assert prepared.quality_status in {"warning", "suspect"}


def test_ohlc_anomaly_is_marked_but_not_fixed() -> None:
    raw = _raw(
        [
            {"日期": "2024-01-02", "开盘": 1.0, "最高": 0.8, "最低": 1.1, "收盘": 1.0, "成交量": 1, "成交额": 1},
        ]
    )
    prepared = prepare_history(
        "510300", raw, None, source="test", collected_at="2024-01-03T15:00:00", today=date(2024, 1, 3)
    )
    assert prepared.quality_status == "suspect"
    assert prepared.data.iloc[0]["quality_status"] == "suspect"
    assert prepared.data.iloc[0]["high"] == 0.8
    assert prepared.data.iloc[0]["low"] == 1.1


def test_latest_record_uses_same_valid_row() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2024-01-03", "2024-01-05", "2024-01-04"]),
            "close": [1.0, 1.5, 0.0],
        }
    )
    assert latest_record(frame) == ("2024-01-05", 1.5)


def test_empty_raw_produces_failed() -> None:
    prepared = prepare_history(
        "510300", pd.DataFrame(), None, source="test", collected_at="2024-01-03T15:00:00"
    )
    assert prepared.quality_status == "failed"
    assert prepared.data.empty
