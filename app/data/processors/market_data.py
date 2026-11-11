"""历史行情标准化、复权合并与入库记录构造。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd

from app.data.processors.normalize import HistoryCleanResult, clean_history, json_safe
from app.data.validators.market_data_validator import QualityResult, validate_history_frame

QUALITY_RANK = {"passed": 0, "warning": 1, "suspect": 2, "failed": 3}


@dataclass
class PreparedHistory:
    code: str
    data: pd.DataFrame
    raw_clean: HistoryCleanResult
    qfq_clean: HistoryCleanResult
    quality: QualityResult
    source: str
    collected_at: str
    issues: list[dict[str, Any]] = field(default_factory=list)

    @property
    def quality_status(self) -> str:
        return self.quality.status

    @property
    def coverage_start(self) -> date | None:
        if self.data.empty:
            return None
        return self.data.iloc[0]["trade_date"].date()

    @property
    def coverage_end(self) -> date | None:
        if self.data.empty:
            return None
        return self.data.iloc[-1]["trade_date"].date()

    @property
    def latest_close(self) -> float | None:
        if self.data.empty:
            return None
        return float(self.data.iloc[-1]["close"])


def _cleaning_issues(cleaned: HistoryCleanResult, label: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if cleaned.missing_columns:
        issues.append(
            {
                "type": "missing_columns",
                "severity": "critical",
                "message": f"{label}缺字段：{cleaned.missing_columns}",
            }
        )
    if cleaned.invalid_date_rows:
        issues.append(
            {
                "type": "invalid_date_dropped",
                "severity": "warning",
                "message": f"{label}删除 {cleaned.invalid_date_rows} 行无效日期",
                "count": cleaned.invalid_date_rows,
            }
        )
    if cleaned.invalid_close_rows:
        issues.append(
            {
                "type": "invalid_close_dropped",
                "severity": "warning",
                "message": f"{label}删除 {cleaned.invalid_close_rows} 行无效收盘价",
                "count": cleaned.invalid_close_rows,
            }
        )
    if cleaned.future_rows:
        issues.append(
            {
                "type": "future_date_dropped",
                "severity": "critical",
                "message": f"{label}删除 {cleaned.future_rows} 行未来日期",
                "count": cleaned.future_rows,
            }
        )
    if cleaned.duplicate_rows:
        issues.append(
            {
                "type": "duplicate_date_dropped",
                "severity": "warning",
                "message": f"{label}删除 {cleaned.duplicate_rows} 行重复日期",
                "count": cleaned.duplicate_rows,
            }
        )
    if cleaned.duplicate_conflict_rows:
        issues.append(
            {
                "type": "duplicate_date_conflict",
                "severity": "critical",
                "message": f"{label}有 {cleaned.duplicate_conflict_rows} 个交易日重复且收盘价不同",
                "count": cleaned.duplicate_conflict_rows,
            }
        )
    return issues


def _combine_status(*statuses: str) -> str:
    return max(statuses, key=lambda value: QUALITY_RANK.get(value, 0))


def prepare_raw_history(
    code: str,
    raw_df: pd.DataFrame,
    *,
    source: str,
    collected_at: str,
    today: date | None = None,
) -> PreparedHistory:
    """只清洗原始行情，不合并任何复权字段。

    日常原始行情同步使用该路径；复权由独立的完整快照刷新负责。
    """
    raw_clean = clean_history(raw_df, today=today)
    issues = _cleaning_issues(raw_clean, "原始行情")
    empty_qfq = clean_history(pd.DataFrame(), today=today)
    if raw_clean.data.empty:
        return PreparedHistory(
            code=code,
            data=pd.DataFrame(),
            raw_clean=raw_clean,
            qfq_clean=empty_qfq,
            quality=QualityResult(status="failed", issues=issues),
            source=source,
            collected_at=collected_at,
            issues=issues,
        )

    data = raw_clean.data.copy()
    validation = validate_history_frame(data, code, today=today)
    issues.extend(validation.issues)
    data["quality_status"] = validation.row_status
    data["quality_notes"] = [note or None for note in validation.row_notes]
    data = data.sort_values("trade_date", kind="mergesort").reset_index(drop=True)

    if any(issue.get("severity") == "critical" for issue in issues):
        issue_status = "suspect"
    elif issues:
        issue_status = "warning"
    else:
        issue_status = "passed"
    return PreparedHistory(
        code=code,
        data=data,
        raw_clean=raw_clean,
        qfq_clean=empty_qfq,
        quality=QualityResult(
            status=_combine_status(validation.status, issue_status),
            issues=issues,
            row_status=validation.row_status,
            row_notes=validation.row_notes,
        ),
        source=source,
        collected_at=collected_at,
        issues=issues,
    )


def prepare_history(
    code: str,
    raw_df: pd.DataFrame,
    qfq_df: pd.DataFrame | None,
    *,
    source: str,
    collected_at: str,
    today: date | None = None,
) -> PreparedHistory:
    """清洗原始行情、合并前复权收盘价，并标记质量状态。

    原始 OHLC 不因复权而改写；`adjusted_close` 仅用于收益/连续序列分析。
    """
    raw_clean = clean_history(raw_df, today=today)
    qfq_clean = clean_history(qfq_df, today=today)
    issues = _cleaning_issues(raw_clean, "原始行情")
    issues.extend(_cleaning_issues(qfq_clean, "前复权行情"))

    if raw_clean.data.empty:
        quality = QualityResult(status="failed", issues=issues)
        return PreparedHistory(
            code=code,
            data=pd.DataFrame(),
            raw_clean=raw_clean,
            qfq_clean=qfq_clean,
            quality=quality,
            source=source,
            collected_at=collected_at,
            issues=issues,
        )

    data = raw_clean.data.copy()
    if qfq_clean.data.empty:
        data["adjusted_close"] = pd.NA
        issues.append(
            {
                "type": "adjusted_close_unavailable",
                "severity": "warning",
                "message": "前复权行情为空，adjusted_close 未填充",
            }
        )
    else:
        adjusted = qfq_clean.data[["trade_date", "close"]].rename(columns={"close": "adjusted_close"})
        adjusted = adjusted.drop_duplicates(subset=["trade_date"], keep="last")
        data = data.merge(adjusted, on="trade_date", how="left")

    validation = validate_history_frame(data, code, today=today)
    issues.extend(validation.issues)
    data["quality_status"] = validation.row_status
    data["quality_notes"] = [note or None for note in validation.row_notes]
    data["adjustment_type"] = "qfq" if data["adjusted_close"].notna().any() else "none"
    data = data.sort_values("trade_date", kind="mergesort").reset_index(drop=True)

    if any(issue.get("severity") == "critical" for issue in issues):
        issue_status = "suspect"
    elif issues:
        issue_status = "warning"
    else:
        issue_status = "passed"
    return PreparedHistory(
        code=code,
        data=data,
        raw_clean=raw_clean,
        qfq_clean=qfq_clean,
        quality=QualityResult(
            status=_combine_status(validation.status, issue_status),
            issues=issues,
            row_status=validation.row_status,
            row_notes=validation.row_notes,
        ),
        source=source,
        collected_at=collected_at,
        issues=issues,
    )


def latest_record(data: pd.DataFrame) -> tuple[str | None, float | None]:
    """取最近一条有效记录；日期与收盘价来自同一行。"""
    if data is None or data.empty:
        return None, None
    work = data.copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce")
    work["close"] = pd.to_numeric(work["close"], errors="coerce")
    work = work.dropna(subset=["trade_date", "close"])
    work = work.loc[work["close"] > 0].sort_values("trade_date", kind="mergesort")
    if work.empty:
        return None, None
    last = work.iloc[-1]
    return pd.Timestamp(last["trade_date"]).date().isoformat(), float(last["close"])


def to_raw_price_records(
    prepared: PreparedHistory,
    *,
    source: str,
    collected_at: str,
) -> list[dict[str, Any]]:
    """构造仅含原始 OHLC 的 UPSERT 记录，不携带任何复权字段。"""
    if prepared.data.empty:
        return []
    records: list[dict[str, Any]] = []
    for row in prepared.data.itertuples(index=False):
        records.append(
            {
                "code": prepared.code,
                "trade_date": pd.Timestamp(row.trade_date).date().isoformat(),
                "open": json_safe(row.open),
                "high": json_safe(row.high),
                "low": json_safe(row.low),
                "close": json_safe(row.close),
                "volume": json_safe(row.volume),
                "amount": json_safe(row.amount),
                "quality_status": row.quality_status,
                "quality_notes": row.quality_notes,
                "source": source,
                "collected_at": collected_at,
            }
        )
    return records


def to_price_records(
    prepared: PreparedHistory,
    *,
    source: str,
    collected_at: str,
) -> list[dict[str, Any]]:
    """把 PreparedHistory 转为 SQLite UPSERT 所需记录。"""
    if prepared.data.empty:
        return []
    records: list[dict[str, Any]] = []
    for row in prepared.data.itertuples(index=False):
        records.append(
            {
                "code": prepared.code,
                "trade_date": pd.Timestamp(row.trade_date).date().isoformat(),
                "open": json_safe(row.open),
                "high": json_safe(row.high),
                "low": json_safe(row.low),
                "close": json_safe(row.close),
                "volume": json_safe(row.volume),
                "amount": json_safe(row.amount),
                "adjusted_close": json_safe(getattr(row, "adjusted_close", None)),
                "adjustment_type": row.adjustment_type,
                "quality_status": row.quality_status,
                "quality_notes": row.quality_notes,
                "source": source,
                "collected_at": collected_at,
            }
        )
    return records
