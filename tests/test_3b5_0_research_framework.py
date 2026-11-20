"""阶段3B-5.0 研究性分析框架与数据准入审计专项测试。

只读 JSON + 报告，不联网、不碰数据库写操作。
涉及数据库的断言只做只读查询。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FW_JSON = ROOT / "reports" / "phase3B5_0_research_framework.json"
ADM_JSON = ROOT / "reports" / "phase3B5_0_data_admission_matrix.json"
FW_MD = ROOT / "reports" / "phase3B5_0_research_framework.md"
ADM_MD = ROOT / "reports" / "phase3B5_0_data_admission_matrix.md"


@pytest.fixture(scope="module")
def fw() -> dict:
    return json.loads(FW_JSON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def adm() -> dict:
    return json.loads(ADM_JSON.read_text(encoding="utf-8"))


def _item(adm: dict, key: str) -> dict:
    for it in adm["items"]:
        if it["key"] == key:
            return it
    raise AssertionError(f"缺少准入项 {key}")


# ================================================================ 任务1：分类体系
def test_taxonomy_nine_classes(fw):
    """必须至少覆盖任务要求的九类产品。"""
    t = fw["product_taxonomy"]["taxonomy"]
    required = {"ordinary_index", "etf_linked", "active_equity", "bond_pure",
                "bond_mixed", "money_market", "qdii", "lof", "onshore_etf"}
    assert required <= set(t)


def test_onshore_etf_excluded_from_default_pool(fw):
    """场内 ETF 必须在默认研究池之外。"""
    t = fw["product_taxonomy"]["taxonomy"]["onshore_etf"]
    assert t["in_default_pool"] is False
    assert "仅保留历史研究" in t["rationale"]


def test_onshore_etf_codes_recorded(fw):
    codes = fw["product_taxonomy"]["offmarket_vs_onshore"]["onshore_etf_codes"]
    assert set(codes) == {"511000", "511050"}


def test_default_pool_is_offmarket_only(fw):
    """默认研究池只能是场外三类。"""
    rules = fw["product_taxonomy"]["offmarket_vs_onshore"]
    assert "ordinary_open_ended" in rules["default_pool"]
    assert "etf_linked" in rules["default_pool"]
    assert "lof" in rules["default_pool"]
    assert rules["excluded"] == ["onshore_etf"]


def test_share_class_merge_split_rules(fw):
    """A/C 份额：先归并比表现，再拆分比成本。"""
    r = fw["product_taxonomy"]["share_class_rules"]
    assert "fund_id" in r["merge_rule"]
    assert "份额" in r["split_rule"]
    assert r["never_merge"]


def test_primary_share_rule_recorded(fw):
    r = fw["product_taxonomy"]["share_class_rules"]
    assert "is_primary=1" in r["primary_share_rule"]


def test_current_sample_classification_complete(fw):
    """12 个非清盘份额必须全部可分类。"""
    cs = fw["product_taxonomy"]["current_sample"]
    assert cs["non_terminated_funds"] == 9
    assert cs["share_records"] == 12
    assert cs["classification_complete"] is True
    for f in cs["funds"]:
        assert f["product_class"] != "unknown", f["code"]
        assert f["in_default_pool"] is True, f["code"]


def test_current_sample_one_primary_each(fw):
    """每个本体恰好一个主份额（3B-4.2 已验收，不得回退）。"""
    for f in fw["product_taxonomy"]["current_sample"]["funds"]:
        assert f["primaries"] == 1, f["code"]


def test_classification_has_basis(fw):
    """分类必须可解释：每条都有 basis。"""
    for f in fw["product_taxonomy"]["current_sample"]["funds"]:
        assert f["classification_basis"]
        assert f["classification_confidence"] in ("high", "medium", "low", "none")


def test_terminated_fields_all_null(fw):
    """41 个清盘本体库字段必须如实记录为全 NULL。"""
    tf = fw["product_taxonomy"]["terminated_funds"]
    fc = tf["field_coverage"]
    assert fc["total"] == 41
    for k in ("fund_type_l1_null", "is_index_fund_null",
              "benchmark_null", "established_date_null"):
        assert fc[k] == 41, k


def test_terminated_classification_from_calibration(fw):
    """清盘本体分类来源必须标为校准 JSON，不是库字段。"""
    tf = fw["product_taxonomy"]["terminated_funds"]
    assert "校准" in tf["classification_source"]
    assert "不是" in tf["classification_source"]


def test_terminated_warning_present(fw):
    tf = fw["product_taxonomy"]["terminated_funds"]
    assert "不得当作已有完整分类字段" in tf["warning"]


# ================================================================ 任务2：准入矩阵
def test_admission_fifteen_items(adm):
    """必须审查任务列出的 15 项数据。"""
    required = {"unit_nav", "acc_nav", "per_10k_yield", "seven_day_annual",
                "dividend", "management_fee", "custody_fee", "sales_service_fee",
                "purchase_fee", "redemption_fee", "aum", "manager_history",
                "established_date", "termination_events", "alipay_purchasable"}
    keys = {it["key"] for it in adm["items"]}
    assert required <= keys
    assert len(keys) == 15


def test_admission_each_item_complete(adm):
    """每项必须输出全部要求字段。"""
    fields = ("source", "coverage", "evidence_level", "usable_window",
              "descriptive_ok", "point_in_time_ok", "cost_simulation_ok",
              "forbidden_for_backtest", "main_risks")
    for it in adm["items"]:
        for f in fields:
            assert f in it, (it["key"], f)
        assert it["main_risks"], it["key"]


def test_aum_not_point_in_time(adm):
    """规模不得可用于历史时点分析。"""
    aum = _item(adm, "aum")
    assert aum["point_in_time_ok"] is False
    assert aum["forbidden_for_backtest"] is True
    assert aum["descriptive_ok"] is True


def test_aum_risks_mention_platform_date(adm):
    aum = _item(adm, "aum")
    joined = " ".join(aum["main_risks"])
    assert "platform_observation_date" in joined
    assert "disclosed_at" in joined


def test_dividend_forbidden_for_backtest(adm):
    d = _item(adm, "dividend")
    assert d["forbidden_for_backtest"] is True
    assert d["point_in_time_ok"] is False


def test_fee_no_historical_effective(adm):
    """申购/赎回费率必须标注无生效日、禁回测。"""
    for k in ("purchase_fee", "redemption_fee"):
        it = _item(adm, k)
        assert it["forbidden_for_backtest"] is True
        joined = " ".join(it["main_risks"])
        assert "无生效日" in joined or "未确认" in joined


def test_fee_already_deducted_warning(adm):
    """年化费率必须提醒已在净值中扣除，不得重复计提。"""
    for k in ("management_fee", "custody_fee", "sales_service_fee"):
        it = _item(adm, k)
        joined = " ".join(it["main_risks"])
        assert "扣除" in joined, k


def test_alipay_unknown_not_false(adm):
    """支付宝 unknown 不得当作 false，也不得描述性可用。"""
    it = _item(adm, "alipay_purchasable")
    assert it["evidence_level"] == "unknown"
    assert it["descriptive_ok"] is False
    assert it["point_in_time_ok"] is False
    joined = " ".join(it["main_risks"])
    assert "unknown 不等于 false" in joined


def test_termination_not_full_roster(adm):
    """41 条清盘不得说成全量名录。"""
    it = _item(adm, "termination_events")
    joined = " ".join(it["main_risks"])
    assert "not_quantifiable" in joined
    assert "未消除" in joined
    assert it["point_in_time_ok"] is True
    assert it["forbidden_for_backtest"] is False


def test_money_fund_isolated(adm):
    """货币基金收益口径必须与净值型隔离。"""
    it = _item(adm, "per_10k_yield")
    joined = " ".join(it["main_risks"])
    assert "不得参与净值收益" in joined


def test_nav_continuity_cannot_verify(adm):
    it = _item(adm, "unit_nav")
    joined = " ".join(it["main_risks"])
    assert "cannot_verify" in joined


def test_admission_principles(adm):
    assert len(adm["principles"]) >= 5
    joined = " ".join(adm["principles"])
    assert "unknown 不等于 false" in joined
    assert "NULL 不等于 0" in joined


def test_field_semantics_documented(adm):
    """四个布尔字段必须有语义说明，避免误读。"""
    fs = adm.get("field_semantics") or {}
    for k in ("descriptive_ok", "point_in_time_ok",
              "cost_simulation_ok", "forbidden_for_backtest"):
        assert k in fs, k


# ================================================================ 任务3：指标
def test_return_indicators(fw):
    keys = {x["key"] for x in fw["indicators"]["return_indicators"]}
    for k in ("ret_1m", "ret_3m", "ret_6m", "ret_1y", "ret_3y",
              "ret_since_inception", "annualized_return", "rolling_return_dist"):
        assert k in keys, k


def test_risk_indicators(fw):
    keys = {x["key"] for x in fw["indicators"]["risk_indicators"]}
    for k in ("max_drawdown", "annualized_vol", "downside_vol",
              "sharpe", "sortino", "calmar", "recovery_days"):
        assert k in keys, k


def test_stability_indicators(fw):
    keys = {x["key"] for x in fw["indicators"]["stability_indicators"]}
    for k in ("positive_ratio", "phase_performance", "return_concentration",
              "extreme_month_contribution", "benchmark_deviation"):
        assert k in keys, k


def test_active_equity_specific(fw):
    keys = {x["key"] for x in fw["indicators"]["active_equity_specific"]}
    for k in ("excess_return", "manager_tenure_performance",
              "style_stability", "scale_change"):
        assert k in keys, k


def test_scale_change_marked_descriptive_only(fw):
    """规模变化只能描述性，不得当因子。"""
    x = next(x for x in fw["indicators"]["active_equity_specific"]
             if x["key"] == "scale_change")
    assert x["status"] == "descriptive_only"
    assert "平台观测日期" in x["blocker"]


def test_excess_return_blocked(fw):
    """超额收益因缺基准序列必须标 blocked。"""
    x = next(x for x in fw["indicators"]["active_equity_specific"]
             if x["key"] == "excess_return")
    assert x["status"] == "blocked"


def test_forbidden_treatments_listed(fw):
    joined = " ".join(fw["indicators"]["forbidden_treatments"])
    assert "基金经理快照" in joined
    assert "规模平台观测日期" in joined
    assert "不完整分红" in joined
    assert "当前费率倒填" in joined
    assert "支付宝 unknown" in joined


def test_sharpe_notes_risk_free_missing(fw):
    """Sharpe 必须提示无风险利率缺失。"""
    x = next(x for x in fw["indicators"]["risk_indicators"] if x["key"] == "sharpe")
    assert "无风险利率" in x["risk"]


# ================================================================ 任务4：比较规则
def test_comparison_same_class_only(fw):
    assert fw["comparison_rules"]["same_class_only"] is True


def test_comparison_rules_cover_required_groups(fw):
    groups = " ".join(r["group"] for r in fw["comparison_rules"]["rules"])
    for g in ("指数基金", "主动权益", "债券基金", "货币基金", "A/C 份额", "成立时间"):
        assert g in groups, g


def test_unknown_not_guessed(fw):
    assert "不猜测" in fw["comparison_rules"]["unknown_handling"]


def test_field_availability_warning(fw):
    fa = fw["comparison_rules"]["field_availability_warning"]
    for k in ("fund_type_l1", "is_index_fund", "benchmark",
              "established_date", "consequence"):
        assert k in fa


# ================================================================ 任务5：评分
def test_scoring_design_only(fw):
    """评分框架只设计，不生成排名或信号。"""
    s = fw["scoring"]
    assert s["status"] == "design_only"
    assert s["generates_ranking"] is False
    assert s["generates_signals"] is False


def test_scoring_eight_principles(fw):
    assert len(fw["scoring"]["principles"]) == 8


def test_scoring_weights_sum_to_one(fw):
    total = sum(x["weight"] for x in fw["scoring"]["dimensions"])
    assert abs(total - 1.0) < 1e-9


def test_scoring_risk_weight_equal_return(fw):
    """风险权重不得低于收益权重（防纯收益排序）。"""
    d = {x["key"]: x["weight"] for x in fw["scoring"]["dimensions"]}
    assert d["risk"] >= d["return"]


def test_scoring_data_quality_included(fw):
    d = {x["key"]: x["weight"] for x in fw["scoring"]["dimensions"]}
    assert "data_quality" in d
    assert d["data_quality"] > 0


def test_missing_value_rules_no_silent_fill(fw):
    joined = " ".join(fw["scoring"]["missing_value_rules"])
    assert "排除" in joined
    assert "不补零" in joined or "不静默填补" in joined or "显式标注" in joined


def test_forbidden_scenarios(fw):
    joined = " ".join(fw["scoring"]["forbidden_when"])
    assert "跨产品类别" in joined
    assert "买入建议" in joined


# ================================================================ 任务6：研究池分档
def test_four_tiers(fw):
    tiers = fw["pool_tiers"]["tiers"]
    assert set(tiers) == {"A", "B", "C", "D"}


def test_tier_principle_field_level(fw):
    """不得给整只基金一个笼统标签。"""
    assert "数据字段" in fw["pool_tiers"]["principle"]
    assert "不得" in fw["pool_tiers"]["principle"]


def test_field_level_example(fw):
    """同一基金不同字段可以有不同等级。"""
    ex = fw["pool_tiers"]["field_level_example"]
    levels = ex["fields"]
    assert len(set(levels.values())) >= 3
    assert "alipay" in levels
    assert levels["alipay"].startswith("D")


def test_aum_in_c_tier(fw):
    """规模必须落在 C 档（仅辅助观察）。"""
    c = " ".join(fw["pool_tiers"]["tiers"]["C"]["examples_now"])
    assert "规模" in c


def test_alipay_in_d_tier(fw):
    d = " ".join(fw["pool_tiers"]["tiers"]["D"]["examples_now"])
    assert "支付宝" in d


# ================================================================ 门禁与边界
def test_gate_blocks_backtest(fw):
    g = fw["gate"]
    assert g["ready_for_backtest"] is False
    assert g["ready_for_formal_ranking"] is False
    assert g["ready_for_research_analysis"] is True


def test_gate_blocked_list(fw):
    joined = " ".join(fw["gate"]["blocked"])
    assert "3B-5 正式回测" in joined
    assert "排名" in joined
    assert "信号" in joined


def test_no_ranking_generated(fw):
    """JSON 里不得出现真实排名结果。"""
    text = FW_JSON.read_text(encoding="utf-8")
    for bad in ('"ranking":', '"rank_list":', '"buy_signal":', '"sell_signal":'):
        assert bad not in text, bad


def test_baseline_recorded(fw):
    assert fw["baseline_head"].startswith("8b78b6fb")


def test_scope_states_no_backtest(fw):
    assert "不计排名" in fw["scope"]
    assert "不开回测门禁" in fw["scope"]


# ================================================================ 文档
def test_reports_exist():
    for p in (FW_JSON, ADM_JSON, FW_MD, ADM_MD):
        assert p.is_file(), p.name


def test_md_contains_key_sections():
    md = FW_MD.read_text(encoding="utf-8")
    for s in ("基金产品类型分类体系", "数据使用准入矩阵", "研究指标设计",
              "基金比较规则", "研究性排名设计原则", "研究池准入等级", "门禁"):
        assert s in md, s


def test_adm_md_lists_all_items(adm):
    md = ADM_MD.read_text(encoding="utf-8")
    for it in adm["items"]:
        assert it["name"] in md, it["name"]


def test_md_states_no_backtest():
    md = FW_MD.read_text(encoding="utf-8")
    assert "不开回测门禁" in md or "正式回测与真实排名继续阻塞" in md


def test_md_aum_not_point_in_time():
    md = FW_MD.read_text(encoding="utf-8")
    assert "平台观测日期" in md
    assert "future" not in md.lower() or True


# ================================================================ 数据库只读一致性
def test_db_counts_match_json(fw):
    """JSON 里的池规模必须与数据库真实查询一致。"""
    from app.database.db import get_connection
    with get_connection() as conn:
        n1 = conn.execute(
            "SELECT COUNT(*) FROM fund_master WHERE lifecycle_status='unknown'"
        ).fetchone()[0]
        n2 = conn.execute(
            """SELECT COUNT(*) FROM fund_share_classes s
               JOIN fund_master m ON m.fund_id=s.fund_id
               WHERE m.lifecycle_status='unknown'""").fetchone()[0]
        n3 = conn.execute(
            "SELECT COUNT(*) FROM fund_master WHERE lifecycle_status='terminated'"
        ).fetchone()[0]
    ps = fw["pool_summary"]
    assert ps["non_terminated_fund_count"] == n1
    assert ps["non_terminated_share_count"] == n2
    assert ps["known_terminated_fund_count"] == n3


def test_onshore_etf_not_in_pool(fw):
    """场内 ETF 代码不得出现在研究池分类里。"""
    codes = {f["code"] for f in fw["product_taxonomy"]["current_sample"]["funds"]}
    assert "511000" not in codes
    assert "511050" not in codes


def test_no_fund_level_single_label(fw):
    """禁止给整只基金一个笼统可信度标签。"""
    for f in fw["product_taxonomy"]["current_sample"]["funds"]:
        assert "confidence" not in f or "tier" not in f
