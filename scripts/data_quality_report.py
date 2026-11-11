"""生成阶段1B数据质量报告（只读数据库，不修正数据）。"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402
from app.database.db import (  # noqa: E402
    get_adjustment_summary,
    get_connection,
    get_market_data_summary,
    get_sync_details,
)


def _scalar(conn, sql: str, params: tuple = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def build_report() -> tuple[str, dict[str, Any]]:
    summary = get_market_data_summary()
    adjustment = get_adjustment_summary()
    with get_connection() as conn:
        duplicate_dates = _scalar(
            conn,
            "SELECT COUNT(*) FROM (SELECT code, trade_date, COUNT(*) c FROM etf_daily_prices "
            "GROUP BY code, trade_date HAVING c > 1)",
        )
        future_dates = _scalar(
            conn,
            "SELECT COUNT(*) FROM etf_daily_prices WHERE trade_date > date('now')",
        )
        ohlc_violations = _scalar(
            conn,
            "SELECT COUNT(*) FROM etf_daily_prices WHERE close <= 0 OR high < low "
            "OR close > high OR close < low OR open > high OR open < low",
        )
        negative_volume = _scalar(
            conn,
            "SELECT COUNT(*) FROM etf_daily_prices WHERE volume < 0 OR amount < 0",
        )
        zero_volume = _scalar(
            conn,
            "SELECT COUNT(*) FROM etf_daily_prices WHERE volume = 0",
        )
        missing_adjusted = _scalar(
            conn,
            "SELECT COUNT(*) FROM etf_daily_prices WHERE adjusted_close IS NULL",
        )
        missing_adjusted_codes = conn.execute(
            "SELECT code, COUNT(*) AS n FROM etf_daily_prices "
            "WHERE adjusted_close IS NULL GROUP BY code ORDER BY code"
        ).fetchall()
        gap_rows = conn.execute(
            """
            WITH ordered AS (
                SELECT code, trade_date,
                       LAG(trade_date) OVER (PARTITION BY code ORDER BY trade_date) AS prev_date
                FROM etf_daily_prices
            )
            SELECT code, COUNT(*) AS gap_count
            FROM ordered
            WHERE prev_date IS NOT NULL AND julianday(trade_date) - julianday(prev_date) > 20
            GROUP BY code
            ORDER BY code
            """
        ).fetchall()
        sources = conn.execute(
            "SELECT code, GROUP_CONCAT(DISTINCT source) AS sources, COUNT(DISTINCT source) AS n "
            "FROM etf_daily_prices GROUP BY code HAVING n > 1 ORDER BY code"
        ).fetchall()
        adjustment_counts = conn.execute(
            "SELECT adjustment_type, COUNT(*) AS n FROM etf_daily_prices GROUP BY adjustment_type"
        ).fetchall()
        snapshot_rows = conn.execute(
            """
            SELECT code, id, status, collected_at, coverage_start, coverage_end,
                   raw_rows, matched_rows, missing_rows
            FROM etf_adjustment_snapshots
            WHERE is_current = 1
            ORDER BY code
            """
        ).fetchall()
        mixed_snapshot_codes = conn.execute(
            """
            SELECT code, COUNT(DISTINCT adjustment_snapshot_id) AS n
            FROM etf_daily_prices
            WHERE adjustment_snapshot_id IS NOT NULL
            GROUP BY code HAVING n > 1 ORDER BY code
            """
        ).fetchall()
        rows_without_snapshot = _scalar(
            conn, "SELECT COUNT(*) FROM etf_daily_prices WHERE adjustment_snapshot_id IS NULL"
        )
        latest_run = conn.execute(
            "SELECT id, run_type, status, started_at, finished_at FROM sync_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        failed_details = []
        if latest_run is not None:
            failed_details = [
                row
                for row in get_sync_details(int(latest_run["id"]))
                if row["status"] != "success"
            ]

    data = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
        "duplicate_dates": duplicate_dates,
        "future_dates": future_dates,
        "ohlc_violations": ohlc_violations,
        "negative_volume_or_amount": negative_volume,
        "zero_volume": zero_volume,
        "missing_adjusted_close": missing_adjusted,
        "missing_adjusted_codes": [dict(row) for row in missing_adjusted_codes],
        "gap_codes": [dict(row) for row in gap_rows],
        "source_conflicts": [dict(row) for row in sources],
        "adjustment_counts": {str(row["adjustment_type"]): int(row["n"]) for row in adjustment_counts},
        "adjustment": adjustment,
        "adjustment_snapshots": [dict(row) for row in snapshot_rows],
        "mixed_snapshot_codes": [dict(row) for row in mixed_snapshot_codes],
        "rows_without_snapshot": rows_without_snapshot,
        "latest_run": dict(latest_run) if latest_run else None,
        "failed_or_empty_details": failed_details,
    }
    return render(data), data


def render(data: dict[str, Any]) -> str:
    summary = data["summary"]
    lines = [
        "# 阶段1B 数据质量报告",
        "",
        f"- 生成时间：{data['generated_at']}",
        f"- ETF 总数：{summary['etf_total']}",
        f"- 已入库 ETF：{summary['etf_ingested']}",
        f"- 行情总记录：{summary['total_records']:,}",
        f"- 未入库 ETF：{summary['missing_etf_count']}",
        f"- 异常记录：{summary['anomaly_record_count']}",
        f"- 最近同步：{summary['last_sync_at'] or '无'}（{summary['last_sync_status'] or '无'}）",
        f"- 行情最近采集时间：{summary['last_price_collected_at'] or '无'}",
        "",
        "## 检查结果",
        "",
        "| 检查项 | 数量 | 说明 |",
        "| --- | ---: | --- |",
        f"| 重复交易日 | {data['duplicate_dates']} | 由 (code, trade_date) 主键约束 |",
        f"| 未来日期 | {data['future_dates']} | 入库前已过滤未来日期 |",
        f"| OHLC 关系异常 | {data['ohlc_violations']} | 只标记，不修改原始价格 |",
        f"| 成交量/成交额为负 | {data['negative_volume_or_amount']} | 标记为 warning |",
        f"| 成交量为 0 | {data['zero_volume']} | 标记为 warning |",
        f"| 前复权收盘价为空 | {data['missing_adjusted_close']} | 原始行情保留，复权字段为空 |",
        f"| 跨来源冲突（同代码多来源） | {len(data['source_conflicts'])} | 当前单一行情来源 |",
        "",
        "## 质量状态分布",
        "",
        "| 状态 | 记录数 |",
        "| --- | ---: |",
    ]
    for status, count in sorted(summary.get("quality_counts", {}).items()):
        lines.append(f"| {status} | {count:,} |")
    lines += ["", "## 复权字段", "", "| adjustment_type | 记录数 |", "| --- | ---: |"]
    for adjustment_type, count in sorted(data["adjustment_counts"].items()):
        lines.append(f"| {adjustment_type} | {count:,} |")
    lines += ["", "前复权收盘价为空的基金："]
    if data["missing_adjusted_codes"]:
        for row in data["missing_adjusted_codes"]:
            lines.append(f"- {row['code']}：{row['n']} 条")
    else:
        lines.append("- 无")

    adj = data["adjustment"]
    lines += [
        "",
        "## 前复权调整快照一致性",
        "",
        f"- 有当前快照 ETF：{adj['current_snapshot_etfs']} / {summary['etf_total']}",
        f"- 部分覆盖快照：{adj['partial_snapshot_etfs']}",
        f"- 当前失败快照：{adj['failed_current_snapshots']}",
        f"- 混合快照 ETF：{adj['mixed_snapshot_etfs']}",
        f"- 复权价缺失记录：{adj['adjusted_missing_records']}",
        f"- 无快照引用的行情记录：{data['rows_without_snapshot']}",
        f"- 最近复权刷新：{adj['last_adjustment_refresh_at'] or '无'}（{adj['last_adjustment_refresh_status'] or '无'}）",
        "",
        "| 代码 | 快照ID | 状态 | 采集时间 | 复权覆盖 | 原始行 | 匹配行 | 缺失行 |",
        "| --- | ---: | --- | --- | --- | ---: | ---: | ---: |",
    ]
    for row in data["adjustment_snapshots"]:
        lines.append(
            f"| {row['code']} | {row['id']} | {row['status']} | {row['collected_at']} | "
            f"{row['coverage_start'] or '-'} ~ {row['coverage_end'] or '-'} | "
            f"{row['raw_rows']} | {row['matched_rows']} | {row['missing_rows']} |"
        )
    lines += ["", "混合快照代码："]
    if data["mixed_snapshot_codes"]:
        lines.extend(f"- {row['code']}：{row['n']} 个快照ID" for row in data["mixed_snapshot_codes"])
    else:
        lines.append("- 无")

    lines += [
        "",
        "## 每只 ETF 覆盖区间",
        "",
        "| 代码 | 名称 | 起始日期 | 结束日期 | 记录数 | 异常记录 | 状态 |",
        "| --- | --- | --- | --- | ---: | ---: | --- |",
    ]
    for row in summary["coverage"]:
        state = "未入库" if not row["has_data"] else ("有异常" if row["anomaly_count"] else "正常")
        lines.append(
            f"| {row['code']} | {row['name']} | {row['start_date'] or '-'} | "
            f"{row['end_date'] or '-'} | {row['record_count']:,} | {row['anomaly_count']} | {state} |"
        )

    lines += ["", "## 行情缺口检查（>20 个日历日）", ""]
    if data["gap_codes"]:
        for row in data["gap_codes"]:
            lines.append(f"- {row['code']}：{row['gap_count']} 处缺口")
    else:
        lines.append("- 未发现超过 20 个日历日的缺口。")

    lines += ["", "## 最近同步失败或空数据", ""]
    if data["failed_or_empty_details"]:
        for row in data["failed_or_empty_details"]:
            lines.append(
                f"- {row['code']}：{row['status']}；{row.get('error_message') or '无错误信息'}"
            )
    else:
        lines.append("- 最近一次同步没有失败或空数据记录。")

    lines += [
        "",
        "## 说明",
        "",
        "- 报告只读数据库，不修改行情。",
        "- 复权收盘价来自 `fund_etf_hist_em(adjust='qfq')`；原始 OHLC 不因复权改写。",
        "- 同一代码不同来源冲突按交易日检测；当前主键保证每个代码每天一行，且本阶段只有一个行情来源。",
        "- 异常行保留在库中并带 quality_status/quality_notes，便于回测时过滤，不做“看起来正常”的修正。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    text, data = build_report()
    settings.report_dir.mkdir(parents=True, exist_ok=True)
    report_path = settings.report_dir / "phase1B_data_quality.md"
    report_path.write_text(text, encoding="utf-8")
    json_path = settings.data_dir / "data_quality_report.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"quality_report={report_path}")
    print(f"summary_records={data['summary']['total_records']} ingested={data['summary']['etf_ingested']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
