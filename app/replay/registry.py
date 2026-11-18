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
from app.replay.manifest import ReplayError

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

-- 阶段3A.3.2.3.6.1：追加式失效关系。
-- 旧 attempt / 旧结果的原始行一律不改，这里只额外记一条
-- 「谁被谁取代、为什么」。唯一键落在被取代的 attempt 上，
-- 同一 attempt 不可被失效两次；新侧字段在重新执行成功后回填。
CREATE TABLE IF NOT EXISTS replay_supersessions (
    supersession_id TEXT PRIMARY KEY,
    record_kind TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    superseded_attempt_id TEXT NOT NULL,
    superseded_record_id TEXT,
    replacement_attempt_id TEXT,
    replacement_record_id TEXT,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_supersede_attempt
    ON replay_supersessions(superseded_attempt_id);
CREATE INDEX IF NOT EXISTS idx_supersede_source
    ON replay_supersessions(record_kind, source_record_id);
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
    """该源记录是否已有**仍然有效**的成功重放；返回最近的 replay_record_id。

    阶段3A.3.2.3.6.1：被 `replay_supersessions` 标记失效的旧 attempt
    不再算数——否则修复缺陷后会被旧结果挡住、无法重新执行。
    """
    init_replay_schema(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT replay_record_id FROM replay_attempts a "
            "WHERE a.record_kind=? AND a.source_record_id=? AND a.status=? "
            "AND a.replay_record_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM replay_supersessions s "
            "                WHERE s.superseded_attempt_id = a.attempt_id) "
            "ORDER BY a.finished_at DESC, a.rowid DESC LIMIT 1",
            (record_kind, source_record_id, STATUS_SUCCESS),
        ).fetchone()
    return str(row[0]) if row else None


def success_map(record_kind: str, db_path=None) -> dict[str, str]:
    """`{source_id: replay_id}`，供 manifest 判定 replayed。"""
    init_replay_schema(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT a.source_record_id, a.replay_record_id FROM replay_attempts a "
            "WHERE a.record_kind=? AND a.status=? AND a.replay_record_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM replay_supersessions s "
            "                WHERE s.superseded_attempt_id = a.attempt_id) "
            "ORDER BY a.finished_at",
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


# ---------------------------------------------------------------- 追加式失效

REASON_MISSING_DETAILS = "missing_corporate_action_details"
REASON_REGIME_INCOMPLETE = "regime_audit_incomplete"


def start_supersession(
    record_kind: str,
    source_record_id: str,
    *,
    superseded_attempt_id: str,
    reason: str,
    db_path=None,
) -> str:
    """标记一条旧重放结果「已被取代」，返回 supersession_id。

    追加式：旧 attempt 行一律不改（`status` 仍是当年真实的 success），
    只在这里新增一条关系记录。同一 attempt 只能被失效一次。
    """
    init_replay_schema(db_path)
    with get_connection(db_path) as conn:
        existing = conn.execute(
            "SELECT supersession_id FROM replay_supersessions "
            "WHERE superseded_attempt_id=?", (superseded_attempt_id,)
        ).fetchone()
        if existing is not None:
            return str(existing[0])
        row = conn.execute(
            "SELECT replay_record_id FROM replay_attempts WHERE attempt_id=?",
            (superseded_attempt_id,),
        ).fetchone()
        if row is None:
            raise ReplayError(f"待失效的 attempt 不存在：{superseded_attempt_id}")
        supersession_id = uuid.uuid4().hex[:16]
        conn.execute(
            "INSERT INTO replay_supersessions "
            "(supersession_id, record_kind, source_record_id, "
            " superseded_attempt_id, superseded_record_id, reason, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (supersession_id, record_kind, source_record_id,
             superseded_attempt_id, row[0], reason, _now()),
        )
    return supersession_id


def complete_supersession(
    supersession_id: str,
    *,
    replacement_attempt_id: str,
    replacement_record_id: str,
    db_path=None,
) -> None:
    """重新执行成功后，回填新侧 attempt / result，闭环这条失效关系。"""
    init_replay_schema(db_path)
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE replay_supersessions "
            "SET replacement_attempt_id=?, replacement_record_id=?, completed_at=? "
            "WHERE supersession_id=?",
            (replacement_attempt_id, replacement_record_id, _now(), supersession_id),
        )


def list_supersessions(record_kind: str | None = None, db_path=None) -> list[dict]:
    """列出全部失效关系；审计报告据此解释旧结果为何不再有效。"""
    init_replay_schema(db_path)
    sql = "SELECT * FROM replay_supersessions"
    params: list[Any] = []
    if record_kind:
        sql += " WHERE record_kind=?"
        params.append(record_kind)
    sql += " ORDER BY created_at, rowid"
    with get_connection(db_path) as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def pending_supersessions(db_path=None) -> list[dict]:
    """尚未完成闭环的失效关系（重新执行还没成功）。"""
    init_replay_schema(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM replay_supersessions WHERE replacement_attempt_id IS NULL "
            "ORDER BY created_at, rowid"
        ).fetchall()
    return [dict(row) for row in rows]
