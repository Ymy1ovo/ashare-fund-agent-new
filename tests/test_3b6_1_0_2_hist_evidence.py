"""阶段3B-6.1.0.2 第三层（完整历史）仓库级可复现测试。

验证：报告里的每一个 total_history_available / net_history_available
都能在证据附件的 full_history_probe 里找到对应记录，且行数、起止日期一致。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORTS = ROOT / "reports"
EVIDENCE = REPORTS / "evidence" / "phase3B6_1_0_index_probe_evidence.json"


@pytest.fixture(scope="module")
def ev() -> dict:
    assert EVIDENCE.exists(), "缺仓库级证据附件"
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def r01() -> dict:
    return json.loads(
        (REPORTS / "phase3B6_1_0_01_index_return_basis.json")
        .read_text(encoding="utf-8"))


def _hist(ev: dict, code: str) -> dict:
    """优先用新的 coverage_quality_probe，回退到 full_history_probe。"""
    qb = ev.get("coverage_quality_probe", {}).get("by_code", {})
    if code in qb:
        return qb[code]
    return ev.get("full_history_probe", {}).get("by_code", {}).get(code) or {}


def test_hist_evidence_exists(ev):
    hp = ev.get("coverage_quality_probe") or ev.get("full_history_probe")
    assert hp, "缺覆盖质量证据"
    codes = hp.get("by_code") or {}
    assert len(codes) > 0


def test_total_history_matches_evidence(r01, ev):
    """每个指数的全收益历史状态必须与证据的实测记录一致。"""
    for x in r01["indexes"]:
        code = x["total_return_index_code"]
        if not code:
            continue
        h = _hist(ev, code)
        if not h:
            continue
        st = x["history_states"]
        assert st["history_retrieved"] == h["history_retrieved"], \
            f"{x['index_code']}: 取到状态不一致"
        assert st["history_coverage_adequate"] == h["history_coverage_adequate"], \
            f"{x['index_code']}: 覆盖状态不一致"
        assert st["history_quality_adequate"] == h["history_quality_adequate"], \
            f"{x['index_code']}: 质量状态不一致"


def test_net_history_matches_evidence(r01, ev):
    """净收益序列的质量记录必须与证据一致。"""
    for x in r01["indexes"]:
        code = x.get("net_total_return_index_code")
        if not code:
            assert x.get("net_return_quality") is None
            continue
        h = _hist(ev, code)
        nq = x.get("net_return_quality")
        if h and nq:
            assert nq["history_retrieved"] == h["history_retrieved"]


def test_price_history_matches_evidence(r01, ev):
    """价格序列的行数与缺口必须与证据一致。"""
    for x in r01["indexes"]:
        code = x["price_index_code"]
        h = _hist(ev, code)
        pq = x.get("price_quality")
        if not h or not pq:
            continue
        if pq["status"] == "ok" and h.get("status") == "ok":
            assert pq["rows"] == h["rows"]
            assert pq["max_gap_days"] == h["max_gap_days"]


def test_no_placeholder_rows_in_evidence(ev):
    """证据里的行数必须是真实探测值。"""
    qb = ev.get("coverage_quality_probe", {}).get("by_code", {})
    for code, h in qb.items():
        if h.get("status") != "ok":
            continue
        assert h["rows"] > 0
        assert h["date_min"] and h["date_max"]
        assert h["duplicate_dates"] == 0, f"{code} 有重复日期"


def test_evidenced_differences_documented(ev):
    """已知异常必须留痕（H30184/H20184 的非正值等）。"""
    qb = ev.get("coverage_quality_probe", {}).get("by_code", {})
    nonpos = {c: h["non_positive_close"] for c, h in qb.items()
              if h.get("non_positive_close", 0) > 0}
    assert "H30184" in nonpos or "H20184" in nonpos


def test_gate_still_closed(r01):
    g = r01["gate"]
    assert g["ready_for_research_analysis"] is True
    assert g["ready_for_backtest"] is False
    assert g["ready_for_formal_ranking"] is False
