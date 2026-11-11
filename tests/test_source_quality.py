from __future__ import annotations

from datetime import date

import pandas as pd

from app.data.validators.source_quality import assess_quality


def test_quality_passes_clean_series() -> None:
    df = pd.DataFrame({"日期": ["2024-01-02", "2024-01-03"], "收盘": [1.0, 1.1]})
    status, issues = assess_quality(
        df, date_column="日期", price_column="收盘", time_series=True, today=date(2024, 1, 4)
    )
    assert status == "passed"
    assert issues == []


def test_quality_detects_duplicate_and_future_dates() -> None:
    df = pd.DataFrame(
        {"日期": ["2024-01-02", "2024-01-02", "2099-01-01"], "收盘": [1.0, 1.1, 2.0]}
    )
    status, issues = assess_quality(
        df, date_column="日期", price_column="收盘", time_series=True, today=date(2024, 1, 4)
    )
    assert status == "failed"
    assert any("duplicate_dates" in issue for issue in issues)
    assert any("future_dates" in issue for issue in issues)


def test_quality_detects_invalid_price_and_stale() -> None:
    df = pd.DataFrame({"日期": ["2024-01-02"], "收盘": [0.0]})
    status, issues = assess_quality(
        df, date_column="日期", price_column="收盘", time_series=True, today=date(2024, 2, 1)
    )
    assert status == "failed"  # 唯一价格也无效
    assert any("nonpositive" in issue for issue in issues)


def test_quality_small_invalid_ratio_is_warning() -> None:
    df = pd.DataFrame({"日期": ["2024-01-02", "2024-01-03"], "收盘": [1.0, 0.0]})
    status, issues = assess_quality(
        df, date_column="日期", price_column="收盘", time_series=True, today=date(2024, 1, 4)
    )
    assert status == "warning"
    assert any("nonpositive" in issue for issue in issues)


def test_quality_empty() -> None:
    status, issues = assess_quality(
        pd.DataFrame(), date_column="日期", price_column="收盘", time_series=True
    )
    assert status == "failed"
    assert issues == ["empty_dataframe"]
