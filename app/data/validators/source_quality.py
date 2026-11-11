"""数据源返回质量评估，与采集调用状态分离。"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

STALE_DAYS = 15


def assess_quality(
    df: pd.DataFrame,
    *,
    date_column: str | None,
    price_column: str | None,
    time_series: bool,
    today: date | None = None,
) -> tuple[str, list[str]]:
    """返回 (passed/warning/failed, 问题列表)。

    - failed：空表、缺关键列、无有效日期、未来日期、价格列全部无效；
    - warning：少量无效日期/价格、重复日期、日期偏旧；
    - passed：未发现问题。
    """
    today = today or date.today()
    issues: list[str] = []
    critical = False

    if df is None or df.empty:
        return "failed", ["empty_dataframe"]
    if date_column and date_column not in df.columns:
        return "failed", [f"missing_date_column:{date_column}"]
    if price_column and price_column not in df.columns:
        issues.append(f"missing_price_column:{price_column}")
        critical = True

    if date_column:
        parsed = pd.to_datetime(df[date_column], errors="coerce")
        invalid_dates = int(parsed.isna().sum())
        if invalid_dates:
            issues.append(f"invalid_dates:{invalid_dates}")
        valid_dates = parsed.dropna()
        if valid_dates.empty:
            issues.append("no_valid_dates")
            critical = True
        else:
            latest_date = valid_dates.max().date()
            future = int((valid_dates > pd.Timestamp(today)).sum())
            if future:
                issues.append(f"future_dates:{future}")
                critical = True
            if time_series:
                duplicate_dates = int(valid_dates.duplicated().sum())
                if duplicate_dates:
                    issues.append(f"duplicate_dates:{duplicate_dates}")
            if latest_date < today - timedelta(days=STALE_DAYS):
                issues.append(f"latest_date_stale:{latest_date.isoformat()}")

    if price_column and price_column in df.columns:
        prices = pd.to_numeric(df[price_column], errors="coerce")
        valid_prices = prices.notna() & (prices > 0)
        invalid_prices = int((~valid_prices).sum())
        if invalid_prices:
            issues.append(f"nonpositive_or_invalid_prices:{invalid_prices}")
            if int(valid_prices.sum()) == 0:
                critical = True

    if critical:
        return "failed", issues
    return ("warning", issues) if issues else ("passed", issues)
