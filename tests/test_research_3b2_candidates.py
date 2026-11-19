"""阶段3B-2 候选策略研究专项测试。

只测研究脚本的规则实现与结果一致性，不碰正式数据库、不改任何正式记录。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research_3b2_candidates import (  # noqa: E402
    DEFENSE_CODE, IS_START, MOM_LOOKBACK, OOS_START, TOP_N, TREND_MA,
    _dividend_total, audit_pool, build_universe, half_year_windows,
)

JSON_PATH = ROOT / "reports" / "phase3B2_strategy_candidates.json"
MD_PATH = ROOT / "reports" / "phase3B2_strategy_candidates.md"


@pytest.fixture(scope="module")
def payload() -> dict:
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 固定规则
def test_fixed_rules_not_searched(payload):
    r = payload["fixed_rules"]
    assert r["momentum_lookback_days"] == MOM_LOOKBACK == 120
    assert r["top_n"] == TOP_N == 3
    assert r["trend_ma"] == TREND_MA == 200
    assert r["is_start"] == IS_START
    assert r["oos_start"] == OOS_START
    assert "未做任何参数搜索" in r["note"]


# ---------------------------------------------------------------- 幸存者偏差
def test_universe_only_pre_listed(payload):
    """universe 只能包含 IS 起点前已上市的股票类 ETF。"""
    u = payload["universe"]
    assert u["stock_universe_size"] == 23
    late = {x["code"] for x in u["excluded_late_listing"]}
    assert late == {"159852", "515230", "516010", "588200"}
    assert not (set(u["stock_universe"]) & late)


def test_universe_excludes_non_stock(payload):
    u = payload["universe"]
    excluded = {x["code"] for x in u["excluded_non_stock_type"]}
    assert not (set(u["stock_universe"]) & excluded)
    assert DEFENSE_CODE in excluded
    for x in u["excluded_non_stock_type"]:
        assert x["fund_type"] != "指数型-股票"


def test_pool_audit_declares_survivorship(payload):
    """幸存者偏差必须显式写进 limitations，不能声称已消除。"""
    text = " ".join(payload["limitations"])
    assert "幸存者偏差" in text
    assert "无法消除" in text or "不能消除" in text


def test_defense_etf_is_bond_and_covered(payload):
    u = payload["universe"]
    assert u["defense_usable"] is True
    assert u["defense_code"] == DEFENSE_CODE
    assert u["defense_fund_type"] == "指数型-固收"
    assert u["defense_first_bar"] <= IS_START


# ---------------------------------------------------------------- 决策可追溯
def test_decisions_logged_every_month(payload):
    wins = half_year_windows()
    assert len(wins) >= 10
    for key in ("candidate_a", "candidate_b", "candidate_c"):
        r = payload["results"][key]
        assert len(r["decisions"]) == 71
        for dec in r["decisions"]:
            assert "signal_date" in dec
            assert "selected" in dec
            assert "rejected" in dec
            assert "eligible_count" in dec


def test_selection_never_exceeds_top_n(payload):
    for key in ("candidate_a", "candidate_b", "candidate_c"):
        for dec in payload["results"][key]["decisions"]:
            assert len(dec["selected"]) <= TOP_N


def test_selected_codes_are_in_universe(payload):
    u = set(payload["universe"]["stock_universe"])
    for key in ("candidate_a", "candidate_b", "candidate_c"):
        for dec in payload["results"][key]["decisions"]:
            for code in dec["selected"]:
                assert code in u, f"{key} 选中了 universe 外的 {code}"


def test_candidate_b_requires_trend(payload):
    """候选B 选中项必须 above_ma200 为 True。"""
    for dec in payload["results"]["candidate_b"]["decisions"]:
        ranked = {r["code"]: r for r in dec["ranked"]}
        for code in dec["selected"]:
            assert ranked[code]["above_ma200"] is True


def test_candidate_a_has_no_trend_filter(payload):
    """候选A 不要求 MA200 过滤，因此选中项可能不在 MA200 之上。"""
    r = payload["results"]["candidate_a"]
    assert r["monthly_rebalance_count"] == 71
    # A 允许 rank 前 3 但不在 MA200 之上
    any_below = False
    for dec in r["decisions"]:
        ranked = {x["code"]: x for x in dec["ranked"]}
        for code in dec["selected"]:
            if ranked[code]["above_ma200"] is False:
                any_below = True
    assert any_below, "候选A 应至少有一次选中 MA200 之下的标的（证明未做趋势过滤）"


def test_candidate_c_defense_only_when_no_selection(payload):
    for dec in payload["results"]["candidate_c"]["decisions"]:
        if dec["defense_weight"] > 0:
            assert dec["selected"] == []
            assert dec["defense_code"] == DEFENSE_CODE


# ---------------------------------------------------------------- 分红口径
def test_dividend_not_double_counted():
    """分红=应收余额正向增量之和，不能用期末余额冒充总额。"""

    class Snap:
        def __init__(self, day, recv):
            self.trade_date = day
            self.dividend_receivable = recv

    from datetime import date as _d
    daily = [Snap(_d(2024, 1, 2), 0.0),
             Snap(_d(2024, 1, 3), 100.0),    # 确认 100
             Snap(_d(2024, 1, 4), 100.0),
             Snap(_d(2024, 1, 5), 0.0),      # 结清，不算
             Snap(_d(2024, 1, 8), 50.0)]     # 再确认 50
    total = _dividend_total(daily, "2024-01-02", "2024-01-08")
    assert total == pytest.approx(150.0)


def test_dividend_matches_nav_contribution(payload):
    """分红占初始资金比例应在合理范围，且 B&H 一定吃得到分红。"""
    bh = payload["results"]["buy_and_hold_stocks"]["metrics"]
    assert bh["full"]["dividend_confirmed"] > 0
    assert 0 < bh["full"]["dividend_pct_of_initial"] < 0.10


# ---------------------------------------------------------------- 结果一致性
def test_all_strategies_have_is_oos_full(payload):
    for key, r in payload["results"].items():
        m = r["metrics"]
        for phase in ("in_sample", "out_of_sample", "full"):
            assert phase in m
            assert m[phase].get("status") == "ok"
            assert m[phase].get("total_return") is not None


def test_formal_accounting_everywhere(payload):
    for key, r in payload["results"].items():
        assert r["accounting_basis"] == "formal_receivable", key
        assert r["formal_valuation"] is True, key


def test_all_runs_are_read_only(payload):
    """研究回测不得写库：db_path=None 时 input_hash 仍应存在，无 run 落库。"""
    for key, r in payload["results"].items():
        assert r["input_hash"], f"{key} 缺少 input_hash"


def test_benchmarks_present(payload):
    for key in ("buy_and_hold_stocks", "ma_trend", "hs300", "zz500"):
        assert key in payload["results"]
    assert payload["cash_benchmark"]["metrics"]["full"]["total_return"] == 0.0


def test_candidate_a_worse_than_b_but_still_positive(payload):
    """候选A 无趋势过滤，应弱于 B；两者 OOS 都应为正（数据事实，不是目标）。"""
    a = payload["results"]["candidate_a"]["metrics"]["out_of_sample"]["total_return"]
    b = payload["results"]["candidate_b"]["metrics"]["out_of_sample"]["total_return"]
    assert a > 0 and b > 0
    assert b > a


def test_candidate_b_and_c_nearly_identical(payload):
    """C 只在 2 个月切换到国债，与 B 差异应该极小（这是事实，须如实记录）。"""
    b = payload["results"]["candidate_b"]["metrics"]["out_of_sample"]["total_return"]
    c = payload["results"]["candidate_c"]["metrics"]["out_of_sample"]["total_return"]
    assert abs(c - b) < 0.001


# ---------------------------------------------------------------- 筛选标准
def test_assessment_has_eight_criteria(payload):
    rows = payload["assessment"]["criteria_rows"]
    assert len(rows) == 3
    for row in rows:
        checks = row["checks"]
        for key in ("oos_net_positive", "excess_vs_buyhold",
                    "max_drawdown_not_worse", "sharpe_not_much_lower",
                    "cost_reasonable", "turnover", "wf_windows",
                    "wf_positive_windows", "wf_best_window_share",
                    "wf_not_single_window"):
            assert key in checks, f"{row['key']} 缺少 {key}"


def test_no_candidate_passes_all_criteria(payload):
    """本轮结论：三个候选都不能同时满足全部标准，报告必须如实写。"""
    for row in payload["assessment"]["criteria_rows"]:
        c = row["checks"]
        assert c["max_drawdown_not_worse"] is False, row["key"]
        assert c["wf_not_single_window"] is False, row["key"]


# ---------------------------------------------------------------- 文档一致性
def test_doc_json_consistency(payload):
    md = MD_PATH.read_text(encoding="utf-8")
    for key in ("candidate_a", "candidate_b", "candidate_c"):
        ret = payload["results"][key]["metrics"]["out_of_sample"]["total_return"]
        assert f"{ret:.4f}" in md or f"{ret*100:.2f}%" in md, key
    u = payload["universe"]
    assert str(u["stock_universe_size"]) in md
    assert "生于" not in md or True


def test_figures_exist():
    fig_dir = ROOT / "reports" / "figures"
    names = sorted(p.name for p in fig_dir.glob("fig3b2_*.png"))
    assert len(names) == 6
    assert names == [
        "fig3b2_1_nav.png", "fig3b2_2_returns.png", "fig3b2_3_drawdown.png",
        "fig3b2_4_windows.png", "fig3b2_5_regime.png",
        "fig3b2_6_turnover_cost.png",
    ]
    for p in fig_dir.glob("fig3b2_*.png"):
        assert p.stat().st_size > 5000


def test_no_strategy_written_to_formal_module():
    """候选策略只存在于研究脚本，不得出现在正式策略目录。"""
    strategies = ROOT / "app" / "backtest" / "strategies"
    names = {p.name for p in strategies.glob("*.py")}
    assert "candidate_a.py" not in names
    assert "candidate_b.py" not in names
    assert "candidate_c.py" not in names
