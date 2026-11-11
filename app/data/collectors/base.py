"""采集器公共工具：独立进程硬超时、有限重试与异常日志。

设计要点：
1. AKShare 内部通常不允许调用方传入超时，线程超时只能放弃等待，无法终止请求。
2. 因此每次调用在独立 spawn 子进程中执行；超时后 terminate/join，确认进程结束。
3. 全局信号量限制同时进行的采集进程数，默认 1。
4. 只有确认上一个子进程已结束后才允许重试，避免超时请求叠加。
"""
from __future__ import annotations

import logging
import multiprocessing
import queue
import threading
import time
import traceback
from typing import Any, Callable

from app.config import settings

logger = logging.getLogger(__name__)


class DataFetchError(RuntimeError):
    """数据源调用失败，保留接口名称与最后一次异常信息。"""


class FetchTimeoutError(DataFetchError):
    """采集超时，且对应子进程已被终止。"""


# 线程信号量限制同一 Python 进程内并发启动的采集子进程数量。
_FETCH_SEMAPHORE = threading.BoundedSemaphore(max(1, settings.fetch_max_concurrency))


def _worker_entry(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    result_queue: Any,
) -> None:
    """子进程入口：把结果或异常序列化后放回队列。"""
    try:
        result_queue.put(("ok", func(*args, **kwargs)))
    except BaseException as exc:  # noqa: BLE001 - 必须把异常带回父进程
        detail = f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=8)}"
        try:
            result_queue.put(("error", detail))
        except BaseException:
            # 连异常都无法回传时只能退出；父进程会根据空结果和 exitcode 报错。
            pass


def _stop_process(process: multiprocessing.Process) -> None:
    """先 terminate，必要时 kill；确保 join，避免僵尸/遗留请求。"""
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
    if process.is_alive():
        process.kill()
        process.join(timeout=5)


def _close_queue(result_queue: Any, *, cancel_join: bool = False) -> None:
    try:
        if cancel_join and hasattr(result_queue, "cancel_join_thread"):
            result_queue.cancel_join_thread()
        result_queue.close()
        result_queue.join_thread()
    except Exception:  # noqa: BLE001 - 清理阶段不能掩盖原始异常
        logger.debug("关闭进程队列失败", exc_info=True)


def run_in_subprocess(
    func: Callable[..., Any],
    *args: Any,
    description: str,
    timeout_seconds: float | None = None,
    **kwargs: Any,
) -> Any:
    """在独立 spawn 子进程中执行调用；超时后终止进程再抛错。"""
    timeout = float(timeout_seconds or settings.fetch_timeout_seconds)
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue(maxsize=1)
    process = context.Process(
        target=_worker_entry,
        args=(func, args, kwargs, result_queue),
        name=f"fetch-{description[:40]}",
        daemon=True,
    )

    with _FETCH_SEMAPHORE:
        process.start()
        logger.info("子进程已启动：%s，pid=%s，超时=%.1fs", description, process.pid, timeout)
        try:
            try:
                status, payload = result_queue.get(timeout=timeout)
            except queue.Empty:
                if process.is_alive():
                    _stop_process(process)
                    raise FetchTimeoutError(
                        f"{description} 超时（>{timeout:.1f}s），已终止子进程 pid={process.pid}"
                    )
                raise DataFetchError(
                    f"{description} 子进程未返回结果且已退出，exitcode={process.exitcode}"
                )
            except (EOFError, OSError) as exc:
                raise DataFetchError(
                    f"{description} 子进程通道异常（exitcode={process.exitcode}）：{type(exc).__name__}: {exc}"
                ) from exc
            finally:
                if process.is_alive():
                    process.join(timeout=5)
                _stop_process(process)
                _close_queue(result_queue, cancel_join=not process.is_alive())
        except BaseException:
            _stop_process(process)
            _close_queue(result_queue, cancel_join=True)
            raise

    if status == "ok":
        return payload
    raise DataFetchError(f"{description} 子进程执行失败：{payload}")


def fetch_with_retry(
    func: Callable[..., Any],
    *args: Any,
    description: str,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
    backoff_seconds: float = 2.0,
    **kwargs: Any,
) -> Any:
    """执行数据源调用；失败后有限重试，且每次重试前旧子进程已结束。"""
    retries = settings.fetch_max_retries if max_retries is None else max_retries
    attempts = max(1, int(retries) + 1)
    last_error: BaseException | None = None

    for attempt in range(1, attempts + 1):
        try:
            logger.info("调用数据源：%s（第 %d/%d 次）", description, attempt, attempts)
            return run_in_subprocess(
                func,
                *args,
                description=description,
                timeout_seconds=timeout_seconds,
                **kwargs,
            )
        except DataFetchError as exc:
            last_error = exc
            logger.warning("数据源调用失败：%s；第 %d/%d 次", exc, attempt, attempts)
            if attempt < attempts:
                # 到这里时 run_in_subprocess 已完成 terminate/join，不会叠加未结束请求。
                time.sleep(backoff_seconds * attempt)

    raise DataFetchError(f"{description} 在 {attempts} 次尝试后仍失败：{last_error}") from last_error
