"""验证结果持久化。

新增 4 张表，全部 CREATE TABLE IF NOT EXISTS；历史回测表一行不动。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.database.db import get_connection

VALIDATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS validation_runs (
    validation_id TEXT PRIMARY KEY,
    strategy_name TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    input_hash TEXT,
    etf_codes TEXT NOT NULL,
    excluded_codes TEXT,
    ma_window_grid TEXT NOT NULL,
    is_start TEXT,
    is_end TEXT,
    oos_start TEXT,
    oos_end TEXT,
    walkforward_config TEXT,
    benchmark_config TEXT,
    stress_config TEXT,
    status TEXT NOT NULL,
    conclusion TEXT,
    summary_json TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS validation_windows (
    validation_id TEXT NOT NULL,
    window_index INTEGER NOT NULL,
    train_start TEXT,
    train_end TEXT,
    test_start TEXT,
    test_end TEXT,
    train_days INTEGER,
    test_days INTEGER,
    selected_param INTEGER,
    status TEXT NOT NULL,
    reason TEXT,
    train_metrics_json TEXT,
    test_metrics_json TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (validation_id, window_index)
);

CREATE TABLE IF NOT EXISTS validation_grid (
    validation_id TEXT NOT NULL,
    ma_window INTEGER NOT NULL,
    phase TEXT NOT NULL,
    status TEXT NOT NULL,
    metrics_json TEXT,
    reason TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (validation_id, ma_window, phase)
);

CREATE TABLE IF NOT EXISTS validation_stress (
    validation_id TEXT NOT NULL,
    scenario_key TEXT NOT NULL,
    scenario_name TEXT,
    is_hypothetical INTEGER NOT NULL DEFAULT 1,
    config_json TEXT,
    status TEXT NOT NULL,
    metrics_json TEXT,
    reason TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (validation_id, scenario_key)
);

CREATE INDEX IF NOT EXISTS idx_validation_runs_status
    ON validation_runs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_validation_grid_phase
    ON validation_grid(validation_id, phase);
"""


class ValidationStorageError(RuntimeError):
    """验证记录写入失败。"""


@dataclass
class ValidationRecord:
    """一次验证任务的主记录。"""

    validation_id: str
    strategy_name: str
    strategy_version: str
    config_hash: str
    eth_codes: list[str]
    ma_window_grid: list[int]
    is_start: str
    is_end: str
    oos_start: str
    oos_end: str
    status: str = "running"
    conclusion: str | None = None
    error_message: str | None = None
    input_hash: str | None = None
    excluded_codes: list[dict] | None = None
    walkforward_config: dict | None = None
    benchmark_config: dict | None = None
    stress_config: dict | None = None
    summary: dict | None = None


def init_validation_schema(db_path=None) -> None:
    with get_connection(db_path) as conn:
        conn.executescript(VALIDATION_SCHEMA)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def save_validation_run(record: ValidationRecord, db_path=None) -> None:
    """写入主记录；同 validation_id 重跑只更新该条，不覆盖其他验证。"""
    init_validation_schema(db_path)
    created = datetime.now().isoformat(timespec="seconds")
    with get_connection(db_path) as conn:
        existing = conn.execute(
            "SELECT validation_id FROM validation_runs WHERE validation_id=?",
            (record.validation_id,),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO validation_runs
                (validation_id, strategy_name, strategy_version, config_hash, input_hash,
                 etf_codes, excluded_codes, ma_window_grid, is_start, is_end, oos_start, oos_end,
                 walkforward_config, benchmark_config, stress_config, status, conclusion,
                 summary_json, error_message, created_at, finished_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(validation_id) DO UPDATE SET
                input_hash=excluded.input_hash,
                excluded_codes=excluded.excluded_codes,
                walkforward_config=excluded.walkforward_config,
                benchmark_config=excluded.benchmark_config,
                stress_config=excluded.stress_config,
                status=excluded.status,
                conclusion=excluded.conclusion,
                summary_json=excluded.summary_json,
                error_message=excluded.error_message,
                finished_at=excluded.finished_at
            """,
            (
                record.validation_id,
                record.strategy_name,
                record.strategy_version,
                record.config_hash,
                record.input_hash,
                _json(record.eth_codes),
                _json(record.excluded_codes or []),
                _json(record.ma_window_grid),
                record.is_start,
                record.is_end,
                record.oos_start,
                record.oos_end,
                _json(record.walkforward_config or {}),
                _json(record.benchmark_config or {}),
                _json(record.stress_config or {}),
                record.status,
                record.conclusion,
                _json(record.summary or {}),
                record.error_message,
                created,
                created if record.status in ("success", "partial", "failed") else None,
            ),
        )
        if not existing:
            # 新任务：清空子表，避免残留同 id 的旧明细
            for table in ("validation_windows", "validation_grid", "validation_stress"):
                conn.execute(f"DELETE FROM {table} WHERE validation_id=?", (record.validation_id,))


def save_windows(validation_id: str, windows: list[dict], db_path=None) -> None:
    if not windows:
        return
    init_validation_schema(db_path)
    created = datetime.now().isoformat(timespec="seconds")
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM validation_windows WHERE validation_id=?", (validation_id,))
        conn.executemany(
            """
            INSERT INTO validation_windows
                (validation_id, window_index, train_start, train_end, test_start, test_end,
                 train_days, test_days, selected_param, status, reason,
                 train_metrics_json, test_metrics_json, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    validation_id,
                    window["index"],
                    window.get("train_start"),
                    window.get("train_end"),
                    window.get("test_start"),
                    window.get("test_end"),
                    window.get("train_days"),
                    window.get("test_days"),
                    window.get("selected_param"),
                    window.get("status", "pending"),
                    window.get("reason"),
                    _json(window.get("train_metrics") or {}),
                    _json(window.get("test_metrics") or {}),
                    created,
                )
                for window in windows
            ],
        )


def save_grid(validation_id: str, phase: str, cells: list[dict], db_path=None) -> None:
    if not cells:
        return
    init_validation_schema(db_path)
    created = datetime.now().isoformat(timespec="seconds")
    with get_connection(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO validation_grid
                (validation_id, ma_window, phase, status, metrics_json, reason, created_at)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(validation_id, ma_window, phase) DO UPDATE SET
                status=excluded.status,
                metrics_json=excluded.metrics_json,
                reason=excluded.reason
            """,
            [
                (
                    validation_id,
                    cell["ma_window"],
                    phase,
                    cell.get("status", "pending"),
                    _json(cell.get("metrics") or {}),
                    cell.get("reason"),
                    created,
                )
                for cell in cells
            ],
        )


def save_stress(validation_id: str, rows: list[dict], db_path=None) -> None:
    if not rows:
        return
    init_validation_schema(db_path)
    created = datetime.now().isoformat(timespec="seconds")
    with get_connection(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO validation_stress
                (validation_id, scenario_key, scenario_name, is_hypothetical,
                 config_json, status, metrics_json, reason, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(validation_id, scenario_key) DO UPDATE SET
                status=excluded.status,
                metrics_json=excluded.metrics_json,
                reason=excluded.reason
            """,
            [
                (
                    validation_id,
                    row["key"],
                    row.get("name"),
                    1 if row.get("is_hypothetical", True) else 0,
                    _json(row.get("config") or {}),
                    row.get("status", "pending"),
                    _json(row.get("metrics") or {}),
                    row.get("reason"),
                    created,
                )
                for row in rows
            ],
        )


def get_validation(validation_id: str, db_path=None) -> dict | None:
    init_validation_schema(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM validation_runs WHERE validation_id=?", (validation_id,)
        ).fetchone()
        if not row:
            return None
        payload = dict(row)
        for key in ("etf_codes", "excluded_codes", "ma_window_grid", "walkforward_config",
                    "benchmark_config", "stress_config", "summary_json"):
            if payload.get(key):
                try:
                    payload[key] = json.loads(payload[key])
                except json.JSONDecodeError:
                    pass
        payload["windows"] = [
            dict(item) for item in conn.execute(
                "SELECT * FROM validation_windows WHERE validation_id=? ORDER BY window_index",
                (validation_id,),
            )
        ]
        payload["grid"] = [
            dict(item) for item in conn.execute(
                "SELECT * FROM validation_grid WHERE validation_id=? ORDER BY phase, ma_window",
                (validation_id,),
            )
        ]
        payload["stress"] = [
            dict(item) for item in conn.execute(
                "SELECT * FROM validation_stress WHERE validation_id=? ORDER BY scenario_key",
                (validation_id,),
            )
        ]
    return payload


def list_validations(limit: int = 20, db_path=None) -> list[dict]:
    init_validation_schema(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT validation_id, strategy_name, strategy_version, status, conclusion, "
            "is_start, is_end, oos_start, oos_end, config_hash, input_hash, created_at "
            "FROM validation_runs ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]
