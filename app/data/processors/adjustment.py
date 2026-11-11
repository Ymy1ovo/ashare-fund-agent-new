"""完整前复权历史刷新与调整快照管理。

核心约束：
- 每次刷新都获取 ETF 的完整历史 qfq，不拼接增量 qfq；
- 只更新 adjusted_close 与快照元数据，绝不修改原始 OHLC；
- 成功或部分成功的快照在单只基金事务中激活；
- 请求失败/空数据只记录失败快照，不覆盖当前有效数据。
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
from app.data.processors.market_data import _cleaning_issues
from app.data.processors.normalize import clean_history
from app.database.db import (
    apply_adjustment_snapshot,
    finish_adjustment_run,
    get_raw_price_rows,
    save_adjustment_snapshot,
    start_adjustment_run,
)

logger = logging.getLogger(__name__)
SOURCE = "AKShare fund_etf_hist_em(adjust=qfq)"


class AdjustedHistoryProvider(Protocol):
    def fetch_qfq_history(self, code: str, start_date: str, end_date: str) -> pd.DataFrame: ...


class AkshareAdjustedProvider:
    def __init__(self, collector: AkshareCollector | None = None) -> None:
        self.collector = collector or AkshareCollector()

    def fetch_qfq_history(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self.collector.fetch_etf_history(
            code,
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",
        )


@dataclass
class AdjustmentRefreshResult:
    run_id: int
    status: str
    total_codes: int
    success_codes: int = 0
    partial_codes: int = 0
    failed_codes: int = 0
    empty_codes: int = 0
    rows_updated: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "total_codes": self.total_codes,
            "success_codes": self.success_codes,
            "partial_codes": self.partial_codes,
            "failed_codes": self.failed_codes,
            "empty_codes": self.empty_codes,
            "rows_updated": self.rows_updated,
            "details": self.details,
        }


def _snapshot_payload(
    *,
    run_id: int,
    code: str,
    status: str,
    collected_at: str,
    coverage_start: str | None,
    coverage_end: str | None,
    matched_start: str | None,
    matched_end: str | None,
    raw_rows: int,
    qfq_rows: int,
    matched_rows: int,
    missing_rows: int,
    issues: list[dict[str, Any]],
    error_message: str | None = None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "code": code,
        "status": status,
        "collected_at": collected_at,
        "source": SOURCE,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "matched_start": matched_start,
        "matched_end": matched_end,
        "raw_rows": raw_rows,
        "qfq_rows": qfq_rows,
        "matched_rows": matched_rows,
        "missing_rows": missing_rows,
        "issues_json": json.dumps(issues, ensure_ascii=False, default=str),
        "error_message": error_message,
        "is_current": 0,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def _detail_base(code: str, started_at: str) -> dict[str, Any]:
    return {
        "code": code,
        "status": "failed",
        "snapshot_id": None,
        "raw_rows": 0,
        "qfq_rows": 0,
        "matched_rows": 0,
        "missing_rows": 0,
        "rows_updated": 0,
        "coverage_start": None,
        "coverage_end": None,
        "error_message": None,
        "started_at": started_at,
        "finished_at": None,
    }


def _refresh_one(
    code: str,
    *,
    run_id: int,
    provider: AdjustedHistoryProvider,
    today: date,
    db_path: Path | None,
) -> tuple[dict[str, Any], int]:
    """刷新单只基金；返回明细与更新行数。"""
    started_at = datetime.now().isoformat(timespec="seconds")
    detail = _detail_base(code, started_at)
    raw_rows = get_raw_price_rows(code, db_path)
    detail["raw_rows"] = len(raw_rows)
    if not raw_rows:
        detail["error_message"] = "数据库中没有原始行情，无法建立复权快照"
        detail["finished_at"] = datetime.now().isoformat(timespec="seconds")
        save_adjustment_snapshot(
            _snapshot_payload(
                run_id=run_id,
                code=code,
                status="failed",
                collected_at=started_at,
                coverage_start=None,
                coverage_end=None,
                matched_start=None,
                matched_end=None,
                raw_rows=0,
                qfq_rows=0,
                matched_rows=0,
                missing_rows=0,
                issues=[{"type": "no_raw_data", "severity": "critical", "message": detail["error_message"]}],
                error_message=detail["error_message"],
            ),
            db_path,
        )
        return detail, 0

    qfq: pd.DataFrame
    try:
        qfq = provider.fetch_qfq_history(code, "20000101", today.strftime("%Y%m%d"))
        if not isinstance(qfq, pd.DataFrame):
            raise TypeError(f"provider 返回类型异常：{type(qfq).__name__}")
    except Exception as exc:  # noqa: BLE001 - 失败时保留当前有效快照
        detail["error_message"] = f"前复权获取失败：{type(exc).__name__}: {exc}"
        detail["finished_at"] = datetime.now().isoformat(timespec="seconds")
        logger.warning("%s 完整前复权刷新失败，保留旧快照：%s", code, exc)
        save_adjustment_snapshot(
            _snapshot_payload(
                run_id=run_id,
                code=code,
                status="failed",
                collected_at=started_at,
                coverage_start=None,
                coverage_end=None,
                matched_start=None,
                matched_end=None,
                raw_rows=len(raw_rows),
                qfq_rows=0,
                matched_rows=0,
                missing_rows=len(raw_rows),
                issues=[{"type": "qfq_fetch_failed", "severity": "critical", "message": detail["error_message"]}],
                error_message=detail["error_message"],
            ),
            db_path,
        )
        return detail, 0

    qfq_clean = clean_history(qfq, today=today)
    detail["qfq_rows"] = len(qfq_clean.data)
    issues = _cleaning_issues(qfq_clean, "前复权行情")
    if qfq_clean.missing_columns or qfq_clean.data.empty:
        detail["status"] = "empty"
        detail["error_message"] = f"前复权清洗后无有效数据，字段问题={qfq_clean.missing_columns}"
        detail["finished_at"] = datetime.now().isoformat(timespec="seconds")
        logger.warning("%s 前复权空数据，保留旧快照", code)
        save_adjustment_snapshot(
            _snapshot_payload(
                run_id=run_id,
                code=code,
                status="empty",
                collected_at=started_at,
                coverage_start=None,
                coverage_end=None,
                matched_start=None,
                matched_end=None,
                raw_rows=len(raw_rows),
                qfq_rows=len(qfq_clean.data),
                matched_rows=0,
                missing_rows=len(raw_rows),
                issues=issues + [{"type": "empty_qfq", "severity": "critical", "message": "前复权数据为空"}],
                error_message=detail["error_message"],
            ),
            db_path,
        )
        return detail, 0

    qfq_map = {
        pd.Timestamp(row.trade_date).date().isoformat(): float(row.close)
        for row in qfq_clean.data.itertuples(index=False)
    }
    raw_dates = [str(row["trade_date"]) for row in raw_rows]
    matched_dates = [trade_date for trade_date in raw_dates if trade_date in qfq_map]
    missing_rows = len(raw_dates) - len(matched_dates)
    detail["matched_rows"] = len(matched_dates)
    detail["missing_rows"] = missing_rows

    if not matched_dates:
        detail["error_message"] = "前复权日期与数据库原始行情没有任何交集"
        detail["finished_at"] = datetime.now().isoformat(timespec="seconds")
        save_adjustment_snapshot(
            _snapshot_payload(
                run_id=run_id,
                code=code,
                status="failed",
                collected_at=started_at,
                coverage_start=qfq_clean.data.iloc[0]["trade_date"].date().isoformat(),
                coverage_end=qfq_clean.data.iloc[-1]["trade_date"].date().isoformat(),
                matched_start=None,
                matched_end=None,
                raw_rows=len(raw_rows),
                qfq_rows=len(qfq_clean.data),
                matched_rows=0,
                missing_rows=len(raw_rows),
                issues=issues + [{"type": "no_date_match", "severity": "critical", "message": detail["error_message"]}],
                error_message=detail["error_message"],
            ),
            db_path,
        )
        return detail, 0

    status = "success" if missing_rows == 0 else "partial"
    if missing_rows:
        issues.append(
            {
                "type": "missing_adjusted_dates",
                "severity": "warning",
                "message": f"{missing_rows} 个原始行情日期没有可用的前复权收盘价，将保持为空",
                "count": missing_rows,
                "examples": [d for d in raw_dates if d not in qfq_map][:5],
            }
        )

    snapshot = _snapshot_payload(
        run_id=run_id,
        code=code,
        status=status,
        collected_at=started_at,
        coverage_start=qfq_clean.data.iloc[0]["trade_date"].date().isoformat(),
        coverage_end=qfq_clean.data.iloc[-1]["trade_date"].date().isoformat(),
        matched_start=min(matched_dates),
        matched_end=max(matched_dates),
        raw_rows=len(raw_rows),
        qfq_rows=len(qfq_clean.data),
        matched_rows=len(matched_dates),
        missing_rows=missing_rows,
        issues=issues,
    )
    updates = [
        {"trade_date": trade_date, "adjusted_close": qfq_map.get(trade_date)}
        for trade_date in raw_dates
    ]
    try:
        snapshot_id = apply_adjustment_snapshot(snapshot, updates, db_path)
    except Exception as exc:  # noqa: BLE001 - 事务回滚后记录失败，旧快照仍有效
        detail["error_message"] = f"应用快照失败：{type(exc).__name__}: {exc}"
        detail["finished_at"] = datetime.now().isoformat(timespec="seconds")
        logger.exception("%s 应用调整快照失败，数据库事务已回滚", code)
        save_adjustment_snapshot(
            _snapshot_payload(
                run_id=run_id,
                code=code,
                status="failed",
                collected_at=started_at,
                coverage_start=None,
                coverage_end=None,
                matched_start=None,
                matched_end=None,
                raw_rows=len(raw_rows),
                qfq_rows=len(qfq_clean.data),
                matched_rows=0,
                missing_rows=len(raw_rows),
                issues=issues + [{"type": "snapshot_apply_failed", "severity": "critical", "message": detail["error_message"]}],
                error_message=detail["error_message"],
            ),
            db_path,
        )
        return detail, 0

    detail.update(
        {
            "status": status,
            "snapshot_id": snapshot_id,
            "rows_updated": len(updates),
            "coverage_start": snapshot["coverage_start"],
            "coverage_end": snapshot["coverage_end"],
            "finished_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    logger.info(
        "%s 前复权快照 %s：快照ID=%s，原始 %d 行，匹配 %d 行，缺失 %d 行，覆盖 %s ~ %s",
        code,
        status,
        snapshot_id,
        len(raw_rows),
        len(matched_dates),
        missing_rows,
        snapshot["coverage_start"],
        snapshot["coverage_end"],
    )
    return detail, len(updates)


def refresh_adjusted_prices(
    codes: Sequence[str],
    provider: AdjustedHistoryProvider,
    *,
    db_path: Path | None = None,
    today: date | None = None,
) -> AdjustmentRefreshResult:
    """完整刷新前复权数据；失败/空数据不会覆盖当前快照。"""
    ordered_codes = list(dict.fromkeys(str(code) for code in codes if str(code)))
    today = today or date.today()
    run_id = start_adjustment_run(len(ordered_codes), db_path)
    result = AdjustmentRefreshResult(run_id=run_id, status="running", total_codes=len(ordered_codes))
    started = time.monotonic()

    try:
        for code in ordered_codes:
            try:
                detail, updated = _refresh_one(
                    code,
                    run_id=run_id,
                    provider=provider,
                    today=today,
                    db_path=db_path,
                )
            except Exception as exc:  # noqa: BLE001 - 单只基金异常不能中断其他基金
                now = datetime.now().isoformat(timespec="seconds")
                detail = {
                    "code": code,
                    "status": "failed",
                    "snapshot_id": None,
                    "raw_rows": 0,
                    "qfq_rows": 0,
                    "matched_rows": 0,
                    "missing_rows": 0,
                    "rows_updated": 0,
                    "coverage_start": None,
                    "coverage_end": None,
                    "error_message": f"{type(exc).__name__}: {exc}",
                    "started_at": now,
                    "finished_at": now,
                }
                updated = 0
                logger.exception("%s 复权刷新发生未捕获异常", code)
            result.details.append(detail)
            result.rows_updated += updated
            if detail["status"] == "success":
                result.success_codes += 1
            elif detail["status"] == "partial":
                result.partial_codes += 1
            elif detail["status"] == "empty":
                result.empty_codes += 1
            else:
                result.failed_codes += 1
    finally:
        failed_total = result.failed_codes + result.empty_codes
        if result.success_codes == result.total_codes:
            result.status = "success"
        elif result.success_codes + result.partial_codes == 0:
            result.status = "failed"
        else:
            result.status = "partial"
        finish_adjustment_run(
            run_id,
            status=result.status,
            success_codes=result.success_codes,
            partial_codes=result.partial_codes,
            failed_codes=result.failed_codes,
            empty_codes=result.empty_codes,
            rows_updated=result.rows_updated,
            message=f"failed={failed_total}, elapsed={time.monotonic() - started:.1f}s",
            db_path=db_path,
        )
        logger.info("前复权刷新结束：%s", result.as_dict())
    return result
