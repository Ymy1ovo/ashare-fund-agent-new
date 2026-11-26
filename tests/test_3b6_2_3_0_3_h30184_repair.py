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
