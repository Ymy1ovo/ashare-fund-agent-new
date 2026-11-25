"""债券指数原始 CSV 逐行质量扫描器（只读）。

阶段3B-6.1.2.1 新增，3B-6.1.2.1.1 修正重复日期边界。

**先逐行扫描原始记录，再统计**，不先建字典去重。

数值七类互斥：
    empty / nan / inf / non_numeric / out_of_range / valid

**日期重复检测独立于数值有效性**（3B-6.1.2.1.1 修正）：
    所有日期合法的原始记录都进入日期重复检测；
    数值有效性只决定该记录能否参与「数值冲突」判断。

三个重复概念严格区分：
    duplicate_dates            合法日期重复记录数（同日期第 2 条起计数）
    conflict_dates             同日存在多个不同**有效**数值的日期数
    invalid_value_duplicate_dates  重复日期中至少一条数值异常的日期数

用法::

    from scripts.scan_bond_index_csv import scan_csv, scan_dir
    st = scan_csv(Path("...csv"))
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

REQUIRED_COLUMNS = ["date", "value"]
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_NAN_TOKENS = {"nan", "+nan", "-nan"}
_INF_TOKENS = {"inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"}
_NULL_TOKENS = {"", "null", "none"}

# 指数点位合理范围：债券指数不可能为负，也不可能高到离谱
VALUE_MIN = 0.0
VALUE_MAX = 100000.0

GAP_THRESHOLD_DAYS = 15


def classify_value(raw) -> tuple[str, float | None]:
    """七类互斥分类，返回 (类别, 数值或 None)。"""
    if raw is None:
        return "empty", None
    s = str(raw).strip()
    low = s.lower()
    if low in _NULL_TOKENS:
        return "empty", None
    if low in _NAN_TOKENS:
        return "nan", None
    if low in _INF_TOKENS:
        return "inf", None
    try:
        v = float(s)
    except (TypeError, ValueError):
        return "non_numeric", None
    if math.isnan(v):
        return "nan", None
    if math.isinf(v):
        return "inf", None
    if v <= VALUE_MIN or v > VALUE_MAX:
        return "out_of_range", v
    return "valid", v


def scan_csv(path: Path) -> dict:
    """逐行扫描单份 CSV，返回完整质量统计（不去重、不跳过）。"""
    path = Path(path)
    raw_bytes = path.read_bytes()
    st = {
        "file": path.name,
        "bytes": len(raw_bytes),
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "structure_ok": True,
        "missing_columns": [],
        "header": [],
        "raw_rows": 0,
        "valid_rows": 0,
        "empty_cells": 0,
        "nan_cells": 0,
        "inf_cells": 0,
        "non_numeric_cells": 0,
        "out_of_range_cells": 0,
        "empty_date_rows": 0,
        "bad_date_format_rows": 0,
        "invalid_date_rows": 0,
        "valid_date_rows": 0,
        "duplicate_dates": 0,
        "conflict_dates": 0,
        "invalid_value_duplicate_dates": 0,
        "out_of_order_rows": 0,
        "conflict_detail": [],
        "invalid_dup_detail": [],
        "date_min": None,
        "date_max": None,
        "max_gap_days": 0,
        "gap_count_over_threshold": 0,
        "missing_intervals": [],
        "bad_samples": [],
        "records": [],
    }

    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames or []
        st["header"] = list(header)
        missing = [c for c in REQUIRED_COLUMNS if c not in header]
        st["missing_columns"] = missing
        st["structure_ok"] = not missing
        if missing:
            st["bad_samples"].append(
                {"line": 1, "kind": "missing_columns", "raw": missing})
            return st

        # 所有合法日期都进这里（不按数值有效性过滤）
        by_date = defaultdict(list)
        prev_date = None
        for lineno, row in enumerate(reader, start=2):
            st["raw_rows"] += 1
            ds = (row.get("date") or "").strip()

            date_ok = False
            if not ds:
                st["empty_date_rows"] += 1
                st["bad_samples"].append(
                    {"line": lineno, "kind": "empty_date", "raw": ds})
            elif not DATE_RE.match(ds):
                st["bad_date_format_rows"] += 1
                st["bad_samples"].append(
                    {"line": lineno, "kind": "bad_date_format", "raw": ds})
            else:
                try:
                    d = date.fromisoformat(ds)
                    date_ok = True
                    st["valid_date_rows"] += 1
                except ValueError:
                    st["invalid_date_rows"] += 1
                    st["bad_samples"].append(
                        {"line": lineno, "kind": "invalid_date", "raw": ds})

            kind, v = classify_value(row.get("value"))
            if kind == "empty":
                st["empty_cells"] += 1
            elif kind == "nan":
                st["nan_cells"] += 1
            elif kind == "inf":
                st["inf_cells"] += 1
            elif kind == "non_numeric":
                st["non_numeric_cells"] += 1
            elif kind == "out_of_range":
                st["out_of_range_cells"] += 1
            else:
                st["valid_rows"] += 1

            if kind != "valid":
                st["bad_samples"].append({
                    "line": lineno, "kind": kind, "raw": row.get("value")})

            rec = {"line": lineno, "date": ds, "value": v, "kind": kind,
                   "date_ok": date_ok}
            st["records"].append(rec)

            if not date_ok:
                continue

            # 日期有序性
            if prev_date is not None and d < prev_date:
                st["out_of_order_rows"] += 1
                st["bad_samples"].append({
                    "line": lineno, "kind": "out_of_order",
                    "raw": f"{prev_date.isoformat()} -> {ds}"})
            prev_date = d

            # 所有合法日期的记录都进入重复检测（含数值异常记录）
            by_date[ds].append(rec)

    # ---------- 重复日期（不依赖数值有效性）----------
    st["duplicate_dates"] = sum(len(v) - 1 for v in by_date.values())

    for ds, items in by_date.items():
        if len(items) < 2:
            continue
        valid_vals = {r["value"] for r in items if r["kind"] == "valid"}
        has_invalid = any(r["kind"] != "valid" for r in items)

        if len(valid_vals) > 1:
            st["conflict_dates"] += 1
            st["conflict_detail"].append({
                "date": ds,
                "values": [{"value": r["value"], "line": r["line"]}
                            for r in items if r["kind"] == "valid"],
            })
        if has_invalid:
            st["invalid_value_duplicate_dates"] += 1
            st["invalid_dup_detail"].append({
                "date": ds,
                "kinds": [r["kind"] for r in items],
                "lines": [r["line"] for r in items],
            })

    # ---------- 日期范围与缺口（只按有效数值记录）----------
    valid_dates = sorted(date.fromisoformat(ds) for ds, items in by_date.items()
                         if any(r["kind"] == "valid" for r in items))
    if valid_dates:
        st["date_min"] = valid_dates[0].isoformat()
        st["date_max"] = valid_dates[-1].isoformat()
        gaps = [(valid_dates[i + 1] - valid_dates[i]).days
                for i in range(len(valid_dates) - 1)]
        if gaps:
            st["max_gap_days"] = max(gaps)
        big = [{"after": valid_dates[i].isoformat(),
                 "before": valid_dates[i + 1].isoformat(),
                 "days": (valid_dates[i + 1] - valid_dates[i]).days}
                for i in range(len(valid_dates) - 1)
                if (valid_dates[i + 1] - valid_dates[i]).days > GAP_THRESHOLD_DAYS]
        st["gap_count_over_threshold"] = len(big)
        st["missing_intervals"] = big[:10]

    st["bad_samples"] = st["bad_samples"][:30]
    return st


def scan_dir(directory: Path) -> dict:
    """扫描目录下全部 CSV。

    同时给出「探测引用行数」与「独立文件行数」两套统计：
    独立文件以 (文件名, 完整 SHA256) 共同识别；
    同名但 SHA256 不同 → 视为不同文件；
    同 SHA256 被多次引用 → 只计一次。
    """
    dirpath = Path(directory)
    files = sorted(dirpath.glob("*.csv"))
    per = [scan_csv(f) for f in files]

    # 独立文件去重：(文件名, 完整 SHA256)
    unique_keys = set()
    unique_rows = 0
    unique_files = []
    for s in per:
        k = (s["file"], s["sha256"])
        if k not in unique_keys:
            unique_keys.add(k)
            unique_rows += s["raw_rows"]
            unique_files.append({"file": s["file"], "sha256": s["sha256"],
                                  "bytes": s["bytes"], "raw_rows": s["raw_rows"],
                                  "valid_rows": s["valid_rows"]})

    agg = {
        "scan_mode": "directory",
        "files_scanned": len(per),
        "unique_raw_file_count": len(unique_keys),
        "unique_raw_rows_total": unique_rows,
        "unique_files": unique_files,
        "raw_rows_total": sum(s["raw_rows"] for s in per),
        "valid_rows_total": sum(s["valid_rows"] for s in per),
        "empty_cells_total": sum(s["empty_cells"] for s in per),
        "nan_cells_total": sum(s["nan_cells"] for s in per),
        "inf_cells_total": sum(s["inf_cells"] for s in per),
        "non_numeric_cells_total": sum(s["non_numeric_cells"] for s in per),
        "out_of_range_cells_total": sum(s["out_of_range_cells"] for s in per),
        "empty_date_rows_total": sum(s["empty_date_rows"] for s in per),
        "bad_date_format_rows_total": sum(s["bad_date_format_rows"] for s in per),
        "invalid_date_rows_total": sum(s["invalid_date_rows"] for s in per),
        "valid_date_rows_total": sum(s["valid_date_rows"] for s in per),
        "duplicate_dates_total": sum(s["duplicate_dates"] for s in per),
        "conflict_dates_total": sum(s["conflict_dates"] for s in per),
        "invalid_value_duplicate_dates_total": sum(
            s["invalid_value_duplicate_dates"] for s in per),
        "out_of_order_rows_total": sum(s["out_of_order_rows"] for s in per),
        "structure_all_ok": all(s["structure_ok"] for s in per),
    }
    agg["all_zero_defects"] = all(
        agg[k] == 0 for k in (
            "empty_cells_total", "nan_cells_total", "inf_cells_total",
            "non_numeric_cells_total", "out_of_range_cells_total",
            "empty_date_rows_total", "bad_date_format_rows_total",
            "invalid_date_rows_total", "duplicate_dates_total",
            "conflict_dates_total", "invalid_value_duplicate_dates_total",
            "out_of_order_rows_total"))
    return {"aggregate": agg,
            "files": [{k: v for k, v in s.items() if k != "records"}
                       for s in per]}


if __name__ == "__main__":
    import sys
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "reports/evidence/phase3B6_1_2/raw")
    res = scan_dir(target)
    print(json.dumps(res["aggregate"], ensure_ascii=False, indent=1))
