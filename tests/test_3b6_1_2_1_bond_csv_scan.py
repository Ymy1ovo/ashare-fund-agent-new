"""阶段3B-6.1.2.1 债券指数原始 CSV 质量扫描测试。

**直接读取真实 CSV 或构造临时 CSV 调用真实扫描函数**，
不检查预计算 JSON 的结论字段。
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.scan_bond_index_csv import (  # noqa: E402
    classify_value, scan_csv, scan_dir)

REPORTS = ROOT / "reports"
RAW = REPORTS / "evidence" / "phase3B6_1_2" / "raw"
BOND = REPORTS / "phase3B6_1_2_bond_index_audit.json"

HEADER = ["date", "value"]


def _write(tmp_path: Path, rows, name="t.csv") -> Path:
    p = tmp_path / name
    with open(p, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        for r in rows:
            w.writerow(r)
    return p


# ============================================================ 分类互斥
def test_classify_seven_categories():
    cases = [
        ("", "empty"), (None, "empty"), ("null", "empty"),
        ("nan", "nan"), ("NaN", "nan"), ("-nan", "nan"),
        ("inf", "inf"), ("-inf", "inf"), ("Infinity", "inf"),
        ("abc", "non_numeric"),
        ("100.5", "valid"),
        ("0", "out_of_range"), ("-1", "out_of_range"),
        ("999999", "out_of_range"),
        ("1e999", "inf"),
    ]
    for raw, expected in cases:
        kind, _ = classify_value(raw)
        assert kind == expected, f"{raw!r}: 期望 {expected}，实际 {kind}"


def test_nan_not_counted_as_empty(tmp_path):
    p = _write(tmp_path, [["2024-01-02", "nan"], ["2024-01-03", ""]])
    st = scan_csv(p)
    assert st["nan_cells"] == 1
    assert st["empty_cells"] == 1
    assert st["nan_cells"] + st["empty_cells"] == 2


def test_inf_not_counted_as_non_numeric(tmp_path):
    p = _write(tmp_path, [["2024-01-02", "inf"], ["2024-01-03", "-inf"]])
    st = scan_csv(p)
    assert st["inf_cells"] == 2
    assert st["non_numeric_cells"] == 0


def test_abc_counted_as_non_numeric(tmp_path):
    p = _write(tmp_path, [["2024-01-02", "abc"]])
    st = scan_csv(p)
    assert st["non_numeric_cells"] == 1
    assert st["nan_cells"] == 0
    assert st["inf_cells"] == 0


def test_mixed_categories_not_confused(tmp_path):
    p = _write(tmp_path, [
        ["2024-01-02", "nan"],
        ["2024-01-03", "inf"],
        ["2024-01-04", "abc"],
        ["2024-01-05", ""],
        ["2024-01-06", "100.0"],
    ])
    st = scan_csv(p)
    assert st["nan_cells"] == 1
    assert st["inf_cells"] == 1
    assert st["non_numeric_cells"] == 1
    assert st["empty_cells"] == 1
    assert st["valid_rows"] == 1


# ============================================================ 日期
def test_bad_date_format_detected(tmp_path):
    p = _write(tmp_path, [["2024/01/02", "100.0"]])
    st = scan_csv(p)
    assert st["bad_date_format_rows"] == 1


def test_impossible_date_detected(tmp_path):
    p = _write(tmp_path, [["2024-02-31", "100.0"]])
    st = scan_csv(p)
    assert st["invalid_date_rows"] == 1


def test_empty_date_detected(tmp_path):
    p = _write(tmp_path, [["", "100.0"]])
    st = scan_csv(p)
    assert st["empty_date_rows"] == 1


def test_out_of_order_detected(tmp_path):
    """日期乱序必须被发现。"""
    p = _write(tmp_path, [
        ["2024-01-05", "100.0"],
        ["2024-01-03", "100.1"],
    ])
    st = scan_csv(p)
    assert st["out_of_order_rows"] == 1
    assert any(s["kind"] == "out_of_order" for s in st["bad_samples"])


def test_sorted_dates_no_false_positive(tmp_path):
    p = _write(tmp_path, [
        ["2024-01-02", "100.0"],
        ["2024-01-03", "100.1"],
        ["2024-01-04", "100.2"],
    ])
    st = scan_csv(p)
    assert st["out_of_order_rows"] == 0
    assert st["duplicate_dates"] == 0
    assert st["conflict_dates"] == 0


# ============================================================ 重复与冲突
def test_duplicate_date_detected(tmp_path):
    p = _write(tmp_path, [
        ["2024-01-02", "100.0"],
        ["2024-01-02", "100.0"],
    ])
    st = scan_csv(p)
    assert st["duplicate_dates"] == 1
    assert st["conflict_dates"] == 0


def test_conflict_date_detected(tmp_path):
    p = _write(tmp_path, [
        ["2024-01-02", "100.0"],
        ["2024-01-02", "101.0"],
    ])
    st = scan_csv(p)
    assert st["duplicate_dates"] == 1
    assert st["conflict_dates"] == 1
    assert st["conflict_detail"][0]["date"] == "2024-01-02"
    assert len(st["conflict_detail"][0]["values"]) == 2


# ============================================================ 结构
def test_missing_column_detected(tmp_path):
    p = tmp_path / "bad.csv"
    with open(p, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date"])
        w.writerow(["2024-01-02"])
    st = scan_csv(p)
    assert st["structure_ok"] is False
    assert "value" in st["missing_columns"]


def test_sha256_is_full_64(tmp_path):
    p = _write(tmp_path, [["2024-01-02", "100.0"]])
    st = scan_csv(p)
    assert len(st["sha256"]) == 64
    assert all(c in "0123456789abcdef" for c in st["sha256"])


def test_bytes_and_rows_recorded(tmp_path):
    p = _write(tmp_path, [["2024-01-02", "100.0"], ["2024-01-03", "100.1"]])
    st = scan_csv(p)
    assert st["bytes"] == p.stat().st_size
    assert st["raw_rows"] == 2
    assert st["valid_rows"] == 2


# ============================================================ 真实 CSV
@pytest.fixture(scope="module")
def real_files():
    files = sorted(RAW.glob("*.csv"))
    assert files, "缺债券指数原始 CSV"
    return files


def test_real_csv_exist(real_files):
    assert len(real_files) == 3


def test_real_csv_scan_zero_defects(real_files):
    """真实 3 份 CSV 逐行扫描必须零缺陷。"""
    for f in real_files:
        st = scan_csv(f)
        assert st["structure_ok"] is True
        assert st["raw_rows"] > 0
        assert st["valid_rows"] == st["raw_rows"]
        assert st["empty_cells"] == 0
        assert st["nan_cells"] == 0
        assert st["inf_cells"] == 0
        assert st["non_numeric_cells"] == 0
        assert st["out_of_range_cells"] == 0
        assert st["duplicate_dates"] == 0
        assert st["conflict_dates"] == 0
        assert st["out_of_order_rows"] == 0
        assert len(st["sha256"]) == 64


def test_real_csv_sha256_matches_json(real_files):
    """JSON 中的完整 SHA256 必须与真实文件一致。"""
    d = json.loads(BOND.read_text(encoding="utf-8"))
    json_shas = {}
    for t in d["targets"]:
        for p in t["probes"]:
            if p["status"] == "ok":
                json_shas[p["raw_file"]["file"]] = p["raw_file"]["sha256"]
    assert json_shas, "JSON 无原始文件记录"
    import hashlib
    for f in real_files:
        actual = hashlib.sha256(f.read_bytes()).hexdigest()
        assert len(actual) == 64
        assert json_shas.get(f.name) == actual, f"{f.name} SHA256 不一致"


def test_scan_dir_aggregate():
    res = scan_dir(RAW)
    agg = res["aggregate"]
    assert agg["files_scanned"] == 3
    assert agg["structure_all_ok"] is True
    assert agg["all_zero_defects"] is True
    assert agg["raw_rows_total"] == agg["valid_rows_total"]


# ============================================================ 异常记录
def test_api_error_records_type_and_message(tmp_path):
    """API 异常必须正确记录类型与信息，不因异常处理再报错。"""
    from scripts.audit_3b6_1_2_bond_index import probe
    rec = probe("__NOT_EXIST_INDEX__", "财富")
    assert rec["status"] == "error"
    assert rec["error_type"], "缺 error_type"
    assert rec["error_message"], "缺 error_message"
    assert "KeyError" in rec["error_type"]


def test_bond_json_error_field_structure():
    """已落盘 JSON 的 error 记录结构必须完整。"""
    d = json.loads(BOND.read_text(encoding="utf-8"))
    for t in d["targets"]:
        for p in t["probes"]:
            if p["status"] == "error":
                assert p.get("error_type")
                assert p.get("error_message")
