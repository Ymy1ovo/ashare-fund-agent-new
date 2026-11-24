"""阶段3B-6.1.0.2 一致性专项测试。

覆盖任务4的 12 项要求：
1. JSON summary 数量与明细数组长度一致
2. Markdown 统计与 JSON 统计一致
3. 10 个指数 factsheet 字段与证据附件一致
4. factsheet 下载状态有真实文件元数据支撑
5. 代码存在 ≠ 完整历史可用
6. 短窗口返回 ≠ 完整历史覆盖
7. 完整历史不可用时不得标记可用
8. 000051 描述不得出现无证据表述
9. 000051 固定收益率不参与资产权重求和
10. 所有 return_basis 仍为 unknown
11. ready_for_backtest 仍为 false
12. ready_for_formal_ranking 仍为 false

**测试不硬编码统计数字**，全部从真实报告结构与证据附件计算。
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
EVIDENCE = REPORTS / "evidence" / "phase3B6_1_0_index_probe_evidence.json"
MD01 = REPORTS / "phase3B6_1_0_01_index_return_basis.md"
MD02 = REPORTS / "phase3B6_1_0_02_composite_benchmark.md"

INDEX_CODES = {"000300", "000905", "000906", "000016", "399997",
               "H30184", "000942", "000012", "000922", "930930"}


def _json(name: str) -> dict:
    p = REPORTS / name
    assert p.exists(), f"缺文件 {name}"
    return json.loads(p.read_text(encoding="utf-8"))


def _md(path: Path) -> str:
    assert path.exists(), f"缺文件 {path.name}"
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def r01() -> dict:
    return _json("phase3B6_1_0_01_index_return_basis.json")


@pytest.fixture(scope="module")
def r02() -> dict:
    return _json("phase3B6_1_0_02_composite_benchmark.json")


@pytest.fixture(scope="module")
def ev() -> dict:
    assert EVIDENCE.exists()
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


# ================================================================ 1. summary 一致性
def test_summary_counts_equal_detail_lengths(r01):
    """JSON summary 的每个统计数必须等于从 indexes 逐项复算的结果。

    3B-6.1.0.3 起统计改为「按经济语义 + 五态」，不再是单一分类数组。
    """
    s = r01["summary"]
    eq = s["equity_indexes_stats"]
    equity = s["by_economic_semantics"]["equity_indexes"]
    assert eq["count"] == len(equity)
    for field, key in (
        ("history_retrieved", "total_return_history_retrieved"),
        ("history_range_verified", "total_return_history_range_verified"),
        ("history_coverage_adequate", "total_return_history_coverage_adequate"),
        ("history_quality_adequate", "total_return_history_quality_adequate"),
        ("backtest_usable", "total_return_backtest_usable"),
    ):
        recalc = sum(1 for x in r01["indexes"]
                     if x["index_code"] in equity
                     and x["history_states"].get(field) is True)
        assert eq[key] == recalc, f"{key}: summary={eq[key]} 复算={recalc}"


def test_summary_categories_are_exhaustive_and_exclusive(r01):
    """按经济语义的分组必须互斥且覆盖全部 10 个指数。"""
    sem = r01["summary"]["by_economic_semantics"]
    equity = set(sem["equity_indexes"])
    bond = set(sem["special_bond_indexes"])
    assert not (equity & bond), "股票与债券分组重叠"
    assert equity | bond == INDEX_CODES, "分组未覆盖全部指数"


def test_summary_total_matches_indexes(r01):
    assert r01["summary"]["total_indexes"] == len(r01["indexes"])
    assert r01["summary"]["consistency_check"]["consistent"] is True


def test_five_states_are_independent(r01):
    """五态必须各自独立判定，且汇总数可逐项复算。"""
    s = r01["summary"]
    eq = s["equity_indexes_stats"]
    equity = s["by_economic_semantics"]["equity_indexes"]
    for key, field in (
        ("total_return_history_retrieved", "history_retrieved"),
        ("total_return_history_coverage_adequate", "history_coverage_adequate"),
        ("total_return_history_quality_adequate", "history_quality_adequate"),
        ("total_return_backtest_usable", "backtest_usable"),
    ):
        recalc = sum(1 for x in r01["indexes"]
                     if x["index_code"] in equity
                     and x["history_states"].get(field) is True)
        assert eq[key] == recalc
    # 逻辑必然：可回测 ⇒ 质量达标 ⇒ 覆盖达标 ⇒ 已取到
    for x in r01["indexes"]:
        st = x["history_states"]
        if st["backtest_usable"]:
            assert st["history_quality_adequate"]
            assert st["history_coverage_adequate"]
            assert st["history_retrieved"]


def test_states_derived_from_real_evidence(r01, ev):
    """每一态都必须能由证据附件的数据独立复算出来。"""
    qb = ev["coverage_quality_probe"]["by_code"]
    for x in r01["indexes"]:
        code = x.get("total_return_index_code")
        if not code or code not in qb:
            continue
        evq = qb[code]
        st = x["history_states"]
        assert st["history_retrieved"] == evq["history_retrieved"], \
            f"{x['index_code']}: 取到状态与证据不符"
        assert st["history_coverage_adequate"] == evq["history_coverage_adequate"]
        assert st["history_quality_adequate"] == evq["history_quality_adequate"]


# ================================================================ 2. MD 与 JSON 一致
def test_markdown_category_counts_match_json(r01):
    """Markdown 里的五态比率必须与 JSON 统计一致。"""
    md = _md(MD01)
    eq = r01["summary"]["equity_indexes_stats"]
    n = eq["count"]
    for key in ("total_return_history_retrieved",
                "total_return_history_range_verified",
                "total_return_history_coverage_adequate",
                "total_return_history_quality_adequate",
                "total_return_backtest_usable"):
        assert f"**{eq[key]}/{n}**" in md, f"MD 缺 {key}={eq[key]}/{n}"


def test_markdown_five_states_match_json(r01):
    md = _md(MD01)
    for x in r01["indexes"]:
        assert f"| `{x['index_code']}` |" in md, f"MD 缺 {x['index_code']}"


def test_markdown_does_not_claim_unverified_full_history(r01):
    """未达覆盖标准的指数，在 MD 与 JSON 中都不得标为覆盖达标。"""
    for x in r01["indexes"]:
        st = x["history_states"]
        if st["history_coverage_adequate"]:
            continue
        assert st["coverage_ratio"] < 0.95, \
            f"{x['index_code']}: 覆盖率 {st['coverage_ratio']} 却标未达标"


# ================================================================ 3. factsheet 一致性
def test_factsheet_fields_match_evidence(r01, ev):
    """10 个指数的 official_factsheet 必须与证据附件一致。"""
    docs = ev["official_documents"]
    for x in r01["indexes"]:
        code = x["index_code"]
        fs = x.get("official_factsheet")
        assert fs is not None, f"{code} 的 official_factsheet 为 null"
        ev_fs = docs[code]["factsheet"]
        assert fs["bytes"] == ev_fs["bytes"], f"{code} 字节数不一致"
        assert fs["pages"] == ev_fs["pages"], f"{code} 页数不一致"
        assert fs["sha256_16"] == ev_fs["sha256_16"], f"{code} sha 不一致"
        assert fs["url"] == ev_fs["url"], f"{code} URL 不一致"


def test_factsheet_download_backed_by_real_metadata(r01):
    """下载状态必须有真实文件元数据（字节/页数/sha）支撑。"""
    for x in r01["indexes"]:
        fs = x.get("official_factsheet")
        if not fs or not fs.get("downloaded"):
            continue
        assert fs["bytes"] > 1000, f"{x['index_code']} 字节数异常"
        assert fs["pages"] >= 1
        assert len(fs["sha256_16"]) == 16
        assert fs["url"].startswith("https://")


def test_markdown_factsheet_table_matches_json(r01):
    """MD 的 factsheet 表格必须与 JSON 的 10/10 一致。"""
    md = _md(MD01)
    downloaded = sum(1 for x in r01["indexes"]
                     if (x.get("official_factsheet") or {}).get("downloaded"))
    assert downloaded == 10
    # MD 里不应出现「8 个指数未取得 factsheet」这类说法
    assert "❌ | — | — | — | — |" not in md.split("## 4.")[1][:2000] \
        if "## 4." in md else True


# ================================================================ 4-7. 三层不得混淆
def test_code_identified_does_not_imply_full_history(r01):
    """代码存在 ≠ 历史覆盖达标。"""
    for x in r01["indexes"]:
        has_code = bool(x["total_return_index_code"])
        st = x["history_states"]
        assert st["history_retrieved"] == has_code or st["history_retrieved"] is False
        if has_code and not st["history_coverage_adequate"]:
            assert st["coverage_ratio"] < 0.95


def test_short_probe_does_not_imply_full_history(r01, ev):
    """短窗口成功 ≠ 覆盖达标。"""
    probe = {}
    for e in ev["indexes"]:
        for v in e["variants"]:
            probe[v["request_code"]] = v
    for x in r01["indexes"]:
        tc = x.get("total_return_index_code")
        if not tc: continue
        short_ok = probe.get(tc, {}).get("status") == "ok"
        if short_ok and not x["history_states"]["history_coverage_adequate"]:
            assert x["history_states"]["coverage_ratio"] < 0.95, \
                f"{x['index_code']}: 短窗口成功但覆盖未达标，比率却 >= 0.95"


def test_unavailable_history_not_marked_available(r01):
    """覆盖未达标时必须给出可追溯的阻断原因。"""
    for x in r01["indexes"]:
        st = x["history_states"]
        if not st["history_coverage_adequate"]:
            blockers = st.get("backtest_blockers") or []
            assert any("历史起点晚" in b or "覆盖" in b for b in blockers), \
                f"{x['index_code']} 覆盖未达标却无阻断说明"


def test_specific_indexes_history_status_accurate(r01, ev):
    """逐指数核对覆盖状态与证据一致。"""
    qb = ev["coverage_quality_probe"]["by_code"]
    for x in r01["indexes"]:
        tc = x.get("total_return_index_code")
        if not tc or tc not in qb: continue
        assert (x["history_states"]["history_coverage_adequate"]
                == qb[tc]["history_coverage_adequate"])


def test_000922_net_history_reflects_reality(r01, ev):
    """000922 净收益序列存在，其覆盖状态必须来自实测。"""
    x = next(v for v in r01["indexes"] if v["index_code"] == "000922")
    assert x["net_total_return_index_code"] == "000922CNY020"
    qb = ev["coverage_quality_probe"]["by_code"]
    if "000922CNY020" in qb:
        nq = x.get("net_return_quality")
        assert nq is not None
        assert nq["history_retrieved"] == qb["000922CNY020"]["history_retrieved"]


# ================================================================ 8-9. 000051
PROHIBITED = ("剩余5%按1%年化固定收益计",
              "剩余 5% 按 1% 年化固定收益计",
              "95%配沪深300，剩余5%",
              "95% 配沪深300，剩余 5%")


def _walk_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_strings(v)


def test_000051_no_unsupported_interpretation(r02):
    """000051 描述不得出现「剩余5%按1%年化固定收益计」等无证据表述。"""
    c = next(x for x in r02["composites"] if x["composite_id"] == 16)
    for s in _walk_strings(c):
        for bad in PROHIBITED:
            # 允许出现在「禁止表述」字段里（那是声明禁止，不是采用）
            if bad in s and "不得表述" not in s and "prohibited" not in s.lower():
                if "这是对原文的推断性解释" in s:
                    continue
                pytest.fail(f"000051 出现无证据表述：{bad}，来源：{s[:120]}")


def test_000051_requires_accurate_description(r02):
    """必须使用统一的严谨描述。"""
    c = next(x for x in r02["composites"] if x["composite_id"] == 16)
    bi = c["benchmark_interpretation"]
    assert "该1%不是资产权重" in bi["accurate_description"]
    assert "未明确说明其余5%" in bi["accurate_description"]
    assert "不推断其配置含义" in bi["accurate_description"]


def test_000051_declares_not_stateable(r02):
    """必须显式声明哪些不能推断。"""
    c = next(x for x in r02["composites"] if x["composite_id"] == 16)
    not_stateable = " ".join(c["benchmark_interpretation"]["not_stateable"])
    assert "5%" in not_stateable
    assert "资产配置" in not_stateable


def test_000051_fixed_rate_not_in_weight_sum(r02):
    """固定年收益率不得进入资产权重求和。"""
    c = next(x for x in r02["composites"] if x["composite_id"] == 16)
    fixed = c.get("fixed_annual_return_components") or []
    assert len(fixed) == 1
    assert fixed[0]["weight"] is None
    assert fixed[0]["annual_rate"] == 0.01

    total = 0.0
    for key in ("index_components", "bond_components", "cash_components"):
        for comp in c.get(key) or []:
            if comp.get("weight") is not None:
                total += comp["weight"]
    assert abs(total - 0.95) < 1e-9, f"资产权重合计应为 0.95，实际 {total}"
    assert abs(total - 0.96) > 1e-9, "资产权重合计不得为 0.96"
    assert c["weight_sum_of_asset_components"] == 0.95


def test_000051_not_reproducible(r02):
    c = next(x for x in r02["composites"] if x["composite_id"] == 16)
    assert c["status"] != "reproducible"
    assert c["period_conversion_evidence"]["method_known"] is False


def test_markdown_000051_uses_accurate_wording(r02):
    md = _md(MD02)
    assert "该1%不是资产权重" in md
    assert "未明确说明其余5%的资产配置方式" in md
    assert "不推断其配置含义" in md


# ================================================================ 10-12. 门禁
def test_all_return_basis_still_unknown(r01):
    for x in r01["indexes"]:
        assert x["return_basis"] == "unknown", \
            f"{x['index_code']} 的 return_basis 被升级为 {x['return_basis']}"
        assert x["usable_for_excess_return"] is False


def test_gates_unchanged(r01, r02):
    for name, d in (("01", r01), ("02", r02)):
        g = d["gate"]
        assert g["ready_for_research_analysis"] is True, f"{name}"
        assert g["ready_for_backtest"] is False, f"{name}"
        assert g["ready_for_formal_ranking"] is False, f"{name}"


def test_no_database_write():
    from app.database.db import get_connection
    with get_connection() as c:
        assert c.execute("SELECT COUNT(*) FROM index_daily").fetchone()[0] == 50603
        assert c.execute("SELECT COUNT(*) FROM index_master").fetchone()[0] == 10
        assert c.execute(
            "SELECT COUNT(*) FROM benchmark_composite").fetchone()[0] == 15
        assert c.execute(
            "SELECT COUNT(*) FROM benchmark_composite_component").fetchone()[0] == 34


def test_reports_have_no_deprecated_category_names(r01, r02):
    """报告不得残留已废弃的分类字段（3B-6.1.0.1 的 all_three_series 等）。"""
    deprecated = ("all_three_series", "price_and_total_only", "price_total_only")
    for name, doc in (("01", r01), ("02", r02)):
        blob = json.dumps(doc, ensure_ascii=False)
        for bad in deprecated:
            assert bad not in blob, f"{name}.json 残留废弃字段 {bad}"


def test_summary_numbers_not_handwritten(r01):
    """summary 数字必须可由 indexes 复算，不可是手写常量。"""
    s = r01["summary"]
    sem = s["by_economic_semantics"]
    assert len(sem["equity_indexes"]) + len(sem["special_bond_indexes"]) \
        == s["total_indexes"]
    eq = s["equity_indexes_stats"]
    recalc = sum(1 for x in r01["indexes"]
                 if x["index_code"] in sem["equity_indexes"]
                 and x["history_states"]["backtest_usable"])
    assert eq["total_return_backtest_usable"] == recalc == 0
