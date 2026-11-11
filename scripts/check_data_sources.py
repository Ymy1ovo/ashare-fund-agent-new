"""阶段1A/1B数据源测试：逐接口真实调用并记录调用与质量结果。

用法：
    .venv\\Scripts\\python.exe scripts\\check_data_sources.py
"""
from __future__ import annotations

import importlib.metadata
import json
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402
from app.data.collectors.akshare_collector import AkshareCollector  # noqa: E402
from app.data.collectors.base import DataFetchError  # noqa: E402
from app.data.processors.normalize import dataframe_preview, json_safe  # noqa: E402
from app.data.validators.source_quality import assess_quality  # noqa: E402
from app.database.db import init_db, save_interface_test  # noqa: E402
from app.logging_config import setup_logging  # noqa: E402

logger = logging.getLogger("phase1b.data_sources")

RESULT_PATH = settings.data_dir / "data_source_test_results.json"
MARKDOWN_PATH = settings.report_dir / "phase1B_data_source_results.md"


def _date_range(df: pd.DataFrame) -> tuple[str | None, str | None, str | None]:
    """自动寻找日期列，返回最小/最大日期与实际使用的列名。"""
    candidates = [col for col in df.columns if "日期" in str(col)]
    for col in candidates:
        parsed = pd.to_datetime(df[col], errors="coerce").dropna()
        if not parsed.empty:
            return parsed.min().date().isoformat(), parsed.max().date().isoformat(), str(col)
    return None, None, None


def _run_case(
    name: str,
    function_name: str,
    params: dict[str, Any],
    call: Callable[[], pd.DataFrame],
    *,
    date_column: str | None,
    price_column: str | None,
    time_series: bool,
) -> dict[str, Any]:
    started = datetime.now()
    logger.info("开始测试：%s", name)
    record: dict[str, Any] = {
        "interface_name": name,
        "function_name": function_name,
        "params": params,
        "tested_at": started.isoformat(timespec="seconds"),
    }
    try:
        df = call()
        if not isinstance(df, pd.DataFrame):
            raise DataFetchError(f"返回类型不是 DataFrame：{type(df).__name__}")
        start_date, end_date, actual_date_column = _date_range(df)
        quality_status, quality_issues = assess_quality(
            df,
            date_column=actual_date_column or date_column,
            price_column=price_column,
            time_series=time_series,
        )
        record.update(
            {
                "status": "success",
                "quality_status": quality_status,
                "quality_issues": quality_issues,
                "row_count": int(len(df)),
                "column_count": int(len(df.columns)),
                "columns": [str(col) for col in df.columns],
                "dtypes": {str(k): str(v) for k, v in df.dtypes.items()},
                "start_date": start_date,
                "end_date": end_date,
                "null_cells": int(df.isna().sum().sum()),
                "sample": dataframe_preview(df, rows=3),
                "duration_seconds": round((datetime.now() - started).total_seconds(), 2),
                "error_message": None,
            }
        )
        if df.empty:
            record["status"] = "empty"
            record["quality_status"] = "failed"
            record["quality_issues"] = ["empty_dataframe"]
            record["error_message"] = "接口调用成功但返回 0 行"
        logger.info(
            "完成测试：%s，调用=%s，质量=%s，行数=%s，问题=%s",
            name,
            record["status"],
            quality_status,
            record["row_count"],
            quality_issues,
        )
    except Exception as exc:  # noqa: BLE001 - 测试脚本需要记录所有失败
        logger.exception("接口测试失败：%s", name)
        record.update(
            {
                "status": "failed",
                "quality_status": "failed",
                "quality_issues": [f"{type(exc).__name__}: {exc}"],
                "row_count": 0,
                "column_count": 0,
                "columns": [],
                "dtypes": {},
                "start_date": None,
                "end_date": None,
                "null_cells": None,
                "sample": [],
                "duration_seconds": round((datetime.now() - started).total_seconds(), 2),
                "error_message": f"{type(exc).__name__}: {exc}",
            }
        )
    save_interface_test(record)
    return record


def main() -> int:
    setup_logging("phase1b_data_sources.log")
    init_db()
    collector = AkshareCollector(
        timeout_seconds=settings.fetch_timeout_seconds,
        max_retries=settings.fetch_max_retries,
    )
    today_str = datetime.now().strftime("%Y%m%d")
    start = "20240101"

    cases = [
        (
            "ETF 基础信息列表（实时行情）",
            "fund_etf_spot_em",
            {},
            collector.fetch_etf_spot,
            {"date_column": "数据日期", "price_column": "最新价", "time_series": False},
        ),
        (
            "ETF 历史日线行情",
            "fund_etf_hist_em",
            {"symbol": "510300", "period": "daily", "start_date": start, "end_date": today_str},
            lambda: collector.fetch_etf_history("510300", start_date=start, end_date=today_str),
            {"date_column": "日期", "price_column": "收盘", "time_series": True},
        ),
        (
            "A股指数历史行情",
            "index_zh_a_hist",
            {"symbol": "000300", "period": "daily", "start_date": start, "end_date": today_str},
            lambda: collector.fetch_index_history("000300", start_date=start, end_date=today_str),
            {"date_column": "日期", "price_column": "收盘", "time_series": True},
        ),
        (
            "场外指数基金基础信息",
            "fund_info_index_em",
            {"symbol": "沪深指数", "indicator": "被动指数型"},
            lambda: collector.fetch_index_fund_info("沪深指数", "被动指数型"),
            {"date_column": "日期", "price_column": "单位净值", "time_series": False},
        ),
        (
            "场外指数基金历史净值",
            "fund_open_fund_info_em",
            {"symbol": "110020", "indicator": "单位净值走势"},
            lambda: collector.fetch_open_fund_nav("110020"),
            {"date_column": "净值日期", "price_column": "单位净值", "time_series": True},
        ),
        (
            "场内基金基础列表（补充验证债券ETF）",
            "fund_exchange_rank_em",
            {},
            collector.fetch_exchange_fund_rank,
            {"date_column": "日期", "price_column": "单位净值", "time_series": False},
        ),
    ]

    records = [
        _run_case(
            name,
            function_name,
            params,
            call,
            date_column=quality["date_column"],
            price_column=quality["price_column"],
            time_series=quality["time_series"],
        )
        for name, function_name, params, call, quality in cases
    ]
    summary = {
        "tested_at": datetime.now().isoformat(timespec="seconds"),
        "python_version": sys.version,
        "akshare_version": importlib.metadata.version("akshare"),
        "total": len(records),
        "call_success": sum(1 for r in records if r["status"] == "success"),
        "empty": sum(1 for r in records if r["status"] == "empty"),
        "failed": sum(1 for r in records if r["status"] == "failed"),
        "quality_passed": sum(1 for r in records if r["quality_status"] == "passed"),
        "quality_warning": sum(1 for r in records if r["quality_status"] == "warning"),
        "quality_failed": sum(1 for r in records if r["quality_status"] == "failed"),
        "records": records,
    }
    RESULT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=json_safe), encoding="utf-8")
    MARKDOWN_PATH.write_text(render_markdown(summary), encoding="utf-8")

    logger.info(
        "接口测试汇总：调用成功=%d，空数据=%d，失败=%d；质量通过=%d，警告=%d，不合格=%d",
        summary["call_success"],
        summary["empty"],
        summary["failed"],
        summary["quality_passed"],
        summary["quality_warning"],
        summary["quality_failed"],
    )
    logger.info("原始结果：%s", RESULT_PATH)
    logger.info("可读结果：%s", MARKDOWN_PATH)
    return 0 if summary["failed"] == 0 else 1


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# 阶段1B 数据源接口测试结果",
        "",
        f"- 测试时间：{summary['tested_at']}",
        f"- Python：{summary['python_version'].splitlines()[0]}",
        f"- AKShare：{summary['akshare_version']}",
        f"- 调用结果：成功 {summary['call_success']} / 空数据 {summary['empty']} / 失败 {summary['failed']}",
        f"- 质量结果：通过 {summary['quality_passed']} / 警告 {summary['quality_warning']} / 不合格 {summary['quality_failed']}",
        "",
        "| 接口 | 函数 | 调用状态 | 质量状态 | 行数 | 列数 | 数据起止 | 耗时(s) |",
        "| --- | --- | --- | --- | ---: | ---: | --- | ---: |",
    ]
    for record in summary["records"]:
        lines.append(
            "| {name} | `{fn}` | {status} | {quality} | {rows} | {cols} | {start} ~ {end} | {secs} |".format(
                name=record["interface_name"],
                fn=record["function_name"],
                status=record["status"],
                quality=record["quality_status"],
                rows=record["row_count"],
                cols=record["column_count"],
                start=record["start_date"] or "-",
                end=record["end_date"] or "-",
                secs=record["duration_seconds"],
            )
        )
    lines += ["", "## 返回字段与质量问题", ""]
    for record in summary["records"]:
        lines.append(f"### {record['interface_name']}")
        lines.append("")
        lines.append(f"- 参数：`{json.dumps(record['params'], ensure_ascii=False)}`")
        lines.append(f"- 调用状态：`{record['status']}`；质量状态：`{record['quality_status']}`")
        lines.append(f"- 行数：{record['row_count']}；字段数：{record['column_count']}")
        lines.append(f"- 字段：{', '.join(record['columns']) if record['columns'] else '无'}")
        if record.get("quality_issues"):
            lines.append(f"- 质量问题：{'; '.join(record['quality_issues'])}")
        if record.get("error_message"):
            lines.append(f"- 异常：{record['error_message']}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
