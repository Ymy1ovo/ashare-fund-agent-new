from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.quant.price_adjustment import (
    PriceDataError,
    SnapshotConsistencyError,
    adjust_prices,
)


def make_frame(**overrides):
    data = {
        "code": ["510300"] * 3,
        "trade_date": ["2024-01-02", "2024-01-03", "2024-01-04"],
        "open": [10.0, 10.5, 10.2],
        "high": [10.8, 10.9, 10.6],
        "low": [9.8, 10.1, 10.0],
        "close": [10.5, 10.7, 10.3],
        "volume": [1000.0, 0.0, None],
        "adjusted_close": [12.6, 12.84, 12.36],
        "adjustment_snapshot_id": [7, 7, 7],
    }
    data.update(overrides)
    return pd.DataFrame(data)


def test_normal_adjustment_preserves_raw_and_uses_one_factor() -> None:
    raw = make_frame()
    original = raw.copy(deep=True)
    result = adjust_prices(raw, today=date(2024, 1, 5))
    assert result.snapshot_id == 7
    assert result.valid_rows == 3
    assert result.invalid_rows == 0
    assert result.data["adjustment_factor"].tolist() == pytest.approx([1.2, 1.2, 1.2])
    assert result.data["adjusted_open"].tolist() == pytest.approx([12.0, 12.6, 12.24])
    assert result.data["adjusted_high"].tolist() == pytest.approx([12.96, 13.08, 12.72])
    assert result.data["adjusted_low"].tolist() == pytest.approx([11.76, 12.12, 12.0])
    assert result.data["adjusted_close"].tolist() == pytest.approx([12.6, 12.84, 12.36])
    assert result.zero_volume_rows == 1
    assert result.missing_volume_rows == 1
    assert result.data.loc[1, "trade_status"] == "zero_volume"
    assert result.data.loc[2, "trade_status"] == "missing_volume"
    pd.testing.assert_frame_equal(raw, original)


def test_ex_dividend_factor_changes_all_adjusted_ohlc() -> None:
    raw = make_frame(
        open=[10.0, 5.0, 5.1],
        high=[10.2, 5.2, 5.3],
        low=[9.9, 4.9, 5.0],
        close=[10.0, 5.0, 5.2],
        adjusted_close=[8.0, 4.0, 4.16],
        volume=[1000.0, 1000.0, 1000.0],
    )
    result = adjust_prices(raw, today=date(2024, 1, 5))
    assert result.data["adjustment_factor"].tolist() == pytest.approx([0.8, 0.8, 0.8])
    assert result.data["adjusted_close"].tolist() == pytest.approx([8.0, 4.0, 4.16])
    assert result.data["adjusted_open"].iloc[1] == pytest.approx(4.0)
    assert result.data["adjusted_high"].iloc[1] == pytest.approx(4.16)


def test_missing_adjusted_close_is_invalid_not_filled() -> None:
    raw = make_frame(adjusted_close=[12.6, None, 12.36])
    result = adjust_prices(raw, today=date(2024, 1, 5))
    assert result.data.loc[1, "price_status"] == "invalid"
    assert "adjusted_close_missing" in result.data.loc[1, "price_reasons"]
    assert np.isnan(result.data.loc[1, "adjusted_open"])
    assert result.valid_rows == 2


def test_raw_close_zero_and_invalid_factor_are_invalid() -> None:
    raw = make_frame(close=[0.0, 10.7, 10.3], adjusted_close=[12.6, np.inf, 12.36])
    result = adjust_prices(raw, today=date(2024, 1, 5))
    assert result.data.loc[0, "price_status"] == "invalid"
    assert result.data.loc[1, "price_status"] == "invalid"
    assert result.data.loc[2, "price_status"] == "valid"


def test_raw_ohlc_relation_anomaly_is_marked() -> None:
    raw = make_frame(high=[9.0, 10.9, 10.6])
    result = adjust_prices(raw, today=date(2024, 1, 5))
    assert result.data.loc[0, "price_status"] == "invalid"
    assert "raw_ohlc_invalid" in result.data.loc[0, "price_reasons"]


def test_snapshot_mix_is_rejected() -> None:
    raw = make_frame(adjustment_snapshot_id=[7, 8, 7])
    with pytest.raises(SnapshotConsistencyError):
        adjust_prices(raw, today=date(2024, 1, 5))


def test_missing_snapshot_is_rejected() -> None:
    raw = make_frame(adjustment_snapshot_id=[None, None, None])
    with pytest.raises(SnapshotConsistencyError):
        adjust_prices(raw, today=date(2024, 1, 5))


def test_calendar_gap_is_marked_but_non_trading_days_are_not() -> None:
    calendar = ["2024-01-02", "2024-01-03", "2024-01-04"]
    raw = make_frame(trade_date=["2024-01-02", "2024-01-04", "2024-01-04"])
    # 重复日期本身只标记；交易日缺口单独返回，不把非交易日误判为缺失。
    result = adjust_prices(raw, calendar_dates=calendar, today=date(2024, 1, 5))
    assert result.expected_missing_dates == ["2024-01-03"]


def test_duplicate_date_is_invalid() -> None:
    raw = make_frame(trade_date=["2024-01-02", "2024-01-02", "2024-01-04"])
    result = adjust_prices(raw, today=date(2024, 1, 5))
    assert (result.data["price_status"] == "invalid").sum() == 2
    assert "duplicate_date" in result.data.loc[0, "price_reasons"]
