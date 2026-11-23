"""阶段3B-5.4 多类型场外基金接入与研究验证专项测试。

全部使用临时 SQLite + 注入式假抓取器，不联网、不碰正式库。
覆盖六类产品 + AC 归组 + 口径隔离 + 证据边界。
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.fund.ingest_user_funds import (  # noqa: E402
    ST_ALREADY_PRESENT, ST_EXCLUDED, ST_FAILED, ST_INGESTED, UserFundIngestor,
    db_fingerprint, ingest_many,
)
from app.fund.migration import ensure_fund_schema  # noqa: E402
from app.fund.migration_3b4_2 import ensure_3b4_2_schema  # noqa: E402
from app.fund.migration_3b4_4 import ensure_3b4_4_schema  # noqa: E402
from app.fund.research.data_access import load_universe  # noqa: E402
from app.fund.research.engine import analyze_by_code  # noqa: E402


def _make_db(tmp_path: Path) -> Path:
    db = tmp_path / "multi.db"
    ensure_fund_schema(db)
    ensure_3b4_2_schema(db)
    ensure_3b4_4_schema(db)
    return db


def _rows(start="2018-01-01", n=600, base=1.0, step=0.0005):
    d0 = date.fromisoformat(start)
    return [((d0 + timedelta(days=i)).isoformat(), round(base + i * step, 6))
            for i in range(n)]


def _basic(name, ftype, company="测试基金公司", est="2018-01-01"):
    return lambda code: {"name": name, "full_name": name + "全称",
                         "company": company, "type": ftype,
                         "benchmark": "沪深300指数收益率×95%",
                         "custodian": "测试银行", "invest_scope": "测试",
                         "established": est}


def _nav_fake(start="2018-01-01", n=600):
    unit = [{"nav_date": d, "unit_nav": v} for d, v in _rows(start, n)]
    acc = [{"nav_date": d, "acc_nav": v} for d, v in _rows(start, n)]
    return lambda c, k: unit if k == "unit" else acc


def _money_fake(start="2018-01-01", n=600):
    return [{"nav_date": d, "per_10k_yield": 0.6, "seven_day_annual": 2.2}
            for d, _ in _rows(start, n)]


def _ing(db, name, ftype, *, company="测试基金公司", money=False):
    kw = dict(fetch_basic=_basic(name, ftype, company),
              fetch_dividend=lambda c: [])
    if money:
        kw["fetch_money"] = lambda c: _money_fake()
    else:
        kw["fetch_nav"] = _nav_fake()
    return UserFundIngestor(db, **kw)


# ================================================================ 六类产品
def test_type_ordinary_index(tmp_path):
    db = _make_db(tmp_path)
    r = _ing(db, "测试普通指数基金", "股票型-标准指数").ingest_one("021001")
    assert r.status == ST_INGESTED
    assert r.product_class == "ordinary_index"


def test_type_etf_linked(tmp_path):
    db = _make_db(tmp_path)
    r = _ing(db, "测试沪深300ETF联接A", "股票型-标准指数").ingest_one("021002")
    assert r.status == ST_INGESTED
    assert r.product_class == "etf_linked"


def test_type_active_equity(tmp_path):
    db = _make_db(tmp_path)
    r = _ing(db, "测试主动股票基金", "股票型-普通").ingest_one("021003")
    assert r.status == ST_INGESTED
    assert r.product_class == "active_equity"


def test_type_mixed_fund(tmp_path):
    """混合型在 3B-5.0 九类体系里归入 active_equity（不单独设类）。"""
    db = _make_db(tmp_path)
    r = _ing(db, "测试混合型基金", "混合型-偏股").ingest_one("021004")
    assert r.status == ST_INGESTED
    assert r.product_class == "active_equity"
    assert r.investment_subtype == "active"
    # fund_type_l1 保留原值，可区分「股票型」与「混合型」
    with sqlite3.connect(db) as conn:
        l1 = conn.execute("SELECT fund_type_l1 FROM fund_master").fetchone()[0]
    assert l1 == "混合型-偏股"


def test_type_bond(tmp_path):
    db = _make_db(tmp_path)
    r = _ing(db, "测试纯债债券基金", "债券型-长期纯债").ingest_one("021005")
    assert r.status == ST_INGESTED
    assert r.product_class == "bond_pure"


def test_type_money(tmp_path):
    db = _make_db(tmp_path)
    r = _ing(db, "测试货币基金", "货币型", money=True).ingest_one("021006")
    assert r.status == ST_INGESTED
    assert r.product_class == "money_market"
    assert r.nav_kind == "money_yield"
    # 货币收益不得写成 net_value
    with sqlite3.connect(db) as conn:
        kinds = {x[0] for x in conn.execute(
            "SELECT DISTINCT nav_kind FROM fund_nav_daily")}
    assert kinds == {"money_yield"}


def test_six_types_all_ingested(tmp_path):
    """六类一次性全部接入成功。"""
    db = _make_db(tmp_path)
    specs = [
        ("021010", "测试普通指数", "股票型-标准指数", False),
        ("021011", "测试ETF联接A", "股票型-标准指数", False),
        ("021012", "测试主动股票", "股票型-普通", False),
        ("021013", "测试混合基金", "混合型-偏股", False),
        ("021014", "测试纯债基金", "债券型-长期纯债", False),
        ("021015", "测试货币基金", "货币型", True),
    ]
    got = []
    for code, name, ftype, money in specs:
        r = _ing(db, name, ftype, money=money).ingest_one(code)
        assert r.status == ST_INGESTED, (code, r.reason)
        got.append(r.product_class)
    assert set(got) == {"ordinary_index", "etf_linked", "active_equity",
                        "bond_pure", "money_market"}
    # 混合型与主动权益同属 active_equity，故去重后 5 类
    assert len(set(got)) == 5


# ================================================================ AC 归组
def test_ac_pair_same_entity(tmp_path):
    db = _make_db(tmp_path)
    a = _ing(db, "测试双份额基金A", "债券型-长期纯债").ingest_one("021020")
    c = _ing(db, "测试双份额基金C", "债券型-长期纯债").ingest_one("021021")
    assert a.status == ST_INGESTED and c.status == ST_INGESTED
    assert a.fund_id == c.fund_id
    with sqlite3.connect(db) as conn:
        shares = conn.execute(
            "SELECT share_class_code, is_primary FROM fund_share_classes "
            "WHERE fund_id=? ORDER BY share_class_code", (a.fund_id,)).fetchall()
    assert len(shares) == 2
    assert dict(shares)["021020"] == 1   # A 为主份额
    assert dict(shares)["021021"] == 0


def test_ac_pair_two_pairs(tmp_path):
    """两组 AC 各自归入独立本体，不互相合并。"""
    db = _make_db(tmp_path)
    a1 = _ing(db, "基金甲A", "股票型-普通").ingest_one("021022")
    c1 = _ing(db, "基金甲C", "股票型-普通").ingest_one("021023")
    a2 = _ing(db, "基金乙A", "股票型-普通").ingest_one("021024")
    c2 = _ing(db, "基金乙C", "股票型-普通").ingest_one("021025")
    assert a1.fund_id == c1.fund_id
    assert a2.fund_id == c2.fund_id
    assert a1.fund_id != a2.fund_id
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM fund_master").fetchone()[0] == 2


def test_ac_different_company_not_merged(tmp_path):
    db = _make_db(tmp_path)
    a = _ing(db, "同名基金A", "股票型-普通", company="甲公司").ingest_one("021026")
    c = _ing(db, "同名基金C", "股票型-普通", company="乙公司").ingest_one("021027")
    assert a.fund_id != c.fund_id


def test_ac_missing_company_not_merged(tmp_path):
    db = _make_db(tmp_path)
    a = _ing(db, "缺公司基金A", "股票型-普通", company="甲公司").ingest_one("021028")
    c = _ing(db, "缺公司基金C", "股票型-普通", company=None).ingest_one("021029")
    assert a.fund_id != c.fund_id


# ================================================================ 幂等与指纹
def test_reingest_idempotent(tmp_path):
    db = _make_db(tmp_path)
    r1 = _ing(db, "测试幂等基金", "股票型-普通").ingest_one("021030")
    fp1 = r1.fingerprint_after["sha256"]
    n1 = r1.nav_rows_total
    r2 = _ing(db, "测试幂等基金", "股票型-普通").ingest_one("021030")
    assert r2.status == ST_ALREADY_PRESENT
    assert r2.fingerprint_after["sha256"] == fp1
    assert r2.nav_rows_total == n1


def test_fingerprint_detects_content_change(tmp_path):
    db = _make_db(tmp_path)
    _ing(db, "测试指纹基金", "股票型-普通").ingest_one("021031")
    before = db_fingerprint(db)["sha256"]
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE fund_nav_daily SET unit_nav=unit_nav+0.01 "
                     "WHERE nav_kind='net_value' AND nav_date=(SELECT MIN(nav_date) "
                     "FROM fund_nav_daily WHERE nav_kind='net_value')")
        conn.commit()
    assert db_fingerprint(db)["sha256"] != before


# ================================================================ 证据边界
def test_alipay_status_unknown(tmp_path):
    db = _make_db(tmp_path)
    r = _ing(db, "测试支付宝边界基金", "股票型-普通").ingest_one("021032")
    rep = analyze_by_code("021032", db)["reports"][0]
    assert rep["admission_levels"]["alipay_purchasable"] == "unknown"
    assert r.status == ST_INGESTED


def test_onshore_etf_rejected(tmp_path):
    db = _make_db(tmp_path)
    for code in ("511000", "511050"):
        assert _ing(db, "测试ETF", "股票型-标准指数").ingest_one(code).status == ST_EXCLUDED


def test_qdii_rejected(tmp_path):
    db = _make_db(tmp_path)
    r = _ing(db, "测试QDII", "QDII-股票").ingest_one("021033")
    assert r.status == ST_EXCLUDED


def test_dividend_absent_not_faked(tmp_path):
    db = _make_db(tmp_path)
    _ing(db, "测试无分红基金", "股票型-普通").ingest_one("021034")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM fund_dividends").fetchone()[0] == 0


def test_gap_recorded_not_hidden(tmp_path):
    db = _make_db(tmp_path)
    left = _rows("2018-01-01", 200)
    right = [((date.fromisoformat("2019-06-01") + timedelta(days=i)).isoformat(),
              round(2.0 + i * 0.0005, 6)) for i in range(200)]
    allrows = left + right
    unit = [{"nav_date": d, "unit_nav": v} for d, v in allrows]
    acc = [{"nav_date": d, "acc_nav": v} for d, v in allrows]
    ing = UserFundIngestor(
        db, fetch_basic=_basic("测试缺口基金", "股票型-普通"),
        fetch_nav=lambda c, k: unit if k == "unit" else acc,
        fetch_dividend=lambda c: [])
    r = ing.ingest_one("021035")
    assert r.status == ST_INGESTED
    assert r.quality["gap_count_over_15d"] >= 1
    assert r.quality["continuity_verification"] == "cannot_verify"
    assert r.warnings


def test_failure_no_partial(tmp_path):
    db = _make_db(tmp_path)
    before = db_fingerprint(db)["sha256"]
    ing = _ing(db, "测试失败基金", "股票型-普通")

    def boom(*a, **kw):
        raise RuntimeError("注入失败")

    ing.nav.upsert_nav_batch = boom
    r = ing.ingest_one("021036")
    assert r.status == ST_FAILED
    assert db_fingerprint(db)["sha256"] == before


def test_fk_enforced_in_tx(tmp_path):
    db = _make_db(tmp_path)
    ing = _ing(db, "测试外键基金", "股票型-普通")
    conn = ing._open_tx()
    try:
        assert int(conn.execute("PRAGMA foreign_keys").fetchone()[0]) == 1
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO fund_share_classes
                   (fund_id, share_class_code, share_class_name, share_class_type,
                    currency, is_primary, source, ingested_at)
                   VALUES (999999,'029999','孤儿','A','CNY',0,'t','t')""")
    finally:
        ing._tx = conn
        ing._rollback_tx()


def test_batch_isolates_failures(tmp_path):
    db = _make_db(tmp_path)

    def basic_switch(code):
        if code == "021041":
            raise RuntimeError("模拟失败")
        return _basic("批量基金" + code[-2:], "股票型-普通")(code)

    ing = UserFundIngestor(db, fetch_basic=basic_switch,
                           fetch_nav=_nav_fake(),
                           fetch_dividend=lambda c: [])
    doc = ingest_many(["021040", "021041", "021042"], db, ingestor=ing)
    st = [r["status"] for r in doc["results"]]
    assert st.count(ST_INGESTED) == 2
    assert st.count(ST_FAILED) == 1


# ================================================================ 研究口径
def _ingest_basic_set(db):
    _ing(db, "测试指数基金", "股票型-标准指数").ingest_one("021050")
    _ing(db, "测试主动基金", "股票型-普通").ingest_one("021051")
    _ing(db, "测试债券基金", "债券型-长期纯债").ingest_one("021052")
    _ing(db, "测试货币基金", "货币型", money=True).ingest_one("021053")


def test_money_uses_separate_scope(tmp_path):
    """货币基金不得与净值型基金同口径。"""
    db = _make_db(tmp_path)
    _ingest_basic_set(db)
    r = analyze_by_code("021053", db)
    rep = r["reports"][0]
    ind = rep["indicators"]
    assert rep["is_money_fund"] is True
    assert ind["uses_unit_nav"] is False
    assert ind["nav_based_indicators"]["status"] == "not_applicable"
    assert ind["per_10k_yield"]["usable_for_net_value_comparison"] is False
    assert "usable_for_net_value_comparison" in ind["per_10k_yield"]
    # 净值型指标字段不应出现
    assert "returns" not in ind or not ind.get("returns")


def test_money_not_in_net_value_ranking(tmp_path):
    """货币基金 peer_group 独立，不与净值型混组。"""
    db = _make_db(tmp_path)
    _ingest_basic_set(db)
    money = analyze_by_code("021053", db)
    idx = analyze_by_code("021050", db)
    assert money["merged"]["peer_group"]["peer_key"] == "money_market"
    assert idx["merged"]["peer_group"]["peer_key"].startswith("ordinary_index")


def test_ac_not_double_counted(tmp_path):
    db = _make_db(tmp_path)
    _ing(db, "测试双份额AC基金A", "股票型-普通").ingest_one("021060")
    _ing(db, "测试双份额AC基金C", "股票型-普通").ingest_one("021061")
    r = analyze_by_code("021060", db)
    assert r["fund_count"] == 1
    assert r["share_count"] == 2
    assert r["merged"]["share_count"] == 2
    assert len(r["merged"]["cost_comparison"]["shares"]) == 2


def test_sharpe_not_fabricated(tmp_path):
    """无风险利率缺失时不得输出常规 Sharpe。"""
    db = _make_db(tmp_path)
    _ingest_basic_set(db)
    ra = analyze_by_code("021051", db)["reports"][0]["indicators"]["risk_adjusted"]
    assert ra["sharpe"]["status"] == "not_available"
    assert ra["sharpe"]["value"] is None
    assert ra["sortino"]["status"] == "not_available"


def test_excess_return_not_computed(tmp_path):
    db = _make_db(tmp_path)
    _ingest_basic_set(db)
    nc = analyze_by_code("021051", db)["reports"][0]["indicators"]["not_computed"]
    assert "无基准" in nc["excess_return"]


def test_insufficient_sample_rejects_annualized(tmp_path):
    db = _make_db(tmp_path)
    ing = UserFundIngestor(
        db, fetch_basic=_basic("测试短样本基金", "股票型-普通"),
        fetch_nav=_nav_fake(n=120), fetch_dividend=lambda c: [])
    ing.ingest_one("021062")
    ann = analyze_by_code("021062", db)["reports"][0]["indicators"]["annualized_return"]
    assert ann["status"] == "insufficient_data"


def test_volatility_annualization_conditional(tmp_path):
    db = _make_db(tmp_path)
    _ingest_basic_set(db)
    vol = analyze_by_code("021050", db)["reports"][0]["indicators"]["risk"]["volatility"]
    assert vol["status"] == "ok"
    if vol["annualized"]:
        assert vol["annualization_factor"] > 0
        assert "观测频率" in vol["annualization_basis"]
    else:
        assert vol["annualization_blocked_reason"]


def test_gap_blocks_annualized(tmp_path):
    """有超阈值缺口时年化必须拒绝。"""
    db = _make_db(tmp_path)
    left = _rows("2018-01-01", 200)
    right = [((date.fromisoformat("2019-06-01") + timedelta(days=i)).isoformat(),
              round(2.0 + i * 0.0005, 6)) for i in range(400)]
    allrows = left + right
    unit = [{"nav_date": d, "unit_nav": v} for d, v in allrows]
    acc = [{"nav_date": d, "acc_nav": v} for d, v in allrows]
    ing = UserFundIngestor(
        db, fetch_basic=_basic("测试缺口年化基金", "股票型-普通"),
        fetch_nav=lambda c, k: unit if k == "unit" else acc,
        fetch_dividend=lambda c: [])
    ing.ingest_one("021063")
    ann = analyze_by_code("021063", db)["reports"][0]["indicators"]["annualized_return"]
    assert ann["status"] == "insufficient_data"
    assert "缺口" in ann["reason"]


def test_benchmark_grouping_by_family(tmp_path):
    """不同基准族必须分组。"""
    db = _make_db(tmp_path)
    _ing(db, "测试300指数基金", "股票型-标准指数").ingest_one("021070")
    ing500 = UserFundIngestor(
        db, fetch_basic=lambda c: {
            "name": "测试500指数基金", "company": "测试基金公司",
            "type": "股票型-标准指数",
            "benchmark": "95%×中证500指数收益率+5%×活期存款利率",
            "established": "2018-01-01"},
        fetch_nav=_nav_fake(), fetch_dividend=lambda c: [])
    ing500.ingest_one("021071")
    k300 = analyze_by_code("021070", db)["merged"]["peer_group"]["peer_key"]
    k500 = analyze_by_code("021071", db)["merged"]["peer_group"]["peer_key"]
    assert k300 != k500
    assert "沪深300" in k300
    assert "中证500" in k500


# ================================================================ 真实库只读
def test_production_db_integrity_only():
    from app.database.db import get_connection
    with get_connection() as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_production_original_samples_intact():
    """原有 12 份额 / 9 本体不得因本阶段缺失。"""
    ORIG = {"000015", "000016", "000051", "000198", "000478", "007300",
            "007301", "110020", "110022", "161005", "012414", "161725"}
    codes = {e["share_code"] for e in load_universe()}
    assert ORIG <= codes
    ids = {e["fund_id"] for e in load_universe() if e["share_code"] in ORIG}
    assert len(ids) == 9


def test_production_lifecycle_intact():
    from app.database.db import get_connection
    with get_connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM fund_master WHERE lifecycle_status='terminated'"
        ).fetchone()[0] >= 41


# ================================================================ 临时库隔离回归
def test_money_stats_reads_target_db_not_production(tmp_path):
    """货币统计必须读分析目标库，不能回落到正式库（3B-5.4 修复回归）。"""
    db = _make_db(tmp_path)
    _ing(db, "测试隔离货币基金", "货币型", money=True).ingest_one("021080")
    ind = analyze_by_code("021080", db)["reports"][0]["indicators"]
    st = ind["stats"]
    assert st["per_10k_yield"]["status"] == "ok"
    assert st["per_10k_yield"]["sample_days"] > 0
    assert st["seven_day_annual"]["status"] == "ok"


def test_money_stats_db_isolation_proof(tmp_path):
    """临时库有数据、正式库没有该份额时，结果必须来自临时库。"""
    db = _make_db(tmp_path)
    _ing(db, "测试隔离货币乙", "货币型", money=True).ingest_one("021081")
    a = analyze_by_code("021081", db)["reports"][0]["indicators"]["stats"]
    # 正式库里不存在 021081，若回落正式库则统计为空
    assert a["per_10k_yield"]["status"] == "ok"
    assert a["per_10k_yield"]["cumulative_per_10k"] > 0
