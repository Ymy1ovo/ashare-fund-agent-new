"""数据质量记录仓储。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from app.fund.models import DataQualityRecord
from app.fund.repo_base import get_conn, use_conn


class QualityRepository:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path

    def record(self, rec: DataQualityRecord, *,
               conn: sqlite3.Connection | None = None) -> int:
        """按 (table_name, record_key, check_name) 幂等写入。

        同一检查项重复执行只更新结果，不产生重复行。
        conn 非空时复用该连接（不自行 commit/rollback）。
        """
        with use_conn(self.db_path, conn) as conn:
            row = conn.execute(
                """SELECT quality_id FROM fund_data_quality
                   WHERE table_name=? AND record_key=? AND check_name=?""",
                (rec.table_name, rec.record_key, rec.check_name)).fetchone()
            if row:
                conn.execute(
                    """UPDATE fund_data_quality SET
                         status=?, detail=?, severity=?, checked_at=?
                       WHERE quality_id=?""",
                    (rec.status, rec.detail, rec.severity, rec.checked_at,
                     int(row["quality_id"])))
                return int(row["quality_id"])
            cur = conn.execute(
                """INSERT INTO fund_data_quality
                   (table_name, record_key, check_name, status, detail,
                    severity, checked_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (rec.table_name, rec.record_key, rec.check_name, rec.status,
                 rec.detail, rec.severity, rec.checked_at))
            return int(cur.lastrowid)

    def record_many(self, records: list[DataQualityRecord]) -> int:
        for rec in records:
            self.record(rec)
        return len(records)

    def list_issues(self, *, table_name: str | None = None,
                    status: str | None = None) -> list[dict]:
        sql = "SELECT * FROM fund_data_quality WHERE 1=1"
        params: list = []
        if table_name:
            sql += " AND table_name=?"
            params.append(table_name)
        if status:
            sql += " AND status=?"
            params.append(status)
        sql += " ORDER BY table_name, record_key, check_name"
        with get_conn(self.db_path) as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def count(self) -> int:
        with get_conn(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) FROM fund_data_quality").fetchone()[0]

    def summary(self) -> dict:
        with get_conn(self.db_path) as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) n FROM fund_data_quality GROUP BY status"
            ).fetchall()
            return {r["status"]: r["n"] for r in rows}
