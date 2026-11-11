"""回测结果看板页面。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from app.backtest.api import (  # noqa: E402
    get_nav,
    get_orders,
    get_positions,
    get_run,
    get_trades,
    list_runs,
)
from app.database.db import init_db  # noqa: E402

st.set_page_config(page_title="回测结果", layout="wide")
init_db()
st.title("历史回测结果")
st.caption("所有数值来自本地回测引擎写入 SQLite 的结果，不使用模拟行情。")

runs = list_runs(50)
if not runs:
    st.info("尚无回测记录。请先运行：python scripts/run_backtest.py --strategy buy_and_hold --codes 510300 --start 2024-01-02 --end 2026-11-09")
    st.stop()

labels = {
    f"{row['run_id']} | {row['strategy_name']} v{row['strategy_version']} | "
    f"{row['start_date']}~{row['end_date']}": row["run_id"]
    for row in runs
}
selected = st.selectbox("回测记录", list(labels))
run_id = labels[selected]
run = get_run(run_id) or {}
summary = run.get("summary_json") or {}
perf = summary.get("performance", {})
check = summary.get("reconciliation", {})

cols = st.columns(5)
cols[0].metric("策略", f"{run.get('strategy_name')} v{run.get('strategy_version')}")
cols[1].metric("总收益", f"{perf.get('total_return', 0):.2%}" if perf.get("total_return") is not None else "不可计算")
cols[2].metric("CAGR", f"{perf.get('cagr', 0):.2%}" if perf.get("cagr") is not None else "不可计算")
cols[3].metric("最大回撤", f"{perf.get('max_drawdown', 0):.2%}" if perf.get("max_drawdown") is not None else "不可计算")
cols[4].metric("账本核对", "通过" if check.get("ok") else "失败")
st.caption(
    f"区间 {run.get('start_date')} ~ {run.get('end_date')}；"
    f"指标版本 {run.get('indicator_version') or '-'}；输入哈希 {run.get('input_hash')}"
)

tab_nav, tab_perf, tab_trades, tab_orders, tab_positions = st.tabs(
    ["净值曲线", "绩效明细", "成交记录", "订单记录", "每日持仓"]
)

with tab_nav:
    nav = pd.DataFrame(get_nav(run_id))
    if nav.empty:
        st.warning("没有净值数据。")
    else:
        nav["trade_date"] = pd.to_datetime(nav["trade_date"])
        nav = nav.set_index("trade_date")
        st.line_chart(nav[["nav", "total_assets"]])
        st.dataframe(nav.tail(30), width="stretch")
        stale = nav["price_status"].astype(str).str.contains("stale", na=False).sum()
        if stale:
            st.warning(f"{stale} 个交易日使用了上一有效收盘价估值，请查看 price_status。")

with tab_perf:
    st.json(perf)
    yearly = summary.get("yearly", [])
    if yearly:
        st.subheader("年度收益")
        table = pd.DataFrame(yearly)
        table["return"] = table["return"].apply(lambda v: f"{v:.2%}" if v is not None else "-")
        st.dataframe(table, width="stretch", hide_index=True)

with tab_trades:
    trades = pd.DataFrame(get_trades(run_id))
    if trades.empty:
        st.info("没有成交。")
    else:
        st.dataframe(trades, width="stretch", hide_index=True)

with tab_orders:
    orders = pd.DataFrame(get_orders(run_id))
    if orders.empty:
        st.info("没有订单。")
    else:
        status = st.multiselect("订单状态", sorted(orders["status"].unique()))
        view = orders[orders["status"].isin(status)] if status else orders
        st.dataframe(view, width="stretch", hide_index=True)

with tab_positions:
    positions = pd.DataFrame(get_positions(run_id))
    if positions.empty:
        st.info("没有持仓记录。")
    else:
        dates = sorted(positions["trade_date"].unique())
        chosen = st.selectbox("交易日", dates, index=len(dates) - 1)
        st.dataframe(positions[positions["trade_date"] == chosen], width="stretch", hide_index=True)

with st.expander("配置与提示"):
    st.json(run.get("config_json"))
    for note in summary.get("notes", []):
        st.write(f"- {note}")
