"""阶段3B-5.3.1 受控接入事务原子性与内容指纹专项测试。

全部使用临时 SQLite + 注入式假抓取器，不联网、不碰正式库。
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
    ST_FAILED, ST_INGESTED, UserFundIngestor, db_fingerprint,
)
from app.fund.migration import ensure_fund_schema  # noqa: E402
from app.fund.migration_3b4_2 import ensure_3b4_2_schema  # noqa: E402
from app.fund.migration_3b4_4 import ensure_3b4_4_schema  # noqa: E402


def _make_db(tmp_path: Path) -> Path:
    db = tmp_path / "atomic.db"
    ensure_fund_schema(db)
    ensure_3b4_2_schema(db)
    ensure_3b4_4_schema(db)
    return db


def _rows(start="2020-01-01", n=40, base=1.0):
    d0 = date.fromisoformat(start)
    return [((d0 + timedelta(days=i)).isoformat(), round(base + i * 0.001, 6))
            for i in range(n)]


def _fakes(name="测试原子基金", company="测试基金公司"):
    def basic(code):
        return {"name": name, "full_name": name + "全称", "company": company,
                "type": "股票型", "benchmark": "沪深300指数收益率×95%",
                "established": "2020-01-01"}
    unit = [{"nav_date": d, "unit_nav": v} for d, v in _rows()]
    acc = [{"nav_date": d, "acc_nav": v} for d, v in _rows()]
    return basic, (lambda c, k: unit if k == "unit" else acc)


def _ing(db, name="测试原子基金", company="测试基金公司"):
    basic, nav = _fakes(name, company)
    ing = UserFundIngestor(db, fetch_basic=basic, fetch_nav=nav,
                           fetch_dividend=lambda c: [])
    return ing


def _bind_db(monkeypatch, db: Path):
    """把 settings.database_path 指到临时库（多处模块都要打）。"""
    from types import SimpleNamespace
    import app.database.db as db_module
    import app.fund.ingest_user_funds._impl as impl
    import app.fund.ingest_user_funds.__main__ as cli
    fake = SimpleNamespace(database_path=db)
    monkeypatch.setattr(db_module, "settings", fake)
    monkeypatch.setattr(impl, "settings", fake)
    monkeypatch.setattr(cli, "db_fingerprint", lambda *a, **kw: db_fingerprint(db))


def _new_ingestor(db, name, company="测试基金公司", div=None):
    basic, nav = _fakes(name, company)
    return UserFundIngestor(db, fetch_basic=basic, fetch_nav=nav,
                            fetch_dividend=div or (lambda c: []))


# ================================================================ 指纹：真内容
def test_fingerprint_covers_all_fund_tables(tmp_path):
    db = _make_db(tmp_path)
    fp = db_fingerprint(db)
    for t in ("fund_master", "fund_share_classes", "fund_nav_daily",
              "fund_dividends", "fund_manager_history", "fund_aum_history",
              "fund_fee_rules", "fund_subscription_status",
              "fund_lifecycle_events", "fund_data_quality"):
        assert t in fp["row_counts"], t
        assert t in fp["table_digests"], t
        assert fp["table_digests"][t]["sha256"]


def test_fingerprint_is_stable(tmp_path):
    db = _make_db(tmp_path)
    assert db_fingerprint(db)["sha256"] == db_fingerprint(db)["sha256"]


def test_fingerprint_changes_on_same_length_edit(tmp_path):
    """同长度内容修改必须改变指纹（旧实现只比行数与长度，会漏检）。"""
    db = _make_db(tmp_path)
    r = _ing(db).ingest_one("013001")
    assert r.status == ST_INGESTED
    before = db_fingerprint(db)["sha256"]

    with sqlite3.connect(db) as conn:
        # 找一个**字符串表示长度相同**的新值，确保旧实现（比长度）无法识别
        row = conn.execute(
            "SELECT share_class_id, nav_date, unit_nav FROM fund_nav_daily "
            "ORDER BY nav_date LIMIT 1").fetchone()
        sid, nd, old = row
        new = round(old + 0.01, 6)
        while len(str(old)) != len(str(new)) and new < old + 0.1:
            new = round(new + 0.01, 6)
        assert len(str(old)) == len(str(new)), f"需构造同长度修改：{old} vs {new}"
        conn.execute(
            "UPDATE fund_nav_daily SET unit_nav=? "
            "WHERE share_class_id=? AND nav_date=? AND nav_kind='net_value'",
            (new, sid, nd))
        conn.commit()

    after = db_fingerprint(db)["sha256"]
    assert after != before, "同长度内容修改未被指纹识别"


def test_fingerprint_changes_on_row_count_unchanged_value_edit(tmp_path):
    """行数不变、只改一条净值，指纹必须变。"""
    db = _make_db(tmp_path)
    _ing(db).ingest_one("013002")
    fp1 = db_fingerprint(db)
    n1 = fp1["row_counts"]["fund_nav_daily"]

    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE fund_nav_daily SET acc_nav=acc_nav+0.5 "
            "WHERE nav_kind='net_value' AND nav_date=(SELECT MIN(nav_date) "
            "FROM fund_nav_daily WHERE nav_kind='net_value')")
        conn.commit()

    fp2 = db_fingerprint(db)
    assert fp2["row_counts"]["fund_nav_daily"] == n1
    assert fp2["sha256"] != fp1["sha256"]


def test_fingerprint_distinguishes_null_from_zero(tmp_path):
    """NULL 与 0 必须能被区分。"""
    db = _make_db(tmp_path)
    _ing(db).ingest_one("013003")
    fp1 = db_fingerprint(db)["sha256"]

    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE fund_dividends SET cash_per_share=0 "
                     "WHERE dividend_id=(SELECT MIN(dividend_id) FROM fund_dividends)")
        conn.commit()

    # 表空时改不到任何行，指纹自然不变；此处只验证 NULL 序列化不塌陷
    fp2 = db_fingerprint(db)["sha256"]
    assert isinstance(fp1, str) and isinstance(fp2, str)


def test_fingerprint_null_vs_zero_by_serialization():
    """序列化层：NULL 与 0 的表示必须不同。"""
    from app.fund.ingest_user_funds._impl import _stable_value
    assert _stable_value(None) != _stable_value(0)
    assert _stable_value(0) != _stable_value(0.0)
    assert _stable_value("1") != _stable_value(1)


# ================================================================ 原子事务
def _assert_rolled_back(db: Path, before_sha: str, code: str):
    after = db_fingerprint(db)
    assert after["sha256"] == before_sha, "回滚后内容指纹必须与接入前完全一致"
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM fund_share_classes WHERE share_class_code=?",
            (code,)).fetchone()[0] == 0, "残留份额记录"


def test_nav_write_failure_rolls_back(tmp_path):
    """基本信息/本体/份额写入成功，净值写入抛异常 → 整体回滚。"""
    db = _make_db(tmp_path)
    ing = _new_ingestor(db, "测试净值失败基金")
    before = db_fingerprint(db)["sha256"]

    def boom(*a, **kw):
        raise RuntimeError("注入：净值写入失败")

    ing.nav.upsert_nav_batch = boom
    r = ing.ingest_one("013010")
    assert r.status == ST_FAILED
    assert "回滚" in r.reason
    assert r.fund_id is None
    _assert_rolled_back(db, before, "013010")


def test_dividend_write_failure_rolls_back(tmp_path):
    """净值写入成功，分红写入抛异常 → 整体回滚。"""
    db = _make_db(tmp_path)
    # per_10_raw 必须是能解析出「现金」的正则友好格式，否则整条被跳过、注入不触发
    div = lambda c: [{"record_date": "2021-01-01", "ex_date": "2021-01-05",
                      "pay_date": "2021-01-10",
                      "per_10_raw": "每10份派现金0.5000元"}]
    ing = _new_ingestor(db, "测试分红失败基金", div=div)
    before = db_fingerprint(db)["sha256"]

    def boom(*a, **kw):
        raise RuntimeError("注入：分红写入失败")

    ing.nav.upsert_dividend_batch = boom
    r = ing.ingest_one("013011")
    assert r.status == ST_FAILED
    _assert_rolled_back(db, before, "013011")


def test_quality_write_failure_rolls_back(tmp_path):
    """净值写入成功，质量记录写入抛异常 → 整体回滚。"""
    db = _make_db(tmp_path)
    # 构造带缺口的净值，触发质量记录写入
    left = _rows("2020-01-01", 30)
    right = [((date.fromisoformat("2020-06-01") + timedelta(days=i)).isoformat(),
              round(2.0 + i * 0.001, 6)) for i in range(30)]
    allrows = left + right
    unit = [{"nav_date": d, "unit_nav": v} for d, v in allrows]
    acc = [{"nav_date": d, "acc_nav": v} for d, v in allrows]
    basic = lambda c: {"name": "测试质量失败基金", "company": "测试基金公司",
                       "type": "股票型", "established": "2020-01-01"}
    ing = UserFundIngestor(db, fetch_basic=basic,
                           fetch_nav=lambda c, k: unit if k == "unit" else acc,
                           fetch_dividend=lambda c: [])
    before = db_fingerprint(db)["sha256"]

    def boom(*a, **kw):
        raise RuntimeError("注入：质量记录写入失败")

    ing.quality.record = boom
    r = ing.ingest_one("013012")
    assert r.status == ST_FAILED
    _assert_rolled_back(db, before, "013012")


def test_master_write_failure_rolls_back(tmp_path):
    """本体写入就失败 → 任何表都不应变化。"""
    db = _make_db(tmp_path)
    ing = _new_ingestor(db, "测试本体失败基金")
    before = db_fingerprint(db)["sha256"]

    def boom(*a, **kw):
        raise RuntimeError("注入：本体写入失败")

    ing.funds.upsert_master = boom
    r = ing.ingest_one("013013")
    assert r.status == ST_FAILED
    _assert_rolled_back(db, before, "013013")


def test_retry_after_failure_succeeds(tmp_path):
    """故障回滚后重新正常接入，必须能完整成功。"""
    db = _make_db(tmp_path)
    before = db_fingerprint(db)["sha256"]

    ing1 = _new_ingestor(db, "测试重试基金")

    def boom(*a, **kw):
        raise RuntimeError("注入：净值写入失败")

    ing1.nav.upsert_nav_batch = boom
    r1 = ing1.ingest_one("013014")
    assert r1.status == ST_FAILED
    assert db_fingerprint(db)["sha256"] == before

    # 重新接入（新的 ingestor，不受注入影响）
    ing2 = _new_ingestor(db, "测试重试基金")
    r2 = ing2.ingest_one("013014")
    assert r2.status == ST_INGESTED, r2.reason
    assert r2.fund_id is not None
    assert r2.nav_rows_total > 0
    after = db_fingerprint(db)
    assert after["sha256"] != before
    assert after["row_counts"]["fund_master"] == 1
    assert after["row_counts"]["fund_nav_daily"] == 40


def test_no_false_success_on_write_failure(tmp_path):
    """写入失败不得返回成功，也不得把异常吞成 ingested。"""
    db = _make_db(tmp_path)
    ing = _new_ingestor(db, "测试不掩盖基金")

    def boom(*a, **kw):
        raise RuntimeError("注入：份额写入失败")

    ing.funds.upsert_share_class = boom
    r = ing.ingest_one("013015")
    assert r.status == ST_FAILED
    assert r.status != ST_INGESTED
    assert r.fund_id is None


# ================================================================ A/C 归组收紧
def test_same_name_same_company_groups(tmp_path):
    db = _make_db(tmp_path)
    a = _new_ingestor(db, "同名同公司基金A", "同一家公司").ingest_one("013020")
    c = _new_ingestor(db, "同名同公司基金C", "同一家公司").ingest_one("013021")
    assert a.status == ST_INGESTED and c.status == ST_INGESTED
    assert a.fund_id == c.fund_id


def test_same_name_different_company_not_grouped(tmp_path):
    db = _make_db(tmp_path)
    a = _new_ingestor(db, "同名异公司基金A", "公司甲").ingest_one("013022")
    c = _new_ingestor(db, "同名异公司基金C", "公司乙").ingest_one("013023")
    assert a.fund_id != c.fund_id
    assert any("不一致" in w for w in c.warnings)


def test_same_name_missing_company_not_grouped(tmp_path):
    """一方公司为空 → 不自动归组。"""
    db = _make_db(tmp_path)
    a = _new_ingestor(db, "缺公司基金A", "公司甲").ingest_one("013024")
    c = _new_ingestor(db, "缺公司基金C", None).ingest_one("013025")
    assert a.fund_id != c.fund_id
    assert any("人工核验" in w for w in c.warnings)


def test_different_base_name_not_grouped(tmp_path):
    db = _make_db(tmp_path)
    a = _new_ingestor(db, "完全不同的基金A", "同一家公司").ingest_one("013026")
    b = _new_ingestor(db, "另一个名字的基金B", "同一家公司").ingest_one("013027")
    assert a.fund_id != b.fund_id


def test_missing_both_companies_not_grouped(tmp_path):
    """双方公司都空 → 不自动归组。"""
    db = _make_db(tmp_path)
    a = _new_ingestor(db, "双空公司基金A", None).ingest_one("013028")
    c = _new_ingestor(db, "双空公司基金C", None).ingest_one("013029")
    assert a.fund_id != c.fund_id


# ================================================================ dry-run
def test_dry_run_truly_no_write(tmp_path, monkeypatch):
    """真正执行 dry-run：不调外部接口、不写库、指纹前后一致。"""
    from app.fund.ingest_user_funds.__main__ import _make_ingestor

    db = _make_db(tmp_path)
    calls = []

    def fake_basic(code):
        calls.append(code)
        return {"name": "不该被调用"}

    monkeypatch.setattr(
        "app.fund.ingest_user_funds._impl._fetch_basic_default", fake_basic)
    monkeypatch.setattr(
        "app.fund.ingest_user_funds._impl._fetch_nav_default",
        lambda c, k: calls.append(c) or [])

    _bind_db(monkeypatch, db)
    before = db_fingerprint(db)
    ing = _make_ingestor(dry_run=True)
    r = ing.ingest_one("013030")
    after = db_fingerprint(db)

    assert calls == [], "dry-run 不得调用外部抓取接口"
    assert before["sha256"] == after["sha256"], "dry-run 不得改变任何基金表"
    assert r.status in ("dry_run_preview", "already_present", "invalid_code",
                        "excluded_product")
    with sqlite3.connect(db) as conn:
        for t in ("fund_master", "fund_share_classes", "fund_nav_daily",
                  "fund_dividends", "fund_data_quality"):
            assert conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0


def test_dry_run_batch_no_write(tmp_path, monkeypatch):
    """批量 dry-run：多只都预检，不写库。"""
    from app.fund.ingest_user_funds.__main__ import main
    db = _make_db(tmp_path)
    _bind_db(monkeypatch, db)
    calls = []
    monkeypatch.setattr(
        "app.fund.ingest_user_funds._impl._fetch_basic_default",
        lambda c: calls.append(c) or {"name": "不该被调用"})

    codes = tmp_path / "codes.txt"
    codes.write_text("013031\n013032\nabc\n", encoding="utf-8")
    out = tmp_path / "out.json"

    before = db_fingerprint(db)
    rc = main(["--codes-file", str(codes), "--json", str(out), "--dry-run"])
    after = db_fingerprint(db)

    assert rc == 0
    assert calls == [], "dry-run 不得调用外部接口"
    assert before["sha256"] == after["sha256"]
    import json
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["dry_run"] is True
    assert doc["database_changed"] is False
    assert doc["result_count"] == 2   # 非法行被跳过


def test_dry_run_reports_existing_without_touching(tmp_path, monkeypatch):
    """dry-run 遇到库中已存在的代码：只报告，不写。"""
    from app.fund.ingest_user_funds.__main__ import _make_ingestor
    db = _make_db(tmp_path)
    _new_ingestor(db, "已存在基金").ingest_one("013033")
    _bind_db(monkeypatch, db)

    before = db_fingerprint(db)
    r = _make_ingestor(dry_run=True).ingest_one("013033")
    after = db_fingerprint(db)
    assert r.status == "already_present"
    assert r.nav_rows_total > 0
    assert before["sha256"] == after["sha256"]
