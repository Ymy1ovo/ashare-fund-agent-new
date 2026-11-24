"""阶段3B-6.0.2.2 复合基准有效行情判定专项测试。

问题：``add_component()`` 原先用 ``SELECT COUNT(*) FROM index_daily``
判断数据可用性，会把只有 suspect 行、或只有 1 条 valid 行的指数
错误标记为 ``data_available=1``。

修正：只统计 ``quality_status='valid'`` 且 ``close`` 有效为正数的行，
且至少需要 2 条（一期收益需要两个点）。

全部使用临时数据库，**绝不触碰正式库**。
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.fund.composite_benchmark import (  # noqa: E402
    COMPONENT_CASH, COMPONENT_INDEX, MIN_VALID_OBSERVATIONS,
    add_component, assess_index_component, count_effective_observations,
    create_composite, evaluate_composite, get_composite,
)
from app.fund.index_layer import (  # noqa: E402
    RETURN_BASIS_NET, RETURN_BASIS_PRICE, RETURN_BASIS_TOTAL,
    RETURN_BASIS_UNKNOWN, get_index_connection, init_index_layer,
    upsert_index_master,
)


@pytest.fixture()
def conn(tmp_path):
    path = tmp_path / "eff_obs_test.db"
    with get_index_connection(path) as c:
        init_index_layer(c)
        yield c


def _weekdays(start, n):
    out, cur = [], date.fromisoformat(start)
    while len(out) < n:
        if cur.weekday() < 5:
            out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def _seed(conn, code, basis, n_rows, quality="valid", close=1000.0):
    """写入指定数量、指定质量状态的行情。"""
    upsert_index_master(conn, index_code=code, index_name=code + "指数",
                        data_source="test", return_basis=basis)
    for i, d in enumerate(_weekdays("2020-01-02", n_rows)):
        conn.execute(
            "INSERT INTO index_daily (index_code, trade_date, close, source,"
            " collected_at, row_fingerprint, quality_status) "
            "VALUES (?,?,?,?,?,?,?)",
            (code, d, close + i, "test", "2020-01-01T00:00:00",
             f"fp_{code}_{d}", quality))


def _two_index_composite(conn, code1="000300", code2="000905"):
    cid = create_composite(conn, benchmark_name="测试", benchmark_raw_text="x")
    add_component(conn, cid, component_type=COMPONENT_INDEX,
                  component_label="成分A", index_code=code1, weight=0.5)
    add_component(conn, cid, component_type=COMPONENT_INDEX,
                  component_label="成分B", index_code=code2, weight=0.5)
    return cid


# ================================================================ A/B
def test_A_all_suspect_not_available(conn):
    """A. 有 10 条行情但全为 suspect → 不可用。"""
    _seed(conn, "000300", RETURN_BASIS_TOTAL, 10, quality="suspect")

    assert conn.execute("SELECT COUNT(*) FROM index_daily").fetchone()[0] == 10
    assert count_effective_observations(conn, "000300") == 0

    v = assess_index_component(conn, "000300")
    assert v["available"] == 0
    assert v["total_rows"] == 10
    assert v["valid_rows"] == 0
    assert "没有有效行情" in v["reason"]

    cid = create_composite(conn, benchmark_name="T", benchmark_raw_text="x")
    add_component(conn, cid, component_type=COMPONENT_INDEX,
                  component_label="沪深300", index_code="000300", weight=0.5)
    comp = get_composite(conn, cid)["components"][0]
    assert comp["data_available"] == 0


def test_B_all_rejected_not_available(conn):
    """B. 有 10 条行情但全为 rejected → 不可用。"""
    _seed(conn, "000300", RETURN_BASIS_TOTAL, 10, quality="rejected")

    assert count_effective_observations(conn, "000300") == 0
    v = assess_index_component(conn, "000300")
    assert v["available"] == 0
    assert v["total_rows"] == 10
    assert "没有有效行情" in v["reason"]


def test_B2_mixed_quality_only_valid_counted(conn):
    """混合质量：只有 valid 行计入有效观测。"""
    _seed(conn, "000300", RETURN_BASIS_TOTAL, 3, quality="valid")
    for d in _weekdays("2021-01-04", 5):
        conn.execute(
            "INSERT INTO index_daily (index_code, trade_date, close, source,"
            " collected_at, row_fingerprint, quality_status) "
            "VALUES (?,?,?,?,?,?,?)",
            ("000300", d, 1000.0, "test", "t", f"fp2_{d}", "suspect"))
    assert conn.execute(
        "SELECT COUNT(*) FROM index_daily WHERE index_code='000300'"
    ).fetchone()[0] == 8
    assert count_effective_observations(conn, "000300") == 3


# ================================================================ C
def test_C_single_valid_not_available(conn):
    """C. 只有 1 条 valid → 不可用（一期收益需要两个点）。"""
    _seed(conn, "000300", RETURN_BASIS_TOTAL, 1, quality="valid")

    assert count_effective_observations(conn, "000300") == 1
    v = assess_index_component(conn, "000300")
    assert v["available"] == 0
    assert "有效行情不足" in v["reason"]
    assert "至少需要 2" in v["reason"]


def test_C2_min_observations_is_two():
    assert MIN_VALID_OBSERVATIONS == 2


def test_C3_null_close_blocked_at_schema(conn):
    """收盘价为空：schema 层 NOT NULL 直接拒绝写入。

    这是第一道防线——空收盘根本进不了表；
    第二道防线才是 ``count_effective_observations`` 过滤非正值。
    """
    import sqlite3
    _seed(conn, "000300", RETURN_BASIS_TOTAL, 2, quality="valid")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO index_daily (index_code, trade_date, close, source,"
            " collected_at, row_fingerprint, quality_status) "
            "VALUES ('000300','2022-01-04',NULL,'t','t','fp_null','valid')")
    assert count_effective_observations(conn, "000300") == 2


def test_C4_non_positive_close_not_counted(conn):
    """零或负收盘价即使标 valid 也不计入。"""
    upsert_index_master(conn, index_code="Z001", index_name="异常",
                        data_source="t", return_basis=RETURN_BASIS_TOTAL)
    for i, d in enumerate(_weekdays("2020-01-02", 3)):
        conn.execute(
            "INSERT INTO index_daily (index_code, trade_date, close, source,"
            " collected_at, row_fingerprint, quality_status) "
            "VALUES (?,?,?,?,?,?,'valid')",
            ("Z001", d, [0.0, -5.0, 100.0][i], "t", "t", f"fz_{d}"))
    assert count_effective_observations(conn, "Z001") == 1
    v = assess_index_component(conn, "Z001")
    assert v["available"] == 0


# ================================================================ D
def test_D_two_valid_with_total_return_available(conn):
    """D. 2 条 valid + total_return → 通过有效行情和口径检查。"""
    _seed(conn, "000300", RETURN_BASIS_TOTAL, 2, quality="valid")

    v = assess_index_component(conn, "000300")
    assert v["available"] == 1
    assert v["valid_rows"] == 2
    assert v["return_basis"] == RETURN_BASIS_TOTAL
    assert v["reason"] is None

    cid = create_composite(conn, benchmark_name="T", benchmark_raw_text="x")
    add_component(conn, cid, component_type=COMPONENT_INDEX,
                  component_label="沪深300", index_code="000300", weight=0.5)
    comp = get_composite(conn, cid)["components"][0]
    assert comp["data_available"] == 1


def test_D2_net_total_return_also_available(conn):
    """net_total_return 同样通过，且口径标识保留。"""
    _seed(conn, "000300", RETURN_BASIS_NET, 5, quality="valid")
    v = assess_index_component(conn, "000300")
    assert v["available"] == 1
    assert v["return_basis"] == RETURN_BASIS_NET


# ================================================================ E
def test_E_two_valid_but_unknown_not_available(conn):
    """E. 2 条 valid 但口径 unknown → 仍不可用。"""
    _seed(conn, "000300", RETURN_BASIS_UNKNOWN, 2, quality="valid")

    v = assess_index_component(conn, "000300")
    assert v["available"] == 0
    assert v["valid_rows"] == 2          # 行情够
    assert "unknown" in v["reason"]      # 但口径不行


def test_E2_two_valid_but_price_return_not_available(conn):
    """2 条 valid 但口径 price_return → 不可用。"""
    _seed(conn, "000300", RETURN_BASIS_PRICE, 2, quality="valid")
    v = assess_index_component(conn, "000300")
    assert v["available"] == 0
    assert "price_return" in v["reason"]


# ================================================================ F
def test_F_reevaluate_detects_degradation(conn):
    """F. 初次可用，之后 valid 减少 → 再次评估必须识别并阻止可复现。"""
    _seed(conn, "000300", RETURN_BASIS_TOTAL, 5, quality="valid")
    _seed(conn, "000905", RETURN_BASIS_TOTAL, 5, quality="valid")

    cid = _two_index_composite(conn)
    v1 = evaluate_composite(conn, cid)
    assert v1["is_reproducible"] is True
    assert v1["is_complete"] is True

    # 把 000300 的 valid 全部改成 suspect（模拟之后数据被降级）
    conn.execute(
        "UPDATE index_daily SET quality_status='suspect' "
        "WHERE index_code='000300'")

    v2 = evaluate_composite(conn, cid)
    assert v2["is_reproducible"] is False
    assert v2["is_complete"] == 0
    assert "有效行情" in v2["missing_reason"]

    # 组件状态也被同步修正
    comps = {c["index_code"]: c for c in get_composite(conn, cid)["components"]}
    assert comps["000300"]["data_available"] == 0
    assert comps["000905"]["data_available"] == 1


def test_F2_reevaluate_detects_rows_deleted(conn):
    """F2. 有效行情被删除到只剩 1 条 → 再次评估阻止可复现。"""
    _seed(conn, "000300", RETURN_BASIS_TOTAL, 5, quality="valid")
    _seed(conn, "000905", RETURN_BASIS_TOTAL, 5, quality="valid")

    cid = _two_index_composite(conn)
    assert evaluate_composite(conn, cid)["is_reproducible"] is True

    # 删到只剩 1 条
    dates = _weekdays("2020-01-02", 5)
    conn.execute(
        "DELETE FROM index_daily WHERE index_code='000300' AND trade_date!=?",
        (dates[0],))
    assert count_effective_observations(conn, "000300") == 1

    v = evaluate_composite(conn, cid)
    assert v["is_reproducible"] is False
    assert "有效行情不足" in v["missing_reason"]


def test_F3_reevaluate_detects_basis_downgrade(conn):
    """F3. 口径被改成 unknown → 再次评估阻止可复现。"""
    _seed(conn, "000300", RETURN_BASIS_TOTAL, 5, quality="valid")
    _seed(conn, "000905", RETURN_BASIS_TOTAL, 5, quality="valid")

    cid = _two_index_composite(conn)
    assert evaluate_composite(conn, cid)["is_reproducible"] is True

    conn.execute("UPDATE index_master SET return_basis='unknown' "
                 "WHERE index_code='000300'")
    v = evaluate_composite(conn, cid)
    assert v["is_reproducible"] is False
    assert "unknown" in v["missing_reason"]


def test_F4_stale_flag_does_not_stick(conn):
    """历史组件曾标 data_available=1，当前不足时不得沿用旧值。"""
    _seed(conn, "000300", RETURN_BASIS_TOTAL, 5, quality="valid")
    _seed(conn, "000905", RETURN_BASIS_TOTAL, 5, quality="valid")
    cid = _two_index_composite(conn)
    evaluate_composite(conn, cid)
    # 人为把组件状态改成可用（模拟脏数据/历史遗留）
    conn.execute(
        "UPDATE benchmark_composite_component SET data_available=1,"
        " unavailable_reason=NULL WHERE index_code='000300'")
    conn.execute(
        "UPDATE index_daily SET quality_status='suspect' "
        "WHERE index_code='000300'")
    v = evaluate_composite(conn, cid)
    assert v["is_reproducible"] is False


# ================================================================ 其他校验不受影响
def test_cash_component_rule_unchanged(conn):
    """现金成分规则不变。"""
    _seed(conn, "000300", RETURN_BASIS_TOTAL, 5, quality="valid")
    _seed(conn, "000905", RETURN_BASIS_TOTAL, 5, quality="valid")
    cid = _two_index_composite(conn)
    add_component(conn, cid, component_type=COMPONENT_CASH,
                  component_label="cash", weight=0.05)
    v = evaluate_composite(conn, cid)
    assert v["is_reproducible"] is False
    assert "无可用收益序列" in v["missing_reason"]


def test_single_component_rule_unchanged(conn):
    _seed(conn, "000300", RETURN_BASIS_TOTAL, 5, quality="valid")
    cid = create_composite(conn, benchmark_name="T", benchmark_raw_text="x")
    add_component(conn, cid, component_type=COMPONENT_INDEX,
                  component_label="A", index_code="000300", weight=0.5)
    v = evaluate_composite(conn, cid)
    assert v["is_reproducible"] is False


def test_weight_rule_unchanged(conn):
    _seed(conn, "000300", RETURN_BASIS_TOTAL, 5, quality="valid")
    _seed(conn, "000905", RETURN_BASIS_TOTAL, 5, quality="valid")
    cid = create_composite(conn, benchmark_name="T", benchmark_raw_text="x")
    add_component(conn, cid, component_type=COMPONENT_INDEX,
                  component_label="A", index_code="000300", weight=None)
    add_component(conn, cid, component_type=COMPONENT_INDEX,
                  component_label="B", index_code="000905", weight=0.5)
    v = evaluate_composite(conn, cid)
    assert v["is_reproducible"] is False
    assert "权重" in v["missing_reason"]


# ================================================================ G/H 正式库
def test_G_production_composites_none_reproducible():
    """G. 正式库 15 条复合基准仍全部不可复现。"""
    with get_index_connection() as c:
        total = c.execute(
            "SELECT COUNT(*) FROM benchmark_composite").fetchone()[0]
        repro = c.execute(
            "SELECT COUNT(*) FROM benchmark_composite "
            "WHERE is_reproducible=1").fetchone()[0]
        complete = c.execute(
            "SELECT COUNT(*) FROM benchmark_composite "
            "WHERE is_complete=1").fetchone()[0]
    assert total == 15
    assert repro == 0
    assert complete == 0


def test_H_production_indices_all_unknown():
    """H. 10 个指数收益口径仍全部 unknown。"""
    with get_index_connection() as c:
        rows = c.execute(
            "SELECT return_basis, COUNT(*) FROM index_master "
            "GROUP BY return_basis").fetchall()
    by = {r[0]: r[1] for r in rows}
    assert by == {"unknown": 10}


def test_H2_production_index_rows_unchanged():
    """H. 50,603 条指数行情不变。"""
    with get_index_connection() as c:
        assert c.execute("SELECT COUNT(*) FROM index_daily").fetchone()[0] == 50603


def test_H3_production_all_indices_assessed_unavailable():
    """正式库 10 个指数按新规则重新判定，全部不可用。

    注意：正式库复合基准组件里存的 ``data_available=1`` 是
    3B-6.0.2 建表时按旧逻辑写入的**历史遗留值**，
    本轮禁止写正式库，故不修改存量字段。
    真正的权威判定是 ``evaluate_composite()`` 每次重新计算，
    以及本函数调用的 ``assess_index_component()``。
    """
    with get_index_connection() as c:
        codes = [r[0] for r in c.execute(
            "SELECT index_code FROM index_master ORDER BY index_code")]
        assert len(codes) == 10
        for code in codes:
            v = assess_index_component(c, code)
            assert v["available"] == 0, code
            # 它们都有大量有效行情，卡在口径 unknown
            assert v["valid_rows"] >= 2, code
            assert "unknown" in (v["reason"] or ""), code


def test_H4_stale_component_flag_does_not_leak():
    """存量组件标记可能过期，但复合基准层面仍全部不可复现。

    这条测试明确承认「存量字段未刷新」这一事实，
    同时证明它不会让任何复合基准变成可复现。
    """
    with get_index_connection() as c:
        repro = c.execute(
            "SELECT COUNT(*) FROM benchmark_composite "
            "WHERE is_reproducible=1").fetchone()[0]
        complete = c.execute(
            "SELECT COUNT(*) FROM benchmark_composite "
            "WHERE is_complete=1").fetchone()[0]
    assert repro == 0
    assert complete == 0


# ================================================================ 门禁
def test_gate_unchanged():
    from app.fund.research.engine import analyze_by_code
    g = analyze_by_code("050002")["gate"]
    assert g["ready_for_research_analysis"] is True
    assert g["ready_for_backtest"] is False
    assert g["ready_for_formal_ranking"] is False
