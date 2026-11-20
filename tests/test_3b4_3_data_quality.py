"""阶段3B-4.3 场外基金数据质量与幸存者偏差验收专项测试。

全部用人工构造数据 + 独立临时库，不联网、不碰正式库。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import db as db_module  # noqa: E402
from app.database.db import get_connection  # noqa: E402
from app.fund.migration import ensure_fund_schema  # noqa: E402
from app.fund.migration_3b4_2 import ensure_3b4_2_schema  # noqa: E402

JSON_PATH = ROOT / "reports" / "phase3B4_3_data_quality.json"
MD_PATH = ROOT / "reports" / "phase3B4_3_data_quality_report.md"

sys.path.insert(0, str(ROOT / "scripts"))
import audit_3b4_3_data_quality as audit  # noqa: E402


@pytest.fixture(scope="module")
def payload() -> dict:
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


@pytest.fixture()
def qdb(tmp_path, monkeypatch):
    db_path = tmp_path / "quality.db"
    monkeypatch.setattr(db_module, "settings",
                        type("S", (), {"database_path": db_path})())
    ensure_fund_schema(db_path)
    ensure_3b4_2_schema(db_path)
    return db_path


def _seed(conn, code, fid=None, status="unknown"):
    """造一个基金本体 + 主份额，返回 (fund_id, share_class_id)。"""
    if fid is None:
        conn.execute(
            "INSERT INTO fund_master (fund_code_primary, fund_name, lifecycle_status, "
            "source, ingested_at) VALUES (?,?,?,?,?)",
            (code, f"测试{code}", status, "test", "2026-01-01"))
        fid = int(conn.execute(
            "SELECT fund_id FROM fund_master WHERE fund_code_primary=?", (code,)
        ).fetchone()[0])
    conn.execute(
        "INSERT INTO fund_share_classes (fund_id, share_class_code, share_class_name, "
        "is_primary, source, ingested_at) VALUES (?,?,?,?,?,?)",
        (fid, code, f"测试{code}", 1, "test", "2026-01-01"))
    sid = int(conn.execute(
        "SELECT share_class_id FROM fund_share_classes WHERE share_class_code=?", (code,)
    ).fetchone()[0])
    return fid, sid


# ================================================================ 1. 清盘重复与归属
def test_lifecycle_no_duplicate_events(payload):
    """41 条事件里不能有同一（本体, 类型）重复。"""
    assert payload["lifecycle"]["total_events"] == 41
    assert payload["lifecycle"]["duplicate_events"] == []


def test_lifecycle_distinct_funds(payload):
    """41 条事件对应 41 个不同本体。"""
    assert payload["lifecycle"]["distinct_funds"] == 41


def test_lifecycle_no_code_conflict(payload):
    """同一代码不能出现在两个基金本体。"""
    assert payload["lifecycle"]["code_conflicts"] == []


def test_lifecycle_all_b_and_traceable(payload):
    L = payload["lifecycle"]
    assert L["by_evidence_level"] == {"B": 41}
    assert L["all_have_url"] is True
    assert L["all_have_ann_id"] is True


def test_lifecycle_structure_split(payload):
    L = payload["lifecycle"]
    assert L["by_product_structure"] == {
        "ordinary_open_ended": 27, "etf_linked": 3, "lof": 11}


def test_lifecycle_not_full_roster(payload):
    """必须明确声明不是完整名录、覆盖率不可量化。"""
    L = payload["lifecycle"]
    assert L["coverage_quantifiable"] is False


def test_survivorship_not_eliminated(payload):
    """不得宣称已消除幸存者偏差。"""
    assert payload["lifecycle"]["survivorship_bias_status"] == "not_eliminated"
    assert "未消除" in payload["conclusions"]["q3_survivorship_bias"]


def test_lifecycle_detects_duplicate_event(qdb):
    """造同一本体两条同类型事件，审计要能发现。

    注意：uq_fund_life_natural 唯一索引会拦住完全相同的（fund_id, type,
    event_date, source），所以这里用不同的 event_date 造出「同类型多次终止」，
    这正是审计要抓的语义重复。
    """
    with get_connection(qdb) as conn:
        fid, _ = _seed(conn, "900001", status="terminated")
        for d in ("2020-01-01", "2020-02-01"):
            conn.execute(
                "INSERT INTO fund_lifecycle_events (fund_id, event_type, event_date, "
                "evidence_level, source, ingested_at, product_structure, fund_codes) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (fid, "terminated", d, "B", "dfcfw.announcement.calibrated",
                 "2026-01-01", "ordinary_open_ended", "900001"))
    with get_connection(qdb) as conn:
        r = audit.audit_lifecycle(conn)
    assert len(r["duplicate_events"]) == 1
    assert r["duplicate_events"][0]["count"] == 2


def test_lifecycle_detects_code_conflict(qdb):
    with get_connection(qdb) as conn:
        f1, _ = _seed(conn, "900002", status="terminated")
        f2, _ = _seed(conn, "900003", status="terminated")
        for fid, codes in ((f1, "900002"), (f2, "900002,900004")):
            conn.execute(
                "INSERT INTO fund_lifecycle_events (fund_id, event_type, "
                "evidence_level, source, ingested_at, product_structure, fund_codes) "
                "VALUES (?,?,?,?,?,?,?)",
                (fid, "terminated", "B", "dfcfw.announcement.calibrated",
                 "2026-01-01", "ordinary_open_ended", codes))
    with get_connection(qdb) as conn:
        r = audit.audit_lifecycle(conn)
    assert len(r["code_conflicts"]) == 1
    assert r["code_conflicts"][0]["code"] == "900002"


# ================================================================ 2. 净值
def test_nav_no_duplicate_dates(payload):
    assert payload["nav"]["duplicate_date_total"] == 0


def test_nav_no_null_unit(payload):
    assert payload["nav"]["null_unit_nav_total"] == 0
    assert payload["nav"]["nonpositive_unit_nav_total"] == 0


def test_nav_kind_isolated(payload):
    """单位净值与货币基金收益口径不得混用。"""
    assert payload["nav"]["mixed_kind_net_value"] == 0
    assert payload["nav"]["mixed_kind_money_yield"] == 0


def test_money_fund_separate_kind(payload):
    kinds = payload["nav"]["nav_kind_distribution"]
    assert kinds.get("money_yield", 0) == 1
    assert kinds.get("net_value", 0) == 11


def test_nav_continuity_cannot_verify(payload):
    """无真实基金日历 → 必须降级 cannot_verify，不得产出连续/不连续结论。"""
    N = payload["nav"]
    assert N["continuity_verification_level"] == "cannot_verify"
    assert N["calendar_role"] == "proxy_not_fund_calendar"
    assert "不代表每只基金真实净值公布日历" in N["calendar_statement"]


def test_nav_duplicate_blocked_by_pk(qdb):
    """净值主键 (share_class_id, nav_date, nav_kind) 必须挡住重复写入。"""
    import sqlite3
    with get_connection(qdb) as conn:
        _, sid = _seed(conn, "900010")
        conn.execute(
            "INSERT INTO fund_nav_daily (share_class_id, nav_date, nav_kind, "
            "unit_nav, source, ingested_at) VALUES (?,?,?,?,?,?)",
            (sid, "2024-01-02", "net_value", 1.0, "test", "2026-01-01"))
    with pytest.raises(sqlite3.IntegrityError):
        with get_connection(qdb) as conn:
            conn.execute(
                "INSERT INTO fund_nav_daily (share_class_id, nav_date, nav_kind, "
                "unit_nav, source, ingested_at) VALUES (?,?,?,?,?,?)",
                (sid, "2024-01-02", "net_value", 1.1, "test", "2026-01-01"))
    with get_connection(qdb) as conn:
        r = audit.audit_nav(conn)
    assert r["duplicate_date_total"] == 0


def test_nav_gap_detection(qdb):
    """相邻净值间隔应被正确计算。"""
    with get_connection(qdb) as conn:
        _, sid = _seed(conn, "900011")
        for d in ("2024-01-02", "2024-01-03", "2024-02-20"):
            conn.execute(
                "INSERT INTO fund_nav_daily (share_class_id, nav_date, nav_kind, "
                "unit_nav, source, ingested_at) VALUES (?,?,?,?,?,?)",
                (sid, d, "net_value", 1.0, "test", "2026-01-01"))
    with get_connection(qdb) as conn:
        r = audit.audit_nav(conn)
    f = next(x for x in r["per_fund"] if x["code"] == "900011")
    assert f["max_gap_days"] == 48
    assert f["gaps_over_30d_count"] == 1


def test_nav_mixed_kind_detected(qdb):
    """净值守则允许 unit_nav；货币行必须有 per_10k_yield。"""
    with get_connection(qdb) as conn:
        _, sid = _seed(conn, "900012")
        conn.execute(
            "INSERT INTO fund_nav_daily (share_class_id, nav_date, nav_kind, "
            "per_10k_yield, source, ingested_at) VALUES (?,?,?,?,?,?)",
            (sid, "2024-01-02", "money_yield", 0.5, "test", "2026-01-01"))
    with get_connection(qdb) as conn:
        r = audit.audit_nav(conn)
    assert r["money_yield_rows"] == 1
    assert r["mixed_kind_money_yield"] == 0


# ================================================================ 3. 分红
def test_dividend_no_duplicate(payload):
    assert payload["dividend"]["duplicate_groups"] == 0


def test_dividend_per10_conversion_ok(payload):
    assert payload["dividend"]["per10_conversion_mismatch"] == 0


def test_dividend_not_complete(payload):
    """不得把当前接口返回当完整历史。"""
    D = payload["dividend"]
    assert "不能" in D["completeness_statement"]
    assert D["usable_for_return_adjustment"] is False


def test_dividend_duplicate_blocked(qdb):
    """同源同除息日的分红必须被 UNIQUE 挡住，审计读到 0 重复。"""
    import sqlite3
    with get_connection(qdb) as conn:
        _, sid = _seed(conn, "900020")
        conn.execute(
            "INSERT INTO fund_dividends (share_class_id, ex_date, "
            "cash_per_share, per_10_raw, source, ingested_at) "
            "VALUES (?,?,?,?,?,?)",
            (sid, "2024-01-02", 0.1, "每10份派现金1.0000元", "test", "2026-01-01"))
    with pytest.raises(sqlite3.IntegrityError):
        with get_connection(qdb) as conn:
            conn.execute(
                "INSERT INTO fund_dividends (share_class_id, ex_date, "
                "cash_per_share, per_10_raw, source, ingested_at) "
                "VALUES (?,?,?,?,?,?)",
                (sid, "2024-01-02", 0.1, "每10份派现金1.0000元", "test",
                 "2026-01-01"))
    with get_connection(qdb) as conn:
        r = audit.audit_dividend(conn)
    assert r["duplicate_groups"] == 0
    assert r["total"] == 1


def test_dividend_per10_mismatch_detected(qdb):
    with get_connection(qdb) as conn:
        _, sid = _seed(conn, "900021")
        conn.execute(
            "INSERT INTO fund_dividends (share_class_id, ex_date, "
            "cash_per_share, per_10_raw, source, ingested_at) VALUES (?,?,?,?,?,?)",
            (sid, "2024-01-02", 0.05, "每10份派现金1.0000元", "test", "2026-01-01"))
    with get_connection(qdb) as conn:
        r = audit.audit_dividend(conn)
    assert r["per10_conversion_mismatch"] == 1


# ================================================================ 4. 费率
def test_fee_null_kept(payload):
    F = payload["fee"]
    assert F["rate_original_null"] == 1
    assert F["rate_original_present"] == 89


def test_fee_effective_from_all_null(payload):
    """当前费率不能当历史费率。"""
    assert payload["fee"]["effective_from_all_null"] is True


def test_fee_basis_all_null(payload):
    """自然日/交易日未确认。"""
    assert payload["fee"]["holding_days_basis_all_null"] is True


def test_fee_not_alipay(payload):
    assert payload["fee"]["alipay_platform_rows"] == 0


def test_fee_all_c_level(payload):
    assert payload["fee"]["by_evidence_level"] == {"C": 90}


def test_fee_not_for_historical_cost(payload):
    assert payload["fee"]["usable_for_historical_cost"] is False
    assert len(payload["fee"]["forbidden_uses"]) >= 4


def test_fee_inferred_flagged(payload):
    assert payload["fee"]["inferred_lower_bound"] == 19


# ================================================================ 5. 经理与规模
def test_manager_dates_all_null(payload):
    M = payload["manager_aum"]
    assert M["manager_start_date_null"] == M["manager_records"]
    assert M["manager_end_date_null"] == M["manager_records"]


def test_no_backfill_allowed(payload):
    assert payload["manager_aum"]["backfill_forbidden"] is True
    assert "禁止" in payload["manager_aum"]["backfill_statement"]


def test_aum_single_snapshot(payload):
    M = payload["manager_aum"]
    assert M["aum_multi_period"] is False
    assert M["aum_snapshot_count"] == 1


def test_manager_not_usable_for_backtest(payload):
    assert payload["manager_aum"]["usable_for_backtest"] is False


# ================================================================ 6. 份额关系
def test_no_multi_primary(payload):
    assert payload["share_relation"]["multi_primary_funds"] == []


def test_no_fund_without_primary(payload):
    assert payload["share_relation"]["no_primary_funds"] == []


def test_terminated_all_exactly_one_primary(payload):
    S = payload["share_relation"]
    assert S["terminated_entities"] == 41
    assert S["terminated_with_exactly_one_primary"] == 41


def test_no_duplicate_share_code(payload):
    assert payload["share_relation"]["duplicate_share_codes"] == 0


def test_money_fund_isolated(payload):
    S = payload["share_relation"]
    assert "000198" in S["money_fund_codes"]
    assert S["money_isolated"] is True


def test_audit_detects_multi_primary(qdb):
    with get_connection(qdb) as conn:
        fid, _ = _seed(conn, "900030")
        conn.execute(
            "INSERT INTO fund_share_classes (fund_id, share_class_code, "
            "share_class_name, is_primary, source, ingested_at) VALUES (?,?,?,?,?,?)",
            (fid, "900031", "第二主份额", 1, "test", "2026-01-01"))
    with get_connection(qdb) as conn:
        r = audit.audit_share_relation(conn)
    assert len(r["multi_primary_funds"]) == 1


def test_audit_detects_no_primary(qdb):
    with get_connection(qdb) as conn:
        conn.execute(
            "INSERT INTO fund_master (fund_code_primary, fund_name, lifecycle_status, "
            "source, ingested_at) VALUES ('900040','无主份额基金','unknown','test','2026-01-01')")
        fid = int(conn.execute(
            "SELECT fund_id FROM fund_master WHERE fund_code_primary='900040'"
        ).fetchone()[0])
        conn.execute(
            "INSERT INTO fund_share_classes (fund_id, share_class_code, "
            "share_class_name, is_primary, source, ingested_at) VALUES (?,?,?,?,?,?)",
            (fid, "900041", "非主", 0, "test", "2026-01-01"))
    with get_connection(qdb) as conn:
        r = audit.audit_share_relation(conn)
    assert len(r["no_primary_funds"]) >= 1


# ================================================================ 7. 支付宝
def test_alipay_all_unknown(payload):
    A = payload["alipay"]
    assert A["alipay_status"] == "unknown"
    assert A["all_unknown"] is True


def test_alipay_statement_present(payload):
    st = payload["alipay"]["statement"]
    assert "不代表支付宝" in st


def test_trading_rules_typed(payload):
    """交易规则必须分四类，不得一律套用。"""
    T = payload["alipay"]["trading_rule_categories"]
    for k in ("industry_convention", "fund_contract",
              "platform_execution", "unverified"):
        assert k in T
    assert payload["alipay"]["cannot_apply_uniformly"] is True


def test_unverified_rules_listed(payload):
    assert len(payload["alipay"]["unverified_rules"]) >= 3


# ================================================================ 8. 证据等级
def test_evidence_levels_defined(payload):
    assert set(payload["evidence_levels"]) == {"A", "B", "C", "D", "unknown"}


def test_no_level_upgrade(payload):
    """接口能返回不等于 A 级：清盘 B、费率 C、净值 C。"""
    assert payload["lifecycle"]["by_evidence_level"] == {"B": 41}
    assert payload["fee"]["by_evidence_level"] == {"C": 90}


def test_usage_matrix_four_tiers(payload):
    M = payload["usage_matrix"]
    for k in ("tier_1_direct_use", "tier_2_conditional",
              "tier_3_auxiliary_only", "tier_4_forbidden"):
        assert k in M
        assert isinstance(M[k], list)


def test_forbidden_includes_alipay_and_history_fee(payload):
    names = " ".join(x["data"] for x in payload["usage_matrix"]["tier_4_forbidden"])
    assert "支付宝可购买状态" in names
    assert "历史生效费率" in names


def test_forbidden_includes_continuity(payload):
    names = " ".join(x["data"] for x in payload["usage_matrix"]["tier_4_forbidden"])
    assert "净值连续性" in names


def test_stage_gate_blocks_backtest(payload):
    gate = payload["stage_gate"]
    assert gate["ready_for_next_stage"] is False
    assert "3B-5" in " ".join(gate["blocked"])


# ================================================================ 文档一致
def test_report_exists(payload):
    assert MD_PATH.is_file()


def test_report_numbers_match_json(payload):
    md = MD_PATH.read_text(encoding="utf-8")
    assert str(payload["lifecycle"]["total_events"]) in md
    assert str(payload["fee"]["total"]) in md
    assert str(payload["dividend"]["total"]) in md


def test_report_states_cannot_verify(payload):
    md = MD_PATH.read_text(encoding="utf-8")
    assert "cannot_verify" in md


def test_report_states_not_eliminated(payload):
    md = MD_PATH.read_text(encoding="utf-8")
    assert "未消除" in md or "not_eliminated" in md


def test_baseline_recorded(payload):
    assert payload["baseline_head"].startswith("93c920cc")


# ================================================================ 边界
def test_no_formal_engine_added():
    for pat in ("*fund*engine*", "*fund*backtest*", "*fund*execution*"):
        assert not list((ROOT / "app").rglob(pat)), pat


def test_migration_still_ten_tables():
    sql = ROOT / "migrations" / "phase3b4_fund_data_layer.sql"
    assert sql.read_text(encoding="utf-8").count(
        "CREATE TABLE IF NOT EXISTS fund_") == 10


def test_3b4_2_migration_unchanged():
    """3B-4.2 迁移文件不得在本轮被改。"""
    sql = ROOT / "migrations" / "phase3b4_2_lifecycle_fee_ingestion.sql"
    assert sql.is_file()
    body = sql.read_text(encoding="utf-8")
    assert "ALTER TABLE fund_lifecycle_events ADD COLUMN announcement_id" in body
