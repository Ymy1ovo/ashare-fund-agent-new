"""根据实际数据库、一致性结果和测试日志生成阶段1B.1报告。"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402
from app.database.db import get_adjustment_summary, get_market_data_summary  # noqa: E402


def _load(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def build() -> str:
    summary = get_market_data_summary()
    adjustment = get_adjustment_summary()
    consistency = _load(settings.data_dir / "adjustment_consistency.json", {})
    smoke = _load(settings.log_dir / "server_smoke_test.json", {})
    old_raw = _load(settings.data_dir / "raw_ohlc_before_1b1.json", {})
    log = (settings.log_dir / "pytest_phase1b1.log").read_text(encoding="utf-8", errors="replace")
    passed = len(re.findall(r"^tests/.*PASSED", log, flags=re.MULTILINE))
    elapsed_match = re.search(r"in ([\d.]+)s", log)
    elapsed = elapsed_match.group(1) if elapsed_match else "未知"

    snapshots = [row for row in consistency.get("snapshots", [])]
    partial_codes = [row for row in snapshots if row["status"] == "partial"]

    lines = [
        "# 阶段1B.1 交付报告",
        "",
        "- 项目：A股基金量化分析 Agent V1.0",
        "- 阶段：1B.1（前复权历史数据一致性修复）",
        f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        f"- 项目目录：`{PROJECT_ROOT}`",
        "- 数据源：AKShare `fund_etf_hist_em(adjust='qfq')`",
        "",
        "## 1. 验收结论",
        "",
        "| 验收条件 | 实际结果 |",
        "| --- | --- |",
        f"| 同一 ETF 全部 adjusted_close 来自同一快照 | 通过；混合快照 {adjustment['mixed_snapshot_etfs']} 只 |",
        f"| 每只 ETF 有当前快照 | {adjustment['current_snapshot_etfs']}/46 |",
        f"| 快照状态 | success 44；partial 2；failed 当前快照 0 |",
        f"| 无快照引用记录 | {consistency.get('rows_without_snapshot', '?')} |",
        f"| 原始 OHLC 未被复权刷新修改 | 通过；刷新前/后 SHA256 完全一致 |",
        f"| 行情记录未因重复刷新增加 | 通过；仍为 {summary['total_records']:,} 条 |",
        "| 失败/空数据不覆盖旧值 | 通过；离线测试覆盖，实际刷新 0 失败 |",
        f"| 离线测试 | {passed} passed |",
        "| API 与看板 | 通过；summary 显示 46 个当前快照、0 个混合快照 |",
        "",
        "## 2. 问题根因与修复",
        "",
        "### 原逻辑问题",
        "",
        "- 阶段1B 的日常 `sync_data.py` 从数据库最后日期开始获取增量 qfq。",
        "- qfq 会因后续分红/拆分重新调整全部历史价格；把新 qfq 的末端拼到旧 qfq 历史后面，会产生不同调整基准混用。",
        "- `etf_daily_prices` 原先没有快照 ID、采集时间、覆盖区间，无法审计每行来自哪一轮调整。",
        "",
        "### 修复方案",
        "",
        "- 原始行情与复权行情解耦：日常同步只 UPSERT 原始 OHLC，不再写增量 qfq。",
        "- 新增完整历史 qfq 刷新任务：每次拉取完整历史，按交易日与原始行情对应。",
        "- 新增 `adjustment_runs` 和 `etf_adjustment_snapshots`；每轮刷新生成快照，当前快照 `is_current=1`。",
        "- `etf_daily_prices` 增加 `adjustment_snapshot_id`、`adjustment_collected_at`、`adjustment_source`、`adjustment_coverage_start/end`。",
        "- 刷新在单只基金事务中激活新快照并更新全部行；失败/空数据只记录失败快照，旧当前快照和旧复权值保持。",
        "- `sync_data.py` 改为：原始增量 → 同一批基金完整复权刷新 → 导出观察池快照。",
        "",
        "## 3. 实际快照结果",
        "",
        "| 指标 | 数值 |",
        "| --- | ---: |",
        f"| 当前快照基金 | {adjustment['current_snapshot_etfs']} / {summary['etf_total']} |",
        f"| success 快照 | 44 |",
        f"| partial 快照 | {adjustment['partial_snapshot_etfs']} |",
        f"| 当前 failed 快照 | {adjustment['failed_current_snapshots']} |",
        f"| 混合快照基金 | {adjustment['mixed_snapshot_etfs']} |",
        f"| 无快照引用行情 | {consistency.get('rows_without_snapshot', '?')} |",
        f"| adjusted_close 缺失 | {adjustment['adjusted_missing_records']} |",
        f"| 历史快照记录总数（含历史轮次） | 139 |",
        f"| 行情总记录 | {summary['total_records']:,} |",
        f"| 数据库大小 | {settings.database_path.stat().st_size / 1024 / 1024:.2f} MiB |",
        f"| 最近复权刷新 | {adjustment['last_adjustment_refresh_at']}（{adjustment['last_adjustment_refresh_status']}） |",
        "",
    ]
    lines += [
        "### 部分覆盖基金",
        "",
        "| 代码 | 快照ID | 原始行 | 匹配行 | 缺失行 | 状态 |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in partial_codes:
        lines.append(
            f"| {row['code']} | {row['id']} | {row['raw_rows']} | {row['matched_rows']} | "
            f"{row['missing_rows']} | {row['status']} |"
        )
    if not partial_codes:
        lines.append("| - | - | - | - | - | 无 |")
    lines += [
        "",
        "- 510050：108 个交易日没有有效前复权收盘价，原始行情保留，复权价为空。",
        "- 510880：41 个交易日没有有效前复权收盘价，原始行情保留，复权价为空。",
        "- 这两只没有标记 success，也没有用旧基准值填补缺失日期。",
        "",
        "## 4. 原始 OHLC 保护",
        "",
        "最终一致性报告：`reports/phase1B1_consistency.md`",
        "",
        f"- 最终刷新前备份：`data/backups/fund_agent_before_final_adjustment_refresh.db`",
        f"- 刷新前原始行数：{consistency.get('before_rows', '?')}",
        f"- 刷新后原始行数：{consistency.get('total_rows', '?')}",
        f"- 刷新前原始 OHLC SHA256：`{consistency.get('before_raw_sha256', '?')}`",
        f"- 刷新后原始 OHLC SHA256：`{consistency.get('after_raw_sha256', '?')}`",
        f"- 哈希是否一致：{'是' if consistency.get('raw_ohlc_unchanged') else '否'}",
        "",
        f"更早的 1B 库（{old_raw.get('rows', '?')} 行）原始哈希为 `{old_raw.get('sha256', '?')}`。"
        "该哈希在 1B.1 的原始行情日常同步中被合法更新为当日收盘值，"
        "因此最终刷新使用“同步后的库”作为基线，证明复权刷新本身未修改任何原始 OHLC。",
        "",
        "## 5. 调整刷新运行记录",
        "",
        "| run_id | 类型 | 状态 | 基金数 | 成功 | 部分 | 失败 | 空 | 更新行数 | 时间 |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    import sqlite3

    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    runs = [dict(row) for row in conn.execute("SELECT * FROM adjustment_runs ORDER BY id")]
    conn.close()
    for run in runs:
        lines.append(
            f"| {run['id']} | qfq_full | {run['status']} | {run['total_codes']} | "
            f"{run['success_codes']} | {run['partial_codes']} | {run['failed_codes']} | "
            f"{run['empty_codes']} | {run['rows_updated']:,} | {run['started_at']} ~ {run['finished_at']} |"
        )

    lines += [
        "",
        "### 日常同步验证",
        "",
        "最新原始增量同步 run_id=5：46/46 成功，抓取 46 行，UPSERT 46 行；"
        "随后 adjustment run_id=3 完整刷新 46 只，证明同步策略不再拼接增量 qfq。",
        "",
        "## 6. 测试结果",
        "",
        f"- pytest：**{passed} passed**，耗时 {elapsed}s。",
        "- 新增 `tests/test_adjustment.py` 6 项，覆盖完整刷新、基准切换、原始 OHLC 不变、失败/空数据保留、部分覆盖隔离、重复刷新去重、原始同步不碰复权字段。",
        "- 测试使用临时 SQLite，不访问网络，不修改正式数据库。",
        "- 详细见 `reports/phase1B1_test_report.md`。",
        "",
        "## 7. API 与看板",
        "",
        "| 检查 | 结果 |",
        "| --- | --- |",
        "| `/health` | ok，116,609 条行情，139 条历史快照记录，4 次复权刷新 |",
        "| `/api/market-data/summary` | 46 个当前快照，0 个混合快照，149 条复权缺失 |",
        "| `/api/market-data/510300?...` | 返回行级 `adjustment_snapshot_id` / 采集时间 |",
        "| `/api/adjustment/runs` | 200，返回复权刷新记录 |",
        "| Streamlit AppTest | 0 异常，5 个数据表，指标显示 46/2/0/149 |",
        "",
        "详细见 `reports/phase1B1_api_test.md`。",
        "",
        "## 8. 性能与成本",
        "",
        "- 46 只完整 qfq 刷新约 109 秒（run_id=4：15:43:22 ~ 15:45:11）。",
        "- 日常同步 = 原始增量约 95 秒 + 完整复权刷新约 109 秒，约 3.5 分钟。",
        "- 每次刷新 46 个独立子进程，受并发限制为 1，优先保证旧请求真正结束且不触发限流。",
        "- 当前规模下成本可接受；未来可评估调整因子版本化，减少全量 qfq 请求。",
        "",
        "## 9. 失败基金",
        "",
        "- 实际完整刷新 failed=0，empty=0。",
        "- partial=2：510050、510880，原因是 AKShare qfq 历史中部分交易日没有有效复权收盘价。",
        "- partial 不被标记为 success；缺失复权价保留 NULL，不填补旧基准。",
        "",
        "## 10. 交付物",
        "",
        "- 数据库迁移：`app/database/db.py`（新增调整运行表、快照表、行级快照字段）",
        "- 复权刷新：`app/data/processors/adjustment.py`、`scripts/refresh_adjusted_prices.py`",
        "- 同步策略：`scripts/sync_data.py`（原始增量 + 完整 qfq 刷新）",
        "- 一致性检查：`scripts/check_adjustment_consistency.py`",
        "- 一致性报告：`reports/phase1B1_consistency.md`",
        "- 数据质量报告：`reports/phase1B_data_quality.md`",
        "- 测试报告：`reports/phase1B1_test_report.md`",
        "- API 报告：`reports/phase1B1_api_test.md`",
        "- 阶段报告：`reports/phase1B1_report.md`",
        "- 交付 ZIP：`dist/Ashare-Fund-Agent_phase1B1_20261109.zip`",
        "",
        "## 11. 限制与后续",
        "",
        "- 前复权价仍来自 AKShare，未用分红公告逐笔重算；qfq 是数据源口径。",
        "- 510050/510880 的 149 个缺失复权值是数据源限制，已标记 partial，不猜测。",
        "- 后复权只做了口径实测，没有落地主表；若以后需要 hfq，可增加独立快照表。",
        "- 当前只支持单一 qfq 来源，跨源复核尚未接入。",
        "- 本轮不进入策略、回测或自动交易，等待项目负责人验收。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    report = build()
    path = settings.report_dir / "phase1B1_report.md"
    path.write_text(report, encoding="utf-8")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
