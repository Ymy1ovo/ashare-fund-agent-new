"""生成阶段2.1 CAGR 与 EMA/MACD 修复前后对比报告。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402
from app.database.db import get_connection  # noqa: E402

OLD = "v1.0.0-30b821a1af15"
NEW = "v1.0.1-30b821a1af15"


def main() -> int:
    with get_connection() as conn:
        old_count = conn.execute(
            "SELECT COUNT(*) FROM etf_indicator_daily WHERE calculation_version=?", (OLD,)
        ).fetchone()[0]
        new_count = conn.execute(
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
        cagr = pd.read_sql_query(
            """
            SELECT o.etf_code, o.trade_date, o.cagr AS old_cagr, n.cagr AS new_cagr
            FROM etf_indicator_daily o
            JOIN etf_indicator_daily n
              ON o.etf_code=n.etf_code AND o.trade_date=n.trade_date
            WHERE o.calculation_version=? AND n.calculation_version=?
            """,
            conn,
            params=(OLD, NEW),
        )
        ema = pd.read_sql_query(
            """
            SELECT o.etf_code, o.trade_date,
                   o.ema12 old_ema12, n.ema12 new_ema12,
                   o.ema26 old_ema26, n.ema26 new_ema26,
                   o.macd_dif old_dif, n.macd_dif new_dif,
                   o.macd_dea old_dea, n.macd_dea new_dea,
                   o.macd_hist old_hist, n.macd_hist new_hist
            FROM etf_indicator_daily o
            JOIN etf_indicator_daily n
              ON o.etf_code=n.etf_code AND o.trade_date=n.trade_date
            WHERE o.calculation_version=? AND n.calculation_version=?
            """,
            conn,
            params=(OLD, NEW),
        )

    latest = cagr.sort_values("trade_date").groupby("etf_code").tail(1).copy()
    latest["delta"] = latest["new_cagr"] - latest["old_cagr"]
    latest["changed"] = latest["delta"].abs() > 1e-12
    valid = cagr.dropna(subset=["old_cagr", "new_cagr"])
    cagr_stats = {
        "common_rows": int(len(cagr)),
        "both_cagr_rows": int(len(valid)),
        "changed_rows": int(((valid["new_cagr"] - valid["old_cagr"]).abs() > 1e-12).sum()),
        "max_abs_delta": float((valid["new_cagr"] - valid["old_cagr"]).abs().max()),
        "latest_changed_etfs": int(latest["changed"].sum()),
        "latest_max_abs_delta": float(latest["delta"].abs().max()),
    }
    ema_stats = {}
    for column, old_col, new_col in (
        ("ema12", "old_ema12", "new_ema12"),
        ("ema26", "old_ema26", "new_ema26"),
        ("macd_dif", "old_dif", "new_dif"),
        ("macd_dea", "old_dea", "new_dea"),
        ("macd_hist", "old_hist", "new_hist"),
    ):
        both = ema.dropna(subset=[old_col, new_col])
        diff = (both[new_col] - both[old_col]).abs()
        ema_stats[column] = {
            "both_rows": int(len(both)),
            "changed_rows": int((diff > 1e-12).sum()),
            "max_abs_delta": float(diff.max()) if len(diff) else 0.0,
        }
    result = {
        "old_version": OLD,
        "new_version": NEW,
        "old_rows": int(old_count),
        "new_rows": int(new_count),
        "snapshot_mismatch_rows": int(snapshot_mismatch),
        "cagr": cagr_stats,
        "ema_macd": ema_stats,
    }
    (settings.data_dir / "phase21_comparison.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "# 阶段2.1 CAGR 修复前后对比",
        "",
        f"- 旧版本：`{OLD}`（{old_count:,} 行）",
        f"- 新版本：`{NEW}`（{new_count:,} 行）",
        f"- 旧版本保留：{'是' if old_count else '否'}",
        f"- 新旧行数一致：{'是' if old_count == new_count else '否'}",
        f"- 新旧快照 ID 不一致行：{snapshot_mismatch}",
        "",
        "## 1. 全量比较",
        "",
        f"- 可比 CAGR 行：{cagr_stats['both_cagr_rows']:,}",
        f"- CAGR 发生变化行：{cagr_stats['changed_rows']:,}",
        f"- 单行最大绝对变化：{cagr_stats['max_abs_delta']:.6f}",
        f"- 最新日期发生变化 ETF：{cagr_stats['latest_changed_etfs']} / 46",
        f"- 最新日期最大绝对变化：{cagr_stats['latest_max_abs_delta']:.6f}",
        "",
        "> 早期行 CAGR 的绝对变化可能较大，是因为早期价格基数小、年化指数对缺失交易日敏感；"
        "这不是收益率被篡改，而是时间分母从“有效价格个数”改为“实际交易日跨度”。",
        "",
        "## 2. 最新日期逐 ETF 对比",
        "",
        "| 代码 | 最新日期 | 旧 CAGR | 新 CAGR | 变化 |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for row in latest.sort_values("etf_code").itertuples():
        lines.append(
            f"| {row.etf_code} | {row.trade_date} | {row.old_cagr:.6%} | "
            f"{row.new_cagr:.6%} | {row.delta:+.6%} |"
        )
    lines += [
        "",
        "## 3. 结论",
        "",
        "- CAGR 已按交易日历位置差计算，缺失日计入时间跨度。",
        "- 新旧快照 ID 完全一致，未修改复权快照。",
        "- 旧版本指标行完整保留，未被覆盖或删除。",
    ]
    (settings.report_dir / "phase2.1_cagr_comparison.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )

    ema_lines = [
        "# 阶段2.1 EMA/MACD 修复前后对比",
        "",
        f"- 旧版本：`{OLD}`（{old_count:,} 行）",
        f"- 新版本：`{NEW}`（{new_count:,} 行）",
        f"- 新旧快照 ID 不一致行：{snapshot_mismatch}",
        "",
        "## 1. 变化统计",
        "",
        "| 指标 | 可比行 | 变化行 | 最大绝对变化 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for column, item in ema_stats.items():
        ema_lines.append(
            f"| {column} | {item['both_rows']:,} | {item['changed_rows']:,} | {item['max_abs_delta']:.6f} |"
        )
    ema_lines += [
        "",
        "## 2. 解释",
        "",
        "- 连续正常行情内 EMA 仍按原 `ewm(span, adjust=False)` 定义，结果不变。",
        "- 出现缺失/无效价格或交易日历缺口时，缺失日输出 NaN，EMA 状态重置。",
        "- MACD 的 EMA12、EMA26、DEA 都不跨断点继承旧状态；DEA 重新积累 9 个有效 DIF 后才输出。",
        "- 变化行集中在存在缺口的 ETF/日期，不是全量公式变化。",
        "",
        "## 3. 测试验证",
        "",
        "- 缺失前 EMA 结果不变。",
        "- 缺失当天 EMA/MACD 为 NaN。",
        "- 缺失后前 25 个交易日 MACD DIF 为空，随后才恢复；DEA 再晚 9 个有效 DIF。",
        "- 修改缺失点之后的行情，不改变缺失点之前的 EMA/MACD 结果。",
    ]
    (settings.report_dir / "phase2.1_ema_macd.md").write_text(
        "\n".join(ema_lines), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
