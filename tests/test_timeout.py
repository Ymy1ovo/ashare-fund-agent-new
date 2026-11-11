from __future__ import annotations

import time

import pytest

from app.data.collectors.base import FetchTimeoutError, run_in_subprocess


def _sleep_and_return(seconds: float, value: str) -> str:
    time.sleep(seconds)
    return value


def test_subprocess_returns_result() -> None:
    assert (
        run_in_subprocess(_sleep_and_return, 0.05, "ok", description="normal", timeout_seconds=20)
        == "ok"
    )


def test_timeout_reports_terminated_child() -> None:
    started = time.monotonic()
    with pytest.raises(FetchTimeoutError) as exc_info:
        run_in_subprocess(_sleep_and_return, 30, "never", description="timeout-test", timeout_seconds=1)
    elapsed = time.monotonic() - started
    message = str(exc_info.value)
    assert "已终止子进程" in message
    assert "pid=" in message
    assert elapsed < 10
