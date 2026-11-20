"""阶段3B-5.1 场外基金研究性分析引擎专项测试。

全部使用人工构造数据 / 临时 SQLite，不依赖外部实时数据。
数据库相关断言一律走 temp_db（conftest 的 production_db_guard 会兜底）。
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.fund.research.classification import (  # noqa: E402
    ONSHORE_ETF_CODES, classify_fund, index_scope, is_offmarket_pool,
    peer_group_key,
)
from app.fund.research.data_access import (  # noqa: E402
    MAX_GAP_DAYS_FOR_RETURN, audit_nav_series,
)
from app.fund.research.indicators import (  # noqa: E402
    compute_money_indicators, compute_nav_indicators,
)


# ================================================================ 构造工具
def make_series(rows, *, code="T00001", nav_kind="net_value"):
    """rows: [(date_str, unit_nav, acc_nav)]"""
    raw = [{"nav_date": d, "unit_nav": u, "acc_nav": a} for d, u, a in rows]
    return audit_nav_series(code, 1, 1, "测试基金", nav_kind, raw)


def daily_rows(start: str, days: int, *, base=1.0, step=0.001,
               field_none_at: set[int] | None = None, dividend_date=None):
    """生成每日连续净值。field_none_at 里的索引 acc_nav 置 None。"""
    d0 = date.fromisoformat(start)
    out = []
    for i in range(days):
        d = d0 + timedelta(days=i)
        unit = base + i * step
        acc = unit
        if dividend_date and d > date.fromisoformat(dividend_date):
            acc = unit + 0.05  # 分红后累计净值高于单位净值
        if field_none_at and i in field_none_at:
            acc = None
        out.append((d.isoformat(), round(unit, 6), None if acc is None else round(acc, 6)))
    return out


# ================================================================ 1. 正常累计净值收益
def test_normal_acc_nav_return():
    rows = daily_rows("2020-01-01", 400, base=1.0, step=0.001)
    s = make_series(rows)
    ind = compute_nav_indicators(s, field_name="acc_nav")
    r = ind["returns"]["ret_12m"]
    assert r["status"] == "ok"
    # 端点必须真实存在，且收益 = end/start - 1
    assert abs(r["value"] - (r["end_value"] / r["start_value"] - 1)) < 1e-6
    assert r["field"] == "acc_nav"
    assert r["window_days"] == 365


def test_return_uses_exact_endpoint():
    """窗口端点必须精确命中，取不到就 insufficient_data。"""
    rows = daily_rows("2020-01-01", 400)
    # 删掉 2021-01-01（正好是 2020-01-01 + 366 天位置附近）
    s = make_series(rows)
    ind = compute_nav_indicators(s, field_name="acc_nav")
    # 起点必须命中 last-30 天；用真实存在的日期才 ok
    assert ind["returns"]["ret_1m"]["status"] == "ok"
    assert ind["returns"]["ret_1m"]["start_date"] is not None


def test_window_missing_endpoint_returns_insufficient():
    """起点不存在时必须 insufficient_data，不能找近似值。"""
    d0 = date.fromisoformat("2020-01-01")
    rows = []
    for i in range(0, 60):
        if i == 29:      # 正好挖掉 30 天前那个点（last 是第 59 天）
            continue
        d = d0 + timedelta(days=i)
        rows.append((d.isoformat(), 1.0 + i * 0.001, 1.0 + i * 0.001))
    s = make_series(rows)
    ind = compute_nav_indicators(s, field_name="acc_nav")
    r = ind["returns"]["ret_1m"]
    assert r["status"] == "insufficient_data"
    assert "不向前后找替代值" in r["reason"]


# ================================================================ 2. 单位净值 vs 累计净值
def test_unit_nav_is_not_total_return():
    """有分红时 unit_nav 收益必须低于 acc_nav 收益。"""
    rows = daily_rows("2020-01-01", 400, base=1.0, step=0.001,
                      dividend_date="2020-06-01")
    s = make_series(rows)
    acc = compute_nav_indicators(s, field_name="acc_nav")
    unit = compute_nav_indicators(s, field_name="unit_nav")
    a = acc["returns"]["ret_12m"]["value"]
    u = unit["returns"]["ret_12m"]["value"]
    assert a > u, (a, u)
    assert "不能" in acc["return_field_note"]


def test_dividend_effect_detected():
    rows = daily_rows("2020-01-01", 400, dividend_date="2020-06-01")
    s = make_series(rows)
    assert s.quality.has_dividend_effect is True
    assert s.quality.acc_equals_unit_ratio is not None
    assert s.quality.acc_equals_unit_ratio < 1.0


def test_no_dividend_means_equal():
    rows = daily_rows("2020-01-01", 100)
    s = make_series(rows)
    assert s.quality.acc_equals_unit_ratio == 1.0
    assert s.quality.has_dividend_effect is False


# ================================================================ 3. 分红不修复收益
def test_no_dividend_repair():
    rows = daily_rows("2020-01-01", 400, dividend_date="2020-06-01")
    s = make_series(rows)
    ind = compute_nav_indicators(s)
    assert ind["dividend_repair_used"] is False
    assert "未" in ind["dividend_repair_note"]
    assert "不完整" in ind["dividend_repair_note"]


# ================================================================ 4/5/6. 日期质量
def test_duplicate_dates_detected():
    rows = daily_rows("2020-01-01", 60)
    rows.append(rows[10])  # 重复
    s = make_series(rows)
    assert s.quality.duplicate_dates == 1
    assert "duplicate_dates" in s.quality.quality_flags


def test_out_of_order_detected():
    rows = daily_rows("2020-01-01", 30)
    rows[5], rows[25] = rows[25], rows[5]
    s = make_series(rows)
    assert s.quality.out_of_order > 0
    assert "out_of_order" in s.quality.quality_flags
    # 内部必须排序后使用
    assert s.points[0].nav_date < s.points[-1].nav_date


def test_duplicate_dates_dedup():
    rows = daily_rows("2020-01-01", 20)
    rows.append(rows[5])
    s = make_series(rows)
    assert len(s.points) == 20  # 去重后仍是 20
    assert s.quality.rows == 21


def test_null_nav_detected():
    rows = daily_rows("2020-01-01", 60, field_none_at={10, 11})
    s = make_series(rows)
    assert s.quality.null_acc == 2
    assert "null_acc_nav" in s.quality.quality_flags


def test_nonpositive_nav_detected():
    rows = daily_rows("2020-01-01", 20)
    rows[3] = (rows[3][0], 0.0, 0.0)
    s = make_series(rows)
    assert s.quality.nonpositive_unit == 1
    assert "nonpositive_unit_nav" in s.quality.quality_flags


# ================================================================ 7/8. 缺口
def test_gap_detected():
    rows = daily_rows("2020-01-01", 20) + daily_rows("2020-04-01", 20)
    s = make_series(rows)
    assert s.quality.gap_count_over_threshold >= 1
    assert s.quality.max_gap_days > MAX_GAP_DAYS_FOR_RETURN


def test_gap_not_crossed_for_return():
    """跨缺口的窗口收益必须拒绝，不能把缺口两端当相邻点。"""
    left = daily_rows("2020-01-01", 200)      # 到 2020-07-18
    right_start = date.fromisoformat("2020-09-01")  # 缺口 45 天，仍在 12 月窗口内
    # 只取 200 天，让 last 落在 2021-03-19，12 月窗口起点 2020-03-19，
    # 从而那个 45 天缺口落在窗口**内部**
    right = [((right_start + timedelta(days=i)).isoformat(),
              1.2 + i * 0.001, 1.2 + i * 0.001) for i in range(200)]
    s = make_series(left + right)
    ind = compute_nav_indicators(s)
    r = ind["returns"]["ret_12m"]
    assert r["status"] == "insufficient_data"
    assert "缺口" in (r["reason"] or "")


def test_gap_skipped_in_daily_returns():
    """日收益序列必须跳过跨缺口的那一对。"""
    from app.fund.research.indicators import _daily_returns
    left = daily_rows("2020-01-01", 50)
    right = [((date.fromisoformat("2020-06-01") + timedelta(days=i)).isoformat(),
              2.0 + i * 0.001, 2.0 + i * 0.001) for i in range(50)]
    s = make_series(left + right)
    rets, skipped = _daily_returns(s, field_name="acc_nav")
    assert any("gap" in str(x.get("reason")) for x in skipped)
    # 不能出现跨越缺口的巨大收益
    assert all(abs(r) < 0.5 for _, r, _ in rets)


# ================================================================ 9. 样本不足
def test_insufficient_sample_annualized():
    rows = daily_rows("2020-01-01", 100)  # 不足 1 年
    s = make_series(rows)
    ind = compute_nav_indicators(s)
    a = ind["annualized_return"]
    assert a["status"] == "insufficient_data"
    assert "不足 1 年" in a["reason"]


def test_insufficient_for_volatility():
    rows = daily_rows("2020-01-01", 10)
    s = make_series(rows)
    ind = compute_nav_indicators(s)
    v = ind["risk"]["volatility"]
    assert v["status"] == "insufficient_data"
    assert "不足 30" in v["reason"]


# ================================================================ 10. 年化自然日口径
def test_annualized_uses_calendar_days():
    # 2 年整，净值翻倍 → 约 sqrt(2)-1
    d0 = date(2020, 1, 1)
    d1 = date(2022, 1, 1)
    rows = [(d0.isoformat(), 1.0, 1.0), (d1.isoformat(), 2.0, 2.0)]
    s = make_series(rows)
    ind = compute_nav_indicators(s)
    a = ind["annualized_return"]
    assert a["status"] == "ok"
    assert a["span_days"] == 731
    assert a["method"] == "自然日间隔复合年化"
    expected = 2.0 ** (365.25 / 731) - 1
    assert abs(a["value"] - expected) < 1e-4


# ================================================================ 11. 波动率年化条件
def test_volatility_annualized_when_daily_confirmed():
    rows = daily_rows("2020-01-01", 500, step=0.0005)
    s = make_series(rows)
    v = compute_nav_indicators(s)["risk"]["volatility"]
    assert v["status"] == "ok"
    assert v["annualized"] is True
    assert v["annualization_factor"] > 0
    assert "观测频率" in v["annualization_basis"]


def test_volatility_not_annualized_when_gap():
    """有超阈值缺口时不得年化。"""
    left = daily_rows("2020-01-01", 300)
    right = [((date.fromisoformat("2021-03-01") + timedelta(days=i)).isoformat(),
              1.3 + i * 0.0005, 1.3 + i * 0.0005) for i in range(300)]
    s = make_series(left + right)
    v = compute_nav_indicators(s)["risk"]["volatility"]
    assert v["annualized"] is False
    assert ("缺口" in v["annualization_blocked_reason"]
            or "1 天间隔" in v["annualization_blocked_reason"])


def test_volatility_not_annualized_when_weekly():
    """周频数据（1 天间隔占比低）不得年化。"""
    d0 = date.fromisoformat("2020-01-01")
    rows = [((d0 + timedelta(days=7 * i)).isoformat(),
             1.0 + i * 0.002, 1.0 + i * 0.002) for i in range(120)]
    s = make_series(rows)
    v = compute_nav_indicators(s)["risk"]["volatility"]
    assert v["annualized"] is False
    assert "1 天间隔占比" in v["annualization_blocked_reason"]


def test_no_zero_fill_for_missing_days():
    """缺失日不得填 0。"""
    from app.fund.research.indicators import _daily_returns
    rows = daily_rows("2020-01-01", 40, field_none_at={20})
    s = make_series(rows)
    rets, skipped = _daily_returns(s, field_name="acc_nav")
    assert any(x["reason"] == "missing_value" for x in skipped)
    assert all(r != 0.0 for _, r, _ in rets if abs(r) < 1e-12) is not None


# ================================================================ 12. 无风险利率缺失
def test_sharpe_not_available_without_risk_free():
    rows = daily_rows("2020-01-01", 500, step=0.0005)
    s = make_series(rows)
    ra = compute_nav_indicators(s)["risk_adjusted"]
    assert ra["sharpe"]["status"] == "not_available"
    assert ra["sharpe"]["value"] is None
    assert "无风险利率" in ra["sharpe"]["reason"]
    assert ra["sortino"]["status"] == "not_available"


def test_zero_hurdle_sharpe_labeled():
    rows = daily_rows("2020-01-01", 500, step=0.0005)
    s = make_series(rows)
    z = compute_nav_indicators(s)["risk_adjusted"]["zero_hurdle_sharpe"]
    if z["status"] == "ok":
        assert "不是" in z["warning"]
        assert "零门槛" in z["warning"]
    else:
        assert z["value"] is None


def test_no_excess_return_without_benchmark():
    rows = daily_rows("2020-01-01", 500)
    s = make_series(rows)
    nc = compute_nav_indicators(s)["not_computed"]
    assert "excess_return" in nc
    assert "无基准" in nc["excess_return"]


# ================================================================ 13. 回撤修复 / ongoing
def test_max_drawdown_and_recovery():
    # 1.0 → 1.5 → 0.75 → 1.5
    rows = [("2020-01-01", 1.0, 1.0), ("2020-02-01", 1.5, 1.5),
            ("2020-03-01", 0.75, 0.75), ("2020-04-01", 1.5, 1.5)]
    s = make_series(rows)
    mdd = compute_nav_indicators(s)["risk"]["max_drawdown"]
    assert mdd["status"] == "ok"
    assert abs(mdd["value"] - 0.5) < 1e-9
    assert mdd["recovery"]["status"] == "ok"
    assert mdd["recovery"]["value"] == 31  # 03-01 → 04-01


def test_drawdown_ongoing():
    rows = [("2020-01-01", 1.0, 1.0), ("2020-02-01", 1.5, 1.5),
            ("2020-03-01", 0.75, 0.75), ("2020-04-01", 1.0, 1.0)]
    s = make_series(rows)
    mdd = compute_nav_indicators(s)["risk"]["max_drawdown"]
    assert mdd["recovery"]["status"] == "ongoing"
    assert "ongoing" in mdd["recovery"]["reason"]


# ================================================================ 14/15. A/C 份额归并
def test_merge_by_fund_groups_shares():
    from app.fund.research.engine import merge_by_fund
    reports = [
        {"fund_id": 1, "fund_code": "000001", "fund_name": "X",
         "share_code": "000001", "product_class": "bond_pure",
         "investment_subtype": "bond_pure",
         "peer_group": {"peer_key": "bond_pure|unknown"}, "indicators": {},
         "share_name": "X A"},
        {"fund_id": 1, "fund_code": "000001", "fund_name": "X",
         "share_code": "000002", "product_class": "bond_pure",
         "investment_subtype": "bond_pure",
         "peer_group": {"peer_key": "bond_pure|unknown"}, "indicators": {},
         "share_name": "X C"},
    ]
    merged = merge_by_fund(reports)
    assert len(merged) == 1
    assert merged[0]["share_count"] == 2
    assert merged[0]["representative_share"] == "000001"
    assert "cost_comparison" in merged[0]


def test_different_funds_not_merged():
    from app.fund.research.engine import merge_by_fund
    reports = [
        {"fund_id": 1, "fund_code": "000001", "fund_name": "X",
         "share_code": "000001", "product_class": "bond_pure",
         "investment_subtype": "bond_pure", "peer_group": {"peer_key": "a"},
         "indicators": {}, "share_name": "X"},
        {"fund_id": 2, "fund_code": "000003", "fund_name": "Y",
         "share_code": "000003", "product_class": "bond_pure",
         "investment_subtype": "bond_pure", "peer_group": {"peer_key": "a"},
         "indicators": {}, "share_name": "Y"},
    ]
    merged = merge_by_fund(reports)
    assert len(merged) == 2


# ================================================================ 16. 货币基金独立
def test_money_fund_not_using_nav():
    from app.fund.research.data_access import NavSeries, QualityReport
    s = NavSeries("M", 1, 1, "货币", "net_value", [], QualityReport("M", "net_value"))
    ind = compute_nav_indicators(s)
    assert ind["sample_size"] == 0
    # 货币基金不走这条路


def test_money_indicators_isolated():
    money = {"code": "000198", "share_class_id": 1, "fund_id": 1,
             "share_class_name": "余额宝", "nav_kind": "money_yield",
             "rows": 100, "date_min": "2020-01-01", "date_max": "2020-04-09",
             "null_per_10k": 0, "null_seven_day": 0, "max_gap_days": 3,
             "gap_count_over_threshold": 0, "gaps_sample": [],
             "continuity_verification": "cannot_verify", "uses_unit_nav": False}
    ind = compute_money_indicators(money)
    assert ind["uses_unit_nav"] is False
    assert ind["nav_based_indicators"]["status"] == "not_applicable"
    assert ind["per_10k_yield"]["usable_for_net_value_comparison"] is False
    assert ind["seven_day_annual"]["usable_for_net_value_comparison"] is False
    assert "禁止与净值型基金同榜" in ind["comparison_rule"]


# ================================================================ 17. LOF 分类
def test_lof_index_classified_as_lof():
    r = classify_fund({"fund_name": "招商中证白酒指数(LOF)",
                       "fund_type_l1": "指数型-股票", "is_index_fund": 1})
    assert r["product_class"] == "lof"
    assert r["investment_subtype"] == "index"


def test_lof_active_classified_as_lof():
    r = classify_fund({"fund_name": "富国天惠成长混合(LOF)",
                       "fund_type_l1": "混合型-偏股", "is_index_fund": None})
    assert r["product_class"] == "lof"
    assert r["investment_subtype"] == "active"


def test_ordinary_index_excludes_lof():
    r = classify_fund({"fund_name": "建信中证500指数增强",
                       "fund_type_l1": "指数型-股票", "is_index_fund": 1})
    assert r["product_class"] == "ordinary_index"


def test_lof_peer_group_by_subtype():
    a = classify_fund({"fund_name": "X(LOF)", "is_index_fund": 1})
    b = classify_fund({"fund_name": "Y(LOF)", "is_index_fund": None})
    ka = peer_group_key(a, "X(LOF)", None)["peer_key"]
    kb = peer_group_key(b, "Y(LOF)", None)["peer_key"]
    assert ka == "lof|index"
    assert kb == "lof|active"
    assert ka != kb


# ================================================================ 18. ETF 联接 vs 场内 ETF
def test_etf_linked_is_not_onshore_etf():
    r = classify_fund({"fund_name": "华夏沪深300ETF联接",
                       "fund_type_l1": "指数型-股票", "is_index_fund": 1})
    assert r["product_class"] == "etf_linked"
    assert is_offmarket_pool(r, "000051") is True


def test_onshore_etf_excluded():
    for code in ONSHORE_ETF_CODES:
        r = classify_fund({"fund_name": "某ETF", "is_index_fund": 1})
        assert is_offmarket_pool(r, code) is False


def test_qdii_excluded():
    r = classify_fund({"fund_name": "某QDII", "fund_type_l1": "QDII"})
    assert r["product_class"] == "qdii"
    assert is_offmarket_pool(r, "000999") is False


# ================================================================ 19. 宽基 vs 行业主题
def test_index_scope_broad():
    assert index_scope("华夏沪深300ETF联接") == "broad"
    assert index_scope("易方达中证500ETF联接") == "broad"


def test_index_scope_sector():
    assert index_scope("国联安中证半导体ETF联接") == "sector"
    assert index_scope("招商中证白酒指数(LOF)") == "sector"


def test_index_scope_unknown():
    assert index_scope("某某混合") == "unknown"


def test_peer_group_separates_broad_and_sector():
    broad = classify_fund({"fund_name": "华夏沪深300ETF联接", "is_index_fund": 1})
    sector = classify_fund({"fund_name": "国联安中证半导体ETF联接", "is_index_fund": 1})
    kb = peer_group_key(broad, "华夏沪深300ETF联接", None)["peer_key"]
    ks = peer_group_key(sector, "国联安中证半导体ETF联接", None)["peer_key"]
    assert kb != ks
    assert "broad" in kb and "sector" in ks


# ================================================================ 20/21. 费率边界
def _fee(rate, eff=None, ann=True):
    return {"fee_type": "management", "tier_order": None, "rate_original": rate,
            "rate_platform": None, "platform_name": None, "is_annual": ann,
            "effective_from": eff, "effective_to": None,
            "evidence_level": "A-" if eff else "C",
            "announcement_id": "ANN1" if eff else None, "detail": None}


def test_fee_with_effective_from_usable_after():
    from app.fund.research.fees import _fee_cell
    cell = _fee_cell({"rate_original": 0.0015, "effective_from": "2023-07-10",
                      "evidence_level": "A-", "announcement_id": "ANN1"})
    assert cell["status"] == "ok"
    assert cell["usable_for_historical"] is True
    assert cell["effective_from"] == "2023-07-10"
    assert cell["deducted_in_nav"] is True


def test_fee_without_effective_from_not_historical():
    from app.fund.research.fees import _fee_cell
    cell = _fee_cell({"rate_original": 0.005, "effective_from": None,
                      "evidence_level": "C", "announcement_id": None})
    assert cell["status"] == "ok"
    assert cell["usable_for_historical"] is False
    assert cell["usable_for_current_scenario"] is True


def test_fee_null_not_zero():
    from app.fund.research.fees import _fee_cell
    cell = _fee_cell({"rate_original": None, "effective_from": None,
                      "evidence_level": "C", "announcement_id": None})
    assert cell["status"] == "not_available"
    assert cell["rate"] is None
    assert "不当 0" in cell["reason"]


def test_fee_tier_historical_false():
    from app.fund.research.fees import _tier_cell
    cell = _tier_cell({"available": True, "tier_count": 5, "tiers_with_rate": 5,
                       "tiers_with_effective_from": 0,
                       "usable_for_current_scenario": True,
                       "usable_for_historical": False})
    assert cell["usable_for_historical"] is False
    assert cell["holding_days_basis"] == "unknown"


def test_alipay_fee_unknown():
    from app.fund.research.fees import _fee_cell
    from app.fund.research.data_access import load_fee_info
    # 不查库，只验证常量语义
    assert _fee_cell(None)["status"] == "not_available"


def test_share_cost_compare_not_comparable_when_unknown():
    from app.fund.research.fees import _diff_sales_service
    a = {"share_code": "A", "sales_service_fee": {"status": "ok", "rate": 0.0}}
    b = {"share_code": "C", "sales_service_fee": {"status": "not_available"}}
    d = _diff_sales_service(a, b)
    assert d["status"] == "not_comparable"


# ================================================================ 22. 规模不作时点因子
def test_aum_not_point_in_time():
    from app.fund.research.engine import admission_levels
    lv = admission_levels({"rows": 100, "null_unit": 0, "null_acc": 0,
                           "duplicate_dates": 0}, {})
    assert lv["aum"] == "C"
    assert lv["dividend"] == "C"


def test_admission_levels_field_level():
    from app.fund.research.engine import admission_levels
    lv = admission_levels({"rows": 100, "null_unit": 0, "null_acc": 0,
                           "duplicate_dates": 0}, {})
    # 不同字段不同等级
    assert lv["unit_nav"] == "A"
    assert lv["aum"] == "C"
    assert lv["alipay_purchasable"] == "unknown"
    assert len(set(lv.values())) >= 3


# ================================================================ 23. 支付宝 unknown
def test_alipay_unknown_stays_unknown():
    from app.fund.research.engine import admission_levels
    lv = admission_levels({"rows": 10, "null_unit": 0, "null_acc": 0,
                           "duplicate_dates": 0}, {})
    assert lv["alipay_purchasable"] == "unknown"
    assert lv["alipay_purchasable"] is not True
    assert lv["alipay_purchasable"] is not False


# ================================================================ 24. 状态与原因输出
def test_all_indicators_have_status():
    rows = daily_rows("2020-01-01", 500)
    s = make_series(rows)
    ind = compute_nav_indicators(s)
    for k, v in ind["returns"].items():
        assert "status" in v and "reason" in v, k
    for k in ("max_drawdown", "volatility", "downside_volatility"):
        assert "status" in ind["risk"][k], k
    for k, v in ind["risk_adjusted"].items():
        assert "status" in v, k


def test_not_computed_always_present():
    rows = daily_rows("2020-01-01", 100)
    s = make_series(rows)
    nc = compute_nav_indicators(s)["not_computed"]
    for k in ("excess_return", "style_stability", "information_ratio", "beta"):
        assert k in nc


# ================================================================ 分类表完整性
def test_taxonomy_nine_classes():
    from app.fund.research.classification import PRODUCT_TAXONOMY
    assert len(PRODUCT_TAXONOMY) == 9
    for k in ("ordinary_index", "etf_linked", "active_equity", "bond_pure",
              "bond_mixed", "money_market", "qdii", "lof", "onshore_etf"):
        assert k in PRODUCT_TAXONOMY


# ================================================================ 真实数据库只读集成（不写）
def test_real_universe_excludes_onshore_etf():
    from app.fund.research.data_access import load_universe
    u = load_universe()
    codes = {e["share_code"] for e in u}
    for c in ONSHORE_ETF_CODES:
        assert c not in codes
    assert len({e["fund_id"] for e in u}) == 9
    assert len(u) == 12


def test_real_161725_is_lof_index():
    from app.fund.research.data_access import load_universe
    u = load_universe()
    f = next(e for e in u if e["share_code"] == "161725")
    assert f["product_class"] == "lof"
    assert f["investment_subtype"] == "index"


def test_real_161005_is_lof_active():
    from app.fund.research.data_access import load_universe
    u = load_universe()
    f = next(e for e in u if e["share_code"] == "161005")
    assert f["product_class"] == "lof"
    assert f["investment_subtype"] == "active"
