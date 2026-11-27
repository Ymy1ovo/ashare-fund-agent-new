"""阶段3B-6.2.3.1.1 全收益指数独立原始数据层专项测试。

**真实操作数据库与业务函数**，不使用文本断言。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.fund import tr_layer  # noqa: E402

REPORTS = ROOT / "reports"
EVID_TR = REPORTS / "evidence" / "phase3B6_2_3_1_0"
AUDIT_3 = REPORTS / "phase3B6_2_3_1_0_3_audit.json"

BASELINE_DB_SHA256 = (
    "1671e4037cd265a2dead8b78d43614189a782385ca450ac6c2de3c4ff36ee873")
EXPECTED_INDEX_DAILY_ROWS = 50603

EXPECTED_CODES = {
    "H00300", "H00905", "H00906", "H00016", "H20539", "399997CNY02",
    "H20184", "H00942", "H00922", "H00012", "N00012", "H20930",
}


@pytest.fixture(scope="module")
def conn():
    with tr_layer.get_tr_connection() as c:
        tr_layer.enable_foreign_keys(c)
        yield c


@pytest.fixture(scope="module")
def audit() -> dict:
    return json.loads(AUDIT_3.read_text(encoding="utf-8"))


def _rows(conn, sql, *args) -> list[dict]:
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def _one(conn, sql, *args):
    conn.row_factory = sqlite3.Row
    r = conn.execute(sql, args).fetchone()
    return dict(r) if r else None


# ============================================================ 1. 隔离
def test_tr_tables_all_prefixed(conn):
    """1. 全收益表全部使用 tr_ 前缀白名单。"""
    names = [r["name"] for r in _rows(
        conn, "select name from sqlite_master where type='table'")]
    for t in tr_layer.TR_TABLES:
        assert t in names, f"缺表 {t}"
    assert "trade_calendar" not in tr_layer.TR_TABLES


def test_no_tr_data_in_index_daily(conn):
    """1b. 全收益代码不得出现在 index_daily。"""
    for code in EXPECTED_CODES:
        n = conn.execute(
            "select count(*) from index_daily where index_code=?",
            (code,)).fetchone()[0]
        assert n == 0, f"{code} 泄漏进 index_daily（{n} 行）"


def test_isolated_helper_true(conn):
    iso = tr_layer.assert_isolated(conn)
    assert iso["isolated"] is True
    assert iso["leaked_into_index_daily"] == []


def test_index_daily_row_count_unchanged(conn):
    """index_daily 行数未变。"""
    assert conn.execute(
        "select count(*) from index_daily").fetchone()[0] == \
        EXPECTED_INDEX_DAILY_ROWS


def test_ingest_run_proves_index_daily_untouched(conn):
    """导入批次必须记录 index_daily 前后指纹且一致。"""
    run = _one(conn, "select * from tr_ingest_runs order by run_id desc")
    assert run is not None
    assert run["index_daily_before"] == run["index_daily_after"] == \
        EXPECTED_INDEX_DAILY_ROWS
    assert run["index_daily_fingerprint_before"] == \
        run["index_daily_fingerprint_after"]
    assert run["status"] == "success"


# ============================================================ 2. 候选注册
def test_twelve_candidates_registered(conn):
    """2. 12 个候选注册信息完整。"""
    cands = tr_layer.list_candidates(conn)
    assert len(cands) == 12
    assert {c["tr_code"] for c in cands} == EXPECTED_CODES


def test_candidate_fields_complete(conn):
    for c in tr_layer.list_candidates(conn):
        assert c["tr_code"]
        assert c["price_index_code"], f"{c['tr_code']} 缺价格指数代码"
        assert c["official_full_name"], f"{c['tr_code']} 缺官方全称"
        assert c["official_basic_date"], f"{c['tr_code']} 缺基日"
        assert c["official_publish_date"], f"{c['tr_code']} 缺发布日"
        assert c["market_group"] in ("stock", "bond", "hk")
        assert c["return_basis"] in (
            "gross_total_return", "net_total_return", "bond_clean_price",
            "bond_interest_reinvestment", "unknown")
        assert c["continuity_level"] in tr_layer.CONTINUITY_STATES
        assert c["source_audit_json"]


def test_base_date_not_publish_date(conn):
    """基日与发布日不得混用。"""
    for c in tr_layer.list_candidates(conn):
        assert c["official_basic_date"] != c["official_publish_date"], \
            f"{c['tr_code']} 基日与发布日相同"


def test_market_groups_separated(conn):
    """股票/债券/港股独立分类。"""
    groups = {}
    for c in tr_layer.list_candidates(conn):
        groups.setdefault(c["market_group"], []).append(c["tr_code"])
    assert set(groups) == {"stock", "bond", "hk"}
    assert len(groups["stock"]) == 9
    assert set(groups["bond"]) == {"H00012", "N00012"}
    assert groups["hk"] == ["H20930"]


def test_bond_basis_not_stock_total_return(conn):
    """债券口径不得混为股票全收益。"""
    for code in ("H00012", "N00012"):
        c = tr_layer.get_candidate(conn, code)
        assert c["return_basis"] in ("bond_clean_price",
                                     "bond_interest_reinvestment"), \
            f"{code} 口径错误：{c['return_basis']}"


# ============================================================ 3-4. 证据追溯
def test_raw_rows_traceable_to_evidence(conn):
    """3. 原始行情可追溯到原始文件。"""
    bad = _rows(conn,
                "select distinct tr_code from tr_index_daily_raw "
                "where evidence_relative_path is null "
                "or evidence_sha256 is null")
    assert not bad, f"缺证据引用：{[b['tr_code'] for b in bad]}"


def test_evidence_sha256_real(conn):
    """4. 证据 SHA256 必须与真实文件一致（真实计算）。"""
    evs = _rows(conn, "select * from tr_evidence_files")
    assert len(evs) >= 30
    checked = 0
    for e in evs:
        f = ROOT / e["relative_path"]
        assert f.exists(), f"证据文件缺失：{e['relative_path']}"
        actual = hashlib.sha256(f.read_bytes()).hexdigest()
        assert actual == e["sha256"], f"{e['relative_path']} SHA256 不符"
        assert e["bytes"] == f.stat().st_size
        checked += 1
    assert checked == len(evs)


def test_raw_row_sha_matches_evidence(conn):
    """行情行引用的 SHA256 必须与证据表一致。"""
    pairs = _rows(conn,
                  "select distinct tr_code, evidence_relative_path, "
                  "evidence_sha256 from tr_index_daily_raw")
    by_path = {e["relative_path"]: e["sha256"]
               for e in _rows(conn, "select * from tr_evidence_files")}
    for p in pairs:
        assert p["evidence_relative_path"] in by_path
        assert p["evidence_sha256"] == by_path[p["evidence_relative_path"]]


# ============================================================ 5. 幂等
def test_reimport_no_duplicates(conn):
    """5. 重复导入不产生重复记录。"""
    before = conn.execute(
        "select count(*) from tr_index_daily_raw").fetchone()[0]
    # 主键 (tr_code, trade_date) 保证唯一
    dup = _rows(conn,
                "select tr_code, trade_date, count(*) c "
                "from tr_index_daily_raw group by 1,2 having c>1")
    assert not dup, f"存在重复：{dup[:3]}"
    assert before == 55942


def test_reimport_idempotent_on_copy(tmp_path):
    """重复导入幂等：在正式库副本上重跑导入脚本，行数不变。

    **不写正式数据库**（conftest 有全局守卫）。
    """
    import shutil
    import subprocess
    src = ROOT / "data" / "fund_agent.db"
    dst = tmp_path / "copy.db"
    shutil.copy2(src, dst)
    before = sqlite3.connect(dst).execute(
        "select count(*) from tr_index_daily_raw").fetchone()[0]
    env = {"PYTHONUTF8": "1", "PATH": str(Path(sys.executable).parent),
           "TR_LAYER_DB_OVERRIDE": str(dst)}
    r = subprocess.run(
        [sys.executable,
         str(ROOT / "scripts" / "build_3b6_2_3_1_1_tr_layer.py")],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
        env={**__import__("os").environ, **env})
    assert r.returncode == 0, r.stderr[-800:]
    after = sqlite3.connect(dst).execute(
        "select count(*) from tr_index_daily_raw").fetchone()[0]
    assert after == before, f"重复导入改变了行数：{before} -> {after}"


# ============================================================ 6. 回滚
def test_rollback_and_reinit(tmp_path):
    """6. 导入失败可回滚；迁移可重复执行且支持回滚。"""
    db = tmp_path / "tr_test.db"
    # 建一个最小 index_daily 以验证回滚不碰它
    c = sqlite3.connect(db)
    c.execute("create table index_daily (index_code text, trade_date text, "
              "close real, quality_status text)")
    c.execute("insert into index_daily values ('000300','2020-01-02',1.0,'valid')")
    c.commit()
    tr_layer.init_tr_layer(c)
    assert c.execute(
        "select count(*) from sqlite_master where name='tr_candidate_master'"
    ).fetchone()[0] == 1
    # 重复执行迁移（幂等）
    tr_layer.init_tr_layer(c)
    assert c.execute(
        "select count(*) from sqlite_master where name='tr_candidate_master'"
    ).fetchone()[0] == 1
    # 回滚
    tr_layer.rollback_tr_layer(c)
    assert c.execute(
        "select count(*) from sqlite_master where name='tr_candidate_master'"
    ).fetchone()[0] == 0
    # index_daily 未受影响
    assert c.execute("select count(*) from index_daily").fetchone()[0] == 1
    c.close()


def test_failed_import_rolls_back(tmp_path):
    """导入失败时事务回滚，不留半截数据。"""
    db = tmp_path / "tr_tx.db"
    c = sqlite3.connect(db)
    tr_layer.init_tr_layer(c)
    c.commit()
    try:
        with c:
            tr_layer.upsert_candidate(c, {
                "tr_code": "BROKEN", "price_index_code": "X",
                "market_group": "stock", "return_basis": "unknown",
                "calendar_type": "none", "calendar_available": 0,
                "calendar_is_official": 0, "mapping_evidence_level": "none",
                "continuity_level": "unknown",
                "real_history_start": "unknown",
                "synthetic_start_status": "unknown"})
            raise RuntimeError("模拟导入失败")
    except RuntimeError:
        pass
    assert c.execute(
        "select count(*) from tr_candidate_master").fetchone()[0] == 0
    c.close()


# ============================================================ 7-9. 异常行
def test_synthetic_row_preserved_and_marked(conn):
    """7. 20040101 疑似合成行被保留且正确标记。"""
    rows = _rows(conn,
                 "select tr_code, close, row_quality_status "
                 "from tr_index_daily_raw where trade_date='20040101'")
    assert len(rows) == 12
    for r in rows:
        assert r["row_quality_status"] == "suspected_synthetic", \
            f"{r['tr_code']} 标记错误：{r['row_quality_status']}"
        assert r["close"] is not None, "原始值被删除"


def test_synthetic_row_original_value_kept(conn):
    """合成行原始数值必须原样保留。"""
    r = _one(conn, "select close from tr_index_daily_raw "
                   "where tr_code='H00300' and trade_date='20040101'")
    assert r["close"] == 1000.0


def test_closed_placeholder_preserved_and_marked(conn):
    """8. 2018-06-18 疑似休市占位行被保留且正确标记。"""
    rows = _rows(conn,
                 "select tr_code, close, row_quality_status "
                 "from tr_index_daily_raw where trade_date='20180618'")
    assert len(rows) >= 8
    closed = [r for r in rows
              if r["row_quality_status"] ==
              "suspected_market_closed_placeholder"]
    assert len(closed) == 8, f"标记数 {len(closed)} != 8"
    for r in closed:
        assert r["close"] is not None


def test_h20184_zero_preserved_and_marked(conn):
    """9. H20184 零值异常被保留且正确标记。"""
    r = _one(conn, "select close, row_quality_status, row_quality_note "
                   "from tr_index_daily_raw "
                   "where tr_code='H20184' and trade_date='20130628'")
    assert r is not None
    assert r["close"] == 0.0, "零值被修正"
    assert r["row_quality_status"] == "invalid_value"
    assert "非正" in r["row_quality_note"]


def test_no_row_defaults_to_verified(conn):
    """未验证行不得默认标记为有效行情。"""
    bad = _rows(conn,
                "select distinct row_quality_status "
                "from tr_index_daily_raw")
    states = {b["row_quality_status"] for b in bad}
    assert states <= set(tr_layer.ROW_QUALITY_STATES)
    assert "verified" not in states
    assert "valid" not in states


def test_no_cleaning_applied(conn):
    """不得删除、插值或修正任何原始行。"""
    for code in EXPECTED_CODES:
        f = EVID_TR / f"hist_{code}_20040101_20261127.json"
        raw = json.loads(f.read_bytes().decode("utf-8")).get("data") or []
        n_db = conn.execute(
            "select count(*) from tr_index_daily_raw where tr_code=?",
            (code,)).fetchone()[0]
        assert n_db == len(raw), \
            f"{code} 行数不符：DB {n_db} vs 原始 {len(raw)}"


# ============================================================ 10-12. 状态
def test_real_history_start_stays_unknown(conn):
    """10. 真实历史起点 unknown 不会被自动转为已知。"""
    for c in tr_layer.list_candidates(conn):
        assert c["real_history_start"] == "unknown", \
            f"{c['tr_code']} 起点被改成 {c['real_history_start']}"
        assert c["synthetic_start_status"] in (
            "confirmed", "strong_inference", "unknown")
        assert c["synthetic_start_status"] != "confirmed", \
            f"{c['tr_code']} 无自身对照却标 confirmed"


def test_bond_hk_calendar_not_replaced(conn):
    """11. 债券/港股日历状态不得替换为 A 股日历。"""
    for code in ("H00012", "N00012", "H20930"):
        c = tr_layer.get_candidate(conn, code)
        assert c["calendar_available"] == 0
        assert "A股交易日历（项目代理）" != c["calendar_type"]
        assert "未取得" in c["calendar_note"]


def test_proxy_not_promoted_to_official(conn):
    """12. 代理连续性不得提升为官方连续性。"""
    n = conn.execute(
        "select count(*) from tr_candidate_master "
        "where continuity_level='verified_official_calendar'").fetchone()[0]
    assert n == 0
    r = tr_layer.get_candidate(conn, "399997CNY02")
    assert r["continuity_level"] == "verified_against_proxy_calendar"
    assert r["calendar_is_official"] == 0


def test_admission_states_not_upgraded(conn):
    """四个准入状态必须保持审计结论，不得升级。"""
    cands = tr_layer.list_candidates(conn)
    assert sum(c["raw_data_layer_ingest_candidate"] for c in cands) == 12
    assert sum(c["validated_series_candidate"] for c in cands) == 0
    assert sum(c["proxy_qualified_series_candidate"] for c in cands) == 0
    assert sum(c["formal_series_admitted"] for c in cands) == 0


def test_continuity_distribution_matches_audit(conn, audit):
    """连续性分布必须与审计 JSON 一致。"""
    t = audit["summary"]["totals"]
    for level in tr_layer.CONTINUITY_STATES:
        db_n = conn.execute(
            "select count(*) from tr_candidate_master where "
            "continuity_level=?", (level,)).fetchone()[0]
        key = f"continuity_{level}"
        assert db_n == t[key], f"{level}：DB {db_n} vs 审计 {t[key]}"


# ============================================================ 13-14. 边界
def test_no_formal_engine_can_read(conn):
    """13. 未验证序列不能被正式回测引擎读取。

    正式回测读的是 index_daily；tr_* 表不在其查询范围。
    """
    # 模拟正式引擎的查询：只查 index_daily
    rows = conn.execute(
        "select count(*) from index_daily where index_code in "
        "('H00300','H00905','H00016','H20930')").fetchone()[0]
    assert rows == 0, "正式引擎能读到全收益数据"


def test_no_formal_ranking_use(conn):
    """14. 未验证序列不能进入正式排名。"""
    n = conn.execute(
        "select count(*) from tr_candidate_master "
        "where formal_series_admitted=1").fetchone()[0]
    assert n == 0


# ============================================================ 15-16. 完整性
def test_integrity_ok(conn):
    """15. integrity_check 通过。"""
    assert conn.execute("pragma integrity_check").fetchone()[0] == "ok"


def test_fk_check_ok(conn):
    """15b. foreign_key_check 无违规。"""
    assert len(conn.execute("pragma foreign_key_check").fetchall()) == 0


def test_migration_repeatable():
    """16. 迁移可重复执行（幂等）。"""
    with tr_layer.get_tr_connection() as c:
        before = tr_layer.tr_table_counts(c)
        tr_layer.init_tr_layer(c)
        after = tr_layer.tr_table_counts(c)
    assert before == after


def test_quality_snapshots_complete(conn):
    """每个候选都有质量快照。"""
    for code in EXPECTED_CODES:
        q = tr_layer.latest_quality_snapshot(conn, code)
        assert q is not None, f"{code} 缺质量快照"
        assert q["real_history_start"] == "unknown"
        assert q["continuity_status"] in tr_layer.CONTINUITY_STATES


def test_mapping_records_marked_technical(conn):
    """映射记录必须标为技术推断。"""
    ms = _rows(conn, "select * from tr_price_index_mapping")
    assert len(ms) == 12
    for m in ms:
        assert m["evidence_level"] == "technical_inference"
        assert m["official_mapping_document_found"] == 0


def test_no_vacuous_assertion():
    """本文件不得出现恒真断言（用 AST 检查，避免字符串自伤）。"""
    import ast
    src = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue
        e = node.test
        # assert True
        if isinstance(e, ast.Constant) and e.value is True:
            raise AssertionError(f"恒真断言于第 {node.lineno} 行")
        # assert X or True
        if isinstance(e, ast.BoolOp) and isinstance(e.op, ast.Or):
            if any(isinstance(v, ast.Constant) and v.value is True
                   for v in e.values):
                raise AssertionError(f"含 or True 于第 {node.lineno} 行")
