"""阶段3B-6.1.0.1 审计语义修正专项测试。

覆盖：
- 000012 上证国债指数的净价/净收益语义分离
- 000051 固定年收益率不是资产权重
- 其余 9 个指数的官方证据等级
- 仓库级证据附件的可复现性（不依赖本地缓存）

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

EVIDENCE = ROOT / "reports" / "evidence" / "phase3B6_1_0_index_probe_evidence.json"
REPORTS = ROOT / "reports"

INDEX_CODES = ["000300", "000905", "000906", "000016", "399997",
               "H30184", "000942", "000012", "000922", "930930"]


def _load(path: Path) -> dict:
    assert path.exists(), f"缺少文件：{path}"
    return json.loads(path.read_text(encoding="utf-8"))


def _report(name: str) -> dict:
    return _load(REPORTS / name)


@pytest.fixture(scope="module")
def evidence() -> dict:
    return _load(EVIDENCE)


@pytest.fixture(scope="module")
def index_report() -> dict:
    return _report("phase3B6_1_0_01_index_return_basis.json")


@pytest.fixture(scope="module")
def composite_report() -> dict:
    return _report("phase3B6_1_0_02_composite_benchmark.json")


def _find_index(report: dict, code: str) -> dict:
    for x in report["indexes"]:
        if x["index_code"] == code:
            return x
    raise AssertionError(f"报告里没有 {code}")


# ================================================================ 问题1：000012
def test_000012_clean_price_is_not_net_total_return(index_report):
    """H00012 是净价指数，绝不能被当作净收益指数。"""
    x = _find_index(index_report, "000012")
    assert x["net_total_return_index_code"] is None, \
        "H00012 是净价指数，不得填入 net_total_return_index_code"
    assert x["clean_price_index_code"] == "H00012"
    assert x["price_or_full_price_index_code"] == "000012"


def test_000012_net_return_semantically_separated(index_report):
    """净价与净收益必须是两个不同概念，不能互相顶替。"""
    x = _find_index(index_report, "000012")
    assert x.get("clean_price_index_code") != x.get("net_total_return_index_code")
    semantics = {v["semantic"] for v in x.get("index_name_variants", {}).values()}
    assert "clean_price" in semantics
    assert "interest_and_reinvestment" in semantics
    variants = x["index_name_variants"]
    assert variants["H00012"]["semantic"] == "clean_price"
    assert variants["H00012"]["semantic"] != "net_total_return"
    assert "净价" in variants["H00012"]["interface_name"]


def test_000012_interest_and_reinvestment_code(index_report):
    """N00012 才是当前审计确认的利息及再投资序列。"""
    x = _find_index(index_report, "000012")
    assert x["total_return_index_code"] == "N00012"
    variants = x["index_name_variants"]
    assert variants["N00012"]["semantic"] == "interest_and_reinvestment"
    assert "利息及再投资" in variants["N00012"]["interface_name"]


def test_000012_has_naming_convention_warning(index_report):
    """必须明确说明前缀不能套用股票指数惯例。"""
    x = _find_index(index_report, "000012")
    warn = x.get("naming_convention_warning") or ""
    assert "H00012" in warn
    assert "净价" in warn
    assert "股票指数" in warn


def test_000012_return_basis_still_unknown(index_report):
    """修正不改变 return_basis。"""
    x = _find_index(index_report, "000012")
    assert x["return_basis"] == "unknown"
    assert x["usable_for_excess_return"] is False


def test_000012_field_mapping_matches_evidence(evidence):
    """报告字段必须与证据附件的实测结果一致。"""
    cmp_ = evidence["same_day_comparison"]["sh_gov_bond_three_variants"]
    assert cmp_["000012"]["semantic"] == "full_price"
    assert cmp_["H00012"]["semantic"] == "clean_price"
    assert cmp_["N00012"]["semantic"] == "interest_and_reinvestment"
    # 三者收盘必须互不相同
    closes = {cmp_["000012"]["close"]["close"],
              cmp_["H00012"]["close"]["close"],
              cmp_["N00012"]["close"]["close"]}
    assert len(closes) == 3


# ================================================================ 问题2：000051
def test_000051_fixed_rate_is_not_weight(composite_report):
    """1% 年收益率不能进入资产权重合计。"""
    c = next(x for x in composite_report["composites"]
             if x["composite_id"] == 16)
    fixed = c.get("fixed_annual_return_components") or []
    assert len(fixed) == 1
    assert fixed[0]["weight"] is None
    assert fixed[0]["annual_rate"] == 0.01
    assert fixed[0]["component_type"] == "fixed_annual_return"


def test_000051_no_stale_weight_component(composite_report):
    """旧版把 1% 记成 weight=0.01 的 fixed_rate 成分，必须已清除。"""
    c = next(x for x in composite_report["composites"]
             if x["composite_id"] == 16)
    assert c.get("fixed_rate_components") == []
    for comp in c.get("fixed_rate_components") or []:
        assert comp.get("weight") != 0.01


def test_000051_asset_weight_sum_is_0_95(composite_report):
    """资产权重合计只能是 0.95，不是 0.96。"""
    c = next(x for x in composite_report["composites"]
             if x["composite_id"] == 16)
    assert c["weight_sum_of_asset_components"] == 0.95
    total = 0.0
    for i in c.get("index_components", []):
        total += i["weight"]
    for b in c.get("bond_components", []):
        total += b["weight"]
    for ca in c.get("cash_components", []):
        total += ca["weight"]
    assert abs(total - 0.95) < 1e-9
    assert abs(total - 0.96) > 1e-9


def test_000051_period_conversion_method_unknown(composite_report):
    """期间折算方法未确定时不能标 reproducible。"""
    c = next(x for x in composite_report["composites"]
             if x["composite_id"] == 16)
    pc = c["period_conversion_evidence"]
    assert pc["required"] is True
    assert pc["method_known"] is False
    assert c["status"] != "reproducible"
    assert any("折算" in r for r in c["reasons"])


def test_fixed_rate_semantics_declared(composite_report):
    c = next(x for x in composite_report["composites"]
             if x["composite_id"] == 16)
    assert c["fixed_rate_semantics"] == "annual_return_not_weight"


def test_other_composites_have_no_fixed_rate_confusion(composite_report):
    """只修正有明确证据的问题，不推测其它基准。"""
    others = [x for x in composite_report["composites"]
              if x["composite_id"] != 16]
    for c in others:
        if c.get("fixed_annual_return_components"):
            pytest.fail(f"{c['composite_id']} 不应有固定年收益率成分")
        if c.get("fixed_rate_components"):
            pytest.fail(f"{c['composite_id']} 不应有 fixed_rate 成分")


# ================================================================ 问题3：官方证据
def test_all_10_indexes_have_official_evidence(index_report, evidence):
    docs = evidence["official_documents"]
    assert len(docs) == 10
    for x in index_report["indexes"]:
        code = x["index_code"]
        assert code in docs, f"{code} 缺官方证据记录"
        assert x.get("official_evidence_level") in (
            "L2_document_verified", "L3_factsheet_only", "L4_no_official_doc")


def test_methodology_docs_actually_downloaded(evidence):
    docs = evidence["official_documents"]
    found = [c for c, d in docs.items() if d.get("downloaded")]
    assert len(found) == 8, f"应取得 8 份编制方案，实际 {len(found)}：{found}"
    for c in found:
        assert docs[c]["bytes"] > 0
        assert docs[c]["pages"] >= 2
        assert len(docs[c]["sha256_16"]) == 16


def test_missing_methodology_reported_honestly(evidence):
    """未取得的 2 份必须如实记录原因，不能静默跳过。"""
    log = evidence["official_search_log"]
    assert set(log["not_found_methodology"]) == {"000012", "930930"}
    for c in log["not_found_methodology"]:
        assert c in log["not_found_reason"]
        assert len(log["not_found_reason"][c]) > 10


def test_search_log_is_traceable(evidence):
    log = evidence["official_search_log"]
    assert log["query_time"]
    assert log["url_base"].startswith("https://")
    assert len(log["patterns_tried"]) >= 3
    assert len(log["keywords"]) >= 2


def test_all_10_have_factsheet(evidence):
    """10 个指数必须全部取得官方 factsheet（编制方案可缺，factsheet 不可缺）。"""
    docs = evidence["official_documents"]
    missing = [c for c in INDEX_CODES if not docs.get(c, {}).get("factsheet")]
    assert not missing, f"缺 factsheet：{missing}"


def test_no_basis_upgraded(index_report):
    """本轮不得升级任何 return_basis。"""
    for x in index_report["indexes"]:
        assert x["return_basis"] == "unknown", \
            f"{x['index_code']} 的 return_basis 被升级了"
        assert x["usable_for_excess_return"] is False


# ================================================================ 问题4：仓库级可复现
def test_evidence_file_in_repo(evidence):
    assert EVIDENCE.exists()
    assert evidence["phase"] == "3B-6.1.0.1"
    assert evidence["call_count"] > 0


def test_evidence_covers_all_10_indexes(evidence):
    codes = {e["index_code"] for e in evidence["indexes"]}
    assert codes == set(INDEX_CODES)


def test_evidence_has_full_call_metadata(evidence):
    """每次调用必须有完整可复核元数据。"""
    for e in evidence["indexes"]:
        for v in e["variants"]:
            for key in ("request_code", "request_start", "request_end",
                        "source", "called_at", "status"):
                assert key in v, f"{e['index_code']} 的变体缺 {key}"
            if v["status"] == "ok":
                assert v["index_name_returned"]
                assert v["rows"] > 0
                assert v["dup_dates_ok"] if "dup_dates_ok" in v else \
                    v["duplicate_dates"] == 0


def test_evidence_price_and_total_are_different(evidence):
    cmp_ = evidence["same_day_comparison"]["csi300_price_vs_total"]
    p = cmp_["price"]["close"]["close"]
    t = cmp_["total"]["close"]["close"]
    assert p != t
    assert t > p


def test_no_local_cache_dependency():
    """证据必须来自仓库内文件，不是本地临时缓存。"""
    assert EVIDENCE.exists(), "证据附件必须提交到仓库"
    assert str(EVIDENCE).replace("\\", "/").count("/reports/evidence/") == 1
    # 证据文件所在目录不得是 .tmp*
    assert ".tmp" not in EVIDENCE.as_posix()
    # 必须位于 reports/evidence 下（正式的仓库产物目录）
    assert EVIDENCE.parent.name == "evidence"
    assert EVIDENCE.parent.parent.name == "reports"


# ================================================================ 门禁与只读
def test_gate_unchanged(index_report, composite_report):
    for d in (index_report, composite_report):
        g = d["gate"]
        assert g["ready_for_research_analysis"] is True
        assert g["ready_for_backtest"] is False
        assert g["ready_for_formal_ranking"] is False


def test_no_index_written_to_db():
    from app.database.db import get_connection
    with get_connection() as c:
        assert c.execute("SELECT COUNT(*) FROM index_daily").fetchone()[0] == 50603
        assert c.execute("SELECT COUNT(*) FROM index_master").fetchone()[0] == 10


def test_no_composite_modified():
    from app.database.db import get_connection
    with get_connection() as c:
        assert c.execute(
            "SELECT COUNT(*) FROM benchmark_composite").fetchone()[0] == 15
        assert c.execute(
            "SELECT COUNT(*) FROM benchmark_composite_component").fetchone()[0] == 34
