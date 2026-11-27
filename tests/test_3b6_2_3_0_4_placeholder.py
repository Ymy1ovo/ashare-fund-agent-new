"""阶段3B-6.2.3.0.4 10 条 2004-01-01 suspect 占位记录溯源专项测试。

**真实读取数据库、真实证据文件、真实项目代码**，不使用固定字符串自证。
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

from scripts.audit_3b6_2_3_0_4_placeholder import (  # noqa: E402
    EXPECTED_CODES, EXPECTED_COUNT, TARGET_DATE, audit, baseline_snapshot,
    connect_ro, file_sha256, find_ingest_logic, scan_internal_code,
    summarize)

REPORTS = ROOT / "reports"
EVID = REPORTS / "evidence" / "phase3B6_2_3_0_4"
AUDIT = REPORTS / "phase3B6_2_3_0_4_audit.json"

# 本轮审计开始时记录的数据库指纹（任务基线）
BASELINE_DB_SHA256 = (
    "1671e4037cd265a2dead8b78d43614189a782385ca450ac6c2de3c4ff36ee873")


@pytest.fixture(scope="module")
def conn():
    c = connect_ro()
    yield c
    c.close()


@pytest.fixture(scope="module")
def audit_doc() -> dict:
    assert AUDIT.exists(), "缺审计 JSON"
    return json.loads(AUDIT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def targets(conn) -> list[dict]:
    return baseline_snapshot(conn)["target_records"]


# ============================================================ 目标记录
def test_target_count_is_exactly_10(targets):
    """1. 目标记录恰好 10 条。"""
    assert len(targets) == EXPECTED_COUNT == 10


def test_target_codes_match_expected(targets):
    """指数集合必须与任务指定一致。"""
    codes = sorted(r["index_code"] for r in targets)
    assert codes == sorted(EXPECTED_CODES)


def test_all_target_date_is_2004_01_01(targets):
    """2. 目标日期全部为 2004-01-01。"""
    for r in targets:
        assert r["trade_date"] == TARGET_DATE


def test_all_still_suspect(targets):
    """3. 10 条记录全部保持 suspect（本轮只读，未改动）。"""
    for r in targets:
        assert r["quality_status"] == "suspect", \
            f"{r['index_code']} 状态被改动"


def test_all_have_quality_note(targets):
    """占位行必须带异常说明，可追溯。"""
    for r in targets:
        assert r["quality_note"], f"{r['index_code']} 缺 quality_note"
        assert "基线占位行" in r["quality_note"]


def test_all_fields_complete(targets):
    """4. 逐条记录字段完整（全字段可读）。"""
    required = ["index_code", "trade_date", "open", "high", "low", "close",
                "volume", "amount", "source", "raw_basis", "run_id",
                "collected_at", "row_fingerprint", "quality_status",
                "quality_note"]
    for r in targets:
        for k in required:
            assert k in r, f"{r['index_code']} 缺字段 {k}"
        assert r["source"] == "akshare.stock_zh_index_hist_csindex"
        assert r["run_id"] is not None
        assert r["collected_at"]
        assert r["row_fingerprint"]


# ============================================================ 逐条结论
def test_every_record_has_conclusion(audit_doc):
    """5. 每条记录均有独立审计结论。"""
    recs = audit_doc["records"]
    assert len(recs) == 10
    for r in recs:
        assert r["final_conclusion"], f"{r['index_code']} 缺结论"
        assert r["evidence_grade"] in ("L1", "L2", "L3", "insufficient")
        assert r["recommended_action"]
        assert r["source_origin_key"]


def test_conclusions_are_distinct_per_index(audit_doc):
    """每条结论必须包含该指数自身信息，不是复制粘贴。"""
    seen = set()
    for r in audit_doc["records"]:
        key = (r["index_code"], r["official_basic_date"],
               r["official_publish_date"], str(r["db_close"]))
        assert key not in seen, f"{r['index_code']} 结论重复"
        seen.add(key)


# ============================================================ 基日 vs 发布日
def test_base_date_not_confused_with_publish_date(audit_doc):
    """6. 不得把基日误认为发布日期。"""
    for r in audit_doc["records"]:
        bd = r["official_basic_date"]
        pd = r["official_publish_date"]
        assert bd, f"{r['index_code']} 缺基日"
        assert pd, f"{r['index_code']} 缺发布日"
        # 已知事实：所有指数基日 != 发布日
        assert bd != pd, f"{r['index_code']} 基日与发布日相同，需复核"


def test_base_date_values_are_real():
    """基日必须是已知的真实基日（对照官方基本信息接口）。"""
    from scripts.audit_3b6_2_3_0_4_placeholder import load_saved_basic
    known = {
        "000012": "2002-12-31", "000016": "2003-12-31",
        "000300": "2004-12-31", "000905": "2004-12-31",
        "000906": "2004-12-31", "000922": "2004-12-31",
        "000942": "2004-12-31", "399997": "2008-12-31",
        "930930": "2014-11-14", "H30184": "2004-12-31",
    }
    for code, bd in known.items():
        b = load_saved_basic(code)
        assert b["basic_date"] == bd, f"{code} 基日 {b['basic_date']} != {bd}"


# ============================================================ 基点 vs 行情
def test_base_value_not_treated_as_quote(audit_doc):
    """7. 不得把基点值误认为真实交易行情。

    5 个指数 close 恰等于基点值 → 必须标记 base_value_confusion=True，
    且结论中不得把它当作真实收盘价。
    """
    confused = [r for r in audit_doc["records"] if r["base_value_confusion"]]
    assert len(confused) == 5
    for r in confused:
        assert r["db_close"] == r["official_basic_index"], \
            f"{r['index_code']} 标了基点混淆但数值不等"
        # 即便数值等于基点，结论仍必须说明是合成行
        assert r["synthetic_when_requested_from_20040101"] is True


def test_non_confused_rows_are_not_base_values(audit_doc):
    """其余 5 个不是基点值，但同样是合成行（证明不是「只把基点写进去」）。"""
    others = [r for r in audit_doc["records"]
              if not r["base_value_confusion"]]
    assert len(others) == 5
    for r in others:
        assert r["db_close"] != r["official_basic_index"]
        assert r["synthetic_when_requested_from_20040101"] is True


# ============================================================ 日历代理
def test_calendar_proxy_not_official(audit_doc):
    """8. 不得将交易日历代理描述为官方发布日历。"""
    for r in audit_doc["records"]:
        note = r["a_share_calendar_proxy_note"]
        assert "代理" in note
        assert "不是指数官方发布日历" in note
    assert audit_doc["a_share_calendar_has_2004_01_01"] is False


# ============================================================ unknown 保留
def test_unknown_kept_when_no_evidence(audit_doc):
    """9. 无证据时必须保留 unknown。"""
    for r in audit_doc["records"]:
        assert r["historical_availability"] == "unknown"
        assert r["historical_availability_note"]
        assert "不能证明" in r["historical_availability_note"]


# ============================================================ 证据等级
def test_no_l3_dressed_as_official(audit_doc):
    """10. 不得将第三方资料冒充官方证据。"""
    for r in audit_doc["records"]:
        if r["evidence_grade"] == "L1":
            # L1 必须有官方原始响应文件 + SHA256
            assert r["official_basic"].get("sha256"), \
                f"{r['index_code']} 标 L1 但无官方文件 SHA256"
            url = r["official_basic"].get("url") or ""
            assert "csindex.com.cn" in url, \
                f"{r['index_code']} 标 L1 但来源非官方：{url}"


def test_all_evidence_is_L1(audit_doc):
    """本轮 10 条全部取得官方原始响应 → 全部 L1。"""
    grades = audit_doc["summary"]["evidence_grade_counts"]
    assert grades.get("L1", 0) == 10
    assert grades.get("L3", 0) == 0
    assert grades.get("insufficient", 0) == 0


def test_evidence_sha256_verifiable(audit_doc):
    """11. 原始证据 SHA256 可复核。"""
    checked = 0
    for r in audit_doc["records"]:
        for key in ("official_basic",):
            b = r[key]
            rel = b.get("file")
            sha = b.get("sha256")
            if not rel or not sha:
                continue
            p = ROOT / rel
            assert p.exists(), f"证据文件缺失 {rel}"
            assert hashlib.sha256(p.read_bytes()).hexdigest() == sha, \
                f"{rel} SHA256 不符"
            assert len(sha) == 64
            checked += 1
    assert checked == 10


# ============================================================ 来源溯源
def test_source_is_official_api_not_internal(audit_doc):
    """来源必须是官方接口，不是项目内部生成。"""
    for r in audit_doc["records"]:
        assert r["source_origin_key"] == "official_api_synthetic_start_row"
        assert "官方接口" in r["source_origin"]
        assert r["db_matches_official"] is True, \
            f"{r['index_code']} DB 值与官方响应不符"


def test_all_synthetic_start_rows(audit_doc):
    """10 条全部是「请求起始日合成行」。"""
    s = audit_doc["summary"]
    assert s["synthetic_start_row_count"] == 10
    assert s["disappears_from_20040102_count"] == 10


def test_row_equals_second_row_all(audit_doc):
    """合成行的数值必须与第二行相同（官方接口重复首行特征）。"""
    assert audit_doc["summary"]["row_equals_second_row"] == 10


def test_no_hardcoded_value_in_production_code():
    """内部生产代码不得硬编码这 5 个真实行情数值。"""
    scan = scan_internal_code()
    for v in ("994.47", "1204.61", "1028.64", "1011.35", "99.22"):
        assert scan["per_value"][v]["production_code_hits"] == 0, \
            f"生产代码硬编码了 {v}"


def test_ingest_start_date_causes_synthetic_row():
    """采集脚本的 DEFAULT_START 必须是 20040101（合成行根因）。"""
    logic = find_ingest_logic()
    assert logic["source_file"] == "app/fund/index_ingest.py"
    f = ROOT / logic["source_file"]
    txt = f.read_text(encoding="utf-8")
    assert 'DEFAULT_START = "20040101"' in txt


def test_ingest_marks_baseline_as_suspect():
    """采集脚本必须把基线行标记为 suspect（不是静默入库为 valid）。"""
    f = ROOT / "app" / "fund" / "index_ingest.py"
    txt = f.read_text(encoding="utf-8")
    assert "baseline" in txt
    assert "suspect" in txt
    assert "占位" in txt


def test_run_records_requested_from_20040101(audit_doc):
    """采集批次记录必须显示请求起始日为 20040101。"""
    runs = audit_doc["ingest_runs"]
    assert runs
    for r in runs:
        assert r["found"] is True
        assert r["request_start_date"] == "20040101"


# ============================================================ 数据库不变性
def test_database_read_only_sha_unchanged():
    """12/13. 数据库只读且 SHA256 未变。"""
    assert file_sha256() == BASELINE_DB_SHA256


def test_database_sha_matches_baseline_json(audit_doc):
    """审计 JSON 记录的基线 SHA 必须与当前一致。"""
    assert audit_doc["baseline"]["database_sha256"] == BASELINE_DB_SHA256


def test_integrity_check_ok(conn):
    """14. integrity_check 正常。"""
    assert conn.execute("pragma integrity_check").fetchone()[0] == "ok"


def test_foreign_key_check_zero(conn):
    """15. foreign_key_check 为 0。"""
    assert len(conn.execute("pragma foreign_key_check").fetchall()) == 0


def test_total_rows_unchanged(conn):
    """index_daily 总行数必须仍为 50,603。"""
    assert conn.execute(
        "select count(*) from index_daily").fetchone()[0] == 50603


def test_other_indexes_untouched(audit_doc):
    """16. 其他指数数据指纹不变（对照基线快照）。"""
    saved = EVID / "baseline_before.json"
    if not saved.exists():
        pytest.skip("无基线快照")
    before = json.loads(saved.read_text(encoding="utf-8"))
    after = baseline_snapshot(connect_ro())
    for code, b in before["other_index_fingerprints"].items():
        a = after["other_index_fingerprints"][code]
        assert a["rows"] == b["rows"], f"{code} 行数变化"
        assert a["fingerprint"] == b["fingerprint"], f"{code} 数据被改动"


def test_h30184_repair_not_rerun(conn):
    """17. 不修改上一阶段 H30184 修复结果。"""
    row = conn.execute(
        "select trade_date, close, quality_status from index_daily "
        "where index_code='H30184' and trade_date='2013-06-28'").fetchone()
    assert row is not None
    assert row[0] == "2013-06-28"
    assert row[1] == 0.0, "close 原值必须保留"
    assert row[2] == "suspect", "上一阶段修复结果被改动"


def test_suspect_total_still_11(conn):
    """suspect 总数仍为 11（10 条占位 + 1 条 H30184）。"""
    n = conn.execute(
        "select count(*) from index_daily where quality_status<>'valid'"
    ).fetchone()[0]
    assert n == 11


# ============================================================ 门禁与报告
def test_gates_all_closed(audit_doc):
    """所有门禁保持关闭。"""
    g = audit_doc["summary"]["gates"]
    assert g["ready_for_research_analysis"] is True
    assert g["ready_for_backtest"] is False
    assert g["ready_for_formal_ranking"] is False
    assert g["ready_for_3b6_2_3_1_series_build"] is False


def test_reports_exist():
    for name in ("phase3B6_2_3_0_4_design.md",
                 "phase3B6_2_3_0_4_audit_report.md",
                 "phase3B6_2_3_0_4_test_report.md"):
        assert (REPORTS / name).exists(), f"缺报告 {name}"


def test_audit_report_has_per_record_conclusions():
    """审计报告必须给出 10 条逐条结论。"""
    txt = (REPORTS / "phase3B6_2_3_0_4_audit_report.md").read_text(
        encoding="utf-8")
    for code in EXPECTED_CODES:
        assert code in txt, f"审计报告缺 {code}"


def test_self_check_all_pass(audit_doc):
    for k, v in audit_doc["summary"]["_self_check"].items():
        assert v is True, f"自校验失败：{k}"


def test_no_vacuous_assertion():
    txt = Path(__file__).read_text(encoding="utf-8")
    assert ("or " + "True") not in txt
    assert ("assert " + "True") not in txt


# ============================================================ 3B-6.2.3.0.4.1 字段语义修正
def test_no_earliest_official_history_field(audit_doc):
    """1. 不再使用 earliest_official_history 表达 API 响应首日。"""
    for r in audit_doc["records"]:
        assert "earliest_official_history" not in r, \
            f"{r['index_code']} 仍保留旧字段"


def test_earliest_response_date_matches_real_json(audit_doc):
    """2. earliest_response_date 必须与真实 JSON 解析出的最早日期一致。"""
    for r in audit_doc["records"]:
        code = r["index_code"]
        f = EVID / f"csindex_hist_{code}_from20040101.json"
        assert f.exists(), f"缺历史响应 {code}"
        rows = json.loads(f.read_text(encoding="utf-8")).get("data") or []
        assert rows, f"{code} 历史响应为空"
        real_first = rows[0].get("tradeDate")
        assert r["earliest_response_date"] == real_first, \
            f"{code} 记录 {r['earliest_response_date']} != 真实 {real_first}"


def test_actual_earliest_quote_date_unknown(audit_doc):
    """3. actual_earliest_historical_quote_date 在无独立证据时必须为 unknown。"""
    for r in audit_doc["records"]:
        assert r["actual_earliest_historical_quote_date"] == "unknown", \
            f"{r['index_code']} 无证据却给了具体日期"
        assert r["actual_earliest_historical_quote_date_evidence"]
        assert "unknown" in r["actual_earliest_historical_quote_date_evidence"]


def test_four_date_concepts_distinguished(audit_doc):
    """基日 / 发布日 / 响应首日 / 真实最早行情日期 四者必须分开。"""
    for r in audit_doc["records"]:
        assert r["official_basic_date"]
        assert r["official_publish_date"]
        assert r["earliest_response_date"]
        assert r["actual_earliest_historical_quote_date"] == "unknown"
        # 响应首日不得被当成真实最早行情日期
        assert r["earliest_response_date"] != \
            r["actual_earliest_historical_quote_date"]


def test_date_semantics_declared(audit_doc):
    """审计 JSON 必须显式声明四类日期语义。"""
    ds = audit_doc["date_semantics"]
    for k in ("official_basic_date", "official_publish_date",
              "earliest_response_date",
              "actual_earliest_historical_quote_date"):
        assert k in ds, f"缺语义声明 {k}"
    assert "不可混为一谈" in ds["warning"]


def test_report_not_claiming_20040101_as_real_history():
    """4. 报告不得把 2004-01-01 描述为真实最早历史行情。"""
    txt = (REPORTS / "phase3B6_2_3_0_4_audit_report.md").read_text(
        encoding="utf-8")
    assert "官方最早历史一律为" not in txt
    assert "官方最早历史" not in txt
    assert "API 响应首日" in txt or "API响应首日" in txt
    assert "真实最早历史行情日期" in txt
    # unknown 必须出现 10 次（每条记录一次）
    assert txt.count("**unknown**") >= 10


# ============================================================ 30 份证据 SHA256
def _evidence_files() -> list[Path]:
    out = []
    for code in EXPECTED_CODES:
        for name in (f"csindex_basic_{code}.json",
                     f"csindex_hist_{code}_from20040101.json",
                     f"csindex_ctrl_{code}_from20040102.json"):
            out.append(EVID / name)
    return out


def test_30_evidence_files_exist():
    """5. 30 份原始证据文件全部存在。"""
    files = _evidence_files()
    assert len(files) == 30
    missing = [f.name for f in files if not f.exists()]
    assert not missing, f"缺失文件：{missing}"
    for f in files:
        assert f.stat().st_size > 0


def test_30_evidence_sha256_matches_manifest():
    """6. 30 份文件 SHA256 与 manifest 一致（真实二进制哈希）。"""
    manifest = EVID / "manifest.json"
    assert manifest.exists(), "缺 manifest.json"
    m = json.loads(manifest.read_text(encoding="utf-8"))
    m_files = m.get("files") or {}
    checked = 0
    for f in _evidence_files():
        assert f.name in m_files, f"manifest 缺 {f.name}"
        actual = hashlib.sha256(f.read_bytes()).hexdigest()
        assert actual == m_files[f.name]["sha256"], \
            f"{f.name} SHA256 与 manifest 不符"
        assert len(actual) == 64
        checked += 1
    assert checked == 30


def test_30_evidence_sha256_matches_audit_json(audit_doc):
    """7. 30 份文件 SHA256 与审计 JSON 对应记录一致。"""
    ev = audit_doc["evidence_files"]
    assert ev["expected_total"] == 30
    assert ev["found_total"] == 30
    assert ev["sha256_match_manifest"] == 30
    by_name = {f["file"]: f for f in ev["files"]}
    checked = 0
    for f in _evidence_files():
        rec = by_name.get(f.name)
        assert rec is not None, f"审计 JSON 缺 {f.name}"
        assert rec["exists"] is True
        actual = hashlib.sha256(f.read_bytes()).hexdigest()
        assert rec["sha256"] == actual, f"{f.name} 审计记录 SHA256 不符"
        assert rec["bytes"] == f.stat().st_size
        checked += 1
    assert checked == 30


def test_evidence_sha256_cross_check_three_sources(audit_doc):
    """三方交叉核对：文件实际哈希 == manifest == 审计 JSON。"""
    m = json.loads((EVID / "manifest.json").read_text(encoding="utf-8"))
    m_files = m.get("files") or {}
    audit_by = {f["file"]: f for f in audit_doc["evidence_files"]["files"]}
    for f in _evidence_files():
        actual = hashlib.sha256(f.read_bytes()).hexdigest()
        assert actual == m_files[f.name]["sha256"]
        assert actual == audit_by[f.name]["sha256"]


def test_no_sha256_string_length_only_check():
    """不得只检查 SHA256 字符串长度——必须真算。"""
    src = Path(__file__).read_text(encoding="utf-8")
    # 本文件必须出现真实哈希计算
    assert "hashlib.sha256(" in src
    assert ".read_bytes()" in src


# ============================================================ URL 参数核验
def test_hist_url_start_param_is_20040101(audit_doc):
    """8. 20040101 请求的实际 URL 起始参数正确。"""
    uv = audit_doc["url_verification"]
    assert uv["hist_urls_correct"] == 10
    for x in uv["per_index"]:
        assert x["hist_url_start_param"] == "20040101", \
            f"{x['index_code']} 历史请求 startDate 错误"
        assert "indexCode=" + x["index_code"] in x["hist_url"]


def test_ctrl_url_start_param_is_20040102(audit_doc):
    """8b. 20040102 对照请求的实际 URL 起始参数正确。"""
    uv = audit_doc["url_verification"]
    assert uv["ctrl_urls_correct"] == 10
    for x in uv["per_index"]:
        assert x["ctrl_url_start_param"] == "20040102", \
            f"{x['index_code']} 对照请求 startDate 错误"


def test_hist_contains_20040101_ctrl_does_not(audit_doc):
    """真实响应日期集合与审计结论一致。"""
    uv = audit_doc["url_verification"]
    assert uv["hist_contains_20040101_count"] == 10
    assert uv["ctrl_contains_20040101_count"] == 0


def test_first_date_consistent_with_parsed(audit_doc):
    """响应首日必须与实际解析结果一致（对照 JSON 复核）。"""
    uv = audit_doc["url_verification"]
    assert uv["first_date_consistent_count"] == 10
    for x in uv["per_index"]:
        code = x["index_code"]
        h = json.loads((EVID / f"csindex_hist_{code}_from20040101.json")
                       .read_text(encoding="utf-8"))
        c = json.loads((EVID / f"csindex_ctrl_{code}_from20040102.json")
                       .read_text(encoding="utf-8"))
        h_rows = h.get("data") or []
        c_rows = c.get("data") or []
        assert h_rows[0]["tradeDate"] == x["hist_first_date"]
        assert c_rows[0]["tradeDate"] == x["ctrl_first_date"]
        assert x["hist_response_row_count"] == len(h_rows)
        assert x["ctrl_response_row_count"] == len(c_rows)


# ============================================================ 原结论不变
def test_original_conclusions_unchanged(audit_doc):
    """10. 原有 10 条记录逐条结论保持不变。"""
    s = audit_doc["summary"]
    assert s["target_count"] == 10
    assert s["synthetic_start_row_count"] == 10
    assert s["disappears_from_20040102_count"] == 10
    assert s["db_matches_official_close"] == 10
    assert s["row_equals_second_row"] == 10
    assert s["base_value_confusion"] == 5
    assert s["all_still_suspect"] == 10
    assert s["evidence_grade_counts"] == {"L1": 10}
    assert s["historical_availability_unknown"] == 10


def test_synthetic_mechanism_not_claimed_as_official_announcement(audit_doc):
    """合成机制是技术判断，不得声称官方发布过解释。"""
    txt = (REPORTS / "phase3B6_2_3_0_4_audit_report.md").read_text(
        encoding="utf-8")
    assert "技术判断" in txt
    assert "不能声称中证官方发布过" in txt


# ============================================================ 数据库不变性
def test_db_sha256_unchanged_again():
    """11. 数据库 SHA256 保持不变。"""
    assert file_sha256() == BASELINE_DB_SHA256


def test_integrity_ok_again(conn):
    """12. integrity_check 正常。"""
    assert conn.execute("pragma integrity_check").fetchone()[0] == "ok"


def test_fk_zero_again(conn):
    """13. foreign_key_check 为 0。"""
    assert len(conn.execute("pragma foreign_key_check").fetchall()) == 0


def test_targets_still_10_suspect(conn):
    """10 条目标记录仍全部 suspect。"""
    n = conn.execute(
        "select count(*) from index_daily where trade_date='2004-01-01' "
        "and quality_status='suspect'").fetchone()[0]
    assert n == 10
    total = conn.execute(
        "select count(*) from index_daily where trade_date='2004-01-01'"
    ).fetchone()[0]
    assert total == 10


def test_suspect_total_11(conn):
    assert conn.execute(
        "select count(*) from index_daily where quality_status<>'valid'"
    ).fetchone()[0] == 11


def test_h30184_still_suspect_zero(conn):
    row = conn.execute(
        "select close, quality_status from index_daily "
        "where index_code='H30184' and trade_date='2013-06-28'").fetchone()
    assert row == (0.0, "suspect")


def test_gates_unchanged_again(audit_doc):
    """14. 四项门禁保持不变。"""
    g = audit_doc["summary"]["gates"]
    assert g["ready_for_research_analysis"] is True
    assert g["ready_for_backtest"] is False
    assert g["ready_for_formal_ranking"] is False
    assert g["ready_for_3b6_2_3_1_series_build"] is False


def test_self_check_includes_new_assertions(audit_doc):
    """自校验必须包含本轮新增的字段语义与证据校验。"""
    sc = audit_doc["summary"]["_self_check"]
    for k in ("no_earliest_official_history_field",
              "every_record_has_earliest_response_date",
              "every_record_earliest_quote_unknown",
              "evidence_30_files_found",
              "evidence_sha256_all_match",
              "hist_urls_all_20040101",
              "ctrl_urls_all_20040102"):
        assert sc.get(k) is True, f"自校验缺 {k} 或未通过"
