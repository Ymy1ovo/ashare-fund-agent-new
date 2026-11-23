"""阶段3B-5.5.1 同类分组可验证性与年化收益证据修正专项测试。

只读：不联网、不写正式库。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.fund.research.practical_report import (  # noqa: E402
    build_practical_report, report_to_markdown,
)
from app.fund.research.quality import (  # noqa: E402
    LEVEL_A, LEVEL_B, LEVEL_C, LEVEL_D, LEVEL_NA,
    _peer_key_family_unknown, build_indicator_grades, grade_annualized,
    grade_peer_comparison,
)

REAL_SAMPLES = ("050002", "001052", "001938", "000032", "000509",
                "001548", "001549", "519066")


# ================================================================ 问题1：可验证性
def test_verifiable_false_with_six_members_is_d():
    """verifiable_group=False，样本 6 个也必须 D（本轮阻断项）。"""
    r = grade_peer_comparison({
        "peer_key": "active_equity|中证500",
        "member_count": 6,
        "grouping_source": "benchmark",
        "benchmark_confidence": "high",
        "verifiable_group": False,
    })
    assert r["quality_level"] == LEVEL_D
    assert r["status"] == "no_verifiable_group"
    assert r["value"] is None
    assert "不可验证" in r["reason"]


def test_verifiable_false_with_huge_sample_still_d():
    r = grade_peer_comparison({
        "peer_key": "lof|index|sector|中证白酒",
        "member_count": 50,
        "grouping_source": "benchmark",
        "benchmark_confidence": "high",
        "verifiable_group": False,
    })
    assert r["quality_level"] == LEVEL_D
    assert r["status"] == "no_verifiable_group"


def test_bond_pure_unknown_is_d():
    """bond_pure|unknown 必须 D。"""
    r = grade_peer_comparison({
        "peer_key": "bond_pure|unknown", "member_count": 2,
        "grouping_source": "benchmark", "benchmark_confidence": "high",
        "verifiable_group": True})
    assert r["quality_level"] == LEVEL_D
    assert r["status"] == "no_verifiable_group"
    assert r["value"] is None


def test_bond_pure_unknown_with_many_members_is_d():
    r = grade_peer_comparison({
        "peer_key": "bond_pure|unknown", "member_count": 12,
        "grouping_source": "benchmark", "benchmark_confidence": "high",
        "verifiable_group": True})
    assert r["quality_level"] == LEVEL_D


def test_active_equity_unknown_is_d():
    """active_equity|unknown 必须 D。"""
    r = grade_peer_comparison({
        "peer_key": "active_equity|unknown", "member_count": 3,
        "grouping_source": "unknown", "benchmark_confidence": "none",
        "verifiable_group": False})
    assert r["quality_level"] == LEVEL_D
    assert r["status"] == "no_verifiable_group"
    assert r["value"] is None


def test_active_equity_unknown_even_if_flag_says_true():
    """即使 flag 误标 True，组键族为 unknown 也必须 D。"""
    r = grade_peer_comparison({
        "peer_key": "active_equity|unknown", "member_count": 8,
        "grouping_source": "benchmark", "benchmark_confidence": "medium",
        "verifiable_group": True})
    assert r["quality_level"] == LEVEL_D
    assert r["status"] == "no_verifiable_group"


def test_lof_active_unknown_is_d():
    r = grade_peer_comparison({
        "peer_key": "lof|active|unknown", "member_count": 5,
        "grouping_source": "unknown", "benchmark_confidence": "none",
        "verifiable_group": False})
    assert r["quality_level"] == LEVEL_D


def test_valid_index_group_ample_sample_is_b():
    """有效指数分组 + ≥5 个本体 → 正常 B。"""
    r = grade_peer_comparison({
        "peer_key": "etf_linked|broad|沪深300", "member_count": 7,
        "grouping_source": "benchmark", "benchmark_confidence": "high",
        "verifiable_group": True})
    assert r["quality_level"] == LEVEL_B
    assert r["status"] == "usable"
    assert r["value"] == 7


def test_valid_benchmark_group_ample_sample_is_b():
    r = grade_peer_comparison({
        "peer_key": "active_equity|中证800", "member_count": 5,
        "grouping_source": "benchmark", "benchmark_confidence": "medium",
        "verifiable_group": True})
    assert r["quality_level"] == LEVEL_B


def test_valid_group_one_member_is_d():
    r = grade_peer_comparison({
        "peer_key": "etf_linked|broad|上证50", "member_count": 1,
        "grouping_source": "benchmark", "benchmark_confidence": "medium",
        "verifiable_group": True})
    assert r["quality_level"] == LEVEL_D
    assert r["status"] == "insufficient_peer_sample"


def test_valid_group_two_to_four_is_c():
    for n in (2, 3, 4):
        r = grade_peer_comparison({
            "peer_key": "ordinary_index|broad|中证500", "member_count": n,
            "grouping_source": "benchmark", "benchmark_confidence": "medium",
            "verifiable_group": True})
        assert r["quality_level"] == LEVEL_C, n
        assert r["status"] == "small_sample"


def test_money_market_not_d_for_missing_index():
    """货币基金不因缺少指数/基准被判 D。"""
    r = grade_peer_comparison({
        "peer_key": "money_market", "member_count": 2,
        "grouping_source": "unknown", "benchmark_confidence": "none",
        "verifiable_group": True})
    assert r["quality_level"] != LEVEL_D
    assert r["quality_level"] == LEVEL_C
    assert r["status"] == "small_sample"


def test_money_market_never_mixes():
    r = grade_peer_comparison({"peer_key": "money_market", "member_count": 2})
    assert "净值型" in r["limitation"]


def test_money_market_ample_sample_is_b():
    r = grade_peer_comparison({"peer_key": "money_market", "member_count": 8})
    assert r["quality_level"] == LEVEL_B
    assert r["status"] == "usable"


def test_money_market_single_is_d():
    r = grade_peer_comparison({"peer_key": "money_market", "member_count": 1})
    assert r["quality_level"] == LEVEL_D
    assert r["status"] == "insufficient_peer_sample"


def test_peer_key_family_parser():
    assert _peer_key_family_unknown("etf_linked|broad|沪深300") == "沪深300"
    assert _peer_key_family_unknown("active_equity|中证500") == "中证500"
    assert _peer_key_family_unknown("bond_pure|unknown") == "unknown"
    assert _peer_key_family_unknown("lof|index|sector|中证白酒") == "中证白酒"
    assert _peer_key_family_unknown("money_market") == "money_market"
    assert _peer_key_family_unknown(None) is None


def test_peer_no_key_is_d():
    r = grade_peer_comparison({"member_count": 9})
    assert r["quality_level"] == LEVEL_D
    assert r["status"] == "no_verifiable_group"


def test_peer_never_ranks():
    for n in (1, 3, 8):
        r = grade_peer_comparison({
            "peer_key": "etf_linked|broad|沪深300", "member_count": n,
            "grouping_source": "benchmark",
            "benchmark_confidence": "high", "verifiable_group": True})
        assert "排名" in r["limitation"] or "对照" in r["limitation"]


# ================================================================ 问题2：年化证据
def test_annualized_with_full_dates_is_a():
    r = grade_annualized({"status": "ok", "value": 0.1026,
                          "start_date": "2015-11-03",
                          "end_date": "2026-11-20",
                          "span_days": 4035})
    assert r["quality_level"] == LEVEL_A
    assert "2015-11-03" in r["evidence"]
    assert "2026-11-20" in r["evidence"]


def test_annualized_fills_dates_from_quality_report():
    """节点无日期时用真实质量信息日期补充（不构造）。"""
    r = grade_annualized(
        {"status": "ok", "value": -0.025595, "span_days": 4217},
        quality={"date_min": "2015-05-05", "date_max": "2026-11-20"})
    assert r["quality_level"] == LEVEL_A
    assert "2015-05-05" in r["evidence"]
    assert "2026-11-20" in r["evidence"]
    assert "与质量报告一致" in r["evidence"]


def test_annualized_ok_but_value_none_not_a():
    """status=ok 但 value=None → 不得给 A。"""
    r = grade_annualized({"status": "ok", "value": None,
                          "start_date": "2015-01-01",
                          "end_date": "2026-01-01"})
    assert r["quality_level"] == LEVEL_D
    assert r["status"] == "invalid_result"
    assert r["value"] is None


def test_annualized_no_dates_never_fabricates():
    """任何可验证日期都没有 → 不给 A，且 evidence 里不出现编造日期。"""
    r = grade_annualized({"status": "ok", "value": 0.05}, quality={})
    assert r["quality_level"] == LEVEL_D
    assert r["status"] == "insufficient_evidence"
    assert "None" in r["evidence"] or "不构造" in (r["limitation"] or "")
    # 不得凭空出现任何 4 位年份
    assert "20" not in r["evidence"].replace("质量信息日期", "")


def test_annualized_gap_block_still_works():
    """既有缺口阻断必须继续通过。"""
    r = grade_annualized({"status": "insufficient_data",
                          "reason": "首尾区间内存在 1 处超过 15 天的缺口"})
    assert r["quality_level"] == LEVEL_D
    assert r["value"] is None
    assert "不跨越缺口" in r["limitation"]


def test_annualized_insufficient_stays_d():
    for st in ("insufficient_data", "no_nav_data", "not_available"):
        r = grade_annualized({"status": st, "value": None})
        assert r["quality_level"] == LEVEL_D, st


def test_annualized_evidence_uses_quality_dates_end_to_end():
    """真实报告里 001052 的年化证据必须带真实日期。"""
    d = build_practical_report("001052")
    cell = d["5_indicator_grades"]["indicators"]["annualized_return"]
    q = d["4_data_quality_level"]["coverage"]
    assert cell["quality_level"] == LEVEL_A
    assert q["date_min"] in cell["evidence"]
    assert q["date_max"] in cell["evidence"]


def test_report_annualized_interval_source():
    d = build_practical_report("001052")
    a = d["7_return_risk"]["annualized_return"]
    assert a["start_date"] is not None
    assert a["end_date"] is not None
    assert a["interval_source"] in ("node", "quality_report")
    assert "未构造日期" in a["interval_note"]


def test_annualized_dates_equal_quality_dates():
    """补充的日期必须与质量报告完全一致，不能是近似值。"""
    d = build_practical_report("001548")
    a = d["7_return_risk"]["annualized_return"]
    q = d["4_data_quality_level"]["coverage"]
    assert a["start_date"] == q["date_min"]
    assert a["end_date"] == q["date_max"]


# ================================================================ 真实样本
@pytest.mark.parametrize("code", REAL_SAMPLES)
def test_real_sample_annualized_has_dates_when_ok(code):
    d = build_practical_report(code)
    cell = d["5_indicator_grades"]["indicators"]["annualized_return"]
    if cell["quality_level"] == LEVEL_A:
        assert cell["value"] is not None
        q = d["4_data_quality_level"]["coverage"]
        assert q["date_min"] in cell["evidence"]
        assert q["date_max"] in cell["evidence"]
    elif d["2_product_classification"]["is_money_fund"]:
        # 货币基金净值型指标恒 not_applicable，不是 D
        assert cell["quality_level"] == LEVEL_NA
    else:
        assert cell["quality_level"] == LEVEL_D


@pytest.mark.parametrize("code", REAL_SAMPLES)
def test_real_sample_peer_never_falsely_verifiable(code):
    """真实样本里，未知基准组不得被评为可比较。"""
    d = build_practical_report(code)
    pg = d["8_peer_comparability"]["peer_group"]
    cell = d["8_peer_comparability"]["grade"]
    if pg["peer_key"] in ("bond_pure|unknown", "active_equity|unknown") \
            or str(pg["peer_key"]).endswith("|unknown"):
        assert cell["quality_level"] == LEVEL_D
        assert cell["status"] == "no_verifiable_group"


def test_bond_sample_000032_now_d():
    """000032 修复前是 C，修复后必须 D（bond_pure|unknown）。"""
    d = build_practical_report("000032")
    cell = d["8_peer_comparability"]["grade"]
    assert cell["quality_level"] == LEVEL_D
    assert cell["status"] == "no_verifiable_group"


def test_active_equity_001938_valid_group_is_c():
    """001938 的组键是 active_equity|中证500（可验证），2 个本体 → C。"""
    d = build_practical_report("001938")
    cell = d["8_peer_comparability"]["grade"]
    pg = d["8_peer_comparability"]["peer_group"]
    assert pg["peer_key"] == "active_equity|中证500"
    assert cell["quality_level"] == LEVEL_C
    assert cell["status"] == "small_sample"


def test_money_000509_not_d():
    d = build_practical_report("000509")
    cell = d["8_peer_comparability"]["grade"]
    assert cell["quality_level"] == LEVEL_C
    assert cell["status"] == "small_sample"


def test_ac_pair_shares_same_peer_and_dedup():
    """001548/001549 同属一个本体，同类组本体数必须是 1。"""
    a = build_practical_report("001548")
    c = build_practical_report("001549")
    assert (a["8_peer_comparability"]["peer_group"]["peer_key"]
            == c["8_peer_comparability"]["peer_group"]["peer_key"])
    assert a["8_peer_comparability"]["peer_group"]["member_count"] == 1
    assert a["8_peer_comparability"]["peer_group"]["deduped_by_fund_id"] is True


def test_build_indicator_grades_uses_quality_for_annualized():
    """build_indicator_grades 必须把 quality 传给年化评级。"""
    report = {
        "quality": {"rows": 3000, "date_min": "2015-01-01",
                    "date_max": "2026-01-01",
                    "gap_count_over_threshold": 0},
        "indicators": {
            "annualized_return": {"status": "ok", "value": 0.06},
            "returns": {}, "risk": {}, "risk_adjusted": {},
            "not_computed": {},
        },
        "is_money_fund": False,
    }
    g = build_indicator_grades(report, peer_ctx=None, cost=None)
    cell = g["indicators"]["annualized_return"]
    assert cell["quality_level"] == LEVEL_A
    assert "2015-01-01" in cell["evidence"]
    assert "2026-01-01" in cell["evidence"]


def test_markdown_shows_annualized_interval():
    d = build_practical_report("001052")
    md = report_to_markdown(d)
    assert "annualized_return" in md
    assert "2015-05-05" in md


# ================================================================ 只读守恒
def test_production_readonly_untouched():
    from app.database.db import get_connection
    with get_connection() as conn:
        before = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("fund_master", "fund_share_classes",
                            "fund_nav_daily", "fund_lifecycle_events")}
    for code in ("050002", "000032", "001052"):
        build_practical_report(code)
    with get_connection() as conn:
        after = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                 for t in before}
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert before == after


def test_gate_fixed():
    d = build_practical_report("050002")
    assert d["gate"]["ready_for_research_analysis"] is True
    assert d["gate"]["ready_for_backtest"] is False
    assert d["gate"]["ready_for_formal_ranking"] is False
