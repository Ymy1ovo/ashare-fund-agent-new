"""历史回测重放（阶段3A.3.2 起，3A.3.2.3.1 改造成通用工具）。

用法：

    # 指定单条源记录重放（推荐）
    python scripts/replay_3a3_2.py --source ac8f4cc7cf234d7e

    # 强制重跑（忽略已有成功重放）
    python scripts/replay_3a3_2.py --source ac8f4cc7cf234d7e --force

    # 批量：只重放分类为 legacy 的记录；单条失败不影响其他
    python scripts/replay_3a3_2.py --pending

    # 旧行为（不指定 source 时保留）：3A.3.2 的固定对照片段
    python scripts/replay_3a3_2.py --legacy-comparison

纪律：

- 不覆盖任何历史记录；新 run_id 由引擎生成。
- 源参数从 `backtest_runs.config_json` 读取；读不到就判 non_replayable，不猜。
- 重放一律使用当前正式公司行为加载逻辑（apply_corporate_actions=True）。
- 重放前后各算一次行情指纹，必须一致。
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
from app.replay.manifest import (  # noqa: E402
    BACKTEST,
    CLASS_LEGACY,
    ReplayError,
    backtest_manifest,
)
from app.replay.registry import (  # noqa: E402
    STATUS_FAILED,
    STATUS_SKIPPED,
    STATUS_SUCCESS,
    init_replay_schema,
    success_map,
)
from app.replay.runner import replay_backtest, replay_many  # noqa: E402
from app.validation.fingerprint import fingerprint_from_db  # noqa: E402
from app.validation.storage import get_validation  # noqa: E402

# 3A.3.2 时期的固定对照源记录；--legacy-comparison 仍按原样使用
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
        "win_rate": perf.win_rate,
        "profit_loss_ratio": perf.profit_loss_ratio,
        "trade_count": perf.trade_count,
        "turnover": perf.turnover,
        "total_cost": perf.total_cost,
    }


def run_one(label: str, start: str, end: str, codes: list[str], strategy,
            *, apply_ca: bool) -> dict:
    """3A.3.2 固定对照流程：内存回测，不落库。"""
    from app.backtest.config import BacktestConfig

    cfg = BacktestConfig(
        start_date=start, end_date=end, initial_cash=1_000_000.0,
        apply_corporate_actions=apply_ca,
    )
    engine = BacktestEngine(cfg, strategy)
    started = time.time()
    result = engine.run(codes, indicator_version=INDICATOR_VERSION)
    perf = compute_performance(
        result.daily, result.trades, result.orders, result.initial_cash,
        annualization=cfg.annualization, risk_free_rate=cfg.risk_free_rate,
    )
    print(f"  [{label}] ca={apply_ca} ret={perf.total_return:+.6f} "
          f"dd={perf.max_drawdown:+.6f} sharpe={perf.sharpe_ratio:.4f} "
          f"trades={perf.trade_count} ({round(time.time()-started,1)}s)")
    return {
        "label": label,
        "apply_corporate_actions": apply_ca,
        "corporate_action_version": DATA_VERSION if apply_ca else "disabled",
        "corporate_action_digest": getattr(engine, "corporate_action_digest", None),
        "accounting_basis": result.accounting_basis,
        "formal_valuation": result.formal_valuation,
        "excluded_actions": len(getattr(engine, "excluded_actions", [])),
        "dividend_settlements": len(getattr(engine, "dividend_settlements", [])),
        "range": f"{start}~{end}",
        "metrics": _metrics(perf),
        "nav_dates": int(len(risk_return_series(result.daily)[0])),
        "applied_actions": len(engine.corporate_action_log),
        "action_log": engine.corporate_action_log,
        "notes": [n for n in result.notes if "公司行为" in n],
        "run_id": result.run_id,
        "input_hash": result.input_hash,
    }


def _legacy_comparison(args) -> int:
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
        "source_metrics": {"is": summary.get("is_metrics"), "oos": summary.get("oos_metrics")},
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
            label, record["oos_start"], record["oos_end"], codes, strat, apply_ca=flag)

    print("\n[样本内]")
    for label, strat, flag in (
        ("ma_trend_is_fixed", MovingAverageTrendStrategy(ma_window=best), True),
        ("ma_trend_is_legacy", MovingAverageTrendStrategy(ma_window=best), False),
    ):
        payload["runs"][label] = run_one(
            label, record["is_start"], record["is_end"], codes, strat, apply_ca=flag)

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


def _print_outcome(outcome) -> None:
    tag = {STATUS_SUCCESS: "OK  ", STATUS_SKIPPED: "SKIP", STATUS_FAILED: "FAIL"}[outcome.status]
    line = f"  [{tag}] {outcome.source_id}"
    if outcome.replay_id:
        line += f" -> {outcome.replay_id}"
    if outcome.reason:
        line += f"  （{outcome.reason}）"
    print(line, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="历史回测重放（可指定源 run_id）")
    parser.add_argument("--source", default=None, help="源 backtest run_id")
    parser.add_argument("--pending", action="store_true",
                        help="批量重放所有分类为 legacy 的记录")
    parser.add_argument("--force", action="store_true", help="忽略已有成功重放，强制重跑")
    parser.add_argument("--dry-run", action="store_true", help="只检查可重放性，不执行")
    parser.add_argument("--legacy-comparison", action="store_true",
                        help="旧行为：3A.3.2 固定对照片段（不落库）")
    parser.add_argument("--out", default="data/replay_3a3_2.json")
    args = parser.parse_args()

    if args.legacy_comparison:
        return _legacy_comparison(args)
    if not args.source and not args.pending:
        parser.error("必须指定 --source <run_id> 或 --pending（或 --legacy-comparison）")

    init_replay_schema()
    fp_before = fingerprint_from_db()

    if args.source:
        manifest = {item["source_id"]: item for item in
                    backtest_manifest(successes=success_map(BACKTEST))}
        item = manifest.get(args.source)
        if not item:
            print(f"源回测记录不存在：{args.source}")
            return 2
        if args.dry_run:
            print(f"{args.source}：{item['classification']}（{item['classification_reason']}）")
            print(f"  可重放：{item['replayable']}")
            return 0 if item["replayable"] else 1
        try:
            outcome = replay_backtest(args.source, force=args.force)
        except ReplayError as exc:
            print(f"失败：{exc}")
            return 2
        _print_outcome(outcome)
        ok = outcome.status in (STATUS_SUCCESS, STATUS_SKIPPED)
    else:
        targets = [i["source_id"] for i in backtest_manifest()
                   if i["classification"] == CLASS_LEGACY]
        if not targets:
            print("没有需要重放的 backtest 记录。")
            return 0
        print(f"待重放 {len(targets)} 条：{'、'.join(targets)}")
        if args.dry_run:
            return 0
        outcomes = replay_many(BACKTEST, targets, force=args.force,
                               on_progress=_print_outcome)
        ok = all(item.status in (STATUS_SUCCESS, STATUS_SKIPPED) for item in outcomes)

    fp_after = fingerprint_from_db()
    same = fp_before.get("sha256") == fp_after.get("sha256")
    print(f"\n行情指纹前后一致：{same}")
    print(f"  前 {fp_before.get('sha256')}")
    print(f"  后 {fp_after.get('sha256')}")
    return 0 if (ok and same) else 1


if __name__ == "__main__":
    raise SystemExit(main())
