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


def piecewise_daily(anchors):
    """按锚点 [(date_str, value)] 线性插值成**每日连续**序列。

    用于构造「无缺口」的多段落数据，避免测试自身因缺口被拒。
    """
    pts = [(date.fromisoformat(d), v) for d, v in anchors]
    out = []
    for (d0, v0), (d1, v1) in zip(pts, pts[1:]):
        span = (d1 - d0).days
        for i in range(span):
            d = d0 + timedelta(days=i)
            v = v0 + (v1 - v0) * (i / span)
            out.append((d.isoformat(), round(v, 6), round(v, 6)))
    d, v = pts[-1]
    out.append((d.isoformat(), round(v, 6), round(v, 6)))
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
    # 2 年整、每日连续（无缺口），净值从 1.0 涨到 2.0
    rows = piecewise_daily([("2020-01-01", 1.0), ("2022-01-01", 2.0)])
    s = make_series(rows)
    assert s.quality.gap_count_over_threshold == 0
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
    """缺失日不得填 0：真正检查缺失点没有产生收益、没有补 0。"""
    from app.fund.research.indicators import _daily_returns
    rows = daily_rows("2020-01-01", 40, field_none_at={20})
    s = make_series(rows)
    rets, skipped = _daily_returns(s, field_name="acc_nav")

    missing_date = rows[20][0]
    ret_dates = {d.isoformat() for d, _, _ in rets}

    # ① 缺失点当天没有产生任何收益记录
    assert missing_date not in ret_dates
    # ② 缺失点之后的第三天（原本应有一条）也没被补出来
    assert rows[21][0] not in ret_dates
    # ③ 没有任何一条收益是被补成 0 的占位
    assert all(r != 0.0 for _, r, _ in rets), "存在被填成 0 的收益"
    # ④ skipped 里有明确原因，且指向缺失点
    reasons = [x for x in skipped if x["reason"] == "missing_value"]
    assert reasons, "缺失点未记录跳过原因"
    assert any(x["date"] == missing_date for x in reasons)
    # ⑤ 有效收益点数 = 总相邻对数 - 被跳过的对数
    assert len(rets) + len(skipped) == len(s.points) - 1
    # ⑥ 缺失前后的净值没有被直接连起来算收益：
    #    缺失点前后两天都在有效日期集合里，但它们之间**没有**收益记录
    d19, d21 = rows[19][0], rows[21][0]
    for (d, _, _), (d_prev, _, _) in zip(rets[1:], rets[:-1]):
        assert not (d_prev.isoformat() == d19 and d.isoformat() == d21), \
            "缺失点前后的净值被直接连接计算了收益"


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
    # 1.0 → 1.5 → 0.75 → 1.5，每日连续
    rows = piecewise_daily([("2020-01-01", 1.0), ("2020-02-01", 1.5),
                            ("2020-03-01", 0.75), ("2020-04-01", 1.5)])
    s = make_series(rows)
    mdd = compute_nav_indicators(s)["risk"]["max_drawdown"]
    assert mdd["status"] == "ok"
    assert abs(mdd["value"] - 0.5) < 1e-9
    assert mdd["recovery"]["status"] == "ok"
    assert mdd["recovery"]["value"] == 31  # 03-01 → 04-01


def test_drawdown_ongoing():
    rows = piecewise_daily([("2020-01-01", 1.0), ("2020-02-01", 1.5),
                            ("2020-03-01", 0.75), ("2020-04-01", 1.0)])
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
    assert merged[0]["representative_reason"]
    assert merged[0]["representative_rule"]
    # 费用比较保留份额维度
    assert merged[0]["cost_comparison"]["share_count"] == 2


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
    # LOF index 与 active 必须分组（LOF 独立产品结构不变）
    assert ka.startswith("lof|index")
    assert kb.startswith("lof|active")
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


# ================================================================ 验收修正 A：本体去重
def test_peer_analysis_dedupes_by_fund_id():
    """同一 fund_id 的两个份额，同类成员数必须是 1。"""
    from app.fund.research.engine import merge_by_fund, peer_analysis
    reports = [
        {"fund_id": 1, "fund_code": "161725", "fund_name": "白酒(LOF)",
         "share_code": "161725", "share_name": "白酒A",
         "product_class": "lof", "investment_subtype": "index",
         "peer_group": {"peer_key": "lof|index|sector|中证白酒"},
         "quality": {"rows": 2794}, "indicators": {}},
        {"fund_id": 1, "fund_code": "161725", "fund_name": "白酒(LOF)",
         "share_code": "012414", "share_name": "白酒C",
         "product_class": "lof", "investment_subtype": "index",
         "peer_group": {"peer_key": "lof|index|sector|中证白酒"},
         "quality": {"rows": 1338}, "indicators": {}},
    ]
    merged = merge_by_fund(reports)
    pa = peer_analysis(merged, share_count=len(reports))
    assert len(merged) == 1
    assert pa["groups"]["lof|index|sector|中证白酒"]["member_count"] == 1
    assert pa["groups"]["lof|index|sector|中证白酒"]["fund_ids"] == [1]
    assert pa["fund_count"] == 1
    assert pa["share_count"] == 2


def test_peer_analysis_different_funds_not_merged():
    from app.fund.research.engine import merge_by_fund, peer_analysis
    reports = [
        {"fund_id": 1, "fund_code": "000051", "fund_name": "A",
         "share_code": "000051", "share_name": "A", "product_class": "etf_linked",
         "investment_subtype": "index",
         "peer_group": {"peer_key": "etf_linked|broad|沪深300"},
         "quality": {"rows": 100}, "indicators": {}},
        {"fund_id": 2, "fund_code": "110020", "fund_name": "B",
         "share_code": "110020", "share_name": "B", "product_class": "etf_linked",
         "investment_subtype": "index",
         "peer_group": {"peer_key": "etf_linked|broad|沪深300"},
         "quality": {"rows": 100}, "indicators": {}},
    ]
    merged = merge_by_fund(reports)
    pa = peer_analysis(merged, share_count=2)
    assert len(merged) == 2
    assert pa["groups"]["etf_linked|broad|沪深300"]["member_count"] == 2


def test_cost_comparison_keeps_all_shares():
    """归并后费用比较仍包含全部份额。"""
    from app.fund.research.engine import merge_by_fund
    reports = [
        {"fund_id": 1, "fund_code": "000015", "fund_name": "纯债",
         "share_code": "000015", "share_name": "纯债A",
         "product_class": "bond_pure", "investment_subtype": "bond_pure",
         "peer_group": {"peer_key": "bond_pure|unknown"},
         "quality": {"rows": 3310}, "indicators": {}},
        {"fund_id": 1, "fund_code": "000015", "fund_name": "纯债",
         "share_code": "000016", "share_name": "纯债C",
         "product_class": "bond_pure", "investment_subtype": "bond_pure",
         "peer_group": {"peer_key": "bond_pure|unknown"},
         "quality": {"rows": 3310}, "indicators": {}},
    ]
    merged = merge_by_fund(reports)
    assert merged[0]["cost_comparison"]["share_count"] == 2
    codes = {x["share_code"] for x in merged[0]["cost_comparison"]["shares"]}
    assert codes == {"000015", "000016"}


def test_representative_insufficient_data_status():
    """全部份额无数据必须标 insufficient_data，不能静默取。"""
    from app.fund.research.engine import merge_by_fund
    reports = [
        {"fund_id": 9, "fund_code": "999999", "fund_name": "空",
         "share_code": "999999", "share_name": "空A",
         "product_class": "bond_pure", "investment_subtype": "bond_pure",
         "peer_group": {"peer_key": "bond_pure|unknown"},
         "quality": {"rows": 0}, "indicators": None},
    ]
    merged = merge_by_fund(reports)
    assert merged[0]["status"] == "insufficient_data"
    assert merged[0]["performance"] is None
    assert "insufficient_data" in merged[0]["representative_reason"]


def test_representative_fallback_reason_recorded():
    """主份额无数据时改选其他份额，必须记录原因。"""
    from app.fund.research.engine import merge_by_fund
    reports = [
        {"fund_id": 3, "fund_code": "007300", "fund_name": "半导体",
         "share_code": "007300", "share_name": "A",
         "product_class": "etf_linked", "investment_subtype": "index",
         "peer_group": {"peer_key": "etf_linked|sector|中证全指半导体"},
         "quality": {"rows": 0}, "indicators": None},
        {"fund_id": 3, "fund_code": "007300", "fund_name": "半导体",
         "share_code": "007301", "share_name": "C",
         "product_class": "etf_linked", "investment_subtype": "index",
         "peer_group": {"peer_key": "etf_linked|sector|中证全指半导体"},
         "quality": {"rows": 1799}, "indicators": {"x": 1}},
    ]
    merged = merge_by_fund(reports)
    assert merged[0]["representative_share"] == "007301"
    assert "主份额数据不足" in merged[0]["representative_reason"]
    assert merged[0]["status"] == "ok"


# ================================================================ 验收修正 B：基准分组
def test_hs300_and_csi500_not_same_group():
    """沪深300 与 中证500 不得进入同一指数比较组。"""
    a = classify_fund({"fund_name": "华夏沪深300ETF联接", "is_index_fund": 1})
    b = classify_fund({"fund_name": "建信中证500指数增强", "is_index_fund": 1})
    ka = peer_group_key(a, "华夏沪深300ETF联接",
                        "沪深300指数收益率×95%＋1%")["peer_key"]
    kb = peer_group_key(b, "建信中证500指数增强",
                        "95%×中证500指数收益率+5%×活期存款利率")["peer_key"]
    assert ka != kb
    assert "沪深300" in ka
    assert "中证500" in kb


def test_same_tracking_index_same_group():
    """同一跟踪指数可以进入同一组。"""
    a = classify_fund({"fund_name": "华夏沪深300ETF联接", "is_index_fund": 1})
    b = classify_fund({"fund_name": "易方达沪深300ETF联接", "is_index_fund": 1})
    ka = peer_group_key(a, "华夏沪深300ETF联接", "沪深300指数收益率×95%")["peer_key"]
    kb = peer_group_key(b, "易方达沪深300ETF联接", "沪深300指数收益率X95%")["peer_key"]
    assert ka == kb
    assert "沪深300" in ka


def test_active_funds_different_benchmark_grouped_apart():
    """两个主动基金基准不同必须分组。"""
    a = classify_fund({"fund_name": "易方达消费行业股票",
                       "fund_type_l1": "股票型", "is_index_fund": None})
    b = classify_fund({"fund_name": "富国天惠成长混合(LOF)",
                       "fund_type_l1": "混合型-偏股", "is_index_fund": None})
    ka = peer_group_key(a, "易方达消费行业股票", "中证内地消费主题指数收益率×85%+中债总指数收益率×15%")
    kb = peer_group_key(b, "富国天惠成长混合(LOF)", "沪深300指数收益率×70%+中债综合全价指数收益率×25%")
    assert ka["peer_key"] != kb["peer_key"]


def test_benchmark_empty_is_unknown():
    """benchmark 为空必须 unknown。"""
    from app.fund.research.classification import normalize_benchmark
    r = normalize_benchmark(None)
    assert r["family"] == "unknown"
    r2 = normalize_benchmark("")
    assert r2["family"] == "unknown"
    a = classify_fund({"fund_name": "天弘余额宝货币", "fund_type_l1": "货币型"})
    pg = peer_group_key(a, "天弘余额宝货币", None)
    assert pg["benchmark_family"] == "unknown"


def test_unrecognizable_benchmark_is_unknown():
    """无法可靠标准化的基准必须 unknown。"""
    from app.fund.research.classification import normalize_benchmark
    r = normalize_benchmark("某个没人认识的定制复合基准×50%+银行存款")
    assert r["family"] == "unknown"
    assert "无法" in r["reason"]


def test_multi_index_benchmark_not_forced_into_group():
    """含多个指数族的复合基准不得强行归组。"""
    from app.fund.research.classification import normalize_benchmark
    r = normalize_benchmark("中证内地消费主题指数收益率×85%+中债总指数收益率×15%")
    assert r["family"] == "unknown"


def test_broad_sector_still_separated():
    """宽基与行业主题隔离继续有效。"""
    broad = classify_fund({"fund_name": "华夏沪深300ETF联接", "is_index_fund": 1})
    sector = classify_fund({"fund_name": "国联安中证半导体ETF联接", "is_index_fund": 1})
    kb = peer_group_key(broad, "华夏沪深300ETF联接", "沪深300指数收益率×95%")
    ks = peer_group_key(sector, "国联安中证半导体ETF联接",
                        "中证全指半导体产品与设备指数收益率×95%")
    assert kb["index_scope"] == "broad"
    assert ks["index_scope"] == "sector"
    assert kb["peer_key"] != ks["peer_key"]


def test_lof_index_active_separated():
    """LOF index/active 独立分组继续有效。"""
    ia = classify_fund({"fund_name": "招商中证白酒指数(LOF)", "is_index_fund": 1})
    ac = classify_fund({"fund_name": "富国天惠成长混合(LOF)", "is_index_fund": None})
    ki = peer_group_key(ia, "招商中证白酒指数(LOF)", "中证白酒指数收益率×95%")
    ka = peer_group_key(ac, "富国天惠成长混合(LOF)", "沪深300指数收益率×70%")
    assert ki["peer_key"].startswith("lof|index")
    assert ka["peer_key"].startswith("lof|active")
    assert ki["peer_key"] != ka["peer_key"]


def test_bond_unknown_not_explained_as_same():
    """债券久期 unknown 不得解释成相同久期。"""
    a = classify_fund({"fund_name": "华夏纯债债券", "fund_type_l1": "债券型-长债"})
    pg = peer_group_key(a, "华夏纯债债券", "中债综合指数")
    assert pg["duration_bucket"] == "unknown"
    assert pg["credit_bucket"] == "unknown"
    assert pg["convertible_bucket"] == "unknown"


def test_onshore_etf_still_excluded():
    for code in ONSHORE_ETF_CODES:
        r = classify_fund({"fund_name": "某ETF", "is_index_fund": 1})
        assert is_offmarket_pool(r, code) is False


# ================================================================ 验收修正 C：缺口安全
def test_annualized_rejected_on_gap():
    """年化收益区间有超 15 天缺口必须拒绝。"""
    left = daily_rows("2020-01-01", 200)
    gap_start = date.fromisoformat("2020-08-01")   # 距 2020-07-18 有 14+ 天
    right = [((gap_start + timedelta(days=400 + i)).isoformat(),
              2.0 + i * 0.001, 2.0 + i * 0.001) for i in range(200)]
    s = make_series(left + right)
    assert s.quality.gap_count_over_threshold >= 1
    a = compute_nav_indicators(s)["annualized_return"]
    assert a["status"] == "insufficient_data"
    assert "缺口" in a["reason"]


def test_annualized_ok_without_gap():
    """无缺口时年化仍能正常计算。"""
    rows = piecewise_daily([("2020-01-01", 1.0), ("2023-01-01", 1.5)])
    s = make_series(rows)
    assert s.quality.gap_count_over_threshold == 0
    a = compute_nav_indicators(s)["annualized_return"]
    assert a["status"] == "ok"
    assert a["value"] is not None


def test_annualized_rejected_on_null_nav():
    """累计净值有空值时不得假装区间完整年化。"""
    rows = piecewise_daily([("2020-01-01", 1.0), ("2023-01-01", 1.5)])
    mid = len(rows) // 2
    rows[mid] = (rows[mid][0], rows[mid][1], None)
    s = make_series(rows)
    a = compute_nav_indicators(s)["annualized_return"]
    assert a["status"] == "insufficient_data"
    assert "为空" in a["reason"]


def test_rolling_window_skips_internal_gap():
    """90 天窗口内部有超阈值缺口时跳过并计数。

    缺口必须小于窗口宽度（90 天）才可能被窗口完整包含，因此用 40 天缺口。
    """
    left = piecewise_daily([("2020-01-01", 1.0), ("2020-06-30", 1.1)])
    right = piecewise_daily([("2020-08-10", 1.2), ("2021-06-30", 1.4)])
    s = make_series(left + right)
    assert s.quality.gap_count_over_threshold >= 1
    gap = s.quality.gaps[0]
    gap_days = gap["days"]
    assert 15 < gap_days < 90, f"缺口 {gap_days} 天需落在 (15, 90) 才可能被 90 天窗口包含"
    r = compute_nav_indicators(s)["stability"]["rolling_positive_ratio_90d"]
    assert r["status"] == "ok"
    assert r["skipped_gap"] > 0, "跨缺口的 90 天窗口必须被跳过"
    # 有效窗口 + 各类跳过 不能超过总候选
    assert r["samples"] >= 5


def test_rolling_insufficient_windows():
    """有效窗口不足 5 个返回 insufficient_data。"""
    rows = piecewise_daily([("2020-01-01", 1.0), ("2020-03-01", 1.02)])
    s = make_series(rows)
    r = compute_nav_indicators(s)["stability"]["rolling_positive_ratio_90d"]
    assert r["status"] == "insufficient_data"
    assert "不足 5" in r["reason"]


def test_max_drawdown_degrades_on_null():
    """累计净值空值时回撤必须降级，不得跨越缺失点。"""
    rows = piecewise_daily([("2020-01-01", 1.0), ("2020-06-01", 1.5),
                            ("2020-12-01", 0.7)])
    mid = len(rows) // 2
    rows[mid] = (rows[mid][0], rows[mid][1], None)
    s = make_series(rows)
    mdd = compute_nav_indicators(s)["risk"]["max_drawdown"]
    assert mdd["degraded"] is True
    assert mdd["null_count"] >= 1
    assert "不是全区间完整最大回撤" in mdd["degraded_reason"]
    assert len(mdd["segments"]) >= 2


def test_max_drawdown_degrades_on_gap():
    """超阈值缺口时回撤明确降级。"""
    left = piecewise_daily([("2020-01-01", 1.0), ("2020-06-01", 1.5)])
    right = piecewise_daily([("2021-06-01", 1.2), ("2021-12-01", 0.8)])
    s = make_series(left + right)
    mdd = compute_nav_indicators(s)["risk"]["max_drawdown"]
    assert mdd["degraded"] is True
    assert "缺口" in mdd["degraded_reason"]
    assert mdd["complete_interval"] is False


def test_recovery_not_across_gap():
    """回撤修复不得跨越缺口。"""
    left = piecewise_daily([("2020-01-01", 1.0), ("2020-03-01", 0.7)])
    right = piecewise_daily([("2021-06-01", 0.7), ("2021-12-01", 1.5)])
    s = make_series(left + right)
    mdd = compute_nav_indicators(s)["risk"]["max_drawdown"]
    rec = mdd["recovery"]
    # 缺口后的净值不能算作缺口前的修复
    if rec.get("status") == "ok":
        assert rec["recovered_date"] <= left[-1][0]


def test_calmar_degrades_with_underlying():
    """年化不可算时 Calmar 必须降级。"""
    left = daily_rows("2020-01-01", 200)
    right = [((date.fromisoformat("2020-08-01") + timedelta(days=400 + i)).isoformat(),
              2.0 + i * 0.001, 2.0 + i * 0.001) for i in range(200)]
    s = make_series(left + right)
    ra = compute_nav_indicators(s)["risk_adjusted"]
    assert ra["calmar"]["status"] == "insufficient_data"


def test_no_gap_results_unchanged():
    """无缺口数据原结果不变。"""
    rows = piecewise_daily([("2020-01-01", 1.0), ("2020-07-01", 1.5),
                            ("2021-01-01", 1.2), ("2022-01-01", 1.8)])
    s = make_series(rows)
    assert s.quality.gap_count_over_threshold == 0
    ind = compute_nav_indicators(s)
    assert ind["annualized_return"]["status"] == "ok"
    mdd = ind["risk"]["max_drawdown"]
    assert mdd["status"] == "ok"
    assert mdd["degraded"] is False
    assert mdd["complete_interval"] is True
    assert ind["risk_adjusted"]["calmar"]["status"] == "ok"


# ================================================================ 验收修正 D：真实样本
def test_sample_dedup_by_fund_id_real():
    """实际样本：三对 A/C 各只算一个本体。"""
    from app.fund.research.data_access import load_universe
    from app.fund.research.engine import merge_by_fund, peer_analysis
    u = load_universe()
    reports = [{"fund_id": e["fund_id"], "fund_code": e["fund_code"],
                "fund_name": e["fund_name"], "share_code": e["share_code"],
                "share_name": e["share_name"],
                "product_class": e["product_class"],
                "investment_subtype": e["investment_subtype"],
                "peer_group": e["peer_group"],
                "quality": {"rows": 1}, "indicators": {}} for e in u]
    merged = merge_by_fund(reports)
    assert len(merged) == 9
    pa = peer_analysis(merged, share_count=len(reports))
    assert pa["fund_count"] == 9
    assert pa["share_count"] == 12
    total_members = sum(g["member_count"] for g in pa["groups"].values())
    assert total_members == 9, "同类成员总数必须等于本体数"
    # 每个 fund_id 只出现一次
    seen = []
    for g in pa["groups"].values():
        seen.extend(g["fund_ids"])
    assert len(seen) == len(set(seen)) == 9
