"""阶段3B-6.1.1.1 原始 CSV 逐行扫描器（只读）。

**不解析成字典后检查**——先逐行扫描原始记录，再统计重复与异常。
供测试与审计共同调用，保证测试执行的是同一套真实逻辑。

数值分类（3B-6.1.1.1.1 修正，七类互斥）：
    1. empty        空字符串 / None / null
    2. nan          NaN 字面量（nan/NaN/-nan 等）
    3. inf          正/负无穷（inf/Infinity/-inf 等）
    4. non_numeric  普通非数值字符串（如 abc）
    5. valid        正常有限数值且在合理范围内
    6. out_of_range 有限数值但超出 [PLAUSIBLE_MIN, PLAUSIBLE_MAX]
    7. (日期异常单独统计)

**NaN 只计入 nan，不再计入 empty；Inf 只计入 inf，不再计入 non_numeric。**
**缺失期限字段必须显式记录并在结果中标记结构异常。**

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
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "reports" / "evidence" / "phase3B6_1_1" / "raw"
EVIDENCE_JSON = ROOT / "reports" / "evidence" / "phase3B6_1_1" / \
    "raw_csv_scan.json"

CURVE = "中债国债收益率曲线"
TENORS = ["3月", "6月", "1年", "3年", "5年", "7年", "10年", "30年"]
REQUIRED_COLUMNS = ["曲线名称", "日期"] + TENORS

# 合理范围（与 coverage_quality.json 声明一致）
PLAUSIBLE_MIN = 0.0
PLAUSIBLE_MAX = 15.0

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 数值字面量（大小写不敏感）
_NAN_TOKENS = {"nan", "+nan", "-nan"}
_INF_TOKENS = {"inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"}
_NULL_TOKENS = {"null", "none", ""}


def classify_cell(raw) -> tuple[str, float | None]:
    """把一个单元格分类为七类之一，返回 (分类, 数值或 None)。

    优先级：empty > nan > inf > non_numeric > out_of_range > valid
    """
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
    # 兜底：某些写法（如 "1e999"）解析后是 inf
    if math.isnan(v):
        return "nan", None
    if math.isinf(v):
        return "inf", None
    if v < PLAUSIBLE_MIN or v > PLAUSIBLE_MAX:
        return "out_of_range", v
    return "valid", v


def _is_number(s: str) -> bool:
    """兼容旧调用：是否为「可直接使用的有限数值」（含超范围）。

    注意：NaN / Inf 不算数字。新代码请用 :func:`classify_cell`。
    """
    kind, _ = classify_cell(s)
    return kind in ("valid", "out_of_range")


def scan_file(path: Path) -> dict:
    """逐行扫描单个 CSV，返回原始统计（不做任何去重）。"""
    stats = {
        "file": path.name,
        "header": [],
        "missing_columns": [],
        "structure_ok": True,
        "raw_rows": 0,
        "date_parsed_rows": 0,
        "date_unparseable_rows": 0,
        "empty_value_cells": 0,
        "nan_cells": 0,
        "inf_cells": 0,
        "non_numeric_cells": 0,
        "out_of_range_cells": 0,
        "valid_cells": 0,
        "records": [],          # [(date_str, tenor, value|None, lineno, kind)]
        "bad_samples": [],
        "tenor_presence": {},
    }
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames or []
        stats["header"] = list(header)

        # ---- 结构检查：8 个目标期限 + 2 个必需列必须全部存在 ----
        missing = [c for c in REQUIRED_COLUMNS if c not in header]
        stats["missing_columns"] = missing
        stats["structure_ok"] = not missing
        stats["tenor_presence"] = {t: (t in header) for t in TENORS}
        if missing:
            stats["bad_samples"].append(
                {"line": 1, "kind": "missing_columns", "raw": missing})

        idx_tenors = [t for t in TENORS if t in header]

        for lineno, row in enumerate(reader, start=2):
            if CURVE not in (row.get("曲线名称") or ""):
                continue
            stats["raw_rows"] += 1
            ds = (row.get("日期") or "").strip()

            # ---- 日期检查 ----
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
                try:
                    date.fromisoformat(ds)
                    date_ok = True
                    stats["date_parsed_rows"] += 1
                except ValueError:
                    stats["date_unparseable_rows"] += 1
                    stats["bad_samples"].append(
                        {"line": lineno, "kind": "invalid_date", "raw": ds})

            # ---- 逐期限单元格检查（七类互斥）----
            for t in idx_tenors:
                kind, v = classify_cell(row.get(t))
                if kind == "empty":
                    stats["empty_value_cells"] += 1
                elif kind == "nan":
                    stats["nan_cells"] += 1
                elif kind == "inf":
                    stats["inf_cells"] += 1
                elif kind == "non_numeric":
                    stats["non_numeric_cells"] += 1
                elif kind == "out_of_range":
                    stats["out_of_range_cells"] += 1
                else:  # valid
                    stats["valid_cells"] += 1

                if kind != "valid":
                    stats["bad_samples"].append({
                        "line": lineno, "kind": kind, "tenor": t,
                        "raw": row.get(t),
                    })

                stats["records"].append(
                    (ds, t, v, lineno, kind if date_ok else "bad_date"))
    return stats


def scan_all() -> dict:
    files = sorted(glob.glob(str(RAW_DIR / "bond_gov_*.csv")))
    per_file = [scan_file(Path(f)) for f in files]

    # 合并全部「有效」原始记录（不去重）
    all_records = []
    for st in per_file:
        for ds, t, v, lineno, kind in st["records"]:
            if kind == "valid":
                all_records.append((ds, t, v, st["file"], lineno))

    # 用 Counter 检查重复（不覆盖）
    counter = Counter((d, t) for d, t, v, f, ln in all_records)

    # 冲突检测：同 key 的数值集合 > 1
    vals = defaultdict(list)
    for d, t, v, f, ln in all_records:
        vals[(d, t)].append((v, f, ln))
    conflicts = {k: v for k, v in vals.items()
                 if len({x[0] for x in v}) > 1}

    per_tenor = Counter(t for d, t, v, f, ln in all_records)

    # 结构异常汇总
    files_with_missing = [
        {"file": st["file"], "missing_columns": st["missing_columns"]}
        for st in per_file if not st["structure_ok"]
    ]
    missing_column_union = sorted({c for st in per_file
                                   for c in st["missing_columns"]})

    return {
        "scanner_version": "3B-6.1.1.1.1",
        "files_scanned": len(files),
        "required_columns": REQUIRED_COLUMNS,
        "structure_all_ok": not files_with_missing,
        "files_with_missing_columns": files_with_missing,
        "missing_columns_union": missing_column_union,
        "raw_rows_total": sum(s["raw_rows"] for s in per_file),
        "date_parsed_rows_total": sum(s["date_parsed_rows"] for s in per_file),
        "date_unparseable_rows_total": sum(s["date_unparseable_rows"]
                                           for s in per_file),
        "empty_value_cells_total": sum(s["empty_value_cells"] for s in per_file),
        "nan_cells_total": sum(s["nan_cells"] for s in per_file),
        "inf_cells_total": sum(s["inf_cells"] for s in per_file),
        "non_numeric_cells_total": sum(s["non_numeric_cells"] for s in per_file),
        "out_of_range_cells_total": sum(s["out_of_range_cells"]
                                         for s in per_file),
        "valid_cells_total": sum(s["valid_cells"] for s in per_file),
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

    print(f"扫描器版本       {result['scanner_version']}")
    print(f"文件数           {result['files_scanned']}")
    print(f"结构全部正常     {result['structure_all_ok']}")
    print(f"原始数据行数     {result['raw_rows_total']}")
    print(f"日期可解析行     {result['date_parsed_rows_total']}")
    print(f"日期不可解析行   {result['date_unparseable_rows_total']}")
    print(f"空值单元格       {result['empty_value_cells_total']}")
    print(f"NaN 单元格       {result['nan_cells_total']}")
    print(f"Inf 单元格       {result['inf_cells_total']}")
    print(f"非数值单元格     {result['non_numeric_cells_total']}")
    print(f"超范围单元格     {result['out_of_range_cells_total']}")
    print(f"有效单元格       {result['valid_cells_total']}")
    print(f"有效记录         {result['valid_records_total']}")
    print(f"唯一(日期,期限)   {result['unique_date_tenor_pairs']}")
    print(f"重复对数         {result['duplicate_pairs_total']}")
    print(f"数值冲突 key     {result['conflict_keys']}")
    print(f"各期限记录数     {result['records_per_tenor']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
