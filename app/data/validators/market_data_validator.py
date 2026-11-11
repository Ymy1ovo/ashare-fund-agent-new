"""历史行情数据质量校验。

规则只做识别与标记，不修改原始 OHLC；可疑行仍可入库，但必须带 quality_status。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd


@dataclass
class QualityResult:
    status: str
    issues: list[dict[str, Any]] = field(default_factory=list)
    row_status: list[str] = field(default_factory=list)
    row_notes: list[str] = field(default_factory=list)


def _issue(issues: list[dict[str, Any]], issue_type: str, severity: str, message: str, **extra: Any) -> None:
    item: dict[str, Any] = {
        "type": issue_type,
        "severity": severity,
        "message": message,
        **extra,
    }
    issues.append(item)


def validate_history_frame(
    df: pd.DataFrame,
    code: str,
    *,
    today: date | None = None,
    gap_days: int = 20,
) -> QualityResult:
    """校验清洗后的行情表。

    返回总体状态：
    - failed：空表或关键字段缺失；
    - suspect：OHLC 关系矛盾、未来日期等严重问题；
    - warning：明显缺口、零成交、复权价缺失等需关注问题；
    - passed：未发现问题。
    """
    issues: list[dict[str, Any]] = []
    if df is None or df.empty:
        _issue(issues, "empty", "critical", "清洗后无有效行情")
        return QualityResult(status="failed", issues=issues)

    required = {"trade_date", "close"}
    missing = sorted(required - set(df.columns))
    if missing:
        _issue(issues, "missing_columns", "critical", f"缺字段：{missing}")
        return QualityResult(status="failed", issues=issues)

    work = df.reset_index(drop=True).copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce")
    work["close"] = pd.to_numeric(work["close"], errors="coerce")
    row_status = ["valid"] * len(work)
    row_notes = [""] * len(work)

    def mark(mask: pd.Series, status: str, note: str) -> int:
        count = int(mask.fillna(False).sum())
        if count:
            for index in work.index[mask.fillna(False)]:
                if status == "suspect" or row_status[index] == "valid":
                    row_status[index] = status
                notes = [part for part in row_notes[index].split(";") if part]
                if note not in notes:
                    notes.append(note)
                row_notes[index] = ";".join(notes)
        return count

    invalid_dates = work["trade_date"].isna()
    invalid_closes = work["close"].isna() | (work["close"] <= 0)
    cutoff = pd.Timestamp(today or date.today())
    future = work["trade_date"] > cutoff
    duplicates = work.duplicated(subset=["trade_date"], keep=False)

    for mask, issue_type, severity, message, note in (
        (invalid_dates, "invalid_date", "critical", "存在无效日期", "invalid_date"),
        (invalid_closes, "invalid_close", "critical", "存在无效或非正收盘价", "invalid_close"),
        (future, "future_date", "critical", "存在未来日期", "future_date"),
        (duplicates, "duplicate_date", "critical", "存在重复交易日", "duplicate_date"),
    ):
        count = int(mask.sum())
        if count:
            _issue(issues, issue_type, severity, f"{message}（{count} 行）", count=count)
            mark(mask, "suspect", note)

    for column in ("open", "high", "low"):
        if column not in work.columns:
            work[column] = pd.NA
        work[column] = pd.to_numeric(work[column], errors="coerce")
    for column in ("volume", "amount"):
        if column not in work.columns:
            work[column] = pd.NA
        work[column] = pd.to_numeric(work[column], errors="coerce")

    missing_ohlc = work[["open", "high", "low", "close"]].isna().any(axis=1)
    count = mark(missing_ohlc, "warning", "missing_ohlc")
    if count:
        _issue(issues, "missing_ohlc", "warning", f"部分 OHLC 为空（{count} 行）", count=count)

    nonpositive_ohlc = (work[["open", "high", "low"]] <= 0).any(axis=1)
    count = mark(nonpositive_ohlc, "suspect", "nonpositive_ohlc")
    if count:
        _issue(issues, "nonpositive_ohlc", "critical", f"OHLC 存在非正值（{count} 行）", count=count)

    high_low_bad = (work["high"] < work["low"]).fillna(False)
    count = mark(high_low_bad, "suspect", "high_below_low")
    if count:
        _issue(issues, "high_below_low", "critical", f"最高价低于最低价（{count} 行）", count=count)

    close_outside = (
        (work["close"] > work["high"]) | (work["close"] < work["low"])
    ).fillna(False)
    count = mark(close_outside, "suspect", "close_outside_high_low")
    if count:
        _issue(issues, "close_outside_high_low", "critical", f"收盘价不在高低区间内（{count} 行）", count=count)

    open_outside = (
        (work["open"] > work["high"]) | (work["open"] < work["low"])
    ).fillna(False)
    count = mark(open_outside, "suspect", "open_outside_high_low")
    if count:
        _issue(issues, "open_outside_high_low", "critical", f"开盘价不在高低区间内（{count} 行）", count=count)

    negative_volume = (work["volume"] < 0).fillna(False)
    count = mark(negative_volume, "warning", "negative_volume")
    if count:
        _issue(issues, "negative_volume", "warning", f"成交量为负（{count} 行）", count=count)

    negative_amount = (work["amount"] < 0).fillna(False)
    count = mark(negative_amount, "warning", "negative_amount")
    if count:
        _issue(issues, "negative_amount", "warning", f"成交额为负（{count} 行）", count=count)

    zero_volume = (work["volume"] == 0).fillna(False)
    count = mark(zero_volume, "warning", "zero_volume")
    if count:
        _issue(issues, "zero_volume", "warning", f"成交量为 0（{count} 行）", count=count)

    if "adjusted_close" in work.columns:
        work["adjusted_close"] = pd.to_numeric(work["adjusted_close"], errors="coerce")
        missing_adjusted = work["adjusted_close"].isna()
        count = mark(missing_adjusted, "warning", "missing_adjusted_close")
        if count:
            _issue(issues, "missing_adjusted_close", "warning", f"复权收盘价缺失（{count} 行）", count=count)
        nonpositive_adjusted = (work["adjusted_close"] <= 0).fillna(False)
        count = mark(nonpositive_adjusted, "suspect", "nonpositive_adjusted_close")
        if count:
            _issue(issues, "nonpositive_adjusted_close", "critical", f"复权收盘价非正（{count} 行）", count=count)

    # 日历日缺口检查；阈值 20 天，避免把春节等长假误判。
    days = work["trade_date"].dropna().sort_values().reset_index(drop=True)
    if len(days) > 1:
        gaps = days.diff().dt.days
        gap_mask = gaps > gap_days
        gap_count = int(gap_mask.fillna(False).sum())
        if gap_count:
            examples = [
                f"{days.iloc[index - 1].date()}->{days.iloc[index].date()}约{int(gaps.iloc[index])}天"
                for index in gaps[gap_mask].index[:5]
            ]
            _issue(
                issues,
                "date_gap",
                "warning",
                f"存在 {gap_count} 处超过 {gap_days} 个日历日的行情缺口",
                count=gap_count,
                examples=examples,
            )
            # 把缺口后的第一行标记为 warning，便于后续按行筛选。
            for index in gaps[gap_mask].index:
                row_status[index] = "warning" if row_status[index] == "valid" else row_status[index]
                note = f"gap_before={int(gaps.iloc[index])}d"
                notes = [part for part in row_notes[index].split(";") if part]
                if note not in notes:
                    notes.append(note)
                row_notes[index] = ";".join(notes)

    severities = {issue["severity"] for issue in issues}
    if "critical" in severities:
        status = "suspect"
    elif "warning" in severities:
        status = "warning"
    else:
        status = "passed"
    return QualityResult(status=status, issues=issues, row_status=row_status, row_notes=row_notes)
