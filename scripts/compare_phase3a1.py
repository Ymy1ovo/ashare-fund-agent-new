"""阶段3A.1：风险指标口径修复前后的对比（真实数据）。"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.backtest.api import get_nav, get_run  # noqa: E402
from app.backtest.metrics import compute_performance  # noqa: E402
from app.backtest.models import DailySnapshot  # noqa: E402
from app.config import settings  # noqa: E402
from app.database.db import get_connection  # noqa: E402

# 阶段3A 用旧口径跑出的回测记录
OLD_RUNS = [
    ("7181d2a6ed3f4555", "buy_and_hold 5只（3A 旧口径）"),
    ("dbf4bc0e46104b23", "ma_trend(20) 5只（3A 旧口径）"),
    ("6a7fe99ac55a4639", "ma_trend(20) 46只（3A 旧口径）"),
    ("8412fc1cefb4437e", "buy_and_hold 510300（3A.1 新口径）"),
    ("08a4c7f1529b42e2", "ma_trend(20) 5只（3A.1 新口径）"),
]


def _daily(run_id):
    rows = get_nav(run_id)
    snapshots = []
    for row in rows:
        status = row.get("price_status")
        if not isinstance(status, dict):
            status = json.loads(status) if status else {}
        snapshots.append(
            DailySnapshot(
                trade_date=date.fromisoformat(row["trade_date"]),
                cash=row["cash"],
                market_value=row["market_value"],
                total_assets=row["total_assets"],
                nav=row["nav"],
                daily_return=row["daily_return"],
                price_status=status,
                positions={},  # 旧记录没有逐日持仓明细的 code->qty 映射，见下方补充
            )
        )
    # 用 positions_daily 还原持仓，才能判定"持仓ETF缺报价"
    with get_connection() as conn:
        held = conn.execute(
            "SELECT trade_date, code, quantity FROM backtest_positions_daily "
            "WHERE run_id=? ORDER BY trade_date", (run_id,)
        ).fetchall()
    by_date: dict[str, dict[str, int]] = {}
    for row in held:
        by_date.setdefault(row["trade_date"], {})[row["code"]] = row["quantity"]
    for snap in snapshots:
        snap.positions = by_date.get(snap.trade_date.isoformat(), {})
    return snapshots


def _fmt(value, pct=False):
    if value is None:
        return "-"
    return f"{value:.2%}" if pct else f"{value:.4f}"


def main() -> int:
    rows = []
    for run_id, label in OLD_RUNS:
        run = get_run(run_id)
        if not run:
            continue
        old = (run.get("summary_json") or {}).get("performance", {})
        daily = _daily(run_id)
        new = compute_performance(
            daily, [], [], run["initial_cash"],
            annualization=252, risk_free_rate=0.0,
        )
        rows.append({
            "run_id": run_id,
            "label": label,
            "old_sharpe": old.get("sharpe_ratio"),
            "new_sharpe": new.sharpe_ratio,
            "old_sortino": old.get("sortino_ratio"),
            "new_sortino": new.sortino_ratio,
            "old_vol": old.get("annualized_volatility"),
            "new_vol": new.annualized_volatility,
            "cagr": new.cagr,
            "risk_sample_days": new.risk_sample_days,
            "gap_excluded": new.gap_return_days_excluded,
            "trading_days": new.trading_days,
        })
    (settings.data_dir / "phase3a1_comparison.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "# 阶段3A.1 风险指标修复前后对比（真实数据）",
        "",
        "旧值来自阶段3A 的 `summary_json.performance`（Sharpe/Sortino 用 CAGR 当分子）；",
        "新值用同一批每日净值 + 新口径重算，隔离口径变化本身，不掺入净值差异。",
        "",
        "| 回测 | 旧Sharpe | 新Sharpe | 旧Sortino | 新Sortino | 年化波动率 | CAGR | 风险样本日 | 排除日 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row['label']} | {_fmt(row['old_sharpe'])} | {_fmt(row['new_sharpe'])} | "
            f"{_fmt(row['old_sortino'])} | {_fmt(row['new_sortino'])} | "
            f"{_fmt(row['new_vol'], True)} | {_fmt(row['cagr'], True)} | "
            f"{row['risk_sample_days']} | {row['gap_excluded']} |"
        )
    lines += [
        "",
        "## 变化原因",
        "",
        "1. 旧口径：`Sharpe = (CAGR - rf) / 年化波动率`，分子是多年年化复合收益，"
        "与分母的日收益波动率不在同一量纲。",
        "2. 新口径：`Sharpe = 日均超额收益 × 252 / (日收益标准差 × sqrt(252))`，"
        "分子分母都来自同一条有效日收益序列。",
        "3. 持仓 ETF 缺有效报价的当日及次日，日收益被排除出风险统计，"
        "避免把 stale_price 的估值变动当成正常单日收益。",
        "4. CAGR 保持不变，仍用交易日跨度计算，不再参与 Sharpe/Sortino。",
        "",
    ]
    path = settings.report_dir / "phase3A1_risk_comparison.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
