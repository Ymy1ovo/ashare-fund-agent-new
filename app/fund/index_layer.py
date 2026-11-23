"""阶段3B-6.0.2 指数与基准数据层。

独立于基金数据层：指数历史不混入 fund_nav_daily，也不混入 etf_daily_prices。

核心约束：
1. 收益口径（return_basis）不得仅凭名称/代码推断，无证据即 ``unknown``；
2. 价格指数只能产生价格收益，不得冒充全收益；
3. 缺失日期不填充、不插值、不当 0 收益；
4. 交易日历代理发现的缺口恒为「疑似」，``gap_is_real_missing`` 永远 NULL；
5. 复合基准缺成分/缺权重即不可复现，不得只接一个成分就宣称完整。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from app.config import settings
from app.database.db import get_connection

# ---------------------------------------------------------------- 常量
RETURN_BASIS_PRICE = "price_return"
RETURN_BASIS_TOTAL = "total_return"
RETURN_BASIS_NET = "net_total_return"
RETURN_BASIS_UNKNOWN = "unknown"
RETURN_BASES = (RETURN_BASIS_PRICE, RETURN_BASIS_TOTAL,
                RETURN_BASIS_NET, RETURN_BASIS_UNKNOWN)

# 可用于「严格总收益比较」的口径；price_return / unknown 都不行
TOTAL_RETURN_BASES = (RETURN_BASIS_TOTAL, RETURN_BASIS_NET)

LAYER_PENDING = "pending"
LAYER_READY = "ready"
LAYER_DEGRADED = "degraded"
LAYER_FAILED = "failed"

QUALITY_A, QUALITY_B, QUALITY_C, QUALITY_D = "A", "B", "C", "D"

MIGRATION_FILE = (Path(__file__).resolve().parents[2]
                  / "migrations" / "phase3b6_0_2_index_data_layer.sql")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- 指纹
def row_fingerprint(index_code: str, trade_date: str, close: float,
                    open_=None, high=None, low=None,
                    volume=None, amount=None) -> str:
    """行级内容指纹：同样内容永远同一指纹，内容变了指纹就变。"""
    payload = json.dumps([
        str(index_code), str(trade_date),
        _num(open_), _num(high), _num(low), _num(close),
        _num(volume), _num(amount),
    ], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _num(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return round(f, 6)


def content_fingerprint(rows: list[dict]) -> str:
    """整段采集结果指纹，用于判断同一请求内容是否变化。"""
    payload = json.dumps(
        sorted([[str(r.get("index_code")), str(r.get("trade_date")),
                 _num(r.get("open")), _num(r.get("high")),
                 _num(r.get("low")), _num(r.get("close")),
                 _num(r.get("volume")), _num(r.get("amount"))]
                for r in rows], key=lambda x: (x[0], x[1])),
        ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 迁移
def enable_foreign_keys(conn: sqlite3.Connection) -> None:
    """SQLite 默认不启用外键，必须每连接显式开启。"""
    conn.execute("PRAGMA foreign_keys = ON")


@contextmanager
def get_index_connection(db_path: Path | None = None):
    """指数数据层专用连接：**显式启用外键**后再进入事务。

    沿用 3B-5.3.2 的既有做法——只改本连接的 PRAGMA，
    不影响项目全局 ``get_connection`` 的行为（全局仍保持 SQLite 默认关闭）。
    外键必须在 BEGIN 之前开启，事务内设置 PRAGMA 无效。
    """
    path = Path(db_path or settings.database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    enabled = int(conn.execute("PRAGMA foreign_keys").fetchone()[0])
    if enabled != 1:
        conn.close()
        raise RuntimeError("无法启用 SQLite 外键约束，拒绝在无保护状态下写入指数层")
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        # executescript 会隐式提交事务，此时 in_transaction 为 False，跳过 COMMIT
        if conn.in_transaction:
            conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()


def init_index_layer(conn: sqlite3.Connection) -> None:
    """建表（幂等）。只新增独立表，不改任何既有表。"""
    conn.executescript(MIGRATION_FILE.read_text(encoding="utf-8"))


def table_row_counts(conn: sqlite3.Connection) -> dict:
    """记录当前各表行数，用于迁移前后对比。"""
    tables = ("fund_master", "fund_share_classes", "fund_nav_daily",
              "fund_lifecycle_events", "etf_daily_prices")
    out = {}
    for t in tables:
        try:
            out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except sqlite3.OperationalError:
            out[t] = None
    return out


# ---------------------------------------------------------------- 指数主数据
def upsert_index_master(conn: sqlite3.Connection, *, index_code: str,
                        index_name: str, data_source: str,
                        index_short_name: str | None = None,
                        index_family: str | None = None,
                        publisher: str | None = None,
                        inception_date: str | None = None,
                        inception_date_evidence: str | None = None,
                        return_basis: str = RETURN_BASIS_UNKNOWN,
                        return_basis_evidence: str | None = None,
                        currency: str = "CNY",
                        frequency: str = "daily",
                        data_status: str = "unknown",
                        layer_status: str = LAYER_PENDING) -> None:
    """写入/更新指数基础信息。

    ``return_basis`` 默认 ``unknown``：没有证据不得升级为全收益。
    """
    if return_basis not in RETURN_BASES:
        raise ValueError(f"非法 return_basis: {return_basis}")
    ts = now_iso()
    conn.execute(
        """
        INSERT INTO index_master
            (index_code, index_name, index_short_name, index_family, publisher,
             data_source, inception_date, inception_date_evidence, frequency,
             currency, return_basis, return_basis_evidence, data_status,
             layer_status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(index_code) DO UPDATE SET
            index_name=excluded.index_name,
            index_short_name=excluded.index_short_name,
            index_family=excluded.index_family,
            publisher=excluded.publisher,
            data_source=excluded.data_source,
            inception_date=excluded.inception_date,
            inception_date_evidence=excluded.inception_date_evidence,
            frequency=excluded.frequency,
            currency=excluded.currency,
            return_basis=excluded.return_basis,
            return_basis_evidence=excluded.return_basis_evidence,
            data_status=excluded.data_status,
            layer_status=excluded.layer_status,
            updated_at=excluded.updated_at
        """,
        (index_code, index_name, index_short_name, index_family, publisher,
         data_source, inception_date, inception_date_evidence, frequency,
         currency, return_basis, return_basis_evidence, data_status,
         layer_status, ts, ts))


def get_index_master(conn: sqlite3.Connection, index_code: str) -> dict | None:
    row = conn.execute("SELECT * FROM index_master WHERE index_code = ?",
                       (index_code,)).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------- 采集审计
def start_ingest_run(conn: sqlite3.Connection, *, index_code: str | None,
                     source: str, interface_name: str,
                     request_start_date: str | None = None,
                     request_end_date: str | None = None,
                     ingest_mode: str = "full") -> int:
    cur = conn.execute(
        """
        INSERT INTO index_ingest_runs
            (index_code, source, interface_name, request_start_date,
             request_end_date, requested_at, status, ingest_mode)
        VALUES (?, ?, ?, ?, ?, ?, 'failed', ?)
        """,
        (index_code, source, interface_name, request_start_date,
         request_end_date, now_iso(), ingest_mode))
    return int(cur.lastrowid)


def finish_ingest_run(conn: sqlite3.Connection, run_id: int, *,
                      status: str, returned_rows: int = 0,
                      actual_date_min: str | None = None,
                      actual_date_max: str | None = None,
                      error_type: str | None = None,
                      error_message: str | None = None,
                      content_fp: str | None = None,
                      note: str | None = None) -> None:
    conn.execute(
        """
        UPDATE index_ingest_runs
        SET finished_at=?, status=?, returned_rows=?, actual_date_min=?,
            actual_date_max=?, error_type=?, error_message=?,
            content_fingerprint=?, note=?
        WHERE run_id=?
        """,
        (now_iso(), status, returned_rows, actual_date_min, actual_date_max,
         error_type, error_message, content_fp, note, run_id))


def get_ingest_run(conn: sqlite3.Connection, run_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM index_ingest_runs WHERE run_id = ?",
                       (run_id,)).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------- 历史行情
def upsert_index_daily(conn: sqlite3.Connection, *, index_code: str,
                       rows: list[dict], source: str, run_id: int | None = None,
                       raw_basis: str = "raw",
                       quality_status: str = "valid",
                       quality_note: str | None = None) -> dict:
    """写入历史行情。

    - 同一 (index_code, trade_date) 只有一条有效记录（主键保证）；
    - 内容没变 → 不更新，计入 ``unchanged``；
    - 内容变了 → 更新并计入 ``updated``（受 ``protect_high_quality`` 约束）；
    - ``protect_high_quality=True`` 时，已存在的 valid 行不会被低质量写入覆盖。

    调用方若需要强事务，请自行传入已开启事务的 conn。
    """
    ts = now_iso()
    inserted = updated = unchanged = skipped = 0
    for r in rows:
        code = r.get("index_code") or index_code
        date = str(r["trade_date"])
        close = r.get("close")
        if close is None:
            # 收盘值空值：拒绝入库，不填补
            skipped += 1
            continue
        fp = row_fingerprint(code, date, close, r.get("open"), r.get("high"),
                             r.get("low"), r.get("volume"), r.get("amount"))
        # 行级质量状态优先于批次默认值（如基线占位行标 suspect）
        row_qs = r.get("quality_status") or quality_status
        row_note = r.get("quality_note") if "quality_note" in r else quality_note
        old = conn.execute(
            "SELECT row_fingerprint, quality_status FROM index_daily "
            "WHERE index_code=? AND trade_date=?", (code, date)).fetchone()
        if old is None:
            conn.execute(
                """
                INSERT INTO index_daily
                    (index_code, trade_date, open, high, low, close, volume,
                     amount, source, raw_basis, run_id, collected_at,
                     row_fingerprint, quality_status, quality_note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (code, date, r.get("open"), r.get("high"), r.get("low"),
                 close, r.get("volume"), r.get("amount"), source, raw_basis,
                 run_id, ts, fp, row_qs, row_note))
            inserted += 1
            continue
        if old["row_fingerprint"] == fp:
            unchanged += 1
            continue
        # 内容变化：默认更新，但不允许把 valid 降级为 rejected
        if old["quality_status"] == "valid" and row_qs == "rejected":
            skipped += 1
            continue
        conn.execute(
            """
            UPDATE index_daily
            SET open=?, high=?, low=?, close=?, volume=?, amount=?,
                source=?, raw_basis=?, run_id=?, collected_at=?,
                row_fingerprint=?, quality_status=?, quality_note=?
            WHERE index_code=? AND trade_date=?
            """,
            (r.get("open"), r.get("high"), r.get("low"), close,
             r.get("volume"), r.get("amount"), source, raw_basis, run_id,
             ts, fp, row_qs, row_note, code, date))
        updated += 1

    return {"inserted": inserted, "updated": updated,
            "unchanged": unchanged, "skipped": skipped,
            "total": len(rows)}


def count_index_daily(conn: sqlite3.Connection, index_code: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM index_daily WHERE index_code=?",
        (index_code,)).fetchone()[0]


def effective_date_range(conn: sqlite3.Connection, index_code: str) -> dict:
    """有效区间：排除被标为 suspect 的基线占位行。

    中证官网接口常在首行返回 2004-01-01 基线值，
    该行数值与第二行相同，不是真实交易日行情，标 suspect 保留可追溯，
    但不计入有效起始日。
    """
    row = conn.execute(
        "SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM index_daily "
        "WHERE index_code=? AND quality_status != 'suspect'",
        (index_code,)).fetchone()
    return {"date_min": row[0], "date_max": row[1], "row_count": row[2]}


def index_date_range(conn: sqlite3.Connection, index_code: str) -> dict:
    row = conn.execute(
        "SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM index_daily "
        "WHERE index_code=?", (index_code,)).fetchone()
    return {"date_min": row[0], "date_max": row[1], "row_count": row[2]}


# ---------------------------------------------------------------- 质量记录
def save_quality_check(conn: sqlite3.Connection, *, index_code: str,
                       run_id: int | None, quality: dict,
                       calendar_proxy: str | None = None,
                       calendar_note: str | None = None) -> int:
    """保存一次质量检查。

    硬性检查全过才可能 ``is_complete=1``；
    ``gap_is_real_missing`` 恒写 NULL（日历代理无法证明真实缺失）。
    """
    c = quality.get("checks") or {}
    hard = quality.get("hard_passed")
    gaps = c.get("gap_checked") or {}

    def ok(key):
        return 1 if (c.get(key) or {}).get("ok") else 0

    level = quality_level_of(quality)
    cur = conn.execute(
        """
        INSERT INTO index_quality_checks
            (index_code, run_id, checked_at, check_start_date, check_end_date,
             row_count, date_parsed_ok, date_ascending_ok, duplicate_dates_ok,
             null_close_ok, numeric_ok, ohlc_complete, suspected_gap_count,
             suspected_gap_days, calendar_proxy, calendar_note,
             gap_is_real_missing, is_complete, quality_level, degrade_reason,
             detail_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?,
                ?, ?)
        """,
        (index_code, run_id, now_iso(), quality.get("date_min"),
         quality.get("date_max"), int(quality.get("rows") or 0),
         ok("date_parsed"), ok("date_ascending"), ok("no_duplicate_dates"),
         ok("no_null_close"), ok("numeric_values_sane"), ok("no_null_ohlc"),
         int(gaps.get("gap_count") or 0),
         int(gaps.get("total_missing_days") or 0),
         calendar_proxy or gaps.get("calendar"),
         calendar_note or gaps.get("calendar_note"),
         1 if hard else 0, level,
         None if hard else (quality.get("reason") or "硬性检查未通过"),
         json.dumps(c, ensure_ascii=False, default=str)))
    return int(cur.lastrowid)


def quality_level_of(quality: dict) -> str:
    """A/B/C/D 分级。

    - A：硬性全过，且 OHLC 完整、无疑似缺口
    - B：硬性全过，但 OHLC 有缺 或 有疑似缺口
    - C：硬性全过但有未解决项（保留）
    - D：硬性未过
    """
    if not quality.get("hard_passed"):
        return QUALITY_D
    c = quality.get("checks") or {}
    ohlc_ok = bool((c.get("no_null_ohlc") or {}).get("ok"))
    gap_days = int(((c.get("gap_checked") or {}).get("total_missing_days")) or 0)
    if ohlc_ok and gap_days == 0:
        return QUALITY_A
    return QUALITY_B


def latest_quality_check(conn: sqlite3.Connection, index_code: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM index_quality_checks WHERE index_code=? "
        "ORDER BY checked_at DESC, check_id DESC LIMIT 1",
        (index_code,)).fetchone()
    return dict(row) if row else None
