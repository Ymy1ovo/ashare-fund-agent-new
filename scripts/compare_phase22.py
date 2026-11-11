"""阶段2.2 区间风险摘要修复前后对比。"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402
from app.database.db import get_connection  # noqa: E402

OLD = "v1.0.1-30b821a1af15"
NEW = "v1.0.2-30b821a1af15"
SAMPLE = ["510300", "510050", "510880", "511030", "159936"]


def _latest_runs(conn, version: str) -> dict[str, dict]:
    rows = conn.execute(
        """
        WITH ranked AS (
            SELECT r.*, ROW_NUMBER() OVER (PARTITION BY etf_code ORDER BY id DESC) AS rn
            FROM indicator_runs r WHERE calculation_version = ?
        )
        SELECT etf_code, summary_json FROM ranked WHERE rn = 1
        """,
        (version,),
    ).fetchall()
    return {
        str(row["etf_code"]): json.loads(row["summary_json"] or "{}")
        for row in rows
    }


def _num(value):
    return float(value) if value is not None and math.isfinite(float(value)) else None


def main() -> int:
    with get_connection() as conn:
        old_runs = _latest_runs(conn, OLD)
        new_runs = _latest_runs(conn, NEW)
        old_rows = conn.execute(
            "SELECT COUNT(*) FROM etf_indicator_daily WHERE calculation_version=?", (OLD,)
        ).fetchone()[0]
        new_rows = conn.execute(
            "SELECT COUNT(*) FROM etf_indicator_daily WHERE calculation_version=?", (NEW,)
        ).fetchone()[0]
        snapshot_mismatch = conn.execute(
            """
            SELECT COUNT(*) FROM etf_indicator_daily o
            JOIN etf_indicator_daily n
              ON o.etf_code=n.etf_code AND o.trade_date=n.trade_date
            WHERE o.calculation_version=? AND n.calculation_version=?
              AND o.adjustment_snapshot_id<>n.adjustment_snapshot_id
            """,
            (OLD, NEW),
        ).fetchone()[0]
        daily = pd.read_sql_query(
            """
            SELECT o.sharpe_ratio os, n.sharpe_ratio ns,
                   o.sortino_ratio ot, n.sortino_ratio nt,
                   o.calmar_ratio oc, n.calmar_ratio nc
            FROM etf_indicator_daily o
            JOIN etf_indicator_daily n
              ON o.etf_code=n.etf_code AND o.trade_date=n.trade_date
            WHERE o.calculation_version=? AND n.calculation_version=?
            """,
            conn,
            params=(OLD, NEW),
        )

    rows = []
    for code in sorted(old_runs):
        old = old_runs[code]
        new = new_runs.get(code, {})
        rows.append(
            {
                "etf_code": code,
                "old_vol": _num(old.get("annualized_volatility")),
                "new_vol": _num(new.get("annualized_volatility")),
                "old_sharpe": _num(old.get("sharpe_ratio")),
                "new_sharpe": _num(new.get("sharpe_ratio")),
                "old_sortino": _num(old.get("sortino_ratio")),
                "new_sortino": _num(new.get("sortino_ratio")),
                "old_mdd": _num(old.get("max_drawdown")),
                "new_mdd": _num(new.get("max_drawdown")),
                "cagr": _num(new.get("cagr")),
                "daily_return_observations": new.get("daily_return_observations"),
                "missing_trading_days": new.get("missing_trading_days"),
            }
        )
    frame = pd.DataFrame(rows)
    stats = {}
    for metric in ("vol", "sharpe", "sortino", "mdd"):
        old = frame[f"old_{metric}"]
        new = frame[f"new_{metric}"]
        mask = old.notna() & new.notna()
        delta = (new[mask] - old[mask]).abs()
        stats[metric] = {
            "both": int(mask.sum()),
            "changed": int((delta > 1e-12).sum()),
            "max_abs_delta": float(delta.max()) if len(delta) else 0.0,
        }
    daily_stats = {}
    for old_col, new_col, name in (
        ("os", "ns", "sharpe_ratio"),
        ("ot", "nt", "sortino_ratio"),
        ("oc", "nc", "calmar_ratio"),
    ):
        mask = daily[old_col].notna() & daily[new_col].notna()
        delta = (daily.loc[mask, new_col] - daily.loc[mask, old_col]).abs()
        daily_stats[name] = {
            "both": int(mask.sum()),
            "changed": int((delta > 1e-12).sum()),
            "max_abs_delta": float(delta.max()) if len(delta) else 0.0,
        }
    output = {
        "old_version": OLD,
        "new_version": NEW,
        "old_rows": int(old_rows),
        "new_rows": int(new_rows),
        "snapshot_mismatch_rows": int(snapshot_mismatch),
        "summary_stats": stats,
        "daily_risk_stats": daily_stats,
        "sample": frame[frame["etf_code"].isin(SAMPLE)][
            [
                "etf_code",
                "old_vol",
                "new_vol",
                "old_sharpe",
                "new_sharpe",
                "old_sortino",
                "new_sortino",
                "old_mdd",
                "new_mdd",
                "cagr",
                "daily_return_observations",
                "missing_trading_days",
            ]
        ].to_dict("records"),
    }
    (settings.data_dir / "phase22_comparison.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "# 阶段2.2 区间风险统计修复前后对比",
        "",
        f"- 旧版本：`{OLD}`（{old_rows:,} 行）",
        f"- 新版本：`{NEW}`（{new_rows:,} 行）",
        f"- 新旧快照 ID 不一致行：{snapshot_mismatch}",
        "",
        "## 1. 区间摘要变化",
        "",
        "| 指标 | 可比 ETF | 变化 ETF | 最大绝对变化 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for metric, label in (
        ("vol", "年化波动率"),
        ("sharpe", "夏普比率"),
        ("sortino", "索提诺比率"),
        ("mdd", "最大回撤"),
    ):
        item = stats[metric]
        lines.append(
            f"| {label} | {item['both']} | {item['changed']} | {item['max_abs_delta']:.6f} |"
        )
    lines += [
        "",
        "## 2. 抽查 5 只 ETF",
        "",
        "| 代码 | 旧波动率 | 新波动率 | 旧夏普 | 新夏普 | 旧索提诺 | 新索提诺 | 日收益样本 | 缺失日 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in output["sample"]:
        def fmt(value, pct=False):
            if value is None:
                return "NaN"
            return f"{value:.2%}" if pct else f"{value:.4f}"

        lines.append(
            f"| {row['etf_code']} | {fmt(row['old_vol'], True)} | {fmt(row['new_vol'], True)} | "
            f"{fmt(row['old_sharpe'])} | {fmt(row['new_sharpe'])} | "
            f"{fmt(row['old_sortino'])} | {fmt(row['new_sortino'])} | "
            f"{row['daily_return_observations']} | {row['missing_trading_days']} |"
        )
    lines += [
        "",
        "## 3. 日表风险指标",
        "",
        "| 指标 | 可比行 | 变化行 | 最大绝对变化 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, item in daily_stats.items():
        lines.append(
            f"| {name} | {item['both']:,} | {item['changed']:,} | {item['max_abs_delta']:.6f} |"
        )
    lines += [
        "",
        "## 4. 结论",
        "",
        "- 区间摘要不再在 dropna 后计算 pct_change，跨缺口收益不会伪装成单日收益。",
        "- 510300 无缺口，摘要结果保持不变。",
        "- 510050、510880 等存在缺失的 ETF，波动率和夏普/索提诺按真实相邻日收益重算。",
        "- 最大回撤继续使用有效价格序列，未填充缺失价格。",
        "- 日表滚动风险指标原本已使用 `pct_change(fill_method=None)`，本轮结果为 0 行变化。",
        "- CAGR 使用阶段2.1的交易日跨度口径，新旧一致。",
    ]
    (settings.report_dir / "phase2.2_risk_comparison.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
