"""阶段3B-6.2.1 基准分类体系专项测试。

**直接调用真实分类/解析逻辑**（`classify_fund` / `parse_benchmark_text` /
`assess_benchmark_usability`），不读取预计算 JSON 做自我验证。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.benchmark_taxonomy_3b6_2_1 import (  # noqa: E402
    BENCHMARK_KINDS, CATEGORY_BENCHMARK_RULES, COMPONENT_TYPES,
    REQUIRED_CATEGORIES, RETURN_BASES, assess_benchmark_usability,
    classify_fund, get_category_rules, parse_benchmark_text)

REPORTS = ROOT / "reports"
AUDIT = REPORTS / "phase3B6_2_1_mapping_audit.json"
AVAILABLE = {"000300", "000905", "000906", "000016", "399997",
              "H30184", "000942", "000012", "000922", "930930"}


# ============================================================ 三类基准边界
def test_three_benchmark_kinds_defined():
    assert set(BENCHMARK_KINDS) == {"contract", "research", "substitute"}
    for k, v in BENCHMARK_KINDS.items():
        assert v["can_be_promoted_to"] is None, f"{k} 不得被升级"


def test_contract_requires_l1():
    assert BENCHMARK_KINDS["contract"]["required_evidence_grade"] == "L1"


def test_contract_not_usable_with_l3_only():
    """L3 第三方文本不得成为合同基准。"""
    parsed = parse_benchmark_text("沪深300指数收益率×95%+活期存款利率(税后)×5%")
    r = assess_benchmark_usability(
        parsed, available_index_codes=AVAILABLE, category="index_plain",
        contract_evidence_grade="L3", has_official_contract_file=False,
        has_historical_weights=False)
    assert r["contract_benchmark_usable"] is False
    assert r["max_kind"] != "contract"
    assert any("未取得基金合同" in x for x in r["reasons"])


def test_contract_not_usable_even_with_l1_if_incomplete():
    """即使有 L1，成分不可算也不能判合同基准可用。"""
    parsed = parse_benchmark_text("中债综合指数收益率×90%+活期存款利率×10%")
    r = assess_benchmark_usability(
        parsed, available_index_codes=AVAILABLE, category="pure_bond",
        contract_evidence_grade="L1", has_official_contract_file=True,
        has_historical_weights=True)
    assert r["contract_benchmark_usable"] is False
    assert r["fully_reproducible"] is False
    assert r["uncomputable_components"]


def test_research_cannot_be_labelled_contract():
    """研究基准的 max_kind 不得是 contract。"""
    parsed = parse_benchmark_text("沪深300指数收益率×95%+活期存款×5%")
    r = assess_benchmark_usability(
        parsed, available_index_codes=AVAILABLE, category="index_plain",
        index_return_basis={"000300": "total_return"},
        contract_evidence_grade="L3",
        research_rule={"rule_version": "v1", "selection_reason": "r",
                        "applicable_category": "index_plain",
                        "divergence_from_contract": "d"})
    assert r["max_kind"] == "research"
    assert any("不得称为合同基准" in x for x in r["reasons"])


def test_substitute_cannot_be_labelled_contract():
    """替代基准 reason 必须声明不得表述为合同基准超额收益。"""
    assert "不得将结果表述为合同基准超额收益" in BENCHMARK_KINDS["substitute"]["note"]


def test_no_auto_promotion_path():
    """任何两类之间都不存在自动升级字段。"""
    for k in BENCHMARK_KINDS:
        assert BENCHMARK_KINDS[k]["can_be_promoted_to"] is None


def test_unavailable_returns_explicit_reason():
    """无可用序列时必须给出明确原因。"""
    parsed = parse_benchmark_text("中证可转换债券指数收益率×80%+活期存款×20%")
    r = assess_benchmark_usability(
        parsed, available_index_codes=AVAILABLE, category="mixed_bond",
        contract_evidence_grade="L3")
    assert r["max_kind"] in ("substitute", "none")
    assert r["reasons"]


# ============================================================ 七个类别
def test_seven_required_categories():
    assert len(REQUIRED_CATEGORIES) == 7
    for c in REQUIRED_CATEGORIES:
        assert c in CATEGORY_BENCHMARK_RULES


def test_money_market_classified():
    r = classify_fund({"fund_name": "天弘余额宝货币", "fund_type_l1": "货币型",
                        "fund_type_l2": "货币型"})
    assert r["required_category"] == "money_market"
    assert r["is_money_market"] is True


def test_etf_feeder_classified():
    r = classify_fund({"fund_name": "华夏沪深300ETF联接",
                        "fund_type_l1": "指数型-股票", "is_index_fund": 1})
    assert r["required_category"] == "etf_feeder"
    assert r["trading_form"] == "etf_feeder"


def test_lof_classified_as_offexchange():
    r = classify_fund({"fund_name": "招商中证白酒指数(LOF)",
                        "fund_type_l1": "指数型-股票", "fund_type_l2": "股票型-标准指数",
                        "is_index_fund": 1})
    assert r["required_category"] == "lof_offexchange"
    assert r["is_lof"] is True


def test_enhanced_index_flagged():
    r = classify_fund({"fund_name": "景顺长城沪深300指数增强",
                        "fund_type_l1": "股票型-增强指数",
                        "fund_type_l2": "股票型-增强指数", "is_index_fund": 1})
    assert r["required_category"] == "index_plain"
    assert r["is_enhanced"] is True


def test_pure_bond_classified():
    r = classify_fund({"fund_name": "华夏纯债债券", "fund_type_l1": "债券型-长债",
                        "fund_type_l2": "债券型-长期纯债"})
    assert r["required_category"] == "pure_bond"


def test_mixed_bond_classified():
    r = classify_fund({"fund_name": "中海可转换债券", "fund_type_l1": "债券型-可转债",
                        "fund_type_l2": "债券型-可转债"})
    assert r["required_category"] == "mixed_bond"


def test_active_equity_classified():
    r = classify_fund({"fund_name": "华夏成长混合", "fund_type_l1": "混合型-偏股",
                        "fund_type_l2": "混合型-偏股"})
    assert r["required_category"] == "active_equity"


def test_degraded_classification_flagged():
    """分类字段全空时必须标记 data_insufficient。"""
    r = classify_fund({"fund_name": "长盛纯债债券型证券投资基金",
                        "fund_full_name": "长盛纯债债券型证券投资基金",
                        "fund_type_l1": None, "fund_type_l2": None})
    assert r["classification_source"] == "name_only_degraded"
    assert r["data_insufficient"] is True
    assert r["classification_confidence"] == "low"


def test_unclassifiable_not_forced():
    """名称也无法判断时不得强行分配类别。"""
    r = classify_fund({"fund_name": "某某集合资产管理计划",
                        "fund_full_name": "某某集合资产管理计划",
                        "fund_type_l1": None, "fund_type_l2": None})
    assert r["required_category"] == "unclassified"


# ============================================================ 收益口径
def test_price_not_total_return():
    assert RETURN_BASES["price"] != RETURN_BASES["total_return"]
    assert "不含分红" in RETURN_BASES["price"]


def test_bond_bases_distinct():
    for a, b in (("full_price", "wealth"), ("net_price", "wealth"),
                  ("full_price", "net_price")):
        assert RETURN_BASES[a] != RETURN_BASES[b]


def test_full_price_not_total_return():
    """全价指数不含再投资，不等于全收益。"""
    assert "不含再投资" in RETURN_BASES["full_price"]
    assert "再投资" in RETURN_BASES["total_return"]


def test_parse_identifies_full_price_bond_index():
    r = parse_benchmark_text("中债-综合全价（总值）指数收益率×90%+沪深300指数收益率×10%")
    bond = [c for c in r["components"] if c["component_type"] == "bond_index"][0]
    assert bond["return_basis"] == "full_price"


def test_parse_identifies_wealth_bond_index():
    r = parse_benchmark_text("中债-综合财富（总值）指数收益率×15%+沪深300指数×85%")
    bond = [c for c in r["components"] if c["component_type"] == "bond_index"][0]
    assert bond["return_basis"] == "wealth"


def test_parse_unknown_bond_basis_flagged():
    r = parse_benchmark_text("中债总指数收益率×100%")
    bond = [c for c in r["components"] if c["component_type"] == "bond_index"][0]
    assert bond["return_basis"] == "unknown"
    assert any("未明说" in n for n in bond["notes"])


# ============================================================ 权重语义
def test_fixed_rate_not_counted_as_cash():
    assert COMPONENT_TYPES["fixed_rate"] != COMPONENT_TYPES["cash"]
    r = parse_benchmark_text("沪深300指数收益率×95%＋1%（指年收益率，评价时应按期间折算）")
    assert r["fixed_rate_count"] == 1
    assert r["cash_count"] == 0


def test_fixed_rate_not_in_asset_weight():
    r = parse_benchmark_text("沪深300指数收益率×95%＋1%（指年收益率，评价时应按期间折算）")
    assert abs(r["asset_weight_sum"] - 0.95) < 1e-9
    assert abs(r["fixed_rate_weight_sum"] - 0.01) < 1e-9


def test_unexplained_residual_not_inferred():
    """未解释的剩余权重必须保留为 residual，不得补成现金。"""
    r = parse_benchmark_text("沪深300指数收益率×95%＋1%（指年收益率，评价时应按期间折算）")
    assert abs(r["unexplained_residual"] - 0.05) < 1e-9
    assert r["cash_count"] == 0, "不得把剩余 5% 推断为现金"
    assert any("不得推断" in n for n in r["notes"])


def test_no_residual_when_weights_complete():
    r = parse_benchmark_text("沪深300指数收益率×95%+活期存款利率(税后)×5%")
    assert r["unexplained_residual"] is None
    assert abs(r["asset_weight_sum"] - 1.0) < 1e-9


def test_unparsed_weight_not_inferred():
    """无法解析权重时不得推断。"""
    r = parse_benchmark_text("中债综合指数")
    assert r["components"][0]["weight"] is None
    assert any("不得推断其权重" in n for n in r["notes"])


# ============================================================ 类别规则
def test_etf_feeder_rule_separates_etf_and_index():
    rules = get_category_rules("etf_feeder")
    joined = " ".join(rules["never"])
    assert "ETF" in joined and "指数" in joined
    assert any("市场价格" in x for x in rules["never"])


def test_lof_rule_rejects_exchange_price():
    rules = get_category_rules("lof_offexchange")
    joined = " ".join(rules["never"])
    assert "场内价格" in joined
    assert "场外" in rules["primary"]


def test_money_market_rule_independent():
    rules = get_category_rules("money_market")
    assert "万份收益" in rules["primary"]
    assert "七日年化" in rules["primary"]
    assert any("普通净值基金" in x for x in rules["never"])


def test_pure_bond_rule_distinguishes_bases():
    rules = get_category_rules("pure_bond")
    joined = " ".join(rules["never"])
    assert "净价" in joined and "全价" in joined and "财富" in joined


def test_mixed_bond_rule_mentions_convertible():
    rules = get_category_rules("mixed_bond")
    assert any("可转债" in x for x in rules["never"])


def test_no_uniform_hs300_rule():
    """不得把所有基金统一映射到沪深300。"""
    for cat in REQUIRED_CATEGORIES:
        rules = get_category_rules(cat)
        primary = rules["primary"]
        if "沪深300" in primary:
            # 允许作为「可比研究指数」举例，但不能是唯一/强制映射
            assert "如" in primary or "可比" in primary, \
                f"{cat} 把沪深300写成了强制主规则：{primary}"
    joined = " ".join(" ".join(get_category_rules(c)["never"])
                       for c in REQUIRED_CATEGORIES)
    assert "不得统一映射到沪深300" in joined


def test_every_category_has_never_and_must_declare():
    for cat in REQUIRED_CATEGORIES:
        rules = get_category_rules(cat)
        assert rules["primary"]
        assert rules["never"]
        assert rules["must_declare"]


def test_unknown_category_raises():
    with pytest.raises(KeyError):
        get_category_rules("not_a_category")


# ============================================================ 真实审计数据
@pytest.fixture(scope="module")
def audit() -> dict:
    assert AUDIT.exists(), "缺映射审计 JSON"
    return json.loads(AUDIT.read_text(encoding="utf-8"))


def test_audit_db_unchanged(audit):
    assert audit["db_unchanged"] is True
    assert audit["db_before"]["db_sha256"] == audit["db_after"]["db_sha256"]


def test_audit_integrity(audit):
    assert audit["integrity_check"] == "ok"
    assert audit["foreign_key_violations"] == 0


def test_audit_120_funds_by_fund_id(audit):
    s = audit["summary"]
    assert s["total_funds_by_fund_id"] == len(audit["funds"]) == 120
    assert s["total_share_classes"] == 149
    assert s["funds_with_multiple_shares"] > 0


def test_ac_shares_merged_by_fund_id(audit):
    """A/C 份额必须按 fund_id 归并，不得重复计数。"""
    ids = [r["fund_id"] for r in audit["funds"]]
    assert len(ids) == len(set(ids)), "存在重复 fund_id"
    multi = [r for r in audit["funds"] if r["share_class_count"] > 1]
    assert multi, "应存在多份额基金"
    for r in multi:
        types = {s["share_class_type"] for s in r["share_classes"]}
        assert len(r["share_classes"]) == r["share_class_count"]


def test_survivorship_declared(audit):
    s = audit["summary"]
    assert "幸存者偏差" in s["survivorship_note"]
    assert s["lifecycle"]["terminated"] == 41
    # 3B-6.2.1.1 修正：unknown 不等于存续
    assert s["lifecycle"]["unknown_status"] == 79
    assert s["lifecycle"]["existing"] == 0


def test_terminated_and_existing_split(audit):
    """生命周期三类互斥：existing / terminated / unknown_status。"""
    term = [r for r in audit["funds"] if r["lifecycle_bucket"] == "terminated"]
    unk = [r for r in audit["funds"] if r["lifecycle_bucket"] == "unknown_status"]
    ex = [r for r in audit["funds"] if r["lifecycle_bucket"] == "existing"]
    assert len(term) == 41
    assert len(unk) == 79
    assert len(ex) == 0
    lc = audit["summary"]["lifecycle"]
    assert lc["terminated"] == len(term)
    assert lc["unknown_status"] == len(unk)
    assert lc["existing"] == len(ex)
    assert len(term) + len(unk) + len(ex) == len(audit["funds"])


def test_category_counts_from_detail(audit):
    from collections import Counter
    recalc = Counter(r["classification"]["required_category"]
                      for r in audit["funds"])
    assert audit["summary"]["category_counts_all"] == dict(recalc)


def test_primary_scope_consistent(audit):
    from collections import Counter
    primary = [r for r in audit["funds"]
               if r["classification"]["classification_source"] == "primary_field"]
    ps = audit["summary"]["primary_scope"]
    assert ps["total_funds"] == len(primary)
    assert ps["has_benchmark_text"] == sum(
        1 for r in primary if r["benchmark_parse"]["raw_text"])
    assert ps["has_index_code"] == sum(
        1 for r in primary
        if any(c["index_code"] for c in r["benchmark_parse"]["components"]))


def test_no_contract_benchmark_usable(audit):
    """全部基准的合同可用性必须为 False（无 L1）。"""
    assert audit["summary"]["contract_benchmark_usable"] == 0
    for r in audit["funds"]:
        assert r["usability"]["contract_benchmark_usable"] is False
        assert r["contract_benchmark"]["has_official_contract_file"] is False
        assert r["contract_benchmark"]["evidence_grade"] == "L3"


def test_no_fully_reproducible(audit):
    assert audit["summary"]["fully_reproducible"] == 0


def test_no_historical_weights(audit):
    """历史权重不得用当前权重回填。"""
    for r in audit["funds"]:
        assert r["contract_benchmark"]["effective_from"] is None
        assert r["contract_benchmark"]["version_count"] == 1
    comp = audit["summary"]["composites"]
    assert comp["components_with_effective_from"] == 0


def test_max_kind_never_contract(audit):
    for r in audit["funds"]:
        assert r["usability"]["max_kind"] in ("research", "substitute", "none")


def test_every_fund_has_reasons_or_usable(audit):
    for r in audit["funds"]:
        if r["usability"]["max_kind"] == "none":
            assert r["usability"]["reasons"], \
                f"{r['fund_code']} 无可用基准却无原因"


def test_money_market_special_note(audit):
    mm = [r for r in audit["funds"]
          if r["classification"]["required_category"] == "money_market"]
    assert mm
    for r in mm:
        joined = " ".join(r["usability"]["reasons"])
        assert "万份收益" in joined or "七日年化" in joined


def test_index_return_basis_unknown(audit):
    """已接入 10 个指数的 return_basis 全部 unknown，不得当作全收益。"""
    idx = audit["summary"]["indexes"]
    assert idx["total"] == 10
    assert idx["return_basis_unknown"] == 10
    for i in idx["detail"]:
        assert i["return_basis"] == "unknown"


def test_composites_preserved(audit):
    c = audit["summary"]["composites"]
    assert c["total"] == 15
    assert c["total_components"] == 34


def test_no_vacuous_assertion():
    src = Path(__file__).read_text(encoding="utf-8")
    bad = "or " + "True"
    for ln in src.splitlines():
        st = ln.strip()
        if st.startswith("#") or st.startswith('"') or st.startswith("'"):
            continue
        assert bad not in ln, f"恒真断言：{st}"


def test_fingerprint_unchanged():
    """指纹必须与审计 JSON 记录的 before/after 一致（动态比对，不硬编码）。"""
    d = json.loads(AUDIT.read_text(encoding="utf-8"))
    from app.config import settings
    import hashlib
    from pathlib import Path as _P
    raw = _P(settings.database_path).read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    assert actual == d["db_before"]["db_sha256"], "数据库指纹与审计前置不一致"
    assert actual == d["db_after"]["db_sha256"], "数据库指纹与审计后置不一致"
    assert d["db_unchanged"] is True


# ============================================================ 报告一致性
DOCS = [REPORTS / "phase3B6_2_1_design.md",
        REPORTS / "phase3B6_2_1_recommendation.md"]


def _docs_text() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in DOCS)


def test_docs_three_kinds_declared():
    txt = _docs_text()
    for k in ("contract", "research", "substitute"):
        assert k in txt


def test_docs_seven_categories_listed():
    txt = _docs_text()
    for c in REQUIRED_CATEGORIES:
        assert c in txt, f"报告缺类别 {c}"


def test_docs_no_promotion_claim():
    """报告不得声称可以升级。"""
    txt = _docs_text()
    assert "**不可升级**" in txt or "禁止" in txt


def test_docs_money_market_independent():
    txt = _docs_text()
    assert "万份收益" in txt
    assert "七日年化" in txt


def test_docs_bond_bases_distinguished():
    txt = _docs_text()
    for b in ("全价", "净价", "财富"):
        assert b in txt


def test_docs_no_uniform_hs300():
    txt = _docs_text()
    assert "不得统一映射到沪深300" in txt


def test_docs_summary_matches_json(audit):
    txt = _docs_text()
    s = audit["summary"]
    assert str(s["total_funds_by_fund_id"]) in txt
    assert str(s["contract_benchmark_usable"]) in txt
    assert str(s["fully_reproducible"]) in txt


def test_docs_no_placeholder_left():
    """不得残留「见下方明细」之类占位。"""
    txt = _docs_text()
    assert "见下方明细" not in txt


def test_gate_values_in_docs():
    txt = _docs_text()
    assert "ready_for_backtest` | **False**" in txt
    assert "ready_for_formal_ranking` | **False**" in txt
    assert "ready_for_research_analysis` | **True**" in txt


# ============================================================ 3B-6.2.1.1 修正

VERIFIED_BASIS = {"000300": "total_return", "000905": "total_return"}
UNKNOWN_BASIS = {"000300": "unknown", "000905": "unknown"}

RULE = {
    "rule_version": "test-v1",
    "selection_reason": "测试",
    "applicable_category": "index_plain",
    "divergence_from_contract": "只覆盖指数部分",
}


def test_unknown_basis_blocks_research():
    """return_basis=unknown 时研究基准不得判为 available。"""
    p = parse_benchmark_text("沪深300指数收益率×95%+活期存款×5%")
    r = assess_benchmark_usability(
        p, available_index_codes=AVAILABLE, category="index_plain",
        index_return_basis=UNKNOWN_BASIS, contract_evidence_grade="L3",
        research_rule=RULE)
    assert r["has_index_observation"] is True, "有点位数据"
    assert r["has_verified_return_basis"] is False, "但口径未确认"
    assert r["research_benchmark_usable"] is False
    assert r["research_benchmark_candidate"] is True, "只能算候选"


def test_observation_not_equal_usable_series():
    """有指数行情点位 ≠ 有合格收益序列。"""
    p = parse_benchmark_text("沪深300指数收益率×95%+活期存款×5%")
    r = assess_benchmark_usability(
        p, available_index_codes=AVAILABLE, category="index_plain",
        index_return_basis=UNKNOWN_BASIS)
    assert r["has_index_observation"] != r["has_verified_return_basis"]


def test_verified_basis_enables_research():
    """口径确认后才能进 research（独立场景：contract 仍不可用）。"""
    p = parse_benchmark_text("沪深300指数收益率×95%+活期存款×5%")
    r = assess_benchmark_usability(
        p, available_index_codes=AVAILABLE, category="index_plain",
        index_return_basis=VERIFIED_BASIS, contract_evidence_grade="L3",
        research_rule=RULE)
    assert r["max_kind"] == "research"
    assert r["contract_benchmark_usable"] is False
    assert r["research_benchmark_usable"] is True


def test_price_basis_needs_declaration():
    """价格指数可作为研究基准，但必须声明会被低估。"""
    p = parse_benchmark_text("沪深300指数收益率×95%+活期存款×5%")
    r = assess_benchmark_usability(
        p, available_index_codes=AVAILABLE, category="index_plain",
        index_return_basis={"000300": "price"}, research_rule=RULE)
    assert r["basis_needs_declaration"] == ["price"]
    assert any("系统性低估" in x for x in r["reasons"])


def test_missing_research_rule_blocks():
    """研究选择规则未声明时不得判为可用。"""
    p = parse_benchmark_text("沪深300指数收益率×95%+活期存款×5%")
    r = assess_benchmark_usability(
        p, available_index_codes=AVAILABLE, category="index_plain",
        index_return_basis=VERIFIED_BASIS, research_rule=None)
    assert r["research_conditions"]["research_rule_declared"] is False
    assert r["research_benchmark_usable"] is False


def test_substitute_requires_explicit_selection():
    """替代基准必须显式提供六项说明，不得自动产生。"""
    p = parse_benchmark_text("沪深300指数收益率×95%+活期存款×5%")
    r = assess_benchmark_usability(
        p, available_index_codes=AVAILABLE, category="index_plain",
        index_return_basis=UNKNOWN_BASIS, substitute_selection=None)
    assert r["substitute_benchmark_usable"] is False
    assert r["substitute_benchmark_candidate"] is True


def test_substitute_usable_but_research_not():
    """替代可用但 research 不可用的独立场景。"""
    p = parse_benchmark_text("沪深300指数收益率×95%+活期存款×5%")
    sel = {
        "reason": "合同基准含现金成分无法计算",
        "source": "中证沪深300价格指数点位",
        "divergence_from_contract": "缺少 5% 现金成分",
        "data_quality": "价格口径，低估分红",
        "applicable_scope": "仅用于相对强弱比较",
        "invalidation_condition": "取得全收益指数后失效",
    }
    r = assess_benchmark_usability(
        p, available_index_codes=AVAILABLE, category="index_plain",
        index_return_basis=UNKNOWN_BASIS, research_rule=None,
        substitute_selection=sel)
    assert r["substitute_benchmark_usable"] is True
    assert r["research_benchmark_usable"] is False
    assert r["max_kind"] == "substitute"


def test_both_unusable_returns_none():
    """两者均不可用必须返回 none。"""
    p = parse_benchmark_text("中债综合指数收益率×90%+活期存款×10%")
    r = assess_benchmark_usability(
        p, available_index_codes=AVAILABLE, category="pure_bond",
        index_return_basis={}, research_rule=None, substitute_selection=None)
    assert r["max_kind"] == "none"
    assert r["research_benchmark_usable"] is False
    assert r["substitute_benchmark_usable"] is False


def test_research_and_substitute_conditions_differ():
    """research 与 substitute 的判定条件必须不同。"""
    p = parse_benchmark_text("沪深300指数收益率×95%+活期存款×5%")
    sel = {
        "reason": "r", "source": "s", "divergence_from_contract": "d",
        "data_quality": "q", "applicable_scope": "a",
        "invalidation_condition": "i",
    }
    # 只给 substitute，不给 research 规则
    r = assess_benchmark_usability(
        p, available_index_codes=AVAILABLE, category="index_plain",
        index_return_basis=UNKNOWN_BASIS, research_rule=None,
        substitute_selection=sel)
    assert r["substitute_benchmark_usable"] != r["research_benchmark_usable"]

    # 只给 research 规则，不给 substitute
    r2 = assess_benchmark_usability(
        p, available_index_codes=AVAILABLE, category="index_plain",
        index_return_basis=VERIFIED_BASIS, research_rule=RULE,
        substitute_selection=None)
    assert r2["research_benchmark_usable"] != r2["substitute_benchmark_usable"]


def test_no_contract_without_l1():
    """即使全部条件满足，无 L1 也不得判 contract。"""
    p = parse_benchmark_text("沪深300指数收益率×95%+活期存款利率×5%")
    r = assess_benchmark_usability(
        p, available_index_codes=AVAILABLE, category="index_plain",
        index_return_basis=VERIFIED_BASIS, research_rule=RULE)
    assert r["contract_benchmark_usable"] is False
    assert r["max_kind"] != "contract"


def test_never_auto_promoted():
    """research/substitute 结果永远不得自动升级为 contract。"""
    p = parse_benchmark_text("沪深300指数收益率×95%+活期存款×5%")
    for basis in (UNKNOWN_BASIS, VERIFIED_BASIS):
        for sub in (None, {"reason": "r", "source": "s",
                            "divergence_from_contract": "d",
                            "data_quality": "q", "applicable_scope": "a",
                            "invalidation_condition": "i"}):
            r = assess_benchmark_usability(
                p, available_index_codes=AVAILABLE, category="index_plain",
                index_return_basis=basis, research_rule=RULE,
                substitute_selection=sub)
            assert r["max_kind"] in ("research", "substitute", "none")
            assert r["contract_benchmark_usable"] is False


# ============================================================ lifecycle 互斥
def test_lifecycle_buckets_exclusive(audit):
    lc = audit["summary"]["lifecycle"]
    assert lc["sum_equals_total"] is True
    assert lc["existing"] + lc["terminated"] + lc["unknown_status"] == lc["total"]
    assert lc["total"] == audit["summary"]["total_funds_by_fund_id"]


def test_lifecycle_buckets_match_detail(audit):
    from collections import Counter
    recalc = Counter(r["lifecycle_bucket"] for r in audit["funds"])
    lc = audit["summary"]["lifecycle"]
    assert lc["existing"] == recalc.get("existing", 0)
    assert lc["terminated"] == recalc.get("terminated", 0)
    assert lc["unknown_status"] == recalc.get("unknown_status", 0)


def test_lifecycle_unknown_not_counted_as_existing(audit):
    """unknown 不得被当作明确存续。"""
    lc = audit["summary"]["lifecycle"]
    unknown_raw = lc["raw_value_counts"].get("unknown", 0)
    assert unknown_raw == 79
    assert lc["unknown_status"] == 79
    assert lc["existing"] == 0, "库中无 active/existing 值，存续应为 0"


def test_lifecycle_raw_values_all_mapped(audit):
    """真实状态值必须全部有明确归类。"""
    lc = audit["summary"]["lifecycle"]
    assert lc["unmapped_raw_values"] == {}
    rule = lc["mapping_rule"]
    for raw in lc["raw_value_counts"]:
        assert raw in rule, f"{raw} 无映射规则"


def test_lifecycle_each_fund_has_bucket(audit):
    for r in audit["funds"]:
        assert r["lifecycle_bucket"] in ("existing", "terminated", "unknown_status")


# ============================================================ 报告一致性（修正后）
def test_docs_no_42_research_usable():
    """报告不得再声称 42 只已拥有可用研究基准。"""
    txt = _docs_text()
    assert "可建研究评价基准 | **42**" not in txt
    assert "**42** 只" not in txt or "候选" in txt


def test_docs_lifecycle_three_buckets():
    txt = _docs_text()
    assert "unknown_status" in txt or "状态未知" in txt
    assert "存续" in txt


def test_docs_return_basis_unknown_blocks():
    txt = _docs_text()
    assert "return_basis" in txt
    assert "unknown" in txt


# ============================================================ 最终一致性
def test_docs_report_candidates_separately(audit):
    """报告必须把候选数与可用数分开陈述。"""
    txt = _docs_text()
    s = audit["summary"]
    assert "研究基准候选" in txt
    assert "研究基准真正可用" in txt
    assert "替代基准候选" in txt
    assert "替代基准真正可用" in txt
    # 数字必须与 JSON 一致
    assert str(s["research_benchmark_candidate"]) in txt
    assert str(s["research_benchmark_usable"]) in txt


def test_docs_no_stale_usable_42():
    """不得再把 42 写成「已可用」。"""
    txt = _docs_text()
    assert "可建研究评价基准 | 42" not in txt
    assert "有可用收益序列 | 42" not in txt


def test_docs_no_79_as_existing():
    """不得再把 79 当作存续。"""
    txt = _docs_text()
    assert "存续基金 | **79**" not in txt
    assert "存续基金 | 79" not in txt


def test_docs_has_verified_basis_zero(audit):
    txt = _docs_text()
    assert audit["summary"]["has_verified_return_basis"] == 0
    assert "收益口径已确认" in txt


def test_all_index_return_basis_unknown(audit):
    """10 个指数全部 unknown，且不得被修改。"""
    for i in audit["summary"]["indexes"]["detail"]:
        assert i["return_basis"] == "unknown", f"{i['index_code']} 口径被改动"


def test_db_before_after_identical(audit):
    assert audit["db_before"]["db_sha256"] == audit["db_after"]["db_sha256"]
    assert audit["db_before"]["db_bytes"] == audit["db_after"]["db_bytes"]


def test_self_check_all_true(audit):
    """自校验三项必须全为 True。"""
    sc = audit["summary"]["_self_check"]
    assert sc["category_sum_equals_total"] is True
    assert sc["lifecycle_three_buckets_sum_equals_total"] is True
    assert sc["research_plus_none_le_total"] is True
