"""阶段3B-6.2.3.1.1.1.1 原始 JSON 逐行核验闭环与迁移规范化专项测试。

**真实操作数据库、真实执行 SQL 迁移、真实调用业务函数。**
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.fund import tr_layer  # noqa: E402

REPORTS = ROOT / "reports"
EVID_TR = REPORTS / "evidence" / "phase3B6_2_3_1_0"
EVID = REPORTS / "evidence" / "phase3B6_2_3_1_1_1_1"
AUDIT = REPORTS / "phase3B6_2_3_1_1_1_1_audit.json"

EXPECTED_INDEX_DAILY_FP = (
    "dbbd07c1339e99f27b0aeadb43eb56848776dbbad97f3fb7b9748bbd2f1e61f6")
EXPECTED_RAW_ROWS = 55942
EXPECTED_EVIDENCE = 34

EXPECTED_CODES = {
    "H00300", "H00905", "H00906", "H00016", "H20539", "399997CNY02",
    "H20184", "H00942", "H00922", "H00012", "N00012", "H20930",
}

ANOMALY_KEYS = (
    "field_mismatch", "raw_record_json_missing",
    "raw_record_json_mismatch", "raw_record_sha256_missing",
    "raw_record_sha256_mismatch", "stored_json_sha_mismatch",
    "missing_in_db", "extra_in_db",
)


@pytest.fixture(scope="module")
def conn():
    with tr_layer.get_tr_connection() as c:
        tr_layer.enable_foreign_keys(c)
        yield c


@pytest.fixture(scope="module")
def audit() -> dict:
    assert AUDIT.exists()
    return json.loads(AUDIT.read_text(encoding="utf-8"))


@pytest.fixture
def temp_tr_db(tmp_path):
    """独立临时库（含 tr_index_daily_raw 最小结构与少量行）。"""
    db = tmp_path / "tr_copy.db"
    src = ROOT / "data" / "fund_agent.db"
    shutil.copy2(src, db)
    c = sqlite3.connect(db)
    c.execute("pragma foreign_keys = ON")
    yield c
    c.close()


def _rows(conn, sql, *args) -> list[dict]:
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


# ============================================================ 1-4. 篡改检测
def _one_candidate_verify(conn, code="H00300") -> dict:
    v = tr_layer.verify_raw_records(conn, EVID_TR)
    return v[code]


def test_detect_json_tampered_sha_kept(temp_tr_db):
    """1. 改 raw_record_json 但不改 SHA，必须检测失败。"""
    c = temp_tr_db
    row = c.execute(
        "select tr_code, trade_date, raw_record_json "
        "from tr_index_daily_raw where raw_record_json is not null limit 1"
    ).fetchone()
    code, d, _ = row
    c.execute(
        "update tr_index_daily_raw set raw_record_json=? "
        "where tr_code=? and trade_date=?",
        ('{"tampered":1}', code, d))
    c.commit()
    r = _one_candidate_verify(c, code)
    assert r["raw_record_json_mismatch"] >= 1
    assert r["stored_json_sha_mismatch"] >= 1
    assert r["complete"] is False


def test_detect_sha_tampered(temp_tr_db):
    """2. 改 raw_record_sha256，必须检测失败。"""
    c = temp_tr_db
    row = c.execute(
        "select tr_code, trade_date from tr_index_daily_raw "
        "where raw_record_sha256 is not null limit 1").fetchone()
    code, d = row
    c.execute(
        "update tr_index_daily_raw set raw_record_sha256=? "
        "where tr_code=? and trade_date=?",
        ("0" * 64, code, d))
    c.commit()
    r = _one_candidate_verify(c, code)
    assert r["raw_record_sha256_mismatch"] >= 1
    assert r["complete"] is False


def test_detect_json_null(temp_tr_db):
    """3. raw_record_json 置 NULL，必须检测失败。"""
    c = temp_tr_db
    row = c.execute(
        "select tr_code, trade_date from tr_index_daily_raw "
        "where raw_record_json is not null limit 1").fetchone()
    code, d = row
    c.execute(
        "update tr_index_daily_raw set raw_record_json=NULL "
        "where tr_code=? and trade_date=?", (code, d))
    c.commit()
    r = _one_candidate_verify(c, code)
    assert r["raw_record_json_missing"] >= 1
    assert r["complete"] is False


def test_detect_sha_null(temp_tr_db):
    """4. raw_record_sha256 置 NULL，必须检测失败。"""
    c = temp_tr_db
    row = c.execute(
        "select tr_code, trade_date from tr_index_daily_raw "
        "where raw_record_sha256 is not null limit 1").fetchone()
    code, d = row
    c.execute(
        "update tr_index_daily_raw set raw_record_sha256=NULL "
        "where tr_code=? and trade_date=?", (code, d))
    c.commit()
    r = _one_candidate_verify(c, code)
    assert r["raw_record_sha256_missing"] >= 1
    assert r["complete"] is False


def test_detect_field_changed(temp_tr_db):
    """5a. 行情字段被改动，必须检测失败。"""
    c = temp_tr_db
    row = c.execute(
        "select tr_code, trade_date, close from tr_index_daily_raw "
        "where close is not null limit 1").fetchone()
    code, d, close = row
    c.execute(
        "update tr_index_daily_raw set close=? "
        "where tr_code=? and trade_date=?",
        (float(close) + 1.0, code, d))
    c.commit()
    r = _one_candidate_verify(c, code)
    assert r["field_mismatch"] >= 1
    assert r["complete"] is False


def test_detect_raw_json_field_changed(tmp_path):
    """5b. 原始 JSON 任一字段变化，必须检测失败。

    做法：复制证据目录并篡改其中一条记录的 consNumber。
    """
    ev = tmp_path / "ev"
    shutil.copytree(EVID_TR, ev)
    f = ev / "hist_H00300_20040101_20261127.json"
    doc = json.loads(f.read_bytes().decode("utf-8"))
    doc["data"][100]["consNumber"] = 999999.0
    f.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    with tr_layer.get_tr_connection() as c:
        v = tr_layer.verify_raw_records(c, ev)
    r = v["H00300"]
    assert r["field_mismatch"] >= 1
    assert r["raw_record_json_mismatch"] >= 1
    assert r["complete"] is False


def test_passes_when_all_match(conn):
    """6. DB 实际 JSON 与原始 JSON 完全一致时通过。"""
    v = tr_layer.verify_raw_records(conn, EVID_TR)
    for code, r in v.items():
        assert r["complete"] is True, f"{code}: {r['samples']}"
        for k in ANOMALY_KEYS:
            assert r[k] == 0, f"{code} {k}={r[k]}"


# ============================================================ 7. 全量
def test_full_55942_verified(conn):
    """7. 55,942 条全量核验无遗漏。"""
    v = tr_layer.verify_raw_records(conn, EVID_TR)
    assert set(v) == EXPECTED_CODES
    total_raw = sum(r["raw_rows"] for r in v.values())
    total_db = sum(r["db_rows"] for r in v.values())
    total_matched = sum(r["matched"] for r in v.values())
    assert total_raw == EXPECTED_RAW_ROWS
    assert total_db == EXPECTED_RAW_ROWS
    assert total_matched == EXPECTED_RAW_ROWS
    for k in ANOMALY_KEYS:
        assert sum(r[k] for r in v.values()) == 0, f"{k} 非 0"


def test_per_candidate_reported(audit):
    """按 12 个候选分别输出结果。"""
    v = audit["verification"]
    assert set(v) == EXPECTED_CODES
    for code, r in v.items():
        assert r["raw_rows"] == r["db_rows"] == r["matched"]
        assert r["complete"] is True
        for k in ANOMALY_KEYS:
            assert r[k] == 0


def test_anomalies_separately_counted(audit):
    """八类异常必须分别统计，不合并。"""
    t = audit["verification_totals"]
    assert set(t["anomalies"]) == set(ANOMALY_KEYS)
    for k in ANOMALY_KEYS:
        assert t["anomalies"][k] == 0
    assert audit["verification_layers"]["note"]


def test_samples_bounded(audit):
    """异常明细样本必须有上限。"""
    for r in audit["verification"].values():
        for k, v in r["samples"].items():
            assert len(v) <= 10, f"{k} 样本超限 {len(v)}"


# ============================================================ 8-10. 迁移
def _cols(c) -> set:
    return {r[1] for r in c.execute("pragma table_info(tr_index_daily_raw)")}


def test_up_adds_columns(temp_tr_db):
    """8a. UP 确实能新增两列。"""
    c = temp_tr_db
    tr_layer.rollback_raw_record_columns(c)
    c.commit()
    assert "raw_record_json" not in _cols(c)
    r = tr_layer.migrate_raw_record_columns(c)
    c.commit()
    assert r["executed"] is True
    assert "raw_record_json" in _cols(c)
    assert "raw_record_sha256" in _cols(c)


def test_up_idempotent(temp_tr_db):
    """8b. UP 重复执行不报错。"""
    c = temp_tr_db
    tr_layer.migrate_raw_record_columns(c)
    c.commit()
    r2 = tr_layer.migrate_raw_record_columns(c)
    c.commit()
    assert r2["executed"] is False
    assert r2["added"] == []


def test_down_drops_columns(temp_tr_db):
    """9a. DOWN 确实能删除两列。"""
    c = temp_tr_db
    r = tr_layer.rollback_raw_record_columns(c)
    c.commit()
    assert r["executed"] is True
    assert "raw_record_json" not in _cols(c)
    assert "raw_record_sha256" not in _cols(c)


def test_down_idempotent(temp_tr_db):
    """9b. DOWN 重复执行不报错。"""
    c = temp_tr_db
    tr_layer.rollback_raw_record_columns(c)
    c.commit()
    r2 = tr_layer.rollback_raw_record_columns(c)
    c.commit()
    assert r2["executed"] is False
    assert r2["dropped"] == []


def test_up_down_up_lifecycle(temp_tr_db):
    """10. UP→DOWN→UP 生命周期正常，且不丢数据。"""
    c = temp_tr_db
    before_rows = c.execute(
        "select count(*) from tr_index_daily_raw").fetchone()[0]
    tr_layer.rollback_raw_record_columns(c)
    c.commit()
    assert "raw_record_json" not in _cols(c)
    tr_layer.migrate_raw_record_columns(c)
    c.commit()
    assert "raw_record_json" in _cols(c)
    after_rows = c.execute(
        "select count(*) from tr_index_daily_raw").fetchone()[0]
    assert after_rows == before_rows


def test_migration_sql_files_have_real_ddl():
    """UP/DOWN SQL 文件必须包含真实 DDL，不能只有注释。"""
    up = tr_layer.RAW_RECORD_MIGRATION_UP.read_text(encoding="utf-8")
    down = tr_layer.RAW_RECORD_MIGRATION_DOWN.read_text(encoding="utf-8")
    assert "ALTER TABLE tr_index_daily_raw ADD COLUMN raw_record_json" in up
    assert "ALTER TABLE tr_index_daily_raw ADD COLUMN raw_record_sha256" in up
    assert "DROP COLUMN raw_record_json" in down
    assert "DROP COLUMN raw_record_sha256" in down
    # 不得删表
    assert "DROP TABLE" not in down.upper()


def test_down_only_drops_two_columns(temp_tr_db):
    """DOWN 只删两列，不动其他字段与表。"""
    c = temp_tr_db
    before = _cols(c)
    other_before = before - {"raw_record_json", "raw_record_sha256"}
    tr_layer.rollback_raw_record_columns(c)
    c.commit()
    after = _cols(c)
    assert after == other_before
    # 表仍存在
    assert c.execute(
        "select count(*) from sqlite_master where type='table' "
        "and name='tr_index_daily_raw'").fetchone()[0] == 1


# ============================================================ 11-12. 不变
def test_index_daily_unchanged(conn):
    """11. index_daily 隔离和内容指纹不变。"""
    fp = tr_layer.index_daily_fingerprint(conn)
    assert fp["row_count"] == 50603
    assert fp["fingerprint"] == EXPECTED_INDEX_DAILY_FP
    assert tr_layer.assert_isolated(conn)["isolated"] is True


def test_admission_unchanged(conn):
    """12. 所有准入状态保持不变。"""
    cands = tr_layer.list_candidates(conn)
    assert sum(c["raw_data_layer_ingest_candidate"] for c in cands) == 12
    assert sum(c["validated_series_candidate"] for c in cands) == 0
    assert sum(c["proxy_qualified_series_candidate"] for c in cands) == 0
    assert sum(c["formal_series_admitted"] for c in cands) == 0


def test_row_count_and_fingerprint_fields(conn):
    """行数与指纹字段数不变。"""
    assert conn.execute(
        "select count(*) from tr_index_daily_raw").fetchone()[0] == \
        EXPECTED_RAW_ROWS
    assert len(tr_layer.FINGERPRINT_FIELDS) == 14


def test_evidence_unchanged(conn):
    """34 份证据与计数不变。"""
    evs = _rows(conn, "select * from tr_evidence_files")
    assert len(evs) == EXPECTED_EVIDENCE
    for e in evs:
        f = ROOT / e["relative_path"]
        assert f.exists()
        assert hashlib.sha256(f.read_bytes()).hexdigest() == e["sha256"]
    run = _rows(conn, "select * from tr_ingest_runs "
                      "order by run_id desc")[0]
    assert run["evidence_count"] == EXPECTED_EVIDENCE


def test_abnormal_rows_preserved(conn):
    """异常行全部保留。"""
    assert conn.execute(
        "select count(*) from tr_index_daily_raw "
        "where trade_date='20040101' and "
        "row_quality_status='suspected_synthetic'").fetchone()[0] == 12
    assert conn.execute(
        "select count(*) from tr_index_daily_raw "
        "where trade_date='20180618' and "
        "row_quality_status='suspected_market_closed_placeholder'"
    ).fetchone()[0] == 8
    r = conn.execute(
        "select close, row_quality_status from tr_index_daily_raw "
        "where tr_code='H20184' and trade_date='20130628'").fetchone()
    assert r[0] == 0.0 and r[1] == "invalid_value"


def test_continuity_and_real_start_unchanged(conn):
    dist = {}
    for c in tr_layer.list_candidates(conn):
        dist[c["continuity_level"]] = \
            dist.get(c["continuity_level"], 0) + 1
        assert c["real_history_start"] == "unknown"
    assert dist.get("verified_official_calendar", 0) == 0
    assert dist.get("verified_against_proxy_calendar", 0) == 1
    assert dist.get("has_unresolved_suspicion", 0) == 8
    assert dist.get("unknown", 0) == 3


def test_integrity_and_fk(conn):
    assert conn.execute("pragma integrity_check").fetchone()[0] == "ok"
    assert len(conn.execute("pragma foreign_key_check").fetchall()) == 0


def test_no_verified_row_state(conn):
    states = {r["row_quality_status"] for r in _rows(
        conn, "select distinct row_quality_status from tr_index_daily_raw")}
    assert "verified" not in states


def test_self_check_all_pass(audit):
    for k, v in audit["_self_check"].items():
        assert v is True, f"自校验失败：{k}"


def test_no_vacuous_assertion():
    """本文件不得出现恒真断言（AST 检查）。"""
    import ast
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue
        e = node.test
        if isinstance(e, ast.Constant) and e.value is True:
            raise AssertionError(f"恒真断言于第 {node.lineno} 行")
        if isinstance(e, ast.BoolOp) and isinstance(e.op, ast.Or):
            if any(isinstance(v, ast.Constant) and v.value is True
                   for v in e.values):
                raise AssertionError(f"含 or True 于第 {node.lineno} 行")
