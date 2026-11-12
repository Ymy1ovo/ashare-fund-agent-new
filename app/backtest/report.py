"""回测报告：Markdown 输出。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.backtest.engine import BacktestResult
from app.backtest.metrics import Performance, reconcile, yearly_table


def _pct(value: float | None) -> str:
    return "不可计算" if value is None else f"{value:.2%}"


def _num(value: float | None, digits: int = 4) -> str:
    return "不可计算" if value is None else f"{value:.{digits}f}"


def render_report(result: BacktestResult, performance: Performance) -> str:
    check = reconcile(result.daily, result.trades, result.initial_cash)
    lines = [
        "# 回测报告",
        "",
        f"- 回测 ID：`{result.run_id}`",
        f"- 策略：{result.strategy_name} v{result.strategy_version}",
        f"- 区间：{result.config.start_date} ~ {result.config.end_date}",
        f"- 执行价：{result.config.execution_price}（下一交易日）",
        f"- 初始资金：{result.initial_cash:,.2f}",
        f"- ETF：{', '.join(result.codes)}",
        f"- 指标版本：{result.indicator_version or '未使用'}",
        f"- 复权快照：{result.snapshot_ids}",
        f"- 输入哈希：`{result.input_hash}`",
        f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        "",
        "## 1. 绩效",
        "",
        "| 指标 | 数值 |",
        "| --- | ---: |",
        f"| 总收益率 | {_pct(performance.total_return)} |",
        f"| CAGR | {_pct(performance.cagr)} |",
        f"| 年化波动率 | {_pct(performance.annualized_volatility)} |",
        f"| 最大回撤 | {_pct(performance.max_drawdown)} |",
        f"| 夏普（日均超额年化） | {_num(performance.sharpe_ratio)} |",
        f"| 索提诺（下行风险） | {_num(performance.sortino_ratio)} |",
        f"| 日均收益 | {_pct(performance.mean_daily_return)} |",
        f"| 日均无风险利率 | {_pct(performance.daily_rf)} |",
        f"| 下行波动率（年化） | {_pct(performance.downside_deviation)} |",
        f"| 风险统计样本日 | {performance.risk_sample_days} |",
        f"| 因估值缺口排除的日收益 | {performance.gap_return_days_excluded} |",
        f"| Calmar | {_num(performance.calmar_ratio)} |",
        f"| 胜率 | {_pct(performance.win_rate)} |",
        f"| 盈亏比 | {_num(performance.profit_loss_ratio)} |",
        f"| 成交笔数 | {performance.trade_count} |",
        f"| 清仓笔数 | {performance.closed_trade_count} |",
        f"| 换手率 | {_num(performance.turnover)} |",
        f"| 佣金合计 | {performance.total_commission:,.2f} |",
        f"| 印花税合计 | {performance.total_stamp_tax:,.2f} |",
        f"| 过户费合计 | {performance.total_transfer_fee:,.2f} |",
        f"| 交易费用合计（佣金+税费） | {performance.total_trade_fees:,.2f} |",
        f"| 滑点成本合计 | {performance.total_slippage:,.2f} |",
        f"| **总成本（费用+滑点）** | **{performance.total_cost:,.2f}** |",
        f"| 平均持仓天数 | {_num(performance.average_holding_days, 1)} |",
        f"| 资金使用率 | {_pct(performance.capital_utilization)} |",
        f"| 交易日数 | {performance.trading_days} |",
        "",
        "## 2. 账本核对",
        "",
        f"- 结果：{'通过' if check['ok'] else '失败'}",
    ]
    lines += [f"- 错误：{error}" for error in check["errors"]]
    lines += ["", "## 3. 年度收益", "", "| 年度 | 收益率 | 交易日 |", "| --- | ---: | ---: |"]
    for row in yearly_table(result.daily):
        lines.append(f"| {row['year']} | {_pct(row['return'])} | {row['days']} |")
    lines += ["", "## 4. 交易明细", ""]
    if result.trades:
        lines += [
            "| # | 日期 | 代码 | 方向 | 数量 | 价格 | 金额 | 佣金 | 印花税 | 过户费 | "
            "费用合计 | 滑点 | 已实现盈亏 |",
            "| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | "
            "---: | ---: | ---: |",
        ]
        for trade in result.trades:
            lines.append(
                f"| {trade.trade_id} | {trade.trade_date} | {trade.code} | {trade.side} | "
                f"{trade.quantity} | {trade.price:.4f} | {trade.gross_amount:,.2f} | "
                f"{trade.commission:.2f} | {trade.stamp_tax:.2f} | {trade.transfer_fee:.2f} | "
                f"{trade.total_fees:.2f} | {trade.slippage_cost:.2f} | "
                f"{trade.realized_pnl:,.2f} |"
            )
    else:
        lines.append("- 无成交")
    lines += ["", "## 5. 未成交订单", ""]
    bad = [order for order in result.orders if order.status not in ("filled",)]
    if bad:
        lines += [
            "| 订单 | 代码 | 方向 | 信号日 | 状态 | 原因 |",
            "| ---: | --- | --- | --- | --- | --- |",
        ]
        for order in bad:
            lines.append(
                f"| {order.order_id} | {order.code} | {order.side} | {order.signal_date} | "
                f"{order.status} | {order.reason or '-'} |"
            )
    else:
        lines.append("- 无")
    lines += ["", "## 6. 提示", ""]
    for note in performance.notes + result.notes:
        lines.append(f"- {note}")
    if not performance.notes and not result.notes:
        lines.append("- 无")
    lines += [
        "",
        "## 7. 口径说明",
        "",
        "- Sharpe/Sortino 使用有效日收益：日均超额收益年化 ÷ 年化波动率 / 下行波动率；CAGR 单独计算。",
        "- 持仓 ETF 缺有效报价的当日及次日，日收益被排除出风险统计，不当作正常单日收益。",
        "- 成交与估值使用原始 OHLC，不使用前复权价成交。",
        "- 信号使用截至 T 日的前复权指标，最早 T+1 开盘成交。",
        "- 未建模现金分红/拆分，收益为价格口径，低估分红贡献。",
        "- 本报告仅为历史模拟，不构成投资建议。",
        "",
    ]
    return "\n".join(lines)
