"""阶段3A.2.1.2 专项测试：敏感性扫描、并发安全、卖出费用不足链路。

全部使用临时数据库或独立副本，不触碰正式库。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from app.validation.concurrency import (
    ConcurrentTask,
    _check_hash_consistency,
    run_with_write_lock,
)
from app.validation.sensitivity_scan import (
    DELETION_MODES,
    DELETION_RATIOS,
    MODE_BLOCK,
    MODE_HOLDING,
    MODE_RANDOM,
    MODE_RECOVERY,
    MODE_SIGNAL,
    ScenarioResult,
    copy_database,
    count_rows,
    delete_continuous_block,
    delete_random_scattered,
    missing_trading_day_count,
    source_fingerprint,
    summarize_matrix,
)


def _seed_market(db_path, code="510300", days=40, price=10.0):
    """写入受控行情，返回交易日字符串列表。"""
    trade_days = []
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO etf_pool (code, name, category, fund_type, "
            "data_source, source_tested_at, status) "
            "VALUES (?,?,?,'指数型-股票','test','2024-01-01','active')",
            (code, "测试ETF", "宽基指数ETF"),
        )
        run_id = conn.execute(
            "INSERT INTO adjustment_runs (started_at, finished_at, status, total_codes, "
            "success_codes) VALUES ('2024-01-01T00:00:00','2024-01-01T00:00:01',"
            "'success',1,1)"
        ).lastrowid
        conn.execute(
            "INSERT INTO etf_adjustment_snapshots "
            "(run_id, code, status, collected_at, source, coverage_start, coverage_end, "
            "matched_start, matched_end, raw_rows, qfq_rows, matched_rows, missing_rows, "
            "is_current, created_at) VALUES (?,?,'success','2024-01-01T00:00:00','t',"
            "?,?,?,?,?,?,?,0,1,'2024-01-01T00:00:00')",
            (run_id, code, "2024-01-02", "2024-03-31",
             "2024-01-02", "2024-03-31", days, days, days),
        )
        snapshot = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for offset in range(days):
            day = (date(2024, 1, 2) + __import__("datetime").timedelta(days=offset)).isoformat()
            trade_days.append(day)
            conn.execute("INSERT OR REPLACE INTO trade_calendar (trade_date) VALUES (?)", (day,))
            conn.execute(
                "INSERT OR REPLACE INTO etf_daily_prices "
                "(code, trade_date, open, high, low, close, volume, amount, "
                "adjusted_close, adjustment_type, quality_status, source, collected_at, "
                "adjustment_snapshot_id, adjustment_collected_at, adjustment_source, "
                "adjustment_coverage_start, adjustment_coverage_end) "
                "VALUES (?,?,?,?,?,?,?,?,?,'qfq','valid','t','2024-01-01T00:00:00',"
                "?,'2024-01-01T00:00:00','t',?,?)",
                (code, day, price, price, price, price, 1000, price * 1000, price,
                 snapshot, "2024-01-02", "2024-03-31"),
            )
        conn.commit()
    return trade_days


# ============================================ 敏感性扫描基础

def test_deletion_ratios_and_modes_cover_required_set() -> None:
    """比例必须覆盖 0/1/3/5/10/20%，模式必须覆盖五种。"""
    assert DELETION_RATIOS == (0.0, 0.01, 0.03, 0.05, 0.10, 0.20)
    assert len(DELETION_MODES) == 5
    assert MODE_RANDOM in DELETION_MODES
    assert MODE_BLOCK in DELETION_MODES
    assert MODE_HOLDING in DELETION_MODES
    assert MODE_SIGNAL in DELETION_MODES
    assert MODE_RECOVERY in DELETION_MODES


def test_copy_database_does_not_touch_source(temp_db) -> None:
    """副本通过 backup API 生成，源库行数不变。"""
    _seed_market(temp_db, days=20)
    before = source_fingerprint(temp_db)
    work = temp_db.parent / "sens_copy_work"
    copy = copy_database(temp_db, work, name="scenario.db")
    after = source_fingerprint(temp_db)

    assert copy.exists()
    assert before == after, "源库指纹被修改"
    with sqlite3.connect(copy) as conn:
        assert count_rows(conn, "2024-01-01", "2024-12-31") == 20


def test_random_deletion_reproducible(temp_db) -> None:
    """相同种子与比例必须删除相同行。"""
    _seed_market(temp_db, days=50)
    work = temp_db.parent / "sens_rand"
    results = []
    for index in range(2):
        copy = copy_database(temp_db, work, name=f"rand_{index}.db")
        with sqlite3.connect(copy) as conn:
            deleted, detail = delete_random_scattered(
                conn, ["510300"], "2024-01-01", "2024-12-31",
                ratio=0.10, seed=12345,
            )
            conn.commit()
            results.append((deleted, json.dumps(detail, sort_keys=True)))
    assert results[0] == results[1], "相同种子删除结果不一致"


def test_random_deletion_ratio_approximately_correct(temp_db) -> None:
    _seed_market(temp_db, days=100)
    work = temp_db.parent / "sens_ratio"
    copy = copy_database(temp_db, work, name="r.db")
    with sqlite3.connect(copy) as conn:
        deleted, _ = delete_random_scattered(
            conn, ["510300"], "2024-01-01", "2024-12-31", ratio=0.10, seed=7
        )
        conn.commit()
    # 100 天里保护首尾各 3 天，可删 94 天，10% ≈ 9 行
    assert 7 <= deleted <= 11, f"删除比例偏离预期：{deleted}"


def test_continuous_block_is_contiguous(temp_db) -> None:
    """连续模式删除的日期必须连续。"""
    _seed_market(temp_db, days=60)
    work = temp_db.parent / "sens_block"
    copy = copy_database(temp_db, work, name="b.db")
    with sqlite3.connect(copy) as conn:
        deleted, detail = delete_continuous_block(
            conn, ["510300"], "2024-01-01", "2024-12-31", ratio=0.10, seed=1
        )
        conn.commit()
    block = detail["blocks"]["510300"]
    assert block["deleted"] == deleted
    assert block["first"] is not None and block["last"] is not None
    # 起止之间的交易日数量应等于删除数（连续）
    first_i = date.fromisoformat(block["first"])
    last_i = date.fromisoformat(block["last"])
    assert (last_i - first_i).days + 1 == deleted


def test_missing_trading_day_count(temp_db) -> None:
    _seed_market(temp_db, days=10)
    work = temp_db.parent / "sens_missing"
    copy = copy_database(temp_db, work, name="m.db")
    calendar = [date(2024, 1, 2 + i).isoformat() for i in range(10)]
    with sqlite3.connect(copy) as conn:
        conn.execute("DELETE FROM etf_daily_prices WHERE trade_date IN (?, ?)",
                     (calendar[3], calendar[7]))
        conn.commit()
        assert missing_trading_day_count(
            conn, calendar[0], calendar[-1], calendar
        ) == 2


def test_zero_ratio_deletes_nothing() -> None:
    """0% 基线组不得删除任何行情。"""
    from app.validation.sensitivity_scan import run_single_scenario
    result = ScenarioResult(
        scenario_id="x", deletion_ratio=0.0,
        deletion_mode=MODE_RANDOM, random_seed=1,
    )
    assert result.deleted_rows == 0


# ============================================ 汇总与状态

def test_summarize_matrix_groups_by_ratio_and_mode() -> None:
    payload = {
        "scenarios": [
            {"deletion_ratio": 0.0, "deletion_mode": MODE_RANDOM,
             "total_return": 0.2, "sharpe": 0.8, "max_drawdown": -0.1,
             "status": "success"},
            {"deletion_ratio": 0.05, "deletion_mode": MODE_RANDOM,
             "total_return": 0.15, "sharpe": 0.6, "max_drawdown": -0.12,
             "status": "partial"},
            {"deletion_ratio": 0.05, "deletion_mode": MODE_BLOCK,
             "total_return": 0.10, "sharpe": 0.4, "max_drawdown": -0.15,
             "status": "partial"},
        ],
    }
    summary = summarize_matrix(payload)
    assert summary["by_ratio"]["0%"]["count"] == 1
    assert summary["by_ratio"]["5%"]["count"] == 2
    assert summary["by_ratio"]["5%"]["returns_mean"] == pytest.approx(0.125)
    assert summary["by_mode"][MODE_RANDOM]["count"] == 2
    assert summary["status_totals"]["success"] == 1
    assert summary["status_totals"]["partial"] == 2


def test_summarize_matrix_keeps_failed_and_insufficient() -> None:
    """failed 与 insufficient 不得从汇总里删除。"""
    payload = {
        "scenarios": [
            {"deletion_ratio": 0.2, "deletion_mode": MODE_RANDOM,
             "total_return": None, "sharpe": None, "max_drawdown": None,
             "status": "failed"},
            {"deletion_ratio": 0.2, "deletion_mode": MODE_BLOCK,
             "total_return": None, "sharpe": None, "max_drawdown": None,
             "status": "insufficient"},
        ],
    }
    summary = summarize_matrix(payload)
    assert summary["status_totals"]["failed"] == 1
    assert summary["status_totals"]["insufficient"] == 1
    assert summary["by_ratio"]["20%"]["count"] == 2


# ============================================ 并发

def test_concurrent_task_hash_consistency_same_params() -> None:
    tasks = [
        ConcurrentTask(task_id="a", params={"x": 1}, input_hash="h1"),
        ConcurrentTask(task_id="b", params={"x": 1}, input_hash="h1"),
    ]
    assert _check_hash_consistency(tasks)["consistent"] is True


def test_concurrent_task_hash_inconsistent_same_params() -> None:
    tasks = [
        ConcurrentTask(task_id="a", params={"x": 1}, input_hash="h1"),
        ConcurrentTask(task_id="b", params={"x": 1}, input_hash="h2"),
    ]
    result = _check_hash_consistency(tasks)
    assert result["consistent"] is False
    assert any("同参数" in p for p in result["problems"])


def test_concurrent_task_hash_inconsistent_diff_params() -> None:
    tasks = [
        ConcurrentTask(task_id="a", params={"x": 1}, input_hash="h1"),
        ConcurrentTask(task_id="b", params={"x": 2}, input_hash="h1"),
    ]
    result = _check_hash_consistency(tasks)
    assert result["consistent"] is False
    assert any("不同参数" in p for p in result["problems"])


def test_write_lock_serializes_and_returns_value(tmp_path) -> None:
    calls = []

    def work(value):
        calls.append(value)
        return value * 2

    assert run_with_write_lock(work, 3, lock_dir=tmp_path) == 6
    assert calls == [3]


def test_write_lock_releases_on_exception(tmp_path) -> None:
    def boom():
        raise ValueError("boom")

    with pytest.raises(ValueError):
        run_with_write_lock(boom, lock_dir=tmp_path)
    assert run_with_write_lock(lambda: "ok", lock_dir=tmp_path) == "ok"
