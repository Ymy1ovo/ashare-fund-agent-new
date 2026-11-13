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
    # 阶段3A.3.2.1：已确认但尚未到账的现金分红（应收，不计入可用现金）
    receivables: list[dict] = field(default_factory=list)

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
        """总资产 = 可用现金 + 持仓市值 + 已确认应收分红。

        应收分红在除息日即计入总资产（经济权益已确定），
        但不能用于下单，因此不计入 cash。
        """
        return self.cash + self.market_value(prices) + self.dividend_receivable

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
        本方法只保证账本自洽，不判断事件合法性（由 corporate_actions 负责）：

        1. 各批次按比例缩放后，用「最大余数法」分配舍入误差，
           保证 `sum(lot.quantity) == position.quantity == new_quantity`；
        2. 每批次成本基准按 1/比例 反比调整，使成本总额在事件前后守恒；
        3. 可卖日期（`available_date`）保持不变，份额调整不得把 T+1 变成 T+0；
        4. 现金增量直接入账，负数会触发现金为负的不变量检查。
        """
        if new_quantity < 0:
            raise PortfolioError(f"{code} 调整后数量不能为负：{new_quantity}")
        position = self.positions.get(code)
        if position is None or position.quantity <= 0:
            self.positions.pop(code, None)
            if cash_delta:
                self.cash += cash_delta
            self._assert_sane()
            return

        old_quantity = position.quantity
        if new_quantity <= 0:
            self.positions.pop(code, None)
            if cash_delta:
                self.cash += cash_delta
            self._assert_sane()
            return

        ratio = new_quantity / old_quantity
        lots = position.lots
        # 1) 逐批取整，记录余数
        scaled = [lot.quantity * ratio for lot in lots]
        floors = [int(value // 1) for value in scaled]
        remainders = [value - floor for value, floor in zip(scaled, floors)]
        shortfall = new_quantity - sum(floors)
        # 2) 最大余数法补齐：按小数部分从大到小依次 +1
        order = sorted(range(len(lots)), key=lambda i: remainders[i], reverse=True)
        index = 0
        while shortfall > 0 and order:
            floors[order[index % len(order)]] += 1
            shortfall -= 1
            index += 1
        while shortfall < 0:
            # 极少数情况下取整会超出，从余数最小的批次扣回
            for i in reversed(order):
                if floors[i] > 0:
                    floors[i] -= 1
                    shortfall += 1
                    break
            else:
                break

        for lot, quantity in zip(lots, floors):
            lot.quantity = quantity
            if lot.price > 0:
                # 成本基准守恒：数量 ×N 则单价 ÷N
                lot.price = lot.price / ratio
        position.lots = [lot for lot in lots if lot.quantity > 0]
        if cash_delta:
            self.cash += cash_delta
        # 3) 强制不变量：批次总和必须等于目标数量
        actual = position.quantity
        if actual != new_quantity:
            raise PortfolioError(
                f"{code} 份额调整后批次之和 {actual} != 目标 {new_quantity}"
            )
        self._assert_sane()

    # ---------- 现金分红应收 / 到账 ----------
    def confirm_dividend_receivable(
        self,
        code: str,
        amount: float,
        *,
        action_id: int = 0,
        ex_date: date | None = None,
        pay_date: date | None = None,
        record_date: date | None = None,
        shares: int = 0,
    ) -> None:
        """在除息日确认一笔应收分红：经济权益已确定，但现金不可交易。"""
        if amount < 0:
            raise PortfolioError(f"{code} 应收分红为负：{amount}")
        if amount == 0:
            return
        self.receivables.append({
            "action_id": action_id,
            "code": code,
            "amount": amount,
            "record_date": record_date,
            "ex_date": ex_date,
            "pay_date": pay_date,
            "shares": shares,
        })
        self._assert_sane()

    def settle_dividend_receivable(self, on_date: date) -> list[dict]:
        """在发放日把已到期应收分红转入可用现金，返回本次结转明细。"""
        settled: list[dict] = []
        remaining: list[dict] = []
        for item in self.receivables:
            pay = item.get("pay_date")
            if pay is not None and pay <= on_date:
                self.cash += float(item["amount"])
                settled.append({**item, "settled_on": on_date})
            else:
                remaining.append(item)
        self.receivables = remaining
        if settled:
            self._assert_sane()
        return settled

    @property
    def dividend_receivable(self) -> float:
        """当前未到账的应收分红合计。"""
        return sum(float(item["amount"]) for item in self.receivables)

    def receivable_of(self, action_id: int) -> float:
        return sum(float(item["amount"]) for item in self.receivables
                   if int(item.get("action_id") or 0) == action_id)

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
        receivable = self.dividend_receivable
        total = self.cash + market_value + receivable
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
            dividend_receivable=receivable,
        )
