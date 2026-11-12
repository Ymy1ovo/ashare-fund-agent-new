"""订单、成交、持仓与账本数据模型。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Literal

Side = Literal["buy", "sell"]
OrderStatus = Literal[
    "pending", "filled", "partial", "rejected", "expired", "cancelled", "unfilled"
]


@dataclass
class Order:
    """一条订单。

    signal_date: 生成信号的交易日（最晚可使用该日收盘数据）
    order_date:  实际提交订单的交易日
    target_weight: 目标权重（0-1），用于调仓订单
    """

    order_id: int
    code: str
    side: Side
    signal_date: date
    order_date: date
    quantity: int
    target_weight: float | None = None
    reference_price: float | None = None
    status: OrderStatus = "pending"
    filled_quantity: int = 0
    fill_date: date | None = None
    fill_price: float | None = None
    fee: float = 0.0
    slippage_cost: float = 0.0
    gross_amount: float = 0.0
    reason: str | None = None
    deferred_days: int = 0
    seq: int = 0
    strategy: str | None = None
    # 是否整笔清仓：为 True 时整手与零股合并成一笔申报，不拆零股
    liquidate: bool = False

    @property
    def remaining_quantity(self) -> int:
        """未成交剩余数量，永不为负。"""
        return max(0, int(self.quantity) - int(self.filled_quantity))

    @property
    def has_fill(self) -> bool:
        """是否已经产生过真实成交。"""
        return int(self.filled_quantity) > 0

    @property
    def filled_gross_amount(self) -> float:
        """订单累计成交金额（用于按订单计算佣金）。"""
        return float(self.gross_amount)

    @property
    def remaining_quantity_after_liquidation(self) -> int:
        """清仓意图下应为 0；仅用于测试断言可读性。"""
        return self.remaining_quantity

    def sync_status(self, terminal: str | None = None) -> str:
        """按统一规则收敛订单状态，Engine 与 Broker 共用。

        - 累计成交量达到原始委托量 → filled
        - 已有成交但未满 → 永远 partial（终态原因写进 reason，不覆盖状态）
        - 完全没有成交 → 才允许 pending / rejected / expired / cancelled / unfilled
        """
        quantity = int(self.quantity)
        filled = int(self.filled_quantity)
        if filled >= quantity:
            self.status = "filled"
        elif filled > 0:
            self.status = "partial"
        elif terminal:
            self.status = terminal
        return self.status

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["remaining_quantity"] = self.remaining_quantity
        for key in ("signal_date", "order_date", "fill_date"):
            value = payload.get(key)
            if isinstance(value, date):
                payload[key] = value.isoformat()
        return payload


@dataclass
class Trade:
    """成交明细。"""

    trade_id: int
    order_id: int
    code: str
    side: Side
    trade_date: date
    quantity: int
    price: float
    gross_amount: float
    commission: float
    slippage_cost: float
    realized_pnl: float = 0.0
    holding_days: float = 0.0
    cash_after: float = 0.0
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["trade_date"] = self.trade_date.isoformat()
        return payload


@dataclass
class Lot:
    """FIFO 买入批次。"""

    trade_date: date
    quantity: int
    price: float
    fee_per_share: float
    available_date: date

    @property
    def cost_basis(self) -> float:
        return self.price + self.fee_per_share


@dataclass
class Position:
    """单只 ETF 持仓。"""

    code: str
    lots: list[Lot] = field(default_factory=list)

    @property
    def quantity(self) -> int:
        return sum(lot.quantity for lot in self.lots)

    def available(self, on_date: date) -> int:
        return sum(lot.quantity for lot in self.lots if lot.available_date <= on_date)

    def add(self, lot: Lot) -> None:
        self.lots.append(lot)

    def consume(self, quantity: int, on_date: date) -> list[tuple[Lot, int]]:
        """按 FIFO 消耗可用份额，返回 (批次, 数量)。"""
        if quantity <= 0:
            raise ValueError("卖出数量必须为正")
        if quantity > self.available(on_date):
            raise ValueError("可卖份额不足")
        remaining = quantity
        consumed: list[tuple[Lot, int]] = []
        for lot in self.lots:
            if remaining <= 0:
                break
            if lot.available_date > on_date or lot.quantity <= 0:
                continue
            take = min(lot.quantity, remaining)
            lot.quantity -= take
            remaining -= take
            consumed.append((lot, take))
        self.lots = [lot for lot in self.lots if lot.quantity > 0]
        return consumed


@dataclass
class DailySnapshot:
    """每日账户快照。"""

    trade_date: date
    cash: float
    market_value: float
    total_assets: float
    nav: float
    daily_return: float | None = None
    positions: dict[str, int] = field(default_factory=dict)
    prices: dict[str, float] = field(default_factory=dict)
    price_status: dict[str, str] = field(default_factory=dict)
    fees_paid_cumulative: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "trade_date": self.trade_date.isoformat(),
            "cash": self.cash,
            "market_value": self.market_value,
            "total_assets": self.total_assets,
            "nav": self.nav,
            "daily_return": self.daily_return,
            "positions": self.positions,
            "prices": self.prices,
            "price_status": self.price_status,
            "fees_paid_cumulative": self.fees_paid_cumulative,
        }
