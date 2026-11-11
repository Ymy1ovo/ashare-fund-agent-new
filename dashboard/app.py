"""阶段1B数据看板：观察池、入库覆盖、质量与同步结果。"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.database.db import (  # noqa: E402
    get_market_data_summary,
    get_market_price_count,
    get_market_prices,
    get_recent_adjustment_runs,
    get_recent_sync_runs,
    get_sync_details,
    init_db,
)
from app.logging_config import setup_logging  # noqa: E402

st.set_page_config(page_title="A股基金量化数据看板", page_icon="📈", layout="wide")
setup_logging("dashboard.log")
init_db()

st.title("A股基金量化分析 Agent · 阶段1B")
st.caption("数据只用于研究，不构成投资建议；当前未接入交易接口。")

summary = get_market_data_summary()
coverage = pd.DataFrame(summary["coverage"])

col1, col2, col3, col4 = st.columns(4)
col1.metric("观察池 ETF", f"{summary['etf_total']} 只")
col2.metric("已入库 ETF", f"{summary['etf_ingested']} 只")
col3.metric("历史行情记录", f"{summary['total_records']:,} 条")
col4.metric("异常记录", f"{summary['anomaly_record_count']:,} 条")

col5, col6, col7 = st.columns(3)
col5.metric("未入库 ETF", f"{summary['missing_etf_count']} 只")
col6.metric("最近同步状态", summary["last_sync_status"] or "未同步")
col7.metric("最近同步时间", summary["last_sync_at"] or "未同步")
st.caption(f"行情最近采集时间：{summary['last_price_collected_at'] or '无'}")

adjustment = summary.get("adjustment", {})
st.subheader("前复权调整快照")
a1, a2, a3, a4 = st.columns(4)
a1.metric("有当前快照 ETF", f"{adjustment.get('current_snapshot_etfs', 0)} 只")
a2.metric("部分覆盖 ETF", f"{adjustment.get('partial_snapshot_etfs', 0)} 只")
a3.metric("混合快照 ETF", f"{adjustment.get('mixed_snapshot_etfs', 0)} 只")
a4.metric("复权价缺失记录", f"{adjustment.get('adjusted_missing_records', 0):,} 条")
st.caption(
    f"最近复权刷新：{adjustment.get('last_adjustment_refresh_at') or '无'}"
    f"（{adjustment.get('last_adjustment_refresh_status') or '无'}）"
)

if coverage.empty:
    st.warning("数据库中没有观察池数据，请先运行建池和入库脚本。")
    st.stop()

coverage["数据状态"] = coverage.apply(
    lambda row: "未入库"
    if not row["has_data"]
    else ("有异常" if int(row["anomaly_count"]) > 0 else "正常"),
    axis=1,
)
coverage["快照状态"] = coverage["adjustment_status"].fillna("无快照")
coverage_display = coverage.rename(
    columns={
        "code": "代码",
        "name": "名称",
        "category": "分类",
        "start_date": "起始日期",
        "end_date": "结束日期",
        "record_count": "记录数",
        "anomaly_count": "异常记录数",
        "has_data": "已入库",
        "adjustment_snapshot_id": "快照ID",
        "adjustment_collected_at": "快照采集时间",
        "adjustment_coverage_start": "复权起始",
        "adjustment_coverage_end": "复权结束",
        "adjustment_missing_rows": "复权缺失行",
    }
)

st.subheader("每只 ETF 历史行情覆盖区间")
st.dataframe(
    coverage_display[
        [
            "代码",
            "名称",
            "分类",
            "起始日期",
            "结束日期",
            "记录数",
            "异常记录数",
            "数据状态",
            "快照状态",
            "快照ID",
            "复权起始",
            "复权结束",
            "复权缺失行",
            "快照采集时间",
        ]
    ],
    width="stretch",
    hide_index=True,
)

quality_counts = summary.get("quality_counts", {})
st.subheader("数据质量状态")
q1, q2, q3, q4 = st.columns(4)
q1.metric("valid", quality_counts.get("valid", 0))
q2.metric("warning", quality_counts.get("warning", 0))
q3.metric("suspect", quality_counts.get("suspect", 0))
q4.metric("未入库 ETF", summary["missing_etf_count"])

st.subheader("最近同步运行")
runs = pd.DataFrame(get_recent_sync_runs(10))
if runs.empty:
    st.info("尚无同步记录。")
else:
    runs_display = runs.rename(
        columns={
            "id": "运行ID",
            "run_type": "类型",
            "started_at": "开始时间",
            "finished_at": "结束时间",
            "status": "状态",
            "total_codes": "基金数",
            "success_codes": "成功",
            "failed_codes": "失败/空",
            "rows_fetched": "抓取行数",
            "rows_written": "写入行数",
        }
    )
    st.dataframe(
        runs_display[
            ["运行ID", "类型", "状态", "基金数", "成功", "失败/空", "抓取行数", "写入行数", "结束时间"]
        ],
        width="stretch",
        hide_index=True,
    )
    latest_run_id = int(runs.iloc[0]["id"])
    details = pd.DataFrame(get_sync_details(latest_run_id))
    if not details.empty:
        st.caption(f"最近一次运行（ID={latest_run_id}）逐基金结果")
        details_display = details.rename(
            columns={
                "code": "代码",
                "status": "状态",
                "rows_fetched": "抓取行数",
                "rows_written": "写入行数",
                "coverage_start": "起始日期",
                "coverage_end": "结束日期",
                "quality_status": "质量状态",
                "error_message": "错误",
            }
        )
        st.dataframe(
            details_display[
                ["代码", "状态", "质量状态", "抓取行数", "写入行数", "起始日期", "结束日期", "错误"]
            ],
            width="stretch",
            hide_index=True,
        )

st.subheader("最近前复权刷新运行")
adjustment_runs = pd.DataFrame(get_recent_adjustment_runs(10))
if adjustment_runs.empty:
    st.info("尚无前复权刷新记录。")
else:
    adjustment_runs_display = adjustment_runs.rename(
        columns={
            "id": "运行ID",
            "started_at": "开始时间",
            "finished_at": "结束时间",
            "status": "状态",
            "total_codes": "基金数",
            "success_codes": "成功",
            "partial_codes": "部分覆盖",
            "failed_codes": "失败",
            "empty_codes": "空数据",
            "rows_updated": "更新行数",
        }
    )
    st.dataframe(
        adjustment_runs_display[
            [
                "运行ID",
                "状态",
                "基金数",
                "成功",
                "部分覆盖",
                "失败",
                "空数据",
                "更新行数",
                "结束时间",
            ]
        ],
        width="stretch",
        hide_index=True,
    )

st.subheader("按 ETF 查看最近行情")
selected = st.selectbox(
    "选择代码",
    options=coverage["code"].tolist(),
    format_func=lambda code: f"{code} {coverage.loc[coverage['code'] == code, 'name'].iloc[0]}",
)
price_total = get_market_price_count(selected)
prices = pd.DataFrame(
    get_market_prices(selected, limit=30, offset=max(0, price_total - 30))
)
if prices.empty:
    st.info("该 ETF 尚未入库历史行情。")
else:
    st.dataframe(
        prices.rename(
            columns={
                "trade_date": "交易日期",
                "open": "开盘",
                "high": "最高",
                "low": "最低",
                "close": "收盘",
                "adjusted_close": "前复权收盘",
                "adjustment_type": "复权类型",
                "volume": "成交量",
                "amount": "成交额",
                "quality_status": "质量状态",
                "quality_notes": "质量备注",
            }
        ),
        width="stretch",
        hide_index=True,
    )
    st.caption(f"显示最近 30 条（共 {price_total:,} 条）；完整数据请使用 API 分页接口。")
