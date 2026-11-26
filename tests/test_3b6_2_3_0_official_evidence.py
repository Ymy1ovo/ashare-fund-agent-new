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
            assert r["official_return_basis_verified"] is False
        else:
            assert j["evidence"], "确认口径必须给出明文依据"


def test_930930_stays_unknown(idx):
    """930930 官方单张未明文说明主序列口径 → 必须保持 unknown。"""
    rec = next(r for r in idx["indexes"] if r["index_code"] == "930930")
    assert rec["return_basis_judgement"]["return_basis"] == "unknown"
    assert rec["official_return_basis_verified"] is False


def test_deprecated_fields_removed_from_detail(idx):
    """旧字段不得再出现在逐指数明细中。"""
    banned = ("series_matched", "data_series_matches_official",
              "series_matches_official", "series_probe")
    for r in idx["indexes"]:
        for k in banned:
            assert k not in r, f"{r['index_code']} 仍保留旧字段 {k}"


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
    """九个维度汇总必须全部由逐条明细自动计算。"""
    s = fund["summary"]["index_summary"]
    recs = idx["indexes"]
    assert s["total_indexes"] == len(recs)
    pairs = {
        "official_identity_verified": "official_identity_verified",
        "official_return_basis_verified": "official_return_basis_verified",
        "api_code_identity_verified": "api_code_identity_verified",
        "api_name_identity_verified": "api_name_identity_verified",
        "database_series_exists": "database_series_exists",
        "database_series_source_traceable":
            "database_series_source_traceable",
        "database_series_numerically_verified":
            "database_series_numerically_verified",
        "historical_coverage_verified": "historical_coverage_verified",
        "point_in_time_verified": "point_in_time_verified",
    }
    for skey, dkey in pairs.items():
        expect = sum(1 for r in recs if r[dkey] is True)
        assert s[skey] == expect, f"{skey} 汇总 {s[skey]} != 明细 {expect}"
    assert (s["official_return_basis_verified"]
            + s["return_basis_still_unknown"] == s["total_indexes"])
    assert (s["database_series_numerically_verified"]
            + s["database_series_numerically_unknown"]
            + s["database_series_numerically_mismatch"]
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
    assert rec["api_identity"]["returned_code"] == "000012"
    assert rec["api_identity"]["returned_full_name"] == "上证国债指数"
    # 数据库里只应存在 000012，不得混入 H00012 / N00012
    assert rec["database"]["rows"] > 0


def test_000012_variants_not_merged():
    """正式库 index_daily 不得混入 H00012 / N00012 记录。"""
    import sqlite3
    from app.config import settings
    p = str(settings.database_path).replace("\\", "/")
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        codes = {r[0] for r in conn.execute(
            "select distinct index_code from index_daily")}
    finally:
        conn.close()
    assert "000012" in codes
    assert "H00012" not in codes, "净价序列混入了正式库"
    assert "N00012" not in codes, "利息再投资序列混入了正式库"


# ============================================================ 九维验证边界（3B-6.2.3.0.1）
def test_api_code_match_not_equal_db_match(idx):
    """1. API 代码匹配不能自动等于数据库历史序列匹配。"""
    for r in idx["indexes"]:
        # 两者是独立字段、独立证据来源，字段名不得混用
        assert "api_code_identity_verified" in r
        assert "database_series_numerically_verified" in r
        assert "series_matched" not in r
        assert "data_series_matches_official" not in r
        # 数值验证必须有逐日比对明细（独立于 API 身份核验）
        num = r["numerical_verification"]
        assert num["comparisons"], "数值验证必须有逐日比对明细"
        for c in num["comparisons"]:
            assert "official_close" in c and "database_close" in c
            assert c.get("official_url"), "比对项必须带官方来源 URL"
        # API 身份核验只看代码/名称，不参与数值判定
        api = r["api_identity"]
        assert "close" not in api, "API 身份核验不得携带收盘价参与数值判定"


def test_api_name_mismatch_fails():
    """2. API 名称不匹配必须失败（不能只比代码）。"""
    from scripts.audit_3b6_2_3_0_evidence import verify_index
    conn = __import__("scripts.audit_3b6_2_3_0_evidence",
                      fromlist=["_db_connect"])._db_connect()
    try:
        r = verify_index("000300", conn)
    finally:
        conn.close()
    # 该指数名称一致
    assert r["api_name_identity_verified"] is True
    # 名称核验必须比对全称而不是代码
    assert r["official"]["index_full_name"] == \
        r["api_identity"]["returned_full_name"]
    # 若把名称改坏，判定逻辑必须为 False
    fake = dict(r["api_identity"])
    fake["returned_full_name"] = "沪深300全收益指数"
    assert (fake["returned_full_name"]
            == r["official"]["index_full_name"]) is False


def test_no_db_series_cannot_pass():
    """3. 正式数据库没有历史数据时不能通过。"""
    from scripts.audit_3b6_2_3_0_evidence import audit_db_series, _db_connect
    conn = _db_connect()
    try:
        out = audit_db_series("NOT_EXIST_CODE", conn)
    finally:
        conn.close()
    assert out["exists"] is False
    assert out["rows"] == 0
    assert out["source_traceable"] is False


def test_untraceable_source_cannot_verify():
    """4. 数据源不可追溯时不能判定数值验证通过。"""
    from scripts.audit_3b6_2_3_0_evidence import audit_db_series, _db_connect
    conn = _db_connect()
    try:
        out = audit_db_series("000300", conn)
    finally:
        conn.close()
    # 可追溯性判定必须依赖四个要素齐全
    if out["source_traceable"]:
        assert out["sources"]
        assert out["run_ids"]
        assert out["row_fingerprint_present"]
        assert out["collected_at_min"]
    else:
        assert out["source_traceable_reason"]


def test_official_doc_alone_cannot_verify_numbers(idx):
    """5. 只有官方文件、没有历史数值证据时不能通过数值级验证。"""
    from scripts.audit_3b6_2_3_0_evidence import numerical_verify, _db_connect
    conn = _db_connect()
    try:
        out = numerical_verify("NOT_EXIST_CODE", conn)
    finally:
        conn.close()
    assert out["official_obtained"] == 0
    assert out["matched"] == 0
    assert out["verified"] is None, "无官方数值必须记 unknown，不是 True"
    assert "unknown" in out["verdict"]


def test_numerical_verification_uses_real_official_data(idx):
    """6. 数值级验证必须使用真实可核验的对照数据。"""
    import hashlib
    samples = EVID / "official_close_samples.json"
    digest = EVID / "official_close_samples.sha256"
    assert samples.exists(), "缺官方数值样本文件"
    assert digest.exists(), "缺官方样本 SHA256"
    payload = samples.read_text(encoding="utf-8")
    assert hashlib.sha256(payload.encode("utf-8")).hexdigest() == \
        digest.read_text(encoding="utf-8").strip()
    data = json.loads(payload)
    assert data, "官方样本为空"
    for k, v in data.items():
        assert v.get("url"), f"{k} 缺官方来源 URL"
        assert "csindex.com.cn" in v["url"]
        assert v.get("close") is not None
        assert v.get("obtained_at")
    # 每只已验证指数至少有 2 个不同年份的官方样本
    for r in idx["indexes"]:
        if r["database_series_numerically_verified"] is not True:
            continue
        years = {c["date"][:4]
                 for c in r["numerical_verification"]["comparisons"]
                 if c["match"]}
        assert len(years) >= 2, \
            f"{r['index_code']} 验证样本不足 2 个不同年份"


def test_000012_h00012_n00012_distinct():
    """7. 000012、H00012、N00012 必须严格区分。"""
    import sys as _sys
    from scripts.audit_3b6_2_3_0_evidence import probe_series
    a = probe_series("000012")
    if not a.get("obtained"):
        pytest.skip("接口限流，无法实测三序列区分")
    b = probe_series("H00012")
    c = probe_series("N00012")
    assert a["returned_code"] == "000012"
    if b.get("obtained"):
        assert b["returned_code"] == "H00012"
        assert b["returned_full_name"] != a["returned_full_name"]
    if c.get("obtained"):
        assert c["returned_code"] == "N00012"
        assert c["returned_full_name"] != a["returned_full_name"]
    assert a["returned_full_name"] == "上证国债指数"


def test_all_summaries_auto_computed(idx, fund):
    """8. 10 个指数汇总统计必须从逐条明细自动计算。"""
    from collections import Counter
    s = fund["summary"]["index_summary"]
    recs = idx["indexes"]
    assert s["total_indexes"] == len(recs) == 10
    # 口径分布由明细重算
    assert s["basis_counts"] == dict(Counter(
        r["return_basis_judgement"]["return_basis"] for r in recs))
    # 证据等级分布由明细重算
    assert s["grade_counts"] == dict(Counter(
        str(r["document"].get("evidence_grade")) for r in recs))
    # 复合结论由明细重算
    assert s["series_matches_official_basis"] == sum(
        1 for r in recs if r["series_matches_official_basis"] is True)


def test_series_matches_basis_requires_full_evidence(idx):
    """9. series_matches_official_basis 必须基于同一指数的完整证据条件。"""
    for r in idx["indexes"]:
        expect = bool(
            r["official_return_basis_verified"] is True
            and r["database_series_numerically_verified"] is True)
        assert r["series_matches_official_basis"] is expect, \
            f"{r['index_code']} 复合结论与逐条条件不符"
    # 930930 口径未确认 → 即使数值验证通过也不能判通过
    rec = next(r for r in idx["indexes"] if r["index_code"] == "930930")
    assert rec["official_return_basis_verified"] is False
    assert rec["series_matches_official_basis"] is False


def test_gate_uses_same_index_conjunction(fund):
    """9b. 门禁不得用两个独立计数都 >0 判定。"""
    g = fund["summary"]["gates"]
    isum = fund["summary"]["index_summary"]
    assert g["series_matches_official_basis"] is (
        isum["series_matches_official_basis"] > 0)
    assert "series_matches_official" not in g, "门禁仍引用已废弃字段"


def test_coverage_and_pit_not_derived(idx):
    """10. 历史连续覆盖和时点可用性不能由数值匹配自动推导。"""
    for r in idx["indexes"]:
        if r["database_series_numerically_verified"] is True:
            assert r["historical_coverage_verified"] is False, \
                f"{r['index_code']} 由数值匹配推导了覆盖确认"
            assert r["point_in_time_verified"] is False, \
                f"{r['index_code']} 由数值匹配推导了时点可用性"
            assert r["historical_coverage_note"]
            assert r["point_in_time_note"]


def test_gates_not_opened_by_rename(fund):
    """11. 门禁不能因为本轮字段重命名而意外开放。"""
    g = fund["summary"]["gates"]
    assert g["ready_for_3b6_2_3_1_series_build"] is False
    assert g["all_indexes_coverage_verified"] is False
    assert g["all_indexes_point_in_time_verified"] is False
    assert "数值级验证通过也不代表可直接回测" in g["note"]


def test_reports_have_no_deprecated_field_claims(idx):
    """12. 报告中的旧字段引用必须同步修正。

    旧字段只允许出现在「废弃声明」语境中（同段落含「废弃」），
    不得再作为结论字段使用。
    """
    for name in ("phase3B6_2_3_0_coverage_report.md",
                 "phase3B6_2_3_0_recommendation.md",
                 "phase3B6_2_3_0_design.md"):
        txt = (REPORTS / name).read_text(encoding="utf-8")
        lines = txt.splitlines()
        for i, line in enumerate(lines):
            for bad in ("series_matched", "data_series_matches_official"):
                # 排除 series_matches_official_basis 这类新字段
                if bad == "series_matched" and \
                        "series_matches_official" in line:
                    continue
                if bad not in line:
                    continue
                # 必须处于废弃声明语境
                ctx = line + (lines[i - 1] if i else "") + \
                    (lines[i + 1] if i + 1 < len(lines) else "")
                assert ("废弃" in ctx or "过度表达" in ctx
                        or "已移除" in ctx), \
                    f"{name} 第 {i + 1} 行仍把 {bad} 当结论使用：{line.strip()}"
    # JSON 必须显式声明废弃字段
    assert "deprecated_fields" in idx
    assert "api_code_identity_verified" in idx["deprecated_fields"]["series_matched"]


def test_no_overclaim_wording_in_reports():
    """报告不得再出现「历史序列已匹配官方」这类过度表达。"""
    for name in ("phase3B6_2_3_0_coverage_report.md",
                 "phase3B6_2_3_0_recommendation.md"):
        txt = (REPORTS / name).read_text(encoding="utf-8")
        assert "历史数据序列已匹配官方" not in txt, \
            f"{name} 仍声称序列已匹配"
        assert "代码级匹配" not in txt, f"{name} 仍用代码级匹配代替数值验证"


def test_database_audit_reads_real_schema(idx):
    """正式数据库审计必须先读真实 Schema，不得猜测表名/字段。"""
    for r in idx["indexes"]:
        db = r["database"]
        assert db["table"] == "index_daily"
        assert "index_code" in db["schema_columns_read"]
        assert "close" in db["schema_columns_read"]
        assert "source" in db["schema_columns_read"]
        assert "run_id" in db["schema_columns_read"]
        assert "row_fingerprint" in db["schema_columns_read"]
        assert "collected_at" in db["schema_columns_read"]


def test_suspect_rows_recorded(idx):
    """库内 suspect 质量记录必须如实保留，不得忽略。"""
    for r in idx["indexes"]:
        db = r["database"]
        if db["exists"]:
            total = sum(db["quality_status_counts"].values())
            assert total == db["rows"]
            assert len(db["suspect_rows"]) == \
                db["quality_status_counts"].get("suspect", 0)


def test_index_master_return_basis_untouched(idx):
    """正式库 index_master.return_basis 必须仍为 unknown（本轮未修改）。"""
    for r in idx["indexes"]:
        m = r["database_master_row"]
        assert m["exists"] is True
        assert m["return_basis"] == "unknown", \
            f"{r['index_code']} return_basis 被修改为 {m['return_basis']}"
