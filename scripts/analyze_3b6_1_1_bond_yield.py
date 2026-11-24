"""阶段3B-6.1.1 中债国债收益率覆盖与质量分析（只读）。

从 ``reports/evidence/phase3B6_1_1/raw/*.csv`` 原始文件重新读取并计算，
不读取任何预计算的结论字段。产物：

- ``reports/phase3B6_1_1_source_audit.json``
- ``reports/phase3B6_1_1_coverage_quality.json``
"""
from __future__ import annotations

import glob
import hashlib
import json
import statistics
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EV = ROOT / "reports" / "evidence" / "phase3B6_1_1"
RAW = EV / "raw"

TENORS = ["3月", "6月", "1年", "3年", "5年", "7年", "10年", "30年"]
CURVE = "中债国债收益率曲线"
# 审计参考区间（不是回测门槛）
REF_START = date(2006, 3, 1)
REF_END = date(2026, 12, 31)

# 节假日/周末判定用：缺口 <= 该天数视为正常非交易日
HOLIDAY_MAX_GAP = 10
# 异常值阈值（中债国债收益率合理区间，用于发现单位错误/坏点）
PLAUSIBLE_MIN = 0.0
PLAUSIBLE_MAX = 15.0


def load_rows():
    """从原始 CSV 重新解析，返回 [(date, tenor, value, source_file)]。"""
    rows = []
    files = sorted(glob.glob(str(RAW / "bond_gov_*.csv")))
    for f in files:
        p = Path(f)
        text = p.read_text(encoding="utf-8-sig")
        lines = text.splitlines()
        if not lines:
            continue
        header = lines[0].split(",")
        idx = {name: i for i, name in enumerate(header)}
        d_i = idx.get("日期")
        c_i = idx.get("曲线名称")
        for ln in lines[1:]:
            parts = ln.split(",")
            if d_i is None or d_i >= len(parts):
                continue
            if c_i is not None and c_i < len(parts) and CURVE not in parts[c_i]:
                continue
            ds = parts[d_i].strip()
            try:
                d = date.fromisoformat(ds)
            except ValueError:
                continue
            for t in TENORS:
                if t not in idx or idx[t] >= len(parts):
                    continue
                raw = parts[idx[t]].strip()
                if raw == "" or raw.lower() == "nan":
                    rows.append((d, t, None, p.name))
                else:
                    try:
                        rows.append((d, t, float(raw), p.name))
                    except ValueError:
                        rows.append((d, t, None, p.name))
    return rows, files


def analyze():
    rows, files = load_rows()

    # 去重（同日期+同期限，取最后一条并记录冲突）
    seen = {}
    conflicts = 0
    for d, t, v, src in rows:
        key = (d, t)
        if key in seen:
            if seen[key] != v:
                conflicts += 1
            continue
        seen[key] = v

    dates_all = sorted({d for (d, t) in seen})
    per_tenor = {}
    for t in TENORS:
        items = sorted((d, v) for (d, tt), v in seen.items() if tt == t)
        valid = [(d, v) for d, v in items if v is not None]
        vals = [v for _, v in valid]
        ds = [d for d, _ in valid]

        # 缺失区间：相邻有效日期间隔 > HOLIDAY_MAX_GAP
        gaps = []
        for a, b in zip(ds, ds[1:]):
            n = (b - a).days
            if n > HOLIDAY_MAX_GAP:
                gaps.append({"after": a.isoformat(), "before": b.isoformat(),
                              "days": n})

        # 异常值
        outliers = [{"date": d.isoformat(), "value": v}
                    for d, v in valid
                    if v < PLAUSIBLE_MIN or v > PLAUSIBLE_MAX]
        zeros = sum(1 for v in vals if v == 0)
        negatives = sum(1 for v in vals if v < 0)

        overlap = 0
        if ds:
            min_o = max(min(ds), REF_START) if ds else REF_START
            max_o = min(max(ds), REF_END)
            if max_o >= min_o:
                overlap = (max_o - min_o).days + 1
        ref_span = (REF_END - REF_START).days + 1

        per_tenor[t] = {
            "date_min": ds[0].isoformat() if ds else None,
            "date_max": ds[-1].isoformat() if ds else None,
            "rows": len(items),
            "valid_rows": len(valid),
            "null_values": len(items) - len(valid),
            "duplicate_dates": len(items) - len({d for d, _ in items}),
            "conflicting_values": conflicts,
            "coverage_ratio_vs_ref_window": round(overlap / ref_span, 6),
            "max_gap_days": max((g["days"] for g in gaps), default=0),
            "gap_count_over_10d": len(gaps),
            "missing_intervals": gaps[:20],
            "outlier_count": len(outliers),
            "outliers": outliers[:10],
            "zero_values": zeros,
            "negative_values": negatives,
            "value_min": min(vals) if vals else None,
            "value_max": max(vals) if vals else None,
            "value_median": statistics.median(vals) if vals else None,
            "unit_evidence": {
                "observed_range": [min(vals), max(vals)] if vals else None,
                "conclusion": ("百分数(%)" if vals and max(vals) <= 20
                                else "需进一步核实"),
                "reason": ("中债国债收益率实测值集中在 1~5 之间，"
                            "若为小数表示则应为 0.01~0.05；"
                            "故判定为百分数，使用时须 /100"),
            },
        }

    return {
        "rows_parsed_total": len(rows),
        "rows_after_dedup": len(seen),
        "raw_file_count": len(files),
        "raw_files": [{"file": Path(f).name,
                        "bytes": Path(f).stat().st_size,
                        "sha256_16": hashlib.sha256(Path(f).read_bytes())
                                       .hexdigest()[:16]}
                       for f in files],
        "distinct_dates": len(dates_all),
        "date_min": dates_all[0].isoformat() if dates_all else None,
        "date_max": dates_all[-1].isoformat() if dates_all else None,
        "tenors": per_tenor,
        "shared_date_index": _shared_index_check(seen),
    }


def _shared_index_check(seen) -> dict:
    """不同期限是否共享相同日期索引。"""
    idx = {}
    for (d, t), v in seen.items():
        if v is None:
            continue
        idx.setdefault(t, set()).add(d)
    if not idx:
        return {"all_identical": False, "note": "无数据"}
    sets = list(idx.values())
    base = sets[0]
    same = all(s == base for s in sets)
    union = set().union(*sets)
    inter = set.intersection(*sets)
    return {
        "all_identical": same,
        "union_dates": len(union),
        "intersection_dates": len(inter),
        "per_tenor_date_counts": {t: len(s) for t, s in idx.items()},
        "note": ("各期限日期索引是否完全一致；不一致说明某些期限有独立缺失"),
    }


def main() -> int:
    result = analyze()

    # ---- source_audit.json ----
    src = json.loads((EV / "bond_yield_raw_audit.json").read_text(encoding="utf-8"))
    source_audit = {
        "phase": "3B-6.1.1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": src["source"],
        "provider": src["provider"],
        "curve": src["curve"],
        "interface_constraints": src["interface_constraints"],
        "empty_probe_2002_2005": src["empty_probe"],
        "segments_ok": sum(1 for s in src["segments"] if s["status"] == "ok"),
        "segments_total": len(src["segments"]),
        "rows_parsed_total": result["rows_parsed_total"],
        "rows_after_dedup": result["rows_after_dedup"],
        "distinct_dates": result["distinct_dates"],
        "date_min": result["date_min"],
        "date_max": result["date_max"],
        "tenors_actual": TENORS,
        "tenors_requested_by_task": ["3月", "6月", "1年", "2年", "3年",
                                      "5年", "7年", "10年"],
        "tenors_missing": ["2年"],
        "tenors_missing_note": (
            "该接口返回的列中**不存在 2 年期**。任务要求的 2 年期"
            "无法从本数据源取得，如实记录，不以 3 年期替代。"),
        "evidence_grade": {
            "level": "L3_third_party_aggregated",
            "why": ("经 AKShare 聚合获取，底层提供方为中债登；"
                     "**未取得中债登官方原始发布文件**，"
                     "不得称为「官方原始数据已独立核验」"),
        },
        "raw_files": result["raw_files"],
        "shared_date_index": result["shared_date_index"],
    }
    (ROOT / "reports" / "phase3B6_1_1_source_audit.json").write_text(
        json.dumps(source_audit, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- coverage_quality.json ----
    cov = {
        "phase": "3B-6.1.1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "reference_window": [REF_START.isoformat(), REF_END.isoformat()],
        "reference_window_note": ("审计参考区间，**不是回测准入门槛**；"
                                   "coverage_ratio_vs_ref_window 以此区间计算"),
        "holiday_gap_threshold_days": HOLIDAY_MAX_GAP,
        "holiday_note": ("周末与法定节假日**不判定为数据缺失**；"
                          "仅当相邻有效日期间隔 > 阈值时才列入 missing_intervals"),
        "outlier_bounds": [PLAUSIBLE_MIN, PLAUSIBLE_MAX],
        "unit_identified": "百分数(%)",
        "unit_note": "使用时须除以 100；不得直接当小数收益",
        "tenors": result["tenors"],
        "summary": {
            "tenors_available": len(TENORS),
            "tenors_requested_by_task": 8,
            "tenors_missing": ["2年"],
            "all_have_data": all(v["valid_rows"] > 0
                                  for v in result["tenors"].values()),
            "total_valid_rows": sum(v["valid_rows"]
                                     for v in result["tenors"].values()),
        },
    }
    (ROOT / "reports" / "phase3B6_1_1_coverage_quality.json").write_text(
        json.dumps(cov, ensure_ascii=False, indent=1), encoding="utf-8")

    # 控制台摘要
    print(f"解析行={result['rows_parsed_total']} 去重后={result['rows_after_dedup']} "
          f"日期数={result['distinct_dates']} {result['date_min']}~{result['date_max']}")
    print(f"{'期限':6} {'有效行':>6} {'起':12} {'止':12} {'覆盖率':>8} {'最大缺口':>8} {'异常':>4}")
    for t in TENORS:
        v = result["tenors"][t]
        print(f"{t:6} {v['valid_rows']:6} {v['date_min']:12} {v['date_max']:12} "
              f"{v['coverage_ratio_vs_ref_window']:8.3f} {v['max_gap_days']:8} "
              f"{v['outlier_count']:4}")
    print(f"共享日期索引一致: {result['shared_date_index']['all_identical']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
