"""阶段3B-6.2.3.1.1.1.2 迁移部分状态幂等性与审计基线专项测试。

**真实构造只有一列存在的数据库结构**，真实执行 SQL，不检查源码字符串。
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
EVID = REPORTS / "evidence" / "phase3B6_2_3_1_1_1_2"
AUDIT = REPORTS / "phase3B6_2_3_1_1_1_2_audit.json"

EXPECTED_INDEX_DAILY_FP = (
    "dbbd07c1339e99f27b0aeadb43eb56848776dbbad97f3fb7b9748bbd2f1e61f6")
EXPECTED_RAW_ROWS = 55942
EXPECTED_EVIDENCE = 34

TASK_BASELINE_HEAD = "cdbdbf0284c8cf9f356fa4d298fd29f03169a014"

COL_JSON = "raw_record_json"
COL_SHA = "raw_record_sha256"


def _make_db(tmp_path) -> sqlite3.Connection:
    """构造最小库：只有 tr_index_daily_raw 三列 + 2 行数据。"""
    db = tmp_path / "partial.db"
    c = sqlite3.connect(db)
    c.execute("create table tr_index_daily_raw ("
              "tr_code text, trade_date text, close real)")
    c.executemany(
        "insert into tr_index_daily_raw values (?,?,?)",
        [("H00300", "20200102", 1.5), ("H00300", "20200103", 1.6)])
    c.commit()
    return c


def _cols(c) -> set[str]:
    return {r[1] for r in c.execute("pragma table_info(tr_index_daily_raw)")}


def _row_count(c) -> int:
    return c.execute(
        "select count(*) from tr_index_daily_raw").fetchone()[0]


def _add_only(c, col: str) -> None:
    """真实构造「只有一列存在」的结构。"""
    c.execute(f"alter table tr_index_daily_raw add column {col} text")
    c.commit()


# ============================================================ 1-4. UP 部分状态
def test_up_from_none(tmp_path):
    """1. 两列都不存在，UP 后两列均存在。"""
    c = _make_db(tmp_path)
    assert COL_JSON not in _cols(c) and COL_SHA not in _cols(c)
    r = tr_layer.migrate_raw_record_columns(c)
    c.commit()
    assert r["executed"] is True
    assert set(r["added"]) == {COL_JSON, COL_SHA}
    assert COL_JSON in _cols(c) and COL_SHA in _cols(c)
    c.close()


def test_up_idempotent_when_both_exist(tmp_path):
    """2. 两列都存在，UP 重复执行无异常。"""
    c = _make_db(tmp_path)
    tr_layer.migrate_raw_record_columns(c)
    c.commit()
    r2 = tr_layer.migrate_raw_record_columns(c)
    c.commit()
    assert r2["executed"] is False
    assert r2["added"] == []
    c.close()


def test_up_when_only_json_exists(tmp_path):
    """3. 仅 raw_record_json 存在，UP 后两列均存在（不重复建列）。"""
    c = _make_db(tmp_path)
    _add_only(c, COL_JSON)
    assert COL_JSON in _cols(c) and COL_SHA not in _cols(c)
    r = tr_layer.migrate_raw_record_columns(c)
    c.commit()
    assert r["added"] == [COL_SHA]
    assert COL_JSON in _cols(c) and COL_SHA in _cols(c)
    c.close()


def test_up_when_only_sha_exists(tmp_path):
    """4. 仅 raw_record_sha256 存在，UP 后两列均存在。"""
    c = _make_db(tmp_path)
    _add_only(c, COL_SHA)
    assert COL_SHA in _cols(c) and COL_JSON not in _cols(c)
    r = tr_layer.migrate_raw_record_columns(c)
    c.commit()
    assert r["added"] == [COL_JSON]
    assert COL_JSON in _cols(c) and COL_SHA in _cols(c)
    c.close()


# ============================================================ 5-8. DOWN 部分状态
def test_down_when_both_exist(tmp_path):
    """5. 两列都存在，DOWN 后两列均不存在。"""
    c = _make_db(tmp_path)
    tr_layer.migrate_raw_record_columns(c)
    c.commit()
    r = tr_layer.rollback_raw_record_columns(c)
    c.commit()
    assert r["executed"] is True
    assert set(r["dropped"]) == {COL_JSON, COL_SHA}
    assert COL_JSON not in _cols(c) and COL_SHA not in _cols(c)
    c.close()


def test_down_when_only_json_exists(tmp_path):
    """6. 仅 raw_record_json 存在，DOWN 后两列均不存在。"""
    c = _make_db(tmp_path)
    _add_only(c, COL_JSON)
    r = tr_layer.rollback_raw_record_columns(c)
    c.commit()
    assert r["dropped"] == [COL_JSON]
    assert COL_JSON not in _cols(c) and COL_SHA not in _cols(c)
    c.close()


def test_down_when_only_sha_exists(tmp_path):
    """7. 仅 raw_record_sha256 存在，DOWN 后两列均不存在。"""
    c = _make_db(tmp_path)
    _add_only(c, COL_SHA)
    r = tr_layer.rollback_raw_record_columns(c)
    c.commit()
    assert r["dropped"] == [COL_SHA]
    assert COL_JSON not in _cols(c) and COL_SHA not in _cols(c)
    c.close()


def test_down_idempotent_when_none(tmp_path):
    """8. 两列都不存在，DOWN 重复执行无异常。"""
    c = _make_db(tmp_path)
    r = tr_layer.rollback_raw_record_columns(c)
    c.commit()
    assert r["executed"] is False
    assert r["dropped"] == []
    c.close()


# ============================================================ 9. 不删表不丢数据
@pytest.mark.parametrize("pre", ["none", "json", "sha", "both"])
def test_no_table_drop_no_data_loss_up(tmp_path, pre):
    """9a. 任何 UP 场景都不删表、不丢数据、不动其他字段。"""
    c = _make_db(tmp_path)
    if pre in ("json", "both"):
        _add_only(c, COL_JSON)
    if pre in ("sha", "both"):
        _add_only(c, COL_SHA)
    other_before = _cols(c) - {COL_JSON, COL_SHA}
    rows_before = _row_count(c)
    tr_layer.migrate_raw_record_columns(c)
    c.commit()
    assert c.execute(
        "select count(*) from sqlite_master where type='table' "
        "and name='tr_index_daily_raw'").fetchone()[0] == 1
    assert _cols(c) - {COL_JSON, COL_SHA} == other_before
    assert _row_count(c) == rows_before
    c.close()


@pytest.mark.parametrize("pre", ["none", "json", "sha", "both"])
def test_no_table_drop_no_data_loss_down(tmp_path, pre):
    """9b. 任何 DOWN 场景都不删表、不丢数据、不动其他字段。"""
    c = _make_db(tmp_path)
    if pre in ("json", "both"):
        _add_only(c, COL_JSON)
    if pre in ("sha", "both"):
        _add_only(c, COL_SHA)
    other_before = _cols(c) - {COL_JSON, COL_SHA}
    rows_before = _row_count(c)
    tr_layer.rollback_raw_record_columns(c)
    c.commit()
    assert c.execute(
        "select count(*) from sqlite_master where type='table' "
        "and name='tr_index_daily_raw'").fetchone()[0] == 1
    assert _cols(c) == other_before
    assert _row_count(c) == rows_before
    c.close()


@pytest.mark.parametrize("pre", ["none", "json", "sha", "both"])
def test_up_down_up_from_any_state(tmp_path, pre):
    """任意初始状态下 UP→DOWN→UP 均正常。"""
    c = _make_db(tmp_path)
    if pre in ("json", "both"):
        _add_only(c, COL_JSON)
    if pre in ("sha", "both"):
        _add_only(c, COL_SHA)
    rows_before = _row_count(c)
    tr_layer.migrate_raw_record_columns(c)
    c.commit()
    assert COL_JSON in _cols(c) and COL_SHA in _cols(c)
    tr_layer.rollback_raw_record_columns(c)
    c.commit()
    assert COL_JSON not in _cols(c) and COL_SHA not in _cols(c)
    tr_layer.migrate_raw_record_columns(c)
    c.commit()
    assert COL_JSON in _cols(c) and COL_SHA in _cols(c)
    assert _row_count(c) == rows_before
    c.close()


# ============================================================ DDL 仍来自 SQL 文件
def test_ddl_still_from_sql_files():
    """DDL 必须仍来自 SQL 文件，不是 Python 硬编码。"""
    src = Path(tr_layer.__file__).read_text(encoding="utf-8")
    # 不得出现硬编码的 add column 语句
    assert "add column raw_record_json text" not in src.lower()
    assert "add column raw_record_sha256 text" not in src.lower()
    # 必须读取 SQL 文件
    assert "RAW_RECORD_MIGRATION_UP" in src
    assert "RAW_RECORD_MIGRATION_DOWN" in src
    up = tr_layer.RAW_RECORD_MIGRATION_UP.read_text(encoding="utf-8")
    down = tr_layer.RAW_RECORD_MIGRATION_DOWN.read_text(encoding="utf-8")
    assert f"ADD COLUMN {COL_JSON}" in up
    assert f"ADD COLUMN {COL_SHA}" in up
    assert f"DROP COLUMN {COL_JSON}" in down
    assert f"DROP COLUMN {COL_SHA}" in down


def test_per_column_statement_filter():
    """逐列筛选函数能正确从 SQL 文件挑出单列语句。"""
    up_json = tr_layer._statements_for_column(
        tr_layer.RAW_RECORD_MIGRATION_UP, COL_JSON, "ADD")
    up_sha = tr_layer._statements_for_column(
        tr_layer.RAW_RECORD_MIGRATION_UP, COL_SHA, "ADD")
    assert len(up_json) == 1 and COL_JSON in up_json[0]
    assert COL_SHA not in up_json[0]
    assert len(up_sha) == 1 and COL_SHA in up_sha[0]
    down_json = tr_layer._statements_for_column(
        tr_layer.RAW_RECORD_MIGRATION_DOWN, COL_JSON, "DROP")
    assert len(down_json) == 1 and COL_JSON in down_json[0]


# ============================================================ 审计基线
def test_audit_baseline_head_correct(audit):
    """审计 JSON 的 baseline_head 必须是本轮任务基线。"""
    assert audit["baseline_head"] == TASK_BASELINE_HEAD


def test_audit_baseline_not_earlier_phase(audit):
    """不得把本轮基线写成更早阶段（3B-6.2.3.1.1）的基线。"""
    assert audit["baseline_head"] != "9cf46ab084e7ecc6e51e60572c770e698b83ad7c"
    assert audit["baseline_head"] != "3aae887da4a82ba77481c0efdb2f32c11feef618"


def test_audit_has_final_head_note(audit):
    """必须有字段说明 final_head 与 baseline_head 不得混淆。"""
    assert "final_head_note" in audit
    assert "不得混淆" in audit["final_head_note"]


def test_reports_baseline_consistent(audit):
    """报告中「本轮任务基线 HEAD」的声明必须与 JSON 一致。

    注意：报告中为说明缺陷可能引用旧阶段基线（如「原写的是 X」），
    这不属于元数据声明，因此只校验**基线声明行**。
    """
    import re
    for name in ("phase3B6_2_3_1_1_1_2_fix_report.md",
                 "phase3B6_2_3_1_1_1_2_test_report.md"):
        txt = (REPORTS / name).read_text(encoding="utf-8")
        assert audit["baseline_head"] in txt, f"{name} 缺本轮基线声明"
        # 抽取所有「本轮任务基线 HEAD：`<sha>`」声明
        decl = re.findall(
            r"本轮任务基线 HEAD\*\*[：:]\s*`([0-9a-f]{40})`", txt)
        assert decl, f"{name} 未找到基线声明"
        for sha in decl:
            assert sha == audit["baseline_head"], \
                f"{name} 基线声明不一致：{sha}"


# ============================================================ 数据保护
@pytest.fixture(scope="module")
def conn():
    with tr_layer.get_tr_connection() as c:
        tr_layer.enable_foreign_keys(c)
        yield c


@pytest.fixture(scope="module")
def audit() -> dict:
    assert AUDIT.exists()
    return json.loads(AUDIT.read_text(encoding="utf-8"))


def test_raw_rows_unchanged(conn):
    assert conn.execute(
        "select count(*) from tr_index_daily_raw").fetchone()[0] == \
        EXPECTED_RAW_ROWS


def test_raw_json_data_intact(conn):
    """raw_record_json 与 SHA 数据不变（抽样真实校验）。"""
    rows = conn.execute(
        "select raw_record_json, raw_record_sha256 from tr_index_daily_raw "
        "limit 300").fetchall()
    assert rows
    for j, s in rows:
        assert j is not None and s is not None
        assert hashlib.sha256(j.encode("utf-8")).hexdigest() == s


def test_index_daily_unchanged(conn):
    fp = tr_layer.index_daily_fingerprint(conn)
    assert fp["row_count"] == 50603
    assert fp["fingerprint"] == EXPECTED_INDEX_DAILY_FP
    assert tr_layer.assert_isolated(conn)["isolated"] is True


def test_evidence_unchanged(conn):
    evs = conn.execute(
        "select relative_path, sha256 from tr_evidence_files").fetchall()
    assert len(evs) == EXPECTED_EVIDENCE
    for rel, sha in evs:
        f = ROOT / rel
        assert f.exists(), f"缺 {rel}"
        assert hashlib.sha256(f.read_bytes()).hexdigest() == sha


def test_admission_unchanged(conn):
    cands = tr_layer.list_candidates(conn)
    assert sum(c["raw_data_layer_ingest_candidate"] for c in cands) == 12
    assert sum(c["validated_series_candidate"] for c in cands) == 0
    assert sum(c["proxy_qualified_series_candidate"] for c in cands) == 0
    assert sum(c["formal_series_admitted"] for c in cands) == 0


def test_integrity_and_fk(conn):
    assert conn.execute("pragma integrity_check").fetchone()[0] == "ok"
    assert len(conn.execute("pragma foreign_key_check").fetchall()) == 0


def test_self_check_all_pass(audit):
    for k, v in audit["_self_check"].items():
        assert v is True, f"自校验失败：{k}"


def test_no_vacuous_assertion():
    """本文件不得出现恒真断言（AST 检查）。"""
    import ast
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue
        e = node.test
        if isinstance(e, ast.Constant) and e.value is True:
            raise AssertionError(f"恒真断言于第 {node.lineno} 行")
        if isinstance(e, ast.BoolOp) and isinstance(e.op, ast.Or):
            if any(isinstance(v, ast.Constant) and v.value is True
                   for v in e.values):
                raise AssertionError(f"含 or True 于第 {node.lineno} 行")
