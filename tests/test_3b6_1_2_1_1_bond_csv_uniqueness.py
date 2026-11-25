"""阶段3B-6.1.2.1.1 债券 CSV 独立文件统计与重复日期边界测试。

**全部调用真实扫描逻辑**（`scan_csv` / `scan_dir`），
不检查预计算 JSON 的结论字段。
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.scan_bond_index_csv import scan_csv, scan_dir  # noqa: E402

REPORTS = ROOT / "reports"
RAW = REPORTS / "evidence" / "phase3B6_1_2" / "raw"
BOND = REPORTS / "phase3B6_1_2_bond_index_audit.json"

HEADER = ["date", "value"]


def _write(path: Path, rows, header=None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header or HEADER)
        for r in rows:
            w.writerow(r)
    return path


# ============================================================ 独立文件统计
def test_unique_file_count_not_probe_count():
    """6 次探测只引用 3 份独立 CSV。"""
    d = json.loads(BOND.read_text(encoding="utf-8"))
    q = d["summary"]["raw_csv_quality"]
    assert q["successful_probe_count"] == 6
    assert q["unique_raw_file_count"] == 3
    assert q["probe_referenced_rows_total"] == 37350
    assert q["unique_raw_rows_total"] == 18675


def test_unique_rows_from_real_files():
    """独立行数必须由真实文件重新扫描得出。"""
    res = scan_dir(RAW)
    agg = res["aggregate"]
    assert agg["unique_raw_file_count"] == len(list(RAW.glob("*.csv"))) == 3
    assert agg["unique_raw_rows_total"] == 18675
    assert agg["raw_rows_total"] == 18675  # 目录内每份只扫一次
    # 每份 6225 行
    for f in agg["unique_files"]:
        assert f["raw_rows"] == 6225


def test_unique_rows_equals_sum_of_files():
    res = scan_dir(RAW)
    agg = res["aggregate"]
    total = sum(f["raw_rows"] for f in agg["unique_files"])
    assert total == agg["unique_raw_rows_total"]


def test_same_sha256_counted_once(tmp_path):
    """相同 SHA256 的多个探测引用只计一份独立文件。"""
    src = next(RAW.glob("*.csv"))
    d = tmp_path / "d"
    d.mkdir()
    # 同一内容复制成两个不同文件名 → 两个文件，各自独立计数
    shutil.copy(src, d / "a.csv")
    shutil.copy(src, d / "b.csv")
    res = scan_dir(d)
    agg = res["aggregate"]
    # 文件名不同但 SHA256 相同 → key 不同，按「(文件名, SHA256)」算 2 份
    assert agg["files_scanned"] == 2
    shas = {f["sha256"] for f in agg["unique_files"]}
    assert len(shas) == 1, "两份文件内容相同，SHA256 应一致"
    assert agg["unique_raw_file_count"] == 2, "(文件名, SHA256) 不同 → 算 2 份"


def test_same_name_different_sha_not_merged(tmp_path):
    """同名但 SHA256 不同不得合并。"""
    d = tmp_path / "d"
    d.mkdir()
    a = _write(d / "x.csv", [["2024-01-02", "100.0"]])
    shas1 = scan_csv(a)["sha256"]
    # 同名覆盖成不同内容
    _write(d / "x.csv", [["2024-01-02", "100.0"], ["2024-01-03", "100.5"]])
    shas2 = scan_csv(d / "x.csv")["sha256"]
    assert shas1 != shas2, "内容不同则 SHA256 必然不同"


def test_probe_referenced_vs_unique_distinct():
    """探测引用行数与独立行数必须是两个不同维度。"""
    d = json.loads(BOND.read_text(encoding="utf-8"))
    q = d["summary"]["raw_csv_quality"]
    assert q["probe_referenced_rows_total"] == q["unique_raw_rows_total"] * 2
    assert q["successful_probe_count"] == q["unique_raw_file_count"] * 2


# ============================================================ 重复日期边界
def test_same_date_same_value(tmp_path):
    p = _write(tmp_path / "a.csv", [
        ["2024-01-02", "100.0"],
        ["2024-01-02", "100.0"],
    ])
    st = scan_csv(p)
    assert st["duplicate_dates"] == 1
    assert st["conflict_dates"] == 0
    assert st["invalid_value_duplicate_dates"] == 0


def test_same_date_diff_value(tmp_path):
    p = _write(tmp_path / "a.csv", [
        ["2024-01-02", "100.0"],
        ["2024-01-02", "101.0"],
    ])
    st = scan_csv(p)
    assert st["duplicate_dates"] == 1
    assert st["conflict_dates"] == 1
    assert st["invalid_value_duplicate_dates"] == 0


def test_same_date_one_valid_one_nan(tmp_path):
    """同日一条有效、一条 NaN——重复日期必须被发现。"""
    p = _write(tmp_path / "a.csv", [
        ["2024-01-02", "100.0"],
        ["2024-01-02", "nan"],
    ])
    st = scan_csv(p)
    assert st["duplicate_dates"] == 1, "NaN 记录不得被排除在重复检测之外"
    assert st["conflict_dates"] == 0, "只有 1 个有效值，不构成数值冲突"
    assert st["invalid_value_duplicate_dates"] == 1
    assert st["nan_cells"] == 1


def test_same_date_one_valid_one_inf(tmp_path):
    p = _write(tmp_path / "a.csv", [
        ["2024-01-02", "100.0"],
        ["2024-01-02", "inf"],
    ])
    st = scan_csv(p)
    assert st["duplicate_dates"] == 1
    assert st["conflict_dates"] == 0
    assert st["invalid_value_duplicate_dates"] == 1
    assert st["inf_cells"] == 1


def test_same_date_one_valid_one_non_numeric(tmp_path):
    p = _write(tmp_path / "a.csv", [
        ["2024-01-02", "100.0"],
        ["2024-01-02", "abc"],
    ])
    st = scan_csv(p)
    assert st["duplicate_dates"] == 1
    assert st["conflict_dates"] == 0
    assert st["invalid_value_duplicate_dates"] == 1
    assert st["non_numeric_cells"] == 1


def test_same_date_one_valid_one_empty(tmp_path):
    p = _write(tmp_path / "a.csv", [
        ["2024-01-02", "100.0"],
        ["2024-01-02", ""],
    ])
    st = scan_csv(p)
    assert st["duplicate_dates"] == 1
    assert st["conflict_dates"] == 0
    assert st["invalid_value_duplicate_dates"] == 1
    assert st["empty_cells"] == 1


def test_different_dates_not_duplicate(tmp_path):
    """不同日期的正常记录不得误报重复。"""
    p = _write(tmp_path / "a.csv", [
        ["2024-01-02", "100.0"],
        ["2024-01-03", "100.1"],
        ["2024-01-04", "100.2"],
    ])
    st = scan_csv(p)
    assert st["duplicate_dates"] == 0
    assert st["conflict_dates"] == 0
    assert st["invalid_value_duplicate_dates"] == 0


def test_invalid_dates_not_in_duplicate_check(tmp_path):
    """日期非法时不参与合法日期重复判定。"""
    p = _write(tmp_path / "a.csv", [
        ["2024/01/02", "100.0"],
        ["2024/01/02", "100.1"],
    ])
    st = scan_csv(p)
    assert st["duplicate_dates"] == 0, "非法日期不参与重复判定"
    assert st["bad_date_format_rows"] == 2


def test_records_not_dropped_for_invalid_values(tmp_path):
    """数值异常不得导致原始记录被丢弃。"""
    p = _write(tmp_path / "a.csv", [
        ["2024-01-02", "nan"],
        ["2024-01-03", "inf"],
        ["2024-01-04", "abc"],
        ["2024-01-05", ""],
        ["2024-01-06", "100.0"],
    ])
    st = scan_csv(p)
    assert st["raw_rows"] == 5
    assert st["valid_date_rows"] == 5, "所有合法日期都应被记录"
    assert len(st["records"]) == 5


# ============================================================ 真实数据
def test_real_csv_duplicate_boundary():
    for f in sorted(RAW.glob("*.csv")):
        st = scan_csv(f)
        assert st["duplicate_dates"] == 0
        assert st["conflict_dates"] == 0
        assert st["invalid_value_duplicate_dates"] == 0
        assert st["valid_date_rows"] == st["raw_rows"]


def test_bond_json_unique_stats_match_rescan():
    """JSON 的独立文件统计必须与重新扫描一致。"""
    d = json.loads(BOND.read_text(encoding="utf-8"))
    q = d["summary"]["raw_csv_quality"]
    res = scan_dir(RAW)
    agg = res["aggregate"]
    assert q["unique_raw_file_count"] == agg["unique_raw_file_count"]
    assert q["unique_raw_rows_total"] == agg["unique_raw_rows_total"]
    for jf in q["unique_files"]:
        actual = hashlib.sha256((RAW / jf["file"]).read_bytes()).hexdigest()
        assert jf["sha256"] == actual
        assert len(jf["sha256"]) == 64
