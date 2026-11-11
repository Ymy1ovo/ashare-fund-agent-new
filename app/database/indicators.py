"""指标运行记录与每日指标的 SQLite 存储。"""
from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any, Iterable

import pandas as pd

from app.database.db import get_connection

INDICATOR_COLUMNS = [
    "return_1d",
    "return_5d",
    "return_10d",
    "return_20d",
    "return_60d",
    "return_120d",
    "return_250d",
    "cagr",
    "ma5",
    "ma10",
    "ma20",
    "ma30",
    "ma60",
    "ma120",
    "ma250",
    "ema12",
    "ema26",
    "rsi6",
    "rsi12",
    "rsi24",
    "macd_dif",
    "macd_dea",
    "macd_hist",
    "volatility_20d",
    "volatility_60d",
    "volatility_120d",
    "max_drawdown_20d",
    "max_drawdown_60d",
    "max_drawdown_120d",
    "max_drawdown_all",
    "atr14",
    "sharpe_ratio",
    "sortino_ratio",
    "calmar_ratio",
]

DAILY_COLUMNS = [
    "etf_code",
    "trade_date",
    "adjustment_snapshot_id",
    "calculation_version",
    "run_id",
    "adjusted_close",
    *INDICATOR_COLUMNS,
    "price_status",
    "trade_status",
    "quality_status",
    "quality_reasons",
    "created_at",
]


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        return value.item()
    return value


def _dict(row) -> dict[str, Any]:
    return dict(row)


def save_indicator_result(
    result,
    *,
    db_path=None,
    incremental: bool = True,
    full_rebuild: bool = False,
) -> dict[str, int]:
    """先写运行记录，再批量 UPSERT 指标行；同一版本/快照不产生重复行。"""
    frame = result.data.copy()
    if incremental and not full_rebuild:
        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT MAX(trade_date) FROM etf_indicator_daily "
                "WHERE etf_code = ? AND calculation_version = ? AND adjustment_snapshot_id = ?",
                (result.etf_code, result.calculation_version, result.snapshot_id),
            ).fetchone()
        last_date = row[0] if row else None
        if last_date:
            frame = frame[frame["trade_date"] > last_date]
    now = result.calculation_time
    summary = result.summary or {}
    quality = result.quality or {}
    params = (
        result.run_id,
        result.etf_code,
        summary.get("actual_start"),
        summary.get("actual_end"),
        json.dumps(result.config, ensure_ascii=False, sort_keys=True),
        result.snapshot_id,
        result.status,
        result.valid_rows,
        result.missing_rows,
        result.calculation_version,
        json.dumps(summary, ensure_ascii=False, default=str),
        json.dumps(quality, ensure_ascii=False, default=str),
        now,
    )
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO indicator_runs
                (run_id, etf_code, start_date, end_date, indicator_config,
                 adjustment_snapshot_id, status, valid_rows, missing_rows,
                 calculation_version, summary_json, quality_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                status = excluded.status,
                valid_rows = excluded.valid_rows,
                missing_rows = excluded.missing_rows,
                summary_json = excluded.summary_json,
                quality_json = excluded.quality_json
            """,
            params,
        )
        rows: list[tuple[Any, ...]] = []
        for record in frame.to_dict("records"):
            values = [
                record.get("etf_code", result.etf_code),
                record.get("trade_date"),
                result.snapshot_id,
                result.calculation_version,
                result.run_id,
                _json_value(record.get("adjusted_close")),
            ]
            values.extend(_json_value(record.get(column)) for column in INDICATOR_COLUMNS)
            values.extend(
                [
                    record.get("price_status"),
                    record.get("trade_status"),
                    record.get("quality_status", "valid"),
                    record.get("quality_reasons"),
                    now,
                ]
            )
            rows.append(tuple(values))
        if rows:
            placeholders = ",".join("?" for _ in DAILY_COLUMNS)
            update_columns = [
                column
                for column in DAILY_COLUMNS
                if column not in ("etf_code", "trade_date", "calculation_version", "adjustment_snapshot_id")
            ]
            updates = ",".join(f"{column}=excluded.{column}" for column in update_columns)
            conn.executemany(
                f"INSERT INTO etf_indicator_daily ({','.join(DAILY_COLUMNS)}) "
                f"VALUES ({placeholders}) ON CONFLICT(etf_code, trade_date, calculation_version, adjustment_snapshot_id) "
                f"DO UPDATE SET {updates}",
                rows,
            )
    return {"written_rows": len(rows), "run_id": result.run_id}


def get_latest_version(etf_code: str, db_path=None) -> str | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT calculation_version FROM etf_indicator_daily "
            "WHERE etf_code = ? ORDER BY created_at DESC, calculation_version DESC LIMIT 1",
            (etf_code,),
        ).fetchone()
    return str(row[0]) if row else None


def get_versions(etf_code: str, db_path=None) -> list[str]:
    with get_connection(db_path) as conn:
        return [
            str(row[0])
            for row in conn.execute(
                "SELECT DISTINCT calculation_version FROM etf_indicator_daily "
                "WHERE etf_code = ? ORDER BY calculation_version",
                (etf_code,),
            )
        ]


def get_indicator_rows(
    etf_code: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    version: str | None = None,
    db_path=None,
) -> list[dict[str, Any]]:
    version = version or get_latest_version(etf_code, db_path=db_path)
    if not version:
        return []
    clauses = ["etf_code = ?", "calculation_version = ?"]
    params: list[Any] = [etf_code, version]
    if start_date:
        clauses.append("trade_date >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("trade_date <= ?")
        params.append(end_date)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM etf_indicator_daily WHERE {' AND '.join(clauses)} "
            "ORDER BY trade_date",
            params,
        ).fetchall()
    return [_dict(row) for row in rows]


def get_latest_indicator(etf_code: str, db_path=None) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM etf_indicator_daily WHERE etf_code = ? "
            "ORDER BY trade_date DESC, created_at DESC LIMIT 1",
            (etf_code,),
        ).fetchone()
    return _dict(row) if row else None


def get_indicator_run(run_id: str, db_path=None) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM indicator_runs WHERE run_id = ?", (run_id,)).fetchone()
    return _dict(row) if row else None


def get_indicator_runs(etf_code: str | None = None, limit: int = 20, db_path=None) -> list[dict[str, Any]]:
    where = "WHERE etf_code = ?" if etf_code else ""
    params: tuple = (etf_code,) if etf_code else ()
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM indicator_runs {where} ORDER BY id DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
    return [_dict(row) for row in rows]


def _with_current_snapshot(rows: list[dict[str, Any]], db_path=None) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        current = {
            str(row["code"]): int(row["id"])
            for row in conn.execute(
                "SELECT code, id FROM etf_adjustment_snapshots WHERE is_current = 1"
            )
        }
    for row in rows:
        row["snapshot_is_current"] = current.get(str(row["etf_code"])) == row.get("adjustment_snapshot_id")
        row["stale"] = not row["snapshot_is_current"]
    return rows


def get_indicator_overview(db_path=None) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            WITH ranked AS (
                SELECT d.*, ROW_NUMBER() OVER (
                    PARTITION BY d.etf_code ORDER BY d.trade_date DESC, d.created_at DESC
                ) AS rn
                FROM etf_indicator_daily d
            )
            SELECT * FROM ranked WHERE rn = 1 ORDER BY etf_code
            """
        ).fetchall()
    return _with_current_snapshot([_dict(row) for row in rows], db_path=db_path)


def get_indicator_ranking(
    metric: str,
    *,
    order: str = "desc",
    limit: int = 20,
    version: str | None = None,
    db_path=None,
) -> list[dict[str, Any]]:
    if metric not in INDICATOR_COLUMNS:
        raise ValueError(f"不支持排序指标：{metric}")
    direction = "ASC" if str(order).lower() == "asc" else "DESC"
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"""
            WITH ranked AS (
                SELECT d.*, ROW_NUMBER() OVER (
                    PARTITION BY d.etf_code ORDER BY d.trade_date DESC, d.created_at DESC
                ) AS rn
                FROM etf_indicator_daily d
                WHERE (? IS NULL OR d.calculation_version = ?)
            )
            SELECT * FROM ranked
            WHERE rn = 1 AND {metric} IS NOT NULL
            ORDER BY {metric} {direction} LIMIT ?
            """,
            (version, version, int(limit)),
        ).fetchall()
    return _with_current_snapshot([_dict(row) for row in rows], db_path=db_path)
