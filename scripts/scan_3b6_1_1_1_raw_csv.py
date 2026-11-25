"""阶段3B-6.1.1.1 原始 CSV 逐行扫描器（只读）。

**不解析成字典后检查**——先逐行扫描原始记录，再统计重复与异常。
供测试与审计共同调用，保证测试执行的是同一套真实逻辑。

用法::

    python scripts/scan_3b6_1_1_1_raw_csv.py           # 打印统计
"""
from __future__ import annotations

import csv
import glob
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "reports" / "evidence" / "phase3B6_1_1" / "raw"
EVIDENCE_JSON = ROOT / "reports" / "evidence" / "phase3B6_1_1" / \
    "raw_csv_scan.json"

CURVE = "中债国债收益率曲线"
TENORS = ["3月", "6月", "1年", "3年", "5年", "7年", "10年", "30年"]

# 合理范围（与 coverage_quality.json 声明一致）
PLAUSIBLE_MIN = 0.0
PLAUSIBLE_MAX = 15.0

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_number(s: str) -> bool:
    try:
        f = float(s)
    except (TypeError, ValueError):
        return False
    return not (math.isnan(f) or math.isinf(f))


def scan_file(path: Path) -> dict:
    """逐行扫描单个 CSV，返回原始统计（不做任何去重）。"""
    stats = {
        "file": path.name,
        "raw_rows": 0,
        "date_parsed_rows": 0,
        "date_unparseable_rows": 0,
        "empty_value_cells": 0,
        "non_numeric_cells": 0,
        "nan_cells": 0,
        "inf_cells": 0,
        "out_of_range_cells": 0,
        "records": [],          # [(date_str, tenor, value|None, lineno)]
        "bad_samples": [],
    }
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames or []
        idx_tenors = [t for t in TENORS if t in header]
        for lineno, row in enumerate(reader, start=2):
            if CURVE not in (row.get("曲线名称") or ""):
                continue
            stats["raw_rows"] += 1
            ds = (row.get("日期") or "").strip()

            # 日期检查
            date_ok = False
            if not ds:
                stats["date_unparseable_rows"] += 1
                stats["bad_samples"].append(
                    {"line": lineno, "kind": "empty_date", "raw": ds})
            elif not DATE_RE.match(ds):
                stats["date_unparseable_rows"] += 1
                stats["bad_samples"].append(
                    {"line": lineno, "kind": "bad_date_format", "raw": ds})
            else:
                from datetime import date
                try:
                    date.fromisoformat(ds)
                    date_ok = True
                    stats["date_parsed_rows"] += 1
                except ValueError:
                    stats["date_unparseable_rows"] += 1
                    stats["bad_samples"].append(
                        {"line": lineno, "kind": "invalid_date", "raw": ds})

            # 逐期限检查
            for t in idx_tenors:
                cell = (row.get(t) or "").strip()
                if not cell or cell.lower() in ("nan", "none", "null"):
                    stats["empty_value_cells"] += 1
                    stats["records"].append((ds, t, None, lineno, "empty"))
                    if cell.lower() == "nan":
                        stats["nan_cells"] += 1
                    continue
                if not _is_number(cell):
                    stats["non_numeric_cells"] += 1
                    stats["bad_samples"].append(
                        {"line": lineno, "kind": "non_numeric",
                         "tenor": t, "raw": cell})
                    stats["records"].append((ds, t, None, lineno, "non_numeric"))
                    continue
                v = float(cell)
                if math.isnan(v):
                    stats["nan_cells"] += 1
                elif math.isinf(v):
                    stats["inf_cells"] += 1
                    stats["records"].append((ds, t, v, lineno, "inf"))
                    continue
                if v < PLAUSIBLE_MIN or v > PLAUSIBLE_MAX:
                    stats["out_of_range_cells"] += 1
                    stats["bad_samples"].append(
                        {"line": lineno, "kind": "out_of_range",
                         "tenor": t, "value": v})
                stats["records"].append((ds, t, v, lineno,
                                          "ok" if date_ok else "bad_date"))
    return stats


def scan_all() -> dict:
    files = sorted(glob.glob(str(RAW_DIR / "bond_gov_*.csv")))
    per_file = [scan_file(Path(f)) for f in files]

    # 合并全部原始记录（不去重）
    all_records = []
    for st in per_file:
        for ds, t, v, lineno, kind in st["records"]:
            if kind == "ok":
                all_records.append((ds, t, v, st["file"], lineno))

    # 用 Counter 检查重复（不覆盖）
    counter = Counter((d, t) for d, t, v, f, ln in all_records)

    # 冲突检测：同 key 的数值集合 > 1
    vals = defaultdict(list)
    for d, t, v, f, ln in all_records:
        vals[(d, t)].append((v, f, ln))
    conflicts = {
        k: v for k, v in vals.items()
        if len({x[0] for x in v}) > 1
    }

    per_tenor = Counter(t for d, t, v, f, ln in all_records)

    total_cells_by_tenor = {}
    for st in per_file:
        pass

    return {
        "files_scanned": len(files),
        "raw_rows_total": sum(s["raw_rows"] for s in per_file),
        "date_parsed_rows_total": sum(s["date_parsed_rows"] for s in per_file),
        "date_unparseable_rows_total": sum(s["date_unparseable_rows"]
                                            for s in per_file),
        "empty_value_cells_total": sum(s["empty_value_cells"] for s in per_file),
        "non_numeric_cells_total": sum(s["non_numeric_cells"] for s in per_file),
        "nan_cells_total": sum(s["nan_cells"] for s in per_file),
        "inf_cells_total": sum(s["inf_cells"] for s in per_file),
        "out_of_range_cells_total": sum(s["out_of_range_cells"]
                                         for s in per_file),
        "valid_records_total": len(all_records),
        "unique_date_tenor_pairs": len(counter),
        "duplicate_pairs_total": sum(c - 1 for c in counter.values()),
        "duplicate_pairs_by_key": {f"{k[0]}|{k[1]}": c
                                    for k, c in counter.items() if c > 1},
        "conflict_keys": len(conflicts),
        "conflict_detail": [
            {"date": k[0], "tenor": k[1],
             "values": [{"value": v[0], "file": v[1], "line": v[2]}
                        for v in vv]}
            for k, vv in list(conflicts.items())[:20]
        ],
        "records_per_tenor": dict(per_tenor),
        "bad_samples": [s for st in per_file for s in st["bad_samples"]][:30],
        "per_file": [{k: v for k, v in s.items() if k != "records"}
                      for s in per_file],
    }


def main(argv=None) -> int:
    result = scan_all()
    EVIDENCE_JSON.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_JSON.write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"文件数           {result['files_scanned']}")
    print(f"原始数据行数     {result['raw_rows_total']}")
    print(f"日期可解析行     {result['date_parsed_rows_total']}")
    print(f"日期不可解析行   {result['date_unparseable_rows_total']}")
    print(f"空值单元格       {result['empty_value_cells_total']}")
    print(f"非数值单元格     {result['non_numeric_cells_total']}")
    print(f"NaN 单元格       {result['nan_cells_total']}")
    print(f"Inf 单元格       {result['inf_cells_total']}")
    print(f"超范围单元格     {result['out_of_range_cells_total']}")
    print(f"有效记录         {result['valid_records_total']}")
    print(f"唯一(日期,期限)   {result['unique_date_tenor_pairs']}")
    print(f"重复对数         {result['duplicate_pairs_total']}")
    print(f"数值冲突 key     {result['conflict_keys']}")
    print(f"各期限记录数     {result['records_per_tenor']}")
    if result["bad_samples"]:
        print(f"异常样本(前 5)   {result['bad_samples'][:5]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
