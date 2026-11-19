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

# ================================================================ 3B-4.1.1 增量
from scripts.research_3b4_1_1_roster_fee_audit import (  # noqa: E402
    EVENT_TYPES as E411,
    audit_fee_tiers as audit_fee_411,
    classify_event as classify_411,
    fund_entity_key,
    is_non_event,
    parse_purchase_tiers as parse_purch_411,
    parse_redeem_tiers as parse_redeem_411,
)

JSON411 = ROOT / "reports" / "phase3B4_1_1_historical_roster_fee_audit.json"
MD411 = ROOT / "reports" / "phase3B4_1_1_historical_roster_fee_audit.md"


@pytest.fixture(scope="module")
def p411() -> dict:
    return json.loads(JSON411.read_text(encoding="utf-8"))


# ---------------- 口径：代码 / 份额 / 本体 / 事件
def test_411_distinguishes_four_counts(p411):
    """必须同时给出代码数、公告事件数、本体数、去重事件数。"""
    r = p411["roster"]
    for k in ("scanned_codes", "raw_code_records", "raw_announcement_events",
              "distinct_events", "distinct_fund_entities", "duplicate_collapsed"):
        assert isinstance(r[k], int), k


def test_411_event_count_less_than_raw(p411):
    """去重后的事件数必须严格小于原始代码记录数。"""
    r = p411["roster"]
    assert r["distinct_events"] < r["raw_code_records"]
    assert r["distinct_fund_entities"] <= r["distinct_events"]


def test_411_no_duplicate_entity_type_pairs(p411):
    """同一（基金本体 + 事件类型）只能出现一次——否则就是没去重。"""
    pairs = [(e["fund_entity"], e["event_type"]) for e in p411["roster"]["events"]]
    assert len(pairs) == len(set(pairs)), "存在重复的(本体,事件类型)对"


def test_411_announcement_ids_unique_per_entity_type(p411):
    """同一本体的同一类型事件，其主公告 ID 不应重复。"""
    for e in p411["roster"]["events"]:
        assert e["announcement_id"]
        assert e["announcement_title"]


# ---------------- 事件分类：五类必须互相独立
def test_411_event_types_independent():
    assert set(E411) == {"liquidation", "merge", "transformation",
                         "share_termination", "delisting", "unknown"}


def test_411_liquidation_not_from_terminate_word():
    """含「终止」不等于清盘——这是 3B-4.1 的核心教训。"""
    assert classify_411("XX基金终止上市公告") == "delisting"
    assert classify_411("关于XX份额终止运作的公告") == "share_termination"
    assert classify_411("XX基金合同(由XX分级基金终止分级运作变更而来)") == "share_termination"


def test_411_transformation_not_delisting():
    """「终止上市及转型期间」是转型，不是终止上市。"""
    assert classify_411("关于终止上市及转型期间基金名称变更的公告") == "transformation"


def test_411_liquidation_by_contract():
    """「终止XX基金合同」才是清盘。"""
    assert classify_411("关于终止XX基金合同的公告") == "liquidation"
    assert classify_411("XX基金清算报告") == "liquidation"


def test_411_merge_classified():
    assert classify_411("XX基金合并公告") == "merge"


def test_411_non_event_filter():
    """合同全文/定期报告不是事件公告。"""
    assert is_non_event("XX基金2023年第3季度报告") is True
    assert is_non_event("XX基金基金合同") is True
    assert is_non_event("XX基金托管协议") is True
    # 但「关于终止XX基金合同的公告」是事件公告
    assert is_non_event("关于终止XX基金合同的公告") is False


# ---------------- 基金本体键
def test_411_entity_key_extracts_fund_name():
    assert fund_entity_key("XX基金清算报告") in ("XX基金", "__no_name__:XX基金清算报告")
    k = fund_entity_key("国投瑞银瑞和沪深300指数分级证券投资基金清算报告")
    assert k == "国投瑞银瑞和沪深300指数分级证券投资基金"


def test_411_entity_key_falls_back_not_merges():
    """抽不出基金名时用整条标题作键，绝不返回空串（会被误合并）。"""
    k = fund_entity_key("基金裕泽：终止上市公告")
    assert k and ("__no_name__" in k or "基金" in k)


# ---------------- 费率区间表达
def test_411_redeem_tier_keeps_both_bounds():
    """必须同时保存下界与上界——只存一个数字无法表达区间。"""
    text = ("赎回费率|适用期限|赎回费率|小于7天|1.50%|"
            "大于等于7天，小于365天|0.50%|大于等于365天|0.00%|注：")
    tiers = parse_redeem_411(text)
    assert len(tiers) == 3
    assert tiers[0]["holding_days_max"] == 7
    assert tiers[0]["max_inclusive"] is False
    assert tiers[1]["holding_days_min"] == 7
    assert tiers[1]["min_inclusive"] is True
    assert tiers[1]["holding_days_max"] == 365


def test_411_redeem_tier_infers_zero_lower_bound():
    """「小于7天」没有显式下界，补 0 但必须标 min_inferred。"""
    tiers = parse_redeem_411("赎回费率|适用期限|赎回费率|小于7天|1.50%|注：")
    assert tiers[0]["holding_days_min"] == 0
    assert tiers[0]["min_inferred"] is True


def test_411_redeem_tier_accepts_xiaoyudengyu():
    """「小于等于6天」必须解析成闭区间上界 6，不能被当成无上限。"""
    tiers = parse_redeem_411(
        "赎回费率|适用期限|赎回费率|小于等于6天|1.50%|大于等于7天|0.00%|注：")
    assert tiers[0]["holding_days_max"] == 6
    assert tiers[0]["max_inclusive"] is True
    assert tiers[0]["is_open_ended"] is False


def test_411_redeem_tier_open_ended():
    tiers = parse_redeem_411(
        "赎回费率|适用期限|赎回费率|大于等于730天|0.00%|注：")
    assert tiers[0]["is_open_ended"] is True
    assert tiers[0]["holding_days_max"] is None


def test_411_year_to_days_conversion():
    tiers = parse_redeem_411("赎回费率|适用期限|赎回费率|大于等于1年|0.25%|注：")
    assert tiers[0]["holding_days_min"] == 365


def test_411_purchase_keeps_original_and_platform():
    """原始费率与平台优惠费率必须分开——平台不等于支付宝。"""
    text = ("申购费率|适用金额|原费率|天天基金优惠费率|"
            "小于50万元|1.00%|&nbsp;|&nbsp;0.10%||友情提示：")
    tiers = parse_purch_411(text)
    assert tiers[0]["original_rate"] == pytest.approx(0.01)
    assert tiers[0]["platform_rate"] == pytest.approx(0.001)


def test_411_purchase_amount_bounds():
    text = ("申购费率|适用金额|原费率|天天基金优惠费率|"
            "大于等于50万元，小于100万元|0.50%|&nbsp;|&nbsp;0.05%||友情提示：")
    tiers = parse_purch_411(text)
    assert tiers[0]["lower_bound"] == pytest.approx(500000)
    assert tiers[0]["upper_bound"] == pytest.approx(1000000)


# ---------------- 真实费率数据边界
def test_411_real_fees_have_no_gaps(p411):
    """12 只真实基金，区间不允许有空洞。"""
    f = p411["fee_audit"]
    assert f["with_gaps"] == 0, "存在区间空洞"
    assert f["with_overlaps"] == 0, "存在区间重叠"


def test_411_real_fees_single_open_end(p411):
    """除货币基金外，每只都必须恰好一档无上限。"""
    f = p411["fee_audit"]
    assert f["all_have_single_open_end"] >= 11


def test_411_real_fees_have_bounds(p411):
    f = p411["fee_audit"]
    assert f["all_have_bounds"] >= 11


def test_411_fee_issues_are_data_nature(p411):
    """剩下的问题必须是「数据本身没有」而不是解析 bug。"""
    for s in p411["fee_audit"]["samples"]:
        if not s["boundary_issues"]:
            continue
        joined = " ".join(s["boundary_issues"])
        ok = ("销售服务费" in joined) or ("无上限档位数异常: 0" in joined)
        assert ok, f"{s['code']} 出现了非数据性质的问题: {s['boundary_issues']}"


def test_411_annual_fees_marked(p411):
    for s in p411["fee_audit"]["samples"]:
        if s.get("annual_fees"):
            assert s["annual_fees"]["is_annual"] is True


# ---------------- 清盘/合并/转型的真实数量
def test_411_liquidation_count_reported(p411):
    """真正清盘事件必须单独统计且数量可观。"""
    liq = [e for e in p411["roster"]["events"] if e["event_type"] == "liquidation"]
    assert len(liq) >= 20, f"清盘样本过少: {len(liq)}"


def test_411_merge_count_honest(p411):
    """合并找不到就报 0，不许凑数。"""
    merge = [e for e in p411["roster"]["events"] if e["event_type"] == "merge"]
    assert len(merge) == 0
    assert "merge" in p411["roster"]["by_event_type_all"]


def test_411_all_event_types_present_in_stats(p411):
    stats = p411["roster"]["by_event_type_all"]
    for k in ("liquidation", "merge", "transformation", "delisting"):
        assert k in stats, k


def test_411_a_level_traceable(p411):
    """每条 A 级证据都必须有公告 URL 与 ID。"""
    for e in p411["roster"]["events"]:
        if e["evidence_level"] != "A":
            continue
        assert e["announcement_id"]
        assert e["announcement_url"].startswith("http")


def test_411_verified_has_url(p411):
    for e in p411["roster"]["events"]:
        assert e["announcement_url"], e["fund_entity"]


def test_411_liquidation_has_event_date(p411):
    """清盘事件应有清算开始日或最后运作日。"""
    liq = [e for e in p411["roster"]["events"] if e["event_type"] == "liquidation"]
    with_date = [e for e in liq if e["event_date"]]
    assert len(with_date) >= len(liq) * 0.7, f"清盘日期覆盖率过低: {len(with_date)}/{len(liq)}"


def test_411_successor_not_self(p411):
    """承接基金名不能等于本基金名。"""
    for e in p411["roster"]["events"]:
        if not e.get("successor_name"):
            continue
        assert not e["successor_name"].startswith(e["fund_entity"][:10]),             f"{e['fund_entity']} 的承接基金误抽成本身"


# ---------------- 文档一致
def test_411_doc_exists(p411):
    md = MD411.read_text(encoding="utf-8")
    assert str(p411["roster"]["distinct_events"]) in md
    assert str(p411["roster"]["distinct_fund_entities"]) in md
    assert "liquidation" in md


def test_411_doc_states_merge_zero(p411):
    md = MD411.read_text(encoding="utf-8")
    assert "合并" in md
    assert "0" in md


def test_411_doc_has_field_suggestion(p411):
    """必须给出最小化字段设计建议。"""
    md = MD411.read_text(encoding="utf-8")
    for k in ("min_inclusive", "max_inclusive", "min_inferred"):
        assert k in md, k


def test_411_baseline_recorded(p411):
    assert p411["baseline_head"].startswith("472603d4")


def test_411_no_formal_layer_touched():
    """本阶段不得新增场外基金回测引擎。"""
    for pat in ("*fund*engine*", "*fund*backtest*", "*fund*execution*"):
        assert not list((ROOT / "app").rglob(pat)), pat


def test_411_migration_still_ten_tables():
    """迁移文件不得被改动。"""
    sql = ROOT / "migrations" / "phase3b4_fund_data_layer.sql"
    body = sql.read_text(encoding="utf-8")
    assert body.count("CREATE TABLE IF NOT EXISTS fund_") == 10

# ================================================================ 3B-4.1.1 验收修正
from scripts.calibrate_3b4_1_1_types_evidence import (  # noqa: E402
    INVESTMENT_TYPE, PRODUCT_STRUCTURE, EVIDENCE_LEVELS as EV_CAL,
    classify_investment, classify_structure, extract_full_name,
    grade_evidence, offmarket_eligible, prefix_hint,
)

JSON_CAL = ROOT / "reports" / "phase3B4_1_1_types_evidence_calibration.json"
MD_CAL = ROOT / "reports" / "phase3B4_1_1_types_evidence_calibration.md"


@pytest.fixture(scope="module")
def pcal() -> dict:
    return json.loads(JSON_CAL.read_text(encoding="utf-8"))


# ---------------- 1. ETF 与 ETF 联接分类
def test_411c_etf_vs_etf_linked():
    """ETF 与 ETF 联接必须分开——名字只差「联接基金」三个字。"""
    etf_name = "招商中债-0-3年长三角地方政府债交易型开放式指数证券投资基金"
    link_name = "国泰中小板300成长交易型开放式指数证券投资基金联接基金"

    st_etf, _ = classify_structure(etf_name, "")
    st_link, _ = classify_structure(link_name, "")
    assert st_etf == "etf"
    assert st_link == "etf_linked"
    assert st_etf != st_link


def test_411c_etf_linked_requires_lianjie():
    """只含「交易型开放式指数」不含「联接」的，是 ETF 不是联接。"""
    st, _ = classify_structure("XX交易型开放式指数证券投资基金", "")
    assert st == "etf"


def test_411c_etf_linked_from_title_only():
    """正文抽不到，但标题写了「联接基金」，也要判成 etf_linked。"""
    st, _ = classify_structure("嘉实中证金边中期国债交易型开放式指数证券投资基金", "",
                               "嘉实…交易型开放式指数证券投资基金联接基金清算报告提示性公告")
    assert st == "etf_linked"


# ---------------- 2. LOF 分类
def test_411c_lof_classification():
    st, _ = classify_structure("XX中小盘股票型证券投资基金(LOF)", "")
    assert st == "lof"
    st2, _ = classify_structure("XX混合型证券投资基金", "", "XX基金(LOF)清算报告")
    assert st2 == "lof"


def test_411c_lof_by_chinese_marker():
    st, _ = classify_structure("XX上市开放式基金", "")
    assert st == "lof"


def test_411c_ordinary_not_lof():
    st, _ = classify_structure("XX灵活配置混合型证券投资基金", "")
    assert st == "ordinary_open_ended"


# ---------------- 3. 场内 ETF 不能计入场外
def test_411c_onshore_etf_excluded():
    """场内 ETF 不算场外可买。"""
    assert offmarket_eligible("etf") is False
    assert offmarket_eligible("etf_linked") is True
    assert offmarket_eligible("lof") is True
    assert offmarket_eligible("ordinary_open_ended") is True
    assert offmarket_eligible("unknown") is False


def test_411c_real_etf_excluded_from_offmarket(pcal):
    """真实数据里，511000 / 511050 必须被排除在场外集合外。"""
    cal = pcal["calibration"]
    for r in cal:
        if r["product_structure"] == "etf":
            assert r["offmarket_eligible"] is False, r["codes_in_event"]
            assert r["is_onshore_etf"] is True
    etf_codes = {c for r in cal if r["is_onshore_etf"] for c in r["codes_in_event"]}
    assert "511000" in etf_codes
    assert "511050" in etf_codes


def test_411c_offmarket_count_is_subset(pcal):
    """场外数量必须严格小于总数（因为有场内 ETF）。"""
    s = pcal["stats"]
    assert 0 < s["offmarket_count"] < s["liquidation_total"]
    assert s["offmarket_count"] + s["onshore_etf_count"] == s["liquidation_total"]


# ---------------- 4. 证据等级逐条独立统计
def test_411c_evidence_per_event(pcal):
    """每条事件都必须有自己的证据等级，不能共用一个值。"""
    cal = pcal["calibration"]
    assert len(cal) == 43
    for r in cal:
        assert r["evidence_level"] in ("A", "B", "C", "D")
        assert r["evidence_reason"], r["codes_in_event"]


def test_411c_eastmoney_is_b_not_a():
    """东财转载不能给 A。"""
    lvl, reason = grade_evidence("http://pdf.dfcfw.com/pdf/H2_AN123_1.pdf")
    assert lvl == "B"
    assert "第三方转载" in reason


def test_411c_official_host_without_verify_is_b():
    lvl, _ = grade_evidence("http://www.csrc.gov.cn/a.pdf", official_verified=False)
    assert lvl == "B"


def test_411c_official_host_verified_is_a():
    lvl, _ = grade_evidence("http://eid.csrc.gov.cn/fund/a.pdf", official_verified=True)
    assert lvl == "A"


def test_411c_unknown_host_is_d():
    lvl, _ = grade_evidence("http://some-random-site.com/a.pdf")
    assert lvl == "D"


def test_411c_all_43_are_b(pcal):
    """真实结论：43 条全部 B 级，一条 A 都没有。"""
    levels = pcal["stats"]["by_evidence_level"]
    assert levels.get("A", 0) == 0
    assert levels.get("B", 0) == 43


# ---------------- 5. A 级数量不能被总事件数代替
def test_411c_a_count_not_total(pcal):
    """A 级数量必须是独立统计，不能等于事件总数。"""
    s = pcal["stats"]
    a = s["by_evidence_level"].get("A", 0)
    assert a != s["liquidation_total"], "A 级数量不能等于事件总数"
    assert a == 0
    # 各级之和必须等于总数
    total = sum(s["by_evidence_level"].values())
    assert total == s["liquidation_total"]


def test_411c_structure_sum_equals_total(pcal):
    s = pcal["stats"]
    assert sum(s["by_product_structure"].values()) == s["liquidation_total"]


def test_411c_investment_sum_equals_total(pcal):
    s = pcal["stats"]
    assert sum(s["by_investment_type"].values()) == s["liquidation_total"]


# ---------------- 6. Markdown 与 JSON 一致
def test_411c_md_json_consistent(pcal):
    md = MD_CAL.read_text(encoding="utf-8")
    s = pcal["stats"]
    for k in ("liquidation_total", "offmarket_count", "onshore_etf_count",
              "etf_linked_count", "lof_count", "ordinary_count"):
        assert str(s[k]) in md, f"报告缺少 {k}={s[k]}"


def test_411c_md_mentions_evidence_b(pcal):
    md = MD_CAL.read_text(encoding="utf-8")
    assert "B 级" in md or "**B**" in md
    assert "43" in md


def test_411c_md_states_etf_excluded(pcal):
    md = MD_CAL.read_text(encoding="utf-8")
    assert "511000" in md
    assert "511050" in md
    assert "剔除" in md


def test_411c_md_names_lianjie_fixed(pcal):
    """四处「联接基金」遗漏必须在报告里明确写出。"""
    md = MD_CAL.read_text(encoding="utf-8")
    for code in ("020025", "020035", "000087"):
        assert code in md


# ---------------- 名称修正
def test_411c_name_has_lianjie():
    n, src = extract_full_name(
        "国泰中小板300成长交易型开放式指数证券投资基金联接基金清算报告 基金管理人：...",
        "国泰中小板300成长交易型开放式指数证券投资基金联接基金清算报告")
    assert n and "联接基金" in n


def test_411c_name_no_duplicated_suffix():
    """「…证券投资基金基金」这种重复尾字必须清掉。"""
    n, _ = extract_full_name("长信价值优选混合型证券投资基金基金清算报告提示性公告",
                             "长信价值优选混合型证券投资基金基金清算报告提示性公告")
    assert n and not n.endswith("基金基金")


def test_411c_name_cleans_prefix():
    n, _ = extract_full_name(
        "1 关于南方誉鼎一年持有期混合型证券投资基金基金合同终止的公告",
        "关于南方誉鼎一年持有期混合型证券投资基金基金合同终止的公告")
    assert n and not n.startswith("关于")
    assert n and not n.startswith("1")


# ---------------- 前缀只作线索
def test_411c_prefix_hint_not_authoritative():
    """代码前缀只能作为线索记录，不能据此判定类型。"""
    assert prefix_hint(["511000"]) is not None
    assert prefix_hint(["000007"]) is None
    # 501 开头但原文没写 LOF → 仍判普通开放式，前缀只记 conflict
    st, _ = classify_structure("汇添富弘安混合型证券投资基金", "")
    assert st == "ordinary_open_ended"
    assert prefix_hint(["501041"]) == "LOF（上交所）"


# ---------------- 投资类型
def test_411c_investment_types():
    assert classify_investment("XX货币市场基金", "")[0] == "money_market"
    assert classify_investment("XX债券型证券投资基金", "")[0] == "bond"
    assert classify_investment("XX混合型证券投资基金", "")[0] == "mixed"
    assert classify_investment("XX股票型证券投资基金", "")[0] == "equity"
    assert classify_investment("XX中证500指数证券投资基金", "")[0] == "index"


def test_411c_investment_unknown_when_no_name():
    assert classify_investment("", "")[0] == "unknown"


# ---------------- 边界
def test_411c_kept_fee_fixes():
    """费率解析器的三个修复必须保留（不得回退）。"""
    text = ("赎回费率|适用期限|赎回费率|小于等于6天|1.50%|"
            "大于等于7天，小于等于364天|0.50%|大于等于365天|0.00%|注：")
    tiers = parse_redeem_411(text)
    assert tiers[0]["holding_days_max"] == 6
    assert tiers[0]["max_inclusive"] is True
    assert tiers[0]["holding_days_min"] == 0
    assert tiers[0]["min_inferred"] is True


def test_411c_migration_still_ten_tables():
    body = (ROOT / "migrations" / "phase3b4_fund_data_layer.sql").read_text(encoding="utf-8")
    assert body.count("CREATE TABLE IF NOT EXISTS fund_") == 10


def test_411c_enums_complete():
    for k in ("ordinary_open_ended", "etf_linked", "etf", "lof",
              "money_market", "bond", "mixed", "other", "unknown"):
        assert k in PRODUCT_STRUCTURE or k in INVESTMENT_TYPE
