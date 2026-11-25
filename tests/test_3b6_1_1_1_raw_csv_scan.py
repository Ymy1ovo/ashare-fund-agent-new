"""阶段3B-6.1.1.1 原始 CSV 逐行校验测试。

**为什么上一版测试不可靠**：原测试把原始 CSV 解析成
``series[(date, tenor)] = value`` 字典后再检查重复——字典赋值会**覆盖**重复键，
重复记录在检查之前就已经消失。同时原解析器用 ``try/except ValueError: continue``
静默跳过坏日期、空值和非数值，可能掩盖真实质量问题。

本测试改为**先逐行扫描原始记录、再统计**，并通过人为构造的临时 CSV
验证扫描器确实能发现问题（正向 + 反向双向验证）。
"""
from __future__ import annotations

import csv
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORTS = ROOT / "reports"
RAW = REPORTS / "evidence" / "phase3B6_1_1" / "raw"
SCAN_JSON = REPORTS / "evidence" / "phase3B6_1_1" / "raw_csv_scan.json"
SCANNER = ROOT / "scripts" / "scan_3b6_1_1_1_raw_csv.py"

TENORS = ["3月", "6月", "1年", "3年", "5年", "7年", "10年", "30年"]
CURVE = "中债国债收益率曲线"
HEADER = ["曲线名称", "日期"] + TENORS


def _load_scanner():
    """导入真实扫描器模块（执行的是审计用的同一套逻辑）。"""
    assert SCANNER.exists(), "缺扫描脚本"
    spec = importlib.util.spec_from_file_location("raw_csv_scanner", SCANNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def scanner():
    return _load_scanner()


@pytest.fixture(scope="module")
def scan_result(scanner):
    """真实 42 份 CSV 的扫描结果（现算，不读缓存 JSON）。"""
    return scanner.scan_all()


def _write_csv(tmp_path: Path, rows, name="t.csv") -> Path:
    p = tmp_path / name
    with open(p, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        for r in rows:
            w.writerow(r)
    return p


def _row(date, vals):
    """构造一行：vals 为 8 个期限的值（缺席填 ''）。"""
    return [CURVE, date] + list(vals)


# ============================================================ 0 为什么原测试不可靠
def test_dict_parsing_hides_duplicates(tmp_path):
    """证明：先建字典再查重，无法发现重复行。"""
    p = _write_csv(tmp_path, [
        _row("2024-01-02", [1.1] * 8),
        _row("2024-01-02", [1.1] * 8),   # 完全重复
    ])
    with open(p, encoding="utf-8-sig", newline="") as fh:
        series = {}
        for row in csv.DictReader(fh):
            for t in TENORS:
                series[(row["日期"], t)] = row[t]
    # 字典里只剩 8 条，重复消失了——这正是旧测试的盲区
    assert len(series) == 8
    dup_in_dict = [k for k, c in Counter(series.keys()).items() if c > 1]
    assert dup_in_dict == [], "字典法必然检测不到重复"

    # 逐行扫描则能发现
    mod = _load_scanner()
    st = mod.scan_file(p)
    assert st["raw_rows"] == 2
    assert st["date_parsed_rows"] == 2
    recs = [r for r in st["records"] if r[4] == "valid"]
    assert len(recs) == 16
    c = Counter((d, t) for d, t, v, ln, k in recs)
    assert sum(n - 1 for n in c.values()) == 8, "逐行扫描应发现 8 条重复"


# ============================================================ 1 逐行计数
def test_raw_rows_counted_before_dedup(scan_result):
    assert scan_result["files_scanned"] == 42
    assert scan_result["raw_rows_total"] > 0
    assert scan_result["date_parsed_rows_total"] == scan_result["raw_rows_total"]
    assert scan_result["date_unparseable_rows_total"] == 0


def test_valid_records_equal_rows_times_tenors(scan_result):
    """有效记录数 = 行数 × 期限数（无跳过）。"""
    expected = scan_result["raw_rows_total"] * len(TENORS)
    assert scan_result["valid_records_total"] == expected


# ============================================================ 2 重复检查
def test_no_duplicate_pairs_in_real_data(scan_result):
    assert scan_result["duplicate_pairs_total"] == 0
    assert scan_result["duplicate_pairs_by_key"] == {}
    assert scan_result["unique_date_tenor_pairs"] == \
        scan_result["valid_records_total"]


def test_conflict_count_zero(scan_result):
    assert scan_result["conflict_keys"] == 0
    assert scan_result["conflict_detail"] == []


def test_duplicate_same_value_detected(tmp_path):
    """相同日期+期限+相同数值的重复，必须被发现。"""
    mod = _load_scanner()
    p = _write_csv(tmp_path, [
        _row("2024-01-02", ["1.5"] + [""] * 7),
        _row("2024-01-02", ["1.5"] + [""] * 7),
    ])
    st = mod.scan_file(p)
    recs = [r for r in st["records"] if r[4] == "valid"]
    c = Counter((d, t) for d, t, v, ln, k in recs)
    dups = {k: n for k, n in c.items() if n > 1}
    assert dups, "相同数值的重复未被发现"
    assert dups[("2024-01-02", "3月")] == 2
    # 数值相同，不是冲突
    vals = [v for d, t, v, ln, k in recs if (d, t) == ("2024-01-02", "3月")]
    assert len(set(vals)) == 1


def test_duplicate_different_value_detected_as_conflict(tmp_path):
    """相同日期+期限但数值不同，必须被识别为冲突。"""
    mod = _load_scanner()
    p = _write_csv(tmp_path, [
        _row("2024-01-02", ["1.5"] + [""] * 7),
        _row("2024-01-02", ["1.7"] + [""] * 7),
    ])
    st = mod.scan_file(p)
    recs = [r for r in st["records"] if r[4] == "valid"]
    vals = [v for d, t, v, ln, k in recs if (d, t) == ("2024-01-02", "3月")]
    assert len(vals) == 2
    assert len(set(vals)) == 2, "不同数值应被识别为冲突"
    assert max(vals) - min(vals) > 0.19


# ============================================================ 3 空值/异常行
def test_empty_value_detected(tmp_path):
    mod = _load_scanner()
    p = _write_csv(tmp_path, [_row("2024-01-02", ["", "1.2"] + [""] * 6)])
    st = mod.scan_file(p)
    assert st["empty_value_cells"] >= 1
    assert any(r[4] == "empty" for r in st["records"])


def test_non_numeric_detected(tmp_path):
    mod = _load_scanner()
    p = _write_csv(tmp_path, [_row("2024-01-02", ["abc"] + [""] * 7)])
    st = mod.scan_file(p)
    assert st["non_numeric_cells"] == 1
    assert any(s["kind"] == "non_numeric" for s in st["bad_samples"])


def test_bad_date_detected(tmp_path):
    mod = _load_scanner()
    p = _write_csv(tmp_path, [_row("2024/01/02", ["1.5"] + [""] * 7)])
    st = mod.scan_file(p)
    assert st["date_unparseable_rows"] == 1
    assert any(s["kind"] == "bad_date_format" for s in st["bad_samples"])


def test_impossible_date_detected(tmp_path):
    mod = _load_scanner()
    p = _write_csv(tmp_path, [_row("2024-02-31", ["1.5"] + [""] * 7)])
    st = mod.scan_file(p)
    assert st["date_unparseable_rows"] == 1


def test_empty_date_detected(tmp_path):
    mod = _load_scanner()
    p = _write_csv(tmp_path, [_row("", ["1.5"] + [""] * 7)])
    st = mod.scan_file(p)
    assert st["date_unparseable_rows"] == 1
    assert any(s["kind"] == "empty_date" for s in st["bad_samples"])


def test_nan_detected(tmp_path):
    mod = _load_scanner()
    p = _write_csv(tmp_path, [_row("2024-01-02", ["nan"] + [""] * 7)])
    st = mod.scan_file(p)
    assert st["nan_cells"] >= 1


def test_out_of_range_detected(tmp_path):
    mod = _load_scanner()
    p = _write_csv(tmp_path, [_row("2024-01-02", ["999.0"] + [""] * 7)])
    st = mod.scan_file(p)
    assert st["out_of_range_cells"] == 1


def test_normal_records_not_flagged(tmp_path):
    """正常记录不得被误判。"""
    mod = _load_scanner()
    p = _write_csv(tmp_path, [
        _row("2024-01-02", ["1.5", "1.6", "1.7", "2.0", "2.2", "2.4",
                             "2.5", "2.8"]),
    ])
    st = mod.scan_file(p)
    assert st["raw_rows"] == 1
    assert st["date_parsed_rows"] == 1
    assert st["date_unparseable_rows"] == 0
    assert st["empty_value_cells"] == 0
    assert st["non_numeric_cells"] == 0
    assert st["nan_cells"] == 0
    assert st["inf_cells"] == 0
    assert st["out_of_range_cells"] == 0
    ok = [r for r in st["records"] if r[4] == "valid"]
    assert len(ok) == len(TENORS)


def test_non_curve_rows_ignored(tmp_path):
    """非国债曲线的行不计入（但也不能污染统计）。"""
    mod = _load_scanner()
    p = tmp_path / "t.csv"
    with open(p, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        w.writerow(["中债中短期票据收益率曲线(AAA)", "2024-01-02"]
                   + ["2.0"] * 8)
        w.writerow(_row("2024-01-02", ["1.5"] * 8))
    st = mod.scan_file(p)
    assert st["raw_rows"] == 1, "只应统计国债曲线行"
    assert st["date_parsed_rows"] == 1


# ============================================================ 4 与 JSON 交叉复算
def test_records_per_tenor_match_coverage_json(scan_result):
    cov = json.loads((REPORTS / "phase3B6_1_1_coverage_quality.json")
                     .read_text(encoding="utf-8"))
    for t in TENORS:
        assert scan_result["records_per_tenor"][t] == \
            cov["tenors"][t]["valid_rows"], f"{t}: 逐行扫描与报告不一致"
        assert cov["tenors"][t]["valid_rows"] == 5185


def test_total_records_match_source_audit(scan_result):
    src = json.loads((REPORTS / "phase3B6_1_1_source_audit.json")
                     .read_text(encoding="utf-8"))
    assert scan_result["valid_records_total"] == 41480
    assert src["rows_after_dedup"] == 41480
    assert scan_result["valid_records_total"] == src["rows_after_dedup"]


def test_distinct_dates_match_source_audit(scan_result):
    src = json.loads((REPORTS / "phase3B6_1_1_source_audit.json")
                     .read_text(encoding="utf-8"))
    dates = set()
    for t in TENORS:
        pass
    # 用扫描结果反推：每个期限 5185 条且互不重复 → 独立日期 5185
    assert scan_result["records_per_tenor"][TENORS[0]] == 5185
    assert src["distinct_dates"] == 5185


def test_raw_rows_equal_distinct_dates(scan_result):
    """每个日期只出现一次（跨 42 文件不重叠）。"""
    assert scan_result["raw_rows_total"] == 5185
    # 重复对数为 0 → 行数 == 唯一日期数
    assert scan_result["unique_date_tenor_pairs"] == 41480


def test_zero_defects_in_real_data(scan_result):
    """真实数据的缺陷计数必须全为 0（若不为 0 需如实报告）。"""
    assert scan_result["date_unparseable_rows_total"] == 0
    assert scan_result["empty_value_cells_total"] == 0
    assert scan_result["non_numeric_cells_total"] == 0
    assert scan_result["nan_cells_total"] == 0
    assert scan_result["inf_cells_total"] == 0
    assert scan_result["out_of_range_cells_total"] == 0
    assert scan_result["duplicate_pairs_total"] == 0
    assert scan_result["conflict_keys"] == 0


# ============================================================ 5 证据落盘
def test_scan_evidence_exists_and_matches(scan_result):
    assert SCAN_JSON.exists(), "缺 raw_csv_scan.json 证据"
    d = json.loads(SCAN_JSON.read_text(encoding="utf-8"))
    assert d["files_scanned"] == scan_result["files_scanned"]
    assert d["valid_records_total"] == scan_result["valid_records_total"]
    assert d["duplicate_pairs_total"] == 0


# ============================================================ 只读与门禁
def test_no_database_write():
    from app.database.db import get_connection
    with get_connection() as c:
        assert c.execute("SELECT COUNT(*) FROM index_daily").fetchone()[0] == 50603
        assert c.execute("SELECT COUNT(*) FROM fund_nav_daily").fetchone()[0] == 245656


def test_fingerprint_unchanged():
    from app.fund.ingest_user_funds import db_fingerprint
    assert db_fingerprint()["sha256"] == (
        "115ac91eee7c26424952e6df23ddeeafe2435974fe5e81a8ba6bbcabfe387dd4")


def test_no_vacuous_assertion():
    src = Path(__file__).read_text(encoding="utf-8")
    bad = "or " + "True"
    for ln in src.splitlines():
        st = ln.strip()
        if st.startswith("#") or st.startswith('"') or st.startswith("'"):
            continue
        assert bad not in ln, f"恒真断言：{st}"


# ============================================================ 3B-6.1.1.1.1 新增
# 七类互斥识别 + 缺失期限字段显式报错

def test_classify_cell_seven_categories(scanner):
    """七类必须互斥，不能把 NaN/Inf 混入其它类。"""
    cases = [
        ("", "empty"),
        (None, "empty"),
        ("null", "empty"),
        ("NULL", "empty"),
        ("nan", "nan"),
        ("NaN", "nan"),
        ("-nan", "nan"),
        ("inf", "inf"),
        ("Inf", "inf"),
        ("-inf", "inf"),
        ("Infinity", "inf"),
        ("-Infinity", "inf"),
        ("abc", "non_numeric"),
        ("1.5", "valid"),
        ("999", "out_of_range"),
        ("-1", "out_of_range"),
        ("1e999", "inf"),      # 解析后是 inf
    ]
    for raw, expected in cases:
        kind, _ = scanner.classify_cell(raw)
        assert kind == expected, f"{raw!r}: 期望 {expected}，实际 {kind}"


def test_nan_counted_only_as_nan(tmp_path, scanner):
    """NaN 只计 nan，不得同时计 empty。"""
    p = _write_csv(tmp_path, [_row("2024-01-02", ["nan"] + [""] * 7)])
    st = scanner.scan_file(p)
    assert st["nan_cells"] == 1
    assert st["empty_value_cells"] == 7, "其余 7 个空列才是 empty"
    # 证明 NaN 与空值没有重复计数
    assert st["nan_cells"] + st["empty_value_cells"] == 8


def test_inf_counted_only_as_inf(tmp_path, scanner):
    """Inf 只计 inf，不得计 non_numeric。"""
    p = _write_csv(tmp_path, [_row("2024-01-02", ["inf"] + [""] * 7)])
    st = scanner.scan_file(p)
    assert st["inf_cells"] == 1
    assert st["non_numeric_cells"] == 0


def test_neg_inf_counted_as_inf(tmp_path, scanner):
    p = _write_csv(tmp_path, [_row("2024-01-02", ["-inf"] + [""] * 7)])
    st = scanner.scan_file(p)
    assert st["inf_cells"] == 1
    assert st["non_numeric_cells"] == 0


def test_abc_counted_as_non_numeric(tmp_path, scanner):
    p = _write_csv(tmp_path, [_row("2024-01-02", ["abc"] + [""] * 7)])
    st = scanner.scan_file(p)
    assert st["non_numeric_cells"] == 1
    assert st["nan_cells"] == 0
    assert st["inf_cells"] == 0


def test_mixed_nan_inf_abc_not_confused(tmp_path, scanner):
    """同一行同时出现 NaN / Inf / abc，三类必须互不混淆。"""
    p = _write_csv(tmp_path, [
        _row("2024-01-02", ["nan", "inf", "abc", "1.5", "", "2.0",
                             "2.5", "3.0"]),
    ])
    st = scanner.scan_file(p)
    assert st["nan_cells"] == 1
    assert st["inf_cells"] == 1
    assert st["non_numeric_cells"] == 1
    assert st["empty_value_cells"] == 1
    assert st["valid_cells"] == 4
    assert st["out_of_range_cells"] == 0

    kinds = {s["kind"] for s in st["bad_samples"]}
    assert {"nan", "inf", "non_numeric", "empty"} <= kinds


def test_bad_samples_keep_line_tenor_raw(tmp_path, scanner):
    """异常样本必须保留行号、期限、原始值。"""
    p = _write_csv(tmp_path, [
        _row("2024-01-02", ["1.5", "nan", "inf", "abc", "", "2.0",
                             "2.5", "3.0"]),
    ])
    st = scanner.scan_file(p)
    for s in st["bad_samples"]:
        if s["kind"] in ("nan", "inf", "non_numeric", "empty"):
            assert "line" in s
            assert "tenor" in s
            assert "raw" in s
    nan_sample = next(s for s in st["bad_samples"] if s["kind"] == "nan")
    assert nan_sample["tenor"] == "6月"
    assert nan_sample["raw"] == "nan"
    assert nan_sample["line"] == 2


# ============================================================ 缺失期限字段
def test_missing_tenor_column_detected(tmp_path, scanner):
    """缺少一个期限列必须显式报告。"""
    p = tmp_path / "missing.csv"
    header = ["曲线名称", "日期"] + [t for t in TENORS if t != "5年"]
    with open(p, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        vals = ["1.5"] * len(TENORS)
        w.writerow([CURVE, "2024-01-02"] + vals[:3] + vals[4:])
    st = scanner.scan_file(p)
    assert st["structure_ok"] is False
    assert "5年" in st["missing_columns"]
    assert st["tenor_presence"]["5年"] is False
    assert any(s["kind"] == "missing_columns" for s in st["bad_samples"])


def test_missing_multiple_columns_detected(tmp_path, scanner):
    p = tmp_path / "missing2.csv"
    header = ["曲线名称", "日期"] + [t for t in TENORS if t not in ("3月", "30年")]
    with open(p, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerow([CURVE, "2024-01-02"] + ["1.5"] * 6)
    st = scanner.scan_file(p)
    assert st["structure_ok"] is False
    assert set(st["missing_columns"]) == {"3月", "30年"}


def test_missing_date_column_detected(tmp_path, scanner):
    p = tmp_path / "nodate.csv"
    header = ["曲线名称"] + TENORS
    with open(p, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerow([CURVE] + ["1.5"] * 8)
    st = scanner.scan_file(p)
    assert st["structure_ok"] is False
    assert "日期" in st["missing_columns"]


def test_complete_8_tenor_csv_passes(tmp_path, scanner):
    """完整 8 期限的正常 CSV 必须判定结构正常且零缺陷。"""
    p = _write_csv(tmp_path, [
        _row("2024-01-02", ["1.5", "1.6", "1.7", "2.0", "2.2", "2.4",
                             "2.5", "2.8"]),
    ])
    st = scanner.scan_file(p)
    assert st["structure_ok"] is True
    assert st["missing_columns"] == []
    assert all(st["tenor_presence"].values())
    assert st["valid_cells"] == 8
    assert st["nan_cells"] == 0
    assert st["inf_cells"] == 0
    assert st["non_numeric_cells"] == 0
    assert st["empty_value_cells"] == 0
    assert st["out_of_range_cells"] == 0


def test_scan_all_reports_structure_status(scan_result):
    """真实 42 份 CSV 必须全部结构正常。"""
    assert scan_result["structure_all_ok"] is True
    assert scan_result["files_with_missing_columns"] == []
    assert scan_result["missing_columns_union"] == []
    assert scan_result["required_columns"] == \
        ["曲线名称", "日期"] + TENORS


def test_scanner_version_marked(scan_result):
    assert scan_result["scanner_version"] == "3B-6.1.1.1.1"
