"""债券指数原始 CSV 逐行质量扫描器（只读）。

阶段3B-6.1.2.1 新增。与 ``scan_3b6_1_1_1_raw_csv.py`` 同思路：
**先逐行扫描原始记录，再统计**，不先建字典去重。

七类互斥数值分类：
    empty / nan / inf / non_numeric / out_of_range / valid
日期类：empty_date / bad_date_format / invalid_date / out_of_order

用法::

    from scripts.scan_bond_index_csv import scan_csv
    st = scan_csv(Path("...csv"))
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
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
        "duplicate_dates": 0,
        "out_of_order_rows": 0,
        "conflict_dates": 0,
        "conflict_detail": [],
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

        seen = {}          # date_str -> [ (value, lineno) ]
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

            if kind != "valid":
                st["bad_samples"].append({
                    "line": lineno, "kind": kind, "raw": row.get("value")})

            st["records"].append(
                {"line": lineno, "date": ds, "value": v, "kind": kind,
                 "date_ok": date_ok})

            if not date_ok:
                continue

            # 日期有序性
            if prev_date is not None and d < prev_date:
                st["out_of_order_rows"] += 1
                st["bad_samples"].append({
                    "line": lineno, "kind": "out_of_order",
                    "raw": f"{prev_date.isoformat()} -> {ds}"})
            prev_date = d

            if kind == "valid":
                st["valid_rows"] += 1
                seen.setdefault(ds, []).append((v, lineno))

    # 重复与冲突（用原始记录列表，不覆盖）
    st["duplicate_dates"] = sum(len(v) - 1 for v in seen.values())
    for ds, items in seen.items():
        vals = {x[0] for x in items}
        if len(vals) > 1:
            st["conflict_dates"] += 1
            st["conflict_detail"].append({
                "date": ds,
                "values": [{"value": x[0], "line": x[1]} for x in items],
            })

    # 日期范围与缺口
    ds_list = sorted(date.fromisoformat(x) for x in seen)
    if ds_list:
        st["date_min"] = ds_list[0].isoformat()
        st["date_max"] = ds_list[-1].isoformat()
        gaps = [(ds_list[i + 1] - ds_list[i]).days for i in range(len(ds_list) - 1)]
        if gaps:
            st["max_gap_days"] = max(gaps)
        big = [{"after": ds_list[i].isoformat(),
                 "before": ds_list[i + 1].isoformat(),
                 "days": (ds_list[i + 1] - ds_list[i]).days}
                for i in range(len(ds_list) - 1)
                if (ds_list[i + 1] - ds_list[i]).days > GAP_THRESHOLD_DAYS]
        st["gap_count_over_threshold"] = len(big)
        st["missing_intervals"] = big[:10]

    st["bad_samples"] = st["bad_samples"][:30]
    return st


def scan_dir(directory: Path) -> dict:
    """扫描目录下全部 CSV。"""
    files = sorted(Path(directory).glob("*.csv"))
    per = [scan_csv(f) for f in files]
    agg = {
        "files_scanned": len(per),
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
        "duplicate_dates_total": sum(s["duplicate_dates"] for s in per),
        "out_of_order_rows_total": sum(s["out_of_order_rows"] for s in per),
        "conflict_dates_total": sum(s["conflict_dates"] for s in per),
        "structure_all_ok": all(s["structure_ok"] for s in per),
    }
    agg["all_zero_defects"] = all(
        agg[k] == 0 for k in (
            "empty_cells_total", "nan_cells_total", "inf_cells_total",
            "non_numeric_cells_total", "out_of_range_cells_total",
            "empty_date_rows_total", "bad_date_format_rows_total",
            "invalid_date_rows_total", "duplicate_dates_total",
            "out_of_order_rows_total", "conflict_dates_total"))
    return {"aggregate": agg,
            "files": [{k: v for k, v in s.items() if k != "records"}
                       for s in per]}


if __name__ == "__main__":
    import sys
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "reports/evidence/phase3B6_1_2/raw")
    res = scan_dir(target)
    print(json.dumps(res["aggregate"], ensure_ascii=False, indent=1))
