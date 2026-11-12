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
    """单笔佣金 = max(成交金额 × 费率, 最低佣金)；成交金额为 0 时不计。

    这是「按笔」模型，仅在 min_commission_model="per_fill" 时直接使用。
    默认模型是 per_order，见 incremental_commission()。
    """
    if gross_amount <= 0:
        return 0.0
    return max(gross_amount * config.commission_rate, config.min_commission)


def order_commission(cumulative_gross: float, config: CostConfig) -> float:
    """按「委托订单累计成交金额」计算的应收佣金总额。

    本项目默认模型（min_commission_model="per_order"）：
        订单累计应收佣金 = max(累计成交金额 × 费率, 最低佣金)
    同一 order_id 的多次分笔成交共用这一份额度。
    """
    if cumulative_gross <= 0:
        return 0.0
    return max(cumulative_gross * config.commission_rate, config.min_commission)


def incremental_commission(
    cumulative_gross: float,
    already_charged: float,
    config: CostConfig,
    *,
    fill_gross: float,
    model: str | None = None,
) -> float:
    """本次成交应当新增收取的佣金。

    model:
      - "per_order"（默认）：按订单累计金额算应收总额，扣除已收部分
      - "per_fill"：每笔成交独立计算 max(金额×费率, 最低佣金)
    """
    resolved = model or getattr(config, "min_commission_model", "per_order")
    if resolved == "per_fill":
        return commission(fill_gross, config)
    if resolved != "per_order":
        raise ValueError(f"未知的 min_commission_model：{resolved}")
    due = order_commission(cumulative_gross, config)
    # 浮点误差保护：增量不为负
    return max(0.0, due - float(already_charged))


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


def sell_quantity(
    raw_quantity: float,
    available: int,
    lot_size: int,
    *,
    liquidate: bool = False,
) -> int:
    """卖单申报数量。

    两条规则必须分开判断，不能只看「是否超过 100 份」：

    - 全部清仓（liquidate=True）：申报全部可卖数量，整手与零股合并成**一笔**，
      零股不得单独拆单。这样 130400 份持仓在策略算出 130399.7 时也是
      「一次卖掉 130400」，不会残留 1 份。
    - 部分减仓（liquidate=False）：按整手向下取整；只有当可卖数量本身
      不足一手时，才允许整笔卖出该零股。

    任何分支都保证返回值 <= available。
    """
    if raw_quantity <= 0 or available <= 0:
        return 0
    if lot_size <= 0:
        raise ValueError("lot_size 必须为正")

    available = int(available)
    if liquidate:
        # 清仓：整手 + 零股合并申报，一次卖完
        return available

    want = int(math.floor(min(float(raw_quantity), available)))
    if want <= 0:
        return 0

    lots = int(want // lot_size) * lot_size
    if lots > 0:
        return lots
    # 可卖数量不足一手 → 整笔卖掉这份零股
    return min(want, available)
