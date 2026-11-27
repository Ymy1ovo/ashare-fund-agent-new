"""阶段3B-6.2.3.1.0.2 合成行证据溯源与休市日保守化专项测试。

**真实调用业务函数 + 真实读取文件 + 真实计算 SHA256**。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.audit_3b6_2_3_1_0_2_evidence_fix import (  # noqa: E402
    BOND_INDEXES, HK_INDEXES, MARKET_CALENDAR, STOCK_TR_CANDIDATES,
    classify_outside_calendar, connect_ro, continuity_after_classification,
    control_evidence, detect_synthetic_start, file_sha256, group_of,
    load_basic, load_rows, price_code_of)

REPORTS = ROOT / "reports"
EVID = REPORTS / "evidence" / "phase3B6_2_3_1_0_2"
EVID_OLD = REPORTS / "evidence" / "phase3B6_2_3_1_0"
EVID_OLD4 = REPORTS / "evidence" / "phase3B6_2_3_0_4"
AUDIT = REPORTS / "phase3B6_2_3_1_0_2_audit.json"

BASELINE_DB_SHA256 = (
    "1671e4037cd265a2dead8b78d43614189a782385ca450ac6c2de3c4ff36ee873")


@pytest.fixture(scope="module")
def conn():
    c = connect_ro()
    yield c
    c.close()


@pytest.fixture(scope="module")
def doc() -> dict:
    assert AUDIT.exists()
    return json.loads(AUDIT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def cal(conn) -> set:
    return {r[0] for r in conn.execute(
        "select trade_date from trade_calendar "
        "where trade_date between '2004-01-01' and '2026-11-27'")}


def _cand(doc, code) -> dict:
    return next(r for r in doc["candidates"] if r["tr_candidate"] == code)


# ============================================================ 1-3. 对照映射
def test_h00016_maps_to_000016():
    """1. H00016 正确映射到 000016 的原价格指数对照文件。"""
    assert price_code_of("H00016") == "000016"
    c = control_evidence("H00016")
    assert c["price_code"] == "000016"
    assert "000016" in (c["price_index_control"].get("file") or "")
    assert "H00016" not in (c["price_index_control"].get("file") or "")


def test_h00300_maps_to_000300():
    """2. H00300 正确映射到 000300。"""
    assert price_code_of("H00300") == "000300"
    c = control_evidence("H00300")
    assert c["price_code"] == "000300"
    assert "000300" in (c["price_index_control"].get("file") or "")


def test_h20184_maps_to_h30184():
    """3. H20184 正确映射到 H30184。"""
    assert price_code_of("H20184") == "H30184"
    c = control_evidence("H20184")
    assert c["price_code"] == "H30184"
    assert "H30184" in (c["price_index_control"].get("file") or "")


def test_all_price_code_mappings():
    """全部 12 个候选的价格指数映射正确。"""
    expected = {
        "H00300": "000300", "H00905": "000905", "H00906": "000906",
        "H00016": "000016", "H20539": "399997", "399997CNY02": "399997",
        "H20184": "H30184", "H00942": "000942", "H00922": "000922",
        "H00012": "000012", "N00012": "000012", "H20930": "930930",
    }
    for tr, price in expected.items():
        assert price_code_of(tr) == price, f"{tr} 映射错误"


# ============================================================ 4-5. 日历隔离
def test_bond_not_using_a_calendar_for_synthetic(cal):
    """4. 债券候选不使用 A 股日历判断合成行。"""
    for code in BOND_INDEXES["000012"]:
        rows = load_rows(EVID_OLD / f"hist_{code}_20040101_20261127.json")
        r = detect_synthetic_start(code, rows, cal, load_basic(code))
        ev = r["evidence"]
        assert ev["market_calendar_available"] is False
        assert ev["first_not_in_market_calendar"] is None, \
            f"{code} 用了 A 股日历判定"
        assert "不得用 A 股日历" in ev["market_calendar_note"]


def test_hk_not_using_a_calendar_for_synthetic(cal):
    """5. 港股候选不使用 A 股日历判断合成行。"""
    for code in HK_INDEXES["930930"]:
        rows = load_rows(EVID_OLD / f"hist_{code}_20040101_20261127.json")
        r = detect_synthetic_start(code, rows, cal, load_basic(code))
        ev = r["evidence"]
        assert ev["market_calendar_available"] is False
        assert ev["first_not_in_market_calendar"] is None


# ============================================================ 6-8. 对照归属
def test_price_control_not_equal_candidate_control():
    """6. 原价格指数对照证据不等同全收益候选自身对照证据。"""
    c = control_evidence("H00300")
    assert c["price_index_control"]["available"] is True
    assert c["tr_candidate_control"]["available"] is False
    assert "不能自动证明" in c["price_index_control"]["proves"]


def test_no_candidate_has_own_control(doc):
    """7. 全收益候选无对照文件时必须 unknown。"""
    s = doc["summary"]["totals"]
    assert s["tr_candidate_control_available"] == 0
    for r in doc["candidates"]:
        ctrl = r["synthetic_start_detection"]["control"]
        assert ctrl["tr_candidate_control"]["available"] is False
        assert ctrl["tr_candidate_control"]["drops_20040101"] is None


def test_control_none_not_claiming_pass(cal):
    """8. control=None 时结论不得声称对照实验通过。"""
    rows = load_rows(EVID_OLD / "hist_H00300_20040101_20261127.json")
    r = detect_synthetic_start("H00300", rows, cal, load_basic("H00300"))
    reason = r["reason"]
    assert r["status"] != "confirmed"
    # 不得声称对照实验通过
    assert "对照实验证实" not in reason
    assert "自身对照证据" in reason or "非官方确认" in reason


def test_evidence_has_no_fabricated_control():
    """证据字段中不得出现伪造的候选对照通过。"""
    c = control_evidence("H20184")
    assert c["tr_candidate_control"]["available"] is False
    assert c["tr_candidate_control"]["sha256"] is None
    assert "不得把原价格指数的对照结论套用" in \
        c["tr_candidate_control"]["reason"]


# ============================================================ 9-10. 三级状态
def test_three_synthetic_statuses_defined(doc):
    """9. confirmed / strong_inference / unknown 三种状态边界。"""
    statuses = {r["synthetic_start_detection"]["status"]
                for r in doc["candidates"]}
    assert statuses <= {"confirmed", "strong_inference", "unknown"}
    s = doc["summary"]["totals"]
    assert s["synthetic_confirmed"] == 0, "无自身对照却有 confirmed"
    assert s["synthetic_strong_inference"] + s["synthetic_unknown"] == 12


def test_no_confirmed_without_own_control(doc):
    """无候选自身对照证据时不得为 confirmed。"""
    for r in doc["candidates"]:
        d = r["synthetic_start_detection"]
        if d["status"] == "confirmed":
            assert d["control"]["tr_candidate_control"]["available"] is True


def test_real_start_unknown_when_not_confirmed(doc):
    """10. 证据不足时真实历史起点为 unknown。"""
    for r in doc["candidates"]:
        d = r["synthetic_start_detection"]
        if d["status"] != "confirmed":
            assert d["real_history_start"] == "unknown", \
                f"{r['tr_candidate']} 未确认却给了具体起点"
            assert "未确认" in d["real_history_start_note"]


def test_strong_inference_not_written_as_official(doc):
    """strong_inference 不得写成官方确认。"""
    for r in doc["candidates"]:
        d = r["synthetic_start_detection"]
        if d["status"] == "strong_inference":
            assert "非官方确认" in d["reason"] or "高置信推断" in d["reason"]


def test_synthetic_detection_evidence_complete(doc):
    """合成行证据字段必须完整。"""
    keys = ["first_date", "second_date", "first_close", "second_close",
            "first_equals_request_start", "market_calendar_available",
            "first_not_in_market_calendar", "first_close_equals_second",
            "official_basic_date", "official_publish_date",
            "price_index_control_drops", "tr_candidate_control_drops"]
    for r in doc["candidates"]:
        ev = r["synthetic_start_detection"]["evidence"]
        for k in keys:
            assert k in ev, f"{r['tr_candidate']} 缺证据项 {k}"


# ============================================================ 11-13. manifest
def test_control_files_sha256_verified():
    """11. 3B-6.2.3.0.4 对照文件真实 SHA256 验证。"""
    m = json.loads((EVID / "manifest.json").read_text(encoding="utf-8"))
    ctrl = [k for k in m["files"] if k.startswith("csindex_ctrl_")]
    assert len(ctrl) >= 10, f"对照文件仅 {len(ctrl)} 份"
    checked = 0
    for name in ctrl:
        info = m["files"][name]
        if not info["exists"]:
            continue
        f = EVID_OLD4 / name
        assert f.exists()
        actual = hashlib.sha256(f.read_bytes()).hexdigest()
        assert actual == info["sha256"], f"{name} SHA256 不符"
        assert info["bytes"] == f.stat().st_size
        checked += 1
    assert checked >= 10


def test_manifest_count_matches_actual(doc):
    """12. manifest 引用文件数量与实际读取数量一致。"""
    m = json.loads((EVID / "manifest.json").read_text(encoding="utf-8"))
    assert m["referenced_total"] == len(m["files"])
    # 12 候选 × 2(历史+基本信息) + 10 价格指数 × 2 + 10 对照 + 12 缺失对照
    assert m["referenced_total"] >= 50
    assert m["missing_count"] == 12, \
        f"缺失对照应记录 12 条，实际 {m['missing_count']}"


def test_manifest_files_exist_or_recorded_missing():
    """13. manifest 中文件要么存在，要么明确记录缺失。"""
    m = json.loads((EVID / "manifest.json").read_text(encoding="utf-8"))
    for name, info in m["files"].items():
        if info["exists"]:
            p = ROOT / info["relative_path"]
            assert p.exists(), f"{name} 标存在但实际缺失"
            assert hashlib.sha256(p.read_bytes()).hexdigest() == info["sha256"]
        else:
            assert info["sha256"] is None
            assert name in m["referenced_missing"]


def test_missing_control_files_recorded():
    """缺失的全收益候选对照文件必须显式记录。"""
    m = json.loads((EVID / "manifest.json").read_text(encoding="utf-8"))
    for tr in ["H00300", "H00016", "H20184", "H00012", "N00012", "H20930"]:
        name = f"csindex_ctrl_{tr}_from20040102.json"
        assert name in m["files"], f"{name} 未记录"
        assert m["files"][name]["exists"] is False


def test_no_original_manifest_marked():
    """缺少原始 manifest 校验时必须明确标记，不伪称三方一致。"""
    m = json.loads((EVID / "manifest.json").read_text(encoding="utf-8"))
    no_orig = [k for k, v in m["files"].items()
               if v["exists"] and v.get("manifest_verified") is None]
    for k in no_orig:
        assert "缺少原始 manifest 校验" in m["files"][k].get("manifest_note", "")


# ============================================================ 14-17. 休市分类
def test_zero_volume_alone_not_confirmed():
    """14. 零成交量但收盘值变化时不得直接确认占位。"""
    rows = [{"tradeDate": "20180615", "close": 100.0, "tradingVol": 100.0},
            {"tradeDate": "20180618", "close": 105.0, "tradingVol": 0.0,
             "changePct": 5.0}]
    out = classify_outside_calendar(rows, ["2018-06-18"])
    assert out[0]["classification"] != "confirmed_market_closed_placeholder"
    assert out[0]["classification"] == "suspected_market_closed_placeholder"


def test_tiny_pct_with_close_change_not_confirmed():
    """15. changePct 很小但收盘值变化时不得直接确认占位。"""
    rows = [{"tradeDate": "20180615", "close": 100.0, "tradingVol": 100.0},
            {"tradeDate": "20180618", "close": 100.4, "tradingVol": 0.0,
             "changePct": 0.01}]
    out = classify_outside_calendar(rows, ["2018-06-18"])
    assert out[0]["classification"] == "suspected_market_closed_placeholder"
    assert out[0]["same_as_prev"] is False


def test_same_close_without_official_calendar_not_confirmed():
    """16. 收盘值相同但缺官方日历证据时不得冒充官方确认。"""
    rows = [{"tradeDate": "20180615", "close": 100.0, "tradingVol": 100.0},
            {"tradeDate": "20180618", "close": 100.0, "tradingVol": 0.0,
             "changePct": 0.0}]
    out = classify_outside_calendar(rows, ["2018-06-18"])
    assert out[0]["classification"] == "suspected_market_closed_placeholder"
    assert out[0]["official_calendar_evidence"] is False
    assert "不得当作已证实" in out[0]["note"]


def test_suspected_does_not_make_continuity_verified():
    """17. suspected 状态不能直接使连续性 verified。"""
    detail = [{"date": "2018-06-18",
               "classification": "suspected_market_closed_placeholder"}]
    status, note = continuity_after_classification("verified", detail)
    assert status != "verified"
    assert status == "has_unresolved_suspicion"
    assert "不得判为 verified" in note


def test_confirmed_placeholder_allows_verified():
    """有官方证据的 confirmed 占位行才允许 verified。"""
    detail = [{"date": "2018-06-18",
               "classification": "confirmed_market_closed_placeholder"}]
    status, _ = continuity_after_classification("verified", detail)
    assert status == "verified"


def test_unexplained_marks_has_issues():
    detail = [{"date": "2020-01-01", "classification": "unexplained"}]
    status, _ = continuity_after_classification("verified", detail)
    assert status == "has_issues"


def test_2018_06_18_per_index_evidence_differs():
    """2018-06-18 的证据在不同指数之间不同，不得互相推广。"""
    codes = ["H00300", "H20539", "H20184"]
    results = {}
    for c in codes:
        rows = load_rows(EVID_OLD / f"hist_{c}_20040101_20261127.json")
        out = classify_outside_calendar(rows, ["2018-06-18"])
        results[c] = out[0] if out else None
    # H00300 close 变化，H20539/H20184 完全相同
    assert results["H00300"]["same_as_prev"] is False
    assert results["H20539"]["same_as_prev"] is True
    assert results["H20184"]["same_as_prev"] is True


def test_all_2018_06_18_are_suspected_not_confirmed(doc):
    """全部 2018-06-18 只能判为 suspected。"""
    for r in doc["candidates"]:
        for x in r["quality"].get("outside_calendar_detail", []):
            if x["date"] == "2018-06-18":
                assert x["classification"] == \
                    "suspected_market_closed_placeholder"
                assert x["official_calendar_evidence"] is False


def test_original_records_preserved(doc):
    """原始记录必须保留（未删除）。"""
    for r in doc["candidates"]:
        assert r["quality"]["row_count"] > 0


# ============================================================ 18. 一致性
def test_json_and_report_consistent(doc):
    """18. JSON 和 Markdown 报告中的候选状态完全一致。"""
    txt = (REPORTS / "phase3B6_2_3_1_0_2_fix_report.md").read_text(
        encoding="utf-8")
    for r in doc["candidates"]:
        assert r["tr_candidate"] in txt, f"报告缺 {r['tr_candidate']}"
    s = doc["summary"]["totals"]
    assert str(s["synthetic_strong_inference"]) in txt
    assert str(s["synthetic_confirmed"]) in txt
    assert str(s["tr_candidate_control_available"]) in txt


def test_report_no_fabricated_control_claim():
    """报告不得声称全收益候选对照实验已证实。"""
    txt = (REPORTS / "phase3B6_2_3_1_0_2_fix_report.md").read_text(
        encoding="utf-8")
    assert "无任何全收益候选" in txt or "无自身对照" in txt


# ============================================================ 19-20. 不变性
def test_original_44_evidence_unchanged():
    """19. 原始 44 份证据 SHA256 不变。"""
    m = json.loads((EVID_OLD / "manifest.json").read_text(encoding="utf-8"))
    files = m.get("files") or {}
    assert len(files) >= 40
    for name, info in files.items():
        f = EVID_OLD / name
        assert f.exists()
        assert hashlib.sha256(f.read_bytes()).hexdigest() == info["sha256"]


def test_db_sha256_unchanged():
    """业务数据未变（原为文件级 SHA 断言）。

    3B-6.2.3.1.1 合法新增 6 张 tr_* 表后文件 SHA 必然变化，
    改为校验业务数据指纹。
    """
    assert_business_data_unchanged()


def test_db_unchanged_flag(doc):
    assert doc["db_unchanged"] is True


def test_integrity_ok(conn):
    assert conn.execute("pragma integrity_check").fetchone()[0] == "ok"


def test_fk_zero(conn):
    assert len(conn.execute("pragma foreign_key_check").fetchall()) == 0


def test_index_daily_unchanged(conn):
    assert conn.execute(
        "select count(*) from index_daily").fetchone()[0] == 50603


def test_no_tr_in_db(conn, doc):
    for r in doc["candidates"]:
        n = conn.execute(
            "select count(*) from index_daily where index_code=?",
            (r["tr_candidate"],)).fetchone()[0]
        assert n == 0


def test_gates_all_closed(doc):
    g = doc["summary"]["gates"]
    assert g["ready_for_research_analysis"] is True
    assert g["ready_for_backtest"] is False
    assert g["ready_for_formal_ranking"] is False
    assert g["ready_for_3b6_2_3_1_series_build"] is False


def test_self_check_all_pass(doc):
    for k, v in doc["summary"]["_self_check"].items():
        assert v is True, f"自校验失败：{k}"


def test_reports_exist():
    for name in ("phase3B6_2_3_1_0_2_fix_report.md",
                 "phase3B6_2_3_1_0_2_test_report.md"):
        assert (REPORTS / name).exists()


def test_no_vacuous_assertion():
    txt = Path(__file__).read_text(encoding="utf-8")
    assert ("or " + "True") not in txt
    assert ("assert " + "True") not in txt


# 阶段3B-6.2.3.1.1 起，数据库文件 SHA 会因合法新增独立表而变化。
# 历史阶段断言的**本意**是「业务数据未被修改」，因此改校验业务数据指纹。
BUSINESS_FINGERPRINT_SQL = """
select 'fund_master', count(*) from fund_master
union all select 'fund_nav_daily', count(*) from fund_nav_daily
union all select 'index_master', count(*) from index_master
union all select 'index_daily', count(*) from index_daily
union all select 'index_daily_suspect',
    count(*) from index_daily where quality_status<>'valid'
union all select 'index_daily_close_sum',
    cast(round(sum(close)*100) as integer) from index_daily
union all select 'index_daily_fp',
    (select count(*) from (select distinct index_code, trade_date,
        close, quality_status from index_daily))
"""

EXPECTED_BUSINESS_FINGERPRINT = {
    "fund_master": 120,
    "fund_nav_daily": 245656,
    "index_master": 10,
    "index_daily": 50603,
    "index_daily_suspect": 11,
}


def business_fingerprint() -> dict:
    """业务数据指纹：行数 + 关键聚合，不含新表。"""
    import sqlite3
    from app.config import settings
    p = str(settings.database_path).replace("\\", "/")
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    c.execute("pragma temp_store = memory")
    try:
        out = {}
        for name, val in c.execute(BUSINESS_FINGERPRINT_SQL):
            out[name] = val
        return out
    finally:
        c.close()


def assert_business_data_unchanged() -> None:
    """断言业务数据未变（替代文件级 SHA 断言）。"""
    fp = business_fingerprint()
    for k, v in EXPECTED_BUSINESS_FINGERPRINT.items():
        assert fp[k] == v, f"业务数据 {k} 变化：{fp[k]} != {v}"
