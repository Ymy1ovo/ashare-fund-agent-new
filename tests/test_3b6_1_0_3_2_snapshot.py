"""阶段3B-6.1.0.3.2 README 历史数据快照日期口径测试。

目标：
- README 当前口径必须与 reports/phase3B6_1_0_01_index_return_basis.json 一致
- 历史快照必须明确标注，不得与当前结论混淆
- 允许历史快照存在（不得为了测试通过删除有价值记录）

所有期望值从 JSON 实时计算，不硬编码。
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

README = ROOT / "README.md"
REPORT = ROOT / "reports" / "phase3B6_1_0_01_index_return_basis.json"


@pytest.fixture(scope="module")
def readme() -> str:
    assert README.exists()
    return README.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def r01() -> dict:
    return json.loads(REPORT.read_text(encoding="utf-8"))


def _index(r01, code):
    return next(x for x in r01["indexes"] if x["index_code"] == code)


def _section(md: str, start_marker: str, end_marker: str | None = None) -> str:
    i = md.find(start_marker)
    assert i >= 0, f"README 缺章节 {start_marker}"
    if end_marker:
        j = md.find(end_marker, i + len(start_marker))
        return md[i:j] if j > 0 else md[i:]
    return md[i:]


# ============================================================ 当前权威表
def test_authoritative_section_exists(readme):
    assert "当前权威结论" in readme
    assert "77.12" in readme


def test_authoritative_table_matches_json(readme, r01):
    """77.12 权威表必须与 JSON 逐项一致。"""
    sec = _section(readme, "### 77.12")
    for x in r01["indexes"]:
        code = x["index_code"]
        pq = x.get("price_quality") or {}
        tq = x.get("total_return_quality") or {}
        # 该行必须存在且包含真实值
        rows = [ln for ln in sec.splitlines()
                if ln.startswith(f"| `{code}` |")]
        assert rows, f"77.12 缺 {code}"
        row = rows[0]
        assert f"{tq['rows']:,}" in row, \
            f"{code}: 全收益行数 {tq['rows']:,} 未出现在权威表"
        assert tq["real_start_date"] in row, \
            f"{code}: 真实起点 {tq['real_start_date']} 未出现在权威表"
        assert f"{tq['coverage_ratio']:.1%}" in row, \
            f"{code}: 覆盖率 {tq['coverage_ratio']:.1%} 未出现在权威表"
        assert tq["date_max"] in row, f"{code}: 截止日未出现在权威表"
        if pq.get("rows"):
            assert f"{pq['rows']:,}" in row


def test_399997_current_values_explicit(readme, r01):
    """399997 当前口径必须是 4,347 行 / 2008-12-31 / 78.2%。"""
    x = _index(r01, "399997")
    tq = x["total_return_quality"]
    sec = _section(readme, "### 77.12")
    assert "**`399997` 当前口径**" in sec
    para = sec.split("**`399997` 当前口径**")[1][:200]
    assert f"{tq['rows']:,}" in para
    assert tq["real_start_date"] in para
    assert f"{tq['coverage_ratio']:.1%}" in para
    assert tq["date_max"] in para


def test_930930_current_values_explicit(readme, r01):
    x = _index(r01, "930930")
    tq = x["total_return_quality"]
    sec = _section(readme, "### 77.12")
    assert "**`930930` 当前口径**" in sec
    para = sec.split("**`930930` 当前口径**")[1][:200]
    assert f"{tq['rows']:,}" in para
    assert tq["real_start_date"] in para
    assert f"{tq['coverage_ratio']:.1%}" in para


# ============================================================ 历史快照标注
def test_db_snapshot_marked_as_historical(readme):
    """70.2 数据库快照必须明确标注为历史快照。"""
    sec = _section(readme, "### 70.2", "### 70.3")
    assert "历史快照" in sec or "入库快照" in sec, "70.2 未标注为快照"
    assert "不是当前审计结论" in sec or "不是当前" in sec
    assert "2026-11-20" in sec


def test_db_snapshot_points_to_authoritative(readme):
    """快照章节必须指向当前权威结论。"""
    sec = _section(readme, "### 70.2", "### 70.3")
    assert "77.10" in sec or "77.12" in sec, "70.2 未指向权威章节"


def test_superseded_conclusion_marked(readme):
    """74.2 的「无全收益」判定必须标注已被推翻。"""
    sec = _section(readme, "### 74.2", "### 74.3")
    assert "推翻" in sec, "74.2 未标注已推翻"
    for code in ("399997", "H30184", "930930"):
        rows = [ln for ln in sec.splitlines() if f"`{code}`" in ln]
        assert rows, f"74.2 缺 {code}"
        assert "推翻" in rows[0] or "~~" in rows[0], \
            f"{code} 行未标注已推翻"


def test_snapshot_index_exists(readme):
    """必须提供历史快照索引表。"""
    assert "历史快照索引" in readme
    sec = _section(readme, "历史快照索引")
    assert "70.2" in sec
    assert "74.2" in sec
    assert "不得作为当前结论引用" in sec


# ============================================================ 无冲突口径
def _current_section(readme: str) -> str:
    """返回 77.12 权威章节 + 77.x 更新章节，这些地方不得出现旧值。"""
    return _section(readme, "### 77.10")


def test_no_conflicting_399997_in_current_sections(readme, r01):
    """当前章节内 399997 的行数/起点必须与 JSON 一致，不得出现旧值。"""
    x = _index(r01, "399997")
    tq = x["total_return_quality"]
    sec = _current_section(readme)
    # 允许出现的当前值
    assert f"{tq['rows']:,}" in sec
    # 旧值若出现，必须在同一行带「快照/旧/推翻」标记
    for old_val in ("4,345", "2009-01-05"):
        for ln in sec.splitlines():
            if old_val not in ln:
                continue
            assert ("快照" in ln or "旧" in ln or "~~" in ln
                    or "推翻" in ln or "历史" in ln), \
                f"当前章节出现旧值 {old_val} 但未标注历史：{ln.strip()[:90]}"


def test_no_conflicting_930930_in_current_sections(readme, r01):
    x = _index(r01, "930930")
    tq = x["total_return_quality"]
    sec = _current_section(readme)
    assert f"{tq['rows']:,}" in sec
    for old_val in ("2,999",):
        for ln in sec.splitlines():
            if old_val not in ln:
                continue
            assert ("快照" in ln or "旧" in ln or "~~" in ln
                    or "历史" in ln), \
                f"当前章节出现旧值 {old_val} 但未标注历史：{ln.strip()[:90]}"


def test_no_unmarked_2026_11_20_as_cutoff(readme):
    """3B-6.1.x 章节内，2026-11-20 只能出现在历史快照语境。"""
    start = readme.find("## 74. 阶段3B-6.1.0")
    assert start > 0
    scope = readme[start:]
    # 该章节里的快照小节整体豁免
    for section_head in ("### 70.2",):
        pass
    in_snapshot_block = False
    for ln in scope.splitlines():
        if "2026-11-20" not in ln:
            continue
        #  Databases 快照表在 70 节（scope 之外），此处只查 74+ 章节
        assert ("快照" in ln or "历史" in ln or "~~" in ln
                or ln.strip().startswith(">")), \
            f"3B-6.1.x 章节出现未标注的 2026-11-20：{ln.strip()[:90]}"


def test_price_vs_total_series_distinguished(readme):
    """必须区分价格序列与全收益序列（两者行数/起点不同）。"""
    sec = _section(readme, "### 77.12")
    assert "价格代码" in sec
    assert "全收益代码" in sec


# ============================================================ 保留历史记录
def test_historical_records_not_deleted(readme):
    """不得为了测试通过删除有历史价值的记录。"""
    # 旧快照的值仍应存在（作为历史记录）
    assert "4,345" in readme, "历史快照 4,345 行被删除"
    assert "2,999" in readme, "历史快照 2,999 行被删除"
    assert "2026-11-20" in readme, "历史快照日期被删除"
    assert "H39997" in readme, "历史错误猜测被删除"
    assert "2009-01-05" in readme, "价格序列起点被删除"


# ============================================================ 其他一致性
def test_readme_coverage_rates_match_json(readme, r01):
    """3B-6.1.x 章节里的覆盖率必须能在 JSON 找到对应。"""
    valid = {f"{x['total_return_quality']['coverage_ratio']:.1%}"
             for x in r01["indexes"] if x.get("total_return_quality")}
    start = readme.find("## 74. 阶段3B-6.1.0")
    assert start > 0
    scope = readme[start:]
    for m in re.finditer(r"(\d{2,3}\.\d%)", scope):
        rate = m.group(1)
        v = float(rate.rstrip("%"))
        if 40 <= v <= 100:
            assert rate in valid, f"3B-6.1.x 出现无法对应 JSON 的覆盖率 {rate}"


def test_gate_unchanged(r01):
    g = r01["gate"]
    assert g["ready_for_research_analysis"] is True
    assert g["ready_for_backtest"] is False
    assert g["ready_for_formal_ranking"] is False


def test_database_fingerprint_untouched():
    from app.fund.ingest_user_funds import db_fingerprint
    assert db_fingerprint()["sha256"] == (
        "115ac91eee7c26424952e6df23ddeeafe2435974fe5e81a8ba6bbcabfe387dd4")
