"""生成阶段2指标数据质量报告。"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402
from app.database.db import get_connection  # noqa: E402
from app.database.indicators import INDICATOR_COLUMNS  # noqa: E402


def main() -> int:
    with get_connection() as conn:
        version_row = conn.execute(
            "SELECT calculation_version FROM indicator_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        version = version_row[0] if version_row else None
        if not version:
            raise SystemExit("没有指标运行记录")
        total = conn.execute(
            "SELECT COUNT(*) FROM etf_indicator_daily WHERE calculation_version=?", (version,)
        ).fetchone()[0]
        etfs = conn.execute(
            "SELECT COUNT(DISTINCT etf_code) FROM etf_indicator_daily WHERE calculation_version=?",
            (version,),
        ).fetchone()[0]
        quality = {
            str(row["quality_status"]): int(row["n"])
            for row in conn.execute(
                "SELECT quality_status, COUNT(*) AS n FROM etf_indicator_daily "
                "WHERE calculation_version=? GROUP BY quality_status",
                (version,),
            )
        }
        trade = {
            str(row["trade_status"]): int(row["n"])
            for row in conn.execute(
                "SELECT trade_status, COUNT(*) AS n FROM etf_indicator_daily "
                "WHERE calculation_version=? GROUP BY trade_status",
                (version,),
            )
        }
        coverage = {}
        for column in INDICATOR_COLUMNS:
            row = conn.execute(
                f"SELECT COUNT(*) AS total, SUM(CASE WHEN {column} IS NOT NULL THEN 1 ELSE 0 END) AS valid "
                "FROM etf_indicator_daily WHERE calculation_version=?",
                (version,),
            ).fetchone()
            valid = int(row["valid"] or 0)
            coverage[column] = {
                "valid_rows": valid,
                "total_rows": int(row["total"]),
                "coverage": round(valid / row["total"], 6) if row["total"] else 0.0,
            }
        per_etf = [
            dict(row)
            for row in conn.execute(
                """
                SELECT d.etf_code, COUNT(*) AS rows,
                       SUM(CASE WHEN d.quality_status = 'invalid' THEN 1 ELSE 0 END) AS invalid_rows,
                       SUM(CASE WHEN d.trade_status = 'zero_volume' THEN 1 ELSE 0 END) AS zero_volume_rows,
                       SUM(CASE WHEN d.trade_status = 'missing_volume' THEN 1 ELSE 0 END) AS missing_volume_rows,
                       MIN(d.trade_date) AS start_date, MAX(d.trade_date) AS end_date,
                       MAX(d.adjustment_snapshot_id) AS snapshot_id,
                       MAX(d.calculation_version) AS calculation_version
                FROM etf_indicator_daily d
                WHERE d.calculation_version=?
                GROUP BY d.etf_code ORDER BY d.etf_code
                """,
                (version,),
            )
        ]
        current = {
            str(row["code"]): int(row["id"])
            for row in conn.execute(
                "SELECT code, id FROM etf_adjustment_snapshots WHERE is_current = 1"
            )
        }
        latest_runs = [
            dict(row)
            for row in conn.execute(
                """
                WITH ranked AS (
                    SELECT r.*, ROW_NUMBER() OVER (PARTITION BY etf_code ORDER BY id DESC) AS rn
                    FROM indicator_runs r WHERE r.calculation_version = ?
                ) SELECT * FROM ranked WHERE rn = 1 ORDER BY etf_code
                """,
                (version,),
            )
        ]
        issue_counts: dict[str, int] = {}
        for run in latest_runs:
            try:
                issues = json.loads(run.get("quality_json") or "{}").get("issues", [])
            except json.JSONDecodeError:
                issues = []
            for issue in issues:
                key = str(issue.get("type"))
                issue_counts[key] = issue_counts.get(key, 0) + 1

    for row in per_etf:
        row["stale"] = current.get(str(row["etf_code"])) != row["snapshot_id"]
    status_counts: dict[str, int] = {}
    for run in latest_runs:
        status_counts[str(run["status"])] = status_counts.get(str(run["status"]), 0) + 1

    output = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "version": version,
        "etf_count": etfs,
        "row_count": total,
        "quality_counts": quality,
        "trade_counts": trade,
        "coverage": coverage,
        "per_etf": per_etf,
        "latest_run_status_counts": status_counts,
        "issue_counts": issue_counts,
    }
    (settings.data_dir / "indicator_quality.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    lines = [
        "# 阶段2 指标数据质量报告",
        "",
        f"- 生成时间：{output['generated_at']}",
        f"- 指标版本：{version}",
        f"- 有指标数据的 ETF：{etfs}",
        f"- 指标行数：{total:,}",
        f"- 指标运行状态：{status_counts}",
        f"- 行质量状态：{quality}",
        f"- 交易状态：{trade}",
        "",
        "## 1. 指标覆盖率",
        "",
        "| 指标 | 有效行 | 总行 | 覆盖率 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for column, item in coverage.items():
        lines.append(
            f"| {column} | {item['valid_rows']:,} | {item['total_rows']:,} | {item['coverage']:.2%} |"
        )
    lines += [
        "",
        "## 2. 逐 ETF 质量",
        "",
        "| 代码 | 行数 | 无效行 | 零成交量 | 缺失成交量 | 快照ID | 是否过期 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in per_etf:
        lines.append(
            f"| {row['etf_code']} | {row['rows']:,} | {row['invalid_rows']} | "
            f"{row['zero_volume_rows']} | {row['missing_volume_rows']} | "
            f"{row['snapshot_id']} | {'是' if row['stale'] else '否'} |"
        )
    lines += [
        "",
        "## 3. 质量问题类型（按最新运行统计）",
        "",
        "| 类型 | 涉及 ETF 数 |",
        "| --- | ---: |",
    ]
    for key, value in sorted(issue_counts.items()):
        lines.append(f"| {key} | {value} |")
    lines += [
        "",
        "## 4. 说明",
        "",
        "- `invalid` 行包含缺失复权价、原始/复权 OHLC 不合法等，相关指标返回空值。",
        "- `zero_volume` 是交易状态标记，不等于价格无效；未用前值填充。",
        "- 覆盖率低于 100% 主要来自上市初期历史不足、250 日窗口、日历缺口或数据源缺失。",
        "- 所有指标行均记录计算版本、复权快照和 run_id。",
        "",
    ]
    report = settings.report_dir / "phase2_indicator_quality.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"report={report} etfs={etfs} rows={total} status={status_counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
