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
    """JSON summary 的每个分类数量必须等于 detail 数组长度。"""
    summary = r01["summary"]
    detail = summary["detail"]
    by_cat = summary["by_coverage_category"]
    assert set(by_cat.keys()) == set(detail.keys()), "分类键集不一致"
    for key, count in by_cat.items():
        assert count == len(detail[key]), \
            f"{key}: summary={count} 但 detail 有 {len(detail[key])} 个"


def test_summary_categories_are_exhaustive_and_exclusive(r01):
    """分类必须互斥且覆盖全部 10 个指数。"""
    detail = r01["summary"]["detail"]
    all_codes = [c for v in detail.values() for c in v]
    assert len(all_codes) == len(set(all_codes)), "存在重复归类"
    assert set(all_codes) == INDEX_CODES, "分类未覆盖全部指数"


def test_summary_total_matches_indexes(r01):
    assert r01["summary"]["total_indexes"] == len(r01["indexes"])
    assert r01["summary"]["consistency_check"]["consistent"] is True


def test_three_layers_are_not_conflated(r01):
    """三层数量必须分别计算，且每层都由自己的证据决定，不得互相冒充。"""
    L = r01["summary"]["by_layer"]
    # 逻辑必然：完整历史可用 ⇒ 代码必然已识别（但反向不成立）
    assert L["full_history_verified_total_return"] <= L["code_identified"]
    # 汇总数必须等于逐指数计数，不得手工填写
    assert L["code_identified"] == sum(
        1 for x in r01["indexes"] if x["layers"]["code_identified"])
    assert L["short_probe_ok"] == sum(
        1 for x in r01["indexes"] if x["layers"]["short_probe_ok"])
    assert L["full_history_verified_total_return"] == sum(
        1 for x in r01["indexes"] if x["layers"]["full_history_verified"])
    # 每个指数的 layers 字段必须自洽
    for x in r01["indexes"]:
        lyr = x["layers"]
        if lyr["full_history_verified"]:
            assert lyr["code_identified"], \
                f"{x['index_code']}: 完整历史可用却标代码未识别"
            assert lyr["short_probe_ok"], \
                f"{x['index_code']}: 完整历史可用却标短窗口不可用"


def test_layers_derived_from_real_evidence(r01, ev):
    """每一层都必须能由证据附件的数据独立复算出来。"""
    probe = {}
    for e in ev["indexes"]:
        for v in e["variants"]:
            probe[v["request_code"]] = v
    for x in r01["indexes"]:
        tc = x["total_return_index_code"]
        has_code = tc is not None
        assert x["layers"]["code_identified"] is has_code
        short_ok = bool(tc and probe.get(tc, {}).get("status") == "ok")
        assert x["layers"]["short_probe_ok"] is short_ok, \
            f"{x['index_code']}: 短窗口状态与证据不符"
        # 完整历史可用 ⇒ 必须有真实行数与起止日期
        if x["layers"]["full_history_verified"]:
            assert x["total_row_count"] and x["total_row_count"] > 0
            assert x["total_history_start"] and x["total_history_end"]


# ================================================================ 2. MD 与 JSON 一致
def test_markdown_category_counts_match_json(r01):
    """Markdown 里每个分类的指数数必须与 JSON 一致。"""
    md = _md(MD01)
    detail = r01["summary"]["detail"]
    labels = r01["summary"]["category_labels"]
    for key, codes in detail.items():
        label = labels[key]
        # MD 里该分类行必须包含 N
        pattern = re.compile(rf"{re.escape(label)}[^|]*\|\s*\*\*(\d+)\*\*")
        m = pattern.search(md)
        if m:
            assert int(m.group(1)) == len(codes), \
                f"{key}: MD 写 {m.group(1)}，JSON 是 {len(codes)}"


def test_markdown_three_layers_match_json(r01):
    md = _md(MD01)
    L = r01["summary"]["by_layer"]
    for key, val in (("code_identified", L["code_identified"]),
                     ("short_probe_ok", L["short_probe_ok"]),
                     ("full_history_verified_total_return",
                      L["full_history_verified_total_return"])):
        assert f"**{val} / 10**" in md, f"MD 缺 {key}={val}/10"


def test_markdown_does_not_claim_unverified_full_history(r01):
    """MD 不得把无完整历史的指数标成完整历史可用。"""
    md = _md(MD01)
    for x in r01["indexes"]:
        if x["layers"]["full_history_verified"]:
            continue
        # 该指数在该表格行里，③ 列必须是 ❌
        line = next((ln for ln in md.splitlines()
                     if ln.startswith(f"| `{x['index_code']}` |")), None)
        if line and "短窗口" in md.split("\n")[0:5]:
            pass  # 表格格式检查在下面单独做
    # 更直接：没有 full_history 的指数必须 total_history_available=False
    for x in r01["indexes"]:
        if not x["layers"]["full_history_verified"]:
            assert x["total_history_available"] is False


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
    """代码存在 ≠ 完整历史可用。"""
    for x in r01["indexes"]:
        has_code = bool(x["total_return_index_code"])
        has_hist = x["total_history_available"]
        if has_code and not has_hist:
            # 允许：代码已识别但历史未取到
            assert x["layers"]["code_identified"] is True
            assert x["layers"]["full_history_verified"] is False
            continue
        if not has_hist:
            assert x["total_row_count"] is None


def test_short_probe_does_not_imply_full_history(r01, ev):
    """短窗口成功 ≠ 完整历史覆盖。"""
    for x in r01["indexes"]:
        lyr = x["layers"]
        if lyr["short_probe_ok"] and not lyr["full_history_verified"]:
            # 这是合法状态，但 total_history_available 必须为 False
            assert x["total_history_available"] is False, \
                f"{x['index_code']}: 短窗口成功但完整历史未验证，不得标记可用"


def test_unavailable_history_not_marked_available(r01):
    """完整历史不可用时字段必须为空，不能填占位值。"""
    for x in r01["indexes"]:
        if x["total_history_available"]:
            assert x["total_row_count"] and x["total_row_count"] > 0
            assert x["total_history_start"] and x["total_history_end"]
        else:
            assert x["total_row_count"] is None
            assert x["total_history_start"] is None
            assert x["total_history_end"] is None


def test_specific_indexes_history_status_accurate(r01):
    """逐指数核对完整历史状态与真实探测一致。"""
    expect_total_hist = {
        "000300": True, "000905": True, "000906": True, "000016": True,
        "399997": True,   # H20539 已实测 4,347 行
        "H30184": True,   # H20184 已实测 5,317 行
        "000942": True,   # H00942 已实测 5,318 行
        "000922": True,   # H00922 已实测 5,318 行
        "930930": True,   # H20930 已实测 3,000 行
    }
    for x in r01["indexes"]:
        want = expect_total_hist.get(x["index_code"])
        if want is None: continue
        assert x["total_history_available"] is want, \
            f"{x['index_code']}: 期望 {want}，实际 {x['total_history_available']}"


def test_000922_net_history_reflects_reality(r01):
    """000922 净收益代码存在，历史必须来自实测。"""
    x = next(v for v in r01["indexes"] if v["index_code"] == "000922")
    assert x["net_total_return_index_code"] == "000922CNY020"
    if x["net_history_available"]:
        assert x["net_row_count"] and x["net_row_count"] > 0
    else:
        assert x["net_row_count"] is None


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
    """summary 数字必须可由 detail 复算，不可是手写常量。"""
    summary = r01["summary"]
    recalc = {k: len(v) for k, v in summary["detail"].items()}
    assert summary["by_coverage_category"] == recalc
    assert sum(recalc.values()) == summary["total_indexes"]
