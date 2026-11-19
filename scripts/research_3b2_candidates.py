"""阶段3B-2 策略候选研究（只读）。

严格只读：不写数据库、不修改正式策略模块、不改引擎/会计/撮合/成本。
所有回测一律 db_path=None（引擎此时不写公司行为与应收明细），
结果只留在本脚本产出的 JSON / Markdown / 图表里。

三个候选规则是**预先固定**的，本脚本不做任何参数搜索，
不使用 OOS 反向调整参数，不扩大参数网格。
"""
from __future__ import annotations

import json
import sys
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from app.backtest.engine import BacktestEngine                      # noqa: E402
from app.backtest.metrics import compute_performance                 # noqa: E402
from app.backtest.strategies.base import StrategyContext, TargetWeight  # noqa: E402
from app.backtest.strategies.buy_and_hold import BuyAndHoldStrategy  # noqa: E402
from app.backtest.strategies.ma_trend import MovingAverageTrendStrategy  # noqa: E402
from app.database.db import get_connection                           # noqa: E402
from app.validation.config import ValidationConfig                   # noqa: E402
from app.validation.fingerprint import fingerprint_from_db            # noqa: E402
from app.validation.regime import (                                   # noqa: E402
    build_regime_series, regime_stats,
    REGIME_BULL, REGIME_BEAR, REGIME_RANGE, REGIME_UNCLASSIFIED,
)

# ---------------------------------------------------------------- 固定口径
IS_START, IS_END = "2021-01-04", "2024-12-31"
OOS_START, OOS_END = "2025-01-02", "2026-11-09"
FULL_START, FULL_END = IS_START, OOS_END

MOM_LOOKBACK = 120          # 6 个月 ≈ 120 个交易日（固定，不搜索）
TOP_N = 3                   # 固定取前 3
TREND_MA = 200              # 固定 MA200（固定，不搜索）
DEFENSE_CODE = "511010"     # 国债ETF国泰，2013-03-25 起满覆盖
HS300_PROXY = "510300"
ZZ500_PROXY = "510500"
MA_TREND_PARAM = 60         # 现有 MA 策略的代表参数（3B-1 中 WF 选中最多）

STOCK_CLASS = "指数型-股票"


def _num(x, nd=10):
    return None if x is None else round(float(x), nd)


# ---------------------------------------------------------------- 池审计
def audit_pool() -> dict:
    """46 只 ETF 的上市日期、覆盖率、分类可靠性审计。

    幸存者偏差必须显式声明：当前 46 只都是「活到今天」的 ETF，
    数据库里没有历史退市 ETF，因此不可能消除幸存者偏差。
    """
    with get_connection() as conn:
        calendar = [r[0] for r in conn.execute(
            "SELECT trade_date FROM trade_calendar WHERE trade_date>=? "
            "AND trade_date<=? ORDER BY trade_date", (FULL_START, FULL_END))]
        rows = conn.execute("""
            SELECT p.code, p.name, p.category, p.fund_type, p.listing_date,
                   COUNT(d.trade_date) n, MIN(d.trade_date) first_bar
            FROM etf_pool p LEFT JOIN etf_daily_prices d
              ON d.code=p.code AND d.trade_date>=? AND d.trade_date<=?
            GROUP BY p.code ORDER BY p.code""", (FULL_START, FULL_END)).fetchall()
        ca_counts = {r[0]: r[1] for r in conn.execute(
            "SELECT code, COUNT(*) FROM corporate_actions GROUP BY code")}
        pool = []
        for r in rows:
            cov = (r["n"] / len(calendar)) if calendar else 0.0
            listed_before_start = (r["first_bar"] or "9999") <= FULL_START
            pool.append({
                "code": r["code"], "name": r["name"], "category": r["category"],
                "fund_type": r["fund_type"], "listing_date": r["listing_date"],
                "first_bar_in_range": r["first_bar"],
                "bars_in_range": r["n"], "coverage_ratio": _num(cov, 6),
                "listed_before_is_start": listed_before_start,
                "corporate_actions": ca_counts.get(r["code"], 0),
            })
    return {
        "calendar_days": len(calendar),
        "total_pool": len(pool),
        "by_fund_type": _count_by(pool, "fund_type"),
        "by_category": _count_by(pool, "category"),
        "full_coverage_count": sum(1 for x in pool if x["coverage_ratio"] >= 0.995),
        "listed_before_is_start": [x["code"] for x in pool
                                   if x["listed_before_is_start"]],
        "rows": pool,
    }


def _count_by(rows: list[dict], key: str) -> dict:
    out: dict[str, int] = {}
    for r in rows:
        out[r[key]] = out.get(r[key], 0) + 1
    return out


def build_universe() -> dict:
    """固定股票类 universe：2021-01-04 之前已上市且为股票类。"""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT p.code, p.name, p.fund_type, MIN(d.trade_date) first_bar
            FROM etf_pool p JOIN etf_daily_prices d ON d.code=p.code
            GROUP BY p.code""").fetchall()
    stocks, excluded_late, excluded_nonstock = [], [], []
    for r in rows:
        if r["fund_type"] != STOCK_CLASS:
            excluded_nonstock.append({"code": r["code"], "name": r["name"],
                                      "fund_type": r["fund_type"]})
            continue
        if r["first_bar"] <= IS_START:
            stocks.append(r["code"])
        else:
            excluded_late.append({"code": r["code"], "name": r["name"],
                                  "first_bar": r["first_bar"],
                                  "reason": "IS 起点之后才上市，不得提前纳入历史排名"})
    with get_connection() as conn:
        defense_ok = conn.execute(
            "SELECT MIN(trade_date), COUNT(*) FROM etf_daily_prices "
            "WHERE code=? AND trade_date>=? AND trade_date<=?",
            (DEFENSE_CODE, FULL_START, FULL_END)).fetchone()
        defense_type = conn.execute(
            "SELECT fund_type, name FROM etf_pool WHERE code=?", (DEFENSE_CODE,)
        ).fetchone()
    return {
        "stock_universe": sorted(stocks),
        "stock_universe_size": len(stocks),
        "excluded_late_listing": excluded_late,
        "excluded_non_stock_type": excluded_nonstock,
        "defense_code": DEFENSE_CODE,
        "defense_name": defense_type["name"] if defense_type else None,
        "defense_fund_type": defense_type["fund_type"] if defense_type else None,
        "defense_first_bar": defense_ok[0],
        "defense_bars": defense_ok[1],
        "defense_usable": bool(
            defense_ok[0] and defense_ok[0] <= IS_START
            and defense_type and defense_type["fund_type"] != STOCK_CLASS),
    }


# ---------------------------------------------------------------- 候选策略
def _load_price_history(codes: list[str]) -> dict[str, pd.Series]:
    """预取全历史前复权收盘价（只读），供动量/趋势计算预热。"""
    if not codes:
        return {}
    out: dict[str, pd.Series] = {}
    with get_connection() as conn:
        for code in codes:
            rows = conn.execute(
                "SELECT trade_date, adjusted_close FROM etf_daily_prices "
                "WHERE code=? AND trade_date<=? ORDER BY trade_date",
                (code, FULL_END)).fetchall()
            series = pd.Series(
                {r["trade_date"]: float(r["adjusted_close"]) for r in rows
                 if r["adjusted_close"] is not None})
            if series.empty:
                continue
            series.index = pd.DatetimeIndex(series.index)
            out[code] = series.sort_index()
    return out


class _MonthlyRotationBase:
    """月度调仓 + 6 个月动量排名的公共实现。

    只读 context 中 signal_date 及之前的数据，不引用未来。
    """

    name = "base"
    version = "0.0.1"

    def __init__(self, stock_codes: list[str], *, defense: str | None = None,
                 require_trend: bool = False) -> None:
        self.stock_codes = list(stock_codes)
        self.defense = defense
        self.require_trend = require_trend
        self.decisions: list[dict] = []
        # 引擎只加载 [start_date, end_date] 的指标行，回测首日没有前 200 天，
        # 直接用 context.indicators 会把开头几个月误判成「样本不足」。
        # 这里从数据库预取全历史前复权收盘价，再按 signal_date 切片，
        # 既保证指标有预热，也保证不引用未来数据。
        self.history = _load_price_history(
            sorted(set(self.stock_codes) | ({defense} if defense else set())))

    # --- 只在每月第一个交易日给意见
    def _is_rebalance_day(self, context: StrategyContext) -> bool:
        dates: set[date] = set()
        for code in context.codes:
            frame = context.bars.get(code)
            if frame is None or frame.empty:
                continue
            for day in frame.index:
                if day.year == context.signal_date.year and \
                        day.month == context.signal_date.month:
                    dates.add(day)
        return bool(dates) and context.signal_date == min(dates)

    def _series_until(self, context: StrategyContext, code: str):
        """取 code 在 signal_date（含）之前的全历史前复权收盘。

        `series.index` 是 DatetimeIndex，`signal_date` 是 date，
        必须转成 Timestamp 再比较，否则 pandas 抛类型错误。
        """
        series = self.history.get(code)
        if series is None or series.empty:
            return None
        cutoff = pd.Timestamp(context.signal_date)
        return series.loc[series.index <= cutoff]

    # --- 6 个月动量（用前复权收盘，不含当日之后）
    def _momentum(self, context: StrategyContext, code: str):
        series = self._series_until(context, code)
        if series is None or len(series) <= MOM_LOOKBACK:
            return None
        latest = float(series.iloc[-1])
        base = float(series.iloc[-1 - MOM_LOOKBACK])
        if base <= 0:
            return None
        return latest / base - 1.0

    # --- 绝对趋势过滤：收盘是否高于 MA200
    def _above_trend(self, context: StrategyContext, code: str):
        series = self._series_until(context, code)
        if series is None or len(series) < TREND_MA:
            return None
        ma = float(series.tail(TREND_MA).mean())
        latest = float(series.iloc[-1])
        return latest > ma

    def _decide(self, context: StrategyContext) -> tuple[list[str], list[dict]]:
        ranked: list[dict] = []
        for code in self.stock_codes:
            if code not in context.codes:
                continue
            mom = self._momentum(context, code)
            # 无论是否启用趋势过滤，都记录真实的 MA200 状态：
            # 它是审计字段，必须反映事实，不能因为「本策略不用它」就填 True。
            # 候选A 不使用它做筛选（require_trend=False），但决策日志里仍可查。
            trend = self._above_trend(context, code)
            ranked.append({"code": code, "momentum": _num(mom, 8),
                           "above_ma200": trend,
                           "trend_filter_applied": self.require_trend})
        scored = [r for r in ranked if r["momentum"] is not None]
        scored.sort(key=lambda r: -r["momentum"])
        selected, rejected = [], []
        for idx, row in enumerate(scored):
            ok = True
            if self.require_trend and row["above_ma200"] is not True:
                ok = False
                row["reject"] = ("趋势过滤未通过（价格未高于 MA200）"
                                 if row["above_ma200"] is False
                                 else "MA200 样本不足")
            if ok and len(selected) >= TOP_N:
                ok = False
                row["reject"] = f"排名第 {idx+1}，超出前 {TOP_N}"
            if ok:
                selected.append(row["code"])
        rejected = [r for r in scored if r["code"] not in selected]
        for r in ranked:
            if r["momentum"] is None:
                rejected.append({**r, "reject": "动量样本不足（不足 6 个月）"})
        return selected, {"ranked": ranked, "selected": selected,
                          "rejected": rejected}


class CandidateA(_MonthlyRotationBase):
    """候选A：6 个月动量前 3 名等权，不做绝对趋势过滤。"""

    name = "candidate_a_rotation"
    version = "1.0.0"

    def target_weights(self, context: StrategyContext) -> list[TargetWeight] | None:
        if not self._is_rebalance_day(context):
            return None
        selected, detail = self._decide(context)
        self.decisions.append({
            "signal_date": context.signal_date.isoformat(),
            "eligible_count": len([r for r in detail["ranked"]
                                   if r["momentum"] is not None]),
            "ranked": detail["ranked"],
            "selected": selected,
            "rejected": detail["rejected"],
            "cash_weight": 0.0 if selected else 1.0,
            "defense_weight": 0.0,
        })
        if not selected:
            return [] if any(v > 0 for v in context.current_weights.values()) else None
        weight = 1.0 / len(selected)
        return [TargetWeight(code=c, weight=weight) for c in selected]


class CandidateB(CandidateA):
    """候选B：相对动量 + MA200 绝对趋势过滤，未通过转现金。"""

    name = "candidate_b_momentum_trend"
    version = "1.0.0"

    def __init__(self, stock_codes, *, defense=None):
        super().__init__(stock_codes, defense=None, require_trend=True)


class CandidateC(CandidateA):
    """候选C：相对动量 + MA200 过滤，风险条件不满足时转防守 ETF。"""

    name = "candidate_c_attack_defense"
    version = "1.0.0"

    def __init__(self, stock_codes, *, defense=DEFENSE_CODE):
        super().__init__(stock_codes, defense=defense, require_trend=True)

    def target_weights(self, context: StrategyContext) -> list[TargetWeight] | None:
        if not self._is_rebalance_day(context):
            return None
        selected, detail = self._decide(context)
        use_defense = not selected and self.defense and \
            self.defense in context.codes
        self.decisions.append({
            "signal_date": context.signal_date.isoformat(),
            "eligible_count": len([r for r in detail["ranked"]
                                   if r["momentum"] is not None]),
            "ranked": detail["ranked"],
            "selected": selected,
            "rejected": detail["rejected"],
            "cash_weight": 0.0 if (selected or use_defense) else 1.0,
            "defense_weight": 1.0 if use_defense else 0.0,
            "defense_code": self.defense if use_defense else None,
        })
        if selected:
            weight = 1.0 / len(selected)
            return [TargetWeight(code=c, weight=weight) for c in selected]
        if use_defense:
            return [TargetWeight(code=self.defense, weight=1.0)]
        return [] if any(v > 0 for v in context.current_weights.values()) else None


# ---------------------------------------------------------------- 回测执行
def run_strategy(codes: list[str], strategy, *, label: str) -> dict:
    cfg = ValidationConfig(
        is_start=IS_START, is_end=IS_END,
        oos_start=OOS_START, oos_end=OOS_END, pool_mode="all",
    )
    bt = cfg.build_backtest_config(FULL_START, FULL_END)
    engine = BacktestEngine(bt, strategy, db_path=None)
    result = engine.run(codes, indicator_version=cfg.indicator_version)
    return {
        "label": label,
        "codes": list(codes),
        "daily": result.daily,
        "trades": result.trades,
        "orders": result.orders,
        "initial_cash": result.initial_cash,
        "annualization": bt.annualization,
        "risk_free_rate": bt.risk_free_rate,
        "accounting_basis": getattr(result, "accounting_basis", None),
        "formal_valuation": bool(getattr(result, "formal_valuation", False)),
        "input_hash": getattr(result, "input_hash", None),
        "notes": list(getattr(result, "notes", []) or []),
    }


def _slice(daily, start: str, end: str):
    return [d for d in daily if start <= d.trade_date.isoformat() <= end]


def _slice_trades(trades, start: str, end: str):
    return [t for t in trades if start <= t.trade_date.isoformat() <= end]


def metrics_for(run: dict, start: str, end: str) -> dict:
    daily = _slice(run["daily"], start, end)
    trades = _slice_trades(run["trades"], start, end)
    if len(daily) < 2:
        return {"status": "insufficient_sample", "trading_days": len(daily)}
    perf = compute_performance(
        daily, trades, [], run["initial_cash"],
        annualization=run["annualization"], risk_free_rate=run["risk_free_rate"],
    )
    dividends = _dividend_total(run["daily"], start, end)
    cash_ratio = _cash_ratio(daily)
    last = daily[-1]
    prev = daily[0]
    return {
        "status": "ok",
        "start": start, "end": end,
        "trading_days": perf.trading_days,
        "total_return": _num(perf.total_return),
        "cagr": _num(perf.cagr),
        "annualized_volatility": _num(perf.annualized_volatility),
        "sharpe_ratio": _num(perf.sharpe_ratio),
        "sortino_ratio": _num(perf.sortino_ratio),
        "max_drawdown": _num(perf.max_drawdown),
        "calmar_ratio": _num(perf.calmar_ratio),
        "win_rate": _num(perf.win_rate, 6),
        "trade_count": perf.trade_count,
        "turnover": _num(perf.turnover, 4),
        "total_cost": _num(perf.total_cost, 4),
        "total_commission": _num(perf.total_commission, 4),
        "total_slippage": _num(perf.total_slippage, 4),
        "average_holding_days": _num(perf.average_holding_days, 2),
        "capital_utilization": _num(perf.capital_utilization, 6),
        "cash_ratio_mean": cash_ratio,
        "dividend_confirmed": _num(dividends, 4),
        "dividend_pct_of_initial": _num(
            dividends / run["initial_cash"], 6) if dividends is not None else None,
        "nav_start": _num(prev.nav), "nav_end": _num(last.nav),
        "notes": list(perf.notes),
    }


def _dividend_total(daily, start: str, end: str):
    """已确认分红总额 = 应收余额的正向增量之和。

    应收在除息日出现（余额上升）、在发放日转为现金（余额下降）。
    因此正的日增量之和就是全部已确认分红，不会重复计算，也不等于
    「应收余额」这个期末快照值。
    """
    total = 0.0
    prev = 0.0
    seen = False
    for snap in daily:
        if not (start <= snap.trade_date.isoformat() <= end):
            continue
        cur = float(getattr(snap, "dividend_receivable", 0.0) or 0.0)
        if cur > prev:
            total += cur - prev
        prev = cur
        seen = True
    return total if seen else None


def _cash_ratio(daily) -> float | None:
    values = []
    for snap in daily:
        if snap.total_assets and snap.total_assets > 0:
            values.append(float(snap.cash) / float(snap.total_assets))
    if not values:
        return None
    return _num(sum(values) / len(values), 6)


def split_metrics(run: dict) -> dict:
    return {
        "in_sample": metrics_for(run, IS_START, IS_END),
        "out_of_sample": metrics_for(run, OOS_START, OOS_END),
        "full": metrics_for(run, FULL_START, FULL_END),
    }


# ---------------------------------------------------------------- 分窗口
def half_year_windows() -> list[tuple[str, str]]:
    """6 个月一段的连续窗口，覆盖全区间（固定规则无需训练期）。"""
    with get_connection() as conn:
        cal = [r[0] for r in conn.execute(
            "SELECT trade_date FROM trade_calendar WHERE trade_date>=? AND "
            "trade_date<=? ORDER BY trade_date", (FULL_START, FULL_END))]
    first_of_month: OrderedDict[str, str] = OrderedDict()
    for day in cal:
        first_of_month.setdefault(day[:7], day)
    months = list(first_of_month.values())
    windows = []
    i = 0
    while i < len(months):
        start = months[i]
        j = i + 6
        end = cal[-1] if j >= len(months) else _prev_day(cal, months[j])
        if start <= end and _days_between(cal, start, end) >= 20:
            windows.append((start, end))
        i += 6
    return windows


def _prev_day(cal: list[str], day: str) -> str:
    for idx, cur in enumerate(cal):
        if cur == day:
            return cal[idx - 1] if idx > 0 else day
    return day


def _days_between(cal: list[str], start: str, end: str) -> int:
    return sum(1 for d in cal if start <= d <= end)


def window_metrics(run: dict) -> list[dict]:
    out = []
    for idx, (start, end) in enumerate(half_year_windows()):
        m = metrics_for(run, start, end)
        m["window_index"] = idx
        out.append(m)
    return out


# ---------------------------------------------------------------- 市场环境
def regime_labels() -> dict:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT trade_date, adjusted_close FROM etf_daily_prices "
            "WHERE code=? AND trade_date<=? ORDER BY trade_date",
            (HS300_PROXY, FULL_END)).fetchall()
    series = pd.Series(
        {r["trade_date"]: float(r["adjusted_close"]) for r in rows
         if r["adjusted_close"] is not None})
    series.index = pd.DatetimeIndex(series.index)
    if series.empty:
        return {}
    built = build_regime_series(series, code=HS300_PROXY)
    return built.labels


def regime_breakdown(run: dict, labels: dict) -> dict:
    daily = _slice(run["daily"], OOS_START, OOS_END)
    if len(daily) < 2:
        return {"status": "insufficient_sample"}
    rets = {}
    for snap in daily:
        day = snap.trade_date
        if snap.daily_return is None:
            rets[day] = None
        else:
            rets[day] = float(snap.daily_return)
    payload = regime_stats(
        pd.Series({pd.Timestamp(d): v for d, v in rets.items()}), labels)
    out = {}
    for label in (REGIME_BULL, REGIME_RANGE, REGIME_BEAR, REGIME_UNCLASSIFIED):
        entry = payload.get(label) or {}
        out[label] = {
            "status": entry.get("status"),
            "samples": entry.get("samples"),
            "cumulative_return": _num(entry.get("cumulative_return")),
            "cagr": _num(entry.get("cagr")),
            "sharpe_ratio": _num(entry.get("sharpe_ratio")),
            "max_drawdown": _num(entry.get("max_drawdown")),
            "win_rate": _num(entry.get("win_rate"), 6),
        }
    return out


# ---------------------------------------------------------------- 主体
def main(out_dir: Path) -> dict:
    print("审计 ETF 池...", flush=True)
    pool = audit_pool()
    universe = build_universe()
    stocks = universe["stock_universe"]
    print(f"  股票类 universe: {len(stocks)} 只", flush=True)

    runs: dict[str, dict] = {}

    print("回测 候选A ...", flush=True)
    strat_a = CandidateA(stocks)
    runs["candidate_a"] = run_strategy(stocks, strat_a, label="候选A 相对强弱轮动")

    print("回测 候选B ...", flush=True)
    strat_b = CandidateB(stocks)
    runs["candidate_b"] = run_strategy(stocks, strat_b, label="候选B 动量+趋势过滤")

    print("回测 候选C ...", flush=True)
    pool_c = stocks + ([DEFENSE_CODE] if universe["defense_usable"] else [])
    strat_c = CandidateC(stocks, defense=DEFENSE_CODE)
    runs["candidate_c"] = run_strategy(pool_c, strat_c, label="候选C 攻守切换")

    print("回测 基准 等权买入持有(股票池) ...", flush=True)
    runs["buy_and_hold_stocks"] = run_strategy(
        stocks, BuyAndHoldStrategy(), label="等权买入持有（23 只股票池）")

    if universe["defense_usable"]:
        print("回测 基准 等权买入持有(含防守) ...", flush=True)
        runs["buy_and_hold_with_defense"] = run_strategy(
            pool_c, BuyAndHoldStrategy(), label="等权买入持有（23 股 + 国债）")

    print(f"回测 基准 现有MA趋势(MA{MA_TREND_PARAM}) ...", flush=True)
    runs["ma_trend"] = run_strategy(
        stocks, MovingAverageTrendStrategy(ma_window=MA_TREND_PARAM),
        label=f"现有MA趋势策略（MA{MA_TREND_PARAM}）")

    print("回测 基准 沪深300 ...", flush=True)
    runs["hs300"] = run_strategy(
        [HS300_PROXY], BuyAndHoldStrategy(), label="沪深300（510300 代理）")

    print("回测 基准 中证500 ...", flush=True)
    runs["zz500"] = run_strategy(
        [ZZ500_PROXY], BuyAndHoldStrategy(), label="中证500（510500 代理）")

    print("计算市场环境...", flush=True)
    labels = regime_labels()

    results = {}
    for key, run in runs.items():
        print(f"  汇总 {key} ...", flush=True)
        entry = {
            "label": run["label"],
            "codes": run["codes"],
            "code_count": len(run["codes"]),
            "accounting_basis": run["accounting_basis"],
            "formal_valuation": run["formal_valuation"],
            "input_hash": run["input_hash"],
            "notes": run["notes"],
            "metrics": split_metrics(run),
            "windows": window_metrics(run),
            "regime_oos": regime_breakdown(run, labels),
        }
        if key.startswith("candidate"):
            strat = {"candidate_a": strat_a, "candidate_b": strat_b,
                     "candidate_c": strat_c}[key]
            entry["decisions"] = strat.decisions
            entry["monthly_rebalance_count"] = len(strat.decisions)
            entry["defense_months"] = sum(
                1 for d in strat.decisions if d.get("defense_weight", 0) > 0)
            entry["cash_months"] = sum(
                1 for d in strat.decisions if d.get("cash_weight", 0) > 0)
        results[key] = entry

    cash_bench = {
        "label": "现金基准",
        "metrics": {
            "in_sample": {"status": "ok", "total_return": 0.0, "cagr": 0.0,
                          "annualized_volatility": 0.0, "max_drawdown": 0.0,
                          "sharpe_ratio": None, "trade_count": 0,
                          "total_cost": 0.0, "note": "持有现金，无交易、无成本"},
            "out_of_sample": {"status": "ok", "total_return": 0.0, "cagr": 0.0,
                              "annualized_volatility": 0.0, "max_drawdown": 0.0,
                              "sharpe_ratio": None, "trade_count": 0,
                              "total_cost": 0.0},
            "full": {"status": "ok", "total_return": 0.0, "cagr": 0.0,
                     "annualized_volatility": 0.0, "max_drawdown": 0.0,
                     "sharpe_ratio": None, "trade_count": 0,
                     "total_cost": 0.0},
        },
    }

    assessment = assess(results, universe)
    fp = fingerprint_from_db()
    payload = {
        "phase": "3B-2",
        "baseline_head": "e671d50aeba3900b8bf90140ee6de2bbf469c65a",
        "fixed_rules": {
            "is_start": IS_START, "is_end": IS_END,
            "oos_start": OOS_START, "oos_end": OOS_END,
            "momentum_lookback_days": MOM_LOOKBACK,
            "top_n": TOP_N, "trend_ma": TREND_MA,
            "defense_code": DEFENSE_CODE,
            "rebalance": "每月第一个交易日收盘出信号，次一交易日开盘成交",
            "note": "规则预先固定，本阶段未做任何参数搜索",
        },
        "market_fingerprint": fp,
        "pool_audit": pool,
        "universe": universe,
        "cash_benchmark": cash_bench,
        "results": results,
        "assessment": assessment,
        "limitations": [
            "数据库只有当前存续的 46 只 ETF，没有退市 ETF 历史，"
            "幸存者偏差无法消除，只能通过「IS 起点前已上市」过滤"
            "避免把未来上市标的提前纳入。",
            "OOS 只有约 22 个月，不足一个完整市场周期。",
            "MA200 与 6 个月动量窗口是预先固定的，未做任何网格搜索；"
            "因此不存在「参数最优化」带来的 IS 过拟合，但也无法判断"
            "更优参数是否存在。",
            "沪深300/中证500 用 ETF 代理（510300/510500），含跟踪误差。",
            "所有回测 db_path=None，不写库；结果是研究数据，"
            "不构成正式 validation 结论。",
        ],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    jp = out_dir / "phase3B2_strategy_candidates.json"
    jp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"JSON -> {jp}", flush=True)
    return payload


def assess(results: dict, universe: dict) -> dict:
    """候选筛选：逐条对照 8 条标准，不按总收益排序。"""
    bh = results["buy_and_hold_stocks"]["metrics"]["out_of_sample"]
    criteria_rows = []
    for key in ("candidate_a", "candidate_b", "candidate_c"):
        r = results[key]
        oos = r["metrics"]["out_of_sample"]
        ws = [w for w in r["windows"] if w.get("status") == "ok"]
        rets = [w["total_return"] for w in ws if w["total_return"] is not None]
        best_share = None
        if rets:
            total = sum(rets)
            best = max(rets)
            best_share = _num(best / total, 6) if total else None
        checks = {
            "oos_net_positive": bool((oos.get("total_return") or 0) > 0),
            "excess_vs_buyhold": _num(
                (oos.get("total_return") or 0) - (bh.get("total_return") or 0), 10)
            if oos.get("total_return") is not None else None,
            "max_drawdown_not_worse": bool(
                (oos.get("max_drawdown") or -1) >= (bh.get("max_drawdown") or -1)),
            "sharpe_not_much_lower": bool(
                (oos.get("sharpe_ratio") or 0) >= (bh.get("sharpe_ratio") or 0) - 0.2),
            "cost_reasonable": _num(
                (oos.get("total_cost") or 0) / 1_000_000.0, 6),
            "turnover": oos.get("turnover"),
            "wf_windows": len(ws),
            "wf_positive_windows": sum(1 for x in rets if x > 0),
            "wf_best_window_share": best_share,
            "wf_not_single_window": bool(best_share is not None and best_share < 0.8),
        }
        criteria_rows.append({"key": key, "label": r["label"], "checks": checks})
    return {
        "out_of_sample_benchmark_buyhold": {
            "total_return": bh.get("total_return"),
            "max_drawdown": bh.get("max_drawdown"),
            "sharpe_ratio": bh.get("sharpe_ratio"),
        },
        "criteria_rows": criteria_rows,
        "note": ("筛选标准逐条对照，不按总收益排序。"
                 "任何一项不满足都会在报告中明确列出。"),
    }


if __name__ == "__main__":
    main(ROOT / "reports")
