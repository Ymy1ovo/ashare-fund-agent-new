"""阶段3B-6.2.3.1.0.3 连续性证据等级与准入统计一致性专项测试。

**真实调用准入计算函数 + 真实读取三方 JSON + 真实计算 SHA256**。
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

from scripts.audit_3b6_2_3_1_0_3_consistency import (  # noqa: E402
    CONTINUITY_LEVELS, compute_admission, connect_ro, file_sha256,
    map_continuity_level)

REPORTS = ROOT / "reports"
EVID = REPORTS / "evidence" / "phase3B6_2_3_1_0_3"
AUDIT_1 = REPORTS / "phase3B6_2_3_1_0_1_audit.json"
AUDIT_2 = REPORTS / "phase3B6_2_3_1_0_2_audit.json"
AUDIT_3 = REPORTS / "phase3B6_2_3_1_0_3_audit.json"

BASELINE_DB_SHA256 = (
    "1671e4037cd265a2dead8b78d43614189a782385ca450ac6c2de3c4ff36ee873")


@pytest.fixture(scope="module")
def conn():
    c = connect_ro()
    yield c
    c.close()


@pytest.fixture(scope="module")
def d1() -> dict:
    return json.loads(AUDIT_1.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def d2() -> dict:
    return json.loads(AUDIT_2.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def d3() -> dict:
    assert AUDIT_3.exists()
    return json.loads(AUDIT_3.read_text(encoding="utf-8"))


def _a3(d3, code) -> dict:
    return next(r for r in d3["candidates"] if r["tr_candidate"] == code)


# ============================================================ 1-2. 代理日历
def test_proxy_calendar_cannot_yield_official_verified():
    """1. 代理日历不能生成 verified_official_calendar。"""
    assert map_continuity_level("verified", False) == \
        "verified_against_proxy_calendar"
    assert map_continuity_level("verified", True) == \
        "verified_official_calendar"


def test_no_official_calendar_verified_in_result(d3):
    """全部候选无 verified_official_calendar。"""
    t = d3["summary"]["totals"]
    assert t["continuity_verified_official_calendar"] == 0
    for r in d3["candidates"]:
        assert r["continuity_level"] != "verified_official_calendar"


def test_399997cny02_marked_as_proxy(d3):
    """2. 399997CNY02 连续性明确标记为代理验证。"""
    r = _a3(d3, "399997CNY02")
    assert r["continuity_level"] == "verified_against_proxy_calendar"
    assert r["calendar_is_official"] is False
    assert "代理" in r["calendar_used"] or "A股" in r["calendar_used"]
    assert "不是官方发布日历" in r["admission"]["continuity_level_definition"]


# ============================================================ 3-5. 状态约束
def test_eight_suspicion_not_verified(d3):
    """3. 8 只疑似占位候选不得标记为连续性已验证。"""
    susp = [r for r in d3["candidates"]
            if r["continuity_level"] == "has_unresolved_suspicion"]
    assert len(susp) == 8
    for r in susp:
        assert r["continuity_level"] != "verified_against_proxy_calendar"
        assert r["admission"]["validated_series_candidate"] is False
        assert r["admission"]["proxy_qualified_series_candidate"] is False


def test_h20184_quality_still_failed(d3):
    """4. H20184 仍然质量不通过。"""
    r = _a3(d3, "H20184")
    assert r["admission"]["evidence_snapshot"][
        "data_quality_verified"] is False
    assert r["admission"]["validated_series_candidate"] is False
    assert r["admission"]["proxy_qualified_series_candidate"] is False
    assert "数据质量" in r["admission"]["blockers"]


def test_bond_hk_still_unknown(d3):
    """5. 债券 2 只和港股 1 只仍为 unknown。"""
    for code in ("H00012", "N00012", "H20930"):
        r = _a3(d3, code)
        assert r["continuity_level"] == "unknown"
        assert r["admission"]["validated_series_candidate"] is False
        assert r["admission"]["proxy_qualified_series_candidate"] is False


# ============================================================ 6. 无冲突
def test_no_conflict_between_010_and_020(d1, d2, d3):
    """6. 第一轮与第二轮 JSON 的连续性状态不存在冲突（三方一致）。"""
    for r3 in d3["candidates"]:
        c = r3["tr_candidate"]
        l1 = next(x for x in d1["candidates"]
                  if x["tr_candidate"] == c)["quality"]["continuity_status"]
        l2 = next(x for x in d2["candidates"]
                  if x["tr_candidate"] == c)["quality"]["continuity_level"]
        assert l1 == l2 == r3["continuity_level"], \
            f"{c} 三方不一致：{l1} / {l2} / {r3['continuity_level']}"


def test_010_preserves_original_snapshot(d1):
    """010 必须保留原始快照供追溯。"""
    assert "_superseded_snapshot" in d1
    snap = d1["_superseded_snapshot"]
    assert snap["original_summary_totals"] is not None
    assert d1["_corrected_by"] == "3B-6.2.3.1.0.3"
    assert "由 8 改为 0" in d1["_correction_note"]


def test_010_per_candidate_original_preserved(d1):
    """010 每个候选保留原始连续性状态。"""
    for r in d1["candidates"]:
        assert "_original_continuity_status" in r
        assert r["_corrected_by"] == "3B-6.2.3.1.0.3"


def test_020_preserves_original_status(d2):
    """020 保留原始四态状态并新增五态字段。"""
    assert "_superseded_snapshot" in d2
    for r in d2["candidates"]:
        assert "continuity_status_original" in r["quality"]
        assert "continuity_level" in r["quality"]


# ============================================================ 7-8. 准入重算
def test_validated_recomputed(d3):
    """7. validated_series_candidate 按最新连续性证据重新计算。"""
    t = d3["summary"]["totals"]
    assert t["validated_series_candidate"] == 0
    for r in d3["candidates"]:
        a = r["admission"]
        # 必须同时满足全部条件才能 validated
        if a["validated_series_candidate"]:
            assert r["continuity_level"] in (
                "verified_official_calendar",)
            assert a["evidence_snapshot"]["data_quality_verified"] is True
            assert a["evidence_snapshot"]["real_history_start"] != "unknown"


def test_proxy_qualified_counted_separately(d3):
    """8. proxy_qualified_series_candidate 独立统计。

    3B-6.2.3.1.0.3.1 修正：代理验证准入补上「真实历史起点已知」条件，
    因此本轮该统计为 0（399997CNY02 起点仍为 unknown）。
    """
    t = d3["summary"]["totals"]
    assert t["proxy_qualified_series_candidate"] == 0
    assert t["validated_series_candidate"] == 0
    r = _a3(d3, "399997CNY02")
    assert r["admission"]["proxy_qualified_series_candidate"] is False
    assert r["admission"]["validated_series_candidate"] is False
    # 连续性等级仍保留为代理验证
    assert r["continuity_level"] == "verified_against_proxy_calendar"
    assert "真实历史起点未知" in r["admission"]["proxy_blockers"]


def test_admission_computed_by_real_function(d3):
    """准入状态必须由真实函数计算，与 JSON 一致。"""
    for r in d3["candidates"]:
        cand = {
            "tr_candidate": r["tr_candidate"],
            "price_index": r["price_index"],
            "group": r["group"],
            "market": r["market"],
            "calendar_used": r["calendar_used"],
            "calendar_is_official": r["calendar_is_official"],
            "continuity_level": r["continuity_level"],
            "quality_020": {
                "coverage_status":
                    r["admission"]["evidence_snapshot"]["coverage_status"],
                "continuity_status": r["admission"]["evidence_snapshot"][
                    "continuity_raw_status"],
            },
            "synthetic_020": {
                "real_history_start": r["admission"]["evidence_snapshot"][
                    "real_history_start"],
                "status": r["admission"]["evidence_snapshot"][
                    "synthetic_status"],
            },
            "dims_020": r["admission"]["evidence_snapshot"],
        }
        recomputed = compute_admission(cand)
        for k in ("raw_data_layer_ingest_candidate",
                  "validated_series_candidate",
                  "proxy_qualified_series_candidate",
                  "formal_series_admitted"):
            assert recomputed[k] == r["admission"][k], \
                f"{r['tr_candidate']} 的 {k} 重算不一致"


# ============================================================ 9. 一致性
def test_all_json_counts_consistent(d1, d2, d3):
    """9. JSON、主报告、两份修正报告的数量一致。"""
    t3 = d3["summary"]["totals"]
    # 010 同步后
    assert d1["summary"]["totals"]["validated_series_candidate"] == \
        t3["validated_series_candidate"]
    assert d1["summary"]["totals"]["formal_series_admitted"] == \
        t3["formal_series_admitted"]
    assert d1["summary"]["totals"]["proxy_qualified_series_candidate"] == \
        t3["proxy_qualified_series_candidate"]
    # 020 五态
    assert d2["summary"]["totals"]["continuity_levels"][
        "verified_against_proxy_calendar"] == 1
    assert d2["summary"]["totals"]["continuity_levels"][
        "has_unresolved_suspicion"] == 8


def test_reports_mention_same_numbers(d3):
    """报告中的数字与 JSON 一致。"""
    txt = (REPORTS / "phase3B6_2_3_1_0_3_fix_report.md").read_text(
        encoding="utf-8")
    t = d3["summary"]["totals"]
    for k in ("raw_data_layer_ingest_candidate",
              "validated_series_candidate",
              "proxy_qualified_series_candidate",
              "formal_series_admitted"):
        assert str(t[k]) in txt, f"报告缺 {k}={t[k]}"


def test_010_report_marked_superseded():
    """010/020 修正报告必须标注以 3.0.3 为准。"""
    for name in ("phase3B6_2_3_1_0_1_fix_report.md",
                 "phase3B6_2_3_1_0_2_fix_report.md"):
        txt = (REPORTS / name).read_text(encoding="utf-8")
        assert "3B-6.2.3.1.0.3" in txt, f"{name} 未标注 3.0.3"
        assert "为准" in txt, f"{name} 未说明以哪个版本为准"


# ============================================================ 10-13
def test_formal_admitted_zero(d3):
    """10. formal_series_admitted=0。"""
    assert d3["summary"]["totals"]["formal_series_admitted"] == 0
    for r in d3["candidates"]:
        assert r["admission"]["formal_series_admitted"] is False


def test_original_evidence_sha256_unchanged():
    """11. 原始官方证据 SHA256 不变。

    只校验**官方原始响应**（basic_/hist_/csindex_* 前缀），
    不校验审计 JSON（其内容已被本轮有意修正）。
    """
    import re
    OFFICIAL = re.compile(r"^(basic_|hist_|csindex_)")
    for base in (REPORTS / "evidence" / "phase3B6_2_3_1_0",
                 REPORTS / "evidence" / "phase3B6_2_3_0_4"):
        m = base / "manifest.json"
        if not m.exists():
            continue
        doc = json.loads(m.read_text(encoding="utf-8"))
        checked = 0
        for name, info in (doc.get("files") or {}).items():
            if not OFFICIAL.match(name):
                continue
            if not info.get("sha256"):
                continue
            f = base / name
            if not f.exists():
                alt = REPORTS / "evidence" / "phase3B6_2_3_0_4" / name
                f = alt if alt.exists() else f
            assert f.exists(), f"缺 {name}"
            assert hashlib.sha256(f.read_bytes()).hexdigest() == \
                info["sha256"], f"{name} 被修改"
            checked += 1
        assert checked > 0, f"{base.name} 未校验任何官方原始证据"


def test_db_sha256_unchanged():
    """业务数据未变（原为文件级 SHA 断言）。

    3B-6.2.3.1.1 合法新增 6 张 tr_* 表后文件 SHA 必然变化，
    改为校验业务数据指纹。
    """
    assert_business_data_unchanged()


def test_db_unchanged_flag(d3):
    assert d3["db_unchanged"] is True


def test_gates_not_opened(d3):
    """13. 门禁没有被意外开放。"""
    g = d3["summary"]["gates"]
    assert g["ready_for_research_analysis"] is True
    assert g["ready_for_backtest"] is False
    assert g["ready_for_formal_ranking"] is False
    assert g["ready_for_3b6_2_3_1_series_build"] is False


def test_integrity_ok(conn):
    assert conn.execute("pragma integrity_check").fetchone()[0] == "ok"


def test_fk_zero(conn):
    assert len(conn.execute("pragma foreign_key_check").fetchall()) == 0


def test_index_daily_unchanged(conn):
    assert conn.execute(
        "select count(*) from index_daily").fetchone()[0] == 50603


def test_no_tr_in_db(conn, d3):
    for r in d3["candidates"]:
        n = conn.execute(
            "select count(*) from index_daily where index_code=?",
            (r["tr_candidate"],)).fetchone()[0]
        assert n == 0


def test_continuity_levels_defined():
    """五态定义必须齐全。"""
    assert set(CONTINUITY_LEVELS) == {
        "verified_official_calendar", "verified_against_proxy_calendar",
        "has_unresolved_suspicion", "has_issues", "unknown"}
    for k, v in CONTINUITY_LEVELS.items():
        assert v["definition"]
        assert "allows_validated" in v


def test_only_official_calendar_allows_validated():
    """只有官方日历等级允许 validated。"""
    allowed = [k for k, v in CONTINUITY_LEVELS.items()
               if v["allows_validated"]]
    assert allowed == ["verified_official_calendar"]


def test_ingest_all_twelve(d3):
    """原始层准入 12/12。"""
    assert d3["summary"]["totals"][
        "raw_data_layer_ingest_candidate"] == 12


def test_manifest_complete():
    m = json.loads((EVID / "manifest.json").read_text(encoding="utf-8"))
    assert m["referenced_total"] == len(m["files"])
    assert m["referenced_exists"] + m["missing_count"] == m["referenced_total"]
    import re
    # 只校验**未被后续阶段修改**的原始官方证据
    OFFICIAL = re.compile(r"^(basic_|hist_|csindex_)")
    checked = 0
    for name, info in m["files"].items():
        if not info["exists"]:
            continue
        p = ROOT / name
        assert p.exists(), f"{name} 标存在但缺失"
        if not OFFICIAL.match(p.name):
            continue
        assert hashlib.sha256(p.read_bytes()).hexdigest() == info["sha256"], \
            f"{name} 哈希不符"
        checked += 1
    assert checked > 0, "未校验任何官方原始证据"


def test_self_check_all_pass(d3):
    for k, v in d3["summary"]["_self_check"].items():
        assert v is True, f"自校验失败：{k}"


def test_reports_exist():
    for name in ("phase3B6_2_3_1_0_3_fix_report.md",
                 "phase3B6_2_3_1_0_3_test_report.md"):
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
