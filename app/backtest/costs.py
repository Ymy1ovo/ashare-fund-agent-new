"""交易成本：佣金、最低佣金、滑点、税费。

所有参数来自 CostConfig，不在此处硬编码业务数值。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from app.backtest.config import CostConfig


@dataclass(frozen=True)
class CostBreakdown:
    """单笔成交的成本拆解。"""

    commission: float
    stamp_duty: float
    transfer_fee: float
    slippage_cost: float

    @property
    def total_fee(self) -> float:
        return self.commission + self.stamp_duty + self.transfer_fee

    @property
    def total_cost(self) -> float:
        return self.total_fee + self.slippage_cost


def commission(gross_amount: float, config: CostConfig) -> float:
    """佣金 = max(成交金额 × 费率, 最低佣金)；成交金额为 0 时不计。"""
    if gross_amount <= 0:
        return 0.0
    return max(gross_amount * config.commission_rate, config.min_commission)


def slippage_price(base_price: float, side: str, config: CostConfig) -> float:
    """滑点后成交价。

    买入抬价、卖出压价；比例滑点与固定滑点互斥（由 CostConfig.validate 保证）。
    """
    if base_price <= 0:
        raise ValueError("基准价必须为正")
    if side not in ("buy", "sell"):
        raise ValueError("side 只能是 buy 或 sell")
    if config.slippage_fixed > 0:
        delta = config.slippage_fixed
    elif config.slippage_bps > 0:
        delta = base_price * config.slippage_bps / 10000.0
    else:
        delta = 0.0
    return base_price + delta if side == "buy" else base_price - delta


def slippage_cost(base_price: float, filled_price: float, quantity: int, side: str) -> float:
    """滑点造成的额外成本（正数）。"""
    if quantity <= 0:
        return 0.0
    diff = (filled_price - base_price) if side == "buy" else (base_price - filled_price)
    return abs(diff) * quantity


def taxes(gross_amount: float, config: CostConfig) -> tuple[float, float]:
    """印花税与过户费。ETF 默认两者为 0，保留可配置能力。"""
    if gross_amount <= 0:
        return 0.0, 0.0
    return (
        gross_amount * config.stamp_duty_rate,
        gross_amount * config.transfer_fee_rate,
    )


def total_cost(gross_amount: float, config: CostConfig) -> CostBreakdown:
    """仅用于估算的完整成本拆解（滑点按 0 计，实际滑点在成交时计算）。"""
    stamp, transfer = taxes(gross_amount, config)
    return CostBreakdown(
        commission=commission(gross_amount, config),
        stamp_duty=stamp,
        transfer_fee=transfer,
        slippage_cost=0.0,
    )


def round_lot(quantity: float, lot_size: int, allow_odd: bool = False) -> int:
    """按最小交易单位向下取整。allow_odd=True 时允许零股（卖出清仓场景可放宽）。"""
    if quantity <= 0:
        return 0
    if lot_size <= 0:
        raise ValueError("lot_size 必须为正")
    if allow_odd:
        return int(math.floor(quantity))
    return int(math.floor(quantity / lot_size) * lot_size)
