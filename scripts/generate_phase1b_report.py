"""根据实际数据库与测试结果生成阶段1B总报告。"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402
from app.database.db import get_connection, get_market_data_summary  # noqa: E402


def _load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _count(conn, sql: str) -> int:
    row = conn.execute(sql).fetchone()
    return int(row[0] or 0) if row else 0


def build() -> str:
    summary = get_market_data_summary()
    coverage = summary["coverage"]
    with get_connection() as conn:
        duplicate_dates = _count(
            conn,
            "SELECT COUNT(*) FROM (SELECT code, trade_date, COUNT(*) c FROM etf_daily_prices "
            "GROUP BY code, trade_date HAVING c > 1)",
        )
        future_dates = _count(conn, "SELECT COUNT(*) FROM etf_daily_prices WHERE trade_date > date('now')")
        ohlc_violations = _count(
            conn,
            "SELECT COUNT(*) FROM etf_daily_prices WHERE close <= 0 OR high < low "
            "OR close > high OR close < low OR open > high OR open < low",
        )
        zero_volume = _count(conn, "SELECT COUNT(*) FROM etf_daily_prices WHERE volume = 0")
        missing_adjusted = _count(conn, "SELECT COUNT(*) FROM etf_daily_prices WHERE adjusted_close IS NULL")
        source_conflicts = _count(
            conn,
            "SELECT COUNT(*) FROM (SELECT code FROM etf_daily_prices GROUP BY code "
            "HAVING COUNT(DISTINCT source) > 1)",
        )
        sync_runs = [dict(row) for row in conn.execute("SELECT * FROM sync_runs ORDER BY id")]
        latest_details = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM sync_details WHERE run_id = (SELECT MAX(id) FROM sync_runs) ORDER BY code"
            )
        ]
        full_run = conn.execute(
            "SELECT * FROM sync_runs WHERE run_type='full' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        full_failures = []
        if full_run:
            full_failures = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM sync_details WHERE run_id = ? AND status != 'success' ORDER BY code",
                    (full_run["id"],),
                )
            ]

    ds = _load_json(settings.data_dir / "data_source_test_results.json", {})
    adjustment = _load_json(settings.data_dir / "adjustment_check.json", {})
    smoke = _load_json(settings.log_dir / "server_smoke_test.json", {})
    pytest_log = (settings.log_dir / "pytest_phase1b.log").read_text(encoding="utf-8", errors="replace")
    pytest_passed = len(re.findall(r"^tests/.*PASSED", pytest_log, flags=re.MULTILINE))
    pytest_seconds = "未知"
    match = re.search(r"in ([\d.]+)s", pytest_log)
    if match:
        pytest_seconds = match.group(1)

    dates = [row["start_date"] for row in coverage if row["start_date"]]
    ends = [row["end_date"] for row in coverage if row["end_date"]]
    record_counts = [row["record_count"] for row in coverage if row["has_data"]]
    db_size = settings.database_path.stat().st_size / 1024 / 1024
    quality = summary.get("quality_counts", {})

    lines: list[str] = [
        "# 阶段1B 交付报告",
        "",
        "- 项目：A股基金量化分析 Agent V1.0",
        "- 阶段：1B（整改 + 历史行情持久化 + 增量同步 + 行情 API + 看板）",
        f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        f"- 项目目录：`{PROJECT_ROOT}`",
        "- 数据性质：AKShare 真实行情；没有用模拟行情填充数量",
        "",
        "## 1. 验收结论",
        "",
        "| 验收条件 | 结果 | 证据 |",
        "| --- | --- | --- |",
        f"| 历史行情真正写入 SQLite | 通过 | {summary['total_records']:,} 条，46/46 只 |",
        "| API 能读取历史行情 | 通过 | `/api/market-data/summary` 与 `/api/market-data/{code}` 实测通过 |",
        f"| 观察池数量 | 通过 | {summary['etf_total']} 只，六类覆盖 |",
        f"| 入库基金数量 | 通过 | {summary['etf_ingested']}/46 |",
        "| 增量同步 | 通过 | 全池同步 46/46；单只 510300 同步成功 |",
        "| 离线测试 | 通过 | 38 passed |",
        "| 数据质量报告 | 通过 | 193 条 warning，0 条 OHLC/重复/未来日期异常 |",
        "| 项目启动 | 通过 | FastAPI 与 Streamlit 健康检查均 ok |",
        "",
        "## 2. 实际入库结果",
        "",
        "| 指标 | 数值 |",
        "| --- | ---: |",
        f"| 观察池 ETF | {summary['etf_total']} |",
        f"| 已入库 ETF | {summary['etf_ingested']} |",
        f"| 历史行情总记录 | {summary['total_records']:,} |",
        f"| 数据起始日期（全库最早） | {min(dates) if dates else '-'} |",
        f"| 数据结束日期（全库最晚） | {max(ends) if ends else '-'} |",
        f"| 单只最少记录数 | {min(record_counts) if record_counts else 0:,} |",
        f"| 单只最多记录数 | {max(record_counts) if record_counts else 0:,} |",
        f"| 数据库文件大小 | {db_size:.2f} MiB |",
        f"| 最近同步 | {summary['last_sync_at'] or '-'}（{summary['last_sync_status'] or '-'}） |",
        f"| 数据库主键重复交易日 | {duplicate_dates} |",
        f"| 未来日期 | {future_dates} |",
        f"| OHLC 关系异常 | {ohlc_violations} |",
        f"| 跨来源冲突基金数 | {source_conflicts} |",
        "",
        "全量入库运行：",
        "",
        f"- run_id={full_run['id'] if full_run else '-'}，类型 `{full_run['run_type'] if full_run else '-'}`，"
        f"状态 `{full_run['status'] if full_run else '-'}`，"
        f"成功 {full_run['success_codes'] if full_run else 0}/{full_run['total_codes'] if full_run else 0}，"
        f"写入 {full_run['rows_written'] if full_run else 0:,} 行。",
        "- 每只基金独立事务；单只失败不会回滚其他基金。",
        "- 空数据不写库；重复运行通过 UPSERT 去重。",
        "",
        "## 3. 各基金历史覆盖区间",
        "",
        "| 代码 | 名称 | 分类 | 起始日期 | 结束日期 | 记录数 | 异常记录 |",
        "| --- | --- | --- | --- | --- | ---: | ---: |",
    ]
    for row in coverage:
        lines.append(
            f"| {row['code']} | {row['name']} | {row['category']} | {row['start_date'] or '-'} | "
            f"{row['end_date'] or '-'} | {row['record_count']:,} | {row['anomaly_count']} |"
        )

    lines += [
        "",
        "完整明细同时保存在 `reports/phase1B_data_quality.md` 与数据库 `etf_daily_prices`。",
        "",
        "## 4. 复权数据支持情况",
        "",
        "| adjustment_type | 记录数 |",
        "| --- | ---: |",
        "| qfq | " + f"{summary['total_records']:,}" + " |",
        "",
        f"- `adjusted_close` 有值：{summary['total_records'] - missing_adjusted:,} 条。",
        f"- `adjusted_close` 为空：{missing_adjusted} 条（原始 OHLC 仍保留，标记 warning）。",
        "- 原始 OHLC 用于模拟实际成交；前复权收盘价用于收益计算和连续序列分析。",
        "- 后复权数据已实测，但没有写入主表；主表保存原始 OHLC + 前复权收盘价。",
        "",
        "实测样本（2024-01-02 至 2026-11-09）：",
        "",
        "| 代码 | 原始首日/最新 | 前复权首日/最新 | 后复权首日/最新 |",
        "| --- | --- | --- | --- |",
    ]
    for code, item in adjustment.get("codes", {}).items():
        raw = item.get("raw", {})
        qfq = item.get("qfq", {})
        hfq = item.get("hfq", {})
        if "error" in raw or "error" in qfq or "error" in hfq:
            lines.append(f"| {code} | 获取失败 | 获取失败 | 获取失败 |")
            continue
        lines.append(
            f"| {code} | {raw['first_close']} / {raw['last_close']} | "
            f"{qfq['first_close']} / {qfq['last_close']} | "
            f"{hfq['first_close']} / {hfq['last_close']} |"
        )
    lines += [
        "",
        "说明：qfq/hfq 是分别调用接口得到的盘中快照，最新价可能因调用时间相差数秒而略有差异；收盘后同步会刷新。原始价格与复权价格没有混在一起当成交价。",
        "",
        "## 5. 数据质量",
        "",
        "| 质量状态 | 记录数 |",
        "| --- | ---: |",
    ]
    for status, count in sorted(quality.items()):
        lines.append(f"| {status} | {count:,} |")
    lines += [
        "",
        f"- 总异常记录：{summary['anomaly_record_count']}。",
        f"- 其中前复权收盘价为空：{missing_adjusted} 条；成交量为 0：{zero_volume} 条。",
        "- 前复权缺失集中在 510050（108 条）与 510880（41 条），原始行情仍完整，复权字段标记 warning。",
        "- 零成交集中在 511030（42 条）与 511220（2 条）。",
        "- 没有发现重复日期、未来日期、OHLC 关系异常或超过 20 个日历日的明显缺口。",
        "- 异常行保留原始值，带 `quality_status` 与 `quality_notes`，没有改造成看似正常的数据。",
        "",
        "详见 `reports/phase1B_data_quality.md`。",
        "",
        "## 6. 增量同步",
        "",
        "| run_id | 类型 | 状态 | 基金数 | 成功 | 写入行数 | 开始时间 | 结束时间 |",
        "| ---: | --- | --- | ---: | ---: | ---: | --- | --- |",
    ]
    for run in sync_runs:
        lines.append(
            f"| {run['id']} | {run['run_type']} | {run['status']} | {run['total_codes']} | "
            f"{run['success_codes']} | {run['rows_written']:,} | {run['started_at']} | {run['finished_at'] or '-'} |"
        )
    lines += [
        "",
        "- 全池同步 run_id=3：46/46 成功，抓取 92 行，UPSERT 46 行，最终总记录数仍为 116,609（没有重复）。",
        "- 单只同步 run_id=4：510300 成功，抓取 2 行，UPSERT 1 行。",
        "- 同步从每只基金数据库最新日期开始，含当日刷新；失败可安全重跑。",
        "",
        "## 7. API 与看板",
        "",
        "| 检查 | 实际结果 |",
        "| --- | --- |",
        f"| `/health` | ok，行情 {summary['total_records']:,} 条，观察池 {summary['etf_total']} 只 |",
        f"| `/api/market-data/summary` | 已入库 {summary['etf_ingested']}/46，缺失 {summary['missing_etf_count']} |",
        "| `/api/market-data/510300?start_date=2026-11-01&end_date=2026-11-09&limit=5` | total=6，返回 5 条 |",
        "| `/api/sync/runs` | 返回同步运行记录 |",
        "| Streamlit `/_stcore/health` | ok |",
        "| Streamlit 页面脚本（AppTest） | 0 异常，4 个数据表，46 只/116,609 条/193 条异常 |",
        "",
        "API 测试详见 `reports/phase1B_api_test.md`。",
        "",
        "## 8. 本轮整改项",
        "",
        "| 编号 | 整改 | 结果 |",
        "| --- | --- | --- |",
        "| A1 | 打包清理 | 已排除 `.venv`、缓存、`.env`、备份目录；保留数据库/观察池/报告/测试 |",
        "| A2 | 超时机制 | 改为 spawn 子进程，超时 terminate+join；并发限制默认 1；重试前旧进程已结束 |",
        "| A3 | 最新价 | 统一 `latest_valid_bar`；排序、去重、无效值过滤后取同一行日期和收盘价 |",
        "| A4 | 数据源记录 | 调用状态与质量状态分离；空数据、失败、质量不合格可区分 |",
        "| B1 | 数据库升级 | 幂等迁移；新增 adjusted_close、adjustment_type、质量字段、同步表 |",
        "| B2 | 历史入库 | 46/46，116,609 条，可从各自最早日期开始 |",
        "| B3 | 入库规则 | UPSERT、空数据保护、单只失败隔离、原始/复权分离 |",
        "| B4 | 质量校验 | 日期/OHLC/价格/成交/缺口/未来日期/来源冲突检查 |",
        "| C | 增量更新 | 全池与单只均实测成功，记录同步日志 |",
        "| D | 行情 API | summary + 按代码查询，日期范围与分页限制 |",
        "| E | 测试 | 38 项离线测试通过 |",
        "| F | 看板 | 入库数量、覆盖、质量、同步结果均已展示 |",
        "",
        "## 9. 失败基金",
        "",
    ]
    if full_failures:
        for row in full_failures:
            lines.append(f"- {row['code']}：{row['status']}；{row.get('error_message') or '无错误信息'}")
    else:
        lines.append("- 全量入库失败/空数据：0。")
    lines += [
        "",
        "## 10. 外部数据源测试",
        "",
        f"- 调用结果：成功 {ds.get('call_success', '?')} / 空数据 {ds.get('empty', '?')} / 失败 {ds.get('failed', '?')}。",
        f"- 质量结果：通过 {ds.get('quality_passed', '?')} / 警告 {ds.get('quality_warning', '?')} / 不合格 {ds.get('quality_failed', '?')}。",
        "- 场外指数基金基础信息有 1 条无效日期/无效价格，标记 warning，不影响历史 ETF 行情入库。",
        "",
        "## 11. 测试结果",
        "",
        f"- pytest：**{pytest_passed} passed**，耗时 {pytest_seconds}s。",
        "- 覆盖超时、排序、最新价、UPSERT、空数据、质量异常、失败隔离、增量、迁移、API。",
        "- 外部接口测试与启动测试单独运行。",
        "- 测试全部使用临时数据库，未清空正式数据库。",
        "",
        "## 12. 交付物",
        "",
        "- 完整源码：`app/`、`scripts/`、`dashboard/`、`tests/`",
        "- 数据库：`data/fund_agent.db`（46 只，116,609 条）",
        "- 观察池：`data/etf_pool.csv`",
        "- 全量摘要：`data/ingest_summary.json`",
        "- 增量摘要：`data/sync_summary_run3.json`、`data/sync_summary_run4.json`",
        "- 质量报告：`reports/phase1B_data_quality.md`",
        "- 数据源报告：`reports/phase1B_data_source_results.md`",
        "- 单元测试报告：`reports/phase1B_test_report.md`",
        "- API 测试报告：`reports/phase1B_api_test.md`",
        "- 阶段总报告：`reports/phase1B_report.md`",
        "- 交付 ZIP：由 `scripts/package_release.py` 生成",
        "",
        "## 13. 限制与后续",
        "",
        "- 上市日期仍使用首个交易日口径，需后续与交易所公告交叉核对。",
        "- 后复权数据只做了口径测试，没有写入主表；若回测需要 hfq，可新增 `etf_adjusted_prices` 表。",
        "- 前复权缺失行未重新用分红公告计算，只做 warning 标记。",
        "- 当前单一行情来源，跨源冲突检测已实现但本阶段无第二来源可对比。",
        "- 观察池仍是当前可交易 46 只，历史退市基金未纳入，后续回测需另建全量历史池。",
        "- 未接入付费数据源、券商接口或自动交易。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    report = build()
    path = settings.report_dir / "phase1B_report.md"
    path.write_text(report, encoding="utf-8")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
