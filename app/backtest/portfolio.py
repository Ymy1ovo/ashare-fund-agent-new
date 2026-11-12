"""组合与资金账本：现金、FIFO 持仓、已实现盈亏、每日估值。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.backtest.models import DailySnapshot, Lot, Position


class PortfolioError(RuntimeError):
    """账本不变量被破坏。"""


@dataclass
class Portfolio:
    """一张完整的资金与持仓账本。

    不变量：
    - cash >= -1e-6（不允许透支）
    - 持仓数量不出现负值
    - total_assets == cash + market_value
    - 累计已付费用 == 各笔成交费用之和
    """

    initial_cash: float
    cash: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)
    realized_pnl: float = 0.0
    total_fees: float = 0.0
    total_slippage: float = 0.0
    trade_count: int = 0
    closed_trade_pnls: list[float] = field(default_factory=list)
    closed_holding_days: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.cash == 0.0:
            self.cash = float(self.initial_cash)
        if self.cash < -1e-6:
            raise PortfolioError("初始现金不能为负")

    # ---------- 查询 ----------
    def position(self, code: str) -> Position:
        return self.positions.setdefault(code, Position(code=code))

    def quantity(self, code: str) -> int:
        return self.positions.get(code, Position(code=code)).quantity

    def available(self, code: str, on_date: date) -> int:
        return self.positions.get(code, Position(code=code)).available(on_date)

    def market_value(self, prices: dict[str, float]) -> float:
        total = 0.0
        for code, position in self.positions.items():
            quantity = position.quantity
            if quantity <= 0:
                continue
            price = prices.get(code)
            if price is None:
                raise PortfolioError(f"{code} 缺少估值价格")
            total += quantity * price
        return total

    def total_assets(self, prices: dict[str, float]) -> float:
        return self.cash + self.market_value(prices)

    def cost_basis(self, code: str) -> float:
        position = self.positions.get(code)
        if not position:
            return 0.0
        return sum(lot.quantity * lot.cost_basis for lot in position.lots)

    def unrealized_pnl(self, code: str, price: float) -> float:
        position = self.positions.get(code)
        if not position or position.quantity == 0:
            return 0.0
        return position.quantity * price - self.cost_basis(code)

    # ---------- 交易 ----------
    def apply_buy(
        self,
        code: str,
        quantity: int,
        price: float,
        fee: float,
        trade_date: date,
        available_date: date,
        slippage_cost: float = 0.0,
    ) -> None:
        if quantity <= 0:
            raise PortfolioError("买入数量必须为正")
        gross = quantity * price
        total = gross + fee
        if total > self.cash + 1e-6:
            raise PortfolioError(
                f"现金不足：需要 {total:.2f}，可用 {self.cash:.2f}"
            )
        self.cash -= total
        fee_per_share = fee / quantity if quantity else 0.0
        self.position(code).add(
            Lot(
                trade_date=trade_date,
                quantity=quantity,
                price=price,
                fee_per_share=fee_per_share,
                available_date=available_date,
            )
        )
        self.total_fees += fee
        self.total_slippage += slippage_cost
        self.trade_count += 1
        self._assert_sane()

    def apply_sell(
        self,
        code: str,
        quantity: int,
        price: float,
        fee: float,
        trade_date: date,
        slippage_cost: float = 0.0,
    ) -> float:
        """卖出并返回已实现盈亏（已扣双边费用影响）。"""
        if quantity <= 0:
            raise PortfolioError("卖出数量必须为正")
        position = self.positions.get(code)
        if position is None:
            raise PortfolioError(f"没有 {code} 持仓，不能卖出")
        if quantity > position.available(trade_date):
            raise PortfolioError(
                f"{code} 可卖 {position.available(trade_date)} 股，不足 {quantity} 股"
            )
        consumed = position.consume(quantity, trade_date)
        gross = quantity * price
        cost = sum(take * lot.cost_basis for lot, take in consumed)
        realized = gross - cost - fee
        self.cash += gross - fee
        self.realized_pnl += realized
        self.total_fees += fee
        self.total_slippage += slippage_cost
        self.trade_count += 1
        self.closed_trade_pnls.append(realized)
        for lot, take in consumed:
            self.closed_holding_days.append(max(0, (trade_date - lot.trade_date).days))
        if position.quantity == 0:
            self.positions.pop(code, None)
        self._assert_sane()
        return realized

    # ---------- 公司行为 ----------
    def apply_corporate_action(
        self,
        code: str,
        new_quantity: int,
        cash_delta: float,
    ) -> None:
        """按事件调整持仓数量与现金。

        只在 Engine 已经算好目标数量与现金增量后调用；
        本方法不判断事件合法性（由 corporate_actions 负责），只保证：
        - 数量按比例缩放后，各批次同步缩放，成本基准随之反比调整，
          使「持仓成本总额」在事件前后保持不变（经济价值连续）；
        - 现金增量直接入账；
        - 账本不变量在之后仍成立。
        """
        if new_quantity < 0:
            raise PortfolioError(f"{code} 调整后数量不能为负：{new_quantity}")
        position = self.positions.get(code)
        if position is None:
            if cash_delta:
                self.cash += cash_delta
            self._assert_sane()
            return
        old_quantity = position.quantity
        if old_quantity <= 0:
            if position.quantity == 0:
                self.positions.pop(code, None)
            if cash_delta:
                self.cash += cash_delta
            self._assert_sane()
            return
        if new_quantity > 0:
            ratio = new_quantity / old_quantity
            for lot in position.lots:
                lot.quantity = int(round(lot.quantity * ratio))
                if lot.price > 0:
                    # 价格反比调整，保证 cost_basis × quantity 守恒
                    lot.price = lot.price / ratio
            # 舍入可能让批次总数与新数量有 1~2 份差异，用最后一笔补齐
            diff = new_quantity - position.quantity
            if diff and position.lots:
                position.lots[-1].quantity += diff
            position.lots = [lot for lot in position.lots if lot.quantity > 0]
        else:
            self.positions.pop(code, None)
        if cash_delta:
            self.cash += cash_delta
        self._assert_sane()

    def _assert_sane(self) -> None:
        if self.cash < -1e-6:
            raise PortfolioError(f"现金为负：{self.cash:.2f}")
        for code, position in self.positions.items():
            if position.quantity < 0:
                raise PortfolioError(f"{code} 持仓为负：{position.quantity}")
        if self.total_fees < -1e-9:
            raise PortfolioError("累计费用为负")

    # ---------- 每日快照 ----------
    def snapshot(
        self,
        trade_date: date,
        prices: dict[str, float],
        nav_base: float,
        previous_nav: float | None,
        price_status: dict[str, str] | None = None,
    ) -> DailySnapshot:
        market_value = self.market_value(prices)
        total = self.cash + market_value
        nav = total / nav_base if nav_base else 0.0
        daily_return = None if previous_nav in (None, 0) else nav / previous_nav - 1
        return DailySnapshot(
            trade_date=trade_date,
            cash=self.cash,
            market_value=market_value,
            total_assets=total,
            nav=nav,
            daily_return=daily_return,
            positions={
                code: position.quantity
                for code, position in self.positions.items()
                if position.quantity > 0
            },
            prices=prices,
            price_status=price_status or {},
            fees_paid_cumulative=self.total_fees,
        )
