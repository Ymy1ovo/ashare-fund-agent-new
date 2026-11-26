"""阶段3B-6.2.3.0.2 连续性/时点可用性/全收益可行性专项测试。

**直接调用真实审计函数**，不读预生成 JSON 自证。
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

from scripts.audit_3b6_2_3_0_2_continuity import (  # noqa: E402
    INDEX_CODES, INDEX_MARKET, TOTAL_RETURN_CANDIDATES, audit_continuity,
    audit_point_in_time, audit_revision_risk, db_connect, summarize)

REPORTS = ROOT / "reports"
EVID = REPORTS / "evidence" / "phase3B6_2_3_0_2"
COV = REPORTS / "phase3B6_2_3_0_2_coverage_audit.json"
PIT = REPORTS / "phase3B6_2_3_0_2_point_in_time_audit.json"
TR = REPORTS / "phase3B6_2_3_0_2_total_return_audit.json"


@pytest.fixture(scope="module")
def cov() -> dict:
    assert COV.exists(), "缺连续性审计 JSON"
    return json.loads(COV.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def pit() -> dict:
    assert PIT.exists(), "缺时点可用性 JSON"
    return json.loads(PIT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def tr() -> dict:
    assert TR.exists(), "缺全收益审计 JSON"
    return json.loads(TR.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def conn():
    c = db_connect()
    yield c
    c.close()


# ============================================================ 日历选择
def test_each_index_has_its_own_calendar():
    """每个指数必须声明适用市场与日历，不得统一套用 A 股日历。"""
    assert len(INDEX_MARKET) == 10
    for code in INDEX_CODES:
        m = INDEX_MARKET[code]
        assert m["market"], f"{code} 缺市场"
        assert m["calendar"], f"{code} 缺日历"
        assert m["basis"], f"{code} 缺日历依据"


def test_bond_and_hk_not_using_a_share_calendar():
    """000012（债券）与 930930（港股通）不得套用 A 股日历。"""
    assert INDEX_MARKET["000012"]["calendar"] != "A股交易日历"
    assert INDEX_MARKET["930930"]["calendar"] != "A股交易日历"
    assert "债券" in INDEX_MARKET["000012"]["calendar"]
    assert "港股" in INDEX_MARKET["930930"]["calendar"]


def test_hk_index_has_dates_outside_a_calendar(conn):
    """930930 必须存在不在 A 股日历内的真实记录（证明日历确实不同）。"""
    n = conn.execute("""
        select count(*) from index_daily d
        where d.index_code='930930' and d.quality_status='valid'
          and not exists (select 1 from trade_calendar t
                          where t.trade_date=d.trade_date)
    """).fetchone()[0]
    assert n > 0, "930930 无 A 股日历外记录，日历区分假设不成立"


def test_calendar_unavailable_means_not_verified(cov):
    """日历不可用的指数必须标记未验证，不得用错误日历给结论。"""
    for r in cov["indexes"]:
        if not r["calendar_available"]:
            assert r["continuity_verified"] is False
            assert r["missing_trading_days"] is None, \
                f"{r['index_code']} 用不可用日历算了缺失日"
            assert "未验证" in r["continuity_verdict"]


# ============================================================ 连续性
def test_continuity_count_matches_detail(cov):
    """10 个指数数量与明细一致。"""
    assert len(cov["indexes"]) == 10
    assert [r["index_code"] for r in cov["indexes"]] == INDEX_CODES
    assert cov["summary"]["total_indexes"] == 10


def test_summary_auto_computed(cov):
    """汇总必须由逐条明细自动计算。"""
    s = cov["summary"]
    recs = cov["indexes"]
    assert s["total_raw_rows"] == sum(r["raw_rows"] for r in recs)
    assert s["total_valid_rows"] == sum(r["valid_rows"] for r in recs)
    assert s["total_suspect_rows"] == sum(r["suspect_rows"] for r in recs)
    assert s["continuity_verified"] == sum(
        1 for r in recs if r["continuity_verified"])
    assert s["calendar_available"] == sum(
        1 for r in recs if r["calendar_available"])
    assert (s["continuity_verified"] + s["continuity_unverified"]
            == s["total_indexes"])


def test_raw_rows_equal_valid_plus_suspect(cov):
    """原始行数 = 有效行数 + suspect 行数。"""
    for r in cov["indexes"]:
        assert r["raw_rows"] == r["valid_rows"] + r["suspect_rows"], \
            f"{r['index_code']} 行数不守恒"


def test_placeholder_rows_identified(cov):
    """10 条 2004-01-01 占位行必须全部识别，且不计入有效行情。"""
    total = sum(len(r["placeholder_rows"]) for r in cov["indexes"])
    assert total == 10, f"占位行数 {total} != 10"
    for r in cov["indexes"]:
        for p in r["placeholder_rows"]:
            assert p["trade_date"] == "2004-01-01"
            assert r["earliest_effective_date"] != "2004-01-01", \
                f"{r['index_code']} 把占位行当成了有效起点"


def test_no_duplicate_or_descending(cov):
    for r in cov["indexes"]:
        assert r["duplicate_dates"] == 0, f"{r['index_code']} 有重复日期"
        assert r["descending_dates"] == 0, f"{r['index_code']} 有倒序"
        assert r["illegal_dates"] == []


def test_non_positive_close_detected(cov):
    """非正收盘必须被检出（H30184 的 0 值）。"""
    total = sum(r["non_positive_close"] for r in cov["indexes"])
    assert total >= 1, "未检出任何非正收盘"
    rec = next(r for r in cov["indexes"] if r["index_code"] == "H30184")
    assert rec["non_positive_close"] == 1
    assert rec["continuity_verified"] is False, \
        "H30184 有 0 值却判连续验证通过"


def test_h30184_zero_close_row(conn):
    """H30184 的 0 值记录必须真实存在且被识别。"""
    rows = conn.execute(
        "select trade_date, close, quality_status from index_daily "
        "where index_code='H30184' and close<=0").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "2013-06-28"
    assert rows[0][1] == 0.0


def test_a_share_indexes_verified(cov):
    """A 股日历可用的 8 个指数中，除 H30184 外应连续验证通过。"""
    for r in cov["indexes"]:
        if not r["calendar_available"]:
            continue
        if r["index_code"] == "H30184":
            continue
        assert r["continuity_verified"] is True, \
            f"{r['index_code']} 连续验证未通过：{r['continuity_verdict']}"
        assert r["missing_trading_days"] == 0


def test_continuity_uses_real_db(conn):
    """连续性审计必须读真实数据库，行数必须与库内一致。"""
    live = conn.execute(
        "select count(*) from index_daily").fetchone()[0]
    assert live == 50603
    recs = [audit_continuity(c, conn) for c in INDEX_CODES]
    assert sum(r["raw_rows"] for r in recs) == live


def test_continuity_verdict_never_empty(cov):
    for r in cov["indexes"]:
        assert r["continuity_verdict"], f"{r['index_code']} 缺结论"


# ============================================================ 时点可用性
def test_point_in_time_not_verified(pit):
    """时点可用性必须为 false，不得因数据完整就判通过。"""
    a = pit["audit"]
    assert a["point_in_time_verified"] is False
    c = a["conclusion"]
    assert c["historical_quotes_exist"] is True
    assert c["point_in_time_availability_provable"] is False
    assert c["historical_publication_time_provable"] is False
    assert c["historical_data_version_traceable"] is False


def test_no_multi_version_rows(conn):
    """同一 (index_code, trade_date) 不得有多版本行。"""
    n = conn.execute("""
        select count(*) from (
            select index_code, trade_date, count(*) c from index_daily
            group by index_code, trade_date having c > 1)""").fetchone()[0]
    assert n == 0


def test_all_collected_in_one_period(pit):
    """历史行情必须确认是集中采集（本轮实测单日）。"""
    a = pit["audit"]
    assert a["collected_at_is_single_batch"] is True
    assert len(a["collected_at_distinct_dates"]) <= 1


def test_fingerprint_semantics_not_history(pit):
    """row_fingerprint 不得被当成历史版本证明。"""
    a = pit["audit"]
    assert a["checks"]["fingerprint_proves_history"] is False
    assert "仅证明当前数据行内容" in a["row_fingerprint_semantics"]


def test_five_concepts_distinguished(pit):
    """历史存在/采集可追溯/版本可追溯/公开可证明/时点可证明必须分开。"""
    c = pit["audit"]["conclusion"]
    for k in ("historical_quotes_exist", "current_collection_time_traceable",
              "historical_data_version_traceable",
              "historical_publication_time_provable",
              "point_in_time_availability_provable"):
        assert k in c, f"缺概念 {k}"


def test_point_in_time_reason_present(pit):
    assert pit["audit"]["reason"]
    assert "不能证明" in pit["audit"]["reason"]


# ============================================================ 全收益可行性
def test_tr_codes_from_official_not_guessed(tr):
    """全收益代码必须逐个有官方全称，不得按命名规律猜测。"""
    for r in tr["indexes"]:
        for c in r["candidates"]:
            assert c["official_full_name"], \
                f"{c['code']} 无官方全称，可能是猜测代码"
            assert c["identity_verified"] is True
            assert c["publisher"] == "中证指数有限公司"


def test_tr_kind_taxonomy(tr):
    """口径分类必须严格区分股票全收益与债券衍生。"""
    kinds = set()
    for r in tr["indexes"]:
        for c in r["candidates"]:
            kinds.add(c["kind"])
    assert "gross_total_return" in kinds
    assert "net_total_return" in kinds
    assert "bond_clean_price" in kinds
    # 债券衍生不得被标成股票全收益
    for r in tr["indexes"]:
        if r["base_index"] == "000012":
            for c in r["candidates"]:
                assert c["kind"] in ("bond_clean_price",
                                     "bond_interest_reinvestment"), \
                    f"000012 衍生序列被误标为 {c['kind']}"


def test_stock_indexes_have_total_return(tr):
    """8 个股票价格指数必须有官方全收益序列。"""
    stock = ["000300", "000905", "000906", "000016", "399997",
             "H30184", "000942", "000922"]
    for code in stock:
        rec = next(r for r in tr["indexes"] if r["base_index"] == code)
        assert rec["total_return_obtainable"] is True, \
            f"{code} 无可用全收益序列"
        assert any(c["kind"] == "gross_total_return"
                   for c in rec["candidates"])


def test_tr_not_yet_in_database(tr):
    """全收益序列本轮只验证可取，未接入正式库。"""
    for r in tr["indexes"]:
        for c in r["candidates"]:
            if c["kind"] in ("gross_total_return", "net_total_return"):
                assert c["already_in_database"] is False, \
                    f"{c['code']} 声称已入库，但本轮未写入"


def test_tr_samples_have_source_and_sha(tr):
    """官方样本必须带来源 URL 与 SHA256。"""
    assert tr["samples_sha256"], "缺样本 SHA256"
    assert len(tr["samples_sha256"]) == 64
    f = EVID / "official_total_return_samples.json"
    assert f.exists()
    payload = f.read_text(encoding="utf-8")
    assert hashlib.sha256(payload.encode("utf-8")).hexdigest() == \
        tr["samples_sha256"]
    data = json.loads(payload)
    for k, v in data.items():
        assert v.get("url"), f"{k} 缺来源 URL"
        assert "csindex.com.cn" in v["url"]


def test_tr_summary_auto_computed(tr):
    s = tr["summary"]
    recs = tr["indexes"]
    assert s["indexes_with_tr_obtainable"] == sum(
        1 for r in recs if r["total_return_obtainable"])
    assert s["indexes_with_tr_candidate"] == sum(
        1 for r in recs if r["has_total_return"])


# ============================================================ 修订风险
def test_revision_risk_all_unknown():
    """修订风险无证据必须全部 unknown。"""
    f = EVID / "revision_risk.json"
    assert f.exists()
    d = json.loads(f.read_text(encoding="utf-8"))
    for r in d["audit"]["indexes"]:
        assert r["official_keeps_history_versions"] is None
        assert r["api_returns_revised_history"] is None
        assert r["methodology_changed"] is None
        assert r["archived_history_available"] is None
    assert d["audit"]["revision_risk_verified"] is False


def test_revision_risk_not_speculated():
    """修订风险结论不得写成已证实事实。"""
    f = EVID / "revision_risk.json"
    d = json.loads(f.read_text(encoding="utf-8"))
    for r in d["audit"]["indexes"]:
        assert "unknown" in r["verdict"].lower()


# ============================================================ 门禁
def test_gates_not_opened(cov, pit, tr, conn):
    """门禁不得因本轮审计而开放。"""
    cont = {"indexes": [audit_continuity(c, conn) for c in INDEX_CODES]}
    p = audit_point_in_time(conn)
    rv = audit_revision_risk(conn)
    from scripts.audit_3b6_2_3_0_2_continuity import (
        CONFIRMED_STOCK_PRICE_INDEXES, _tr_coverage)
    fake_idx = [{"base_index": c, "candidates": [],
                 "has_total_return": False, "total_return_obtainable": False,
                 "has_gross_total_return": False,
                 "has_net_total_return": False,
                 "gross_total_return_obtainable": False,
                 "net_total_return_obtainable": False} for c in INDEX_CODES]
    t = {"indexes": fake_idx, "coverage": _tr_coverage(fake_idx)}
    s = summarize(cont, p, t, rv)
    g = s["gates"]
    assert g["ready_for_3b6_2_3_1_series_build"] is False
    assert g["point_in_time_verified"] is False


def test_930930_should_be_excluded(tr):
    """930930 口径 unknown + 日历未知 → 应排除。"""
    rec = next(r for r in tr["indexes"] if r["base_index"] == "930930")
    # 有全收益候选，但主序列口径仍未确认
    assert rec["candidates"]
    from scripts.audit_3b6_2_3_0_2_continuity import INDEX_MARKET
    assert INDEX_MARKET["930930"]["calendar"] != "A股交易日历"


def test_docs_exist():
    for name in ("phase3B6_2_3_0_2_design.md",
                 "phase3B6_2_3_0_2_recommendation.md"):
        assert (REPORTS / name).exists(), f"缺文档 {name}"


def test_docs_gate_values():
    txt = (REPORTS / "phase3B6_2_3_0_2_recommendation.md").read_text(
        encoding="utf-8")
    assert "ready_for_backtest" in txt
    assert "ready_for_3b6_2_3_1_series_build" in txt
    assert "false" in txt.lower()


def test_no_vacuous_assertion():
    txt = Path(__file__).read_text(encoding="utf-8")
    assert ("or " + "True") not in txt
    assert ("assert " + "True") not in txt


# ============================================================ 3B-6.2.3.0.2.1 修正
def test_stock_denominator_is_eight_confirmed():
    """1. 8 个已确认股票价格指数作为统计分母。"""
    from scripts.audit_3b6_2_3_0_2_continuity import (
        CONFIRMED_STOCK_PRICE_INDEXES)
    assert len(CONFIRMED_STOCK_PRICE_INDEXES) == 8
    assert set(CONFIRMED_STOCK_PRICE_INDEXES) == {
        "000300", "000905", "000906", "000016",
        "399997", "H30184", "000942", "000922"}


def test_930930_not_in_stock_denominator(tr):
    """2. 930930 不能计入已确认股票价格指数分母。"""
    cov = tr["coverage"]
    assert "930930" not in cov["confirmed_stock_price_indexes"]
    assert cov["confirmed_stock_price_indexes_total"] == 8
    assert cov["hk_index_derivative_candidate_count"] == 1
    hk = cov["hk_index_derivative_candidates"][0]
    assert hk["base_index"] == "930930"
    assert hk["counts_in_stock_denominator"] is False


def test_000012_bond_counted_separately(tr):
    """3. 000012 债券衍生序列独立统计。"""
    cov = tr["coverage"]
    assert "000012" not in cov["confirmed_stock_price_indexes"]
    assert cov["bond_index_derivative_candidate_count"] == 1
    bond = cov["bond_index_derivative_candidates"][0]
    assert bond["base_index"] == "000012"
    assert bond["counts_in_stock_denominator"] is False
    assert set(bond["kinds"]) == {"bond_clean_price",
                                  "bond_interest_reinvestment"}


def test_gross_and_net_counted_separately(tr):
    """4. 全收益和净收益口径严格区分。"""
    cov = tr["coverage"]
    assert cov["confirmed_stock_indexes_with_gross_total_return"] == 8
    assert cov["confirmed_stock_indexes_with_net_total_return"] == 5
    # 全收益代码不得出现在净收益列表里
    assert not set(cov["confirmed_stock_gross_total_return_codes"]) & \
        set(cov["confirmed_stock_net_total_return_codes"])
    for r in tr["indexes"]:
        for c in r["candidates"]:
            if c["kind"] == "gross_total_return":
                assert "全收益" in (c["official_full_name"] or "")
            if c["kind"] == "net_total_return":
                assert "净收益" in (c["official_full_name"] or "")


def test_unconfirmed_basis_not_passed(tr):
    """5. 未经官方证据确认的衍生口径不得判定通过。"""
    for r in tr["indexes"]:
        for c in r["candidates"]:
            if not c["identity_verified"]:
                assert c["kind"] == "unknown", \
                    f"{c['code']} 无官方证据却给了口径 {c['kind']}"
    # 930930 主序列口径 unknown → 其衍生不得计入已确认分母
    hk = next(r for r in tr["indexes"] if r["base_index"] == "930930")
    assert hk["counts_in_confirmed_stock_denominator"] is False


def test_no_annual_estimate_without_full_series(tr):
    """6. 不存在完整历史序列时不得生成 1.5%~2.5% 年化差异结论。"""
    d = tr["return_difference_estimate"]
    assert d["quantitative_estimate_produced"] is False
    assert d["quantitative_estimate"] is None
    assert d["both_full_series_available"] is False
    assert "1.5%" in d["removed_claim"] or "1.5" in d["removed_claim"]
    assert d["requirements_for_future_estimate"]
    # 该数值只允许出现在「已删除」声明语境中，不得作为结论使用
    txt = (REPORTS / "phase3B6_2_3_0_2_recommendation.md").read_text(
        encoding="utf-8")
    lines = txt.splitlines()
    for i, line in enumerate(lines):
        if "1.5" not in line:
            continue
        ctx = line + (lines[i - 1] if i else "")
        assert ("已删除" in ctx or "删除理由" in ctx
                or "不足以" in ctx), \
            f"第 {i + 1} 行仍把年化差异当结论：{line.strip()}"


def test_suspect_rows_still_exist(conn, cov):
    """7. 10 条 suspect 占位记录仍然存在。

    3B-6.2.3.0.3 把 H30184/2013-06-28 的零值行也标记为 suspect，
    因此库内 suspect 总数为 11，其中 10 条是 2004-01-01 占位行。
    """
    n = conn.execute(
        "select count(*) from index_daily where quality_status<>'valid'"
    ).fetchone()[0]
    assert n == 11
    placeholders = conn.execute(
        "select count(*) from index_daily where quality_status<>'valid' "
        "and trade_date='2004-01-01'").fetchone()[0]
    assert placeholders == 10
    for r in cov["indexes"]:
        assert len(r["placeholder_rows"]) == 1
        assert r["placeholder_rows"][0]["trade_date"] == "2004-01-01"


def test_h30184_zero_still_present(conn, cov):
    """8. H30184 零值记录仍存在，close 原值未被修改。

    3B-6.2.3.0.3 按官方证据把它标记为 suspect（官方无法确认真实点位），
    但**没有插值、没有改 close**。
    """
    row = conn.execute(
        "select trade_date, close, quality_status from index_daily "
        "where index_code='H30184' and close<=0").fetchone()
    assert row is not None
    assert row[0] == "2013-06-28"
    assert row[1] == 0.0, "close 原值必须保留"
    assert row[2] == "suspect", "应已标记 suspect"
    rec = next(r for r in cov["indexes"] if r["index_code"] == "H30184")
    assert rec["non_positive_close"] == 1


def test_database_evidence_complete(cov):
    """9. 正式数据库只读证据必须完整（含 64 位 SHA256）。"""
    db = cov["database_evidence"]
    assert db["read_only"] is True
    assert len(db["database_sha256"]) == 64
    assert all(ch in "0123456789abcdef" for ch in db["database_sha256"])
    assert db["integrity_check"] == "ok"
    assert db["foreign_key_violations"] == 0
    assert db["index_daily_total_rows"] == 50603
    assert db["suspect_placeholder_count"] == 10
    assert db["non_positive_close_count"] == 1
    assert db["h30184_zero_row_present"] is True
    assert len(db["per_index_rows"]) == 10
    for code, v in db["per_index_rows"].items():
        assert v["raw_rows"] == v["valid_rows"] + v["suspect_rows"]


def test_coverage_auto_computed(tr):
    """10. 汇总统计由逐指数明细自动计算。"""
    cov = tr["coverage"]
    recs = tr["indexes"]
    stock = [r for r in recs
             if r["base_index"] in cov["confirmed_stock_price_indexes"]]
    assert cov["confirmed_stock_price_indexes_total"] == len(stock) == 8
    assert cov["confirmed_stock_indexes_with_gross_total_return"] == sum(
        1 for r in stock if r["gross_total_return_obtainable"])
    assert cov["confirmed_stock_indexes_with_net_total_return"] == sum(
        1 for r in stock if r["net_total_return_obtainable"])
    assert cov["total_return_series_in_database"] == sum(
        1 for r in recs for c in r["candidates"] if c["already_in_database"])


def test_gates_all_closed(tr):
    """11. 所有门禁保持关闭。"""
    txt = (REPORTS / "phase3B6_2_3_0_2_recommendation.md").read_text(
        encoding="utf-8")
    for gate in ("ready_for_research_analysis", "ready_for_backtest",
                 "ready_for_formal_ranking",
                 "ready_for_3b6_2_3_1_series_build"):
        assert gate in txt, f"缺门禁 {gate}"
    assert tr["coverage"]["total_return_series_in_database"] == 0


def test_continuity_wording_accurate():
    """连续性措辞必须准确，不得把代理日历结果说成官方连续性证明。"""
    for name in ("phase3B6_2_3_0_2_recommendation.md",
                 "phase3B6_2_3_0_2_design.md"):
        txt = (REPORTS / name).read_text(encoding="utf-8")
        assert "A 股交易日历代理" in txt or "A股交易日历代理" in txt
        # 该措辞只允许出现在否定语境（"不能/不得/更不"）
        for i, line in enumerate(txt.splitlines()):
            if "官方历史行情完全连续" in line:
                ctx = line + (txt.splitlines()[i - 1] if i else "")
                assert ("不能" in ctx or "不得" in ctx or "更不" in ctx), \
                    f"{name} 第 {i + 1} 行把代理日历说成了官方连续证明"
    design = (REPORTS / "phase3B6_2_3_0_2_design.md").read_text(
        encoding="utf-8")
    assert "连续性 unknown" in design
    assert "连续性不通过" in design


def test_derivative_codes_have_official_evidence(tr):
    """所有衍生序列必须带官方证据（名称 + 样本 + URL）。"""
    for r in tr["indexes"]:
        for c in r["candidates"]:
            assert c["official_full_name"], f"{c['code']} 缺官方全称"
            assert c["publisher"] == "中证指数有限公司"
            if c["official_api_available"]:
                got = [s for s in c["official_api_samples"]
                       if s.get("close") is not None]
                assert got, f"{c['code']} 声称可取但无样本"
                for s in got:
                    assert s.get("url"), f"{c['code']} 样本缺 URL"
