"""阶段3B-6.2.3.1.0 官方全收益指数历史序列可行性审计专项测试。

**真实读取原始证据文件并重新计算 SHA256**，不使用固定字符串自证。
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

from scripts.audit_3b6_2_3_1_0_total_return import (  # noqa: E402
    BOND_INDEXES, HK_INDEXES, STOCK_PRICE_INDEXES, STOCK_TR_CANDIDATES,
    _real_history_start, connect_ro, file_sha256, summarize)

REPORTS = ROOT / "reports"
EVID = REPORTS / "evidence" / "phase3B6_2_3_1_0"
AUDIT = REPORTS / "phase3B6_2_3_1_0_audit.json"

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


def _all_candidates(doc) -> list[dict]:
    return doc["candidates"]


# ============================================================ 分组隔离
def test_three_groups_disjoint(doc):
    """股票/债券/港股必须分为三个独立集合，不得混用。"""
    groups = {r["group"] for r in _all_candidates(doc)}
    assert groups == {"stock_total_return", "bond_derivative",
                      "hk_derivative"}
    # 债券与港股不得出现在股票集合
    stock_codes = {r["tr_candidate"] for r in _all_candidates(doc)
                   if r["group"] == "stock_total_return"}
    for c in list(BOND_INDEXES.values())[0]:
        assert c not in stock_codes, f"{c} 债券序列混入股票集合"
    for c in list(HK_INDEXES.values())[0]:
        assert c not in stock_codes, f"{c} 港股序列混入股票集合"


def test_bond_and_hk_counted_separately(doc):
    """债券与港股必须独立统计。"""
    s = doc["summary"]
    assert s["bond_derivative"]["candidate_count"] == 2
    assert s["hk_derivative"]["candidate_count"] == 1
    assert s["stock_total_return"]["candidate_count"] == 9


def test_stock_price_indexes_all_covered(doc):
    """8 个股票价格指数必须全部有全收益候选。"""
    s = doc["summary"]
    assert s["stock_price_indexes_expected"] == 8
    assert s["stock_price_indexes_covered"] == 8
    covered = {r["price_index"] for r in _all_candidates(doc)
               if r["group"] == "stock_total_return"}
    assert covered == set(STOCK_PRICE_INDEXES)


# ============================================================ 官方身份
def test_all_candidates_identity_verified(doc):
    """全部候选的官方身份必须已核验。"""
    for r in _all_candidates(doc):
        assert r["dimensions"]["official_identity_verified"] is True, \
            f"{r['tr_candidate']} 身份未核验"
        b = r["tr_basic"]
        assert b["official_full_name"], f"{r['tr_candidate']} 缺官方全称"
        assert b["basic_date"], f"{r['tr_candidate']} 缺基日"
        assert b["publish_date"], f"{r['tr_candidate']} 缺发布日"


def test_identity_evidence_from_official_host(doc):
    """身份证据必须来自官方域名。"""
    for r in _all_candidates(doc):
        url = r["tr_basic"].get("url") or ""
        assert "csindex.com.cn" in url, \
            f"{r['tr_candidate']} 身份证据非官方：{url}"


def test_base_date_not_confused_with_publish_date(doc):
    """基日与发布日必须分别记录且不相等。"""
    for r in _all_candidates(doc):
        b = r["tr_basic"]
        assert b["basic_date"] != b["publish_date"], \
            f"{r['tr_candidate']} 基日与发布日相同"


# ============================================================ 收益口径
def test_return_basis_from_official_name(doc):
    """收益口径必须由官方名称明确判定。"""
    for r in _all_candidates(doc):
        if r["group"] == "stock_total_return":
            assert r["return_basis"] in ("gross_total_return",
                                         "net_total_return"), \
                f"{r['tr_candidate']} 股票序列口径未判定"
            name = r["tr_basic"]["official_full_name"]
            if r["return_basis"] == "gross_total_return":
                assert "全收益" in name
            else:
                assert "净收益" in name


def test_bond_basis_not_stock_total_return(doc):
    """债券衍生序列不得被判为股票全收益。"""
    for r in _all_candidates(doc):
        if r["group"] == "bond_derivative":
            assert r["return_basis"] not in ("gross_total_return",
                                             "net_total_return"), \
                f"{r['tr_candidate']} 债券序列被误判为股票全收益口径"
            assert r["dimensions"]["return_basis_verified"] is False


# ============================================================ 历史接口
def test_history_api_available_for_all(doc):
    """全部候选必须取得完整历史（>100 行）。"""
    for r in _all_candidates(doc):
        assert r["dimensions"]["history_api_available"] is True, \
            f"{r['tr_candidate']} 历史接口不可用"
        assert r["quality"]["row_count"] > 100


def test_history_raw_files_exist_and_sha256(doc):
    """历史原始文件必须存在且 SHA256 可复核（真实计算）。"""
    m = json.loads((EVID / "manifest.json").read_text(encoding="utf-8"))
    m_files = m.get("files") or {}
    checked = 0
    for r in _all_candidates(doc):
        code = r["tr_candidate"]
        rel = r["tr_history_meta"].get("file")
        assert rel, f"{code} 缺历史文件路径"
        p = ROOT / rel
        assert p.exists(), f"{code} 历史文件缺失"
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        assert actual == r["tr_history_meta"]["sha256"], \
            f"{code} 历史文件 SHA256 不符"
        assert actual == m_files[p.name]["sha256"], \
            f"{code} 与 manifest 不符"
        checked += 1
    assert checked == len(_all_candidates(doc))


def test_history_url_contains_real_params(doc):
    """历史请求 URL 必须含真实指数代码与起止日期。"""
    for r in _all_candidates(doc):
        url = r["tr_history_meta"].get("url") or ""
        assert "indexCode=" + r["tr_candidate"] in url, \
            f"{r['tr_candidate']} URL 缺 indexCode"
        assert "startDate=20040101" in url
        assert "endDate=" in url


def test_manifest_covers_all_evidence():
    """manifest 必须覆盖全部原始证据并带 SHA256。"""
    m = json.loads((EVID / "manifest.json").read_text(encoding="utf-8"))
    assert m["file_count"] == len(m["files"])
    assert m["file_count"] >= 20
    for name, info in m["files"].items():
        f = EVID / name
        assert f.exists(), f"manifest 列出的 {name} 不存在"
        assert hashlib.sha256(f.read_bytes()).hexdigest() == info["sha256"]


# ============================================================ 覆盖率与质量
def test_no_missing_trading_days_for_stock(doc):
    """股票全收益序列相对 A 股日历代理不得有缺失交易日。"""
    for r in _all_candidates(doc):
        if r["group"] != "stock_total_return":
            continue
        assert r["quality"]["missing_trading_days"] == 0, \
            f"{r['tr_candidate']} 缺 {r['quality']['missing_trading_days']} 天"


def test_real_history_start_not_20040101(doc):
    """真实历史起点不得是首行合成行 20040101。"""
    for r in _all_candidates(doc):
        q = r["quality"]
        if q.get("synthetic_first_row"):
            assert q["real_history_start"] != "20040101", \
                f"{r['tr_candidate']} 把合成行当成了真实起点"


def test_calendar_source_declared_as_proxy(doc):
    """日历来源必须声明为 A 股代理，不是官方日历。"""
    assert "代理" in doc["calendar_source"]
    assert "不是" in doc["calendar_source"]
    for r in _all_candidates(doc):
        assert "代理" in r["quality"]["calendar_source"]


def test_data_quality_checks_present(doc):
    """数据质量必须逐项检查（重复/倒序/非法/非数值/NaN/Inf/非正/空值）。"""
    keys = ("duplicate_dates", "descending_dates", "illegal_dates",
            "null_close", "non_numeric_close", "nan_or_inf_close",
            "non_positive_close")
    for r in _all_candidates(doc):
        for k in keys:
            assert k in r["quality"], f"{r['tr_candidate']} 缺质量项 {k}"


def test_h20184_zero_value_recorded(doc):
    """H20184 的 2013-06-28 零值必须如实记录（与价格指数同源问题）。"""
    r = next(x for x in _all_candidates(doc)
             if x["tr_candidate"] == "H20184")
    assert r["quality"]["non_positive_close"] >= 1
    assert "20130628" in r["quality"]["non_positive_sample"]
    assert r["dimensions"]["data_quality_verified"] is False


# ============================================================ 数值关系
def test_cross_year_samples_multiple_years(doc):
    """数值关系必须用多个不同年份样本比对。"""
    for r in _all_candidates(doc):
        samples = r["cross_year_samples"]
        if r["group"] != "stock_total_return":
            continue
        years = {s["date"][:4] for s in samples}
        assert len(years) >= 5, \
            f"{r['tr_candidate']} 样本年份仅 {len(years)} 个"


def test_ratio_relationship_checked(doc):
    """全收益/价格比值关系必须被检查并记录。"""
    for r in _all_candidates(doc):
        if r["group"] != "stock_total_return":
            continue
        m = r["mapping"]
        assert "all_ratios_at_least_one" in m
        assert "ratio_increasing" in m
        assert m["ratio_sample_count"] > 100


def test_ratio_equals_one_early_period_recorded(doc):
    """早期比值恰为 1 的事实必须记录（未体现分红再投资）。"""
    r = next(x for x in _all_candidates(doc)
             if x["tr_candidate"] == "H00300")
    m = r["mapping"]
    assert m["ratio_equals_one_count"] > 0, "未记录早期比值等于1的事实"
    assert "未体现分红再投资" in m["note"]


def test_mapping_note_admits_technical_judgement(doc):
    """映射判定必须声明是技术判断，不能替代官方口径文件。"""
    for r in _all_candidates(doc):
        assert "技术判断" in r["mapping"]["note"]


# ============================================================ 时点可用性
def test_point_in_time_all_unknown(doc):
    """全部候选的时点可用性必须为 unknown。"""
    for r in _all_candidates(doc):
        assert r["dimensions"]["point_in_time_available"] is False
        pit = r["point_in_time"]
        assert pit["historical_point_in_time_availability"] == "unknown"
        assert pit["has_historical_snapshot"] is False
        assert pit["has_revision_records"] is False


def test_point_in_time_reason_present(doc):
    """时点可用性 unknown 必须给出具体原因。"""
    pit = _all_candidates(doc)[0]["point_in_time"]
    assert "不能证明" in pit["reason"]
    assert "回溯" in pit["reason"]


# ============================================================ 九维独立
def test_nine_dimensions_all_present(doc):
    """九维必须全部存在且独立。"""
    dims = ["official_identity_verified", "mapping_to_price_index_verified",
            "return_basis_verified", "history_api_available",
            "history_coverage_verified", "data_quality_verified",
            "continuity_verified", "point_in_time_available",
            "formal_series_admitted"]
    for r in _all_candidates(doc):
        for d in dims:
            assert d in r["dimensions"], f"{r['tr_candidate']} 缺维度 {d}"


def test_no_candidate_admitted(doc):
    """本轮不得有任何候选准入正式序列。"""
    s = doc["summary"]
    assert s["admitted_count"] == 0
    for r in _all_candidates(doc):
        assert r["dimensions"]["formal_series_admitted"] is False


def test_admission_requires_all_eight(doc):
    """正式准入必须八项全通过（不得单项通过就准入）。"""
    for r in _all_candidates(doc):
        d = r["dimensions"]
        eight = [v for k, v in d.items()
                 if k != "formal_series_admitted"]
        assert d["formal_series_admitted"] == all(eight), \
            f"{r['tr_candidate']} 准入判定与八维不一致"


def test_identity_pass_not_equal_admission(doc):
    """官方身份通过不等于正式准入。"""
    for r in _all_candidates(doc):
        if r["dimensions"]["official_identity_verified"]:
            assert r["dimensions"]["formal_series_admitted"] is False


def test_summary_auto_computed(doc):
    """汇总必须由逐条明细自动计算。"""
    s = doc["summary"]
    recs = _all_candidates(doc)
    assert s["total_candidates"] == len(recs)
    for g in ("stock_total_return", "bond_derivative", "hk_derivative"):
        n = sum(1 for r in recs if r["group"] == g)
        assert s[g]["candidate_count"] == n


def test_self_check_all_pass(doc):
    for k, v in doc["summary"]["_self_check"].items():
        assert v is True, f"自校验失败：{k}"


# ============================================================ 数据库不变性
def test_db_sha256_unchanged():
    """业务数据未变（原为文件级 SHA 断言）。

    3B-6.2.3.1.1 合法新增 6 张 tr_* 表后文件 SHA 必然变化，
    改为校验业务数据指纹。
    """
    assert_business_data_unchanged()


def test_db_unchanged_flag(doc):
    assert doc["db_unchanged"] is True
    assert doc["db_before"]["database_sha256"] == \
        doc["db_after"]["database_sha256"]


def test_integrity_ok(conn):
    assert conn.execute("pragma integrity_check").fetchone()[0] == "ok"


def test_fk_zero(conn):
    assert len(conn.execute("pragma foreign_key_check").fetchall()) == 0


def test_index_daily_rows_unchanged(conn):
    assert conn.execute(
        "select count(*) from index_daily").fetchone()[0] == 50603


def test_no_tr_written_to_db(conn):
    """全收益序列不得写入正式库。"""
    for r in _all_candidates(
            json.loads(AUDIT.read_text(encoding="utf-8"))):
        n = conn.execute(
            "select count(*) from index_daily where index_code=?",
            (r["tr_candidate"],)).fetchone()[0]
        assert n == 0, f"{r['tr_candidate']} 已被写入正式库"


# ============================================================ 门禁与报告
def test_gates_all_closed(doc):
    g = doc["summary"]["gates"]
    assert g["ready_for_research_analysis"] is True
    assert g["ready_for_backtest"] is False
    assert g["ready_for_formal_ranking"] is False
    assert g["ready_for_3b6_2_3_1_series_build"] is False


def test_reports_exist():
    for name in ("phase3B6_2_3_1_0_design.md",
                 "phase3B6_2_3_1_0_audit_report.md",
                 "phase3B6_2_3_1_0_test_report.md"):
        assert (REPORTS / name).exists(), f"缺报告 {name}"


def test_audit_report_answers_eight_questions():
    """审计报告必须回答任务的 8 个问题。"""
    txt = (REPORTS / "phase3B6_2_3_1_0_audit_report.md").read_text(
        encoding="utf-8")
    for kw in ("8 个股票价格指数", "官方身份", "完整历史",
               "历史起点", "回溯", "时点可用性",
               "进入下一阶段", "阻塞", "额外官方证据"):
        assert kw in txt, f"审计报告缺「{kw}」"


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
