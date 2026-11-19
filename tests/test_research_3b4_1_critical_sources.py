"""阶段3B-4.1 场外基金关键历史数据源审计专项测试。

全部用人工构造数据 + Mock，不联网、不写库、不碰正式数据层。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research_3b4_1_critical_sources import (  # noqa: E402
    DELISTED_FEE_PROBE, EVENT_TYPES, EVIDENCE_LEVELS, FEE_SAMPLES,
    TERMINATED_SAMPLES, classify_event, extract_dates_from_text,
    extract_successor, parse_annual_fees, parse_purchase_tiers,
    parse_redeem_tiers,
)

JSON_PATH = ROOT / "reports" / "phase3B4_1_critical_data_sources.json"
MD_PATH = ROOT / "reports" / "phase3B4_1_critical_data_sources.md"


@pytest.fixture(scope="module")
def payload() -> dict:
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


# ================================================================ 证据分级
def test_evidence_levels_defined(payload):
    assert set(payload["evidence_levels"]) == {"A", "B", "C", "D"}
    for level, desc in EVIDENCE_LEVELS.items():
        assert payload["evidence_levels"][level] == desc


def test_no_c_upgraded_to_a(payload):
    """C 级不能被包装成 A 级：费率来源是第三方页面，必须标 C。"""
    for r in payload["fees"]["samples"]:
        if r["ok"] and r.get("page_has_fee"):
            assert r["evidence_level"] == "C", r["code"]


def test_terminated_a_level_requires_source_text(payload):
    """A 级证据必须有可读正文 + 至少一个关键日期。"""
    for s in payload["terminated_funds"]["samples"]:
        if s["evidence_level"] == "A":
            assert s["pdf_ok"] is True, s["code"]
            assert (s["last_trading_date"] or s["delisting_date"]
                    or s["liquidation_start"]), s["code"]


# ================================================================ 事件分类
def test_event_types_distinguish_four_kinds(payload):
    """清盘/合并/转型/份额终止必须分开，不得混为一类。"""
    for k in ("liquidation", "merge", "transformation",
              "share_termination", "delisting"):
        assert k in EVENT_TYPES
        assert k in payload["event_types"]


def test_classify_liquidation():
    assert classify_event("XX基金清算报告") == "liquidation"
    assert classify_event("关于终止XX基金合同的公告") == "liquidation"
    assert classify_event("XX基金清盘公告") == "liquidation"


def test_classify_share_termination_before_delisting():
    """「终止运作」优先于「终止上市」——同一公告常同时出现。"""
    assert classify_event("关于XX份额终止运作、终止上市的公告") == "share_termination"


def test_classify_delisting():
    assert classify_event("基金天元终止上市提示性公告") == "delisting"


def test_classify_transformation():
    assert classify_event("关于XX基金转型的公告") == "transformation"


def test_classify_unknown():
    assert classify_event("XX基金2023年第3季度报告") == "unknown"
    assert classify_event("") == "unknown"
    assert classify_event(None) == "unknown"


# ================================================================ 日期抽取
def test_extract_last_trading_date():
    text = "本基金的最后运作日为2020年8月27日，于2020年8月28日起进入清算期。"
    d = extract_dates_from_text(text)
    assert d["last_trading_date"] == "2020-08-27"
    assert d["liquidation_start"] == "2020-08-28"


def test_extract_delisting_date():
    text = "终止上市日：2014年7月3日 终止上市权益登记日：2014年7月2日"
    d = extract_dates_from_text(text)
    assert d["delisting_date"] == "2014-07-03"


def test_extract_established_date():
    text = "本基金经核准募集，于2009年10月14日成立并正式运作。"
    d = extract_dates_from_text(text)
    assert d["established_date"] == "2009-10-14"


def test_extract_returns_none_when_absent():
    """抽不到就返回 None，不许猜。"""
    d = extract_dates_from_text("这是一段没有任何日期的文本。")
    for v in d.values():
        assert v is None


def test_extract_handles_iso_date():
    text = "终止上市日 2017-12-11"
    d = extract_dates_from_text(text)
    assert d["delisting_date"] == "2017-12-11"


# ================================================================ 承接基金
def test_extract_successor_name():
    text = '基金于2013年10月17日起变更为“大成景丰债券型证券投资基金”并继续运作'
    s = extract_successor(text)
    assert s["successor_name"] == "大成景丰债券型证券投资基金"


def test_successor_code_never_guessed():
    """承接基金代码不得从名称后的数字猜测——那常是份额代码。"""
    text = '变更为“大成景丰债券型证券投资基金（160919）”'
    s = extract_successor(text)
    assert s["successor_name"]
    assert s["successor_code"] is None, "代码必须留空由人工核对"


def test_extract_successor_returns_none_when_absent():
    s = extract_successor("本基金进入清算期，不再转型。")
    assert s["successor_name"] is None
    assert s["successor_code"] is None


# ================================================================ 费率解析
def test_parse_annual_fees():
    text = "管理费率|1.00%（每年）|托管费率|0.20%（每年）|销售服务费率|0.10%（每年）"
    f = parse_annual_fees(text)
    assert f["management_fee"] == pytest.approx(0.01)
    assert f["custody_fee"] == pytest.approx(0.002)
    assert f["sales_service_fee"] == pytest.approx(0.001)


def test_parse_annual_fees_missing_returns_none():
    """费率缺失必须是 None，不能返回 0 冒充。"""
    f = parse_annual_fees("销售服务费率|---|")
    assert f["sales_service_fee"] is None


def test_parse_purchase_tiers_keeps_both_rates():
    """必须同时保留原费率与平台优惠费率——平台不等于支付宝。"""
    text = ("申购费率|适用金额|原费率|天天基金优惠费率|"
            "小于50万元|1.00%|&nbsp;&nbsp;|&nbsp;&nbsp;0.10%|"
            "大于等于50万元，小于100万元|0.50%|&nbsp;|&nbsp;0.05%|"
            "|友情提示：")
    tiers = parse_purchase_tiers(text)
    assert len(tiers) == 2
    assert tiers[0]["original_rate"] == pytest.approx(0.01)
    assert tiers[0]["platform_rate"] == pytest.approx(0.001)
    assert tiers[0]["bound_amount"] == pytest.approx(500000)


def test_parse_redeem_tiers_basic():
    text = ("赎回费率|适用期限|赎回费率|小于7天|1.50%|"
            "大于等于7天，小于365天|0.50%|大于等于365天|0.00%|注：")
    tiers = parse_redeem_tiers(text)
    assert len(tiers) == 3
    assert tiers[0]["holding_days"] == 7
    assert tiers[0]["rate"] == pytest.approx(0.015)
    assert tiers[1]["holding_days"] == 365
    assert tiers[1]["rate"] == pytest.approx(0.005)
    assert tiers[2]["rate"] == pytest.approx(0.0)


def test_parse_redeem_tiers_year_unit():
    """「年」必须换算成天，否则阶梯会错位。"""
    text = "赎回费率|适用期限|赎回费率|大于等于1年|0.25%|注："
    tiers = parse_redeem_tiers(text)
    assert tiers[0]["holding_unit"] == "年"
    assert tiers[0]["holding_days"] == 365


def test_parse_redeem_tiers_empty_returns_empty():
    assert parse_redeem_tiers("没有费率信息") == []


# ================================================================ 样本要求
def test_terminated_sample_count_at_least_20(payload):
    assert len(TERMINATED_SAMPLES) >= 20
    assert payload["terminated_funds"]["count"] >= 20


def test_terminated_samples_cover_multiple_years(payload):
    years = payload["terminated_funds"]["by_year"]
    assert len(years) >= 5, f"覆盖年份过少: {years}"


def test_terminated_samples_cover_multiple_types(payload):
    types = payload["terminated_funds"]["by_event_type"]
    assert len([k for k in types if k != "unknown"]) >= 2, types


def test_all_terminated_samples_not_in_current_table(payload):
    """所有样本都必须不在当前存续名册里，否则就不是「历史终止」。"""
    bad = [s["code"] for s in payload["terminated_funds"]["samples"]
           if s["in_current_name_table"] is True]
    assert not bad, f"这些代码仍在存续名册: {bad}"


def test_fee_sample_count_at_least_10(payload):
    assert len(FEE_SAMPLES) >= 10
    assert payload["fees"]["count"] >= 10


def test_ac_pairs_at_least_3(payload):
    assert payload["fees"]["ac_pair_count"] >= 3, "至少要 3 组 A/C 份额"


def test_ac_pairs_have_distinct_codes(payload):
    for p in payload["fees"]["ac_pairs"]:
        assert p["a_code"] != p["c_code"]
        assert p["a_name"] != p["c_name"]


def test_ac_pairs_show_sales_service_difference(payload):
    """C 类销售服务费应大于 A 类（A 通常为 0）。"""
    checked = 0
    for p in payload["fees"]["ac_pairs"]:
        a = p["a_sales_service_fee"]
        c = p["c_sales_service_fee"]
        if a is None or c is None:
            continue
        assert c > a, f"{p['pair_id']}: C 类销售服务费应更高 (A={a}, C={c})"
        checked += 1
    assert checked >= 3


def test_every_sample_has_source_and_date(payload):
    """每个样本都必须有来源链接与核验日期。"""
    for s in payload["terminated_funds"]["samples"]:
        assert s["announcement_url"], s["code"]
    for r in payload["fees"]["samples"]:
        assert r["source_url"], r["code"]
        assert r["fetched_at"], r["code"]


def test_missing_fields_recorded(payload):
    """拿不到的字段必须显式记录，不能留空当没事。"""
    any_missing = False
    for s in payload["terminated_funds"]["samples"]:
        assert isinstance(s["missing_fields"], list)
        if s["missing_fields"]:
            any_missing = True
    assert any_missing, "应当至少有一个样本记录了缺失字段"


# ================================================================ 桌面结论
def test_historical_fee_not_recoverable(payload):
    """已终止基金的历史费率在公开渠道不可恢复——这是真实结论。"""
    probe = payload["fees"]["historical_fee_probe"]
    assert len(probe) >= 3
    assert payload["fees"]["historical_fee_recoverable"] == 0
    for p in probe:
        assert p["recoverable"] is False
        assert p["evidence_level"] == "D"


def test_alipay_not_obtainable(payload):
    a = payload["alipay"]
    assert a["conclusion"] == "not_obtainable"
    assert a["reason"]
    assert len(a["prohibited"]) >= 3
    assert a["recommendation"]["storage"].endswith("'unknown'")


def test_alipay_distinguishes_three_concepts(payload):
    d = payload["alipay"]["distinction"]
    assert "fund_open_subscription" in d
    assert "eastmoney_purchasable" in d
    assert "alipay_purchasable" in d
    assert "无公开数据源" in d["alipay_purchasable"]


def test_no_probe_claims_alipay_api(payload):
    """所有支付宝探测都必须标记「没有公开基金状态 API」。"""
    for p in payload["alipay"]["probes"]:
        assert p["public_api_for_fund_status"] is False, p["name"]


def test_answers_cover_six_questions(payload):
    a = payload["answers"]
    for k in ("q1_liquidated_roster_reliable", "q2_redemption_fee_tiers",
              "q3_historical_fees_recoverable", "q4_alipay_status_automatable",
              "q5_worth_automating", "q6_keep_manual"):
        assert k in a, k


def test_q1_answer_is_honest(payload):
    """不能声称「名录已完整建立」。"""
    q1 = payload["answers"]["q1_liquidated_roster_reliable"]
    assert q1["answer"] == "partially"
    assert "无法量化" in q1["coverage"]


def test_q4_answer_is_no(payload):
    assert payload["answers"]["q4_alipay_status_automatable"]["answer"] == "no"


def test_unresolved_listed(payload):
    assert len(payload["unresolved"]) >= 4


# ================================================================ 数据源
def test_sources_include_terminated_capable(payload):
    """必须至少有一个数据源明确覆盖已终止基金。"""
    covering = [s for s in payload["sources"] if s["covers_terminated"]]
    assert len(covering) >= 2


def test_sources_declare_evidence_level(payload):
    for s in payload["sources"]:
        assert s["evidence_level"] in ("A", "B", "C", "D")


def test_alipay_source_marked_not_suitable(payload):
    ali = next(s for s in payload["sources"] if "支付宝" in s["name"])
    assert ali["automation_suitable"] is False
    assert ali["auth_required"] is True


# ================================================================ 边界
def test_no_formal_data_layer_touched():
    """本阶段不得新增场外基金回测引擎/执行层。"""
    for pat in ("*fund*engine*", "*fund*backtest*", "*fund*execution*"):
        assert not list((ROOT / "app").rglob(pat)), pat


def test_migration_file_unchanged():
    """迁移文件不得在本阶段被改动（与 3B-4.0 一致）。"""
    sql = ROOT / "migrations" / "phase3b4_fund_data_layer.sql"
    assert sql.is_file()
    body = sql.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS fund_master" in body
    # 本阶段不得新增 fund_* 表定义
    assert body.count("CREATE TABLE IF NOT EXISTS fund_") == 10


# ================================================================ 文档一致
def test_doc_exists_and_consistent(payload):
    md = MD_PATH.read_text(encoding="utf-8")
    t = payload["terminated_funds"]
    assert str(t["count"]) in md
    assert str(payload["fees"]["count"]) in md
    assert "not_obtainable" in md or "不可获取" in md
    assert "survivorship_bias" in md or "幸存者偏差" in md


def test_doc_states_alipay_unknown(payload):
    md = MD_PATH.read_text(encoding="utf-8")
    assert "unknown" in md


def test_baseline_head_recorded(payload):
    assert payload["baseline_head"].startswith("e02096c5")
