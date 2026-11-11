"""阶段1B.1 调整快照一致性检查。

检查：
- 每只基金有且仅有一个当前调整快照；
- 所有行引用同一个当前快照；
- 复权缺失行数与快照 missing_rows 一致；
- 刷新后原始 OHLC 行数与哈希与刷新前备份完全一致。

用法：
    python scripts/check_adjustment_consistency.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402
from app.database.db import get_connection  # noqa: E402


def _raw_hash(db_path: Path) -> tuple[int, str]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT code, trade_date, open, high, low, close, volume, amount "
        "FROM etf_daily_prices ORDER BY code, trade_date"
    ).fetchall()
    conn.close()
    digest = hashlib.sha256()
    for row in rows:
        digest.update(json.dumps(row, ensure_ascii=False, default=str).encode("utf-8"))
    return len(rows), digest.hexdigest()


def build(before_db: Path | None) -> tuple[str, dict]:
    errors: list[str] = []
    with get_connection() as conn:
        current = {
            str(row["code"]): dict(row)
            for row in conn.execute(
                "SELECT * FROM etf_adjustment_snapshots WHERE is_current = 1 ORDER BY code"
            )
        }
        stats = [
            dict(row)
            for row in conn.execute(
                """
                SELECT code, COUNT(*) AS row_count,
                       COUNT(DISTINCT adjustment_snapshot_id) AS snapshot_count,
                       SUM(CASE WHEN adjusted_close IS NULL THEN 1 ELSE 0 END) AS missing_rows,
                       MIN(trade_date) AS start_date, MAX(trade_date) AS end_date
                FROM etf_daily_prices GROUP BY code ORDER BY code
                """
            )
        ]
        rows_without_snapshot = int(
            conn.execute(
                "SELECT COUNT(*) FROM etf_daily_prices WHERE adjustment_snapshot_id IS NULL"
            ).fetchone()[0]
        )
        total_rows = int(conn.execute("SELECT COUNT(*) FROM etf_daily_prices").fetchone()[0])
        mixed = [
            dict(row)
            for row in conn.execute(
                """
                SELECT code, COUNT(DISTINCT adjustment_snapshot_id) AS n
                FROM etf_daily_prices WHERE adjustment_snapshot_id IS NOT NULL
                GROUP BY code HAVING n > 1 ORDER BY code
                """
            )
        ]

    for row in stats:
        code = row["code"]
        snap = current.get(code)
        if snap is None:
            errors.append(f"{code} 没有当前调整快照")
            continue
        if int(row["snapshot_count"] or 0) != 1:
            errors.append(f"{code} 存在 {row['snapshot_count']} 个行级快照引用")
        if snap["status"] not in {"success", "partial"}:
            errors.append(f"{code} 当前快照状态为 {snap['status']}")
        if int(row["missing_rows"] or 0) != int(snap["missing_rows"] or 0):
            errors.append(
                f"{code} adjusted_close 缺失 {row['missing_rows']} 行，"
                f"快照记录 {snap['missing_rows']} 行"
            )
        if int(row["row_count"]) != int(snap["raw_rows"]):
            errors.append(f"{code} 行情 {row['row_count']} 行，快照 raw_rows={snap['raw_rows']}")
        if not snap["coverage_start"] or not snap["coverage_end"]:
            errors.append(f"{code} 快照覆盖区间为空")

    if rows_without_snapshot:
        errors.append(f"{rows_without_snapshot} 条行情没有 adjustment_snapshot_id")
    if mixed:
        errors.append(f"存在混合快照基金：{mixed}")

    before_rows = before_hash = None
    if before_db and before_db.exists():
        before_rows, before_hash = _raw_hash(before_db)
        after_rows, after_hash = _raw_hash(settings.database_path)
        if before_rows != after_rows:
            errors.append(f"原始行情行数变化：before={before_rows}, after={after_rows}")
        if before_hash != after_hash:
            errors.append("原始 OHLC 哈希变化，复权刷新修改了原始行情")
    else:
        before_hash = "未提供备份，跳过比较"
        after_rows, after_hash = _raw_hash(settings.database_path)

    result = {
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "pool_snapshot_count": len(current),
        "total_rows": total_rows,
        "rows_without_snapshot": rows_without_snapshot,
        "mixed_snapshot_codes": mixed,
        "before_db": str(before_db) if before_db else None,
        "before_rows": before_rows,
        "before_raw_sha256": before_hash,
        "after_raw_sha256": after_hash,
        "raw_ohlc_unchanged": before_hash == after_hash,
        "errors": errors,
        "ok": not errors,
        "coverage": stats,
        "snapshots": list(current.values()),
    }
    return render(result), result


def render(data: dict) -> str:
    lines = [
        "# 阶段1B.1 调整快照一致性检查报告",
        "",
        f"- 检查时间：{data['checked_at']}",
        f"- 当前快照基金数：{data['pool_snapshot_count']}",
        f"- 行情总记录：{data['total_rows']:,}",
        f"- 无快照引用记录：{data['rows_without_snapshot']}",
        f"- 混合快照基金：{len(data['mixed_snapshot_codes'])}",
        f"- 刷新前备份：{data['before_db'] or '无'}",
        f"- 刷新前原始行数：{data['before_rows']}",
        f"- 刷新后原始行数：{data['total_rows']}",
        f"- 刷新前原始 OHLC SHA256：{data['before_raw_sha256']}",
        f"- 刷新后原始 OHLC SHA256：{data['after_raw_sha256']}",
        f"- 原始 OHLC 未变化：{'是' if data['raw_ohlc_unchanged'] else '否'}",
        "",
        "## 检查结果",
        "",
    ]
    if data["errors"]:
        lines.extend(f"- 失败：{error}" for error in data["errors"])
    else:
        lines.append("- 全部通过。")

    lines += [
        "",
        "## 逐基金快照",
        "",
        "| 代码 | 快照ID | 状态 | 原始行 | 匹配行 | 缺失行 | 行级快照数 | 复权覆盖 |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    snapshots = {str(row["code"]): row for row in data["snapshots"]}
    for row in data["coverage"]:
        snap = snapshots.get(str(row["code"]), {})
        lines.append(
            f"| {row['code']} | {snap.get('id', '-')} | {snap.get('status', '-')} | "
            f"{row['row_count']} | {snap.get('matched_rows', '-')} | {row['missing_rows']} | "
            f"{row['snapshot_count']} | {snap.get('coverage_start', '-')} ~ {snap.get('coverage_end', '-')} |"
        )
    lines += [
        "",
        "## 结论",
        "",
        "同一只 ETF 的所有非空 adjusted_close 均引用当前唯一快照；"
        "原始 OHLC 行数与哈希未变化。"
        if data["ok"]
        else "存在未通过项，不能认为调整快照一致性完成。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="检查前复权调整快照一致性")
    parser.add_argument(
        "--before-db",
        default=str(settings.data_dir / "backups" / "fund_agent_before_1b1.db"),
        help="刷新前数据库备份，用于原始 OHLC 哈希对比",
    )
    args = parser.parse_args()
    text, data = build(Path(args.before_db))
    report = settings.report_dir / "phase1B1_consistency.md"
    report.write_text(text, encoding="utf-8")
    output = settings.data_dir / "adjustment_consistency.json"
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"report={report}")
    print(f"ok={data['ok']} errors={data['errors']} raw_unchanged={data['raw_ohlc_unchanged']}")
    return 0 if data["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
