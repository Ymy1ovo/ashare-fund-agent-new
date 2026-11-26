"""阶段3B-6.2.2 基金—基准映射规则模块（纯逻辑，不读写数据库）。

在 3B-6.2.1 分类体系（:mod:`scripts.benchmark_taxonomy_3b6_2_1`）之上，
新增**确定性、可解释、可追溯**的三类基准映射规则。

核心约束（不可违反）：

1. ``contract`` / ``research`` / ``substitute`` 三类**独立记录**，
   不得互相冒充，不得自动升级（:data:`PROMOTION_FORBIDDEN`）。
2. 映射置信度（:data:`CONFIDENCE_LEVELS`）**不等于**基准可用性；
   置信度 A 也不能绕过收益口径/历史权重/成分完整性门槛。
3. 任一必要成分不可计算 → 合同基准不可复现。
4. 未解释的权重/成分**不得推断**。
5. 场外基金不得使用场内交易价格。

用法::

    from scripts.fund_benchmark_mapping_3b6_2_2 import map_fund_benchmark
    rec = map_fund_benchmark(fund, index_info, category_rules=...)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.benchmark_taxonomy_3b6_2_1 import (  # noqa: E402
    BENCHMARK_KINDS, CATEGORY_BENCHMARK_RULES, REQUIRED_CATEGORIES,
    assess_benchmark_usability, classify_fund, parse_benchmark_text)

# ------------------------------------------------------------------ 版本
MAPPING_RULE_VERSION = "3B-6.2.2-v1"

# ------------------------------------------------------------------ 置信度
CONFIDENCE_LEVELS = {
    "A": {
        "label": "高",
        "definition": (
            "L1 官方合同证据、映射关系明确、收益口径确认、"
            "全部必要成分可计算"),
        "requires": [
            "L1 官方合同文件",
            "映射关系在合同中明确写出",
            "收益口径已确认（非 unknown）",
            "全部必要成分可计算",
        ],
        "non_critical_gaps_allowed": False,
        "can_bypass_usability": False,
    },
    "B": {
        "label": "中高",
        "definition": (
            "映射关系有可靠的 L1/L2 证据，基准身份明确，"
            "不存在关键映射缺口，但存在非关键缺口"),
        "requires": [
            "L1 或 L2 映射证据",
            "基准身份（用哪个指数）明确",
            "不存在关键映射缺口（必要成分完整、可确认）",
        ],
        "non_critical_gaps_allowed": True,
        "non_critical_gap_examples": [
            "收益口径未确认（不影响「是哪只指数」，只影响能否算）",
            "现金利率/固定收益率等非必要成分无法计算",
            "未持有官方合同原始文件（不影响身份，只影响合同基准准入）",
        ],
        "critical_gap_note": (
            "**仅凭 L3 第三方平台文本，不能评为 B 级**；"
            "**必要成分缺失（指数未映射、债券指数未接入、复合基准权重"
            "无法确认）属关键缺口，L1/L2 证据也只能评 C**"),
        "can_bypass_usability": False,
    },
    "C": {
        "label": "中低",
        "definition": (
            "存在合理候选映射，但关键证据缺失，"
            "包括仅有 L3 第三方资料、收益口径未确认、必要成分不完整等"),
        "requires": [
            "有可识别的候选指数",
        ],
        "critical_gaps": [
            "仅有 L3 第三方资料（映射关系未获官方证据确认）",
            "收益口径未确认",
            "必要成分缺失或无法确认（指数未映射/债券指数未接入/"
            "复合基准权重无法确认）",
        ],
        "can_bypass_usability": False,
    },
    "D": {
        "label": "低",
        "definition": "分类或映射依据严重不足，无法建立可靠候选关系",
        "requires": [],
        "triggers": [
            "分类字段不足且已降级（classification_confidence=low）",
            "无任何已映射的候选指数",
            "货币基金无万份收益/七日年化数据",
        ],
        "can_bypass_usability": False,
    },
}

CONFIDENCE_NOTE = (
    "**置信度不能替代基准可用性判定**：即使置信度为 A，"
    "只要收益口径、历史权重或必要成分不满足条件，"
    "也不能判为可回测")

# ------------------------------------------------------------------ 禁止升级
PROMOTION_FORBIDDEN = {
    ("research", "contract"): "研究基准不得升级为合同基准",
    ("substitute", "contract"): "替代基准不得升级为合同基准",
    ("substitute", "research"): "替代基准不得升级为研究基准",
    ("current_weight", "historical_weight"): "不得用当前权重回填历史权重",
    ("L3", "L1"): "第三方平台文本不得升级为官方合同证据",
    ("etf_market_price", "index_return"): "ETF 场内价格不得当作指数收益",
    ("lof_exchange_price", "otc_nav"): "LOF 场内价格不得当作场外净值",
    ("price_index", "total_return"): "价格指数不得冒充全收益指数",
    ("full_price", "wealth"): "债券全价指数不得当财富指数",
    ("net_price", "wealth"): "债券净价指数不得当财富指数",
    ("fixed_rate", "asset_weight"): "固定年化收益率不得当资产权重",
    ("cash_rate", "repo_rate"): "现金存款利率不得当银行间回购利率",
}

# ------------------------------------------------------------------ 七类映射规则
FUND_CATEGORY_MAPPING_RULES = {
    "index_plain": {
        "rule_id": "R-INDEX",
        "primary_source": "目标指数",
        "must_separate": ["目标指数代码", "目标指数的收益口径"],
        "forbidden": [
            "不得统一映射到沪深300",
            "不得用价格指数冒充全收益指数",
            "不得因基金名称含行业词就猜行业指数",
        ],
        "candidate_condition": "指数代码已映射且有历史行情",
        "usable_condition": "**收益口径已确认（非 unknown）** + 研究规则已声明",
        "downgrade_when": "收益口径 unknown → 只能标记候选",
    },
    "etf_feeder": {
        "rule_id": "R-FEEDER",
        "primary_source": "目标指数（非目标 ETF 的市场价格）",
        "must_separate": ["目标 ETF 代码", "目标 ETF 场内价格", "目标指数代码"],
        "forbidden": [
            "**不得把目标 ETF 的二级市场价格收益当作指数收益**",
            "不得用 ETF 折溢价代替指数表现",
            "不得因为目标 ETF 有价格就认定指数收益可用",
        ],
        "candidate_condition": "目标指数已映射且有历史行情",
        "usable_condition": "目标指数收益口径已确认",
        "downgrade_when": "仅有 ETF 价格、无指数口径 → 置信度降为 C",
    },
    "active_equity": {
        "rule_id": "R-ACTIVE",
        "primary_source": "合同基准 + 投资范围 + 可比研究指数",
        "must_separate": ["A股暴露", "港股暴露", "行业主题暴露"],
        "forbidden": [
            "不得把研究选择的指数写成合同基准",
            "不得仅因名称相似就强制匹配指数",
            "不得跨市场混用（A股指数替代港股基准）",
        ],
        "candidate_condition": "合同基准含已映射指数，或投资范围明确可对标",
        "usable_condition": "收益口径已确认 + 研究选择理由已声明",
        "downgrade_when": "无投资范围证据 → 置信度降为 C",
    },
    "pure_bond": {
        "rule_id": "R-PUREBOND",
        "primary_source": "与久期/债券类型匹配的债券指数",
        "must_separate": ["利率债 / 信用债", "短债 / 中长期", "净价 / 全价 / 财富"],
        "forbidden": [
            "**不得用国债收益率曲线替代债券指数收益序列**",
            "不得把净价、全价、财富指数混用",
            "久期不匹配时不得直接映射",
        ],
        "candidate_condition": "债券指数已接入且口径匹配",
        "usable_condition": "债券指数口径已确认 + 久期类型匹配",
        "downgrade_when": "债券指数全部未接入 → 置信度 D，不可用",
    },
    "mixed_bond": {
        "rule_id": "R-MIXEDBOND",
        "primary_source": "债券指数 + 权益指数的复合（保留全部成分与权重）",
        "must_separate": ["权益仓位", "可转债风险", "债券类型"],
        "forbidden": [
            "不得把可转债简单归类为纯债",
            "不得忽略权益仓位",
            "缺乏证据时不得假设仓位为 0",
        ],
        "candidate_condition": "成分全部识别且至少一个可用序列",
        "usable_condition": "全部成分可计算 + 口径已确认",
        "downgrade_when": "缺权益或债券成分证据 → 置信度 C/D",
    },
    "money_market": {
        "rule_id": "R-MONEY",
        "primary_source": "万份收益 / 七日年化（独立口径）",
        "must_separate": ["万份收益", "七日年化", "节假收益结转规则"],
        "forbidden": [
            "**不得与普通净值基金混算**",
            "不得直接把 Shibor 或国债收益率当成货币基金收益",
            "不得用净值增长率替代万份收益",
        ],
        "candidate_condition": "有万份收益或七日年化数据",
        "usable_condition": "展示口径与结转规则均已确认",
        "downgrade_when": "仅有普通净值 → 置信度 D，不可用",
    },
    "lof_offexchange": {
        "rule_id": "R-LOF",
        "primary_source": "**场外份额净值**（非场内交易价格）",
        "must_separate": ["场内交易代码", "场外申购代码", "A/C 份额"],
        "forbidden": [
            "**不得使用场内市场价格或折溢价替代场外净值**",
            "不得因名称含 LOF 就套用场内价格",
            "A/C 份额不得重复统计基金本体",
        ],
        "candidate_condition": "场外份额净值可得",
        "usable_condition": "场外净值口径确认 + 底层投资类型基准可用",
        "downgrade_when": "仅有场内价格 → 置信度 D，不可用",
    },
}

# ------------------------------------------------------------------ 复合基准处理
COMPOSITE_RULES = {
    "rule_version": MAPPING_RULE_VERSION,
    "must_keep_all_components": True,
    "forbidden_simplification": "**不得把复合基准简化为单一指数**",
    "weight_separation": (
        "固定年化收益率（``fixed_rate``）与资产配置权重（``asset_weight``）"
        "必须严格区分，不得相加"),
    "rate_separation": (
        "现金利率 / 存款利率 / 回购利率 / 固定收益率分属不同类别，不得混为一类"),
    "basis_separation": (
        "价格指数 / 全收益指数 / 债券净价 / 全价 / 财富指数不得混用"),
    "unknown_weight_policy": "权重无法验证时必须标记 ``None``，不得推断",
    "historical_weight_policy": (
        "**历史权重和基准变更生效日期未知时，不得假设当前权重在历史上一直有效**"),
    "blocking_rule": (
        "**任一必要成分不可计算，完整合同基准就不能标记为可复现**"),
    "no_relaxation": (
        "不得为了提高可用数量而放宽标准；"
        "此前已审计的 15 条复合基准均不可完整复现，本轮结论不变"),
}


# ------------------------------------------------------------------ 计算置信度
def compute_confidence(
    *,
    classification_confidence: str,
    mapping_evidence_grade: str = "L3",
    has_official_contract: bool = False,
    has_index_observation: bool,
    has_verified_basis: bool,
    all_components_computable: bool,
    category: str,
    has_critical_mapping_gap: bool = False,
    critical_gaps: list[str] | None = None,
    non_critical_gaps: list[str] | None = None,
    has_candidate_mapping: bool | None = None,
) -> tuple[str, list[str]]:
    """按**映射证据强度**计算置信度（A/B/C/D）。

    **置信度只评价「映射关系本身的证据强度」，不代表基准可用性。**

    关键边界：

    - **仅有 L3 第三方平台文本 → 最高只能 C**，
      因为无法证明「合同里写的确实是这只指数」。
    - L1/L2 证据下，收益口径 ``unknown`` 或现金/固定收益率成分缺失属
      **非关键缺口**（不影响「是哪只指数」这一身份判断），可评 B，
      但基准仍不可用。
    - **必要成分缺失（指数代码未映射、债券指数未接入、复合基准权重
      无法确认）属关键缺口**，即使有 L1/L2 证据也只能评 C。
    - 无论哪一级，``can_bypass_usability`` 恒为 ``False``。

    :param mapping_evidence_grade: 映射关系的证据等级 L1/L2/L3/L4
    :param has_critical_mapping_gap: 是否存在关键映射缺口
    :param critical_gaps: 关键缺口明细（用于说明）
    :param non_critical_gaps: 非关键缺口明细（用于说明）
    """
    notes: list[str] = []
    critical_gaps = critical_gaps or []
    non_critical_gaps = non_critical_gaps or []

    # ---- D：分类依据严重不足 ----
    if classification_confidence == "low":
        notes.append("分类字段不足，已降级分类，无法建立可靠映射关系")
        return "D", notes

    # ---- D：无任何候选映射 ----
    # 有候选指数成分但代码未映射/无序列 → 属关键缺口，走 C，不是 D
    if has_candidate_mapping is None:
        has_candidate_mapping = has_index_observation
    if not has_index_observation and not has_candidate_mapping:
        if category == "money_market":
            notes.append("货币基金需独立口径，当前无万份收益/七日年化数据")
        else:
            notes.append("无已映射的候选指数，无法建立映射关系")
        return "D", notes

    reliable = mapping_evidence_grade in ("L1", "L2")

    # ---- A：L1 + 官方合同 + 口径确认 + 全成分可算 + 无关键缺口 ----
    if (mapping_evidence_grade == "L1" and has_official_contract
            and has_verified_basis and all_components_computable
            and not has_critical_mapping_gap):
        return "A", notes

    # ---- B：L1/L2 证据 + 基准身份明确 + **无关键映射缺口** ----
    if reliable and not has_critical_mapping_gap:
        notes.append(
            f"映射关系有 {mapping_evidence_grade} 证据支持，基准身份明确")
        if not has_official_contract:
            notes.append("未持有官方合同原始文件")
        if not has_verified_basis:
            notes.append(
                "收益口径未确认（**非关键缺口**：不影响是哪只指数，"
                "但基准**不可用**）")
        if not all_components_computable:
            notes.append("存在不可计算的非必要成分（**非关键缺口**，不予补齐）")
        for g in non_critical_gaps:
            notes.append(f"非关键缺口：{g}")
        return "B", notes

    # ---- C：关键证据缺失（L3 资料 / 关键映射缺口） ----
    if not reliable:
        notes.append(
            f"仅有 {mapping_evidence_grade} 第三方资料，"
            "**无法证明合同里写的确实是该指数**")
    if has_critical_mapping_gap:
        notes.append("**存在关键映射缺口：必要成分缺失或无法确认**")
        for g in critical_gaps:
            notes.append(f"关键缺口：{g}")
    if not has_official_contract:
        notes.append("未取得基金合同/招募说明书原始文件")
    if not has_verified_basis:
        notes.append("收益口径未确认（关键证据缺失）")
    if not all_components_computable and not has_critical_mapping_gap:
        notes.append("存在不可计算成分（非关键缺口），但证据等级不足，仍评 C")
    return "C", notes


# ------------------------------------------------------------------ 主映射函数
def map_fund_benchmark(
    fund: dict,
    *,
    index_info: dict[str, dict],
    available_index_codes: set[str],
    research_rule: dict | None = None,
    substitute_selection: dict | None = None,
    contract_evidence_grade: str = "L3",
    has_official_contract_file: bool = False,
    has_historical_weights: bool = False,
) -> dict:
    """为单只基金生成三类基准的独立映射记录。

    :param fund: 基金字典（含 fund_name/fund_type_l1/fund_type_l2/
                 is_index_fund/fund_code/benchmark/lifecycle_status）
    :param index_info: ``{index_code: {return_basis, index_name, has_series, rows}}``
    :param available_index_codes: 有历史序列的指数代码集合
    :returns: 完整映射记录（见模块 docstring）
    """
    cls = classify_fund(fund)
    category = cls["required_category"]
    parsed = parse_benchmark_text(fund.get("benchmark"))
    basis_map = {k: v.get("return_basis", "unknown")
                  for k, v in index_info.items()}

    # 研究选择规则补全：调用方只需给 selection_reason，
    # 其余三项由本模块按类别规则自动声明（不改变可用性门槛）
    rule_for_assess = None
    if research_rule:
        rule_for_assess = {
            "rule_version": research_rule.get("rule_version",
                                              MAPPING_RULE_VERSION),
            "selection_reason": research_rule.get("selection_reason"),
            "applicable_category": category,
            "divergence_from_contract": (
                "研究基准只覆盖合同基准中已映射的指数部分，"
                "不含债券指数/现金/固定收益率成分，**不等于合同基准**"),
        }

    usability = assess_benchmark_usability(
        parsed,
        available_index_codes=available_index_codes,
        category=category,
        index_return_basis=basis_map,
        contract_evidence_grade=contract_evidence_grade,
        has_official_contract_file=has_official_contract_file,
        has_historical_weights=has_historical_weights,
        research_rule=rule_for_assess,
        substitute_selection=substitute_selection,
    )

    rule = FUND_CATEGORY_MAPPING_RULES.get(category, {})
    all_computable = not usability["uncomputable_components"]

    confidence, conf_notes = compute_confidence(
        classification_confidence=cls["classification_confidence"],
        mapping_evidence_grade=contract_evidence_grade,
        has_official_contract=has_official_contract_file,
        has_index_observation=usability["has_index_observation"],
        has_verified_basis=usability["has_verified_return_basis"],
        all_components_computable=all_computable,
        category=category,
        # 关键缺口状态来自真实解析结果，不是测试手工传入
        has_critical_mapping_gap=usability["has_critical_mapping_gap"],
        critical_gaps=usability["critical_gaps"],
        non_critical_gaps=usability["non_critical_gaps"],
        has_candidate_mapping=usability["has_candidate_mapping"],
    )

    # ---- 三类基准独立记录 ----
    research_rule_full = {
        "rule_version": MAPPING_RULE_VERSION,
        "rule_id": rule.get("rule_id"),
        "selection_reason": (rule_for_assess or {}).get("selection_reason"),
        "applicable_category": category,
        "divergence_from_contract": (
            "研究基准只覆盖合同基准中已映射的指数部分，"
            "不含债券指数/现金/固定收益率成分，"
            "**不等于合同基准**"),
    }

    contract_record = {
        "kind": "contract",
        "available": usability["contract_benchmark_usable"],
        "name": parsed["raw_text"] or None,
        "components": parsed["components"],
        "asset_weight_sum": parsed["asset_weight_sum"],
        "fixed_rate_weight_sum": parsed["fixed_rate_weight_sum"],
        "unexplained_residual": parsed["unexplained_residual"],
        "return_basis_verified": usability["has_verified_return_basis"],
        "evidence_grade": contract_evidence_grade,
        "has_official_contract_file": has_official_contract_file,
        "historical_weights_verified": has_historical_weights,
        "uncomputable_components": usability["uncomputable_components"],
        "unavailable_reason": (
            None if usability["contract_benchmark_usable"]
            else "；".join(usability["reasons"]) or "成分或证据不完整"),
    }

    research_record = {
        "kind": "research",
        "available": usability["research_benchmark_usable"],
        "candidate": usability["research_benchmark_candidate"],
        "name": (f"{category} 研究比较序列") if research_rule else None,
        "components": [c for c in parsed["components"]
                        if c["component_type"] == "equity_index"],
        "return_basis_verified": usability["has_verified_return_basis"],
        "evidence_grade": "L3",
        "rule": research_rule_full,
        "conditions": usability["research_conditions"],
        "divergence_from_contract": research_rule_full["divergence_from_contract"],
        "unavailable_reason": (
            None if usability["research_benchmark_usable"]
            else "；".join(usability["reasons"]) or "研究条件未全部满足"),
    }

    substitute_record = {
        "kind": "substitute",
        "available": usability["substitute_benchmark_usable"],
        "candidate": usability["substitute_benchmark_candidate"],
        "selection_provided": usability["substitute_selection_provided"],
        "selection_complete": usability["substitute_selection_complete"],
        "explicit_selection": substitute_selection,
        "evidence_grade": "L3",
        "unavailable_reason": (
            None if usability["substitute_benchmark_usable"]
            else ("未提供显式替代选择" if not substitute_selection
                  else "替代条件未满足")),
    }

    return {
        "fund_id": fund.get("fund_id"),
        "fund_code": fund.get("fund_code"),
        "fund_name": fund.get("fund_name"),
        "share_codes": fund.get("share_codes", []),
        "lifecycle_status": fund.get("lifecycle_status"),
        "lifecycle_bucket": fund.get("lifecycle_bucket"),
        "category": category,
        "category_label": cls["category_label"],
        "classification": {
            "source": cls["classification_source"],
            "confidence": cls["classification_confidence"],
            "data_insufficient": cls["data_insufficient"],
        },
        "mapping_rule_version": MAPPING_RULE_VERSION,
        "category_rule_id": rule.get("rule_id"),
        "max_kind": usability["max_kind"],
        "confidence": confidence,
        "confidence_notes": conf_notes,
        "confidence_is_not_usability": True,
        "has_critical_mapping_gap": usability["has_critical_mapping_gap"],
        "critical_gaps": usability["critical_gaps"],
        "non_critical_gaps": usability["non_critical_gaps"],
        "benchmarks": {
            "contract": contract_record,
            "research": research_record,
            "substitute": substitute_record,
        },
        "allowed_to_next_stage": bool(
            usability["research_benchmark_usable"]
            or usability["contract_benchmark_usable"]),
        "blocking_reasons": usability["reasons"] or (
            [] if usability["max_kind"] != "none" else ["无可用基准"]),
        "data_quality": {
            "parse_status": parsed["parse_status"],
            "component_count": parsed["component_count"],
            "uncomputable_count": len(usability["uncomputable_components"]),
            "index_observation": usability["has_index_observation"],
            "index_verified_basis": usability["has_verified_return_basis"],
        },
    }


# ------------------------------------------------------------------ 校验辅助
def assert_no_promotion(from_kind: str, to_kind: str) -> None:
    """若存在禁止的升级关系则抛错。"""
    key = (from_kind, to_kind)
    if key in PROMOTION_FORBIDDEN:
        raise ValueError(
            f"禁止升级 {from_kind} → {to_kind}：{PROMOTION_FORBIDDEN[key]}")


def is_promotion_allowed(from_kind: str, to_kind: str) -> bool:
    return (from_kind, to_kind) not in PROMOTION_FORBIDDEN


def get_category_mapping_rule(category: str) -> dict:
    if category not in FUND_CATEGORY_MAPPING_RULES:
        raise KeyError(f"未知类别：{category}")
    return FUND_CATEGORY_MAPPING_RULES[category]


__all__ = [
    "MAPPING_RULE_VERSION", "CONFIDENCE_LEVELS", "CONFIDENCE_NOTE",
    "PROMOTION_FORBIDDEN", "FUND_CATEGORY_MAPPING_RULES", "COMPOSITE_RULES",
    "BENCHMARK_KINDS", "CATEGORY_BENCHMARK_RULES", "REQUIRED_CATEGORIES",
    "compute_confidence", "map_fund_benchmark", "assert_no_promotion",
    "is_promotion_allowed", "get_category_mapping_rule",
]
