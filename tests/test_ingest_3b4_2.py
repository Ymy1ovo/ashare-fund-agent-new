"""阶段3B-4.2 关键历史数据正式入库专项测试。

全部使用独立临时数据库 + JSON 数据源，不联网、不碰正式库。
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
from app.fund.ingest_3b4_2 import (  # noqa: E402
    DISCLAIMER, FEE_PLATFORM, ONSHORE_ETF_CODES, load_calibration,
    load_fee_audit, select_offmarket_events,
)
from app.fund.migration import ensure_fund_schema  # noqa: E402
from app.fund.migration_3b4_2 import (  # noqa: E402
    FEE_COLUMNS, LIFECYCLE_COLUMNS, current_schema, ensure_3b4_2_schema,
)

CAL_JSON = ROOT / "reports" / "phase3B4_1_1_types_evidence_calibration.json"
FEE_JSON = ROOT / "reports" / "phase3B4_1_1_historical_roster_fee_audit.json"


# ---------------------------------------------------------------- fixtures
@pytest.fixture(scope="module")
def calibration() -> dict:
    return load_calibration()


@pytest.fixture(scope="module")
def fee_audit() -> dict:
    return load_fee_audit()


# 3B-4.0 已入库的 12 只存续基金份额代码。
# 费率入库只做「给已有份额补费率」，不为费率新建份额，
# 所以测试库必须先预置这 12 个份额（与正式库一致）。
EXISTING_SHARE_CODES = (
    "000015", "000016", "000051", "000198", "000478",
    "007300", "007301", "012414", "110020", "110022", "161005", "161725",
)


def _seed_existing_funds(db_path) -> None:
    """预置 12 只存续基金的本体与份额（模拟 3B-4.0 已入库状态）。"""
    now = "2026-11-19T00:00:00"
    with get_connection(db_path) as conn:
        for code in EXISTING_SHARE_CODES:
            conn.execute(
                """INSERT OR IGNORE INTO fund_master
                   (fund_code_primary, fund_name, lifecycle_status, source, ingested_at)
                   VALUES (?,?,?,?,?)""",
                (code, f"测试基金{code}", "active", "test.seed", now))
            fid = conn.execute(
                "SELECT fund_id FROM fund_master WHERE fund_code_primary=?",
                (code,)).fetchone()[0]
            conn.execute(
                """INSERT OR IGNORE INTO fund_share_classes
                   (fund_id, share_class_code, share_class_name, share_class_type,
                    is_primary, source, ingested_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (fid, code, f"测试基金{code}", "plain", 1, "test.seed", now))


@pytest.fixture()
def fund_db(tmp_path, monkeypatch):
    """独立临时库 + 场外基金建表 + 预置 12 只存续基金（不碰正式库）。"""
    db_path = tmp_path / "fund_3b4_2.db"
    monkeypatch.setattr(db_module, "settings",
                        type("S", (), {"database_path": db_path})())
    ensure_fund_schema(db_path)
    ensure_3b4_2_schema(db_path)
    _seed_existing_funds(db_path)
    return db_path


@pytest.fixture()
def ingested(fund_db):
    from app.fund.ingest_3b4_2 import ingest_fees, ingest_lifecycle
    life = ingest_lifecycle(fund_db)
    fees = ingest_fees(fund_db)
    return {"db": fund_db, "life": life, "fees": fees}


# ---------------------------------------------------------------- 迁移
def test_migration_adds_lifecycle_columns(fund_db):
    cols = current_schema(fund_db)["fund_lifecycle_events"]["columns"]
    for name, _ in LIFECYCLE_COLUMNS:
        assert name in cols, name


def test_migration_adds_fee_columns(fund_db):
    cols = current_schema(fund_db)["fund_fee_rules"]["columns"]
    for name, _ in FEE_COLUMNS:
        assert name in cols, name


def test_migration_is_idempotent(fund_db):
    first = ensure_3b4_2_schema(fund_db)
    second = ensure_3b4_2_schema(fund_db)
    assert sum(len(v) for v in second.values()) == 0
    # 第一次已经加过（fixture 里加过），此处再跑应为 0
    assert sum(len(v) for v in first.values()) == 0


def test_migration_keeps_existing_columns(fund_db):
    cols = current_schema(fund_db)["fund_fee_rules"]["columns"]
    for old in ("fee_rule_id", "share_class_id", "fee_type", "tier_order",
                "lower_bound", "upper_bound", "rate", "holding_days_min",
                "holding_days_max", "effective_from", "effective_to",
                "source", "evidence_level", "ingested_at"):
        assert old in cols, old


def test_migration_creates_fingerprint_index(fund_db):
    idx = current_schema(fund_db)["fund_lifecycle_events"]["indexes"]
    assert "uq_fund_life_fingerprint" in idx


# ---------------------------------------------------------------- 范围筛选
def test_selects_41_offmarket(calibration):
    off, excluded = select_offmarket_events(calibration)
    assert len(off) == 41
    assert len(excluded) == 2


def test_excludes_onshore_etf(calibration):
    off, excluded = select_offmarket_events(calibration)
    off_codes = {c for r in off for c in r["codes_in_event"]}
    for code in ONSHORE_ETF_CODES:
        assert code not in off_codes
    exc_codes = {c for r in excluded for c in r["codes_in_event"]}
    assert set(ONSHORE_ETF_CODES) <= exc_codes


def test_offmarket_structures_only(calibration):
    off, _ = select_offmarket_events(calibration)
    allowed = {"ordinary_open_ended", "etf_linked", "lof"}
    assert {r["product_structure"] for r in off} <= allowed


def test_structure_distribution(calibration):
    off, _ = select_offmarket_events(calibration)
    from collections import Counter
    c = Counter(r["product_structure"] for r in off)
    assert c["ordinary_open_ended"] == 27
    assert c["etf_linked"] == 3
    assert c["lof"] == 11


# ---------------------------------------------------------------- 生命周期入库
def test_lifecycle_41_rows(ingested):
    assert ingested["life"]["stat"]["inserted"] == 41
    with get_connection(ingested["db"]) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM fund_lifecycle_events "
            "WHERE source='dfcfw.announcement.calibrated'").fetchone()[0]
    assert n == 41


def test_lifecycle_excluded_2(ingested):
    assert ingested["life"]["stat"]["excluded"] == 2
    with get_connection(ingested["db"]) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM fund_lifecycle_events "
            "WHERE fund_codes LIKE '%511000%' OR fund_codes LIKE '%511050%'"
        ).fetchone()[0]
    assert n == 0


def test_lifecycle_all_b(ingested):
    with get_connection(ingested["db"]) as conn:
        rows = conn.execute(
            "SELECT evidence_level, COUNT(*) FROM fund_lifecycle_events "
            "WHERE source='dfcfw.announcement.calibrated' GROUP BY evidence_level"
        ).fetchall()
    assert {r[0]: r[1] for r in rows} == {"B": 41}


def test_lifecycle_has_url_and_id(ingested):
    with get_connection(ingested["db"]) as conn:
        bad = conn.execute(
            "SELECT COUNT(*) FROM fund_lifecycle_events "
            "WHERE source='dfcfw.announcement.calibrated' "
            "AND (announcement_url IS NULL OR announcement_id IS NULL)").fetchone()[0]
    assert bad == 0


def test_lifecycle_has_disclaimer(ingested):
    with get_connection(ingested["db"]) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM fund_lifecycle_events "
            "WHERE source='dfcfw.announcement.calibrated' AND detail LIKE ?",
            (f"%{DISCLAIMER[:15]}%",)).fetchone()[0]
    assert n == 41


def test_lifecycle_multi_code_single_entity(ingested):
    """多份额代码不能生成多个基金本体。"""
    with get_connection(ingested["db"]) as conn:
        rows = conn.execute(
            "SELECT fund_codes, fund_id FROM fund_lifecycle_events "
            "WHERE source='dfcfw.announcement.calibrated'").fetchall()
        fids = [r["fund_id"] for r in rows]
    assert len(fids) == len(set(fids)), "同一事件生成了多个 fund_id"
    multi = [r for r in rows if "," in (r["fund_codes"] or "")]
    assert len(multi) >= 10
    for r in multi:
        assert len(r["fund_codes"].split(",")) >= 2


def test_lifecycle_null_date_stays_null(ingested):
    """缺失清算开始日必须保持 NULL，不能填公告日期。"""
    with get_connection(ingested["db"]) as conn:
        rows = conn.execute(
            "SELECT event_date, announcement_date FROM fund_lifecycle_events "
            "WHERE source='dfcfw.announcement.calibrated'").fetchall()
    nulls = [r for r in rows if r["event_date"] is None]
    assert len(nulls) >= 10, "应有一批记录没有清算开始日"
    for r in nulls:
        assert r["announcement_date"] is not None
        # 不能把公告日冒充事件日
        assert r["event_date"] != r["announcement_date"]


def test_lifecycle_idempotent(ingested):
    from app.fund.ingest_3b4_2 import ingest_lifecycle
    second = ingest_lifecycle(ingested["db"])
    assert second["stat"]["inserted"] == 0
    assert second["stat"]["skipped_existing"] == 41
    with get_connection(ingested["db"]) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM fund_lifecycle_events "
            "WHERE source='dfcfw.announcement.calibrated'").fetchone()[0]
    assert n == 41


def test_lifecycle_does_not_touch_alipay(ingested):
    with get_connection(ingested["db"]) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM fund_subscription_status "
            "WHERE alipay_purchasable <> 'unknown'").fetchone()[0]
    assert n == 0


# ---------------------------------------------------------------- 费率入库
def test_fee_rows_inserted(ingested):
    assert ingested["fees"]["stat"]["inserted"] > 0
    with get_connection(ingested["db"]) as conn:
        n = conn.execute("SELECT COUNT(*) FROM fund_fee_rules").fetchone()[0]
    assert n == ingested["fees"]["stat"]["inserted"]


def test_fee_types_present(ingested):
    with get_connection(ingested["db"]) as conn:
        rows = conn.execute(
            "SELECT fee_type, COUNT(*) FROM fund_fee_rules GROUP BY fee_type").fetchall()
    got = {r[0]: r[1] for r in rows}
    for t in ("purchase", "redemption", "management", "custody", "sales_service"):
        assert t in got, t


def test_fee_original_and_platform_separated(ingested):
    """原始费率与平台优惠费率必须分列，且平台名是 eastmoney 不是 alipay。"""
    with get_connection(ingested["db"]) as conn:
        rows = conn.execute(
            "SELECT rate_original, rate_platform, platform_name FROM fund_fee_rules "
            "WHERE fee_type='purchase' AND rate_platform IS NOT NULL").fetchall()
    assert rows
    for r in rows:
        assert r["platform_name"] == FEE_PLATFORM
        assert r["platform_name"] != "alipay"
        assert r["rate_original"] > r["rate_platform"]


def test_fee_platform_never_alipay(ingested):
    with get_connection(ingested["db"]) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM fund_fee_rules WHERE platform_name='alipay'"
        ).fetchone()[0]
    assert n == 0


def test_fee_amount_tier_bounds(ingested):
    with get_connection(ingested["db"]) as conn:
        rows = conn.execute(
            "SELECT * FROM fund_fee_rules WHERE fee_type='purchase' "
            "ORDER BY share_class_id, tier_order").fetchall()
    assert rows
    for r in rows:
        d = dict(r)
        if d["upper_bound"] is not None and d["lower_bound"] is not None:
            assert d["upper_bound"] > d["lower_bound"]
        assert d["lower_inclusive"] in (0, 1, None)
        assert d["upper_inclusive"] in (0, 1, None)


def test_fee_holding_days_bounds(ingested):
    with get_connection(ingested["db"]) as conn:
        rows = conn.execute(
            "SELECT * FROM fund_fee_rules WHERE fee_type='redemption' "
            "ORDER BY share_class_id, tier_order").fetchall()
    assert rows
    for r in rows:
        d = dict(r)
        if d["holding_days_max"] is not None:
            assert d["holding_days_max"] >= d["holding_days_min"]


def test_fee_inclusive_flags_present(ingested):
    """闭区间与开区间必须能表达：每档都要有 min/max inclusive 标记。"""
    with get_connection(ingested["db"]) as conn:
        rows = conn.execute(
            "SELECT * FROM fund_fee_rules WHERE fee_type='redemption'").fetchall()
    for r in rows:
        d = dict(r)
        assert d["holding_days_min_inclusive"] in (0, 1)
        if d["holding_days_max"] is not None:
            assert d["holding_days_max_inclusive"] in (0, 1)


def test_fee_inferred_lower_flagged(ingested):
    """首档无显式下界时补 0，必须标 inferred=1。"""
    with get_connection(ingested["db"]) as conn:
        rows = conn.execute(
            "SELECT holding_days_min, holding_days_min_inferred FROM "
            "fund_fee_rules WHERE fee_type='redemption' AND tier_order=0").fetchall()
    inferred = [r for r in rows if r["holding_days_min_inferred"] == 1]
    assert inferred, "应有推断下界"
    for r in inferred:
        assert r["holding_days_min"] == 0


def test_fee_missing_rate_is_null(ingested):
    """缺失费率必须 NULL，不能填 0。"""
    with get_connection(ingested["db"]) as conn:
        rows = conn.execute(
            "SELECT fee_type, rate_original FROM fund_fee_rules "
            "WHERE rate_original IS NULL").fetchall()
    assert rows, "应至少有一条 NULL 费率（110022 销售服务费 ---）"
    for r in rows:
        assert r["rate_original"] is None


def test_fee_none_rate_not_zero(ingested):
    """110022 销售服务费页面是 ---，必须是 NULL 而不是 0。"""
    with get_connection(ingested["db"]) as conn:
        rows = conn.execute(
            "SELECT rate_original FROM fund_fee_rules f "
            "JOIN fund_share_classes s ON s.share_class_id=f.share_class_id "
            "WHERE s.share_class_code='110022' AND f.fee_type='sales_service'"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["rate_original"] is None


def test_money_fund_no_fake_redeem(ingested):
    """货币基金 000198 没有赎回阶梯，不得伪造。"""
    with get_connection(ingested["db"]) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM fund_fee_rules f "
            "JOIN fund_share_classes s ON s.share_class_id=f.share_class_id "
            "WHERE s.share_class_code='000198' AND f.fee_type='redemption'"
        ).fetchone()[0]
    assert n == 0


def test_fee_evidence_c(ingested):
    with get_connection(ingested["db"]) as conn:
        rows = conn.execute(
            "SELECT evidence_level, COUNT(*) FROM fund_fee_rules "
            "GROUP BY evidence_level").fetchall()
    assert {r[0]: r[1] for r in rows} == {"C": 90}


def test_fee_effective_dates_null(ingested):
    """抓取日期不得冒充历史生效日期。"""
    with get_connection(ingested["db"]) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM fund_fee_rules WHERE effective_from IS NOT NULL"
        ).fetchone()[0]
    assert n == 0
    # 但 fetched_at 必须有值（那是抓取时间，不是生效时间）
    with get_connection(ingested["db"]) as conn:
        m = conn.execute(
            "SELECT COUNT(*) FROM fund_fee_rules WHERE fetched_at IS NULL"
        ).fetchone()[0]
    assert m == 0


def test_fee_holding_basis_null(ingested):
    """自然日/交易日未确认，必须 NULL。"""
    with get_connection(ingested["db"]) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM fund_fee_rules WHERE holding_days_basis IS NOT NULL"
        ).fetchone()[0]
    assert n == 0


def test_fee_annual_flagged(ingested):
    with get_connection(ingested["db"]) as conn:
        rows = conn.execute(
            "SELECT fee_type FROM fund_fee_rules WHERE is_annual=1 "
            "GROUP BY fee_type").fetchall()
    assert {r[0] for r in rows} == {"management", "custody", "sales_service"}


def test_fee_idempotent(ingested):
    from app.fund.ingest_3b4_2 import ingest_fees
    before = None
    with get_connection(ingested["db"]) as conn:
        before = conn.execute("SELECT COUNT(*) FROM fund_fee_rules").fetchone()[0]
    second = ingest_fees(ingested["db"])
    assert second["stat"]["inserted"] == 0
    with get_connection(ingested["db"]) as conn:
        after = conn.execute("SELECT COUNT(*) FROM fund_fee_rules").fetchone()[0]
    assert before == after == 90


# ---------------------------------------------------------------- 数据库
def test_integrity_ok(ingested):
    with get_connection(ingested["db"]) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_foreign_keys_ok(ingested):
    with get_connection(ingested["db"]) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_unique_constraint_works(ingested):
    """同一 fingerprint 不能插两次（DB 层面兜底）。"""
    import sqlite3
    with get_connection(ingested["db"]) as conn:
        row = conn.execute(
            "SELECT fund_id, event_fingerprint, event_type, source, ingested_at "
            "FROM fund_lifecycle_events LIMIT 1").fetchone()
    with pytest.raises(sqlite3.IntegrityError):
        with get_connection(ingested["db"]) as conn:
            conn.execute(
                "INSERT INTO fund_lifecycle_events "
                "(fund_id, event_type, evidence_level, source, ingested_at, "
                " event_fingerprint) VALUES (?,?,?,?,?,?)",
                (row["fund_id"], row["event_type"], "B", row["source"],
                 row["ingested_at"], row["event_fingerprint"]))


def test_existing_data_preserved(ingested):
    """净值/分红/经理等原有数据不受影响（临时库里本来为空，验证表仍存在）。"""
    with get_connection(ingested["db"]) as conn:
        for t in ("fund_nav_daily", "fund_dividends", "fund_manager_history",
                  "fund_aum_history", "fund_data_quality"):
            assert conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone() is not None


def test_repository_still_compatible(ingested):
    """现有数据层 Repository 仍能正常使用。"""
    from app.fund.repository import FundRepository
    repo = FundRepository(ingested["db"])
    assert repo.count_master() >= 41
    # 现有方法仍可用
    assert repo.get_master_by_code("000007") is not None


# ---------------------------------------------------------------- 数据源未变
def test_source_json_untouched(calibration):
    """校准 JSON 仍是 43 条，未被导入过程改写。"""
    assert len(calibration["calibration"]) == 43


def test_fee_source_untouched(fee_audit):
    assert fee_audit["count"] == 12

# ================================================================ 主从标记（验收修正）
from app.fund.ingest_3b4_2 import (  # noqa: E402
    ShareOwnershipError, _ensure_share, _pick_primary_code,
)


def _primaries_of(db, fund_id: int) -> list[str]:
    with get_connection(db) as conn:
        rows = conn.execute(
            "SELECT share_class_code FROM fund_share_classes "
            "WHERE fund_id=? AND is_primary=1", (fund_id,)).fetchall()
    return sorted(r["share_class_code"] for r in rows)


def _all_shares_of(db, fund_id: int) -> list[dict]:
    with get_connection(db) as conn:
        rows = conn.execute(
            "SELECT share_class_code, is_primary FROM fund_share_classes "
            "WHERE fund_id=? ORDER BY share_class_code", (fund_id,)).fetchall()
    return [dict(r) for r in rows]


def _fund_id_by_code(db, code: str) -> int:
    with get_connection(db) as conn:
        return int(conn.execute(
            "SELECT fund_id FROM fund_share_classes WHERE share_class_code=?",
            (code,)).fetchone()[0])


# ---------------- 1~3. 单/双/三代码本体恰好一个主份额
def test_single_code_fund_has_one_primary(ingested):
    fid = _fund_id_by_code(ingested["db"], "000007")
    assert _primaries_of(ingested["db"], fid) == ["000007"]


def test_two_code_fund_has_one_primary(ingested):
    fid = _fund_id_by_code(ingested["db"], "000022")
    prim = _primaries_of(ingested["db"], fid)
    assert len(prim) == 1
    assert prim == ["000022"]


def test_three_code_fund_has_one_primary(ingested):
    fid = _fund_id_by_code(ingested["db"], "000091")
    prim = _primaries_of(ingested["db"], fid)
    assert len(prim) == 1
    shares = _all_shares_of(ingested["db"], fid)
    assert len(shares) == 3


# ---------------- 4. 主代码与 _pick_primary_code 一致
def test_primary_matches_pick_rule(ingested):
    with get_connection(ingested["db"]) as conn:
        rows = conn.execute(
            "SELECT fund_id, fund_codes FROM fund_lifecycle_events "
            "WHERE source='dfcfw.announcement.calibrated'").fetchall()
    for r in rows:
        codes = [c for c in (r["fund_codes"] or "").split(",") if c]
        expected = _pick_primary_code(codes)
        assert _primaries_of(ingested["db"], int(r["fund_id"])) == [expected], \
            (r["fund_codes"], expected)


# ---------------- 5. 其他份额全部 is_primary=0
def test_all_other_shares_non_primary(ingested):
    with get_connection(ingested["db"]) as conn:
        rows = conn.execute(
            "SELECT fund_id, fund_codes FROM fund_lifecycle_events "
            "WHERE source='dfcfw.announcement.calibrated'").fetchall()
    checked = 0
    for r in rows:
        codes = [c for c in (r["fund_codes"] or "").split(",") if c]
        if len(codes) < 2:
            continue
        primary = _pick_primary_code(codes)
        for sh in _all_shares_of(ingested["db"], int(r["fund_id"])):
            if sh["share_class_code"] == primary:
                assert sh["is_primary"] == 1
            else:
                assert sh["is_primary"] == 0, (sh, primary)
            checked += 1
    assert checked >= 20


# ---------------- 6. 重复导入后主从关系不变
def test_primary_unchanged_after_reimport(ingested):
    from app.fund.ingest_3b4_2 import ingest_lifecycle
    before = {}
    with get_connection(ingested["db"]) as conn:
        for r in conn.execute(
                "SELECT fund_id, share_class_code, is_primary "
                "FROM fund_share_classes WHERE fund_id>=23").fetchall():
            before[(r["fund_id"], r["share_class_code"])] = r["is_primary"]
    ingest_lifecycle(ingested["db"])
    after = {}
    with get_connection(ingested["db"]) as conn:
        for r in conn.execute(
                "SELECT fund_id, share_class_code, is_primary "
                "FROM fund_share_classes WHERE fund_id>=23").fetchall():
            after[(r["fund_id"], r["share_class_code"])] = r["is_primary"]
    assert before == after


# ---------------- 7. 已存在且同本体的份额可复用
def test_existing_share_same_fund_reused(fund_db):
    with get_connection(fund_db) as conn:
        fid = conn.execute(
            "SELECT fund_id FROM fund_share_classes WHERE share_class_code='000051'"
        ).fetchone()[0]
        sid1 = _ensure_share(conn, int(fid), "000051", "测试", "2026-01-01")
        sid2 = _ensure_share(conn, int(fid), "000051", "测试", "2026-01-01")
    assert sid1 == sid2


# ---------------- 8. 已存在但属于其他本体的份额必须报错
def test_share_owned_by_other_fund_raises(fund_db):
    with get_connection(fund_db) as conn:
        real_fid = conn.execute(
            "SELECT fund_id FROM fund_share_classes WHERE share_class_code='000051'"
        ).fetchone()[0]
        other_fid = int(real_fid) + 9999
        conn.execute(
            "INSERT INTO fund_master (fund_code_primary, fund_name, lifecycle_status, "
            "source, ingested_at) VALUES ('999999','别的基金','terminated','test','2026-01-01')")
        other_fid = conn.execute(
            "SELECT fund_id FROM fund_master WHERE fund_code_primary='999999'"
        ).fetchone()[0]
        with pytest.raises(ShareOwnershipError) as ei:
            _ensure_share(conn, int(other_fid), "000051", "测试", "2026-01-01")
    assert ei.value.code == "000051"
    assert ei.value.actual_fund_id == int(real_fid)
    assert ei.value.expected_fund_id == int(other_fid)


def test_conflict_does_not_reassign(fund_db):
    """报错后归属不能改变。"""
    with get_connection(fund_db) as conn:
        original = int(conn.execute(
            "SELECT fund_id FROM fund_share_classes WHERE share_class_code='000015'"
        ).fetchone()[0])
        conn.execute(
            "INSERT INTO fund_master (fund_code_primary, fund_name, lifecycle_status, "
            "source, ingested_at) VALUES ('888888','别的','terminated','test','2026-01-01')")
        other = int(conn.execute(
            "SELECT fund_id FROM fund_master WHERE fund_code_primary='888888'"
        ).fetchone()[0])
        with pytest.raises(ShareOwnershipError):
            _ensure_share(conn, other, "000015", "测试", "2026-01-01")
        still = int(conn.execute(
            "SELECT fund_id FROM fund_share_classes WHERE share_class_code='000015'"
        ).fetchone()[0])
    assert still == original


# ---------------- 9. 修复脚本幂等
def test_primary_fix_idempotent(ingested):
    sys.path.insert(0, str(ROOT / "scripts"))
    import importlib
    mod = importlib.import_module("fix_3b4_2_primary_flags")
    from app.fund.ingest_3b4_2 import load_calibration as _lc
    calib = _lc()
    with get_connection(ingested["db"]) as conn:
        fixes1, _ = mod.plan_fixes(conn, calib)
        for f in fixes1:
            conn.execute(
                "UPDATE fund_share_classes SET is_primary=? WHERE share_class_id=?",
                (f["is_primary"], f["share_class_id"]))
    with get_connection(ingested["db"]) as conn:
        fixes2, _ = mod.plan_fixes(conn, calib)
        need = sum(1 for f in fixes2 if conn.execute(
            "SELECT is_primary FROM fund_share_classes WHERE share_class_id=?",
            (f["share_class_id"],)).fetchone()[0] != f["is_primary"])
    assert need == 0


# ---------------- 10. 修复不动其他基金本体
def test_primary_fix_only_touches_41_funds(ingested):
    sys.path.insert(0, str(ROOT / "scripts"))
    import importlib
    mod = importlib.import_module("fix_3b4_2_primary_flags")
    from app.fund.ingest_3b4_2 import load_calibration as _lc

    # 先记下 12 只预置存续基金的主从
    with get_connection(ingested["db"]) as conn:
        seeded = {r["share_class_code"]: r["is_primary"]
                  for r in conn.execute(
                      "SELECT share_class_code, is_primary FROM fund_share_classes "
                      "WHERE source='test.seed'").fetchall()}

    calib = _lc()
    with get_connection(ingested["db"]) as conn:
        fixes, _ = mod.plan_fixes(conn, calib)
        touched_ids = {f["share_class_id"] for f in fixes}
        for f in fixes:
            conn.execute(
                "UPDATE fund_share_classes SET is_primary=? WHERE share_class_id=?",
                (f["is_primary"], f["share_class_id"]))
        # 预置基金未被列入修复计划
        seeded_ids = {r["share_class_id"] for r in conn.execute(
            "SELECT share_class_id FROM fund_share_classes "
            "WHERE source='test.seed'").fetchall()}
        assert not (touched_ids & seeded_ids)

    with get_connection(ingested["db"]) as conn:
        after = {r["share_class_code"]: r["is_primary"]
                 for r in conn.execute(
                     "SELECT share_class_code, is_primary FROM fund_share_classes "
                     "WHERE source='test.seed'").fetchall()}
    assert after == seeded
