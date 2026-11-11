"""复权口径实测：比较同一 ETF 的原始、前复权、后复权日线。

用法：
    .venv\\Scripts\\python.exe scripts\\check_adjustment.py
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402
from app.data.collectors.akshare_collector import AkshareCollector  # noqa: E402
from app.data.processors.normalize import clean_history, latest_valid_bar  # noqa: E402
from app.logging_config import setup_logging  # noqa: E402

logger = logging.getLogger("phase1b.adjustment")
CODES = ("510300", "511010", "513100")


def main() -> int:
    setup_logging("phase1b_adjustment.log")
    collector = AkshareCollector(timeout_seconds=settings.fetch_timeout_seconds, max_retries=settings.fetch_max_retries)
    today = date.today()
    start = "20240101"
    result: dict[str, object] = {"tested_at": today.isoformat(), "codes": {}}
    for code in CODES:
        item: dict[str, object] = {}
        for label, adjust in (("raw", ""), ("qfq", "qfq"), ("hfq", "hfq")):
            try:
                df = collector.fetch_etf_history(code, start_date=start, adjust=adjust)
                cleaned = clean_history(df, today=today)
                latest, latest_close = latest_valid_bar(df, today=today)
                first = cleaned.data.iloc[0] if not cleaned.data.empty else None
                item[label] = {
                    "rows": int(len(cleaned.data)),
                    "first_date": first["trade_date"].date().isoformat() if first is not None else None,
                    "first_close": float(first["close"]) if first is not None else None,
                    "last_date": latest.isoformat() if latest else None,
                    "last_close": latest_close,
                }
                logger.info("%s %s：%s 行，%s %.4f -> %s %.4f", code, label, len(cleaned.data), item[label]["first_date"], item[label]["first_close"] or 0, item[label]["last_date"], latest_close or 0)
            except Exception as exc:  # noqa: BLE001
                item[label] = {"error": f"{type(exc).__name__}: {exc}"}
                logger.exception("%s %s 获取失败", code, label)
        result["codes"][code] = item

    output = settings.data_dir / "adjustment_check.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("复权口径结果：%s", output)
    return 0 if all("error" not in value for item in result["codes"].values() for value in item.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
