"""阶段3A.2 策略可信度验证页面。

只读取数据库中已保存的验证结果，不在此处重跑回测。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.validation.storage import get_validation, list_validations  # noqa: E402


def _fmt(value, kind: str = "num") -> str:
    """统一格式化；None 显示为不可计算，不用 0 冒充。"""
    if value is None:
        return "不可计算"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "不可计算"
    if kind == "pct":
        return f"{number * 100:.2f}%"
    if kind == "int":
        return f"{int(number):,}"
    return f"{number:.4f}"

st.set_page_config(page_title="策略验证", page_icon="🔍", layout="wide")
st.title("策略可信度验证（阶段3A.2）")
st.caption("结论基于样本外表现、Walk-Forward、参数敏感性与压力测试，不构成投资建议。")

runs = list_validations(limit=50)
if not runs:
    st.warning("还没有验证记录。请先运行：`python scripts/run_validation.py`")
    st.stop()

labels = [
    f"{row['validation_id']} | {row['conclusion'] or row['status']} | {row['created_at']}"
    for row in runs
]
choice = st.selectbox("选择验证记录", labels)
validation_id = choice.split(" | ")[0]
payload = get_validation(validation_id)
if not payload:
    st.error("验证记录不存在")
    st.stop()

summary = payload.get("summary_json") or {}
if isinstance(summary, str):
    summary = json.loads(summary)

col1, col2, col3, col4 = st.columns(4)
col1.metric("结论", payload.get("conclusion") or payload.get("status"))
col2.metric("样本内区间", f"{payload.get('is_start')} ~ {payload.get('is_end')}")
col3.metric("样本外区间", f"{payload.get('oos_start')} ~ {payload.get('oos_end')}")
col4.metric("状态", payload.get("status"))

st.divider()

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["样本内/外", "Walk-Forward", "参数敏感性", "基准与压力", "数据质量"]
)

with tab1:
    st.subheader("样本内 vs 样本外")
    is_metrics = summary.get("is_metrics") or {}
    oos_metrics = summary.get("oos_metrics") or {}
    keys = [
        ("total_return", "总收益率", "pct"),
        ("cagr", "CAGR", "pct"),
        ("annualized_volatility", "年化波动率", "pct"),
        ("sharpe_ratio", "Sharpe", "num"),
        ("sortino_ratio", "Sortino", "num"),
        ("max_drawdown", "最大回撤", "pct"),
        ("calmar_ratio", "Calmar", "num"),
        ("trade_count", "交易次数", "int"),
    ]
    rows = []
    for key, name, kind in keys:
        rows.append({
            "指标": name,
            "样本内": _fmt(is_metrics.get(key), kind),
            "样本外": _fmt(oos_metrics.get(key), kind),
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.info(
        "样本外只使用样本内选出的参数，未用样本外数据调参。"
        "样本外结果单独展示，不参与参数选择。"
    )

with tab2:
    st.subheader("Walk-Forward 滚动窗口")
    windows = payload.get("windows") or []
    if not windows:
        st.warning("没有窗口记录")
    else:
        rows = []
        for window in windows:
            metrics = window.get("test_metrics_json") or {}
            if isinstance(metrics, str):
                metrics = json.loads(metrics)
            rows.append({
                "窗口": window["window_index"],
                "训练区间": f"{window['train_start']} ~ {window['train_end']}",
                "验证区间": f"{window['test_start']} ~ {window['test_end']}",
                "选中参数": f"MA{window['selected_param']}" if window.get("selected_param") else "-",
                "验证收益": _fmt(metrics.get("total_return"), "pct"),
                "验证Sharpe": _fmt(metrics.get("sharpe_ratio"), "num"),
                "验证回撤": _fmt(metrics.get("max_drawdown"), "pct"),
                "状态": window["status"],
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)
        failed = [w for w in windows if w["status"] != "success"]
        if failed:
            st.warning(f"{len(failed)} 个窗口未成功，原因已记录在数据表 status 列。")

with tab3:
    st.subheader("参数敏感性（样本内全部组合）")
    grid = payload.get("grid") or []
    if not grid:
        st.warning("没有参数网格记录")
    else:
        rows = []
        for cell in grid:
            metrics = cell.get("metrics_json") or {}
            if isinstance(metrics, str):
                metrics = json.loads(metrics)
            rows.append({
                "阶段": cell["phase"],
                "MA窗口": cell["ma_window"],
                "状态": cell["status"],
                "总收益": _fmt(metrics.get("total_return"), "pct"),
                "Sharpe": _fmt(metrics.get("sharpe_ratio"), "num"),
                "最大回撤": _fmt(metrics.get("max_drawdown"), "pct"),
                "交易次数": metrics.get("trade_count"),
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)
        st.caption("展示全部参数组合，不做筛选。")

with tab4:
    st.subheader("压力测试场景")
    stress = payload.get("stress") or []
    if not stress:
        st.warning("没有压力测试记录")
    else:
        rows = []
        for row in stress:
            metrics = row.get("metrics_json") or {}
            if isinstance(metrics, str):
                metrics = json.loads(metrics)
            rows.append({
                "场景": row["scenario_name"] or row["scenario_key"],
                "假设": "模拟假设" if row["is_hypothetical"] else "实际配置",
                "状态": row["status"],
                "总收益": _fmt(metrics.get("total_return"), "pct"),
                "Sharpe": _fmt(metrics.get("sharpe_ratio"), "num"),
                "最大回撤": _fmt(metrics.get("max_drawdown"), "pct"),
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)
        st.caption("所有成本/滑点变化均为模拟假设，未修改任何历史行情。")

with tab5:
    st.subheader("数据质量与局限")
    excluded = payload.get("excluded_codes") or []
    if isinstance(excluded, str):
        excluded = json.loads(excluded)
    if excluded:
        st.write(f"因数据不足被剔除：{len(excluded)} 项")
        st.dataframe(excluded, use_container_width=True, hide_index=True)
    reasons = summary.get("conclusion_reasons") or []
    if reasons:
        st.write("结论依据：")
        for reason in reasons:
            st.write(f"- {reason}")
    st.warning(
        "回测为价格收益口径，无分红/拆分数据；基准使用 ETF 代理而非真实指数；"
        "样本外区间仅覆盖单一市场阶段。"
    )
