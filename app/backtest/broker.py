"""模拟撮合：成交、拒单、延期、按整手缩减。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.backtest.config import BacktestConfig, InstrumentRule
from app.backtest.costs import commission, round_lot, slippage_cost, taxes
from app.backtest.execution import Quote, available_date, fill_price
from app.backtest.models import Order, Trade
from app.backtest.portfolio import Portfolio


@dataclass
class FillResult:
    """一次撮合尝试的结果。"""

    filled: bool
    order: Order
    trade: Trade | None = None
    reason: str | None = None
    deferred: bool = False


@dataclass
class Broker:
    """确定性撮合器；同一日订单顺序由调用方固定。

    default_factory=int 让 trade_id 从 1 开始递增，保证重复运行结果一致。
    """

    config: BacktestConfig
    calendar: list[date]
    _trade_seq: int = field(default=0)

    def next_trade_id(self) -> int:
        self._trade_seq += 1
        return self._trade_seq

    def _max_affordable(self, portfolio: Portfolio, price: float, rule: InstrumentRule) -> int:
        """按含佣金后的现金上限反推最大可买股数，再按整手取整。"""
        if price <= 0:
            return 0
        candidate = int(portfolio.cash // (price * (1 + self.config.costs.commission_rate)))
        candidate = round_lot(candidate, rule.lot_size)
        while candidate > 0:
            gross = candidate * price
            fee = commission(gross, self.config.costs)
            if gross + fee <= portfolio.cash + 1e-6:
                return candidate
            candidate -= rule.lot_size
        return 0

    def execute(
        self,
        order: Order,
        quote: Quote,
        rule: InstrumentRule,
        portfolio: Portfolio,
        trade_date: date,
    ) -> FillResult:
        """尝试撮合一笔订单。

        优先级：可交易性 → 涨跌停 → 数量规则 → 资金/持仓约束 → 成交。
        任何一步不满足都不虚构成交，只记录原因并延期或拒绝。
        """
        ok, reason = quote.tradable()
        if not ok:
            order.status = "pending"
            order.reason = reason
            order.deferred_days += 1
            return FillResult(filled=False, order=order, reason=reason, deferred=True)

        price, blocked = fill_price(quote, order.side, rule, self.config)
        if blocked:
            order.status = "pending"
            order.reason = blocked
            order.deferred_days += 1
            return FillResult(filled=False, order=order, reason=blocked, deferred=True)

        quantity = int(order.quantity)
        if order.side == "buy":
            want = round_lot(quantity, rule.lot_size)
            affordable = self._max_affordable(portfolio, price, rule)
            if affordable < want:
                if self.config.cash_shortfall_policy == "reject" or affordable <= 0:
                    order.status = "rejected"
                    order.reason = "insufficient_cash"
                    return FillResult(filled=False, order=order, reason="insufficient_cash")
                want = affordable
                order.reason = "reduced_by_cash"
            quantity = want
        else:
            available = portfolio.available(order.code, trade_date)
            if available <= 0:
                order.status = "rejected"
                order.reason = "no_available_position"
                return FillResult(filled=False, order=order, reason="no_available_position")
            # 卖出：可卖量不足时，按配置决定「部分成交」还是「整单拒绝」
            if quantity > available and not self.config.allow_partial_fill:
                order.status = "rejected"
                order.reason = "insufficient_position"
                return FillResult(filled=False, order=order, reason="insufficient_position")
            capped = min(quantity, available)
            quantity = round_lot(capped, rule.lot_size, allow_odd=True)
            if quantity <= 0:
                order.status = "rejected"
                order.reason = "insufficient_position"
                return FillResult(filled=False, order=order, reason="insufficient_position")
            if quantity < int(order.quantity):
                order.reason = order.reason or "partial_by_available"

        # 累计成交数量不得超过原始订单数量：在动账本之前先夹紧
        remaining_before = int(order.quantity) - int(order.filled_quantity)
        if remaining_before <= 0:
            order.status = "filled"
            order.reason = "already_fully_filled"
            return FillResult(filled=False, order=order, reason="already_fully_filled")
        if quantity > remaining_before:
            quantity = remaining_before
        if quantity <= 0:
            order.status = "rejected"
            order.reason = order.reason or "zero_quantity"
            return FillResult(filled=False, order=order, reason=order.reason)

        gross = quantity * price
        fee = commission(gross, self.config.costs)
        stamp, transfer = taxes(gross, self.config.costs)
        fee += stamp + transfer
        reference = quote.open if self.config.execution_price == "open" else quote.close
        slip = slippage_cost(reference, price, quantity, order.side)

        if order.side == "buy":
            portfolio.apply_buy(
                code=order.code,
                quantity=quantity,
                price=price,
                fee=fee,
                trade_date=trade_date,
                available_date=available_date(trade_date, rule, self.calendar),
                slippage_cost=slip,
            )
            realized = 0.0
            holding_days = 0.0
        else:
            realized = portfolio.apply_sell(
                code=order.code,
                quantity=quantity,
                price=price,
                fee=fee,
                trade_date=trade_date,
                slippage_cost=slip,
            )
            holding_days = (
                portfolio.closed_holding_days[-1] if portfolio.closed_holding_days else 0.0
            )

        trade = Trade(
            trade_id=self.next_trade_id(),
            order_id=order.order_id,
            code=order.code,
            side=order.side,
            trade_date=trade_date,
            quantity=quantity,
            price=price,
            gross_amount=gross,
            commission=fee,
            slippage_cost=slip,
            realized_pnl=realized,
            holding_days=holding_days,
            cash_after=portfolio.cash,
            reason=order.reason,
        )
        order.filled_quantity += quantity
        order.fill_date = trade_date
        order.fill_price = price
        order.fee += fee
        order.slippage_cost += slip
        # 只有「累计成交量 == 原始订单量」才算完全成交；否则严格保留 partial
        order.status = "filled" if order.filled_quantity >= int(order.quantity) else "partial"
        if order.status == "partial":
            order.reason = order.reason or "partially_filled"
        return FillResult(filled=True, order=order, trade=trade)
