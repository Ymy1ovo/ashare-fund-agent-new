from __future__ import annotations

from types import SimpleNamespace

from app.data.processors.task_status import (
    EXIT_FAILED,
    EXIT_PARTIAL,
    EXIT_SUCCESS,
    combined_sync_status,
    exit_code_for_status,
    refresh_task_status,
)


def _adj(**kwargs):
    defaults = {
        "status": "success",
        "total_codes": 3,
        "success_codes": 3,
        "partial_codes": 0,
        "failed_codes": 0,
        "empty_codes": 0,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _raw(**kwargs):
    defaults = {
        "status": "success",
        "total_codes": 3,
        "success_codes": 3,
        "failed_codes": 0,
        "empty_codes": 0,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_exit_code_for_status() -> None:
    assert exit_code_for_status("success") == EXIT_SUCCESS
    assert exit_code_for_status("partial") == EXIT_PARTIAL
    assert exit_code_for_status("failed") == EXIT_FAILED


def test_refresh_all_success() -> None:
    result = refresh_task_status(_adj())
    assert result["status"] == "success"
    assert result["exit_code"] == 0


def test_refresh_partial_failure() -> None:
    result = refresh_task_status(_adj(status="partial", success_codes=2, failed_codes=1))
    assert result["status"] == "partial"
    assert result["exit_code"] == 2


def test_refresh_empty_is_not_success() -> None:
    result = refresh_task_status(_adj(status="partial", success_codes=2, empty_codes=1))
    assert result["status"] == "partial"
    assert result["exit_code"] == 2


def test_refresh_all_failed() -> None:
    result = refresh_task_status(_adj(status="failed", success_codes=0, failed_codes=3))
    assert result["status"] == "failed"
    assert result["exit_code"] == 1


def test_combined_success() -> None:
    result = combined_sync_status(_raw(), _adj())
    assert result["status"] == "success"
    assert result["exit_code"] == 0


def test_combined_raw_success_but_adjustment_partial() -> None:
    result = combined_sync_status(
        _raw(), _adj(status="partial", success_codes=2, partial_codes=1)
    )
    assert result["status"] == "partial"
    assert result["exit_code"] == 2
    assert result["raw_status"] == "success"
    assert result["adjustment_status"] == "partial"


def test_combined_adjustment_failure_does_not_report_success() -> None:
    result = combined_sync_status(
        _raw(), _adj(status="failed", success_codes=0, failed_codes=3)
    )
    assert result["status"] == "partial"
    assert result["exit_code"] == 2


def test_combined_no_valid_update_is_failed() -> None:
    result = combined_sync_status(
        _raw(status="failed", success_codes=0, failed_codes=3),
        _adj(status="failed", success_codes=0, failed_codes=3),
    )
    assert result["status"] == "failed"
    assert result["exit_code"] == 1
