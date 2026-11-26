"""阶段3B-6.2.1 场外公募基金基准分类体系（纯逻辑模块，只读）。

**不读写数据库**，只提供可被审计脚本与测试直接调用的分类函数。

三个基准概念严格区分（见 :data:`BENCHMARK_KINDS`）：

    contract   合同业绩比较基准 —— 必须来自基金合同/招募说明书（L1）
    research   研究评价基准   —— 为研究选择，可与合同不同，必须披露差异
    substitute 替代基准       —— 合同基准不可复现时的有限研究替代

**任何函数都不得把 research / substitute 升级为 contract。**

七个必需基金类别（:data:`REQUIRED_CATEGORIES`）按 :data:`CATEGORY_PRECEDENCE`
顺序判定，命中即停：

    1. money_market       货币基金
    2. lof_offexchange    LOF 场外份额
    3. etf_feeder         ETF 联接基金
    4. index_plain        普通指数基金（含增强指数，用 is_enhanced 标记）
    5. active_equity      主动权益基金
    6. pure_bond          纯债基金
    7. mixed_bond         混合债券基金

**LOF / ETF联接 是交易形态（trading_form），与投资类型（investment_category）
正交**；`:func:`classify_fund` 同时给出两个维度，避免丢失信息。
"""
from __future__ import annotations

import re
from typing import Any

# ------------------------------------------------------------------ 常量
BENCHMARK_KINDS = {
    "contract": {
        "name": "合同业绩比较基准",
        "definition": "来源于基金合同、招募说明书及正式公告的业绩比较基准",
        "required_evidence_grade": "L1",
        "can_be_promoted_to": None,
        "note": ("必须保留原始合同文字、证据来源、文件日期与有效期间；"
                  "不得把第三方平台文本当成官方合同证据；"
                  "不得用当前合同基准回填历史期间；"
                  "基准变更必须记录生效日期，历史版本必须保留"),
    },
    "research": {
        "name": "研究评价基准",
        "definition": "为进行基金研究而选择的可比较基准",
        "required_evidence_grade": "L2",
        "can_be_promoted_to": None,
        "note": ("可以与合同基准不同，但必须明确选择原因、适用基金类型、"
                  "选择规则版本，并披露与合同基准的差异；"
                  "**不得冒充合同业绩比较基准**"),
    },
    "substitute": {
        "name": "替代基准",
        "definition": "合同基准不可复现时用于有限研究的替代序列",
        "required_evidence_grade": "L3",
        "can_be_promoted_to": None,
        "note": ("必须明确标记为替代基准；"
                  "**不得将结果表述为合同基准超额收益**；"
                  "必须说明替代原因、数据质量与偏差、适用范围与失效条件；"
                  "**不允许自动升级为正式基准**"),
    },
}

EVIDENCE_GRADES = {
    "L1": "基金管理人、指数发布机构、法定披露文件原始证据",
    "L2": "权威机构可追溯的官方转载或正式数据库",
    "L3": "第三方聚合数据",
    "L4": "无法核验的二手描述或推断",
}

REQUIRED_CATEGORIES = [
    "money_market", "lof_offexchange", "etf_feeder",
    "index_plain", "active_equity", "pure_bond", "mixed_bond",
]

CATEGORY_LABELS = {
    "money_market": "货币基金",
    "lof_offexchange": "LOF场外份额",
    "etf_feeder": "ETF联接基金",
    "index_plain": "普通指数基金",
    "active_equity": "主动权益基金",
    "pure_bond": "纯债基金",
    "mixed_bond": "混合债券基金",
    "unclassified": "无法分类（数据不足）",
}

INVESTMENT_CATEGORIES = [
    "money_market", "index_plain", "active_equity", "pure_bond", "mixed_bond",
]

TRADING_FORMS = ["etf_feeder", "lof_offexchange", "otc_plain"]

# 收益口径 —— 绝不可互相替代
RETURN_BASES = {
    "price": "价格指数（仅价格变动，不含分红/利息）",
    "total_return": "全收益指数（价格 + 分红再投资）",
    "net_return": "净收益指数（扣除税费后的再投资）",
    "full_price": "全价指数（含应计利息，不含再投资）",
    "net_price": "净价指数（不含应计利息）",
    "wealth": "财富指数（中债特有，含利息及再投资）",
    "fixed_rate": "固定年化收益率（合同约定的数值，不是资产权重）",
    "unknown": "口径未知",
}

# 成分类型 —— fixed_rate 与 cash 严格分开
COMPONENT_TYPES = {
    "equity_index": "股票/综合指数",
    "bond_index": "债券指数",
    "cash": "现金类利率（活期/同业存款等）",
    "fixed_rate": "固定年化收益率",
    "unknown": "无法识别的成分",
}

# 会污染基准收入的错误做法（供测试与报告引用）
FORBIDDEN_CONFLATIONS = [
    ("price_index_as_total_return", "把价格指数当全收益指数"),
    ("full_price_as_total_return", "把债券全价指数当全收益"),
    ("net_price_as_wealth", "把债券净价指数当财富指数"),
    ("fixed_rate_as_weight", "把固定年化收益率当资产配置权重"),
    ("cash_as_repo_rate", "把现金利率当银行间回购利率"),
    ("etf_market_price_as_index_return", "把 ETF 市场价格当指数收益"),
    ("lof_exchange_price_as_otc", "把 LOF 场内价格当场外份额净值"),
    ("research_as_contract", "把研究评价基准写成合同基准"),
    ("substitute_as_contract", "把替代基准写成合同基准"),
    ("current_weight_backfilled", "用当前权重回填历史权重"),
    ("unexplained_residual_inferred", "推断未解释的剩余权重/成分"),
]

# 已知指数名 → 代码（仅来自 index_master 已接入的 10 个）
KNOWN_INDEX_NAMES = {
    "沪深300": "000300",
    "中证500": "000905",
    "中证800": "000906",
    "上证50": "000016",
    "中证白酒": "399997",
    "中证全指半导体产品与设备": "H30184",
    "中证全指半导体": "H30184",
    "中证内地消费主题": "000942",
    "上证国债": "000012",
    "中证红利": "000922",
    "中证港股通综合": "930930",
}

# 债券指数关键词（未接入，仅识别）
BOND_INDEX_KEYWORDS = ["中债", "中证全债", "中证综合债", "中证综合债券",
                       "中证可转换债券", "国债总", "上证国债"]

# 现金类关键词
CASH_KEYWORDS = ["活期存款", "定期存款", "通知存款", "同业存款", "同业存单",
                 "存款利率", "活期", "定期"]

# 合同里出现固定年化收益率的典型写法
FIXED_RATE_RE = re.compile(
    r"(?<![\d.])(\d+(?:\.\d+)?)\s*%[^×*%]{0,20}(?:指年收益率|年收益率|按期间折算)")

# 成分抽取：支持「名称×95%」「95%×名称」「名称*95%」
COMP_PATTERNS = [
    re.compile(r"([\u4e00-\u9fa5A-Za-z0-9\-（）()＋+\.]{2,40}?)\s*[×xX*]\s*(\d+(?:\.\d+)?)\s*%"),
    re.compile(r"(\d+(?:\.\d+)?)\s*%\s*[×xX*]\s*([\u4e00-\u9fa5A-Za-z0-9\-（）()＋+\.]{2,40})"),
    re.compile(r"([\u4e00-\u9fa5A-Za-z0-9\-（）()＋+\.]{2,40}?)\s*收益率\s*[×xX*]\s*(\d+(?:\.\d+)?)\s*%"),
]


# ------------------------------------------------------------------ 分类
def _norm(s: Any) -> str:
    return "" if s is None else str(s).strip()


def classify_fund(fund: dict) -> dict:
    """把一个基金分类到七个必需类别之一，并给出投资类型/交易形态两个维度。

    :param fund: 至少含 ``fund_name``；可选 ``fund_type_l1`` ``fund_type_l2``
                 ``is_index_fund`` ``fund_code``
    :returns: ``{required_category, investment_category, trading_form,
                 is_enhanced, is_lof, is_etf_feeder, reason}``
    """
    name = _norm(fund.get("fund_name"))
    full_name = _norm(fund.get("fund_full_name"))
    l1 = _norm(fund.get("fund_type_l1"))
    l2 = _norm(fund.get("fund_type_l2"))
    idx_flag = fund.get("is_index_fund")

    # ---- 分类信号来源与置信度 ----
    # primary  : fund_type_l1/l2 齐全（正式分类字段）
    # degraded : L1/L2 缺失，只能用 fund_full_name + fund_name 兜底
    # none     : 连名称都不足以判断
    if l1 and l2:
        classification_source = "primary_field"
        confidence = "high"
        data_insufficient = False
    elif l1 or l2:
        classification_source = "partial_field"
        confidence = "medium"
        data_insufficient = False
    else:
        classification_source = "name_only_degraded"
        confidence = "low"
        data_insufficient = True

    type_text = l1 + "|" + l2 + "|" + full_name + "|" + name

    is_lof = "LOF" in name.upper()
    is_feeder = "联接" in name
    is_money = l1.startswith("货币") or "货币" in full_name
    is_enhanced = ("增强" in l2) or ("增强" in name) or (l1 == "股票型-增强指数")
    is_index = (idx_flag == 1) or ("指数" in l1) or ("指数" in l2) or ("指数" in name)

    # ---- 交易形态 ----
    if is_feeder:
        trading_form = "etf_feeder"
    elif is_lof:
        trading_form = "lof_offexchange"
    else:
        trading_form = "otc_plain"

    # ---- 投资类型 ----
    if is_money:
        investment = "money_market"
    elif is_index:
        investment = "index_plain"
    elif "债券" in type_text:
        if ("纯债" in type_text) or ("长债" in type_text and "可转债" not in type_text
                                      and "普通债券" not in type_text):
            investment = "pure_bond"
        else:
            investment = "mixed_bond"
    elif ("股票" in type_text) or ("混合" in type_text):
        investment = "active_equity"
    else:
        investment = "active_equity"   # 兜底，但会被 reason 标出

    # ---- 七个必需类别（LOF/联接 优先，与投资类型正交）----
    if is_money:
        required = "money_market"
        reason = "fund_type_l1 以「货币」开头"
    elif is_lof:
        required = "lof_offexchange"
        reason = "基金名称含 LOF（按场外份额处理，底层投资类型见 investment_category）"
    elif is_feeder:
        required = "etf_feeder"
        reason = "基金名称含「联接」（目标 ETF 与目标指数必须分开）"
    elif is_index:
        required = "index_plain"
        reason = ("is_index_fund=1 或类型/名称含「指数」"
                   + ("；增强型指数" if is_enhanced else ""))
    elif investment == "pure_bond":
        required = "pure_bond"
        reason = "债券型且为纯债/长债（不含可转债与普通债券）"
    elif investment == "mixed_bond":
        required = "mixed_bond"
        reason = "债券型但含可转债或普通债券成分（需识别权益仓位）"
    else:
        required = "active_equity"
        reason = "股票型/混合型非指数产品"
        if data_insufficient:
            # 名称里连「债券」「股票」「混合」都没有 → 不得强行分配
            has_equity_word = any(k in type_text for k in ("股票", "混合", "权益"))
            has_bond_word = "债券" in type_text
            if not has_equity_word and not has_bond_word:
                required = "unclassified"
                reason = ("**分类字段全空且名称无法判断类别**——"
                            "不得强行分配到任何类别")

    return {
        "fund_code": _norm(fund.get("fund_code")),
        "fund_name": name,
        "fund_full_name": full_name,
        "required_category": required,
        "classification_source": classification_source,
        "classification_confidence": confidence,
        "data_insufficient": data_insufficient,
        "category_label": CATEGORY_LABELS[required],
        "investment_category": investment,
        "investment_label": CATEGORY_LABELS[investment],
        "trading_form": trading_form,
        "is_enhanced": bool(is_enhanced and is_index),
        "is_lof": is_lof,
        "is_etf_feeder": is_feeder,
        "is_money_market": is_money,
        "reason": reason,
    }


# ------------------------------------------------------------------ 基准解析
def _split_terms(text: str) -> list[str]:
    """按 + ＋ 切分基准表达式。"""
    parts = re.split(r"[+＋]", text)
    return [p.strip() for p in parts if p.strip()]


def _identify_component(term: str) -> dict:
    """识别单个基准项：返回成分类型、名称、权重、指数代码。"""
    term = term.strip()
    out = {
        "raw_term": term,
        "component_type": "unknown",
        "name": None,
        "weight": None,
        "index_code": None,
        "return_basis": "unknown",
        "notes": [],
    }

    # 权重
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", term)
    weight_pct = float(m.group(1)) if m else None
    if weight_pct is not None:
        out["weight"] = round(weight_pct / 100.0, 6)

    # 固定年化收益率：带「指年收益率/按期间折算」说明
    if re.search(r"(指年收益率|按期间折算|年收益率)", term):
        out["component_type"] = "fixed_rate"
        out["return_basis"] = "fixed_rate"
        out["name"] = term
        out["notes"].append(
            "**固定年化收益率，不是资产配置权重**；期间折算规则未在合同说明")
        return out

    # 现金类
    if any(k in term for k in CASH_KEYWORDS):
        out["component_type"] = "cash"
        out["name"] = term
        out["notes"].append(
            "现金类利率；**不等于银行间回购利率，也不等于无风险利率**")
        if "税后" in term:
            out["notes"].append("合同注明税后")
        elif "税前" in term:
            out["notes"].append("合同注明税前")
        else:
            out["notes"].append("合同未注明税前/税后")
        return out

    # 债券指数
    if any(k in term for k in BOND_INDEX_KEYWORDS):
        out["component_type"] = "bond_index"
        name_m = re.search(r"([\u4e00-\u9fa5A-Za-z0-9\-（）()]{2,40}?)指数", term)
        out["name"] = name_m.group(0) if name_m else term
        # 口径
        if "财富" in term:
            out["return_basis"] = "wealth"
        elif "全价" in term:
            out["return_basis"] = "full_price"
        elif "净价" in term:
            out["return_basis"] = "net_price"
        else:
            out["return_basis"] = "unknown"
            out["notes"].append("**合同未明说债券指数收益口径**")
        out["notes"].append("中债/中证债券指数**未接入正式库**，无法计算")
        return out

    # 股票/综合指数
    for k, code in KNOWN_INDEX_NAMES.items():
        if k in term:
            out["component_type"] = "equity_index"
            out["index_code"] = code
            out["name"] = k
            break
    else:
        if "指数" in term:
            out["component_type"] = "equity_index"
            nm = re.search(r"([\u4e00-\u9fa5A-Za-z0-9\-（）()]{2,40}?)指数", term)
            out["name"] = nm.group(0) if nm else term
            out["notes"].append("**该指数未接入正式库，无可用收益序列**")

    if out["component_type"] == "equity_index":
        if "全收益" in term:
            out["return_basis"] = "total_return"
        elif "净收益" in term:
            out["return_basis"] = "net_return"
        else:
            out["return_basis"] = "unknown"
            out["notes"].append(
                "**合同只说「指数收益率」，未指明价格/全收益/净收益**")
    return out


def parse_benchmark_text(text: str | None) -> dict:
    """把合同基准原文拆成成分列表。

    绝不在权重缺失时推断权重，也不把未解释的剩余比例补成任何成分。
    """
    raw = _norm(text)
    if not raw:
        return {
            "raw_text": "",
            "components": [],
            "component_count": 0,
            "declared_weight_sum": 0.0,
            "asset_weight_sum": 0.0,
            "fixed_rate_weight_sum": 0.0,
            "unknown_count": 0,
            "unexplained_residual": None,
            "has_fixed_rate": False,
            "cash_count": 0,
            "fixed_rate_count": 0,
            "bond_index_count": 0,
            "equity_index_count": 0,
            "parse_status": "empty",
            "notes": ["**无基准文本**"],
        }

    terms = _split_terms(raw)
    comps = [_identify_component(t) for t in terms]

    # **fixed_rate 不是资产权重**，不计入 asset_weight_sum
    asset_weights = [c["weight"] for c in comps
                     if c["weight"] is not None and c["component_type"] != "fixed_rate"]
    fixed_weights = [c["weight"] for c in comps
                     if c["weight"] is not None and c["component_type"] == "fixed_rate"]
    declared_asset = sum(asset_weights)
    declared_all = sum(asset_weights) + sum(fixed_weights)
    has_unparsed = any(c["weight"] is None for c in comps)
    residual = None
    if not has_unparsed and 0 < declared_asset < 1.0:
        residual = round(1.0 - declared_asset, 6)

    notes = []
    if has_unparsed:
        notes.append("**存在未解析出权重的成分**——不得推断其权重")
    if residual:
        notes.append(
            f"**未解释的剩余 {residual:.0%} 不得推断为现金或其他资产**")

    return {
        "raw_text": raw,
        "components": comps,
        "component_count": len(comps),
        "declared_weight_sum": round(declared_all, 6),
        "asset_weight_sum": round(declared_asset, 6),
        "fixed_rate_weight_sum": round(sum(fixed_weights), 6),
        "unexplained_residual": residual,
        "has_fixed_rate": any(c["component_type"] == "fixed_rate" for c in comps),
        "cash_count": sum(1 for c in comps if c["component_type"] == "cash"),
        "fixed_rate_count": sum(1 for c in comps
                                 if c["component_type"] == "fixed_rate"),
        "bond_index_count": sum(1 for c in comps
                                 if c["component_type"] == "bond_index"),
        "equity_index_count": sum(1 for c in comps
                                   if c["component_type"] == "equity_index"),
        "unknown_count": sum(1 for c in comps
                              if c["component_type"] == "unknown"),
        "parse_status": "parsed",
        "notes": notes,
    }


# ------------------------------------------------------------------ 基准可用性
# 与研究用途相容的收益口径（价格指数不可直接当全收益）
RESEARCH_COMPATIBLE_BASES = {
    "total_return", "net_return", "wealth",
}
# 可作为研究基准但必须声明的口径（价格类，收益会被低估）
RESEARCH_DECLARABLE_BASES = {
    "price", "full_price", "net_price",
}


def assess_benchmark_usability(
    parsed: dict,
    *,
    available_index_codes: set[str],
    category: str,
    index_return_basis: dict[str, str] | None = None,
    contract_evidence_grade: str = "L3",
    has_official_contract_file: bool = False,
    has_historical_weights: bool = False,
    research_rule: dict | None = None,
    substitute_selection: dict | None = None,
) -> dict:
    """判定一条基准能达到的最高可用层级。

    **四个层级严格递进，不满足就降级，不得凭空产生：**

    ``contract``
        必须有 L1 官方合同文件 + 全部成分可算 + 历史权重可验证。

    ``research``
        必须有：指数代码已映射 + 有历史行情 + **``return_basis`` 已确认
        且不为 ``unknown``** + 口径与研究用途相容 + 研究选择规则明确。

    ``substitute``
        必须在合同不可复现时，由调用方**显式提供** ``substitute_selection``
        （含替代原因/序列来源/与原基准差异/数据质量/适用范围/失效条件）。
        **不会因为「有指数数据」就自动产生替代基准。**

    ``none``
        以上都不满足，必须给出明确原因。

    :param index_return_basis: ``{index_code: return_basis}``，
        来自 ``index_master.return_basis``；缺省视为全部 ``unknown``。
    :param research_rule: 研究基准选择规则，至少含
        ``rule_version`` ``selection_reason`` ``applicable_category``
        ``divergence_from_contract``。
    :param substitute_selection: 替代基准选择说明，至少含
        ``reason`` ``source`` ``divergence_from_contract`` ``data_quality``
        ``applicable_scope`` ``invalidation_condition``。
    """
    comps = parsed.get("components", [])
    basis_map = index_return_basis or {}
    reasons: list[str] = []

    # ================= 1. 指数观察 vs 收益口径 =================
    # has_index_observation：有代码且有历史行情点位
    observed = [c for c in comps
                if c["component_type"] == "equity_index"
                and c.get("index_code") in available_index_codes]
    has_index_observation = bool(observed)
    # 有可识别的候选指数成分（哪怕代码未映射/无序列/未接入），
    # 用于区分「无候选映射(D)」与「有候选但必要成分缺失(C)」
    has_candidate_mapping = any(
        c["component_type"] in ("equity_index", "bond_index") for c in comps)

    # has_verified_return_basis：口径已确认（非 unknown）
    verified_basis = []
    unknown_basis = []
    for c in observed:
        b = basis_map.get(c["index_code"], "unknown")
        if b == "unknown":
            unknown_basis.append(c["index_code"])
        else:
            verified_basis.append((c["index_code"], b))
    has_verified_return_basis = bool(verified_basis) and not unknown_basis

    # 研究报告用指数若全为 unknown，则不能判定为可用
    if observed and not has_verified_return_basis:
        reasons.append(
            f"**指数 {sorted({c['index_code'] for c in observed})} 的 "
            "`return_basis` 为 `unknown`，点位数据不得当作合格收益序列**")

    # 口径与研究用途的相容性
    basis_compatible = False
    basis_needs_declaration = []
    if has_verified_return_basis:
        bases = {b for _, b in verified_basis}
        if bases & RESEARCH_COMPATIBLE_BASES:
            basis_compatible = True
        if bases & RESEARCH_DECLARABLE_BASES:
            basis_compatible = True
            basis_needs_declaration = sorted(bases & RESEARCH_DECLARABLE_BASES)
            reasons.append(
                f"**使用价格类口径 {basis_needs_declaration}，"
                "会导致基准收益被系统性低估，必须在研究报告中声明**")

    # ================= 2. 成分可计算性（合同基准用） =================
    # 缺口分两级：**关键缺口**影响基准身份或必要成分的确认（必须降 C），
    # **非关键缺口**只影响能否计算（可评 B，但基准仍不可用）。
    uncomputable = []
    critical_gaps: list[str] = []
    non_critical_gaps: list[str] = []
    for c in comps:
        t = c["component_type"]
        if t == "equity_index":
            if not c.get("index_code"):
                msg = f"{c['name']}（未映射代码）"
                uncomputable.append(msg)
                critical_gaps.append(msg)
            elif c["index_code"] not in available_index_codes:
                msg = f"{c['name']}（无收益序列）"
                uncomputable.append(msg)
                critical_gaps.append(msg)
        elif t == "bond_index":
            msg = f"{c['name']}（债券指数未接入）"
            uncomputable.append(msg)
            critical_gaps.append(msg)
        elif t == "cash":
            msg = f"{c['name']}（现金利率无历史序列）"
            uncomputable.append(msg)
            non_critical_gaps.append(msg)
        elif t == "fixed_rate":
            msg = f"{c['name']}（折算规则未知）"
            uncomputable.append(msg)
            non_critical_gaps.append(msg)
        else:
            msg = f"{c['name'] or c['raw_term']}（无法识别）"
            uncomputable.append(msg)
            critical_gaps.append(msg)

    # 复合基准：必要权重/成分无法确认 → 关键缺口
    if len(comps) > 1:
        residual = parsed.get("unexplained_residual")
        if residual:
            critical_gaps.append(
                f"未解释的剩余 {residual:.0%} 权重"
                "（复合基准成分构成无法确认）")
        unparsed = [c["raw_term"] for c in comps if c["weight"] is None]
        if unparsed:
            critical_gaps.append(
                f"复合基准成分权重无法确认 {unparsed}")

    has_critical_mapping_gap = bool(critical_gaps)
    fully_computable = not uncomputable and bool(comps)

    # ================= 3. contract 判定 =================
    contract_ok = (
        contract_evidence_grade == "L1"
        and has_official_contract_file
        and parsed.get("parse_status") == "parsed"
    )
    if not contract_ok:
        if contract_evidence_grade != "L1":
            reasons.append(
                f"合同基准证据等级为 {contract_evidence_grade}，"
                "**必须有 L1 官方合同文件**")
        if not has_official_contract_file:
            reasons.append("**未取得基金合同/招募说明书原始文件**")
        if parsed.get("parse_status") != "parsed":
            reasons.append("基准文本缺失或无法解析")

    contract_usable = (
        contract_ok and fully_computable and has_historical_weights)

    # ================= 4. research 判定 =================
    # 研究基准必须同时满足 6 条，缺一不可
    rule_ok = bool(research_rule) and all(
        research_rule.get(k) for k in (
            "rule_version", "selection_reason", "applicable_category",
            "divergence_from_contract"))
    if not rule_ok and has_index_observation:
        reasons.append("**研究基准选择规则未完整声明**（需规则版本/选择原因/"
                        "适用类别/与合同基准的差异）")

    research_conditions = {
        "index_code_mapped": bool(observed),
        "history_data_available": bool(observed),
        "return_basis_verified": has_verified_return_basis,
        "basis_compatible_with_research": basis_compatible,
        "research_rule_declared": rule_ok,
        "not_price_index_as_total_return": not (
            has_verified_return_basis
            and {b for _, b in verified_basis} == {"price"}),
    }
    research_usable = all(research_conditions.values())
    # 候选：成分已识别 + 有观察数据，但未通过全部检查
    research_candidate = bool(observed) and not research_usable

    # ================= 5. substitute 判定 =================
    # 替代基准必须由调用方显式提供 6 项说明，且必须「合同不可复现」
    sub_keys = ("reason", "source", "divergence_from_contract",
                "data_quality", "applicable_scope", "invalidation_condition")
    sub_complete = bool(substitute_selection) and all(
        substitute_selection.get(k) for k in sub_keys)
    has_any_series = has_index_observation or bool(verified_basis)
    substitute_usable = bool(
        sub_complete
        and not contract_usable          # 合同可复现时不需要替代
        and has_any_series)
    substitute_candidate = bool(has_any_series) and not substitute_usable

    if substitute_selection and not sub_complete:
        missing = [k for k in sub_keys if not substitute_selection.get(k)]
        reasons.append(f"**替代基准说明缺项：{missing}**")

    # ================= 6. 最高层级（严格递进） =================
    if contract_usable:
        max_kind = "contract"
    elif research_usable:
        max_kind = "research"
        if not contract_ok:
            reasons.append("**只能作为研究评价基准，不得称为合同基准**")
    elif substitute_usable:
        max_kind = "substitute"
        reasons.append("**只能作为替代基准，结果不得表述为合同基准超额收益**")
    else:
        max_kind = "none"
        if not comps:
            reasons.append("**无基准成分，无法建立任何基准**")

    return {
        "max_kind": max_kind,
        # ---- 合同 ----
        "contract_benchmark_usable": contract_usable,
        "fully_reproducible": contract_usable,
        # ---- 研究：候选 vs 可用 严格分开 ----
        "research_benchmark_candidate": research_candidate,
        "research_benchmark_usable": research_usable,
        "research_conditions": research_conditions,
        # ---- 替代：候选 vs 可用 严格分开 ----
        "substitute_benchmark_candidate": substitute_candidate,
        "substitute_benchmark_usable": substitute_usable,
        "substitute_selection_provided": bool(substitute_selection),
        "substitute_selection_complete": sub_complete,
        # ---- 数据事实（分开报告，不得混用）----
        "has_index_observation": has_index_observation,
        "has_candidate_mapping": has_candidate_mapping,
        "has_verified_return_basis": has_verified_return_basis,
        "index_observed_codes": sorted({c["index_code"] for c in observed}),
        "index_unknown_basis_codes": sorted(set(unknown_basis)),
        "index_verified_basis": [{"index_code": k, "return_basis": v}
                                   for k, v in verified_basis],
        "basis_needs_declaration": basis_needs_declaration,
        # ---- 诊断 ----
        "uncomputable_components": uncomputable,
        # ---- 缺口分级（关键 vs 非关键，两者必须分开判断）----
        "has_critical_mapping_gap": has_critical_mapping_gap,
        "critical_gaps": critical_gaps,
        "non_critical_gaps": non_critical_gaps,
        "required_components_complete": not has_critical_mapping_gap,
        "reasons": reasons,
        "category": category,
    }


# ------------------------------------------------------------------ 类别基准规则
CATEGORY_BENCHMARK_RULES = {
    "index_plain": {
        "primary": "**该基金实际跟踪指数的收益口径**（优先全收益/净收益，非价格）",
        "never": ["不得统一映射到沪深300",
                   "不得用价格指数冒充全收益指数"],
        "must_declare": ["跟踪指数的官方代码", "该码对应的收益口径",
                          "合同文本是否指明口径"],
    },
    "etf_feeder": {
        "primary": "**目标指数**的收益口径（与目标 ETF 分开记录）",
        "never": ["**不得把目标 ETF 的二级市场价格收益当作指数收益**",
                   "不得用 ETF 折溢价代替指数表现"],
        "must_declare": ["目标 ETF 代码", "目标指数代码",
                          "合同基准写的是 ETF 还是指数"],
    },
    "active_equity": {
        "primary": "结合投资范围 + 合同基准 + 可比研究指数（如中证800/沪深300）",
        "never": ["不得把研究选择的指数说成合同基准"],
        "must_declare": ["投资范围（A股/港股/行业）", "合同基准原文",
                          "研究指数的选择理由与规则版本"],
    },
    "pure_bond": {
        "primary": "**与久期匹配的中债/中证债券指数**（区分利率债/信用债/短债/中长期）",
        "never": ["不得把净价、全价、财富指数混用",
                   "不得用国债收益率曲线代替债券指数收益率"],
        "must_declare": ["债券类型（利率债/信用债）", "久期区间",
                          "指数口径（全价/净价/财富）"],
    },
    "mixed_bond": {
        "primary": "债券指数 + 权益指数的复合，**必须识别权益仓位与可转债风险**",
        "never": ["不得把可转债当纯债",
                   "不得忽略权益仓位对基准的影响"],
        "must_declare": ["权益仓位上限", "是否含可转债", "复合权重来源"],
    },
    "money_market": {
        "primary": "**万份收益 / 七日年化**独立口径（不与普通净值基金混算）",
        "never": ["不得把货币基金当作普通净值基金计算收益率",
                   "不得把 Shibor 直接当作货币基金收益"],
        "must_declare": ["收益展示口径", "是否复权", "节假日收益结转规则"],
    },
    "lof_offexchange": {
        "primary": "**场外份额净值**（与场内交易价格严格分开）",
        "never": ["**不得因为名称含 LOF 就套用场内价格**",
                   "不得用场内折溢价代替场外净值"],
        "must_declare": ["场外份额代码", "场内代码", "份额类别（A/C）"],
    },
}


def get_category_rules(category: str) -> dict:
    if category not in CATEGORY_BENCHMARK_RULES:
        raise KeyError(f"未知类别：{category}")
    return CATEGORY_BENCHMARK_RULES[category]
