"""回测策略。"""
from app.backtest.strategies.base import Strategy, StrategyContext, TargetWeight
from app.backtest.strategies.buy_and_hold import BuyAndHoldStrategy
from app.backtest.strategies.ma_trend import MovingAverageTrendStrategy

__all__ = [
    "Strategy",
    "StrategyContext",
    "TargetWeight",
    "BuyAndHoldStrategy",
    "MovingAverageTrendStrategy",
]
