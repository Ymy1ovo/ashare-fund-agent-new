"""增量更新观察池行情。

用法：
    .venv\\Scripts\\python.exe scripts\\sync_data.py
    .venv\\Scripts\\python.exe scripts\\sync_data.py --code 510300
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402
from app.data.collectors.akshare_collector import AkshareCollector  # noqa: E402
from app.data.processors.adjustment import AkshareAdjustedProvider, refresh_adjusted_prices  # noqa: E402
from app.data.processors.ingest import AkshareHistoryProvider, run_ingest  # noqa: E402
from app.data.processors.pool_export import export_pool_csv  # noqa: E402
from app.data.processors.task_status import combined_sync_status  # noqa: E402
from app.database.db import get_pool_codes, init_db  # noqa: E402
from app.logging_config import setup_logging  # noqa: E402

logger = logging.getLogger("phase1b.sync")


def _codes(codes: list[str] | None) -> list[str]:
    selected = codes or get_pool_codes()
    if not selected:
        raise SystemExit("观察池为空，无法同步；请先构建观察池")
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description="按数据库最新日期增量同步 ETF 行情")
    parser.add_argument("--code", action="append", help="只同步指定代码，可重复")
    parser.add_argument("--limit", type=int, default=0, help="仅同步前 N 只，0 表示全部")
    parser.add_argument("--timeout", type=int, default=settings.fetch_timeout_seconds)
    args = parser.parse_args()

    setup_logging("phase1b_sync.log")
    init_db()
    codes = _codes(args.code)
    if args.limit and args.limit > 0:
        codes = codes[: args.limit]

    collector = AkshareCollector(timeout_seconds=args.timeout, max_retries=settings.fetch_max_retries)
    # 第一步：只增量更新原始 OHLC，不拼接任何 qfq。
    result = run_ingest(codes, AkshareHistoryProvider(collector), mode="sync")
    output = settings.data_dir / f"sync_summary_run{result.run_id}.json"
    payload = json.dumps(result.as_dict(), ensure_ascii=False, indent=2, default=str)
    output.write_text(payload, encoding="utf-8")
    # 同时保留最近一次摘要，便于看板和人工快速查看；历史运行另有带 run_id 的文件与数据库记录。
    (settings.data_dir / "sync_summary.json").write_text(payload, encoding="utf-8")

    # 第二步：对同一批基金执行完整历史 qfq 刷新，避免新旧调整基准混用。
    adjustment = refresh_adjusted_prices(codes, AkshareAdjustedProvider(collector))
    adjustment_payload = json.dumps(adjustment.as_dict(), ensure_ascii=False, indent=2, default=str)
    adjustment_path = settings.data_dir / f"adjustment_refresh_summary_run{adjustment.run_id}.json"
    adjustment_path.write_text(adjustment_payload, encoding="utf-8")
    (settings.data_dir / "adjustment_refresh_summary.json").write_text(adjustment_payload, encoding="utf-8")

    pool_rows = export_pool_csv(settings.etf_pool_path)
    overall = combined_sync_status(result, adjustment)
    combined = {
        "raw_run_id": result.run_id,
        "adjustment_run_id": adjustment.run_id,
        "raw": result.as_dict(),
        "adjustment": adjustment.as_dict(),
        "overall": overall,
    }
    combined_path = settings.data_dir / "sync_combined_summary.json"
    combined_path.write_text(
        json.dumps(combined, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    logger.info("增量同步结束：%s", json.dumps(result.as_dict(), ensure_ascii=False, default=str))
    logger.info("复权刷新结束：%s", json.dumps(adjustment.as_dict(), ensure_ascii=False, default=str))
    logger.info("整体任务状态：%s", json.dumps(overall, ensure_ascii=False))
    print(
        f"raw_run_id={result.run_id} raw_status={result.status} total={result.total_codes} "
        f"success={result.success_codes} empty={result.empty_codes} failed={result.failed_codes} "
        f"rows_written={result.rows_written} raw_summary={output}"
    )
    print(
        f"adjustment_run_id={adjustment.run_id} status={adjustment.status} "
        f"success={adjustment.success_codes} partial={adjustment.partial_codes} "
        f"empty={adjustment.empty_codes} failed={adjustment.failed_codes} "
        f"rows_updated={adjustment.rows_updated} adjustment_summary={adjustment_path} "
        f"pool_csv_rows={pool_rows}"
    )
    print(
        f"overall_status={overall['status']} exit_code={overall['exit_code']} "
        f"combined_summary={combined_path}"
    )
    return int(overall["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
