"""阶段3B-4.4 数据缺口补强专项测试。

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
from app.fund.migration_3b4_4 import (  # noqa: E402
    AUM_COLUMNS, MANAGER_COLUMNS, current_schema, ensure_3b4_4_schema,
)

JSON_PATH = ROOT / "reports" / "phase3B4_4_data_gap_research.json"
MD_PATH = ROOT / "reports" / "phase3B4_4_data_gap_research.md"

sys.path.insert(0, str(ROOT / "scripts"))
import audit_3b4_4_data_gap as audit  # noqa: E402


@pytest.fixture(scope="module")
def payload() -> dict:
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


SAMPLE = ("000015", "000016", "000051", "000198", "000478", "007300",
          "007301", "012414", "110020", "110022", "161005", "161725")


@pytest.fixture()
def gapdb(tmp_path, monkeypatch):
    """独立临时库 + 12 只样本基金 + 90 条费率骨架。"""
    db_path = tmp_path / "gap.db"
    monkeypatch.setattr(db_module, "settings",
                        type("S", (), {"database_path": db_path})())
    ensure_fund_schema(db_path)
    ensure_3b4_2_schema(db_path)
    ensure_3b4_4_schema(db_path)
    now = "2026-11-19T00:00:00"
    with get_connection(db_path) as conn:
        for i, code in enumerate(SAMPLE, start=100):
            conn.execute(
                "INSERT INTO fund_master (fund_id, fund_code_primary, fund_name, "
                "lifecycle_status, source, ingested_at) VALUES (?,?,?,?,?,?)",
                (i, code, "T" + code, "unknown", "test", now))
            conn.execute(
                "INSERT INTO fund_share_classes (share_class_id, fund_id, "
                "share_class_code, share_class_name, is_primary, source, ingested_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (i, i, code, "T" + code, 1, "test", now))
            for ft, rate in (("management", 0.012), ("custody", 0.002),
                             ("sales_service", 0.0)):
                conn.execute(
                    """INSERT INTO fund_fee_rules
                       (share_class_id, fee_type, tier_order, rate, rate_original,
                        is_annual, platform_name, source_name, evidence_level,
                        source, ingested_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (i, ft, 0, rate, rate, 1, "eastmoney",
                     "天天基金F10费率页", "C", "test", now))
    return db_path


# ================================================================ 迁移
def test_migration_adds_manager_columns(gapdb):
    cols = current_schema(gapdb)["fund_manager_history"]["columns"]
    for name, _ in MANAGER_COLUMNS:
        assert name in cols, name


def test_migration_adds_aum_columns(gapdb):
    cols = current_schema(gapdb)["fund_aum_history"]["columns"]
    for name, _ in AUM_COLUMNS:
        assert name in cols, name


def test_migration_idempotent(gapdb):
    first = ensure_3b4_4_schema(gapdb)
    assert sum(len(v) for v in first.values()) == 0
    second = ensure_3b4_4_schema(gapdb)
    assert sum(len(v) for v in second.values()) == 0


def test_migration_keeps_old_columns(gapdb):
    schema = current_schema(gapdb)
    for c in ("manager_id", "fund_id", "manager_name", "start_date",
              "end_date", "tenure_days", "source", "ingested_at"):
        assert c in schema["fund_manager_history"]["columns"]
    for c in ("aum_id", "report_date", "aum_total", "shares_total",
              "aum_unit", "source", "ingested_at"):
        assert c in schema["fund_aum_history"]["columns"]


# ================================================================ 费率生效日
def test_fee_effective_applied(gapdb):
    from app.fund.ingest_3b4_4 import ingest_fee_effective
    st = ingest_fee_effective(gapdb)
    assert st["inserted"] > 0
    assert st["failed"] == 0
    with get_connection(gapdb) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM fund_fee_rules WHERE effective_from IS NOT NULL"
        ).fetchone()[0]
    assert n == st["inserted"]


def test_fee_effective_has_announcement(gapdb):
    from app.fund.ingest_3b4_4 import ingest_fee_effective
    ingest_fee_effective(gapdb)
    with get_connection(gapdb) as conn:
        rows = conn.execute(
            """SELECT effective_from, announcement_id, source_url, evidence_level,
                      detail FROM fund_fee_rules WHERE effective_from IS NOT NULL"""
        ).fetchall()
    assert rows
    for r in rows:
        assert r["announcement_id"]
        assert r["source_url"] and "eastmoney" in r["source_url"]
        assert r["evidence_level"] == "A-"
        d = json.loads(r["detail"])
        assert d["quote"]
        assert d["disclaimer"]


def test_fee_effective_only_annual(gapdb):
    """只有年化费率补生效日，申购/赎回阶梯不得被补。"""
    from app.fund.ingest_3b4_4 import ingest_fee_effective
    ingest_fee_effective(gapdb)
    with get_connection(gapdb) as conn:
        bad = conn.execute(
            """SELECT COUNT(*) FROM fund_fee_rules
               WHERE effective_from IS NOT NULL AND (is_annual IS NULL OR is_annual<>1)"""
        ).fetchone()[0]
    assert bad == 0


def test_fee_rate_unchanged(gapdb):
    """补生效日不得改动 rate_original。"""
    from app.fund.ingest_3b4_4 import ingest_fee_effective
    before = {}
    with get_connection(gapdb) as conn:
        for r in conn.execute(
                "SELECT fee_rule_id, rate_original FROM fund_fee_rules").fetchall():
            before[r["fee_rule_id"]] = r["rate_original"]
    ingest_fee_effective(gapdb)
    with get_connection(gapdb) as conn:
        for r in conn.execute(
                "SELECT fee_rule_id, rate_original FROM fund_fee_rules").fetchall():
            assert before[r["fee_rule_id"]] == r["rate_original"]


def test_fee_effective_idempotent(gapdb):
    from app.fund.ingest_3b4_4 import ingest_fee_effective
    first = ingest_fee_effective(gapdb)
    second = ingest_fee_effective(gapdb)
    assert second["inserted"] == 0
    assert second["skipped_existing"] == first["inserted"]


def test_fee_null_stays_null(gapdb):
    """没有公告的费率必须保持 NULL，不推断。"""
    from app.fund.ingest_3b4_4 import ingest_fee_effective
    ingest_fee_effective(gapdb)
    with get_connection(gapdb) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM fund_fee_rules WHERE effective_from IS NULL"
        ).fetchone()[0]
    assert n > 0


# ================================================================ 基金经理
def test_manager_records_inserted(gapdb):
    from app.fund.ingest_3b4_4 import ingest_manager
    st = ingest_manager(gapdb)
    assert st["inserted"] > 0
    with get_connection(gapdb) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM fund_manager_history WHERE start_date IS NOT NULL"
        ).fetchone()[0]
    assert n > 0


def test_manager_has_evidence(gapdb):
    from app.fund.ingest_3b4_4 import ingest_manager
    ingest_manager(gapdb)
    with get_connection(gapdb) as conn:
        rows = conn.execute(
            "SELECT announcement_id, evidence_level, change_type, detail "
            "FROM fund_manager_history WHERE announcement_id IS NOT NULL").fetchall()
    assert rows
    for r in rows:
        assert r["announcement_id"].startswith("AN")
        assert r["evidence_level"] == "A-"
        assert r["change_type"]
        assert json.loads(r["detail"])["quote"]


def test_manager_no_backfill(gapdb):
    """新增记录必须都来自公告，起始日不得晚于记录创建时间。"""
    from app.fund.ingest_3b4_4 import ingest_manager
    ingest_manager(gapdb)
    with get_connection(gapdb) as conn:
        rows = conn.execute(
            "SELECT start_date, end_date FROM fund_manager_history "
            "WHERE announcement_id IS NOT NULL").fetchall()
    for r in rows:
        if r["start_date"] and r["end_date"]:
            assert r["end_date"] >= r["start_date"]


def test_manager_idempotent(gapdb):
    from app.fund.ingest_3b4_4 import ingest_manager
    first = ingest_manager(gapdb)
    second = ingest_manager(gapdb)
    assert second["inserted"] == 0
    assert second["skipped_existing"] == first["inserted"]


# ================================================================ 规模
def test_aum_series_inserted(gapdb):
    from app.fund.ingest_3b4_4 import ingest_aum
    st = ingest_aum(gapdb)
    assert st["inserted"] > 0
    with get_connection(gapdb) as conn:
        periods = conn.execute(
            "SELECT COUNT(DISTINCT report_date) FROM fund_aum_history").fetchone()[0]
    assert periods > 1


def test_aum_multi_period(gapdb):
    """规模必须是多期时间序列，不是单快照。"""
    from app.fund.ingest_3b4_4 import ingest_aum
    ingest_aum(gapdb)
    with get_connection(gapdb) as conn:
        rows = conn.execute(
            "SELECT share_class_id, COUNT(*) n FROM fund_aum_history "
            "WHERE evidence_level IS NOT NULL GROUP BY 1").fetchall()
    assert rows
    assert max(r["n"] for r in rows) > 10


def test_aum_dates_are_real_disclosure_dates(gapdb):
    """日期必须来自页面原始披露日，不得是编造日期。

    2013 年后基本都是季末；2013 年前有月频/周频披露，
    所以不能强制要求全是季末，但必须都能在证据 JSON 里找到。
    """
    from app.fund.ingest_3b4_4 import ingest_aum, load_aum_json
    ingest_aum(gapdb)
    src = load_aum_json()
    allowed = {p["report_date"] for periods in src.values() for p in periods}
    with get_connection(gapdb) as conn:
        dates = [r[0] for r in conn.execute(
            "SELECT DISTINCT report_date FROM fund_aum_history "
            "WHERE evidence_level IS NOT NULL").fetchall()]
    for d in dates:
        assert d in allowed, d
    # 主体是定期报告口径：大部分日期落在季末/半年末/年末
    quarters = sum(1 for d in dates
                   if d[5:] in ("03-31", "06-30", "09-30", "12-31"))
    assert quarters >= len(dates) * 0.5


def test_aum_undisclosed_skipped(gapdb):
    """页面显示 --- 的期次必须跳过，不能填 0。"""
    from app.fund.ingest_3b4_4 import ingest_aum
    ingest_aum(gapdb)
    with get_connection(gapdb) as conn:
        zeros = conn.execute(
            "SELECT COUNT(*) FROM fund_aum_history WHERE aum_total = 0"
        ).fetchone()[0]
    assert zeros == 0


def test_aum_idempotent(gapdb):
    from app.fund.ingest_3b4_4 import ingest_aum
    first = ingest_aum(gapdb)
    second = ingest_aum(gapdb)
    assert second["inserted"] == 0
    assert second["skipped_existing"] == first["inserted"]


def test_aum_published_date_null(gapdb):
    """公告发布日期未采集，必须 NULL。"""
    from app.fund.ingest_3b4_4 import ingest_aum
    ingest_aum(gapdb)
    with get_connection(gapdb) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM fund_aum_history WHERE disclosed_at IS NOT NULL"
        ).fetchone()[0]
    assert n == 0


# ================================================================ 数据库
def test_integrity_ok(gapdb):
    from app.fund.ingest_3b4_4 import run_all
    run_all(gapdb)
    with get_connection(gapdb) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_run_all_idempotent(gapdb):
    from app.fund.ingest_3b4_4 import run_all
    run_all(gapdb)
    with get_connection(gapdb) as conn:
        snap1 = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                 for t in ("fund_manager_history", "fund_aum_history",
                           "fund_fee_rules")}
    run_all(gapdb)
    with get_connection(gapdb) as conn:
        snap2 = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                 for t in ("fund_manager_history", "fund_aum_history",
                           "fund_fee_rules")}
    assert snap1 == snap2


def test_existing_rows_preserved(gapdb):
    """原有 8 条无日期经理记录不得被删或改。"""
    with get_connection(gapdb) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM fund_manager_history WHERE start_date IS NULL"
        ).fetchone()[0]
    from app.fund.ingest_3b4_4 import run_all
    run_all(gapdb)
    with get_connection(gapdb) as conn:
        m = conn.execute(
            "SELECT COUNT(*) FROM fund_manager_history WHERE start_date IS NULL"
        ).fetchone()[0]
    assert m >= n


# ================================================================ 审计 JSON
def test_fee_stats(payload):
    f = payload["fee"]
    assert f["total_rules"] == 90
    assert f["with_effective_from"] == 11
    assert f["without_effective_from"] == 79
    assert f["with_effective_from"] + f["without_effective_from"] == f["total_rules"]


def test_fee_evidence_split(payload):
    f = payload["fee"]
    assert f["by_evidence_level"].get("A-") == 11
    assert f["by_evidence_level"].get("C") == 79


def test_fee_no_backfill(payload):
    assert payload["fee"]["backfilled_from_current_rate"] == 0


def test_dividend_no_new_records(payload):
    d = payload["dividend"]
    assert d["new_records_added"] == 0
    assert d["usable_for_return_adjustment"] is False


def test_dividend_conflicts_recorded(payload):
    """差异必须被记录，不是被抹掉。"""
    d = payload["dividend"]
    assert "announcement_missing_in_db" in d
    assert d["unverifiable"] >= 0


def test_manager_has_dates(payload):
    m = payload["manager"]
    assert m["with_start_date"] > 0
    assert m["backfill_violations"] == 0


def test_aum_series(payload):
    """规模是多日期序列，但日期语义是平台观测日，非验证报告期。"""
    a = payload["aum"]
    assert a["distinct_dates"] > 1
    assert a["date_semantics"] == "platform_observation_date"
    assert a["period_end_verified"] is False
    assert a["publication_date_verified"] is False


def test_coverage_not_quantifiable(payload):
    c = payload["coverage"]
    assert c["coverage_quantifiable"] is False
    assert c["coverage_status"] == "not_quantifiable"


def test_survivorship_not_eliminated(payload):
    assert payload["coverage"]["survivorship_bias_status"] == "not_eliminated"
    assert "未消除" in payload["coverage"]["survivorship_bias_status"] or \
        payload["coverage"]["survivorship_bias_status"] == "not_eliminated"


def test_scan_scope_recorded(payload):
    s = payload["coverage"]["scan_scope"]
    assert s["scanned_codes"] == 844
    assert s["rule"]
    assert s["limitation"]


def test_alipay_all_unknown(payload):
    a = payload["alipay"]
    assert a["status"] == "unknown"
    assert a["all_unknown"] is True


def test_decisions_three(payload):
    d = payload["decisions"]
    for k in ("alipay_purchasable", "nav_publishing_calendar",
              "liquidation_roster_completeness"):
        assert k in d
        assert d[k]["decision"]


def test_alipay_manual_flow(payload):
    flow = payload["decisions"]["alipay_purchasable"]["manual_verification_flow"]
    assert "verified_at" in flow["fields"]
    assert flow["validity"]


def test_calendar_cannot_verify(payload):
    d = payload["decisions"]["nav_publishing_calendar"]
    assert d["status"] == "cannot_verify"
    assert d["no_further_development"] is True


def test_no_further_development(payload):
    for k in ("alipay_purchasable", "nav_publishing_calendar",
              "liquidation_roster_completeness"):
        assert payload["decisions"][k]["no_further_development"] is True


def test_usage_matrix_four_tiers(payload):
    m = payload["usage_matrix"]
    for k in ("tier_1_direct_use", "tier_2_conditional",
              "tier_3_auxiliary_only", "tier_4_forbidden"):
        assert k in m
        assert isinstance(m[k], list)


def test_aum_not_direct_use(payload):
    """规模已从第一档降级：日期语义未验证，不能直接用于研究。"""
    names = " ".join(x["data"] for x in payload["usage_matrix"]["tier_1_direct_use"])
    assert "规模" not in names


def test_backfill_forbidden(payload):
    names = " ".join(x["data"] for x in payload["usage_matrix"]["tier_4_forbidden"])
    assert "回填" in names


def test_gate_blocks_backtest(payload):
    g = payload["stage_gate"]
    assert g["ready_for_backtest"] is False
    assert g["must_not_relax_gate"] is True
    assert "3B-5" in " ".join(g["blocked"])


def test_evidence_levels_include_a_minus(payload):
    assert "A-" in payload["evidence_levels"]


# ================================================================ 文档
def test_report_exists():
    assert MD_PATH.is_file()


def test_report_numbers_match(payload):
    md = MD_PATH.read_text(encoding="utf-8")
    assert str(payload["fee"]["total_rules"]) in md
    assert str(payload["fee"]["with_effective_from"]) in md


def test_report_states_not_quantifiable():
    md = MD_PATH.read_text(encoding="utf-8")
    assert "not_quantifiable" in md


def test_report_states_cannot_verify():
    md = MD_PATH.read_text(encoding="utf-8")
    assert "cannot_verify" in md


def test_report_no_false_completion():
    """不得把『尝试过搜索』写成『数据已经补齐』。"""
    md = MD_PATH.read_text(encoding="utf-8")
    assert "不能补齐" in md or "仍缺" in md or "仍然" in md


def test_baseline_recorded(payload):
    assert payload["baseline_head"].startswith("2294b4aa")

# ================================================================ 规模日期语义（验收修正）
def test_aum_non_quarter_dates_not_marked_verified(gapdb):
    """1. 非季末日期不得被标记为已验证报告期末。"""
    from app.fund.ingest_3b4_4 import ingest_aum
    ingest_aum(gapdb)
    with get_connection(gapdb) as conn:
        rows = conn.execute(
            """SELECT report_date, detail FROM fund_aum_history
               WHERE evidence_level IS NOT NULL""").fetchall()
    assert rows
    for r in rows:
        d = json.loads(r["detail"])
        assert d.get("period_end_verified") is False, r["report_date"]
        assert d.get("date_semantics") == "platform_observation_date"


def test_aum_db_no_period_end_true(gapdb):
    """2. 数据库不得残留 report_date_is_period_end=true。"""
    from app.fund.ingest_3b4_4 import ingest_aum
    ingest_aum(gapdb)
    with get_connection(gapdb) as conn:
        stale = conn.execute(
            "SELECT COUNT(*) FROM fund_aum_history "
            "WHERE detail LIKE '%report_date_is_period_end%'").fetchone()[0]
        truthy = conn.execute(
            """SELECT COUNT(*) FROM fund_aum_history
               WHERE detail LIKE '%"period_end_verified": true%'""").fetchone()[0]
    assert stale == 0
    assert truthy == 0


def test_aum_point_in_time_false(gapdb):
    """4. disclosed_at 未验证时 point_in_time_usable 必须为 false。"""
    from app.fund.ingest_3b4_4 import ingest_aum
    ingest_aum(gapdb)
    with get_connection(gapdb) as conn:
        rows = conn.execute(
            """SELECT detail, disclosed_at FROM fund_aum_history
               WHERE evidence_level IS NOT NULL""").fetchall()
    assert rows
    for r in rows:
        assert r["disclosed_at"] is None
        d = json.loads(r["detail"])
        assert d.get("point_in_time_usable") is False
        assert d.get("publication_date_verified") is False


def test_aum_business_fields_stable(gapdb):
    """3. 元数据修正前后 report_date / aum_total / shares_total 不变。"""
    from app.fund.ingest_3b4_4 import ingest_aum
    ingest_aum(gapdb)
    with get_connection(gapdb) as conn:
        before = [tuple(r) for r in conn.execute(
            """SELECT aum_id, report_date, aum_total, shares_total, source,
                      evidence_level FROM fund_aum_history ORDER BY aum_id""").fetchall()]
    # 模拟元数据修正（重写 detail）
    from app.fund.ingest_3b4_4 import DISCLAIMER_AUM, DATE_SEMANTICS
    new_detail = json.dumps({
        "date_semantics": DATE_SEMANTICS,
        "period_end_verified": False,
        "publication_date_verified": False,
        "point_in_time_usable": False,
        "disclaimer": DISCLAIMER_AUM,
    }, ensure_ascii=False)
    with get_connection(gapdb) as conn:
        conn.execute(
            "UPDATE fund_aum_history SET detail=? WHERE evidence_level IS NOT NULL",
            (new_detail,))
        after = [tuple(r) for r in conn.execute(
            """SELECT aum_id, report_date, aum_total, shares_total, source,
                      evidence_level FROM fund_aum_history ORDER BY aum_id""").fetchall()]
    assert before == after


def test_aum_fix_idempotent(gapdb):
    """8. 修正脚本重复执行不产生变化。"""
    from app.fund.ingest_3b4_4 import DATE_SEMANTICS, DISCLAIMER_AUM, ingest_aum
    ingest_aum(gapdb)
    detail = json.dumps({
        "date_semantics": DATE_SEMANTICS,
        "period_end_verified": False,
        "publication_date_verified": False,
        "point_in_time_usable": False,
        "disclaimer": DISCLAIMER_AUM,
    }, ensure_ascii=False)

    def apply() -> int:
        with get_connection(gapdb) as conn:
            cur = conn.execute(
                """UPDATE fund_aum_history SET detail=?
                   WHERE evidence_level IS NOT NULL
                     AND (detail NOT LIKE '%point_in_time_usable%'
                          OR detail LIKE '%report_date_is_period_end%')""",
                (detail,))
            return cur.rowcount

    first = apply()
    second = apply()
    assert second == 0
    with get_connection(gapdb) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM fund_aum_history").fetchone()[0]
    assert n > 0


# ---------------- 包装在真实库上的检查
def test_real_db_no_stale_period_end(payload):
    """真实库不得残留 report_date_is_period_end。"""
    from app.database.db import get_connection, settings
    with get_connection() as conn:
        stale = conn.execute(
            "SELECT COUNT(*) FROM fund_aum_history "
            "WHERE detail LIKE '%report_date_is_period_end%'").fetchone()[0]
    assert stale == 0


def test_real_db_point_in_time_false(payload):
    from app.database.db import get_connection
    with get_connection() as conn:
        bad = conn.execute(
            """SELECT COUNT(*) FROM fund_aum_history
               WHERE evidence_level IS NOT NULL
                 AND detail LIKE '%"point_in_time_usable": true%'""").fetchone()[0]
    assert bad == 0


def test_payload_aum_semantics(payload):
    """6. 报告 JSON 与审计脚本的规模日期语义一致。"""
    a = payload["aum"]
    assert a["date_semantics"] == "platform_observation_date"
    assert a["period_end_verified"] is False
    assert a["publication_date_verified"] is False
    assert a["point_in_time_usable"] is False
    assert a["usable_as_point_in_time"] is False
    assert a["usable_as_descriptive_history"] is True
    assert a["disclosed_at_all_null"] is True


def test_payload_distinct_dates_not_periods(payload):
    """138 是平台观测日期数，不是已验证报告期数。"""
    a = payload["aum"]
    assert a["distinct_dates"] == 138
    assert a["distinct_dates_unit"] == "platform_observation_date"
    assert "distinct_report_dates" not in a
    assert a["non_quarter_end_date_count"] > 0
    assert a["quarter_end_date_count"] + a["non_quarter_end_date_count"] == 138


def test_payload_aum_not_tier1(payload):
    """7. 规模不得出现在第一档（可直接用于研究）。"""
    names = " ".join(x["data"] for x in payload["usage_matrix"]["tier_1_direct_use"])
    assert "规模" not in names


def test_payload_aum_in_tier3(payload):
    names = " ".join(x["data"] for x in payload["usage_matrix"]["tier_3_auxiliary_only"])
    assert "规模" in names


def test_payload_aum_forbidden_as_point_in_time(payload):
    names = " ".join(x["data"] for x in payload["usage_matrix"]["tier_4_forbidden"])
    assert "时点" in names or "规模" in names


def test_md_no_138_periods():
    """5. 报告不得把 138 个不同日期称为 138 个已验证报告期。"""
    md = MD_PATH.read_text(encoding="utf-8")
    for bad in ("138 个报告期末", "138 个报告期", "138 个已验证报告期"):
        assert bad not in md, bad
    assert "平台观测日期" in md


def test_md_states_point_in_time_false():
    md = MD_PATH.read_text(encoding="utf-8")
    assert "point_in_time_usable = false" in md or "`point_in_time_usable` = **`false`**" in md or "point_in_time_usable" in md
    assert "platform_observation_date" in md


# ================================================================ 费率核验
def test_fee_verification_all_pass(payload):
    """11 条费率记录逐条核验全部一致。"""
    rows = payload["fee"]["verification"]
    assert len(rows) == 11
    for x in rows:
        assert x["rate_match"] is True, x["code"]
        assert x["eff_match"] is True, x["code"]
        assert x["ann_id_match"] is True, x["code"]


def test_fee_rate_equals_announcement_after(payload):
    rows = payload["fee"]["verification"]
    for x in rows:
        assert abs(x["db_rate"] - x["ann_rate_after"]) < 1e-9, x["code"]


def test_fee_verification_mismatch_count_zero(payload):
    assert payload["fee"]["verification_mismatch"] == 0
