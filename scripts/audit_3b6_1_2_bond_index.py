"""阶段3B-6.1.2 债券指数成分专项追溯（只读）。

对 15 条基准中的 5 个债券指数成分，逐个审计：
代码、发布机构、可得序列、历史起止、覆盖率、缺口、重复、非正值、
价格/全价/净价/财富口径、是否含利息再投资、编制方案变化、修订风险。

**只读**：真实调用公开接口，原始序列落盘到
``reports/evidence/phase3B6_1_2/raw/``，不写正式数据库。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORTS = ROOT / "reports"
EV = REPORTS / "evidence" / "phase3B6_1_2"
RAW = EV / "raw"

CHINABOND_SOURCE = "akshare.bond_index_general_cbond"
CHINABOND_UPSTREAM = ("https://yield.chinabond.com.cn/cbweb-mn/indices/"
                       "singleIndexQueryResult")

# 5 个债券指数成分 → 候选中债指数名（来自 INDEX_MAPPING）
TARGETS = [
    {"contract_label": "中债总",
     "used_by": [110022],
     "candidate_index": "综合指数",
     "indicators": ["财富", "全价", "净价"],
     "mapping_confidence": "LOW",
     "note": "合同写「中债总指数」，无法确认对应「综合指数」还是「总指数」族系"},
    {"contract_label": "中债综合全价",
     "used_by": [161005],
     "candidate_index": "综合指数",
     "indicators": ["全价"],
     "mapping_confidence": "MEDIUM",
     "note": "「综合全价」字面吻合「综合指数[全价]」，未取得官方代码对照"},
    {"contract_label": "中证综合债券",
     "used_by": [1938],
     "candidate_index": None,
     "indicators": [],
     "mapping_confidence": "NONE",
     "note": "**中证系列债券指数无可用接口**，完全阻断"},
    {"contract_label": "中债-总全价(总值)",
     "used_by": [12346],
     "candidate_index": "综合指数",
     "indicators": ["全价"],
     "mapping_confidence": "LOW",
     "note": "「总全价(总值)」的代码未确认；全价序列可得但不等于总收益"},
    {"contract_label": "中债综合财富",
     "used_by": [12344],
     "candidate_index": "综合指数",
     "indicators": ["财富"],
     "mapping_confidence": "MEDIUM",
     "note": "「综合财富」字面吻合「综合指数[财富]」；财富指数含利息再投资"},
]

REF_START = "2002-01-04"
GAP_THRESHOLD_DAYS = 15


def probe(candidate_index: str, indicator: str) -> dict:
    rec = {
        "source": CHINABOND_SOURCE,
        "upstream": CHINABOND_UPSTREAM,
        "params": {"index_category": candidate_index, "indicator": indicator,
                    "period": "总值"},
        "called_at": datetime.now().isoformat(timespec="seconds"),
        "status": None, "rows": 0, "error": None,
    }
    try:
        import akshare as ak
        df = ak.bond_index_general_cbond(
            index_category=candidate_index, indicator=indicator, period="总值")
    except Exception as exc:
        rec["status"] = "error"
        rec["error"] = f"{type(exc).__name__}: {str(ex)[:150]}"
        return rec

    if df is None or len(df) == 0:
        rec["status"] = "empty"
        return rec

    rec["status"] = "ok"
    rec["rows"] = int(len(df))
    dates = [str(d) for d in df["date"].tolist()]
    values = [float(v) for v in df["value"].tolist()]
    rec["date_min"] = dates[0]
    rec["date_max"] = dates[-1]
    rec["duplicate_dates"] = len(dates) - len(set(dates))
    rec["non_positive_values"] = sum(1 for v in values if v <= 0)
    rec["value_min"] = min(values)
    rec["value_max"] = max(values)
    rec["value_first"] = values[0]
    rec["value_last"] = values[-1]

    # 缺口
    from datetime import date as _d
    ds = [_d.fromisoformat(x) for x in dates]
    gaps = [{"after": dates[i], "before": dates[i + 1],
              "days": (ds[i + 1] - ds[i]).days}
            for i in range(len(ds) - 1) if (ds[i + 1] - ds[i]).days > GAP_THRESHOLD_DAYS]
    rec["max_gap_days"] = max(((ds[i + 1] - ds[i]).days for i in range(len(ds) - 1)),
                               default=0)
    rec["gap_count_over_threshold"] = len(gaps)
    rec["missing_intervals"] = gaps[:10]

    # 覆盖率（相对 2002-01-04 起）
    span = (ds[-1] - _d.fromisoformat(REF_START)).days + 1
    rec["coverage_ratio"] = round(len(ds) / span, 6)

    # 原始序列落盘（仅此 5 条，体积可控）
    RAW.mkdir(parents=True, exist_ok=True)
    fn = RAW / f"cbond_{candidate_index}_{indicator}.csv"
    df.to_csv(fn, index=False, encoding="utf-8-sig")
    data = fn.read_bytes()
    rec["raw_file"] = {
        "file": fn.name, "bytes": len(data),
        "sha256_16": hashlib.sha256(data).hexdigest()[:16],
    }
    rec["sample"] = [{"date": dates[i], "value": values[i]} for i in range(3)]
    return rec


def main() -> int:
    EV.mkdir(parents=True, exist_ok=True)
    out = {
        "phase": "3B-6.1.2",
        "task": "bond_index_component_audit",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": CHINABOND_SOURCE,
        "upstream": CHINABOND_UPSTREAM,
        "publisher": "中债金融估值中心（中债登）",
        "evidence_grade": "L3",
        "evidence_grade_reason": (
            "经 AKShare 聚合访问中债登数据；**未下载中债登官方编制方案或指数公告**，"
            "不能描述为「官方原始数据已独立核验」"),
        "indicator_semantics": {
            "财富": "含利息及再投资的财富指数（≈总收益口径）",
            "全价": "全价指数（含应计利息，不含再投资）",
            "净价": "净价指数（不含应计利息）",
            "warning": ("**全价指数不等于全收益指数**；"
                          "**财富指数含利息再投资，接近总收益但不等于「全收益」标准定义**"),
        },
        "gap_threshold_days": GAP_THRESHOLD_DAYS,
        "targets": [],
        "summary": {},
    }

    ok_count = 0
    for t in TARGETS:
        entry = {
            "contract_label": t["contract_label"],
            "used_by_composite": t["used_by"],
            "candidate_index_name": t["candidate_index"],
            "candidate_index": t["candidate_index"],
            "mapping_confidence": t["mapping_confidence"],
            "mapping_note": t["note"],
            "probes": [],
            "official_code": None,
            "official_publisher": "中债金融估值中心（中债登）"
                                    if t["candidate_index"] else None,
            "index_publication_date": None,
            "methodology_doc_obtained": False,
            "code_changed_or_terminated": "unknown",
            "revision_risk": "未排除",
            "series_semantics_confirmed": False,
            "blocking_reason": None,
        }
        if t["candidate_index"] is None:
            entry["blocking_reason"] = (
                "**该债券指数无可用数据接口**。"
                "不得用国债收益率曲线代替债券指数收益率。")
            out["targets"].append(entry)
            print(f"{t['contract_label']}: 阻断（无接口）")
            continue

        for ind in t["indicators"]:
            rec = probe(t["candidate_index"], ind)
            entry["probes"].append(rec)
            print(f"{t['contract_label']} [{ind}]: {rec['status']} "
                  f"rows={rec['rows']}")
            time.sleep(4)
            if rec["status"] == "ok":
                ok_count += 1

        # 合同是否明说口径
        label = t["contract_label"]
        if "全价" in label:
            entry["contract_states_basis"] = "全价"
            entry["series_semantics_confirmed"] = True
            entry["blocking_reason"] = (
                "合同明说「全价」，全价序列可得；但**全价 ≠ 全收益**，"
                "若基准本意是全收益则口径不符")
        elif "财富" in label:
            entry["contract_states_basis"] = "财富"
            entry["series_semantics_confirmed"] = True
            entry["blocking_reason"] = (
                "合同明说「财富」，财富序列可得且含利息再投资；"
                "但**代码映射未获官方确认**")
        else:
            entry["contract_states_basis"] = None
            entry["blocking_reason"] = (
                "**合同未明说收益口径**（仅「中债总指数」），"
                "无法确定应使用财富/全价/净价中的哪一条")

        out["targets"].append(entry)

    out["summary"] = {
        "total_bond_components": len(TARGETS),
        "interface_available": sum(1 for t in out["targets"]
                                    if t["candidate_index"] is not None),
        "interface_blocked": sum(1 for t in out["targets"]
                                  if t["candidate_index"] is None),
        "probes_ok": ok_count,
        "contract_states_basis": sum(1 for t in out["targets"]
                                       if t.get("contract_states_basis")),
        "all_three_series": sum(1 for t in out["targets"]
                                 if len(t["probes"]) == 3
                                 and all(p["status"] == "ok" for p in t["probes"])),
        "official_code_confirmed": sum(1 for t in out["targets"]
                                        if t["official_code"]),
        "methodology_doc_obtained": sum(1 for t in out["targets"]
                                         if t["methodology_doc_obtained"]),
        "series_semantics_confirmed": sum(1 for t in out["targets"]
                                           if t["series_semantics_confirmed"]),
        "fully_qualified": 0,
        "note": ("**0 条债券指数成分达到「完全合格」**："
                  "代码映射未获官方确认、无编制方案、修订风险未排除"),
    }

    (REPORTS / "phase3B6_1_2_bond_index_audit.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    s = out["summary"]
    print()
    print(f"债券成分 {s['total_bond_components']} 个")
    print(f"  有接口 {s['interface_available']} / 阻断 {s['interface_blocked']}")
    print(f"  探测成功 {s['probes_ok']} 次")
    print(f"  合同明说口径 {s['contract_states_basis']}")
    print(f"  官方代码确认 {s['official_code_confirmed']}")
    print(f"  完全合格 {s['fully_qualified']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
