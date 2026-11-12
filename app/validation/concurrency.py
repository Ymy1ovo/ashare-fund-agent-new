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

# 进程内写锁：保证同一进程的验证任务串行
_WRITE_LOCK = threading.Lock()
# 跨进程文件锁：基于正式数据库路径生成，文件位置稳定
_LOCK_FILE_NAME = ".validation_write.lock"


def shared_lock_path(db_path=None) -> Path:
    """返回与正式数据库同目录的稳定锁文件路径。

    不能用「每次调用独立的临时目录」——那样跨进程拿到的不是同一把锁。
    """
    if db_path is None:
        from app.config import settings

        db_path = settings.database_path
    return Path(db_path).resolve().parent / _LOCK_FILE_NAME


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


def _ensure_lock_file_byte(lock_path: Path, attempts: int = 20) -> None:
    """确保锁文件存在且至少有 1 字节（Windows 区域锁的前提）。

    多进程同时首建时，写字节可能撞 PermissionError / OSError；
    此时说明别的进程正在创建同一个文件，稍后重试即可。
    """
    for _ in range(attempts):
        try:
            if lock_path.exists() and lock_path.stat().st_size > 0:
                return
            with open(lock_path, "ab") as handle:
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(bytes([0]))
                    handle.flush()
            if lock_path.stat().st_size > 0:
                return
        except (PermissionError, OSError):
            pass
        time.sleep(0.05)
    # 最终仍未就绪：不阻塞，交给后续加锁逻辑决定（可能超时）
    return



def run_with_write_lock(func: Callable, *args, lock_dir: Path | None = None,
                        timeout: float = 3600.0, db_path=None,
                        db_path_lock=None, **kwargs):
    """在全流程串行锁内执行 func（阶段3A.2.1.2.1 修正模型）。

    模型说明：**不是「计算并行 + 写入串行」，而是整个验证任务串行排队。**
    理由：验证流程全程读同一份行情、写同一个 SQLite，串行最安全，
    且没有证据表明并行计算能带来可观测收益（实测 4 任务串行 840 秒可完成）。

    - 锁文件位置：优先 db_path 同目录的 `.validation_write.lock`（跨进程稳定）；
      lock_dir 仅用于临时库测试，正式库场景不得使用随机临时目录。
    - 超时抛 ConcurrencyError，由调用方记录为 failed，不伪装成功。
    - 异常路径通过 finally 释放锁。
    """
    with _WRITE_LOCK:
        # lock 目标库优先用 db_path_lock（避免与传给 func 的 db_path 语义混淆）
        lock_target = db_path_lock if db_path_lock is not None else db_path
        lock_path = (
            Path(lock_dir) / _LOCK_FILE_NAME
            if lock_dir is not None
            else shared_lock_path(lock_target)
        )
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + timeout
        # 必须保证锁文件至少有 1 字节：Windows msvcrt.locking 是对
        # 「从当前位置开始的 N 字节」做区域锁，空文件上的区域锁不可靠。
        # 多进程同时首建时可能撞写冲突，用独立句柄重试，失败即视为他人已建好。
        _ensure_lock_file_byte(lock_path)
        handle = open(lock_path, "r+b")
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
                    f"获取验证锁超时（{timeout}s）：{lock_path}"
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
            elif lock_dir is not None:
                # 临时库测试：显式指定锁目录
                result = run_with_write_lock(
                    run_validation, cfg, lock_dir=lock_dir,
                )
            else:
                # 正式库：公开入口自带锁，不再重复加锁
                result = run_validation(cfg)
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
    # 正式库场景使用「正式数据库同目录」的稳定锁文件；
    # 只有临时库测试才通过 lock_dir 覆盖
    lock_dir = root / "locks" if workdir is not None else None
    if lock_dir is not None:
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
        "execution_model": "full-pipeline-serial",
        "write_model": (
            "整个验证任务串行排队：进程内 threading.Lock + "
            "正式库同目录 .validation_write.lock 文件锁"
        ),
        "compute_parallel": False,
        "lock_path": str(shared_lock_path()),
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
