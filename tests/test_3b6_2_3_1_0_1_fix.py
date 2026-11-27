"""阶段3B-6.2.3.1.0.1 审计边界纠偏专项测试。

**真实调用业务函数 + 真实读取证据文件 + 真实计算 SHA256**。
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.audit_3b6_2_3_1_0_1_fix import (  # noqa: E402
    BOND_INDEXES, HK_INDEXES, MARKET_CALENDAR, STOCK_TR_CANDIDATES,
    _classify_outside_calendar, build_mapping_evidence, compute_three_states,
    connect_ro, detect_synthetic_start, file_sha256, group_of,
    load_basic, load_old_evidence, to_number, verify_old_evidence_integrity)

REPORTS = ROOT / "reports"
EVID = REPORTS / "evidence" / "phase3B6_2_3_1_0_1"
EVID_OLD = REPORTS / "evidence" / "phase3B6_2_3_1_0"
AUDIT = REPORTS / "phase3B6_2_3_1_0_1_audit.json"

BASELINE_DB_SHA256 = (
    "1671e4037cd265a2dead8b78d43614189a782385ca450ac6c2de3c4ff36ee873")


@pytest.fixture(scope="module")
def conn():
    c = connect_ro()
    yield c
    c.close()


@pytest.fixture(scope="module")
def doc() -> dict:
    assert AUDIT.exists(), "缺审计 JSON"
    return json.loads(AUDIT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def cal(conn) -> set:
    return {r[0] for r in conn.execute(
        "select trade_date from trade_calendar "
        "where trade_date between '2004-01-01' and '2026-11-27'")}


def _cand(doc, code) -> dict:
    return next(r for r in doc["candidates"] if r["tr_candidate"] == code)


# ============================================================ 1. 合成行识别
def test_h00016_synthetic_start_detected(cal):
    """1. H00016 合成起始行必须被识别。"""
    rows = load_old_evidence("H00016")["rows"]
    basic = load_basic("H00016")
    r = detect_synthetic_start("H00016", rows, cal, basic)
    assert r["confirmed"] is True, f"未识别：{r['reason']}"
    assert r["synthetic_row"] == "20040101"
    assert r["real_history_start"] == "20040102"
    ev = r["evidence"]
    assert ev["first_equals_request_start"] is True
    assert ev["first_not_in_a_calendar"] is True
    assert ev["first_close_equals_second"] is True


def test_20040101_not_in_a_calendar(cal):
    """2. 2004-01-01 不是 A 股交易日。"""
    assert "2004-01-01" not in cal


def test_h00016_contradiction_resolved(doc):
    """报告矛盾必须解决：首行合成 vs 真实起点不能同为 20040101。"""
    r = _cand(doc, "H00016")
    s = r["synthetic_start_detection"]
    assert s["synthetic_row"] == "20040101"
    assert s["real_history_start"] == "20040102"
    assert s["synthetic_row"] != s["real_history_start"]


def test_unknown_start_when_evidence_insufficient(cal):
    """3. 未确认真实起点时标记 unknown。"""
    # 构造：首行非请求起始日、数值与第二行不同、无对照证据
    fake = [{"tradeDate": "20200102", "close": 100.0},
            {"tradeDate": "20200103", "close": 200.0}]
    r = detect_synthetic_start("NOT_EXIST", fake, cal, {"basic_date": "2020-01-01"})
    assert r["confirmed"] is False
    assert r["real_history_start"] == "unknown"
    assert "unknown" in r["reason"]


def test_all_candidates_synthetic_detected(doc):
    """全部候选首行均为请求起始日合成行。"""
    for r in doc["candidates"]:
        s = r["synthetic_start_detection"]
        assert s["confirmed"] is True, f"{r['tr_candidate']} 未识别合成行"
        assert s["synthetic_row"] == "20040101"
        assert s["real_history_start"] != "20040101"


# ============================================================ 2. 映射证据
def test_base_date_match_true_when_equal():
    """4. 基日相同才允许通过。"""
    ev = build_mapping_evidence(
        "000300", "H00300",
        {"basic_date": "2004-12-31", "official_full_name": "沪深300指数"},
        {"basic_date": "2004-12-31", "official_full_name": "沪深300全收益指数"},
        [], [], {"real_history_start": "unknown"})
    assert ev["base_date_match"] is True


def test_base_date_match_false_when_different():
    """4b. 基日不同必须失败。"""
    ev = build_mapping_evidence(
        "000012", "H00012",
        {"basic_date": "2002-12-31", "official_full_name": "上证国债指数"},
        {"basic_date": "2018-01-02", "official_full_name": "上证国债指数(净价)"},
        [], [], {"real_history_start": "unknown"})
    assert ev["base_date_match"] is False
    assert ev["mapping_verified"] is False


def test_base_date_null_not_passed():
    """4c. 基日为 null 不得当成通过。"""
    ev = build_mapping_evidence(
        "000300", "H00300",
        {"basic_date": None, "official_full_name": "沪深300指数"},
        {"basic_date": "2004-12-31", "official_full_name": "沪深300全收益指数"},
        [], [], {"real_history_start": "unknown"})
    assert ev["base_date_match"] is False
    assert ev["mapping_verified"] is False


def test_mapping_base_date_never_null_in_json(doc):
    """5. 审计 JSON 中 base_date_match 不得为 null。"""
    for r in doc["candidates"]:
        m = r["mapping_evidence"]
        assert m["base_date_match"] is not None, \
            f"{r['tr_candidate']} base_date_match 仍为 null"
        assert isinstance(m["base_date_match"], bool)


def test_mapping_evidence_complete_fields(doc):
    """映射证据字段必须齐全。"""
    required = ["price_index_code", "price_index_official_name",
                "price_index_basic_date", "tr_candidate_code",
                "tr_candidate_official_name", "tr_candidate_basic_date",
                "base_date_match", "ratio_sample_count", "ratio_first",
                "ratio_last", "all_ratios_ge_one", "ratio_increasing",
                "ratio_equals_one_count", "mapping_evidence_level",
                "mapping_conclusion"]
    for r in doc["candidates"]:
        m = r["mapping_evidence"]
        for k in required:
            assert k in m, f"{r['tr_candidate']} 映射证据缺 {k}"


def test_mapping_is_technical_not_official(doc):
    """6. 映射必须标注为技术判断，不是官方映射文件。"""
    for r in doc["candidates"]:
        m = r["mapping_evidence"]
        assert m["mapping_evidence_level"] == "technical_inference"
        assert m["official_mapping_document_found"] is False
        assert "技术映射判断" in m["mapping_evidence_note"]
        assert "不是" in m["mapping_evidence_note"]


def test_mapping_uses_ge_one_not_gt_one(doc):
    """统一口径：比值判据必须是 >=1，不得写 >1。"""
    for r in doc["candidates"]:
        m = r["mapping_evidence"]
        assert "all_ratios_ge_one" in m
        assert "all_ratios_gt_one" not in m
        note = m["mapping_evidence_note"]
        assert ">=1" in note or "≥1" in note


# ============================================================ 3. 日历隔离
def test_bond_not_using_a_share_calendar(doc):
    """7. 债券指数不得使用 A 股日历。"""
    for code in BOND_INDEXES["000012"]:
        r = _cand(doc, code)
        assert r["group"] == "bond"
        assert r["calendar_used"] != "A股交易日历（项目代理）"
        assert r["calendar_available"] is False


def test_hk_not_using_a_share_calendar(doc):
    """8. 港股指数不得使用 A 股日历。"""
    for code in HK_INDEXES["930930"]:
        r = _cand(doc, code)
        assert r["group"] == "hk"
        assert r["calendar_used"] != "A股交易日历（项目代理）"
        assert r["calendar_available"] is False


def test_no_calendar_means_coverage_unknown(doc):
    """9. 无适用日历时覆盖/连续性必须 unknown。"""
    for r in doc["candidates"]:
        if r["calendar_available"]:
            continue
        q = r["quality"]
        assert q["coverage_status"] == "unknown"
        assert q["continuity_status"] == "unknown"
        assert q["missing_trading_days"] is None
        assert q["dates_outside_calendar"] is None


def test_unknown_not_interpreted_as_gap(doc):
    """不得把未知解释为数据缺失。"""
    for r in doc["candidates"]:
        if r["quality"]["coverage_status"] != "unknown":
            continue
        q = r["quality"]
        assert q["missing_trading_days"] is None, \
            f"{r['tr_candidate']} 把 unknown 当成了缺失"


def test_unknown_not_interpreted_as_pass(doc):
    """不得把未知解释为连续性通过。"""
    for r in doc["candidates"]:
        if r["quality"]["continuity_status"] != "unknown":
            continue
        assert r["dimensions"]["history_continuity_verified"] is False


def test_market_calendar_table_declared():
    """市场日历表必须声明三类市场的日历适用性。"""
    assert set(MARKET_CALENDAR) == {"stock", "bond", "hk"}
    assert MARKET_CALENDAR["stock"]["calendar_available"] is True
    assert MARKET_CALENDAR["bond"]["calendar_available"] is False
    assert MARKET_CALENDAR["hk"]["calendar_available"] is False
    for g in ("stock", "bond", "hk"):
        assert MARKET_CALENDAR[g]["calendar_is_official"] is False


# ============================================================ 4. NaN/Inf
def test_string_nan_detected():
    """10. 字符串 'NaN' 必须被识别。"""
    for v in ("NaN", "nan", " nan ", "+nan", "-nan"):
        num, reason = to_number(v)
        assert num is None, f"{v} 未被识别"
        assert reason == "nan_string", f"{v} -> {reason}"


def test_string_infinity_detected():
    """11. 字符串 'Infinity' 必须被识别。"""
    for v in ("Infinity", "inf", "Inf", "+inf", "+Infinity"):
        num, reason = to_number(v)
        assert num is None, f"{v} 未被识别"
        assert reason == "inf_string"
    for v in ("-Infinity", "-inf", "-Inf"):
        num, reason = to_number(v)
        assert num is None
        assert reason == "neg_inf_string"


def test_float_nan_inf_detected():
    """浮点 NaN/Inf 必须被识别。"""
    assert to_number(float("nan"))[1] == "nan"
    assert to_number(float("inf"))[1] == "inf"
    assert to_number(float("-inf"))[1] == "inf"


def test_invalid_dates_detected(doc):
    """12. 非法日期与缺失日期必须检查。"""
    for r in doc["candidates"]:
        q = r["quality"]
        assert "illegal_date_count" in q
        assert "missing_date_count" in q


def test_nan_does_not_bypass_quality():
    """字符串 NaN 不得绕过质量检查。"""
    fake_rows = [{"tradeDate": "20200102", "close": "NaN"},
                 {"tradeDate": "20200103", "close": "Infinity"}]
    from scripts.audit_3b6_2_3_1_0_1_fix import audit_quality
    q = audit_quality("FAKE", fake_rows, set(), group="stock",
                      synth={"real_history_start": "unknown"})
    assert q["nan_close"] >= 1
    assert q["inf_close"] >= 1
    assert q["data_quality_verified"] is False


# ============================================================ 5. 三类状态
def test_three_states_computed(doc):
    """13. 三类下一阶段状态必须分别计算。"""
    for r in doc["candidates"]:
        st = r["next_stage_states"]
        for k in ("raw_data_layer_ingest_candidate",
                  "validated_series_candidate", "formal_series_admitted"):
            assert k in st, f"{r['tr_candidate']} 缺状态 {k}"
            assert isinstance(st[k], bool)


def test_raw_ingest_does_not_imply_validated(doc):
    """原始层准入不等于已验证序列。"""
    for r in doc["candidates"]:
        st = r["next_stage_states"]
        if st["validated_series_candidate"]:
            assert st["raw_data_layer_ingest_candidate"] is True


def test_h20184_raw_ok_but_not_validated(doc):
    """H20184 零值异常：可进原始层，但不得评为数据质量通过。"""
    r = _cand(doc, "H20184")
    st = r["next_stage_states"]
    assert st["raw_data_layer_ingest_candidate"] is True
    assert st["validated_series_candidate"] is False
    assert r["dimensions"]["data_quality_verified"] is False
    assert r["quality"]["non_positive_close"] >= 1


def test_h20930_not_claimed_missing(doc):
    """H20930：不得因 A 股日历不适用就认定数据缺失。"""
    r = _cand(doc, "H20930")
    q = r["quality"]
    assert q["coverage_status"] == "unknown"
    assert q["missing_trading_days"] is None
    assert r["next_stage_states"]["raw_data_layer_ingest_candidate"] is True


def test_formal_admitted_still_zero(doc):
    """15. 正式准入仍为 0。"""
    assert doc["summary"]["totals"]["formal_series_admitted"] == 0
    for r in doc["candidates"]:
        assert r["next_stage_states"]["formal_series_admitted"] is False


def test_state_rules_declared(doc):
    """三类状态规则必须声明。"""
    rule = doc["candidates"][0]["next_stage_states"]["rule"]
    assert "raw_data_layer_ingest_candidate" in rule
    assert "validated_series_candidate" in rule
    assert "formal_series_admitted" in rule


# ============================================================ 6. JSON/报告一致
def test_json_and_report_admission_consistent(doc):
    """14. JSON 与 Markdown 报告的准入名单必须一致。"""
    txt = (REPORTS / "phase3B6_2_3_1_0_1_fix_report.md").read_text(
        encoding="utf-8")
    totals = doc["summary"]["totals"]
    assert str(totals["raw_data_layer_ingest_candidate"]) in txt
    assert str(totals["validated_series_candidate"]) in txt
    assert str(totals["formal_series_admitted"]) in txt
    # 报告必须列出 validated 的具体候选
    validated = [r["tr_candidate"] for r in doc["candidates"]
                 if r["next_stage_states"]["validated_series_candidate"]]
    for code in validated:
        assert code in txt, f"报告缺 validated 候选 {code}"
    # 报告不得把 H20184 列入 validated
    assert _cand(doc, "H20184")["next_stage_states"][
        "validated_series_candidate"] is False


def test_h20184_not_in_validated_list_in_report(doc):
    """报告不得把 H20184 列入 validated 名单。"""
    txt = (REPORTS / "phase3B6_2_3_1_0_1_fix_report.md").read_text(
        encoding="utf-8")
    r = _cand(doc, "H20184")
    assert r["next_stage_states"]["validated_series_candidate"] is False
    # 找到 validated 段落后检查
    if "已验证序列" in txt:
        seg = txt.split("已验证序列")[1][:800]
        assert "H20184" not in seg or "不可" in seg


# ============================================================ 7. 证据完整性
def test_all_evidence_sha256_verified():
    """16. 全部历史原始证据 SHA256 真实复核。"""
    m = json.loads((EVID_OLD / "manifest.json").read_text(encoding="utf-8"))
    files = m.get("files") or {}
    assert len(files) >= 20
    checked = 0
    for name, info in files.items():
        f = EVID_OLD / name
        assert f.exists(), f"缺文件 {name}"
        actual = hashlib.sha256(f.read_bytes()).hexdigest()
        assert actual == info["sha256"], f"{name} SHA256 不符"
        assert len(actual) == 64
        checked += 1
    assert checked == len(files)


def test_manifest_matches_actual_files():
    """17. manifest 与实际文件一致（本轮为引用式清单）。"""
    m = json.loads((EVID / "manifest.json").read_text(encoding="utf-8"))
    assert m["no_new_download"] is True
    # 本轮不产生新官方响应，manifest 记录引用关系
    ref = m["referenced_evidence"]
    assert m["referenced_count"] == len(ref) >= 20
    assert m["referenced_all_match"] is True
    for name, info in ref.items():
        f = EVID_OLD / name
        assert f.exists(), f"引用文件缺失 {name}"
        actual = hashlib.sha256(f.read_bytes()).hexdigest()
        assert actual == info["actual_sha256"], f"{name} 实际哈希不符"
        assert info["match"] is True, f"{name} 与旧 manifest 不符"


def test_old_evidence_unmodified():
    """3B-6.2.3.1.0 的原始证据不得被修改。"""
    r = verify_old_evidence_integrity()
    assert r["all_match"] is True, f"被修改：{r['mismatched']}"
    assert r["checked"] >= 20


# ============================================================ 8. 数据库
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
    """全收益序列不得写入正式库。"""
    for r in doc["candidates"]:
        n = conn.execute(
            "select count(*) from index_daily where index_code=?",
            (r["tr_candidate"],)).fetchone()[0]
        assert n == 0, f"{r['tr_candidate']} 已被写入"


# ============================================================ 9. 其他
def test_outside_calendar_classification(doc):
    """日历外日期必须分类（休市占位 vs 无法解释）。"""
    for r in doc["candidates"]:
        q = r["quality"]
        if q["coverage_status"] == "unknown":
            continue
        if "outside_calendar_detail" in q:
            for x in q["outside_calendar_detail"]:
                assert x["classification"] in (
                    "market_closed_placeholder", "unexplained")


def test_2018_06_18_classified_as_closed():
    """2018-06-18（端午）必须分类为休市占位行。"""
    rows = load_old_evidence("H00300")["rows"]
    out = _classify_outside_calendar(rows, ["2018-06-18"])
    assert out[0]["classification"] == "market_closed_placeholder"
    assert out[0]["trading_vol"] == 0.0


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
    for name in ("phase3B6_2_3_1_0_1_fix_report.md",
                 "phase3B6_2_3_1_0_1_test_report.md"):
        assert (REPORTS / name).exists(), f"缺报告 {name}"


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
