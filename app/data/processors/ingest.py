"""历史行情与增量行情入库流程。

核心保证：
- 单只基金一个事务，失败不影响其他基金；
- 空数据不写库，不覆盖已有数据；
- UPSERT 保证重复运行不产生重复记录；
- 原始 OHLC 与前复权收盘价分开保存；
- 每次运行和每只基金都记录同步明细与质量状态。
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol, Sequence

import pandas as pd

from app.data.collectors.akshare_collector import AkshareCollector
from app.data.processors.market_data import (
    PreparedHistory,
    latest_record,
    prepare_raw_history,
    to_raw_price_records,
)
from app.database.db import (
    count_prices_for_code,
    finish_sync_run,
    get_latest_trade_date,
    get_price_source_map,
    save_sync_detail,
    start_sync_run,
    update_pool_market_stats,
    upsert_raw_daily_prices,
)

logger = logging.getLogger(__name__)


class HistoryProvider(Protocol):
    def fetch_history(
        self,
        code: str,
        start_date: str,
        end_date: str,
        adjust: str = "",
    ) -> pd.DataFrame: ...


class AkshareHistoryProvider:
    """真实 AKShare 行情提供者。"""

    def __init__(self, collector: AkshareCollector | None = None) -> None:
        self.collector = collector or AkshareCollector()

    def fetch_history(
        self,
        code: str,
        start_date: str,
        end_date: str,
        adjust: str = "",
    ) -> pd.DataFrame:
        return self.collector.fetch_etf_history(
            code,
            start_date=start_date,
            end_date=end_date,
            adjust=adjust,
        )


@dataclass
class IngestResult:
    run_id: int
    status: str
    total_codes: int
    success_codes: int = 0
    empty_codes: int = 0
    failed_codes: int = 0
    rows_fetched: int = 0
    rows_written: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "total_codes": self.total_codes,
            "success_codes": self.success_codes,
            "empty_codes": self.empty_codes,
            "failed_codes": self.failed_codes,
            "rows_fetched": self.rows_fetched,
            "rows_written": self.rows_written,
            "details": self.details,
        }


def _append_issue(prepared: PreparedHistory, issue: dict[str, Any], status: str = "warning") -> None:
    prepared.issues.append(issue)
    prepared.quality.issues.append(issue)
    rank = {"passed": 0, "warning": 1, "suspect": 2, "failed": 3}
    if rank.get(status, 1) > rank.get(prepared.quality.status, 0):
        prepared.quality.status = status


def _mark_source_conflicts(
    prepared: PreparedHistory,
    records: list[dict[str, Any]],
    existing: dict[str, dict[str, Any]],
) -> list[str]:
    """发现同一代码同日不同来源且价格不同：标记异常，不静默覆盖。"""
    conflict_dates: list[str] = []
    for record in records:
        old = existing.get(record["trade_date"])
        if not old:
            continue
        old_close = old.get("close")
        old_source = old.get("source")
        if old_source and old_source != record["source"] and old_close is not None:
            if abs(float(old_close) - float(record["close"])) > 1e-6:
                conflict_dates.append(record["trade_date"])
                record["quality_status"] = "suspect"
                note = f"source_price_conflict:{old_source}"
                record["quality_notes"] = (
                    f"{record['quality_notes']};{note}" if record.get("quality_notes") else note
                )
    if conflict_dates:
        _append_issue(
            prepared,
            {
                "type": "source_price_conflict",
                "severity": "critical",
                "message": f"发现 {len(conflict_dates)} 个交易日不同来源价格冲突",
                "count": len(conflict_dates),
                "examples": conflict_dates[:5],
            },
            status="suspect",
        )
    return conflict_dates


def _detail_base(run_id: int, code: str, started_at: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "code": code,
        "status": "failed",
        "rows_fetched": 0,
        "rows_written": 0,
        "coverage_start": None,
        "coverage_end": None,
        "quality_status": "failed",
        "quality_issues_json": "[]",
        "error_message": None,
        "started_at": started_at,
        "finished_at": None,
    }


def _ingest_one(
    code: str,
    *,
    run_id: int,
    provider: HistoryProvider,
    mode: str,
    today: date,
    db_path: Path | None,
) -> tuple[dict[str, Any], int, int]:
    """采集并写入单只基金；返回明细、抓取行数、写入行数。"""
    started_at = datetime.now().isoformat(timespec="seconds")
    detail = _detail_base(run_id, code, started_at)
    collected_at = started_at

    try:
        last_date = get_latest_trade_date(code, db_path) if mode == "sync" else None
        # 增量模式从已有最后日期开始（含当天，刷新可能未收盘的最后一条），无数据则全量。
        start_date = last_date.replace("-", "") if last_date else "20000101"
        end_date = today.strftime("%Y%m%d")
        raw = provider.fetch_history(code, start_date, end_date, "")
        if not isinstance(raw, pd.DataFrame):
            raise TypeError(f"provider 返回类型异常：{type(raw).__name__}")
        detail["rows_fetched"] = int(len(raw))

        # 原始行情同步只处理 OHLC；复权由 adjustment.refresh_adjusted_prices 完整刷新。
        prepared = prepare_raw_history(
            code,
            raw,
            source="AKShare fund_etf_hist_em(raw)",
            collected_at=collected_at,
            today=today,
        )
        detail["quality_status"] = prepared.quality_status
        detail["quality_issues_json"] = json.dumps(prepared.issues, ensure_ascii=False, default=str)

        if prepared.data.empty:
            detail["status"] = "empty"
            detail["finished_at"] = datetime.now().isoformat(timespec="seconds")
            logger.warning("%s 清洗后无有效行情，空数据不写库", code)
            return detail, detail["rows_fetched"], 0

        records = to_raw_price_records(prepared, source=prepared.source, collected_at=collected_at)
        existing = get_price_source_map(code, start_date=start_date, end_date=end_date, db_path=db_path)
        _mark_source_conflicts(prepared, records, existing)
        detail["quality_status"] = prepared.quality_status
        detail["quality_issues_json"] = json.dumps(prepared.issues, ensure_ascii=False, default=str)

        written = upsert_raw_daily_prices(records, db_path=db_path)
        total_count = count_prices_for_code(code, db_path)
        last_trade_date, latest_close = latest_record(prepared.data)
        if last_trade_date is not None and latest_close is not None:
            update_pool_market_stats(
                code,
                last_trade_date=last_trade_date,
                latest_price=latest_close,
                history_rows=total_count,
                db_path=db_path,
            )

        detail.update(
            {
                "status": "success",
                "rows_written": written,
                "coverage_start": prepared.coverage_start.isoformat() if prepared.coverage_start else None,
                "coverage_end": prepared.coverage_end.isoformat() if prepared.coverage_end else None,
                "finished_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
        logger.info(
            "%s 入库成功：抓取 %d 行，写入/更新 %d 行，覆盖 %s ~ %s，质量=%s",
            code,
            detail["rows_fetched"],
            written,
            detail["coverage_start"],
            detail["coverage_end"],
            prepared.quality_status,
        )
        return detail, detail["rows_fetched"], written
    except Exception as exc:  # noqa: BLE001 - 单只失败不影响其他基金
        detail["status"] = "failed"
        detail["error_message"] = f"{type(exc).__name__}: {exc}"
        detail["finished_at"] = datetime.now().isoformat(timespec="seconds")
        logger.exception("%s 入库失败", code)
        return detail, detail["rows_fetched"], 0


def run_ingest(
    codes: Sequence[str],
    provider: HistoryProvider,
    *,
    mode: str = "full",
    db_path: Path | None = None,
    today: date | None = None,
) -> IngestResult:
    """执行原始行情全量或增量入库。

    mode=full：从 20000101 开始获取原始行情；
    mode=sync：从数据库已有最后交易日开始获取原始行情；
    前复权不在此函数内拼接，必须由完整快照刷新任务独立完成。
    """
    if mode not in {"full", "sync"}:
        raise ValueError(f"不支持的入库模式：{mode}")
    ordered_codes = list(dict.fromkeys(str(code) for code in codes if str(code)))
    today = today or date.today()
    run_id = start_sync_run(mode, len(ordered_codes), db_path)
    result = IngestResult(run_id=run_id, status="running", total_codes=len(ordered_codes))
    started = time.monotonic()

    try:
        for code in ordered_codes:
            detail, fetched, written = _ingest_one(
                code,
                run_id=run_id,
                provider=provider,
                mode=mode,
                today=today,
                db_path=db_path,
            )
            save_sync_detail(detail, db_path)
            result.details.append(detail)
            result.rows_fetched += fetched
            result.rows_written += written
            if detail["status"] == "success":
                result.success_codes += 1
            elif detail["status"] == "empty":
                result.empty_codes += 1
            else:
                result.failed_codes += 1
    finally:
        failed_total = result.failed_codes + result.empty_codes
        if result.success_codes == 0:
            result.status = "failed"
        elif failed_total:
            result.status = "partial"
        else:
            result.status = "success"
        finish_sync_run(
            run_id,
            status=result.status,
            success_codes=result.success_codes,
            failed_codes=failed_total,
            rows_fetched=result.rows_fetched,
            rows_written=result.rows_written,
            message=(
                f"mode={mode}, empty={result.empty_codes}, "
                f"elapsed={time.monotonic() - started:.1f}s"
            ),
            db_path=db_path,
        )
        logger.info("入库运行结束：%s", result.as_dict())

    return result
