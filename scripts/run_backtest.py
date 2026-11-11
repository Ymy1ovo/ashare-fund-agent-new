"""运行回测并把结果写入数据库。

用法：
    python scripts/run_backtest.py --strategy buy_and_hold --codes 510300 --start 2024-01-01 --end 2026-11-09
    python scripts/run_backtest.py --strategy ma_trend --ma-window 20 --all --start 2024-01-01 --end 2026-11-09
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.backtest.config import BacktestConfig, CostConfig  # noqa: E402
from app.backtest.engine import BacktestEngine  # noqa: E402
from app.backtest.metrics import compute_performance  # noqa: E402
from app.backtest.report import render_report  # noqa: E402
from app.backtest.storage import save_result  # noqa: E402
from app.backtest.strategies.buy_and_hold import BuyAndHoldStrategy  # noqa: E402
from app.backtest.strategies.ma_trend import MovingAverageTrendStrategy  # noqa: E402
from app.config import settings  # noqa: E402
from app.database.db import init_db  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 ETF 历史回测")
    parser.add_argument("--strategy", choices=("buy_and_hold", "ma_trend"), default="buy_and_hold")
    parser.add_argument("--codes", nargs="*", help="ETF 代码；缺省用观察池")
    parser.add_argument("--all", action="store_true", help="使用全部 46 只 ETF")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--cash", type=float, default=1_000_000.0)
    parser.add_argument("--ma-window", type=int, default=20)
    parser.add_argument("--execution-price", choices=("open", "close"), default="open")
    parser.add_argument("--commission-rate", type=float, default=0.00025)
    parser.add_argument("--min-commission", type=float, default=5.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--rebalance-tolerance", type=float, default=0.02)
    parser.add_argument("--indicator-version", default="latest")
    parser.add_argument("--no-save", action="store_true", help="只打印，不写数据库")
    args = parser.parse_args()

    init_db()
    config = BacktestConfig(
        start_date=args.start,
        end_date=args.end,
        initial_cash=args.cash,
        execution_price=args.execution_price,
        rebalance_tolerance=args.rebalance_tolerance,
        costs=CostConfig(
            commission_rate=args.commission_rate,
            min_commission=args.min_commission,
            slippage_bps=args.slippage_bps,
        ),
    )
    codes = None if args.all else args.codes
    if args.strategy == "buy_and_hold":
        strategy = BuyAndHoldStrategy()
    else:
        strategy = MovingAverageTrendStrategy(ma_window=args.ma_window)

    engine = BacktestEngine(config, strategy)
    result = engine.run(codes, indicator_version=args.indicator_version)
    performance = compute_performance(
        result.daily, result.trades, result.orders, result.initial_cash,
        annualization=config.annualization, risk_free_rate=config.risk_free_rate,
    )
    report = render_report(result, performance)
    report_path = settings.report_dir / f"backtest_{result.run_id}.md"
    report_path.write_text(report, encoding="utf-8")
    payload = {
        "run_id": result.run_id,
        "input_hash": result.input_hash,
        "performance": performance.as_dict(),
        "meta": result.as_meta(),
    }
    summary_path = settings.data_dir / f"backtest_summary_{result.run_id}.json"
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    saved = None
    if not args.no_save:
        saved = save_result(result, performance)
    print(json.dumps({
        "run_id": result.run_id,
        "input_hash": result.input_hash,
        "codes": len(result.codes),
        "trades": len(result.trades),
        "total_return": performance.total_return,
        "cagr": performance.cagr,
        "max_drawdown": performance.max_drawdown,
        "cost": performance.total_cost,
        "report": str(report_path),
        "saved": saved,
    }, ensure_ascii=False, indent=2))
    return 0 if saved is None or saved["reconciliation"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
