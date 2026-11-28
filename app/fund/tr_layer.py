"""阶段3B-6.2.3.1.1 全收益指数独立原始数据层。

**与 index_daily 完全物理隔离**：

- 只操作 ``tr_*`` 前缀的表；
- 不读不写 ``index_daily`` / ``index_master``；
- 原始数据原样归档，**不清洗、不插值、不修正**。

设计要点：

1. 候选注册表保留市场/口径/日历/连续性/真实起点等全部审计状态
2. 逐行质量标记，未验证行**不默认为有效行情**
3. 导入幂等（主键去重）+ 事务原子性 + 失败回滚
4. 每次导入记录 index_daily 前后行数与指纹，证明未触碰
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION_UP = ROOT / "migrations" / "phase3b6_2_3_1_1_total_return_layer.sql"
MIGRATION_DOWN = (ROOT / "migrations"
                  / "phase3b6_2_3_1_1_total_return_layer_down.sql")

TR_TABLES = (
    "tr_candidate_master",
    "tr_evidence_files",
    "tr_ingest_runs",
    "tr_index_daily_raw",
    "tr_candidate_quality",
    "tr_price_index_mapping",
)

# 逐行质量状态（**不含 verified/normal_verified**，未验证行不得默认有效）
ROW_QUALITY_STATES = (
    "normal_unverified",
    "suspected_synthetic",
    "suspected_market_closed_placeholder",
    "invalid_value",
    "unknown",
)

# 连续性五态
CONTINUITY_STATES = (
    "verified_official_calendar",
    "verified_against_proxy_calendar",
    "has_unresolved_suspicion",
    "has_issues",
    "unknown",
)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def get_tr_connection(db_path: Path | None = None):
    """全收益层专用连接。

    支持 ``TR_LAYER_DB_OVERRIDE`` 环境变量指向数据库副本，
    便于在**不触碰正式库**的前提下验证导入幂等性。
    """
    import os
    from app.database.db import get_connection
    if db_path is None:
        ov = os.environ.get("TR_LAYER_DB_OVERRIDE")
        if ov:
            db_path = Path(ov)
    return get_connection(db_path)


def enable_foreign_keys(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON")


def init_tr_layer(conn: sqlite3.Connection) -> dict:
    """建表（幂等）。返回各表是否存在与行数。"""
    enable_foreign_keys(conn)
    conn.executescript(MIGRATION_UP.read_text(encoding="utf-8"))
    return tr_table_counts(conn)


def rollback_tr_layer(conn: sqlite3.Connection) -> dict:
    """回滚：只删 tr_* 表，**不触碰任何现有表**。"""
    enable_foreign_keys(conn)
    before = tr_table_counts(conn)
    conn.executescript(MIGRATION_DOWN.read_text(encoding="utf-8"))
    return {"before": before, "after": tr_table_counts(conn)}


def tr_table_counts(conn: sqlite3.Connection) -> dict:
    out = {}
    for t in TR_TABLES:
        exists = conn.execute(
            "select count(*) from sqlite_master where type='table' and name=?",
            (t,)).fetchone()[0]
        if exists:
            out[t] = conn.execute(f"select count(*) from {t}").fetchone()[0]
        else:
            out[t] = None
    return out


def index_daily_fingerprint(conn: sqlite3.Connection) -> dict:
    """index_daily 内容指纹（用于证明本层未触碰它）。"""
    rows = conn.execute(
        "select index_code, trade_date, close, quality_status "
        "from index_daily order by index_code, trade_date").fetchall()
    h = hashlib.sha256()
    for r in rows:
        h.update(f"{r[0]}|{r[1]}|{r[2]}|{r[3]}\n".encode())
    return {"row_count": len(rows), "fingerprint": h.hexdigest()}


# 指纹覆盖的**全部**原始行情字段，顺序固定。
FINGERPRINT_FIELDS = (
    "tr_code", "trade_date", "open", "high", "low", "close",
    "volume", "amount", "change", "change_pct",
    "cons_number", "peg", "returned_code", "returned_name",
)


def row_fingerprint(rec: dict) -> str:
    """单行内容指纹：覆盖**所有保存的原始行情字段**，顺序固定。

    序列化规则固定为 ``字段名=repr(值)`` 逐行拼接，
    保证同一数据永远产生同一指纹，任一字段变化都会改变指纹。
    """
    h = hashlib.sha256()
    for k in FINGERPRINT_FIELDS:
        h.update(f"{k}={rec.get(k)!r}\n".encode())
    return h.hexdigest()


# ---------------------------------------------------------------- 候选注册
def upsert_candidate(conn: sqlite3.Connection, cand: dict) -> str:
    """写入/更新候选注册（幂等）。返回 'inserted' 或 'updated'。"""
    code = cand["tr_code"]
    exists = conn.execute(
        "select count(*) from tr_candidate_master where tr_code=?",
        (code,)).fetchone()[0]
    cols = (
        "tr_code", "price_index_code", "official_full_name",
        "official_short_name", "publisher", "official_basic_date",
        "official_publish_date", "official_basic_index", "market_group",
        "market_label", "return_basis", "calendar_type",
        "calendar_available", "calendar_is_official", "calendar_note",
        "mapping_verified", "mapping_evidence_level", "base_date_match",
        "continuity_level", "real_history_start", "synthetic_start_status",
        "data_quality_verified", "non_positive_close_count",
        "raw_data_layer_ingest_candidate", "validated_series_candidate",
        "proxy_qualified_series_candidate", "formal_series_admitted",
        "source_audit_json", "source_evidence_manifest", "layer_version",
    )
    # NOT NULL 字段的默认值（调用方未提供时用保守默认）
    defaults = {
        "market_group": "stock", "return_basis": "unknown",
        "calendar_type": "unknown", "calendar_available": 0,
        "calendar_is_official": 0, "mapping_verified": 0,
        "mapping_evidence_level": "none", "continuity_level": "unknown",
        "real_history_start": "unknown", "synthetic_start_status": "unknown",
        "data_quality_verified": 0, "non_positive_close_count": 0,
        "raw_data_layer_ingest_candidate": 0,
        "validated_series_candidate": 0,
        "proxy_qualified_series_candidate": 0,
        "formal_series_admitted": 0, "layer_version": "tr-v1",
    }
    vals = [cand.get(c) if cand.get(c) is not None else defaults.get(c)
            for c in cols]
    now = now_iso()
    if exists:
        sets = ", ".join(f"{c}=?" for c in cols if c != "tr_code")
        conn.execute(
            f"update tr_candidate_master set {sets}, updated_at=? "
            f"where tr_code=?",
            [v for c, v in zip(cols, vals) if c != "tr_code"] + [now, code])
        return "updated"
    placeholders = ", ".join("?" for _ in cols)
    conn.execute(
        f"insert into tr_candidate_master ({', '.join(cols)}, "
        f"created_at, updated_at) values ({placeholders}, ?, ?)",
        vals + [now, now])
    return "inserted"


def get_candidate(conn: sqlite3.Connection, tr_code: str) -> dict | None:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "select * from tr_candidate_master where tr_code=?",
        (tr_code,)).fetchone()
    return dict(row) if row else None


def list_candidates(conn: sqlite3.Connection) -> list[dict]:
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(
        "select * from tr_candidate_master order by tr_code")]


# ---------------------------------------------------------------- 证据
def upsert_evidence(conn: sqlite3.Connection, ev: dict) -> str:
    rel = ev["relative_path"]
    exists = conn.execute(
        "select count(*) from tr_evidence_files where relative_path=?",
        (rel,)).fetchone()[0]
    if exists:
        conn.execute(
            "update tr_evidence_files set evidence_kind=?, subject_code=?, "
            "bytes=?, sha256=?, request_url=?, obtained_at=?, "
            "original_manifest_sha256=?, manifest_verified=? "
            "where relative_path=?",
            (ev.get("evidence_kind"), ev.get("subject_code"), ev.get("bytes"),
             ev.get("sha256"), ev.get("request_url"), ev.get("obtained_at"),
             ev.get("original_manifest_sha256"),
             ev.get("manifest_verified"), rel))
        return "updated"
    conn.execute(
        "insert into tr_evidence_files (relative_path, evidence_kind, "
        "subject_code, bytes, sha256, request_url, obtained_at, "
        "original_manifest_sha256, manifest_verified, created_at) "
        "values (?,?,?,?,?,?,?,?,?,?)",
        (rel, ev.get("evidence_kind"), ev.get("subject_code"), ev.get("bytes"),
         ev.get("sha256"), ev.get("request_url"), ev.get("obtained_at"),
         ev.get("original_manifest_sha256"), ev.get("manifest_verified"),
         now_iso()))
    return "inserted"


# ---------------------------------------------------------------- 批次
def start_run(conn: sqlite3.Connection, batch_key: str) -> int:
    """幂等：同一 batch_key 重复导入时复用已有 run，重置为 running。"""
    row = conn.execute(
        "select run_id from tr_ingest_runs where batch_key=?",
        (batch_key,)).fetchone()
    if row:
        conn.execute(
            "update tr_ingest_runs set started_at=?, status='running', "
            "finished_at=NULL where run_id=?", (now_iso(), row[0]))
        return row[0]
    conn.execute(
        "insert into tr_ingest_runs (batch_key, started_at, status) "
        "values (?, ?, 'running')", (batch_key, now_iso()))
    return conn.execute(
        "select run_id from tr_ingest_runs where batch_key=?",
        (batch_key,)).fetchone()[0]


def finish_run(conn: sqlite3.Connection, run_id: int, *, status: str,
               **kw) -> None:
    fields = ["finished_at=?", "status=?"]
    vals: list = [now_iso(), status]
    for k in ("candidate_count", "rows_inserted", "rows_skipped",
              "evidence_count", "index_daily_before", "index_daily_after",
              "index_daily_fingerprint_before",
              "index_daily_fingerprint_after", "error_message", "note"):
        if k in kw:
            fields.append(f"{k}=?")
            vals.append(kw[k])
    vals.append(run_id)
    conn.execute(
        f"update tr_ingest_runs set {', '.join(fields)} where run_id=?", vals)


# ---------------------------------------------------------------- 行情
def insert_raw_rows(conn: sqlite3.Connection, tr_code: str,
                    rows: list[dict], *, run_id: int,
                    source_interface: str, request_url: str | None,
                    evidence_relative_path: str | None,
                    evidence_sha256: str | None) -> dict:
    """插入原始行情（幂等：主键冲突即跳过，不覆盖已存原始值）。"""
    inserted = 0
    skipped = 0
    for r in rows:
        rec = {
            "tr_code": tr_code,
            "trade_date": r.get("tradeDate"),
            "open": r.get("open"), "high": r.get("high"),
            "low": r.get("low"), "close": r.get("close"),
            "volume": r.get("tradingVol"), "amount": r.get("tradingValue"),
            "change": r.get("change"), "change_pct": r.get("changePct"),
            "cons_number": r.get("consNumber"), "peg": r.get("peg"),
            "returned_code": r.get("indexCode"),
            "returned_name": r.get("indexNameCnAll"),
        }
        if not rec["trade_date"]:
            skipped += 1
            continue
        cur = conn.execute(
            "insert or ignore into tr_index_daily_raw (tr_code, trade_date, "
            "open, high, low, close, volume, amount, change, change_pct, "
            "cons_number, peg, returned_code, returned_name, "
            "source_interface, request_url, run_id, evidence_relative_path, "
            "evidence_sha256, row_quality_status, row_quality_note, "
            "row_fingerprint, ingested_at) "
            "values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (tr_code, rec["trade_date"], rec["open"], rec["high"],
             rec["low"], rec["close"], rec["volume"], rec["amount"],
             rec["change"], rec["change_pct"], rec["cons_number"],
             rec["peg"], rec["returned_code"], rec["returned_name"],
             source_interface, request_url, run_id,
             evidence_relative_path, evidence_sha256,
             r.get("_row_quality", "unknown"),
             r.get("_row_quality_note"),
             row_fingerprint(rec), now_iso()))
        if cur.rowcount:
            inserted += 1
        else:
            skipped += 1
    return {"inserted": inserted, "skipped": skipped}


def count_raw_rows(conn: sqlite3.Connection, tr_code: str) -> int:
    return conn.execute(
        "select count(*) from tr_index_daily_raw where tr_code=?",
        (tr_code,)).fetchone()[0]


def row_quality_distribution(conn: sqlite3.Connection,
                             tr_code: str) -> dict:
    conn.row_factory = sqlite3.Row
    return {r["row_quality_status"]: r["c"]
            for r in conn.execute(
                "select row_quality_status, count(*) c "
                "from tr_index_daily_raw where tr_code=? "
                "group by row_quality_status", (tr_code,))}


# ---------------------------------------------------------------- 质量快照
def save_quality_snapshot(conn: sqlite3.Connection, tr_code: str, *,
                          run_id: int | None, row_count: int,
                          distribution: dict, coverage_status: str,
                          continuity_status: str,
                          missing_trading_days: int | None,
                          dates_outside_calendar: int | None,
                          real_history_start: str,
                          detail: dict | None = None) -> None:
    # 幂等：同一 (tr_code, run_id) 只保留一条快照
    conn.execute(
        "delete from tr_candidate_quality where tr_code=? and run_id is ?",
        (tr_code, run_id))
    conn.execute(
        "insert into tr_candidate_quality (tr_code, run_id, checked_at, "
        "row_count, normal_unverified_count, suspected_synthetic_count, "
        "suspected_market_closed_count, invalid_value_count, unknown_count, "
        "coverage_status, continuity_status, missing_trading_days, "
        "dates_outside_calendar, real_history_start, detail_json) "
        "values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (tr_code, run_id, now_iso(), row_count,
         distribution.get("normal_unverified", 0),
         distribution.get("suspected_synthetic", 0),
         distribution.get("suspected_market_closed_placeholder", 0),
         distribution.get("invalid_value", 0),
         distribution.get("unknown", 0),
         coverage_status, continuity_status, missing_trading_days,
         dates_outside_calendar, real_history_start,
         json.dumps(detail, ensure_ascii=False) if detail else None))


def latest_quality_snapshot(conn: sqlite3.Connection,
                            tr_code: str) -> dict | None:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "select * from tr_candidate_quality where tr_code=? "
        "order by checked_at desc, quality_id desc limit 1",
        (tr_code,)).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------- 映射
def save_mapping(conn: sqlite3.Connection, m: dict) -> None:
    """幂等：同一 tr_code 只保留最新一条映射。"""
    conn.execute("delete from tr_price_index_mapping where tr_code=?",
                 (m["tr_code"],))
    conn.execute(
        "insert into tr_price_index_mapping (tr_code, price_index_code, "
        "price_index_official_name, price_index_basic_date, tr_basic_date, "
        "base_date_match, ratio_sample_count, ratio_first, ratio_last, "
        "all_ratios_ge_one, ratio_increasing, ratio_equals_one_count, "
        "mapping_verified, evidence_level, "
        "official_mapping_document_found, note, created_at) "
        "values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (m["tr_code"], m["price_index_code"],
         m.get("price_index_official_name"), m.get("price_index_basic_date"),
         m.get("tr_basic_date"), m.get("base_date_match"),
         m.get("ratio_sample_count"), m.get("ratio_first"),
         m.get("ratio_last"), m.get("all_ratios_ge_one"),
         m.get("ratio_increasing"), m.get("ratio_equals_one_count"),
         1 if m.get("mapping_verified") else 0,
         m.get("evidence_level", "technical_inference"),
         1 if m.get("official_mapping_document_found") else 0,
         m.get("note"), now_iso()))


def latest_mapping(conn: sqlite3.Connection, tr_code: str) -> dict | None:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "select * from tr_price_index_mapping where tr_code=? "
        "order by mapping_id desc limit 1", (tr_code,)).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------- 边界守卫
def assert_isolated(conn: sqlite3.Connection) -> dict:
    """证明本层与 index_daily 隔离：tr_* 表不含任何普通指数行情。"""
    # 1) tr 表的表名全部以 tr_ 开头
    # 用 TR_TABLES 白名单，避免 trade_calendar 之类的前缀误匹配
    tr_names = [r[0] for r in conn.execute(
        "select name from sqlite_master where type='table' "
        "and name in ({}) order by name".format(
            ",".join("?" * len(TR_TABLES))), TR_TABLES)]
    bad = [n for n in tr_names if n not in TR_TABLES]
    # 2) 全收益代码不得出现在 index_daily
    codes = [r[0] for r in conn.execute(
        "select tr_code from tr_candidate_master")]
    leaked = []
    for c in codes:
        n = conn.execute(
            "select count(*) from index_daily where index_code=?",
            (c,)).fetchone()[0]
        if n:
            leaked.append({"code": c, "rows": n})
    return {
        "tr_tables": tr_names,
        "tr_table_count": len(tr_names),
        "bad_names": bad,
        "leaked_into_index_daily": leaked,
        "isolated": not bad and not leaked,
    }


def relabel_existing_rows(conn: sqlite3.Connection, tr_code: str,
                          synth_row: str | None,
                          closed_dates: set[str]) -> int:
    """幂等重跑时重新标记已存在行的质量状态。

    **只改 row_quality_status / row_quality_note，不动任何原始数值。**
    """
    n = 0
    rows = conn.execute(
        "select trade_date, close, row_quality_status from tr_index_daily_raw "
        "where tr_code=?", (tr_code,)).fetchall()
    for d, close, cur in rows:
        if synth_row and d == synth_row:
            new, note = ("suspected_synthetic",
                         "请求起始日疑似合成行（strong_inference，非官方确认）")
        elif d in closed_dates:
            new, note = ("suspected_market_closed_placeholder",
                         "疑似休市占位行（无官方日历证据，仅疑似）")
        elif close is None:
            new, note = "invalid_value", "close 缺失"
        else:
            try:
                v = float(close)
            except (TypeError, ValueError):
                new, note = "invalid_value", f"close 非数值：{close!r}"
            else:
                if v <= 0:
                    new, note = "invalid_value", f"close 非正值：{v}"
                else:
                    new, note = ("normal_unverified",
                                 "原始值未经验证，不得视为有效行情")
        if new != cur:
            conn.execute(
                "update tr_index_daily_raw set row_quality_status=?, "
                "row_quality_note=? where tr_code=? and trade_date=?",
                (new, note, tr_code, d))
            n += 1
    return n


# ---------------------------------------------------------------- 原始记录完整性
# 规范化序列化的字段顺序（固定规则，保证可复现）
RAW_RECORD_FIELDS = (
    "tradeDate", "indexCode", "indexNameCnAll", "indexNameCn",
    "indexNameEnAll", "indexNameEn",
    "open", "high", "low", "close", "change", "changePct",
    "tradingVol", "tradingValue", "consNumber", "peg",
)

RAW_RECORD_MIGRATION_UP = (ROOT / "migrations"
                           / "phase3b6_2_3_1_1_1_raw_record.sql")
RAW_RECORD_MIGRATION_DOWN = (ROOT / "migrations"
                             / "phase3b6_2_3_1_1_1_raw_record_down.sql")


def normalize_raw_record(rec: dict) -> str:
    """把原始接口记录序列化为**规范化 JSON**（固定字段顺序、固定分隔符）。

    只保留 ``RAW_RECORD_FIELDS`` 中的字段；缺失字段保留为 ``null``。
    **不修改任何数值**，只是统一序列化方式。
    """
    ordered = {k: rec.get(k) for k in RAW_RECORD_FIELDS}
    return json.dumps(ordered, ensure_ascii=False, sort_keys=False,
                      separators=(",", ":"))


def raw_record_sha256(rec: dict) -> str:
    """规范化记录的 SHA256（**不等于**原始证据文件 SHA256）。"""
    return hashlib.sha256(normalize_raw_record(rec).encode("utf-8")).hexdigest()


def _raw_record_columns(conn: sqlite3.Connection) -> set[str]:
    return {r[1] for r in conn.execute(
        "pragma table_info(tr_index_daily_raw)")}


def _statements_for_column(sql_path: Path, column: str,
                           action: str) -> list[str]:
    """从真实 SQL 文件中挑出**针对某一列**的语句。

    DDL 仍然以 SQL 文件为唯一来源，这里只做筛选，不硬编码 DDL。
    ``action`` 为 ``ADD`` 或 ``DROP``。
    """
    out = []
    needle = f"{action.lower()} column {column.lower()}"
    for stmt in _split_sql(sql_path.read_text(encoding="utf-8")):
        if needle in stmt.lower():
            out.append(stmt)
    return out


def migrate_raw_record_columns(conn: sqlite3.Connection) -> dict:
    """幂等新增 raw_record_json / raw_record_sha256 两列。

    **逐列执行**：只对**尚不存在**的列执行对应 DDL。

    - 两列都已存在 → 不执行任何 DDL
    - 只有一列存在 → 只新增缺的那一列
    - 两列都不存在 → 新增两列

    实际 DDL 来自 ``migrations/phase3b6_2_3_1_1_1_raw_record.sql``。
    """
    before = _raw_record_columns(conn)
    added: list[str] = []
    for col in ("raw_record_json", "raw_record_sha256"):
        if col in _raw_record_columns(conn):
            continue
        stmts = _statements_for_column(
            RAW_RECORD_MIGRATION_UP, col, "ADD")
        if not stmts:
            raise RuntimeError(f"UP SQL 中找不到新增 {col} 的语句")
        for stmt in stmts:
            conn.execute(stmt)
        added.append(col)
    after = _raw_record_columns(conn)
    return {"added": sorted(added), "columns": sorted(after),
            "executed": bool(added)}


def rollback_raw_record_columns(conn: sqlite3.Connection) -> dict:
    """幂等删除两列。**逐列执行**：只删**实际存在**的列。

    - 两列都不存在 → 不执行任何 DDL
    - 只有一列存在 → 只删那一列
    - 两列都存在 → 删除两列

    实际 DDL 来自 ``migrations/phase3b6_2_3_1_1_1_raw_record_down.sql``。
    **只删这两列，不删表、不动其他字段。**
    """
    before = _raw_record_columns(conn)
    dropped: list[str] = []
    # 先删 SHA 再删 JSON，与 DOWN 文件中的顺序一致
    for col in ("raw_record_sha256", "raw_record_json"):
        if col not in _raw_record_columns(conn):
            continue
        stmts = _statements_for_column(
            RAW_RECORD_MIGRATION_DOWN, col, "DROP")
        if not stmts:
            raise RuntimeError(f"DOWN SQL 中找不到删除 {col} 的语句")
        for stmt in stmts:
            conn.execute(stmt)
        dropped.append(col)
    after = _raw_record_columns(conn)
    return {"dropped": sorted(dropped), "columns": sorted(after),
            "executed": bool(dropped)}


def _split_sql(sql: str) -> list[str]:
    """把 SQL 文件拆成语句（去掉注释与空行）。"""
    lines = []
    for line in sql.splitlines():
        s = line.strip()
        if not s or s.startswith("--"):
            continue
        lines.append(line)
    text = "\n".join(lines)
    return [s.strip() for s in text.split(";") if s.strip()]


def backfill_raw_records(conn: sqlite3.Connection,
                         hist_dir: Path) -> dict:
    """从原始历史 JSON 回填 raw_record_json / raw_record_sha256。

    **只写这两个字段，不动任何行情数值。**
    返回逐候选的回填统计。
    """
    out = {}
    codes = [r[0] for r in conn.execute(
        "select tr_code from tr_candidate_master order by tr_code")]
    for code in codes:
        f = hist_dir / f"hist_{code}_20040101_20261127.json"
        if not f.exists():
            out[code] = {"error": "缺原始文件", "updated": 0}
            continue
        rows = json.loads(f.read_bytes().decode("utf-8")).get("data") or []
        updated = 0
        for rec in rows:
            d = rec.get("tradeDate")
            if not d:
                continue
            conn.execute(
                "update tr_index_daily_raw set raw_record_json=?, "
                "raw_record_sha256=? where tr_code=? and trade_date=?",
                (normalize_raw_record(rec), raw_record_sha256(rec), code, d))
            updated += 1
        out[code] = {"updated": updated, "source_rows": len(rows)}
    return out


def verify_raw_records(conn: sqlite3.Connection,
                       hist_dir: Path) -> dict:
    """逐候选逐行核对：原始 JSON vs 数据库。

    **不允许抽样**，逐条比对全部原始字段，并**实际读取数据库保存的
    ``raw_record_json`` 内容**进行比对（不只比 SHA 列）。

    四层核验严格分开统计：

    1. ``field_mismatch``：行情字段（close/cons_number/...）不一致
    2. ``raw_record_json_mismatch``：数据库 JSON 内容与原始规范化结果不一致
    3. ``raw_record_sha256_mismatch``：SHA 列与原始规范化 SHA 不一致
    4. ``stored_json_sha_mismatch``：SHA 列与**数据库实际 JSON** 的 SHA 不一致
    """
    out = {}
    codes = [r[0] for r in conn.execute(
        "select tr_code from tr_candidate_master order by tr_code")]
    for code in codes:
        f = hist_dir / f"hist_{code}_20040101_20261127.json"
        if not f.exists():
            out[code] = {"error": "缺原始文件"}
            continue
        raw_rows = json.loads(f.read_bytes().decode("utf-8")).get("data") or []
        raw_by_date = {r.get("tradeDate"): r for r in raw_rows
                       if r.get("tradeDate")}
        db_rows = {r[0]: r for r in conn.execute(
            "select trade_date, open, high, low, close, volume, amount, "
            "change, change_pct, cons_number, peg, returned_code, "
            "returned_name, raw_record_json, raw_record_sha256 "
            "from tr_index_daily_raw where tr_code=?", (code,))}

        counters = {
            "matched": 0,
            "field_mismatch": 0,
            "raw_record_json_missing": 0,
            "raw_record_json_mismatch": 0,
            "raw_record_sha256_missing": 0,
            "raw_record_sha256_mismatch": 0,
            "stored_json_sha_mismatch": 0,
            "missing_in_db": 0,
            "extra_in_db": 0,
        }
        samples: dict[str, list] = {k: [] for k in counters
                                    if k not in ("matched",)}

        for d, rec in raw_by_date.items():
            row = db_rows.get(d)
            if row is None:
                counters["missing_in_db"] += 1
                if len(samples["missing_in_db"]) < 10:
                    samples["missing_in_db"].append(d)
                continue

            expected_json = normalize_raw_record(rec)
            expected_sha = raw_record_sha256(rec)
            stored_json = row[13]
            stored_sha = row[14]

            problems = {}

            # 1) 行情字段逐项比对
            expect = {
                "open": rec.get("open"), "high": rec.get("high"),
                "low": rec.get("low"), "close": rec.get("close"),
                "volume": rec.get("tradingVol"),
                "amount": rec.get("tradingValue"),
                "change": rec.get("change"),
                "change_pct": rec.get("changePct"),
                "cons_number": rec.get("consNumber"),
                "peg": rec.get("peg"),
                "returned_code": rec.get("indexCode"),
                "returned_name": rec.get("indexNameCnAll"),
            }
            actual = {
                "open": row[1], "high": row[2], "low": row[3],
                "close": row[4], "volume": row[5], "amount": row[6],
                "change": row[7], "change_pct": row[8],
                "cons_number": row[9], "peg": row[10],
                "returned_code": row[11], "returned_name": row[12],
            }
            bad_fields = {k: {"raw": expect[k], "db": actual[k]}
                          for k in expect if expect[k] != actual[k]}
            if bad_fields:
                counters["field_mismatch"] += 1
                problems["field_mismatch"] = bad_fields

            # 2) 数据库实际保存的 JSON 内容
            if stored_json is None:
                counters["raw_record_json_missing"] += 1
                problems["raw_record_json_missing"] = True
            elif stored_json != expected_json:
                counters["raw_record_json_mismatch"] += 1
                problems["raw_record_json_mismatch"] = {
                    "expected": expected_json[:200],
                    "stored": stored_json[:200]}

            # 3) SHA 列 vs 原始规范化 SHA
            if stored_sha is None:
                counters["raw_record_sha256_missing"] += 1
                problems["raw_record_sha256_missing"] = True
            elif stored_sha != expected_sha:
                counters["raw_record_sha256_mismatch"] += 1
                problems["raw_record_sha256_mismatch"] = {
                    "expected": expected_sha, "stored": stored_sha}

            # 4) SHA 列 vs 数据库实际 JSON 的 SHA
            if stored_json is not None and stored_sha is not None:
                actual_json_sha = hashlib.sha256(
                    stored_json.encode("utf-8")).hexdigest()
                if stored_sha != actual_json_sha:
                    counters["stored_json_sha_mismatch"] += 1
                    problems["stored_json_sha_mismatch"] = {
                        "stored_json_sha": actual_json_sha,
                        "stored_sha_column": stored_sha}

            if problems:
                for k, v in problems.items():
                    if len(samples[k]) < 10:
                        samples[k].append({"date": d, "detail": v})
            else:
                counters["matched"] += 1

        for d in db_rows:
            if d not in raw_by_date:
                counters["extra_in_db"] += 1
                if len(samples["extra_in_db"]) < 10:
                    samples["extra_in_db"].append(d)

        total_bad = sum(counters[k] for k in counters
                        if k not in ("matched",))
        out[code] = {
            "raw_rows": len(raw_rows), "db_rows": len(db_rows),
            **counters,
            "samples": samples,
            "complete": (total_bad == 0 and counters["matched"] == len(raw_rows)),
        }
    return out
