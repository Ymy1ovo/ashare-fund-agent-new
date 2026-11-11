"""简单均线趋势策略。

规则：信号日收盘价（前复权）高于 MA 时目标满仓，否则空仓。
只用 signal_date 及之前的指标；不引用未来数据。
"""
from __future__ import annotations

from app.backtest.strategies.base import StrategyContext, TargetWeight


class MovingAverageTrendStrategy:
    name = "ma_trend"
    version = "1.0.0"

    def __init__(self, ma_window: int = 20, codes: list[str] | None = None) -> None:
        if ma_window < 2:
            raise ValueError("ma_window 必须 >= 2")
        self.ma_window = int(ma_window)
        self.codes = codes

    def target_weights(self, context: StrategyContext) -> list[TargetWeight]:
        targets: list[TargetWeight] = []
        selected = [code for code in (self.codes or context.codes) if code in context.codes]
        holding: list[str] = []
        for code in selected:
            indicators = context.indicators.get(code)
            if indicators is None or indicators.empty:
                continue
            column = f"ma{self.ma_window}"
            if column not in indicators.columns:
                continue
            row = indicators.loc[indicators.index <= context.signal_date]
            if row.empty:
                continue
            latest = row.iloc[-1]
            ma_value = latest.get(column)
            price = latest.get("adjusted_close")
            if ma_value is None or price is None:
                continue
            try:
                if float(price) > float(ma_value):
                    holding.append(code)
            except (TypeError, ValueError):
                continue
        if not holding:
            # 明确空仓；引擎按容忍带决定是否真的产生卖单
            return [] if any(value > 0 for value in context.current_weights.values()) else None
        weight = 1.0 / len(holding)
        for code in holding:
            targets.append(TargetWeight(code=code, weight=weight))
        return targets
