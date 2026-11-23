"""产品结构 / 投资子类型分类（3B-5.0 定稿规则，3B-5.1 复用为唯一实现）。

两条铁律：
1. LOF 是**产品结构**类别，优先级高于「是否跟踪指数」。
   指数型 LOF 仍然是 LOF，只是 investment_subtype=index。
2. 场内 ETF 不在场外默认研究池。
"""
from __future__ import annotations

# 九类产品（与 3B-5.0 报告一致）
PRODUCT_TAXONOMY = {
    "ordinary_index": {
        "label": "普通开放式指数基金",
        "in_default_pool": True,
        "identity_fields": ["is_index_fund=1", "非 ETF 联接", "非 LOF"],
        "comparison_rule": ("宽基与行业主题必须分开比较；"
                            "不同跟踪指数不得混排；"
                            "**指数型 LOF 不算此类**，它归 LOF"),
        "peer_group_key": "product_class+index_scope",
    },
    "etf_linked": {
        "label": "ETF 联接基金",
        "in_default_pool": True,
        "identity_fields": ["fund_name 含「ETF联接」"],
        "comparison_rule": "与直接指数基金可比，但需注明是否含 ETF 折溢价传导",
        "peer_group_key": "product_class+index_scope",
    },
    "active_equity": {
        "label": "主动权益基金",
        "in_default_pool": True,
        "identity_fields": ["fund_type_l1 in (股票型, 混合型-偏股)", "is_index_fund != 1"],
        "comparison_rule": "必须按可验证的业绩基准分组",
        "peer_group_key": "product_class+benchmark_family",
    },
    "bond_pure": {
        "label": "普通债券基金",
        "in_default_pool": True,
        "identity_fields": ["fund_type_l1 含「债券型」", "不含二级债基特征"],
        "comparison_rule": "按久期分组；久期字段缺失则标 unknown",
        "peer_group_key": "product_class+duration_bucket",
    },
    "bond_mixed": {
        "label": "混合债券基金",
        "in_default_pool": True,
        "identity_fields": ["fund_type_l1 含「债券型」+ 含权特征"],
        "comparison_rule": "不得与纯债混排；转债暴露未知时标 unknown",
        "peer_group_key": "product_class+duration_bucket",
    },
    "money_market": {
        "label": "货币基金",
        "in_default_pool": True,
        "identity_fields": ["fund_type_l1 含「货币型」"],
        "comparison_rule": ("独立收益口径（每万份收益/7日年化），"
                            "**不得**与净值型基金计算同类收益/回撤"),
        "peer_group_key": "product_class",
    },
    "qdii": {
        "label": "QDII 基金",
        "in_default_pool": False,
        "identity_fields": ["fund_type_l1 含 QDII"],
        "comparison_rule": "跨境口径特殊，默认不纳入",
        "peer_group_key": "product_class",
    },
    "lof": {
        "label": "LOF 基金",
        "in_default_pool": True,
        "identity_fields": ["fund_name 含 (LOF)"],
        "structure_dimension": "product_structure",
        "investment_subtypes": ["index（指数型 LOF）", "active（主动型 LOF）"],
        "comparison_rule": ("作为独立产品结构类别；"
                            "**内部**再按 investment_subtype 分 index / active 两组比较；"
                            "**不得**把指数型 LOF 与普通开放式指数基金归入同一类别"),
        "forbidden": "不得因为 LOF 跟踪指数就把它改判成普通开放式指数基金",
        "peer_group_key": "product_class+investment_subtype",
    },
    "onshore_etf": {
        "label": "场内 ETF",
        "in_default_pool": False,
        "identity_fields": ["product_structure='etf'"],
        "comparison_rule": "**禁止**混入场外默认研究池",
        "peer_group_key": "excluded",
    },
}

# 场内 ETF 已知代码（不得进入场外默认池）
ONSHORE_ETF_CODES = ("511000", "511050")

# 宽基 vs 行业主题：按名称关键词判定；判定不了就 unknown，不猜
BROAD_KEYWORDS = ("沪深300", "中证500", "中证1000", "上证50", "创业板",
                  "科创板", "中证800", "全指", "MSCI", "A500", "中证A")
SECTOR_KEYWORDS = ("白酒", "半导体", "消费", "医药", "军工", "新能源",
                   "银行", "证券", "地产", "科技", "芯片", "food", "酿酒")


def classify_fund(row) -> dict:
    """按库内字段做可解释分类；缺字段返回 unknown，不猜。

    row 需要具备：fund_name / fund_type_l1 / fund_type_l2 / is_index_fund
    """
    def g(key):
        try:
            return row[key]
        except (KeyError, IndexError, TypeError):
            return None

    name = g("fund_name") or ""
    l1 = g("fund_type_l1") or ""
    l2 = g("fund_type_l2") or ""
    is_idx = g("is_index_fund")

    if "货币" in l1:
        return {"product_class": "money_market", "investment_subtype": "money_market",
                "in_default_pool": True, "basis": "fund_type_l1 含「货币型」",
                "confidence": "high"}
    if "QDII" in l1.upper():
        return {"product_class": "qdii", "investment_subtype": "qdii",
                "in_default_pool": False, "basis": "fund_type_l1 含 QDII",
                "confidence": "high"}
    if "ETF联接" in name or "ETF联接" in name.replace(" ", ""):
        return {"product_class": "etf_linked", "investment_subtype": "index",
                "in_default_pool": True,
                "basis": "基金名称含「ETF联接」→ 产品结构=ETF联接",
                "confidence": "high"}

    # LOF 是产品结构，优先于「是否跟踪指数」
    if "(LOF)" in name or "（LOF）" in name:
        subtype = "index" if is_idx == 1 else "active"
        basis = ("名称含 (LOF) → 产品结构=LOF；"
                 + ("is_index_fund=1 → 底层策略=index" if subtype == "index"
                    else "is_index_fund!=1 → 底层策略=active"))
        return {"product_class": "lof", "investment_subtype": subtype,
                "in_default_pool": True, "basis": basis, "confidence": "high"}

    if is_idx == 1:
        return {"product_class": "ordinary_index", "investment_subtype": "index",
                "in_default_pool": True,
                "basis": "is_index_fund=1 且非 ETF 联接、非 LOF（普通开放式指数）",
                "confidence": "high"}
    if "债券" in l1:
        if "二级" in l2 or "转债" in l2:
            return {"product_class": "bond_mixed", "investment_subtype": "bond_mixed",
                    "in_default_pool": True,
                    "basis": "债券型 + l2 含二级/转债", "confidence": "medium"}
        return {"product_class": "bond_pure", "investment_subtype": "bond_pure",
                "in_default_pool": True,
                "basis": "fund_type_l1 含「债券型」", "confidence": "high"}
    if "股票" in l1 or "混合" in l1:
        return {"product_class": "active_equity", "investment_subtype": "active",
                "in_default_pool": True,
                "basis": "fund_type_l1 为股票型/混合型且非指数",
                "confidence": "high"}
    return {"product_class": "unknown", "investment_subtype": None,
            "in_default_pool": False,
            "basis": "库内分类字段不足以判定", "confidence": "none"}


def is_offmarket_pool(classification: dict, code: str | None = None) -> bool:
    """是否属于场外默认研究池。场内 ETF 一律排除。"""
    if code and code in ONSHORE_ETF_CODES:
        return False
    if classification.get("product_class") in ("onshore_etf", "qdii"):
        return False
    return bool(classification.get("in_default_pool"))


def index_scope(fund_name: str | None) -> str:
    """宽基 / 行业主题 / unknown。判定不了就 unknown。"""
    if not fund_name:
        return "unknown"
    if any(k in fund_name for k in SECTOR_KEYWORDS):
        return "sector"
    if any(k in fund_name for k in BROAD_KEYWORDS):
        return "broad"
    return "unknown"


# 基准标准化：只做**保守、可解释**的归一化。
# 不新增未经验证的映射表；认不出来就 unknown，绝不强行归组。
BENCHMARK_ALIASES = {
    # 归一化后完全相同的写法合并（同义写法，不是推断关系）
    "沪深300指数": "沪深300",
    "沪深300指数收益率": "沪深300",
    "中证500指数": "中证500",
    "中证500指数收益率": "中证500",
    "中证白酒指数": "中证白酒",
    "中证白酒指数收益率": "中证白酒",
    "中证全指半导体产品与设备指数": "中证全指半导体",
    "中证全指半导体产品与设备指数收益率": "中证全指半导体",
    "中证内地消费主题指数": "中证内地消费主题",
    "中证内地消费主题指数收益率": "中证内地消费主题",
    "中债综合指数": "中债综合",
    "中债综合全价指数": "中债综合全价",
    "中债总指数": "中债总",
}

# 可识别的指数族（用于从复合基准文本中提取主基准）
_INDEX_FAMILIES = (
    "沪深300", "中证500", "中证1000", "中证800", "中证A500",
    "上证50", "创业板指", "科创50", "中证白酒",
    "中证全指半导体", "中证内地消费主题",
    "中债综合全价", "中债综合", "中债总",
    "MSCI中国A股", "国证2000",
)

# 基准文本中的修饰：收益、加权、百分比权重等
_NOISE_TOKENS = ("收益率", "指数", "×", "*", "x", "X",
                 "银行活期存款利率", "活期存款利率", "税后",
                 "金融机构人民币", "基准利率", "年收益率", "评价时",
                 "按期", "换算")


def normalize_benchmark(text: str | None) -> dict:
    """把基准文本标准化成可比族名。

    返回 {family, confidence, reason}。
    认不出来 → family='unknown'，**不猜**。
    """
    if text is None or not str(text).strip():
        return {"family": "unknown", "confidence": "none",
                "reason": "benchmark 为空，无法建立可比组"}

    raw = str(text).strip()
    # 1) 完整匹配别名表
    if raw in BENCHMARK_ALIASES:
        return {"family": BENCHMARK_ALIASES[raw], "confidence": "high",
                "reason": f"基准文本与已知写法完全一致：{raw}"}

    # 2) 从文本中提取**唯一**一个可识别指数族
    hits = [fam for fam in _INDEX_FAMILIES if fam in raw]
    # 去重：中证500 与 中证500低波动 只保留更长匹配
    hits = sorted(set(hits), key=len, reverse=True)
    deduped = [h for h in hits if not any(h != o and h in o for o in hits)]

    if len(deduped) == 1:
        fam = deduped[0]
        # 复合基准（含权重百分比）仍归到主基准族，但降级为 medium
        has_weight = "%" in raw or "×" in raw or "X" in raw
        return {"family": fam,
                "confidence": "medium" if has_weight else "high",
                "reason": (f"从基准文本提取到唯一指数族「{fam}」"
                           + ("；该基准为加权复合表述，按主基准归组"
                              if has_weight else ""))}

    if len(deduped) > 1:
        return {"family": "unknown", "confidence": "none",
                "reason": (f"基准文本含多个指数族 {deduped}，"
                           "无法确定单一主基准，标 unknown 不强行归组")}

    return {"family": "unknown", "confidence": "none",
            "reason": f"无法从基准文本识别出已知指数族：{raw[:40]}"}


def peer_group_key(classification: dict, fund_name: str | None,
                   benchmark: str | None,
                   tracking_index: str | None = None) -> dict:
    """同类比较分组键。

    分组依据必须是**可验证的**基准或跟踪指数：
    - 指数/ETF联接：按跟踪指数或基准里的指数族分组；
    - 主动权益：按标准化后的基准族分组，不同基准必须分组；
    - 无法确认 → unknown，不强行归组。
    宽基/行业主题（index_scope）作为**附加维度**保留。
    """
    pc = classification.get("product_class")
    base = {"product_class": pc,
            "investment_subtype": classification.get("investment_subtype")}
    norm = normalize_benchmark(benchmark or tracking_index)
    base["benchmark_family"] = norm["family"]
    base["benchmark_confidence"] = norm["confidence"]
    base["benchmark_reason"] = norm["reason"]

    if pc in ("ordinary_index", "etf_linked"):
        base["index_scope"] = index_scope(fund_name)
        # 跟踪指数优先；没有 tracking_index 就用基准族
        idx_family = norm["family"]
        base["tracking_family"] = idx_family
        key = f"{pc}|{base['index_scope']}|{idx_family}"
    elif pc == "lof":
        base["index_scope"] = index_scope(fund_name)
        if base["investment_subtype"] == "index":
            base["tracking_family"] = norm["family"]
            key = f"lof|index|{base['index_scope']}|{norm['family']}"
        else:
            base["tracking_family"] = None
            key = f"lof|active|{norm['family']}"
    elif pc in ("bond_pure", "bond_mixed"):
        # 久期/信用/转债暴露无可靠数据 → unknown，不解释成相同风险
        base["duration_bucket"] = "unknown"
        base["credit_bucket"] = "unknown"
        base["convertible_bucket"] = "unknown"
        key = f"{pc}|unknown"
    elif pc == "active_equity":
        key = f"active_equity|{norm['family']}"
    else:
        key = str(pc)

    base["peer_key"] = key
    base["verifiable_group"] = norm["family"] != "unknown" or pc in (
        "bond_pure", "bond_mixed", "money_market")
    return base
