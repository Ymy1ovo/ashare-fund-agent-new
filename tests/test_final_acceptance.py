"""阶段3A.2.1.2.1 专项测试：验收缺陷修复。

覆盖：信号附近删除比例、CLI 可复现、源库完整指纹、串行锁安全、多进程锁。
"""
from __future__ import annotations

import multiprocessing as mp
import os
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from app.validation.concurrency import (
    ConcurrencyError,
    run_with_write_lock,
    shared_lock_path,
)
from app.validation.sensitivity_scan import (
    copy_database,
    delete_signal_adjacent,
    source_fingerprint,
)


def _seed_prices(db_path, code="510300", days=60, price=10.0):
    from datetime import date, timedelta

    trade_days = []
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO etf_pool (code, name, category, fund_type, "
            "data_source, source_tested_at, status) "
            "VALUES (?,?,?,'指数型-股票','t','2024-01-01','active')",
            (code, "测试ETF", "宽基指数ETF"),
        )
        run_id = conn.execute(
            "INSERT INTO adjustment_runs (started_at, finished_at, status, "
            "total_codes, success_codes) VALUES ('2024-01-01T00:00:00',"
            "'2024-01-01T00:00:01','success',1,1)"
        ).lastrowid
        conn.execute(
            "INSERT INTO etf_adjustment_snapshots "
            "(run_id, code, status, collected_at, source, coverage_start, "
            "coverage_end, matched_start, matched_end, raw_rows, qfq_rows, "
            "matched_rows, missing_rows, is_current, created_at) "
            "VALUES (?,?,'success','2024-01-01T00:00:00','t',?,?,?,?,?,?,?,0,1,"
            "'2024-01-01T00:00:00')",
            (run_id, code, "2024-01-02", "2024-12-31",
             "2024-01-02", "2024-12-31", days, days, days),
        )
        snapshot = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for offset in range(days):
            day = (date(2024, 1, 2) + timedelta(days=offset)).isoformat()
            trade_days.append(day)
            conn.execute(
                "INSERT OR REPLACE INTO trade_calendar (trade_date) VALUES (?)",
                (day,),
            )
            conn.execute(
                "INSERT OR REPLACE INTO etf_daily_prices "
                "(code, trade_date, open, high, low, close, volume, amount, "
                "adjusted_close, adjustment_type, quality_status, source, "
                "collected_at, adjustment_snapshot_id, adjustment_collected_at, "
                "adjustment_source, adjustment_coverage_start, "
                "adjustment_coverage_end) "
                "VALUES (?,?,?,?,?,?,?,?,?,'qfq','valid','t',"
                "'2024-01-01T00:00:00',?,'2024-01-01T00:00:00','t',?,?)",
                (code, day, price, price, price, price, 1000, price * 1000,
                 price, snapshot, "2024-01-02", "2024-12-31"),
            )
        conn.commit()
    return trade_days


def _signal_map(days: list[str], count: int = 40) -> dict[str, list[str]]:
    """从交易日中挑出 count 个作为信号日（跳过首尾）。"""
    middle = days[5:-5]
    return {"510300": middle[:count]}


# ==================================================== 一、信号附近删除

def test_signal_deletion_ratio_affects_count(temp_db) -> None:
    """不同删除比例必须得到不同删除数量。"""
    days = _seed_prices(temp_db, days=80)
    signals = _signal_map(days, count=40)
    work = temp_db.parent / "sig_ratio"
    results = {}
    for ratio in (0.05, 0.20):
        copy = copy_database(temp_db, work, name=f"r{int(ratio*100)}.db")
        with sqlite3.connect(copy) as conn:
            deleted, detail = delete_signal_adjacent(
                conn, ["510300"], days[0], days[-1], ratio, 20261112,
                signal_dates=signals,
            )
            conn.commit()
        results[ratio] = deleted
    assert results[0.05] < results[0.20], (
        f"比例未生效：5% 删 {results[0.05]}，20% 删 {results[0.20]}"
    )
    assert results[0.05] == pytest.approx(2, abs=1)
    assert results[0.20] == pytest.approx(8, abs=1)


def test_signal_deletion_zero_ratio_deletes_nothing(temp_db) -> None:
    days = _seed_prices(temp_db, days=80)
    signals = _signal_map(days, count=40)
    work = temp_db.parent / "sig_zero"
    copy = copy_database(temp_db, work, name="z.db")
    with sqlite3.connect(copy) as conn:
        deleted, _ = delete_signal_adjacent(
            conn, ["510300"], days[0], days[-1], 0.0, 20261112,
            signal_dates=signals,
        )
        conn.commit()
    assert deleted == 0


def test_signal_deletion_reproducible(temp_db) -> None:
    """同种子同比例必须删除相同日期。"""
    days = _seed_prices(temp_db, days=80)
    signals = _signal_map(days, count=40)
    work = temp_db.parent / "sig_rep"
    picked = []
    for index in range(2):
        copy = copy_database(temp_db, work, name=f"rep{index}.db")
        with sqlite3.connect(copy) as conn:
            _, detail = delete_signal_adjacent(
                conn, ["510300"], days[0], days[-1], 0.10, 999,
                signal_dates=signals,
            )
            conn.commit()
        picked.append(detail["signal"]["510300"]["dates"])
    assert picked[0] == picked[1], "同种子结果不一致"


def test_signal_deletion_protects_boundaries(temp_db) -> None:
    """首尾各 3 个信号日不得被删除。"""
    days = _seed_prices(temp_db, days=80)
    signals = _signal_map(days, count=40)
    work = temp_db.parent / "sig_prot"
    copy = copy_database(temp_db, work, name="p.db")
    with sqlite3.connect(copy) as conn:
        _, detail = delete_signal_adjacent(
            conn, ["510300"], days[0], days[-1], 0.20, 20261112,
            signal_dates=signals,
        )
        conn.commit()
    picked = detail["signal"]["510300"]["dates"]
    all_signals = sorted(signals["510300"])
    protected = set(all_signals[:3]) | set(all_signals[-3:])
    assert not (set(picked) & protected), f"删除了受保护区间：{picked}"


def test_signal_deletion_no_signals_reports_skip(temp_db) -> None:
    """无信号日时不得伪造删除。"""
    days = _seed_prices(temp_db, days=40)
    work = temp_db.parent / "sig_none"
    copy = copy_database(temp_db, work, name="n.db")
    with sqlite3.connect(copy) as conn:
        deleted, detail = delete_signal_adjacent(
            conn, ["510300"], days[0], days[-1], 0.10, 1, signal_dates={},
        )
        conn.commit()
    assert deleted == 0
    assert detail["skipped"], "必须记录 skipped 明细"
    assert detail["skipped"][0]["reason"] == "no_signal_dates"


def test_signal_deletion_records_detail_fields(temp_db) -> None:
    """必须记录信号数、可删数、实际删除数、实际比例。"""
    days = _seed_prices(temp_db, days=80)
    signals = _signal_map(days, count=40)
    work = temp_db.parent / "sig_detail"
    copy = copy_database(temp_db, work, name="d.db")
    with sqlite3.connect(copy) as conn:
        delete_signal_adjacent(conn, ["510300"], days[0], days[-1], 0.10,
                               20261112, signal_dates=signals)
        conn.commit()
    # 重新调用一次取 detail
    copy2 = copy_database(temp_db, work, name="d2.db")
    with sqlite3.connect(copy2) as conn:
        _, detail = delete_signal_adjacent(
            conn, ["510300"], days[0], days[-1], 0.10, 20261112,
            signal_dates=signals,
        )
        conn.commit()
    entry = detail["signal"]["510300"]
    for key in ("signal_count", "eligible", "deleted", "actual_ratio"):
        assert key in entry, f"缺少字段 {key}"
    assert entry["signal_count"] == 40
    assert entry["eligible"] == 34
    assert entry["deleted"] >= 1
    assert 0 < entry["actual_ratio"] <= 1


# ==================================================== 四、源库完整指纹

def test_source_fingerprint_uses_full_content(temp_db) -> None:
    """指纹必须来自 market-fingerprint-v3，不是行数求和。"""
    _seed_prices(temp_db, days=10)
    fp = source_fingerprint(temp_db)
    assert fp.startswith("market-fingerprint-v3:"), fp
    assert len(fp.split(":")[1]) == 64


def test_source_fingerprint_detects_single_row_change(temp_db) -> None:
    """改一行但保持行数不变，指纹必须变化。"""
    days = _seed_prices(temp_db, days=10)
    before = source_fingerprint(temp_db)
    with sqlite3.connect(temp_db) as conn:
        conn.execute(
            "UPDATE etf_daily_prices SET adjusted_close = 99.5 "
            "WHERE code='510300' AND trade_date=?", (days[4],),
        )
        conn.commit()
        count_after = conn.execute(
            "SELECT COUNT(*) FROM etf_daily_prices"
        ).fetchone()[0]
    after = source_fingerprint(temp_db)
    assert count_after == 10, "行数必须未变"
    assert before != after, "行数不变但内容变了，指纹必须变化"


def test_source_fingerprint_stable_when_unchanged(temp_db) -> None:
    _seed_prices(temp_db, days=10)
    assert source_fingerprint(temp_db) == source_fingerprint(temp_db)


# ==================================================== 三、串行锁

def test_shared_lock_path_is_stable() -> None:
    """锁路径必须基于正式数据库路径，稳定不随机。"""
    from app.config import settings

    path_a = shared_lock_path()
    path_b = shared_lock_path(settings.database_path)
    assert path_a == path_b
    assert path_a.name == ".validation_write.lock"
    assert path_a.parent == Path(settings.database_path).resolve().parent


def test_run_with_write_lock_serializes(tmp_path) -> None:
    """同一把锁下的执行必须串行。"""
    order: list[str] = []

    def work(name: str, delay: float) -> str:
        order.append(f"{name}-start")
        time.sleep(delay)
        order.append(f"{name}-end")
        return name

    results: list[str] = []
    threads = [
        threading.Thread(
            target=lambda n=n, d=d: results.append(
                run_with_write_lock(work, n, d, lock_dir=tmp_path)
            )
        )
        for n, d in (("a", 0.15), ("b", 0.05))
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 2
    assert order[0].endswith("-start") and order[1].endswith("-end")
    assert order[2].endswith("-start") and order[3].endswith("-end")


def test_run_with_write_lock_releases_on_exception(tmp_path) -> None:
    def boom():
        raise ValueError("boom")

    with pytest.raises(ValueError):
        run_with_write_lock(boom, lock_dir=tmp_path)
    assert run_with_write_lock(lambda: "ok", lock_dir=tmp_path) == "ok"


# ==================================================== 多进程共享锁

def _process_worker(lock_dir: str, tag: str, delay: float, queue) -> None:
    """子进程 worker：持有共享锁，记录进入/离开顺序。"""
    from pathlib import Path as _P

    from app.validation.concurrency import run_with_write_lock as _lock

    def work() -> str:
        queue.put(f"{tag}-enter")
        time.sleep(delay)
        queue.put(f"{tag}-exit")
        return tag

    try:
        _lock(work, lock_dir=_P(lock_dir), timeout=60.0)
    except Exception as exc:  # noqa: BLE001
        queue.put(f"{tag}-error:{type(exc).__name__}")


@pytest.mark.skipif(os.name != "nt" and not hasattr(os, "fork"),
                    reason="需要支持多进程的 Python 环境")
def test_multiprocess_shared_lock(tmp_path) -> None:
    """两个独立 Python 进程共享同一锁文件，必须串行。"""
    ctx = mp.get_context("spawn")
    queue = ctx.Queue()
    lock_dir = tmp_path / "lockdir"
    lock_dir.mkdir(parents=True, exist_ok=True)

    procs = [
        ctx.Process(target=_process_worker,
                    args=(str(lock_dir), tag, delay, queue))
        for tag, delay in (("P1", 0.6), ("P2", 0.2))
    ]
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join(timeout=120)

    events = []
    while not queue.empty():
        events.append(queue.get())

    assert len(events) == 4, f"事件不全：{events}"
    tags = [e.split("-")[0] for e in events]
    kinds = [e.split("-")[1] for e in events]
    # 串行：前两个事件必须是同一进程的 enter + exit
    assert tags[0] == tags[1], f"不同进程交错执行：{events}"
    assert kinds[0] == "enter" and kinds[1] == "exit"
    assert tags[2] == tags[3]
    assert kinds[2] == "enter" and kinds[3] == "exit"
    assert {tags[0], tags[2]} == {"P1", "P2"}


def test_lock_file_created_in_stable_location(tmp_path) -> None:
    """锁文件必须落在指定目录，不是随机临时目录。"""
    target = tmp_path / "lockroot"
    target.mkdir(parents=True, exist_ok=True)
    run_with_write_lock(lambda: 1, lock_dir=target)
    lock_file = target / ".validation_write.lock"
    assert lock_file.exists(), "锁文件未在稳定位置创建"
