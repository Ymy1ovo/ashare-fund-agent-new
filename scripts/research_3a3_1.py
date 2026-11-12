"""阶段3A.3.1 只读研究脚本：MA250 失效归因。

用法：
    python scripts/research_3a3_1.py
    python scripts/research_3a3_1.py --validation-id 32aead3291734f91

纪律（本脚本硬约束）：
- 不写数据库：只调用 BacktestEngine.run()，它不落库；
  运行前后各取一次行情指纹，不一致直接判定失败。
- 不改参数：MA 窗口固定取验证记录里样本内选出的值，不做参数搜索。
- 不改切分：样本外区间直接读验证记录的 oos_start / oos_end。
- 不删标的：ETF 清单取验证记录的 etf_codes（已按覆盖率过滤的结果）。
- 不填补缺失：净值/收益序列保留原始交易日索引。

输出：data/research_3a3_1.json（运行产物，不进 Git）
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd  # noqa: E402

from app.backtest.data import load_bars  # noqa: E402
from app.backtest.engine import BacktestEngine  # noqa: E402
from app.backtest.metrics import compute_performance, risk_return_series  # noqa: E402
from app.backtest.strategies.buy_and_hold import BuyAndHoldStrategy  # noqa: E402
from app.backtest.strategies.ma_trend import MovingAverageTrendStrategy  # noqa: E402
from app.research import attribution as attr  # noqa: E402
from app.validation.config import ValidationConfig  # noqa: E402
from app.validation.fingerprint import fingerprint_from_db  # noqa: E402
from app.validation.regime import build_regime_series  # noqa: E402

DEFAULT_VALIDATION_ID = "32aead3291734f91"
INDICATOR_VERSION = "v1.0.2-30b821a1af15"


def _load_validation(validation_id: str) -> dict:
    """只读读取验证记录（含 JSON 字段解析）。"""
    from app.validation.storage import get_validation

    record = get_validation(validation_id)
    if not record:
        raise SystemExit(f"验证记录不存在：{validation_id}")
    return record


def _metrics(performance) -> dict:
    return {
        "total_return": performance.total_return,
        "cagr": performance.cagr,
        "annualized_volatility": performance.annualized_volatility,
        "sharpe_ratio": performance.sharpe_ratio,
        "sortino_ratio": performance.sortino_ratio,
        "calmar_ratio": performance.calmar_ratio,
        "max_drawdown": performance.max_drawdown,
        "win_rate": performance.win_rate,
        "profit_loss_ratio": performance.profit_loss_ratio,
        "trade_count": performance.trade_count,
        "turnover": performance.turnover,
        "capital_utilization": performance.capital_utilization,
        "total_cost": performance.total_cost,
        "total_commission": performance.total_commission,
        "total_stamp_tax": performance.total_stamp_tax,
        "total_transfer_fee": performance.total_transfer_fee,
        "total_slippage": performance.total_slippage,
        "average_holding_days": performance.average_holding_days,
        "trading_days": performance.trading_days,
        "risk_sample_days": performance.risk_sample_days,
        "gap_return_days_excluded": performance.gap_return_days_excluded,
        "notes": list(performance.notes),
    }


def _run(config, strategy, codes: list[str]):
    engine = BacktestEngine(config, strategy)
    result = engine.run(codes, indicator_version=INDICATOR_VERSION)
    performance = compute_performance(
        result.daily, result.trades, result.orders, result.initial_cash,
        annualization=config.annualization, risk_free_rate=config.risk_free_rate,
    )
    return result, performance


def _regime_labels(proxy_code: str, oos_start: str, oos_end: str, ma_window: int) -> dict:
    """沿用既有市场环境体系：510300 MA250 偏离 ±5%。

    预热数据单独取（trade_date < oos_start），只参与 MA 计算，
    不进入 labels，也不进入任何统计。
    """
    from app.database.db import get_connection

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT trade_date, adjusted_close, close FROM etf_daily_prices "
            "WHERE code = ? AND trade_date < ? ORDER BY trade_date",
            (proxy_code, oos_start),
        ).fetchall()
    warm_pairs = [
        (str(row[0]), float(row[1] if row[1] is not None else row[2]))
        for row in rows
        if (row[1] is not None or row[2] is not None)
    ]
    warmup = pd.Series(
        [value for _, value in warm_pairs],
        index=pd.DatetimeIndex([pd.Timestamp(day) for day, _ in warm_pairs]),
        dtype=float,
    )

    proxy = load_bars(proxy_code, oos_start, oos_end, indicator_version=None)
    naive_close = proxy.adjusted_close.fillna(proxy.frame["close"])
    naive_close.index = pd.DatetimeIndex([pd.Timestamp(day) for day in naive_close.index])

    combined = pd.concat([warmup, naive_close]).sort_index()
    combined = combined[~combined.index.duplicated(keep="last")]
    series = build_regime_series(
        combined, code=proxy_code, ma_window=ma_window,
        output_start=date.fromisoformat(oos_start),
    )
    return {
        "labels": dict(series.labels),
        "summary": series.summary(),
        "warmup_days": series.warmup_days,
        "notes": list(series.notes),
        "input_rows": len(warm_pairs),
        "oos_rows": len(naive_close),
    }


def _price_rows(codes: list[str], start: str, end: str) -> dict[str, list[dict]]:
    """只读取原始收盘与前复权收盘，用于口径断点检测。"""
    from app.database.db import get_connection

    placeholders = ",".join("?" for _ in codes)
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT code, trade_date, close, adjusted_close FROM etf_daily_prices "
            f"WHERE code IN ({placeholders}) AND trade_date >= ? AND trade_date <= ? "
            f"ORDER BY code, trade_date",
            (*codes, start, end),
        ).fetchall()
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(str(row[0]), []).append({
            "code": str(row[0]),
            "trade_date": str(row[1]),
            "close": row[2],
            "adjusted_close": row[3],
        })
    return grouped


def _block(result, performance, config, initial_cash: float) -> dict:
    """单个策略的完整分析块。"""
    nav, _returns, _statuses = risk_return_series(result.daily)
    decomposition = attr.decompose_nav(result.daily, result.trades)
    # nav 是归一到 1 的净值序列，不能用它算金额；金额一律用每日总资产。
    # 毛收益 = 期末总资产 - 初始资金 + 已付总成本（成本此前已从账户扣除）
    net_gain = (
        float(result.daily[-1].total_assets) - float(initial_cash)
        if result.daily else None
    )
    gross_profit = (
        net_gain + float(performance.total_cost) if net_gain is not None else None
    )
    return {
        "metrics": _metrics(performance),
        "decomposition": {
            key: value for key, value in decomposition.items() if key != "rows"
        },
        "cost": attr.cost_breakdown(
            result.trades, initial_cash=initial_cash, gross_profit=gross_profit
        ),
        "gross_profit": None if gross_profit is None else round(gross_profit, 4),
        "net_gain": None if net_gain is None else round(net_gain, 4),
        "behaviour": attr.trade_behaviour(result.daily, result.trades),
        "contribution": attr.contribution_ranking(decomposition),
        "drawdown": attr.drawdown_profile(nav),
        "downside": attr.downside_participation(nav),
        "concentration": {
            key: value
            for key, value in attr.concentration_profile(result.daily).items()
            if key != "per_day"
        },
        "nav_dates": int(len(nav)),
        "trades": len(result.trades),
        "orders": len(result.orders),
        "price_breakpoints": {
            "detected": None,
            "contamination": None,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="阶段3A.3.1 MA250 失效归因（只读）")
    parser.add_argument("--validation-id", default=DEFAULT_VALIDATION_ID)
    parser.add_argument("--out", default="data/research_3a3_1.json")
    args = parser.parse_args()

    started = time.time()
    started_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    fingerprint_before = fingerprint_from_db()
    record = _load_validation(args.validation_id)

    codes = list(record["etf_codes"])
    oos_start = record["oos_start"]
    oos_end = record["oos_end"]
    summary = record.get("summary_json") or {}
    best_window = summary.get("best_param") or 250

    base = ValidationConfig()
    oos_cfg = base.build_backtest_config(oos_start, oos_end)

    print(f"[研究] 验证记录 {args.validation_id}")
    print(f"[研究] 样本外 {oos_start} ~ {oos_end}，ETF {len(codes)} 只")
    print(f"[研究] MA 窗口（样本内选出，未调参）：{best_window}")

    print("[研究] 重跑 MA 趋势策略（样本外）...")
    ma_result, ma_perf = _run(
        oos_cfg, MovingAverageTrendStrategy(ma_window=best_window), codes
    )
    print(f"        完成：收益 {ma_perf.total_return:.6f} 回撤 {ma_perf.max_drawdown:.6f}")

    print("[研究] 重跑等权买入持有（样本外，同池同成本）...")
    bh_result, bh_perf = _run(oos_cfg, BuyAndHoldStrategy(), codes)
    print(f"        完成：收益 {bh_perf.total_return:.6f} 回撤 {bh_perf.max_drawdown:.6f}")

    regime_labels = _regime_labels(
        base.regime_proxy_code, oos_start, oos_end, base.regime_ma_window
    )

    # ---- 价格口径断点检测（只检测，不修复）----
    print("[研究] 检测原始/复权价格口径断点...")
    oos_prices = _price_rows(codes, oos_start, oos_end)
    breaks = []
    for code, rows in oos_prices.items():
        breaks.extend(attr.detect_price_breakpoints(rows))
    breaks.sort(key=lambda item: (item["trade_date"], item["code"]))

    is_prices = _price_rows(codes, record["is_start"], record["is_end"])
    breaks_is = []
    for code, rows in is_prices.items():
        breaks_is.extend(attr.detect_price_breakpoints(rows))
    breaks_all = (
        [dict(item, phase="oos") for item in breaks]
        + [dict(item, phase="is") for item in sorted(
            breaks_is, key=lambda x: (x["trade_date"], x["code"]))]
    )
    print(f"        样本外断点 {len(breaks)} 个，样本内断点 {len(breaks_is)} 个")

    ma_block = _block(ma_result, ma_perf, oos_cfg, oos_cfg.initial_cash)
    bh_block = _block(bh_result, bh_perf, oos_cfg, oos_cfg.initial_cash)
    ma_block["price_breakpoints"] = {
        "detected": len(breaks),
        "contamination": attr.contamination_estimate(
            ma_result.daily, breaks, initial_cash=oos_cfg.initial_cash
        ),
    }
    bh_block["price_breakpoints"] = {
        "detected": len(breaks),
        "contamination": attr.contamination_estimate(
            bh_result.daily, breaks, initial_cash=oos_cfg.initial_cash
        ),
    }

    payload = {
        "phase": "3A.3.1",
        "validation_id": args.validation_id,
        "input": {
            "oos_start": oos_start,
            "oos_end": oos_end,
            "etf_count": len(codes),
            "etf_codes": codes,
            "excluded_codes": record.get("excluded_codes"),
            "ma_window": best_window,
            "initial_cash": oos_cfg.initial_cash,
            "execution_price": oos_cfg.execution_price,
            "annualization": oos_cfg.annualization,
            "risk_free_rate": oos_cfg.risk_free_rate,
            "cost": {
                "commission_rate": oos_cfg.costs.commission_rate,
                "min_commission": oos_cfg.costs.min_commission,
                "slippage_bps": oos_cfg.costs.slippage_bps,
                "stamp_duty_rate": oos_cfg.costs.stamp_duty_rate,
                "transfer_fee_rate": oos_cfg.costs.transfer_fee_rate,
                "min_commission_model": oos_cfg.costs.min_commission_model,
            },
            "indicator_version": INDICATOR_VERSION,
            "regime_proxy": base.regime_proxy_code,
            "regime_ma_window": base.regime_ma_window,
        },
        "fingerprint_before": fingerprint_before,
        "ma_trend": ma_block,
        "buy_and_hold": bh_block,
        "price_breakpoints": {
            "threshold": attr.PRICE_BREAK_THRESHOLD,
            "rows": breaks,
            "count": len(breaks),
            "by_phase": {
                "is": sum(1 for item in breaks_all if item["phase"] == "is"),
                "oos": sum(1 for item in breaks_all if item["phase"] == "oos"),
            },
            "all_phase_rows": breaks_all,
        },
        "regime": {
            "labels": regime_labels["summary"],
            "warmup_days": regime_labels["warmup_days"],
            "notes": regime_labels["notes"],
            "input_rows": regime_labels["input_rows"],
            "oos_rows": regime_labels["oos_rows"],
            "ma_trend": attr.regime_attribution(
                ma_result.daily, regime_labels["labels"], ma_result.trades
            ),
            "buy_and_hold": attr.regime_attribution(
                bh_result.daily, regime_labels["labels"], bh_result.trades
            ),
        },
        "runtime": {
            "started_at": started_at,
            "elapsed_seconds": None,
        },
    }

    fingerprint_after = fingerprint_from_db()
    payload["fingerprint_after"] = fingerprint_after
    payload["data_unchanged"] = (
        fingerprint_before.get("sha256") == fingerprint_after.get("sha256")
    )
    payload["runtime"]["elapsed_seconds"] = round(time.time() - started, 2)

    out_path = PROJECT_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"[研究] 数据指纹一致：{payload['data_unchanged']}")
    print(f"[研究] 耗时 {payload['runtime']['elapsed_seconds']}s，输出 {out_path}")
    return 0 if payload["data_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
