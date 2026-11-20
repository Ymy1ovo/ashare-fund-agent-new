"""阶段3B-4.4 数据缺口补强：证据追溯列迁移。

只补列、只加索引，不改已有列、不删数据。
SQLite 的 ALTER TABLE ADD COLUMN 不支持 IF NOT EXISTS，
所以先查 PRAGMA table_info 再逐列补，保证可重复执行。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from app.database.db import get_connection

MIGRATION_FILE = (Path(__file__).resolve().parents[2]
                  / "migrations" / "phase3b4_4_evidence_columns.sql")

MANAGER_COLUMNS = (
    ("announcement_id", "TEXT"),
    ("announcement_url", "TEXT"),
    ("evidence_level", "TEXT"),
    ("change_type", "TEXT"),
    ("detail", "TEXT"),
)

AUM_COLUMNS = (
    ("announcement_id", "TEXT"),
    ("announcement_url", "TEXT"),
    ("evidence_level", "TEXT"),
    ("disclosed_at", "TEXT"),
    ("detail", "TEXT"),
)

FEE_COLUMNS = (
    ("announcement_id", "TEXT"),
)

TABLES = {
    "fund_manager_history": MANAGER_COLUMNS,
    "fund_aum_history": AUM_COLUMNS,
    "fund_fee_rules": FEE_COLUMNS,
}

INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_fund_mgr_announcement "
    "ON fund_manager_history(announcement_id)",
    "CREATE INDEX IF NOT EXISTS idx_fund_mgr_evidence "
    "ON fund_manager_history(evidence_level)",
    "CREATE INDEX IF NOT EXISTS idx_fund_aum_evidence "
    "ON fund_aum_history(evidence_level)",
    "CREATE INDEX IF NOT EXISTS idx_fund_fee_announcement "
    "ON fund_fee_rules(announcement_id)",
    "CREATE INDEX IF NOT EXISTS idx_fund_fee_effective "
    "ON fund_fee_rules(effective_from, effective_to)",
)


def _existing_columns(conn, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _table_exists(conn, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def ensure_3b4_4_schema(db_path: str | Path | None = None) -> dict[str, list[str]]:
    """幂等补列。返回每张表本次新增的列名。"""
    added: dict[str, list[str]] = {}
    with get_connection(db_path) as conn:
        for table, columns in TABLES.items():
            if not _table_exists(conn, table):
                added[table] = []
                continue
            have = _existing_columns(conn, table)
            new_here = []
            for name, sqltype in columns:
                if name in have:
                    continue
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sqltype}")
                new_here.append(name)
            added[table] = new_here
        for sql in INDEXES:
            conn.execute(sql)
    return added


def current_schema(db_path: str | Path | None = None) -> dict:
    with get_connection(db_path) as conn:
        out = {}
        for table in TABLES:
            if not _table_exists(conn, table):
                out[table] = {"columns": [], "indexes": []}
                continue
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            idx = [r[1] for r in conn.execute(f"PRAGMA index_list({table})").fetchall()]
            out[table] = {"columns": cols, "indexes": idx}
        return out


def read_migration_sql() -> str:
    return MIGRATION_FILE.read_text(encoding="utf-8")
