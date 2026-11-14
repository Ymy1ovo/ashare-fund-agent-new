"""重放登记表：记录「源记录 → 重放记录」的对应关系与执行状态。

只新增一张表，不改任何历史表、不改任何历史行。
`init_replay_schema()` 幂等，重复执行不会重建或清空。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.database.db import get_connection

SCHEMA = """
CREATE TABLE IF NOT EXISTS replay_attempts (
    attempt_id TEXT PRIMARY KEY,
    record_kind TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    replay_record_id TEXT,
    source_input_hash TEXT,
    replay_input_hash TEXT,
    source_accounting_version TEXT,
    replay_accounting_version TEXT,
    source_config_hash TEXT,
    replay_params_json TEXT,
    status TEXT NOT NULL,
    reason TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    replay_timestamp TEXT
);
CREATE INDEX IF NOT EXISTS idx_replay_source
    ON replay_attempts(record_kind, source_record_id);
CREATE INDEX IF NOT EXISTS idx_replay_status ON replay_attempts(status);
"""

STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"
TERMINAL = (STATUS_SUCCESS, STATUS_FAILED, STATUS_SKIPPED)


@dataclass
class ReplayOutcome:
    """一次重放尝试的结果。"""

    source_id: str
    status: str
    replay_id: str | None = None
    reason: str | None = None
    attempt_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == STATUS_SUCCESS


def init_replay_schema(db_path=None) -> None:
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def start_attempt(
    record_kind: str,
    source_record_id: str,
    *,
    source_input_hash: str | None = None,
    source_accounting_version: str | None = None,
    source_config_hash: str | None = None,
    replay_params: dict | None = None,
    db_path=None,
) -> str:
    """开一条 running 记录；不覆盖历史 attempt。"""
    import json

    init_replay_schema(db_path)
    attempt_id = uuid.uuid4().hex[:16]
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO replay_attempts "
            "(attempt_id, record_kind, source_record_id, status, started_at, "
            " source_input_hash, source_accounting_version, source_config_hash, "
            " replay_params_json) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                attempt_id, record_kind, source_record_id, STATUS_RUNNING, _now(),
                source_input_hash, source_accounting_version, source_config_hash,
                json.dumps(replay_params or {}, ensure_ascii=False, sort_keys=True, default=str),
            ),
        )
    return attempt_id


def finish_attempt(
    attempt_id: str,
    status: str,
    *,
    replay_record_id: str | None = None,
    replay_input_hash: str | None = None,
    replay_accounting_version: str | None = None,
    reason: str | None = None,
    db_path=None,
) -> None:
    if status not in TERMINAL:
        raise ValueError(f"非终态状态：{status}")
    stamped = _now()
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE replay_attempts SET status=?, replay_record_id=?, replay_input_hash=?, "
            "replay_accounting_version=?, reason=?, finished_at=?, replay_timestamp=? "
            "WHERE attempt_id=?",
            (status, replay_record_id, replay_input_hash, replay_accounting_version,
             reason, stamped, stamped, attempt_id),
        )


def find_success(record_kind: str, source_record_id: str, db_path=None) -> str | None:
    """该源记录是否已有成功重放；返回最近的 replay_record_id。"""
    init_replay_schema(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT replay_record_id FROM replay_attempts "
            "WHERE record_kind=? AND source_record_id=? AND status=? "
            "AND replay_record_id IS NOT NULL "
            "ORDER BY finished_at DESC, rowid DESC LIMIT 1",
            (record_kind, source_record_id, STATUS_SUCCESS),
        ).fetchone()
    return str(row[0]) if row else None


def success_map(record_kind: str, db_path=None) -> dict[str, str]:
    """`{source_id: replay_id}`，供 manifest 判定 replayed。"""
    init_replay_schema(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT source_record_id, replay_record_id FROM replay_attempts "
            "WHERE record_kind=? AND status=? AND replay_record_id IS NOT NULL "
            "ORDER BY finished_at",
            (record_kind, STATUS_SUCCESS),
        ).fetchall()
    return {str(row[0]): str(row[1]) for row in rows}


def list_attempts(record_kind: str | None = None, limit: int = 100, db_path=None) -> list[dict]:
    init_replay_schema(db_path)
    sql = "SELECT * FROM replay_attempts"
    params: list[Any] = []
    if record_kind:
        sql += " WHERE record_kind=?"
        params.append(record_kind)
    sql += " ORDER BY started_at DESC, rowid DESC LIMIT ?"
    params.append(limit)
    with get_connection(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]
