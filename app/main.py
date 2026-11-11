"""FastAPI 应用入口。"""
from __future__ import annotations

import json
import re
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from app.config import settings
from app.database.db import (
    count_rows,
    get_connection,
    get_current_adjustment_snapshot,
    get_etf_exists,
    get_etf_name,
    get_market_data_summary,
    get_market_price_count,
    get_market_prices,
    get_recent_adjustment_runs,
    get_recent_sync_runs,
    init_db,
)
from app.database.indicators import (
    INDICATOR_COLUMNS,
    get_indicator_overview,
    get_indicator_ranking,
    get_indicator_rows,
    get_indicator_run,
    get_latest_indicator,
    get_latest_version,
)
from app.logging_config import setup_logging

_CODE_RE = re.compile(r"^\d{6}$")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    setup_logging("api.log")
    init_db()
    yield


app = FastAPI(
    title="A股基金量化分析 Agent",
    version="0.2.1",
    description="阶段1B.1：ETF观察池、历史行情持久化、调整快照与行情查询",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, Any]:
    """启动与数据库健康检查。"""
    try:
        result = {
            "status": "ok",
            "database": str(settings.database_path),
            "etf_pool_count": count_rows("etf_pool"),
            "data_source_test_count": count_rows("data_source_tests"),
            "price_record_count": count_rows("etf_daily_prices"),
            "sync_run_count": count_rows("sync_runs"),
            "adjustment_snapshot_count": count_rows("etf_adjustment_snapshots"),
            "adjustment_run_count": count_rows("adjustment_runs"),
            "indicator_run_count": count_rows("indicator_runs"),
            "indicator_row_count": count_rows("etf_indicator_daily"),
        }
    except Exception as exc:  # noqa: BLE001 - 健康检查需要返回真实错误
        return JSONResponse(
            status_code=503,
            content={"status": "error", "error": f"{type(exc).__name__}: {exc}"},
        )
    return result


@app.get("/api/etf-pool")
def etf_pool() -> list[dict[str, Any]]:
    """返回初始 ETF 观察池。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT code, name, category, fund_type, tracking_index, established_date, "
            "listing_date, last_trade_date, history_rows, latest_price, data_source, status "
            "FROM etf_pool ORDER BY category, code"
        ).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/data-source-tests")
def data_source_tests() -> list[dict[str, Any]]:
    """返回最近的接口测试记录，调用状态与质量状态分开。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT interface_name, function_name, status, quality_status, quality_issues_json, "
            "row_count, start_date, end_date, error_message, tested_at "
            "FROM data_source_tests ORDER BY id DESC LIMIT 50"
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            item["quality_issues"] = json.loads(item.pop("quality_issues_json") or "[]")
        except json.JSONDecodeError:
            item["quality_issues"] = []
        result.append(item)
    return result


@app.get("/api/market-data/summary")
def market_data_summary() -> dict[str, Any]:
    """历史行情覆盖、入库数量、最近同步与异常统计。"""
    return get_market_data_summary()


@app.get("/api/market-data/{code}")
def market_data(
    code: str,
    start_date: str | None = Query(default=None, description="开始日期 YYYY-MM-DD，含当天"),
    end_date: str | None = Query(default=None, description="结束日期 YYYY-MM-DD，含当天"),
    limit: int = Query(default=500, ge=1, le=2000, description="单次返回条数上限"),
    offset: int = Query(default=0, ge=0, description="分页偏移"),
) -> dict[str, Any]:
    """按代码查询历史行情，必须支持日期范围和条数限制。"""
    if not _CODE_RE.match(code):
        raise HTTPException(status_code=400, detail="基金代码必须是六位数字")

    for label, value in (("start_date", start_date), ("end_date", end_date)):
        if value is None:
            continue
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"{label} 必须是 YYYY-MM-DD") from exc
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date 不能晚于 end_date")

    exists = get_etf_exists(code)
    total = get_market_price_count(code, start_date=start_date, end_date=end_date)
    if not exists and total == 0:
        raise HTTPException(status_code=404, detail="未找到该 ETF 或其历史行情")
    records = get_market_prices(
        code,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )
    return {
        "code": code,
        "name": get_etf_name(code),
        "start_date": start_date,
        "end_date": end_date,
        "total": total,
        "limit": limit,
        "offset": offset,
        "records": records,
    }


@app.get("/api/sync/runs")
def sync_runs(limit: int = Query(default=10, ge=1, le=100)) -> list[dict[str, Any]]:
    """最近原始行情同步运行记录。"""
    return get_recent_sync_runs(limit)


@app.get("/api/adjustment/runs")
def adjustment_runs(limit: int = Query(default=10, ge=1, le=100)) -> list[dict[str, Any]]:
    """最近完整前复权快照刷新记录。"""
    return get_recent_adjustment_runs(limit)


def _validate_indicator_dates(start_date: str | None, end_date: str | None) -> None:
    for label, value in (("start_date", start_date), ("end_date", end_date)):
        if value is None:
            continue
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"{label} 必须是 YYYY-MM-DD") from exc
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date 不能晚于 end_date")


def _indicator_payload(code: str, rows: list[dict[str, Any]], indicators: list[str] | None) -> dict[str, Any]:
    version = rows[0]["calculation_version"]
    snapshot_id = rows[0]["adjustment_snapshot_id"]
    current = get_current_adjustment_snapshot(code)
    current_id = int(current["id"]) if current else None
    run = get_indicator_run(rows[0]["run_id"])
    summary = json.loads(run["summary_json"]) if run and run.get("summary_json") else {}
    quality = json.loads(run["quality_json"]) if run and run.get("quality_json") else {}
    config = json.loads(run["indicator_config"]) if run and run.get("indicator_config") else {}
    selected = indicators or INDICATOR_COLUMNS
    data = []
    for row in rows:
        item = {"trade_date": row["trade_date"], "adjusted_close": row.get("adjusted_close")}
        item.update({column: row.get(column) for column in selected})
        item.update(
            {
                "quality_status": row.get("quality_status"),
                "quality_reasons": row.get("quality_reasons"),
                "price_status": row.get("price_status"),
                "trade_status": row.get("trade_status"),
            }
        )
        data.append(item)
    return {
        "etf_code": code,
        "name": get_etf_name(code),
        "status": run["status"] if run else None,
        "version": version,
        "calculation_version": version,
        "snapshot_id": snapshot_id,
        "snapshot_is_current": current_id == snapshot_id,
        "stale": current_id != snapshot_id,
        "parameters": config,
        "summary": summary,
        "quality": quality,
        "coverage": quality.get("coverage", {}),
        "start_date": rows[0]["trade_date"],
        "end_date": rows[-1]["trade_date"],
        "total": len(data),
        "data": data,
    }


@app.get("/api/indicators/overview")
def indicators_overview() -> dict[str, Any]:
    """指标计算概览。"""
    rows = get_indicator_overview()
    status_counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get("quality_status") or "unknown")
        status_counts[value] = status_counts.get(value, 0) + 1
    return {
        "total": len(rows),
        "stale": sum(1 for row in rows if row.get("stale")),
        "quality_counts": status_counts,
        "items": rows,
    }


@app.get("/api/indicators/ranking")
def indicators_ranking(
    metric: str = Query(default="return_20d", description="排序指标"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=20, ge=1, le=100),
    version: str | None = Query(default=None),
) -> dict[str, Any]:
    """按指标排序；仅展示计算结果，不构成买卖建议。"""
    if metric not in INDICATOR_COLUMNS:
        raise HTTPException(status_code=400, detail=f"不支持的指标：{metric}")
    rows = get_indicator_ranking(metric, order=order, limit=limit, version=version)
    return {
        "metric": metric,
        "order": order,
        "limit": limit,
        "disclaimer": "仅按历史指标排序，不构成投资建议。",
        "items": [
            {
                "etf_code": row["etf_code"],
                "name": get_etf_name(row["etf_code"]),
                "trade_date": row["trade_date"],
                "value": row.get(metric),
                "version": row["calculation_version"],
                "snapshot_id": row["adjustment_snapshot_id"],
                "stale": row.get("stale"),
                "quality_status": row.get("quality_status"),
            }
            for row in rows
        ],
    }


@app.get("/api/indicators/{etf_code}")
def indicator_detail(
    etf_code: str,
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    indicators: str | None = Query(default=None, description="逗号分隔的指标列"),
    version: str | None = Query(default=None),
) -> dict[str, Any]:
    """读取已计算指标；不会在 API 内临时计算或伪造数据。"""
    if not _CODE_RE.match(etf_code):
        raise HTTPException(status_code=400, detail="基金代码必须是六位数字")
    _validate_indicator_dates(start_date, end_date)
    selected = [item.strip() for item in (indicators or "").split(",") if item.strip()] or None
    if selected:
        unknown = set(selected) - set(INDICATOR_COLUMNS)
        if unknown:
            raise HTTPException(status_code=400, detail=f"不支持的指标：{sorted(unknown)}")
    if not get_etf_exists(etf_code):
        raise HTTPException(status_code=404, detail="未找到该 ETF")
    rows = get_indicator_rows(
        etf_code, start_date=start_date, end_date=end_date, version=version
    )
    if not rows:
        base_rows = get_indicator_rows(etf_code, version=version)
        if not base_rows:
            raise HTTPException(status_code=404, detail="该 ETF 尚未计算指标，或指定版本不存在")
        raise HTTPException(status_code=404, detail="指定日期区间没有指标数据")
    return _indicator_payload(etf_code, rows, selected)


@app.get("/api/indicators/{etf_code}/latest")
def indicator_latest(etf_code: str) -> dict[str, Any]:
    if not _CODE_RE.match(etf_code):
        raise HTTPException(status_code=400, detail="基金代码必须是六位数字")
    if not get_etf_exists(etf_code):
        raise HTTPException(status_code=404, detail="未找到该 ETF")
    row = get_latest_indicator(etf_code)
    if not row:
        raise HTTPException(status_code=404, detail="该 ETF 尚未计算指标")
    return _indicator_payload(etf_code, [row], None)


# ---------------- 阶段3A：回测 API ----------------
@app.get("/api/backtests")
def backtest_list(limit: int = Query(default=20, ge=1, le=100)) -> list[dict[str, Any]]:
    """最近回测记录。"""
    from app.backtest.api import list_runs

    return list_runs(limit)


@app.get("/api/backtests/{run_id}")
def backtest_detail(run_id: str) -> dict[str, Any]:
    """回测元信息与结果摘要。"""
    from app.backtest.api import get_run

    payload = get_run(run_id)
    if not payload:
        raise HTTPException(status_code=404, detail="回测记录不存在")
    return payload


@app.get("/api/backtests/{run_id}/nav")
def backtest_nav(run_id: str) -> dict[str, Any]:
    from app.backtest.api import get_nav, get_run

    if not get_run(run_id):
        raise HTTPException(status_code=404, detail="回测记录不存在")
    return {"run_id": run_id, "items": get_nav(run_id)}


@app.get("/api/backtests/{run_id}/trades")
def backtest_trades(run_id: str) -> dict[str, Any]:
    from app.backtest.api import get_run, get_trades

    if not get_run(run_id):
        raise HTTPException(status_code=404, detail="回测记录不存在")
    return {"run_id": run_id, "items": get_trades(run_id)}


@app.get("/api/backtests/{run_id}/orders")
def backtest_orders(run_id: str) -> dict[str, Any]:
    from app.backtest.api import get_orders, get_run

    if not get_run(run_id):
        raise HTTPException(status_code=404, detail="回测记录不存在")
    return {"run_id": run_id, "items": get_orders(run_id)}


@app.get("/api/backtests/{run_id}/positions")
def backtest_positions(
    run_id: str,
    trade_date: str | None = Query(default=None, description="YYYY-MM-DD，缺省返回全部"),
) -> dict[str, Any]:
    from app.backtest.api import get_positions, get_run

    if not get_run(run_id):
        raise HTTPException(status_code=404, detail="回测记录不存在")
    return {"run_id": run_id, "items": get_positions(run_id, trade_date)}
