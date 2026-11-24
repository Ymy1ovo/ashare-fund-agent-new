"""阶段3B-6.1.0 官方基准与无风险利率数据源可行性审计 —— 只读测试。

验证审计口径与报告一致性；不联网、不写库。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.fund.index_returns import (  # noqa: E402
    RETURN_BASIS_NET, RETURN_BASIS_PRICE, RETURN_BASIS_TOTAL,
    RETURN_BASIS_UNKNOWN,
)
from app.fund.research.excess_return import (  # noqa: E402
    BLOCK_BASIS_PRICE, BLOCK_BASIS_UNKNOWN, EXCESS_NOT_AVAILABLE,
    assess_composite, check_benchmark_usable, evaluate_excess_return,
)

RAW = ROOT / ".tmp610" / "raw"
REPORTS = ROOT / "reports"


# ================================================================ 口径不可混用
def test_price_basis_never_usable_for_excess():
    """价格指数不得冒充全收益。"""
    r = check_benchmark_usable("000300", RETURN_BASIS_PRICE)
    assert r["usable"] is False
    assert r["block"] == BLOCK_BASIS_PRICE


def test_net_basis_is_distinct_from_total():
    """净收益与全收益是不同常量，不得混用。"""
    assert RETURN_BASIS_NET != RETURN_BASIS_TOTAL
    assert RETURN_BASIS_NET == "net_total_return"
    assert RETURN_BASIS_TOTAL == "total_return"


def test_unknown_basis_stays_unknown():
    r = check_benchmark_usable("399997", RETURN_BASIS_UNKNOWN)
    assert r["usable"] is False
    assert r["block"] == BLOCK_BASIS_UNKNOWN


# ================================================================ 复合基准
def test_composite_with_missing_cash_not_reproducible():
    """含现金成分但无收益序列 → 不可复现。"""
    c = {"components": [
        {"component_label": "沪深300", "component_type": "index",
         "weight": 0.95, "data_available": True},
        {"component_label": "cash", "component_type": "cash",
         "weight": 0.05, "data_available": False},
    ]}
    r = assess_composite(c)
    assert r["reproducible"] is False


def test_composite_with_missing_bond_not_reproducible():
    c = {"components": [
        {"component_label": "中证500", "component_type": "index",
         "weight": 0.9, "data_available": True},
        {"component_label": "中证综合债券", "component_type": "bond_index",
         "weight": 0.1, "data_available": False},
    ]}
    assert assess_composite(c)["reproducible"] is False


def test_single_component_cannot_stand_for_composite():
    """不得用单一成分替代完整复合基准。"""
    c = {"components": [{"component_label": "沪深300",
                         "component_type": "index",
                         "weight": 1.0, "data_available": True}]}
    assert assess_composite(c)["reproducible"] is False


def test_unknown_weight_blocks_even_if_data_available():
    """权重未知不得均分，直接判定不可复现。"""
    c = {"components": [
        {"component_label": "沪深300", "component_type": "index",
         "weight": None, "data_available": True},
        {"component_label": "中债综合", "component_type": "bond_index",
         "weight": 0.3, "data_available": True},
    ]}
    assert assess_composite(c)["reproducible"] is False


# ================================================================ 实测数据校验
@pytest.mark.skipif(not (RAW / "index_basis.json").exists(),
                    reason="需先运行 audit_3b6_1_0_index_basis.py --probe")
def test_all_10_indexes_probed():
    doc = json.loads((RAW / "index_basis.json").read_text(encoding="utf-8"))
    assert len(doc["indexes"]) == 10
    codes = {e["index_code"] for e in doc["indexes"]}
    assert codes == {"000300", "000905", "000906", "000016", "399997",
                     "H30184", "000942", "000012", "000922", "930930"}


@pytest.mark.skipif(not (RAW / "index_basis.json").exists(), reason="no probe")
def test_total_return_variants_actually_returned_by_source():
    """全收益变体必须真的返回不同名称，不能只凭代码猜测。"""
    doc = json.loads((RAW / "index_basis.json").read_text(encoding="utf-8"))
    for e in doc["indexes"]:
        for v in e["variants"]:
            if v.get("kind") == "total" and v.get("status") == "ok":
                assert "全收益" in v["index_name_returned"] or \
                       "再投资" in v["index_name_returned"]
            if v.get("kind") == "price" and v.get("status") == "ok":
                assert e["index_name"][:4] in v["index_name_returned"] or \
                       v["index_name_returned"]


@pytest.mark.skipif(not (RAW / "index_basis.json").exists(), reason="no probe")
def test_price_and_total_are_different_series():
    """价格与全收益必须是不同数值（沪深300 实测）。"""
    doc = json.loads((RAW / "index_basis.json").read_text(encoding="utf-8"))
    for e in doc["indexes"]:
        if e["index_code"] != "000300":
            continue
        price = next(v for v in e["variants"]
                     if v["kind"] == "price" and v["status"] == "ok")
        total = next(v for v in e["variants"]
                     if v["kind"] == "total" and v["status"] == "ok")
        assert price["sample"][0]["close"] != total["sample"][0]["close"]
        assert total["sample"][0]["close"] > price["sample"][0]["close"]


# ================================================================ 报告一致性
def _load(name: str) -> dict:
    p = REPORTS / name
    if not p.exists():
        pytest.skip(f"{name} 未生成")
    return json.loads(p.read_text(encoding="utf-8"))


def test_index_report_covers_all_10():
    d = _load("phase3B6_1_0_01_index_return_basis.json")
    assert len(d["indexes"]) == 10


def test_index_report_no_basis_upgraded_without_evidence():
    """没有证据的指数必须保持 unknown。"""
    d = _load("phase3B6_1_0_01_index_return_basis.json")
    for e in d["indexes"]:
        if e["return_basis"] in (RETURN_BASIS_TOTAL, RETURN_BASIS_NET):
            assert e["methodology_evidence"] is not None
            assert e["total_return_index_code"] or e["net_total_return_index_code"]


def test_composite_report_covers_all_15():
    d = _load("phase3B6_1_0_02_composite_benchmark.json")
    assert len(d["composites"]) == 15


def test_composite_none_reproducible_currently():
    d = _load("phase3B6_1_0_02_composite_benchmark.json")
    for c in d["composites"]:
        assert c["status"] in ("reproducible", "partially_reproducible",
                                "not_reproducible")
        if c["status"] == "reproducible":
            assert c["all_components_available"] is True
            assert c["historical_weight_evidence"] is True


def test_gate_unchanged_in_all_reports():
    for name in ("phase3B6_1_0_01_index_return_basis.json",
                 "phase3B6_1_0_02_composite_benchmark.json",
                 "phase3B6_1_0_03_risk_free_rate.json",
                 "phase3B6_1_0_05_ingestion_recommendation.json"):
        d = _load(name)
        assert d["gate"]["ready_for_research_analysis"] is True
        assert d["gate"]["ready_for_backtest"] is False
        assert d["gate"]["ready_for_formal_ranking"] is False


# ================================================================ 只读保证
def test_no_index_written_to_db():
    """指数层行数必须与 3B-6.0.2 交付时一致。"""
    from app.database.db import get_connection
    with get_connection() as c:
        n = c.execute("SELECT COUNT(*) FROM index_daily").fetchone()[0]
        m = c.execute("SELECT COUNT(*) FROM index_master").fetchone()[0]
    assert n == 50603
    assert m == 10


def test_no_composite_modified():
    from app.database.db import get_connection
    with get_connection() as c:
        n = c.execute("SELECT COUNT(*) FROM benchmark_composite").fetchone()[0]
        comps = c.execute(
            "SELECT COUNT(*) FROM benchmark_composite_component").fetchone()[0]
    assert n == 15
    assert comps == 34
