"""阶段3B-4.2 最小必要迁移：给生命周期事件与费率规则补字段。

只补列、只加索引：
- 不改已有列的类型与约束；
- 不删任何数据、不重建任何表；
- 全部操作先查 PRAGMA，已存在则跳过，可重复执行。

SQLite 的 ALTER TABLE ADD COLUMN 不支持 IF NOT EXISTS，
所以这里用「查表结构 → 逐列补」的方式实现幂等；
`migrations/phase3b4_2_lifecycle_fee_ingestion.sql` 是同一迁移的可读文档。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from app.database.db import get_connection

MIGRATION_FILE = (Path(__file__).resolve().parents[2]
                  / "migrations" / "phase3b4_2_lifecycle_fee_ingestion.sql")

# (列名, 类型) —— 顺序即追加顺序，便于人工比对
LIFECYCLE_COLUMNS = (
    ("announcement_id", "TEXT"),
    ("product_structure", "TEXT"),
    ("fund_codes", "TEXT"),
    ("event_fingerprint", "TEXT"),
    ("fetched_at", "TEXT"),
)

FEE_COLUMNS = (
    ("lower_inclusive", "INTEGER"),
    ("upper_inclusive", "INTEGER"),
    ("lower_inferred", "INTEGER"),
    ("holding_days_min_inclusive", "INTEGER"),
    ("holding_days_max_inclusive", "INTEGER"),
    ("holding_days_min_inferred", "INTEGER"),
    ("rate_original", "REAL"),
    ("rate_platform", "REAL"),
    ("platform_name", "TEXT"),
    ("is_annual", "INTEGER"),
    ("holding_days_basis", "TEXT"),
    ("source_name", "TEXT"),
    ("source_url", "TEXT"),
    ("fetched_at", "TEXT"),
    ("detail", "TEXT"),
)

INDEXES = (
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_fund_life_fingerprint
       ON fund_lifecycle_events(event_fingerprint)
       WHERE event_fingerprint IS NOT NULL""",
    """CREATE INDEX IF NOT EXISTS idx_fund_life_announcement
       ON fund_lifecycle_events(announcement_id)""",
    """CREATE INDEX IF NOT EXISTS idx_fund_life_structure
       ON fund_lifecycle_events(product_structure)""",
    """CREATE INDEX IF NOT EXISTS idx_fund_fee_type
       ON fund_fee_rules(share_class_id, fee_type)""",
    """CREATE INDEX IF NOT EXISTS idx_fund_fee_platform
       ON fund_fee_rules(platform_name)""",
)


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,)).fetchone() is not None


def ensure_3b4_2_schema(db_path: Path | None = None) -> dict:
    """补列 + 建索引（幂等）。返回本次实际新增的列与索引。"""
    added: dict[str, list[str]] = {"fund_lifecycle_events": [],
                                   "fund_fee_rules": []}
    with get_connection(db_path) as conn:
        for table, columns in (("fund_lifecycle_events", LIFECYCLE_COLUMNS),
                               ("fund_fee_rules", FEE_COLUMNS)):
            if not _table_exists(conn, table):
                # 基础表由 phase3b4 建；这里不负责从零建表
                continue
            have = _existing_columns(conn, table)
            for name, ctype in columns:
                if name in have:
                    continue
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ctype}")
                added[table].append(name)
        for sql in INDEXES:
            conn.execute(sql)
    return added


def current_schema(db_path: Path | None = None) -> dict:
    """回读两张表当前列与索引，供测试与报告比对。"""
    with get_connection(db_path) as conn:
        out = {}
        for table in ("fund_lifecycle_events", "fund_fee_rules"):
            out[table] = {
                "columns": [r[1] for r in conn.execute(f"PRAGMA table_info({table})")],
                "indexes": [r[1] for r in conn.execute(f"PRAGMA index_list({table})")],
            }
        return out


def read_migration_sql() -> str:
    return MIGRATION_FILE.read_text(encoding="utf-8")
