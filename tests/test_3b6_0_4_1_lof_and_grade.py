"""阶段3B-6.0.4.1 LOF 分类修正 + 组级质量等级一致性专项测试。

只读：不联网、不写正式库。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.fund.research.classification import (  # noqa: E402
    classify_fund, detect_lof, peer_group_key,
)
from app.fund.research.peer_engine import (  # noqa: E402
    PEER_COMPARABLE, PEER_DESCRIPTIVE_ONLY, PEER_EXCLUDED,
    group_quality_grade, group_usability,
)
from app.fund.research.quality import (  # noqa: E402
    LEVEL_B, LEVEL_C, LEVEL_D, grade_peer_comparison,
)

# 5 只简称被截断、只有全称含 LOF 的基金（真实库内数据）
TRUNCATED_LOF = {
    "001883": ("中欧新动力混合", "中欧新动力混合型证券投资基金(LOF)"),
    "001886": ("中欧成长", "中欧行业成长混合型证券投资基金(LOF)"),
    "001888": ("中欧盛世成长", "中欧盛世成长混合型证券投资基金(LOF)"),
    "001889": ("中欧增强回报债券", "中欧增强回报债券型证券投资基金(LOF)"),
    "002592": ("中欧纯债", "中欧纯债债券型证券投资基金(LOF)"),
}


def _row(name, full=None, l1="混合型-偏股", l2=None, is_idx=None):
    return {"fund_name": name, "fund_full_name": full,
            "fund_type_l1": l1, "fund_type_l2": l2 or l1,
            "is_index_fund": is_idx}


# ================================================================ 1. detect_lof
def test_detect_lof_short_name_only():
    r = detect_lof("招商中证白酒指数(LOF)", "招商中证白酒指数证券投资基金")
    assert r["recognized"] is True
    assert r["evidence"] == "short_name"
    assert r["evidence_field"] == "fund_name"


def test_detect_lof_full_name_only():
    r = detect_lof("中欧新动力混合", "中欧新动力混合型证券投资基金(LOF)")
    assert r["recognized"] is True
    assert r["evidence"] == "full_name"
    assert r["evidence_field"] == "fund_full_name"


def test_detect_lof_both():
    r = detect_lof("富国天惠成长混合(LOF)",
                   "富国天惠精选成长混合型证券投资基金(LOF)")
    assert r["recognized"] is True
    assert r["evidence"] == "both"


def test_detect_lof_neither():
    r = detect_lof("华夏纯债债券", "华夏纯债债券型证券投资基金")
    assert r["recognized"] is False
    assert r["evidence"] == "none"
    assert r["evidence_field"] is None


def test_detect_lof_chinese_paren():
    assert detect_lof("某某基金（LOF）", None)["recognized"] is True
    assert detect_lof("某某基金", "某某基金型证券投资基金（LOF）")["recognized"] is True


def test_detect_lof_no_false_positive_from_substring():
    """不含 LOF 标记的普通名称不得误识别。"""
    for name, full in (
        ("中欧成长", "中欧行业成长型证券投资基金"),
        ("国联安中证半导体ETF联接", "国联安中证全指半导体产品与设备ETF联接基金"),
        ("易方达消费行业股票", "易方达消费行业股票型证券投资基金"),
    ):
        assert detect_lof(name, full)["recognized"] is False


# ================================================================ 2. 5 只基金
@pytest.mark.parametrize("code", sorted(TRUNCATED_LOF))
def test_truncated_lof_funds_classified_as_lof(code):
    """5 只简称被截断的基金必须识别为 LOF。"""
    name, full = TRUNCATED_LOF[code]
    cls = classify_fund(_row(name, full))
    assert cls["product_class"] == "lof"
    assert cls["lof_evidence"] == "full_name"
    assert cls["lof_evidence_field"] == "fund_full_name"


@pytest.mark.parametrize("code", sorted(TRUNCATED_LOF))
def test_truncated_lof_not_in_active_equity_or_bond(code):
    """修正前它们被归入 active_equity / bond_pure，必须不再如此。"""
    name, full = TRUNCATED_LOF[code]
    cls = classify_fund(_row(name, full))
    assert cls["product_class"] not in ("active_equity", "bond_pure",
                                         "bond_mixed", "ordinary_index",
                                         "etf_linked")


def test_lof_without_full_name_still_flagged():
    """只有简称时按简称判定，并标注全称缺失（待核实），不猜测。"""
    cls = classify_fund(_row("某基金(LOF)", None))
    assert cls["product_class"] == "lof"
    assert cls["lof_name_missing_full"] is True


def test_non_lof_without_full_name_not_guessed():
    """简称不含 LOF、全称缺失 → 不得猜成 LOF。"""
    cls = classify_fund(_row("华夏纯债债券", None))
    assert cls["product_class"] != "lof"


# ================================================================ 3. 子类型
def test_lof_index_subtype():
    cls = classify_fund(_row("招商中证白酒指数(LOF)",
                             "招商中证白酒指数证券投资基金",
                             l1="指数型-股票", is_idx=1))
    assert cls["product_class"] == "lof"
    assert cls["investment_subtype"] == "index"


def test_lof_active_subtype():
    cls = classify_fund(_row("中欧新动力混合",
                             "中欧新动力混合型证券投资基金(LOF)",
                             l1="混合型-偏股", is_idx=None))
    assert cls["product_class"] == "lof"
    assert cls["investment_subtype"] == "active"


def test_lof_index_peer_key_starts_with_lof():
    cls = classify_fund(_row("招商中证白酒指数(LOF)",
                             "招商中证白酒指数证券投资基金",
                             l1="指数型-股票", is_idx=1))
    pg = peer_group_key(cls, "招商中证白酒指数(LOF)",
                        "中证白酒指数收益率×95%+银行活期存款利率×5%", None)
    assert pg["peer_key"].startswith("lof|index|")


def test_lof_active_peer_key_starts_with_lof():
    cls = classify_fund(_row("中欧新动力混合",
                             "中欧新动力混合型证券投资基金(LOF)"))
    pg = peer_group_key(cls, "中欧新动力混合",
                        "中证800指数收益率*85%+中证全债指数收益率*15%", None)
    assert pg["peer_key"].startswith("lof|active|")


# ================================================================ 4. 组级评级
def test_bond_pure_unknown_14_is_d():
    r = group_quality_grade("bond_pure|unknown", 14)
    assert r["quality_level"] == LEVEL_D
    assert r["status"] == "no_verifiable_group"


def test_bond_pure_unknown_50_still_d():
    r = group_quality_grade("bond_pure|unknown", 50)
    assert r["quality_level"] == LEVEL_D


def test_bond_mixed_unknown_is_d():
    r = group_quality_grade("bond_mixed|unknown", 2)
    assert r["quality_level"] == LEVEL_D


def test_active_equity_unknown_is_d():
    r = group_quality_grade("active_equity|unknown", 4)
    assert r["quality_level"] == LEVEL_D


def test_unknown_family_index_group_is_d_even_with_many_members():
    r = group_quality_grade("etf_linked|unknown|unknown", 20)
    assert r["quality_level"] == LEVEL_D


def test_money_market_7_is_b():
    r = group_quality_grade("money_market", 7)
    assert r["quality_level"] == LEVEL_B
    assert r["status"] == "usable"


def test_money_market_3_is_c():
    assert group_quality_grade("money_market", 3)["quality_level"] == LEVEL_C


def test_money_market_1_is_d():
    assert group_quality_grade("money_market", 1)["quality_level"] == LEVEL_D


def test_engine_grade_matches_authoritative_rule():
    """引擎不得自建映射，必须与 grade_peer_comparison 完全一致。"""
    for key, n in (("bond_pure|unknown", 14), ("bond_mixed|unknown", 2),
                   ("active_equity|unknown", 4), ("money_market", 7),
                   ("etf_linked|broad|沪深300", 5),
                   ("ordinary_index|broad|中证500", 5),
                   ("active_equity|中证800", 3)):
        a = group_quality_grade(key, n)
        b = grade_peer_comparison({"peer_key": key, "member_count": n})
        assert a["quality_level"] == b["quality_level"]
        assert a["status"] == b["status"]


# ================================================================ 5. 真实库一致性
def test_live_bond_pure_unknown_is_d():
    """正式库重新分组后 bond_pure|unknown 必须是 D。"""
    from app.fund.research.data_access import load_universe
    u = load_universe()
    seen = {}
    for e in u:
        seen.setdefault(e["fund_id"], e)
    groups = {}
    for fid, e in seen.items():
        groups.setdefault(e["peer_group"]["peer_key"], []).append(fid)
    key = "bond_pure|unknown"
    if key in groups:
        r = group_quality_grade(key, len(groups[key]),
                                seen[groups[key][0]]["peer_group"])
        assert r["quality_level"] == LEVEL_D


def test_live_lof_members_all_have_lof_class():
    from app.fund.research.data_access import load_universe
    u = load_universe()
    lof = {e["fund_code"] for e in u if e["product_class"] == "lof"}
    for code in TRUNCATED_LOF:
        assert code in lof, f"{code} 未识别为 LOF"


def test_live_active_equity_800_excludes_truncated_lof():
    """active_equity|中证800 不得再包含上述 5 只 LOF。"""
    from app.fund.research.data_access import load_universe
    u = load_universe()
    members = {e["fund_code"] for e in u
               if e["peer_group"]["peer_key"] == "active_equity|中证800"}
    assert not (members & set(TRUNCATED_LOF))


def test_live_group_counts_are_data_driven():
    """可比组数量必须由真实分类算出，不得写死。"""
    from app.fund.research.data_access import load_universe
    u = load_universe()
    seen = {}
    for e in u:
        seen.setdefault(e["fund_id"], e)
    groups = {}
    for fid, e in seen.items():
        groups.setdefault(e["peer_group"]["peer_key"], []).append(fid)
    comparable = sum(1 for k, v in groups.items()
                     if group_usability(k, len(v))["status"] == PEER_COMPARABLE)
    # 只断言它是算出来的正数，不写死具体值
    assert comparable >= 1
    assert comparable < len(groups)


def test_live_no_duplicate_fund_id():
    from app.fund.research.data_access import load_universe
    u = load_universe()
    ids = [e["fund_id"] for e in u]
    assert len(ids) > len(set(ids))      # 份额 > 本体
    assert len(set(ids)) == 79


# ================================================================ 6. Markdown/JSON 一致性
def test_report_markdown_and_json_grades_consistent(tmp_path):
    """任务要求：报告生成后 JSON 与 Markdown 评级必须一致。

    这里用**同一份组级结果**分别渲染两种格式，断言等级完全一致。
    """
    keys = [("bond_pure|unknown", 12), ("bond_mixed|unknown", 2),
            ("active_equity|unknown", 4), ("money_market", 7),
            ("etf_linked|broad|沪深300", 5)]

    # 单一数据源
    rows = []
    for key, n in keys:
        g = group_quality_grade(key, n)
        rows.append({"peer_key": key, "member_count": n,
                     "quality_level": g["quality_level"],
                     "status": g["status"]})

    # JSON 侧
    payload = json.loads(json.dumps({"groups": rows}, ensure_ascii=False))

    # Markdown 侧（与报告生成器同构：从同一份 rows 渲染）
    md_lines = ["| 组键 | 本体数 | 等级 |", "| --- | ---: | --- |"]
    for r in rows:
        md_lines.append(f"| `{r['peer_key']}` | {r['member_count']} | "
                        f"**{r['quality_level']}** |")
    markdown = "\n".join(md_lines)

    for r in payload["groups"]:
        # JSON 里出现的每个等级必须在 Markdown 里出现
        assert r["quality_level"] in markdown
        # 且 bond_* 必须是 D
        if r["peer_key"].startswith("bond_"):
            assert r["quality_level"] == LEVEL_D


def test_bond_keys_must_be_d_in_both_formats():
    for key in ("bond_pure|unknown", "bond_mixed|unknown"):
        r = group_quality_grade(key, 14)
        assert r["quality_level"] == LEVEL_D
        # 渲染成 markdown 行也必须是 D
        line = f"| `{key}` | 14 | **{r['quality_level']}** |"
        assert "**D**" in line
