"""阶段3B-6.1.2 时点可用性审计（只读）。

对 15 条基准的八态独立判定结果做时点可用性专项汇总，
并落盘 ``reports/phase3B6_1_2_point_in_time_audit.json``。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def main() -> int:
    audit = json.loads(
        (REPORTS / "phase3B6_1_2_benchmark_audit.json")
        .read_text(encoding="utf-8"))
    bond = json.loads(
        (REPORTS / "phase3B6_1_2_bond_index_audit.json")
        .read_text(encoding="utf-8"))

    # 逐基准时点可用性
    pit_benchmarks = []
    for b in audit["benchmarks"]:
        pit_benchmarks.append({
            "composite_id": b["composite_id"],
            "benchmark_name": b["benchmark_name"],
            "component_count": b["component_count"],
            "component_types": b["components_by_type"],
            "point_in_time_verified": b["states"]["point_in_time_verified"],
            "observation_date_evidence": "无（所有成分均无发布日期/时刻证据）",
            "publication_date_evidence": "无",
            "available_date_evidence": "无",
            "recommended_conservative_lag": "T+1（**建议值，未验证**）",
            "reason": b["blockers"][-1] if b["blockers"] else "未知",
            "earliest_reproducible_date": b["earliest_reproducible_date"],
            "latest_reproducible_date": b["latest_reproducible_date"],
        })

    doc = {
        "phase": "3B-6.1.2",
        "task": "point_in_time_audit",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "baseline_head": "16307eb5ef4f19ca62417a546b6d2ec0a13d492a",
        "three_dates_definition": {
            "observation_date": "收益率/点位对应的观察日期",
            "publication_date": "数据实际公开日期",
            "available_date": "研究系统允许使用的最早日期",
            "warning": "**无可靠证据时不得把三者默认视为相同**",
        },
        "evidence_by_component_type": {
            "index": {
                "observation_date": "有（接口日期字段）",
                "publication_date": "**无官方时刻证据**",
                "available_date": "**无法证明**",
                "source": "3B-6.1.1 已审计（中债国债收益率）与指数点位接口",
            },
            "bond_index": {
                "observation_date": "有（接口 date 字段）",
                "publication_date": "**无中债登官方发布时刻证据**",
                "available_date": "**无法证明**",
                "source": "本轮 3B-6.1.2 债券指数审计",
            },
            "cash": {
                "observation_date": "**无历史序列**",
                "publication_date": "不适用",
                "available_date": "**无法证明**",
                "source": "活期/同业存款利率历史序列未取得",
            },
            "fixed_rate": {
                "observation_date": "合同约定值，无观察日概念",
                "publication_date": "合同签署日",
                "available_date": "**期间折算规则未知**",
                "source": "合同仅写「按期间折算」，未给公式",
            },
        },
        "forward_look_bias_warning": (
            "**在取得各成分发布时刻与修订记录证据前，任何「观察日即可用日」"
            "的假设都属前视偏差风险，不得为了扩大历史样本而默认成立**"),
        "benchmarks": pit_benchmarks,
        "summary": {
            "total_benchmarks": len(pit_benchmarks),
            "point_in_time_verified": sum(
                1 for b in pit_benchmarks if b["point_in_time_verified"]),
            "all_unverified": all(not b["point_in_time_verified"]
                                    for b in pit_benchmarks),
            "component_types_needing_evidence": ["index", "bond_index",
                                                  "cash", "fixed_rate"],
            "component_types_with_evidence": [],
            "note": ("**15/15 条基准的时点可用性全部未验证**："
                      "4 类成分均无发布时刻证据"),
        },
        "bond_index_pit_detail": [
            {"contract_label": t["contract_label"],
              "mapping_confidence": t["mapping_confidence"],
              "methodology_doc_obtained": t["methodology_doc_obtained"],
              "revision_risk": t["revision_risk"],
              "publication_time_evidence": False}
            for t in bond["targets"]],
    }

    (REPORTS / "phase3B6_1_2_point_in_time_audit.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

    s = doc["summary"]
    print(f"基准 {s['total_benchmarks']} 条")
    print(f"  时点可用已验证 {s['point_in_time_verified']}")
    print(f"  全部未验证      {s['all_unverified']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
