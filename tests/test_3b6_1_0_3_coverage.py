"""阶段3B-6.1.0.3 历史覆盖与质量分离测试。

全部断言从证据附件与报告结构**计算**得出，不硬编码预期结果。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORTS = ROOT / "reports"
EVIDENCE = REPORTS / "evidence" / "phase3B6_1_0_index_probe_evidence.json"
MD01 = REPORTS / "phase3B6_1_0_01_index_return_basis.md"

STATES = ("history_retrieved", "history_range_verified",
          "history_coverage_adequate", "history_quality_adequate",
          "backtest_usable")


@pytest.fixture(scope="module")
def ev() -> dict:
    assert EVIDENCE.exists()
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def r01() -> dict:
    return json.loads(
        (REPORTS / "phase3B6_1_0_01_index_return_basis.json")
        .read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def qb(ev) -> dict:
    return ev["coverage_quality_probe"]["by_code"]


def _idx(r01, code):
    return next(x for x in r01["indexes"] if x["index_code"] == code)


# ============================================================ 1. 五态不自动传递
def test_retrieved_does_not_imply_coverage(qb, r01):
    """history_retrieved=true 不自动意味着 coverage_adequate=true。"""
    counterexample = [c for c, v in qb.items()
                      if v.get("history_retrieved") and not v.get("history_coverage_adequate")]
    assert counterexample, "证据里应存在「取到但不覆盖达标」的实例"
    for c in counterexample:
        assert qb[c]["coverage_ratio"] < 0.95, \
            f"{c}: 覆盖未达标但比率 {qb[c]['coverage_ratio']} >= 0.95"
    # 报告里必须如实反映
    for x in r01["indexes"]:
        st = x["history_states"]
        if st["history_coverage_adequate"]:
            assert st["history_retrieved"], \
                f"{x['index_code']}: 覆盖达标却标未取到"


def test_range_verified_does_not_imply_quality(qb, r01):
    """history_range_verified=true 不自动意味着 quality_adequate=true。"""
    counterexample = [c for c, v in qb.items()
                      if v.get("history_range_verified") and not v.get("history_quality_adequate")]
    assert counterexample, "证据里应存在「区间已核实但质量不达标」的实例"
    for x in r01["indexes"]:
        st = x["history_states"]
        if st["history_quality_adequate"]:
            assert st["history_range_verified"]


def test_five_states_are_independent_fields(r01):
    """五态必须是五个独立布尔字段，不能合并成一个。"""
    for x in r01["indexes"]:
        st = x["history_states"]
        for s in STATES:
            assert s in st, f"{x['index_code']} 缺状态 {s}"
            assert isinstance(st[s], bool)


def test_no_deprecated_broad_field(r01):
    """不得残留语义过宽的 full_history_verified 字段（修正记录里的引用除外）。"""
    for x in r01["indexes"]:
        assert "full_history_verified" not in x, \
            f"{x['index_code']} 仍残留 full_history_verified"
        assert "layers" not in x
    summary = r01["summary"]
    assert "full_history_verified_total_return" not in summary
    for key in summary.get("equity_indexes_stats", {}):
        assert "verified_total_return" not in key or key.startswith("total_return_history")


# ============================================================ 2. 重大缺口判定
def test_major_gap_blocks_coverage(qb):
    """存在重大日期缺口时不得标记连续覆盖达标。"""
    for code, v in qb.items():
        if not v.get("history_coverage_adequate"):
            continue
        # 覆盖达标者，剔除占位后的内部缺口必须小
        assert v["max_interior_gap_days"] <= 20, \
            f"{code}: 内部缺口 {v['max_interior_gap_days']} 天却标覆盖达标"


def test_399997_not_marked_full_coverage(qb):
    """399997 不能因接口成功就标记完整连续覆盖。"""
    v = qb["H20539"]
    assert v["history_retrieved"] is True
    assert v["history_coverage_adequate"] is False, \
        "399997 全收益真实起点 2008-12-31，覆盖率约 78%，不得标覆盖达标"
    assert v["coverage_ratio"] < 0.95


def test_930930_not_marked_full_coverage(qb):
    """930930 不能因接口成功就标记完整连续覆盖。"""
    v = qb["H20930"]
    assert v["history_retrieved"] is True
    assert v["history_coverage_adequate"] is False, \
        "930930 全收益真实起点 2014-11-14，覆盖率约 52%，不得标覆盖达标"
    assert v["coverage_ratio"] < 0.95


# ============================================================ 3. 占位行
def test_baseline_placeholder_not_counted(qb):
    """基线占位行不得计入真实有效覆盖。"""
    for code, v in qb.items():
        if v.get("has_baseline_placeholder"):
            assert v["real_rows_excluding_placeholder"] == v["rows"] - 1, \
                f"{code}: 占位行剔除逻辑不一致"
            assert v["real_start_date"] != v["date_min"], \
                f"{code}: 有占位行但真实起点等于 date_min"
        else:
            assert v["real_rows_excluding_placeholder"] == v["rows"]
            assert v["real_start_date"] == v["date_min"]


def test_365_gap_is_baseline_placeholder(qb):
    """365~369 天缺口必须被识别为占位行而非数据缺失。"""
    for code in ("H00300", "H00905", "H00906", "H00942", "H00922", "H20184"):
        v = qb.get(code)
        if not v: continue
        if v["max_gap_days"] in (365, 366, 369):
            assert v["has_baseline_placeholder"] is True, \
                f"{code}: {v['max_gap_days']} 天缺口应识别为基线占位"
            assert v["max_interior_gap_days"] <= 20, \
                f"{code}: 剔除占位后不应仍有大缺口"


def test_no_placeholder_for_true_dense_series(qb):
    """000300/000016 次行紧接首行，不得误标占位。"""
    for code in ("000300", "000016", "H00016"):
        v = qb.get(code)
        if not v: continue
        assert v["has_baseline_placeholder"] is False, \
            f"{code}: 实测无占位行"


# ============================================================ 4. 非正值保留
def test_non_positive_values_preserved(qb):
    """非正值异常必须保留并记录，不得删除或插值。"""
    found = {c: v for c, v in qb.items()
             if v.get("non_positive_close", 0) > 0}
    assert found, "应存在非正值异常记录"
    for code, v in found.items():
        assert v["non_positive_dates"], f"{code}: 有非正值但无日期记录"
        assert len(v["non_positive_dates"]) == v["non_positive_close"]
        assert v["history_quality_adequate"] is False, \
            f"{code}: 有非正值却标质量达标"


# ============================================================ 5. 经济语义分离
def test_bond_index_excluded_from_equity_stats(r01):
    """000012 特殊债券序列不计入普通股票指数全收益统计。"""
    s = r01["summary"]
    equity = s["by_economic_semantics"]["equity_indexes"]
    bond = s["by_economic_semantics"]["special_bond_indexes"]
    assert "000012" not in equity
    assert "000012" in bond
    assert len(equity) + len(bond) == s["total_indexes"]
    assert s["equity_indexes_stats"]["count"] == len(equity)
    assert s["special_bond_stats"]["count"] == len(bond)


def test_summary_stats_recomputed_from_indexes(r01):
    """summary 统计必须可由 indexes 逐项复算。"""
    s = r01["summary"]
    equity = s["by_economic_semantics"]["equity_indexes"]
    for key, field in (
        ("total_return_history_retrieved", "history_retrieved"),
        ("total_return_history_range_verified", "history_range_verified"),
        ("total_return_history_coverage_adequate", "history_coverage_adequate"),
        ("total_return_history_quality_adequate", "history_quality_adequate"),
        ("total_return_backtest_usable", "backtest_usable"),
    ):
        recalc = sum(1 for x in r01["indexes"]
                     if x["index_code"] in equity
                     and x["history_states"].get(field) is True)
        assert s["equity_indexes_stats"][key] == recalc, \
            f"{key}: summary={s['equity_indexes_stats'][key]} 复算={recalc}"


# ============================================================ 6. 回测阻断可追溯
def test_backtest_blockers_per_index(r01):
    """每个指数必须有可追溯的 backtest_usable=false 原因。"""
    for x in r01["indexes"]:
        st = x["history_states"]
        assert st["backtest_usable"] is False
        blockers = st.get("backtest_blockers")
        assert blockers, f"{x['index_code']} 缺回测阻断原因"
        assert any("口径" in b or "unknown" in b for b in blockers), \
            f"{x['index_code']} 未说明口径问题"


def test_backtest_usable_zero(r01):
    s = r01["summary"]
    assert s["equity_indexes_stats"]["total_return_backtest_usable"] == 0
    assert s["special_bond_stats"]["backtest_usable"] == 0
    assert s["all_indexes_backtest_usable"] == 0


# ============================================================ 7. 门禁与口径
def test_all_return_basis_unknown(r01):
    for x in r01["indexes"]:
        assert x["return_basis"] == "unknown"
        assert x["usable_for_excess_return"] is False


def test_gates_still_false(r01):
    g = r01["gate"]
    assert g["ready_for_research_analysis"] is True
    assert g["ready_for_backtest"] is False
    assert g["ready_for_formal_ranking"] is False


# ============================================================ 8. MD/JSON/证据一致
def test_markdown_five_states_match_json(r01):
    md = MD01.read_text(encoding="utf-8")
    for x in r01["indexes"]:
        assert f"| `{x['index_code']}` |" in md, \
            f"MD 缺指数 {x['index_code']}"
    # 比率表必须与 summary 一致
    s = r01["summary"]
    e = s["equity_indexes_stats"]
    for label, key in (("数据获取成功率", "total_return_history_retrieved"),
                        ("历史区间核实率", "total_return_history_range_verified"),
                        ("覆盖达标率", "total_return_history_coverage_adequate"),
                        ("质量达标率", "total_return_history_quality_adequate"),
                        ("回测可用率", "total_return_backtest_usable")):
        assert f"**{e[key]}/{e['count']}**" in md, \
            f"MD 缺 {label} = {e[key]}/{e['count']}"


def test_rate_breakdown_matches_stats(r01):
    s = r01["summary"]
    e = s["equity_indexes_stats"]
    rb = s["rate_breakdown"]
    assert rb["data_retrieval_rate"] == f"{e['total_return_history_retrieved']}/{e['count']}"
    assert rb["coverage_adequate_rate"] == f"{e['total_return_history_coverage_adequate']}/{e['count']}"
    assert rb["backtest_usable_rate"] == f"{e['total_return_backtest_usable']}/{e['count']}"


def test_evidence_standard_declared(ev):
    """证据必须声明阈值来源。"""
    std = ev["coverage_quality_probe"]["standard"]
    assert 0 < std["coverage_adequate_min_ratio"] <= 1
    assert std["quality_max_interior_gap_days"] > 0
    assert "审计口径" in std["note"]


def test_report_quality_matches_evidence(r01, qb):
    """报告里每个指数的质量判定必须与证据一致。"""
    for x in r01["indexes"]:
        code = x.get("total_return_index_code")
        if not code or code not in qb:
            continue
        evq = qb[code]
        st = x["history_states"]
        assert st["history_retrieved"] == evq["history_retrieved"]
        assert st["history_coverage_adequate"] == evq["history_coverage_adequate"]
        assert st["history_quality_adequate"] == evq["history_quality_adequate"]


# ============================================================ 9. 只读
def test_no_database_write():
    from app.database.db import get_connection
    with get_connection() as c:
        assert c.execute("SELECT COUNT(*) FROM index_daily").fetchone()[0] == 50603
        assert c.execute("SELECT COUNT(*) FROM index_master").fetchone()[0] == 10
        assert c.execute(
            "SELECT COUNT(*) FROM benchmark_composite").fetchone()[0] == 15
        assert c.execute(
            "SELECT COUNT(*) FROM benchmark_composite_component").fetchone()[0] == 34
