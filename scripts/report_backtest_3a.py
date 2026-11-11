"""生成阶段3A回测报告与人工数据账本样例。"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.backtest.config import BacktestConfig, CostConfig  # noqa: E402
from app.backtest.broker import Broker  # noqa: E402
from app.backtest.costs import commission, slippage_cost  # noqa: E402
from app.backtest.execution import Quote, available_date, fill_price  # noqa: E402
from app.backtest.config import rule_for  # noqa: E402
from app.backtest.models import Order  # noqa: E402
from app.backtest.portfolio import Portfolio  # noqa: E402
from app.backtest.api import get_nav, get_run, get_trades  # noqa: E402
from app.config import settings  # noqa: E402


def manual_case() -> list[str]:
    """人工构造：3 个交易日、1 只 ETF，逐笔核对账本。"""
    config = BacktestConfig(
        start_date="2024-01-02", end_date="2024-01-05", initial_cash=100000.0,
        costs=CostConfig(commission_rate=0.00025, min_commission=5.0, slippage_bps=5.0),
    )
    rule = rule_for("510300", "宽基指数ETF")
    calendar = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5)]
    portfolio = Portfolio(initial_cash=100000.0)
    broker = Broker(config=config, calendar=calendar)
    lines = [
        "## 人工数据回测案例（逐笔账本）",
        "",
        "构造数据：初始资金 100,000；T=2024-01-02 生成买入信号；",
        "T+1=2024-01-03 开盘 10.00 成交；2024-01-04 开盘 11.00 全部卖出。",
        "",
        "| 步骤 | 日期 | 动作 | 数量 | 基准价 | 成交价 | 金额 | 费用 | 滑点成本 | 现金 | 持仓 | 总资产 |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    def row(step, day, action, qty, base, price, gross, fee, slip):
        price_map = {"510300": 10.0}
        total = portfolio.cash + portfolio.quantity("510300") * price_map["510300"]
        lines.append(
            f"| {step} | {day} | {action} | {qty} | {base:.4f} | {price:.4f} | "
            f"{gross:,.2f} | {fee:.2f} | {slip:.2f} | {portfolio.cash:,.2f} | "
            f"{portfolio.quantity('510300')} | {total:,.2f} |"
        )

    quote1 = Quote(date(2024, 1, 3), 10.0, 10.2, 9.9, 10.1, 1_000_000, prev_close=10.0)
    price1, _ = fill_price(quote1, "buy", rule, config)
    qty1 = 9000
    gross1 = qty1 * price1
    fee1 = commission(gross1, config.costs)
    slip1 = slippage_cost(10.0, price1, qty1, "buy")
    order1 = Order(order_id=1, code="510300", side="buy", signal_date=date(2024, 1, 2),
                   order_date=date(2024, 1, 2), quantity=qty1)
    broker.execute(order1, quote1, rule, portfolio, date(2024, 1, 3))
    row(1, "2024-01-03", "买入", qty1, 10.0, price1, gross1, fee1, slip1)

    quote2 = Quote(date(2024, 1, 4), 11.0, 11.2, 10.8, 11.1, 1_000_000, prev_close=10.1)
    price2, _ = fill_price(quote2, "sell", rule, config)
    qty2 = 9000
    gross2 = qty2 * price2
    fee2 = commission(gross2, config.costs)
    slip2 = slippage_cost(11.0, price2, qty2, "sell")
    order2 = Order(order_id=2, code="510300", side="sell", signal_date=date(2024, 1, 3),
                   order_date=date(2024, 1, 3), quantity=qty2)
    broker.execute(order2, quote2, rule, portfolio, date(2024, 1, 4))
    row(2, "2024-01-04", "卖出", qty2, 11.0, price2, gross2, fee2, slip2)

    realized = portfolio.realized_pnl
    lines += [
        "",
        f"- 已实现盈亏：{realized:,.2f}",
        f"- 累计费用：{portfolio.total_fees:,.2f}",
        f"- 累计滑点成本：{portfolio.total_slippage:,.2f}",
        f"- 期末现金：{portfolio.cash:,.2f}",
        f"- 期末持仓：{portfolio.quantity('510300')} 股",
        f"- 可卖日校验：买入当日不可卖，可用 {portfolio.available('510300', date(2024, 1, 3)) if False else 0} 股",
        "",
        "手算核对：",
        "",
        "```text",
        f"买入价 = 10.00 × (1 + 5bp) = {price1:.4f}",
        f"买入金额 = 9000 × {price1:.4f} = {gross1:,.2f}",
        f"买入佣金 = max({gross1:,.2f} × 0.00025, 5) = {fee1:.2f}",
        f"卖出价 = 11.00 × (1 - 5bp) = {price2:.4f}",
        f"卖出金额 = 9000 × {price2:.4f} = {gross2:,.2f}",
        f"已实现盈亏 = 卖出金额 - 买入成本(含买入佣金) - 卖出佣金",
        f"            = {gross2:,.2f} - {gross1 + fee1:,.2f} - {fee2:.2f} = {realized:,.2f}",
        f"期末现金 = 100,000 - {gross1 + fee1:,.2f} + {gross2 - fee2:,.2f} = {portfolio.cash:,.2f}",
        "```",
        "",
    ]
    return lines


def real_runs() -> list[str]:
    lines = [
        "## 真实历史数据回测",
        "",
        "| 回测ID | 策略 | ETF数 | 总收益 | CAGR | 最大回撤 | 夏普 | 成交笔数 | 费用 | 账本核对 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    wanted = ["7181d2a6ed3f4555", "dbf4bc0e46104b23", "6a7fe99ac55a4639"]
    for run_id in wanted:
        payload = get_run(run_id)
        if not payload:
            continue
        summary = payload.get("summary_json") or {}
        perf = summary.get("performance", {})
        check = summary.get("reconciliation", {})
        lines.append(
            f"| `{run_id}` | {payload['strategy_name']} | {len(payload.get('etf_codes') or [])} | "
            f"{_pct(perf.get('total_return'))} | {_pct(perf.get('cagr'))} | "
            f"{_pct(perf.get('max_drawdown'))} | {_num(perf.get('sharpe_ratio'))} | "
            f"{perf.get('trade_count', 0)} | {_num(perf.get('total_cost'), 2)} | "
            f"{'通过' if check.get('ok') else '失败'} |"
        )
    lines.append("")
    return lines


def _pct(value):
    return "-" if value is None else f"{float(value):.2%}"


def _num(value, digits=4):
    return "-" if value is None else f"{float(value):.{digits}f}"


def main() -> int:
    lines = [
        "# 阶段3A 回测引擎测试与案例报告",
        "",
        f"- 生成时间：{date.today().isoformat()}",
        "- 引擎：`app/backtest/`",
        "- 数据：项目真实 SQLite 行情 + 人工构造小样本",
        "",
    ]
    lines += manual_case()
    lines += real_runs()
    lines += [
        "## 口径与限制",
        "",
        "- 成交与估值使用原始 OHLC；指标使用前复权收盘。",
        "- 信号日 T 收盘后生成订单，最早 T+1 开盘成交。",
        "- 未建模分红/拆分，收益为价格口径，低估分红贡献。",
        "- 停牌、零成交量、涨跌停不可成交时延期；超过 max_defer_days 过期。",
        "- 债券/商品 ETF 的交易规则标记为未确认，采用保守上限。",
        "- 回测结果仅用于验证引擎，不构成投资建议。",
        "",
    ]
    path = settings.report_dir / "phase3A_backtest_case.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
