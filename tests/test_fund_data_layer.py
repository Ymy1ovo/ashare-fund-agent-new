"""阶段3B-4.0 场外基金数据层专项测试。

全部使用独立临时数据库 + Mock 外部接口，不联网、不污染正式库。
"""
from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

import app.database.db as db_module
from app.fund.ingest import FundIngestor, IngestStats
from app.fund.migration import FUND_TABLES, ensure_fund_schema
from app.fund.models import (
    DataQualityRecord, DividendRecord, FeeRuleRecord, FundMasterRecord,
    FundShareClassRecord, LifecycleEventRecord, ManagerRecord, NavRecord,
    SubscriptionStatusRecord,
)
from app.fund.normalize import (
    base_fund_name, detect_share_class_type, is_money_fund,
    parse_cash_per_share, to_float, to_iso_date,
)
from app.fund.repo_base import should_overwrite, source_confidence
from app.fund.repo_nav import NavRepository
from app.fund.repo_quality import QualityRepository
from app.fund.repo_status import StatusRepository
from app.fund.repository import FundRepository


@pytest.fixture
def fund_db(tmp_path, monkeypatch):
    """独立临时数据库，与正式库完全隔离。"""
    db_path = tmp_path / "fund_test.db"
    monkeypatch.setattr(db_module, "settings",
                        SimpleNamespace(database_path=db_path))
    ensure_fund_schema(db_path=db_path)
    return db_path


def _master(**kw) -> FundMasterRecord:
    base = dict(fund_code_primary="000051", fund_name="华夏沪深300ETF联接",
                source="akshare.fund_name_em", ingested_at="2026-11-19T10:00:00")
    base.update(kw)
    return FundMasterRecord(**base)


def _share(code="000051", name="华夏沪深300ETF联接A", **kw) -> FundShareClassRecord:
    base = dict(share_class_code=code, share_class_name=name,
                source="akshare.fund_name_em", ingested_at="2026-11-19T10:00:00")
    base.update(kw)
    return FundShareClassRecord(**base)


# ================================================================ 迁移
def test_migration_creates_all_ten_tables(fund_db):
    with sqlite3.connect(fund_db) as conn:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    for t in FUND_TABLES:
        assert t in names, t
    assert len(FUND_TABLES) == 10


def test_migration_is_idempotent(fund_db):
    """重复执行不建重复表、不报错、不清空数据。"""
    repo = FundRepository(fund_db)
    repo.upsert_master(_master())
    before = repo.count_master()

    ensure_fund_schema(db_path=fund_db)
    ensure_fund_schema(db_path=fund_db)

    assert repo.count_master() == before


def test_migration_does_not_touch_etf_tables(fund_db):
    """场外基金迁移不得创建或改动 ETF 表。"""
    with sqlite3.connect(fund_db) as conn:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "etf_daily_prices" not in names
    assert "backtest_runs" not in names
    assert not any(n.startswith("validation_") for n in names)


# ================================================================ 约束
def test_foreign_key_enforced(fund_db):
    """份额必须挂在一个存在的基金本体上。"""
    with sqlite3.connect(fund_db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO fund_share_classes "
                "(fund_id, share_class_code, share_class_name, source, ingested_at) "
                "VALUES (99999,'X001','孤儿份额','test','2026-11-19T10:00:00')")


def test_share_class_code_is_unique(fund_db):
    repo = FundRepository(fund_db)
    fid = repo.upsert_master(_master())
    repo.upsert_share_class(fid, _share())
    # 同一代码写两次只应有一行
    repo.upsert_share_class(fid, _share())
    assert repo.count_share_classes() == 1


def test_nav_check_constraint_rejects_mixed_kind(fund_db):
    """货币型净值行不能带 unit_nav，净值型行不能带 per_10k_yield。"""
    repo = FundRepository(fund_db)
    fid = repo.upsert_master(_master())
    sc = repo.upsert_share_class(fid, _share())
    with sqlite3.connect(fund_db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO fund_nav_daily "
                "(share_class_id, nav_date, nav_kind, unit_nav, per_10k_yield, "
                " source, ingested_at) VALUES (?,?,?,?,?,?,?)",
                (sc, "2026-01-05", "net_value", 1.5, 0.5, "test", "2026-11-19T10:00:00"))


def test_conflicting_source_cannot_overwrite_better(fund_db):
    """低置信度来源不得覆盖高置信度来源。"""
    assert should_overwrite("akshare.fund_open_fund_info_em", "manual") is False
    assert should_overwrite("manual", "akshare.fund_open_fund_info_em") is True
    assert source_confidence("official_contract") > source_confidence(
        "akshare.fund_name_em")


# ================================================================ 本体与份额
def test_master_and_share_linked(fund_db):
    repo = FundRepository(fund_db)
    fid = repo.upsert_master(_master())
    sc = repo.upsert_share_class(fid, _share())
    got = repo.get_fund_with_shares("000051")
    assert got is not None
    assert len(got["share_classes"]) == 1
    assert got["share_classes"][0]["share_class_id"] == sc


def test_ac_shares_share_one_master(fund_db):
    """A/C 必须是同一个基金本体的两个份额，不是两只基金。"""
    repo = FundRepository(fund_db)
    fid = repo.upsert_master(_master(fund_code_primary="161725",
                                     fund_name="招商中证白酒指数(LOF)"))
    a = repo.upsert_share_class(fid, _share("161725", "招商中证白酒指数(LOF)A"))
    c = repo.upsert_share_class(fid, _share("012414", "招商中证白酒指数(LOF)C"))

    assert a != c
    shares = repo.list_shares_of_fund(fid)
    assert len(shares) == 2
    assert {s["share_class_code"] for s in shares} == {"161725", "012414"}
    assert repo.count_master() == 1, "A/C 不能算成两只基金"


def test_share_codes_never_merged(fund_db):
    """份额代码必须保持独立，不能被合并。"""
    repo = FundRepository(fund_db)
    fid = repo.upsert_master(_master())
    repo.upsert_share_class(fid, _share("161725", "白酒A"))
    repo.upsert_share_class(fid, _share("012414", "白酒C"))
    assert repo.get_share_class("161725")["share_class_code"] == "161725"
    assert repo.get_share_class("012414")["share_class_code"] == "012414"


def test_unknown_established_date_stays_null(fund_db):
    """成立日期未知必须是 NULL，不能填今天。"""
    repo = FundRepository(fund_db)
    repo.upsert_master(_master(established_date=None))
    got = repo.get_master_by_code("000051")
    assert got["established_date"] is None


def test_unknown_terminated_date_stays_null(fund_db):
    repo = FundRepository(fund_db)
    repo.upsert_master(_master(terminated_date=None))
    assert repo.get_master_by_code("000051")["terminated_date"] is None


def test_lifecycle_status_defaults_unknown(fund_db):
    repo = FundRepository(fund_db)
    fid = repo.upsert_master(_master())
    assert repo.get_master(fid)["lifecycle_status"] == "unknown"


# ================================================================ 净值
def test_nav_batch_insert(fund_db):
    repo = FundRepository(fund_db)
    nav = NavRepository(fund_db)
    fid = repo.upsert_master(_master())
    sc = repo.upsert_share_class(fid, _share())

    res = nav.upsert_nav_batch(sc, [
        NavRecord(nav_date="2026-01-05", unit_nav=1.50, acc_nav=1.60,
                  ingested_at="2026-11-19T10:00:00"),
        NavRecord(nav_date="2026-01-06", unit_nav=1.52, acc_nav=1.62,
                  ingested_at="2026-11-19T10:00:00"),
    ])
    assert res["inserted"] == 2
    assert nav.count_nav("net_value") == 2


def test_unit_and_acc_nav_separate(fund_db):
    """单位净值与累计净值必须是两列，不能混用。"""
    repo = FundRepository(fund_db)
    nav = NavRepository(fund_db)
    fid = repo.upsert_master(_master())
    sc = repo.upsert_share_class(fid, _share())

    nav.upsert_nav_batch(sc, [NavRecord(
        nav_date="2026-01-05", unit_nav=2.4727, acc_nav=5.5207,
        ingested_at="2026-11-19T10:00:00")])
    row = nav.list_nav(sc)[0]
    assert row["unit_nav"] == pytest.approx(2.4727)
    assert row["acc_nav"] == pytest.approx(5.5207)
    assert row["unit_nav"] != row["acc_nav"]


def test_nav_repeat_write_is_idempotent(fund_db):
    repo = FundRepository(fund_db)
    nav = NavRepository(fund_db)
    fid = repo.upsert_master(_master())
    sc = repo.upsert_share_class(fid, _share())

    rec = NavRecord(nav_date="2026-01-05", unit_nav=1.50,
                    ingested_at="2026-11-19T10:00:00")
    nav.upsert_nav_batch(sc, [rec])
    res = nav.upsert_nav_batch(sc, [rec])
    assert res["updated"] == 1
    assert nav.count_nav("net_value") == 1


def test_nav_query_by_date_range(fund_db):
    repo = FundRepository(fund_db)
    nav = NavRepository(fund_db)
    fid = repo.upsert_master(_master())
    sc = repo.upsert_share_class(fid, _share())
    nav.upsert_nav_batch(sc, [
        NavRecord(nav_date=f"2026-01-{d:02d}", unit_nav=1.0 + d / 100,
                  ingested_at="2026-11-19T10:00:00") for d in range(1, 11)])
    rows = nav.list_nav(sc, start="2026-01-03", end="2026-01-06")
    assert [r["nav_date"] for r in rows] == [
        "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06"]


def test_money_fund_uses_separate_branch(fund_db):
    """货币基金不得伪装成单位净值型。"""
    repo = FundRepository(fund_db)
    nav = NavRepository(fund_db)
    fid = repo.upsert_master(_master(fund_code_primary="000198",
                                     fund_name="天弘余额宝货币"))
    sc = repo.upsert_share_class(fid, _share("000198", "天弘余额宝货币"))

    nav.upsert_nav_batch(sc, [NavRecord(
        nav_date="2026-01-05", nav_kind="money_yield",
        per_10k_yield=0.2340, seven_day_annual=0.891,
        source="akshare.fund_money_fund_info_em",
        ingested_at="2026-11-19T10:00:00")])

    rows = nav.list_nav(sc, nav_kind="money_yield")
    assert len(rows) == 1
    assert rows[0]["unit_nav"] is None
    assert rows[0]["acc_nav"] is None
    assert rows[0]["per_10k_yield"] == pytest.approx(0.2340)
    assert nav.count_nav("net_value") == 0


def test_money_fund_rejects_unit_nav(fund_db):
    """货币型行里塞 unit_nav 会被 CHECK 拒绝。"""
    repo = FundRepository(fund_db)
    fid = repo.upsert_master(_master(fund_code_primary="000198"))
    sc = repo.upsert_share_class(fid, _share("000198", "余额宝"))
    with sqlite3.connect(fund_db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO fund_nav_daily (share_class_id, nav_date, nav_kind, "
                "unit_nav, per_10k_yield, source, ingested_at) VALUES (?,?,?,?,?,?,?)",
                (sc, "2026-01-05", "money_yield", 1.0, 0.5, "test", "x"))


# ================================================================ 分红
def test_dividend_per_10_conversion(fund_db):
    """每10份必须除以 10。"""
    repo = FundRepository(fund_db)
    nav = NavRepository(fund_db)
    fid = repo.upsert_master(_master())
    sc = repo.upsert_share_class(fid, _share())
    nav.upsert_dividend_batch(sc, [DividendRecord(
        ex_date="2024-04-29", cash_per_share=0.021,
        per_10_raw="每10份派现金0.2100元", ingested_at="2026-11-19T10:00:00")])
    row = nav.list_dividends(sc)[0]
    assert row["cash_per_share"] == pytest.approx(0.021)
    assert row["per_10_raw"] == "每10份派现金0.2100元", "原始文本必须保留"


def test_dividend_repeat_write_idempotent(fund_db):
    repo = FundRepository(fund_db)
    nav = NavRepository(fund_db)
    fid = repo.upsert_master(_master())
    sc = repo.upsert_share_class(fid, _share())
    rec = DividendRecord(ex_date="2024-04-29", cash_per_share=0.021,
                         per_10_raw="每10份派现金0.2100元",
                         ingested_at="2026-11-19T10:00:00")
    nav.upsert_dividend_batch(sc, [rec])
    res = nav.upsert_dividend_batch(sc, [rec])
    assert res["updated"] == 1
    assert nav.count_dividends() == 1


def test_dividend_different_source_keeps_both(fund_db):
    """不同来源的同一除息日各留一条，用于保留差异证据。"""
    repo = FundRepository(fund_db)
    nav = NavRepository(fund_db)
    fid = repo.upsert_master(_master())
    sc = repo.upsert_share_class(fid, _share())
    nav.upsert_dividend_batch(sc, [
        DividendRecord(ex_date="2024-04-29", cash_per_share=0.021,
                       per_10_raw="每10份派现金0.2100元",
                       source="akshare.fund_open_fund_info_em",
                       ingested_at="2026-11-19T10:00:00"),
        DividendRecord(ex_date="2024-04-29", cash_per_share=0.022,
                       per_10_raw="每10份派现金0.2200元",
                       source="manual", ingested_at="2026-11-19T10:00:00"),
    ])
    assert nav.count_dividends() == 2


# ================================================================ 状态/费率
def test_status_snapshot_keeps_history(fund_db):
    """历史状态必须按日期保留，不能被最新值覆盖。"""
    repo = FundRepository(fund_db)
    st = StatusRepository(fund_db)
    fid = repo.upsert_master(_master())
    sc = repo.upsert_share_class(fid, _share())

    st.save_subscription_status(sc, SubscriptionStatusRecord(
        as_of_date="2026-01-05", source="akshare.fund_purchase_em",
        ingested_at="2026-11-19T10:00:00", purchase_status="开放申购"))
    st.save_subscription_status(sc, SubscriptionStatusRecord(
        as_of_date="2026-06-05", source="akshare.fund_purchase_em",
        ingested_at="2026-11-19T10:00:00", purchase_status="暂停申购"))

    rows = st.list_subscription_status(sc)
    assert len(rows) == 2
    assert rows[0]["purchase_status"] == "开放申购"
    assert rows[1]["purchase_status"] == "暂停申购"


def test_alipay_status_defaults_unknown(fund_db):
    """天天基金状态不能冒充支付宝可购买状态。"""
    repo = FundRepository(fund_db)
    st = StatusRepository(fund_db)
    fid = repo.upsert_master(_master())
    sc = repo.upsert_share_class(fid, _share())
    st.save_subscription_status(sc, SubscriptionStatusRecord(
        as_of_date="2026-01-05", source="akshare.fund_purchase_em",
        ingested_at="2026-11-19T10:00:00", purchase_status="开放申购"))
    assert st.latest_subscription_status(sc)["alipay_purchasable"] == "unknown"


def test_fee_rate_may_be_null(fund_db):
    """费率未知允许 NULL，不得填行业平均。"""
    repo = FundRepository(fund_db)
    st = StatusRepository(fund_db)
    fid = repo.upsert_master(_master())
    sc = repo.upsert_share_class(fid, _share())
    st.add_fee_rule(sc, FeeRuleRecord(
        fee_type="redemption", source="manual", ingested_at="2026-11-19T10:00:00",
        holding_days_min=0, holding_days_max=7, rate=None))
    rows = st.find_fee_rules(sc, "redemption")
    assert len(rows) == 1
    assert rows[0]["rate"] is None


def test_fee_rule_query_by_holding_days(fund_db):
    repo = FundRepository(fund_db)
    st = StatusRepository(fund_db)
    fid = repo.upsert_master(_master())
    sc = repo.upsert_share_class(fid, _share())
    for tier, lo, hi, rate in ((0, 0, 7, 0.015), (1, 7, 365, 0.005),
                               (2, 365, None, 0.0)):
        st.add_fee_rule(sc, FeeRuleRecord(
            fee_type="redemption", source="manual",
            ingested_at="2026-11-19T10:00:00", tier_order=tier,
            holding_days_min=lo, holding_days_max=hi, rate=rate))

    got = st.find_fee_rules(sc, "redemption", holding_days=30)
    assert len(got) == 1
    assert got[0]["rate"] == pytest.approx(0.005)


# ================================================================ 质量/生命周期
def test_quality_record_is_idempotent(fund_db):
    q = QualityRepository(fund_db)
    rec = DataQualityRecord(table_name="fund_nav_daily", record_key="000051:x",
                            check_name="test_check", status="ok",
                            checked_at="2026-11-19T10:00:00")
    q.record(rec)
    q.record(rec)
    assert q.count() == 1


def test_quality_records_mismatch(fund_db):
    q = QualityRepository(fund_db)
    q.record(DataQualityRecord(
        table_name="fund_nav_daily", record_key="000051:date_mismatch",
        check_name="unit_acc_date_mismatch", status="mismatch",
        detail="单位净值独有 2 日", severity="warning",
        checked_at="2026-11-19T10:00:00"))
    rows = q.list_issues(status="mismatch")
    assert len(rows) == 1
    assert rows[0]["severity"] == "warning"


def test_lifecycle_event_idempotent(fund_db):
    repo = FundRepository(fund_db)
    fid = repo.upsert_master(_master())
    ev = LifecycleEventRecord(event_type="established", source="test",
                              ingested_at="2026-11-19T10:00:00",
                              event_date="2009-07-10")
    repo.add_lifecycle_event(fid, ev)
    repo.add_lifecycle_event(fid, ev)
    assert len(repo.list_lifecycle_events(fid)) == 1


def test_manager_tenure_dates_may_be_null(fund_db):
    """经理任职起止未知必须 NULL，不得用今天伪造。"""
    repo = FundRepository(fund_db)
    fid = repo.upsert_master(_master())
    repo.add_manager(fid, ManagerRecord(
        manager_name="赵宗庭", source="test",
        ingested_at="2026-11-19T10:00:00"))
    row = repo.list_managers(fid)[0]
    assert row["start_date"] is None
    assert row["end_date"] is None


def test_manager_idempotent(fund_db):
    repo = FundRepository(fund_db)
    fid = repo.upsert_master(_master())
    rec = ManagerRecord(manager_name="赵宗庭", source="test",
                        ingested_at="2026-11-19T10:00:00")
    repo.add_manager(fid, rec)
    repo.add_manager(fid, rec)
    assert len(repo.list_managers(fid)) == 1


# ================================================================ 事务回滚
def test_transaction_rollback_on_error(fund_db):
    """异常必须回滚，不留下半条记录。"""
    repo = FundRepository(fund_db)
    fid = repo.upsert_master(_master())
    sc = repo.upsert_share_class(fid, _share())
    before = NavRepository(fund_db).count_nav()

    with pytest.raises(sqlite3.IntegrityError):
        with db_module.get_connection(fund_db) as conn:
            conn.execute(
                "INSERT INTO fund_nav_daily (share_class_id, nav_date, nav_kind, "
                "unit_nav, source, ingested_at) VALUES (?,?,?,?,?,?)",
                (sc, "2026-01-05", "net_value", 1.5, "test", "x"))
            # 故意触发约束冲突
            conn.execute(
                "INSERT INTO fund_nav_daily (share_class_id, nav_date, nav_kind, "
                "unit_nav, per_10k_yield, source, ingested_at) VALUES (?,?,?,?,?,?,?)",
                (sc, "2026-01-06", "net_value", 1.6, 0.5, "test", "x"))

    assert NavRepository(fund_db).count_nav() == before


# ================================================================ 归一化
def test_parse_cash_per_share_never_returns_ten():
    for raw in ("每10份派现金0.2100元", "每10份派现金0.3800元"):
        assert parse_cash_per_share(raw) != pytest.approx(1.0)
    assert parse_cash_per_share("每10份派现金0.2100元") == pytest.approx(0.021)
    assert parse_cash_per_share(None) is None


def test_detect_share_class_type():
    assert detect_share_class_type("华夏沪深300ETF联接A") == "A"
    assert detect_share_class_type("招商中证白酒指数(LOF)C") == "C"
    assert detect_share_class_type("易方达消费行业股票") == "plain"


def test_base_fund_name_strips_suffix():
    assert base_fund_name("招商中证白酒指数(LOF)A") == "招商中证白酒指数(LOF)"
    assert base_fund_name("华夏沪深300ETF联接A") == "华夏沪深300ETF联接"


def test_is_money_fund():
    assert is_money_fund("货币型-普通货币") is True
    assert is_money_fund("股票型-标准指数") is False
    assert is_money_fund(None) is False


def test_to_float_never_invents_zero():
    """空值不能变成 0，必须返回 None。"""
    assert to_float(None) is None
    assert to_float("") is None
    assert to_float("abc") is None
    assert to_float("1.23") == pytest.approx(1.23)


def test_to_iso_date():
    assert to_iso_date("2024-04-29 00:00:00") == "2024-04-29"
    assert to_iso_date(None) is None
    assert to_iso_date("nan") is None


# ================================================================ 导入（Mock）
def _mock_ingestor(db_path) -> FundIngestor:
    return FundIngestor(
        db_path,
        fetch_name_table=lambda: [{
            "fund_code": "161725", "fund_name": "招商中证白酒指数(LOF)A",
            "fund_type": "指数型-股票"}],
        fetch_basic=lambda code: {
            "full_name": "招商中证白酒指数证券投资基金",
            "established": "2015-05-27", "scale": "209.47亿",
            "company": "招商基金", "manager": "侯昊",
            "type": "股票型-标准指数",
            "benchmark": "中证白酒指数收益率×95%",
            "custodian": "中国银行", "invest_scope": "跟踪中证白酒指数"},
        fetch_nav=lambda code, kind: (
            [{"nav_date": "2026-01-05", "unit_nav": 0.5791},
             {"nav_date": "2026-01-06", "unit_nav": 0.5800}]
            if kind == "unit" else
            [{"nav_date": "2026-01-05", "acc_nav": 2.2952},
             {"nav_date": "2026-01-06", "acc_nav": 2.2960}]),
        fetch_money=lambda code: [],
        fetch_fund_dividends=lambda code: [{
            "record_date": "2024-04-29", "ex_date": "2024-04-29",
            "pay_date": "2024-05-06", "per_10_raw": "每10份派现金0.4500元"}],
        fetch_purchase=lambda: {"161725": {
            "purchase_status": "限大额", "redeem_status": "开放赎回",
            "min_purchase": 10.0, "daily_limit": 500000.0,
            "next_open_date": None}},
    )


def test_ingest_end_to_end_with_mock(fund_db):
    ing = _mock_ingestor(fund_db)
    stats = IngestStats()
    name_row = {"fund_code": "161725", "fund_name": "招商中证白酒指数(LOF)A",
                "fund_type": "指数型-股票"}
    basic = ing._fetch_basic("161725")
    fid, sc = ing.ingest_master_and_share(name_row=name_row, basic=basic, stats=stats)
    ing.ingest_nav("161725", sc, is_money=False, stats=stats)
    ing.ingest_dividends("161725", sc, stats=stats)
    ing.ingest_status("161725", sc, purchase_row=ing._fetch_purchase()["161725"],
                      stats=stats)

    repo = FundRepository(fund_db)
    nav = NavRepository(fund_db)
    st = StatusRepository(fund_db)
    assert repo.count_master() == 1
    assert repo.count_share_classes() == 1
    assert nav.count_nav("net_value") == 2
    assert nav.count_dividends() == 1
    assert st.count_subscription_status() == 1

    master = repo.get_master(fid)
    assert master["established_date"] == "2015-05-27"
    assert master["terminated_date"] is None, "清盘日期不得推测"
    assert master["lifecycle_status"] == "unknown"


def test_ingest_nav_missing_acc_nav_is_recorded(fund_db):
    """单位净值与累计净值日期不一致时必须留痕，不能静默丢弃。"""
    ing = FundIngestor(
        fund_db,
        fetch_nav=lambda code, kind: (
            [{"nav_date": "2026-01-05", "unit_nav": 1.0},
             {"nav_date": "2026-01-06", "unit_nav": 1.1}]
            if kind == "unit" else
            [{"nav_date": "2026-01-05", "acc_nav": 1.2}]),
    )
    repo = FundRepository(fund_db)
    fid = repo.upsert_master(_master())
    sc = repo.upsert_share_class(fid, _share())
    res = ing.ingest_nav("000051", sc, is_money=False, stats=IngestStats())
    assert res["unit_only_dates"] == 1

    issues = QualityRepository(fund_db).list_issues(status="mismatch")
    assert len(issues) == 1
    assert "date_mismatch" in issues[0]["record_key"]


def test_ingest_money_fund_branch(fund_db):
    """货币基金走 money_yield 分支，不写 unit_nav。"""
    ing = FundIngestor(
        fund_db,
        fetch_money=lambda code: [
            {"nav_date": "2026-01-05", "per_10k_yield": 0.2340,
             "seven_day_annual": 0.891}],
    )
    repo = FundRepository(fund_db)
    fid = repo.upsert_master(_master(fund_code_primary="000198",
                                     fund_name="天弘余额宝货币"))
    sc = repo.upsert_share_class(fid, _share("000198", "天弘余额宝货币"))
    res = ing.ingest_nav("000198", sc, is_money=True, stats=IngestStats())
    assert res["kind"] == "money_yield"

    nav = NavRepository(fund_db)
    assert nav.count_nav("money_yield") == 1
    assert nav.count_nav("net_value") == 0


def test_ingest_duplicate_run_no_duplicates(fund_db):
    """同一批数据导入两次不产生重复行。"""
    ing = _mock_ingestor(fund_db)
    name_row = {"fund_code": "161725", "fund_name": "招商中证白酒指数(LOF)A",
                "fund_type": "指数型-股票"}
    for _ in range(2):
        basic = ing._fetch_basic("161725")
        fid, sc = ing.ingest_master_and_share(name_row=name_row, basic=basic,
                                              stats=IngestStats())
        ing.ingest_nav("161725", sc, is_money=False, stats=IngestStats())
        ing.ingest_dividends("161725", sc, stats=IngestStats())

    repo = FundRepository(fund_db)
    nav = NavRepository(fund_db)
    assert repo.count_master() == 1
    assert repo.count_share_classes() == 1
    assert nav.count_nav("net_value") == 2
    assert nav.count_dividends() == 1


def test_ingest_lifecycle_established_event(fund_db):
    ing = _mock_ingestor(fund_db)
    name_row = {"fund_code": "161725", "fund_name": "招商中证白酒指数(LOF)A",
                "fund_type": "指数型-股票"}
    fid, _ = ing.ingest_master_and_share(
        name_row=name_row, basic=ing._fetch_basic("161725"), stats=IngestStats())
    events = FundRepository(fund_db).list_lifecycle_events(fid)
    assert len(events) == 1
    assert events[0]["event_type"] == "established"
    assert events[0]["event_date"] == "2015-05-27"


# ================================================================ A/C 归属
def test_group_merges_ac_shares_into_one_master(fund_db):
    """A/C 两份额必须归到同一个基金本体，master 只 1 行。"""
    ing = FundIngestor(
        fund_db,
        fetch_name_table=lambda: [],
        fetch_basic=lambda code: {"full_name": f"测试基金{code}",
                                  "established": "2013-03-08",
                                  "company": "华夏基金",
                                  "manager": "柳万军",
                                  "type": "债券型-长期纯债",
                                  "scale": "108.71亿"},
    )
    members = [
        {"fund_code": "000015", "fund_name": "华夏纯债债券A",
         "fund_type": "债券型-长债"},
        {"fund_code": "000016", "fund_name": "华夏纯债债券C",
         "fund_type": "债券型-长债"},
    ]
    basics = {m["fund_code"]: ing._fetch_basic(m["fund_code"]) for m in members}
    res = ing.ingest_fund_group(members, basics=basics, stats=IngestStats())

    assert res["merged"] is True
    assert res["needs_review"] is False
    assert res["primary_code"] == "000015", "A 类应作为主代码"

    repo = FundRepository(fund_db)
    assert repo.count_master() == 1, "A/C 不能算成两只基金"
    assert repo.count_share_classes() == 2
    shares = repo.list_shares_of_fund(res["fund_id"])
    assert {s["share_class_code"] for s in shares} == {"000015", "000016"}
    assert {s["share_class_type"] for s in shares} == {"A", "C"}


def test_group_does_not_merge_different_bases(fund_db):
    """基础名不一致时不得强行合并。"""
    ing = FundIngestor(fund_db, fetch_name_table=lambda: [],
                       fetch_basic=lambda code: {})
    members = [
        {"fund_code": "000051", "fund_name": "华夏沪深300ETF联接A",
         "fund_type": "指数型-股票"},
        {"fund_code": "110020", "fund_name": "易方达沪深300ETF联接A",
         "fund_type": "指数型-股票"},
    ]
    res = ing.ingest_fund_group(members, basics={}, stats=IngestStats())
    assert res["merged"] is False
    assert res["needs_review"] is True, "无法可靠归属时必须标待核实"
    assert FundRepository(fund_db).count_master() == 2


def test_group_single_member_is_independent(fund_db):
    ing = FundIngestor(fund_db, fetch_name_table=lambda: [],
                       fetch_basic=lambda code: {"established": "2009-07-10"})
    members = [{"fund_code": "000051", "fund_name": "华夏沪深300ETF联接A",
                "fund_type": "指数型-股票"}]
    res = ing.ingest_fund_group(members, basics={"000051": {"established":
                                                            "2009-07-10"}},
                                stats=IngestStats())
    assert res["merged"] is False
    assert res["needs_review"] is False, "单成员不是待核实"
    assert res["fund_id"] is not None
    assert FundRepository(fund_db).count_master() == 1


def test_group_repeat_run_idempotent(fund_db):
    ing = FundIngestor(fund_db, fetch_name_table=lambda: [],
                       fetch_basic=lambda code: {"established": "2013-03-08"})
    members = [
        {"fund_code": "000015", "fund_name": "华夏纯债债券A",
         "fund_type": "债券型-长债"},
        {"fund_code": "000016", "fund_name": "华夏纯债债券C",
         "fund_type": "债券型-长债"},
    ]
    basics = {m["fund_code"]: ing._fetch_basic(m["fund_code"]) for m in members}
    ing.ingest_fund_group(members, basics=basics, stats=IngestStats())
    ing.ingest_fund_group(members, basics=basics, stats=IngestStats())

    repo = FundRepository(fund_db)
    assert repo.count_master() == 1
    assert repo.count_share_classes() == 2


# ================================================================ 货币基金完整链路
def test_money_fund_full_ingest_has_no_unit_nav(fund_db):
    """货币基金全链路：只有 money_yield 行，净净值行必须为 0。"""
    ing = FundIngestor(
        fund_db,
        fetch_name_table=lambda: [],
        fetch_basic=lambda code: {},          # 货币基金雪球接口会失败
        fetch_money=lambda code: [
            {"nav_date": "2026-01-05", "per_10k_yield": 0.2340,
             "seven_day_annual": 0.891},
            {"nav_date": "2026-01-06", "per_10k_yield": 0.2658,
             "seven_day_annual": 0.880}],
    )
    members = [{"fund_code": "000198", "fund_name": "天弘余额宝货币",
                "fund_type": "货币型-普通货币"}]
    res = ing.ingest_fund_group(members, basics={}, stats=IngestStats())
    sc = res["share_ids"]["000198"]
    ing.ingest_nav("000198", sc, is_money=True, stats=IngestStats())

    nav = NavRepository(fund_db)
    assert nav.count_nav("money_yield") == 2
    assert nav.count_nav("net_value") == 0
    rows = nav.list_nav(sc, nav_kind="money_yield")
    assert all(r["unit_nav"] is None for r in rows)
