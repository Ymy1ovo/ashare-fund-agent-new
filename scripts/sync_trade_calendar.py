"""同步 A 股交易日历到 SQLite。

用法：
    .venv\\Scripts\\python.exe scripts\\sync_trade_calendar.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402
from app.data.collectors.akshare_collector import AkshareCollector  # noqa: E402
from app.data.processors.normalize import parse_date  # noqa: E402
from app.database.db import get_trade_calendar, init_db, replace_trade_calendar  # noqa: E402
from app.logging_config import setup_logging  # noqa: E402

logger = logging.getLogger("phase2.calendar")


def main() -> int:
    setup_logging("phase2_calendar.log")
    init_db()
    collector = AkshareCollector(
        timeout_seconds=settings.fetch_timeout_seconds,
        max_retries=settings.fetch_max_retries,
    )
    df = collector.fetch_trade_calendar()
    if df.empty or "trade_date" not in df.columns:
        logger.error("交易日历接口返回空数据或字段异常：%s", list(df.columns))
        return 1
    dates = [d.isoformat() for value in df["trade_date"] if (d := parse_date(value)) is not None]
    count = replace_trade_calendar(dates)
    stored = get_trade_calendar()
    logger.info("交易日历写入/确认 %d 条，数据库共 %d 条", count, len(stored))
    print(f"calendar_rows={count} database_rows={len(stored)} first={stored[0] if stored else '-'} last={stored[-1] if stored else '-'}")
    return 0 if stored else 1


if __name__ == "__main__":
    raise SystemExit(main())
