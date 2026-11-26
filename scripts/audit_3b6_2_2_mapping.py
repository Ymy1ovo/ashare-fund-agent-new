"""阶段3B-6.2.2 基金—基准映射只读审计。

对正式库全部 120 个基金本体（按 ``fund_id`` 去重）执行
:func:`scripts.fund_benchmark_mapping_3b6_2_2.map_fund_benchmark`，
并单独审计 15 条复合基准。

**只读**：以 ``mode=ro`` 打开数据库。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from scripts.benchmark_taxonomy_3b6_2_1 import (  # noqa: E402
    CATEGORY_LABELS, REQUIRED_CATEGORIES)
from scripts.fund_benchmark_mapping_3b6_2_2 import (  # noqa: E402
    COMPOSITE_RULES, CONFIDENCE_LEVELS, CONFIDENCE_NOTE,
    FUND_CATEGORY_MAPPING_RULES, MAPPING_RULE_VERSION, PROMOTION_FORBIDDEN,
    map_fund_benchmark)

REPORTS = ROOT / "reports"
DB = Path(settings.database_path)

LIFECYCLE_MAP = {
    "active": "existing",
    "existing": "existing",
    "terminated": "terminated",
    "unknown": "unknown_status",
}


def db_fingerprint() -> dict:
    raw = DB.read_bytes()
    return {
        "db_path": str(DB),
        "db_sha256": hashlib.sha256(raw).hexdigest(),
        "db_bytes": len(raw),
        "db_mtime": datetime.fromtimestamp(DB.stat().st_mtime).isoformat(
            timespec="seconds"),
    }


def load_funds(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute("""
        SELECT fund_id, fund_code_primary, fund_name, fund_full_name,
               fund_type_l1, fund_type_l2, is_index_fund, lifecycle_status,
               benchmark, established_date
        FROM fund_master ORDER BY fund_id
    """).fetchall()
    shares = defaultdict(list)
    for r in con.execute("""
        SELECT fund_id, share_class_code, share_class_type, is_primary
        FROM fund_share_classes ORDER BY fund_id, share_class_id
    """):
        shares[r[0]].append({"code": r[1], "type": r[2],
                              "is_primary": bool(r[3])})

    funds = []
    for r in rows:
        bucket = LIFECYCLE_MAP.get(r[7], "unknown_status")
        funds.append({
            "fund_id": r[0], "fund_code": r[1], "fund_name": r[2],
            "fund_full_name": r[3], "fund_type_l1": r[4], "fund_type_l2": r[5],
            "is_index_fund": r[6], "lifecycle_status": r[7],
            "lifecycle_bucket": bucket, "benchmark": r[8],
            "established_date": r[9],
            "share_codes": [s["code"] for s in shares.get(r[0], [])],
            "share_classes": shares.get(r[0], []),
        })
    return funds


def load_index_info(con: sqlite3.Connection) -> dict:
    info = {}
    for r in con.execute("""
        SELECT index_code, index_name, index_short_name, return_basis,
               data_status, publisher
        FROM index_master ORDER BY index_code
    """):
        cov = con.execute(
            "SELECT COUNT(*), MIN(trade_date), MAX(trade_date) "
            "FROM index_daily WHERE index_code=?", (r[0],)).fetchone()
        info[r[0]] = {
            "index_code": r[0], "index_name": r[1], "index_short_name": r[2],
            "return_basis": r[3], "data_status": r[4], "publisher": r[5],
            "rows": cov[0], "date_min": cov[1], "date_max": cov[2],
            "has_series": cov[0] > 0,
        }
    return info


def load_composites(con: sqlite3.Connection) -> list[dict]:
    comps = con.execute("""
        SELECT composite_id, benchmark_name, benchmark_raw_text,
               evidence_source, is_complete, is_reproducible, missing_reason
        FROM benchmark_composite ORDER BY composite_id
    """).fetchall()
    parts = defaultdict(list)
    for r in con.execute("""
        SELECT composite_id, component_type, index_code, component_label,
               weight, weight_evidence, weight_effective_from,
               weight_effective_to, data_available
        FROM benchmark_composite_component
        ORDER BY composite_id, component_id
    """):
        parts[r[0]].append({
            "component_type": r[1], "index_code": r[2],
            "component_label": r[3],
            "weight": None if r[4] is None else float(r[4]),
            "weight_evidence": r[5],
            "weight_effective_from": r[6], "weight_effective_to": r[7],
            "data_available": bool(r[8]),
        })
    return [{
        "composite_id": r[0], "benchmark_name": r[1], "raw_text": r[2],
        "evidence_source": r[3], "is_complete": bool(r[4]),
        "is_reproducible": bool(r[5]), "missing_reason": r[6],
        "components": parts.get(r[0], []),
    } for r in comps]


def audit_composites(composites: list[dict],
                     index_info: dict) -> tuple[list[dict], dict]:
    """逐条审计 15 条复合基准。"""
    results = []
    for c in composites:
        comps = c["components"]
        asset_weight = sum(p["weight"] for p in comps
                            if p["weight"] is not None
                            and p["component_type"] != "fixed_rate")
        fixed_weight = sum(p["weight"] for p in comps
                            if p["weight"] is not None
                            and p["component_type"] == "fixed_rate")
        has_effective = sum(1 for p in comps if p["weight_effective_from"])

        uncomputable = []
        for p in comps:
            t = p["component_type"]
            if t == "index":
                code = p["index_code"]
                if not code:
                    uncomputable.append(f"{p['component_label']}（未映射代码）")
                elif code not in index_info:
                    uncomputable.append(f"{p['component_label']}（指数未接入）")
                elif index_info[code]["return_basis"] == "unknown":
                    uncomputable.append(
                        f"{p['component_label']}（收益口径 unknown）")
            elif t == "bond_index":
                uncomputable.append(f"{p['component_label']}（债券指数未接入）")
            elif t == "cash":
                uncomputable.append(f"{p['component_label']}（现金利率无序列）")
            elif t == "fixed_rate":
                uncomputable.append(f"{p['component_label']}（折算规则未知）")
            else:
                uncomputable.append(f"{p['component_label']}（类型未知）")

        results.append({
            "composite_id": c["composite_id"],
            "benchmark_name": c["benchmark_name"],
            "raw_text": c["raw_text"],
            "evidence_source": c["evidence_source"],
            "evidence_grade": "L3",
            "component_count": len(comps),
            "components": comps,
            "component_types": dict(Counter(p["component_type"] for p in comps)),
            "asset_weight_sum": round(asset_weight, 6),
            "fixed_rate_weight_sum": round(fixed_weight, 6),
            "unexplained_residual": (
                round(1.0 - asset_weight, 6)
                if 0 < asset_weight < 1.0 else None),
            "components_with_effective_from": has_effective,
            "historical_weights_verified": has_effective == len(comps) > 0,
            "uncomputable_components": uncomputable,
            "contract_reproducible": False,
            "reproducible_reason": (
                "**存在不可计算成分**：" + "；".join(uncomputable)
                if uncomputable else "**缺 L1 官方合同与历史权重证据**"),
            "db_claimed": {
                "is_complete": c["is_complete"],
                "is_reproducible": c["is_reproducible"],
                "missing_reason": c["missing_reason"],
            },
            "simplified_to_single_index": False,
            "rule_version": COMPOSITE_RULES["rule_version"],
        })

    summary = {
        "total": len(results),
        "total_components": sum(r["component_count"] for r in results),
        "all_not_reproducible": all(not r["contract_reproducible"]
                                     for r in results),
        "with_uncomputable": sum(1 for r in results
                                  if r["uncomputable_components"]),
        "with_historical_weights": sum(
            1 for r in results if r["historical_weights_verified"]),
        "with_unexplained_residual": sum(
            1 for r in results if r["unexplained_residual"] is not None),
        "component_type_counts": dict(Counter(
            t for r in results for t in r["component_types"]
            for _ in range(r["component_types"][t]))),
        "any_simplified": any(r["simplified_to_single_index"] for r in results),
    }
    return results, summary


def main() -> int:
    REPORTS.mkdir(exist_ok=True)
    before = db_fingerprint()

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    funds = load_funds(con)
    index_info = load_index_info(con)
    composites = load_composites(con)
    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    fk = len(con.execute("PRAGMA foreign_key_check").fetchall())
    con.close()

    available_codes = {k for k, v in index_info.items() if v["has_series"]}

    # ---------------- 逐基金映射 ----------------
    records = []
    for f in funds:
        # 研究规则：仅当合同基准含已映射指数时才声明
        rule = None
        if f["benchmark"]:
            rule = {
                "rule_version": MAPPING_RULE_VERSION,
                "selection_reason": (
                    f"按 {f['lifecycle_bucket']} 基金的类别规则，"
                    "取合同基准中已映射的股票/综合指数作为研究比较序列"),
            }
        rec = map_fund_benchmark(
            f,
            index_info=index_info,
            available_index_codes=available_codes,
            research_rule=rule,
            substitute_selection=None,      # 本轮不提供替代选择
            contract_evidence_grade="L3",
            has_official_contract_file=False,
            has_historical_weights=False,
        )
        rec["share_class_count"] = len(f.get("share_classes", []))
        records.append(rec)

    # ---------------- 统计 ----------------
    def cnt(pred):
        return sum(1 for r in records if pred(r))

    cat_counts = Counter(r["category"] for r in records)
    life_counts = Counter(r["lifecycle_bucket"] for r in records)
    conf_counts = Counter(r["confidence"] for r in records)

    per_category = {}
    for cat in REQUIRED_CATEGORIES:
        sub = [r for r in records if r["category"] == cat]
        per_category[cat] = {
            "label": CATEGORY_LABELS[cat],
            "fund_count": len(sub),
            "rule_id": FUND_CATEGORY_MAPPING_RULES.get(cat, {}).get("rule_id"),
            "contract_available": sum(
                1 for r in sub if r["benchmarks"]["contract"]["available"]),
            "contract_candidate": sum(
                1 for r in sub
                if r["benchmarks"]["contract"]["name"]),
            "research_candidate": sum(
                1 for r in sub if r["benchmarks"]["research"]["candidate"]),
            "research_available": sum(
                1 for r in sub if r["benchmarks"]["research"]["available"]),
            "substitute_candidate": sum(
                1 for r in sub if r["benchmarks"]["substitute"]["candidate"]),
            "substitute_available": sum(
                1 for r in sub if r["benchmarks"]["substitute"]["available"]),
            "allowed_to_next_stage": sum(
                1 for r in sub if r["allowed_to_next_stage"]),
            "confidence_distribution": dict(Counter(r["confidence"]
                                                      for r in sub)),
            "no_usable": sum(1 for r in sub if r["max_kind"] == "none"),
        }

    summary = {
        "mapping_rule_version": MAPPING_RULE_VERSION,
        "total_funds_by_fund_id": len(records),
        "total_share_classes": sum(r["share_class_count"] for r in records),
        "funds_with_multiple_shares": sum(
            1 for r in records if r["share_class_count"] > 1),
        "lifecycle": {
            "existing": life_counts.get("existing", 0),
            "terminated": life_counts.get("terminated", 0),
            "unknown_status": life_counts.get("unknown_status", 0),
            "total": len(records),
            "sum_equals_total": (life_counts.get("existing", 0)
                                  + life_counts.get("terminated", 0)
                                  + life_counts.get("unknown_status", 0)
                                  == len(records)),
            "note": ("**状态未知基金不得当作存续基金**；"
                      "库中无明确存续标记"),
        },
        "category_counts": dict(cat_counts),
        "category_labels": CATEGORY_LABELS,
        "required_categories_covered": sorted(set(cat_counts)
                                                & set(REQUIRED_CATEGORIES)),
        "required_categories_missing": sorted(set(REQUIRED_CATEGORIES)
                                                - set(cat_counts)),
        "confidence_distribution": dict(conf_counts),
        "confidence_note": CONFIDENCE_NOTE,
        "contract": {
            "total_with_text": cnt(
                lambda r: bool(r["benchmarks"]["contract"]["name"])),
            "available": cnt(
                lambda r: r["benchmarks"]["contract"]["available"]),
        },
        "research": {
            "candidate": cnt(
                lambda r: r["benchmarks"]["research"]["candidate"]),
            "available": cnt(
                lambda r: r["benchmarks"]["research"]["available"]),
        },
        "substitute": {
            "candidate": cnt(
                lambda r: r["benchmarks"]["substitute"]["candidate"]),
            "available": cnt(
                lambda r: r["benchmarks"]["substitute"]["available"]),
        },
        "allowed_to_next_stage": cnt(lambda r: r["allowed_to_next_stage"]),
        "no_usable_benchmark": cnt(lambda r: r["max_kind"] == "none"),
        "index_return_basis": {
            "total": len(index_info),
            "unknown": sum(1 for v in index_info.values()
                            if v["return_basis"] == "unknown"),
            "verified": sum(1 for v in index_info.values()
                             if v["return_basis"] != "unknown"),
            "all_unknown": all(v["return_basis"] == "unknown"
                                for v in index_info.values()),
        },
        "unavailable_reason_buckets": dict(Counter(
            r["benchmarks"]["contract"]["unavailable_reason"]
            for r in records if not r["benchmarks"]["contract"]["available"]
        ).most_common(15)),
        "_self_check": {
            "category_sum_equals_total": (
                sum(cat_counts.values()) == len(records)),
            "lifecycle_sum_equals_total": (
                life_counts.get("existing", 0) + life_counts.get("terminated", 0)
                + life_counts.get("unknown_status", 0) == len(records)),
            "allowed_le_total": cnt(lambda r: r["allowed_to_next_stage"])
                <= len(records),
        },
    }

    composite_results, composite_summary = audit_composites(composites,
                                                              index_info)

    after = db_fingerprint()
    doc = {
        "phase": "3B-6.2.2",
        "task": "场外公募基金与基准映射规则实现",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "baseline_head": "e9fcd3cd197c7f58d3267d3a20825caa6e320548",
        "mapping_rule_version": MAPPING_RULE_VERSION,
        "read_only": True,
        "db_before": before,
        "db_after": after,
        "db_unchanged": before["db_sha256"] == after["db_sha256"],
        "integrity_check": integrity,
        "foreign_key_violations": fk,
        "confidence_levels": CONFIDENCE_LEVELS,
        "confidence_note": CONFIDENCE_NOTE,
        "promotion_forbidden": {
            f"{k[0]} -> {k[1]}": v for k, v in PROMOTION_FORBIDDEN.items()},
        "composite_rules": COMPOSITE_RULES,
        "category_mapping_rules": FUND_CATEGORY_MAPPING_RULES,
        "index_info": index_info,
        "summary": summary,
        "per_category": per_category,
        "composites_summary": composite_summary,
        "composites": composite_results,
        "funds": records,
    }

    (REPORTS / "phase3B6_2_2_mapping_audit.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

    rules_doc = {
        "phase": "3B-6.2.2",
        "mapping_rule_version": MAPPING_RULE_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "benchmark_kinds": {
            "contract": "合同业绩比较基准（需 L1）",
            "research": "研究评价基准（需收益口径确认 + 选择规则）",
            "substitute": "替代基准（需调用方显式选择）",
        },
        "promotion_forbidden": {
            f"{k[0]} -> {k[1]}": v for k, v in PROMOTION_FORBIDDEN.items()},
        "confidence_levels": CONFIDENCE_LEVELS,
        "confidence_note": CONFIDENCE_NOTE,
        "category_mapping_rules": FUND_CATEGORY_MAPPING_RULES,
        "composite_rules": COMPOSITE_RULES,
        "required_categories": REQUIRED_CATEGORIES,
        "lifecycle_mapping": LIFECYCLE_MAP,
    }
    (REPORTS / "phase3B6_2_2_mapping_rules.json").write_text(
        json.dumps(rules_doc, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---------------- 打印 ----------------
    print(f"映射规则版本 {MAPPING_RULE_VERSION}")
    print(f"基金 {len(records)} 只 / 份额 {summary['total_share_classes']}")
    lc = summary["lifecycle"]
    print(f"  生命周期：存续 {lc['existing']} / 终止 {lc['terminated']} / "
          f"状态未知 {lc['unknown_status']}"
          f"（守恒 {lc['sum_equals_total']}）")
    print()
    print("置信度分布：" + str(summary["confidence_distribution"]))
    print()
    print("三类基准：")
    print(f"  合同：有文本 {summary['contract']['total_with_text']} / "
          f"可用 {summary['contract']['available']}")
    print(f"  研究：候选 {summary['research']['candidate']} / "
          f"可用 {summary['research']['available']}")
    print(f"  替代：候选 {summary['substitute']['candidate']} / "
          f"可用 {summary['substitute']['available']}")
    print(f"  允许进入下一阶段 {summary['allowed_to_next_stage']}")
    print(f"  无任何可用基准 {summary['no_usable_benchmark']}")
    print()
    print("七类基金映射：")
    print(f"  {'类别':18} {'数量':>4} {'合同可用':>8} {'研究候选':>8} "
          f"{'研究可用':>8} {'替代可用':>8} {'下一阶段':>8}")
    for cat in REQUIRED_CATEGORIES:
        pc = per_category[cat]
        print(f"  {cat:18} {pc['fund_count']:>4} {pc['contract_available']:>8} "
              f"{pc['research_candidate']:>8} {pc['research_available']:>8} "
              f"{pc['substitute_available']:>8} {pc['allowed_to_next_stage']:>8}")
    print()
    print(f"复合基准：{composite_summary['total']} 条 / "
          f"{composite_summary['total_components']} 成分 / "
          f"可复现 {sum(1 for r in composite_results if r['contract_reproducible'])}")
    print(f"  有不可计算成分 {composite_summary['with_uncomputable']}")
    print(f"  有历史权重 {composite_summary['with_historical_weights']}")
    print(f"  简化成单一指数 {composite_summary['any_simplified']}")
    print()
    print(f"数据库：{before['db_sha256'][:16]}… → {after['db_sha256'][:16]}… "
          f"{'一致' if doc['db_unchanged'] else '不一致'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
