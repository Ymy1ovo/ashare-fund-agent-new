"""阶段3B-6.2.1 双向映射审计（只读）。

从正式库读取基金/份额/指数/基准，用 :mod:`scripts.benchmark_taxonomy_3b6_2_1`
的分类与解析逻辑逐条判定，输出：

- ``reports/phase3B6_2_1_mapping_audit.json``

**只读**：以 ``mode=ro`` 打开数据库，不写任何表。
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
    BENCHMARK_KINDS, CATEGORY_LABELS, EVIDENCE_GRADES, REQUIRED_CATEGORIES,
    assess_benchmark_usability, classify_fund, get_category_rules,
    parse_benchmark_text)

REPORTS = ROOT / "reports"
DB = Path(settings.database_path)


def db_fingerprint() -> dict:
    raw = DB.read_bytes()
    return {
        "db_path": str(DB),
        "db_sha256": hashlib.sha256(raw).hexdigest(),
        "db_bytes": len(raw),
        "db_mtime": datetime.fromtimestamp(DB.stat().st_mtime).isoformat(
            timespec="seconds"),
    }


def load_funds(con: sqlite3.Connection) -> tuple[list[dict], dict]:
    """读基金本体，按 fund_id 去重（A/C 份额归并）。"""
    rows = con.execute("""
        SELECT fund_id, fund_code_primary, fund_name, fund_full_name,
               fund_company, fund_type_l1, fund_type_l2, is_index_fund,
               established_date, terminated_date, lifecycle_status, benchmark,
               tracking_index
        FROM fund_master ORDER BY fund_id
    """).fetchall()

    share_rows = con.execute("""
        SELECT fund_id, share_class_code, share_class_name, share_class_type,
               is_primary
        FROM fund_share_classes ORDER BY fund_id, share_class_id
    """).fetchall()

    shares_by_fund = defaultdict(list)
    for r in share_rows:
        shares_by_fund[r[0]].append({
            "share_class_code": r[1], "share_class_name": r[2],
            "share_class_type": r[3], "is_primary": bool(r[4]),
        })

    funds = []
    for r in rows:
        funds.append({
            "fund_id": r[0],
            "fund_code": r[1],
            "fund_name": r[2],
            "fund_full_name": r[3],
            "fund_company": r[4],
            "fund_type_l1": r[5],
            "fund_type_l2": r[6],
            "is_index_fund": r[7],
            "established_date": r[8],
            "terminated_date": r[9],
            "lifecycle_status": r[10],
            "benchmark": r[11],
            "tracking_index": r[12],
            "share_classes": shares_by_fund.get(r[0], []),
        })

    share_stats = {
        "total_share_classes": len(share_rows),
        "distinct_fund_ids_with_shares": len(shares_by_fund),
        "funds_with_multiple_shares": sum(
            1 for v in shares_by_fund.values() if len(v) > 1),
    }
    return funds, share_stats


def load_indexes(con: sqlite3.Connection) -> dict:
    rows = con.execute("""
        SELECT index_code, index_name, index_short_name, publisher,
               return_basis, data_status
        FROM index_master ORDER BY index_code
    """).fetchall()
    coverage = {}
    for r in con.execute("""
        SELECT index_code, COUNT(*), MIN(trade_date), MAX(trade_date)
        FROM index_daily GROUP BY index_code
    """):
        coverage[r[0]] = {"rows": r[1], "date_min": r[2], "date_max": r[3]}
    return {
        "indexes": [{
            "index_code": r[0], "index_name": r[1], "index_short_name": r[2],
            "publisher": r[3], "return_basis": r[4], "data_status": r[5],
            "coverage": coverage.get(r[0]),
            "has_return_series": coverage.get(r[0], {}).get("rows", 0) > 0,
        } for r in rows],
        "available_codes": {r[0] for r in rows
                             if coverage.get(r[0], {}).get("rows", 0) > 0},
    }


def load_composites(con: sqlite3.Connection) -> list[dict]:
    comps = con.execute("""
        SELECT composite_id, benchmark_name, benchmark_raw_text,
               evidence_source, is_complete, is_reproducible, missing_reason
        FROM benchmark_composite ORDER BY composite_id
    """).fetchall()
    parts = con.execute("""
        SELECT composite_id, component_type, index_code, component_label,
               weight, weight_evidence, weight_effective_from,
               weight_effective_to, data_available
        FROM benchmark_composite_component ORDER BY composite_id, component_id
    """).fetchall()
    by = defaultdict(list)
    for p in parts:
        by[p[0]].append({
            "component_type": p[1], "index_code": p[2], "component_label": p[3],
            "weight": None if p[4] is None else float(p[4]),
            "weight_evidence": p[5],
            "weight_effective_from": p[6], "weight_effective_to": p[7],
            "data_available": bool(p[8]),
        })
    return [{
        "composite_id": r[0], "benchmark_name": r[1],
        "benchmark_raw_text": r[2], "evidence_source": r[3],
        "is_complete": bool(r[4]), "is_reproducible": bool(r[5]),
        "missing_reason": r[6],
        "components": by.get(r[0], []),
    } for r in comps]


def main() -> int:
    REPORTS.mkdir(exist_ok=True)
    before = db_fingerprint()

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    funds, share_stats = load_funds(con)
    idx = load_indexes(con)
    composites = load_composites(con)
    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    fk = len(con.execute("PRAGMA foreign_key_check").fetchall())
    con.close()

    available_codes = idx["available_codes"]
    # index_code -> return_basis（全部来自 index_master，不修改）
    basis_map = {i["index_code"]: i["return_basis"] for i in idx["indexes"]}

    # ---------------- 逐基金分类与基准判定 ----------------
    records = []
    for f in funds:
        cls = classify_fund(f)
        parsed = parse_benchmark_text(f["benchmark"])

        # 合同基准证据：正式库来源为 platform（第三方平台），等级 L3
        grade = "L3"
        has_official = False

        rule = cls["required_category"]
        research_rule = {
            "rule_version": "3B-6.2.1-v1",
            "selection_reason": (
                f"按类别 {rule} 的基准选择规则，选取合同基准中"
                "已映射的股票/综合指数作为研究比较序列"),
            "applicable_category": rule,
            "divergence_from_contract": (
                "研究基准只覆盖合同基准中的股票指数部分，"
                "不含债券指数/现金/固定收益率成分，因此不等于合同基准"),
        }
        usability = assess_benchmark_usability(
            parsed,
            available_index_codes=available_codes,
            category=cls["required_category"],
            index_return_basis=basis_map,
            contract_evidence_grade=grade,
            has_official_contract_file=has_official,
            has_historical_weights=False,
            research_rule=research_rule,
            substitute_selection=None,
        )

        # 货币基金特殊口径
        money_market_special = cls["required_category"] == "money_market"
        if money_market_special:
            usability["reasons"].append(
                "货币基金使用万份收益/七日年化独立口径，**不与普通净值基金混算**")

        records.append({
            "fund_id": f["fund_id"],
            "fund_code": f["fund_code"],
            "fund_name": f["fund_name"],
            "fund_company": f["fund_company"],
            "lifecycle_status": f["lifecycle_status"],
            "established_date": f["established_date"],
            "terminated_date": f["terminated_date"],
            "classification": cls,
            "share_class_count": len(f["share_classes"]),
            "share_classes": f["share_classes"],
            "contract_benchmark": {
                "raw_text": parsed["raw_text"],
                "section": "正式库 fund_master.benchmark",
                "evidence_grade": grade,
                "evidence_grade_reason": (
                    "来源为第三方平台披露文本（akshare.fund_name_em 等），"
                    "**未取得基金合同/招募说明书原文**，不能作为 L1 合同证据"),
                "has_official_contract_file": has_official,
                "effective_from": None,
                "effective_to": None,
                "version_count": 1,
                "note": ("**历史版本未知**：正式库只存当前文本，"
                          "无法判断成立以来是否变更"),
            },
            "benchmark_parse": parsed,
            "usability": usability,
        })

    # ---------------- 统计（全部由明细生成） ----------------
    def by_category(pred):
        return sum(1 for r in records if pred(r))

    # ---- 生命周期互斥分类（3B-6.2.1.1 修正）----
    LIFECYCLE_MAP = {
        "active": "existing",
        "existing": "existing",
        "terminated": "terminated",
        "unknown": "unknown_status",
    }
    lifecycle_buckets = Counter()
    lifecycle_unmapped = Counter()
    for r in records:
        raw = r["lifecycle_status"]
        bucket = LIFECYCLE_MAP.get(raw)
        if bucket is None:
            lifecycle_unmapped[raw] += 1
            bucket = "unknown_status"
        r["lifecycle_bucket"] = bucket
        lifecycle_buckets[bucket] += 1

    existing = [r for r in records if r["lifecycle_bucket"] == "existing"]
    terminated = [r for r in records if r["lifecycle_bucket"] == "terminated"]
    unknown_status = [r for r in records if r["lifecycle_bucket"] == "unknown_status"]

    cat_counts = Counter(r["classification"]["required_category"] for r in records)
    cat_counts_existing = Counter(
        r["classification"]["required_category"] for r in existing)
    cat_counts_unknown = Counter(
        r["classification"]["required_category"] for r in unknown_status)

    has_benchmark = by_category(lambda r: bool(r["benchmark_parse"]["raw_text"]))
    has_benchmark_existing = sum(1 for r in existing
                                  if r["benchmark_parse"]["raw_text"])

    has_index_code = by_category(
        lambda r: any(c["index_code"] for c in r["benchmark_parse"]["components"]))
    has_index_code_existing = sum(
        1 for r in existing
        if any(c["index_code"] for c in r["benchmark_parse"]["components"]))

    has_series = by_category(lambda r: r["usability"]["substitute_benchmark_usable"])
    has_series_existing = sum(
        1 for r in existing if r["usability"]["substitute_benchmark_usable"])

    contract_usable = by_category(lambda r: r["usability"]["contract_benchmark_usable"])
    fully_repro = by_category(lambda r: r["usability"]["fully_reproducible"])
    research_candidate = by_category(
        lambda r: r["usability"]["research_benchmark_candidate"])
    research_usable = by_category(lambda r: r["usability"]["research_benchmark_usable"])
    substitute_candidate = by_category(
        lambda r: r["usability"]["substitute_benchmark_candidate"])
    substitute_usable = by_category(
        lambda r: r["usability"]["substitute_benchmark_usable"])
    substitute_only = by_category(
        lambda r: r["usability"]["max_kind"] == "substitute")
    none_usable = by_category(lambda r: r["usability"]["max_kind"] == "none")
    has_index_observation = by_category(
        lambda r: r["usability"]["has_index_observation"])
    has_verified_basis = by_category(
        lambda r: r["usability"]["has_verified_return_basis"])

    summary = {
        "total_funds_by_fund_id": len(records),
        "total_share_classes": share_stats["total_share_classes"],
        "funds_with_multiple_shares": share_stats["funds_with_multiple_shares"],
        "survivorship_note": (
            "**幸存者偏差声明**：正式库含 41 只 terminated 基金，"
            "但全部无分类与基准文本（fund_type_l1 为 NULL）；"
            "存续基金 79 只。任何只基于存续基金的统计都存在幸存者偏差。"),
        "lifecycle": {
            "existing": len(existing),
            "terminated": len(terminated),
            "unknown_status": len(unknown_status),
            "total": len(records),
            "sum_equals_total": (len(existing) + len(terminated)
                                  + len(unknown_status) == len(records)),
            "raw_value_counts": dict(Counter(
                r["lifecycle_status"] for r in records)),
            "mapping_rule": {
                "active": "existing",
                "existing": "existing",
                "terminated": "terminated",
                "unknown": "unknown_status",
                "_note": ("**unknown 字面含义即状态未知，不得当作明确存续**；"
                            "当前库中不存在 active/existing 值"),
            },
            "unmapped_raw_values": dict(lifecycle_unmapped),
            "note": ("**数据库中实际只有 unknown（79 只）与 terminated（41 只）"
                      "两种取值**，没有任何基金被明确标记为存续。"
                      "此前报告把 79 只 unknown 当作「存续」，属统计语义错误。"),
        },
        "category_counts_all": dict(cat_counts),
        "category_counts_existing": dict(cat_counts_existing),
        "category_counts_unknown_status": dict(cat_counts_unknown),
        "category_labels": CATEGORY_LABELS,
        "required_categories_covered": sorted(
            set(cat_counts) & set(REQUIRED_CATEGORIES)),
        "required_categories_missing": sorted(
            set(REQUIRED_CATEGORIES) - set(cat_counts)),
        "has_benchmark_text": has_benchmark,
        "has_benchmark_text_existing": has_benchmark_existing,
        "_existing_scope_note": (
            "**`*_existing` 系列字段统计的是明确标记存续的基金，当前库中为 0 只**，"
            "故这些字段均为 0；有意义的对照口径是 `primary_scope`"),
        "has_index_code": has_index_code,
        "has_index_code_existing": has_index_code_existing,
        "has_usable_return_series": has_series,
        "has_usable_return_series_existing": has_series_existing,
        "contract_benchmark_usable": contract_usable,
        "fully_reproducible": fully_repro,
        "has_index_observation": has_index_observation,
        "has_verified_return_basis": has_verified_basis,
        "research_benchmark_candidate": research_candidate,
        "research_benchmark_usable": research_usable,
        "substitute_benchmark_candidate": substitute_candidate,
        "substitute_benchmark_usable": substitute_usable,
        "substitute_only": substitute_only,
        "no_usable_benchmark": none_usable,
        "component_type_counts": dict(Counter(
            c["component_type"]
            for r in records for c in r["benchmark_parse"]["components"])),
        "indexes": {
            "total": len(idx["indexes"]),
            "with_return_series": sum(
                1 for i in idx["indexes"] if i["has_return_series"]),
            "return_basis_unknown": sum(
                1 for i in idx["indexes"] if i["return_basis"] == "unknown"),
            "detail": idx["indexes"],
        },
        "composites": {
            "total": len(composites),
            "total_components": sum(len(c["components"]) for c in composites),
            "components_with_effective_from": sum(
                1 for c in composites for p in c["components"]
                if p["weight_effective_from"]),
            "detail": composites,
        },
    }
    # ---- 主口径 vs 降级口径（幸存者偏差与数据充分性）----
    primary = [r for r in records
               if r["classification"]["classification_source"] == "primary_field"]
    degraded = [r for r in records if r["classification"]["data_insufficient"]]

    summary["classification_quality"] = {
        "primary_field_funds": len(primary),
        "partial_field_funds": sum(
            1 for r in records
            if r["classification"]["classification_source"] == "partial_field"),
        "name_only_degraded_funds": len(degraded),
        "confidence_counts": dict(Counter(
            r["classification"]["classification_confidence"] for r in records)),
        "note": ("**降级分类的基金（分类字段全空）只能靠名称推断，"
                  "其类别标注不得用于正式统计口径**"),
    }
    summary["primary_category_counts"] = dict(Counter(
        r["classification"]["required_category"] for r in primary))
    summary["degraded_category_counts"] = dict(Counter(
        r["classification"]["required_category"] for r in degraded))

    # 主口径下的基准可用性（可信统计）
    summary["primary_scope"] = {
        "total_funds": len(primary),
        "has_benchmark_text": sum(
            1 for r in primary if r["benchmark_parse"]["raw_text"]),
        "has_index_code": sum(
            1 for r in primary
            if any(c["index_code"] for c in r["benchmark_parse"]["components"])),
        "has_usable_return_series": sum(
            1 for r in primary if r["usability"]["substitute_benchmark_usable"]),
        "contract_benchmark_usable": sum(
            1 for r in primary if r["usability"]["contract_benchmark_usable"]),
        "fully_reproducible": sum(
            1 for r in primary if r["usability"]["fully_reproducible"]),
        "has_index_observation": sum(
            1 for r in primary if r["usability"]["has_index_observation"]),
        "has_verified_return_basis": sum(
            1 for r in primary if r["usability"]["has_verified_return_basis"]),
        "research_benchmark_candidate": sum(
            1 for r in primary
            if r["usability"]["research_benchmark_candidate"]),
        "research_benchmark_usable": sum(
            1 for r in primary if r["usability"]["research_benchmark_usable"]),
        "substitute_benchmark_candidate": sum(
            1 for r in primary
            if r["usability"]["substitute_benchmark_candidate"]),
        "substitute_benchmark_usable": sum(
            1 for r in primary if r["usability"]["substitute_benchmark_usable"]),
        "substitute_only": sum(
            1 for r in primary if r["usability"]["max_kind"] == "substitute"),
        "no_usable_benchmark": sum(
            1 for r in primary if r["usability"]["max_kind"] == "none"),
    }

    # 自校验
    summary["_self_check"] = {
        "category_sum_equals_total": (
            sum(cat_counts.values()) == len(records)),
        "lifecycle_three_buckets_sum_equals_total": (
            len(existing) + len(terminated) + len(unknown_status) == len(records)),
        "research_plus_none_le_total": (
            research_usable + none_usable <= len(records)),
    }

    after = db_fingerprint()

    doc = {
        "phase": "3B-6.2.1",
        "task": "场外公募基金基准分类体系映射审计",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "baseline_head": "13e95a26bfe94f5574febc263304c7fbbc2bc7ab",
        "read_only": True,
        "db_before": before,
        "db_after": after,
        "db_unchanged": before["db_sha256"] == after["db_sha256"],
        "integrity_check": integrity,
        "foreign_key_violations": fk,
        "benchmark_kinds": BENCHMARK_KINDS,
        "evidence_grades": EVIDENCE_GRADES,
        "required_categories": REQUIRED_CATEGORIES,
        "category_rules": {c: get_category_rules(c) for c in REQUIRED_CATEGORIES},
        "summary": summary,
        "funds": records,
    }

    out = REPORTS / "phase3B6_2_1_mapping_audit.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"基金 {len(records)} 只（fund_id 去重）/ 份额 {share_stats['total_share_classes']}")
    print(f"  生命周期：明确存续 {len(existing)} / 终止 {len(terminated)} / "
          f"状态未知 {len(unknown_status)}"
          f"（合计 {len(existing)+len(terminated)+len(unknown_status)}"
          f" {'=' if summary['lifecycle']['sum_equals_total'] else '!='} {len(records)}）")
    print(f"  有基准文本 {has_benchmark}")
    print(f"  能识别指数代码 {has_index_code}")
    print(f"  有可用收益序列 {has_series}")
    print(f"  合同基准可用 {contract_usable}")
    print(f"  完整可复现 {fully_repro}")
    print(f"  有指数点位 {has_index_observation}")
    print(f"  收益口径已确认 {has_verified_basis}")
    print(f"  研究基准候选 {research_candidate} / 真正可用 {research_usable}")
    print(f"  替代基准候选 {substitute_candidate} / 真正可用 {substitute_usable}")
    print(f"  仅替代基准 {substitute_only}")
    print(f"  无可用基准 {none_usable}")
    print()
    print(f"分类质量：主口径 {len(primary)} / 降级 {len(degraded)}")
    print()
    print("主口径统计：" + str(summary["primary_scope"]))
    print()
    print("类别分布：")
    for c in REQUIRED_CATEGORIES:
        print(f"  {c:18} {cat_counts.get(c, 0):3}  （状态未知 {cat_counts_unknown.get(c, 0)}）")
    print()
    print(f"数据库指纹：{before['db_sha256'][:16]}… → {after['db_sha256'][:16]}… "
          f"{'一致' if doc['db_unchanged'] else '不一致'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
