"""完整刷新观察池历史前复权数据。

用法：
    .venv\\Scripts\\python.exe scripts\\refresh_adjusted_prices.py
    .venv\\Scripts\\python.exe scripts\\refresh_adjusted_prices.py --code 510300
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
from app.data.processors.task_status import refresh_task_status  # noqa: E402
from app.database.db import get_pool_codes, init_db  # noqa: E402
from app.logging_config import setup_logging  # noqa: E402

logger = logging.getLogger("phase1b1.refresh")


def _codes(codes: list[str] | None) -> list[str]:
    selected = codes or get_pool_codes()
    if not selected:
        raise SystemExit("观察池为空，无法刷新复权快照")
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description="完整刷新 ETF 前复权历史快照")
    parser.add_argument("--code", action="append", help="只刷新指定代码，可重复")
    parser.add_argument("--limit", type=int, default=0, help="仅刷新前 N 只，0 表示全部")
    parser.add_argument("--timeout", type=int, default=settings.fetch_timeout_seconds)
    args = parser.parse_args()

    setup_logging("phase1b1_refresh.log")
    init_db()
    codes = _codes(args.code)
    if args.limit and args.limit > 0:
        codes = codes[: args.limit]

    collector = AkshareCollector(timeout_seconds=args.timeout, max_retries=settings.fetch_max_retries)
    result = refresh_adjusted_prices(codes, AkshareAdjustedProvider(collector))
    task = refresh_task_status(result)
    payload = json.dumps(
        {**result.as_dict(), "task_status": task},
        ensure_ascii=False,
        indent=2,
        default=str,
    )
    output = settings.data_dir / f"adjustment_refresh_summary_run{result.run_id}.json"
    output.write_text(payload, encoding="utf-8")
    (settings.data_dir / "adjustment_refresh_summary.json").write_text(payload, encoding="utf-8")
    logger.info("前复权刷新结束：%s", json.dumps(result.as_dict(), ensure_ascii=False, default=str))
    print(
        f"run_id={result.run_id} status={task['status']} total={result.total_codes} "
        f"success={result.success_codes} partial={result.partial_codes} "
        f"empty={result.empty_codes} failed={result.failed_codes} "
        f"rows_updated={result.rows_updated} exit_code={task['exit_code']} summary={output}"
    )
    return int(task["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
