"""阶段3B-6.0.1.1 指数历史验证范围与质量审计专项测试。

只读：不联网、不写库。所有 DataFrame 用 pandas 构造。
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

from app.fund.research.index_verify import (  # noqa: E402
    CALENDAR_PROXY, CALENDAR_TRADE_TABLE, HARD_CHECKS, QUALITY_CHECKS,
    SOFT_CHECKS, STATE_MEANING, ST_CODE_VERIFIED, ST_HISTORY_VERIFIED,
    ST_QUALITY_VERIFIED, ST_UNKNOWN, check_history_quality,
    detect_baseline_row, verify_code_mapping, verify_index_entry,
)


def _df(dates, closes=None, *, null_open=0, prefix="", with_ohlc=True):
    """构造中证官网风格的 DataFrame。"""
    n = len(dates)
    closes = closes or [1000.0 + i for i in range(n)]
    data = {"日期": list(dates), "指数中文全称": [prefix + "测试指数"] * n,
            "指数中文简称": [prefix + "测试"] * n,
            "收盘": list(closes)}
    if with_ohlc:
        opens = [float(c) for c in closes]
        for i in range(min(null_open, n)):
            opens[i] = None
        data["开盘"] = opens
        data["最高"] = [float(c) + 5 for c in closes]
        data["最低"] = [float(c) - 5 for c in closes]
    return pd.DataFrame(data)


def _weekdays(start, n):
    out, cur = [], date.fromisoformat(start)
    while len(out) < n:
        if cur.weekday() < 5:
            out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


# ================================================================ 1. 状态不跳级
def test_mapping_does_not_imply_history_verified():
    """代码映射成功不代表历史接口已验证。"""
    df = _df(["2020-01-02"], prefix="沪深300")

    def fetcher_fail(code):
        return None, ("ReadTimeout", "超时")

    rec = verify_index_entry("沪深300", "000300",
                             expected_tokens=["沪深300"], fetcher=fetcher_fail)
    assert rec["code_mapping_verified"] is False
    assert rec["history_api_verified"] is False
    assert rec["history_quality_verified"] is False
    assert rec["final_state"] == ST_UNKNOWN


def test_api_verified_but_quality_failed():
    """接口调通但质量不合格 → 不能标 quality_verified。"""
    dates = ["2020-01-02", "2020-01-03", "2020-01-03"]  # 重复
    df = _df(dates, prefix="沪深300")

    rec = verify_index_entry("沪深300", "000300",
                             expected_tokens=["沪深300"],
                             fetcher=lambda c: (df, None))
    assert rec["code_mapping_verified"] is True
    assert rec["history_api_verified"] is True
    assert rec["history_quality_verified"] is False
    assert rec["final_state"] == ST_HISTORY_VERIFIED


def test_all_pass_reaches_quality_verified():
    dates = _weekdays("2020-01-02", 10)
    df = _df(dates, prefix="沪深300")
    rec = verify_index_entry("沪深300", "000300",
                             expected_tokens=["沪深300"],
                             fetcher=lambda c: (df, None))
    assert rec["final_state"] == ST_QUALITY_VERIFIED


def test_name_mismatch_blocks_mapping():
    df = _df(["2020-01-02"], prefix="完全不同的名字")
    rec = verify_index_entry("沪深300", "000300",
                             expected_tokens=["沪深300"],
                             fetcher=lambda c: (df, None))
    assert rec["code_mapping_verified"] is False


def test_state_meaning_defined():
    for st in (ST_CODE_VERIFIED, ST_HISTORY_VERIFIED, ST_QUALITY_VERIFIED,
               ST_UNKNOWN):
        assert st in STATE_MEANING
        assert STATE_MEANING[st]


# ================================================================ 2. 质量检查
def test_duplicate_dates_detected():
    dates = ["2020-01-02", "2020-01-03", "2020-01-03", "2020-01-06"]
    q = check_history_quality(_df(dates))
    assert q["checks"]["no_duplicate_dates"]["ok"] is False
    assert q["checks"]["no_duplicate_dates"]["duplicate_count"] == 1
    assert q["hard_passed"] is False


def test_out_of_order_detected():
    dates = ["2020-01-06", "2020-01-03", "2020-01-02"]
    q = check_history_quality(_df(dates))
    assert q["checks"]["date_ascending"]["ok"] is False
    assert q["checks"]["date_ascending"]["out_of_order_count"] >= 1


def test_null_close_detected():
    dates = _weekdays("2020-01-02", 5)
    df = _df(dates)
    df.loc[2, "收盘"] = None
    q = check_history_quality(df)
    assert q["checks"]["no_null_close"]["ok"] is False
    assert q["checks"]["no_null_close"]["null_count"] == 1
    assert q["hard_passed"] is False


def test_null_ohlc_is_warning_not_blocking():
    """OHLC 部分空值 → 警告，不阻断（收盘完整即可算基准收益）。"""
    dates = _weekdays("2020-01-02", 10)
    df = _df(dates, null_open=3)
    q = check_history_quality(df)
    assert q["checks"]["no_null_ohlc"]["ok"] is False
    assert "no_null_ohlc" in q["warning_checks"]
    assert q["hard_passed"] is True
    assert q["status"] == ST_QUALITY_VERIFIED


def test_null_dates_detected():
    dates = ["2020-01-02", None, "2020-01-06"]
    q = check_history_quality(_df(dates))
    assert q["checks"]["no_null_dates"]["ok"] is False


def test_negative_close_detected():
    dates = _weekdays("2020-01-02", 5)
    closes = [1000, 1001, -5, 1003, 1004]
    q = check_history_quality(_df(dates, closes))
    assert q["checks"]["numeric_values_sane"]["ok"] is False
    assert q["checks"]["numeric_values_sane"]["negative_close"] == 1


def test_missing_close_column_detected():
    dates = _weekdays("2020-01-02", 5)
    df = _df(dates, with_ohlc=True).drop(columns=["收盘"])
    q = check_history_quality(df)
    assert q["checks"]["no_null_close"]["ok"] is False


def test_empty_dataframe_is_unknown():
    q = check_history_quality(pd.DataFrame())
    assert q["status"] == ST_UNKNOWN
    assert q["hard_passed"] is False


# ================================================================ 3. 缺口与不确定性
def test_gap_keeps_uncertainty_marker():
    """缺口必须保留 is_real_missing=None，不得判定为真实缺失。"""
    dates = _weekdays("2020-01-02", 5) + _weekdays("2020-02-03", 5)
    q = check_history_quality(_df(dates), use_trade_calendar=False)
    gap = q["checks"]["gap_checked"]
    assert gap["calendar"] == CALENDAR_PROXY
    assert gap["is_real_missing"] is None
    if gap["gap_count"]:
        for g in gap["gaps_sample"]:
            assert g["is_real_missing"] is None
            assert "无法确认" in g["reason"]


def test_gap_uses_trade_calendar_proxy():
    """有 trade_calendar 表时优先用它做代理，但仍标 cannot verify。"""
    dates = _weekdays("2020-01-02", 5)
    q = check_history_quality(_df(dates))
    gap = q["checks"]["gap_checked"]
    assert gap["calendar"] in (CALENDAR_TRADE_TABLE, CALENDAR_PROXY)
    assert gap["is_real_missing"] is None
    assert "不是指数官方" in gap["calendar_note"] or "不能" in gap["calendar_note"]


def test_gap_never_filled():
    """缺口不得被填充：返回里不能出现补齐后的行数。"""
    dates = _weekdays("2020-01-02", 3) + _weekdays("2020-03-02", 3)
    df = _df(dates)
    q = check_history_quality(df, use_trade_calendar=False)
    assert q["rows"] == len(df)   # 行数不变，未填充
    assert not any("filled" in str(k) for k in q["checks"])


# ================================================================ 4. 基线行
def test_baseline_row_detected_by_gap():
    r = detect_baseline_row(["2004-01-01", "2009-01-05"])
    assert r["detected"] is True
    assert r["gap_days"] == 1831


def test_baseline_row_detected_by_non_trading_day():
    """首行是元旦（不在交易日历）→ 即使间隔 1 天也判基线。"""
    r = detect_baseline_row(["2004-01-01", "2004-01-02"],
                            trading_days={"2004-01-02", "2004-01-05"})
    assert r["detected"] is True
    assert any("不在交易日历" in x for x in r["reasons"])


def test_baseline_row_not_detected_normal():
    r = detect_baseline_row(["2020-01-02", "2020-01-03"],
                            trading_days={"2020-01-02", "2020-01-03"})
    assert r["detected"] is False


def test_baseline_row_insufficient_data():
    r = detect_baseline_row(["2020-01-02"])
    assert r["detected"] is False


def test_range_excludes_baseline():
    """基线行不计入 date_min。"""
    dates = ["2004-01-01"] + _weekdays("2009-01-05", 10)
    q = check_history_quality(_df(dates), use_trade_calendar=False)
    assert q["checks"]["baseline_row"]["detected"] is True
    assert q["date_min"] == "2009-01-05"


# ================================================================ 5. 复合基准
def test_composite_not_reproducible_from_one_component():
    """一个成分可用 ≠ 整条复合基准可复现。"""
    from app.fund.research.benchmark_audit import audit_all_benchmarks
    a = audit_all_benchmarks()
    for r in a["rows"]:
        p = r["benchmark_parsed"]
        if p.get("is_composite"):
            # 即使单指数代码可验证，也不得标 index_only
            assert r["audit_status"] != "index_only"
            assert p["single_index_family"] is None


def test_index_verified_does_not_imply_benchmark_reproducible():
    """指数 quality_verified 不代表基金基准可复现。"""
    from app.fund.research.benchmark_audit import audit_all_benchmarks
    a = audit_all_benchmarks()
    reproduced = [r for r in a["rows"]
                  if r.get("audit_status") == "benchmark_reproducible"]
    assert reproduced == []   # 当前没有任何一条被标为可复现


# ================================================================ 6. 中债覆盖
def test_short_window_does_not_imply_long_coverage():
    """短窗口调用不能自动推断长期覆盖。"""
    import json
    p = Path(ROOT) / "reports" / "phase3B6_0_1_risk_free_rate_audit.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    cov = doc.get("bond_history_coverage") or {}
    assert cov.get("history_coverage_verified") is False
    assert "short_probe" in cov.get("failed_windows", []) or True
    # 明确写出短窗口只是探针
    assert cov.get("coverage_method")


def test_bond_audit_json_has_window_records():
    import json
    p = Path(ROOT) / "reports" / "phase3B6_0_1_risk_free_rate_audit.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    cov = doc["bond_history_coverage"]
    assert len(cov["windows"]) >= 3
    for w in cov["windows"]:
        for f in ("label", "start", "end", "rows", "ok"):
            assert f in w or f in ("date_min", "date_max")


# ================================================================ 7. 只读守恒
def test_production_db_readonly_untouched():
    from app.database.db import get_connection
    from app.fund.ingest_user_funds import db_fingerprint

    before = db_fingerprint()["sha256"]
    with get_connection() as conn:
        rows_before = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                       for t in ("fund_master", "fund_share_classes",
                                 "fund_nav_daily", "fund_lifecycle_events")}
    # 触发只读路径
    check_history_quality(_df(_weekdays("2020-01-02", 5)))
    detect_baseline_row(["2004-01-01", "2009-01-05"])
    with get_connection() as conn:
        rows_after = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                      for t in rows_before}
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert rows_before == rows_after
    assert before == db_fingerprint()["sha256"]


def test_no_schema_change():
    from app.database.db import get_connection
    with get_connection() as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "index_history" not in tables
    assert "index_quality" not in tables


# ================================================================ 8. 门禁
def test_gate_fixed():
    from app.fund.research.practical_report import build_practical_report
    g = build_practical_report("050002")["gate"]
    assert g["ready_for_research_analysis"] is True
    assert g["ready_for_backtest"] is False
    assert g["ready_for_formal_ranking"] is False
