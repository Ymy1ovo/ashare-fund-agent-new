"""阶段3B-6.2.3.0 官方证据获取与覆盖率审计专项测试。

**直接调用真实审计逻辑与真实证据文件**，不使用预计算数字自证。
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.audit_3b6_2_3_0_evidence import (  # noqa: E402
    INDEX_CODES, compare_with_l3, extract_benchmark, judge_basis,
    normalize_benchmark)

REPORTS = ROOT / "reports"
EVID = REPORTS / "evidence" / "phase3B6_2_3_0"
IDX_JSON = REPORTS / "phase3B6_2_3_0_index_evidence.json"
FUND_JSON = REPORTS / "phase3B6_2_3_0_fund_contract_audit.json"

SHA_RE = re.compile(r"^[0-9a-f]{64}$")


@pytest.fixture(scope="module")
def idx() -> dict:
    assert IDX_JSON.exists(), "缺指数证据 JSON"
    return json.loads(IDX_JSON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fund() -> dict:
    assert FUND_JSON.exists(), "缺基金合同审计 JSON"
    return json.loads(FUND_JSON.read_text(encoding="utf-8"))


# ============================================================ 数量一致性
def test_index_count_matches_detail(idx):
    """10 个指数数量与明细一致。"""
    assert idx["indexes"] and len(idx["indexes"]) == 10
    codes = [r["index_code"] for r in idx["indexes"]]
    assert sorted(codes) == sorted(INDEX_CODES)
    assert len(set(codes)) == 10


def test_fund_count_matches_detail(fund):
    """78 只基金数量与明细一致。"""
    assert fund["summary"]["fund_summary"]["total_funds"] == 78
    assert len(fund["funds"]) == 78
    ids = [r["fund_id"] for r in fund["funds"]]
    assert len(set(ids)) == 78, "A/C 份额必须按 fund_id 去重"


def test_fund_codes_unique(fund):
    codes = [r["fund_code"] for r in fund["funds"]]
    assert len(set(codes)) == len(codes)


# ============================================================ SHA256
def test_all_sha256_are_64_hex(idx, fund):
    """所有已获取文件的 SHA256 必须是完整 64 位。"""
    n = 0
    for r in idx["indexes"]:
        s = r["document"].get("sha256")
        if s:
            assert SHA_RE.match(s), f"{r['index_code']} SHA256 非 64 位：{s}"
            n += 1
    for r in fund["funds"]:
        s = r.get("sha256")
        if s:
            assert SHA_RE.match(s), f"{r['fund_code']} SHA256 非 64 位：{s}"
            n += 1
    assert n > 0, "没有任何 SHA256，审计未真实下载"


def test_sha256_matches_actual_file(idx, fund):
    """JSON 记录的 SHA256 必须与磁盘文件实际哈希一致。"""
    checked = 0
    for r in idx["indexes"] + fund["funds"]:
        doc = r.get("document") or r.get("current_contract") or {}
        rel = doc.get("file")
        if not rel or not doc.get("sha256"):
            continue
        p = ROOT / rel
        assert p.exists(), f"证据文件缺失：{rel}"
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        assert actual == doc["sha256"], f"{rel} SHA256 不符"
        checked += 1
    assert checked > 0


def test_no_sha256_without_real_file(idx, fund):
    """未真实下载到的文件不得填写 SHA256。"""
    for r in idx["indexes"]:
        d = r["document"]
        if d.get("sha256"):
            assert d.get("file") and (ROOT / d["file"]).exists()
    for r in fund["funds"]:
        c = r.get("current_contract") or {}
        if c.get("sha256"):
            assert c.get("file") and (ROOT / c["file"]).exists()


# ============================================================ 证据等级
def test_no_l1_without_official_source(idx, fund):
    """无官方来源的文件不得标 L1。"""
    OFFICIAL_HOSTS = ("oss-ch.csindex.com.cn", "cdn.efunds.com.cn",
                      "static.cninfo.com.cn")
    for r in idx["indexes"]:
        d = r["document"]
        if d.get("evidence_grade") == "L1":
            url = d.get("url") or ""
            assert any(h in url for h in OFFICIAL_HOSTS), \
                f"{r['index_code']} 标 L1 但来源非官方：{url}"
            assert d.get("sha256"), "L1 证据必须有 SHA256"
    for r in fund["funds"]:
        if r.get("evidence_grade") == "L1":
            c = r.get("current_contract") or {}
            assert c.get("obtained") and c.get("readable")
            assert SHA_RE.match(c.get("sha256") or ""), "L1 必须有 64 位 SHA256"


def test_unknown_basis_not_upgraded(idx):
    """没有官方证据不得升级 return_basis。"""
    for r in idx["indexes"]:
        j = r["return_basis_judgement"]
        if not j["basis_confirmed"]:
            assert j["return_basis"] == "unknown", \
                f"{r['index_code']} 无明文依据却给了 {j['return_basis']}"
            assert r["return_basis_confirmed"] is False
        else:
            assert j["evidence"], "确认口径必须给出明文依据"


def test_930930_stays_unknown(idx):
    """930930 官方单张未明文说明主序列口径 → 必须保持 unknown。"""
    rec = next(r for r in idx["indexes"] if r["index_code"] == "930930")
    assert rec["return_basis_judgement"]["return_basis"] == "unknown"
    assert rec["return_basis_confirmed"] is False


def test_confirmed_requires_both_conditions(idx):
    """口径确认必须同时满足「官方口径确认」+「序列代码匹配」。"""
    for r in idx["indexes"]:
        j = r["return_basis_judgement"]
        expect = bool(j["basis_confirmed"]
                      and r["data_series_matches_official"])
        assert r["return_basis_confirmed"] is expect


# ============================================================ 历史版本
def test_current_contract_not_history(fund):
    """不得用当前文件冒充历史版本（同类文档内比较）。"""
    for r in fund["funds"]:
        c = r.get("current_contract") or {}
        if not c.get("obtained"):
            continue
        for h in r.get("history_versions") or []:
            assert h.get("url") != c.get("url"), \
                f"{r['fund_code']} 历史版本与当前版本 URL 相同"
            # 只在**同一文档类型**内比较：招募说明书可以比合同更新
            if h.get("doc_type") != c.get("doc_type"):
                continue
            hd, cd = h.get("date"), c.get("disclosed_date")
            if hd and cd:
                assert hd <= cd, \
                    f"{r['fund_code']} 同类历史版本日期晚于当前版本"


def test_history_versions_recorded_separately(fund):
    """历史版本必须单独记录，不混入当前版本。"""
    for r in fund["funds"]:
        assert "history_versions" in r
        assert isinstance(r["history_versions"], list)


# ============================================================ 覆盖率汇总
def test_index_summary_matches_detail(idx, fund):
    """指数汇总必须与明细一致。"""
    s = fund["summary"]["index_summary"]
    assert s["total_indexes"] == len(idx["indexes"])
    assert s["return_basis_confirmed"] == sum(
        1 for r in idx["indexes"] if r["return_basis_confirmed"])
    assert s["series_matches_official"] == sum(
        1 for r in idx["indexes"] if r["data_series_matches_official"])
    assert (s["return_basis_confirmed"] + s["return_basis_still_unknown"]
            == s["total_indexes"])


def test_fund_summary_matches_detail(fund):
    """基金汇总必须与明细一致。"""
    s = fund["summary"]["fund_summary"]
    recs = fund["funds"]
    assert s["l1_contract_obtained"] == sum(
        1 for r in recs if r["contract_found"])
    assert s["prospectus_only"] == sum(
        1 for r in recs if r["prospectus_found"] and not r["contract_found"])
    assert s["still_l3_only"] == sum(
        1 for r in recs if not r["contract_found"]
        and not r["prospectus_found"])
    assert (s["l1_contract_obtained"] + s["prospectus_only"]
            + s["still_l3_only"] == s["total_funds"])
    assert s["text_conflict_with_l3"] == sum(
        1 for r in recs if r.get("text_consistent_with_l3") is False)


def test_self_check_all_pass(fund):
    sc = fund["summary"]["_self_check"]
    for k, v in sc.items():
        assert v is True, f"自校验失败：{k}"


# ============================================================ 口径判定逻辑
def test_judge_basis_needs_explicit_text():
    """无明文依据时 judge_basis 必须返回 unknown。"""
    out = judge_basis("本指数由若干证券组成，反映市场表现。", "编制方案")
    assert out["return_basis"] == "unknown"
    assert out["basis_confirmed"] is False


def test_judge_basis_hs300_rule():
    """沪深300「除息不予修正」明文 → price。"""
    text = "除息：凡有样本除息（分红派息），沪深300指数不予修正，任其自然回落"
    out = judge_basis(text, "编制方案")
    assert out["return_basis"] == "price"
    assert out["evidence"]


def test_judge_basis_formula_rule():
    """仅用证券价格×调整股本数、无再投资表述 → price。"""
    text = ("四、指数计算 调整市值＝∑(证券价格×调整股本数)。"
            "调整股本数的计算方法、除数修正方法参见计算与维护细则。")
    out = judge_basis(text, "编制方案")
    assert out["return_basis"] == "price"


def test_judge_basis_bond_derivatives():
    """债券单张列出净价/再投资为衍生指数 → 主序列 full_price。"""
    text = "净价指数 代码 利息再投资 指数 代码 N00012 上证国债指数"
    out = judge_basis(text, "指数单张（Factsheet）")
    assert out["return_basis"] == "full_price"


def test_judge_basis_factsheet_without_text_is_unknown():
    """单张无明文 → unknown（不得凭衍生指数推断主序列）。"""
    out = judge_basis("全收益指数 代码 H20930 净收益指数 代码 --",
                      "指数单张（Factsheet）")
    assert out["return_basis"] == "unknown"


# ============================================================ 文本比对
def test_normalize_handles_x_as_multiply():
    assert normalize_benchmark("沪深300指数收益率X95%") == \
        normalize_benchmark("沪深300指数收益率×95%")


def test_compare_detects_weight_conflict():
    """权重成分不一致必须判为冲突，不能因「包含」就判一致。"""
    ct = ("业绩比较基准：沪深300指数收益率*90%+中债-国债总全价(1-3年)"
          "指数收益率*5%+同业存款利率*5%")
    l3 = "沪深300指数收益率*70%+中债综合全价指数收益率*25%+同业存款利率*5%"
    out = compare_with_l3(ct, l3)
    assert out["comparable"] is True
    assert out["consistent"] is False
    assert out["l3_weights"] != out["contract_weights"]


def test_compare_consistent_when_identical():
    ct = "业绩比较基准：中证白酒指数收益率*95%+活期存款利率(税后)*5%。"
    l3 = "中证白酒指数收益率×95%+活期存款利率(税后)×5%"
    out = compare_with_l3(ct, l3)
    assert out["consistent"] is True


def test_compare_not_found_is_conflict():
    out = compare_with_l3("业绩比较基准：中证白酒指数收益率*95%",
                          "沪深300指数收益率*95%")
    assert out["consistent"] is False


# ============================================================ 基准条款提取
def test_extract_rejects_tracking_sentence():
    """「业绩比较基准的紧密跟踪……」不含基准定义，必须排除。"""
    text = ("业绩比较基准的紧密跟踪，在正常市场情况下，力争本基金的"
            "净值增长率与业绩衡量基准之间的年化跟踪误差控制在4%以内。")
    out = extract_benchmark(text)
    assert out["found"] is False


def test_extract_accepts_definition_sentence():
    text = ("业绩比较基准为：沪深300指数收益率*95%+活期存款利率(税后)*5%。"
            "未来若出现标的指数不符合法律法规……")
    out = extract_benchmark(text)
    assert out["found"] is True
    assert "沪深300指数收益率" in out["primary"]


# ============================================================ 真实文件存在
def test_evidence_files_exist(idx, fund):
    """所有记录的证据文件必须真实存在于仓库。"""
    n = 0
    for r in idx["indexes"]:
        rel = r["document"].get("file")
        if rel:
            assert (ROOT / rel).exists(), f"缺文件 {rel}"
            assert (ROOT / rel).read_bytes()[:4] == b"%PDF"
            n += 1
    for r in fund["funds"]:
        c = r.get("current_contract") or {}
        if c.get("file"):
            assert (ROOT / c["file"]).exists()
            assert (ROOT / c["file"]).read_bytes()[:4] == b"%PDF"
            n += 1
    assert n >= 19, f"证据文件过少：{n}"


def test_evidence_index_not_l3(idx):
    """指数证据等级不得为 L3（必须来自官方机构）。"""
    for r in idx["indexes"]:
        g = r["document"].get("evidence_grade")
        assert g == "L1", f"{r['index_code']} 证据等级 {g} 非 L1"


# ============================================================ 门禁与边界
def test_gates_unchanged(fund):
    g = fund["summary"]["gates"]
    assert g["at_least_one_index_basis_l1"] is True
    assert g["at_least_one_fund_l1_contract"] is True
    assert g["ready_for_3b6_2_3_1_series_build"] is False, \
        "官方口径确认不等于可建收益序列"


def test_no_vacuous_assertion():
    """不得出现恒真断言。"""
    txt = Path(__file__).read_text(encoding="utf-8")
    assert ("or " + "True") not in txt
    assert ("assert " + "True") not in txt


def test_docs_exist_and_gates():
    for name in ("phase3B6_2_3_0_design.md",
                 "phase3B6_2_3_0_coverage_report.md",
                 "phase3B6_2_3_0_recommendation.md"):
        p = REPORTS / name
        assert p.exists(), f"缺文档 {name}"
        t = p.read_text(encoding="utf-8")
        assert "ready_for_backtest" in t
        assert "false" in t.lower()


def test_docs_coverage_matches_json(idx, fund):
    """文档中的覆盖率数字必须与 JSON 一致。"""
    txt = (REPORTS / "phase3B6_2_3_0_coverage_report.md").read_text(
        encoding="utf-8")
    isum = fund["summary"]["index_summary"]
    fsum = fund["summary"]["fund_summary"]
    assert str(isum["return_basis_confirmed"]) in txt
    assert str(fsum["l1_contract_obtained"]) in txt
    assert str(fsum["still_l3_only"]) in txt
    assert str(fsum["total_funds"]) in txt


def test_004746_contract_obtained(fund):
    """004746 已取得 L1 合同原件，且合同基准含 80% 上证50 + 20% 上证国债。"""
    rec = next(r for r in fund["funds"] if r["fund_code"] == "004746")
    assert rec["contract_found"] is True
    assert rec["evidence_grade"] == "L1"
    prim = rec["current_contract"]["benchmark_excerpt"]["primary"]
    assert "上证50指数收益率" in prim
    assert "80" in prim and "20" in prim


def test_161005_conflict_recorded(fund):
    """161005 的 L3 文本与合同原件冲突，必须如实记录。"""
    rec = next(r for r in fund["funds"] if r["fund_code"] == "161005")
    assert rec["contract_found"] is True
    assert rec["text_consistent_with_l3"] is False
    tc = rec["text_comparison"]
    assert tc["l3_weights"] != tc["contract_weights"]


def test_000012_multi_series_distinguished(idx):
    """000012 必须与 H00012/N00012 区分，口径为全价而非净价/再投资。"""
    rec = next(r for r in idx["indexes"] if r["index_code"] == "000012")
    assert rec["return_basis_judgement"]["return_basis"] == "full_price"
    assert rec["series_probe"]["returned_code"] == "000012"
    assert rec["series_probe"]["returned_full_name"] == "上证国债指数"
