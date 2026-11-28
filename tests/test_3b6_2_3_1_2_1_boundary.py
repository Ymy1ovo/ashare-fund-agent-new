"""阶段3B-6.2.3.1.2.1 质量分级与连续性判定边界修复专项测试。

**真实调用审计函数 + 真实读取数据库**。
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
    audit_calendar, audit_row_quality, grade_candidate)

REPORTS = ROOT / "reports"
EVID = REPORTS / "evidence" / "phase3B6_2_3_1_2"
AUDIT = REPORTS / "phase3B6_2_3_1_2_audit.json"
GRADING = REPORTS / "phase3B6_2_3_1_2_candidate_grading.json"

EXPECTED_FP = (
    "dbbd07c1339e99f27b0aeadb43eb56848776dbbad97f3fb7b9748bbd2f1e61f6")
EXPECTED_RAW_ROWS = 55942
EXPECTED_INDEX_ROWS = 50603
EXPECTED_EVIDENCE = 34
TASK_BASELINE = "aaa41cca487a90758ab17f24051fc2e93f52830c"

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
    return json.loads(GRADING.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def a_cal(conn) -> set:
    return {r[0] for r in conn.execute(
        "select trade_date from trade_calendar")}


def _rows(conn, code) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "select trade_date, open, high, low, close, volume, amount, "
        "change, change_pct, row_quality_status "
        "from tr_index_daily_raw where tr_code=? order by trade_date",
        (code,))]


def _cand(audit, code) -> dict:
    return next(c for c in audit["candidates"] if c["tr_code"] == code)


def _mk_row(d, close, prev_note="", **kw):
    r = {"trade_date": d, "close": close, "open": close,
         "high": close, "low": close, "volume": 100.0, "amount": 1000.0,
         "change": None, "change_pct": None}
    r.update(kw)
    return r


# ============================================================ 修复1：连续性
def test_suspected_closed_blocks_proxy_verification(conn, a_cal):
    """1. 有疑似休市记录的候选必须是 has_unresolved_suspicion。"""
    # 用真实候选 H00300（有 2018-06-18 疑似休市）
    rows = _rows(conn, "H00300")
    r = audit_calendar({"market_group": "stock",
                        "_synthetic_row": rows[0]["trade_date"]},
                       rows, a_cal)
    assert r["suspected_market_closed_count"] > 0
    assert r["continuity_status"] == "has_unresolved_suspicion", \
        f"疑似休市未被阻断：{r['continuity_status']}"


def test_no_suspected_can_be_proxy_verified(conn, a_cal):
    """2. 无疑似休市且无缺失的候选可以为 verified_against_proxy_calendar。"""
    # 用真实候选 399997CNY02（无 2018-06-18 记录）
    rows = _rows(conn, "399997CNY02")
    r = audit_calendar({"market_group": "stock",
                        "_synthetic_row": rows[0]["trade_date"]},
                       rows, a_cal)
    assert r["suspected_market_closed_count"] == 0
    assert r["missing_trading_days"] == 0
    assert r["continuity_status"] == "verified_against_proxy_calendar"


def test_missing_trading_days_gives_has_issues(conn, a_cal):
    """3. 存在缺失交易日必须判 has_issues。"""
    # 构造：删掉 2020 年若干交易日
    rows = [r for r in _rows(conn, "399997CNY02")
            if not (r["trade_date"].startswith("202003")
                    and r["trade_date"] < "20200310")]
    r = audit_calendar({"market_group": "stock",
                        "_synthetic_row": rows[0]["trade_date"]},
                       rows, a_cal)
    assert r["missing_trading_days"] > 0
    assert r["continuity_status"] == "has_issues"


def test_bond_hk_still_unknown(conn, a_cal):
    """4. 债券、港股仍然 unknown。"""
    for code in ("H00012", "N00012"):
        rows = _rows(conn, code)
        r = audit_calendar({"market_group": "bond",
                            "_synthetic_row": rows[0]["trade_date"]},
                           rows, a_cal)
        assert r["continuity_status"] == "unknown"
    rows = _rows(conn, "H20930")
    r = audit_calendar({"market_group": "hk",
                        "_synthetic_row": rows[0]["trade_date"]},
                       rows, a_cal)
    assert r["continuity_status"] == "unknown"


def test_suspected_not_bypassing_continuity(conn, a_cal):
    """5. 疑似休市记录不能绕过连续性阻断。"""
    rows = _rows(conn, "H20539")
    r = audit_calendar({"market_group": "stock",
                        "_synthetic_row": rows[0]["trade_date"]},
                       rows, a_cal)
    det = r["outside_detail"]
    susp = [x for x in det if x["classification"] == "suspected_market_closed"]
    assert susp, "该候选应有疑似休市记录"
    assert r["continuity_status"] != "verified_against_proxy_calendar"
    assert r["continuity_status"] == "has_unresolved_suspicion"


def test_all_12_real_candidates_checked(audit):
    """检查全部 12 个真实候选（非人工样例）。"""
    for c in audit["candidates"]:
        cal = c["calendar"]
        susp_n = cal.get("suspected_market_closed_count", 0)
        if susp_n > 0:
            assert cal["continuity_status"] == "has_unresolved_suspicion", \
                f"{c['tr_code']} 有 {susp_n} 条疑似休市却判 {cal['continuity_status']}"


def test_continuity_distribution_matches_baseline(audit):
    """修复后分布必须与上一阶段原始五态分布一致。"""
    d = audit["summary"]["continuity_distribution"]
    assert d.get("verified_official_calendar", 0) == 0
    assert d.get("verified_against_proxy_calendar", 0) == 1
    assert d.get("has_unresolved_suspicion", 0) == 8
    assert d.get("has_issues", 0) == 0
    assert d.get("unknown", 0) == 3
    assert sum(d.values()) == 12


def test_closed_placeholder_records_preserved(conn):
    """2018-06-18 疑似休市原始记录必须保留。"""
    n = conn.execute(
        "select count(*) from tr_index_daily_raw "
        "where trade_date='20180618' and "
        "row_quality_status='suspected_market_closed_placeholder'"
    ).fetchone()[0]
    assert n == 8


def test_no_official_calendar_upgrade(audit):
    """代理验证绝对不能升级为官方验证。"""
    for c in audit["candidates"]:
        assert c["calendar"]["calendar_is_official"] is False
        assert c["calendar"]["continuity_status"] != \
            "verified_official_calendar"


# ============================================================ 修复2：判级
def _base_cand(**over):
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
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = {**base[k], **v}
        else:
            base[k] = v
    return base


def test_h20184_real_data_graded_d(audit):
    """6. H20184 真实数据必须评为 D。"""
    c = _cand(audit, "H20184")
    assert c["row_quality"]["fatal_issue_count"] == 1
    assert c["row_quality"]["data_quality_status"] == "has_fatal"
    assert c["grading"]["final_grade"] == "D", \
        f"H20184 被评为 {c['grading']['final_grade']}"


def test_close_zero_graded_d():
    """7. 构造 close 为 0 的候选必须评为 D。"""
    c = _base_cand(row_quality={"data_quality_status": "has_fatal",
                                "fatal_issue_count": 1})
    assert grade_candidate(c)["final_grade"] == "D"


def test_close_negative_graded_d():
    """8. 构造 close 为负值的候选必须评为 D。"""
    rows = [_mk_row("20200102", 100.0), _mk_row("20200103", -5.0)]
    q = audit_row_quality({"market_group": "stock"}, rows, None)
    assert q["fatal_issue_count"] >= 1
    c = _base_cand(row_quality=q)
    assert grade_candidate(c)["final_grade"] == "D"


def test_calendar_unknown_no_fatal_graded_c():
    """9. 身份口径通过、日历 unknown、无致命 → C。"""
    c = _base_cand(calendar={"continuity_status": "unknown"})
    assert grade_candidate(c)["final_grade"] == "C"


def test_proxy_calendar_and_quality_graded_b():
    """10. 身份口径通过、代理日历、质量通过 → B。"""
    c = _base_cand()
    assert grade_candidate(c)["final_grade"] == "B"


def test_all_six_graded_a():
    """11. 六项全部通过 → A。"""
    c = _base_cand(
        historical_start={"historical_start_status": "confirmed"},
        calendar={"continuity_status": "verified_official_calendar"},
        point_in_time={"historical_point_in_time_status": "verified"})
    assert grade_candidate(c)["final_grade"] == "A"


def test_d_not_intercepted_by_c():
    """12. D 级不会被 C 级分支提前截获。"""
    # 日历 unknown（本来是 C 的条件）+ 致命质量 → 必须是 D
    c = _base_cand(calendar={"continuity_status": "unknown"},
                   row_quality={"data_quality_status": "has_fatal",
                                "fatal_issue_count": 1})
    g = grade_candidate(c)
    assert g["final_grade"] == "D", f"被 C 截获：{g['final_grade']}"
    assert g["grade_priority_rule"] == "A → D → B → C → UNKNOWN"


def test_identity_missing_graded_unknown():
    """身份不足 → UNKNOWN。"""
    c = _base_cand(identity_evidence_level="none")
    assert grade_candidate(c)["final_grade"] == "UNKNOWN"


def test_grade_distribution_from_real_data(audit):
    """分级分布必须从真实数据重算，不得硬编码。"""
    g = audit["summary"]["grade_distribution"]
    assert sum(g.values()) == 12
    # D 级必须恰好是致命质量候选数
    fatal_n = sum(1 for c in audit["candidates"]
                  if c["row_quality"]["fatal_issue_count"] > 0)
    assert g.get("D", 0) == fatal_n
    # A 级必须为 0（三项关键证据缺失）
    assert g.get("A", 0) == 0


def test_grading_file_consistent(audit, grading):
    a = {c["tr_code"]: c["grading"]["final_grade"]
         for c in audit["candidates"]}
    g = {c["tr_code"]: c["final_grade"] for c in grading["candidates"]}
    assert a == g


# ============================================================ 修复3：无效前值
def test_invalid_prev_close_blocks_return_calc():
    """13. 无效前值不得制造连带收益异常。"""
    rows = [
        _mk_row("20130627", 3000.0),
        _mk_row("20130628", 0.0),          # 无效
        _mk_row("20130701", 3100.0),
    ]
    q = audit_row_quality({"market_group": "stock"}, rows, None)
    blocked = q["checks"]["blocked_by_invalid_previous_close"]
    assert blocked["count"] >= 1, "未记录无效前值阻断"
    # 不得产生虚假 extreme_jump
    assert q["checks"]["extreme_jump"]["count"] == 0, \
        f"无效前值产生了虚假跳变：{q['checks']['extreme_jump']['sample']}"


def test_invalid_prev_close_no_change_inconsistency():
    """无效前值不得产生 change 不一致。"""
    rows = [
        _mk_row("20130627", 3000.0),
        _mk_row("20130628", 0.0),
        _mk_row("20130701", 3100.0, change=3100.0, change_pct=100.0),
    ]
    q = audit_row_quality({"market_group": "stock"}, rows, None)
    assert q["checks"]["change_inconsistent"]["count"] == 0
    assert q["checks"]["change_pct_inconsistent"]["count"] == 0


def test_h20184_real_has_blocked_count(audit):
    """H20184 真实数据必须记录无效前值阻断。"""
    c = _cand(audit, "H20184")
    b = c["row_quality"]["checks"]["blocked_by_invalid_previous_close"]
    assert b["count"] >= 1


def test_abnormal_value_still_preserved(conn):
    """原始异常值必须保留（不得修正）。"""
    r = conn.execute(
        "select close from tr_index_daily_raw "
        "where tr_code='H20184' and trade_date='20130628'").fetchone()
    assert r["close"] == 0.0


# ============================================================ 修复4：用途限制
def test_usage_restrictions_present(audit):
    """14. 每个候选必须有显式质量筛选规则。"""
    for c in audit["candidates"]:
        u = c["data_usage_restrictions"]
        assert u["rule"]
        assert "不得默认使用全部" in u["rule"]
        assert u["excluded_count"] == len(u["must_exclude_before_return_calc"])
        assert u["excluded_count"] + u["usable_after_exclusion"] == \
            c["row_count"]


def test_excluded_records_are_abnormal(audit):
    """被排除的记录必须是异常标记行。"""
    for c in audit["candidates"]:
        for x in c["data_usage_restrictions"]["must_exclude_before_return_calc"]:
            assert x["row_quality_status"] != "normal_unverified"


def test_residual_continuity_gap_declared(audit):
    """排除异常行后仍存在连续性缺口时必须声明。"""
    for c in audit["candidates"]:
        u = c["data_usage_restrictions"]
        if c["calendar"]["continuity_status"] != \
                "verified_against_proxy_calendar":
            assert u["residual_continuity_gap"] is True
            assert "不得描述为官方完整历史序列" in u["residual_note"]


def test_synthetic_rows_in_exclusion_list(audit):
    """12 条疑似合成行必须在排除清单中。"""
    for c in audit["candidates"]:
        excl = c["data_usage_restrictions"]["must_exclude_before_return_calc"]
        assert any(x["row_quality_status"] == "suspected_synthetic"
                   for x in excl), f"{c['tr_code']} 未排除合成行"


# ============================================================ 修复5：质量检查
def test_non_trading_date_filled_for_stock(conn, a_cal):
    """15. A 股候选的 non_trading_date 必须实际填充。"""
    rows = _rows(conn, "H00300")
    q = audit_row_quality(
        {"market_group": "stock",
         "_synthetic_row": rows[0]["trade_date"]}, rows, a_cal)
    assert q["calendar_diagnostic"]["applicable"] is True
    assert q["calendar_diagnostic"]["official"] is False
    assert q["checks"]["non_trading_date"]["count"] > 0, \
        "non_trading_date 未被填充"


def test_non_trading_date_not_applicable_for_bond(conn, a_cal):
    """债券不得借用 A 股日历做非交易日诊断。"""
    rows = _rows(conn, "H00012")
    q = audit_row_quality(
        {"market_group": "bond",
         "_synthetic_row": rows[0]["trade_date"]}, rows, a_cal)
    assert q["calendar_diagnostic"]["applicable"] is False
    assert q["checks"]["non_trading_date"]["count"] == 0
    assert "不得借用 A 股日历" in q["calendar_diagnostic"]["reason"]


def test_non_trading_date_not_applicable_for_hk(conn, a_cal):
    """港股不得借用 A 股日历。"""
    rows = _rows(conn, "H20930")
    q = audit_row_quality(
        {"market_group": "hk",
         "_synthetic_row": rows[0]["trade_date"]}, rows, a_cal)
    assert q["calendar_diagnostic"]["applicable"] is False


def test_non_trading_is_proxy_anomaly_not_official():
    """代理日历发现的非交易日只能标为代理异常。"""
    rows = [_mk_row("20200101", 100.0),   # 元旦，非交易日
            _mk_row("20200102", 101.0)]
    q = audit_row_quality({"market_group": "stock"}, rows,
                          {"2020-01-02"})
    nt = q["checks"]["non_trading_date"]["sample"]
    assert nt
    assert "代理异常" in nt[0]["note"]
    assert "非官方休市认定" in nt[0]["note"]


# ---- 逐项真实函数测试（不得只测字段名） ----
def test_check_illegal_date():
    rows = [_mk_row("2020-01-02", 100.0)]     # 格式错误
    q = audit_row_quality({"market_group": "stock"}, rows, None)
    assert q["checks"]["illegal_date"]["count"] == 1


def test_check_duplicate_date():
    rows = [_mk_row("20200102", 100.0), _mk_row("20200102", 101.0)]
    q = audit_row_quality({"market_group": "stock"}, rows, None)
    assert q["checks"]["duplicate_date"]["count"] == 1


def test_check_close_zero():
    rows = [_mk_row("20200102", 0.0)]
    q = audit_row_quality({"market_group": "stock"}, rows, None)
    assert q["checks"]["close_non_positive"]["count"] == 1


def test_check_high_lt_low():
    rows = [_mk_row("20200102", 100.0, high=90.0, low=110.0)]
    q = audit_row_quality({"market_group": "stock"}, rows, None)
    assert q["checks"]["high_lt_low"]["count"] == 1


def test_check_ohlc_inconsistent():
    rows = [_mk_row("20200102", 100.0, open=100.0, high=95.0, low=90.0)]
    q = audit_row_quality({"market_group": "stock"}, rows, None)
    assert q["checks"]["ohlc_inconsistent"]["count"] == 1


def test_check_volume_negative():
    rows = [_mk_row("20200102", 100.0, volume=-1.0)]
    q = audit_row_quality({"market_group": "stock"}, rows, None)
    assert q["checks"]["volume_negative"]["count"] == 1


def test_check_change_inconsistent():
    rows = [_mk_row("20200102", 100.0),
            _mk_row("20200103", 110.0, change=1.0)]
    q = audit_row_quality({"market_group": "stock"}, rows, None)
    assert q["checks"]["change_inconsistent"]["count"] == 1


def test_check_change_pct_inconsistent():
    rows = [_mk_row("20200102", 100.0),
            _mk_row("20200103", 110.0, change=10.0, change_pct=1.0)]
    q = audit_row_quality({"market_group": "stock"}, rows, None)
    assert q["checks"]["change_pct_inconsistent"]["count"] == 1


def test_check_extreme_jump():
    rows = [_mk_row("20200102", 100.0), _mk_row("20200103", 200.0)]
    q = audit_row_quality({"market_group": "stock"}, rows, None)
    assert q["checks"]["extreme_jump"]["count"] == 1


def test_check_repeated_price_run():
    rows = [_mk_row(f"2020010{i}", 100.0) for i in range(1, 7)]
    q = audit_row_quality({"market_group": "stock"}, rows, None)
    assert q["checks"]["repeated_price_run"]["count"] >= 1


# ============================================================ 数据保护
def test_raw_rows_unchanged(conn):
    assert conn.execute(
        "select count(*) from tr_index_daily_raw").fetchone()[0] == \
        EXPECTED_RAW_ROWS


def test_index_daily_unchanged(conn):
    with tr_layer.get_tr_connection() as c:
        fp = tr_layer.index_daily_fingerprint(c)
    assert fp["row_count"] == EXPECTED_INDEX_ROWS
    assert fp["fingerprint"] == EXPECTED_FP


def test_raw_record_unchanged(conn):
    rows = conn.execute(
        "select raw_record_json, raw_record_sha256 from tr_index_daily_raw "
        "limit 200").fetchall()
    for j, s in rows:
        assert hashlib.sha256(j.encode("utf-8")).hexdigest() == s


def test_evidence_unchanged(conn):
    evs = conn.execute(
        "select relative_path, sha256 from tr_evidence_files").fetchall()
    assert len(evs) == EXPECTED_EVIDENCE
    for rel, sha in evs:
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == sha


def test_integrity_and_fk(conn):
    assert conn.execute("pragma integrity_check").fetchone()[0] == "ok"
    assert len(conn.execute("pragma foreign_key_check").fetchall()) == 0


def test_isolation_kept(conn):
    with tr_layer.get_tr_connection() as c:
        assert tr_layer.assert_isolated(c)["isolated"] is True


def test_synthetic_rows_preserved(conn):
    assert conn.execute(
        "select count(*) from tr_index_daily_raw "
        "where row_quality_status='suspected_synthetic'").fetchone()[0] == 12


def test_gates_closed(audit):
    g = audit["summary"]["gates"]
    assert g["ready_for_research_analysis"] is True
    assert g["ready_for_backtest"] is False
    assert g["ready_for_formal_ranking"] is False
    assert g["ready_for_3b6_2_3_1_series_build"] is False
    a = audit["summary"]["admission"]
    assert a["validated_series_candidate"] == 0
    assert a["proxy_qualified_series_candidate"] == 0
    assert a["formal_series_admitted"] == 0


def test_baseline_recorded(audit):
    assert audit["baseline_head"] == TASK_BASELINE


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
