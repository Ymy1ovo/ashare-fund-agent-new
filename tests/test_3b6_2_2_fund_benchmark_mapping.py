"""阶段3B-6.2.2 基金—基准映射规则专项测试。

**全部直接调用真实映射函数**，使用固定输入，不读取预计算 JSON 自我验证。
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
    REQUIRED_CATEGORIES)
from scripts.fund_benchmark_mapping_3b6_2_2 import (  # noqa: E402
    COMPOSITE_RULES, CONFIDENCE_LEVELS, CONFIDENCE_NOTE,
    FUND_CATEGORY_MAPPING_RULES, MAPPING_RULE_VERSION, PROMOTION_FORBIDDEN,
    assert_no_promotion, compute_confidence, get_category_mapping_rule,
    is_promotion_allowed, map_fund_benchmark)

REPORTS = ROOT / "reports"
AUDIT = REPORTS / "phase3B6_2_2_mapping_audit.json"
RULES = REPORTS / "phase3B6_2_2_mapping_rules.json"

# ---------------- 固定测试输入 ----------------
IDX_UNKNOWN = {
    "000300": {"return_basis": "unknown", "index_name": "沪深300",
                "has_series": True, "rows": 5558},
    "000905": {"return_basis": "unknown", "index_name": "中证500",
                "has_series": True, "rows": 5317},
}
IDX_VERIFIED = {
    "000300": {"return_basis": "total_return", "index_name": "沪深300",
                "has_series": True, "rows": 5558},
}
CODES = {"000300", "000905"}

RULE = {
    "rule_version": MAPPING_RULE_VERSION,
    "selection_reason": "测试用研究选择理由",
}

FUND_INDEX = {
    "fund_id": 1, "fund_code": "000051", "fund_name": "测试沪深300指数基金",
    "fund_type_l1": "股票型-标准指数", "fund_type_l2": "股票型-标准指数",
    "is_index_fund": 1, "lifecycle_status": "unknown",
    "lifecycle_bucket": "unknown_status",
    "benchmark": "沪深300指数收益率×95%+活期存款利率(税后)×5%",
    "share_codes": ["000051"],
}

FUND_FEEDER = {
    "fund_id": 2, "fund_code": "000961", "fund_name": "测试沪深300ETF联接",
    "fund_type_l1": "股票型-标准指数", "fund_type_l2": "股票型-标准指数",
    "is_index_fund": 1, "lifecycle_status": "unknown",
    "lifecycle_bucket": "unknown_status",
    "benchmark": "沪深300指数收益率×95%＋银行活期存款利率（税后）×5%",
    "share_codes": ["000961"],
}

FUND_MONEY = {
    "fund_id": 3, "fund_code": "000198", "fund_name": "测试货币基金",
    "fund_type_l1": "货币型-普通货币", "fund_type_l2": "货币型",
    "is_index_fund": None, "lifecycle_status": "unknown",
    "lifecycle_bucket": "unknown_status", "benchmark": "",
    "share_codes": ["000198"],
}

FUND_LOF = {
    "fund_id": 4, "fund_code": "161725", "fund_name": "测试中证白酒指数(LOF)",
    "fund_type_l1": "指数型-股票", "fund_type_l2": "股票型-标准指数",
    "is_index_fund": 1, "lifecycle_status": "unknown",
    "lifecycle_bucket": "unknown_status",
    "benchmark": "中证白酒指数收益率×95%＋活期存款利率(税后)×5%",
    "share_codes": ["161725", "012414"],
}

FUND_PUREBOND = {
    "fund_id": 5, "fund_code": "000015", "fund_name": "测试纯债债券",
    "fund_type_l1": "债券型-长债", "fund_type_l2": "债券型-长期纯债",
    "is_index_fund": None, "lifecycle_status": "unknown",
    "lifecycle_bucket": "unknown_status",
    "benchmark": "中债综合指数收益率", "share_codes": ["000015"],
}

FUND_MIXEDBOND = {
    "fund_id": 6, "fund_code": "000047", "fund_name": "测试双债债券",
    "fund_type_l1": "债券型-普通债券", "fund_type_l2": "债券型-普通债券",
    "is_index_fund": None, "lifecycle_status": "unknown",
    "lifecycle_bucket": "unknown_status",
    "benchmark": "中债-综合全价（1-3年）指数收益率*75%+中证可转换债券（全价）指数收益率*25%",
    "share_codes": ["000047"],
}

FUND_ACTIVE = {
    "fund_id": 7, "fund_code": "000001", "fund_name": "测试成长混合",
    "fund_type_l1": "混合型-偏股", "fund_type_l2": "混合型-偏股",
    "is_index_fund": None, "lifecycle_status": "unknown",
    "lifecycle_bucket": "unknown_status",
    "benchmark": "中证800指数收益率*85%+中债-综合全价（总值）指数收益率*15%",
    "share_codes": ["000001"],
}


def _map(fund, idx=None, codes=None, rule=None, **kw):
    return map_fund_benchmark(
        fund,
        index_info=idx or IDX_UNKNOWN,
        available_index_codes=codes or CODES,
        research_rule=rule,
        contract_evidence_grade=kw.pop("grade", "L3"),
        has_official_contract_file=kw.pop("official", False),
        has_historical_weights=kw.pop("hist_w", False),
        substitute_selection=kw.pop("sub", None),
    )


# ============================================================ 版本与常量
def test_rule_version_declared():
    assert MAPPING_RULE_VERSION == "3B-6.2.2-v1"


def test_confidence_levels_four():
    assert set(CONFIDENCE_LEVELS) == {"A", "B", "C", "D"}
    for k, v in CONFIDENCE_LEVELS.items():
        assert v["can_bypass_usability"] is False, f"{k} 不得绕过可用性判定"


def test_confidence_note_states_not_usability():
    assert "置信度不能替代基准可用性判定" in CONFIDENCE_NOTE.replace("**", "")


def test_seven_category_rules_exist():
    assert len(REQUIRED_CATEGORIES) == 7
    for c in REQUIRED_CATEGORIES:
        r = get_category_mapping_rule(c)
        assert r["rule_id"]
        assert r["primary_source"]
        assert r["forbidden"]
        assert r["candidate_condition"]
        assert r["usable_condition"]


def test_unknown_category_raises():
    with pytest.raises(KeyError):
        get_category_mapping_rule("not_exist")


def test_no_uniform_hs300():
    """不得统一套用沪深300。"""
    for cat in REQUIRED_CATEGORIES:
        r = get_category_mapping_rule(cat)
        assert "沪深300" not in r["primary_source"], \
            f"{cat} 的主基准不得固定为沪深300"
    joined = " ".join(" ".join(get_category_mapping_rule(c)["forbidden"])
                       for c in REQUIRED_CATEGORIES)
    assert "不得统一映射到沪深300" in joined


# ============================================================ 七类规则要点
def test_index_rule_separates_bases():
    r = get_category_mapping_rule("index_plain")
    joined = " ".join(r["forbidden"])
    assert "价格指数" in joined and "全收益" in joined


def test_feeder_rule_separates_etf_and_index():
    r = get_category_mapping_rule("etf_feeder")
    assert "目标 ETF" in r["must_separate"] or any("ETF" in x for x in r["must_separate"])
    joined = " ".join(r["forbidden"])
    assert "二级市场价格" in joined or "市场价格" in joined


def test_active_rule_separates_markets():
    r = get_category_mapping_rule("active_equity")
    joined = " ".join(r["must_separate"])
    assert "A股" in joined and "港股" in joined


def test_pure_bond_rule_rejects_yield_curve():
    r = get_category_mapping_rule("pure_bond")
    joined = " ".join(r["forbidden"])
    assert "国债收益率曲线" in joined
    assert "债券指数" in joined


def test_mixed_bond_rule_mentions_convertible():
    r = get_category_mapping_rule("mixed_bond")
    joined = " ".join(r["forbidden"])
    assert "可转债" in joined


def test_money_rule_independent():
    r = get_category_mapping_rule("money_market")
    assert "万份收益" in r["primary_source"]
    assert "七日年化" in r["primary_source"]
    joined = " ".join(r["forbidden"])
    assert "普通净值基金" in joined
    assert "Shibor" in joined


def test_lof_rule_rejects_exchange_price():
    r = get_category_mapping_rule("lof_offexchange")
    assert "场外份额净值" in r["primary_source"]
    joined = " ".join(r["forbidden"])
    assert "场内市场价格" in joined


# ============================================================ 禁止升级
def test_promotion_forbidden_table():
    assert ("research", "contract") in PROMOTION_FORBIDDEN
    assert ("substitute", "contract") in PROMOTION_FORBIDDEN
    assert ("substitute", "research") in PROMOTION_FORBIDDEN
    assert ("L3", "L1") in PROMOTION_FORBIDDEN
    assert ("price_index", "total_return") in PROMOTION_FORBIDDEN
    assert ("fixed_rate", "asset_weight") in PROMOTION_FORBIDDEN


def test_assert_no_promotion_raises():
    for pair in (("research", "contract"), ("substitute", "contract"),
                  ("substitute", "research"), ("L3", "L1")):
        with pytest.raises(ValueError):
            assert_no_promotion(*pair)


def test_promotion_allowed_for_unlisted():
    assert is_promotion_allowed("contract", "contract") is True


# ============================================================ 置信度计算
def test_confidence_A_requires_all_three():
    """A 级：L1 + 官方合同 + 口径确认 + 全成分可算，四项缺一不可。"""
    c, _ = compute_confidence(
        classification_confidence="high", mapping_evidence_grade="L1",
        has_official_contract=True, has_index_observation=True,
        has_verified_basis=True, all_components_computable=True,
        category="index_plain")
    assert c == "A"


def test_confidence_A_needs_all_four():
    """A 级四项条件任一缺失都不得为 A。"""
    base = dict(classification_confidence="high", mapping_evidence_grade="L1",
                has_official_contract=True, has_index_observation=True,
                has_verified_basis=True, all_components_computable=True,
                category="index_plain")
    assert compute_confidence(**base)[0] == "A"
    for key in ("has_official_contract", "has_verified_basis",
                "all_components_computable"):
        kw = dict(base)
        kw[key] = False
        assert compute_confidence(**kw)[0] != "A", f"{key}=False 仍评为 A"


def test_mapping_identity_requires_l1_or_l2():
    """映射关系身份必须有 L1/L2 证据，L3 不足以确认「是哪只指数」。"""
    assert CONFIDENCE_LEVELS["A"]["requires"].count("L1 官方合同文件") == 1
    assert "L1/L2" in CONFIDENCE_LEVELS["B"]["definition"]
    assert "L3" in CONFIDENCE_LEVELS["B"]["critical_gap_note"]
    assert "仅凭 L3 第三方平台文本，不能评为 B 级" in \
        CONFIDENCE_LEVELS["B"]["critical_gap_note"].replace("**", "")


def test_confidence_B_with_l2_evidence():
    """B 级：L1/L2 证据 + 非关键缺口（口径未确认/成分不全）。"""
    c, notes = compute_confidence(
        classification_confidence="high", mapping_evidence_grade="L2",
        has_official_contract=False, has_index_observation=True,
        has_verified_basis=False, all_components_computable=False,
        category="index_plain")
    assert c == "B"
    assert any("非关键缺口" in n for n in notes)
    assert any("不可用" in n for n in notes)


def test_confidence_B_without_official_but_l1():
    """L1 证据但缺官方合同文件、口径未确认 → B（非关键缺口）。"""
    c, notes = compute_confidence(
        classification_confidence="high", mapping_evidence_grade="L1",
        has_official_contract=False, has_index_observation=True,
        has_verified_basis=False, all_components_computable=True,
        category="index_plain")
    assert c == "B"
    assert any("未持有官方合同原始文件" in n for n in notes)


def test_l3_never_becomes_B():
    """**L3 + 有点位 + 全成分可算，不得自动评 B。**"""
    c, notes = compute_confidence(
        classification_confidence="high", mapping_evidence_grade="L3",
        has_official_contract=False, has_index_observation=True,
        has_verified_basis=False, all_components_computable=True,
        category="index_plain")
    assert c == "C", "仅有 L3 资料不得评 B"
    assert any("无法证明合同里写的确实是该指数" in n for n in notes)


def test_l3_with_all_good_but_no_l1_still_C():
    """即使成分全可算、口径已确认，只有 L3 证据最高也只能 C。"""
    c, _ = compute_confidence(
        classification_confidence="high", mapping_evidence_grade="L3",
        has_official_contract=True, has_index_observation=True,
        has_verified_basis=True, all_components_computable=True,
        category="index_plain")
    assert c == "C"


def test_confidence_C_with_uncomputable():
    c, notes = compute_confidence(
        classification_confidence="high", mapping_evidence_grade="L3",
        has_official_contract=False, has_index_observation=True,
        has_verified_basis=False, all_components_computable=False,
        category="index_plain")
    assert c == "C"
    assert any("必要成分不完整" in n for n in notes)


def test_unknown_basis_alone_not_D():
    """仅收益口径 unknown，但映射身份有 L1 证据 → B，不是 D。"""
    c, _ = compute_confidence(
        classification_confidence="high", mapping_evidence_grade="L1",
        has_official_contract=True, has_index_observation=True,
        has_verified_basis=False, all_components_computable=True,
        category="index_plain")
    assert c == "B", "口径 unknown 不得直接判 D"
    assert c != "D"


def test_confidence_D_when_low_classification():
    c, notes = compute_confidence(
        classification_confidence="low", mapping_evidence_grade="L1",
        has_official_contract=True, has_index_observation=True,
        has_verified_basis=True, all_components_computable=True,
        category="index_plain")
    assert c == "D"
    assert any("分类字段不足" in n for n in notes)


def test_confidence_D_when_no_index():
    c, _ = compute_confidence(
        classification_confidence="high", has_official_contract=False,
        has_index_observation=False, has_verified_basis=False,
        all_components_computable=False, category="pure_bond")
    assert c == "D"


def test_confidence_A_still_not_usable():
    """置信度 A 也不能让 contract 可回测（需真实 L1 与历史权重）。"""
    # 纯指数基准（无 cash 成分），L1 + 官方文件 + 口径已确认 → 置信度 A
    f = dict(FUND_INDEX)
    f["benchmark"] = "沪深300指数收益率×100%"
    rec = _map(f, idx=IDX_VERIFIED, rule=RULE,
               grade="L1", official=True, hist_w=False)
    assert rec["confidence"] == "A"
    # 但缺历史权重 → contract 仍不可用
    assert rec["benchmarks"]["contract"]["available"] is False
    # 研究基准可用（口径已确认），故允许进入下一阶段做研究分析；
    # 但 contract 不可用，绝不能回测
    assert rec["max_kind"] == "research"
    assert rec["allowed_to_next_stage"] is True
    assert rec["confidence_is_not_usability"] is True


def test_confidence_A_with_history_still_needs_all():
    """A 级 + 历史权重齐全时才可能 contract 可用（本库无此条件）。"""
    f = dict(FUND_INDEX)
    f["benchmark"] = "沪深300指数收益率×100%"
    rec = _map(f, idx=IDX_VERIFIED, rule=RULE,
               grade="L1", official=True, hist_w=True)
    assert rec["confidence"] == "A"
    # 100% 单一指数可算 + L1 + 历史权重 → 该假设场景下合同可用
    assert rec["benchmarks"]["contract"]["available"] is True
    assert rec["max_kind"] == "contract"


# ============================================================ 三类基准独立
def test_three_kinds_independent_keys():
    rec = _map(FUND_INDEX, rule=RULE)
    assert set(rec["benchmarks"]) == {"contract", "research", "substitute"}
    for k in rec["benchmarks"]:
        assert rec["benchmarks"][k]["kind"] == k


def test_contract_not_l1_never_available():
    rec = _map(FUND_INDEX, idx=IDX_VERIFIED, rule=RULE)
    assert rec["benchmarks"]["contract"]["evidence_grade"] == "L3"
    assert rec["benchmarks"]["contract"]["has_official_contract_file"] is False
    assert rec["benchmarks"]["contract"]["available"] is False


def test_research_unknown_basis_not_available():
    rec = _map(FUND_INDEX, idx=IDX_UNKNOWN, rule=RULE)
    assert rec["benchmarks"]["research"]["candidate"] is True
    assert rec["benchmarks"]["research"]["available"] is False
    assert rec["benchmarks"]["research"]["return_basis_verified"] is False


def test_research_verified_basis_available():
    rec = _map(FUND_INDEX, idx=IDX_VERIFIED, rule=RULE)
    assert rec["benchmarks"]["research"]["available"] is True
    assert rec["benchmarks"]["research"]["return_basis_verified"] is True
    assert rec["max_kind"] == "research"


def test_substitute_requires_explicit_selection():
    rec = _map(FUND_INDEX, idx=IDX_VERIFIED, rule=RULE)
    assert rec["benchmarks"]["substitute"]["candidate"] is True
    assert rec["benchmarks"]["substitute"]["available"] is False
    assert rec["benchmarks"]["substitute"]["selection_provided"] is False


def test_substitute_with_full_selection():
    sel = {
        "reason": "合同基准含现金成分无法计算",
        "source": "中证沪深300价格指数",
        "divergence_from_contract": "缺 5% 现金成分",
        "data_quality": "价格口径，低估分红",
        "applicable_scope": "仅相对强弱比较",
        "invalidation_condition": "取得全收益指数后失效",
    }
    rec = _map(FUND_INDEX, idx=IDX_UNKNOWN, rule=None, sub=sel)
    assert rec["benchmarks"]["substitute"]["available"] is True
    assert rec["benchmarks"]["research"]["available"] is False
    assert rec["max_kind"] == "substitute"


def test_research_and_substitute_differ():
    """两者判定条件必须不同。"""
    rec1 = _map(FUND_INDEX, idx=IDX_VERIFIED, rule=RULE)
    assert rec1["benchmarks"]["research"]["available"] is True
    assert rec1["benchmarks"]["substitute"]["available"] is False

    rec2 = _map(FUND_INDEX, idx=IDX_UNKNOWN, rule=None, sub={
        "reason": "r", "source": "s", "divergence_from_contract": "d",
        "data_quality": "q", "applicable_scope": "a",
        "invalidation_condition": "i"})
    assert rec2["benchmarks"]["substitute"]["available"] is True
    assert rec2["benchmarks"]["research"]["available"] is False


def test_no_usable_returns_none():
    rec = _map(FUND_PUREBOND, idx={}, codes=set(), rule=None)
    assert rec["max_kind"] == "none"
    assert rec["allowed_to_next_stage"] is False
    assert rec["blocking_reasons"]


def test_different_kinds_never_promoted():
    """任何情形下 research/substitute 都不得变成 contract。"""
    for idx in (IDX_UNKNOWN, IDX_VERIFIED):
        for sub in (None, {"reason": "r", "source": "s",
                            "divergence_from_contract": "d",
                            "data_quality": "q", "applicable_scope": "a",
                            "invalidation_condition": "i"}):
            rec = _map(FUND_INDEX, idx=idx, rule=RULE, sub=sub)
            assert rec["benchmarks"]["contract"]["available"] is False
            assert rec["max_kind"] in ("research", "substitute", "none")


# ============================================================ 七类实际映射
def test_index_plain_mapping():
    rec = _map(FUND_INDEX, rule=RULE)
    assert rec["category"] == "index_plain"
    assert rec["category_rule_id"] == "R-INDEX"


def test_etf_feeder_mapping():
    rec = _map(FUND_FEEDER, rule=RULE)
    assert rec["category"] == "etf_feeder"
    assert rec["category_rule_id"] == "R-FEEDER"


def test_lof_mapping_uses_offexchange():
    rec = _map(FUND_LOF, rule=RULE)
    assert rec["category"] == "lof_offexchange"
    assert rec["category_rule_id"] == "R-LOF"


def test_lof_shares_not_duplicated():
    """A/C 份额按 fund_id 归并，只产出一条记录。"""
    rec = _map(FUND_LOF, rule=RULE)
    assert rec["fund_id"] == 4
    assert len(rec["share_codes"]) == 2, "份额代码记录但不拆成多条"


def test_money_market_mapping():
    rec = _map(FUND_MONEY, rule=None)
    assert rec["category"] == "money_market"
    assert rec["category_rule_id"] == "R-MONEY"
    # 货币基金无万份收益数据 → 不可用
    assert rec["max_kind"] == "none"


def test_pure_bond_mapping():
    rec = _map(FUND_PUREBOND, idx={}, codes=set(), rule=None)
    assert rec["category"] == "pure_bond"
    assert rec["category_rule_id"] == "R-PUREBOND"


def test_mixed_bond_mapping():
    rec = _map(FUND_MIXEDBOND, idx={}, codes=set(), rule=None)
    assert rec["category"] == "mixed_bond"
    assert rec["category_rule_id"] == "R-MIXEDBOND"


def test_active_equity_mapping():
    rec = _map(FUND_ACTIVE, idx={"000906": {"return_basis": "unknown",
                                              "has_series": True, "rows": 5317}},
               codes={"000906"}, rule=RULE)
    assert rec["category"] == "active_equity"
    assert rec["category_rule_id"] == "R-ACTIVE"


# ============================================================ 权重语义
def test_fixed_rate_not_asset_weight():
    """固定年化收益率不计入资产权重。"""
    f = dict(FUND_INDEX)
    f["benchmark"] = "沪深300指数收益率×95%＋1%（指年收益率，评价时应按期间折算）"
    rec = _map(f, rule=RULE)
    c = rec["benchmarks"]["contract"]
    assert abs(c["asset_weight_sum"] - 0.95) < 1e-9
    assert abs(c["fixed_rate_weight_sum"] - 0.01) < 1e-9
    assert abs(c["unexplained_residual"] - 0.05) < 1e-9


def test_unexplained_residual_not_filled():
    f = dict(FUND_INDEX)
    f["benchmark"] = "沪深300指数收益率×95%＋1%（指年收益率，评价时应按期间折算）"
    rec = _map(f, rule=RULE)
    types = [c["component_type"]
             for c in rec["benchmarks"]["contract"]["components"]]
    assert "cash" not in types, "不得把剩余 5% 推断为现金"


def test_unknown_component_not_auto_filled():
    f = dict(FUND_INDEX)
    f["benchmark"] = "某个不存在的指数收益率×100%"
    rec = _map(f, codes=set(), rule=RULE)
    comps = rec["benchmarks"]["contract"]["components"]
    assert comps[0]["index_code"] is None
    assert rec["benchmarks"]["contract"]["available"] is False


def test_incomplete_weight_blocks():
    """权重不完整时合同基准不可通过。"""
    f = dict(FUND_INDEX)
    f["benchmark"] = "沪深300指数收益率×60%"
    rec = _map(f, rule=RULE)
    assert rec["benchmarks"]["contract"]["available"] is False
    assert rec["benchmarks"]["contract"]["unexplained_residual"] == 0.4


# ============================================================ 历史权重
def test_historical_weights_missing_blocks_contract():
    f = dict(FUND_INDEX)
    rec = _map(f, idx=IDX_VERIFIED, rule=RULE,
               grade="L1", official=True, hist_w=False)
    assert rec["benchmarks"]["contract"]["historical_weights_verified"] is False
    assert rec["benchmarks"]["contract"]["available"] is False


def test_current_weight_not_backfilled():
    """当前权重不得自动成为历史权重。"""
    rec = _map(FUND_INDEX, idx=IDX_VERIFIED, rule=RULE)
    assert rec["benchmarks"]["contract"]["historical_weights_verified"] is False


# ============================================================ 生命周期
def test_unknown_lifecycle_not_existing():
    rec = _map(FUND_INDEX, rule=RULE)
    assert rec["lifecycle_status"] == "unknown"
    assert rec["lifecycle_bucket"] == "unknown_status"
    assert rec["lifecycle_bucket"] != "existing"


def test_terminated_lifecycle_preserved():
    f = dict(FUND_INDEX)
    f["lifecycle_status"] = "terminated"
    f["lifecycle_bucket"] = "terminated"
    rec = _map(f, rule=RULE)
    assert rec["lifecycle_bucket"] == "terminated"


def test_degraded_classification_lowers_confidence():
    f = {"fund_id": 9, "fund_code": "999999", "fund_name": "某测试基金",
          "fund_type_l1": None, "fund_type_l2": None,
          "is_index_fund": None, "lifecycle_status": "terminated",
          "lifecycle_bucket": "terminated", "benchmark": "沪深300指数收益率×95%",
          "share_codes": []}
    rec = _map(f, rule=RULE)
    assert rec["confidence"] == "D"
    assert rec["classification"]["data_insufficient"] is True


# ============================================================ 复合基准规则
def test_composite_rules_declared():
    assert COMPOSITE_RULES["must_keep_all_components"] is True
    assert "不得把复合基准简化为单一指数" in \
        COMPOSITE_RULES["forbidden_simplification"].replace("**", "")
    assert "不得假设当前权重在历史上一直有效" in \
        COMPOSITE_RULES["historical_weight_policy"].replace("**", "")
    assert "任一必要成分不可计算" in \
        COMPOSITE_RULES["blocking_rule"].replace("**", "")


# ============================================================ 真实审计数据
@pytest.fixture(scope="module")
def audit() -> dict:
    assert AUDIT.exists(), "缺映射审计 JSON"
    return json.loads(AUDIT.read_text(encoding="utf-8"))


def test_audit_db_unchanged(audit):
    assert audit["db_unchanged"] is True
    assert audit["db_before"]["db_sha256"] == audit["db_after"]["db_sha256"]
    assert audit["db_before"]["db_bytes"] == audit["db_after"]["db_bytes"]


def test_audit_integrity(audit):
    assert audit["integrity_check"] == "ok"
    assert audit["foreign_key_violations"] == 0


def test_audit_120_funds(audit):
    assert audit["summary"]["total_funds_by_fund_id"] == 120
    assert len(audit["funds"]) == 120
    ids = [r["fund_id"] for r in audit["funds"]]
    assert len(ids) == len(set(ids))


def test_audit_lifecycle_exclusive(audit):
    lc = audit["summary"]["lifecycle"]
    assert lc["sum_equals_total"] is True
    assert lc["existing"] + lc["terminated"] + lc["unknown_status"] == lc["total"]
    assert lc["existing"] == 0
    assert lc["unknown_status"] == 79
    assert lc["terminated"] == 41


def test_audit_category_sum(audit):
    from collections import Counter
    recalc = Counter(r["category"] for r in audit["funds"])
    assert audit["summary"]["category_counts"] == dict(recalc)
    assert sum(recalc.values()) == 120


def test_audit_seven_categories_present(audit):
    for c in REQUIRED_CATEGORIES:
        assert c in audit["per_category"]
        assert audit["per_category"][c]["rule_id"]


def test_audit_no_contract_available(audit):
    assert audit["summary"]["contract"]["available"] == 0
    for r in audit["funds"]:
        assert r["benchmarks"]["contract"]["available"] is False


def test_audit_research_candidate_vs_available(audit):
    s = audit["summary"]["research"]
    assert s["candidate"] > 0
    assert s["available"] == 0, "口径未知时研究基准不得可用"


def test_audit_substitute_not_auto(audit):
    s = audit["summary"]["substitute"]
    assert s["candidate"] > 0
    assert s["available"] == 0, "不得因有指数点位就自动产生替代基准"


def test_audit_allowed_zero(audit):
    assert audit["summary"]["allowed_to_next_stage"] == 0


def test_audit_confidence_distribution(audit):
    from collections import Counter
    recalc = Counter(r["confidence"] for r in audit["funds"])
    assert audit["summary"]["confidence_distribution"] == dict(recalc)
    assert sum(recalc.values()) == 120


def test_audit_index_basis_all_unknown(audit):
    ib = audit["summary"]["index_return_basis"]
    assert ib["total"] == 10
    assert ib["unknown"] == 10
    assert ib["all_unknown"] is True
    assert ib["verified"] == 0


def test_audit_self_check(audit):
    sc = audit["summary"]["_self_check"]
    assert sc["category_sum_equals_total"] is True
    assert sc["lifecycle_sum_equals_total"] is True
    assert sc["allowed_le_total"] is True


def test_audit_composites_15(audit):
    cs = audit["composites_summary"]
    assert cs["total"] == 15
    assert cs["total_components"] == 34
    assert len(audit["composites"]) == 15


def test_audit_composites_none_reproducible(audit):
    """15 条复合基准均不可完整复现。"""
    cs = audit["composites_summary"]
    assert cs["all_not_reproducible"] is True
    for c in audit["composites"]:
        assert c["contract_reproducible"] is False
        assert c["uncomputable_components"]


def test_audit_composites_not_simplified(audit):
    assert audit["composites_summary"]["any_simplified"] is False
    for c in audit["composites"]:
        assert c["simplified_to_single_index"] is False
        assert c["component_count"] >= 1


def test_audit_composites_no_historical_weights(audit):
    assert audit["composites_summary"]["with_historical_weights"] == 0
    for c in audit["composites"]:
        assert c["components_with_effective_from"] == 0


def test_audit_per_category_consistent(audit):
    """per_category 数量必须与 funds 明细一致。"""
    from collections import Counter
    recalc = Counter(r["category"] for r in audit["funds"])
    for cat, pc in audit["per_category"].items():
        assert pc["fund_count"] == recalc.get(cat, 0), f"{cat} 数量不符"


def test_rules_json_exists():
    assert RULES.exists()
    d = json.loads(RULES.read_text(encoding="utf-8"))
    assert d["mapping_rule_version"] == MAPPING_RULE_VERSION
    assert set(d["confidence_levels"]) == {"A", "B", "C", "D"}
    assert len(d["category_mapping_rules"]) == 7


def test_rules_json_matches_module():
    d = json.loads(RULES.read_text(encoding="utf-8"))
    assert d["category_mapping_rules"] == FUND_CATEGORY_MAPPING_RULES
    assert d["confidence_levels"] == CONFIDENCE_LEVELS
    assert d["composite_rules"] == COMPOSITE_RULES


def test_no_vacuous_assertion():
    src = Path(__file__).read_text(encoding="utf-8")
    bad = "or " + "True"
    for ln in src.splitlines():
        st = ln.strip()
        if st.startswith("#") or st.startswith('"') or st.startswith("'"):
            continue
        assert bad not in ln, f"恒真断言：{st}"


def test_allowed_requires_at_least_one_usable():
    """无任何可用基准时不得进入下一阶段。"""
    f = dict(FUND_INDEX)
    f["benchmark"] = "沪深300指数收益率×95%+活期存款利率(税后)×5%"
    rec = _map(f, idx=IDX_UNKNOWN, rule=RULE)   # 口径未知 + 含现金
    assert rec["max_kind"] == "none"
    assert rec["allowed_to_next_stage"] is False


# ============================================================ 报告一致性
DOCS622 = [REPORTS / "phase3B6_2_2_design.md",
           REPORTS / "phase3B6_2_2_recommendation.md"]


def _docs_text() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in DOCS622)


def test_docs_exist():
    for p in DOCS622:
        assert p.exists(), f"缺文档 {p.name}"


def test_docs_three_kinds_declared():
    txt = _docs_text()
    for k in ("contract", "research", "substitute"):
        assert k in txt


def test_docs_seven_categories():
    txt = _docs_text()
    for c in REQUIRED_CATEGORIES:
        assert c in txt, f"报告缺类别 {c}"


def test_docs_confidence_four_levels():
    txt = _docs_text()
    for k in ("A", "B", "C", "D"):
        assert f"**{k}**" in txt, f"报告缺置信度 {k}"


def test_docs_confidence_not_usability():
    txt = _docs_text().replace("**", "")
    assert "置信度不能替代基准可用性判定" in txt


def test_docs_no_uniform_hs300():
    txt = _docs_text()
    assert "统一映射到沪深300" in txt


def test_docs_composites_not_simplified():
    txt = _docs_text()
    assert "不得把复合基准简化为单一指数" in txt


def test_docs_lifecycle_three_buckets():
    txt = _docs_text().replace("**", "")
    assert "明确存续" in txt
    assert "状态未知" in txt


def test_docs_gate_values():
    txt = _docs_text()
    assert "ready_for_backtest` | **False**" in txt
    assert "ready_for_formal_ranking` | **False**" in txt
    assert "ready_for_research_analysis` | **True**" in txt


def test_docs_numbers_match_json(audit):
    txt = _docs_text()
    s = audit["summary"]
    assert str(s["total_funds_by_fund_id"]) in txt
    assert str(s["contract"]["available"]) in txt
    assert str(s["research"]["available"]) in txt
    assert str(s["substitute"]["available"]) in txt


def test_docs_no_placeholder():
    txt = _docs_text()
    assert "见下方明细" not in txt
    assert "TODO" not in txt
    assert "待补充" not in txt


def test_docs_per_category_counts_match(audit):
    """七类数量必须在文档中如实出现。"""
    txt = _docs_text()
    for cat, pc in audit["per_category"].items():
        assert str(pc["fund_count"]) in txt


# ============================================================ 3B-6.2.2.1 评级边界
def test_all_120_confidence_matches_detail(audit):
    """120 只评级分布必须与实际明细一致。"""
    from collections import Counter
    recalc = Counter(r["confidence"] for r in audit["funds"])
    assert audit["summary"]["confidence_distribution"] == dict(recalc)
    assert sum(recalc.values()) == 120


def test_004746_rated_C(audit):
    """004746 仅有 L3 资料，必须评 C 而非 B。"""
    rec = next((r for r in audit["funds"] if r["fund_code"] == "004746"), None)
    assert rec is not None
    assert rec["confidence"] == "C", f"004746 评级 {rec['confidence']} 偏高"
    notes = " ".join(rec["confidence_notes"])
    assert "L3" in notes
    assert "无法证明合同里写的确实是该指数" in notes


def test_no_fund_rated_above_evidence(audit):
    """凡证据等级为 L3 的，不得评 A 或 B。"""
    for r in audit["funds"]:
        grade = r["benchmarks"]["contract"]["evidence_grade"]
        if grade == "L3":
            assert r["confidence"] in ("C", "D"), \
                f"{r['fund_code']} 证据 {grade} 却评 {r['confidence']}"


def test_confidence_A_never_bypasses_usability(audit):
    """A 级也不能绕过可用性——本轮 A 级为 0。"""
    assert audit["summary"]["confidence_distribution"].get("A", 0) == 0
    for r in audit["funds"]:
        if r["confidence"] == "A":
            assert r["benchmarks"]["contract"]["available"] is True


def test_confidence_levels_definitions_consistent(audit):
    """JSON 中的四级定义必须与模块一致。"""
    j = audit["confidence_levels"]
    assert j == CONFIDENCE_LEVELS
    for k in ("A", "B", "C", "D"):
        assert j[k]["can_bypass_usability"] is False
    assert "L1/L2" in j["B"]["definition"]
    assert "L3" in j["C"]["definition"]


def test_rules_json_confidence_consistent():
    d = json.loads(RULES.read_text(encoding="utf-8"))
    assert d["confidence_levels"] == CONFIDENCE_LEVELS
    assert "仅凭 L3 第三方平台文本，不能评为 B 级" in \
        d["confidence_levels"]["B"]["critical_gap_note"].replace("**", "")


def test_counts_unchanged_after_fix(audit):
    """评级修正不得改变七类数量与三类基准数量。"""
    s = audit["summary"]
    assert s["total_funds_by_fund_id"] == 120
    assert s["total_share_classes"] == 149
    assert s["contract"]["available"] == 0
    assert s["research"]["candidate"] == 42
    assert s["research"]["available"] == 0
    assert s["substitute"]["candidate"] == 42
    assert s["substitute"]["available"] == 0
    assert s["allowed_to_next_stage"] == 0
    from collections import Counter
    recalc = Counter(r["category"] for r in audit["funds"])
    assert s["category_counts"] == dict(recalc)
    assert sum(recalc.values()) == 120


def test_composites_unchanged(audit):
    cs = audit["composites_summary"]
    assert cs["total"] == 15
    assert cs["total_components"] == 34
    assert cs["all_not_reproducible"] is True


def test_docs_confidence_fix_documented():
    """报告必须记录本次评级修正。"""
    txt = _docs_text().replace("**", "")
    assert "004746" in txt
    assert "仅有 L3" in txt or "L3 第三方" in txt
    assert "B 级 0 只" in txt or "B 级为 0" in txt or "B | 0" in txt


def test_docs_no_confidence_B_claim(audit):
    """报告不得再声称有 B 级基金。"""
    txt = _docs_text()
    n_b = audit["summary"]["confidence_distribution"].get("B", 0)
    assert n_b == 0
    assert "B 级 1 只" not in txt
    assert "**B** | 中高 | **1**" not in txt
