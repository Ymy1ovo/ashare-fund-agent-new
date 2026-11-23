"""阶段3B-5.3 用户自选基金受控接入专项测试。

全部使用临时数据库 + 注入式假抓取器，不联网、不碰正式库。
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
    ST_ALREADY_PRESENT, ST_EXCLUDED, ST_FAILED, ST_INGESTED, ST_INVALID_CODE,
    ST_NOT_FOUND, UserFundIngestor, audit_new_nav, db_fingerprint, ingest_many,
)
from app.fund.migration import ensure_fund_schema  # noqa: E402
from app.fund.migration_3b4_2 import ensure_3b4_2_schema  # noqa: E402
from app.fund.migration_3b4_4 import ensure_3b4_4_schema  # noqa: E402


# ---------------------------------------------------------------- 临时库
def _make_db(tmp_path: Path) -> Path:
    db = tmp_path / "ingest.db"
    ensure_fund_schema(db)
    ensure_3b4_2_schema(db)
    ensure_3b4_4_schema(db)
    return db


def _daily(start: str, n: int, base=1.0, step=0.001):
    d0 = date.fromisoformat(start)
    return [((d0 + timedelta(days=i)).isoformat(),
             round(base + i * step, 6)) for i in range(n)]


# ---------------------------------------------------------------- 假抓取器
def make_fakes(*, name="测试指数基金A", ftype="指数型-股票",
               start="2018-01-01", n=500, money=False):
    def basic(code):
        return {"name": name, "full_name": name + "全称", "company": "测试公司",
                "type": ftype, "benchmark": "沪深300指数收益率×95%",
                "custodian": "测试银行", "invest_scope": "跟踪指数",
                "established": "2018-01-01", "manager": "张三"}

    unit = [{"nav_date": d, "unit_nav": v} for d, v in _daily(start, n)]
    acc = [{"nav_date": d, "acc_nav": v} for d, v in _daily(start, n)]

    def nav(code, kind):
        return unit if kind == "unit" else acc

    def moneyf(code):
        return [{"nav_date": d, "per_10k_yield": 0.7, "seven_day_annual": 2.5}
                for d, _ in _daily(start, n)]

    def div(code):
        return []

    return basic, (moneyf if money else nav), div


def _ing(db: Path, **kw):
    basic, nav, div = make_fakes(**kw)
    money = kw.get("money", False)
    return UserFundIngestor(
        db, fetch_basic=basic,
        fetch_nav=(None if money else nav),
        fetch_money=(nav if money else None),
        fetch_dividend=div)


# ================================================================ 1-5 分类接入
def test_ingest_ordinary_index(tmp_path):
    db = _make_db(tmp_path)
    r = _ing(db).ingest_one("012345")
    assert r.status == ST_INGESTED
    assert r.product_class == "ordinary_index"
    assert r.nav_kind == "net_value"
    assert r.nav_rows_written > 0


def test_ingest_etf_linked(tmp_path):
    db = _make_db(tmp_path)
    r = _ing(db, name="测试沪深300ETF联接", ftype="指数型-股票").ingest_one("012346")
    assert r.status == ST_INGESTED
    assert r.product_class == "etf_linked"


def test_ingest_active_equity(tmp_path):
    db = _make_db(tmp_path)
    r = _ing(db, name="测试主动股票", ftype="股票型").ingest_one("012347")
    assert r.status == ST_INGESTED
    assert r.product_class == "active_equity"


def test_ingest_bond(tmp_path):
    db = _make_db(tmp_path)
    r = _ing(db, name="测试纯债债券", ftype="债券型-长债").ingest_one("012348")
    assert r.status == ST_INGESTED
    assert r.product_class == "bond_pure"


def test_ingest_money_independent(tmp_path):
    db = _make_db(tmp_path)
    r = _ing(db, name="测试货币基金", ftype="货币型-普通货币",
             money=True).ingest_one("012349")
    assert r.status == ST_INGESTED
    assert r.product_class == "money_market"
    assert r.nav_kind == "money_yield"
    # 货币收益不得写成 net_value
    with sqlite3.connect(db) as conn:
        kinds = {x[0] for x in conn.execute(
            "SELECT DISTINCT nav_kind FROM fund_nav_daily")}
    assert kinds == {"money_yield"}


# ================================================================ 6 A/C 归组
def test_ac_shares_grouped(tmp_path):
    """A/C 份额按基础名归入同一本体，表现不重复计数。"""
    db = _make_db(tmp_path)
    basic_a, nav, div = make_fakes(name="测试双份额基金A", ftype="债券型-长债")
    basic_c, _, _ = make_fakes(name="测试双份额基金C", ftype="债券型-长债")

    ing_a = UserFundIngestor(db, fetch_basic=basic_a, fetch_nav=nav,
                             fetch_dividend=div)
    a = ing_a.ingest_one("012350")
    assert a.status == ST_INGESTED

    ing_c = UserFundIngestor(db, fetch_basic=basic_c, fetch_nav=nav,
                             fetch_dividend=div)
    c = ing_c.ingest_one("012351")
    assert c.status == ST_INGESTED
    # 基础名相同 → 同一本体
    assert a.fund_id == c.fund_id
    assert c.warnings and "归入已存在本体" in c.warnings[0]

    with sqlite3.connect(db) as conn:
        n_fund = conn.execute("SELECT COUNT(*) FROM fund_master").fetchone()[0]
        n_share = conn.execute(
            "SELECT COUNT(*) FROM fund_share_classes WHERE fund_id=?",
            (a.fund_id,)).fetchone()[0]
    assert n_fund == 1, "A/C 不应生成两个本体"
    assert n_share == 2


def test_different_company_not_merged(tmp_path):
    """公司不同则不合并，避免错误归属。"""
    db = _make_db(tmp_path)
    basic_a, nav, div = make_fakes(name="同名基金A", ftype="股票型")
    basic_b, _, _ = make_fakes(name="同名基金C", ftype="股票型")

    def basic_a2(c):
        d = basic_a(c)
        d["company"] = "公司甲"
        return d

    def basic_b2(c):
        d = basic_b(c)
        d["company"] = "公司乙"
        return d

    a = UserFundIngestor(db, fetch_basic=basic_a2, fetch_nav=nav,
                         fetch_dividend=div).ingest_one("012352")
    b = UserFundIngestor(db, fetch_basic=basic_b2, fetch_nav=nav,
                         fetch_dividend=div).ingest_one("012353")
    assert a.fund_id != b.fund_id


def test_reingest_is_idempotent(tmp_path):
    db = _make_db(tmp_path)
    ing = _ing(db)
    r1 = ing.ingest_one("012352")
    fp1 = r1.fingerprint_after["sha256"]
    n1 = r1.nav_rows_total
    r2 = ing.ingest_one("012352")
    assert r2.status == ST_ALREADY_PRESENT
    assert r2.fingerprint_after["sha256"] == fp1
    assert r2.nav_rows_total == n1


# ================================================================ 7-9 拒绝
def test_not_found(tmp_path):
    db = _make_db(tmp_path)
    basic, nav, div = make_fakes()
    ing = UserFundIngestor(db, fetch_basic=lambda c: {"name": None},
                           fetch_nav=nav, fetch_dividend=div)
    r = ing.ingest_one("012353")
    assert r.status == ST_NOT_FOUND
    assert r.fund_id is None


def test_onshore_etf_rejected(tmp_path):
    db = _make_db(tmp_path)
    ing = _ing(db)
    for code in ("511000", "511050"):
        r = ing.ingest_one(code)
        assert r.status == ST_EXCLUDED
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM fund_master").fetchone()[0] == 0


def test_qdii_handled(tmp_path):
    db = _make_db(tmp_path)
    r = _ing(db, name="测试QDII基金", ftype="QDII-股票").ingest_one("012354")
    assert r.status == ST_EXCLUDED
    assert "QDII" in r.reason


def test_invalid_code(tmp_path):
    db = _make_db(tmp_path)
    for bad in ("abc", "12345", "1234567", ""):
        assert _ing(db).ingest_one(bad).status == ST_INVALID_CODE


# ================================================================ 10 失败与超时
def test_fetch_failure_no_partial(tmp_path):
    db = _make_db(tmp_path)
    before = db_fingerprint(db)

    def boom(code):
        raise RuntimeError("网络错误")

    ing = UserFundIngestor(db, fetch_basic=boom)
    r = ing.ingest_one("012355")
    assert r.status == ST_FAILED
    after = db_fingerprint(db)
    assert after["sha256"] == before["sha256"], "失败留下了半成品"
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM fund_master").fetchone()[0] == 0


def test_timeout_status(tmp_path):
    db = _make_db(tmp_path)

    class TimeoutError_(Exception):
        pass

    def to(code):
        raise TimeoutError_("timeout")

    ing = UserFundIngestor(db, fetch_basic=to)
    r = ing.ingest_one("012356")
    assert r.status in (ST_FAILED, "timeout")


def test_nav_failure_no_partial(tmp_path):
    db = _make_db(tmp_path)
    basic, _, div = make_fakes()

    def boom(code, kind):
        raise RuntimeError("净值接口失败")

    ing = UserFundIngestor(db, fetch_basic=basic, fetch_nav=boom,
                           fetch_dividend=div)
    r = ing.ingest_one("012357")
    assert r.status == ST_FAILED
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM fund_master").fetchone()[0] == 0


# ================================================================ 12 不覆盖有效数据
def test_reingest_does_not_overwrite(tmp_path):
    db = _make_db(tmp_path)
    ing = _ing(db)
    ing.ingest_one("012358")

    with sqlite3.connect(db) as conn:
        sid = conn.execute(
            "SELECT share_class_id FROM fund_share_classes WHERE share_class_code=?",
            ("012358",)).fetchone()[0]
        first = conn.execute(
            "SELECT unit_nav FROM fund_nav_daily WHERE share_class_id=? "
            "ORDER BY nav_date LIMIT 1", (sid,)).fetchone()[0]

    r2 = ing.ingest_one("012358")
    assert r2.status == ST_ALREADY_PRESENT
    with sqlite3.connect(db) as conn:
        again = conn.execute(
            "SELECT unit_nav FROM fund_nav_daily WHERE share_class_id=? "
            "ORDER BY nav_date LIMIT 1", (sid,)).fetchone()[0]
    assert again == first


# ================================================================ 13 空值不填 0
def test_null_nav_not_zero(tmp_path):
    db = _make_db(tmp_path)
    rows = _daily("2020-01-01", 30)
    unit = [{"nav_date": d, "unit_nav": v} for d, v in rows]
    unit[5] = {"nav_date": rows[5][0], "unit_nav": None}   # 空值
    acc = [{"nav_date": d, "acc_nav": v} for d, v in rows]
    basic = lambda c: {"name": "测试空值基金", "type": "股票型",
                       "established": "2020-01-01"}
    ing = UserFundIngestor(db, fetch_basic=basic,
                           fetch_nav=lambda c, k: unit if k == "unit" else acc,
                           fetch_dividend=lambda c: [])
    r = ing.ingest_one("012359")
    assert r.status == ST_INGESTED
    with sqlite3.connect(db) as conn:
        vals = [x[0] for x in conn.execute(
            "SELECT unit_nav FROM fund_nav_daily ORDER BY nav_date")]
    assert None not in vals
    assert 0.0 not in vals
    assert len(vals) == 29  # 空值那天整行未写入，不是填 0


# ================================================================ 14 缺口审计
def test_gap_quality_audit(tmp_path):
    db = _make_db(tmp_path)
    left = _daily("2020-01-01", 50)
    right = [((date.fromisoformat("2020-06-01") + timedelta(days=i)).isoformat(),
              round(2.0 + i * 0.001, 6)) for i in range(50)]
    allrows = left + right
    unit = [{"nav_date": d, "unit_nav": v} for d, v in allrows]
    acc = [{"nav_date": d, "acc_nav": v} for d, v in allrows]
    basic = lambda c: {"name": "测试缺口基金", "type": "股票型",
                       "established": "2020-01-01"}
    ing = UserFundIngestor(db, fetch_basic=basic,
                           fetch_nav=lambda c, k: unit if k == "unit" else acc,
                           fetch_dividend=lambda c: [])
    r = ing.ingest_one("012360")
    assert r.status == ST_INGESTED
    assert r.quality["gap_count_over_15d"] >= 1
    assert r.quality["continuity_verification"] == "cannot_verify"
    assert r.warnings, "缺口未产生警告"


def test_audit_marks_cannot_verify(tmp_path):
    db = _make_db(tmp_path)
    r = _ing(db).ingest_one("012361")
    q = r.quality
    assert q["continuity_verification"] == "cannot_verify"
    assert "A 股交易日历" in q["continuity_note"]


# ================================================================ 15 批量隔离
def test_batch_isolates_failures(tmp_path):
    db = _make_db(tmp_path)
    basic, nav, div = make_fakes()

    def basic2(code):
        if code == "012363":
            raise RuntimeError("模拟失败")
        if code == "012364":
            return {"name": None}
        return basic(code)

    ing = UserFundIngestor(db, fetch_basic=basic2, fetch_nav=nav,
                           fetch_dividend=div)
    doc = ingest_many(["012362", "012363", "012364", "012365"], db,
                      ingestor=ing)
    assert doc["result_count"] == 4
    statuses = [r["status"] for r in doc["results"]]
    assert statuses.count(ST_INGESTED) == 2
    assert statuses.count(ST_FAILED) == 1
    assert statuses.count(ST_NOT_FOUND) == 1
    assert doc["status_summary"]


def test_batch_duplicate_skipped(tmp_path):
    db = _make_db(tmp_path)
    ing = _ing(db)
    doc = ingest_many(["012366", "012366"], db, ingestor=ing)
    assert doc["results"][1]["status"] == "duplicate_skipped"
    assert doc["status_summary"].get(ST_INGESTED) == 1


# ================================================================ 16 来源与证据
def test_sources_and_evidence_recorded(tmp_path):
    db = _make_db(tmp_path)
    r = _ing(db).ingest_one("012367")
    assert r.status == ST_INGESTED
    assert any("akshare" in s for s in r.sources)
    assert "third_party" in r.evidence_levels
    with sqlite3.connect(db) as conn:
        src = conn.execute("SELECT source FROM fund_master").fetchone()[0]
        nsrc = {x[0] for x in conn.execute(
            "SELECT DISTINCT source FROM fund_nav_daily")}
        ing_at = conn.execute(
            "SELECT ingested_at FROM fund_master").fetchone()[0]
    assert "akshare" in src
    assert all("akshare" in x for x in nsrc)
    assert ing_at


# ================================================================ 17 接入后可查询
def test_queryable_after_ingest(tmp_path):
    db = _make_db(tmp_path)
    r = _ing(db).ingest_one("012368")
    assert r.status == ST_INGESTED

    from app.fund.research.engine import analyze_by_code
    rep = analyze_by_code("012368", db)
    assert rep["status"] == "found"
    assert rep["share_count"] == 1


# ================================================================ 18/19 回归
def test_real_default_pool_unchanged():
    """原 12 份额 / 9 本体的**原始样本**仍在，且新增基金不破坏既有结构。

    3B-5.3 允许向正式库接入新基金，因此默认池份额数会随之增长；
    这里校验的是**原有 12 个份额全部仍在、9 个本体全部仍在**。
    """
    from app.fund.research.engine import analyze_universe
    ORIGINAL_SHARES = {"000015", "000016", "000051", "000198", "000478",
                       "007300", "007301", "110020", "110022", "161005",
                       "012414", "161725"}
    ORIGINAL_FUNDS = 9
    r = analyze_universe()
    u = r["universe"]
    codes = {e["share_code"] for e in
             __import__("app.fund.research.data_access",
                        fromlist=["load_universe"]).load_universe()}
    assert ORIGINAL_SHARES <= codes, "原有 12 份额缺失"
    assert u["fund_count"] >= ORIGINAL_FUNDS
    # 原有 9 个本体仍在
    from app.fund.research.data_access import load_universe
    fund_ids = {e["fund_id"] for e in load_universe()
                if e["share_code"] in ORIGINAL_SHARES}
    assert len(fund_ids) == ORIGINAL_FUNDS


def test_real_lifecycle_untouched():
    from app.database.db import get_connection
    with get_connection() as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM fund_lifecycle_events").fetchone()[0]
    assert n == 49


# ================================================================ 20 指纹
def test_fingerprint_recorded(tmp_path):
    db = _make_db(tmp_path)
    r = _ing(db).ingest_one("012369")
    assert r.fingerprint_before is not None
    assert r.fingerprint_after is not None
    assert r.fingerprint_before["sha256"] != r.fingerprint_after["sha256"]
    assert r.fingerprint_after["row_counts"]["fund_nav_daily"] > 0


def test_dry_run_no_write(tmp_path):
    db = _make_db(tmp_path)
    before = db_fingerprint(db)
    after = db_fingerprint(db)
    assert before["sha256"] == after["sha256"]
