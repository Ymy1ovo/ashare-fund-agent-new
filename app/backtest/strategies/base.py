"""策略接口。

策略只能看到截至 signal_date（含当日）的数据，由引擎保证切片。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

import pandas as pd


@dataclass
class TargetWeight:
    """目标权重；weight=0 表示清仓。"""

    code: str
    weight: float


@dataclass
class StrategyContext:
    """策略可见的全部信息（已按 signal_date 截断）。"""

    signal_date: date
    codes: list[str]
    bars: dict[str, pd.DataFrame]
    indicators: dict[str, pd.DataFrame]
    current_weights: dict[str, float]
    history_days: int
    extra: dict = field(default_factory=dict)


class Strategy(Protocol):
    """策略协议。"""

    name: str
    version: str

    def target_weights(self, context: StrategyContext) -> list[TargetWeight] | None:
        """返回目标权重。

        - None：本日无意见，引擎不生成订单，维持现有仓位
        - []：明确要求清空全部持仓
        - 非空列表：未列出的代码按 0 权重处理
        """
        ...
