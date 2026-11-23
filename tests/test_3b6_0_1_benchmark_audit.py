"""阶段3B-6.0.1 基准与指数数据源审计专项测试（只读）。

不联网、不写库、不采集。接口连通性验证由审计脚本单独跑，不在单测里。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.fund.research.benchmark_audit import (  # noqa: E402
    BOND_FAMILIES_UNRESOLVED, EV_CONTRACT, EV_INFERRED, EV_NONE, EV_PLATFORM,
    EV_TRACKING, EVIDENCE_TYPES, EXTERNAL_INDEX_CATALOG, INDEX_CATALOG,
    audit_all_benchmarks, classify_evidence, index_code_for, parse_benchmark,
    summarize_audit,
)


# ================================================================ 四类证据
def test_evidence_types_distinct():
    """四类证据必须互不相同且各自有定义。"""
    assert EV_CONTRACT != EV_TRACKING != EV_PLATFORM != EV_INFERRED
    for t in (EV_CONTRACT, EV_TRACKING, EV_PLATFORM, EV_INFERRED, EV_NONE):
        assert t in EVIDENCE_TYPES
        assert EVIDENCE_TYPES[t][0]


def test_tracking_index_wins_over_benchmark():
    r = classify_evidence({"tracking_index": "000300", "benchmark": "沪深300"})
    assert r["evidence_type"] == EV_TRACKING


def test_benchmark_text_is_platform_not_contract():
    """库内 benchmark 是第三方转述，不得标成合同原文。"""
    r = classify_evidence({"benchmark": "沪深300指数收益率×95%+活期存款×5%"})
    assert r["evidence_type"] == EV_PLATFORM
    assert "未" in r["evidence_note"] and "合同" in r["evidence_note"]


def test_no_evidence_is_none():
    r = classify_evidence({"benchmark": "", "tracking_index": None})
    assert r["evidence_type"] == EV_NONE
    assert r["evidence_value"] is None


def test_inferred_type_never_used_by_scanner():
    """扫描器不得把名称推测写进 evidence_type。"""
    a = audit_all_benchmarks()
    for row in a["rows"]:
        assert row["evidence_type"] != EV_INFERRED


# ================================================================ 基准解析
def test_single_index_benchmark():
    p = parse_benchmark("沪深300指数收益率")
    assert p["index_families"] == ["沪深300"]
    assert p["single_index_family"] == "沪深300"
    assert p["is_composite"] is False
    assert p["confidence"] == "high"


def test_empty_benchmark():
    p = parse_benchmark(None)
    assert p["confidence"] == "none"
    assert p["components"] == []
    assert p["single_index_family"] is None


def test_composite_not_reduced_to_single_index():
    """复合基准绝不能退化成单指数。"""
    p = parse_benchmark("沪深300指数收益率×70%+中债综合全价指数收益率×25%+同业存款利率×5%")
    assert p["is_composite"] is True
    assert p["single_index_family"] is None
    assert "沪深300" in p["index_families"]
    assert p["bond_component"] is True
    assert p["cash_component"] is True


def test_index_plus_cash_is_composite():
    p = parse_benchmark("95%*沪深300指数+5%*银行同业存款利率")
    assert p["is_composite"] is True
    assert p["single_index_family"] is None
    assert p["cash_component"] is True
    assert len(p["index_families"]) == 1


def test_multi_index_composite():
    p = parse_benchmark("中证800指数收益率*70%+上证国债指数收益率*25%+活期存款基准利率*5%")
    assert len(p["index_families"]) >= 2
    assert p["is_composite"] is True
    assert p["single_index_family"] is None


def test_bond_only_benchmark():
    p = parse_benchmark("中债综合指数")
    assert p["index_families"] == []
    assert p["bond_component"] is True
    assert p["single_index_family"] is None


def test_cash_only_benchmark():
    p = parse_benchmark("活期存款利率（税后）")
    assert p["cash_component"] is True
    assert p["index_families"] == []


def test_weights_extracted():
    p = parse_benchmark("沪深300指数收益率×70%+中债综合全价指数收益率×25%+同业存款利率×5%")
    weights = [c["weight"] for c in p["components"] if c["weight"] is not None]
    assert 0.70 in weights
    assert 0.25 in weights


def test_unresolved_component_not_guessed():
    """识别不出的成分必须留在 unresolved，不得被吞掉。"""
    p = parse_benchmark("某未知自定义指数收益率×60%+沪深300指数收益率×40%")
    assert p["unresolved_parts"]
    assert p["is_composite"] is True
    assert p["single_index_family"] is None


# ================================================================ 指数代码
def test_index_code_lookup():
    assert index_code_for("沪深300")["index_code"] == "000300"
    assert index_code_for("中证500")["index_code"] == "000905"
    assert index_code_for("上证50")["index_code"] == "000016"
    assert index_code_for("中证全指半导体")["index_code"] == "H30184"


def test_unknown_index_not_resolved():
    for fam in ("不存在的指数", "中债综合", None, ""):
        r = index_code_for(fam)
        assert r["resolvable"] is False
        assert r["index_code"] is None


def test_bond_families_have_no_code():
    """债券族一律无已核实官网代码。"""
    for fam in BOND_FAMILIES_UNRESOLVED:
        r = index_code_for(fam)
        assert r["resolvable"] is False, fam


def test_external_catalog_marked_partial():
    """恒生指数走新浪，必须标 partial，不得混入 csindex 口径。"""
    r = index_code_for("恒生指数")
    assert r["resolvable"] is True
    assert r["catalog"] == "external_partial"
    assert r["completeness"] == "partial"
    assert "2013-08-20" in r["note"]


def test_catalog_codes_unique():
    codes = [v["codes"]["csindex"] for v in INDEX_CATALOG.values()]
    assert len(codes) == len(set(codes))


# ================================================================ 全量审计
def test_audit_covers_all_funds():
    """必须覆盖全量，不是抽样。"""
    a = audit_all_benchmarks()
    assert a["scanned_fund_count"] == len(a["rows"])
    assert a["database_written"] is False
    assert a["readonly"] is True
    assert "全部" in a["scope_note"]


def test_audit_includes_terminated():
    a = audit_all_benchmarks()
    term = [r for r in a["rows"] if r["lifecycle_status"] == "terminated"]
    assert len(term) == 41


def test_audit_share_count_matches_db():
    from app.database.db import get_connection
    with get_connection() as conn:
        n = conn.execute("SELECT COUNT(*) FROM fund_share_classes").fetchone()[0]
    a = audit_all_benchmarks()
    assert a["scanned_share_count"] == n


def test_audit_ac_shares_grouped():
    """A/C 必须归到同一 fund_id，不被算成两个本体。"""
    a = audit_all_benchmarks()
    by_id = {r["fund_id"]: r for r in a["rows"]}
    assert 73 in by_id and by_id[73]["share_count"] == 2    # 000032/000033
    assert 75 in by_id and by_id[75]["share_count"] == 2    # 001548/001549
    # 本体列表里 fund_id 唯一
    ids = [r["fund_id"] for r in a["rows"]]
    assert len(ids) == len(set(ids))


def test_audit_unknown_never_promoted():
    """无基准的基金绝不能变成可验证基准。"""
    a = audit_all_benchmarks()
    for r in a["rows"]:
        if r["evidence_type"] == EV_NONE:
            assert r["audit_status"] == "no_benchmark"
            assert r["index_family"] is None
            assert r["index_code"] is None
            assert r["index_identifiable"] is False


def test_audit_composite_no_single_index_claim():
    a = audit_all_benchmarks()
    for r in a["rows"]:
        if r["benchmark_parsed"]["is_composite"]:
            assert r["benchmark_parsed"]["single_index_family"] is None


def test_audit_status_values_known():
    a = audit_all_benchmarks()
    known = {"no_benchmark", "index_only", "index_plus_cash",
             "composite_multi_index", "composite_with_bond",
             "bond_index_without_code", "cash_only",
             "unparsed_component", "unparsed"}
    for r in a["rows"]:
        assert r["audit_status"] in known, r["audit_status"]


def test_summary_consistent():
    a = audit_all_benchmarks()
    s = summarize_audit(a)
    assert sum(s["by_audit_status"].values()) == len(a["rows"])
    assert sum(s["by_evidence_type"].values()) == len(a["rows"])
    assert s["all"]["fund_count"] == len(a["rows"])
    assert s["live"]["fund_count"] + s["terminated"]["fund_count"] == len(a["rows"])


def test_summary_live_numbers():
    a = audit_all_benchmarks()
    s = summarize_audit(a)
    assert s["live"]["fund_count"] == 19
    assert s["live"]["share_count"] == 26
    assert s["live"]["has_tracking_index"] == 0
    assert s["live"]["has_benchmark"] == 18
    assert s["live"]["no_benchmark"] == 1


def test_summary_multi_index_listed():
    a = audit_all_benchmarks()
    s = summarize_audit(a)
    for x in s["multi_index_composites"]:
        assert len(x["index_families"]) >= 2


def test_money_fund_isolated():
    """货币基金不得被当成指数基金。"""
    a = audit_all_benchmarks()
    money = [r for r in a["rows"] if r["fund_id"] in (22, 74)]
    assert len(money) == 2
    for r in money:
        assert r["audit_status"] in ("no_benchmark", "cash_only")
        assert r["index_code"] is None


# ================================================================ 只读守恒
def test_database_untouched_and_fingerprint_same():
    from app.database.db import get_connection
    from app.fund.ingest_user_funds import db_fingerprint

    before = db_fingerprint()["sha256"]
    with get_connection() as conn:
        rows_before = {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("fund_master", "fund_share_classes", "fund_nav_daily",
                      "fund_dividends", "fund_lifecycle_events")
        }
    audit_all_benchmarks()
    with get_connection() as conn:
        rows_after = {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in rows_before
        }
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    after = db_fingerprint()["sha256"]
    assert rows_before == rows_after
    assert before == after


def test_no_schema_change():
    """不得新增/修改表结构。"""
    from app.database.db import get_connection
    with get_connection() as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    for t in ("fund_master", "fund_share_classes", "fund_nav_daily"):
        assert t in tables
    # 审计模块不引入任何新表
    assert "fund_benchmark_audit" not in tables
    assert "benchmark_audit" not in tables


# ================================================================ 门禁
def test_gate_unchanged():
    from app.fund.research.engine import analyze_by_code
    g = analyze_by_code("050002")["gate"]
    assert g["ready_for_research_analysis"] is True
    assert g["ready_for_backtest"] is False
    assert g["ready_for_formal_ranking"] is False
