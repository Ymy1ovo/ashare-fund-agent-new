"""阶段3B-6.1.2.1.1.1 异常重复统计传递与探测引用去重测试。

**全部真实调用 `scan_csv()` 与 `_build_csv_quality()`**，
不检查预计算 JSON 的静态字段。
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.scan_bond_index_csv import scan_csv  # noqa: E402
from scripts.audit_3b6_1_2_bond_index import _build_csv_quality  # noqa: E402

REPORTS = ROOT / "reports"
RAW = REPORTS / "evidence" / "phase3B6_1_2" / "raw"
BOND = REPORTS / "phase3B6_1_2_bond_index_audit.json"

HEADER = ["date", "value"]


def _write(path: Path, rows) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        for r in rows:
            w.writerow(r)
    return path


def _target_from_csv(paths: list[Path]) -> list[dict]:
    """把若干真实 CSV 扫描结果包装成 targets 结构（模拟探测记录）。"""
    probes = []
    for p in paths:
        q = scan_csv(p)
        probes.append({
            "status": "ok",
            "raw_file": {
                "file": p.name,
                "bytes": q["bytes"],
                "sha256": q["sha256"],
                "sha256_16": q["sha256"][:16],
                "raw_rows": q["raw_rows"],
                "valid_rows": q["valid_rows"],
                "empty_cells": q["empty_cells"],
                "nan_cells": q["nan_cells"],
                "inf_cells": q["inf_cells"],
                "non_numeric_cells": q["non_numeric_cells"],
                "out_of_range_cells": q["out_of_range_cells"],
                "duplicate_dates": q["duplicate_dates"],
                "conflict_dates": q["conflict_dates"],
                "invalid_value_duplicate_dates":
                    q["invalid_value_duplicate_dates"],
                "valid_date_rows": q["valid_date_rows"],
                "out_of_order_rows": q["out_of_order_rows"],
                "structure_ok": q["structure_ok"],
            },
        })
    return [{"probes": probes}]


# ============================================================ 问题1：字段传递
def test_valid_plus_nan_aggregated(tmp_path):
    """同日一条有效 + 一条 NaN → 汇总必须为 1。"""
    p = _write(tmp_path / "nan_case.csv", [
        ["2024-01-02", "100.0"],
        ["2024-01-02", "nan"],
    ])
    st = scan_csv(p)
    assert st["invalid_value_duplicate_dates"] == 1, "扫描器必须先算对"

    q = _build_csv_quality(_target_from_csv([p]))
    assert q["total_invalid_value_duplicate_dates"] == 1
    assert q["total_duplicate_dates"] == 1
    assert q["total_conflicts"] == 0


def test_valid_plus_inf_aggregated(tmp_path):
    """同日一条有效 + 一条 Inf → 汇总必须为 1。"""
    p = _write(tmp_path / "inf_case.csv", [
        ["2024-01-02", "100.0"],
        ["2024-01-02", "inf"],
    ])
    st = scan_csv(p)
    assert st["invalid_value_duplicate_dates"] == 1

    q = _build_csv_quality(_target_from_csv([p]))
    assert q["total_invalid_value_duplicate_dates"] == 1
    assert q["total_conflicts"] == 0


def test_valid_plus_empty_aggregated(tmp_path):
    """同日一条有效 + 一条空值 → 汇总必须为 1。"""
    p = _write(tmp_path / "empty_case.csv", [
        ["2024-01-02", "100.0"],
        ["2024-01-02", ""],
    ])
    st = scan_csv(p)
    assert st["invalid_value_duplicate_dates"] == 1

    q = _build_csv_quality(_target_from_csv([p]))
    assert q["total_invalid_value_duplicate_dates"] == 1


def test_valid_plus_non_numeric_aggregated(tmp_path):
    """同日一条有效 + 一条非数值 → 汇总必须为 1。"""
    p = _write(tmp_path / "abc_case.csv", [
        ["2024-01-02", "100.0"],
        ["2024-01-02", "abc"],
    ])
    q = _build_csv_quality(_target_from_csv([p]))
    assert q["total_invalid_value_duplicate_dates"] == 1


def test_multiple_files_aggregate_sum(tmp_path):
    """多文件异常重复必须累加。"""
    p1 = _write(tmp_path / "a.csv", [
        ["2024-01-02", "100.0"], ["2024-01-02", "nan"]])
    p2 = _write(tmp_path / "b.csv", [
        ["2024-01-03", "100.0"], ["2024-01-03", "inf"]])
    q = _build_csv_quality(_target_from_csv([p1, p2]))
    assert q["total_invalid_value_duplicate_dates"] == 2


def test_clean_file_aggregates_zero(tmp_path):
    """干净文件汇总必须为 0，不能误报。"""
    p = _write(tmp_path / "clean.csv", [
        ["2024-01-02", "100.0"], ["2024-01-03", "100.1"]])
    q = _build_csv_quality(_target_from_csv([p]))
    assert q["total_invalid_value_duplicate_dates"] == 0
    assert q["total_duplicate_dates"] == 0
    assert q["total_conflicts"] == 0


def test_field_present_in_real_json():
    """真实 JSON 的 raw_file 必须含该字段。"""
    d = json.loads(BOND.read_text(encoding="utf-8"))
    found = 0
    for t in d["targets"]:
        for p in t["probes"]:
            if p["status"] == "ok":
                assert "invalid_value_duplicate_dates" in p["raw_file"]
                found += 1
    assert found == 6


def test_quality_detail_keeps_field():
    """quality_detail 中必须继续保留该字段。"""
    d = json.loads(BOND.read_text(encoding="utf-8"))
    for t in d["targets"]:
        for p in t["probes"]:
            if p["status"] == "ok":
                qd = p["raw_file"]["quality_detail"]
                assert "invalid_value_duplicate_dates" in qd
                assert qd["invalid_value_duplicate_dates"] == \
                    p["raw_file"]["invalid_value_duplicate_dates"]


# ============================================================ 问题2：探测去重
def test_same_file_referenced_multiple_times_counted_once(tmp_path):
    """同一文件被多次探测引用 → 独立文件只计一次。"""
    p = _write(tmp_path / "same.csv", [
        ["2024-01-02", "100.0"], ["2024-01-03", "100.1"]])
    # 同一文件引用 4 次
    q = _build_csv_quality(_target_from_csv([p, p, p, p]))
    assert q["successful_probe_count"] == 4, "探测次数按每次累计"
    assert q["probe_referenced_rows_total"] == 4 * 2, "引用行数按每次累计"
    assert q["unique_raw_file_count"] == 1, "独立文件只计一次"
    assert q["unique_raw_rows_total"] == 2, "独立行数只计一次"


def test_six_probes_three_unique_files(tmp_path):
    """构造 6 条探测、3 份独立文件。"""
    p1 = _write(tmp_path / "f1.csv", [["2024-01-02", "100.0"]])
    p2 = _write(tmp_path / "f2.csv", [["2024-01-02", "200.0"],
                                        ["2024-01-03", "200.1"]])
    p3 = _write(tmp_path / "f3.csv", [["2024-01-02", "300.0"],
                                        ["2024-01-03", "300.1"],
                                        ["2024-01-04", "300.2"]])
    # 6 次探测：f1×3, f2×2, f3×1
    q = _build_csv_quality(_target_from_csv([p1, p1, p1, p2, p2, p3]))
    assert q["successful_probe_count"] == 6
    assert q["probe_referenced_rows_total"] == 1 * 3 + 2 * 2 + 3 * 1  # 10
    assert q["unique_raw_file_count"] == 3
    assert q["unique_raw_rows_total"] == 1 + 2 + 3  # 6
    assert q["probe_referenced_rows_total"] != q["unique_raw_rows_total"]


def test_same_name_different_sha_counted_separately(tmp_path):
    """同名但 SHA256 不同 → 计为两个独立文件。"""
    p_old = _write(tmp_path / "x_v1.csv", [["2024-01-02", "100.0"]])
    st_old = scan_csv(p_old)

    p_new = _write(tmp_path / "x_v2.csv", [["2024-01-02", "100.0"],
                                             ["2024-01-03", "100.5"]])
    st_new = scan_csv(p_new)
    assert st_old["sha256"] != st_new["sha256"], "内容不同 SHA256 必不同"

    # 人为构造同名但不同 SHA256 的两条探测
    t = {"probes": [
        {"status": "ok", "raw_file": {
            "file": "same_name.csv", "bytes": st_old["bytes"],
            "sha256": st_old["sha256"], "sha256_16": st_old["sha256"][:16],
            "raw_rows": st_old["raw_rows"], "valid_rows": st_old["valid_rows"],
            "empty_cells": 0, "nan_cells": 0, "inf_cells": 0,
            "non_numeric_cells": 0, "out_of_range_cells": 0,
            "duplicate_dates": 0, "conflict_dates": 0,
            "invalid_value_duplicate_dates": 0,
            "out_of_order_rows": 0, "structure_ok": True}},
        {"status": "ok", "raw_file": {
            "file": "same_name.csv", "bytes": st_new["bytes"],
            "sha256": st_new["sha256"], "sha256_16": st_new["sha256"][:16],
            "raw_rows": st_new["raw_rows"], "valid_rows": st_new["valid_rows"],
            "empty_cells": 0, "nan_cells": 0, "inf_cells": 0,
            "non_numeric_cells": 0, "out_of_range_cells": 0,
            "duplicate_dates": 0, "conflict_dates": 0,
            "invalid_value_duplicate_dates": 0,
            "out_of_order_rows": 0, "structure_ok": True}},
    ]}
    q = _build_csv_quality([t])
    assert q["unique_raw_file_count"] == 2, "同名不同 SHA256 不得合并"
    assert q["unique_raw_rows_total"] == 1 + 2


def test_different_name_same_sha_counted_separately(tmp_path):
    """不同文件名但 SHA256 相同 → 按 (文件名, SHA256) 规则分别计数。"""
    p1 = _write(tmp_path / "a.csv", [["2024-01-02", "100.0"]])
    p2 = tmp_path / "b.csv"
    p2.write_bytes(p1.read_bytes())     # 完全相同字节
    st1, st2 = scan_csv(p1), scan_csv(p2)
    assert st1["sha256"] == st2["sha256"], "字节相同则 SHA256 相同"

    q = _build_csv_quality(_target_from_csv([p1, p2]))
    assert q["unique_raw_file_count"] == 2, "(文件名, SHA256) 不同即两份"
    assert q["unique_raw_rows_total"] == 2


def test_duplicate_uniqueness_by_name_and_sha(tmp_path):
    """同一 (文件名, SHA256) 重复引用与不同名同 SHA 的组合。"""
    p1 = _write(tmp_path / "a.csv", [["2024-01-02", "100.0"]])
    p2 = tmp_path / "b.csv"
    p2.write_bytes(p1.read_bytes())
    # a×2, b×1 → 独立 2 份，探测 3 次
    q = _build_csv_quality(_target_from_csv([p1, p1, p2]))
    assert q["successful_probe_count"] == 3
    assert q["unique_raw_file_count"] == 2
    assert q["unique_raw_rows_total"] == 2
    assert q["probe_referenced_rows_total"] == 3


def test_probe_and_unique_never_confused(tmp_path):
    """探测统计与独立文件统计必须互不混淆。"""
    p1 = _write(tmp_path / "f1.csv", [["2024-01-02", "100.0"],
                                        ["2024-01-03", "100.1"]])
    p2 = _write(tmp_path / "f2.csv", [["2024-01-02", "200.0"]])
    q = _build_csv_quality(_target_from_csv([p1, p1, p2, p2, p1]))
    assert q["successful_probe_count"] == 5
    assert q["unique_raw_file_count"] == 2
    assert q["probe_referenced_rows_total"] == 2 + 2 + 1 + 1 + 2
    assert q["unique_raw_rows_total"] == 3


# ============================================================ 真实数据
def test_real_data_after_fix():
    """真实数据复核：3 份独立、18,675 行；6 次探测、37,350 行。"""
    d = json.loads(BOND.read_text(encoding="utf-8"))
    q = d["summary"]["raw_csv_quality"]
    assert q["successful_probe_count"] == 6
    assert q["probe_referenced_rows_total"] == 37350
    assert q["unique_raw_file_count"] == 3
    assert q["unique_raw_rows_total"] == 18675
    assert q["total_duplicate_dates"] == 0
    assert q["total_conflicts"] == 0
    assert q["total_invalid_value_duplicate_dates"] == 0


def test_real_sha256_matches_files():
    """每份文件完整 SHA256 必须与真实文件重算一致。"""
    d = json.loads(BOND.read_text(encoding="utf-8"))
    q = d["summary"]["raw_csv_quality"]
    for jf in q["unique_files"]:
        actual = hashlib.sha256((RAW / jf["file"]).read_bytes()).hexdigest()
        assert jf["sha256"] == actual
        assert len(jf["sha256"]) == 64


def test_build_csv_quality_on_real_json_targets():
    """用真实 JSON 的 targets 重跑汇总，结果必须一致。"""
    d = json.loads(BOND.read_text(encoding="utf-8"))
    recomputed = _build_csv_quality(d["targets"])
    original = d["summary"]["raw_csv_quality"]
    for k in ("successful_probe_count", "probe_referenced_rows_total",
              "unique_raw_file_count", "unique_raw_rows_total",
              "total_invalid_value_duplicate_dates"):
        assert recomputed[k] == original[k], f"{k} 不一致"
