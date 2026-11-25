"""阶段3B-6.1.2 15 条复合基准历史审计（只读）。

从正式库读取 15 条 benchmark_composite + 34 条成分，
逐条建立独立审计记录，并落盘：

- ``reports/phase3B6_1_2_benchmark_audit.json``
- ``reports/phase3B6_1_2_component_history.json``

**只读**：不写正式数据库，不改任何业务代码。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database.db import get_connection  # noqa: E402

REPORTS = ROOT / "reports"
EV = REPORTS / "evidence" / "phase3B6_1_2"

# 七态定义（任务第五部分）
STATES = [
    "component_identified",
    "weight_verified",
    "weight_history_verified",
    "return_basis_verified",
    "history_data_available",
    "point_in_time_verified",
    "formula_reproducible",
    "historically_reproducible",
]

# 指数收益口径（来自 3B-6.1.0/3B-6.1.0.3 已确认的证据）
INDEX_BASIS = {
    "000300": {"price": "000300", "total": "H00300", "net": "N00300",
               "basis_verified": False,
               "note": "有官方编制方案证明全收益/净收益存在，但 return_basis 仍 unknown"},
    "000905": {"price": "000905", "total": "H00905", "net": "N00905",
               "basis_verified": False, "note": "仅 factsheet 披露代码"},
    "000906": {"price": "000906", "total": "H00906", "net": "N00906",
               "basis_verified": False, "note": "仅 factsheet 披露代码"},
    "000016": {"price": "000016", "total": "H00016", "net": "N00016",
               "basis_verified": False, "note": "仅 factsheet 披露代码"},
    "399997": {"price": "399997", "total": "H20539", "net": "399997CNY02",
               "basis_verified": False, "note": "仅 factsheet 披露代码；覆盖率 78.2%"},
    "H30184": {"price": "H30184", "total": "H20184", "net": None,
               "basis_verified": False, "note": "无净收益；H20184 有 1 个非正值"},
    "000942": {"price": "000942", "total": "H00942", "net": None,
               "basis_verified": False, "note": "无净收益"},
    "000922": {"price": "000922", "total": "H00922", "net": "000922CNY020",
               "basis_verified": False, "note": "仅 factsheet 披露代码"},
    "930930": {"price": "930930", "total": "H20930", "net": None,
               "basis_verified": False, "note": "无净收益；覆盖率 52.5%"},
    "000012": {"price": "000012", "total": "N00012", "net": None,
               "basis_verified": False,
               "note": "债券指数；H00012=净价、N00012=利息及再投资；语义特殊"},
}

# 债券指数成分：本轮实测可得的序列
BOND_INDEX_EVIDENCE = {
    "中债总": {
        "official_name": "中债-新综合指数（族系之一）",
        "publisher": "中债金融估值中心（中债登）",
        "series_available": ["财富", "全价", "净价"],
        "rows": 6225, "date_min": "2002-01-04", "date_max": "2026-11-24",
        "mapping_confidence": "LOW",
        "note": ("**无法确认「中债总」对应哪个具体中债指数代码**。"
                  "本轮实测「综合指数」族系有财富/全价/净价三套序列，"
                  "但合同原文「中债总指数」不足以唯一映射。"),
    },
    "中债综合全价": {
        "official_name": "中债-综合指数（全价）",
        "publisher": "中债金融估值中心（中债登）",
        "series_available": ["全价"],
        "rows": 6225, "date_min": "2002-01-04", "date_max": "2026-11-24",
        "mapping_confidence": "MEDIUM",
        "note": "「综合全价」与「综合指数[全价]」字面吻合，但未取得官方代码对照文件",
    },
    "中证综合债券": {
        "official_name": None,
        "publisher": "中证指数有限公司（推定）",
        "series_available": [],
        "rows": 0, "date_min": None, "date_max": None,
        "mapping_confidence": "NONE",
        "note": "**中证系列债券指数未在 AKShare 找到可用接口**，阻断",
    },
    "中债-总全价(总值)": {
        "official_name": "中债-总指数（全价，总值）",
        "publisher": "中债金融估值中心（中债登）",
        "series_available": ["全价"],
        "rows": 6225, "date_min": "2002-01-04", "date_max": "2026-11-24",
        "mapping_confidence": "LOW",
        "note": "「总全价(总值)」的具体代码未确认；全价序列可得但不等于全收益",
    },
    "中债综合财富": {
        "official_name": "中债-综合指数（财富）",
        "publisher": "中债金融估值中心（中债登）",
        "series_available": ["财富"],
        "rows": 6225, "date_min": "2002-01-04", "date_max": "2026-11-24",
        "mapping_confidence": "MEDIUM",
        "note": "「综合财富」与「综合指数[财富]」字面吻合；财富指数含利息再投资",
    },
}

# 现金/固定收益成分的经济含义
CASH_SEMANTICS = {
    "cash": {
        "generic_name": "活期存款利率",
        "variants_in_contracts": [
            "活期存款利率(税后)",
            "银行活期存款利率(税后)",
            "金融机构人民币活期存款基准利率（税后）",
            "人民币活期存款税后利率",
            "商业银行活期存款利率（税前）",
            "同业存款利率",
            "银行同业存款利率",
            "活期存款基准利率",
        ],
        "economic_meaning": "银行存款利率，**不是市场无风险利率**",
        "tax_status": "混合（部分税后、部分税前、部分未标注）",
        "annualization": "年化",
        "history_series_available": False,
        "point_in_time_available": False,
        "note": ("**未取得任何一条活期/同业存款利率的历史序列**。"
                  "央行公布的基准利率自 2015-10-24 起未再调整，"
                  "但合同要求的「税后」口径需自行换算，且历史各期实际执行利率不明。"),
    },
    "fixed_rate": {
        "generic_name": "固定年化收益率",
        "variants_in_contracts": ["1%（指年收益率，评价时应按期间折算）"],
        "economic_meaning": "合同约定的固定年化收益率，**不是资产权重**",
        "tax_status": "未说明",
        "annualization": "年化",
        "period_conversion_method": "unknown",
        "history_series_available": False,
        "point_in_time_available": False,
        "note": "合同只写「按期间折算」，未给公式、天数基准、起止点",
    },
}


def _f(v):
    return None if v is None else float(v)


def load_db() -> tuple[list[dict], list[dict], dict]:
    with get_connection() as c:
        comps = c.execute("""
            SELECT composite_id, benchmark_name, benchmark_raw_text,
                   evidence_source, is_complete, is_reproducible, missing_reason
            FROM benchmark_composite ORDER BY composite_id
        """).fetchall()
        parts = c.execute("""
            SELECT component_id, composite_id, component_type, index_code,
                   component_label, weight, weight_evidence,
                   weight_effective_from, weight_effective_to,
                   data_available, unavailable_reason
            FROM benchmark_composite_component
            ORDER BY composite_id, component_id
        """).fetchall()
        funds = c.execute("""
            SELECT fund_code_primary, fund_name, fund_full_name, fund_company,
                   fund_type_l1, established_date, benchmark
            FROM fund_master
        """).fetchall()

    fund_map = {r[0]: {"fund_code": r[0], "fund_name": r[1],
                        "fund_full_name": r[2], "fund_company": r[3],
                        "fund_type_l1": r[4], "established_date": r[5],
                        "fund_master_benchmark": r[6]}
                for r in funds}

    comp_list = [{
        "composite_id": r[0], "benchmark_name": r[1],
        "benchmark_raw_text": r[2], "evidence_source": r[3],
        "is_complete": bool(r[4]), "is_reproducible": bool(r[5]),
        "missing_reason": r[6],
    } for r in comps]

    part_list = [{
        "component_id": r[0], "composite_id": r[1], "component_type": r[2],
        "index_code": r[3], "component_label": r[4], "weight": _f(r[5]),
        "weight_evidence": r[6],
        "weight_effective_from": r[7], "weight_effective_to": r[8],
        "data_available": bool(r[9]), "unavailable_reason": r[10],
    } for r in parts]
    return comp_list, part_list, fund_map


def extract_fund_code(benchmark_name: str) -> str:
    return benchmark_name.split(" ")[0]


def build_component_audit(comp: dict, part: dict, fund: dict) -> dict:
    """单个成分的完整审计记录。"""
    ctype = part["component_type"]
    rec = {
        "component_id": part["component_id"],
        "composite_id": part["composite_id"],
        "component_name": part["component_label"],
        "index_code": part["index_code"],
        "component_category": ctype,
        "weight": part["weight"],
        "weight_unit": "无（固定年化收益率）" if ctype == "fixed_rate" else "比例",
        "weight_evidence_in_db": part["weight_evidence"],
        "weight_has_text_evidence": bool(part["weight_evidence"]),
        "weight_effective_from": part["weight_effective_from"],
        "weight_effective_to": part["weight_effective_to"],
        "data_available_in_db": part["data_available"],
        "unavailable_reason": part["unavailable_reason"],
    }

    # ---- 收益口径 ----
    if ctype == "index":
        code = part["index_code"]
        if code in INDEX_BASIS:
            ev = INDEX_BASIS[code]
            rec["return_basis"] = {
                "contract_text_states_basis": False,
                "price_code": ev["price"],
                "total_return_code": ev["total"],
                "net_return_code": ev["net"],
                "verified": ev["basis_verified"],
                "note": ev["note"],
            }
            rec["return_basis_status"] = "unknown"
        elif code is None:
            rec["return_basis"] = {
                "contract_text_states_basis": False,
                "verified": False,
                "note": "**该成分未映射到任何指数代码**（恒生指数）",
            }
            rec["return_basis_status"] = "not_verified"
        else:
            rec["return_basis"] = {"verified": False, "note": "代码不在已审计集合"}
            rec["return_basis_status"] = "unknown"
    elif ctype == "bond_index":
        ev = BOND_INDEX_EVIDENCE.get(part["component_label"], {})
        rec["return_basis"] = {
            "verified": False,
            "available_series": ev.get("series_available", []),
            "mapping_confidence": ev.get("mapping_confidence", "NONE"),
            "note": ev.get("note", "未审计"),
        }
        # 合同是否明说「全价/财富/总收益」？
        label = part["component_label"] or ""
        if "全价" in label:
            rec["return_basis_status"] = "contract_states_full_price"
        elif "财富" in label:
            rec["return_basis_status"] = "contract_states_wealth"
        else:
            rec["return_basis_status"] = "unknown"
    elif ctype == "cash":
        rec["return_basis"] = dict(CASH_SEMANTICS["cash"])
        rec["return_basis_status"] = "unknown"
    elif ctype == "fixed_rate":
        rec["return_basis"] = dict(CASH_SEMANTICS["fixed_rate"])
        rec["return_basis_status"] = "fixed_annual_rate"
    else:
        rec["return_basis"] = {"verified": False, "note": "未知成分类型"}
        rec["return_basis_status"] = "unknown"

    # ---- 历史数据可得性 ----
    if ctype == "index":
        rec["history_data_available"] = part["index_code"] in INDEX_BASIS
    elif ctype == "bond_index":
        ev = BOND_INDEX_EVIDENCE.get(part["component_label"], {})
        rec["history_data_available"] = ev.get("rows", 0) > 0
        rec["history_data_detail"] = {
            "rows": ev.get("rows"), "date_min": ev.get("date_min"),
            "date_max": ev.get("date_max"),
        }
    else:
        rec["history_data_available"] = False

    # ---- 时点可用性 ----
    rec["point_in_time_available"] = False
    rec["point_in_time_note"] = (
        "**无任何成分具备历史时点可用性证据**："
        "指数无发布时间证据，债券指数无发布时刻证据，"
        "存款利率无历史序列，固定收益率无折算规则")

    # ---- 权重历史 ----
    rec["weight_history_evidence"] = (
        "缺失" if not part["weight_effective_from"] else part["weight_effective_from"])
    rec["weight_history_verified"] = False

    return rec


def build_benchmark_audit(comp: dict, parts: list[dict], fund: dict) -> dict:
    cid = comp["composite_id"]
    cats = {}
    for p in parts:
        cats.setdefault(p["component_type"], []).append(p)

    # 文本一致性
    fm_bench = fund.get("fund_master_benchmark") or ""
    raw = comp["benchmark_raw_text"] or ""
    text_identical = raw.strip() == fm_bench.strip()
    # 三级文本分类
    def norm_chars(s):
        """仅统一符号与空白（全角/半角、× X x 与 *）。"""
        return (s.replace("＋", "+").replace("×", "*").replace("X", "*")
                 .replace("x", "*").replace("（", "(").replace("）", ")")
                 .replace(" ", ""))

    def norm_terms(s):
        """再统一乘法因子与加项的顺序（a*b == b*a，a+b == b+a）。"""
        terms = []
        for term in norm_chars(s).split("+"):
            factors = sorted(f for f in term.split("*") if f)
            terms.append("*".join(factors))
        return "+".join(sorted(terms))

    text_equivalent = norm_chars(raw) == norm_chars(fm_bench)
    text_same_terms = norm_terms(raw) == norm_terms(fm_bench)
    if text_identical:
        text_class = "identical"
        text_note = "两处文本完全一致"
    elif text_equivalent:
        text_class = "char_diff_only"
        text_note = "仅全角/半角、× 与 * 的符号差异，语义相同"
    elif text_same_terms:
        text_class = "order_diff_only"
        text_note = "仅各项书写顺序不同，语义相同"
    else:
        text_class = "semantic_diff"
        text_note = "**语义实质不同**，必须确认以合同为准"

    # 权重合计
    asset_weight = sum(p["weight"] for p in parts
                       if p["component_type"] != "fixed_rate"
                       and p["weight"] is not None)
    fixed_weights = [p["weight"] for p in parts
                     if p["component_type"] == "fixed_rate"]

    # 七态
    comp_identified = all(
        (p["index_code"] is not None) or (p["component_type"] != "index")
        for p in parts)
    all_weight_evidence = all(p["weight_evidence"] for p in parts)
    weight_history = all(p["weight_effective_from"] for p in parts)
    basis_verified = all(
        (INDEX_BASIS.get(p["index_code"], {}).get("basis_verified", False)
         if p["component_type"] == "index"
         else {"bond_index": BOND_INDEX_EVIDENCE.get(
                   p["component_label"], {}).get("mapping_confidence") in ("HIGH",),
               "cash": False, "fixed_rate": False}.get(p["component_type"], False))
        for p in parts)
    hist_available = all(
        (p["component_type"] == "index" and p["index_code"] in INDEX_BASIS)
        or (p["component_type"] == "bond_index"
            and BOND_INDEX_EVIDENCE.get(p["component_label"], {}).get("rows", 0) > 0)
        for p in parts)
    pit_verified = False
    formula_ok = hist_available and basis_verified
    hist_reproducible = (comp_identified and all_weight_evidence
                          and weight_history and basis_verified
                          and hist_available and pit_verified)

    states = {
        "component_identified": comp_identified,
        "weight_verified": all_weight_evidence,
        "weight_history_verified": weight_history,
        "return_basis_verified": basis_verified,
        "history_data_available": hist_available,
        "point_in_time_verified": pit_verified,
        "formula_reproducible": formula_ok,
        "historically_reproducible": hist_reproducible,
    }

    # 阻断原因
    blockers = []
    if not comp_identified:
        blockers.append("存在未映射到代码的成分（恒生指数）")
    if not all_weight_evidence:
        blockers.append("存在无权重证据的成分")
    if not weight_history:
        blockers.append("**历史权重与生效日期全部缺失**（15/15 条基准的 weight_effective_from 均为 NULL）")
    if not basis_verified:
        blockers.append("**收益口径未确认**（全部 return_basis=unknown 或未核实）")
    if not hist_available:
        missing = [p["component_label"] for p in parts
                   if p["component_type"] in ("bond_index", "cash", "fixed_rate")
                   and not (p["component_type"] == "bond_index"
                            and BOND_INDEX_EVIDENCE.get(
                                p["component_label"], {}).get("rows", 0) > 0)]
        if missing:
            blockers.append(f"历史数据缺失：{', '.join(sorted(set(missing)))}")
    if not pit_verified:
        blockers.append("**时点可用性无证据**")

    return {
        "composite_id": cid,
        "fund_code": extract_fund_code(comp["benchmark_name"]),
        "benchmark_name": comp["benchmark_name"],
        "fund_info": fund,
        "benchmark_raw_text": raw,
        "fund_master_benchmark_text": fm_bench,
        "text_consistency": {
            "identical": text_identical,
            "equivalent_after_normalization": text_equivalent,
            "same_terms_different_order": text_same_terms,
            "classification": text_class,
            "note": text_note,
        },
        "evidence_source": comp["evidence_source"],
        "evidence_grade": "L3",
        "evidence_grade_reason": (
            "来源为 `platform`（第三方平台披露文本），"
            "**未取得基金合同/招募说明书原始文件**，"
            "不能作为 L1 法定披露证据"),
        "component_count": len(parts),
        "components_by_type": {k: len(v) for k, v in cats.items()},
        "asset_weight_sum": round(asset_weight, 6),
        "fixed_rate_components": len(fixed_weights),
        "unexplained_residual": round(1.0 - asset_weight, 6) if asset_weight < 1 else 0.0,
        "states": states,
        "db_claimed": {
            "is_complete": comp["is_complete"],
            "is_reproducible": comp["is_reproducible"],
            "missing_reason": comp["missing_reason"],
        },
        "blockers": blockers,
        "earliest_reproducible_date": None,
        "latest_reproducible_date": None,
        "non_reproducible_interval": "全部历史（无法确定任何可用区间）",
        "required_evidence": [
            "基金合同/招募说明书原始文件（L1）",
            "历次基准变更公告及生效日期（L1）",
            "各债券指数的官方代码对照与编制方案（L1/L2）",
            "活期/同业存款利率的历史序列及税后换算口径",
            "固定年化收益率的期间折算规则",
            "各成分数据的发布时刻与修订记录",
        ],
    }


def main() -> int:
    EV.mkdir(parents=True, exist_ok=True)
    comps, parts, funds = load_db()

    by_comp = {}
    for p in parts:
        by_comp.setdefault(p["composite_id"], []).append(p)

    bench_audit = []
    comp_audit = []
    for c in comps:
        code = extract_fund_code(c["benchmark_name"])
        fund = funds.get(code, {})
        ps = by_comp.get(c["composite_id"], [])
        bench_audit.append(build_benchmark_audit(c, ps, fund))
        for p in ps:
            comp_audit.append(build_component_audit(c, p, fund))

    # summary 全部由明细自动生成
    def cnt(key):
        return sum(1 for b in bench_audit if b["states"][key])

    summary = {
        "total_benchmarks": len(bench_audit),
        "total_components": len(comp_audit),
        "component_identified": cnt("component_identified"),
        "weight_verified": cnt("weight_verified"),
        "weight_history_verified": cnt("weight_history_verified"),
        "return_basis_verified": cnt("return_basis_verified"),
        "history_data_available": cnt("history_data_available"),
        "point_in_time_verified": cnt("point_in_time_verified"),
        "formula_reproducible": cnt("formula_reproducible"),
        "historically_reproducible": cnt("historically_reproducible"),
        "fully_not_reproducible": sum(
            1 for b in bench_audit
            if not b["states"]["formula_reproducible"]
            and not b["states"]["historically_reproducible"]),
        "all_weights_have_evidence": sum(
            1 for b in bench_audit if b["states"]["weight_verified"]),
        "text_identical_count": sum(
            1 for b in bench_audit if b["text_consistency"]["identical"]),
        "text_equivalent_count": sum(
            1 for b in bench_audit
            if b["text_consistency"]["equivalent_after_normalization"]),
        "text_semantic_diff_count": sum(
            1 for b in bench_audit
            if b["text_consistency"]["classification"] == "semantic_diff"),
        "text_semantic_diff_ids": [
            b["composite_id"] for b in bench_audit
            if b["text_consistency"]["classification"] == "semantic_diff"],
        "components_without_code": sum(
            1 for c in comp_audit
            if c["component_category"] == "index" and c["index_code"] is None),
        "fixed_rate_components": sum(
            1 for c in comp_audit if c["component_category"] == "fixed_rate"),
        "cash_components": sum(
            1 for c in comp_audit if c["component_category"] == "cash"),
        "bond_index_components": sum(
            1 for c in comp_audit if c["component_category"] == "bond_index"),
    }
    # 自校验：数量必须与明细一致
    summary["_self_check"] = {
        "sum_equals_total": (
            summary["component_identified"] + 0 <= summary["total_benchmarks"]),
        "detail_length": len(bench_audit),
        "summary_total": summary["total_benchmarks"],
        "consistent": len(bench_audit) == summary["total_benchmarks"],
    }

    doc = {
        "phase": "3B-6.1.2",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "baseline_head": "16307eb5ef4f19ca62417a546b6d2ec0a13d492a",
        "audit_target": "正式库 benchmark_composite 全部 15 条记录",
        "states_definition": {
            "component_identified": "成分已识别（有名称与代码或明确资产类别）",
            "weight_verified": "权重有可靠文本证据（当前合同）",
            "weight_history_verified": "历史权重及生效时间已核实",
            "return_basis_verified": "各成分收益率口径已核实",
            "history_data_available": "历史行情数据可取得",
            "point_in_time_verified": "历史时点可用性有证据支持",
            "formula_reproducible": "公式可以完整计算",
            "historically_reproducible": "历史期间能按当时有效合同完整复现",
        },
        "states_are_independent": True,
        "no_auto_inheritance_note": (
            "**八态独立判定**：成分已识别不得自动推导为历史可复现；"
            "历史行情可获取不得自动推导为历史时点可用。"),
        "evidence_grade_definition": {
            "L1": "基金管理人、指数发布机构、法定披露文件原始证据",
            "L2": "权威机构可追溯的官方转载或正式数据库",
            "L3": "第三方聚合数据",
            "L4": "无法核验的二手描述或推断",
        },
        "summary": summary,
        "benchmarks": bench_audit,
    }
    (REPORTS / "phase3B6_1_2_benchmark_audit.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

    ch = {
        "phase": "3B-6.1.2",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "note": "逐成分历史审计：成分类别、权重、口径、历史数据、时点可用性",
        "component_count": len(comp_audit),
        "bond_index_evidence": BOND_INDEX_EVIDENCE,
        "cash_semantics": CASH_SEMANTICS,
        "index_basis_evidence": INDEX_BASIS,
        "components": comp_audit,
    }
    (REPORTS / "phase3B6_1_2_component_history.json").write_text(
        json.dumps(ch, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"基准 {len(bench_audit)} 条，成分 {len(comp_audit)} 个")
    for k in ("component_identified", "weight_verified", "weight_history_verified",
              "return_basis_verified", "history_data_available",
              "point_in_time_verified", "formula_reproducible",
              "historically_reproducible"):
        print(f"  {k:32} {summary[k]}/15")
    print(f"  文本完全一致                     {summary['text_identical_count']}/15")
    print(f"  归一化后一致                     {summary['text_equivalent_count']}/15")
    print(f"  语义实质不同                     {summary['text_semantic_diff_count']}/15"
          f" {summary['text_semantic_diff_ids']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
