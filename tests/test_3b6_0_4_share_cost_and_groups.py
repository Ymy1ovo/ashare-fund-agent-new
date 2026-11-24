"""阶段3B-6.0.4 A/C 份额成本与同类组隔离专项测试。

只读：临时库构造，不碰正式库。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.fund.research.peer_engine import (  # noqa: E402
    PEER_COMPARABLE, PEER_DESCRIPTIVE_ONLY, PEER_EXCLUDED,
    group_usability, is_verifiable_group,
)
from app.fund.research.share_cost import (  # noqa: E402
    COST_COMPUTABLE, COST_NOT_AVAILABLE, analyze_share_cost,
    redemption_fee_at,
)


# ================================================================ 组可用性
def test_money_market_is_verifiable():
    assert is_verifiable_group("money_market") is True


def test_bond_pure_unknown_not_verifiable():
    assert is_verifiable_group("bond_pure|unknown") is False


def test_index_group_with_family_is_verifiable():
    assert is_verifiable_group("etf_linked|broad|沪深300") is True


def test_index_group_with_unknown_family_not_verifiable():
    assert is_verifiable_group("etf_linked|unknown|unknown") is False


def test_group_below_two_is_excluded():
    r = group_usability("etf_linked|broad|沪深300", 1)
    assert r["status"] == PEER_EXCLUDED


def test_group_below_five_is_descriptive_only():
    r = group_usability("etf_linked|broad|沪深300", 3)
    assert r["status"] == PEER_DESCRIPTIVE_ONLY
    assert r["verifiable"] is True


def test_group_five_plus_is_comparable():
    r = group_usability("etf_linked|broad|沪深300", 5)
    assert r["status"] == PEER_COMPARABLE


def test_unverifiable_group_never_comparable():
    """数量再多，基准族 unknown 也不能算可比较。"""
    r = group_usability("bond_pure|unknown", 50)
    assert r["status"] == PEER_DESCRIPTIVE_ONLY
    assert r["verifiable"] is False


def test_group_isolation_different_index_not_merged():
    assert is_verifiable_group("etf_linked|broad|沪深300") is True
    assert is_verifiable_group("etf_linked|broad|中证500") is True
    # 两个不同的组键，绝不相同
    assert ("etf_linked|broad|沪深300" != "etf_linked|broad|中证500")


# ================================================================ 赎回费阶梯
def test_redemption_fee_at_hits_tier():
    tiers = [
        {"holding_days_min": 0, "holding_days_max": 7, "rate": 0.015,
         "holding_days_min_inclusive": 1, "holding_days_max_inclusive": 0},
        {"holding_days_min": 7, "holding_days_max": 365, "rate": 0.005,
         "holding_days_min_inclusive": 1, "holding_days_max_inclusive": 0},
        {"holding_days_min": 365, "holding_days_max": None, "rate": 0.0,
         "holding_days_min_inclusive": 1, "holding_days_max_inclusive": None},
    ]
    assert redemption_fee_at(tiers, 3)["value"] == 0.015
    assert redemption_fee_at(tiers, 30)["value"] == 0.005
    assert redemption_fee_at(tiers, 400)["value"] == 0.0


def test_redemption_fee_missing_tiers_is_unknown():
    r = redemption_fee_at(None, 30)
    assert r["status"] == "unknown"
    assert r["value"] is None
    assert "无赎回费阶梯" in r["reason"]


def test_redemption_fee_no_matching_tier_is_unknown():
    tiers = [{"holding_days_min": 0, "holding_days_max": 7, "rate": 0.015,
              "holding_days_min_inclusive": 1, "holding_days_max_inclusive": 1}]
    r = redemption_fee_at(tiers, 100)
    assert r["status"] == "unknown"
    assert "不插值" in r["reason"]


def test_redemption_fee_overlapping_conflict_is_unknown():
    """重叠且费率不同 → 拒绝判定，不猜。"""
    tiers = [
        {"holding_days_min": 0, "holding_days_max": 100, "rate": 0.01,
         "holding_days_min_inclusive": 1, "holding_days_max_inclusive": 1},
        {"holding_days_min": 0, "holding_days_max": 100, "rate": 0.02,
         "holding_days_min_inclusive": 1, "holding_days_max_inclusive": 1},
    ]
    r = redemption_fee_at(tiers, 50)
    assert r["status"] == "unknown"
    assert "重叠" in r["reason"]


# ================================================================ 成本分析
def _make_fee_db(tmp_path, *, with_sales_service=True):
    """构造最小临时库，含一个本体两个份额与费率。"""
    from app.database.db import init_db
    from app.fund.migration import ensure_fund_schema
    from app.fund.migration_3b4_2 import ensure_3b4_2_schema
    db = tmp_path / "fee_probe.db"
    init_db(db_path=db)
    ensure_fund_schema(db)
    ensure_3b4_2_schema(db)
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO fund_master (fund_id, fund_code_primary, fund_name, "
        "lifecycle_status, source, ingested_at) VALUES "
        "(1, 'T00001', '测试基金', 'active', 'test', '2026-01-01')")
    for sid, code, typ in ((1, "T00001", "A"), (2, "T00002", "C")):
        conn.execute(
            "INSERT INTO fund_share_classes (share_class_id, fund_id, "
            "share_class_code, share_class_name, share_class_type, "
            "is_primary, source, ingested_at) VALUES "
            "(?, 1, ?, ?, ?, ?, 'test', '2026-01-01')",
            (sid, code, code, typ, 1 if sid == 1 else 0))
    # 赎回费阶梯
    for sid in (1, 2):
        conn.execute(
            "INSERT INTO fund_fee_rules (share_class_id, fee_type, tier_order, "
            "rate, holding_days_min, holding_days_max, "
            "holding_days_min_inclusive, holding_days_max_inclusive, "
            "source, evidence_level, ingested_at) VALUES "
            "(?, 'redemption', 0, 0.015, 0, 7, 1, 0, 'test', 'C', '2026-01-01')",
            (sid,))
        conn.execute(
            "INSERT INTO fund_fee_rules (share_class_id, fee_type, tier_order, "
            "rate, holding_days_min, holding_days_max, "
            "holding_days_min_inclusive, holding_days_max_inclusive, "
            "source, evidence_level, ingested_at) VALUES "
            "(?, 'redemption', 1, 0.0, 7, NULL, 1, NULL, 'test', 'C', '2026-01-01')",
            (sid,))
        if with_sales_service:
            conn.execute(
                "INSERT INTO fund_fee_rules (share_class_id, fee_type, tier_order, "
                "rate, source, evidence_level, ingested_at) VALUES "
                "(?, 'sales_service', 0, 0.004, 'test', 'C', '2026-01-01')",
                (sid,))
    conn.commit()
    conn.close()
    return db


def test_share_cost_not_available_without_sales_service(tmp_path):
    """销售服务费缺失时，未知费率不得当 0 → 不给结论。"""
    db = _make_fee_db(tmp_path, with_sales_service=False)
    r = analyze_share_cost(db, fund_id=1,
                           shares=[{"share_code": "T00001", "share_name": "A",
                                    "share_class_type": "A", "is_primary": 1},
                                   {"share_code": "T00002", "share_name": "C",
                                    "share_class_type": "C", "is_primary": 0}])
    assert r["status"] == COST_NOT_AVAILABLE
    assert r["computable_horizons"] == []
    assert r["conclusion"] is None


def test_share_cost_computable_when_all_fees_present(tmp_path):
    db = _make_fee_db(tmp_path, with_sales_service=True)
    r = analyze_share_cost(db, fund_id=1,
                           shares=[{"share_code": "T00001", "share_name": "A",
                                    "share_class_type": "A", "is_primary": 1},
                                   {"share_code": "T00002", "share_name": "C",
                                    "share_class_type": "C", "is_primary": 0}])
    assert r["status"] == COST_COMPUTABLE
    assert len(r["computable_horizons"]) > 0
    # 但依然不给购买建议
    assert r["conclusion"] is None
    assert r["cannot_conclude_reasons"]


def test_share_cost_never_outputs_buy_advice(tmp_path):
    db = _make_fee_db(tmp_path, with_sales_service=True)
    r = analyze_share_cost(db, fund_id=1,
                           shares=[{"share_code": "T00001", "share_name": "A",
                                    "share_class_type": "A", "is_primary": 1}])
    assert r["conclusion"] is None
    assert "支付宝" in r["conclusion_note"]


def test_alipay_fee_always_unknown(tmp_path):
    db = _make_fee_db(tmp_path)
    r = analyze_share_cost(db, fund_id=1,
                           shares=[{"share_code": "T00001", "share_name": "A",
                                    "share_class_type": "A", "is_primary": 1}])
    assert r["shares"][0]["alipay_fee"]["status"] == "unknown"


def test_empty_shares_returns_no_shares():
    r = analyze_share_cost(None, fund_id=1, shares=[])
    assert r["status"] == "no_shares"
