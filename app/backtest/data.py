"""回测数据读取：行情、日历、指标版本、快照。"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from app.database.db import get_connection


class BacktestDataError(RuntimeError):
    """行情或快照不满足回测条件。"""


@dataclass
class BarData:
    """一只 ETF 的原始行情。"""

    code: str
    frame: pd.DataFrame            # index=date, 原始 open/high/low/close/volume
    adjusted_close: pd.Series      # 与 frame 同索引
    snapshot_id: int
    indicator_version: str | None
    indicator_frame: pd.DataFrame | None


def load_calendar(start_date: str, end_date: str, db_path=None) -> list[date]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT trade_date FROM trade_calendar WHERE trade_date >= ? AND trade_date <= ? "
            "ORDER BY trade_date",
            (start_date, end_date),
        ).fetchall()
    return [date.fromisoformat(str(row[0])) for row in rows]


def load_pool(db_path=None) -> dict[str, dict[str, Any]]:
    with get_connection(db_path) as conn:
        return {str(row["code"]): dict(row) for row in conn.execute("SELECT * FROM etf_pool")}


def load_bars(
    code: str,
    start_date: str,
    end_date: str,
    *,
    indicator_version: str | None = None,
    db_path=None,
) -> BarData:
    with get_connection(db_path) as conn:
        frame = pd.read_sql_query(
            """
            SELECT trade_date, open, high, low, close, volume, amount,
                   adjusted_close, adjustment_snapshot_id
            FROM etf_daily_prices
            WHERE code = ? AND trade_date >= ? AND trade_date <= ?
            ORDER BY trade_date
            """,
            conn,
            params=(code, start_date, end_date),
        )
        snapshot_ids = {
            int(value)
            for value in frame["adjustment_snapshot_id"].dropna().unique()
        } if not frame.empty else set()
        if frame.empty:
            raise BacktestDataError(f"{code} 在 {start_date}~{end_date} 没有行情")
        if len(snapshot_ids) > 1:
            raise BacktestDataError(
                f"{code} 混合了多个复权快照 {sorted(snapshot_ids)}，拒绝回测"
            )
        snapshot_id = snapshot_ids.pop() if snapshot_ids else 0
        indicator_frame = None
        resolved_version = indicator_version
        if indicator_version == "latest":
            row = conn.execute(
                "SELECT calculation_version FROM etf_indicator_daily WHERE etf_code=? "
                "ORDER BY created_at DESC LIMIT 1",
                (code,),
            ).fetchone()
            resolved_version = str(row[0]) if row else None
        if resolved_version:
            indicator_frame = pd.read_sql_query(
                "SELECT * FROM etf_indicator_daily WHERE etf_code=? AND calculation_version=? "
                "AND trade_date >= ? AND trade_date <= ? ORDER BY trade_date",
                conn,
                params=(code, resolved_version, start_date, end_date),
            )
            if indicator_frame.empty:
                raise BacktestDataError(
                    f"{code} 没有指标版本 {resolved_version} 的数据"
                )
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    frame = frame.set_index("trade_date").sort_index()
    for column in ("open", "high", "low", "close", "volume", "amount"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    adjusted = pd.to_numeric(frame["adjusted_close"], errors="coerce")
    bars = frame[["open", "high", "low", "close", "volume", "amount", "adjustment_snapshot_id"]].copy()
    if indicator_frame is not None:
        indicator_frame["trade_date"] = pd.to_datetime(indicator_frame["trade_date"]).dt.date
        indicator_frame = indicator_frame.set_index("trade_date").sort_index()
    return BarData(
        code=code,
        frame=bars,
        adjusted_close=adjusted,
        snapshot_id=snapshot_id,
        indicator_version=resolved_version,
        indicator_frame=indicator_frame,
    )


def tradable(row: pd.Series | None, code: str) -> tuple[bool, str]:
    """判断当日是否可成交，返回 (可交易, 原因)。"""
    if row is None:
        return False, "missing_quote"
    required = ("open", "high", "low", "close")
    for column in required:
        value = row.get(column)
        if value is None or pd.isna(value) or float(value) <= 0:
            return False, f"invalid_{column}"
    volume = row.get("volume")
    if volume is None or pd.isna(volume):
        return False, "missing_volume"
    if float(volume) <= 0:
        return False, "zero_volume"
    high, low, open_price = float(row["high"]), float(row["low"]), float(row["open"])
    if high < low or open_price > high or open_price < low:
        return False, "invalid_ohlc"
    return True, "ok"


def indicator_snapshot_ids(code: str, version: str, db_path=None) -> set[int]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT adjustment_snapshot_id FROM etf_indicator_daily "
            "WHERE etf_code=? AND calculation_version=?",
            (code, version),
        ).fetchall()
    return {int(row[0]) for row in rows if row[0] is not None}
