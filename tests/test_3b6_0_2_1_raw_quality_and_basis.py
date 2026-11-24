"""阶段3B-6.0.2.1 原始指数质量校验顺序 + 复合基准收益口径专项测试。

两个验收阻断：
A. 原始数据质量检查必须先于去重/排序，否则重复与倒序会被掩盖；
B. 复合基准可复现性必须检查 index_master.return_basis，
   「有历史行情」≠「有可用于总收益比较的序列」。

全部使用临时数据库，**绝不触碰正式库**。
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.fund.composite_benchmark import (  # noqa: E402
    COMPONENT_BOND, COMPONENT_CASH, COMPONENT_INDEX, add_component,
    create_composite, evaluate_composite, get_composite,
)
from app.fund.index_ingest import collect_one  # noqa: E402
from app.fund.index_layer import (  # noqa: E402
    RETURN_BASIS_NET, RETURN_BASIS_PRICE, RETURN_BASIS_TOTAL,
    RETURN_BASIS_UNKNOWN, count_index_daily, get_index_connection,
    get_index_master, init_index_layer, latest_quality_check,
    upsert_index_master,
)


# ---------------------------------------------------------------- 夹具
@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "raw_quality_test.db"
    with get_index_connection(path) as conn:
        init_index_layer(conn)
    return path


@pytest.fixture()
def conn(db):
    with get_index_connection(db) as c:
        yield c


def _df(dates, closes=None, prefix="测试"):
    n = len(dates)
    closes = closes or [1000.0 + i for i in range(n)]
    return pd.DataFrame({
        "日期": list(dates), "指数中文全称": [prefix + "指数"] * n,
        "指数中文简称": [prefix] * n,
        "开盘": [float(c) for c in closes],
        "最高": [float(c) + 5 for c in closes],
        "最低": [float(c) - 5 for c in closes],
        "收盘": list(closes)})


def _weekdays(start, n):
    out, cur = [], date.fromisoformat(start)
    while len(out) < n:
        if cur.weekday() < 5:
            out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def _ingest(conn, code, df, **kw):
    return collect_one(conn, code, index_name=code + "指数",
                       index_short_name=code, index_family="中证/上证系列",
                       fetcher=lambda s, a, b: df,
                       sleeper=lambda *_: None,
                       attempts=1, sleep_sec=0, **kw)


def _seed_index(conn, code, basis, rows=10):
    """写入一个有历史行情的指数，并指定收益口径。"""
    upsert_index_master(conn, index_code=code, index_name=code + "指数",
                        data_source="test", return_basis=basis)
    for d in _weekdays("2020-01-02", rows):
        conn.execute(
            "INSERT INTO index_daily (index_code, trade_date, close, source,"
            " collected_at, row_fingerprint) VALUES (?,?,?,?,?,?)",
            (code, d, 1000.0, "test", "2020-01-01T00:00:00", "fp_" + d))


# ================================================================
# 阻断一：原始数据质量检查必须先于去重/排序
# ================================================================
def test_A_duplicate_dates_rejected_at_ingest(conn):
    """A. 原始返回 5 行、其中 2 行日期相同 → 拒绝入库。"""
    base = _weekdays("2020-01-02", 4)
    dates = base[:2] + [base[1]] + base[2:]          # 5 行，第 2/3 行同日期
    assert len(dates) == 5
    assert len(set(dates)) == 4

    r = _ingest(conn, "000300", _df(dates))

    assert r["ok"] is False
    assert r["quality_hard_passed"] is False
    assert r["rows_written"] == 0
    assert count_index_daily(conn, "000300") == 0

    # 采集审计记录保留
    run = conn.execute(
        "SELECT status, returned_rows, note FROM index_ingest_runs "
        "WHERE run_id=?", (r["run_ids"][0],)).fetchone()
    assert run is not None
    assert run["status"] == "partial"
    assert run["returned_rows"] == 5
    assert "重复" in (run["note"] or "")

    # 质量记录能反映重复日期失败
    q = latest_quality_check(conn, "000300")
    assert q is not None
    assert q["duplicate_dates_ok"] == 0
    assert q["is_complete"] == 0
    assert q["quality_level"] == "D"
    detail = q["detail_json"] or ""
    assert "duplicate" in detail or "重复" in detail


def test_A2_duplicate_not_hidden_by_dedup(conn):
    """重复必须被检查到——证明去重没有跑在质检之前。"""
    base = _weekdays("2020-01-02", 4)
    dates = base[:2] + [base[1]] + base[2:]
    r = _ingest(conn, "000905", _df(dates))
    q = latest_quality_check(conn, "000905")
    assert q["duplicate_dates_ok"] == 0
    assert r["rows_returned"] == 5        # 原始 5 行如实记录，未被去重抹掉


def test_B_descending_dates_rejected_at_ingest(conn):
    """B. 原始返回日期倒序 → 拒绝入库。"""
    dates = list(reversed(_weekdays("2020-01-02", 5)))
    assert dates == sorted(dates, reverse=True)

    r = _ingest(conn, "000300", _df(dates))

    assert r["ok"] is False
    assert r["quality_hard_passed"] is False
    assert count_index_daily(conn, "000300") == 0

    q = latest_quality_check(conn, "000300")
    assert q is not None
    assert q["date_ascending_ok"] == 0
    assert q["quality_level"] == "D"

    run = conn.execute(
        "SELECT status, note FROM index_ingest_runs WHERE run_id=?",
        (r["run_ids"][0],)).fetchone()
    assert run["status"] == "partial"
    assert "升序" in (run["note"] or "") or "倒序" in (run["note"] or "")


def test_B2_descending_not_hidden_by_sort(conn):
    """倒序必须被检查到——证明排序没有跑在质检之前。"""
    dates = list(reversed(_weekdays("2020-01-02", 5)))
    r = _ingest(conn, "000906", _df(dates))
    q = latest_quality_check(conn, "000906")
    assert q["date_ascending_ok"] == 0
    assert r["rows_returned"] == 5


def test_C_normal_data_ingested(conn):
    """C. 正常升序无重复 5 行 → 正常入库 5 行。"""
    dates = _weekdays("2020-01-02", 5)
    r = _ingest(conn, "000300", _df(dates))

    assert r["ok"] is True
    assert r["quality_hard_passed"] is True
    assert r["rows_written"] == 5
    assert count_index_daily(conn, "000300") == 5
    assert r["rows_returned"] == 5

    q = latest_quality_check(conn, "000300")
    assert q["is_complete"] == 1
    assert q["duplicate_dates_ok"] == 1
    assert q["date_ascending_ok"] == 1


def test_C2_normal_order_preserved_in_result(conn):
    """正常数据入库后日期区间正确。"""
    dates = _weekdays("2020-01-02", 5)
    r = _ingest(conn, "000300", _df(dates))
    assert r["date_min"] == dates[0]
    assert r["date_max"] == dates[-1]


def test_raw_quality_runs_before_normalization(conn):
    """顺序证明：原始 5 行含重复，若有去重前置则 duplicate_dates_ok 会是 1。"""
    base = _weekdays("2020-01-02", 4)
    dates = base[:2] + [base[1]] + base[2:]
    _ingest(conn, "000300", _df(dates))
    q = latest_quality_check(conn, "000300")
    # 原始 5 行 → 质检看到重复 → 失败；若先排序去重则只会有 4 行且通过
    assert q["row_count"] == 5
    assert q["duplicate_dates_ok"] == 0


def test_rejected_data_leaves_no_daily_rows(conn):
    """被拒数据不得留下任何 index_daily 行。"""
    dates = list(reversed(_weekdays("2020-01-02", 5)))
    _ingest(conn, "000300", _df(dates))
    assert conn.execute("SELECT COUNT(*) FROM index_daily").fetchone()[0] == 0


def test_master_recorded_on_quality_failure(conn):
    """质量失败仍登记 master，便于追溯。"""
    dates = list(reversed(_weekdays("2020-01-02", 5)))
    _ingest(conn, "000300", _df(dates))
    m = get_index_master(conn, "000300")
    assert m is not None
    assert m["return_basis"] == RETURN_BASIS_UNKNOWN
    assert m["layer_status"] == "degraded"


# ================================================================
# 阻断二：复合基准必须校验收益口径
# ================================================================
def test_D_unknown_basis_blocks_reproducible(conn):
    """A 类：有历史数据但口径 unknown → 不可复现，原因指出口径未知。"""
    _seed_index(conn, "000300", RETURN_BASIS_UNKNOWN)
    assert count_index_daily(conn, "000300") == 10   # 确实有数据

    cid = create_composite(conn, benchmark_name="测试", benchmark_raw_text="x")
    add_component(conn, cid, component_type=COMPONENT_INDEX,
                  component_label="沪深300", index_code="000300", weight=1.0)
    add_component(conn, cid, component_type=COMPONENT_INDEX,
                  component_label="中证500", index_code="000300", weight=0.0)

    v = evaluate_composite(conn, cid)
    assert v["is_reproducible"] is False
    assert "unknown" in v["missing_reason"]
    assert "口径" in v["missing_reason"]


def test_D2_unknown_component_marked_unavailable(conn):
    """口径 unknown 时 data_available 必须为 0。"""
    _seed_index(conn, "000300", RETURN_BASIS_UNKNOWN)
    cid = create_composite(conn, benchmark_name="测试", benchmark_raw_text="x")
    add_component(conn, cid, component_type=COMPONENT_INDEX,
                  component_label="沪深300", index_code="000300", weight=0.95)
    comp = get_composite(conn, cid)["components"][0]
    assert comp["data_available"] == 0
    assert "unknown" in (comp["unavailable_reason"] or "")


def test_E_price_return_blocks_reproducible(conn):
    """B 类：有数据但口径 price_return → 不得冒充全收益，原因指出不含分红。"""
    _seed_index(conn, "000300", RETURN_BASIS_PRICE)

    cid = create_composite(conn, benchmark_name="测试", benchmark_raw_text="x")
    add_component(conn, cid, component_type=COMPONENT_INDEX,
                  component_label="沪深300", index_code="000300", weight=1.0)
    add_component(conn, cid, component_type=COMPONENT_INDEX,
                  component_label="占位", index_code="000300", weight=0.0)

    v = evaluate_composite(conn, cid)
    assert v["is_reproducible"] is False
    assert "price_return" in v["missing_reason"]
    assert "分红" in v["missing_reason"]


def test_F_total_return_passes_basis_but_others_block(conn):
    """C 类：口径 total_return 通过成分检查，但其他成分缺失仍不可复现。"""
    _seed_index(conn, "000300", RETURN_BASIS_TOTAL)

    cid = create_composite(conn, benchmark_name="测试", benchmark_raw_text="x")
    add_component(conn, cid, component_type=COMPONENT_INDEX,
                  component_label="沪深300", index_code="000300", weight=0.70)
    add_component(conn, cid, component_type=COMPONENT_BOND,
                  component_label="中债综合", weight=0.30)

    # 指数成分通过口径检查
    comps = get_composite(conn, cid)["components"]
    idx_comp = next(c for c in comps if c["component_type"] == COMPONENT_INDEX)
    assert idx_comp["data_available"] == 1

    # 但整体仍不可复现（债券成分无序列）
    v = evaluate_composite(conn, cid)
    assert v["is_reproducible"] is False
    assert "债券" in v["missing_reason"] or "bond" in v["missing_reason"]


def test_G_net_total_return_passes_and_kept_distinct(conn):
    """D 类：net_total_return 通过检查，且与 total_return 保持独立标识。"""
    _seed_index(conn, "000300", RETURN_BASIS_NET)
    _seed_index(conn, "000905", RETURN_BASIS_TOTAL)

    cid = create_composite(conn, benchmark_name="测试", benchmark_raw_text="x")
    add_component(conn, cid, component_type=COMPONENT_INDEX,
                  component_label="净值指数", index_code="000300", weight=0.5)
    add_component(conn, cid, component_type=COMPONENT_INDEX,
                  component_label="全收益指数", index_code="000905", weight=0.5)

    comps = {c["index_code"]: c for c in get_composite(conn, cid)["components"]}
    assert comps["000300"]["data_available"] == 1
    assert comps["000905"]["data_available"] == 1

    # 口径各自独立保存，没有被统一改写
    assert get_index_master(conn, "000300")["return_basis"] == RETURN_BASIS_NET
    assert get_index_master(conn, "000905")["return_basis"] == RETURN_BASIS_TOTAL


def test_H_cash_still_blocks_even_with_good_basis(conn):
    """口径合格但现金成分无序列 → 仍不可复现。"""
    _seed_index(conn, "000300", RETURN_BASIS_TOTAL)
    cid = create_composite(conn, benchmark_name="测试", benchmark_raw_text="x")
    add_component(conn, cid, component_type=COMPONENT_INDEX,
                  component_label="沪深300", index_code="000300", weight=0.95)
    add_component(conn, cid, component_type=COMPONENT_CASH,
                  component_label="cash", weight=0.05)
    v = evaluate_composite(conn, cid)
    assert v["is_reproducible"] is False
    assert "无可用收益序列" in v["missing_reason"]


def test_I_missing_weight_still_not_reproducible(conn):
    """F 类：缺历史权重证据仍不可复现，且不补造。"""
    _seed_index(conn, "000300", RETURN_BASIS_TOTAL)
    cid = create_composite(conn, benchmark_name="测试", benchmark_raw_text="x")
    add_component(conn, cid, component_type=COMPONENT_INDEX,
                  component_label="沪深300", index_code="000300", weight=None)
    add_component(conn, cid, component_type=COMPONENT_INDEX,
                  component_label="沪深300-b", index_code="000300", weight=0.5)

    v = evaluate_composite(conn, cid)
    assert v["is_reproducible"] is False
    assert "权重" in v["missing_reason"]

    comps = get_composite(conn, cid)["components"]
    no_weight = [c for c in comps if c["weight"] is None]
    assert len(no_weight) == 1
    assert no_weight[0]["weight"] is None      # 未补造


def test_J_fake_series_is_not_total_return(conn):
    """「有历史行情」≠「有可用于总收益比较的序列」。"""
    _seed_index(conn, "000300", RETURN_BASIS_UNKNOWN)
    assert count_index_daily(conn, "000300") == 10        # 有行情
    cid = create_composite(conn, benchmark_name="测试", benchmark_raw_text="x")
    add_component(conn, cid, component_type=COMPONENT_INDEX,
                  component_label="沪深300", index_code="000300", weight=0.5)
    add_component(conn, cid, component_type=COMPONENT_INDEX,
                  component_label="沪深300-b", index_code="000300", weight=0.5)
    comps = get_composite(conn, cid)["components"]
    assert all(c["data_available"] == 0 for c in comps)   # 但不可用


# ================================================================
# 正式库现状：10 个 unknown，15 条复合基准不可复现
# ================================================================
def test_K_production_all_indices_unknown():
    """E 类：正式库 10 个指数仍全部 unknown。"""
    with get_index_connection() as c:
        rows = c.execute(
            "SELECT return_basis, COUNT(*) FROM index_master "
            "GROUP BY return_basis").fetchall()
    by = {r[0]: r[1] for r in rows}
    assert by.get("unknown") == 10
    assert by.get("total_return", 0) == 0
    assert by.get("net_total_return", 0) == 0
    assert by.get("price_return", 0) == 0


def test_L_production_composites_none_reproducible():
    """E 类：正式库 15 条复合基准仍全部不可复现。"""
    with get_index_connection() as c:
        total = c.execute(
            "SELECT COUNT(*) FROM benchmark_composite").fetchone()[0]
        repro = c.execute(
            "SELECT COUNT(*) FROM benchmark_composite "
            "WHERE is_reproducible=1").fetchone()[0]
    assert total == 15
    assert repro == 0


def test_M_production_index_rows_unchanged():
    """正式库指数行数保持 50,603。"""
    with get_index_connection() as c:
        n = c.execute("SELECT COUNT(*) FROM index_daily").fetchone()[0]
    assert n == 50603


def test_N_production_basis_not_touched_by_tests():
    """跑完本轮测试后，正式库口径仍全 unknown（未被测试改写）。"""
    with get_index_connection() as c:
        basis = {r[0] for r in c.execute(
            "SELECT DISTINCT return_basis FROM index_master")}
    assert basis == {"unknown"}


# ================================================================
# 门禁
# ================================================================
def test_gate_unchanged():
    from app.fund.research.engine import analyze_by_code
    g = analyze_by_code("050002")["gate"]
    assert g["ready_for_research_analysis"] is True
    assert g["ready_for_backtest"] is False
    assert g["ready_for_formal_ranking"] is False
