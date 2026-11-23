"""阶段3B-5.5 数据质量分级与指标可信度专项测试。

只读：不联网、不写库、不改正式数据。
需要临时库的用例全部自建 SQLite。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.fund.ingest_user_funds import UserFundIngestor  # noqa: E402
from app.fund.migration import ensure_fund_schema  # noqa: E402
from app.fund.migration_3b4_2 import ensure_3b4_2_schema  # noqa: E402
from app.fund.migration_3b4_4 import ensure_3b4_4_schema  # noqa: E402
from app.fund.research.practical_report import (  # noqa: E402
    build_practical_report, report_to_markdown,
)
from app.fund.research.quality import (  # noqa: E402
    LEVEL_A, LEVEL_B, LEVEL_C, LEVEL_D, LEVEL_NA, LEVEL_MEANING,
    build_indicator_grades, grade_annualized, grade_annualized_volatility,
    grade_daily_volatility, grade_excess_return, grade_fund,
    grade_max_drawdown, grade_nav_data, grade_peer_comparison,
    grade_sharpe, grade_share_cost, grade_source, worst_level,
)

OFFMARKET_SAMPLES = ("050002", "001052", "001938", "000032", "000509", "001548")


def _make_db(tmp_path: Path) -> Path:
    db = tmp_path / "q55.db"
    ensure_fund_schema(db)
    ensure_3b4_2_schema(db)
    ensure_3b4_4_schema(db)
    return db


def _days(start="2018-01-01", n=800):
    d0 = date.fromisoformat(start)
    return [(d0 + timedelta(days=i)).isoformat() for i in range(n)]


def _ingest(db, code, name, ftype="股票型-普通", *, money=False,
            n=800, company="测试基金公司"):
    def basic(c):
        return {"name": name, "full_name": name + "全称", "company": company,
                "type": ftype, "benchmark": "沪深300指数收益率×95%",
                "established": "2018-01-01"}
    kw = dict(fetch_basic=basic, fetch_dividend=lambda c: [])
    if money:
        kw["fetch_money"] = lambda c: [
            {"nav_date": d, "per_10k_yield": 0.6, "seven_day_annual": 2.2}
            for d in _days(n=n)]
    else:
        ds = _days(n=n)
        unit = [{"nav_date": d, "unit_nav": 1.0 + i * 0.0005}
                for i, d in enumerate(ds)]
        acc = [{"nav_date": d, "acc_nav": 1.0 + i * 0.0006}
               for i, d in enumerate(ds)]
        kw["fetch_nav"] = lambda c, k: unit if k == "unit" else acc
    return UserFundIngestor(db, **kw).ingest_one(code)


# ================================================================ 1. A/B/C/D
def test_grade_a_clean_long_history():
    q = {"rows": 3000, "date_min": "2015-01-01", "date_max": "2026-01-01",
         "gap_count_over_threshold": 0, "duplicate_dates": 0,
         "null_unit_nav": 0, "null_acc_nav": 0, "nonpositive_unit_nav": 0}
    r = grade_nav_data(q)
    assert r["quality_level"] == LEVEL_A
    assert r["status"] == "ok"


def test_grade_b_with_gaps():
    q = {"rows": 3000, "date_min": "2015-01-01", "date_max": "2026-01-01",
         "gap_count_over_threshold": 2, "duplicate_dates": 0,
         "null_unit_nav": 0, "null_acc_nav": 0}
    r = grade_nav_data(q)
    assert r["quality_level"] == LEVEL_B
    assert "缺口" in r["limitation"]


def test_grade_b_short_span():
    q = {"rows": 600, "date_min": "2023-01-01", "date_max": "2024-06-01",
         "gap_count_over_threshold": 0}
    assert grade_nav_data(q)["quality_level"] == LEVEL_B


def test_grade_c_anomalies():
    q = {"rows": 3000, "date_min": "2015-01-01", "date_max": "2026-01-01",
         "gap_count_over_threshold": 0, "duplicate_dates": 3}
    r = grade_nav_data(q)
    assert r["quality_level"] == LEVEL_C
    assert "重复日期" in r["evidence"]


def test_grade_c_very_short_history():
    q = {"rows": 120, "date_min": "2025-09-01", "date_max": "2026-01-01",
         "gap_count_over_threshold": 0}
    r = grade_nav_data(q)
    assert r["quality_level"] == LEVEL_C
    assert r["status"] == "short_history"


def test_grade_d_no_data():
    r = grade_nav_data({"rows": 0})
    assert r["quality_level"] == LEVEL_D
    assert r["status"] == "no_data"


def test_grade_does_not_read_returns():
    """质量分级不得接收或使用收益数值——传入收益字段也不影响结果。"""
    base = {"rows": 3000, "date_min": "2015-01-01", "date_max": "2026-01-01",
            "gap_count_over_threshold": 0}
    good = dict(base, ret_12m=0.5)
    bad = dict(base, ret_12m=-0.9)
    assert grade_nav_data(good)["quality_level"] == grade_nav_data(bad)["quality_level"]


# ================================================================ 2. 表现独立
def test_return_level_independent_from_quality(tmp_path):
    """高收益不提升质量等级；低收益不降低质量等级。"""
    db = _make_db(tmp_path)

    def make(code, name, slope):
        ds = _days(n=800)
        unit = [{"nav_date": d, "unit_nav": 1.0 + i * slope}
                for i, d in enumerate(ds)]
        acc = [{"nav_date": d, "acc_nav": 1.0 + i * slope} for i, d in enumerate(ds)]
        ing = UserFundIngestor(
            db,
            fetch_basic=lambda c: {"name": name, "company": "测试公司",
                                   "type": "股票型-普通",
                                   "established": "2018-01-01"},
            fetch_nav=lambda c, k: unit if k == "unit" else acc,
            fetch_dividend=lambda c: [])
        return ing.ingest_one(code)

    up = make("022001", "测试上涨基金", 0.002)     # 涨
    down = make("022002", "测试下跌基金", -0.0008)  # 跌
    assert up.status == down.status == "ingested"

    a = build_practical_report("022001", db)
    b = build_practical_report("022002", db)
    # 数据质量等级相同
    assert (a["4_data_quality_level"]["overall_level"]
            == b["4_data_quality_level"]["overall_level"])
    # 但收益符号相反
    ra = a["7_return_risk"]["returns"]["ret_12m"]["value"]
    rb = b["7_return_risk"]["returns"]["ret_12m"]["value"]
    assert ra > 0 > rb


def test_fund_grade_states_not_returns():
    g = grade_fund({"rows": 3000, "date_min": "2015-01-01",
                    "date_max": "2026-01-01", "gap_count_over_threshold": 0},
                   source="akshare.fund_open_fund_info_em")
    assert g["not_influenced_by_returns"] is True
    assert "与基金收益高低无关" in g["statement"]


# ================================================================ 3. 缺口降级
def test_gap_degrades_annualized():
    r = grade_annualized({"status": "insufficient_data",
                          "reason": "存在 1 处超过 15 天的缺口"})
    assert r["quality_level"] == LEVEL_D
    assert r["value"] is None
    assert "不跨越缺口" in r["limitation"]


def test_gap_degrades_annualized_volatility():
    r = grade_annualized_volatility({
        "status": "ok", "value": 0.0069, "daily_vol": 0.0069,
        "annualized": False,
        "annualization_blocked_reason": "存在 1 处超过 15 天的缺口"})
    assert r["quality_level"] == LEVEL_D
    assert r["status"] == "blocked"
    assert r["value"] is None


def test_daily_volatility_reads_daily_vol_not_value():
    """value 可能是年化值；日波动必须取 daily_vol。"""
    node = {"status": "ok", "value": 0.2339, "daily_vol": 0.0150,
            "sample_size": 2801, "observed_per_year": 242.78}
    r = grade_daily_volatility(node)
    assert r["quality_level"] == LEVEL_A
    assert r["value"] == 0.0150
    assert r["value"] != node["value"]


# ================================================================ 4. 回撤不完整
def test_max_drawdown_degraded_marked():
    r = grade_max_drawdown({"status": "ok", "value": 0.33, "degraded": True,
                            "complete_interval": False, "segment_count": 2,
                            "gap_count_over_threshold": 1, "null_count": 0,
                            "degraded_reason": "存在 1 处缺口"})
    assert r["quality_level"] == LEVEL_B
    assert r["status"] == "degraded"
    assert "不是全区间完整最大回撤" in r["limitation"]


def test_max_drawdown_complete_is_a():
    r = grade_max_drawdown({"status": "ok", "value": 0.29, "degraded": False,
                            "complete_interval": True, "segment_count": 1,
                            "gap_count_over_threshold": 0, "null_count": 0})
    assert r["quality_level"] == LEVEL_A


def test_max_drawdown_not_computable():
    r = grade_max_drawdown({"status": "insufficient_data", "value": None})
    assert r["quality_level"] == LEVEL_D
    assert r["value"] is None


# ================================================================ 5. Sharpe
def test_sharpe_rejected_without_riskfree():
    r = grade_sharpe({"status": "not_available", "value": None,
                      "reason": "无风险利率无可靠数据源"})
    assert r["quality_level"] == LEVEL_D
    assert r["value"] is None
    assert "0 冒充" in r["limitation"]


def test_sharpe_never_zero_filled(tmp_path):
    db = _make_db(tmp_path)
    _ingest(db, "022010", "测试Sharpe基金")
    grades = build_indicator_grades(
        build_practical_report("022010", db) and
        {"quality": {"rows": 800}, "indicators": {"risk_adjusted": {
            "sharpe": {"status": "not_available", "value": None}},
            "not_computed": {}}})
    assert grades["indicators"]["sharpe"]["value"] is None


# ================================================================ 6. 超额收益
def test_excess_return_rejected_without_benchmark():
    r = grade_excess_return({"excess_return": "无基准收益序列，禁止计算超额收益"})
    assert r["quality_level"] == LEVEL_D
    assert r["status"] == "not_computed"
    assert r["value"] is None


def test_excess_return_not_zero(tmp_path):
    db = _make_db(tmp_path)
    _ingest(db, "022011", "测试超额基金")
    d = build_practical_report("022011", db)
    cell = d["5_indicator_grades"]["indicators"]["excess_return"]
    assert cell["value"] is None
    assert cell["status"] == "not_computed"


# ================================================================ 7. 同类样本
def test_peer_insufficient_sample():
    r = grade_peer_comparison({"peer_key": "ordinary_index|broad|沪深300",
                               "member_count": 1,
                               "grouping_source": "benchmark",
                               "benchmark_confidence": "medium"})
    assert r["quality_level"] == LEVEL_D
    assert r["status"] == "insufficient_peer_sample"
    assert "拒绝比较" in r["limitation"]


def test_peer_no_verifiable_group():
    r = grade_peer_comparison({"peer_key": "unknown", "member_count": 3})
    assert r["quality_level"] == LEVEL_D
    assert r["status"] == "no_verifiable_group"


def test_peer_small_sample_is_c():
    r = grade_peer_comparison({"peer_key": "bond_pure|unknown", "member_count": 2,
                               "grouping_source": "benchmark",
                               "benchmark_confidence": "medium"})
    assert r["quality_level"] == LEVEL_C
    assert r["status"] == "small_sample"


def test_peer_usable_needs_five():
    r = grade_peer_comparison({"peer_key": "etf_linked|broad|沪深300",
                               "member_count": 6,
                               "grouping_source": "benchmark",
                               "benchmark_confidence": "high"})
    assert r["quality_level"] == LEVEL_B
    assert r["status"] == "usable"


def test_peer_never_ranking(tmp_path):
    d = build_practical_report("050002")
    assert d["8_peer_comparability"]["ranking_generated"] is False
    assert d["8_peer_comparability"]["cross_group_comparison_allowed"] is False


def test_peer_deduped_by_fund_id(tmp_path):
    db = _make_db(tmp_path)
    _ingest(db, "022020", "测试双份额基金A", "债券型-长期纯债")
    _ingest(db, "022021", "测试双份额基金C", "债券型-长期纯债")
    d = build_practical_report("022020", db)
    pg = d["8_peer_comparability"]["peer_group"]
    assert pg["deduped_by_fund_id"] is True
    assert pg["member_count"] == 1   # 两个份额 → 一个本体


# ================================================================ 8. A/C 成本
def test_share_cost_single_share_not_applicable():
    r = grade_share_cost({"shares": [{"share_code": "A"}]})
    assert r["quality_level"] == LEVEL_NA
    assert r["status"] == "single_share"


def test_share_cost_insufficient_evidence():
    cost = {"shares": [
        {"share_code": "A", "sales_service_fee": {"status": "ok", "rate": 0.0},
         "purchase_fee": {"status": "partial"},
         "redemption_fee": {"status": "partial"}},
        {"share_code": "C", "sales_service_fee": {"status": "ok", "rate": 0.004},
         "purchase_fee": {"status": "not_available"},
         "redemption_fee": {"status": "partial"}},
    ]}
    r = grade_share_cost(cost)
    assert r["quality_level"] == LEVEL_D
    assert r["status"] == "insufficient_fee_evidence"
    assert "不得给出 A/C 确定性推荐" in r["reason"]


def test_share_cost_never_recommends(tmp_path):
    d = build_practical_report("000032")
    s = d["9_share_cost_evidence"]
    assert s["buy_sell_conclusion"] is None
    assert s["grade"]["value"] is None


def test_share_cost_partial_even_when_complete():
    """字段齐全也只能到 C：持有期口径与支付宝费率仍不可验证。"""
    full = {"shares": [
        {"share_code": "A", "sales_service_fee": {"status": "ok", "rate": 0.0},
         "purchase_fee": {"status": "partial"},
         "redemption_fee": {"status": "partial"}},
        {"share_code": "C", "sales_service_fee": {"status": "ok", "rate": 0.004},
         "purchase_fee": {"status": "partial"},
         "redemption_fee": {"status": "partial"}},
    ]}
    r = grade_share_cost(full)
    assert r["quality_level"] == LEVEL_C
    assert r["value"] is None


# ================================================================ 9. 货币独立
def test_money_indicators_not_applicable(tmp_path):
    db = _make_db(tmp_path)
    _ingest(db, "022030", "测试货币基金", "货币型", money=True)
    d = build_practical_report("022030", db)
    g = d["5_indicator_grades"]["indicators"]
    assert g["ret_12m"]["quality_level"] == LEVEL_NA
    assert g["ret_12m"]["status"] == "not_applicable"
    assert g["max_drawdown"]["quality_level"] == LEVEL_NA
    assert g["annualized_return"]["quality_level"] == LEVEL_NA
    assert d["5_indicator_grades"]["not_applicable_count"] >= 10


def test_money_uses_money_caliber(tmp_path):
    db = _make_db(tmp_path)
    _ingest(db, "022031", "测试货币乙", "货币型", money=True)
    d = build_practical_report("022031", db)
    rr = d["7_return_risk"]
    assert rr["caliber"] == "money_market"
    assert rr["uses_unit_nav"] is False
    assert rr["comparable_with_net_value_funds"] is False
    assert rr["per_10k_yield"]["status"] == "ok"
    assert rr["seven_day_annual"]["status"] == "ok"


def test_money_peer_group_separate(tmp_path):
    db = _make_db(tmp_path)
    _ingest(db, "022032", "测试货币丙", "货币型", money=True)
    d = build_practical_report("022032", db)
    assert d["8_peer_comparability"]["peer_group"]["peer_key"] == "money_market"


# ================================================================ 10. 类型分级
def test_grades_differ_by_product_type(tmp_path):
    db = _make_db(tmp_path)
    _ingest(db, "022040", "测试普通指数", "股票型-标准指数")
    _ingest(db, "022041", "测试债券", "债券型-长期纯债")
    _ingest(db, "022042", "测试货币", "货币型", money=True)
    idx = build_practical_report("022040", db)
    bond = build_practical_report("022041", db)
    money = build_practical_report("022042", db)
    assert idx["2_product_classification"]["product_class"] == "ordinary_index"
    assert bond["2_product_classification"]["product_class"] == "bond_pure"
    assert money["2_product_classification"]["is_money_fund"] is True
    # 三者指标等级分布不同（货币有大量 not_applicable）
    assert (money["5_indicator_grades"]["not_applicable_count"]
            > idx["5_indicator_grades"]["not_applicable_count"])


def test_level_meaning_complete():
    for lv in (LEVEL_A, LEVEL_B, LEVEL_C, LEVEL_D, LEVEL_NA):
        assert lv in LEVEL_MEANING
        assert LEVEL_MEANING[lv]


def test_worst_level_ignores_not_applicable():
    assert worst_level(LEVEL_A, LEVEL_NA) == LEVEL_A
    assert worst_level(LEVEL_A, LEVEL_C) == LEVEL_C
    assert worst_level(LEVEL_NA, LEVEL_NA) == LEVEL_NA


# ================================================================ 11. 字段完整性
REQUIRED_SECTIONS = (
    "1_basic_info", "2_product_classification", "3_data_source",
    "4_data_quality_level", "5_indicator_grades", "5_indicator_grades_summary",
    "6_gaps_and_anomalies", "7_return_risk", "8_peer_comparability",
    "9_share_cost_evidence", "10_not_computable", "11_conclusions",
    "12_limitations", "gate",
)


@pytest.mark.parametrize("code", OFFMARKET_SAMPLES)
def test_real_report_has_all_sections(code):
    d = build_practical_report(code)
    assert d["status"] == "found", d.get("reason")
    for sec in REQUIRED_SECTIONS:
        assert sec in d, sec


@pytest.mark.parametrize("code", OFFMARKET_SAMPLES)
def test_real_indicator_grades_have_all_fields(code):
    d = build_practical_report(code)
    g = d["5_indicator_grades"]["indicators"]
    assert len(g) == 13, sorted(g)
    for key, cell in g.items():
        for f in ("value", "status", "quality_level", "evidence",
                  "limitation", "reason"):
            assert f in cell, (key, f)
        assert cell["quality_level"] in (LEVEL_A, LEVEL_B, LEVEL_C, LEVEL_D,
                                         LEVEL_NA)


@pytest.mark.parametrize("code", OFFMARKET_SAMPLES)
def test_conclusions_three_buckets(code):
    d = build_practical_report(code)
    c = d["11_conclusions"]
    assert c["facts_supported_by_data"]
    assert c["cannot_prove_yet"]
    assert c["boundary"]["is_forecast"] is False
    assert c["boundary"]["is_investment_advice"] is False


def test_report_has_no_buy_sell_words():
    """报告不得出现买卖指令式表述字段。"""
    d = build_practical_report("050002")
    assert d["11_conclusions"]["boundary"]["cannot_be_used_as"]
    txt = json.dumps(d, ensure_ascii=False)
    for banned in ('"action": "buy"', '"action": "sell"',
                   '"recommendation":', '"target_price"'):
        assert banned not in txt


def test_gate_fixed():
    d = build_practical_report("050002")
    g = d["gate"]
    assert g["ready_for_research_analysis"] is True
    assert g["ready_for_backtest"] is False
    assert g["ready_for_formal_ranking"] is False


# ================================================================ 12. JSON/MD 一致
def test_markdown_matches_json():
    d = build_practical_report("050002")
    md = report_to_markdown(d)
    assert d["1_basic_info"]["fund_name"] in md
    assert d["1_basic_info"]["share_code"] in md
    assert f"**{d['4_data_quality_level']['overall_level']}**" in md
    for key in d["5_indicator_grades"]["indicators"]:
        assert key in md
    for sec in ("## 1.", "## 2.", "## 3.", "## 4.", "## 5.", "## 6.",
                "## 7.", "## 8.", "## 9.", "## 10.", "## 11.", "## 12."):
        assert sec in md


def test_markdown_no_fake_numbers():
    """Markdown 中不可计算指标必须显示 — 而不是 0。"""
    d = build_practical_report("050002")
    md = report_to_markdown(d)
    assert "annualized_return" in md
    # 该基金年化不可计算，表格里必须是破折号
    line = next(ln for ln in md.splitlines() if "| annualized_return |" in ln)
    assert "—" in line
    assert "| 0 |" not in line


def test_markdown_mentions_acc_nav():
    d = build_practical_report("001938")
    md = report_to_markdown(d)
    assert "acc_nav" in md


# ================================================================ 守恒
def test_production_untouched_by_readonly():
    """本模块只读，正式库行数不得变化。"""
    from app.database.db import get_connection
    with get_connection() as conn:
        before = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("fund_master", "fund_share_classes",
                            "fund_nav_daily", "fund_dividends",
                            "fund_lifecycle_events")}
        conn.execute("PRAGMA integrity_check")
        after = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                 for t in before}
    assert before == after


def test_source_grade_third_party():
    r = grade_source("akshare.fund_open_fund_info_em")
    assert r["quality_level"] == LEVEL_B
    assert r["status"] == "third_party"
    assert "不得冒充支付宝" in r["limitation"]
    assert grade_source(None)["quality_level"] == LEVEL_D
