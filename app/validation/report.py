"""阶段3A.2 验证报告生成。"""
from __future__ import annotations

from typing import Any


def _pct(value: Any, digits: int = 2) -> str:
    if value is None:
        return "不可计算"
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return "不可计算"


def _num(value: Any, digits: int = 4) -> str:
    if value is None:
        return "不可计算"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "不可计算"


def _int(value: Any) -> str:
    if value is None:
        return "不可计算"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "不可计算"


def render_validation_report(result) -> str:
    config = result.config
    lines: list[str] = []
    lines.append("# 阶段3A.2 策略可信度验证报告")
    lines.append("")
    lines.append(f"- validation_id：`{result.validation_id}`")
    lines.append(f"- 策略：`{config.strategy_name}` v{config.strategy_version}")
    lines.append(f"- 生成时间：{__import__('datetime').datetime.now().isoformat(timespec='seconds')}")
    lines.append("")
    lines.append("## 1. 验证配置与数据范围")
    lines.append("")
    lines.append("| 项目 | 内容 |")
    lines.append("| --- | --- |")
    lines.append(f"| 样本内区间 | {result.split['is_start']} ~ {result.split['is_end']}"
                 f"（{result.split['is_days']} 个交易日） |")
    lines.append(f"| 样本外区间 | {result.split['oos_start']} ~ {result.split['oos_end']}"
                 f"（{result.split['oos_days']} 个交易日） |")
    lines.append(f"| 区间重叠 | {'是（异常）' if result.split['overlap'] else '否'} |")
    lines.append(f"| 参与验证 ETF | {len(result.codes)} 只 |")
    lines.append(f"| 因覆盖不足剔除 | {len(result.excluded)} 只 |")
    lines.append(f"| 账户初始资金 | {config.initial_cash:,.0f} 元 |")
    lines.append(f"| 交易成本 | 佣金 {config.commission_rate:.4%}，最低 "
                 f"{config.min_commission:.2f} 元，滑点 {config.slippage_bps:.1f}bp |")
    lines.append(f"| 执行价格 | 次日{'开盘' if config.execution_price == 'open' else '收盘'} |")
    lines.append(f"| 指标版本 | `{config.indicator_version}` |")
    lines.append(f"| 参数网格 | MA {', '.join(str(x) for x in config.ma_window_grid)} |")
    fingerprint = getattr(result, "data_fingerprint", None) or {}
    if fingerprint:
        lines.append(
            f"| 数据指纹算法 | `{fingerprint.get('algorithm')}` |"
        )
        lines.append(
            f"| 数据指纹 SHA256 | `{fingerprint.get('sha256')}`（{fingerprint.get('rows')} 行） |"
        )
    lines.append("")

    if result.excluded:
        lines.append("### 被剔除的 ETF")
        lines.append("")
        lines.append("| ETF | 行情行数 | 区间交易日 | 覆盖率 | 原因 |")
        lines.append("| --- | ---: | ---: | ---: | --- |")
        for item in result.excluded:
            lines.append(
                f"| `{item['code']}` | {item['rows']:,} | {item['calendar_days']:,} | "
                f"{item['coverage']:.1%} | {item['reason']} |"
            )
        lines.append("")

    lines.append("## 2. 数据完整性说明")
    lines.append("")
    lines.append("- 行情、指标、复权快照均来自现有数据库，未做任何填充或修改。")
    lines.append("- 样本内外严格按真实交易日切分，无重叠、无随机打乱。")
    lines.append("- 缺失交易日不在收益序列中被压缩，不影响 Sharpe/Sortino 口径。")
    lines.append("- 持仓 ETF 缺有效报价的日期，日收益已从风险统计中排除。")
    for note in result.notes:
        lines.append(f"- {note}")
    lines.append("")

    lines.append("## 3. 样本内结果")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("| --- | ---: |")
    lines.append(f"| 最优参数 | MA{result.grid.get('best_param')} |")
    lines.append(f"| 总收益率 | {_pct(result.is_metrics.get('total_return'))} |")
    lines.append(f"| CAGR | {_pct(result.is_metrics.get('cagr'))} |")
    lines.append(f"| 年化波动率 | {_pct(result.is_metrics.get('annualized_volatility'))} |")
    lines.append(f"| Sharpe | {_num(result.is_metrics.get('sharpe_ratio'))} |")
    lines.append(f"| Sortino | {_num(result.is_metrics.get('sortino_ratio'))} |")
    lines.append(f"| 最大回撤 | {_pct(result.is_metrics.get('max_drawdown'))} |")
    lines.append(f"| Calmar | {_num(result.is_metrics.get('calmar_ratio'))} |")
    lines.append(f"| 交易次数 | {_int(result.is_metrics.get('trade_count'))} |")
    lines.append(f"| 换手率 | {_num(result.is_metrics.get('turnover'), 2)} |")
    lines.append(f"| 风险收益样本日 | {_int(result.is_metrics.get('risk_sample_days'))} |")
    lines.append("")

    lines.append("## 4. 样本外结果（独立展示）")
    lines.append("")
    lines.append("样本外只使用样本内选出的参数，未用样本外数据做任何参数选择。")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("| --- | ---: |")
    lines.append(f"| 参数（来自样本内） | MA{result.grid.get('best_param')} |")
    lines.append(f"| 总收益率 | {_pct(result.oos_metrics.get('total_return'))} |")
    lines.append(f"| CAGR | {_pct(result.oos_metrics.get('cagr'))} |")
    lines.append(f"| 年化波动率 | {_pct(result.oos_metrics.get('annualized_volatility'))} |")
    lines.append(f"| Sharpe | {_num(result.oos_metrics.get('sharpe_ratio'))} |")
    lines.append(f"| Sortino | {_num(result.oos_metrics.get('sortino_ratio'))} |")
    lines.append(f"| 最大回撤 | {_pct(result.oos_metrics.get('max_drawdown'))} |")
    lines.append(f"| Calmar | {_num(result.oos_metrics.get('calmar_ratio'))} |")
    lines.append(f"| 交易次数 | {_int(result.oos_metrics.get('trade_count'))} |")
    lines.append("")

    lines.append("## 5. Walk-Forward 结果")
    lines.append("")
    ok = [w for w in result.windows if w["status"] == "success"]
    lines.append(f"窗口总数 {len(result.windows)}，成功 {len(ok)}，"
                 f"数据不足 {sum(1 for w in result.windows if w['status'] == 'insufficient_data')}，"
                 f"失败 {sum(1 for w in result.windows if w['status'] == 'failed')}。")
    lines.append("")
    lines.append("| 窗口 | 训练区间 | 训练天数 | 验证区间 | 验证天数 | 选中参数 | "
                 "验证期收益 | 验证期Sharpe | 验证期回撤 | 状态 |")
    lines.append("| ---: | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |")
    for window in result.windows:
        test = window.get("test_metrics") or {}
        lines.append(
            f"| {window['index']} | {window['train_start']}~{window['train_end']} | "
            f"{_int(window['train_days'])} | {window['test_start']}~{window['test_end']} | "
            f"{_int(window['test_days'])} | "
            f"{('MA' + str(window['selected_param'])) if window.get('selected_param') else '-'} | "
            f"{_pct(test.get('total_return'))} | {_num(test.get('sharpe_ratio'))} | "
            f"{_pct(test.get('max_drawdown'))} | {window['status']} |"
        )
    lines.append("")
    reasons = [w for w in result.windows if w.get("reason")]
    if reasons:
        lines.append("### 窗口说明")
        lines.append("")
        for window in reasons:
            lines.append(f"- 窗口 {window['index']}：{window['reason']}")
        lines.append("")

    lines.append("## 6. 市场环境结果")
    lines.append("")
    regime = result.regime
    if not regime.get("labels_available"):
        lines.append(f"市场环境分类不可用：{regime.get('error', '未知原因')}")
    else:
        lines.append(f"参考标的：`{regime['proxy_code']}`（{regime['proxy_note']}）")
        lines.append("")
        lines.append("分类规则：收盘价相对 MA250 偏离 > +5% 为牛市，< -5% 为熊市，"
                     "其余为震荡市；MA250 样本不足时标记 unclassified，不强行归类。")
        lines.append("")
        warmup = regime.get("warmup") or {}
        if warmup:
            lines.append(
                f"预热数据：有效价格 {warmup.get('valid_prices', warmup.get('days'))} 个"
                f"（需求 {warmup.get('required')}），"
                f"数据库记录 {warmup.get('db_rows', '-')} 条，"
                f"无效价格 {warmup.get('invalid_prices', '-')} 条，"
                f"状态 `{warmup.get('status')}`"
            )
            lines.append("")
        output_range = regime.get("output_range") or {}
        if output_range:
            lines.append(
                f"输出区间：{output_range.get('start')} ~ {output_range.get('end')}"
                f"（OOS {output_range.get('oos_start')} ~ {output_range.get('oos_end')}）"
            )
            lines.append("")
        summary = regime.get("summary", {})
        lines.append(
            f"分类天数：{summary.get('counts', {})}；"
            f"预热 {summary.get('warmup_days')} 天不计入输出"
        )
        lines.append("")
        diagnostics = regime.get("oos_return_diagnostics") or {}
        if diagnostics:
            lines.append(
                f"OOS 日收益诊断（口径 `{diagnostics.get('definition')}`）："
                f"快照 {diagnostics.get('nav_days')} 天 = "
                f"首日 {diagnostics.get('first_day')} + "
                f"缺口 {diagnostics.get('gap_days_excluded')} + "
                f"缺净值 {diagnostics.get('missing_nav')} + "
                f"有效 {diagnostics.get('valid_return_days')}"
                f"（可加总：{diagnostics.get('identity_holds')}）。"
                f"缺失日保留 NaN，未压缩。"
            )
            lines.append("")
        lines.append("| 环境 | 区间交易日 | 有效日收益 | 缺失日 | 状态 | 累计收益 | 胜率 | 年化波动率 |")
        lines.append("| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: |")
        for label in ("bull", "bear", "range", "unclassified"):
            entry = regime.get("stats", {}).get(label, {})
            if not entry:
                continue
            lines.append(
                f"| {label} | {_int(entry.get('total_days'))} | "
                f"{_int(entry.get('valid_days'))} | {_int(entry.get('missing_days'))} | "
                f"{entry.get('status')} | "
                f"{_pct(entry.get('cumulative_return'))} | {_pct(entry.get('win_rate'))} | "
                f"{_pct(entry.get('annualized_volatility'))} |"
            )
        lines.append("")
        lines.append("累计收益只按有效日收益复利，缺失日不计入，不代表连续交易日收益。")
        for note in summary.get("notes", []):
            lines.append("")
            lines.append(f"- {note}")
    lines.append("")

    lines.append("## 7. 参数敏感性结果")
    lines.append("")
    lines.append("以下为样本内全部参数组合，不只展示最优。")
    lines.append("")
    lines.append("| MA窗口 | 状态 | 总收益 | CAGR | Sharpe | Sortino | 最大回撤 | Calmar | 交易次数 | 换手率 |")
    lines.append("| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in result.grid.get("grid", []):
        metrics = row.get("metrics") or {}
        lines.append(
            f"| {row['ma_window']} | {row['status']} | "
            f"{_pct(metrics.get('total_return'))} | {_pct(metrics.get('cagr'))} | "
            f"{_num(metrics.get('sharpe_ratio'))} | {_num(metrics.get('sortino_ratio'))} | "
            f"{_pct(metrics.get('max_drawdown'))} | {_num(metrics.get('calmar_ratio'))} | "
            f"{_int(metrics.get('trade_count'))} | {_num(metrics.get('turnover'), 2)} |"
        )
    lines.append("")
    lines.append(
        f"正收益组合：{result.grid.get('positive_count')} / "
        f"{result.grid.get('total_count')}"
        f"（{_pct(result.grid.get('positive_ratio'))}）"
    )
    lines.append("")
    if result.grid.get("stable_neighbors"):
        lines.append(f"稳定相邻档位：{result.grid['stable_neighbors']}")
    else:
        lines.append("稳定相邻档位：无")
    lines.append("")
    oos_cell = result.grid.get("oos_result")
    if oos_cell:
        lines.append("### 样本外最终验证（仅最优参数，不参与选参）")
        lines.append("")
        lines.append(f"MA{oos_cell['ma_window']}：状态 {oos_cell['status']}")
        lines.append("")
    flags = result.grid.get("risk_flags", [])
    if flags:
        lines.append("### 过拟合风险提示")
        lines.append("")
        for flag in flags:
            lines.append(f"- {flag}")
        lines.append("")

    lines.append("## 8. 基准比较")
    lines.append("")
    lines.append("| 基准 | 区间 | 状态 | 总收益 | CAGR | Sharpe | 最大回撤 | 交易次数 |")
    lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |")
    for row in result.benchmarks:
        metrics = row.get("metrics") or {}
        lines.append(
            f"| {row['name']} | {row.get('range') or '-'} | {row['status']} | "
            f"{_pct(metrics.get('total_return'))} | {_pct(metrics.get('cagr'))} | "
            f"{_num(metrics.get('sharpe_ratio'))} | {_pct(metrics.get('max_drawdown'))} | "
            f"{_int(metrics.get('trade_count'))} |"
        )
    lines.append("")
    lines.append("口径说明：")
    lines.append("")
    lines.append("- 数据库没有独立指数表，沪深300/中证500 基准使用对应 ETF 代理，"
                 "含跟踪误差与交易费用，不能与纯指数收益直接等同。")
    lines.append("- 所有基准使用同一初始资金、同一成本与滑点配置。")
    lines.append("")

    lines.append("## 9. 压力测试结果")
    lines.append("")
    lines.append("| 场景 | 类型 | 假设 | 状态 | 总收益 | Sharpe | 最大回撤 | 交易次数 |")
    lines.append("| --- | --- | --- | --- | ---: | ---: | ---: | ---: |")
    for row in result.stress:
        metrics = row.get("metrics") or {}
        lines.append(
            f"| {row['name']} | {row.get('config', {}).get('kind', '-')} | "
            f"{'模拟假设' if row.get('is_hypothetical') else '实际配置'} | {row['status']} | "
            f"{_pct(metrics.get('total_return'))} | {_num(metrics.get('sharpe_ratio'))} | "
            f"{_pct(metrics.get('max_drawdown'))} | {_int(metrics.get('trade_count'))} |"
        )
    lines.append("")
    lines.append("所有成本与滑点变化均为模拟假设，未修改任何历史行情。")
    lines.append("")
    data_scenarios = [
        row for row in result.stress
        if (row.get("config") or {}).get("kind") == "data"
    ]
    if data_scenarios:
        lines.append("### 数据类压力场景")
        lines.append("")
        lines.append("| 场景 | 状态 | 结果说明 |")
        lines.append("| --- | --- | --- |")
        for row in data_scenarios:
            evaluation = row.get("evaluation") or {}
            lines.append(
                f"| {row['name']} | {row['status']} | {row.get('reason') or '-'} |"
            )
            if evaluation:
                parts = []
                for key, label in (
                    ("daily_rows", "快照"),
                    ("trading_days", "交易日"),
                    ("first_day_skipped", "首日"),
                    ("gap_days_excluded", "缺口"),
                    ("missing_nav_days", "缺净值"),
                    ("valid_return_days", "有效收益"),
                ):
                    value = evaluation.get(key)
                    if value is not None:
                        parts.append(f"{label} {value}")
                if parts:
                    lines.append(f"| | | {' / '.join(parts)} |")
        lines.append("")
        lines.append(
            "数据类场景在独立 SQLite 副本上执行，源数据库行数与指纹前后一致。"
        )
        lines.append("")

    lines.append("## 10. 过拟合风险评估")
    lines.append("")
    flags = result.grid.get("risk_flags", [])
    if flags:
        for flag in flags:
            lines.append(f"- {flag}")
    else:
        lines.append("- 未检测到明显的过拟合特征，但仍需结合样本外表现判断。")
    lines.append("")

    lines.append("## 11. 数据质量与局限性")
    lines.append("")
    lines.append("- 回测为价格收益口径：数据库无分红/拆分事件表，分红贡献被低估。")
    lines.append("- 滑点为固定 bp，无冲击成本与成交量约束。")
    lines.append("- 涨跌停为整日近似。")
    lines.append("- 债券/商品 ETF 交易规则未逐一确认，采用保守上限。")
    lines.append("- 基准使用 ETF 代理而非真实指数。")
    lines.append("- 样本外区间仅覆盖单一市场阶段，不能代表全部市场环境。")
    lines.append("- 策略参数只有 MA 窗口一个自由度，参数敏感性的解释力有限。")
    lines.append("")

    lines.append("## 12. 最终结论")
    lines.append("")
    lines.append(f"**{result.conclusion}**")
    lines.append("")
    for reason in result.conclusion_reasons:
        lines.append(f"- {reason}")
    lines.append("")
    lines.append("本结论基于样本外表现、Walk-Forward 稳定性、参数敏感性与压力测试，"
                 "不依据单一收益数字。")
    return "\n".join(lines) + "\n"
