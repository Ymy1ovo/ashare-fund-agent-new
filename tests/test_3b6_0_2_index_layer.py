"""阶段3B-6.0.2 指数与基准数据层专项测试。

全部使用临时数据库，**绝不触碰正式库**。
"""
from __future__ import annotations

import sqlite3
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
from app.fund.index_ingest import (  # noqa: E402
    FIRST_BATCH, _to_rows, collect_first_batch, collect_one, retry_failed,
)
from app.fund.index_layer import (  # noqa: E402
    QUALITY_A, QUALITY_B, QUALITY_D, RETURN_BASIS_NET, RETURN_BASIS_PRICE,
    RETURN_BASIS_TOTAL, RETURN_BASIS_UNKNOWN,
    content_fingerprint, count_index_daily, effective_date_range,
    get_index_connection, get_index_master, index_date_range,
    init_index_layer, latest_quality_check, row_fingerprint,
    save_quality_check, start_ingest_run,
)
from app.fund.index_returns import (  # noqa: E402
    ReturnBasisError, assert_basis_usable_for_total_return, basis_kind,
)
from app.fund.research.index_verify import check_history_quality  # noqa: E402


# ================================================================ 夹具
@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "index_test.db"
    with get_index_connection(path) as conn:
        init_index_layer(conn)
    return path


@pytest.fixture()
def conn(db):
    with get_index_connection(db) as c:
        yield c


def _df(dates, closes=None, null_open=0, prefix="沪深300"):
    n = len(dates)
    closes = closes or [1000.0 + i for i in range(n)]
    opens = [float(c) for c in closes]
    for i in range(min(null_open, n)):
        opens[i] = None
    return pd.DataFrame({
        "日期": list(dates), "指数中文全称": [prefix + "指数"] * n,
        "指数中文简称": [prefix] * n, "开盘": opens,
        "最高": [float(c) + 5 for c in closes],
        "最低": [float(c) - 5 for c in closes], "收盘": list(closes)})


def _weekdays(start, n):
    out, cur = [], date.fromisoformat(start)
    while len(out) < n:
        if cur.weekday() < 5:
            out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def _ok_fetcher(symbol, start, end):
    return _df(_weekdays("2020-01-02", 30), prefix=symbol)


def _ingest(conn, code="000300", fetcher=_ok_fetcher, **kw):
    return collect_one(conn, code, index_name=code + "指数",
                       index_short_name=code, index_family="中证/上证系列",
                       fetcher=fetcher, sleeper=lambda *_: None, **kw)


# ================================================================ 1. 代码唯一性
def test_index_code_primary_key_unique(conn):
    """指数代码是主键，重复登记只更新不新增。"""
    from app.fund.index_layer import upsert_index_master
    upsert_index_master(conn, index_code="000300", index_name="沪深300指数",
                        data_source="test")
    upsert_index_master(conn, index_code="000300", index_name="沪深300指数改名",
                        data_source="test")
    n = conn.execute("SELECT COUNT(*) FROM index_master").fetchone()[0]
    assert n == 1
    assert get_index_master(conn, "000300")["index_name"] == "沪深300指数改名"


def test_first_batch_codes_unique():
    codes = [c[0] for c in FIRST_BATCH]
    assert len(codes) == len(set(codes)) == 10


# ================================================================ 2. 同日期唯一
def test_same_index_same_date_unique(conn):
    """同一指数同一日期不能产生重复有效记录。"""
    _ingest(conn, "000300")
    assert count_index_daily(conn, "000300") == 30
    _ingest(conn, "000300")
    assert count_index_daily(conn, "000300") == 30   # 幂等，不翻倍


def test_duplicate_dates_in_payload_rejected_at_ingest(conn):
    """【3B-6.0.2.1 收紧】原始返回重复日期 → 采集入口直接拒绝，0 行入库。

    旧版此处断言「去重后入库成功」——正是本轮要修的绕过：
    字典去重发生在质量检查之前，重复记录在检查前就被抹掉了。
    收紧后：原始数据先质检，重复即硬性失败，绝不允许去重掩盖。
    """
    dates = _weekdays("2020-01-02", 5) + ["2020-01-06"]   # 重复 1 条
    r = _ingest(conn, "000905", fetcher=lambda s, a, b: _df(dates))
    assert r["ok"] is False
    assert r["quality_hard_passed"] is False
    assert count_index_daily(conn, "000905") == 0


def test_db_level_no_duplicate(conn):
    """数据库层面也无法插入重复主键。"""
    _ingest(conn, "000300")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO index_daily (index_code, trade_date, close, source, "
            "collected_at, row_fingerprint) VALUES "
            "('000300','2020-01-02',100,'t','2020-01-01', 'fp')")


# ================================================================ 3. 幂等
def test_reingest_idempotent(conn):
    r1 = _ingest(conn, "000300")
    assert r1["write_detail"]["inserted"] == 30
    r2 = _ingest(conn, "000300")
    assert r2["write_detail"]["inserted"] == 0
    assert r2["write_detail"]["unchanged"] == 30
    assert count_index_daily(conn, "000300") == 30


# ================================================================ 4. 增量更新
def test_incremental_only_adds_new(conn):
    _ingest(conn, "000300")
    dates = _weekdays("2020-01-02", 35)      # 多 5 天
    r = _ingest(conn, "000300", fetcher=lambda s, a, b: _df(dates))
    assert r["write_detail"]["inserted"] == 5
    assert r["write_detail"]["unchanged"] == 30
    assert count_index_daily(conn, "000300") == 35


def test_value_change_updates_row(conn):
    _ingest(conn, "000300")
    dates = _weekdays("2020-01-02", 30)
    new_closes = [1001.0 + i * 2 for i in range(30)]     # 收盘全变
    r = _ingest(conn, "000300",
                fetcher=lambda s, a, b: _df(dates, new_closes))
    assert r["write_detail"]["updated"] == 30
    assert r["write_detail"]["inserted"] == 0


# ================================================================ 5. 单指数失败隔离
def test_single_failure_does_not_block_others(conn):
    calls = {"n": 0}

    def flaky(symbol, start, end):
        calls["n"] += 1
        if symbol == "000905":
            raise RuntimeError("模拟接口故障")
        return _df(_weekdays("2020-01-02", 5), prefix=symbol)

    results = collect_first_batch(
        conn, fetcher=flaky, sleeper=lambda *_: None,
        indices=(("000300", "沪深300", "沪深300", "中证/上证系列"),
                 ("000905", "中证500", "中证500", "中证/上证系列"),
                 ("000906", "中证800", "中证800", "中证/上证系列")))
    by_code = {r["index_code"]: r for r in results}
    assert by_code["000300"]["ok"] is True
    assert by_code["000905"]["ok"] is False
    assert by_code["000906"]["ok"] is True
    assert count_index_daily(conn, "000300") == 5
    assert count_index_daily(conn, "000905") == 0


def test_failed_run_recorded(conn):
    def always_fail(s, a, b):
        raise RuntimeError("boom")

    r = _ingest(conn, "000300", fetcher=always_fail, attempts=2,
                sleep_sec=0)
    assert r["ok"] is False
    row = conn.execute(
        "SELECT status, error_type FROM index_ingest_runs WHERE run_id=?",
        (r["run_ids"][0],)).fetchone()
    assert row[0] == "failed"
    assert row[1] == "RuntimeError"


def test_retry_after_failure(conn):
    from app.fund.index_layer import upsert_index_master
    upsert_index_master(conn, index_code="000300", index_name="沪深300指数",
                        data_source="test")
    _ingest(conn, "000300", fetcher=lambda s, a, b: (_ for _ in ()).throw(
        RuntimeError("boom")), attempts=1, sleep_sec=0)
    assert count_index_daily(conn, "000300") == 0
    r = retry_failed(conn, "000300", fetcher=_ok_fetcher)
    assert r["ok"] is True
    assert count_index_daily(conn, "000300") == 30


# ================================================================ 6-9. 硬性拒绝
def test_null_close_rejected(conn):
    """收盘值空值：硬性失败，不入库。"""
    dates = _weekdays("2020-01-02", 5)
    df = _df(dates)
    df.loc[2, "收盘"] = None
    r = _ingest(conn, "000300", fetcher=lambda s, a, b: df)
    assert r["ok"] is False
    assert r["quality_hard_passed"] is False
    assert count_index_daily(conn, "000300") == 0


def test_duplicate_dates_hard_fail_at_quality():
    """重复日期在质量层就是硬性失败。"""
    dates = ["2020-01-02", "2020-01-03", "2020-01-03"]
    q = check_history_quality(_df(dates))
    assert q["checks"]["no_duplicate_dates"]["ok"] is False
    assert q["hard_passed"] is False


def test_descending_dates_detected():
    dates = ["2020-01-06", "2020-01-03", "2020-01-02"]
    q = check_history_quality(_df(dates))
    assert q["checks"]["date_ascending"]["ok"] is False
    assert q["hard_passed"] is False


def test_negative_close_rejected(conn):
    dates = _weekdays("2020-01-02", 5)
    r = _ingest(conn, "000300",
                fetcher=lambda s, a, b: _df(dates, [1000, 1001, -5, 1003, 1004]))
    assert r["ok"] is False
    assert count_index_daily(conn, "000300") == 0


def test_non_numeric_close_rejected(conn):
    dates = _weekdays("2020-01-02", 5)
    df = _df(dates)
    df["收盘"] = df["收盘"].astype(object)
    df.loc[2, "收盘"] = "异常"
    r = _ingest(conn, "000300", fetcher=lambda s, a, b: df)
    assert r["ok"] is False


# ================================================================ 10. OHLC 警告
def test_ohlc_partial_only_warning(conn):
    """OHLC 部分缺失只产生警告，不阻断入库。"""
    r = _ingest(conn, "000300",
                fetcher=lambda s, a, b: _df(_weekdays("2020-01-02", 10),
                                            null_open=3))
    assert r["ok"] is True
    assert r["ohlc_complete"] is False
    q = latest_quality_check(conn, "000300")
    assert q["ohlc_complete"] == 0
    assert q["quality_level"] in (QUALITY_A, QUALITY_B)


# ================================================================ 11-12. 缺口
def test_gap_keeps_uncertainty(conn):
    """缺口保留不确定性，不判定真实缺失。"""
    dates = _weekdays("2020-01-02", 5) + _weekdays("2020-03-02", 5)
    _ingest(conn, "000300", fetcher=lambda s, a, b: _df(dates))
    q = latest_quality_check(conn, "000300")
    assert q["suspected_gap_count"] >= 1
    assert q["gap_is_real_missing"] is None
    assert "不能" in (q["calendar_note"] or "") or \
           "不是指数官方" in (q["calendar_note"] or "")


def test_gap_never_filled(conn):
    """缺失日期不被填充：行数等于真实返回行数。"""
    dates = _weekdays("2020-01-02", 5) + _weekdays("2020-03-02", 5)
    r = _ingest(conn, "000300", fetcher=lambda s, a, b: _df(dates))
    assert r["rows_returned"] == 10
    assert count_index_daily(conn, "000300") == 10


# ================================================================ 13-14. 口径
def test_price_vs_total_strictly_separated():
    price = basis_kind(RETURN_BASIS_PRICE)
    total = basis_kind(RETURN_BASIS_TOTAL)
    assert price["usable_for_total_return"] is False
    assert total["usable_for_total_return"] is True
    assert price != total


def test_price_basis_rejected_for_total_return():
    with pytest.raises(ReturnBasisError):
        assert_basis_usable_for_total_return(RETURN_BASIS_PRICE)


def test_unknown_basis_rejected_for_total_return():
    with pytest.raises(ReturnBasisError):
        assert_basis_usable_for_total_return(RETURN_BASIS_UNKNOWN)


def test_total_basis_allowed():
    assert_basis_usable_for_total_return(RETURN_BASIS_TOTAL)
    assert_basis_usable_for_total_return(RETURN_BASIS_NET)


def test_ingest_defaults_to_unknown_basis(conn):
    """采集默认标记 unknown，不得擅自升级为全收益。"""
    _ingest(conn, "000300")
    m = get_index_master(conn, "000300")
    assert m["return_basis"] == RETURN_BASIS_UNKNOWN
    assert m["inception_date"] is None


def test_ingest_does_not_infer_inception(conn):
    """成立日期无证据必须留空，不得用首行日期顶替。"""
    _ingest(conn, "000300")
    m = get_index_master(conn, "000300")
    assert m["inception_date"] is None
    assert "首行日期不得顶替" in (m["inception_date_evidence"] or "")


# ================================================================ 15-16. 追溯与指纹
def test_source_traceable(conn):
    _ingest(conn, "000300")
    run = conn.execute(
        "SELECT source, interface_name, status, returned_rows, "
        "actual_date_min, actual_date_max, content_fingerprint "
        "FROM index_ingest_runs ORDER BY run_id DESC LIMIT 1").fetchone()
    assert run[0] and run[1]
    assert run[2] == "success"
    assert run[3] > 0
    assert run[4] and run[5]
    assert run[6]
    row = conn.execute(
        "SELECT source, run_id, collected_at FROM index_daily LIMIT 1").fetchone()
    assert row[0] and row[1] and row[2]


def test_row_fingerprint_detects_change():
    a = row_fingerprint("000300", "2020-01-02", 100.0)
    b = row_fingerprint("000300", "2020-01-02", 100.1)
    assert a != b
    assert a == row_fingerprint("000300", "2020-01-02", 100.0)


def test_content_fingerprint_detects_change():
    r1 = [{"index_code": "000300", "trade_date": "2020-01-02", "close": 100}]
    r2 = [{"index_code": "000300", "trade_date": "2020-01-02", "close": 101}]
    assert content_fingerprint(r1) != content_fingerprint(r2)
    assert content_fingerprint(r1) == content_fingerprint(
        [{"index_code": "000300", "trade_date": "2020-01-02", "close": 100}])


# ================================================================ 17-18. 复合基准
def test_composite_incomplete_without_components(conn):
    cid = create_composite(conn, benchmark_name="测试基准",
                           benchmark_raw_text="沪深300×70%+中债综合×30%")
    v = evaluate_composite(conn, cid)
    assert v["is_complete"] is False
    assert v["is_reproducible"] is False


def test_composite_missing_component_not_complete(conn):
    _ingest(conn, "000300")
    cid = create_composite(conn, benchmark_name="测试", benchmark_raw_text="x")
    add_component(conn, cid, component_type=COMPONENT_INDEX,
                  component_label="沪深300", index_code="000300", weight=0.7)
    add_component(conn, cid, component_type=COMPONENT_BOND,
                  component_label="中债综合", weight=0.3)
    v = evaluate_composite(conn, cid)
    assert v["is_complete"] is False      # 债券成分无数据
    assert v["is_reproducible"] is False
    assert "债券" in v["missing_reason"] or "bond" in v["missing_reason"]


def test_composite_no_weight_not_reproducible(conn):
    """有成分有数据但缺权重 → 不可复现，权重不得补造。"""
    _ingest(conn, "000300")
    cid = create_composite(conn, benchmark_name="测试", benchmark_raw_text="x")
    add_component(conn, cid, component_type=COMPONENT_INDEX,
                  component_label="沪深300", index_code="000300", weight=None)
    v = evaluate_composite(conn, cid)
    assert v["is_reproducible"] is False
    assert "权重" in v["missing_reason"]
    comp = get_composite(conn, cid)["components"][0]
    assert comp["weight"] is None          # 没有补造


def test_composite_cash_component_blocks_reproducible(conn):
    """指数全齐但现金成分无序列 → 整条不可复现。"""
    _ingest(conn, "000300")
    cid = create_composite(conn, benchmark_name="测试", benchmark_raw_text="x")
    add_component(conn, cid, component_type=COMPONENT_INDEX,
                  component_label="沪深300", index_code="000300", weight=0.95)
    add_component(conn, cid, component_type=COMPONENT_CASH,
                  component_label="cash", weight=0.05)
    v = evaluate_composite(conn, cid)
    assert v["is_reproducible"] is False
    assert "无可用收益序列" in v["missing_reason"]


def test_composite_one_component_not_claim_full(conn):
    """只接一个成分就宣称整条可复现 = 禁止。"""
    _ingest(conn, "000300")
    cid = create_composite(conn, benchmark_name="双指数", benchmark_raw_text="x")
    add_component(conn, cid, component_type=COMPONENT_INDEX,
                  component_label="沪深300", index_code="000300", weight=0.5)
    v = evaluate_composite(conn, cid)
    assert v["is_reproducible"] is False


def test_composite_unmapped_index_not_available(conn):
    """未映射代码的指数成分如实记为不可用。"""
    cid = create_composite(conn, benchmark_name="恒生", benchmark_raw_text="x")
    add_component(conn, cid, component_type=COMPONENT_INDEX,
                  component_label="恒生指数", index_code=None, weight=0.3)
    v = evaluate_composite(conn, cid)
    assert v["is_complete"] is False
    assert "未映射" in v["missing_reason"]


# ================================================================ 19-20. 事务与外键
def test_transaction_rollback_on_error(db):
    """写入失败必须整体回滚。"""
    with pytest.raises(sqlite3.IntegrityError):
        with get_index_connection(db) as c:
            c.execute(
                "INSERT INTO index_master (index_code, index_name, data_source,"
                " created_at, updated_at) VALUES ('X1','测试','t','t','t')")
            # 违反外键：index_daily 引用不存在的指数
            c.execute(
                "INSERT INTO index_daily (index_code, trade_date, close, source,"
                " collected_at, row_fingerprint) "
                "VALUES ('NOT_EXIST','2020-01-02',1,'t','t','fp')")
    with get_index_connection(db) as c:
        assert c.execute("SELECT COUNT(*) FROM index_master").fetchone()[0] == 0


def test_foreign_keys_enabled(db):
    with get_index_connection(db) as c:
        assert int(c.execute("PRAGMA foreign_keys").fetchone()[0]) == 1


def test_fk_violation_rejected(db):
    with pytest.raises(sqlite3.IntegrityError):
        with get_index_connection(db) as c:
            c.execute(
                "INSERT INTO index_daily (index_code, trade_date, close, source,"
                " collected_at, row_fingerprint) "
                "VALUES ('NO_SUCH','2020-01-02',1,'t','t','fp')")


def test_fk_check_clean(db):
    with get_index_connection(db) as c:
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []


def test_cascade_delete_components(db):
    """删除复合基准，成分级联删除。"""
    with get_index_connection(db) as c:
        cid = create_composite(c, benchmark_name="T", benchmark_raw_text="x")
        add_component(c, cid, component_type=COMPONENT_CASH,
                      component_label="cash", weight=0.05)
        c.execute("DELETE FROM benchmark_composite WHERE composite_id=?", (cid,))
        assert c.execute("SELECT COUNT(*) FROM benchmark_composite_component"
                         ).fetchone()[0] == 0


# ================================================================ 21. 正式库不受影响
def test_production_fund_tables_untouched(tmp_path):
    """正式库基金表在指数层建表/写入后不受影响。"""
    from app.database.db import get_connection
    from app.fund.ingest_user_funds import db_fingerprint

    before = db_fingerprint()["sha256"]
    with get_connection() as c:
        rows_before = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                       for t in ("fund_master", "fund_share_classes",
                                 "fund_nav_daily", "fund_lifecycle_events")}
    p = tmp_path / "isolated.db"
    with get_index_connection(p) as c:
        init_index_layer(c)
        upsert_indices(c)
        _ingest(c, "000300")
    with get_connection() as c:
        rows_after = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                      for t in rows_before}
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert rows_before == rows_after
    assert before == db_fingerprint()["sha256"]


def upsert_indices(c):
    from app.fund.index_layer import upsert_index_master
    upsert_index_master(c, index_code="000300", index_name="沪深300指数",
                        data_source="test")


def test_index_tables_separate_from_fund_tables(conn):
    """指数历史不得混入基金净值表或 ETF 行情表。"""
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "index_daily" in tables
    assert "index_master" in tables
    # index_daily 的列里绝不能出现 nav / accumulated_nav
    cols = {r[1] for r in conn.execute("PRAGMA table_info(index_daily)")}
    assert "nav" not in cols
    assert "accumulated_nav" not in cols
    assert "close" in cols


# ================================================================ 22. 口径不混拼
def test_different_sources_not_spliced(conn):
    """不同来源的行各自带 source，不得静默拼接掩盖来源。"""
    _ingest(conn, "000300")
    sources = {r[0] for r in conn.execute(
        "SELECT DISTINCT source FROM index_daily WHERE index_code='000300'")}
    assert len(sources) == 1


def test_basis_is_per_index_not_global(conn):
    """每个指数独立记录口径，不得全局统一。"""
    from app.fund.index_layer import upsert_index_master
    upsert_index_master(conn, index_code="A1", index_name="价格指数",
                        data_source="t", return_basis=RETURN_BASIS_PRICE)
    upsert_index_master(conn, index_code="B1", index_name="净值指数",
                        data_source="t", return_basis=RETURN_BASIS_NET)
    assert get_index_master(conn, "A1")["return_basis"] == RETURN_BASIS_PRICE
    assert get_index_master(conn, "B1")["return_basis"] == RETURN_BASIS_NET


def test_invalid_basis_rejected(conn):
    from app.fund.index_layer import upsert_index_master
    with pytest.raises(ValueError):
        upsert_index_master(conn, index_code="C1", index_name="x",
                            data_source="t", return_basis="total_return_v2")


# ================================================================ 附加：基线行
def test_baseline_row_marked_suspect(conn):
    """接口基线占位行标 suspect，不计入有效区间。"""
    dates = ["2004-01-01"] + _weekdays("2009-01-05", 20)
    _ingest(conn, "399997", fetcher=lambda s, a, b: _df(dates, prefix="白酒"))
    q = conn.execute(
        "SELECT quality_status, COUNT(*) FROM index_daily "
        "WHERE index_code='399997' GROUP BY quality_status").fetchall()
    by = dict(q)
    assert by.get("suspect") == 1
    assert by.get("valid") == 20
    rng = effective_date_range(conn, "399997")
    assert rng["date_min"] == "2009-01-05"
    raw = index_date_range(conn, "399997")
    assert raw["date_min"] == "2004-01-01"


# ================================================================ 门禁
def test_gate_unchanged():
    from app.fund.research.engine import analyze_by_code
    g = analyze_by_code("050002")["gate"]
    assert g["ready_for_research_analysis"] is True
    assert g["ready_for_backtest"] is False
    assert g["ready_for_formal_ranking"] is False
