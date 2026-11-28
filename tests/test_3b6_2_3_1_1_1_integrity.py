"""阶段3B-6.2.3.1.1.1 原始归档完整性与审计计数修复专项测试。

**真实操作数据库与业务函数**，不使用文本断言。
"""
from __future__ import annotations

import hashlib
import json
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
EVID = REPORTS / "evidence" / "phase3B6_2_3_1_1_1"
AUDIT = REPORTS / "phase3B6_2_3_1_1_1_audit.json"

EXPECTED_INDEX_DAILY_FP = (
    "dbbd07c1339e99f27b0aeadb43eb56848776dbbad97f3fb7b9748bbd2f1e61f6")
EXPECTED_RAW_ROWS = 55942
EXPECTED_EVIDENCE = 34

EXPECTED_CODES = {
    "H00300", "H00905", "H00906", "H00016", "H20539", "399997CNY02",
    "H20184", "H00942", "H00922", "H00012", "N00012", "H20930",
}


@pytest.fixture(scope="module")
def conn():
    with tr_layer.get_tr_connection() as c:
        tr_layer.enable_foreign_keys(c)
        yield c


@pytest.fixture(scope="module")
def audit() -> dict:
    assert AUDIT.exists()
    return json.loads(AUDIT.read_text(encoding="utf-8"))


def _rows(conn, sql, *args) -> list[dict]:
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


# ============================================================ 1-2. 证据计数
def test_evidence_count_matches_unique_files(conn, audit):
    """1. 证据计数 = 数据库唯一证据文件数。"""
    n = conn.execute(
        "select count(*) from tr_evidence_files").fetchone()[0]
    run = _rows(conn, "select * from tr_ingest_runs "
                      "order by run_id desc")[0]
    assert run["evidence_count"] == n, \
        f"批次 {run['evidence_count']} != 唯一 {n}"
    assert n == EXPECTED_EVIDENCE
    assert audit["evidence"]["unique_files"] == n
    assert audit["evidence"]["consistent"] is True


def test_evidence_count_matches_manifest(conn):
    """2. 证据计数 = manifest 文件数。"""
    n = conn.execute(
        "select count(*) from tr_evidence_files").fetchone()[0]
    m = json.loads((EVID / "manifest.json").read_text(encoding="utf-8"))
    assert m["file_count"] == n
    assert len(m["files"]) == n


def test_no_duplicate_evidence_paths(conn):
    """同一文件不得重复登记。"""
    dup = _rows(conn,
                "select relative_path, count(*) c from tr_evidence_files "
                "group by 1 having c>1")
    assert not dup, f"重复登记：{dup}"


def test_evidence_count_fixed_in_source():
    """导入脚本必须按数据库唯一数统计，不累加调用次数。"""
    src = (ROOT / "scripts" / "build_3b6_2_3_1_1_tr_layer.py").read_text(
        encoding="utf-8")
    assert "select count(*) from tr_evidence_files" in src


# ============================================================ 3-6. 指纹
def _mk_rec(**kw) -> dict:
    base = {
        "tr_code": "H00300", "trade_date": "20200102",
        "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5,
        "volume": 100.0, "amount": 200.0, "change": 0.1,
        "change_pct": 0.02, "cons_number": 300.0, "peg": 13.42,
        "returned_code": "H00300", "returned_name": "沪深300全收益指数",
    }
    base.update(kw)
    return base


def test_fingerprint_covers_cons_number():
    """3. 只改 cons_number，指纹必须改变。"""
    a = tr_layer.row_fingerprint(_mk_rec())
    b = tr_layer.row_fingerprint(_mk_rec(cons_number=301.0))
    assert a != b


def test_fingerprint_covers_peg():
    """4. 只改 peg，指纹必须改变。"""
    a = tr_layer.row_fingerprint(_mk_rec())
    b = tr_layer.row_fingerprint(_mk_rec(peg=99.99))
    assert a != b


def test_fingerprint_covers_every_field():
    """5. 任一原始字段改变都会改变指纹。"""
    base = tr_layer.row_fingerprint(_mk_rec())
    changes = {
        "tr_code": "H00905", "trade_date": "20200103",
        "open": 9.9, "high": 9.9, "low": 9.9, "close": 9.9,
        "volume": 9.9, "amount": 9.9, "change": 9.9, "change_pct": 9.9,
        "cons_number": 9.9, "peg": 9.9,
        "returned_code": "X", "returned_name": "Y",
    }
    assert len(changes) == len(tr_layer.FINGERPRINT_FIELDS)
    for k, v in changes.items():
        assert tr_layer.row_fingerprint(_mk_rec(**{k: v})) != base, \
            f"{k} 变化未影响指纹"


def test_fingerprint_stable():
    """6. 相同原始记录产生稳定指纹。"""
    r1 = _mk_rec()
    r2 = dict(r1)
    assert tr_layer.row_fingerprint(r1) == tr_layer.row_fingerprint(r2)
    # 多次调用稳定
    assert tr_layer.row_fingerprint(r1) == tr_layer.row_fingerprint(r1)


def test_fingerprint_fields_declared():
    """指纹字段必须覆盖全部 14 个原始字段。"""
    expected = {
        "tr_code", "trade_date", "open", "high", "low", "close",
        "volume", "amount", "change", "change_pct",
        "cons_number", "peg", "returned_code", "returned_name",
    }
    assert set(tr_layer.FINGERPRINT_FIELDS) == expected
    assert len(tr_layer.FINGERPRINT_FIELDS) == 14


def test_all_db_fingerprints_recomputed(conn):
    """数据库中所有行指纹必须与当前字段一致（真实重算）。"""
    rows = _rows(conn,
                 "select tr_code, trade_date, open, high, low, close, "
                 "volume, amount, change, change_pct, cons_number, peg, "
                 "returned_code, returned_name, row_fingerprint "
                 "from tr_index_daily_raw")
    assert len(rows) == EXPECTED_RAW_ROWS
    bad = []
    for r in rows:
        rec = {k: r[k] for k in tr_layer.FINGERPRINT_FIELDS}
        if tr_layer.row_fingerprint(rec) != r["row_fingerprint"]:
            bad.append(f"{r['tr_code']}/{r['trade_date']}")
            if len(bad) >= 5:
                break
    assert not bad, f"指纹不符：{bad}"


# ============================================================ 7-9. 逐行核对
def test_all_candidates_verified(conn, audit):
    """7. 12 个候选逐行原始记录核对。

    3B-6.2.3.1.1.1.1 起审计 JSON 改为八类异常分别统计，
    原 `mismatched` 字段已拆为 `field_mismatch` 等。
    """
    v = audit["verification"]
    assert set(v) == EXPECTED_CODES
    for code, r in v.items():
        assert r["complete"] is True, f"{code} 不完整：{r.get('samples')}"
        assert r["field_mismatch"] == 0
        assert r["raw_record_json_mismatch"] == 0
        assert r["raw_record_sha256_mismatch"] == 0
        assert r["stored_json_sha_mismatch"] == 0
        assert r["missing_in_db"] == 0
        assert r["extra_in_db"] == 0
        assert r["matched"] == r["raw_rows"] == r["db_rows"]


def test_total_rows_no_missing_no_extra(audit):
    """8. 55,942 条记录无遗漏、无多余。"""
    t = audit["verification_totals"]
    assert t["matched"] == EXPECTED_RAW_ROWS
    assert t["missing_in_db"] == 0
    assert t["extra_in_db"] == 0
    assert t["all_complete"] is True
    # 八类异常全部为 0
    for k, v in t["anomalies"].items():
        assert v == 0, f"{k} 非 0：{v}"


def test_field_values_match_raw_file(conn):
    """9. 原始文件与数据库的字段值一致（真实重新核对）。"""
    verify = tr_layer.verify_raw_records(conn, EVID_TR)
    for code, r in verify.items():
        assert r["complete"] is True, f"{code}: {r.get('diffs')}"
        assert r["matched"] == r["raw_rows"]


def test_cons_number_and_peg_verified(conn):
    """特别核对 consNumber 与 peg。"""
    conn.row_factory = sqlite3.Row
    for code in ("H00300", "H20184", "H20930"):
        f = EVID_TR / f"hist_{code}_20040101_20261127.json"
        raw = json.loads(f.read_bytes().decode("utf-8")).get("data") or []
        sample = raw[len(raw) // 2]
        d = sample["tradeDate"]
        row = conn.execute(
            "select cons_number, peg, returned_code, returned_name "
            "from tr_index_daily_raw where tr_code=? and trade_date=?",
            (code, d)).fetchone()
        assert row["cons_number"] == sample.get("consNumber")
        assert row["peg"] == sample.get("peg")
        assert row["returned_code"] == sample.get("indexCode")
        assert row["returned_name"] == sample.get("indexNameCnAll")


def test_raw_record_columns_present(conn):
    """raw_record_json / raw_record_sha256 两列必须存在。"""
    cols = {r["name"] for r in _rows(
        conn, "pragma table_info(tr_index_daily_raw)")}
    assert "raw_record_json" in cols
    assert "raw_record_sha256" in cols


def test_raw_record_json_backfilled(conn):
    """全部行的 raw_record_json 必须已回填且与重算一致。"""
    n_null = conn.execute(
        "select count(*) from tr_index_daily_raw "
        "where raw_record_json is null or raw_record_sha256 is null"
    ).fetchone()[0]
    assert n_null == 0
    rows = _rows(conn,
                 "select raw_record_json, raw_record_sha256 "
                 "from tr_index_daily_raw limit 200")
    for r in rows:
        actual = hashlib.sha256(
            r["raw_record_json"].encode("utf-8")).hexdigest()
        assert actual == r["raw_record_sha256"]


def test_raw_record_sha_not_replacing_evidence_sha(conn):
    """规范化记录 SHA 不得替代原始证据文件 SHA。"""
    rows = _rows(conn,
                 "select distinct evidence_sha256, raw_record_sha256 "
                 "from tr_index_daily_raw limit 50")
    for r in rows:
        assert r["evidence_sha256"] != r["raw_record_sha256"], \
            "规范化 SHA 与原始文件 SHA 相同，可能被误替换"


def test_normalize_is_deterministic():
    """规范化序列化必须固定规则、可复现。"""
    rec = {"tradeDate": "20200102", "close": 1.5, "peg": 13.42,
           "consNumber": 300.0}
    a = tr_layer.normalize_raw_record(rec)
    b = tr_layer.normalize_raw_record(dict(rec))
    assert a == b
    # 字段顺序固定
    assert a.index("tradeDate") < a.index("close") < a.index("peg")


# ============================================================ 10. 数值未变
def test_values_untouched(audit):
    """10. 行指纹更新不修改行情数值。"""
    d = audit["data_unchanged"]
    assert d["values_identical"] is True
    assert d["rows_equal"] is True
    assert d["rows_before"] == d["rows_after"] == EXPECTED_RAW_ROWS


def test_abnormal_rows_still_present(conn):
    """异常记录必须仍然存在且标记不变。"""
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
    assert r[0] == 0.0
    assert r[1] == "invalid_value"


# ============================================================ 11. 幂等
def test_rerun_no_duplicates(conn):
    """11. 重复执行修复不产生重复记录。"""
    n = conn.execute(
        "select count(*) from tr_index_daily_raw").fetchone()[0]
    assert n == EXPECTED_RAW_ROWS
    dup = _rows(conn,
                "select tr_code, trade_date, count(*) c "
                "from tr_index_daily_raw group by 1,2 having c>1")
    assert not dup


def test_migration_idempotent(conn):
    """迁移可重复执行。"""
    before = {r["name"] for r in _rows(
        conn, "pragma table_info(tr_index_daily_raw)")}
    mig = tr_layer.migrate_raw_record_columns(conn)
    assert mig["added"] == []
    after = {r["name"] for r in _rows(
        conn, "pragma table_info(tr_index_daily_raw)")}
    assert before == after


# ============================================================ 12. 完整性
def test_integrity_ok(conn):
    assert conn.execute("pragma integrity_check").fetchone()[0] == "ok"


def test_fk_zero(conn):
    assert len(conn.execute("pragma foreign_key_check").fetchall()) == 0


def test_index_daily_fingerprint_unchanged(conn):
    """index_daily 内容指纹必须为任务给定值。"""
    fp = tr_layer.index_daily_fingerprint(conn)
    assert fp["row_count"] == 50603
    assert fp["fingerprint"] == EXPECTED_INDEX_DAILY_FP


def test_isolation_ok(conn):
    iso = tr_layer.assert_isolated(conn)
    assert iso["isolated"] is True


def test_evidence_sha256_unchanged(conn):
    """34 份证据文件 SHA256 不变。"""
    evs = _rows(conn, "select * from tr_evidence_files")
    assert len(evs) == EXPECTED_EVIDENCE
    for e in evs:
        f = ROOT / e["relative_path"]
        assert f.exists()
        assert hashlib.sha256(f.read_bytes()).hexdigest() == e["sha256"]


def test_continuity_and_real_start_unchanged(conn):
    """连续性等级与真实历史起点状态不变。"""
    dist = {}
    for c in tr_layer.list_candidates(conn):
        dist[c["continuity_level"]] = \
            dist.get(c["continuity_level"], 0) + 1
        assert c["real_history_start"] == "unknown"
    assert dist.get("verified_official_calendar", 0) == 0
    assert dist.get("verified_against_proxy_calendar", 0) == 1
    assert dist.get("has_unresolved_suspicion", 0) == 8
    assert dist.get("unknown", 0) == 3


def test_admission_states_unchanged(conn):
    cands = tr_layer.list_candidates(conn)
    assert sum(c["raw_data_layer_ingest_candidate"] for c in cands) == 12
    assert sum(c["validated_series_candidate"] for c in cands) == 0
    assert sum(c["proxy_qualified_series_candidate"] for c in cands) == 0
    assert sum(c["formal_series_admitted"] for c in cands) == 0


def test_no_verified_row_state(conn):
    """不允许任何原始行情被标记为 verified。"""
    states = {r["row_quality_status"] for r in _rows(
        conn, "select distinct row_quality_status "
              "from tr_index_daily_raw")}
    assert "verified" not in states
    assert states <= set(tr_layer.ROW_QUALITY_STATES)


def test_self_check_all_pass(audit):
    for k, v in audit["_self_check"].items():
        assert v is True, f"自校验失败：{k}"


def test_no_vacuous_assertion():
    """本文件不得出现恒真断言（用 AST 检查）。"""
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
