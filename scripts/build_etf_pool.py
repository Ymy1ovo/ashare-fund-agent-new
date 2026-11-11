"""构建并验证阶段1A初始 ETF 观察池。

真实数据源：
- AKShare `fund_etf_spot_em`：ETF 实时列表、名称、最新价
- AKShare `fund_exchange_rank_em`：场内基金列表、基金类型、成立日期（补充债券ETF）
- AKShare `fund_etf_hist_em`：历史日线，取首个交易日与最近交易日
- 东方财富基金档案 F10：跟踪标的、成立日期

用法：
    .venv\\Scripts\\python.exe scripts\\build_etf_pool.py
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402
from app.data.collectors.akshare_collector import AkshareCollector  # noqa: E402
from app.data.processors.etf_seeds import ETF_SEEDS  # noqa: E402
from app.data.processors.normalize import (  # noqa: E402
    clean_history,
    latest_valid_bar,
    normalize_code,
    parse_date,
)
from app.data.validators.etf_validator import validate_pool  # noqa: E402
from app.database.db import init_db, replace_etf_pool  # noqa: E402
from app.logging_config import setup_logging  # noqa: E402

logger = logging.getLogger("phase1a.etf_pool")

POOL_COLUMNS = [
    "code",
    "name",
    "category",
    "fund_type",
    "tracking_index",
    "established_date",
    "listing_date",
    "listing_date_source",
    "last_trade_date",
    "history_rows",
    "latest_price",
    "data_source",
    "source_tested_at",
    "status",
]


def _build_maps(
    spot: pd.DataFrame, rank: pd.DataFrame, names: pd.DataFrame
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    spot_map: dict[str, dict[str, Any]] = {}
    for record in spot.to_dict("records"):
        code = normalize_code(record.get("代码"))
        if code:
            spot_map[code] = record

    rank_map: dict[str, dict[str, Any]] = {}
    for record in rank.to_dict("records"):
        code = normalize_code(record.get("基金代码"))
        if code:
            rank_map[code] = record

    name_map: dict[str, dict[str, Any]] = {}
    for record in names.to_dict("records"):
        code = normalize_code(record.get("基金代码"))
        if code:
            name_map[code] = record
    return spot_map, rank_map, name_map


def build_pool() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    collector = AkshareCollector(
        timeout_seconds=settings.fetch_timeout_seconds,
        max_retries=settings.fetch_max_retries,
    )
    now = datetime.now().isoformat(timespec="seconds")
    today = date.today()

    logger.info("拉取 ETF 实时列表")
    spot = collector.fetch_etf_spot()
    logger.info("拉取场内基金列表")
    rank = collector.fetch_exchange_fund_rank()
    logger.info("拉取基金名称/类型列表")
    names = collector.fetch_fund_name_list()
    spot_map, rank_map, name_map = _build_maps(spot, rank, names)
    logger.info("数据源列表：ETF实时=%d，场内基金=%d，全市场基金=%d", len(spot_map), len(rank_map), len(name_map))

    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    warnings: list[str] = []

    for seed in ETF_SEEDS:
        code = seed.code
        logger.info("验证 %s（%s）", code, seed.category)
        if code not in spot_map and code not in rank_map:
            failures.append({"code": code, "reason": "ETF实时列表和场内基金列表均未找到该代码"})
            continue

        spot_row = spot_map.get(code, {})
        rank_row = rank_map.get(code, {})
        name_row = name_map.get(code, {})
        name = str(spot_row.get("名称") or rank_row.get("基金简称") or name_row.get("基金简称") or "").strip()
        if not name:
            failures.append({"code": code, "reason": "数据源未返回基金名称"})
            continue

        fund_type = str(name_row.get("基金类型") or rank_row.get("类型") or "").strip()
        established = parse_date(rank_row.get("成立日期"))
        tracking_index = ""
        profile: dict[str, Any] = {}
        try:
            profile = collector.fetch_fund_profile(code)
            tracking_index = str(profile.get("tracking_index") or "").strip()
            established = parse_date(profile.get("established_date")) or established
            fund_type = str(profile.get("fund_type") or fund_type).strip()
        except Exception as exc:  # noqa: BLE001 - 单只基金失败不影响整个池
            warnings.append(f"{code} F10 档案读取失败：{type(exc).__name__}: {exc}")
            logger.warning("%s F10 档案读取失败：%s", code, exc)

        try:
            history = collector.fetch_etf_history(code, start_date="20000101")
        except Exception as exc:  # noqa: BLE001
            failures.append({"code": code, "reason": f"历史日线读取失败：{type(exc).__name__}: {exc}"})
            logger.warning("%s 历史日线读取失败：%s", code, exc)
            continue

        if history.empty:
            failures.append({"code": code, "reason": "历史日线为空"})
            continue
        cleaned = clean_history(history, today=today)
        if cleaned.missing_columns:
            failures.append({"code": code, "reason": f"历史日线缺字段：{cleaned.missing_columns}"})
            continue
        if cleaned.data.empty:
            failures.append({"code": code, "reason": "清洗后无有效历史日线"})
            continue

        first_date = cleaned.data.iloc[0]["trade_date"].date()
        last_date, latest_close = latest_valid_bar(history, today=today)
        if last_date is None or latest_close is None:
            failures.append({"code": code, "reason": "无法取得同一有效行的最新日期/收盘价"})
            continue
        if last_date < today - timedelta(days=45):
            failures.append({"code": code, "reason": f"最近交易日 {last_date} 超过45天，疑似停止交易"})
            continue

        source_parts = [
            "AKShare fund_etf_hist_em（日线/上市首日/最新收盘）",
            "东方财富基金档案F10（跟踪指数/成立日期）",
        ]
        if spot_row:
            source_parts.insert(0, "AKShare fund_etf_spot_em（仅名称核验）")
        else:
            source_parts.insert(0, "AKShare fund_exchange_rank_em（名称/成立日期）")

        record = {
            "code": code,
            "name": name,
            "category": seed.category,
            "fund_type": fund_type,
            "tracking_index": tracking_index,
            "established_date": established.isoformat() if established else "",
            "listing_date": first_date.isoformat(),
            # F10基本概况页不提供上市日期，用首个交易日作为可复核的替代口径，并明确标注。
            "listing_date_source": "AKShare fund_etf_hist_em 日线首个交易日",
            "last_trade_date": last_date.isoformat(),
            "history_rows": int(len(cleaned.data)),
            # 日期和收盘价来自同一行，且该行已经过排序、去重、无效值过滤。
            "latest_price": latest_close,
            "data_source": "；".join(source_parts),
            "source_tested_at": now,
            "status": "active",
        }
        records.append(record)
        logger.info(
            "通过 %s %s：类型=%s，跟踪=%s，上市首日=%s，最近=%s",
            code,
            name,
            fund_type or "空",
            tracking_index or "空",
            first_date,
            last_date,
        )

    validation = validate_pool(
        records,
        spot_codes=set(spot_map) | set(rank_map),
        min_count=30,
        max_count=50,
    )
    validation["warnings"].extend(warnings)
    validation["failures"] = failures
    validation["missing_tracking_index"] = [row["code"] for row in records if not row["tracking_index"]]
    validation["source_counts"] = {
        "spot_list": len(spot_map),
        "exchange_rank": len(rank_map),
        "fund_name_list": len(name_map),
    }
    return records, validation


def save_pool(records: list[dict[str, Any]]) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(records, columns=POOL_COLUMNS)
    df.to_csv(settings.etf_pool_path, index=False, encoding="utf-8-sig")
    replace_etf_pool(records)
    logger.info("观察池已写入：%s（%d 条），并同步到 SQLite", settings.etf_pool_path, len(records))


def main() -> int:
    setup_logging("phase1a_etf_pool.log")
    init_db()
    records, validation = build_pool()
    save_pool(records)

    validation_path = settings.data_dir / "etf_pool_validation.json"
    validation_path.write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("校验结果：%s", json.dumps(validation, ensure_ascii=False))
    if not validation["ok"]:
        logger.error("观察池校验未通过：%s", validation["errors"])
        return 1
    logger.info("观察池校验通过，共 %d 只", len(records))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
