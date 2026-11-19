"""阶段3B-3 场外基金数据可行性审计专项测试。

只测审计脚本的规则实现与产出一致性；不联网、不写库、不碰正式回测模块。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research_3b3_fund_data import (  # noqa: E402
    INITIAL_WINDOW_DAYS, SAMPLE_FUNDS, SHARE_PAIRS, _missing_runs,
    _parse_cash_per_10, check_nav_continuity, design_reuse, design_schema,
)

JSON_PATH = ROOT / "reports" / "phase3B3_fund_data_feasibility.json"
MD_PATH = ROOT / "reports" / "phase3B3_fund_data_feasibility.md"


@pytest.fixture(scope="module")
def payload() -> dict:
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 分红解析口径
def test_cash_per_share_parsing():
    """每10份 X 元必须归一化为每份 X/10，不能把「10」误当分红额。"""
    assert _parse_cash_per_10("每10份派现金0.2100元") == pytest.approx(0.021)
    assert _parse_cash_per_10("每10份派现金1.1500元") == pytest.approx(0.115)
    assert _parse_cash_per_10("每10份派现金0.0180元") == pytest.approx(0.0018)


def test_cash_per_share_never_returns_ten():
    """回归测试：早期解析器会把「每10份」的 10 当成金额，恒返回 1.0。"""
    for raw in ("每10份派现金0.2100元", "每10份派现金0.3800元",
                "每10份派现金0.0500元"):
        assert _parse_cash_per_10(raw) != pytest.approx(1.0)


def test_cash_per_share_handles_missing():
    assert _parse_cash_per_10(None) is None
    assert _parse_cash_per_10("不分红") is None


# ---------------------------------------------------------------- 样本覆盖
def test_sample_size_and_categories(payload):
    assert len(SAMPLE_FUNDS) >= 11
    cats = {c for _, c, _ in SAMPLE_FUNDS}
    for need in ("宽基指数", "行业指数", "ETF联接", "主动权益", "债券", "货币"):
        assert need in cats, need
    assert payload["summary"]["sample_target"] == len(SAMPLE_FUNDS)


def test_all_samples_verified(payload):
    assert payload["summary"]["sample_failed"] == 0
    assert payload["summary"]["sample_verified"] == len(SAMPLE_FUNDS)
    for f in payload["sample_funds"]:
        assert f["status"].startswith("ok"), f["code"]
        assert f["name_matched"] is True, f["code"]


def test_sample_names_match_expected(payload):
    expect = {c: n for c, _, n in SAMPLE_FUNDS}
    for f in payload["sample_funds"]:
        assert f["code"] in expect


# ---------------------------------------------------------------- A/C 份额
def test_share_pairs_distinct_codes(payload):
    """A/C 是不同代码但同一基金本体，绝不能被算成两只基金。"""
    for p in payload["share_classes"]["pairs"]:
        if p["c_code"] is None:
            continue
        assert p["a_code"] != p["c_code"]
        assert p["a_name"] != p["c_name"]


def test_share_class_counts(payload):
    sc = payload["share_classes"]
    assert sc["suffix_a_count"] > 5000
    assert sc["suffix_c_count"] > 5000
    assert sc["total_funds"] == 28380
    # A + C 之和必须小于总数，否则说明口径重复计数
    assert sc["suffix_a_count"] + sc["suffix_c_count"] < sc["total_funds"]


def test_share_pairs_declared_in_script():
    assert len(SHARE_PAIRS) >= 3


# ---------------------------------------------------------------- 净值口径
def test_unit_and_acc_nav_both_present(payload):
    """单位净值与累计净值必须是两个独立字段，不能混用。"""
    for f in payload["sample_funds"]:
        if f["category"] == "货币":
            continue
        assert f["unit_nav"]["rows"] > 0
        assert f["acc_nav"]["rows"] > 0
        assert "unit_last" in f["unit_vs_acc"]


def test_acc_nav_not_less_than_unit_nav(payload):
    for f in payload["sample_funds"]:
        va = f.get("unit_vs_acc")
        if not va:
            continue
        assert va["acc_last"] + 1e-9 >= va["unit_last"], f["code"]


def test_dividend_funds_have_acc_above_unit(payload):
    """有分红的基金，累计净值必须高于单位净值（差额即累计分红）。"""
    for f in payload["sample_funds"]:
        dv = f.get("dividends") or {}
        va = f.get("unit_vs_acc")
        if dv.get("count") and va and va["diff"] is not None:
            assert va["diff"] > 0, f["code"]


def test_money_fund_has_no_nav(payload):
    """货币基金用万份收益，没有单位净值——不能套用其他基金的净值口径。"""
    mf = [f for f in payload["sample_funds"] if f["category"] == "货币"]
    assert len(mf) == 1
    assert mf[0]["unit_nav"]["type"] == "money_fund_yield"


# ---------------------------------------------------------------- 跳变归因
def test_nav_jumps_are_attributed(payload):
    """净值跳变必须能归因到拆分或分红，否则应记异常。"""
    for f in payload["sample_funds"]:
        attr = f.get("nav_jump_attribution")
        if not attr:
            continue
        assert attr["total"] == (attr["explained_by_splits"]
                                 + attr["explained_by_dividends"]
                                 + attr["unexplained"])
        if attr["unexplained"] == 0:
            assert f["status"] == "ok", f["code"]


def test_no_unexplained_jumps_in_samples(payload):
    for f in payload["sample_funds"]:
        attr = f.get("nav_jump_attribution") or {}
        assert attr.get("unexplained", 0) == 0, f["code"]


# ---------------------------------------------------------------- 分红稳定性
def test_dividend_fetch_is_stable(payload):
    """分红接口两次返回条数必须一致；不一致要显式标注。"""
    for f in payload["sample_funds"]:
        dv = f.get("dividends")
        if not dv:
            continue
        assert "fetch_stable" in dv
        if dv["count"]:
            assert dv["fetch_stable"] is True, f["code"]


def test_dividend_rows_have_required_dates(payload):
    for f in payload["sample_funds"]:
        for r in ((f.get("dividends") or {}).get("rows") or []):
            assert r["ex_date"]
            assert r["record_date"]
            assert r["cash_per_share"] is not None
            assert 0 < r["cash_per_share"] < 1


# ---------------------------------------------------------------- 幸存者偏差
def test_survivorship_explicitly_unresolved(payload):
    s = payload["survivorship"]
    assert s["conclusion"] == "survivorship_bias_unresolved"
    assert s["liquidated_fund_source_available"] is False
    assert s["has_liquidated_status"] is False
    assert s["reason"]
    assert len(s["mitigation"]) >= 2


def test_no_liquidated_status_claimed(payload):
    """申购状态里没有清盘/终止取值，不得虚构。"""
    vals = payload["survivorship"]["purchase_status_values"]
    for v in vals:
        assert "清盘" not in v
        assert "终止" not in v


# ---------------------------------------------------------------- 数据源
def test_all_sources_probed(payload):
    s = payload["sources"]["summary"]
    assert s["total"] >= 12
    assert s["failed"] == 0
    for p in payload["sources"]["probes"]:
        assert p["status"] in ("ok", "empty")
        assert p["public"] is True
        assert p["auth_required"] is False
        assert p["long_term_stable"], p["source"]


def test_sources_record_stability_judgement(payload):
    """「现在能访问」不等于「长期稳定」，每个源必须写明稳定性判断。"""
    for p in payload["sources"]["probes"]:
        assert p["long_term_stable"] in ("高", "中", "低")
        assert len(p["stability_reason"]) > 5, p["source"]


# ---------------------------------------------------------------- 交易规则
def test_trading_rules_cover_required_topics(payload):
    rules = payload["trading_rules"]["rules"]
    assert len(rules) >= 10
    blob = " ".join(r["rule"] for r in rules)
    for kw in ("15:00", "申购确认", "赎回", "申购费", "赎回费",
               "A类", "暂停申购", "转换", "支付宝"):
        assert kw in blob, kw


def test_every_rule_has_evidence_level(payload):
    for r in payload["trading_rules"]["rules"]:
        assert r["evidence_level"]
        assert isinstance(r["data_source_available"], bool)
        assert isinstance(r["needs_manual_verification"], bool)
        assert r["note"]


def test_alipay_status_marked_unknown(payload):
    """没有可靠证据，不得声称某基金一定能在支付宝买到。"""
    rule = next(r for r in payload["trading_rules"]["rules"]
                if "支付宝" in r["rule"])
    assert rule["data_source_available"] is False
    assert "unknown" in rule["note"].lower()


def test_redemption_fee_not_claimed_available(payload):
    fees = payload["fees_and_status"]
    assert fees["has_redemption_fee_field"] is False
    assert fees["has_holding_period_rule"] is False
    assert fees["limitation"]


# ---------------------------------------------------------------- 架构设计
def test_schema_has_required_tables(payload):
    names = {t["table"] for t in payload["schema"]["tables"]}
    for need in ("fund_master", "fund_share_classes", "fund_nav_daily",
                 "fund_dividends", "fund_manager_history", "fund_aum_history",
                 "fund_fee_rules", "fund_subscription_status",
                 "fund_lifecycle_events", "fund_data_quality"):
        assert need in names, need


def test_schema_separates_master_and_share(payload):
    """基金本体与份额必须两级，否则 A/C 会重复计数。"""
    names = [t["table"] for t in payload["schema"]["tables"]]
    assert names.index("fund_master") < names.index("fund_share_classes")


def test_schema_not_migrated(payload):
    assert payload["schema"]["not_migrated"] is True
    assert "未执行" in payload["schema"]["migration_note"]


def test_schema_nav_has_two_columns():
    cols = next(t["columns"] for t in design_schema()["tables"]
                if t["table"] == "fund_nav_daily")
    assert "unit_nav" in cols
    assert "acc_nav" in cols


def test_schema_lifecycle_has_terminated():
    cols = next(t["columns"] for t in design_schema()["tables"]
                if t["table"] == "fund_master")
    assert "terminated_date" in cols


# ---------------------------------------------------------------- 模块复用
def test_reuse_boundary_declared(payload):
    r = payload["reuse"]
    assert len(r["reusable"]) >= 5
    assert len(r["to_build"]) >= 4
    assert "不把场内" in r["hard_boundary"]


def test_reuse_lists_fund_specific_builds(payload):
    built = " ".join(x["module"] for x in payload["reuse"]["to_build"])
    for kw in ("净值", "申购赎回", "费率"):
        assert kw in built, kw


# ---------------------------------------------------------------- 不碰正式模块
def test_no_formal_module_touched():
    """3B-3 的边界：不得修改回测/验证/量化模块，也不得开发场外基金回测引擎。

    注意：3B-4.0 已正式落地 app/fund/ 数据层，因此不能再断言该目录不存在。
    这里改为检查「3B-3 的禁止项」——不允许出现场外基金**回测/执行引擎**。
    """
    for rel in ("app/backtest", "app/validation", "app/quant"):
        assert (ROOT / rel).is_dir(), rel
    for pat in ("*fund*engine*", "*fund*backtest*", "*fund*execution*"):
        assert not list((ROOT / "app").rglob(pat)), pat


def test_3b3_was_design_only():
    """3B-3 本身只输出设计：断言存在于当时。

    3B-4.0 已正式建表，因此这里不再断言「库里没有 fund_* 表」，
    改为断言 3B-3 的 JSON 自己记录了「未迁移」这一事实。
    """
    payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    assert payload["schema"]["not_migrated"] is True
    assert "未执行" in payload["schema"]["migration_note"]


# ---------------------------------------------------------------- 文档一致性
def test_doc_exists_and_mentions_key_facts(payload):
    md = MD_PATH.read_text(encoding="utf-8")
    assert "survivorship_bias_unresolved" in md
    assert str(payload["summary"]["sample_verified"]) in md
    assert "支付宝" in md
    for p in payload["share_classes"]["pairs"][:2]:
        if p["a_code"]:
            assert p["a_code"] in md


def test_unresolved_listed(payload):
    assert len(payload["unresolved"]) >= 5
    blob = " ".join(payload["unresolved"])
    assert "survivorship" in blob.lower()


def test_baseline_head_recorded(payload):
    assert payload["baseline_head"].startswith("e14a8fa")

# ================================================================
# 净值日期连续性：全部用人工构造的小型数据验证
# ================================================================

# 一段干净的交易日历（跳过周末：1/6、1/7、1/13、1/14）
CAL = [
    "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05",
    "2024-01-08", "2024-01-09", "2024-01-10", "2024-01-11", "2024-01-12",
    "2024-01-15", "2024-01-16", "2024-01-17", "2024-01-18", "2024-01-19",
]


def test_continuity_complete_series_is_verified():
    """完整序列：三档结论必须是「已按交易日历代理验证」。"""
    r = check_nav_continuity(CAL, CAL)
    assert r["verdict"] == "verified_against_trading_calendar"
    assert r["missing_days"] == 0
    assert r["unexplained_missing"] == 0
    assert r["duplicate_dates"] == []
    assert r["is_sorted"] is True
    assert r["null_date_count"] == 0


def test_continuity_detects_duplicate_dates():
    """重复净值日期必须被检出。"""
    r = check_nav_continuity(CAL + ["2024-01-05"], CAL)
    assert r["verdict"] == "gaps_found"
    assert "2024-01-05" in r["duplicate_dates"]
    assert "重复" in r["verdict_reason"]


def test_continuity_detects_unsorted_dates():
    """乱序必须被检出（且不能用排序后的结果掩盖）。"""
    bad = list(CAL)
    bad[0], bad[-1] = bad[-1], bad[0]
    r = check_nav_continuity(bad, CAL)
    assert r["verdict"] == "gaps_found"
    assert r["is_sorted"] is False
    assert "乱序" in r["verdict_reason"]


def test_continuity_detects_null_dates():
    """空值日期必须被检出并计数。"""
    r = check_nav_continuity(CAL[:5] + [None] + CAL[5:], CAL)
    assert r["verdict"] == "gaps_found"
    assert r["null_date_count"] == 1
    assert "空值" in r["verdict_reason"]


def test_continuity_detects_missing_trading_day():
    """单个交易日缺失必须被检出。"""
    r = check_nav_continuity([d for d in CAL if d != "2024-01-10"], CAL)
    assert r["verdict"] == "gaps_found"
    assert r["missing_days"] == 1


def test_continuity_detects_consecutive_missing():
    """连续多日缺失必须合并成一段，并记录区间。"""
    drop = {"2024-01-09", "2024-01-10", "2024-01-11"}
    r = check_nav_continuity([d for d in CAL if d not in drop], CAL)
    assert r["verdict"] == "gaps_found"
    assert r["missing_days"] == 3
    runs = r["missing_runs"]
    assert len(runs) == 1
    assert runs[0]["start"] == "2024-01-09"
    assert runs[0]["end"] == "2024-01-11"
    assert runs[0]["trading_days"] == 3


def test_continuity_records_longest_gap():
    """最长连续缺失区间要单独记下来。"""
    r = check_nav_continuity(
        [d for d in CAL if d not in {"2024-01-09", "2024-01-10"}], CAL)
    assert r["longest_gap"] is not None
    assert r["longest_gap"]["start"] == "2024-01-09"
    assert r["longest_gap"]["trading_days"] == 2


def test_weekend_net_value_not_reported_as_gap():
    """周末出现净值（季末估值日）不是缺口，不得误报。"""
    # 2024-01-06 是周六
    r = check_nav_continuity(sorted(CAL + ["2024-01-06"]), CAL)
    assert r["verdict"] == "verified_against_trading_calendar"
    assert "2024-01-06" in r["off_calendar_dates"]
    assert r["off_calendar_is_problem"] is False


def test_holiday_not_reported_as_gap():
    """节假日不在日历里，自然不会被算作「应有净值却缺失」。"""
    # 构造一个跨春节的日历：2024-02-09 之后到 2024-02-19 是假期
    cal = ["2024-02-07", "2024-02-08", "2024-02-09",
           "2024-02-19", "2024-02-20", "2024-02-21"]
    r = check_nav_continuity(cal, cal)
    assert r["verdict"] == "verified_against_trading_calendar"
    assert r["missing_days"] == 0


def test_continuity_degrades_without_calendar():
    """拿不到可靠日历且无结构问题 → cannot_verify，不得声称连续。"""
    r = check_nav_continuity(CAL, None)
    assert r["verdict"] == "cannot_verify"
    assert r["calendar_available"] is False
    assert "无法" in r["verdict_reason"]


def test_continuity_still_detects_structure_without_calendar():
    """无日历也不能放过重复/乱序/空值——这些不依赖日历。"""
    r = check_nav_continuity(CAL + ["2024-01-05"], None)
    assert r["verdict"] == "gaps_found"
    assert r["duplicate_dates"]


def test_continuity_empty_input():
    r = check_nav_continuity([], CAL)
    assert r["verdict"] == "cannot_verify"
    assert r["total_rows"] == 0


def test_continuity_always_carries_caveat():
    """任何结论都必须带「代理验证」caveat，不能当绝对证明。"""
    for cal in (CAL,):
        r = check_nav_continuity(CAL, cal)
        assert r["verification_level"] == "proxy"
        assert "不是基金净值公布日历" in r["caveat"]


def test_initial_weekly_phase_explained():
    """成立初期按周公布造成的缺日，应被识别为低频期而非缺口。"""
    # 前 4 次按周（1/2、1/9、1/16），之后转日频
    weekly = ["2024-01-02", "2024-01-09", "2024-01-16"]
    daily = [d for d in CAL if d > "2024-01-16"]
    r = check_nav_continuity(weekly + daily, CAL)
    assert r["initial_weekly_phase"]["detected"] is True
    assert r["explained_by_initial_weekly"] > 0


def test_transition_gap_still_counts_as_gap():
    """周公布转日频接缝处的缺口仍算缺口，不能并入「已验证连续」。"""
    weekly = ["2024-01-02", "2024-01-09", "2024-01-16"]
    # 跳过 1/17（接缝），之后日频
    daily = [d for d in CAL if d > "2024-01-17"]
    r = check_nav_continuity(weekly + daily, CAL)
    assert r["verdict"] == "gaps_found"
    assert r["transition_gap_days"] >= 1
    assert "缺口" in r["verdict_reason"]


def test_calendar_day_mode_for_money_fund():
    """货币基金按自然日核对，周末也应有净值。"""
    cal_days = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]
    r = check_nav_continuity(cal_days, None, calendar_mode="calendar_day")
    assert r["calendar_source"].startswith("自然日")
    # 缺 1/3 → 应报缺口
    r2 = check_nav_continuity(
        ["2024-01-01", "2024-01-02", "2024-01-04"], None,
        calendar_mode="calendar_day")
    assert r2["verdict"] == "gaps_found"
    assert r2["missing_days"] == 1


def test_missing_runs_merges_across_weekend():
    """跨周末的缺失算同一段，不能被拆成两段。"""
    runs = _missing_runs(["2024-01-05", "2024-01-08"])  # 周五 + 下周一
    assert len(runs) == 1
    assert runs[0]["start"] == "2024-01-05"
    assert runs[0]["end"] == "2024-01-08"


def test_missing_runs_splits_on_long_break():
    """间隔超过 3 天必须拆成独立区间。"""
    runs = _missing_runs(["2024-01-05", "2024-01-15"])
    assert len(runs) == 2


# ---------------------------------------------------------------- 真实样本结论
def test_sample_continuity_present(payload):
    """每只样本都必须有连续性结果，不能留空。"""
    for f in payload["sample_funds"]:
        c = f.get("continuity")
        assert c, f["code"]
        assert c["verdict"] in (
            "verified_against_trading_calendar", "gaps_found", "cannot_verify")


def test_continuity_three_tiers_counted(payload):
    """三档结论必须分开计数，不能合并成一个「通过」。"""
    s = payload["summary"]
    for k in ("continuity_verified", "continuity_gaps_found",
              "continuity_cannot_verify"):
        assert isinstance(s[k], int)
    total = (s["continuity_verified"] + s["continuity_gaps_found"]
             + s["continuity_cannot_verify"])
    assert total == len(payload["sample_funds"])


def test_gaps_found_is_honestly_reported(payload):
    """本轮真实结论：不是全部连续。必须如实体现。"""
    s = payload["summary"]
    assert s["continuity_calendar_available"] is True
    # 若真的全部通过，这条会失败——用来防止「为了好看写全通过」
    assert s["continuity_gaps_found"] >= 1
    assert s["continuity_total_missing_days"] >= 1


def test_doc_does_not_claim_all_continuous(payload):
    """报告不得再「声称」全部连续。

    报告在「不能声称的事」一节里会**引用**这句话来否定它，
    所以要先剥掉该章节再看正文，否则会把否定句误判成声明。
    """
    md = MD_PATH.read_text(encoding="utf-8")
    cut = md.find("#### 6.0.6 不能声称的事")
    assert cut > 0, "报告缺少「不能声称的事」章节"
    body = md[:cut]
    for b in ("全部连续、无空洞", "净值全部连续"):
        for line in body.splitlines():
            if b not in line:
                continue
            # 允许「引用后否定」的写法（含修正/错误/不再/原报告 等字样），
            # 但不允许把它当成结论陈述。
            assert any(k in line for k in
                       ("修正", "错误", "不再", "原报告", "不得", "不能声称")), \
                f"正文仍在声称：{b} → {line.strip()}"


def test_continuity_audit_declares_proxy(payload):
    ca = payload["continuity_audit"]
    assert ca["calendar_is_fund_nav_calendar"] is False
    assert ca["verification_level"] == "proxy"
    assert "代理" in ca["caveat"]


def test_every_verdict_has_reason(payload):
    """每个结论都必须给出理由，不能只给标签。"""
    for f in payload["sample_funds"]:
        c = f["continuity"]
        assert c["verdict_reason"], f["code"]
