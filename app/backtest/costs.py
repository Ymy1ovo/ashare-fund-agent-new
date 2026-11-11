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


def sell_quantity(raw_quantity: float, available: int, lot_size: int) -> int:
    """卖单申报数量：整手优先，清仓时才允许一次性卖出剩余碎股。

    ETF 规则：
    - 卖出通常以整手（默认 100 份）为申报单位；
    - 若账户持仓不足整手（除权、送股、此前部分成交留下的零股），
      允许一次性全部卖出，不留零股。

    因此这里只在「可卖数量本身就是最终可卖全部」时才允许非整手，
    避免策略每次算出 130399.7 就申报 130399、留 1 股碎股。
    """
    if raw_quantity <= 0 or available <= 0:
        return 0
    if lot_size <= 0:
        raise ValueError("lot_size 必须为正")

    want = int(math.floor(min(raw_quantity, available)))
    if want <= 0:
        return 0

    lots = int(want // lot_size) * lot_size
    if lots > 0:
        # 整手部分足够 → 按整手申报
        return lots
    # 可卖数量不足一手 → 只能整笔卖出剩余零股
    return min(want, available)
