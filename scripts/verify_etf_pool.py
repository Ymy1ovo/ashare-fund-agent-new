"""对已生成的 ETF 观察池做独立真实性复核。

检查项：
1. 代码是否存在于 ETF 实时列表或场内基金列表。
2. 名称是否与数据源完全一致。
3. 近 40 天是否有真实行情，最新收盘价是否为正。
4. 跟踪指数、基金类型、成立/上市日期是否完整。
5. 六类基金覆盖与数量是否符合阶段目标。

用法：
    .venv\\Scripts\\python.exe scripts\\verify_etf_pool.py
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402
from app.data.collectors.akshare_collector import AkshareCollector  # noqa: E402
from app.data.processors.normalize import (  # noqa: E402
    clean_history,
    latest_valid_bar,
    normalize_code,
    parse_date,
)
from app.data.validators.etf_validator import CATEGORIES  # noqa: E402
from app.logging_config import setup_logging  # noqa: E402

logger = logging.getLogger("phase1a.verify_pool")


def main() -> int:
    setup_logging("phase1a_verify_pool.log")
    if not settings.etf_pool_path.exists():
        logger.error("观察池文件不存在：%s", settings.etf_pool_path)
        return 1

    pool = pd.read_csv(settings.etf_pool_path, dtype={"code": str})
    collector = AkshareCollector(
        timeout_seconds=settings.fetch_timeout_seconds,
        max_retries=settings.fetch_max_retries,
    )
    spot = collector.fetch_etf_spot()
    rank = collector.fetch_exchange_fund_rank()
    spot_map = {normalize_code(row["代码"]): row for row in spot.to_dict("records")}
    rank_map = {normalize_code(row["基金代码"]): row for row in rank.to_dict("records")}
    today = date.today()
    start = (today - timedelta(days=40)).strftime("%Y%m%d")

    errors: list[str] = []
    checked: list[dict] = []
    for row in pool.to_dict("records"):
        code = normalize_code(row.get("code"))
        source_row = spot_map.get(code) or rank_map.get(code)
        if source_row is None:
            errors.append(f"{code} 未在实时列表或场内基金列表中找到")
            continue
        source_name = str(source_row.get("名称") or source_row.get("基金简称") or "").strip()
        if source_name != str(row["name"]).strip():
            errors.append(f"{code} 名称不一致：池={row['name']!r}，源={source_name!r}")
        if not row.get("tracking_index") or pd.isna(row.get("tracking_index")):
            errors.append(f"{code} 跟踪指数为空")
        if not row.get("fund_type") or pd.isna(row.get("fund_type")):
            errors.append(f"{code} 基金类型为空")
        established = parse_date(row.get("established_date"))
        listing = parse_date(row.get("listing_date"))
        if established and listing and established > listing:
            errors.append(f"{code} 成立日期晚于上市日期")

        try:
            history = collector.fetch_etf_history(code, start_date=start)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{code} 近期行情读取失败：{type(exc).__name__}: {exc}")
            continue
        if history.empty:
            errors.append(f"{code} 近期行情为空")
            continue
        cleaned = clean_history(history, today=today)
        if cleaned.missing_columns or cleaned.data.empty:
            errors.append(f"{code} 近期行情清洗后无有效记录")
            continue
        latest, latest_close = latest_valid_bar(history, today=today)
        if latest is None or latest_close is None:
            errors.append(f"{code} 无法取得同一有效行的最新日期/收盘价")
            continue
        if latest < today - timedelta(days=10):
            errors.append(f"{code} 最近交易日 {latest} 超过10天")
        if latest_close <= 0:
            errors.append(f"{code} 最新收盘价非正：{latest_close}")
        checked.append(
            {
                "code": code,
                "name": source_name,
                "latest_trade_date": latest.isoformat(),
                "latest_close": latest_close,
                "window_rows": int(len(cleaned.data)),
            }
        )
        logger.info("复核通过 %s %s，最近 %s 收盘 %.4f", code, source_name, latest, latest_close)

    category_counts = pool["category"].value_counts().to_dict()
    missing_categories = [category for category in CATEGORIES if category_counts.get(category, 0) == 0]
    if missing_categories:
        errors.append(f"分类缺失：{missing_categories}")
    if not 30 <= len(pool) <= 50:
        errors.append(f"数量超出 30~50：{len(pool)}")
    if len(checked) != len(pool):
        errors.append(f"仅完成 {len(checked)}/{len(pool)} 只的实时行情复核")

    result = {
        "checked_at": pd.Timestamp.now().isoformat(),
        "pool_count": int(len(pool)),
        "checked_count": len(checked),
        "category_counts": {str(k): int(v) for k, v in category_counts.items()},
        "errors": errors,
        "ok": not errors,
        "details": checked,
    }
    output = settings.data_dir / "etf_pool_realtime_verification.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("复核结果：%s", json.dumps({k: result[k] for k in ("ok", "pool_count", "checked_count", "errors")}, ensure_ascii=False))
    logger.info("复核明细：%s", output)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
