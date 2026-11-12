"""多验证任务并发安全性验证（阶段3A.2.1.2）。

区分两件事：
1. 计算并发：每个任务在独立 SQLite 副本上跑，天然隔离；
2. 写入并发：SQLite 单写者模型，需要串行化或 busy_timeout 保护。

本模块用「写入锁 + busy_timeout」实现安全并发，并把串行写入显式记录下来，
不掩盖 "database is locked"。
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

# 进程内写锁：保证同一进程的验证写入串行
_WRITE_LOCK = threading.Lock()
# 跨进程文件锁（多个 Python 进程共享同一个 DB 时使用）
_LOCK_FILE_NAME = ".validation_write.lock"


class ConcurrencyError(RuntimeError):
    """并发验证无法安全执行。"""


@dataclass
class ConcurrentTask:
    """一个并发验证任务的记录。"""

    task_id: str
    params: dict
    validation_id: str | None = None
    strategy_version: str | None = None
    input_hash: str | None = None
    data_fingerprint: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    duration: float | None = None
    status: str = "pending"
    error_message: str | None = None
    database_integrity: str | None = None
    result_isolation: bool | None = None
    result: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "params": self.params,
            "validation_id": self.validation_id,
            "strategy_version": self.strategy_version,
            "input_hash": self.input_hash,
            "data_fingerprint": self.data_fingerprint,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "status": self.status,
            "error_message": self.error_message,
            "database_integrity": self.database_integrity,
            "result_isolation": self.result_isolation,
        }


def _now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def run_with_write_lock(func: Callable, *args, lock_dir: Path | None = None,
                        timeout: float = 120.0, **kwargs):
    """带进程内锁 + 跨进程文件锁执行写操作。"""
    with _WRITE_LOCK:
        if lock_dir is not None:
            lock_path = Path(lock_dir) / _LOCK_FILE_NAME
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            deadline = time.time() + timeout
            handle = open(lock_path, "a+b")
            try:
                locked = False
                while time.time() < deadline:
                    try:
                        if os.name == "nt":
                            import msvcrt
                            handle.seek(0)
                            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        locked = True
                        break
                    except OSError:
                        time.sleep(0.05)
                if not locked:
                    raise ConcurrencyError(
                        f"获取文件锁超时（{timeout}s）：{lock_path}"
                    )
                try:
                    return func(*args, **kwargs)
                finally:
                    try:
                        if os.name == "nt":
                            import msvcrt
                            handle.seek(0)
                            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                    except OSError:
                        pass
            finally:
                handle.close()
        return func(*args, **kwargs)


def _make_single_task(
    task_id: str,
    overrides: dict,
    *,
    lock_dir: Path,
    serializer: Callable | None = None,
) -> tuple[ConcurrentTask, Callable]:
    """构造一个任务的执行函数（延迟执行）。"""
    task = ConcurrentTask(task_id=task_id, params=dict(overrides))

    def execute() -> ConcurrentTask:
        from app.config import settings
        from app.validation.config import ValidationConfig
        from app.validation.runner import ValidationError, run_validation

        task.start_time = _now()
        started = time.time()
        try:
            cfg = ValidationConfig(**overrides)
            cfg.validate()
            if serializer is not None:
                result = serializer(cfg)
            else:
                result = run_with_write_lock(
                    run_validation, cfg, lock_dir=lock_dir,
                )
            task.validation_id = result.validation_id
            task.strategy_version = cfg.strategy_version
            # 必须取「验证记录里的 input_hash」——它包含 config + ETF 池 + 数据指纹，
            # 而不是单独的市场数据指纹（后者同一份行情下必然相同，不能区分参数）
            from app.validation.storage import get_validation

            record = get_validation(result.validation_id) or {}
            task.input_hash = record.get("input_hash")
            task.data_fingerprint = getattr(result, "data_fingerprint", {}).get("sha256")
            task.status = result.status
            task.result = {
                "conclusion": result.conclusion,
                "etf_count": len(result.codes),
                "is_days": result.split.get("is_days"),
                "oos_days": result.split.get("oos_days"),
                "fingerprint": getattr(result, "data_fingerprint", {}).get("sha256"),
            }
        except ValidationError as exc:
            task.status = "failed"
            task.error_message = f"ValidationError: {str(exc)[:200]}"
        except Exception as exc:  # noqa: BLE001 并发任务允许失败但必须记录
            task.status = "failed"
            task.error_message = f"{type(exc).__name__}: {str(exc)[:200]}"
            task.result["traceback"] = traceback.format_exc()[-600:]
        finally:
            task.end_time = _now()
            task.duration = round(time.time() - started, 3)
        return task

    return task, execute


def run_concurrent_tasks(
    task_specs: list[dict],
    *,
    workdir: Path | None = None,
) -> dict:
    """并发执行多个验证任务。

    task_specs: [{"task_id": str, "overrides": dict}, ...]
    """
    from app.config import settings

    root = Path(workdir or tempfile.mkdtemp(prefix="concurrency_"))
    root.mkdir(parents=True, exist_ok=True)
    lock_dir = root / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)

    tasks: list[ConcurrentTask] = []
    runners: list[Callable] = []
    for spec in task_specs:
        task, execute = _make_single_task(
            spec["task_id"], spec.get("overrides", {}), lock_dir=lock_dir,
        )
        tasks.append(task)
        runners.append(execute)

    threads: list[threading.Thread] = []
    results: list[ConcurrentTask] = []

    def worker(fn: Callable) -> None:
        try:
            results.append(fn())
        except Exception as exc:  # noqa: BLE001
            # 极端情况：execute 自身异常
            tasks[0].error_message = str(exc)[:200]

    started = time.time()
    for runner in runners:
        thread = threading.Thread(target=lambda fn=runner: results.append(fn()))
        threads.append(thread)
        thread.start()
    for thread in threads:
        thread.join()
    elapsed = round(time.time() - started, 3)

    # 数据库完整性检查
    db_path = Path(settings.database_path)
    integrity = "unknown"
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    except Exception as exc:  # noqa: BLE001
        integrity = f"error: {exc}"

    # 唯一性与隔离检查
    ids = [task.validation_id for task in results if task.validation_id]
    unique_ids = len(set(ids)) == len(ids)
    # 同参数任务指纹应一致、不同参数任务指纹应不同
    same_param_hashes = [
        (task.params, task.input_hash) for task in results
    ]
    hash_consistency = _check_hash_consistency(results)

    for task in results:
        task.database_integrity = integrity
        task.result_isolation = unique_ids and hash_consistency["consistent"]


    payload = {
        "task_count": len(task_specs),
        "elapsed_seconds": elapsed,
        "database_integrity": integrity,
        "validation_ids_unique": unique_ids,
        "validation_ids": ids,
        "hash_consistency": hash_consistency,
        "serialized_writes": True,
        "write_model": "process-internal thread lock + cross-process file lock",
        "tasks": [
            task.as_dict() for task in sorted(results, key=lambda t: t.task_id)
        ],
    }
    shutil.rmtree(root, ignore_errors=True)
    return payload


def _check_hash_consistency(tasks: list[ConcurrentTask]) -> dict:
    """校验 input_hash 与数据指纹的隔离性。

    - 相同参数 → input_hash 必须相同（可复现）
    - 不同参数 → input_hash 必须不同（不串参数）
    - 同一份行情 → data_fingerprint 必须相同（不串数据）
    """
    problems: list[str] = []
    by_params: dict[str, set] = {}
    for task in tasks:
        key = json.dumps(task.params, sort_keys=True, default=str)
        if task.input_hash:
            by_params.setdefault(key, set()).add(task.input_hash)
    for key, hashes in by_params.items():
        if len(hashes) > 1:
            problems.append(f"同参数任务出现不同 input_hash：{key} -> {hashes}")

    all_hashes = [task.input_hash for task in tasks if task.input_hash]
    if len(by_params) == len(tasks) and len(set(all_hashes)) != len(all_hashes):
        problems.append("不同参数任务出现相同 input_hash")

    fingerprints = {t.data_fingerprint for t in tasks if t.data_fingerprint}
    if len(fingerprints) > 1:
        problems.append(f"任务间数据指纹不一致：{fingerprints}")

    return {"consistent": not problems, "problems": problems}
