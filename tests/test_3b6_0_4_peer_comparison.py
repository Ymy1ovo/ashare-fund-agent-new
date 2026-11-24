"""阶段3B-6.0.4 同类比较与超额收益边界专项测试。

只读：不联网、不写正式库。构造临时库验证边界行为。
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.fund.research.data_access import audit_nav_series  # noqa: E402
from app.fund.research.excess_return import (  # noqa: E402
    BLOCK_BASIS_PRICE, BLOCK_BASIS_UNKNOWN, BLOCK_COMPOSITE_INCOMPLETE,
    BLOCK_COMPOSITE_MISSING_COMPONENT, BLOCK_COMPOSITE_MISSING_WEIGHT,
    BLOCK_NO_BENCHMARK_SERIES, EXCESS_NOT_AVAILABLE, assess_composite,
    check_benchmark_usable, evaluate_excess_return, peer_relative_note,
)
from app.fund.research.peer_comparison import (  # noqa: E402
    MIN_ROLLING_WINDOWS, annualized_from_return, best_window_dependency,
    common_window, exclude_best_window, has_gap_between, rolling_windows,
    series_span, value_on, window_return,
)
from app.fund.index_returns import (  # noqa: E402
    RETURN_BASIS_NET, RETURN_BASIS_PRICE, RETURN_BASIS_TOTAL,
    RETURN_BASIS_UNKNOWN,
)


# ---------------------------------------------------------------- 构造工具
def make_series(values, *, start=date(2020, 1, 1), code="T00001",
                share_id=1, fund_id=1, step_days=1, gaps_at=None):
    """构造净值序列。values 为 acc_nav 列表。"""
    rows = []
    d = start
    for i, v in enumerate(values):
        rows.append({"nav_date": d.isoformat(), "unit_nav": v, "acc_nav": v})
        d = d + timedelta(days=step_days)
    return audit_nav_series(code, share_id, fund_id, code, "net_value", rows)


def daily_series(n=800, *, start_value=1.0, growth=0.0002, **kw):
    vals = [start_value * (1 + growth) ** i for i in range(n)]
    return make_series(vals, **kw)


# ================================================================ 1. 区间收益
def test_window_return_exact_endpoints_ok():
    s = daily_series(400)
    r = window_return(s, "2020-01-01", "2020-06-29")
    assert r["status"] == "ok"
    assert r["value"] is not None
    assert r["start_date"] == "2020-01-01"
    assert r["end_date"] == "2020-06-29"


def test_window_return_missing_start_is_insufficient():
    s = daily_series(400)
    r = window_return(s, "1999-01-01", "2020-06-29")
    assert r["status"] == "insufficient_data"
    assert r["value"] is None
    assert "起点" in r["reason"]


def test_window_return_missing_end_is_insufficient():
    s = daily_series(400)
    r = window_return(s, "2020-01-01", "2099-12-31")
    assert r["status"] == "insufficient_data"
    assert "终点" in r["reason"]


def test_window_return_does_not_interpolate_endpoint():
    """端点不存在时绝不向前后找最近值。"""
    s = daily_series(400)
    r = window_return(s, "2020-01-01", "2020-06-28")  # 2020-06-28 存在
    ok = window_return(s, "2020-01-01", "2020-06-27")
    assert r["status"] == "ok"
    assert ok["status"] == "ok"
    r2 = window_return(s, "2020-01-01", "2020-06-28")
    assert value_on(s, "2020-06-28") is not None


# ================================================================ 2. 缺口
def test_gap_blocks_window_return():
    """超过阈值缺口 → 不跨越计算。"""
    vals = [1.0] * 10 + [1.1] * 10
    rows = []
    d = date(2020, 1, 1)
    for i, v in enumerate(vals):
        if i == 10:
            d = d + timedelta(days=40)   # 大缺口
        rows.append({"nav_date": d.isoformat(), "unit_nav": v, "acc_nav": v})
        d = d + timedelta(days=1)
    s = audit_nav_series("GAP01", 1, 1, "GAP01", "net_value", rows)
    r = window_return(s, "2020-01-01", "2020-01-20")
    assert r["status"] == "insufficient_data"
    assert "缺口" in r["reason"]
    assert has_gap_between(s, "2020-01-01", "2020-01-20") is True


def test_no_gap_returns_false():
    s = daily_series(100)
    assert has_gap_between(s, "2020-01-01", "2020-02-01") is False


# ================================================================ 3. 年化
def test_annualized_requires_at_least_one_year():
    r = annualized_from_return(0.1, 300)
    assert r["status"] == "insufficient_data"
    assert r["value"] is None
    assert "不足 1 年" in r["reason"]


def test_annualized_ok_for_two_years():
    r = annualized_from_return(0.21, 730)
    assert r["status"] == "ok"
    assert abs(r["value"] - 0.1) < 1e-6
    assert r["basis"] == "natural_days"


def test_annualized_none_return_insufficient():
    r = annualized_from_return(None, 730)
    assert r["status"] == "insufficient_data"


# ================================================================ 4. 共同区间
def test_common_window_intersects():
    spans = [
        {"date_min": "2020-01-01", "date_max": "2023-01-01"},
        {"date_min": "2021-06-01", "date_max": "2024-01-01"},
    ]
    cw = common_window(spans)
    assert cw["status"] == "ok"
    assert cw["date_min"] == "2021-06-01"
    assert cw["date_max"] == "2023-01-01"


def test_common_window_empty_intersection():
    spans = [
        {"date_min": "2020-01-01", "date_max": "2021-01-01"},
        {"date_min": "2022-01-01", "date_max": "2023-01-01"},
    ]
    cw = common_window(spans)
    assert cw["status"] == "insufficient_data"
    assert cw["date_min"] is None


def test_common_window_single_fund_insufficient():
    cw = common_window([{"date_min": "2020-01-01", "date_max": "2023-01-01"}])
    assert cw["status"] == "insufficient_data"
    assert "不足 2 只" in cw["reason"]


def test_different_inception_dates_use_common_window():
    """成立时间不同的基金，必须用共同区间而非各自成立以来。"""
    a = daily_series(1200, start=date(2018, 1, 1))
    b = daily_series(800, start=date(2020, 1, 1))
    cw = common_window([series_span(a), series_span(b)])
    assert cw["status"] == "ok"
    assert cw["date_min"] >= "2020-01-01"


# ================================================================ 5. 滚动窗口
def test_rolling_windows_insufficient_for_short_series():
    s = daily_series(200)
    r = rolling_windows(s, window_days=365)
    assert r["status"] == "insufficient_data"
    assert r["valid_count"] < MIN_ROLLING_WINDOWS


def test_rolling_windows_ok_for_long_series():
    s = daily_series(1600)
    r = rolling_windows(s, window_days=365, step_days=30)
    assert r["status"] == "ok"
    assert r["valid_count"] >= MIN_ROLLING_WINDOWS
    assert 0 <= r["positive_ratio"] <= 1
    assert r["median_return"] is not None


def test_rolling_windows_skip_gap():
    """窗口跨越超阈值缺口时必须跳过，不得跨缺口算收益。"""
    rows = []
    d = date(2020, 1, 1)
    for i in range(30):
        v = 1.0 + i * 0.0001
        rows.append({"nav_date": d.isoformat(), "unit_nav": v, "acc_nav": v})
        d = d + timedelta(days=1)
    d = d + timedelta(days=60)                      # 大缺口
    for i in range(30):
        v = 1.5 + i * 0.0001
        rows.append({"nav_date": d.isoformat(), "unit_nav": v, "acc_nav": v})
        d = d + timedelta(days=1)
    s = audit_nav_series("GAP02", 1, 1, "GAP02", "net_value", rows)
    r = rolling_windows(s, window_days=10, step_days=1)
    assert r["skipped_count"] > 0
    # 跨缺口的窗口收益不得出现在结果里
    for w in r.get("windows", []):
        assert not has_gap_between(s, w["start_date"], w["end_date"])


# ================================================================ 6. 稳定性
def test_best_window_dependency_flags_single_spike():
    rolling = {"status": "ok", "valid_count": 10,
               "windows": [{"start_date": "a", "end_date": "b", "return": 0.01}] * 9
                          + [{"start_date": "x", "end_date": "y", "return": 1.0}],
               "median_return": 0.01, "spread": 0.99, "positive_ratio": 1.0}
    r = best_window_dependency(rolling)
    assert r["status"] == "ok"
    assert r["high_dependency"] is True
    assert r["best_window"]["return"] == 1.0


def test_exclude_best_window_changes_conclusion():
    rolling = {"status": "ok", "valid_count": 6,
               "windows": [{"return": 0.5}] + [{"return": -0.01}] * 5,
               "median_return": -0.01, "spread": 0.51, "positive_ratio": 1 / 6}
    r = exclude_best_window(rolling)
    assert r["status"] == "ok"
    assert r["remaining_count"] == 5
    assert r["positive_ratio"] == 0.0


def test_stability_insufficient_passthrough():
    r = best_window_dependency({"status": "insufficient_data", "reason": "x"})
    assert r["status"] == "insufficient_data"


# ================================================================ 7. 超额收益阻断
def test_price_basis_blocks_excess_return():
    r = check_benchmark_usable("000300", RETURN_BASIS_PRICE)
    assert r["usable"] is False
    assert r["block"] == BLOCK_BASIS_PRICE


def test_unknown_basis_blocks_excess_return():
    r = check_benchmark_usable("000300", RETURN_BASIS_UNKNOWN)
    assert r["usable"] is False
    assert r["block"] == BLOCK_BASIS_UNKNOWN


def test_total_basis_passes_component_check():
    r = check_benchmark_usable("000300", RETURN_BASIS_TOTAL)
    assert r["usable"] is True


def test_net_basis_is_accepted_as_total_like():
    r = check_benchmark_usable("000300", RETURN_BASIS_NET)
    assert r["usable"] is True


def test_excess_return_not_available_without_benchmark():
    r = evaluate_excess_return({"benchmark_index_codes": [], "index_bases": {},
                                "composite": None})
    assert r["excess_return_status"] == EXCESS_NOT_AVAILABLE
    assert r["block"] == BLOCK_NO_BENCHMARK_SERIES


def test_excess_return_not_available_with_unknown_basis():
    r = evaluate_excess_return({
        "benchmark_index_codes": ["000300"],
        "index_bases": {"000300": RETURN_BASIS_UNKNOWN},
        "composite": None,
    })
    assert r["excess_return_status"] == EXCESS_NOT_AVAILABLE
    assert r["block"] == BLOCK_BASIS_UNKNOWN


def test_composite_missing_weight_blocks():
    c = {"components": [
        {"component_label": "沪深300", "component_type": "index",
         "weight": None, "data_available": True},
        {"component_label": "中债综合", "component_type": "bond",
         "weight": 0.3, "data_available": True},
    ]}
    r = assess_composite(c)
    assert r["reproducible"] is False
    assert r["block"] == BLOCK_COMPOSITE_MISSING_WEIGHT


def test_composite_missing_component_blocks():
    c = {"components": [
        {"component_label": "沪深300", "component_type": "index",
         "weight": 0.7, "data_available": True},
        {"component_label": "中债综合", "component_type": "bond",
         "weight": 0.3, "data_available": False},
    ]}
    r = assess_composite(c)
    assert r["reproducible"] is False
    assert r["block"] == BLOCK_COMPOSITE_MISSING_COMPONENT


def test_composite_single_component_blocked():
    c = {"components": [{"component_label": "沪深300",
                         "component_type": "index", "weight": 1.0,
                         "data_available": True}]}
    r = assess_composite(c)
    assert r["reproducible"] is False
    assert r["block"] == BLOCK_COMPOSITE_INCOMPLETE


def test_composite_complete_is_reproducible():
    c = {"components": [
        {"component_label": "沪深300", "component_type": "index",
         "weight": 0.7, "data_available": True},
        {"component_label": "中债综合", "component_type": "bond",
         "weight": 0.3, "data_available": True},
    ]}
    assert assess_composite(c)["reproducible"] is True


def test_peer_relative_is_not_alpha_always_declared():
    for payload in (
        {"benchmark_index_codes": [], "index_bases": {}, "composite": None},
        {"benchmark_index_codes": ["000300"],
         "index_bases": {"000300": RETURN_BASIS_UNKNOWN}, "composite": None},
    ):
        r = evaluate_excess_return(payload)
        assert r["peer_relative_is_not_alpha"] is True


def test_peer_relative_note_declares_no_forward_guarantee():
    n = peer_relative_note()
    assert n["ranking_is_not_alpha"] is True
    assert n["no_forward_guarantee"] is True
    assert len(n["why_not"]) >= 2


def test_even_with_verified_basis_no_series_still_blocked():
    """口径核实但库内无基准收益序列，仍然阻断。"""
    r = evaluate_excess_return({
        "benchmark_index_codes": ["000300"],
        "index_bases": {"000300": RETURN_BASIS_TOTAL},
        "composite": None,
    })
    assert r["excess_return_status"] == EXCESS_NOT_AVAILABLE
    assert r["block"] == BLOCK_NO_BENCHMARK_SERIES
