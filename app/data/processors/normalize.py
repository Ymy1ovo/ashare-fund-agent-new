"""字段清洗与标准化工具。"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import pandas as pd

_CODE_PATTERN = re.compile(r"(\d{6})")
_DATE_CLEAN_PATTERN = re.compile(r"[年月/]")

HISTORY_COLUMNS = ["trade_date", "open", "high", "low", "close", "volume", "amount"]


def normalize_code(value: Any) -> str:
    """把 sh510300 / 510300.0 等写法统一为六位数字代码。"""
    if value is None:
        return ""
    text = str(value).strip()
    match = _CODE_PATTERN.search(text)
    if match:
        return match.group(1)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2].zfill(6)
    return text.zfill(6) if text.isdigit() else ""


def parse_date(value: Any) -> date | None:
    """把多种日期写法解析为 date；无法解析时返回 None，不猜测。"""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or text in {"-", "--", "nan", "NaT", "None"}:
        return None
    text = text.split(" ")[0].split("T")[0]
    text = _DATE_CLEAN_PATTERN.sub("-", text).replace("日", "")
    text = re.sub(r"-+", "-", text).strip("-")
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y-%m", "%Y"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.date()
        except ValueError:
            continue
    parsed = pd.to_datetime(text, errors="coerce")
    return None if pd.isna(parsed) else parsed.date()


def _valid_dates(df: pd.DataFrame, date_column: str, today: date | None = None) -> pd.Series:
    if df is None or df.empty or date_column not in df.columns:
        return pd.Series(dtype="datetime64[ns]")
    parsed = pd.to_datetime(df[date_column], errors="coerce").dropna()
    cutoff = pd.Timestamp(today or date.today())
    return parsed.loc[parsed <= cutoff]


def first_trade_date(df: pd.DataFrame, date_column: str = "日期") -> date | None:
    """返回最早有效交易日；只依赖日期列，不要求收盘价。"""
    dates = _valid_dates(df, date_column)
    return None if dates.empty else dates.min().date()


def latest_trade_date(df: pd.DataFrame, date_column: str = "日期") -> date | None:
    """返回最近有效交易日；只依赖日期列，不要求收盘价。"""
    dates = _valid_dates(df, date_column)
    return None if dates.empty else dates.max().date()


@dataclass
class HistoryCleanResult:
    """行情清洗结果，保留被过滤行数以便质量审计。"""

    data: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=HISTORY_COLUMNS))
    input_rows: int = 0
    invalid_date_rows: int = 0
    invalid_close_rows: int = 0
    future_rows: int = 0
    duplicate_rows: int = 0
    duplicate_conflict_rows: int = 0
    missing_columns: list[str] = field(default_factory=list)

    @property
    def dropped_rows(self) -> int:
        return self.invalid_date_rows + self.invalid_close_rows + self.future_rows + self.duplicate_rows


def clean_history(df: pd.DataFrame, today: date | None = None) -> HistoryCleanResult:
    """标准化历史日线。

    - 同一行内同时校验日期与收盘价；
    - 删除无效日期、无效收盘价、未来日期；
    - 按日期升序排序；
    - 同一天重复时保留排序后的最后一条，并记录冲突数量。
    """
    empty = pd.DataFrame(columns=HISTORY_COLUMNS)
    if df is None or df.empty:
        return HistoryCleanResult(data=empty)

    mapping = {
        "日期": "trade_date",
        "trade_date": "trade_date",
        "开盘": "open",
        "open": "open",
        "收盘": "close",
        "close": "close",
        "最高": "high",
        "high": "high",
        "最低": "low",
        "low": "low",
        "成交量": "volume",
        "volume": "volume",
        "成交额": "amount",
        "amount": "amount",
    }
    result = df.rename(columns={k: v for k, v in mapping.items() if k in df.columns}).copy()
    missing_columns = [column for column in ("trade_date", "close") if column not in result.columns]
    if missing_columns:
        return HistoryCleanResult(
            data=empty,
            input_rows=len(df),
            missing_columns=missing_columns,
        )

    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce")
    invalid_date = result["trade_date"].isna()
    invalid_date_rows = int(invalid_date.sum())
    result = result.loc[~invalid_date].copy()

    result["close"] = pd.to_numeric(result["close"], errors="coerce")
    invalid_close = result["close"].isna() | (result["close"] <= 0)
    invalid_close_rows = int(invalid_close.sum())
    result = result.loc[~invalid_close].copy()

    cutoff = pd.Timestamp(today or date.today())
    future = result["trade_date"] > cutoff
    future_rows = int(future.sum())
    result = result.loc[~future].copy()

    for column in ("open", "high", "low", "volume", "amount"):
        if column in result.columns:
            result[column] = pd.to_numeric(result[column], errors="coerce")
        else:
            result[column] = pd.NA

    result = result.sort_values("trade_date", kind="mergesort").reset_index(drop=True)
    before_dedup = len(result)
    duplicate_mask = result.duplicated(subset=["trade_date"], keep="last")
    duplicate_rows = int(duplicate_mask.sum())
    duplicate_conflict_rows = 0
    if duplicate_rows:
        # 同一天存在多行且收盘价不同，属于数据源冲突；仍只保留最后一条并显式记录。
        conflicting = result.groupby("trade_date")["close"].nunique(dropna=True)
        duplicate_conflict_rows = int((conflicting > 1).sum())
    result = result.loc[~duplicate_mask].copy()
    result = result[["trade_date", "open", "high", "low", "close", "volume", "amount"]]
    result = result.reset_index(drop=True)

    return HistoryCleanResult(
        data=result,
        input_rows=len(df),
        invalid_date_rows=invalid_date_rows,
        invalid_close_rows=invalid_close_rows,
        future_rows=future_rows,
        duplicate_rows=duplicate_rows,
        duplicate_conflict_rows=duplicate_conflict_rows,
        missing_columns=missing_columns,
    )


def normalize_history(df: pd.DataFrame) -> pd.DataFrame:
    """将 ETF/指数日线统一为英文列，并完成清洗与排序。"""
    return clean_history(df).data


def latest_valid_bar(df: pd.DataFrame, today: date | None = None) -> tuple[date | None, float | None]:
    """返回最后一条同时具有有效日期和有效收盘价的记录。

    先排序再去最后一条，避免乱序数据用 iloc[-1] 取错日期或价格。
    """
    cleaned = clean_history(df, today=today)
    if cleaned.data.empty:
        return None, None
    last = cleaned.data.iloc[-1]
    return last["trade_date"].date(), float(last["close"])


def json_safe(value: Any) -> Any:
    """把 pandas/numpy 标量转为可 JSON 序列化的值。"""
    if value is None:
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def dataframe_preview(df: pd.DataFrame, rows: int = 3) -> list[dict[str, Any]]:
    """返回 DataFrame 的少量样本，NaN 转为 None。"""
    if df is None or df.empty:
        return []
    sample = df.head(rows).copy()
    return [{str(k): json_safe(v) for k, v in record.items()} for record in sample.to_dict("records")]
