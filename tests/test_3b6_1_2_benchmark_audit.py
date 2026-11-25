"""阶段3B-6.1.2 复合基准审计测试。

**全部从真实报告 JSON 与正式库重新计算**，不读取预计算的结论字段做假比对。
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
AUDIT = REPORTS / "phase3B6_1_2_benchmark_audit.json"
COMP = REPORTS / "phase3B6_1_2_component_history.json"
BOND = REPORTS / "phase3B6_1_2_bond_index_audit.json"
PIT = REPORTS / "phase3B6_1_2_point_in_time_audit.json"

STATES = [
    "component_identified", "weight_verified", "weight_history_verified",
    "return_basis_verified", "history_data_available",
    "point_in_time_verified", "formula_reproducible",
    "historically_reproducible",
]


@pytest.fixture(scope="module")
def audit() -> dict:
    assert AUDIT.exists()
    return json.loads(AUDIT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def comp() -> dict:
    assert COMP.exists()
    return json.loads(COMP.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def bond() -> dict:
    assert BOND.exists()
    return json.loads(BOND.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def pit() -> dict:
    assert PIT.exists()
    return json.loads(PIT.read_text(encoding="utf-8"))


# ============================================================ 15 条完整性
def test_all_15_benchmarks_present(audit):
    assert audit["summary"]["total_benchmarks"] == 15
    assert len(audit["benchmarks"]) == 15
    ids = [b["composite_id"] for b in audit["benchmarks"]]
    assert sorted(ids) == list(range(16, 31))


def test_benchmark_ids_match_database(audit):
    """必须与正式库的 15 条记录一一对应。"""
    from app.database.db import get_connection
    with get_connection() as c:
        db_ids = [r[0] for r in c.execute(
            "SELECT composite_id FROM benchmark_composite "
            "ORDER BY composite_id").fetchall()]
    assert [b["composite_id"] for b in audit["benchmarks"]] == db_ids


def test_no_benchmark_omitted_or_merged(audit, comp):
    """每条的成分数必须与 DB 一致。"""
    from app.database.db import get_connection
    with get_connection() as c:
        db_counts = dict(c.execute(
            "SELECT composite_id, COUNT(*) FROM benchmark_composite_component "
            "GROUP BY composite_id").fetchall())
    for b in audit["benchmarks"]:
        assert b["component_count"] == db_counts[b["composite_id"]], \
            f"{b['composite_id']}: 成分数不符"


def test_total_components_is_34(audit, comp):
    assert audit["summary"]["total_components"] == 34
    assert len(comp["components"]) == 34
    assert sum(b["component_count"] for b in audit["benchmarks"]) == 34


# ============================================================ summary 与 detail
def test_summary_counts_derived_from_detail(audit):
    """summary 每个数量必须可由 benchmarks 明细复算。"""
    s = audit["summary"]
    for key in STATES:
        recalc = sum(1 for b in audit["benchmarks"] if b["states"][key])
        assert s[key] == recalc, f"{key}: summary={s[key]} 复算={recalc}"


def test_fully_not_reproducible_count(audit):
    recalc = sum(1 for b in audit["benchmarks"]
                 if not b["states"]["formula_reproducible"]
                 and not b["states"]["historically_reproducible"])
    assert audit["summary"]["fully_not_reproducible"] == recalc


def test_text_consistency_counts(audit):
    s = audit["summary"]
    assert s["text_identical_count"] == sum(
        1 for b in audit["benchmarks"] if b["text_consistency"]["identical"])
    assert s["text_equivalent_count"] == sum(
        1 for b in audit["benchmarks"]
        if b["text_consistency"]["equivalent_after_normalization"])


# ============================================================ 八态独立
def test_eight_states_present_and_boolean(audit):
    for b in audit["benchmarks"]:
        for st in STATES:
            assert st in b["states"], f"{b['composite_id']} 缺 {st}"
            assert isinstance(b["states"][st], bool)


def test_no_auto_inheritance(audit):
    """八态必须独立：存在「前者真后者假」的实例。"""
    # 成分已识别但历史不可复现
    assert any(b["states"]["component_identified"]
               and not b["states"]["historically_reproducible"]
               for b in audit["benchmarks"])
    # 有权重文本（L3）但历史权重不可验证
    assert any(b["states"]["weight_text_evidence_present"]
               and not b["states"]["weight_history_verified"]
               for b in audit["benchmarks"])


def test_component_identified_not_imply_reproducible(audit):
    for b in audit["benchmarks"]:
        if b["states"]["historically_reproducible"]:
            assert b["states"]["component_identified"]
            assert b["states"]["point_in_time_verified"]


# ============================================================ 权重
def test_weight_sum_check(audit, comp):
    """固定年化收益率不得计入资产权重合计。"""
    for b in audit["benchmarks"]:
        parts = [c for c in comp["components"]
                 if c["composite_id"] == b["composite_id"]]
        asset = sum(p["weight"] for p in parts
                    if p["component_category"] != "fixed_rate"
                    and p["weight"] is not None)
        assert abs(b["asset_weight_sum"] - round(asset, 6)) < 1e-9


def test_fixed_rate_not_in_asset_weight(audit, comp):
    """000051 的 1% 固定收益率不得是资产权重。"""
    b = next(x for x in audit["benchmarks"] if x["composite_id"] == 16)
    assert b["fixed_rate_components"] == 1
    # 资产权重只有沪深300的 95%；1% 是固定年化收益率，不是资产权重
    assert abs(b["asset_weight_sum"] - 0.95) < 1e-9
    # 剩余 5% 既非资产也无解释，必须如实保留为未解释残余
    assert abs(b["unexplained_residual"] - 0.05) < 1e-9, \
        f"残余应为 5%，实际 {b['unexplained_residual']}"

    parts = [c for c in comp["components"] if c["composite_id"] == 16]
    fr = [p for p in parts if p["component_category"] == "fixed_rate"]
    assert len(fr) == 1
    assert fr[0]["return_basis_status"] == "fixed_annual_rate"
    assert fr[0]["return_basis"]["period_conversion_method"] == "unknown"


def test_all_weight_text_recorded(audit, comp):
    """权重文本必须 34/34 全部存在（但等级为 L3，不等于官方验证）。"""
    s = audit["summary"]
    assert s["weight_text_evidence_present"] == 15
    assert s["weight_verified"] == 0
    for c in comp["components"]:
        assert c["weight_text_evidence_present"], \
            f"成分 {c['component_id']} 缺权重文本"
        assert c["weight_evidence_in_db"]


def test_weight_history_all_missing(audit):
    """15/15 条的历史权重生效日期均为 NULL。"""
    assert audit["summary"]["weight_history_verified"] == 0
    for b in audit["benchmarks"]:
        assert b["states"]["weight_history_verified"] is False


# ============================================================ 价格 vs 全收益
def test_price_and_total_distinguished(comp):
    """指数成分必须同时记录价格代码与全收益代码，不得混用。"""
    for c in comp["components"]:
        if c["component_category"] != "index":
            continue
        rb = c["return_basis"]
        if rb.get("price_code"):
            assert rb.get("total_return_code") is not None
            assert rb["price_code"] != rb["total_return_code"], \
                f"{c['component_name']}: 价格与全收益代码相同"


def test_return_basis_status_is_unknown(comp):
    """全部指数成分的 return_basis 状态必须为 unknown / not_verified。"""
    for c in comp["components"]:
        if c["component_category"] != "index":
            continue
        assert c["return_basis_status"] in ("unknown", "not_verified"), \
            f"{c['component_name']}: {c['return_basis_status']}"


def test_no_basis_upgraded(audit):
    assert audit["summary"]["return_basis_verified"] == 0


# ============================================================ 债券指数
def test_bond_components_all_audited(bond):
    assert bond["summary"]["total_bond_components"] == 5
    labels = {t["contract_label"] for t in bond["targets"]}
    assert labels == {"中债总", "中债综合全价", "中证综合债券",
                       "中债-总全价(总值)", "中债综合财富"}


def test_bond_index_semantics_documented(bond):
    """价格/全价/净价/财富口径必须明确区分。"""
    sem = bond["indicator_semantics"]
    assert "财富" in sem and "全价" in sem and "净价" in sem
    assert "全价指数不等于全收益指数" in sem["warning"].replace("**", "")


def test_bond_no_official_code_confirmed(bond):
    """0 条债券指数成分的官方代码获得确认。"""
    assert bond["summary"]["official_code_confirmed"] == 0
    for t in bond["targets"]:
        assert t["official_code"] is None


def test_bond_no_methodology_doc(bond):
    assert bond["summary"]["methodology_doc_obtained"] == 0


def test_bond_fully_qualified_zero(bond):
    assert bond["summary"]["fully_qualified"] == 0


def test_bond_blocked_component_recorded(bond):
    """中证综合债券无接口，必须明确阻断，不得用国债收益率替代。"""
    t = next(x for x in bond["targets"]
             if x["contract_label"] == "中证综合债券")
    assert t["candidate_index"] is None
    assert "不得用国债收益率曲线代替" in t["blocking_reason"]


def test_bond_probe_quality(bond):
    """探测成功的序列质量必须记录完整。"""
    for t in bond["targets"]:
        for p in t["probes"]:
            if p["status"] != "ok":
                continue
            assert p["rows"] > 0
            assert p["duplicate_dates"] == 0
            assert p["non_positive_values"] == 0
            assert "sha256_16" in p["raw_file"]
            assert p["raw_file"]["bytes"] > 0


def test_bond_evidence_grade_l3(bond):
    assert bond["evidence_grade"] == "L3"
    assert "官方原始" in bond["evidence_grade_reason"]


# ============================================================ 时点可用性
def test_point_in_time_all_unverified(pit):
    s = pit["summary"]
    assert s["total_benchmarks"] == 15
    assert s["point_in_time_verified"] == 0
    assert s["all_unverified"] is True


def test_three_dates_not_conflated(pit):
    """三个日期必须分开定义，不得默认相同。"""
    d = pit["three_dates_definition"]
    assert "observation_date" in d
    assert "publication_date" in d
    assert "available_date" in d
    assert "不得把三者默认视为相同" in d["warning"]


def test_no_component_type_has_publication_evidence(pit):
    for t, ev in pit["evidence_by_component_type"].items():
        assert "无" in ev["publication_date"] or "不适用" in ev["publication_date"], \
            f"{t}: 不应有发布时刻证据"


def test_forward_look_bias_warned(pit):
    assert "前视偏差" in pit["forward_look_bias_warning"]


# ============================================================ 历史权重不回填
def test_no_backfill_current_weight_to_history(audit):
    """当前权重不得回填到历史（历史权重字段全空时不得声称可复现）。"""
    for b in audit["benchmarks"]:
        if not b["states"]["weight_history_verified"]:
            assert b["states"]["historically_reproducible"] is False
            assert b["earliest_reproducible_date"] is None


def test_no_change_date_means_not_reproducible(audit):
    """基准变更日期缺失时不能声称历史可复现。"""
    for b in audit["benchmarks"]:
        if b["states"]["historically_reproducible"]:
            assert b["earliest_reproducible_date"] is not None
            assert b["latest_reproducible_date"] is not None


# ============================================================ 不完整公式
def test_incomplete_formula_not_reproducible(audit):
    """有缺失成分的基准不得标 formula_reproducible。"""
    for b in audit["benchmarks"]:
        if b["states"]["formula_reproducible"]:
            assert b["states"]["history_data_available"]
            assert b["states"]["return_basis_verified"]


def test_formula_reproducible_zero(audit):
    assert audit["summary"]["formula_reproducible"] == 0
    assert audit["summary"]["historically_reproducible"] == 0


# ============================================================ 证据等级
def test_evidence_grade_declared(audit):
    assert audit["evidence_grade_definition"]["L1"]
    assert audit["evidence_grade_definition"]["L3"]
    for b in audit["benchmarks"]:
        assert b["evidence_grade"] in ("L1", "L2", "L3", "L4")


def test_all_benchmarks_are_l3(audit):
    """全部基准来源为 platform，历史审计后仍为 L3。"""
    for b in audit["benchmarks"]:
        assert b["evidence_grade"] == "L3"
        assert "未取得基金合同" in b["evidence_grade_reason"]


# ============================================================ 阻断与证据需求
def test_every_benchmark_has_blockers(audit):
    for b in audit["benchmarks"]:
        assert b["blockers"], f"{b['composite_id']} 缺阻断原因"


def test_every_benchmark_lists_required_evidence(audit):
    for b in audit["benchmarks"]:
        assert len(b["required_evidence"]) >= 4


def test_required_evidence_mentions_contract_and_weights(audit):
    for b in audit["benchmarks"]:
        joined = " ".join(b["required_evidence"])
        assert "合同" in joined or "招募说明书" in joined
        assert "变更" in joined or "生效日期" in joined


# ============================================================ 只读与门禁
def test_no_database_write():
    from app.database.db import get_connection
    with get_connection() as c:
        assert c.execute(
            "SELECT COUNT(*) FROM benchmark_composite").fetchone()[0] == 15
        assert c.execute(
            "SELECT COUNT(*) FROM benchmark_composite_component"
        ).fetchone()[0] == 34
        assert c.execute("SELECT COUNT(*) FROM index_daily").fetchone()[0] == 50603


def test_fingerprint_unchanged():
    from app.fund.ingest_user_funds import db_fingerprint
    assert db_fingerprint()["sha256"] == (
        "115ac91eee7c26424952e6df23ddeeafe2435974fe5e81a8ba6bbcabfe387dd4")


def test_no_vacuous_assertion():
    src = Path(__file__).read_text(encoding="utf-8")
    bad = "or " + "True"
    for ln in src.splitlines():
        st = ln.strip()
        if st.startswith("#") or st.startswith('"') or st.startswith("'"):
            continue
        assert bad not in ln, f"恒真断言：{st}"


# ============================================================ 文本一致性分级
def test_text_consistency_classified(audit):
    """每条基准必须有明确的文本一致性分类。"""
    valid = {"identical", "char_diff_only", "order_diff_only", "semantic_diff"}
    for b in audit["benchmarks"]:
        assert b["text_consistency"]["classification"] in valid


def test_semantic_diff_count_matches_detail(audit):
    s = audit["summary"]
    recalc = sum(1 for b in audit["benchmarks"]
                 if b["text_consistency"]["classification"] == "semantic_diff")
    assert s["text_semantic_diff_count"] == recalc
    assert sorted(s["text_semantic_diff_ids"]) == sorted(
        b["composite_id"] for b in audit["benchmarks"]
        if b["text_consistency"]["classification"] == "semantic_diff")


def test_tax_status_conflict_documented(audit):
    """000478 的税前/税后冲突必须被识别为语义不同。"""
    b = next(x for x in audit["benchmarks"] if x["composite_id"] == 20)
    assert b["text_consistency"]["classification"] == "semantic_diff"
    assert "税后" in b["benchmark_raw_text"]
    assert "税前" in b["fund_master_benchmark_text"]


def test_deposit_type_conflict_documented(audit):
    """050002 的活期/同业存款冲突必须被识别为语义不同。"""
    b = next(x for x in audit["benchmarks"] if x["composite_id"] == 22)
    assert b["text_consistency"]["classification"] == "semantic_diff"
    assert "活期存款" in b["benchmark_raw_text"]
    assert "同业存款" in b["fund_master_benchmark_text"]


def test_identical_benchmarks_also_recorded(audit):
    """完全一致的基准也要如实记录，不能只记异常。"""
    identical = [b for b in audit["benchmarks"]
                 if b["text_consistency"]["classification"] == "identical"]
    assert len(identical) == audit["summary"]["text_identical_count"]
    for b in identical:
        assert b["benchmark_raw_text"] == b["fund_master_benchmark_text"]


# ============================================================ 3B-6.1.2.1 新增
STATES_V2 = [
    "component_identified", "weight_text_evidence_present", "weight_verified",
    "weight_history_verified", "return_basis_verified",
    "history_data_available", "point_in_time_verified",
    "formula_reproducible", "historically_reproducible",
]


def test_component_category_counts_exact(audit, comp):
    """34 条成分分类必须严格为 index 18 / bond_index 5 / cash 10 / fixed_rate 1。"""
    from collections import Counter
    cnt = Counter(c["component_category"] for c in comp["components"])
    assert cnt["index"] == 18
    assert cnt["bond_index"] == 5
    assert cnt["cash"] == 10
    assert cnt["fixed_rate"] == 1
    assert sum(cnt.values()) == 34
    assert audit["summary"]["components_by_category"] == {
        "index": 18, "bond_index": 5, "cash": 10, "fixed_rate": 1}


def test_cash_and_fixed_rate_not_merged(audit, comp):
    """fixed_rate 不得计入 cash。"""
    cash = [c for c in comp["components"] if c["component_category"] == "cash"]
    fixed = [c for c in comp["components"]
             if c["component_category"] == "fixed_rate"]
    assert len(cash) == 10
    assert len(fixed) == 1
    assert not set(c["component_id"] for c in cash) & \
        set(c["component_id"] for c in fixed)
    # 000051 的 fixed_rate 必须是独立类别
    fr = fixed[0]
    assert fr["composite_id"] == 16
    assert fr["component_name"] == "fixed_rate"


def test_l3_weight_not_upgraded_to_official(audit, comp):
    """L3 权重文本不得自动升级为官方权重验证。"""
    assert audit["summary"]["weight_text_evidence_present"] == 15
    assert audit["summary"]["weight_verified"] == 0
    for c in comp["components"]:
        assert c["weight_evidence_grade"] == "L3"
        assert c["weight_official_contract_evidence"] is False
        assert c["weight_text_evidence_present"] is True


def test_weight_three_states_distinguished(audit):
    """三种权重状态必须分别记录。"""
    s = audit["summary"]
    assert s["weight_text_evidence_present"] == 15   # 有第三方文本
    assert s["weight_verified"] == 0                 # 无官方合同证据
    assert s["weight_history_verified"] == 0         # 无历史权重


def test_summary_detail_all_consistent(audit):
    """所有 summary 计数必须可由明细复算。"""
    s = audit["summary"]
    bm = audit["benchmarks"]
    for k in STATES_V2:
        recalc = sum(1 for b in bm if b["states"][k])
        assert s[k] == recalc, f"{k}: summary={s[k]} 复算={recalc}"
    assert s["total_benchmarks"] == len(bm) == 15
    assert s["total_components"] == sum(b["component_count"] for b in bm) == 34


def test_semantic_conflict_ids_exact(audit):
    """语义冲突必须正好是 ID 18/20/22/23。"""
    assert audit["summary"]["text_semantic_diff_count"] == 4
    assert sorted(audit["summary"]["text_semantic_diff_ids"]) == [18, 20, 22, 23]
    actual = sorted(b["composite_id"] for b in audit["benchmarks"]
                    if b["text_consistency"]["classification"] == "semantic_diff")
    assert actual == [18, 20, 22, 23]


def test_formula_requires_all_conditions(audit):
    """公式可复现必须同时满足全部必要条件。"""
    for b in audit["benchmarks"]:
        fc = b["formula_conditions"]
        assert set(fc) == {
            "all_components_identified", "all_weights_official",
            "all_component_data_available", "return_basis_verified",
            "formula_rules_explicit", "fixed_rate_conversion_known",
            "no_missing_cash_bond_index_component"}
        assert b["states"]["formula_reproducible"] == all(fc.values())


def test_formula_not_hardcoded_false(audit):
    """不可复现必须由具体失败条件得出，不是硬编码。"""
    for b in audit["benchmarks"]:
        fc = b["formula_conditions"]
        failed = [k for k, v in fc.items() if not v]
        assert failed, f"{b['composite_id']} 无失败条件却被判不可复现"
        assert b["states"]["formula_reproducible"] is False


def test_historical_reproducible_requires_more(audit):
    """历史可复现的附加条件必须存在且真实判定。"""
    for b in audit["benchmarks"]:
        hc = b["historically_reproducible_conditions"]
        for k in ("weight_history_verified", "benchmark_change_traceable",
                  "point_in_time_verified", "historical_component_data_available"):
            assert k in hc
        assert b["states"]["historically_reproducible"] == all(hc.values())


def test_weight_history_missing_blocks_historical(audit):
    """历史权重缺失时不得判历史可复现。"""
    for b in audit["benchmarks"]:
        if not b["historically_reproducible_conditions"]["weight_history_verified"]:
            assert b["states"]["historically_reproducible"] is False


# ============================================================ 债券成分关联
def test_bond_used_by_composite_ids_real(bond):
    """composite_id 必须真实存在于正式库。"""
    from app.database.db import get_connection
    with get_connection() as c:
        valid = {r[0] for r in c.execute(
            "SELECT composite_id FROM benchmark_composite").fetchall()}
    for t in bond["targets"]:
        assert t["used_by_composite_ids"], f"{t['contract_label']} 无 composite_id"
        for cid in t["used_by_composite_ids"]:
            assert cid in valid, f"{cid} 不是真实 composite_id"
            assert cid >= 16, f"{cid} 看起来像基金代码"


def test_bond_fund_codes_keep_leading_zero(bond):
    """001938 不得丢前导零。"""
    t = next(x for x in bond["targets"] if x["contract_label"] == "中证综合债券")
    assert t["used_by_fund_codes"] == ["001938"]
    assert all(len(c) == 6 for x in bond["targets"]
               for c in x["used_by_fund_codes"])


def test_bond_fund_code_matches_composite(bond):
    """fund_code 与 composite_id 必须一一对应。"""
    from app.database.db import get_connection
    with get_connection() as c:
        rows = c.execute(
            "SELECT composite_id, benchmark_name FROM benchmark_composite"
        ).fetchall()
    mapping = {r[0]: r[1].split(" ")[0] for r in rows}
    for t in bond["targets"]:
        for cid, code in zip(t["used_by_composite_ids"], t["used_by_fund_codes"]):
            assert mapping[cid] == code, f"{cid}: {mapping[cid]} != {code}"


def test_bond_no_fund_code_as_composite_id(bond):
    """不得把基金代码误当 composite_id。"""
    for t in bond["targets"]:
        for cid in t["used_by_composite_ids"]:
            assert isinstance(cid, int)
            assert cid not in (110022, 161005, 1938, 12346, 12344)


# ============================================================ 报告与 JSON 一致性
DOCS = [
    REPORTS / "phase3B6_1_2_design.md",
    REPORTS / "phase3B6_1_2_recommendation.md",
]


def _read_docs() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in DOCS)


def test_docs_no_stale_weight_verified_15(audit):
    """报告不得残留「weight_verified = 15/15」的旧统计。"""
    txt = _read_docs()
    assert "weight_verified` | **15/15**" not in txt
    assert audit["summary"]["weight_verified"] == 0


def test_docs_semantic_conflict_ids(audit):
    """报告中的语义冲突 ID 必须与明细一致。"""
    txt = _read_docs()
    ids = audit["summary"]["text_semantic_diff_ids"]
    assert str(sorted(ids)) in txt or "18, 20, 22, 23" in txt


def test_docs_no_stale_six_conflicts():
    """不得残留「6 条语义冲突」的旧统计。"""
    txt = _read_docs()
    assert "语义实质不同** | **6/15" not in txt
    assert "实质不同的 6 条" not in txt


def test_docs_component_category_numbers(audit):
    """报告必须写明 index 18 / bond_index 5 / cash 10 / fixed_rate 1。"""
    txt = _read_docs()
    import re as _re
    for cat, n in (("index", 18), ("bond_index", 5), ("cash", 10),
                    ("fixed_rate", 1)):
        pat = r"`" + cat + r"`\s*\|\s*\**" + str(n) + r"\**"
        assert _re.search(pat, txt), f"缺 {cat}={n}"


def test_docs_fixed_rate_not_in_cash():
    """报告必须明确 fixed_rate 不计入 cash。"""
    txt = _read_docs()
    assert "固定年化收益率" in txt
    assert "不计入 `cash`" in txt or "不得计入 `cash`" in txt


# ============================================================ 证据检索记录
def test_evidence_search_log_exists():
    p = REPORTS / "evidence" / "phase3B6_1_2" / "evidence_search_log.json"
    assert p.exists(), "缺原始证据检索记录"


def test_evidence_log_no_fake_download():
    p = REPORTS / "evidence" / "phase3B6_1_2" / "evidence_search_log.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["summary"]["documents_obtained"] == 0
    assert d["summary"]["funds_with_l1_evidence"] == 0
    for f in d["funds_document_status"]:
        assert f["document_obtained"] is False
        assert f["sha256"] is None, "未下载文件不得填写 SHA256"
        assert f["current_evidence_grade"] == "L3"


def test_evidence_log_channels_really_probed():
    p = REPORTS / "evidence" / "phase3B6_1_2" / "evidence_search_log.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    assert len(d["channels_probed"]) == 5
    for ch in d["channels_probed"]:
        assert ch["url"].startswith("http")
        assert ch["probed_at"]
        assert ch["reachable"] is True
        assert ch["http_status"] == 200


def test_evidence_log_covers_all_15_funds():
    p = REPORTS / "evidence" / "phase3B6_1_2" / "evidence_search_log.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    assert len(d["funds_document_status"]) == 15
    codes = {f["fund_code"] for f in d["funds_document_status"]}
    assert len(codes) == 15


# ============================================================ 3B-6.1.2.1.1
def test_docs_no_stale_cash_fixed_count():
    """报告不得残留「16 个现金/固定成分」的旧描述。"""
    txt = _read_docs()
    assert "16 个现金/固定成分" not in txt
    assert "16个现金" not in txt


def test_docs_no_blanket_cash_statement():
    """不得声称「每条基准都有 5%~10% 的现金类成分」。"""
    txt = _read_docs()
    # 允许出现在「不能说」的否定语境里，但不能作为断言出现
    for line in txt.splitlines():
        if "5%~10%" in line or "5%～10%" in line:
            assert ("不能说" in line or "不得" in line or "**" in line), \
                f"出现未经限定的现金比例断言：{line}"


def test_docs_cash_fixed_separately_stated():
    """报告必须明确 fixed_rate 不属于 cash。"""
    txt = _read_docs()
    assert "`fixed_rate` 不属于 `cash`" in txt or \
        "`fixed_rate`（1 个）不得计入 `cash`" in txt


def test_docs_category_numbers_match_detail(audit, comp):
    """报告分类数字必须与 34 条明细一致。"""
    from collections import Counter
    cnt = Counter(c["component_category"] for c in comp["components"])
    txt = _read_docs()
    import re as _re
    for cat, n in cnt.items():
        pat = r"`" + cat + r"`\s*\|\s*\**" + str(n) + r"\**"
        assert _re.search(pat, txt), f"报告中缺 {cat}={n}"


def test_docs_unexplained_residual_not_inferred():
    """000051 剩余 5% 不得被推断为现金或其他资产。"""
    txt = _read_docs()
    assert "不得推断" in txt or "没有说明" in txt
