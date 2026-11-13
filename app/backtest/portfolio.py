"""组合与资金账本：现金、FIFO 持仓、已实现盈亏、每日估值。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.backtest.models import DailySnapshot, Lot, Position


# 份额比例允许的浮点误差；小于该值视为无零碎份额
RATIO_EPS = 1e-9


def position_cost_basis(position: Position) -> float:
    """一个持仓的总成本基准（各批次数量 × 批次单位成本）。"""
    return sum(lot.quantity * lot.cost_basis for lot in position.lots)


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
    # 阶段3A.3.2.2：公司行为产生的已实现盈亏（与成交平仓分开记录）
    corporate_action_realized: list[float] = field(default_factory=list)

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
        cash_delta: float = 0.0,
        *,
        official_ratio: float | None = None,
        compensation_price: float | None = None,
        fractional_policy: str = "truncate",
        action_id: int = 0,
        action_type: str = "",
    ) -> dict:
        """按事件调整持仓数量与现金，并返回本次调整的完整账本留痕。

        成本基准规则（阶段3A.3.2.2 修正）：

        1. **用官方折算比例** `official_ratio` 缩放份额，不用
           `new_quantity / old_quantity`。后者已被整数取整污染，
           用它折成本会把零碎份额的成本错误地摊到剩余份额上。
        2. 零碎份额按 `fractional_policy` 处置：
           - `cash_compensation`：按 `compensation_price` 现金补偿，
             对应成本基准从持仓中转出，差额计入已实现盈亏；
           - `truncate`：按公告「尾差计入基金财产」舍去，无现金，
             对应成本作为损失转出；
           - `round_up`：按公告「小数点后份额进位」补足，无现金，
             新增份额不增加成本（成本单价被动稀释）。
        3. 每个 FIFO lot 独立计算处置成本：批次内被处置份额占比 × 该批次成本，
           保证多批次场景下成本按各自单价转出。
        4. 事件不增加 `trade_count`、不写入 `closed_trade_pnls`：
           公司行为不是成交，必须与交易统计分离。
        5. 可卖日期 `available_date` 保持不变，T+1 不因份额调整提前。
        """
        result: dict = {
            "action_id": action_id,
            "action_type": action_type,
            "code": code,
            "fractional_policy": fractional_policy,
            "shares_before": 0,
            "shares_after": 0,
            "official_ratio": official_ratio,
            "ratio_source": "official" if official_ratio else "implied",
            "fractional_shares": 0.0,
            "compensation_cash": 0.0,
            "disposed_cost_basis": 0.0,
            "realized_pnl": 0.0,
            "cost_basis_before": 0.0,
            "cost_basis_after": 0.0,
            "compensation_price": compensation_price,
        }

        if new_quantity < 0:
            raise PortfolioError(f"{code} 调整后数量不能为负：{new_quantity}")

        position = self.positions.get(code)
        if position is None or position.quantity <= 0:
            self.positions.pop(code, None)
            if cash_delta:
                self.cash += cash_delta
            self._assert_sane()
            return result

        old_quantity = position.quantity
        result["shares_before"] = old_quantity
        result["cost_basis_before"] = position_cost_basis(position)

        if new_quantity <= 0:
            # 整个持仓被清零：全部成本转为处置成本
            disposed = result["cost_basis_before"]
            self.positions.pop(code, None)
            self.cash += cash_delta
            self.realized_pnl += cash_delta - disposed
            self.corporate_action_realized.append(cash_delta - disposed)
            result.update({
                "shares_after": 0,
                "compensation_cash": cash_delta,
                "disposed_cost_basis": disposed,
                "realized_pnl": cash_delta - disposed,
                "cost_basis_after": 0.0,
            })
            self._assert_sane()
            return result

        # ---- 1) 确定缩放比例与理论零碎份额 ----
        if official_ratio is not None and official_ratio > 0:
            ratio = float(official_ratio)
        else:
            # 未提供官方比例：退化为整数比例（等价于「没有零碎份额」）
            ratio = new_quantity / old_quantity
        raw_total = old_quantity * ratio
        expected_new = int(raw_total // 1)
        if fractional_policy == "round_up" and raw_total - expected_new > RATIO_EPS:
            expected_new = int(raw_total // 1) + 1
        if abs(new_quantity - expected_new) > 0:
            raise PortfolioError(
                f"{code} 目标份额 {new_quantity} 与官方比例 {ratio} 推算的 "
                f"{expected_new} 不一致（理论 {raw_total}）"
            )
        fractional_shares = abs(raw_total - expected_new)
        if fractional_policy == "round_up":
            # 进位补足不属于「零碎处置」，不记处置份额
            fractional_shares = 0.0

        # ---- 2) 逐批次按比例缩放 + 最大余数法分配整数份额 ----
        lots = position.lots
        scaled = [lot.quantity * ratio for lot in lots]
        floors = [int(value // 1) for value in scaled]
        if fractional_policy == "round_up":
            floors = [int(value // 1) + (1 if value - int(value // 1) > RATIO_EPS else 0)
                      for value in scaled]
        remainders = [value - base for value, base in
                      zip(scaled, [int(v // 1) for v in scaled])]
        shortfall = new_quantity - sum(floors)
        order = sorted(range(len(lots)), key=lambda i: remainders[i], reverse=True)
        index = 0
        while shortfall > 0 and order:
            floors[order[index % len(order)]] += 1
            shortfall -= 1
            index += 1
        while shortfall < 0:
            removed = False
            for i in reversed(order):
                if floors[i] > 0:
                    floors[i] -= 1
                    shortfall += 1
                    removed = True
                    break
            if not removed:
                break

        # ---- 3) 转出零碎份额对应成本 ----
        # 零碎份额是**组合层面**的经济事件，不是逐批次的记账差异：
        # 最大余数法把整数份额分配给不同批次，只是账本拆分方式，
        # 不代表某个批次多处置或少处置了份额。
        #
        # 因此按「整个持仓」计算应转出的成本，再按各批次成本占比分摊：
        #   total_disposed = 总成本 × (零碎份额 / 理论总份额)
        # round_up 口径下零碎份额由基金管理人补足，不转出任何成本。
        cost_before_total = sum(lot.quantity * lot.cost_basis for lot in lots)
        if fractional_policy == "round_up" or raw_total <= 0:
            disposed_total = 0.0
        else:
            disposed_total = cost_before_total * (fractional_shares / raw_total)

        for lot, allocated in zip(lots, floors):
            lot_cost_before = lot.quantity * lot.cost_basis
            if cost_before_total > 0:
                share = lot_cost_before / cost_before_total
            else:
                share = 0.0
            lot_remaining = lot_cost_before - disposed_total * share
            if allocated > 0:
                per_share_after = lot_remaining / allocated
                if lot.price > 0 and per_share_after > 0:
                    scale = per_share_after / lot.cost_basis
                    lot.price = lot.price * scale
                    lot.fee_per_share = lot.fee_per_share * scale
                else:
                    lot.price = per_share_after
                    lot.fee_per_share = 0.0
            lot.quantity = allocated
        position.lots = [lot for lot in lots if lot.quantity > 0]

        # ---- 4) 现金补偿、已实现盈亏与账本落账 ----
        compensation = float(cash_delta)
        realized = compensation - disposed_total
        self.cash += compensation
        self.realized_pnl += realized
        self.corporate_action_realized.append(realized)

        actual = position.quantity
        if actual != new_quantity:
            raise PortfolioError(
                f"{code} 份额调整后批次之和 {actual} != 目标 {new_quantity}"
            )
        result.update({
            "shares_after": actual,
            "fractional_shares": fractional_shares,
            "compensation_cash": compensation,
            "disposed_cost_basis": disposed_total,
            "realized_pnl": realized,
            "cost_basis_after": position_cost_basis(position),
        })
        self._assert_sane()
        return result

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
