"""阶段3A.3.1 归因计算（只读）。

全部函数都是纯计算：输入是既有 BacktestResult 的 daily / trades / orders，
输出是可核验的字典。不访问数据库、不写文件、不修改任何历史记录。

核心口径（净值变动分解，恒等式可逐日核对）：

    Δ总资产_t = Σ_c q_{c,t-1} × (p_{c,t} - p_{c,t-1})          # 持有收益
              + Σ_c (q_{c,t} - q_{c,t-1}) × (p_{c,t} - fill_{c,t})  # 交易执行价差
              - Σ fees_t                                       # 佣金+印花税+过户费

三条注意：
1. 滑点已经体现在 fill 价里，**不能**再单列进 fees，否则重复计算；
2. 残差必须接近 0，否则说明口径有遗漏，结论暂停；
3. 费用只统计 trade.commission/stamp_tax/transfer_fee，与 metrics 模块一致。
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable

import numpy as np
import pandas as pd

DECOMPOSITION_DEFINITION = "nav-decomposition-v1"
BEHAVIOUR_DEFINITION = "trade-behaviour-v1"
RISK_DEFINITION = "risk-metrics-v1"


def _safe_div(numerator: float, denominator: float) -> float | None:
    if denominator is None or denominator == 0 or not math.isfinite(denominator):
        return None
    value = numerator / denominator
    return value if math.isfinite(value) else None


def _round(value: float | None, digits: int = 6) -> float | None:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return None
    return round(float(value), digits)


def _trades_by_day_code(trades: Iterable) -> dict[tuple, dict]:
    """把成交按 (日期, 代码) 聚合，得到带方向的净数量、成交额与费用。"""
    bucket: dict[tuple, dict] = {}
    for trade in trades:
        key = (trade.trade_date, trade.code)
        item = bucket.setdefault(
            key,
            {
                "signed_qty": 0, "abs_qty": 0, "notional": 0.0, "signed_notional": 0.0,
                "commission": 0.0, "stamp_tax": 0.0, "transfer_fee": 0.0,
                "slippage_cost": 0.0, "fills": 0,
            },
        )
        sign = 1 if trade.side == "buy" else -1
        item["signed_qty"] += sign * int(trade.quantity)
        item["abs_qty"] += int(trade.quantity)
        item["notional"] += float(trade.gross_amount)
        # 买入与卖出可能落在同一天同一标的，成交价不同：
        # 执行价差必须按「逐笔带符号成交额」累计，不能用混合均价
        # （混合均价会在同向净变化里引入残差，实测 2026-10-09 差 15.56 元）。
        item["signed_notional"] += sign * float(trade.gross_amount)
        item["commission"] += float(trade.commission)
        item["stamp_tax"] += float(trade.stamp_tax)
        item["transfer_fee"] += float(trade.transfer_fee)
        item["slippage_cost"] += float(trade.slippage_cost)
        item["fills"] += 1
    for item in bucket.values():
        qty = item["abs_qty"]
        item["avg_fill_price"] = item["notional"] / qty if qty else None
        item["fees"] = item["commission"] + item["stamp_tax"] + item["transfer_fee"]
    return bucket


def decompose_nav(daily: list, trades: list) -> dict:
    """按恒等式把每日净值变动拆成 持有收益 / 交易价差 / 费用。"""
    if not daily:
        return {
            "definition": DECOMPOSITION_DEFINITION,
            "rows": [], "totals": {}, "per_code": {},
            "identity_ok": False, "note": "没有每日快照",
        }

    fills = _trades_by_day_code(trades)
    by_day_fees: dict = defaultdict(float)
    for (day, _code), item in fills.items():
        by_day_fees[day] += item["fees"]

    rows: list[dict] = []
    totals = defaultdict(float)
    per_code: dict[str, dict] = defaultdict(
        lambda: {"holding_pnl": 0.0, "exec_gap": 0.0,
                 "buy_notional": 0.0, "sell_notional": 0.0}
    )
    max_residual = 0.0
    anomalies: list[str] = []

    for index in range(1, len(daily)):
        prev = daily[index - 1]
        cur = daily[index]
        codes = set(prev.positions) | set(cur.positions)
        holding = 0.0
        exec_gap = 0.0
        for code in sorted(codes):
            q0 = int(prev.positions.get(code, 0))
            q1 = int(cur.positions.get(code, 0))
            p0 = prev.prices.get(code)
            p1 = cur.prices.get(code)
            if p0 is None or p1 is None:
                if q0 or q1:
                    anomalies.append(f"{cur.trade_date} {code} 缺估值价格")
                continue
            delta_pnl = q0 * (float(p1) - float(p0))
            holding += delta_pnl
            per_code[code]["holding_pnl"] += delta_pnl

            delta_qty = q1 - q0
            if delta_qty:
                item = fills.get((cur.trade_date, code))
                if item is None or item["avg_fill_price"] is None:
                    anomalies.append(
                        f"{cur.trade_date} {code} 数量变化 {delta_qty} 但无成交记录"
                    )
                    continue
                # 逐笔口径：Σ sign×qty×(p1 - fill) == delta_qty×p1 - Σ sign×gross
                gap = delta_qty * float(p1) - float(item["signed_notional"])
                exec_gap += gap
                per_code[code]["exec_gap"] += gap
                if delta_qty > 0:
                    per_code[code]["buy_notional"] += item["notional"]
                else:
                    per_code[code]["sell_notional"] += item["notional"]

        fees = float(by_day_fees.get(cur.trade_date, 0.0))
        delta_na = float(cur.total_assets) - float(prev.total_assets)
        explained = holding + exec_gap - fees
        residual = delta_na - explained
        max_residual = max(max_residual, abs(residual))
        rows.append({
            "trade_date": cur.trade_date.isoformat(),
            "delta_total_assets": _round(delta_na, 4),
            "holding_pnl": _round(holding, 4),
            "exec_gap": _round(exec_gap, 4),
            "fees": _round(fees, 4),
            "residual": _round(residual, 6),
        })
        totals["delta_total_assets"] += delta_na
        totals["holding_pnl"] += holding
        totals["exec_gap"] += exec_gap
        totals["fees"] += fees

    return {
        "definition": DECOMPOSITION_DEFINITION,
        "rows": rows,
        "totals": {key: _round(value, 4) for key, value in totals.items()},
        "per_code": {
            code: {key: _round(value, 4) for key, value in item.items()}
            for code, item in sorted(per_code.items())
        },
        "max_abs_residual": _round(max_residual, 8),
        "identity_ok": max_residual < 0.01,
        "anomalies": anomalies[:20],
        "anomaly_count": len(anomalies),
        "note": "滑点已含在成交价中，fees 只算佣金+印花税+过户费，避免重复计入",
    }


def cost_breakdown(trades: list, *, initial_cash: float,
                   gross_profit: float | None = None) -> dict:
    """成本拆分：只统计真实成交记录上的费用字段。"""
    total_commission = float(sum(trade.commission for trade in trades))
    total_stamp = float(sum(trade.stamp_tax for trade in trades))
    total_transfer = float(sum(trade.transfer_fee for trade in trades))
    total_slippage = float(sum(trade.slippage_cost for trade in trades))
    total_trade_fees = total_commission + total_stamp + total_transfer
    total_cost = total_trade_fees + total_slippage

    def _side(pool: list) -> dict:
        fees = float(sum(trade.total_fees for trade in pool))
        slippage = float(sum(trade.slippage_cost for trade in pool))
        notional = float(sum(trade.gross_amount for trade in pool))
        count = len(pool)
        return {
            "trade_count": count,
            "notional": _round(notional, 2),
            "fees": _round(fees, 4),
            "slippage": _round(slippage, 4),
            "total_cost": _round(fees + slippage, 4),
            "avg_cost_per_trade": _round((fees + slippage) / count, 4) if count else None,
        }

    return {
        "definition": "cost-breakdown-v1",
        "trade_count": len(trades),
        "commission": _round(total_commission, 4),
        "stamp_tax": _round(total_stamp, 4),
        "transfer_fee": _round(total_transfer, 4),
        "slippage": _round(total_slippage, 4),
        "trade_fees": _round(total_trade_fees, 4),
        "total_cost": _round(total_cost, 4),
        "avg_cost_per_trade": _round(total_cost / len(trades), 4) if trades else None,
        "cost_over_initial_cash": (
            _round(total_cost / initial_cash, 6) if initial_cash else None
        ),
        "cost_over_gross_profit": (
            _round(_safe_div(total_cost, gross_profit), 6)
            if gross_profit else None
        ),
        "fee_share_of_cost": _round(_safe_div(total_trade_fees, total_cost), 6),
        "slippage_share_of_cost": _round(_safe_div(total_slippage, total_cost), 6),
        "buy": _side([trade for trade in trades if trade.side == "buy"]),
        "sell": _side([trade for trade in trades if trade.side == "sell"]),
        "note": "ETF 默认免印花税，stamp_tax 与 transfer_fee 为 0 是配置结果而非缺失",
    }


def trade_behaviour(daily: list, trades: list) -> dict:
    """交易频率、持仓时长、换手、空仓与现金占比。"""
    buys = [trade for trade in trades if trade.side == "buy"]
    sells = [trade for trade in trades if trade.side == "sell"]

    holding_days = [
        float(trade.holding_days) for trade in sells
        if trade.holding_days is not None
    ]
    per_code_trades: dict[str, int] = defaultdict(int)
    per_code_round_trips: dict[str, int] = defaultdict(int)
    for trade in trades:
        per_code_trades[trade.code] += 1
        if trade.side == "sell":
            per_code_round_trips[trade.code] += 1

    exposure: list[float] = []
    cash_ratio: list[float] = []
    flat_days = 0
    longest_flat = 0
    current_flat = 0
    for item in daily:
        total = float(item.total_assets)
        market = float(item.market_value)
        ratio = market / total if total > 0 else 0.0
        exposure.append(ratio)
        cash_ratio.append(1.0 - ratio)
        if market <= 1e-9:
            flat_days += 1
            current_flat += 1
            longest_flat = max(longest_flat, current_flat)
        else:
            current_flat = 0

    traded_notional = float(sum(trade.gross_amount for trade in trades))
    average_assets = (
        float(np.mean([item.total_assets for item in daily])) if daily else 0.0
    )
    quick = [trade for trade in sells
             if trade.holding_days is not None and trade.holding_days <= 5]

    return {
        "definition": BEHAVIOUR_DEFINITION,
        "buy_count": len(buys),
        "sell_count": len(sells),
        "total_trades": len(trades),
        "closed_round_trips": len(sells),
        "avg_holding_days": _round(float(np.mean(holding_days)), 4) if holding_days else None,
        "median_holding_days": _round(float(np.median(holding_days)), 4) if holding_days else None,
        "max_holding_days": _round(max(holding_days), 4) if holding_days else None,
        "min_holding_days": _round(min(holding_days), 4) if holding_days else None,
        "holding_within_5_days": len(quick),
        "holding_within_5_days_ratio": _round(_safe_div(len(quick), len(sells))),
        "turnover_total": _round(_safe_div(traded_notional, average_assets), 4),
        "traded_notional": _round(traded_notional, 2),
        "avg_exposure": _round(float(np.mean(exposure)), 6) if exposure else None,
        "median_exposure": _round(float(np.median(exposure)), 6) if exposure else None,
        "avg_cash_ratio": _round(float(np.mean(cash_ratio)), 6) if cash_ratio else None,
        "flat_days": flat_days,
        "flat_days_ratio": _round(_safe_div(flat_days, len(daily))),
        "longest_flat_run": longest_flat,
        "trading_days": len(daily),
        "per_code_trades": dict(sorted(per_code_trades.items())),
        "per_code_round_trips": dict(sorted(per_code_round_trips.items())),
    }


def contribution_ranking(decomposition: dict) -> dict:
    """按标的口径汇总持有收益 + 交易价差，给出贡献排名与集中度。"""
    per_code = decomposition.get("per_code", {})
    if not per_code:
        return {"definition": "contribution-v1", "rows": []}

    rows = []
    for code, item in per_code.items():
        total = float(item.get("holding_pnl") or 0.0) + float(item.get("exec_gap") or 0.0)
        rows.append({"code": code, "total_pnl": total, **item})
    rows.sort(key=lambda entry: entry["total_pnl"], reverse=True)

    positive = sum(entry["total_pnl"] for entry in rows if entry["total_pnl"] > 0)
    negative = sum(entry["total_pnl"] for entry in rows if entry["total_pnl"] < 0)
    total = positive + negative
    top5 = sum(entry["total_pnl"] for entry in rows[:5])
    top5_positive = sum(entry["total_pnl"] for entry in rows[:5] if entry["total_pnl"] > 0)

    return {
        "definition": "contribution-v1",
        "rows": [
            {
                "code": entry["code"],
                "total_pnl": _round(entry["total_pnl"], 2),
                "holding_pnl": _round(float(entry.get("holding_pnl") or 0.0), 2),
                "exec_gap": _round(float(entry.get("exec_gap") or 0.0), 2),
                "buy_notional": _round(float(entry.get("buy_notional") or 0.0), 2),
                "sell_notional": _round(float(entry.get("sell_notional") or 0.0), 2),
            }
            for entry in rows
        ],
        "top5_pnl": _round(top5, 2),
        "top5_share_of_total": _round(_safe_div(top5, total)),
        "top5_share_of_positive": _round(_safe_div(top5_positive, positive)),
        "positive_sum": _round(positive, 2),
        "negative_sum": _round(negative, 2),
        "total": _round(total, 2),
        "positive_count": sum(1 for entry in rows if entry["total_pnl"] > 0),
        "negative_count": sum(1 for entry in rows if entry["total_pnl"] < 0),
        "best": rows[0]["code"] if rows else None,
        "worst": rows[-1]["code"] if rows else None,
    }


def drawdown_profile(nav: pd.Series) -> dict:
    """最大回撤区间与最长水下时间（基于估值净值序列，不压缩缺失日）。"""
    if nav is None or nav.empty:
        return {"definition": RISK_DEFINITION, "max_drawdown": None, "recovered": None}

    values = nav.astype(float)
    running_max = values.cummax()
    drawdown = values / running_max - 1.0
    trough_date = drawdown.idxmin()
    max_dd = float(drawdown.min())

    peak_date = values.loc[:trough_date].idxmax()
    peak_value = float(values.loc[peak_date])
    after = values.loc[trough_date:]
    candidates = after[after >= peak_value]
    recovered = not candidates.empty
    recovery_date = candidates.index[0] if recovered else None

    def _days(start, end) -> int | None:
        if start is None or end is None:
            return None
        return int((pd.Timestamp(end) - pd.Timestamp(start)).days)

    longest_underwater = 0
    longest_span = None
    start_underwater = None
    for stamp, value in values.items():
        peak_so_far = float(running_max.loc[stamp])
        if value < peak_so_far - 1e-12:
            if start_underwater is None:
                start_underwater = stamp
            span = _days(start_underwater, stamp)
            if span is not None and span >= longest_underwater:
                longest_underwater = span
                longest_span = (start_underwater, stamp)
        else:
            start_underwater = None

    return {
        "definition": RISK_DEFINITION,
        "max_drawdown": _round(max_dd, 6),
        "peak_date": pd.Timestamp(peak_date).date().isoformat(),
        "trough_date": pd.Timestamp(trough_date).date().isoformat(),
        "peak_to_trough_days": _days(peak_date, trough_date),
        "recovered": recovered,
        "recovery_date": (
            pd.Timestamp(recovery_date).date().isoformat() if recovered else None
        ),
        "trough_to_recovery_days": _days(trough_date, recovery_date),
        "total_recovery_days": _days(peak_date, recovery_date) if recovered else None,
        "recovery_status": (
            f"已恢复，用时 {_days(peak_date, recovery_date)} 天"
            if recovered else "截至样本末未恢复"
        ),
        "longest_underwater_days": longest_underwater,
        "longest_underwater_span": (
            [pd.Timestamp(longest_span[0]).date().isoformat(),
             pd.Timestamp(longest_span[1]).date().isoformat()]
            if longest_span else None
        ),
    }


def downside_participation(nav: pd.Series) -> dict:
    """上涨/下跌日分别统计，判断趋势过滤是否真的降低了风险。"""
    if nav is None or len(nav) < 2:
        return {"definition": RISK_DEFINITION, "note": "净值序列过短"}
    returns = nav.astype(float).pct_change(fill_method=None).dropna()
    if returns.empty:
        return {"definition": RISK_DEFINITION, "note": "没有可用日收益"}
    up = returns[returns > 0]
    down = returns[returns < 0]
    return {
        "definition": RISK_DEFINITION,
        "sample_days": int(len(returns)),
        "up_days": int(len(up)),
        "down_days": int(len(down)),
        "up_mean": _round(float(up.mean()), 6) if len(up) else None,
        "down_mean": _round(float(down.mean()), 6) if len(down) else None,
        "up_sum": _round(float(up.sum()), 6),
        "down_sum": _round(float(down.sum()), 6),
        "worst_day": _round(float(returns.min()), 6),
        "best_day": _round(float(returns.max()), 6),
        "note": "只描述本次样本，不外推为未来特征",
    }


def regime_attribution(daily: list, labels: dict, trades: list) -> dict:
    """按既有市场环境（510300 MA250 ±5%）分组统计。

    环境标签由 app.validation.regime 生成，本函数**不重新定义**任何阈值。
    显式区分：
    - warmup：分类预热数据，不计入任何统计；
    - unclassified：样本不足，不强行归类；
    - 缺失日（持仓 ETF 缺价）不与正常日合并。
    """
    from app.validation.regime import REGIME_BEAR, REGIME_BULL, REGIME_RANGE, REGIME_UNCLASSIFIED

    trades_by_day: dict = defaultdict(list)
    for trade in trades:
        trades_by_day[trade.trade_date].append(trade)

    payload: dict = {}
    for label in (REGIME_BULL, REGIME_BEAR, REGIME_RANGE, REGIME_UNCLASSIFIED):
        payload[label] = {
            "days": 0,
            "exposure": [],
            "nav": [],
            "trades": 0,
            "buy_count": 0,
            "sell_count": 0,
            "gap_days": 0,
        }

    for index, item in enumerate(daily):
        label = labels.get(item.trade_date, REGIME_UNCLASSIFIED)
        bucket = payload[label]
        bucket["days"] += 1
        total = float(item.total_assets)
        bucket["exposure"].append(float(item.market_value) / total if total > 0 else 0.0)
        bucket["nav"].append(float(item.nav))
        if item.price_status and any(status != "ok" for status in item.price_status.values()):
            bucket["gap_days"] += 1
        for trade in trades_by_day.get(item.trade_date, []):
            bucket["trades"] += 1
            if trade.side == "buy":
                bucket["buy_count"] += 1
            else:
                bucket["sell_count"] += 1

    result: dict = {}
    for label, bucket in payload.items():
        nav_series = pd.Series(bucket["nav"], dtype=float)
        if nav_series.empty:
            result[label] = {
                "days": bucket["days"], "status": "no_data",
                "note": "该环境在样本外没有交易日",
            }
            continue
        segment_return = (
            float(nav_series.iloc[-1] / nav_series.iloc[0] - 1)
            if nav_series.iloc[0] > 0 else None
        )
        peak = nav_series.cummax()
        segment_dd = float((nav_series / peak - 1.0).min())
        result[label] = {
            "days": bucket["days"],
            "status": "ok" if bucket["days"] > 0 else "no_data",
            "segment_return": _round(segment_return, 6),
            "segment_max_drawdown": _round(segment_dd, 6),
            "avg_exposure": _round(float(np.mean(bucket["exposure"])), 6),
            "trades": bucket["trades"],
            "buy_count": bucket["buy_count"],
            "sell_count": bucket["sell_count"],
            "gap_days": bucket["gap_days"],
            "note": "区间收益按该环境内的净值首末点计算，跨环境断点处收益不计入",
        }
    return {
        "definition": "regime-attribution-v1",
        "labels_source": "app.validation.regime（510300 MA250 偏离 ±5%）",
        "regimes": result,
        "note": "环境分类沿用既有体系，本报告未重新定义阈值",
    }


def concentration_profile(daily: list) -> dict:
    """持仓集中度随时间的变化。

    趋势策略「空仓几只 → 满仓少数几只」时权重会被动放大，
    这里量化持仓只数与最大单只权重，用于判断回撤是否来自集中。
    """
    if not daily:
        return {"definition": "concentration-v1", "note": "没有每日快照"}

    counts: list[int] = []
    max_weights: list[float] = []
    herfindahl: list[float] = []
    per_day: list[dict] = []

    for item in daily:
        total = float(item.total_assets)
        weights = {}
        for code, qty in item.positions.items():
            if qty <= 0:
                continue
            price = item.prices.get(code)
            if price is None or total <= 0:
                continue
            weights[code] = float(qty) * float(price) / total
        if not weights:
            counts.append(0)
            max_weights.append(0.0)
            herfindahl.append(0.0)
            per_day.append({"trade_date": item.trade_date.isoformat(), "holdings": 0})
            continue
        counts.append(len(weights))
        max_weights.append(max(weights.values()))
        herfindahl.append(sum(value * value for value in weights.values()))
        top = max(weights.items(), key=lambda kv: kv[1])
        per_day.append({
            "trade_date": item.trade_date.isoformat(),
            "holdings": len(weights),
            "max_weight": _round(top[1], 6),
            "max_code": top[0],
            "hhi": _round(sum(value * value for value in weights.values()), 6),
        })

    def _stats(values: list[float]) -> dict:
        if not values:
            return {}
        arr = np.asarray(values, dtype=float)
        return {
            "mean": _round(float(arr.mean()), 6),
            "median": _round(float(np.median(arr)), 6),
            "min": _round(float(arr.min()), 6),
            "max": _round(float(arr.max()), 6),
        }

    return {
        "definition": "concentration-v1",
        "holdings": _stats(counts),
        "max_weight": _stats(max_weights),
        "hhi": _stats(herfindahl),
        "effective_n": (
            _round(1.0 / float(np.mean(herfindahl)), 4)
            if herfindahl and float(np.mean(herfindahl)) > 0 else None
        ),
        "days_with_single_holding": sum(1 for value in counts if value == 1),
        "days_with_two_or_fewer": sum(1 for value in counts if 0 < value <= 2),
        "days_flat": sum(1 for value in counts if value == 0),
        "per_day": per_day,
    }


PRICE_BREAK_THRESHOLD = 0.08
BREAK_DEFINITION = "price-breakpoint-v1"


def detect_price_breakpoints(rows: list[dict], *, threshold: float = PRICE_BREAK_THRESHOLD) -> list[dict]:
    """检测「原始收盘」与「前复权收盘」日收益显著不一致的日期。

    判定依据：同一交易日上

        |(close_t / close_{t-1}) - (adj_t / adj_{t-1})| > threshold

    两个序列描述的是同一只 ETF 的同一天，正常波动下日收益应基本一致
    （复权因子只在除权除息日微调）。出现 50% 级别的偏离，只可能是
    原始价格序列里插入了「份额折算 / 拆分」这类**数量口径变化**，
    而持仓数量没有同步调整。

    本函数只检测、不修复：修复属于数据层与引擎层改动，需要单独阶段。
    """
    result: list[dict] = []
    prev = None
    for row in sorted(rows, key=lambda item: item["trade_date"]):
        if prev is not None:
            c0, c1 = prev.get("close"), row.get("close")
            a0, a1 = prev.get("adjusted_close"), row.get("adjusted_close")
            if None not in (c0, c1, a0, a1) and c0 > 0 and a0 > 0:
                raw_return = c1 / c0 - 1
                adj_return = a1 / a0 - 1
                gap = abs(raw_return - adj_return)
                if gap > threshold:
                    result.append({
                        "code": row["code"],
                        "trade_date": row["trade_date"],
                        "prev_close": round(float(c0), 4),
                        "close": round(float(c1), 4),
                        "prev_adjusted": round(float(a0), 4),
                        "adjusted": round(float(a1), 4),
                        "raw_return": _round(raw_return, 6),
                        "adjusted_return": _round(adj_return, 6),
                        "gap": _round(gap, 6),
                        "implied_ratio": _round((1 + raw_return) / (1 + adj_return), 6)
                        if (1 + adj_return) != 0 else None,
                    })
        prev = row
    return result


def contamination_estimate(daily: list, breaks: list[dict], *, initial_cash: float) -> dict:
    """估计「价格断点」对净值的虚增金额（部分均衡近似）。

    **这是近似值，不是官方的重算结果。** 做法：
    在每个断点日，用前一交易日收盘持仓数量 × 前一交易日原始价 ×
    断点日两种口径的比值偏离，得到当日被虚构（或被抹掉）的市值，
    再从累计净值里扣除。

    局限（必须写进报告）：
    - 不考虑「扣除虚增后净值不同 → 后续目标权重不同 → 成交不同」的反馈，
      因此只用于评估污染量级，不能当作修正后的正式绩效；
    - 只覆盖已检测到的断点，未检测到的口径问题不在内。
    """
    if not daily:
        return {"definition": BREAK_DEFINITION, "note": "没有每日快照"}

    by_day: dict = defaultdict(list)
    for item in breaks:
        by_day[item["trade_date"]].append(item)

    cumulative = 0.0
    levels: list[dict] = []
    prev = None
    for snap in daily:
        fake = 0.0
        day = snap.trade_date.isoformat()
        if prev is not None and day in by_day:
            for item in by_day[day]:
                qty = int(prev.positions.get(item["code"], 0))
                if qty <= 0:
                    continue
                base_price = prev.prices.get(item["code"])
                if base_price is None:
                    continue
                # 断点日原始收益相对复权收益多出（或少掉）的比例
                extra = item["implied_ratio"] - 1
                fake += qty * float(base_price) * float(extra)
        cumulative += fake
        levels.append({
            "trade_date": day,
            "total_assets": round(float(snap.total_assets), 2),
            "estimated_assets": round(float(snap.total_assets) - cumulative, 2),
            "day_fake": round(fake, 2),
        })
        prev = snap

    nav = pd.Series(
        [item["total_assets"] for item in levels],
        index=pd.DatetimeIndex([pd.Timestamp(item["trade_date"]) for item in levels]),
        dtype=float,
    )
    corrected = pd.Series(
        [item["estimated_assets"] for item in levels], index=nav.index, dtype=float
    )

    def _stats(series: pd.Series) -> dict:
        last, first = float(series.iloc[-1]), float(initial_cash)
        intervals = len(series) - 1
        returns = series.pct_change(fill_method=None).dropna()
        std = float(returns.std(ddof=1)) if len(returns) > 1 else float("nan")
        return {
            "total_return": _round(last / first - 1),
            "cagr": _round((last / first) ** (252 / intervals) - 1) if intervals > 0 else None,
            "annualized_volatility": _round(std * math.sqrt(252)) if std == std else None,
            "sharpe_ratio": (
                _round(float(returns.mean()) * 252 / (std * math.sqrt(252)))
                if std == std and std > 0 else None
            ),
            "max_drawdown": _round(float((series / series.cummax() - 1).min())),
        }

    affected = [item for item in levels if abs(item["day_fake"]) > 1e-6]
    return {
        "definition": BREAK_DEFINITION,
        "breakpoint_count": len(breaks),
        "affected_days": len(affected),
        "cumulative_fake_amount": _round(cumulative, 2),
        "fake_over_initial_cash": (
            _round(cumulative / initial_cash, 6) if initial_cash else None
        ),
        "observed": _stats(nav),
        "estimated": _stats(corrected),
        "detail": affected,
        "note": (
            "estimated 为部分均衡近似（未回放后续调仓反馈），"
            "只能用于评估污染量级，不能作为修正后的正式绩效"
        ),
    }
