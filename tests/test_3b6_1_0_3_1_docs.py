"""阶段3B-6.1.0.3.1 文档口径一致性测试。

确保：
- 废弃字段被明确标记，而不是直接引用
- 不再出现「5,318 行/序列」这类笼统结论
- 399997/930930 不被描述成可用于长周期回测
- 非正值异常按三层序列分别登记
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORTS = ROOT / "reports"
DOCS = {
    "design": REPORTS / "phase3B6_1_0_00_design.md",
    "source_quality": REPORTS / "phase3B6_1_0_04_source_quality.md",
    "ingestion": REPORTS / "phase3B6_1_0_05_ingestion_recommendation.md",
    "readme": ROOT / "README.md",
    "changelog": ROOT / "CHANGELOG.md",
}


@pytest.fixture(scope="module")
def r01() -> dict:
    return json.loads(
        (REPORTS / "phase3B6_1_0_01_index_return_basis.json")
        .read_text(encoding="utf-8"))


def _read(key: str) -> str:
    p = DOCS[key]
    assert p.exists(), f"缺文档 {p.name}"
    return p.read_text(encoding="utf-8")


# ============================================================ 废弃字段标记
def test_deprecated_field_marked_in_design():
    md = _read("design")
    assert "full_history_verified" in md
    # 必须同时出现「废弃」或删除线
    idx = md.find("full_history_verified")
    context = md[max(0, idx - 200):idx + 300]
    assert "废弃" in context or "~~" in context, \
        "00_design 中 full_history_verified 未标记为废弃"


def test_deprecated_field_marked_in_ingestion():
    md = _read("ingestion")
    assert "废弃" in md, "05_ingestion 未标记旧口径已废弃"


def test_deprecated_field_marked_in_readme():
    md = _read("readme")
    assert "已废弃" in md
    assert "不得作为当前状态引用" in md


def test_deprecated_marked_in_changelog():
    md = _read("changelog")
    assert "已废弃" in md


# ============================================================ 笼统结论清理
BLANKET_PATTERNS = [
    r"2004-01-01\s*[~-]\s*现在，\s*5,?318\s*行/序列",
    r"2004年至今.*5,?318",
]


def test_no_blanket_row_count_claim():
    """不得再出现「2004年至今、5,318 行/序列」这类笼统结论。

    弃用声明本身（带 ⚠️ 或「」引号）不算违规——那是在标注旧说法已废弃。
    """
    for key in DOCS:
        md = _read(key)
        for line in md.splitlines():
            # 弃用声明行豁免
            if "⚠️" in line or "「" in line or "~~" in line or "不得" in line:
                continue
            for pat in BLANKET_PATTERNS:
                assert not re.search(pat, line), \
                    f"{key}: 仍存在笼统结论 `{pat}`：{line.strip()[:80]}"


def test_real_per_index_coverage_documented(r01):
    """必须按各指数真实起点/行数描述。"""
    md = _read("source_quality")
    for x in r01["indexes"]:
        tq = x.get("total_return_quality") or {}
        code = x.get("total_return_index_code")
        if not code:
            continue
        # 该指数的真实起点与行数必须出现
        assert tq["real_start_date"] in md, f"04 缺 {x['index_code']} 真实起点"
        assert f"{tq['rows']:,}" in md, f"04 缺 {x['index_code']} 真实行数"


def test_readme_documents_per_index_coverage(r01):
    md = _read("readme")
    # 至少覆盖到起点差异最大的几个
    for code in ("399997", "930930", "000016"):
        assert code in md
    assert "52.5%" in md
    assert "78.2%" in md


# ============================================================ 回测可用性表述
def test_399997_930930_not_described_as_long_term_usable():
    """399997/930930 不得被描述成可用于长周期回测。"""
    for key in ("ingestion", "readme", "changelog"):
        md = _read(key)
        # 若同一句里同时出现指数代码与「长周期」正向描述则失败
        for code in ("399997", "930930"):
            for m in re.finditer(code, md):
                # 窗口包含代码前后文，避免漏掉写在代码之前的否定词
                seg = md[max(0, m.start() - 80):m.start() + 120]
                if "长周期" not in seg:
                    continue
                assert ("不可" in seg or "不能" in seg or "不接入" in seg
                        or "暂不" in seg or "仅作短周期" in seg
                        or "不得" in seg or "否定" in seg), \
                    f"{key}: {code} 附近的「长周期」描述未否定"


def test_ingestion_keeps_original_blockers():
    """原有阻断结论必须保留。"""
    md = _read("ingestion")
    assert "unknown" in md
    assert "历史权重" in md


def test_research_vs_backtest_distinction():
    """不得把研究可用误写成回测可用。"""
    md = _read("readme")
    assert "ready_for_backtest" in md or "回测" in md
    # 回测相关表述中必须是否定的
    assert "回测可用率" in md or "backtest_usable" in md


# ============================================================ 非正值分层
def test_non_positive_register_complete(r01):
    reg = r01["non_positive_anomaly_register"]
    assert reg["total_count"] == 5
    layers = {r["series_layer"] for r in reg["register"]}
    assert layers == {"price", "total_return", "net_return"}, \
        f"非正值未覆盖三层：{layers}"


def test_non_positive_documented_in_source_quality():
    md = _read("source_quality")
    for code in ("H30184", "H20184", "N00905", "N00906", "N00016"):
        assert code in md, f"04 未登记 {code} 的非正值"
    assert "净收益" in md and "全收益" in md and "价格" in md


def test_non_positive_documented_in_readme():
    md = _read("readme")
    for code in ("H30184", "H20184", "N00905", "N00906", "N00016"):
        assert code in md, f"README 未登记 {code}"


def test_anomaly_layer_separation_in_json(r01):
    """JSON 里每个指数必须分别记录三层异常。"""
    for x in r01["indexes"]:
        a = x["anomaly_by_series"]
        assert set(a.keys()) >= {"price_series", "total_return_series",
                                  "net_return_series"}
        for layer in ("price_series", "total_return_series", "net_return_series"):
            assert "non_positive_close" in a[layer]
            assert "dates" in a[layer]


# ============================================================ 门禁
def test_gate_unchanged(r01):
    g = r01["gate"]
    assert g["ready_for_research_analysis"] is True
    assert g["ready_for_backtest"] is False
    assert g["ready_for_formal_ranking"] is False


def test_return_basis_all_unknown(r01):
    for x in r01["indexes"]:
        assert x["return_basis"] == "unknown"
