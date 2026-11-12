"""模拟撮合：成交、拒单、延期、按整手缩减。

状态管理统一交给 Order.sync_status：
- 有成交就只能是 filled / partial；
- rejected / expired / cancelled / unfilled 只对「完全没有成交」的订单生效。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.backtest.config import BacktestConfig, InstrumentRule
from app.backtest.costs import (
    incremental_commission,
    round_lot,
    sell_quantity,
    slippage_cost,
    taxes,
)
from app.backtest.execution import Quote, available_date, fill_price
from app.backtest.models import Order, Trade
from app.backtest.portfolio import Portfolio


def append_reason(current: str | None, suffix: str) -> str:
    """在既有原因后追加分段标记，已存在时不重复追加。"""
    if not current:
        return suffix
    if suffix in current.split(';'):
        return current
    return current + ';' + suffix


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

    def _max_affordable(
        self,
        portfolio: Portfolio,
        price: float,
        rule: InstrumentRule,
        order: Order | None = None,
    ) -> int:
        """按含佣金后的现金上限反推最大可买股数，再按整手取整。

        佣金按订单累计模型计算：若该订单已有成交，本次只需补收
        「累计应收 - 已收」，不能用全额最低佣金重复判断，否则会低估可买量。
        """
        if price <= 0:
            return 0
        already_charged = float(order.fee) if order is not None else 0.0
        prior_gross = float(order.gross_amount) if order is not None else 0.0
        commission_rate = self.config.costs.commission_rate
        candidate = int(portfolio.cash // (price * (1 + commission_rate)))
        candidate = round_lot(candidate, rule.lot_size)
        while candidate > 0:
            gross = candidate * price
            fee = incremental_commission(
                prior_gross + gross,
                already_charged,
                self.config.costs,
                fill_gross=gross,
            )
            if gross + fee <= portfolio.cash + 1e-6:
                return candidate
            candidate -= rule.lot_size
        return 0

    def _defer(self, order: Order, reason: str) -> FillResult:
        """不可成交：延期一次，状态不因延期而倒退。"""
        order.deferred_days += 1
        order.reason = append_reason(order.reason, reason) if order.has_fill else reason
        order.sync_status()
        return FillResult(filled=False, order=order, reason=reason, deferred=True)

    def _terminate(self, order: Order, reason: str, terminal: str) -> FillResult:
        """终态：只有完全未成交时才落到 terminal，已有成交一律保留 partial。"""
        order.reason = append_reason(order.reason, reason) if order.has_fill else reason
        order.sync_status(terminal=terminal)
        return FillResult(filled=False, order=order, reason=reason)

    def execute(
        self,
        order: Order,
        quote: Quote,
        rule: InstrumentRule,
        portfolio: Portfolio,
        trade_date: date,
    ) -> FillResult:
        """尝试撮合一笔订单。

        优先级：已完成检查 → 可交易性 → 涨跌停 → 数量规则 → 资金/持仓约束 → 成交。
        任何一步不满足都不虚构成交，只记录原因并延期或进入终态。
        """
        # 0) 已完成订单禁止重复撮合：不新增成交、不改数量、不重复收费
        if order.remaining_quantity <= 0:
            order.sync_status()
            return FillResult(filled=False, order=order, reason='already_fully_filled')

        # 1) 可交易性
        ok, reason = quote.tradable()
        if not ok:
            return self._defer(order, reason)

        price, blocked = fill_price(quote, order.side, rule, self.config)
        if blocked:
            return self._defer(order, blocked)

        # 2) 数量：只对「剩余未成交数量」撮合，绝不重复成交已成交部分
        remaining = order.remaining_quantity
        quantity = remaining
        if order.side == 'buy':
            want = round_lot(remaining, rule.lot_size)
            if want <= 0:
                return self._terminate(order, 'zero_quantity', 'rejected')
            affordable = self._max_affordable(portfolio, price, rule, order)
            if affordable < want:
                if self.config.cash_shortfall_policy == 'reject' or affordable <= 0:
                    return self._terminate(order, 'insufficient_cash', 'rejected')
                quantity = affordable
                order.reason = append_reason(order.reason, 'reduced_by_cash')
            else:
                quantity = want
        else:
            available = portfolio.available(order.code, trade_date)
            if available <= 0:
                return self._terminate(order, 'no_available_position', 'rejected')
            # 卖出：可卖量不足时，按配置决定「部分成交」还是「整单拒绝」
            if remaining > available and not self.config.allow_partial_fill:
                return self._terminate(order, 'insufficient_position', 'rejected')
            # 卖出：清仓单整手+零股合并申报；部分减仓按整手
            quantity = sell_quantity(
                min(remaining, available), available, rule.lot_size,
                liquidate=bool(order.liquidate),
            )
            if quantity <= 0:
                return self._terminate(order, 'insufficient_position', 'rejected')
            if quantity < remaining:
                order.reason = append_reason(order.reason, 'partial_by_available')

        # 3) 兜底夹紧：累计成交永不超过原始委托量，且不出现负数
        quantity = min(int(quantity), order.remaining_quantity)
        if quantity <= 0:
            return self._terminate(order, 'zero_quantity', 'rejected')

        gross = quantity * price
        # 佣金按订单累计模型计算：同一 order_id 的多次成交共用最低佣金额度
        cumulative_gross = float(order.gross_amount) + gross
        fee = incremental_commission(
            cumulative_gross,
            order.fee,
            self.config.costs,
            fill_gross=gross,
        )
        stamp, transfer = taxes(gross, self.config.costs)
        fee += stamp + transfer
        reference = quote.open if self.config.execution_price == 'open' else quote.close
        slip = slippage_cost(reference, price, quantity, order.side)

        # 卖出净收入不足以覆盖费用且现金不够补差时，不制造负现金：
        # 这是「卖出收入 < 最低佣金」的病态碎股情形，按拒单处理并记录原因，
        # 而不是让账本抛异常中断整个回测。
        if order.side == 'sell':
            net_proceeds = gross - fee
            if net_proceeds < 0 and portfolio.cash + net_proceeds < -1e-6:
                return self._terminate(
                    order, 'sell_proceeds_below_fee', 'rejected'
                )

        if order.side == 'buy':
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
        order.gross_amount += gross
        order.fee += fee
        order.slippage_cost += slip
        # 只有累计成交量达到原始委托量才算 filled，否则严格保留 partial
        order.sync_status()
        if order.status == 'partial':
            order.reason = order.reason or 'partially_filled'
        return FillResult(filled=True, order=order, trade=trade)
