"""阶段3B-1.1 研究统计去重专项测试。

只测研究脚本的统计函数，不碰数据库、不改任何正式记录。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research_3b1_baseline import (  # noqa: E402
    analyze_param_ranking, analyze_walkforward, count_layers,
    dedupe_by_config, grade_evidence, oos_fingerprint_groups,
)

JSON_PATH = ROOT / "reports" / "phase3B1_strategy_effectiveness_baseline.json"
MD_PATH = ROOT / "reports" / "phase3B1_strategy_effectiveness_baseline.md"


@pytest.fixture(scope="module")
def payload() -> dict:
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def included(payload: dict) -> list[dict]:
    return [u for u in payload["units"] if u.get("included")]


# ---------------------------------------------------------------- 去重本身
def test_dedupe_collapses_g1_g4(included):
    uniq, merged = dedupe_by_config(included)
    tags = [u["tag"] for u in uniq]
    assert len(uniq) == len(included) - 1
    assert "G1" in tags and "G4" not in tags
    assert [m["tag"] for m in merged] == ["G4"]
    assert merged[0]["merged_into"] == "G1"


def test_dedupe_keeps_g9_and_p0b(included):
    """G9 哈希不同、P0b 哈希不同，都不允许被合并掉。"""
    tags = [u["tag"] for u in dedupe_by_config(included)[0]]
    assert "G9" in tags
    assert "P0b" in tags
    assert len(tags) == 8


def test_dedupe_does_not_mutate_input(included):
    before = [u["tag"] for u in included]
    dedupe_by_config(included)
    assert [u["tag"] for u in included] == before


# ---------------------------------------------------------------- 三层计数
def test_count_layers_three_numbers(payload, included):
    layers = count_layers(included)
    assert layers["included_records"] == 9
    assert layers["unique_config_input_pairs"] == 8
    assert layers["unique_oos_result_fingerprints"] == 6
    # 与 JSON 里落盘的值一致
    assert payload["statistical_layers"]["included_records"] == 9
    assert payload["statistical_layers"]["unique_config_input_pairs"] == 8
    assert payload["statistical_layers"]["unique_oos_result_fingerprints"] == 6


def test_independent_samples_is_not_estimable(payload, included):
    """禁止造一个独立样本数字出来。"""
    layers = count_layers(included)
    assert layers["statistically_independent_samples"] == "not_estimable"
    assert payload["statistical_layers"]["statistically_independent_samples"] == "not_estimable"
    assert payload["evidence_grading"]["statistically_independent_samples"] == "not_estimable"
    assert layers["not_estimable_reason"]


def test_oos_fingerprint_groups(payload, included):
    groups = oos_fingerprint_groups(included)
    assert len(groups) == 6
    sizes = sorted(len(g["tags"]) for g in groups)
    assert sizes == [1, 1, 1, 1, 2, 3]


# ---------------------------------------------------------------- 参数排名
def test_param_ranking_uses_unique_configs(payload):
    rows = payload["param_ranking"]["rows"]
    assert len(rows) == 8
    assert "G4" not in [r["tag"] for r in rows]


def test_param_ranking_summary_numbers(payload):
    s = payload["param_ranking"]["summary"]
    assert s["unit_count"] == 8
    assert s["is_best_is_ma250_count"] == 6
    assert s["is_best_on_boundary_count"] == 7
    assert s["is_oos_best_match_count"] == 2
    assert s["oos_best_param_distribution"] == {"30": 5, "60": 2, "120": 1}
    assert s["oos_best_is_ma250_count"] == 0


def test_param_ranking_no_nine_basis(payload):
    """任何 9 为分母的比值都不应出现在汇总里。"""
    s = payload["param_ranking"]["summary"]
    for key in ("is_best_on_boundary_ratio", "is_oos_best_match_ratio",
                "is_best_is_ma250_ratio"):
        val = s[key]
        assert val is not None
        assert abs(val * 9 - round(val * 9)) > 1e-9 or abs(val * 8 - round(val * 8)) < 1e-9


# ---------------------------------------------------------------- Walk-Forward
def test_walkforward_uses_unique_configs(payload):
    rows = payload["walkforward"]["rows"]
    assert len(rows) == 8
    assert "G4" not in [r["tag"] for r in rows]
    assert payload["walkforward"]["summary"]["unit_count"] == 8


def test_walkforward_concentration(payload):
    s = payload["walkforward"]["summary"]
    assert s["concentration_configs"] == 6
    assert s["all_windows_positive_configs"] == 0


def test_walkforward_distinguishes_window_schedules(payload):
    """7 组共享同一窗口排布，只有 G7 不同 —— 重复窗口不算独立验证。"""
    s = payload["walkforward"]["summary"]
    assert s["distinct_window_schedule_groups"] == 2
    groups = {g["windows"]: g for g in s["window_schedule_groups"]}
    assert set(groups) == {8, 7}
    assert groups[8]["tags"] == ["G1", "G2", "G3", "G5", "G8", "G9", "P0b"]
    assert groups[7]["tags"] == ["G7"]


# ---------------------------------------------------------------- 超额中位数
def test_excess_median_positive(payload):
    g = payload["evidence_grading"]
    assert g["beat_buyhold_total"] == 8
    assert g["beat_buyhold_count"] == 4
    assert g["lose_buyhold_count"] == 4
    # 修正后的中位数必须是正的约 +0.37%
    assert g["excess_median"] == pytest.approx(0.0037291601, abs=1e-9)
    assert g["excess_median"] > 0


def test_excess_median_matches_manual_median(payload):
    import statistics
    vals = sorted(e["excess"] for e in payload["evidence_grading"]["excess_vs_buyhold"])
    assert payload["evidence_grading"]["excess_median"] == pytest.approx(
        statistics.median(vals), abs=1e-9)


def test_excess_range(payload):
    g = payload["evidence_grading"]
    assert g["excess_min"] == pytest.approx(-0.0229539606, abs=1e-9)
    assert g["excess_max"] == pytest.approx(0.0541557573, abs=1e-9)


def test_excess_basis_is_unique_configs(payload):
    g = payload["evidence_grading"]
    assert g["unique_config_input_pairs"] == 8
    assert g["included_records"] == 9
    assert len(g["excess_vs_buyhold"]) == 8


# ---------------------------------------------------------------- 文档一致性
def _body_only() -> str:
    """修正说明章节会刻意引用旧数字，正文检查必须排除它。"""
    md = MD_PATH.read_text(encoding="utf-8")
    marker = "## 16. 修正说明"
    return md.split(marker)[0] if marker in md else md


def test_doc_json_consistency(payload):
    """Markdown 报告里的关键数字必须与 JSON 一致。"""
    md = _body_only()
    s = payload["param_ranking"]["summary"]
    g = payload["evidence_grading"]
    layers = payload["statistical_layers"]

    assert f"{s['is_best_is_ma250_count']}/{s['unit_count']}" in md
    assert f"{s['is_best_on_boundary_count']}/{s['unit_count']}" in md
    assert f"{s['is_oos_best_match_count']}/{s['unit_count']}" in md
    assert f"{g['beat_buyhold_count']}/{g['beat_buyhold_total']}" in md
    assert f"{layers['unique_config_input_pairs']}" in md
    assert "not_estimable" in md
    # 禁止再出现旧的独立结果集表述
    assert "6 个真正独立的结果集" not in md
    assert "6 份独立证据" not in md


def test_doc_does_not_claim_nine_basis(payload):
    """正文（§16 修正说明之外）不得再出现以 9 为分母的旧基数。"""
    md = _body_only()
    for stale in ("7/9", "8/9", "2/9", "4/9", "6/9"):
        assert stale not in md, f"报告正文里仍有旧基数 {stale}"


def test_md_has_correction_section():
    md = MD_PATH.read_text(encoding="utf-8")
    assert "## 16. 修正说明" in md
    assert "旧值（错误）" in md
    assert "新值（修正）" in md


def test_figures_are_unique_config(payload):
    """图表必须基于 8 组唯一配置，不得画 9 条。"""
    fig_dir = ROOT / "reports" / "figures"
    # 只检查 3B-1 自己的图；3B-2 的 fig3b2_*.png 由图目录共存，不算在本测试范围
    names = sorted(p.name for p in fig_dir.glob("fig*.png")
                   if not p.name.startswith("fig3b2_"))
    assert len(names) == 6
    assert names == [
        "fig1_is_oos_param_return.png",
        "fig2_param_ranking_heatmap.png",
        "fig3_ma250_boundary.png",
        "fig4_strategy_vs_benchmark.png",
        "fig5_walkforward_windows.png",
        "fig6_regime_performance.png",
    ]
    for p in fig_dir.glob("fig*.png"):
        if p.name.startswith("fig3b2_"):
            continue
        assert p.stat().st_size > 5000


def test_analyze_functions_are_reusable(included):
    """函数必须能在内存里重算出一致结果，说明去重逻辑是内在的。"""
    ranking = analyze_param_ranking(included)
    assert ranking["summary"]["unit_count"] == 8
    wf = analyze_walkforward(included)
    assert wf["summary"]["unit_count"] == 8
    grade = grade_evidence(included, ranking, wf, {})
    assert grade["unique_config_input_pairs"] == 8
    assert grade["statistically_independent_samples"] == "not_estimable"
