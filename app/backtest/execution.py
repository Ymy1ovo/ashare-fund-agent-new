"""成交价、涨跌停、整手与 T+N 可用性判断。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from app.backtest.config import BacktestConfig, InstrumentRule
from app.backtest.costs import slippage_price


@dataclass
class Quote:
    """一个交易日的可成交行情（原始价，未复权）。"""

    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    prev_close: float | None = None
    status: str = "ok"

    @classmethod
    def from_row(cls, trade_date: date, row: pd.Series, prev_close: float | None) -> "Quote":
        def _num(value) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return float("nan")

        return cls(
            trade_date=trade_date,
            open=_num(row.get("open")),
            high=_num(row.get("high")),
            low=_num(row.get("low")),
            close=_num(row.get("close")),
            volume=_num(row.get("volume")),
            prev_close=prev_close,
        )

    def tradable(self) -> tuple[bool, str]:
        if self.status != "ok":
            return False, self.status
        for name in ("open", "high", "low", "close"):
            value = getattr(self, name)
            if value is None or pd.isna(value) or value <= 0:
                return False, f"invalid_{name}"
        if pd.isna(self.volume) or self.volume <= 0:
            return False, "zero_volume" if not pd.isna(self.volume) else "missing_volume"
        if self.high < self.low or not (self.low <= self.open <= self.high):
            return False, "invalid_ohlc"
        return True, "ok"


def base_price(quote: Quote, config: BacktestConfig) -> float:
    """未加滑点的基准成交价。默认开盘，可配置收盘。"""
    return quote.open if config.execution_price == "open" else quote.close


def limit_prices(quote: Quote, rule: InstrumentRule) -> tuple[float | None, float | None]:
    """涨跌停价；缺少前收盘时不限制。"""
    if quote.prev_close is None or pd.isna(quote.prev_close) or quote.prev_close <= 0:
        return None, None
    up = quote.prev_close * (1 + rule.price_limit_pct)
    down = quote.prev_close * (1 - rule.price_limit_pct)
    return round(up, 4), round(down, 4)


def limit_blocked(quote: Quote, rule: InstrumentRule, side: str, price: float) -> str | None:
    """涨跌停导致的不可成交原因；可成交返回 None。

    保守规则：买入价 >= 涨停 视为买不到；卖出价 <= 跌停 视为卖不出。
    """
    up, down = limit_prices(quote, rule)
    if side == "buy" and up is not None and price >= up - 1e-9:
        return "limit_up_blocked"
    if side == "sell" and down is not None and price <= down + 1e-9:
        return "limit_down_blocked"
    return None


def fill_price(quote: Quote, side: str, rule: InstrumentRule, config: BacktestConfig) -> tuple[float, str | None]:
    """计算含滑点的成交价，并做涨跌停与区间约束。

    返回 (价格, 阻断原因)。价格被限制在当日 [low, high] 内，避免不真实成交。
    """
    raw = base_price(quote, config)
    slipped = slippage_price(raw, side, config.costs)
    up, down = limit_prices(quote, rule)
    if up is not None:
        slipped = min(slipped, up)
    if down is not None:
        slipped = max(slipped, down)
    slipped = min(max(slipped, quote.low), quote.high)
    blocked = limit_blocked(quote, rule, side, slipped)
    if blocked:
        return slipped, blocked
    return slipped, None


def available_date(fill_date: date, rule: InstrumentRule, calendar: list[date]) -> date:
    """T+N 可卖日；T+0 当日可卖。"""
    if rule.settlement_days == 0:
        return fill_date
    later = [day for day in calendar if day > fill_date]
    if not later:
        return fill_date + timedelta(days=7)
    index = min(rule.settlement_days - 1, len(later) - 1)
    return later[index]
