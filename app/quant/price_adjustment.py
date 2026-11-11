"""统一价格口径：用单一行内因子生成复权 OHLC。

调整因子 = adjusted_close / raw_close
adjusted_open/high/low = raw_open/high/low × 因子
adjusted_close 使用数据库已有的前复权收盘价。

原始 OHLC 只读，不在本模块修改，也不写回数据库。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable

import numpy as np
import pandas as pd


class PriceDataError(ValueError):
    """价格输入或快照不满足计算条件。"""


class SnapshotConsistencyError(PriceDataError):
    """同一 ETF 存在多个或缺失调整快照。"""


@dataclass
class PriceAdjustmentResult:
    data: pd.DataFrame
    issues: list[dict[str, Any]] = field(default_factory=list)
    expected_missing_dates: list[str] = field(default_factory=list)
    valid_rows: int = 0
    invalid_rows: int = 0
    zero_volume_rows: int = 0
    missing_volume_rows: int = 0
    snapshot_id: int | None = None


def validate_snapshot(df: pd.DataFrame) -> int:
    """要求同一 ETF 的所有行只包含一个非空快照 ID。"""
    if df is None or df.empty:
        raise SnapshotConsistencyError("空行情，无法确定调整快照")
    if "adjustment_snapshot_id" not in df.columns:
        raise SnapshotConsistencyError("行情缺少 adjustment_snapshot_id")
    ids = pd.to_numeric(df["adjustment_snapshot_id"], errors="coerce").dropna().unique()
    if len(ids) == 0:
        raise SnapshotConsistencyError("行情没有 adjustment_snapshot_id")
    if len(ids) > 1:
        raise SnapshotConsistencyError(f"同一 ETF 混合了多个调整快照：{sorted(int(i) for i in ids)}")
    return int(ids[0])


def _issue(issues: list[dict[str, Any]], issue_type: str, severity: str, message: str, **extra: Any) -> None:
    issues.append({"type": issue_type, "severity": severity, "message": message, **extra})


def adjust_prices(
    df: pd.DataFrame,
    *,
    calendar_dates: Iterable[str] | None = None,
    today: date | None = None,
) -> PriceAdjustmentResult:
    """生成统一复权 OHLC 与行级质量状态。

    输出保留全部输入行；不合法行只标记，不删除、不填值。
    """
    if df is None or df.empty:
        raise PriceDataError("价格数据为空")
    required = {
        "code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "adjusted_close",
        "adjustment_snapshot_id",
    }
    missing = sorted(required - set(df.columns))
    if missing:
        raise PriceDataError(f"价格数据缺字段：{missing}")

    snapshot_id = validate_snapshot(df)
    work = df.copy().reset_index(drop=True)
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume", "adjusted_close"):
        work[column] = pd.to_numeric(work[column], errors="coerce")

    issues: list[dict[str, Any]] = []
    reasons: list[list[str]] = [[] for _ in range(len(work))]

    invalid_date = work["trade_date"].isna()
    duplicate_date = work["trade_date"].duplicated(keep=False) & work["trade_date"].notna()
    future = work["trade_date"] > pd.Timestamp(today or date.today())

    raw_close = work["close"]
    adjusted_close = work["adjusted_close"]
    raw_ohlc = work[["open", "high", "low"]]
    raw_ohlc_bad = (
        raw_close.isna()
        | (raw_close <= 0)
        | raw_ohlc.isna().any(axis=1)
        | (raw_ohlc <= 0).any(axis=1)
        | (work["high"] < work["low"])
        | (work["close"] > work["high"])
        | (work["close"] < work["low"])
        | (work["open"] > work["high"])
        | (work["open"] < work["low"])
    )
    adjusted_missing = adjusted_close.isna() | (adjusted_close <= 0)
    factor = adjusted_close / raw_close
    factor_bad = factor.isna() | ~np.isfinite(factor) | (factor <= 0)

    invalid_price = (
        invalid_date | duplicate_date | future | raw_ohlc_bad | adjusted_missing | factor_bad
    )

    for flag, reason in (
        (invalid_date, "invalid_date"),
        (duplicate_date, "duplicate_date"),
        (future, "future_date"),
        (raw_ohlc_bad, "raw_ohlc_invalid"),
        (adjusted_missing, "adjusted_close_missing"),
        (factor_bad, "adjustment_factor_invalid"),
    ):
        count = int(flag.sum())
        if count:
            _issue(issues, reason, "critical" if reason != "duplicate_date" else "warning",
                   f"{reason}：{count} 行", count=count)
            for index in work.index[flag]:
                reasons[index].append(reason)

    # 成交量 0 与成交量缺失分开标记，不把停牌/无成交当成缺失价格。
    zero_volume = work["volume"].notna() & (work["volume"] == 0)
    missing_volume = work["volume"].isna()
    if int(zero_volume.sum()):
        _issue(issues, "zero_volume", "warning", f"成交量为 0：{int(zero_volume.sum())} 行", count=int(zero_volume.sum()))
    if int(missing_volume.sum()):
        _issue(issues, "missing_volume", "warning", f"成交量缺失：{int(missing_volume.sum())} 行", count=int(missing_volume.sum()))

    # 复权 OHLC：因子合法时计算；非法行保持 NaN。
    factor_for_math = factor.where(~factor_bad)
    work["adjustment_factor"] = factor_for_math
    work["adjusted_open"] = work["open"] * factor_for_math
    work["adjusted_high"] = work["high"] * factor_for_math
    work["adjusted_low"] = work["low"] * factor_for_math
    work["adjusted_close"] = adjusted_close.where(~adjusted_missing)
    work["price_status"] = np.where(invalid_price, "invalid", "valid")
    work["price_reasons"] = [";".join(r) if r else None for r in reasons]
    work["trade_status"] = np.select(
        [zero_volume, missing_volume],
        ["zero_volume", "missing_volume"],
        default="normal",
    )

    adjusted_bad = pd.Series(False, index=work.index)
    valid_factor = ~factor_bad & ~adjusted_missing & ~raw_ohlc_bad
    # 数据源前复权收盘价通常保留 3 位小数，乘以因子后与独立舍入的 adjusted_close
    # 可能有 1e-16 级浮点差；用极小容差避免把正常舍入判成 OHLC 关系异常。
    tol = 1e-6
    adjusted_bad.loc[valid_factor] = (
        (work.loc[valid_factor, "adjusted_high"] + tol < work.loc[valid_factor, "adjusted_low"])
        | (work.loc[valid_factor, "adjusted_close"] > work.loc[valid_factor, "adjusted_high"] + tol)
        | (work.loc[valid_factor, "adjusted_close"] + tol < work.loc[valid_factor, "adjusted_low"])
        | (work.loc[valid_factor, "adjusted_open"] > work.loc[valid_factor, "adjusted_high"] + tol)
        | (work.loc[valid_factor, "adjusted_open"] + tol < work.loc[valid_factor, "adjusted_low"])
    )
    if int(adjusted_bad.sum()):
        _issue(issues, "adjusted_ohlc_invalid", "critical", f"复权 OHLC 关系异常：{int(adjusted_bad.sum())} 行", count=int(adjusted_bad.sum()))
        for index in work.index[adjusted_bad]:
            reasons[index].append("adjusted_ohlc_invalid")
        work.loc[adjusted_bad, "price_status"] = "invalid"
        work["price_reasons"] = [";".join(r) if r else None for r in reasons]

    expected_missing: list[str] = []
    if calendar_dates:
        dates = pd.to_datetime(work["trade_date"], errors="coerce").dropna()
        if not dates.empty:
            start, end = dates.min().date().isoformat(), dates.max().date().isoformat()
            expected = [str(d) for d in calendar_dates if start <= str(d) <= end]
            actual = set(dates.dt.date.astype(str))
            expected_missing = [d for d in expected if d not in actual]
            if expected_missing:
                _issue(
                    issues,
                    "missing_trading_dates",
                    "warning",
                    f"交易日历中存在但行情缺失的日期：{len(expected_missing)} 天",
                    count=len(expected_missing),
                    examples=expected_missing[:5],
                )

    return PriceAdjustmentResult(
        data=work,
        issues=issues,
        expected_missing_dates=expected_missing,
        valid_rows=int((work["price_status"] == "valid").sum()),
        invalid_rows=int((work["price_status"] != "valid").sum()),
        zero_volume_rows=int(zero_volume.sum()),
        missing_volume_rows=int(missing_volume.sum()),
        snapshot_id=snapshot_id,
    )
