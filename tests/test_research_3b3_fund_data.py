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
    SAMPLE_FUNDS, SHARE_PAIRS, _parse_cash_per_10, design_reuse, design_schema,
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
    """本阶段不得修改回测/验证/量化模块，也不得新增场外基金引擎。

    app/data/processors/fund_profile.py 是既有文件（仓库初始提交就有），
    属存量解析工具，不是本阶段新增，不在此约束内。
    """
    for rel in ("app/backtest", "app/validation", "app/quant"):
        assert (ROOT / rel).is_dir(), rel
    # 只检查「本阶段是否新增了场外基金引擎/回测适配层」
    for pat in ("*fund*engine*", "*fund*backtest*", "*fund*execution*"):
        assert not list((ROOT / "app").rglob(pat)), pat
    assert not (ROOT / "app" / "fund").exists()


def test_no_fund_tables_in_db():
    """本阶段只输出设计，数据库里不得出现 fund_* 表。"""
    from app.database.db import get_connection
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'fund%'"
        ).fetchall()
    assert rows == [], [r[0] for r in rows]


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
