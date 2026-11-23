"""阶段3B-5.3.2 事务连接外键约束与指纹序列化专项测试。

全部使用临时 SQLite，正式库只做只读完整性检查。
"""
from __future__ import annotations

import json
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
from app.fund.ingest_user_funds._impl import (  # noqa: E402
    _encode_row, _stable_value,
)
from app.fund.migration import ensure_fund_schema  # noqa: E402
from app.fund.migration_3b4_2 import ensure_3b4_2_schema  # noqa: E402
from app.fund.migration_3b4_4 import ensure_3b4_4_schema  # noqa: E402


def _make_db(tmp_path: Path) -> Path:
    db = tmp_path / "fk.db"
    ensure_fund_schema(db)
    ensure_3b4_2_schema(db)
    ensure_3b4_4_schema(db)
    return db


def _rows(start="2020-01-01", n=40, base=1.0):
    d0 = date.fromisoformat(start)
    return [((d0 + timedelta(days=i)).isoformat(), round(base + i * 0.001, 6))
            for i in range(n)]


def _ing(db, name="测试外键基金", company="测试基金公司"):
    def basic(code):
        return {"name": name, "full_name": name + "全称", "company": company,
                "type": "股票型", "benchmark": "沪深300", "established": "2020-01-01"}
    unit = [{"nav_date": d, "unit_nav": v} for d, v in _rows()]
    acc = [{"nav_date": d, "acc_nav": v} for d, v in _rows()]
    return UserFundIngestor(db, fetch_basic=basic,
                            fetch_nav=lambda c, k: unit if k == "unit" else acc,
                            fetch_dividend=lambda c: [])


# ================================================================ P0 外键
def test_tx_connection_enables_foreign_keys(tmp_path):
    """接入专用事务连接必须真正启用外键约束。"""
    db = _make_db(tmp_path)
    ing = _ing(db)
    conn = ing._open_tx()
    try:
        assert int(conn.execute("PRAGMA foreign_keys").fetchone()[0]) == 1
    finally:
        ing._tx = conn
        ing._rollback_tx()


def test_tx_connection_fk_on_before_begin(tmp_path):
    """外键必须在 BEGIN IMMEDIATE 之前开启（事务内 PRAGMA 无效）。"""
    db = _make_db(tmp_path)
    ing = _ing(db)
    conn = ing._open_tx()
    try:
        # 已处于事务中；外键仍为 1 说明是 BEGIN 之前设的
        assert conn.in_transaction is True
        assert int(conn.execute("PRAGMA foreign_keys").fetchone()[0]) == 1
    finally:
        ing._tx = conn
        ing._rollback_tx()


def test_global_connection_unaffected(tmp_path, monkeypatch):
    """项目全局连接行为不得被本改动影响。"""
    import app.database.db as db_module
    from types import SimpleNamespace
    db = _make_db(tmp_path)
    monkeypatch.setattr(db_module, "settings",
                        SimpleNamespace(database_path=db))
    with db_module.get_connection() as conn:
        # 全局连接保持 SQLite 默认（关闭），未被本轮改动
        assert int(conn.execute("PRAGMA foreign_keys").fetchone()[0]) == 0


def test_insert_orphan_share_raises_integrity_error(tmp_path):
    """通过事务连接插入不存在的 fund_id 对应份额，必须抛 IntegrityError。"""
    db = _make_db(tmp_path)
    ing = _ing(db)
    conn = ing._open_tx()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO fund_share_classes
                   (fund_id, share_class_code, share_class_name,
                    share_class_type, currency, is_primary, source, ingested_at)
                   VALUES (999999, '099999', '孤儿份额', 'A', 'CNY', 0,
                           'test', '2020-01-01T00:00:00')""")
    finally:
        ing._tx = conn
        ing._rollback_tx()


def test_orphan_insert_rolls_back_whole_transaction(tmp_path):
    """外键异常触发后整个接入事务回滚，不留半成品。"""
    db = _make_db(tmp_path)
    before = db_fingerprint(db)["sha256"]

    ing = _ing(db)

    # 在净值写入阶段注入「孤儿份额」写入，触发外键失败
    orig = ing.nav.upsert_nav_batch

    def boom(sc_id, records, *, conn=None, **kw):
        if conn is not None:
            conn.execute(
                """INSERT INTO fund_nav_daily
                   (share_class_id, nav_date, nav_kind, unit_nav, source, ingested_at)
                   VALUES (999999, '2020-01-01', 'net_value', 1.0, 'test',
                           '2020-01-01T00:00:00')""")
        return orig(sc_id, records, conn=conn, **kw)

    ing.nav.upsert_nav_batch = boom
    r = ing.ingest_one("014001")

    assert r.status == ST_FAILED
    assert "回滚" in r.reason
    after = db_fingerprint(db)
    assert after["sha256"] == before, "外键失败后必须整体回滚"
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM fund_master").fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM fund_share_classes").fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM fund_nav_daily").fetchone()[0] == 0


def test_normal_ingest_still_works_with_fk_on(tmp_path):
    """开启外键后正常接入仍然成功。"""
    db = _make_db(tmp_path)
    r = _ing(db).ingest_one("014002")
    assert r.status == ST_INGESTED, r.reason
    assert r.nav_rows_total == 40
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


# ================================================================ P1 序列化
def test_separator_not_ambiguous():
    """("a|b","c") 与 ("a","b|c") 必须产生不同序列化。"""
    a = _encode_row(["a|b", "c"])
    b = _encode_row(["a", "b|c"])
    assert a != b


def test_separator_variants_all_distinct():
    cases = [
        ["a|b", "c"],
        ["a", "b|c"],
        ["a|", "b|c"],
        ["a", "|", "b|c"],
        ["|", "a", "b|c"],
    ]
    seen = {_encode_row(c) for c in cases}
    assert len(seen) == len(cases)


def test_bracket_and_quote_not_ambiguous():
    """JSON 结构字符也要被正确转义，不能靠拼接。"""
    a = _encode_row(['["a"]', "b"])
    b = _encode_row(['["a", "b"]'])
    assert a != b
    a2 = _encode_row(['a\\"b'])
    b2 = _encode_row(['a"b'])
    assert a2 != b2


def test_json_encoding_is_valid_json():
    """编码结果本身必须是合法 JSON（可用 json.loads 还原结构）。"""
    raw = _encode_row(["a|b", None, 1, 1.5, b"xy"])
    parsed = json.loads(raw.decode("utf-8"))
    assert len(parsed) == 5
    assert parsed[0] == ["str", "a|b"]
    assert parsed[1] == ["null", None]
    assert parsed[2] == ["int", 1]
    assert parsed[3] == ["float", "1.5"]
    assert parsed[4] == ["bytes", b"xy".hex()]


def test_type_tags_preserved():
    """NULL / int / float / str / bytes 的类型必须可区分。"""
    assert _encode_row([None]) != _encode_row([0])
    assert _encode_row([1]) != _encode_row([1.0])
    assert _encode_row([1]) != _encode_row(["1"])
    assert _encode_row([b"1"]) != _encode_row(["1"])
    assert _stable_value(None)[0] == "null"
    assert _stable_value(True)[0] == "bool"
    assert _stable_value(3)[0] == "int"
    assert _stable_value(3.0)[0] == "float"
    assert _stable_value(b"3")[0] == "bytes"
    assert _stable_value("3")[0] == "str"


def test_serialization_deterministic():
    """同样数据重复计算结果一致。"""
    vals = ["x|y", None, 2, 2.5, b"\x01\x02"]
    assert _encode_row(vals) == _encode_row(list(vals))


def test_nan_inf_serializable():
    """nan / inf 不能破坏 JSON 编码。"""
    assert b"nan" in _encode_row([float("nan")])
    assert b"inf" in _encode_row([float("inf")])
    assert b"-inf" in _encode_row([float("-inf")])


def test_fingerprint_unchanged_by_recompute(tmp_path):
    db = _make_db(tmp_path)
    _ing(db).ingest_one("014003")
    assert db_fingerprint(db)["sha256"] == db_fingerprint(db)["sha256"]


# ================================================================ 保留原有能力
def test_fingerprint_changes_on_same_length_edit(tmp_path):
    """保留：同长度修改必须改变指纹。"""
    db = _make_db(tmp_path)
    _ing(db).ingest_one("014004")
    before = db_fingerprint(db)["sha256"]
    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT share_class_id, nav_date, unit_nav FROM fund_nav_daily "
            "ORDER BY nav_date LIMIT 1").fetchone()
        sid, nd, old = row
        new = round(old + 0.01, 6)
        while len(str(old)) != len(str(new)) and new < old + 0.1:
            new = round(new + 0.01, 6)
        assert len(str(old)) == len(str(new))
        conn.execute(
            "UPDATE fund_nav_daily SET unit_nav=? "
            "WHERE share_class_id=? AND nav_date=? AND nav_kind='net_value'",
            (new, sid, nd))
        conn.commit()
    assert db_fingerprint(db)["sha256"] != before


def test_fingerprint_changes_row_count_unchanged(tmp_path):
    """保留：行数不变、只改一条净值，指纹必须变。"""
    db = _make_db(tmp_path)
    _ing(db).ingest_one("014005")
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


# ================================================================ 正式库只读
def test_production_db_readonly_integrity():
    """正式库只做只读完整性检查。"""
    from app.database.db import get_connection
    with get_connection() as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
