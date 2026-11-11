"""指标输入与行级数据质量。"""
from __future__ import annotations

from typing import Any

import pandas as pd


def build_row_quality(frame: pd.DataFrame, price_issues: list[dict[str, Any]]) -> pd.DataFrame:
    reasons: list[list[str]] = []
    statuses: list[str] = []
    for _, row in frame.iterrows():
        row_reasons: list[str] = []
        if not bool(row.get("data_present", False)):
            row_reasons.append("missing_ohlc")
        raw_reason = row.get("price_reasons")
        if isinstance(raw_reason, str) and raw_reason:
            row_reasons.extend(raw_reason.split(";"))
        trade_status = row.get("trade_status")
        if trade_status == "zero_volume":
            row_reasons.append("zero_volume")
        elif trade_status == "missing_volume":
            row_reasons.append("missing_volume")
        if row_reasons:
            invalid = any(
                reason in {
                    "invalid_date",
                    "duplicate_date",
                    "future_date",
                    "raw_ohlc_invalid",
                    "adjusted_close_missing",
                    "adjustment_factor_invalid",
                    "adjusted_ohlc_invalid",
                    "missing_ohlc",
                }
                for reason in row_reasons
            )
            status = "invalid" if invalid else "warning"
        else:
            status = "valid"
        reasons.append(sorted(set(row_reasons)))
        statuses.append(status)
    result = pd.DataFrame(index=frame.index)
    result["quality_status"] = statuses
    result["quality_reasons"] = [";".join(items) if items else None for items in reasons]
    return result


def indicator_coverage(frame: pd.DataFrame, columns: list[str]) -> dict[str, dict[str, Any]]:
    total = len(frame)
    result: dict[str, dict[str, Any]] = {}
    for column in columns:
        if column not in frame.columns:
            continue
        valid = int(frame[column].notna().sum())
        result[column] = {
            "valid_rows": valid,
            "total_rows": total,
            "coverage": round(valid / total, 6) if total else 0.0,
        }
    return result


def quality_counts(frame: pd.DataFrame) -> dict[str, int]:
    if "quality_status" not in frame.columns:
        return {}
    counts = frame["quality_status"].value_counts().to_dict()
    return {str(key): int(value) for key, value in counts.items()}
