"""买入并持有基准策略。"""
from __future__ import annotations

from app.backtest.strategies.base import StrategyContext, TargetWeight


class BuyAndHoldStrategy:
    """首日等权买入，之后不再调仓。"""

    name = "buy_and_hold"
    version = "1.0.0"

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self.weights = weights or {}

    def target_weights(self, context: StrategyContext) -> list[TargetWeight] | None:
        if context.current_weights and any(value > 0 for value in context.current_weights.values()):
            return None
        if self.weights:
            total = sum(self.weights.values())
            if total <= 0:
                raise ValueError("buy_and_hold 权重之和必须为正")
            return [
                TargetWeight(code=code, weight=weight / total)
                for code, weight in self.weights.items()
                if code in context.codes and weight > 0
            ]
        if not context.codes:
            return []
        equal = 1.0 / len(context.codes)
        return [TargetWeight(code=code, weight=equal) for code in context.codes]
