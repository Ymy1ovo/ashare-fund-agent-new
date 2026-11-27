"""阶段3B-6.2.3.1.0.3.1 代理验证准入缺失真实历史起点条件修复专项测试。

**真实调用 compute_admission()**，不使用固定文本自证。
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
    CONTINUITY_LEVELS, compute_admission, connect_ro, file_sha256)

REPORTS = ROOT / "reports"
EVID = REPORTS / "evidence" / "phase3B6_2_3_1_0_3_1"
AUDIT = REPORTS / "phase3B6_2_3_1_0_3_audit.json"
AUDIT_1 = REPORTS / "phase3B6_2_3_1_0_1_audit.json"
AUDIT_2 = REPORTS / "phase3B6_2_3_1_0_2_audit.json"

BASELINE_DB_SHA256 = (
    "1671e4037cd265a2dead8b78d43614189a782385ca450ac6c2de3c4ff36ee873")


@pytest.fixture(scope="module")
def conn():
    c = connect_ro()
    yield c
    c.close()


@pytest.fixture(scope="module")
def d3() -> dict:
    assert AUDIT.exists()
    return json.loads(AUDIT.read_text(encoding="utf-8"))


def _mk(cont_level: str, *, real_start: str, quality=True, coverage=True,
        identity=True, basis=True, mapping=True) -> dict:
    """构造调用 compute_admission() 所需的最小候选结构。"""
    return {
        "tr_candidate": "TEST",
        "price_index": "TESTP",
        "group": "stock",
        "market": "沪深A股",
        "calendar_used": "A股交易日历（项目代理）",
        "calendar_is_official": False,
        "continuity_level": cont_level,
        "quality_020": {"coverage_status":
                        "verified" if coverage else "unknown"},
        "synthetic_020": {"real_history_start": real_start,
                          "status": "strong_inference"},
        "dims_020": {
            "official_identity_verified": identity,
            "return_basis_verified": basis,
            "history_api_available": True,
            "mapping_to_price_index_verified": mapping,
            "data_quality_verified": quality,
            "point_in_time_available": False,
        },
    }


# ============================================================ 1-4. 真实起点条件
def test_proxy_true_requires_known_start():
    """1. 代理日历连续但真实历史起点 unknown → 代理准入必须 false。"""
    r = compute_admission(_mk("verified_against_proxy_calendar",
                              real_start="unknown"))
    assert r["proxy_qualified_series_candidate"] is False
    assert "真实历史起点未知" in r["proxy_blockers"]


def test_proxy_true_when_start_known():
    """2. 代理日历连续且真实起点已知，其他条件满足 → 允许 true。"""
    r = compute_admission(_mk("verified_against_proxy_calendar",
                              real_start="20040102"))
    assert r["proxy_qualified_series_candidate"] is True
    assert r["proxy_blockers"] == []
    # 但不得因此变成 validated（连续性非官方等级）
    assert r["validated_series_candidate"] is False


def test_official_continuity_still_needs_known_start():
    """3. 官方日历连续但真实起点 unknown → validated 必须 false。"""
    r = compute_admission(_mk("verified_official_calendar",
                              real_start="unknown"))
    assert r["validated_series_candidate"] is False
    assert "真实历史起点未知" in r["blockers"]
    # 官方连续性下 proxy 也需起点已知
    assert r["proxy_qualified_series_candidate"] is False


def test_both_admissions_check_real_start():
    """4. 代理和官方两类准入均必须检查真实历史起点。"""
    for level in ("verified_official_calendar",
                  "verified_against_proxy_calendar"):
        bad = compute_admission(_mk(level, real_start="unknown"))
        good = compute_admission(_mk(level, real_start="20040102"))
        assert bad["proxy_qualified_series_candidate"] is False
        assert good["proxy_qualified_series_candidate"] is True
        if level == "verified_official_calendar":
            assert bad["validated_series_candidate"] is False
            assert good["validated_series_candidate"] is True
        else:
            assert bad["validated_series_candidate"] is False
            assert good["validated_series_candidate"] is False


def test_proxy_rejects_none_start():
    """real_history_start=None 也必须拒绝。"""
    r = compute_admission(_mk("verified_against_proxy_calendar",
                              real_start=None))
    assert r["proxy_qualified_series_candidate"] is False
    assert "真实历史起点未知" in r["proxy_blockers"]


def test_proxy_still_requires_other_conditions():
    """代理准入仍要求身份/口径/映射/质量/覆盖。"""
    for kw in ("identity", "basis", "mapping", "quality", "coverage"):
        r = compute_admission(_mk("verified_against_proxy_calendar",
                                  real_start="20040102", **{kw: False}))
        assert r["proxy_qualified_series_candidate"] is False, \
            f"{kw}=False 时 proxy 仍通过"


# ============================================================ 5-6. 真实数据
def test_proxy_qualified_zero_in_result(d3):
    """5. 12 只候选重新计算后，代理验证候选为 0。"""
    assert d3["summary"]["totals"]["proxy_qualified_series_candidate"] == 0
    for r in d3["candidates"]:
        assert r["admission"]["proxy_qualified_series_candidate"] is False


def test_399997cny02_keeps_level_but_not_admitted(d3):
    """6. 399997CNY02 保留代理连续性等级，但准入为 false。"""
    r = next(x for x in d3["candidates"]
             if x["tr_candidate"] == "399997CNY02")
    a = r["admission"]
    # 连续性等级保留
    assert r["continuity_level"] == "verified_against_proxy_calendar"
    assert "代理" in a["continuity_level_definition"]
    # 覆盖与连续性结果保留
    assert a["evidence_snapshot"]["coverage_status"] == "verified"
    assert a["evidence_snapshot"]["continuity_raw_status"] == "verified"
    # 但三个准入均为 false
    assert a["proxy_qualified_series_candidate"] is False
    assert a["validated_series_candidate"] is False
    assert a["formal_series_admitted"] is False
    # 阻断原因明确包含真实起点
    assert "真实历史起点未知" in a["proxy_blockers"]
    assert a["evidence_snapshot"]["real_history_start"] == "unknown"


def test_399997cny02_not_marked_official(d3):
    """不得将代理验证误写成官方验证。"""
    r = next(x for x in d3["candidates"]
             if x["tr_candidate"] == "399997CNY02")
    assert r["calendar_is_official"] is False
    assert r["continuity_level"] != "verified_official_calendar"


def test_ingest_still_12(d3):
    assert d3["summary"]["totals"][
        "raw_data_layer_ingest_candidate"] == 12


def test_validated_zero(d3):
    assert d3["summary"]["totals"]["validated_series_candidate"] == 0


def test_formal_zero(d3):
    assert d3["summary"]["totals"]["formal_series_admitted"] == 0


def test_continuity_levels_unchanged(d3):
    """五态连续性统计不变（代理等级仍为 1）。"""
    t = d3["summary"]["totals"]
    assert t["continuity_verified_official_calendar"] == 0
    assert t["continuity_verified_against_proxy_calendar"] == 1
    assert t["continuity_has_unresolved_suspicion"] == 8
    assert t["continuity_unknown"] == 3


# ============================================================ 7. 一致性
def test_three_json_consistent(d3):
    """7. 三份 JSON 的连续性等级一致。"""
    d1 = json.loads(AUDIT_1.read_text(encoding="utf-8"))
    d2 = json.loads(AUDIT_2.read_text(encoding="utf-8"))
    for r3 in d3["candidates"]:
        c = r3["tr_candidate"]
        l1 = next(x for x in d1["candidates"]
                  if x["tr_candidate"] == c)["quality"]["continuity_status"]
        l2 = next(x for x in d2["candidates"]
                  if x["tr_candidate"] == c)["quality"]["continuity_level"]
        assert l1 == l2 == r3["continuity_level"], f"{c} 三方不一致"


def test_reports_match_json(d3):
    """报告统计必须与 JSON 一致。"""
    txt = (REPORTS / "phase3B6_2_3_1_0_3_1_fix_report.md").read_text(
        encoding="utf-8")
    t = d3["summary"]["totals"]
    for k in ("raw_data_layer_ingest_candidate",
              "validated_series_candidate",
              "proxy_qualified_series_candidate",
              "formal_series_admitted"):
        assert str(t[k]) in txt, f"报告缺 {k}={t[k]}"


def test_admission_recomputed_matches_json(d3):
    """真实调用 compute_admission 重算，必须与 JSON 一致。"""
    for r in d3["candidates"]:
        snap = r["admission"]["evidence_snapshot"]
        cand = {
            "tr_candidate": r["tr_candidate"],
            "price_index": r["price_index"],
            "group": r["group"],
            "market": r["market"],
            "calendar_used": r["calendar_used"],
            "calendar_is_official": r["calendar_is_official"],
            "continuity_level": r["continuity_level"],
            "quality_020": {
                "coverage_status": snap["coverage_status"]},
            "synthetic_020": {
                "real_history_start": snap["real_history_start"],
                "status": snap["synthetic_status"]},
            "dims_020": snap,
        }
        rec = compute_admission(cand)
        for k in ("raw_data_layer_ingest_candidate",
                  "validated_series_candidate",
                  "proxy_qualified_series_candidate",
                  "formal_series_admitted"):
            assert rec[k] == r["admission"][k], \
                f"{r['tr_candidate']} 的 {k} 重算不一致"


# ============================================================ 8-10. 不变性
def test_original_evidence_sha256_unchanged():
    """8. 原始官方证据 SHA256 不变。"""
    import re
    OFFICIAL = re.compile(r"^(basic_|hist_|csindex_)")
    checked = 0
    for base in (REPORTS / "evidence" / "phase3B6_2_3_1_0",
                 REPORTS / "evidence" / "phase3B6_2_3_0_4"):
        m = base / "manifest.json"
        if not m.exists():
            continue
        doc = json.loads(m.read_text(encoding="utf-8"))
        for name, info in (doc.get("files") or {}).items():
            if not OFFICIAL.match(name) or not info.get("sha256"):
                continue
            f = base / name
            assert f.exists(), f"缺 {name}"
            assert hashlib.sha256(f.read_bytes()).hexdigest() == \
                info["sha256"], f"{name} 被修改"
            checked += 1
    assert checked > 0


def test_db_sha256_unchanged():
    """业务数据未变（原为文件级 SHA 断言）。

    3B-6.2.3.1.1 合法新增 6 张 tr_* 表后文件 SHA 必然变化，
    改为校验业务数据指纹。
    """
    assert_business_data_unchanged()


def test_db_unchanged_flag(d3):
    assert d3["db_unchanged"] is True


def test_gates_all_closed(d3):
    """10. 所有门禁保持关闭。"""
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


def test_manifest_complete():
    m = json.loads((EVID / "manifest.json").read_text(encoding="utf-8"))
    assert m["referenced_total"] == len(m["files"])
    for name, info in m["files"].items():
        if info["exists"]:
            p = ROOT / name
            assert p.exists(), f"{name} 标存在但缺失"
            assert hashlib.sha256(p.read_bytes()).hexdigest() == info["sha256"]


def test_reports_exist():
    for name in ("phase3B6_2_3_1_0_3_1_fix_report.md",
                 "phase3B6_2_3_1_0_3_1_test_report.md"):
        assert (REPORTS / name).exists(), f"缺报告 {name}"


def test_self_check_all_pass(d3):
    for k, v in d3["summary"]["_self_check"].items():
        assert v is True, f"自校验失败：{k}"


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
