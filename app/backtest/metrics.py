"""回测绩效统计。

风险指标口径（阶段3A.1 修正）：
- 日收益按交易日索引计算，pct_change(fill_method=None)
- 缺失日保留 NaN，不压缩、不填充
- Sharpe/Sortino 使用「日均超额收益年化」，不再用 CAGR 当分子
- 持仓 ETF 缺有效报价的日期，日收益标记为不可用于风险统计
- 样本不足 / 分母为 0 返回 None，绝不输出无穷大
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from app.backtest.models import DailySnapshot, Order, Trade


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def max_drawdown(nav: pd.Series) -> float | None:
    clean = nav.dropna()
    if len(clean) < 2:
        return None
    peaks = clean.cummax()
    return _finite(float((clean / peaks - 1).min()))


def held_price_gap_days(daily: list[DailySnapshot]) -> set[date]:
    """返回「有实际持仓的 ETF 缺有效报价」的交易日。

    只统计当日持仓数量 > 0 的 ETF；未持仓 ETF 缺行情不影响组合风险统计。
    """
    gaps: set[date] = set()
    for item in daily:
        for code, quantity in item.positions.items():
            if not quantity:
                continue
            if item.price_status.get(code, "ok") != "ok":
                gaps.add(item.trade_date)
                break
    return gaps


def risk_return_series(
    daily: list[DailySnapshot],
) -> tuple[pd.Series, pd.Series, list[dict[str, Any]]]:
    """返回 (估值净值序列, 可用于风险统计的日收益序列, 逐日状态列表)。

    日收益在 t 日不可用的条件：
    - t 日或 t-1 日存在「持仓 ETF 缺有效报价」；
    - 净值本身为 NaN 或前一日为 0。
    缺口前后不把跨日收益伪装成单日收益：受影响的那一天直接置 NaN。
    """
    if not daily:
        return pd.Series(dtype=float), pd.Series(dtype=float), []

    index = pd.DatetimeIndex([pd.Timestamp(item.trade_date) for item in daily])
    nav = pd.Series([item.nav for item in daily], index=index, dtype=float)
    gaps = held_price_gap_days(daily)
    raw_returns = nav.pct_change(fill_method=None)
    usable = raw_returns.copy()

    statuses: list[dict[str, Any]] = []
    for position, item in enumerate(daily):
        if position == 0:
            status = "first_day"
            reason = "首个交易日没有前值，不产生日收益"
        elif item.trade_date in gaps:
            status = "held_price_gap"
            reason = "当日持仓 ETF 缺有效报价，估值不完整"
            usable.iloc[position] = np.nan
        elif daily[position - 1].trade_date in gaps:
            status = "prior_day_price_gap"
            reason = "前一交易日估值不完整，本日收益不可信"
            usable.iloc[position] = np.nan
        elif pd.isna(raw_returns.iloc[position]):
            status = "missing_nav"
            reason = "净值缺失或前值为 0"
            usable.iloc[position] = np.nan
        else:
            status = "ok"
            reason = ""
        statuses.append(
            {
                "trade_date": item.trade_date.isoformat(),
                "return_status": status,
                "return_reason": reason,
                "nav": item.nav,
                "raw_return": _finite(raw_returns.iloc[position]),
            }
        )
    return nav, usable.dropna(), statuses


def return_sample_stats(daily: list["DailySnapshot"]) -> dict:
    """统一的收益率样本统计口径。

    全项目只有这一处定义，报告与压力测试都必须调用它，避免出现
    「有效收益 256 / 269」这类互相矛盾的数字。

    定义（互斥且可加总）：

    - nav_days：每日快照总数
    - first_day：首个交易日没有前值，不产生日收益
    - held_price_gap：持仓 ETF 缺有效报价导致估值不完整
    - prior_day_price_gap：前一交易日估值不完整，本日收益不可信
    - missing_nav：净值缺失或前值为 0
    - valid_return_days：可用日收益数量

    恒等式：nav_days == first_day + held_price_gap + prior_day_price_gap
                       + missing_nav + valid_return_days
    """
    if not daily:
        return {
            "nav_days": 0,
            "first_day": 0,
            "held_price_gap": 0,
            "prior_day_price_gap": 0,
            "missing_nav": 0,
            "valid_return_days": 0,
            "excluded_days": 0,
            "identity_holds": True,
            "definition": "return-sample-stats-v1",
        }

    _, _, statuses = risk_return_series(daily)
    counts: dict[str, int] = {}
    for item in statuses:
        counts[item["return_status"]] = counts.get(item["return_status"], 0) + 1

    nav_days = len(statuses)
    first_day = counts.get("first_day", 0)
    held_gap = counts.get("held_price_gap", 0)
    prior_gap = counts.get("prior_day_price_gap", 0)
    missing_nav = counts.get("missing_nav", 0)
    valid = counts.get("ok", 0)
    excluded = held_gap + prior_gap + missing_nav

    return {
        "nav_days": nav_days,
        "first_day": first_day,
        "held_price_gap": held_gap,
        "prior_day_price_gap": prior_gap,
        "missing_nav": missing_nav,
        "valid_return_days": valid,
        "excluded_days": excluded,
        "identity_holds": nav_days == first_day + excluded + valid,
        "definition": "return-sample-stats-v1",
    }


@dataclass
class Performance:
    """回测绩效汇总。"""

    total_return: float | None = None
    cagr: float | None = None
    annualized_volatility: float | None = None
    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    calmar_ratio: float | None = None
    max_drawdown: float | None = None
    win_rate: float | None = None
    profit_loss_ratio: float | None = None
    trade_count: int = 0
    closed_trade_count: int = 0
    turnover: float | None = None
    total_cost: float = 0.0
    total_commission: float = 0.0
    total_slippage: float = 0.0
    average_holding_days: float | None = None
    capital_utilization: float | None = None
    annual_returns: dict[int, float] = field(default_factory=dict)
    trading_days: int = 0
    risk_sample_days: int = 0
    nav_days_with_price_gaps: int = 0
    gap_return_days_excluded: int = 0
    mean_daily_return: float | None = None
    mean_daily_excess: float | None = None
    downside_deviation: float | None = None
    daily_rf: float | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        payload = dict(self.__dict__)
        payload["annual_returns"] = {str(k): v for k, v in self.annual_returns.items()}
        return payload


def compute_performance(
    daily: list[DailySnapshot],
    trades: list[Trade],
    orders: list[Order],
    initial_cash: float,
    *,
    annualization: int = 252,
    risk_free_rate: float = 0.0,
) -> Performance:
    """从每日快照和成交流水计算绩效。

    Sharpe / Sortino 口径（标准日收益法）：
        daily_rf   = (1 + risk_free_rate) ** (1 / annualization) - 1
        excess_t   = r_t - daily_rf，只用可用日收益
        Sharpe     = mean(excess) * annualization / (std(r_t, ddof=1) * sqrt(annualization))
                   = mean(excess) * sqrt(annualization) / std(r_t, ddof=1)
        Sortino    = mean(excess) * annualization / downside_deviation
        downside_deviation = sqrt(mean(min(excess_t, 0)^2)) * sqrt(annualization)

    CAGR 仍单独计算，不作为 Sharpe/Sortino 分子。
    """
    result = Performance()
    if not daily:
        result.notes.append("没有每日快照")
        return result

    nav, returns, statuses = risk_return_series(daily)
    result.trading_days = len(nav)
    result.risk_sample_days = len(returns)
    if nav.empty or nav.iloc[0] == 0:
        result.notes.append("首日净值为 0，无法计算收益")
        return result

    total_return = float(nav.iloc[-1] / nav.iloc[0] - 1)
    result.total_return = _finite(total_return)

    # CAGR：与阶段2.1一致，使用交易日索引跨度，与日收益风险指标分开
    intervals = len(nav) - 1
    if intervals > 0 and nav.iloc[0] > 0:
        result.cagr = _finite((nav.iloc[-1] / nav.iloc[0]) ** (annualization / intervals) - 1)

    std = float(returns.std(ddof=1)) if len(returns) > 1 else float("nan")
    result.annualized_volatility = _finite(std * math.sqrt(annualization))
    result.mean_daily_return = _finite(returns.mean()) if len(returns) else None

    daily_rf = (1 + risk_free_rate) ** (1 / annualization) - 1
    result.daily_rf = _finite(daily_rf)
    excess = returns - daily_rf
    result.mean_daily_excess = _finite(excess.mean()) if len(excess) else None

    if result.mean_daily_excess is not None and math.isfinite(std) and std > 0:
        result.sharpe_ratio = _finite(
            result.mean_daily_excess * annualization / (std * math.sqrt(annualization))
        )

    if len(excess) > 1:
        downside = np.minimum(excess.to_numpy(dtype=float), 0.0)
        downside_dev = float(np.sqrt(np.mean(np.square(downside))) * math.sqrt(annualization))
        result.downside_deviation = _finite(downside_dev)
        if result.downside_deviation and result.downside_deviation > 0 and result.mean_daily_excess is not None:
            result.sortino_ratio = _finite(
                result.mean_daily_excess * annualization / result.downside_deviation
            )
        elif result.downside_deviation == 0:
            result.notes.append("下行波动率为 0（没有下跌日），Sortino 不可计算")
    else:
        result.notes.append("有效日收益不足 2 个，Sharpe/Sortino 不可计算")

    # 最大回撤使用估值净值序列；若当天估值依赖上一有效收盘，在报告中提示
    result.max_drawdown = max_drawdown(nav)
    if result.cagr is not None and result.max_drawdown not in (None, 0):
        result.calmar_ratio = _finite(result.cagr / abs(result.max_drawdown))

    excluded = [
        item for item in statuses
        if item["return_status"] in ("held_price_gap", "prior_day_price_gap")
    ]
    result.gap_return_days_excluded = len(excluded)
    all_gap_days = sorted({
        item["trade_date"] for item in statuses
        if item["return_status"] == "held_price_gap"
    })
    result.nav_days_with_price_gaps = len(all_gap_days)
    if excluded:
        result.notes.append(
            f"{len(excluded)} 个日收益因持仓 ETF 估值不完整被排除在风险统计外"
            f"（区间 {excluded[0]['trade_date']} ~ {excluded[-1]['trade_date']}）"
        )

    sells = [trade for trade in trades if trade.side == "sell"]
    result.trade_count = len(trades)
    result.closed_trade_count = len(sells)
    if sells:
        wins = [trade.realized_pnl for trade in sells if trade.realized_pnl > 0]
        losses = [trade.realized_pnl for trade in sells if trade.realized_pnl < 0]
        result.win_rate = _finite(len(wins) / len(sells))
        if losses and wins:
            result.profit_loss_ratio = _finite(
                (sum(wins) / len(wins)) / abs(sum(losses) / len(losses))
            )
        holding = [trade.holding_days for trade in sells if trade.holding_days is not None]
        if holding:
            result.average_holding_days = _finite(float(np.mean(holding)))

    result.total_commission = float(sum(trade.commission for trade in trades))
    result.total_slippage = float(sum(trade.slippage_cost for trade in trades))
    result.total_cost = result.total_commission + result.total_slippage

    traded_notional = float(sum(trade.gross_amount for trade in trades))
    average_assets = float(np.mean([item.total_assets for item in daily])) if daily else 0.0
    if average_assets > 0 and intervals > 0:
        result.turnover = _finite(traded_notional / average_assets)

    if average_assets > 0:
        utilization = float(np.mean([
            item.market_value / item.total_assets if item.total_assets > 0 else 0.0
            for item in daily
        ]))
        result.capital_utilization = _finite(utilization)

    by_year: dict[int, list[float]] = defaultdict(list)
    for item in daily:
        by_year[item.trade_date.year].append(item.nav)
    for year, values in sorted(by_year.items()):
        if len(values) >= 2 and values[0] > 0:
            result.annual_returns[year] = float(values[-1] / values[0] - 1)

    unfilled = [order for order in orders if order.status in ("unfilled", "expired", "rejected", "partial")]
    if unfilled:
        result.notes.append(f"{len(unfilled)} 笔订单未完全成交（拒绝/过期/未触发/部分成交）")
    return result


def yearly_table(daily: list[DailySnapshot]) -> list[dict[str, Any]]:
    """年度收益明细。"""
    grouped: dict[int, list[DailySnapshot]] = defaultdict(list)
    for item in daily:
        grouped[item.trade_date.year].append(item)
    rows = []
    previous_end: float | None = None
    for year, items in sorted(grouped.items()):
        # 年度收益以上一年最后一个净值为起点；首年才用当年首个净值。
        start_nav = previous_end if previous_end is not None else items[0].nav
        end_nav = items[-1].nav
        rows.append(
            {
                "year": year,
                "start_nav": start_nav,
                "end_nav": end_nav,
                "return": float(end_nav / start_nav - 1) if start_nav else None,
                "days": len(items),
            }
        )
        previous_end = end_nav
    return rows


def reconcile(
    daily: list[DailySnapshot], trades: list[Trade], initial_cash: float
) -> dict[str, Any]:
    """账本核对：现金 + 持仓市值 = 总资产；期初现金推演 = 期末现金。"""
    errors: list[str] = []
    for item in daily:
        expected = item.cash + item.market_value
        if abs(expected - item.total_assets) > 1e-6:
            errors.append(
                f"{item.trade_date} 总资产不一致：cash+mv={expected:.4f} vs {item.total_assets:.4f}"
            )
        if item.cash < -1e-6:
            errors.append(f"{item.trade_date} 现金为负：{item.cash:.4f}")
    if daily:
        cash_flow = 0.0
        for trade in trades:
            sign = -1 if trade.side == "buy" else 1
            # 现金变动 = 成交金额 - 全部交易费用（佣金 + 印花税 + 过户费）
            cash_flow += sign * trade.gross_amount - trade.total_fees
        expected_cash = initial_cash + cash_flow
        if abs(expected_cash - daily[-1].cash) > 1e-4:
            errors.append(
                f"期末现金推演不一致：{expected_cash:.4f} vs {daily[-1].cash:.4f}"
            )
    for trade in trades:
        if trade.quantity <= 0:
            errors.append(f"成交数量非正：trade={trade.trade_id}")
        if trade.commission < 0 or trade.slippage_cost < 0:
            errors.append(f"成交成本为负：trade={trade.trade_id}")
        if trade.stamp_tax < 0 or trade.transfer_fee < 0:
            errors.append(f"交易税费为负：trade={trade.trade_id}")
    return {"ok": not errors, "errors": errors}
