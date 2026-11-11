from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.database.db import get_connection
from app.database.indicators import (
    get_indicator_overview,
    get_indicator_rows,
    save_indicator_result,
)
from app.quant.engine import (
    IndicatorCalculationError,
    batch_exit_code,
    calculate_indicators,
    calculate_many,
)


def _seed(db_path, code="510300", rows=10, snapshot_id=None, second_snapshot=False):
    dates = pd.date_range("2024-01-02", periods=rows, freq="B")
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO adjustment_runs (started_at, finished_at, status, total_codes, success_codes) "
            "VALUES ('2024-01-01T00:00:00', '2024-01-01T00:00:01', 'success', 1, 1)"
        )
        run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO etf_adjustment_snapshots "
            "(run_id, code, status, collected_at, source, coverage_start, coverage_end, "
            "matched_start, matched_end, raw_rows, qfq_rows, matched_rows, missing_rows, is_current, created_at) "
            "VALUES (?, ?, 'success', '2024-01-01T00:00:00', 'test', ?, ?, ?, ?, ?, ?, ?, 0, 1, '2024-01-01T00:00:00')",
            (run_id, code, dates[0].date().isoformat(), dates[-1].date().isoformat(),
             dates[0].date().isoformat(), dates[-1].date().isoformat(),
             rows, rows, rows),
        )
        snapshot_id = snapshot_id or conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("UPDATE etf_adjustment_snapshots SET is_current = 1 WHERE id = ?", (snapshot_id,))
        if second_snapshot:
            conn.execute(
                "INSERT INTO etf_adjustment_snapshots "
                "(run_id, code, status, collected_at, source, coverage_start, coverage_end, "
                "matched_start, matched_end, raw_rows, qfq_rows, matched_rows, missing_rows, is_current, created_at) "
                "VALUES (?, ?, 'success', '2024-01-02T00:00:00', 'test', ?, ?, ?, ?, ?, ?, ?, 0, 0, '2024-01-02T00:00:00')",
                (run_id, code, dates[0].date().isoformat(), dates[-1].date().isoformat(),
                 dates[0].date().isoformat(), dates[-1].date().isoformat(),
                 rows, rows, rows),
            )
        for index, current in enumerate(dates):
            close = 10.0 + index * 0.1
            conn.execute(
                """
                INSERT INTO etf_daily_prices
                    (code, trade_date, open, high, low, close, volume, amount,
                     adjusted_close, adjustment_type, quality_status, source, collected_at,
                     adjustment_snapshot_id, adjustment_collected_at, adjustment_source,
                     adjustment_coverage_start, adjustment_coverage_end)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'qfq', 'valid', 'test', '2024-01-01T00:00:00',
                        ?, '2024-01-01T00:00:00', 'test', ?, ?)
                """,
                (
                    code,
                    current.date().isoformat(),
                    close - 0.1,
                    close + 0.1,
                    close - 0.2,
                    close,
                    1000.0,
                    10000.0,
                    close * 1.2,
                    snapshot_id,
                    dates[0].date().isoformat(),
                    dates[-1].date().isoformat(),
                ),
            )
        conn.executemany(
            "INSERT INTO trade_calendar (trade_date) VALUES (?)",
            [(d.date().isoformat(),) for d in dates],
        )
    return [d.date().isoformat() for d in dates], snapshot_id


def _config():
    return {
        "enabled": ["returns", "trend", "momentum", "volatility", "risk"],
        "return_windows": [1, 2],
        "ma_windows": [2, 3],
        "ema_spans": [2],
        "rsi_periods": [2],
        "macd": {"fast": 2, "slow": 3, "signal": 2},
        "vol_windows": [2],
        "mdd_windows": [2],
        "atr_period": 2,
        "risk_window": 2,
        "risk_free_rate": 0.0,
        "annualization": 252,
        "std_ddof": 1,
    }


def test_engine_success_and_snapshot_traceability(temp_db) -> None:
    dates, snapshot_id = _seed(temp_db)
    with get_connection(temp_db) as conn:
        before = conn.execute(
            "SELECT code, trade_date, open, high, low, close, volume FROM etf_daily_prices "
            "WHERE code='510300' ORDER BY trade_date"
        ).fetchall()
    result = calculate_indicators("510300", db_path=temp_db)
    with get_connection(temp_db) as conn:
        after = conn.execute(
            "SELECT code, trade_date, open, high, low, close, volume FROM etf_daily_prices "
            "WHERE code='510300' ORDER BY trade_date"
        ).fetchall()
    assert [tuple(row) for row in before] == [tuple(row) for row in after]
    assert result.status == "success"
    assert result.snapshot_id == snapshot_id
    assert result.snapshot_is_current is True
    assert result.calculation_version.startswith("v1.0.2-")
    assert len(result.data) == len(dates)
    assert {"return_1d", "ma5", "rsi6", "macd_hist", "volatility_20d", "sharpe_ratio"} <= set(result.data.columns)
    assert result.data["trade_date"].iloc[0] == dates[0]


def test_missing_adjusted_close_is_partial_and_never_filled(temp_db) -> None:
    dates, _ = _seed(temp_db)
    with get_connection(temp_db) as conn:
        conn.execute(
            "UPDATE etf_daily_prices SET adjusted_close = NULL WHERE code='510300' AND trade_date=?",
            (dates[3],),
        )
    result = calculate_indicators("510300", db_path=temp_db)
    assert result.status == "partial"
    row = result.data[result.data["trade_date"] == dates[3]].iloc[0]
    assert row["quality_status"] == "invalid"
    assert pd.isna(row["return_1d"])
    assert row["price_status"] == "invalid"


def test_zero_volume_is_warning_not_invalid_price(temp_db) -> None:
    dates, _ = _seed(temp_db)
    with get_connection(temp_db) as conn:
        conn.execute(
            "UPDATE etf_daily_prices SET volume = 0 WHERE code='510300' AND trade_date=?",
            (dates[2],),
        )
    result = calculate_indicators("510300", db_path=temp_db)
    row = result.data[result.data["trade_date"] == dates[2]].iloc[0]
    assert row["trade_status"] == "zero_volume"
    assert result.status == "success"


def test_snapshot_mix_is_rejected(temp_db) -> None:
    _seed(temp_db, second_snapshot=True)
    with get_connection(temp_db) as conn:
        conn.execute(
            "UPDATE etf_daily_prices SET adjustment_snapshot_id = "
            "(SELECT MAX(id) FROM etf_adjustment_snapshots) "
            "WHERE code='510300' AND trade_date='2024-01-04'"
        )
    with pytest.raises(IndicatorCalculationError):
        calculate_indicators("510300", db_path=temp_db)


def test_future_data_does_not_change_past_indicators(temp_db) -> None:
    dates, _ = _seed(temp_db)
    cutoff = dates[4]
    before = calculate_indicators("510300", end_date=cutoff, db_path=temp_db, today=date(2024, 2, 1))
    with get_connection(temp_db) as conn:
        conn.execute(
            "UPDATE etf_daily_prices SET close = close * 5, high = high * 5, low = low * 5, "
            "adjusted_close = adjusted_close * 5, volume = volume * 2 "
            "WHERE code='510300' AND trade_date > ?",
            (cutoff,),
        )
    after = calculate_indicators("510300", end_date=cutoff, db_path=temp_db, today=date(2024, 2, 1))
    columns = [column for column in before.data.columns if column.startswith(
        ("return_", "ma", "ema", "rsi", "macd", "volatility", "max_drawdown", "atr", "sharpe", "sortino", "calmar", "cagr")
    )]
    pd.testing.assert_frame_equal(
        before.data[["trade_date", *columns]].reset_index(drop=True),
        after.data[["trade_date", *columns]].reset_index(drop=True),
    )


def test_save_incremental_and_parameter_version(temp_db) -> None:
    _seed(temp_db)
    result = calculate_indicators("510300", db_path=temp_db)
    first = save_indicator_result(result, db_path=temp_db)
    assert first["written_rows"] > 0
    second = save_indicator_result(result, db_path=temp_db)
    assert second["written_rows"] == 0
    rows = get_indicator_rows("510300", db_path=temp_db)
    assert len(rows) == len(result.data)

    custom = calculate_indicators(
        "510300", indicator_config={**_config(), "risk_window": 3}, db_path=temp_db
    )
    save_indicator_result(custom, db_path=temp_db, full_rebuild=True)
    assert custom.calculation_version != result.calculation_version
    rows_v2 = get_indicator_rows("510300", version=custom.calculation_version, db_path=temp_db)
    assert len(rows_v2) == len(custom.data)
    old_rows = get_indicator_rows("510300", version=result.calculation_version, db_path=temp_db)
    assert len(old_rows) == len(result.data)


def test_daily_cagr_matches_range_summary_with_missing_day(temp_db) -> None:
    dates, _ = _seed(temp_db)
    with get_connection(temp_db) as conn:
        conn.execute(
            "UPDATE etf_daily_prices SET adjusted_close=NULL WHERE code='510300' AND trade_date=?",
            (dates[1],),
        )
    result = calculate_indicators("510300", db_path=temp_db)
    last = result.data.iloc[-1]
    assert result.summary["elapsed_trading_intervals"] == len(dates) - 1
    assert result.summary["missing_trading_days"] == 1
    assert result.summary["cagr"] == pytest.approx(last["cagr"])
    assert result.quality["cagr_missing_trading_days"] == 1


def test_calculate_many_partial_failure_and_empty_data(temp_db) -> None:
    _seed(temp_db)
    results, failures = calculate_many(["510300", "999999"], db_path=temp_db)
    assert len(results) == 1
    assert len(failures) == 1
    assert failures[0]["reason"] == "no_data"
    assert batch_exit_code(results, failures, 2) == 2
    with pytest.raises(IndicatorCalculationError):
        calculate_indicators("999999", db_path=temp_db)


def test_overview_marks_stale_snapshot(temp_db) -> None:
    _seed(temp_db)
    result = calculate_indicators("510300", db_path=temp_db)
    save_indicator_result(result, db_path=temp_db)
    overview = get_indicator_overview(db_path=temp_db)
    assert overview[0]["etf_code"] == "510300"
    assert overview[0]["stale"] is False

    with get_connection(temp_db) as conn:
        old_id = result.snapshot_id
        conn.execute(
            "INSERT INTO etf_adjustment_snapshots "
            "(run_id, code, status, collected_at, source, coverage_start, coverage_end, "
            "matched_start, matched_end, raw_rows, qfq_rows, matched_rows, missing_rows, is_current, created_at) "
            "VALUES (1, '510300', 'success', '2024-01-02T00:00:00', 'test', "
            "'2024-01-02', '2024-01-12', '2024-01-02', '2024-01-12', 10, 10, 10, 0, 0, '2024-01-02T00:00:00')"
        )
        new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("UPDATE etf_adjustment_snapshots SET is_current = 0 WHERE id = ?", (old_id,))
        conn.execute("UPDATE etf_adjustment_snapshots SET is_current = 1 WHERE id = ?", (new_id,))
    overview = get_indicator_overview(db_path=temp_db)
    assert overview[0]["stale"] is True
