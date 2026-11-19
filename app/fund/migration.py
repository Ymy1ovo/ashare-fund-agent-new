"""场外基金数据层迁移。

独立于 app/database/db.py 的 init_db：
- 场外基金表由本模块单独建，不混进 ETF 的 SCHEMA；
- 全部语句 IF NOT EXISTS，可重复执行；
- 不触碰任何 ETF 表。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from app.database.db import get_connection

MIGRATION_FILE = Path(__file__).resolve().parents[2] / "migrations" / "phase3b4_fund_data_layer.sql"

FUND_TABLES = (
    "fund_master",
    "fund_share_classes",
    "fund_nav_daily",
    "fund_dividends",
    "fund_manager_history",
    "fund_aum_history",
    "fund_fee_rules",
    "fund_subscription_status",
    "fund_lifecycle_events",
    "fund_data_quality",
)


def read_migration_sql() -> str:
    return MIGRATION_FILE.read_text(encoding="utf-8")


def ensure_fund_schema(db_path: Path | None = None) -> dict:
    """建表（幂等）。返回本次执行后各表是否存在与行数。"""
    sql = read_migration_sql()
    with get_connection(db_path) as conn:
        conn.executescript(sql)
        out = {}
        for table in FUND_TABLES:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,)).fetchone() is not None
            rows = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] if exists else None
            out[table] = {"exists": exists, "rows": rows}
    return out


def fund_table_names(conn: sqlite3.Connection | None = None,
                     db_path: Path | None = None) -> list[str]:
    if conn is not None:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'fund\\_%' ESCAPE '\\' "
            "ORDER BY name").fetchall()
        return [r[0] for r in rows]
    with get_connection(db_path) as c:
        return fund_table_names(c)
