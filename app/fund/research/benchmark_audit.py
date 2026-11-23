"""阶段3B-6.0.1 业绩比较基准与跟踪指数数据源审计（只读）。

四类证据必须严格区分，**绝不可混为一谈**：

| 常量 | 含义 | 证据强度 |
| --- | --- | --- |
| ``EV_CONTRACT`` | 基金合同约定的业绩比较基准 | 最强（但库内只有转述文字） |
| ``EV_TRACKING`` | 基金合同约定的跟踪指数 | 最强（但库内全 NULL） |
| ``EV_PLATFORM`` | 第三方平台展示的基准文字 | 中等（聚合数据，非合同原文） |
| ``EV_INFERRED`` | 仅从基金名称推测 | 最弱，**不得当作可验证基准** |

本模块只做审计与统计：不写库、不采集、不修改任何评级逻辑。
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from app.database.db import get_connection

# ---------------------------------------------------------------- 证据类型
EV_CONTRACT = "contract_benchmark"
EV_TRACKING = "contract_tracking_index"
EV_PLATFORM = "platform_benchmark_text"
EV_INFERRED = "inferred_from_name"
EV_NONE = "none"

EVIDENCE_TYPES = {
    EV_CONTRACT: ("基金合同约定的业绩比较基准", "strong",
                  "库内 benchmark 字段由第三方接口转述，非合同原文影印件"),
    EV_TRACKING: ("基金合同约定的跟踪指数", "strong",
                  "库内 tracking_index 字段"),
    EV_PLATFORM: ("第三方平台展示的基准文字", "medium",
                  "天天基金/雪球聚合口径，可能与合同原文有出入"),
    EV_INFERRED: ("仅凭基金名称推测", "weak",
                  "**不得**当作可验证基准，只能提示人工复核"),
    EV_NONE: ("无任何基准证据", "none", "只能标 unknown"),
}

# ---------------------------------------------------------------- 指数族→代码
# 只收录**已实际验证**过可获取历史日线的映射。
# code_source / verified_at / verify_rows 由 verify_index_source() 回填。
INDEX_CATALOG = {
    "沪深300": {"codes": {"csindex": "000300"},
                "source": "akshare.stock_zh_index_hist_csindex",
                "underlying": "中证指数有限公司"},
    "中证500": {"codes": {"csindex": "000905"},
                "source": "akshare.stock_zh_index_hist_csindex",
                "underlying": "中证指数有限公司"},
    "中证800": {"codes": {"csindex": "000906"},
                "source": "akshare.stock_zh_index_hist_csindex",
                "underlying": "中证指数有限公司"},
    "上证50": {"codes": {"csindex": "000016"},
               "source": "akshare.stock_zh_index_hist_csindex",
               "underlying": "中证指数有限公司"},
    "中证白酒": {"codes": {"csindex": "399997"},
                 "source": "akshare.stock_zh_index_hist_csindex",
                 "underlying": "中证指数有限公司（深证系列）"},
    "中证全指半导体": {"codes": {"csindex": "H30184"},
                       "source": "akshare.stock_zh_index_hist_csindex",
                       "underlying": "中证指数有限公司"},
    "中证内地消费主题": {"codes": {"csindex": "000942"},
                         "source": "akshare.stock_zh_index_hist_csindex",
                         "underlying": "中证指数有限公司"},
    "上证国债": {"codes": {"csindex": "000012"},
                 "source": "akshare.stock_zh_index_hist_csindex",
                 "underlying": "中证指数有限公司（上证系列）"},
    "中证红利": {"codes": {"csindex": "000922"},
                 "source": "akshare.stock_zh_index_hist_csindex",
                 "underlying": "中证指数有限公司"},
    "中证港股通综合": {"codes": {"csindex": "930930"},
                       "source": "akshare.stock_zh_index_hist_csindex",
                       "underlying": "中证指数有限公司"},
}

# 有历史序列但**不在中证官网**的指数族，单独登记，避免混入 csindex 口径
EXTERNAL_INDEX_CATALOG = {
    "恒生指数": {
        "code": "HSI",
        "source": "akshare.stock_hk_index_daily_sina",
        "underlying": "恒生指数有限公司（新浪财经转发）",
        "start_observed": "2013-08-20",
        "completeness": "partial",
        "note": ("新浪只提供 2013-08-20 之后的日线，"
                 "早于该日期不可得；不能假定覆盖基金成立以来全区间"),
    },
}

# 债券类基准：只有"指数族名"，没有可确认的官网代码，一律 unknown
BOND_FAMILIES_UNRESOLVED = (
    "中债综合", "中债综合全价", "中债总", "中债-优选投资级信用债财富",
    "中证综合债券", "中债综合财富",
)

# 现金类成分（不构成指数基准）
CASH_TOKENS = ("活期存款", "银行同业存款", "同业存款利率", "金融机构人民币活期存款",
               "商业银行活期存款", "活期存款基准利率", "税后", "税前")


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", "", str(text or ""))


# ---------------------------------------------------------------- 基准解析
def _split_terms(norm: str) -> list[str]:
    """按 ``+`` / ``＋`` 拆成基准项。

    基金合同里的复合基准几乎都用加号连接：
    ``A×95%＋B×5%``、``A×70%+B×25%+C×5%``。
    """
    parts = re.split(r"[+＋]", norm)
    return [p for p in (x.strip() for x in parts) if p]


def _term_components(term: str) -> list[dict]:
    """解析单个基准项，返回其中识别到的成分。"""
    out: list[dict] = []
    left = term

    for family in sorted(INDEX_CATALOG, key=len, reverse=True):
        if family in left:
            out.append({"family": family, "kind": "index", "raw": family})
            left = left.replace(family, "|")
    for family in sorted(EXTERNAL_INDEX_CATALOG, key=len, reverse=True):
        if family in left:
            out.append({"family": family, "kind": "index", "raw": family})
            left = left.replace(family, "|")
    for family in sorted(BOND_FAMILIES_UNRESOLVED, key=len, reverse=True):
        if family in left:
            out.append({"family": family, "kind": "bond_index", "raw": family})
            left = left.replace(family, "|")

    # 现金类：任一现金词出现即算现金项
    if any(tok in term for tok in CASH_TOKENS):
        out.append({"family": "cash", "kind": "cash",
                    "raw": next(tok for tok in CASH_TOKENS if tok in term)})

    # 固定加项：形如 "1%" / "1%（说明文字）" / "5%*银行同业存款利率"
    # 判据：去掉数字/百分号/乘号/标点后，剩余文字只含「利率/存款/折算」等
    # 说明性词汇。若还剩未知实体名（如「某未知自定义指数」），不当作固定加项。
    if not out and re.search(r"\d+(\.\d+)?\s*%", term):
        residual = re.sub(r"[\d.%+＋×xX*（）()\s，,、；;：:。]", "", term)
        residual = re.sub(r"指|即|其中|收益率|年收益率"
                          r"|评价时应按期间折算|评价时|按期|换算"
                          r"|基准利率|利率|存款|活期|税后|税前|指数", "",
                          residual)
        if not residual:
            out.append({"family": "fixed_rate", "kind": "cash", "raw": term})

    return out


def parse_benchmark(text: str | None) -> dict:
    """解析业绩比较基准文字。

    **核心规则：复合基准绝不退化成单指数。**

    只要基准文字里有多个加号项、或有识别不出的成分，
    就不给 ``single_index_family``，宁可标 composite/unparsed。

    返回：
    - ``terms``: 原始拆分后的各项
    - ``components``: [{"family", "kind", "weight", "raw"}]
      kind ∈ index / bond_index / cash
    - ``is_composite``: 是否多成分
    - ``single_index_family``: 仅当**唯一一项、唯一指数成分**时非 None
    - ``index_families``: 全部识别到的指数族
    - ``unresolved_parts``: 未识别的项原文
    - ``confidence`` / ``reason``
    """
    raw = str(text or "").strip()
    if not raw:
        return {
            "raw": None, "terms": [], "components": [], "is_composite": False,
            "single_index_family": None, "index_families": [],
            "unresolved_parts": [], "cash_component": False,
            "bond_component": False, "weights_sum": None,
            "confidence": "none", "reason": "基准文字为空",
        }

    norm = _norm(raw)
    terms = _split_terms(norm)
    components: list[dict] = []
    unresolved: list[str] = []

    for term in terms:
        comps = _term_components(term)
        if not comps:
            unresolved.append(term)
            continue
        # 该项的权重
        m = re.search(r"(\d{1,3})\s*%", term)
        w = int(m.group(1)) / 100.0 if m else None
        for c in comps:
            components.append({**c, "weight": w, "term": term})

    index_fams = [c["family"] for c in components if c["kind"] == "index"]
    bond_fams = [c["family"] for c in components if c["kind"] == "bond_index"]
    has_cash = any(c["kind"] == "cash" for c in components)

    # 复合判定：多成分 或 多个加号项 或 有未识别项
    is_composite = (len(components) > 1 or len(terms) > 1
                    or bool(unresolved))

    single = (index_fams[0]
              if (len(terms) == 1 and not unresolved
                  and len(components) == 1 and len(index_fams) == 1)
              else None)

    if not components and unresolved:
        confidence = "none"
        reason = "未识别出任何可归类成分"
    elif is_composite:
        confidence = "medium"
        parts = [c["family"] for c in components] + unresolved
        reason = (f"复合基准，{len(terms)} 个加号项，成分 {parts}；"
                  "**不得只用其中一个指数冒充完整基准**")
    elif index_fams:
        confidence = "high"
        reason = "单指数基准，可直接对应指数代码"
    else:
        confidence = "low"
        reason = "仅债券或现金成分，无可确认的官网指数代码"

    return {
        "raw": raw,
        "terms": terms,
        "term_count": len(terms),
        "components": components,
        "is_composite": is_composite,
        "single_index_family": single,
        "index_families": index_fams,
        "bond_families": bond_fams,
        "unresolved_parts": unresolved,
        "cash_component": has_cash,
        "bond_component": bool(bond_fams),
        "weights_sum": (round(sum(c["weight"] or 0 for c in components), 4)
                        if components and all(c["weight"] is not None
                                              for c in components)
                        else None),
        "confidence": confidence,
        "reason": reason,
    }


def classify_evidence(row: dict) -> dict:
    """判定这条基准证据属于哪一类。四类严格区分。"""
    tracking = (row.get("tracking_index") or "").strip()
    benchmark = (row.get("benchmark") or "").strip()
    source = str(row.get("source") or "")

    if tracking:
        return {
            "evidence_type": EV_TRACKING,
            "evidence_label": EVIDENCE_TYPES[EV_TRACKING][0],
            "evidence_strength": EVIDENCE_TYPES[EV_TRACKING][1],
            "evidence_note": EVIDENCE_TYPES[EV_TRACKING][2],
            "evidence_value": tracking,
            "source_record": source,
        }
    if benchmark:
        # 库内 benchmark 来自第三方接口转述，不是合同原文
        return {
            "evidence_type": EV_PLATFORM,
            "evidence_label": EVIDENCE_TYPES[EV_PLATFORM][0],
            "evidence_strength": EVIDENCE_TYPES[EV_PLATFORM][1],
            "evidence_note": (
                "库内 benchmark 由公开接口转述（fund_individual_basic_info_xq）；"
                "**未经基金合同原文核对**，因此归类为平台转述而非合同原文"),
            "evidence_value": benchmark,
            "source_record": source,
        }
    return {
        "evidence_type": EV_NONE,
        "evidence_label": EVIDENCE_TYPES[EV_NONE][0],
        "evidence_strength": EVIDENCE_TYPES[EV_NONE][1],
        "evidence_note": EVIDENCE_TYPES[EV_NONE][2],
        "evidence_value": None,
        "source_record": source,
    }


def index_code_for(family: str | None) -> dict:
    """指数族 → 官网代码。未收录返回 unknown，不猜。"""
    if not family:
        return {"index_code": None, "index_source": None,
                "underlying": None, "resolvable": False,
                "reason": "无指数族"}
    node = INDEX_CATALOG.get(family)
    if node:
        code = node["codes"].get("csindex")
        return {"index_code": code, "index_source": node["source"],
                "underlying": node["underlying"], "resolvable": bool(code),
                "catalog": "csindex_official", "reason": None}
    ext = EXTERNAL_INDEX_CATALOG.get(family)
    if ext:
        return {"index_code": ext["code"], "index_source": ext["source"],
                "underlying": ext["underlying"], "resolvable": True,
                "catalog": "external_partial",
                "completeness": ext["completeness"],
                "note": ext["note"], "reason": None}
    return {"index_code": None, "index_source": None,
            "underlying": None, "resolvable": False,
            "catalog": None,
            "reason": f"指数族「{family}」未收录已验证官网代码"}
# ---------------------------------------------------------------- 全量审计
def audit_all_benchmarks(db_path: Path | None = None) -> dict:
    """扫描**全部**基金本体（含已清盘），逐只给出基准审计结论。

    只读：不写库、不改数据。
    """
    with get_connection(db_path) as conn:
        masters = [dict(r) for r in conn.execute("""
            SELECT fund_id, fund_code_primary, fund_name, fund_company,
                   fund_type_l1, fund_type_l2, is_index_fund, benchmark,
                   tracking_index, lifecycle_status, source
            FROM fund_master ORDER BY fund_id""").fetchall()]
        shares = [dict(r) for r in conn.execute("""
            SELECT share_class_id, fund_id, share_class_code, share_class_name,
                   is_primary FROM fund_share_classes""").fetchall()]

    shares_by_fund: dict[int, list[dict]] = {}
    for s in shares:
        shares_by_fund.setdefault(s["fund_id"], []).append(s)

    rows = []
    for m in masters:
        ev = classify_evidence(m)
        parsed = parse_benchmark(m.get("benchmark"))
        fam = (parsed["index_families"][0]
               if len(parsed["index_families"]) == 1 else
               parsed["single_index_family"])
        code_info = index_code_for(fam)

        n_idx = len(parsed["index_families"])
        only_cash_extra = (parsed["is_composite"]
                           and not parsed["bond_component"]
                           and not parsed["unresolved_parts"]
                           and all(c["kind"] in ("index", "cash")
                                   for c in parsed["components"]))

        if ev["evidence_type"] == EV_NONE:
            status = "no_benchmark"
            unknown_reason = "库内无 benchmark 也无 tracking_index"
        elif n_idx >= 2:
            status = "composite_multi_index"
            unknown_reason = (f"多指数复合基准（{parsed['index_families']}）："
                              "必须所有指数序列齐全才能复现，**不得只取其中一个**")
        elif parsed["bond_component"] and n_idx == 0:
            status = "bond_index_without_code"
            unknown_reason = "债券指数无已核实的官网代码，无法取历史序列"
        elif parsed["bond_component"] and n_idx >= 1:
            status = "composite_with_bond"
            unknown_reason = ("指数 + 债券指数复合基准：债券指数无已核实代码，"
                              "整条基准无法复现")
        elif parsed["unresolved_parts"]:
            status = "unparsed_component"
            unknown_reason = (f"存在无法识别的成分 {parsed['unresolved_parts']}，"
                              "不猜、不用其余成分替代")
        elif n_idx == 1 and only_cash_extra:
            status = "index_plus_cash"
            unknown_reason = ("单一指数 + 现金成分：指数代码可验证，"
                              "但现金利率序列尚未接入，整条基准暂不可复现")
        elif n_idx == 1 and not parsed["is_composite"]:
            status = "index_only"
            unknown_reason = None
        elif parsed["cash_component"]:
            status = "cash_only"
            unknown_reason = "基准只有现金利率成分，不构成指数基准"
        else:
            status = "unparsed"
            unknown_reason = "基准文字无法解析出可归类成分"

        rows.append({
            "fund_id": m["fund_id"],
            "fund_code": m["fund_code_primary"],
            "fund_name": m["fund_name"],
            "fund_company": m["fund_company"],
            "product_class": None,  # 由调用方补 classification
            "fund_type_l1": m["fund_type_l1"],
            "fund_type_l2": m["fund_type_l2"],
            "is_index_fund": m["is_index_fund"],
            "lifecycle_status": m["lifecycle_status"],
            "benchmark_raw": m.get("benchmark"),
            "tracking_index": m.get("tracking_index"),
            "evidence_type": ev["evidence_type"],
            "evidence_label": ev["evidence_label"],
            "evidence_strength": ev["evidence_strength"],
            "evidence_note": ev["evidence_note"],
            "source_record": ev["source_record"],
            "benchmark_parsed": parsed,
            "benchmark_is_clear": bool(parsed["components"]),
            "index_identifiable": bool(fam),
            "index_family": fam,
            "index_families_all": parsed["index_families"],
            "index_code": code_info["index_code"],
            "index_source": code_info["index_source"],
            "index_underlying": code_info["underlying"],
            "index_code_resolvable": code_info["resolvable"],
            "index_catalog": code_info.get("catalog"),
            "index_completeness": code_info.get("completeness"),
            "index_source_note": code_info.get("note"),
            "audit_status": status,
            "unknown_reason": unknown_reason,
            "share_count": len(shares_by_fund.get(m["fund_id"], [])),
        })

    return {
        "phase": "3B-6.0.1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "readonly": True,
        "database_written": False,
        "scanned_fund_count": len(rows),
        "scanned_share_count": len(shares),
        "scope_note": ("本审计覆盖库内**全部** %d 个基金本体（含 %d 个已清盘），"
                       "不是抽样" % (
                           len(rows),
                           sum(1 for r in rows
                               if r["lifecycle_status"] == "terminated"))),
        "evidence_types": EVIDENCE_TYPES,
        "rows": rows,
    }


def summarize_audit(audit: dict) -> dict:
    """按状态 / 证据类型 / 生命周期统计。"""
    rows = audit["rows"]

    def cnt(key, value):
        return sum(1 for r in rows if r.get(key) == value)

    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r["audit_status"]] = by_status.get(r["audit_status"], 0) + 1
    by_evidence: dict[str, int] = {}
    for r in rows:
        by_evidence[r["evidence_type"]] = by_evidence.get(r["evidence_type"], 0) + 1

    live = [r for r in rows if r["lifecycle_status"] != "terminated"]
    term = [r for r in rows if r["lifecycle_status"] == "terminated"]

    def stats(subset):
        return {
            "fund_count": len(subset),
            "share_count": sum(r["share_count"] for r in subset),
            "has_benchmark": sum(1 for r in subset if r["benchmark_raw"]),
            "has_tracking_index": sum(1 for r in subset if r["tracking_index"]),
            "index_identifiable": sum(1 for r in subset if r["index_identifiable"]),
            "index_only": sum(1 for r in subset
                              if r["audit_status"] == "index_only"),
            "index_plus_cash": sum(1 for r in subset
                                   if r["audit_status"] == "index_plus_cash"),
            "index_code_verified": sum(1 for r in subset
                                       if r["index_code_resolvable"]),
            "multi_index_composite": sum(1 for r in subset
                                         if r["audit_status"] == "composite_multi_index"),
            "composite": sum(1 for r in subset
                             if r["benchmark_parsed"]["is_composite"]),
            "no_benchmark": sum(1 for r in subset
                                if r["audit_status"] == "no_benchmark"),
            "bond_without_code": sum(1 for r in subset
                                     if r["audit_status"] == "bond_index_without_code"),
        }

    return {
        "by_audit_status": by_status,
        "by_evidence_type": by_evidence,
        "all": stats(rows),
        "live": stats(live),
        "terminated": stats(term),
        "composite_funds": [
            {"fund_id": r["fund_id"], "fund_code": r["fund_code"],
             "components": [c["family"] for c in r["benchmark_parsed"]["components"]]}
            for r in rows if r["benchmark_parsed"]["is_composite"]
        ],
        "index_code_verified_funds": [
            {"fund_id": r["fund_id"], "fund_code": r["fund_code"],
             "index_family": r["index_family"], "index_code": r["index_code"],
             "audit_status": r["audit_status"]}
            for r in rows if r["index_code_resolvable"]
        ],
        "multi_index_composites": [
            {"fund_id": r["fund_id"], "fund_code": r["fund_code"],
             "index_families": r["benchmark_parsed"]["index_families"]}
            for r in rows if r["audit_status"] == "composite_multi_index"
        ],
    }
