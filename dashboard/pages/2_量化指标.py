"""量化指标看板页面。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from app.database.db import get_current_adjustment_snapshot, get_etf_name, get_pool_codes, init_db  # noqa: E402
from app.database.indicators import (  # noqa: E402
    get_indicator_rows,
    get_indicator_run,
    get_versions,
)
from app.quant.risk import summarize_range  # noqa: E402

st.set_page_config(page_title="量化指标", layout="wide")
init_db()
st.title("量化指标分析")
st.caption("所有数值来自 SQLite 中已计算的指标；缺失值保留为空，不做填充。")

codes = get_pool_codes()
if not codes:
    st.warning("观察池为空，请先构建 ETF 观察池。")
    st.stop()
labels = {f"{code} {get_etf_name(code) or ''}": code for code in codes}
default_code = "510300" if "510300" in codes else codes[0]
default_index = list(codes).index(default_code)
selected_label = st.selectbox("ETF", list(labels), index=default_index)
code = labels[selected_label]

versions = get_versions(code)
if not versions:
    st.info("该 ETF 尚未计算指标。请先运行：python scripts/calculate_indicators.py --code " + code)
    st.stop()
version = st.selectbox("指标版本", versions, index=len(versions) - 1)
all_rows = get_indicator_rows(code, version=version)
if not all_rows:
    st.warning("该版本没有指标数据。")
    st.stop()

frame = pd.DataFrame(all_rows)
frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
frame = frame.sort_values("trade_date")
min_date = frame["trade_date"].min().date()
max_date = frame["trade_date"].max().date()
selection = st.date_input(
    "日期区间", value=(min_date, max_date), min_value=min_date, max_value=max_date
)
if isinstance(selection, (tuple, list)):
    start_date, end_date = selection[0], selection[-1]
else:
    start_date = end_date = selection
mask = (frame["trade_date"].dt.date >= start_date) & (frame["trade_date"].dt.date <= end_date)
view = frame.loc[mask].copy()
if view.empty:
    st.warning("所选日期区间没有指标数据。")
    st.stop()

latest = view.iloc[-1]
run = get_indicator_run(str(latest["run_id"]))
full_summary = json.loads(run["summary_json"]) if run and run.get("summary_json") else {}
quality = json.loads(run["quality_json"]) if run and run.get("quality_json") else {}
summary = summarize_range(
    view.set_index("trade_date"),
    annualization=int(full_summary.get("annualization", 252)),
    risk_free_rate=float(full_summary.get("risk_free_rate", 0.0)),
)
summary.update(
    {
        "actual_start": view["trade_date"].min().date().isoformat(),
        "actual_end": view["trade_date"].max().date().isoformat(),
        "output_rows": len(view),
        "calendar_missing_dates": full_summary.get("calendar_missing_dates"),
    }
)
current = get_current_adjustment_snapshot(code)
current_id = int(current["id"]) if current else None
stale = current_id != int(latest["adjustment_snapshot_id"])

status_cols = st.columns(5)
status_cols[0].metric("指标状态", run["status"] if run else "-")
status_cols[1].metric("快照 ID", int(latest["adjustment_snapshot_id"]))
status_cols[2].metric("快照当前", "是" if not stale else "否")
status_cols[3].metric("行数", f"{len(view):,}")
status_cols[4].metric("质量", str(latest["quality_status"]))
if stale:
    st.error("该指标版本使用的复权快照已过期，请重新计算后再用于分析。")
st.caption(f"计算版本：{version}；指标配置：{run['indicator_config'] if run else '-'}")
st.caption(f"请求区间摘要：{summary.get('actual_start')} ~ {summary.get('actual_end')}")

tab_overview, tab_returns, tab_trend, tab_momentum, tab_vol, tab_quality = st.tabs(
    ["概览", "收益", "趋势", "动量", "波动与回撤", "数据质量"]
)

with tab_overview:
    cols = st.columns(4)
    cols[0].metric("区间收益", f"{summary.get('interval_return'):.2%}" if summary.get("interval_return") is not None else "不可计算")
    cols[1].metric("CAGR", f"{summary.get('cagr'):.2%}" if summary.get("cagr") is not None else "不可计算")
    cols[2].metric("年化波动率", f"{summary.get('annualized_volatility'):.2%}" if summary.get("annualized_volatility") is not None else "不可计算")
    cols[3].metric("最大回撤", f"{summary.get('max_drawdown'):.2%}" if summary.get("max_drawdown") is not None else "不可计算")
    cols = st.columns(3)
    cols[0].metric("夏普", f"{summary.get('sharpe_ratio'):.3f}" if summary.get("sharpe_ratio") is not None else "不可计算")
    cols[1].metric("索提诺", f"{summary.get('sortino_ratio'):.3f}" if summary.get("sortino_ratio") is not None else "不可计算")
    cols[2].metric("Calmar", f"{summary.get('calmar_ratio'):.3f}" if summary.get("calmar_ratio") is not None else "不可计算")
    st.json({"summary": summary, "parameters": json.loads(run["indicator_config"]) if run else {}, "quality_issues": quality.get("issues", [])})

with tab_returns:
    return_cols = [
        column
        for column in ["return_1d", "return_5d", "return_10d", "return_20d", "return_60d", "return_120d", "return_250d", "cagr"]
        if column in view.columns
    ]
    st.subheader("收益率最新值")
    latest_returns = {column: latest.get(column) for column in return_cols}
    st.dataframe(
        pd.DataFrame([{"指标": key, "数值": value} for key, value in latest_returns.items()]),
        width="stretch",
        hide_index=True,
    )
    st.subheader("累计净值（前复权）")
    nav = view.set_index("trade_date")["adjusted_close"] / view["adjusted_close"].dropna().iloc[0]
    st.line_chart(nav.rename("累计净值"))
    st.caption("累计净值仅基于所选区间内的有效前复权收盘价，缺失日起点不填充。")

with tab_trend:
    trend_cols = [column for column in ["adjusted_close", "ma5", "ma10", "ma20", "ma30", "ma60", "ma120", "ma250", "ema12", "ema26"] if column in view.columns]
    st.subheader("价格与均线")
    st.line_chart(view.set_index("trade_date")[trend_cols])
    st.caption("MA/EMA 只在窗口完整时输出；历史不足处为空。")

with tab_momentum:
    left, right = st.columns(2)
    with left:
        st.subheader("RSI")
        rsi_cols = [column for column in ["rsi6", "rsi12", "rsi24"] if column in view.columns]
        st.line_chart(view.set_index("trade_date")[rsi_cols])
    with right:
        st.subheader("MACD")
        macd_cols = [column for column in ["macd_dif", "macd_dea", "macd_hist"] if column in view.columns]
        st.line_chart(view.set_index("trade_date")[macd_cols])
    st.caption("RSI 使用 Wilder 平滑；MACD 柱 = 2 × (DIF - DEA)。")

with tab_vol:
    vol_cols = [column for column in ["volatility_20d", "volatility_60d", "volatility_120d"] if column in view.columns]
    mdd_cols = [column for column in ["max_drawdown_20d", "max_drawdown_60d", "max_drawdown_120d", "max_drawdown_all"] if column in view.columns]
    st.subheader("历史波动率")
    if vol_cols:
        st.line_chart(view.set_index("trade_date")[vol_cols])
    else:
        st.info("没有波动率数据。")
    st.subheader("回撤")
    if mdd_cols:
        st.line_chart(view.set_index("trade_date")[mdd_cols])
    else:
        st.info("没有回撤数据。")
    st.subheader("ATR")
    atr_cols = [column for column in ["atr14"] if column in view.columns]
    if atr_cols:
        st.line_chart(view.set_index("trade_date")[atr_cols])
    else:
        st.info("没有 ATR 数据。")
    st.caption("波动率使用日收益标准差 ddof=1 × sqrt(252)；ATR14 使用统一复权 OHLC。")

with tab_quality:
    st.subheader("数据质量")
    st.json(quality)
    coverage = quality.get("coverage", {})
    if coverage:
        coverage_frame = pd.DataFrame(
            [{"指标": key, **value} for key, value in coverage.items()]
        )
        st.dataframe(coverage_frame, width="stretch", hide_index=True)
    issues = quality.get("issues", [])
    st.subheader("质量问题")
    if issues:
        st.dataframe(pd.DataFrame(issues), width="stretch", hide_index=True)
    else:
        st.success("没有记录到数据质量问题。")
    st.subheader("指标明细（最近 200 行）")
    st.dataframe(view.tail(200), width="stretch", hide_index=True)
