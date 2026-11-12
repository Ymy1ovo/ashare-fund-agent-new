"""阶段3A.3.2 历史回测重放：用修复后的账本重跑样本内/样本外。

纪律：
- 不覆盖任何历史记录；新 run_id / validation_id 写入，旧记录完整保留。
- 样本区间、ETF 池、MA 参数、成本配置全部沿用原记录的取值。
- 同时跑「修复口径」与「旧口径」（apply_corporate_actions=False）以形成对照。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.backtest.corporate_actions import DATA_VERSION  # noqa: E402
from app.backtest.engine import BacktestEngine  # noqa: E402
from app.backtest.metrics import compute_performance, risk_return_series  # noqa: E402
from app.backtest.strategies.buy_and_hold import BuyAndHoldStrategy  # noqa: E402
from app.backtest.strategies.ma_trend import MovingAverageTrendStrategy  # noqa: E402
from app.validation.config import ValidationConfig  # noqa: E402
from app.validation.fingerprint import fingerprint_from_db  # noqa: E402
from app.validation.storage import get_validation  # noqa: E402

SOURCE_VID = "32aead3291734f91"
INDICATOR_VERSION = "v1.0.2-30b821a1af15"


def _metrics(perf) -> dict:
    return {
        "total_return": perf.total_return,
        "cagr": perf.cagr,
        "annualized_volatility": perf.annualized_volatility,
        "sharpe_ratio": perf.sharpe_ratio,
        "sortino_ratio": perf.sortino_ratio,
        "calmar_ratio": perf.calmar_ratio,
        "max_drawdown": perf.max_drawdown,
        "trade_count": perf.trade_count,
        "total_cost": perf.total_cost,
        "total_commission": perf.total_commission,
        "total_stamp_tax": perf.total_stamp_tax,
        "total_transfer_fee": perf.total_transfer_fee,
        "total_slippage": perf.total_slippage,
        "win_rate": perf.win_rate,
        "turnover": perf.turnover,
        "trading_days": perf.trading_days,
        "risk_sample_days": perf.risk_sample_days,
    }


def run_one(label: str, start: str, end: str, codes: list[str], strategy,
            *, apply_ca: bool) -> dict:
    cfg = ValidationConfig().build_backtest_config(start, end)
    cfg = type(cfg)(
        start_date=cfg.start_date, end_date=cfg.end_date,
        initial_cash=cfg.initial_cash, execution_price=cfg.execution_price,
        max_defer_days=cfg.max_defer_days, risk_free_rate=cfg.risk_free_rate,
        annualization=cfg.annualization, rebalance_tolerance=cfg.rebalance_tolerance,
        costs=cfg.costs, apply_corporate_actions=apply_ca,
    )
    engine = BacktestEngine(cfg, strategy)
    started = time.time()
    result = engine.run(codes, indicator_version=INDICATOR_VERSION)
    perf = compute_performance(
        result.daily, result.trades, result.orders, result.initial_cash,
        annualization=cfg.annualization, risk_free_rate=cfg.risk_free_rate,
    )
    nav, returns, _ = risk_return_series(result.daily)
    print(f"  [{label}] ca={apply_ca} ret={perf.total_return:+.6f} "
          f"dd={perf.max_drawdown:+.6f} sharpe={perf.sharpe_ratio:.4f} "
          f"trades={perf.trade_count} ({round(time.time()-started,1)}s)")
    return {
        "label": label,
        "apply_corporate_actions": apply_ca,
        "corporate_action_version": DATA_VERSION if apply_ca else "disabled",
        "range": f"{start}~{end}",
        "metrics": _metrics(perf),
        "nav_dates": int(len(nav)),
        "applied_actions": len(engine.corporate_action_log),
        "action_log": engine.corporate_action_log,
        "notes": [n for n in result.notes if "公司行为" in n],
        "run_id": result.run_id,
        "input_hash": result.input_hash,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="阶段3A.3.2 历史回测重放")
    parser.add_argument("--out", default="data/replay_3a3_2.json")
    args = parser.parse_args()

    started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    fp_before = fingerprint_from_db()
    record = get_validation(SOURCE_VID)
    if not record:
        raise SystemExit(f"源验证记录不存在：{SOURCE_VID}")

    codes = list(record["etf_codes"])
    summary = record.get("summary_json") or {}
    best = summary.get("best_param") or 250
    print(f"源记录 {SOURCE_VID}：样本内 {record['is_start']}~{record['is_end']}，"
          f"样本外 {record['oos_start']}~{record['oos_end']}，MA{best}，{len(codes)} 只")

    payload = {
        "phase": "3A.3.2",
        "source_validation_id": SOURCE_VID,
        "source_metrics": {
            "is": summary.get("is_metrics"),
            "oos": summary.get("oos_metrics"),
        },
        "corporate_action_version": DATA_VERSION,
        "fingerprint_before": fp_before,
        "started_at": started_at,
        "runs": {},
    }

    print("\n[样本外]")
    for label, strat, flag in (
        ("ma_trend_fixed", MovingAverageTrendStrategy(ma_window=best), True),
        ("ma_trend_legacy", MovingAverageTrendStrategy(ma_window=best), False),
        ("buy_and_hold_fixed", BuyAndHoldStrategy(), True),
        ("buy_and_hold_legacy", BuyAndHoldStrategy(), False),
    ):
        payload["runs"][label] = run_one(
            label, record["oos_start"], record["oos_end"], codes, strat, apply_ca=flag
        )

    print("\n[样本内]")
    for label, strat, flag in (
        ("ma_trend_is_fixed", MovingAverageTrendStrategy(ma_window=best), True),
        ("ma_trend_is_legacy", MovingAverageTrendStrategy(ma_window=best), False),
    ):
        payload["runs"][label] = run_one(
            label, record["is_start"], record["is_end"], codes, strat, apply_ca=flag
        )

    fp_after = fingerprint_from_db()
    payload["fingerprint_after"] = fp_after
    payload["data_unchanged"] = fp_before.get("sha256") == fp_after.get("sha256")

    out = PROJECT_ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                   encoding="utf-8")
    print(f"\n数据指纹一致：{payload['data_unchanged']}")
    print(f"输出 {out}")
    return 0 if payload["data_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
