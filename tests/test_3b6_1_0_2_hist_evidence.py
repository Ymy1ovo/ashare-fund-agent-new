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
    return ev["full_history_probe"]["by_code"].get(code) or {}


def test_hist_evidence_exists(ev):
    hp = ev.get("full_history_probe")
    assert hp, "缺 full_history_probe"
    assert hp["codes_probed"] > 0
    assert hp["request_range"] == ["20040101", "20261231"]


def test_total_history_matches_evidence(r01, ev):
    """每个指数的全收益历史状态必须与证据附件的实测记录一致。"""
    for x in r01["indexes"]:
        code = x["total_return_index_code"]
        if not code:
            assert x["total_history_available"] is False
            continue
        h = _hist(ev, code)
        if x["total_history_available"]:
            assert h.get("status") == "ok", \
                f"{x['index_code']} 声称历史可用，但证据里 {code} 无数据"
            assert x["total_row_count"] == h["rows"], \
                f"{x['index_code']} 行数不一致：报告 {x['total_row_count']} vs 证据 {h['rows']}"
            assert x["total_history_start"] == h["date_min"]
            assert x["total_history_end"] == h["date_max"]
        else:
            assert h.get("status") != "ok", \
                f"{x['index_code']} 声称历史不可用，但证据里 {code} 有数据"


def test_net_history_matches_evidence(r01, ev):
    """净收益历史状态必须与证据一致。"""
    for x in r01["indexes"]:
        code = x["net_total_return_index_code"]
        if not code:
            assert x["net_history_available"] is False
            continue
        h = _hist(ev, code)
        if x["net_history_available"]:
            assert h.get("status") == "ok"
            assert x["net_row_count"] == h["rows"]
        else:
            assert h.get("status") != "ok"


def test_price_history_matches_evidence(r01, ev):
    """价格历史行数必须与证据一致。"""
    for x in r01["indexes"]:
        code = x["price_index_code"]
        h = _hist(ev, code)
        if x["history_available"]:
            assert h.get("status") == "ok", f"{code} 价格历史无证据"
            assert x["row_count"] == h["rows"]
            assert x["max_gap_days"] == h["max_gap_days"]


def test_no_placeholder_rows_in_evidence(ev):
    """证据里的行数必须是真实探测值，不能是占位符。"""
    for code, h in ev["full_history_probe"]["by_code"].items():
        if h.get("status") != "ok":
            continue
        assert h["rows"] > 0
        assert h["date_min"] and h["date_max"]
        assert h["duplicate_dates"] == 0, f"{code} 有重复日期"
        assert h["max_gap_days"] >= 0


def test_evidenced_differences_documented(ev):
    """已知异常必须在证据里留痕（H30184/H20184 的非正值等）。"""
    by = ev["full_history_probe"]["by_code"]
    nonpos = {c: h["non_positive_close"] for c, h in by.items()
              if h.get("status") == "ok" and h.get("non_positive_close", 0) > 0}
    # 至少 H30184 / H20184 各 1 个（已记录的历史缺陷）
    assert "H30184" in nonpos or "H20184" in nonpos


def test_gate_still_closed(r01):
    g = r01["gate"]
    assert g["ready_for_research_analysis"] is True
    assert g["ready_for_backtest"] is False
    assert g["ready_for_formal_ranking"] is False
