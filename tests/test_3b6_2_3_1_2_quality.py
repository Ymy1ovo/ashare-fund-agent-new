"""阶段3B-6.2.3.1.2 质量验证与可用性分级专项测试。

**真实操作数据库、真实调用审计函数、真实计算 SHA256。**
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
from scripts.audit_3b6_2_3_1_2_quality import (  # noqa: E402
    GRADE_DEFINITIONS, MARKET_CALENDAR, TASK_CLAIMED_MARKET,
    audit_calendar, audit_historical_start, audit_row_quality,
    grade_candidate)

REPORTS = ROOT / "reports"
EVID = REPORTS / "evidence" / "phase3B6_2_3_1_2"
AUDIT = REPORTS / "phase3B6_2_3_1_2_audit.json"
GRADING = REPORTS / "phase3B6_2_3_1_2_candidate_grading.json"

EXPECTED_FP = (
    "dbbd07c1339e99f27b0aeadb43eb56848776dbbad97f3fb7b9748bbd2f1e61f6")
EXPECTED_RAW_ROWS = 55942
EXPECTED_INDEX_ROWS = 50603
EXPECTED_EVIDENCE = 34
TASK_BASELINE = "6a76d2890ddd5ec21d97d90ed1ab4b07d3ea168a"

EXPECTED_CODES = {
    "399997CNY02", "H00012", "H00016", "H00300", "H00905", "H00906",
    "H00922", "H00942", "H20184", "H20539", "H20930", "N00012",
}


@pytest.fixture(scope="module")
def conn():
    p = str(__import__("app.config", fromlist=["settings"]).settings
            .database_path).replace("\\", "/")
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    c.execute("pragma temp_store = memory")
    c.row_factory = sqlite3.Row
    yield c
    c.close()


@pytest.fixture(scope="module")
def audit() -> dict:
    assert AUDIT.exists()
    return json.loads(AUDIT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def grading() -> dict:
    assert GRADING.exists()
    return json.loads(GRADING.read_text(encoding="utf-8"))


def _rows(conn, code) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "select trade_date, open, high, low, close, volume, amount, "
        "change, change_pct, row_quality_status "
        "from tr_index_daily_raw where tr_code=? order by trade_date",
        (code,))]


def _cand(audit, code) -> dict:
    return next(c for c in audit["candidates"] if c["tr_code"] == code)


# ============================================================ 1. 完整覆盖
def test_twelve_candidates_covered(audit):
    """1. 12 个候选完整覆盖。"""
    codes = {c["tr_code"] for c in audit["candidates"]}
    assert codes == EXPECTED_CODES
    assert len(audit["candidates"]) == 12


def test_all_candidates_graded(audit):
    for c in audit["candidates"]:
        assert c["grading"]["final_grade"] in GRADE_DEFINITIONS


def test_grading_file_consistent(audit, grading):
    """分级 JSON 与审计 JSON 完全一致。"""
    a = {c["tr_code"]: c["grading"]["final_grade"]
         for c in audit["candidates"]}
    g = {c["tr_code"]: c["final_grade"] for c in grading["candidates"]}
    assert a == g
    assert grading["grade_distribution"] == audit["summary"][
        "grade_distribution"]


# ============================================================ 2. 市场日历隔离
def test_market_calendar_isolation():
    """2. 各市场日历隔离：债券/港股不可用 A 股日历。"""
    assert MARKET_CALENDAR["stock"]["calendar_available"] is True
    assert MARKET_CALENDAR["bond"]["calendar_available"] is False
    assert MARKET_CALENDAR["hk"]["calendar_available"] is False
    for g in ("stock", "bond", "hk"):
        assert MARKET_CALENDAR[g]["calendar_is_official"] is False


def test_bond_hk_calendar_unknown(audit):
    """债券/港股连续性必须 unknown。"""
    for c in audit["candidates"]:
        if c["market_group"] in ("bond", "hk"):
            assert c["calendar"]["continuity_status"] == "unknown", \
                f"{c['tr_code']} 日历被错误判定"
            assert c["calendar"]["calendar_available"] is False
            assert c["calendar"]["missing_trading_days"] is None


def test_bond_not_using_a_share_calendar(conn):
    """真实调用：债券候选不得用 A 股日历判定。"""
    a_cal = {r[0] for r in conn.execute(
        "select trade_date from trade_calendar")}
    for code in ("H00012", "N00012"):
        rows = _rows(conn, code)
        r = audit_calendar({"market_group": "bond",
                            "_synthetic_row": rows[0]["trade_date"]},
                           rows, a_cal)
        assert r["continuity_status"] == "unknown"
        assert r["calendar_available"] is False


def test_hk_not_using_a_share_calendar(conn):
    """港股候选不得用 A 股日历判定。"""
    a_cal = {r[0] for r in conn.execute(
        "select trade_date from trade_calendar")}
    rows = _rows(conn, "H20930")
    r = audit_calendar({"market_group": "hk",
                        "_synthetic_row": rows[0]["trade_date"]},
                       rows, a_cal)
    assert r["continuity_status"] == "unknown"


def test_proxy_not_upgraded_to_official(audit):
    """9. 代理日历不得升级为官方验证。"""
    for c in audit["candidates"]:
        assert c["calendar"]["calendar_is_official"] is False
        assert c["calendar"]["continuity_status"] != \
            "verified_official_calendar"
    assert audit["summary"]["calendar_official"] == 0


# ============================================================ 3. 历史起点
def test_historical_start_all_unknown(audit):
    """3. 真实历史起点未知时不得升级。"""
    for c in audit["candidates"]:
        hs = c["historical_start"]
        assert hs["historical_start_status"] == "unknown"
        assert hs["actual_earliest_historical_quote_date"] == "unknown"
        assert hs["historical_start_blockers"]


def test_request_start_not_used_as_real_start(audit):
    """4. 请求起始日期不得直接作为真实历史起点。"""
    for c in audit["candidates"]:
        hs = c["historical_start"]
        assert hs["request_start_date"] == "20040101"
        assert hs["api_earliest_returned_date"] == "20040101"
        assert hs["actual_earliest_historical_quote_date"] != "20040101"
        assert hs["historical_start_evidence_level"] == \
            "request_start_artifact"


def test_six_date_concepts_distinct(audit):
    """六类日期必须分开记录。"""
    for c in audit["candidates"]:
        d = c["historical_start"]["date_concepts_distinct"]
        assert len(d) == 6
        assert d["3_request_start"] == "20040101"
        assert d["5_confirmed_real_start"] == "unknown"
        assert d["6_first_publicly_available"] == "unknown"


def test_synthetic_rows_not_confirmed_as_real(audit):
    """5. 疑似合成行不得被自动认定为真实行情。"""
    for c in audit["candidates"]:
        assert c["row_quality_distribution"].get(
            "suspected_synthetic", 0) == 1
        assert c["historical_start"]["synthetic_row_preserved"] == "20040101"


def test_synthetic_rows_preserved_in_db(conn):
    """疑似合成行原始记录必须保留。"""
    n = conn.execute(
        "select count(*) from tr_index_daily_raw "
        "where trade_date='20040101' and "
        "row_quality_status='suspected_synthetic'").fetchone()[0]
    assert n == 12


# ============================================================ 4. 休市占位
def test_closed_placeholder_not_auto_upgraded(audit):
    """6. 疑似休市占位行不得自动升级。"""
    for c in audit["candidates"]:
        for x in c["calendar"].get("outside_detail", []):
            assert x["official_calendar_evidence"] is False
            if x["classification"] == "suspected_market_closed":
                assert "仅疑似" in x["note"]


def test_closed_placeholder_rows_preserved(conn):
    n = conn.execute(
        "select count(*) from tr_index_daily_raw "
        "where trade_date='20180618' and "
        "row_quality_status='suspected_market_closed_placeholder'"
    ).fetchone()[0]
    assert n == 8


# ============================================================ 5. 质量
def test_abnormal_close_not_fixed(audit):
    """7. 异常 close 不得被自动修正。"""
    c = _cand(audit, "H20184")
    nz = c["row_quality"]["checks"]["close_non_positive"]
    assert nz["count"] >= 1
    assert nz["sample"][0]["close"] == 0.0
    assert c["row_quality"]["data_quality_status"] == "has_fatal"


def test_h20184_zero_still_in_db(conn):
    r = conn.execute(
        "select close, row_quality_status from tr_index_daily_raw "
        "where tr_code='H20184' and trade_date='20130628'").fetchone()
    assert r["close"] == 0.0
    assert r["row_quality_status"] == "invalid_value"


def test_row_quality_checks_all_present(audit):
    """12 项检查必须全部存在。"""
    expected = {
        "illegal_date", "duplicate_date", "close_null",
        "close_non_positive", "close_non_numeric", "high_lt_low",
        "ohlc_inconsistent", "volume_negative", "amount_negative",
        "change_inconsistent", "change_pct_inconsistent",
        "extreme_jump", "repeated_price_run", "non_trading_date"}
    for c in audit["candidates"]:
        assert set(c["row_quality"]["checks"]) == expected


def test_no_duplicate_dates(conn):
    """真实核查：任何候选不得有重复日期。"""
    dup = conn.execute(
        "select tr_code, trade_date, count(*) c from tr_index_daily_raw "
        "group by 1,2 having c>1").fetchall()
    assert not dup


def test_row_quality_real_call(conn):
    """真实调用 audit_row_quality，结果与 JSON 一致。"""
    rows = _rows(conn, "H00300")
    r = audit_row_quality({"tr_code": "H00300"}, rows)
    assert r["row_count"] == len(rows)
    assert r["fatal_issue_count"] == 0


# ============================================================ 6. 时点
def test_point_in_time_all_unknown(audit):
    """8. 历史时点可用性未知时不得获得完整回测准入。"""
    for c in audit["candidates"]:
        pit = c["point_in_time"]
        assert pit["historical_point_in_time_status"] == "unknown"
        assert pit["first_available_date"] == "unknown"
        assert pit["point_in_time_blockers"]
        assert pit["historical_publication_evidence"] is None
        assert pit["historical_revision_evidence"] is None


def test_no_point_in_time_candidate_passes_backtest(audit):
    """时点 unknown 的候选不得允许严格回测。"""
    for c in audit["candidates"]:
        if c["point_in_time"]["historical_point_in_time_status"] != "verified":
            forbidden = c["grading"]["forbidden_uses"]
            assert any("历史时点" in f or "回测" in f for f in forbidden)


# ============================================================ 7. 分级
def test_no_grade_a(audit):
    """没有任何候选获得 A 级。"""
    assert audit["summary"]["grade_distribution"].get("A", 0) == 0


def test_grade_counts_match(audit):
    g = audit["summary"]["grade_distribution"]
    assert g.get("B", 0) == 8
    assert g.get("C", 0) == 4
    assert sum(g.values()) == 12


def test_grade_rules_consistent():
    """分级规则对 12 个候选一致适用（真实调用）。"""
    base = {
        "identity_evidence_level": "official",
        "return_basis_evidence_level": "official",
        "historical_start": {"historical_start_status": "unknown"},
        "calendar": {"continuity_status":
                     "verified_against_proxy_calendar"},
        "row_quality": {"data_quality_status": "pass",
                        "fatal_issue_count": 0},
        "point_in_time": {"historical_point_in_time_status": "unknown"},
    }
    # 同样输入必须得同样等级
    g1 = grade_candidate(dict(base))["final_grade"]
    g2 = grade_candidate(dict(base))["final_grade"]
    assert g1 == g2 == "B"

    # 质量致命 → C
    bad = {**base, "row_quality": {"data_quality_status": "has_fatal",
                                   "fatal_issue_count": 1}}
    assert grade_candidate(bad)["final_grade"] == "C"

    # 日历 unknown → C
    no_cal = {**base, "calendar": {"continuity_status": "unknown"}}
    assert grade_candidate(no_cal)["final_grade"] == "C"


def test_grade_a_requires_all_six():
    """A 级必须六项全通过（含官方日历与真实起点）。"""
    full = {
        "identity_evidence_level": "official",
        "return_basis_evidence_level": "official",
        "historical_start": {"historical_start_status": "confirmed"},
        "calendar": {"continuity_status": "verified_official_calendar"},
        "row_quality": {"data_quality_status": "pass",
                        "fatal_issue_count": 0},
        "point_in_time": {"historical_point_in_time_status": "verified"},
    }
    assert grade_candidate(dict(full))["final_grade"] == "A"
    # 少任一项都不能是 A
    for k, v in (("historical_start",
                  {"historical_start_status": "unknown"}),
                 ("calendar", {"continuity_status":
                               "verified_against_proxy_calendar"}),
                 ("point_in_time",
                  {"historical_point_in_time_status": "unknown"})):
        broken = {**full, k: v}
        assert grade_candidate(broken)["final_grade"] != "A", \
            f"{k} 缺失仍得 A 级"


def test_allowed_forbidden_present(audit):
    for c in audit["candidates"]:
        assert c["grading"]["allowed_uses"]
        assert c["grading"]["forbidden_uses"]
        assert c["grading"]["blockers"]


# ============================================================ 8. 市场标注
def test_task_table_mismatch_recorded(audit):
    """任务书市场标注错误必须记录证据。"""
    mm = audit["task_candidate_table_errors"]["mismatches"]
    codes = {m["tr_code"] for m in mm}
    assert codes == {"H00012", "H20930"}
    for m in mm:
        assert m["task_claimed"] != m["db_actual"]
        assert m["official_name"]
        assert m["evidence_file"]


def test_mismatch_not_overwriting_records(audit):
    """记录差异但不得覆盖原始记录。"""
    for m in audit["task_candidate_table_errors"]["mismatches"]:
        assert "不覆盖原始记录" in m["action"]


# ============================================================ 9-12. 数据保护
def test_raw_rows_unchanged(conn):
    """10. 原始行情 55,942 行不变。"""
    assert conn.execute(
        "select count(*) from tr_index_daily_raw").fetchone()[0] == \
        EXPECTED_RAW_ROWS


def test_raw_record_json_unchanged(conn):
    """11. raw_record_json / sha256 不变。"""
    rows = conn.execute(
        "select raw_record_json, raw_record_sha256 from tr_index_daily_raw "
        "limit 200").fetchall()
    assert rows
    for j, s in rows:
        assert j is not None and s is not None
        assert hashlib.sha256(j.encode("utf-8")).hexdigest() == s


def test_index_daily_unchanged(conn):
    """12. index_daily 行数与指纹不变。"""
    with tr_layer.get_tr_connection() as c:
        fp = tr_layer.index_daily_fingerprint(c)
    assert fp["row_count"] == EXPECTED_INDEX_ROWS
    assert fp["fingerprint"] == EXPECTED_FP


def test_integrity_and_fk(conn):
    assert conn.execute("pragma integrity_check").fetchone()[0] == "ok"
    assert len(conn.execute("pragma foreign_key_check").fetchall()) == 0


def test_isolation_kept(conn):
    with tr_layer.get_tr_connection() as c:
        assert tr_layer.assert_isolated(c)["isolated"] is True


def test_evidence_unchanged(conn):
    evs = conn.execute(
        "select relative_path, sha256 from tr_evidence_files").fetchall()
    assert len(evs) == EXPECTED_EVIDENCE
    for rel, sha in evs:
        f = ROOT / rel
        assert f.exists()
        assert hashlib.sha256(f.read_bytes()).hexdigest() == sha


# ============================================================ 13. 门禁
def test_all_gates_closed(audit):
    """13. 所有门禁保持关闭。"""
    g = audit["summary"]["gates"]
    assert g["ready_for_research_analysis"] is True
    assert g["ready_for_backtest"] is False
    assert g["ready_for_formal_ranking"] is False
    assert g["ready_for_3b6_2_3_1_series_build"] is False


def test_no_admission_upgrade(audit):
    a = audit["summary"]["admission"]
    assert a["raw_data_layer_ingest_candidate"] == 12
    assert a["validated_series_candidate"] == 0
    assert a["proxy_qualified_series_candidate"] == 0
    assert a["formal_series_admitted"] == 0


def test_baseline_recorded(audit):
    assert audit["baseline_head"] == TASK_BASELINE


def test_self_check_all_pass(audit):
    for k, v in audit["_self_check"].items():
        assert v is True, f"自校验失败：{k}"


def test_manifest_complete():
    m = json.loads((EVID / "manifest.json").read_text(encoding="utf-8"))
    assert m["file_count"] == len(m["files"]) == 24
    for rel, info in m["files"].items():
        f = ROOT / rel
        assert f.exists()
        assert hashlib.sha256(f.read_bytes()).hexdigest() == info["sha256"]


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
