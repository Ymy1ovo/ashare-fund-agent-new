"""启动冒烟测试：真实启动 FastAPI 与 Streamlit，检查 HTTP 可用后关闭。

用法：
    .venv\\Scripts\\python.exe scripts\\smoke_test_servers.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = PROJECT_ROOT / "logs" / "server_smoke_test.log"
RESULT_PATH = PROJECT_ROOT / "logs" / "server_smoke_test.json"


def _wait_http(url: str, timeout_seconds: int = 40) -> tuple[bool, str]:
    deadline = time.time() + timeout_seconds
    last_error = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                return True, response.read().decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001 - 轮询启动状态
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(1)
    return False, last_error


def _stop(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def main() -> int:
    results: dict[str, object] = {}
    log_lines: list[str] = []
    processes: list[subprocess.Popen[str]] = []

    try:
        api = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8765",
                "--log-level",
                "info",
            ],
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        processes.append(api)
        ok, body = _wait_http("http://127.0.0.1:8765/health")
        results["fastapi_health"] = {"ok": ok, "body": body}
        log_lines.append(f"FastAPI /health ok={ok} body={body}")

        pool_ok, pool_body = _wait_http("http://127.0.0.1:8765/api/etf-pool")
        pool_count = 0
        if pool_ok:
            try:
                pool_count = len(json.loads(pool_body))
            except json.JSONDecodeError:
                pool_ok = False
        results["fastapi_etf_pool"] = {"ok": pool_ok, "count": pool_count}
        log_lines.append(f"FastAPI /api/etf-pool ok={pool_ok} count={pool_count}")

        summary_ok, summary_body = _wait_http("http://127.0.0.1:8765/api/market-data/summary")
        summary_payload: dict[str, object] = {}
        if summary_ok:
            try:
                summary_payload = json.loads(summary_body)
            except json.JSONDecodeError:
                summary_ok = False
        results["fastapi_market_summary"] = {"ok": summary_ok, "body": summary_payload}
        adjustment_info = summary_payload.get("adjustment", {})
        log_lines.append(
            "FastAPI /api/market-data/summary "
            f"ok={summary_ok} records={summary_payload.get('total_records')} "
            f"ingested={summary_payload.get('etf_ingested')} "
            f"snapshots={adjustment_info.get('current_snapshot_etfs')} "
            f"mixed={adjustment_info.get('mixed_snapshot_etfs')}"
        )

        detail_ok, detail_body = _wait_http(
            "http://127.0.0.1:8765/api/market-data/510300"
            "?start_date=2026-11-01&end_date=2026-11-09&limit=5"
        )
        detail_count = 0
        detail_payload: dict[str, object] = {}
        if detail_ok:
            try:
                detail_payload = json.loads(detail_body)
                detail_count = len(detail_payload.get("records", []))
            except json.JSONDecodeError:
                detail_ok = False
        results["fastapi_market_detail"] = {
            "ok": detail_ok,
            "records_returned": detail_count,
            "body": {
                "total": detail_payload.get("total"),
                "limit": detail_payload.get("limit"),
                "start_date": detail_payload.get("start_date"),
                "end_date": detail_payload.get("end_date"),
            },
        }
        log_lines.append(
            f"FastAPI /api/market-data/510300 ok={detail_ok} records={detail_count} "
            f"total={detail_payload.get('total')}"
        )

        sync_ok, sync_body = _wait_http("http://127.0.0.1:8765/api/sync/runs?limit=1")
        sync_count = 0
        if sync_ok:
            try:
                sync_count = len(json.loads(sync_body))
            except json.JSONDecodeError:
                sync_ok = False
        results["fastapi_sync_runs"] = {"ok": sync_ok, "count": sync_count}
        log_lines.append(f"FastAPI /api/sync/runs ok={sync_ok} count={sync_count}")

        adj_ok, adj_body = _wait_http("http://127.0.0.1:8765/api/adjustment/runs?limit=1")
        adj_count = 0
        if adj_ok:
            try:
                adj_count = len(json.loads(adj_body))
            except json.JSONDecodeError:
                adj_ok = False
        results["fastapi_adjustment_runs"] = {"ok": adj_ok, "count": adj_count}
        log_lines.append(f"FastAPI /api/adjustment/runs ok={adj_ok} count={adj_count}")

        ind_ok, ind_body = _wait_http("http://127.0.0.1:8765/api/indicators/overview")
        ind_total = 0
        if ind_ok:
            try:
                ind_total = int(json.loads(ind_body).get("total", 0))
            except (json.JSONDecodeError, TypeError, ValueError):
                ind_ok = False
        results["fastapi_indicator_overview"] = {"ok": ind_ok, "count": ind_total}
        log_lines.append(f"FastAPI /api/indicators/overview ok={ind_ok} count={ind_total}")

        ind_detail_ok, ind_detail_body = _wait_http(
            "http://127.0.0.1:8765/api/indicators/510300"
            "?start_date=2026-11-01&end_date=2026-11-09&indicators=return_1d,ma20,rsi6"
        )
        ind_rows = 0
        if ind_detail_ok:
            try:
                payload = json.loads(ind_detail_body)
                ind_rows = len(payload.get("data", []))
                if payload.get("stale") is not False:
                    ind_detail_ok = False
            except json.JSONDecodeError:
                ind_detail_ok = False
        results["fastapi_indicator_detail"] = {"ok": ind_detail_ok, "rows": ind_rows}
        log_lines.append(f"FastAPI /api/indicators/510300 ok={ind_detail_ok} rows={ind_rows}")

        streamlit = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                "dashboard/app.py",
                "--server.headless",
                "true",
                "--server.port",
                "8766",
                "--browser.gatherUsageStats",
                "false",
            ],
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        processes.append(streamlit)
        st_ok, st_body = _wait_http("http://127.0.0.1:8766/_stcore/health")
        results["streamlit_health"] = {"ok": st_ok, "body": st_body}
        log_lines.append(f"Streamlit /_stcore/health ok={st_ok} body={st_body}")

        if api.poll() is not None:
            output = api.stdout.read() if api.stdout else ""
            results["fastapi_exit_output"] = output[-3000:]
            log_lines.append(f"FastAPI 提前退出：{output[-3000:]}")
        if streamlit.poll() is not None:
            output = streamlit.stdout.read() if streamlit.stdout else ""
            results["streamlit_exit_output"] = output[-3000:]
            log_lines.append(f"Streamlit 提前退出：{output[-3000:]}")
    finally:
        for process in processes:
            if process.poll() is None:
                _stop(process)

    checks = {
        "fastapi_health": bool(results.get("fastapi_health", {}).get("ok")),
        "fastapi_etf_pool": bool(results.get("fastapi_etf_pool", {}).get("ok"))
        and results["fastapi_etf_pool"].get("count", 0) > 0,
        "fastapi_market_summary": bool(results.get("fastapi_market_summary", {}).get("ok"))
        and results["fastapi_market_summary"].get("body", {}).get("total_records", 0) > 0
        and results["fastapi_market_summary"]
        .get("body", {})
        .get("adjustment", {})
        .get("current_snapshot_etfs", 0)
        > 0,
        "fastapi_market_detail": bool(results.get("fastapi_market_detail", {}).get("ok"))
        and results["fastapi_market_detail"].get("records_returned", 0) > 0,
        "fastapi_sync_runs": bool(results.get("fastapi_sync_runs", {}).get("ok"))
        and results["fastapi_sync_runs"].get("count", 0) > 0,
        "fastapi_adjustment_runs": bool(results.get("fastapi_adjustment_runs", {}).get("ok"))
        and results["fastapi_adjustment_runs"].get("count", 0) > 0,
        "fastapi_indicator_overview": bool(results.get("fastapi_indicator_overview", {}).get("ok"))
        and results["fastapi_indicator_overview"].get("count", 0) > 0,
        "fastapi_indicator_detail": bool(results.get("fastapi_indicator_detail", {}).get("ok"))
        and results["fastapi_indicator_detail"].get("rows", 0) > 0,
        "streamlit_health": bool(results.get("streamlit_health", {}).get("ok")),
    }
    results["checks"] = checks
    results["ok"] = all(checks.values())
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    RESULT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n".join(log_lines))
    print(f"结果文件：{RESULT_PATH}")
    return 0 if results["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
