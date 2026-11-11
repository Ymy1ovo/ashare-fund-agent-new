from __future__ import annotations

from datetime import date

import pandas as pd

from app.data.processors.normalize import (
    clean_history,
    first_trade_date,
    json_safe,
    latest_trade_date,
    latest_valid_bar,
    normalize_code,
    normalize_history,
    parse_date,
)


def test_normalize_code() -> None:
    assert normalize_code("510300") == "510300"
    assert normalize_code("sh510300") == "510300"
    assert normalize_code(510300) == "510300"
    assert normalize_code("510300.0") == "510300"
    assert normalize_code("") == ""


def test_parse_date_variants() -> None:
    assert parse_date("2024-01-02") == date(2024, 1, 2)
    assert parse_date("2024年01月02日") == date(2024, 1, 2)
    assert parse_date("20240102") == date(2024, 1, 2)
    assert parse_date(pd.Timestamp("2024-01-02")) == date(2024, 1, 2)
    assert parse_date("") is None
    assert parse_date("not-a-date") is None


def test_normalize_history() -> None:
    raw = pd.DataFrame(
        {
            "日期": ["2024-01-03", "2024-01-02"],
            "开盘": ["1.0", "0.9"],
            "收盘": ["1.1", "1.0"],
            "最高": ["1.2", "1.1"],
            "最低": ["0.9", "0.8"],
            "成交量": ["100", "90"],
            "成交额": ["110", "100"],
        }
    )
    normalized = normalize_history(raw)
    assert list(normalized.columns) == ["trade_date", "open", "high", "low", "close", "volume", "amount"]
    assert normalized["trade_date"].is_monotonic_increasing
    assert normalized.iloc[0]["close"] == 1.0


def test_date_helpers() -> None:
    df = pd.DataFrame({"日期": ["2024-01-03", "2024-01-02", "bad"]})
    assert first_trade_date(df) == date(2024, 1, 2)
    assert latest_trade_date(df) == date(2024, 1, 3)


def test_latest_valid_bar_ignores_unsorted_and_invalid_tail() -> None:
    raw = pd.DataFrame(
        {
            "日期": ["2024-01-05", "2024-01-04", "2024-01-03", "bad", "2099-01-01"],
            "收盘": [1.5, 0.0, 1.3, 9.9, 8.8],
        }
    )
    assert latest_valid_bar(raw, today=date(2024, 1, 6)) == (date(2024, 1, 5), 1.5)


def test_latest_valid_bar_uses_corresponding_sorted_row() -> None:
    raw = pd.DataFrame(
        {
            "日期": ["2024-01-04", "2024-01-05", "2024-01-03"],
            "收盘": [4.0, 5.0, 3.0],
        }
    )
    assert latest_valid_bar(raw, today=date(2024, 1, 6)) == (date(2024, 1, 5), 5.0)


def test_clean_history_counts_filtered_rows() -> None:
    raw = pd.DataFrame(
        {
            "日期": ["2024-01-03", "2024-01-03", "bad", "2024-01-02", "2099-01-01"],
            "收盘": [1.1, 1.2, 1.0, -1.0, 9.9],
            "开盘": [1, 1, 1, 1, 1],
            "最高": [1.3, 1.3, 1.3, 1.3, 1.3],
            "最低": [0.9, 0.9, 0.9, 0.9, 0.9],
            "成交量": [1, 1, 1, 1, 1],
            "成交额": [1, 1, 1, 1, 1],
        }
    )
    cleaned = clean_history(raw, today=date(2024, 1, 4))
    assert len(cleaned.data) == 1
    assert cleaned.invalid_date_rows == 1
    assert cleaned.invalid_close_rows == 1
    assert cleaned.future_rows == 1
    assert cleaned.duplicate_rows == 1
    assert cleaned.duplicate_conflict_rows == 1


def test_json_safe() -> None:
    assert json_safe(float("nan")) is None
    assert json_safe(pd.Timestamp("2024-01-02")) == "2024-01-02T00:00:00"
