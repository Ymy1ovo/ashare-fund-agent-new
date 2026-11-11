"""统一指标计算引擎。"""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable

import numpy as np
import pandas as pd

from app.database.db import get_connection, get_current_adjustment_snapshot, get_trade_calendar
from app.quant.config import DEFAULT_CONFIG, calculation_version, normalize_config
from app.quant.momentum import compute_macd, compute_rsi
from app.quant.price_adjustment import PriceAdjustmentResult, PriceDataError, adjust_prices
from app.quant.returns import compute_returns
from app.quant.risk import compute_risk, summarize_range
from app.quant.trend import compute_trend
from app.quant.validation import build_row_quality, indicator_coverage, quality_counts
from app.quant.volatility import compute_volatility


class IndicatorCalculationError(ValueError):
    def __init__(self, reason: str, message: str | None = None):
        self.reason = reason
        super().__init__(message or reason)


@dataclass
class IndicatorResult:
    etf_code: str
    data: pd.DataFrame
    status: str
    reason: str | None
    snapshot_id: int | None
    snapshot_is_current: bool
    calculation_version: str
    calculation_time: str
    run_id: str
    config: dict[str, Any]
    summary: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)
    valid_rows: int = 0
    missing_rows: int = 0
    coverage: dict[str, Any] = field(default_factory=dict)

    def as_meta(self) -> dict[str, Any]:
        return {
            "etf_code": self.etf_code,
            "status": self.status,
            "reason": self.reason,
            "snapshot_id": self.snapshot_id,
            "snapshot_is_current": self.snapshot_is_current,
            "calculation_version": self.calculation_version,
            "calculation_time": self.calculation_time,
            "run_id": self.run_id,
            "config": self.config,
            "summary": self.summary,
            "quality": self.quality,
            "valid_rows": self.valid_rows,
            "missing_rows": self.missing_rows,
            "coverage": self.coverage,
        }


def _load_prices(code: str, db_path=None) -> pd.DataFrame:
    with get_connection(db_path) as conn:
        return pd.read_sql_query(
            """
            SELECT code, trade_date, open, high, low, close, volume, amount,
                   adjusted_close, adjustment_snapshot_id, adjustment_collected_at,
                   adjustment_source, quality_status, source, collected_at
            FROM etf_daily_prices
            WHERE code = ?
            ORDER BY trade_date
            """,
            conn,
            params=(code,),
        )


def _calendar_for(df: pd.DataFrame, db_path=None) -> tuple[list[str], bool]:
    dates = pd.to_datetime(df["trade_date"], errors="coerce").dropna()
    if dates.empty:
        return [], False
    start, end = dates.min().date().isoformat(), dates.max().date().isoformat()
    calendar = get_trade_calendar(start, end, db_path=db_path)
    if not calendar:
        return sorted(set(dates.dt.date.astype(str))), False
    # 实际行情中若有不在日历中的日期，也纳入索引并保留，不能静默丢弃。
    merged = sorted(set(calendar) | set(dates.dt.date.astype(str)))
    return merged, True


def _date_arg(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise IndicatorCalculationError("invalid_date", f"非法日期：{value}") from exc


def _enabled_columns(config: dict[str, Any]) -> list[str]:
    columns: list[str] = []
    if "returns" in config["enabled"]:
        columns += [f"return_{w}d" for w in config["return_windows"]] + ["cagr"]
    if "trend" in config["enabled"]:
        columns += [f"ma{w}" for w in config["ma_windows"]] + [f"ema{s}" for s in config["ema_spans"]]
    if "momentum" in config["enabled"]:
        columns += [f"rsi{p}" for p in config["rsi_periods"]] + ["macd_dif", "macd_dea", "macd_hist"]
    if "volatility" in config["enabled"]:
        columns += [f"volatility_{w}d" for w in config["vol_windows"]]
        columns += [f"max_drawdown_{w}d" for w in config["mdd_windows"]] + ["max_drawdown_all"]
        columns += [f"atr{config['atr_period']}"]
    if "risk" in config["enabled"]:
        columns += ["sharpe_ratio", "sortino_ratio", "calmar_ratio"]
    return columns


def calculate_indicators(
    etf_code: str,
    start_date: str | None = None,
    end_date: str | None = None,
    indicator_config: dict[str, Any] | None = None,
    *,
    db_path=None,
    run_id: str | None = None,
    today: date | None = None,
) -> IndicatorResult:
    code = str(etf_code).zfill(6)
    config = normalize_config(indicator_config)
    version = calculation_version(config)
    start = _date_arg(start_date)
    end = _date_arg(end_date)
    if start and end and start > end:
        raise IndicatorCalculationError("invalid_date_range", "开始日期不能晚于结束日期")
    run_id = run_id or uuid.uuid4().hex
    calc_time = datetime.now().isoformat(timespec="seconds")

    raw = _load_prices(code, db_path)
    if raw.empty:
        raise IndicatorCalculationError("no_data", f"{code} 没有行情数据")
    raw["trade_date"] = pd.to_datetime(raw["trade_date"], errors="coerce")
    if raw["trade_date"].isna().any():
        raise IndicatorCalculationError("invalid_date", "行情包含非法日期")
    if raw["trade_date"].duplicated().any():
        raise IndicatorCalculationError("duplicate_date", "行情包含重复日期")

    current_snapshot = get_current_adjustment_snapshot(code, db_path=db_path)
    current_snapshot_id = int(current_snapshot["id"]) if current_snapshot else None
    try:
        adjusted = adjust_prices(raw, calendar_dates=None, today=today)
    except PriceDataError as exc:
        raise IndicatorCalculationError("price_data_invalid", str(exc)) from exc
    snapshot_id = adjusted.snapshot_id
    snapshot_is_current = current_snapshot_id == snapshot_id

    calendar, calendar_available = _calendar_for(raw, db_path=db_path)
    if not calendar:
        raise IndicatorCalculationError("calendar_empty", "无法建立交易日索引")
    calendar_index = pd.DatetimeIndex(pd.to_datetime(calendar))
    prices = adjusted.data.set_index("trade_date").sort_index()
    full = prices.reindex(calendar_index)
    full["code"] = code
    full["data_present"] = full["close"].notna()
    full["adjustment_snapshot_id"] = snapshot_id
    missing = ~full["data_present"]
    if missing.any():
        full.loc[missing, "price_status"] = "invalid"
        full.loc[missing, "price_reasons"] = "missing_ohlc"
        full.loc[missing, "trade_status"] = "missing"

    output_start = max(start, raw["trade_date"].min().date().isoformat()) if start else raw["trade_date"].min().date().isoformat()
    output_end = min(end, raw["trade_date"].max().date().isoformat()) if end else raw["trade_date"].max().date().isoformat()
    if output_start > output_end:
        raise IndicatorCalculationError("empty_range", "请求区间内没有行情")

    # 先在全历史上计算，后续截取请求区间，保证起点指标能使用起点之前的 trailing 数据。
    if "returns" in config["enabled"]:
        full = full.join(
            compute_returns(full, config["return_windows"], annualization=int(config["annualization"]))
        )
    if "trend" in config["enabled"]:
        full = full.join(compute_trend(full, config["ma_windows"], config["ema_spans"]))
    if "momentum" in config["enabled"]:
        full = full.join(compute_rsi(full, config["rsi_periods"]))
        full = full.join(compute_macd(full, **config["macd"]))
    if "volatility" in config["enabled"]:
        full = full.join(
            compute_volatility(
                full,
                vol_windows=config["vol_windows"],
                mdd_windows=config["mdd_windows"],
                atr_period=int(config["atr_period"]),
                annualization=int(config["annualization"]),
                ddof=int(config["std_ddof"]),
            )
        )
    if "risk" in config["enabled"]:
        full = full.join(
            compute_risk(
                full,
                risk_window=int(config["risk_window"]),
                annualization=int(config["annualization"]),
                risk_free_rate=float(config["risk_free_rate"]),
            )
        )

    full = full.drop(columns=["quality_status"], errors="ignore")
    full = full.join(build_row_quality(full, adjusted.issues))
    full["trade_date"] = full.index.strftime("%Y-%m-%d")
    output = full.loc[
        (full.index >= pd.Timestamp(output_start)) & (full.index <= pd.Timestamp(output_end))
    ].copy()
    if output.empty:
        raise IndicatorCalculationError("empty_range", "请求区间内没有行情")

    columns = _enabled_columns(config)
    coverage = indicator_coverage(output, columns)
    valid_rows = int((output["quality_status"] != "invalid").sum())
    missing_rows = int((output["quality_status"] == "invalid").sum())
    issues = list(adjusted.issues)
    if adjusted.expected_missing_dates:
        # adjust_prices 未传 calendar；这里单独计算日历缺口。
        actual_dates = set(raw["trade_date"].dt.date.astype(str))
        expected = [
            d for d in calendar if raw["trade_date"].min().date().isoformat() <= d <= raw["trade_date"].max().date().isoformat()
        ]
        missing_dates = [d for d in expected if d not in actual_dates]
        if missing_dates:
            issues.append(
                {
                    "type": "missing_trading_dates",
                    "severity": "warning",
                    "message": f"交易日历中存在但行情缺失的日期：{len(missing_dates)} 天",
                    "count": len(missing_dates),
                    "examples": missing_dates[:5],
                }
            )
    else:
        actual_dates = set(raw["trade_date"].dt.date.astype(str))
        expected = [
            d for d in calendar if raw["trade_date"].min().date().isoformat() <= d <= raw["trade_date"].max().date().isoformat()
        ]
        missing_dates = [d for d in expected if d not in actual_dates]
        if missing_dates:
            issues.append(
                {
                    "type": "missing_trading_dates",
                    "severity": "warning",
                    "message": f"交易日历中存在但行情缺失的日期：{len(missing_dates)} 天",
                    "count": len(missing_dates),
                    "examples": missing_dates[:5],
                }
            )
    if not calendar_available:
        issues.append(
            {
                "type": "calendar_unavailable",
                "severity": "warning",
                "message": "数据库没有交易日历，缺失日期只按实际行情序列判断",
            }
        )
    if not snapshot_is_current:
        issues.append(
            {
                "type": "snapshot_not_current",
                "severity": "warning",
                "message": f"计算快照 {snapshot_id} 不是当前快照 {current_snapshot_id}",
            }
        )

    if valid_rows == 0:
        status = "failed"
        reason = "no_valid_rows"
    elif missing_rows > 0 or not snapshot_is_current:
        status = "partial"
        reason = "quality_issues" if missing_rows > 0 else "snapshot_not_current"
    else:
        status = "success"
        reason = None
    summary = summarize_range(
        output,
        annualization=int(config["annualization"]),
        risk_free_rate=float(config["risk_free_rate"]),
    )
    summary.update(
        {
            "requested_start": start,
            "requested_end": end,
            "actual_start": output_start,
            "actual_end": output_end,
            "output_rows": int(len(output)),
            "valid_rows": valid_rows,
            "missing_rows": missing_rows,
            "calendar_available": calendar_available,
            "calendar_missing_dates": len(missing_dates),
        }
    )
    cagr_missing = int(summary.get("missing_trading_days", 0) or 0)
    if cagr_missing > 0:
        issues.append(
            {
                "type": "cagr_missing_trading_days",
                "severity": "warning",
                "message": f"CAGR 时间跨度内缺失 {cagr_missing} 个交易日，年化分母已计入",
                "count": cagr_missing,
            }
        )
    quality = {
        "issues": issues,
        "counts": quality_counts(output),
        "zero_volume_rows": int((output["trade_status"] == "zero_volume").sum()),
        "missing_volume_rows": int((output["trade_status"] == "missing_volume").sum()),
        "calendar_missing_dates": len(missing_dates),
        "cagr_missing_trading_days": cagr_missing,
        "cagr_span_trading_days": summary.get("span_trading_days"),
        "cagr_valid_price_days": summary.get("valid_price_days"),
        "snapshot_id": snapshot_id,
        "snapshot_is_current": snapshot_is_current,
        "coverage": coverage,
    }
    return IndicatorResult(
        etf_code=code,
        data=output,
        status=status,
        reason=reason,
        snapshot_id=snapshot_id,
        snapshot_is_current=snapshot_is_current,
        calculation_version=version,
        calculation_time=calc_time,
        run_id=run_id,
        config=config,
        summary=summary,
        quality=quality,
        valid_rows=valid_rows,
        missing_rows=missing_rows,
        coverage=coverage,
    )


def calculate_many(
    codes: Iterable[str],
    start_date: str | None = None,
    end_date: str | None = None,
    indicator_config: dict[str, Any] | None = None,
    *,
    db_path=None,
    today: date | None = None,
) -> tuple[list[IndicatorResult], list[dict[str, Any]]]:
    results: list[IndicatorResult] = []
    failures: list[dict[str, Any]] = []
    for code in codes:
        try:
            results.append(
                calculate_indicators(
                    code,
                    start_date,
                    end_date,
                    indicator_config,
                    db_path=db_path,
                    today=today,
                )
            )
        except Exception as exc:
            reason = getattr(exc, "reason", "unexpected_error")
            failures.append({"etf_code": str(code).zfill(6), "reason": reason, "message": str(exc)})
    return results, failures


def batch_exit_code(results: list[IndicatorResult], failures: list[dict[str, Any]], total: int) -> int:
    if total == 0 or (not results and failures):
        return 1
    if not failures and all(item.status == "success" for item in results):
        return 0
    return 2
