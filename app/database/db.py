"""SQLite 初始化、幂等迁移与数据仓储。

阶段1B在保留旧表/旧数据的前提下增加：
- 行情复权字段与质量标记
- 数据源质量字段
- 同步运行与逐基金同步明细表
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from app.config import ensure_runtime_dirs, settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS data_source_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interface_name TEXT NOT NULL,
    function_name TEXT NOT NULL,
    params_json TEXT NOT NULL,
    status TEXT NOT NULL,
    quality_status TEXT NOT NULL DEFAULT 'not_checked',
    quality_issues_json TEXT,
    row_count INTEGER,
    columns_json TEXT,
    start_date TEXT,
    end_date TEXT,
    error_message TEXT,
    tested_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS etf_pool (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    fund_type TEXT,
    tracking_index TEXT,
    established_date TEXT,
    listing_date TEXT,
    listing_date_source TEXT,
    last_trade_date TEXT,
    history_rows INTEGER,
    latest_price REAL,
    data_source TEXT NOT NULL,
    source_tested_at TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS etf_daily_prices (
    code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    amount REAL,
    adjusted_close REAL,
    adjustment_type TEXT NOT NULL DEFAULT 'raw',
    adjustment_snapshot_id INTEGER,
    adjustment_collected_at TEXT,
    adjustment_source TEXT,
    adjustment_coverage_start TEXT,
    adjustment_coverage_end TEXT,
    quality_status TEXT NOT NULL DEFAULT 'valid',
    quality_notes TEXT,
    source TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    PRIMARY KEY (code, trade_date)
);

CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_type TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    total_codes INTEGER NOT NULL DEFAULT 0,
    success_codes INTEGER NOT NULL DEFAULT 0,
    failed_codes INTEGER NOT NULL DEFAULT 0,
    rows_fetched INTEGER NOT NULL DEFAULT 0,
    rows_written INTEGER NOT NULL DEFAULT 0,
    message TEXT
);

CREATE TABLE IF NOT EXISTS sync_details (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    status TEXT NOT NULL,
    rows_fetched INTEGER NOT NULL DEFAULT 0,
    rows_written INTEGER NOT NULL DEFAULT 0,
    coverage_start TEXT,
    coverage_end TEXT,
    quality_status TEXT,
    quality_issues_json TEXT,
    error_message TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    FOREIGN KEY (run_id) REFERENCES sync_runs(id)
);

CREATE TABLE IF NOT EXISTS adjustment_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    total_codes INTEGER NOT NULL DEFAULT 0,
    success_codes INTEGER NOT NULL DEFAULT 0,
    partial_codes INTEGER NOT NULL DEFAULT 0,
    failed_codes INTEGER NOT NULL DEFAULT 0,
    empty_codes INTEGER NOT NULL DEFAULT 0,
    rows_updated INTEGER NOT NULL DEFAULT 0,
    message TEXT
);

CREATE TABLE IF NOT EXISTS trade_calendar (
    trade_date TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS etf_adjustment_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    status TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    source TEXT NOT NULL,
    coverage_start TEXT,
    coverage_end TEXT,
    matched_start TEXT,
    matched_end TEXT,
    raw_rows INTEGER NOT NULL DEFAULT 0,
    qfq_rows INTEGER NOT NULL DEFAULT 0,
    matched_rows INTEGER NOT NULL DEFAULT 0,
    missing_rows INTEGER NOT NULL DEFAULT 0,
    issues_json TEXT,
    error_message TEXT,
    is_current INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES adjustment_runs(id)
);

CREATE TABLE IF NOT EXISTS indicator_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    etf_code TEXT NOT NULL,
    start_date TEXT,
    end_date TEXT,
    indicator_config TEXT NOT NULL,
    adjustment_snapshot_id INTEGER,
    status TEXT NOT NULL,
    valid_rows INTEGER NOT NULL DEFAULT 0,
    missing_rows INTEGER NOT NULL DEFAULT 0,
    calculation_version TEXT NOT NULL,
    summary_json TEXT,
    quality_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS etf_indicator_daily (
    etf_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    adjustment_snapshot_id INTEGER NOT NULL,
    calculation_version TEXT NOT NULL,
    run_id TEXT NOT NULL,
    adjusted_close REAL,
    return_1d REAL,
    return_5d REAL,
    return_10d REAL,
    return_20d REAL,
    return_60d REAL,
    return_120d REAL,
    return_250d REAL,
    cagr REAL,
    ma5 REAL,
    ma10 REAL,
    ma20 REAL,
    ma30 REAL,
    ma60 REAL,
    ma120 REAL,
    ma250 REAL,
    ema12 REAL,
    ema26 REAL,
    rsi6 REAL,
    rsi12 REAL,
    rsi24 REAL,
    macd_dif REAL,
    macd_dea REAL,
    macd_hist REAL,
    volatility_20d REAL,
    volatility_60d REAL,
    volatility_120d REAL,
    max_drawdown_20d REAL,
    max_drawdown_60d REAL,
    max_drawdown_120d REAL,
    max_drawdown_all REAL,
    atr14 REAL,
    sharpe_ratio REAL,
    sortino_ratio REAL,
    calmar_ratio REAL,
    price_status TEXT,
    trade_status TEXT,
    quality_status TEXT NOT NULL,
    quality_reasons TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (etf_code, trade_date, calculation_version, adjustment_snapshot_id)
);

-- 阶段3A：回测引擎表（独立文件 migrations/phase3a_backtest.sql）

CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id TEXT PRIMARY KEY,
    strategy_name TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    config_json TEXT NOT NULL,
    initial_cash REAL NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    etf_codes TEXT NOT NULL,
    indicator_version TEXT,
    snapshot_ids TEXT,
    input_hash TEXT NOT NULL,
    summary_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backtest_daily_nav (
    run_id TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    cash REAL NOT NULL,
    market_value REAL NOT NULL,
    total_assets REAL NOT NULL,
    nav REAL NOT NULL,
    daily_return REAL,
    price_status TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, trade_date)
);

CREATE TABLE IF NOT EXISTS backtest_positions_daily (
    run_id TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    code TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    close_price REAL,
    market_value REAL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, trade_date, code)
);

CREATE TABLE IF NOT EXISTS backtest_orders (
    run_id TEXT NOT NULL,
    order_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    side TEXT NOT NULL,
    signal_date TEXT NOT NULL,
    order_date TEXT NOT NULL,
    fill_date TEXT,
    quantity INTEGER NOT NULL,
    filled_quantity INTEGER NOT NULL DEFAULT 0,
    fill_price REAL,
    status TEXT NOT NULL,
    reason TEXT,
    deferred_days INTEGER NOT NULL DEFAULT 0,
    fee REAL NOT NULL DEFAULT 0,
    slippage_cost REAL NOT NULL DEFAULT 0,
    reference_price REAL,
    target_weight REAL,
    strategy TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, order_id)
);

CREATE TABLE IF NOT EXISTS backtest_trades (
    run_id TEXT NOT NULL,
    trade_id INTEGER NOT NULL,
    order_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    side TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price REAL NOT NULL,
    gross_amount REAL NOT NULL,
    commission REAL NOT NULL,
    slippage_cost REAL NOT NULL,
    realized_pnl REAL NOT NULL DEFAULT 0,
    holding_days REAL,
    cash_after REAL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, trade_id)
);
"""

INDEXES = """
CREATE INDEX IF NOT EXISTS idx_prices_code_date ON etf_daily_prices(code, trade_date);
CREATE INDEX IF NOT EXISTS idx_prices_quality ON etf_daily_prices(quality_status);
CREATE INDEX IF NOT EXISTS idx_prices_snapshot ON etf_daily_prices(adjustment_snapshot_id);
CREATE INDEX IF NOT EXISTS idx_sync_details_code ON sync_details(code);
CREATE INDEX IF NOT EXISTS idx_sync_details_run ON sync_details(run_id);
CREATE INDEX IF NOT EXISTS idx_adj_snap_code ON etf_adjustment_snapshots(code);
CREATE INDEX IF NOT EXISTS idx_adj_snap_run ON etf_adjustment_snapshots(run_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_adj_snap_current
    ON etf_adjustment_snapshots(code) WHERE is_current = 1;
CREATE INDEX IF NOT EXISTS idx_indicator_daily_code_date
    ON etf_indicator_daily(etf_code, trade_date);
CREATE INDEX IF NOT EXISTS idx_indicator_daily_code_version
    ON etf_indicator_daily(etf_code, calculation_version, trade_date);
CREATE INDEX IF NOT EXISTS idx_indicator_runs_code
    ON indicator_runs(etf_code, created_at);
CREATE INDEX IF NOT EXISTS idx_bt_nav_run_date ON backtest_daily_nav(run_id, trade_date);
CREATE INDEX IF NOT EXISTS idx_bt_orders_run ON backtest_orders(run_id, signal_date);
CREATE INDEX IF NOT EXISTS idx_bt_trades_run ON backtest_trades(run_id, trade_date);
CREATE INDEX IF NOT EXISTS idx_bt_positions_run ON backtest_positions_daily(run_id, trade_date);
CREATE INDEX IF NOT EXISTS idx_bt_orders_status ON backtest_orders(run_id, status);
"""

UPSERT_PRICE_SQL = """
INSERT INTO etf_daily_prices
    (code, trade_date, open, high, low, close, volume, amount,
     adjusted_close, adjustment_type, quality_status, quality_notes, source, collected_at)
VALUES
    (:code, :trade_date, :open, :high, :low, :close, :volume, :amount,
     :adjusted_close, :adjustment_type, :quality_status, :quality_notes, :source, :collected_at)
ON CONFLICT(code, trade_date) DO UPDATE SET
    open = excluded.open,
    high = excluded.high,
    low = excluded.low,
    close = excluded.close,
    volume = excluded.volume,
    amount = excluded.amount,
    adjusted_close = COALESCE(excluded.adjusted_close, etf_daily_prices.adjusted_close),
    adjustment_type = excluded.adjustment_type,
    quality_status = excluded.quality_status,
    quality_notes = COALESCE(excluded.quality_notes, etf_daily_prices.quality_notes),
    source = excluded.source,
    collected_at = excluded.collected_at
"""

# 日常同步只更新原始行情，绝不碰 adjusted_close / 快照字段。
UPSERT_RAW_PRICE_SQL = """
INSERT INTO etf_daily_prices
    (code, trade_date, open, high, low, close, volume, amount,
     adjusted_close, adjustment_type, quality_status, quality_notes, source, collected_at)
VALUES
    (:code, :trade_date, :open, :high, :low, :close, :volume, :amount,
     NULL, 'none', :quality_status, :quality_notes, :source, :collected_at)
ON CONFLICT(code, trade_date) DO UPDATE SET
    open = excluded.open,
    high = excluded.high,
    low = excluded.low,
    close = excluded.close,
    volume = excluded.volume,
    amount = excluded.amount,
    source = excluded.source,
    collected_at = excluded.collected_at
"""

APPLY_ADJUSTMENT_SQL = """
UPDATE etf_daily_prices
SET adjusted_close = ?,
    adjustment_type = 'qfq',
    adjustment_snapshot_id = ?,
    adjustment_collected_at = ?,
    adjustment_source = ?,
    adjustment_coverage_start = ?,
    adjustment_coverage_end = ?
WHERE code = ? AND trade_date = ?
"""


@contextmanager
def get_connection(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """获取 SQLite 连接，异常时回滚并向上抛出。"""
    ensure_runtime_dirs()
    path = db_path or settings.database_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    # Windows 下临时目录配置异常时，文件型临时表会报 unable to open database file；
    # 小规模个人行情库使用内存临时表更稳定，同时设置锁等待。
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if column not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _migrate(conn: sqlite3.Connection) -> None:
    """旧库平滑升级；只加列/表，不删除旧数据。"""
    # 阶段1A测试记录没有质量字段，旧记录统一标记为 legacy。
    _add_column_if_missing(conn, "data_source_tests", "quality_status", "TEXT NOT NULL DEFAULT 'legacy'")
    _add_column_if_missing(conn, "data_source_tests", "quality_issues_json", "TEXT")
    # 旧日线表是原始行情，默认按 raw/valid 处理。
    _add_column_if_missing(conn, "etf_daily_prices", "adjusted_close", "REAL")
    _add_column_if_missing(conn, "etf_daily_prices", "adjustment_type", "TEXT NOT NULL DEFAULT 'raw'")
    _add_column_if_missing(conn, "etf_daily_prices", "quality_status", "TEXT NOT NULL DEFAULT 'valid'")
    _add_column_if_missing(conn, "etf_daily_prices", "quality_notes", "TEXT")
    # 阶段1B.1：行级调整快照引用与快照元数据。
    _add_column_if_missing(conn, "etf_daily_prices", "adjustment_snapshot_id", "INTEGER")
    _add_column_if_missing(conn, "etf_daily_prices", "adjustment_collected_at", "TEXT")
    _add_column_if_missing(conn, "etf_daily_prices", "adjustment_source", "TEXT")
    _add_column_if_missing(conn, "etf_daily_prices", "adjustment_coverage_start", "TEXT")
    _add_column_if_missing(conn, "etf_daily_prices", "adjustment_coverage_end", "TEXT")
    _add_column_if_missing(conn, "etf_indicator_daily", "adjusted_close", "REAL")
    # 阶段3A.1：订单剩余未成交数量（独立迁移 migrations/phase3a1_backtest_partial_fill.sql）
    _add_column_if_missing(conn, "backtest_orders", "remaining_quantity", "INTEGER")
    conn.executescript(INDEXES)


def init_db(db_path: Path | None = None) -> None:
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def save_interface_test(record: dict[str, Any], db_path: Path | None = None) -> None:
    """写入一条接口测试记录，调用状态与数据质量分开保存。"""
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO data_source_tests
                (interface_name, function_name, params_json, status, quality_status,
                 quality_issues_json, row_count, columns_json, start_date, end_date,
                 error_message, tested_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["interface_name"],
                record["function_name"],
                json.dumps(record.get("params", {}), ensure_ascii=False),
                record["status"],
                record.get("quality_status", "not_checked"),
                json.dumps(record.get("quality_issues", []), ensure_ascii=False),
                record.get("row_count"),
                json.dumps(record.get("columns", []), ensure_ascii=False),
                record.get("start_date"),
                record.get("end_date"),
                record.get("error_message"),
                record["tested_at"],
            ),
        )


def replace_etf_pool(records: Iterable[dict[str, Any]], db_path: Path | None = None) -> int:
    """用本次验证结果整体替换观察池，避免旧数据残留。"""
    rows = list(records)
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM etf_pool")
        conn.executemany(
            """
            INSERT INTO etf_pool
                (code, name, category, fund_type, tracking_index, established_date,
                 listing_date, listing_date_source, last_trade_date, history_rows,
                 latest_price, data_source, source_tested_at, status)
            VALUES
                (:code, :name, :category, :fund_type, :tracking_index, :established_date,
                 :listing_date, :listing_date_source, :last_trade_date, :history_rows,
                 :latest_price, :data_source, :source_tested_at, :status)
            """,
            rows,
        )
    return len(rows)


def upsert_daily_prices(rows: Iterable[dict[str, Any]], db_path: Path | None = None) -> int:
    """批量 UPSERT 完整日线；空输入直接返回 0，绝不删除已有数据。"""
    records = list(rows)
    if not records:
        return 0
    with get_connection(db_path) as conn:
        conn.executemany(UPSERT_PRICE_SQL, records)
    return len(records)


def upsert_raw_daily_prices(rows: Iterable[dict[str, Any]], db_path: Path | None = None) -> int:
    """只写入原始 OHLC；不触碰 adjusted_close 与调整快照字段。"""
    records = list(rows)
    if not records:
        return 0
    with get_connection(db_path) as conn:
        conn.executemany(UPSERT_RAW_PRICE_SQL, records)
    return len(records)


def get_raw_price_rows(code: str, db_path: Path | None = None) -> list[dict[str, Any]]:
    """读取某只 ETF 已入库的原始行情日期与原始收盘价。"""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT trade_date, close FROM etf_daily_prices WHERE code = ? ORDER BY trade_date",
            (code,),
        ).fetchall()
    return [dict(row) for row in rows]


def start_adjustment_run(total_codes: int, db_path: Path | None = None) -> int:
    from datetime import datetime

    with get_connection(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO adjustment_runs (started_at, status, total_codes) VALUES (?, 'running', ?)",
            (datetime.now().isoformat(timespec="seconds"), total_codes),
        )
        return int(cursor.lastrowid)


def finish_adjustment_run(
    run_id: int,
    *,
    status: str,
    success_codes: int,
    partial_codes: int,
    failed_codes: int,
    empty_codes: int,
    rows_updated: int,
    message: str = "",
    db_path: Path | None = None,
) -> None:
    from datetime import datetime

    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE adjustment_runs
            SET finished_at = ?, status = ?, success_codes = ?, partial_codes = ?,
                failed_codes = ?, empty_codes = ?, rows_updated = ?, message = ?
            WHERE id = ?
            """,
            (
                datetime.now().isoformat(timespec="seconds"),
                status,
                success_codes,
                partial_codes,
                failed_codes,
                empty_codes,
                rows_updated,
                message,
                run_id,
            ),
        )


def _insert_adjustment_snapshot(conn: sqlite3.Connection, snapshot: dict[str, Any]) -> int:
    cursor = conn.execute(
        """
        INSERT INTO etf_adjustment_snapshots
            (run_id, code, status, collected_at, source, coverage_start, coverage_end,
             matched_start, matched_end, raw_rows, qfq_rows, matched_rows, missing_rows,
             issues_json, error_message, is_current, created_at)
        VALUES
            (:run_id, :code, :status, :collected_at, :source, :coverage_start, :coverage_end,
             :matched_start, :matched_end, :raw_rows, :qfq_rows, :matched_rows, :missing_rows,
             :issues_json, :error_message, :is_current, :created_at)
        """,
        snapshot,
    )
    return int(cursor.lastrowid)


def save_adjustment_snapshot(snapshot: dict[str, Any], db_path: Path | None = None) -> int:
    """记录失败/空数据快照，不改变当前有效快照。"""
    payload = dict(snapshot)
    payload.setdefault("is_current", 0)
    payload.setdefault("created_at", payload["collected_at"])
    with get_connection(db_path) as conn:
        return _insert_adjustment_snapshot(conn, payload)


def apply_adjustment_snapshot(
    snapshot: dict[str, Any],
    rows: Iterable[dict[str, Any]],
    db_path: Path | None = None,
) -> int:
    """在单只基金事务内激活新快照并更新所有行，原始 OHLC 不变。"""
    from datetime import datetime

    updates = list(rows)
    if not updates:
        raise ValueError("调整快照更新行为空")
    payload = dict(snapshot)
    payload.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
    payload["is_current"] = 0

    with get_connection(db_path) as conn:
        snapshot_id = _insert_adjustment_snapshot(conn, payload)
        conn.execute(
            "UPDATE etf_adjustment_snapshots SET is_current = 0 WHERE code = ? AND is_current = 1",
            (payload["code"],),
        )
        conn.execute(
            "UPDATE etf_adjustment_snapshots SET is_current = 1 WHERE id = ?",
            (snapshot_id,),
        )
        conn.executemany(
            APPLY_ADJUSTMENT_SQL,
            [
                (
                    row["adjusted_close"],
                    snapshot_id,
                    payload["collected_at"],
                    payload["source"],
                    payload["coverage_start"],
                    payload["coverage_end"],
                    payload["code"],
                    row["trade_date"],
                )
                for row in updates
            ],
        )
    return snapshot_id


def get_current_adjustment_snapshot(code: str, db_path: Path | None = None) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM etf_adjustment_snapshots WHERE code = ? AND is_current = 1",
            (code,),
        ).fetchone()
    return dict(row) if row else None


def get_recent_adjustment_runs(limit: int = 10, db_path: Path | None = None) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM adjustment_runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]


def get_adjustment_summary(db_path: Path | None = None) -> dict[str, Any]:
    """调整快照完整性与混合快照统计。"""
    with get_connection(db_path) as conn:
        current_total = int(
            conn.execute(
                "SELECT COUNT(*) FROM etf_adjustment_snapshots WHERE is_current = 1"
            ).fetchone()[0]
        )
        partial = int(
            conn.execute(
                "SELECT COUNT(*) FROM etf_adjustment_snapshots "
                "WHERE is_current = 1 AND status = 'partial'"
            ).fetchone()[0]
        )
        failed_current = int(
            conn.execute(
                "SELECT COUNT(*) FROM etf_adjustment_snapshots "
                "WHERE is_current = 1 AND status NOT IN ('success', 'partial')"
            ).fetchone()[0]
        )
        mixed = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT code FROM etf_daily_prices
                    WHERE adjustment_snapshot_id IS NOT NULL
                    GROUP BY code HAVING COUNT(DISTINCT adjustment_snapshot_id) > 1
                )
                """
            ).fetchone()[0]
        )
        adjusted_missing = int(
            conn.execute(
                "SELECT COUNT(*) FROM etf_daily_prices WHERE adjusted_close IS NULL"
            ).fetchone()[0]
        )
        last_run = conn.execute(
            "SELECT id, finished_at, status FROM adjustment_runs "
            "WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return {
        "current_snapshot_etfs": current_total,
        "partial_snapshot_etfs": partial,
        "failed_current_snapshots": failed_current,
        "mixed_snapshot_etfs": mixed,
        "adjusted_missing_records": adjusted_missing,
        "last_adjustment_refresh_at": last_run["finished_at"] if last_run else None,
        "last_adjustment_refresh_status": last_run["status"] if last_run else None,
        "last_adjustment_run_id": int(last_run["id"]) if last_run else None,
    }


def update_pool_market_stats(
    code: str,
    last_trade_date: str,
    latest_price: float,
    history_rows: int,
    db_path: Path | None = None,
) -> None:
    """用入库结果刷新观察池的最新行情摘要。"""
    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE etf_pool
            SET last_trade_date = ?, latest_price = ?, history_rows = ?
            WHERE code = ?
            """,
            (last_trade_date, latest_price, history_rows, code),
        )


def replace_trade_calendar(dates: Iterable[str], db_path: Path | None = None) -> int:
    """UPSERT 交易日历；不删除已有日期。"""
    rows = [(str(value),) for value in dates if str(value)]
    if not rows:
        return 0
    with get_connection(db_path) as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO trade_calendar (trade_date) VALUES (?)", rows
        )
    return len(rows)


def get_trade_calendar(
    start_date: str | None = None,
    end_date: str | None = None,
    db_path: Path | None = None,
) -> list[str]:
    clauses: list[str] = []
    params: list[Any] = []
    if start_date:
        clauses.append("trade_date >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("trade_date <= ?")
        params.append(end_date)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_connection(db_path) as conn:
        return [
            str(row[0])
            for row in conn.execute(
                f"SELECT trade_date FROM trade_calendar {where} ORDER BY trade_date", params
            )
        ]


def get_pool_codes(db_path: Path | None = None) -> list[str]:
    with get_connection(db_path) as conn:
        return [str(row[0]) for row in conn.execute("SELECT code FROM etf_pool ORDER BY code")]


def get_latest_trade_date(code: str, db_path: Path | None = None) -> str | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT MAX(trade_date) FROM etf_daily_prices WHERE code = ?", (code,)
        ).fetchone()
    return None if row is None or row[0] is None else str(row[0])


def count_prices_for_code(code: str, db_path: Path | None = None) -> int:
    with get_connection(db_path) as conn:
        return int(
            conn.execute("SELECT COUNT(*) FROM etf_daily_prices WHERE code = ?", (code,)).fetchone()[0]
        )


def get_price_source_map(
    code: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    db_path: Path | None = None,
) -> dict[str, dict[str, Any]]:
    """读取已有行情的日期、收盘价、来源，用于跨来源冲突检测。"""
    clauses = ["code = ?"]
    params: list[Any] = [code]
    if start_date:
        clauses.append("trade_date >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("trade_date <= ?")
        params.append(end_date)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT trade_date, close, source FROM etf_daily_prices WHERE {' AND '.join(clauses)}",
            params,
        ).fetchall()
    return {str(row["trade_date"]): dict(row) for row in rows}


def start_sync_run(run_type: str, total_codes: int, db_path: Path | None = None) -> int:
    from datetime import datetime

    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO sync_runs (run_type, started_at, status, total_codes)
            VALUES (?, ?, 'running', ?)
            """,
            (run_type, datetime.now().isoformat(timespec="seconds"), total_codes),
        )
        return int(cursor.lastrowid)


def finish_sync_run(
    run_id: int,
    *,
    status: str,
    success_codes: int,
    failed_codes: int,
    rows_fetched: int,
    rows_written: int,
    message: str = "",
    db_path: Path | None = None,
) -> None:
    from datetime import datetime

    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE sync_runs
            SET finished_at = ?, status = ?, success_codes = ?, failed_codes = ?,
                rows_fetched = ?, rows_written = ?, message = ?
            WHERE id = ?
            """,
            (
                datetime.now().isoformat(timespec="seconds"),
                status,
                success_codes,
                failed_codes,
                rows_fetched,
                rows_written,
                message,
                run_id,
            ),
        )


def save_sync_detail(detail: dict[str, Any], db_path: Path | None = None) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO sync_details
                (run_id, code, status, rows_fetched, rows_written, coverage_start,
                 coverage_end, quality_status, quality_issues_json, error_message,
                 started_at, finished_at)
            VALUES
                (:run_id, :code, :status, :rows_fetched, :rows_written, :coverage_start,
                 :coverage_end, :quality_status, :quality_issues_json, :error_message,
                 :started_at, :finished_at)
            """,
            detail,
        )


def get_market_data_summary(db_path: Path | None = None) -> dict[str, Any]:
    """返回 API/看板使用的行情覆盖摘要。"""
    with get_connection(db_path) as conn:
        pool_total = int(conn.execute("SELECT COUNT(*) FROM etf_pool").fetchone()[0])
        ingested_total = int(
            conn.execute("SELECT COUNT(DISTINCT code) FROM etf_daily_prices").fetchone()[0]
        )
        record_total = int(conn.execute("SELECT COUNT(*) FROM etf_daily_prices").fetchone()[0])
        anomaly_rows = int(
            conn.execute(
                "SELECT COUNT(*) FROM etf_daily_prices WHERE quality_status != 'valid'"
            ).fetchone()[0]
        )
        quality_counts = {
            str(row["quality_status"]): int(row["count"])
            for row in conn.execute(
                "SELECT quality_status, COUNT(*) AS count FROM etf_daily_prices GROUP BY quality_status"
            ).fetchall()
        }
        last_collected_row = conn.execute(
            "SELECT MAX(collected_at) FROM etf_daily_prices"
        ).fetchone()
        coverage_rows = conn.execute(
            """
            SELECT p.code, p.name, p.category,
                   MIN(d.trade_date) AS start_date,
                   MAX(d.trade_date) AS end_date,
                   COUNT(d.code) AS record_count,
                   SUM(CASE WHEN d.quality_status != 'valid' THEN 1 ELSE 0 END) AS anomaly_count,
                   MAX(s.id) AS adjustment_snapshot_id,
                   MAX(s.status) AS adjustment_status,
                   MAX(s.collected_at) AS adjustment_collected_at,
                   MAX(s.coverage_start) AS adjustment_coverage_start,
                   MAX(s.coverage_end) AS adjustment_coverage_end,
                   MAX(s.missing_rows) AS adjustment_missing_rows
            FROM etf_pool p
            LEFT JOIN etf_daily_prices d ON d.code = p.code
            LEFT JOIN etf_adjustment_snapshots s ON s.code = p.code AND s.is_current = 1
            GROUP BY p.code, p.name, p.category
            ORDER BY p.category, p.code
            """
        ).fetchall()
        missing_rows = conn.execute(
            """
            SELECT p.code, p.name
            FROM etf_pool p
            LEFT JOIN (SELECT DISTINCT code FROM etf_daily_prices) d ON d.code = p.code
            WHERE d.code IS NULL
            ORDER BY p.code
            """
        ).fetchall()
        last_sync = conn.execute(
            "SELECT id, finished_at, status FROM sync_runs WHERE finished_at IS NOT NULL "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()

    coverage = [dict(row) for row in coverage_rows]
    for row in coverage:
        row["record_count"] = int(row["record_count"] or 0)
        row["anomaly_count"] = int(row["anomaly_count"] or 0)
        row["adjustment_missing_rows"] = int(row["adjustment_missing_rows"] or 0)
        row["has_data"] = row["record_count"] > 0
    adjustment = get_adjustment_summary(db_path)
    return {
        "etf_total": pool_total,
        "etf_ingested": ingested_total,
        "total_records": record_total,
        "last_sync_at": last_sync["finished_at"] if last_sync else None,
        "last_sync_status": last_sync["status"] if last_sync else None,
        "last_sync_run_id": int(last_sync["id"]) if last_sync else None,
        "last_price_collected_at": last_collected_row[0] if last_collected_row else None,
        "missing_etf_count": len(missing_rows),
        "missing_etfs": [dict(row) for row in missing_rows],
        "anomaly_record_count": anomaly_rows,
        "quality_counts": quality_counts,
        "adjustment": adjustment,
        "coverage": coverage,
    }


def get_market_prices(
    code: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 500,
    offset: int = 0,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    clauses = ["code = ?"]
    params: list[Any] = [code]
    if start_date:
        clauses.append("trade_date >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("trade_date <= ?")
        params.append(end_date)
    params.extend([limit, offset])
    sql = f"""
        SELECT code, trade_date, open, high, low, close, volume, amount,
               adjusted_close, adjustment_type, adjustment_snapshot_id,
               adjustment_collected_at, adjustment_source,
               adjustment_coverage_start, adjustment_coverage_end,
               quality_status, quality_notes, source, collected_at
        FROM etf_daily_prices
        WHERE {' AND '.join(clauses)}
        ORDER BY trade_date ASC
        LIMIT ? OFFSET ?
    """
    with get_connection(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def get_market_price_count(
    code: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    db_path: Path | None = None,
) -> int:
    clauses = ["code = ?"]
    params: list[Any] = [code]
    if start_date:
        clauses.append("trade_date >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("trade_date <= ?")
        params.append(end_date)
    with get_connection(db_path) as conn:
        return int(
            conn.execute(
                f"SELECT COUNT(*) FROM etf_daily_prices WHERE {' AND '.join(clauses)}", params
            ).fetchone()[0]
        )


def get_etf_exists(code: str, db_path: Path | None = None) -> bool:
    with get_connection(db_path) as conn:
        return conn.execute("SELECT 1 FROM etf_pool WHERE code = ?", (code,)).fetchone() is not None


def get_etf_name(code: str, db_path: Path | None = None) -> str | None:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT name FROM etf_pool WHERE code = ?", (code,)).fetchone()
    return None if row is None else str(row[0])


def get_recent_sync_runs(limit: int = 10, db_path: Path | None = None) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM sync_runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]


def get_sync_details(run_id: int, db_path: Path | None = None) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM sync_details WHERE run_id = ? ORDER BY code", (run_id,)
        ).fetchall()
    return [dict(row) for row in rows]


def count_rows(table: str, db_path: Path | None = None) -> int:
    allowed = {
        "data_source_tests",
        "etf_pool",
        "etf_daily_prices",
        "sync_runs",
        "sync_details",
        "adjustment_runs",
        "etf_adjustment_snapshots",
        "trade_calendar",
        "indicator_runs",
        "etf_indicator_daily",
        "backtest_runs",
        "backtest_daily_nav",
        "backtest_orders",
        "backtest_trades",
        "backtest_positions_daily",
    }
    if table not in allowed:
        raise ValueError(f"不允许查询表：{table}")
    with get_connection(db_path) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
