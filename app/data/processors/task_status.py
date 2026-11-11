"""统一任务状态与退出码。

约定：
- success: 所有目标 ETF 成功，退出码 0。
- partial: 有成功更新，但存在失败/空数据/部分覆盖，退出码 2。
- failed: 整体失败或没有任何有效更新，退出码 1。
"""
from __future__ import annotations

from typing import Any

EXIT_SUCCESS = 0
EXIT_FAILED = 1
EXIT_PARTIAL = 2


def exit_code_for_status(status: str) -> int:
    if status == "success":
        return EXIT_SUCCESS
    if status == "partial":
        return EXIT_PARTIAL
    return EXIT_FAILED


def refresh_task_status(result: Any) -> dict[str, Any]:
    """复权刷新结果 → 统一状态。"""
    total = int(getattr(result, "total_codes", 0))
    success = int(getattr(result, "success_codes", 0))
    partial = int(getattr(result, "partial_codes", 0))
    failed = int(getattr(result, "failed_codes", 0))
    empty = int(getattr(result, "empty_codes", 0))
    if total == 0:
        status = "failed"
    elif success == total and failed == 0 and empty == 0 and partial == 0:
        status = "success"
    elif success + partial == 0:
        status = "failed"
    else:
        status = "partial"
    return {
        "status": status,
        "exit_code": exit_code_for_status(status),
        "total_codes": total,
        "success_codes": success,
        "partial_codes": partial,
        "failed_codes": failed,
        "empty_codes": empty,
    }


def combined_sync_status(raw_result: Any, adjustment_result: Any) -> dict[str, Any]:
    """原始行情同步 + 复权刷新 → 统一整体状态。

    原始行情成功不能掩盖复权刷新失败；复权刷新成功也不能掩盖原始行情失败。
    """
    raw_status = str(getattr(raw_result, "status", "failed"))
    adjustment_status = str(getattr(adjustment_result, "status", "failed"))
    raw_success = int(getattr(raw_result, "success_codes", 0))
    raw_total = int(getattr(raw_result, "total_codes", 0))
    raw_failed = int(getattr(raw_result, "failed_codes", 0))
    raw_empty = int(getattr(raw_result, "empty_codes", 0))
    adjustment_success = int(getattr(adjustment_result, "success_codes", 0))
    adjustment_partial = int(getattr(adjustment_result, "partial_codes", 0))
    adjustment_failed = int(getattr(adjustment_result, "failed_codes", 0))
    adjustment_empty = int(getattr(adjustment_result, "empty_codes", 0))
    adjustment_total = int(getattr(adjustment_result, "total_codes", 0))

    raw_ok = raw_total > 0 and raw_success == raw_total and raw_failed == 0 and raw_empty == 0
    adjustment_ok = (
        adjustment_total > 0
        and adjustment_success == adjustment_total
        and adjustment_failed == 0
        and adjustment_empty == 0
        and adjustment_partial == 0
    )
    if raw_ok and adjustment_ok:
        status = "success"
    elif raw_success + adjustment_success + adjustment_partial == 0:
        status = "failed"
    else:
        status = "partial"

    return {
        "status": status,
        "exit_code": exit_code_for_status(status),
        "raw_status": raw_status,
        "adjustment_status": adjustment_status,
        "raw_success_codes": raw_success,
        "raw_failed_codes": raw_failed,
        "raw_empty_codes": raw_empty,
        "adjustment_success_codes": adjustment_success,
        "adjustment_partial_codes": adjustment_partial,
        "adjustment_failed_codes": adjustment_failed,
        "adjustment_empty_codes": adjustment_empty,
    }
