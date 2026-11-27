"""阶段3B-6.2.3.0.3 H30184 零值修复专项测试。

**直接调用真实修复函数与真实数据库**，不读预生成报告自证。
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

from scripts.repair_3b6_2_3_0_3_h30184 import (  # noqa: E402
    DECISION, TARGET_DATE, TARGET_INDEX, apply_repair, connect_ro,
    file_sha256, index_fingerprints, is_anomaly, load_official_evidence,
    read_target, snapshot, validate_decision)

REPORTS = ROOT / "reports"
EVID = REPORTS / "evidence" / "phase3B6_2_3_0_3"


@pytest.fixture(scope="module")
def conn():
    c = connect_ro()
    yield c
    c.close()


@pytest.fixture(scope="module")
def official() -> dict:
    return load_official_evidence()


# ============================================================ 异常识别
def test_target_anomaly_identified(conn):
    """1. H30184 目标异常记录能被准确识别。"""
    rec = read_target(conn)
    assert rec is not None
    assert rec["index_code"] == "H30184"
    assert rec["trade_date"] == "2013-06-28"
    assert rec["close"] == 0.0
    assert rec["open"] is None and rec["high"] is None and rec["low"] is None
    assert is_anomaly(rec) is True


def test_is_anomaly_rejects_normal_row():
    """正常记录不得被判为异常。"""
    assert is_anomaly({"close": 1502.22}) is False
    assert is_anomaly({"close": None}) is False
    assert is_anomaly(None) is False


def test_only_one_zero_row_in_db(conn):
    """全库只有一条非正收盘记录，且就是目标记录。"""
    rows = conn.execute(
        "select index_code, trade_date, close from index_daily "
        "where close<=0").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == TARGET_INDEX
    assert rows[0][1] == TARGET_DATE


# ============================================================ 官方证据
def test_official_evidence_complete(official):
    """官方证据必须完整（URL、SHA256、指数名、收盘值）。"""
    assert official["evidence_grade"] == "L1"
    assert official["official_name"] == "中证全指半导体产品与设备指数"
    assert official["official_close"] == 0.0
    assert len(official["single_date_sha256"]) == 64
    assert len(official["range_sha256"]) == 64
    assert "csindex.com.cn" in official["single_date_url"]
    assert "csindex.com.cn" in official["range_url"]


def test_official_raw_files_exist(official):
    """原始响应文件必须真实存在且 SHA256 一致。"""
    for name, key in (("single_20130628.json", "single_date_sha256"),
                      ("range_20130624_20130703.json", "range_sha256")):
        f = EVID / name
        assert f.exists(), f"缺原始响应 {name}"
        assert hashlib.sha256(f.read_bytes()).hexdigest() == official[key]


def test_official_single_date_returns_empty(official):
    """官方单一日期查询返回空数组（关键证据）。"""
    assert official["single_date_rows"] == 0


def test_official_range_shows_zero(official):
    """官方区间查询对目标日返回 close=0.0 且 OHLC 全 null。"""
    assert official["official_close"] == 0.0
    assert official["official_open"] is None
    assert official["range_row_count"] >= 5
    # 前后交易日有有效值，证明是单日异常而非整段缺失
    assert official["prev_day_close"] and official["prev_day_close"] > 0
    assert official["next_day_close"] and official["next_day_close"] > 0


# ============================================================ 决策约束
def test_insufficient_evidence_blocks_repair():
    """2. 官方证据不足时不允许填补点位（情况 A 被拒绝）。"""
    with pytest.raises(ValueError, match="证据不足"):
        validate_decision("A", {"official_close": None})
    with pytest.raises(ValueError, match="证据不足"):
        validate_decision("A", {"official_close": 0.0})


def test_decision_b_rejects_when_official_has_value():
    """官方给了正值时不能静默按 B 处理。"""
    with pytest.raises(ValueError, match="不应按 B/C"):
        validate_decision("B", {"official_close": 1502.22})


def test_unknown_decision_rejected():
    with pytest.raises(ValueError, match="未知决策"):
        validate_decision("X", {"official_close": None})


def test_apply_repair_dry_run_does_not_write(official):
    """3. dry_run 不得修改数据库。"""
    before_sha = file_sha256()
    r = apply_repair(official, dry_run=True)
    assert r["modified"] is False
    assert r["affected_rows"] == 0
    assert file_sha256() == before_sha


def test_decision_is_b():
    """本轮决策必须是 B（官方无法确认真实点位）。"""
    assert DECISION == "B"


# ============================================================ 修复后状态
def test_target_marked_suspect(conn):
    """目标记录已标记 suspect，且 close 原值保留。"""
    rec = read_target(conn)
    assert rec["quality_status"] == "suspect"
    assert rec["close"] == 0.0, "close 原值必须保留，不得插值"
    assert rec["quality_note"] and "官方无法确认真实收盘点位" in rec["quality_note"]


def test_ohlc_not_fabricated(conn):
    """4. OHLC 缺失时不得凭空补造。"""
    rec = read_target(conn)
    assert rec["open"] is None
    assert rec["high"] is None
    assert rec["low"] is None


def test_original_fields_preserved(conn):
    """原始字段（source/run_id/row_fingerprint/collected_at）不得改动。"""
    rec = read_target(conn)
    assert rec["source"] == "akshare.stock_zh_index_hist_csindex"
    assert rec["run_id"] == 266
    assert rec["collected_at"] == "2026-11-23T17:38:31"
    assert rec["row_fingerprint"] == (
        "0084f7d807800fc23855387e55d7ea24131619d8ad2c1d9bb78c30a4ab23e702")


def test_other_indexes_unaffected(conn):
    """5. 其他指数记录不受影响（行数 + 指纹）。"""
    fp_file = EVID / "fingerprints_before.json"
    before = (json.loads(fp_file.read_text(encoding="utf-8"))
              if fp_file.exists() else None)
    after = index_fingerprints(conn)
    assert len(after) == 10
    if before:
        for code, b in before.items():
            assert after[code]["rows"] == b["rows"], f"{code} 行数变化"
            if code != TARGET_INDEX:
                assert after[code]["fingerprint"] == b["fingerprint"], \
                    f"{code} 数据被改动"


def test_placeholder_rows_intact(conn):
    """6. 10 条 suspect 占位记录不受影响。"""
    rows = conn.execute(
        "select index_code, close, quality_status from index_daily "
        "where trade_date='2004-01-01' order by index_code").fetchall()
    assert len(rows) == 10
    for r in rows:
        assert r[2] == "suspect", f"{r[0]} 占位行状态被改"


def test_total_rows_unchanged(conn):
    """总行数不得变化（只改状态，不删不增）。"""
    assert conn.execute(
        "select count(*) from index_daily").fetchone()[0] == 50603


def test_suspect_count_is_11(conn):
    """suspect 行数从 10 增至 11（新增的正是目标记录）。"""
    n = conn.execute(
        "select count(*) from index_daily where quality_status<>'valid'"
    ).fetchone()[0]
    assert n == 11


# ============================================================ 事务与完整性
def test_transaction_rollback_on_wrong_scope():
    """7. 影响行数不为 1 时必须回滚。"""
    conn = sqlite3.connect(ROOT / "data" / "fund_agent.db")
    try:
        before = conn.execute(
            "select count(*) from index_daily").fetchone()[0]
        with pytest.raises(RuntimeError):
            with conn:
                cur = conn.execute(
                    "update index_daily set quality_status='suspect' "
                    "where index_code='H30184' and trade_date='NOT_EXIST'")
                if cur.rowcount != 1:
                    raise RuntimeError(f"影响行数 {cur.rowcount} != 1")
        assert conn.execute(
            "select count(*) from index_daily").fetchone()[0] == before
    finally:
        conn.close()


def test_integrity_and_fk_ok(conn):
    """8. 修改前后数据库完整性检查正常。"""
    assert conn.execute("pragma integrity_check").fetchone()[0] == "ok"
    assert len(conn.execute("pragma foreign_key_check").fetchall()) == 0


def test_db_sha256_is_64_hex():
    """数据库 SHA256 必须是完整 64 位。"""
    s = file_sha256()
    assert len(s) == 64
    assert all(ch in "0123456789abcdef" for ch in s)


# ============================================================ 收益计算影响
def test_anomaly_excluded_from_valid_series(conn):
    """9. 异常记录不再进入有效收益计算。"""
    rows = conn.execute(
        "select trade_date, close from index_daily "
        "where index_code='H30184' and quality_status='valid' "
        "order by trade_date").fetchall()
    dates = {r[0] for r in rows}
    assert TARGET_DATE not in dates, "异常日仍出现在 valid 序列中"
    # H30184 原始 5316 行；suspect = 2004-01-01 占位行 + 目标记录 = 2
    assert len(rows) == 5314


def test_no_zero_close_in_valid_series(conn):
    """有效序列中不得存在非正收盘。"""
    n = conn.execute(
        "select count(*) from index_daily "
        "where quality_status='valid' and close<=0").fetchone()[0]
    assert n == 0


# ============================================================ 报告
def test_repair_report_exists():
    """10. 报告必须存在且记录证据等级与处理依据。"""
    for name in ("phase3B6_2_3_0_3_design.md",
                 "phase3B6_2_3_0_3_repair_report.md",
                 "phase3B6_2_3_0_3_test_report.md"):
        assert (REPORTS / name).exists(), f"缺报告 {name}"
    txt = (REPORTS / "phase3B6_2_3_0_3_repair_report.md").read_text(
        encoding="utf-8")
    assert "L1" in txt
    assert "情况 B" in txt or "情况B" in txt
    assert "suspect" in txt


def test_report_distinguishes_fact_vs_action():
    """报告必须区分官方事实、数据库状态、修复动作、未确认事项。"""
    txt = (REPORTS / "phase3B6_2_3_0_3_repair_report.md").read_text(
        encoding="utf-8")
    for kw in ("官方确认事实", "数据库实际状态", "修复动作", "未能确认"):
        assert kw in txt, f"报告缺分段「{kw}」"


def test_gates_unchanged():
    """所有门禁保持关闭。"""
    txt = (REPORTS / "phase3B6_2_3_0_3_repair_report.md").read_text(
        encoding="utf-8")
    for gate in ("ready_for_research_analysis", "ready_for_backtest",
                 "ready_for_formal_ranking",
                 "ready_for_3b6_2_3_1_series_build"):
        assert gate in txt


def test_no_vacuous_assertion():
    txt = Path(__file__).read_text(encoding="utf-8")
    assert ("or " + "True") not in txt
    assert ("assert " + "True") not in txt


# ============================================================ 证据来源一致性（3B-6.2.3.0.3.1）
def _evidence_json(name: str) -> tuple[dict, str]:
    """读取真实证据文件，返回 (解析结果, SHA256)。"""
    f = EVID / name
    assert f.exists(), f"缺证据文件 {name}"
    raw = f.read_bytes()
    return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()


def test_range_evidence_row_count_is_7():
    """区间查询实际行数必须为 7（读真实文件，不读报告）。"""
    d, _ = _evidence_json("range_20130624_20130703.json")
    rows = d.get("data") or []
    assert len(rows) == 7


def test_range_evidence_last_date_is_0702():
    """区间查询最后日期必须是 2013-07-02，不是 2013-07-03。"""
    d, _ = _evidence_json("range_20130624_20130703.json")
    dates = [r["tradeDate"] for r in d["data"]]
    assert dates[0] == "20130624"
    assert dates[-1] == "20130702"
    assert "20130703" not in dates, "7 行区间响应不应包含 2013-07-03"


def test_0703_only_in_wide_evidence():
    """2013-07-03 数据只存在于宽区间证据中。"""
    rng, _ = _evidence_json("range_20130624_20130703.json")
    wide, _ = _evidence_json("h30184_wide.json")
    rng_dates = {r["tradeDate"] for r in rng["data"]}
    wide_dates = {r["tradeDate"] for r in wide["data"]}
    assert "20130703" not in rng_dates
    assert "20130703" in wide_dates
    row = next(r for r in wide["data"] if r["tradeDate"] == "20130703")
    assert row["close"] == 1569.54


def test_wide_evidence_row_count_is_41():
    """宽区间证据必须为 41 行。"""
    d, _ = _evidence_json("h30184_wide.json")
    assert len(d.get("data") or []) == 41


def test_report_does_not_attribute_0703_to_range():
    """报告不得把 2013-07-03 的**数据**归入 7 行区间响应。

    注意区分：
    - URL 里的 ``endDate=20130703`` 是**请求参数**，合法；
    - 逐日表格里 ``2013-07-03`` 那一行的**来源列**必须是宽区间证据。
    """
    txt = (REPORTS / "phase3B6_2_3_0_3_repair_report.md").read_text(
        encoding="utf-8")
    lines = txt.splitlines()
    # 只检查「逐日数据表格」中日期单元格恰为 2013-07-03 的行，
    # 避免把 URL 的 endDate 参数、证据文件名 range_...20130703.json 误判
    checked = 0
    for i, line in enumerate(lines):
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells:
            continue
        if cells[0] not in ("`2013-07-03`", "2013-07-03"):
            continue
        checked += 1
        # 该行的来源列必须是宽区间证据
        assert "h30184_wide" in line, \
            f"第 {i + 1} 行把 2013-07-03 的数据归入区间响应：{line.strip()}"
        assert "range_20130624_20130703" not in line, \
            f"第 {i + 1} 行把 2013-07-03 的数据归入区间响应：{line.strip()}"
    assert checked >= 1, "逐日表格中未找到 2013-07-03 行"


def test_report_states_range_is_7_rows():
    """报告必须明确写出区间查询为 7 行。"""
    txt = (REPORTS / "phase3B6_2_3_0_3_repair_report.md").read_text(
        encoding="utf-8")
    assert "7 行" in txt
    assert "2013-07-02" in txt
    assert "h30184_wide.json" in txt


def test_report_marks_source_per_row():
    """逐日表格必须标注来源文件列。"""
    txt = (REPORTS / "phase3B6_2_3_0_3_repair_report.md").read_text(
        encoding="utf-8")
    assert "来源文件" in txt


def test_evidence_sha256_unchanged(official):
    """原始证据 SHA256 不得改变。"""
    _, rng_sha = _evidence_json("range_20130624_20130703.json")
    _, wide_sha = _evidence_json("h30184_wide.json")
    _, single_sha = _evidence_json("single_20130628.json")
    assert rng_sha == official["range_sha256"]
    assert rng_sha == ("ccbbb38316fab0f9c24a56d79a7c15af7559e114399253da4"
                       "b5cbbb660b609e5")
    assert single_sha == official["single_date_sha256"]
    assert wide_sha == ("858ecda87ee336bb0568f9bfeb9ba895f54c01eecc44b28a46"
                        "e934d1614d7e26")


def test_decision_and_evidence_grade_unchanged(official):
    """不得改变证据等级与情况 B 决策。"""
    assert official["evidence_grade"] == "L1"
    assert DECISION == "B"


def test_db_sha256_unchanged_by_doc_fix():
    """本轮是纯文档修正，数据库 SHA256 必须仍为修复后值。"""
    assert file_sha256() == (
        "1671e4037cd265a2dead8b78d43614189a782385ca450ac6c2de3c4ff36ee873")
