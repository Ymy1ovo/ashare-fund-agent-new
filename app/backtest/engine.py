"""回测主引擎：信号 → 目标权重 → 订单 → 撮合 → 账本 → 每日净值。"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd

from app.backtest.broker import Broker, FillResult, append_reason
from app.backtest.config import BacktestConfig, InstrumentRule, rule_for
from app.backtest.costs import round_lot, sell_quantity
from app.backtest.data import BarData, load_bars, load_calendar, load_pool
from app.backtest.execution import Quote
from app.backtest.models import DailySnapshot, Order, Trade
from app.backtest.portfolio import Portfolio
from app.backtest.strategies.base import Strategy, StrategyContext, TargetWeight


class BacktestError(RuntimeError):
    """回测无法继续。"""


@dataclass
class BacktestResult:
    """一次回测的完整产出。"""

    run_id: str
    config: BacktestConfig
    strategy_name: str
    strategy_version: str
    codes: list[str]
    indicator_version: str | None
    snapshot_ids: dict[str, int]
    rules: dict[str, InstrumentRule]
    daily: list[DailySnapshot]
    orders: list[Order]
    trades: list[Trade]
    initial_cash: float
    input_hash: str
    notes: list[str] = field(default_factory=list)

    def nav_series(self) -> pd.Series:
        if not self.daily:
            return pd.Series(dtype=float)
        index = pd.DatetimeIndex([pd.Timestamp(item.trade_date) for item in self.daily])
        return pd.Series([item.nav for item in self.daily], index=index, name="nav")

    def as_meta(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "strategy_name": self.strategy_name,
            "strategy_version": self.strategy_version,
            "codes": self.codes,
            "indicator_version": self.indicator_version,
            "snapshot_ids": self.snapshot_ids,
            "initial_cash": self.initial_cash,
            "input_hash": self.input_hash,
            "start_date": self.config.start_date,
            "end_date": self.config.end_date,
            "execution_price": self.config.execution_price,
            "notes": self.notes,
        }


def _input_hash(
    config: BacktestConfig,
    strategy: Strategy,
    codes: list[str],
    indicator_version: str | None,
    snapshot_ids: dict[str, int],
    data_hash: str,
    *,
    corporate_action_version: str | None = None,
    corporate_action_digest: str | None = None,
) -> str:
    """输入哈希：参数 + 策略 + ETF池 + 指标版本 + 快照 + 行情指纹 + 公司行为。

    公司行为部分同时纳入：
    - 口径版本号（`ca-v1`/`ca-v2` 这类，标记会计规则）；
    - **本次实际参与的事件数据 SHA256**（标记数据内容）。
    因此即使版本号不变，只要事件内容变化，input_hash 必然变化。
    """
    payload = {
        "config": config.as_dict(),
        "strategy": [strategy.name, strategy.version],
        "codes": sorted(codes),
        "indicator_version": indicator_version,
        "snapshot_ids": dict(sorted(snapshot_ids.items())),
        "data": data_hash,
        "corporate_action_version": (
            corporate_action_version if config.apply_corporate_actions else "disabled"
        ),
        "corporate_action_digest": (
            corporate_action_digest if config.apply_corporate_actions else "disabled"
        ),
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _frame_hash(bars: dict[str, BarData]) -> str:
    digest = hashlib.sha256()
    for code in sorted(bars):
        frame = bars[code].frame
        digest.update(code.encode("utf-8"))
        for trade_date, row in frame.iterrows():
            payload = [
                str(trade_date),
                row.get("open"), row.get("high"), row.get("low"),
                row.get("close"), row.get("volume"),
            ]
            digest.update(json.dumps(payload, default=str).encode("utf-8"))
    return digest.hexdigest()[:16]


class BacktestEngine:
    """严格 T+1 的回测引擎。

    每个交易日：
    1. 开盘：撮合早于当日挂起的订单（signal_date < 当日）
    2. 收盘：按原始收盘价估值，写入每日快照
    3. 收盘后：用截至当日的数据生成下一批订单（signal_date = 当日）
    """

    def __init__(
        self,
        config: BacktestConfig,
        strategy: Strategy,
        *,
        db_path=None,
        calendar: list[date] | None = None,
    ) -> None:
        config.validate()
        self.config = config
        self.strategy = strategy
        self.db_path = db_path
        self.calendar = calendar or load_calendar(
            config.start_date, config.end_date, db_path=db_path
        )
        if not self.calendar:
            raise BacktestError("回测区间内没有交易日")
        self.notes: list[str] = []
        # 阶段3A.3.2：公司行为应用日志与 run_id（run 开始时写入）
        self.corporate_action_log: list[dict] = []
        # 本次回测实际参与的事件数据指纹（未参与的事件不影响它）
        self.corporate_action_digest: str | None = None
        self.dividend_settlements: list[dict] = []
        self._pending_receivable: dict[int, float] = {}
        self.excluded_actions: list[dict] = []
        # 阶段3A.3.2.2：份额调整的完整账本留痕（成本转出 / 已实现盈亏）
        self.corporate_action_ledger: list[dict] = []
        # 权益登记日锁定的分红份额（action_id -> 份额）
        self._dividend_locked_shares: dict[int, int] = {}
        self._run_id_for_actions: str | None = None

    def _load_corporate_actions(self, codes: list[str]) -> list:
        """加载区间内已确认的公司行为事件；未确认事件不参与回测。

        只读：不写数据库、不修改事件本身。
        """
        if not getattr(self.config, "apply_corporate_actions", True):
            self.notes.append("公司行为：配置显式关闭（apply_corporate_actions=False）")
            return []
        from app.backtest.corporate_actions import load_actions

        try:
            actions = load_actions(
                start=self.config.start_date,
                end=self.config.end_date,
                codes=list(codes),
                db_path=self.db_path,
            )
        except Exception as exc:  # noqa: BLE001 事件表缺失时不应阻断回测
            self.notes.append(f"公司行为：事件表不可用（{type(exc).__name__}），按旧口径回测")
            return []
        confirmed = [item for item in actions if item.is_confirmed]
        excluded = [item for item in actions if not item.is_confirmed]
        if excluded:
            self.notes.append(
                f"公司行为：{len(excluded)} 条未确认事件因证据等级不足未应用"
                f"（unverified_corporate_action）；涉及标的 "
                + ",".join(sorted({item.code for item in excluded}))
            )
            self.excluded_actions = [item.as_dict() for item in excluded]
        official = sum(1 for item in confirmed if item.is_officially_confirmed)
        secondary = len(confirmed) - official
        if confirmed:
            self.notes.append(
                f"公司行为：已应用 {len(confirmed)} 条事件"
                f"（official_confirmed {official} / secondary_confirmed {secondary}）"
            )
        return confirmed

    def _capture_dividend_shares(self, trade_date, record_index, portfolio) -> None:
        """在权益登记日收盘锁定每笔分红对应的持仓份额。

        现金分红的权益归「权益登记日收盘时登记在册的份额」所有，
        因此必须在这一天定格；后续买卖不影响已经确定的应收金额。
        """
        actions = record_index.get(trade_date)
        if not actions:
            return
        for action in actions:
            self._dividend_locked_shares[action.action_id] = portfolio.quantity(action.code)

    def _apply_corporate_actions(
        self,
        trade_date: date,
        action_index: dict,
        portfolio: Portfolio,
        bars: dict[str, BarData],
        rules: dict[str, InstrumentRule],
    ) -> None:
        """在 trade_date 应用当日生效的公司行为。

        - 份额调整：新数量 = floor(旧数量 × 比例)，零碎部分按当日原始价折现金；
        - 现金分红：现金 += 持仓 × 每份分红；
        - 未确认 / other 类型：直接跳过并在 notes 中留痕；
        - 同一事件对同一 run 只应用一次（由 record_application 唯一约束保证）。
        """
        actions = action_index.get(trade_date)
        if not actions:
            return
        from app.backtest import corporate_actions as ca

        for action in actions:
            data = bars.get(action.code)
            price = None
            if data is not None and trade_date in data.frame.index:
                close = data.frame.loc[trade_date, "close"]
                if pd.notna(close) and float(close) > 0:
                    price = float(close)
            if price is None and data is not None:
                history = data.frame.loc[data.frame.index <= trade_date, "close"].dropna()
                if not history.empty:
                    price = float(history.iloc[-1])

            if action.action_type == ca.ACTION_CASH_DISTRIBUTION:
                # 优先用权益登记日锁定的份额；未锁定（登记日在回测区间之前或
                # 非交易日）时退回当日持仓，并在 notes 留痕
                if action.action_id in self._dividend_locked_shares:
                    holding = self._dividend_locked_shares[action.action_id]
                else:
                    holding = portfolio.quantity(action.code)
                    self.notes.append(
                        f"公司行为：{action.code} {action.ex_date} 分红未取得登记日份额，"
                        f"按除息日持仓 {holding} 计算"
                    )
            else:
                holding = portfolio.quantity(action.code)
            if action.action_type == ca.ACTION_CASH_DISTRIBUTION and not getattr(
                self.config, "apply_cash_distributions", True
            ):
                self.notes.append(
                    f"公司行为：{action.code} {action.effective_date} 分红被配置关闭"
                )
                continue
            try:
                impact = ca.compute_impact(action, holding=holding, price=price)
            except ca.CorporateActionError as exc:
                self.notes.append(f"公司行为跳过 {action.code} {action.effective_date}：{exc}")
                continue
            if impact.shares_after == impact.shares_before and abs(impact.cash_delta) < 1e-12:
                continue
            ledger: dict = {}
            if action.action_type == ca.ACTION_CASH_DISTRIBUTION:
                # 只确认应收，不动现金
                portfolio.confirm_dividend_receivable(
                    action.code,
                    impact.cash_delta,
                    action_id=action.action_id,
                    ex_date=action.ex_date,
                    pay_date=action.pay_date or action.effective_date,
                    record_date=action.record_date,
                    shares=impact.shares_before,
                )
            else:
                ledger = portfolio.apply_corporate_action(
                    action.code,
                    impact.shares_after,
                    impact.cash_delta,
                    official_ratio=impact.official_ratio,
                    compensation_price=impact.compensation_price,
                    fractional_policy=impact.fractional_policy,
                    action_id=action.action_id,
                    action_type=action.action_type,
                )
                self.corporate_action_ledger.append(ledger)
            # 只有显式给了 db_path 才持久化；测试/纯内存回测不写任何数据库
            if self._run_id_for_actions and self.db_path is not None:
                ca.record_application(
                    run_id=self._run_id_for_actions,
                    impact=impact,
                    ledger=ledger,
                    db_path=self.db_path,
                )
                if action.action_type == ca.ACTION_CASH_DISTRIBUTION:
                    self._pending_receivable[action.action_id] = impact.cash_delta
                    if self.db_path is not None:
                        ca.save_receivable(
                            run_id=self._run_id_for_actions,
                            action=action,
                            shares=impact.shares_before,
                            amount=impact.cash_delta,
                            db_path=self.db_path,
                        )
            self.corporate_action_log.append(impact.as_dict())

    def _load(self, codes: list[str]) -> dict[str, BarData]:
        bars: dict[str, BarData] = {}
        for code in codes:
            bars[code] = load_bars(
                code,
                self.config.start_date,
                self.config.end_date,
                indicator_version=None,
                db_path=self.db_path,
            )
        return bars

    def _load_indicators(self, codes: list[str], version: str | None) -> dict[str, pd.DataFrame]:
        if not version:
            return {}
        payload: dict[str, pd.DataFrame] = {}
        for code in codes:
            data = load_bars(
                code,
                self.config.start_date,
                self.config.end_date,
                indicator_version=version,
                db_path=self.db_path,
            )
            if data.indicator_frame is not None:
                payload[code] = data.indicator_frame
        return payload

    def _rules(self, pool: dict[str, dict[str, Any]], codes: list[str]) -> dict[str, InstrumentRule]:
        rules = {}
        for code in codes:
            category = str(pool.get(code, {}).get("category") or "未知")
            rule = rule_for(code, category, self.config.instrument_overrides)
            rules[code] = rule
            if not rule.confirmed:
                self.notes.append(f"{code} 交易规则未确认：{rule.notes or 'N/A'}")
        return rules

    def _build_quote(
        self,
        bars: BarData,
        trade_date: date,
        previous_close: float | None,
    ) -> Quote | None:
        if trade_date not in bars.frame.index:
            return None
        row = bars.frame.loc[trade_date]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[-1]
        return Quote.from_row(trade_date, row, previous_close)

    def _previous_close(self, bars: BarData, trade_date: date) -> float | None:
        history = bars.frame.loc[bars.frame.index < trade_date]
        if history.empty:
            return None
        return float(history["close"].iloc[-1])

    def _current_weights(
        self,
        portfolio: Portfolio,
        prices: dict[str, float],
        total: float,
    ) -> dict[str, float]:
        if total <= 0:
            return {}
        return {
            code: portfolio.quantity(code) * prices.get(code, 0.0) / total
            for code in self.codes
        }

    def _signal_context(
        self,
        signal_date: date,
        bars: dict[str, BarData],
        indicators: dict[str, pd.DataFrame],
        portfolio: Portfolio,
        prices: dict[str, float],
        total: float,
    ) -> StrategyContext:
        sliced_bars = {
            code: frame.loc[frame.index <= signal_date]
            for code, frame in ((code, data.frame) for code, data in bars.items())
        }
        sliced_ind = {
            code: frame.loc[frame.index <= signal_date]
            for code, frame in indicators.items()
        }
        return StrategyContext(
            signal_date=signal_date,
            codes=list(self.codes),
            bars=sliced_bars,
            indicators=sliced_ind,
            current_weights=self._current_weights(portfolio, prices, total),
            history_days=len(sliced_bars.get(self.codes[0], [])) if self.codes else 0,
        )

    def _orders_from_weights(
        self,
        signal_date: date,
        targets: list[TargetWeight],
        portfolio: Portfolio,
        prices: dict[str, float],
        total: float,
        rules: dict[str, InstrumentRule],
        indicators_available: bool,
    ) -> list[Order]:
        """目标权重 → 订单。低于阈值的差额忽略。"""
        target_map = {item.code: max(0.0, float(item.weight)) for item in targets}
        for code in self.codes:
            target_map.setdefault(code, 0.0)
        if any(weight < 0 for weight in target_map.values()):
            raise BacktestError("目标权重不能为负")
        weight_sum = sum(target_map.values())
        if weight_sum > 1.0 + 1e-9:
            raise BacktestError(f"目标权重之和超过 1：{weight_sum:.6f}")

        current = self._current_weights(portfolio, prices, total)
        orders: list[Order] = []
        seq = 0
        for code in sorted(target_map):
            target = target_map[code]
            current_weight = current.get(code, 0.0)
            delta = target - current_weight
            price = prices.get(code)
            if price is None or price <= 0:
                continue
            rule = rules[code]
            # 容忍带内的偏离不调仓，避免每日因价格漂移产生大量小额订单
            if abs(delta) < self.config.rebalance_tolerance:
                continue
            notional = abs(delta) * total
            raw_quantity = notional / price
            if delta > 0:
                quantity = round_lot(raw_quantity, rule.lot_size)
                if quantity <= 0:
                    continue
                seq += 1
                orders.append(
                    Order(
                        order_id=0,
                        code=code,
                        side="buy",
                        signal_date=signal_date,
                        order_date=signal_date,
                        quantity=quantity,
                        target_weight=target,
                        reference_price=price,
                        seq=seq,
                        strategy=self.strategy.name,
                    )
                )
            else:
                available = portfolio.available(code, signal_date)
                # 目标权重为 0 表示明确清仓：整手与零股合并成一笔申报
                liquidate = target <= 1e-9
                quantity = sell_quantity(
                    raw_quantity, available, rule.lot_size, liquidate=liquidate
                )
                if quantity <= 0:
                    continue
                seq += 1
                orders.append(
                    Order(
                        order_id=0,
                        code=code,
                        side="sell",
                        signal_date=signal_date,
                        order_date=signal_date,
                        quantity=quantity,
                        target_weight=target,
                        reference_price=price,
                        seq=seq,
                        strategy=self.strategy.name,
                        liquidate=liquidate,
                    )
                )
        return orders

    def run(
        self,
        codes: list[str] | None = None,
        *,
        indicator_version: str | None = "latest",
        run_id: str | None = None,
    ) -> BacktestResult:
        """执行回测。

        所有订单在生成后的下一个交易日才进入撮合，禁止当日信号当日成交。
        """
        pool = load_pool(db_path=self.db_path)
        self.codes = sorted(codes or list(pool))
        if not self.codes:
            raise BacktestError("回测 ETF 池为空")
        bars = self._load(self.codes)
        indicators = self._load_indicators(self.codes, indicator_version)
        rules = self._rules(pool, self.codes)
        snapshot_ids = {code: data.snapshot_id for code, data in bars.items()}
        if indicator_version:
            resolved = {data.indicator_version for data in
                        (load_bars(code, self.config.start_date, self.config.end_date,
                                   indicator_version=indicator_version, db_path=self.db_path)
                         for code in self.codes)}
            resolved = {value for value in resolved if value}
            if len(resolved) > 1:
                raise BacktestError(f"多个 ETF 使用了不同指标版本：{sorted(resolved)}")
            indicator_version = resolved.pop() if resolved else indicator_version

        # 阶段3A.3.2：加载本区间内的公司行为事件（只取已确认的）
        actions = self._load_corporate_actions(self.codes)
        from app.backtest import corporate_actions as ca
        from app.backtest.corporate_actions import DATA_VERSION as ca_version
        resolved_run_id = run_id or uuid.uuid4().hex[:16]
        self._run_id_for_actions = resolved_run_id
        # 份额调整按「生效交易日」索引；现金分红按「除息日」确认应收。
        action_index: dict[date, list] = {}
        # 现金分红的应收份额必须在权益登记日收盘锁定：
        # 登记日之后、除息日之前可能还有买卖，用除息日持仓会算错。
        record_index: dict[date, list] = {}
        for action in actions:
            if action.action_type == "cash_distribution":
                action_index.setdefault(action.ex_date, []).append(action)
                lock_day = action.record_date or action.ex_date
                record_index.setdefault(lock_day, []).append(action)
            else:
                action_index.setdefault(action.effective_date, []).append(action)

        portfolio = Portfolio(initial_cash=self.config.initial_cash)
        broker = Broker(config=self.config, calendar=self.calendar)
        orders: list[Order] = []
        trades: list[Trade] = []
        daily: list[DailySnapshot] = []
        pending: list[Order] = []
        order_seq = 0
        nav_base = self.config.initial_cash
        previous_nav: float | None = None

        for trade_date in self.calendar:
            # 0) 公司行为：在开盘撮合之前调整持仓数量与现金。
            #    净值在事件日自然连续：拆分后价格除以比例、数量乘回比例；
            #    分红时价格除息下跌、现金等额补回。
            self._apply_corporate_actions(
                trade_date, action_index, portfolio, bars, rules
            )
            # 发放日到账：把已到期的应收分红转入可用现金（在开盘撮合之前完成，
            # 因为这笔钱在当日开盘前就已到账，可以用于当天交易）
            self._capture_dividend_shares(trade_date, record_index, portfolio)
            from app.backtest import corporate_actions as ca
            settled = portfolio.settle_dividend_receivable(trade_date)
            for item in settled:
                if self._run_id_for_actions and self.db_path is not None:
                    ca.settle_receivable(
                        run_id=self._run_id_for_actions,
                        action_id=int(item["action_id"]),
                        db_path=self.db_path,
                    )
                self.dividend_settlements.append({
                    "code": item["code"],
                    "action_id": item["action_id"],
                    "amount": round(float(item["amount"]), 6),
                    "pay_date": item["pay_date"].isoformat() if item.get("pay_date") else None,
                    "settled_on": trade_date.isoformat(),
                })

            # 1) 开盘撮合：只撮合 signal_date < trade_date 的订单
            executable = sorted(
                [order for order in pending if order.signal_date < trade_date],
                key=lambda item: (item.signal_date, item.seq, item.code),
            )
            still_pending: list[Order] = []
            for order in executable:
                data = bars.get(order.code)
                quote = (
                    self._build_quote(data, trade_date, self._previous_close(data, trade_date))
                    if data is not None else None
                )
                if quote is None:
                    order.deferred_days += 1
                    if order.has_fill:
                        order.reason = append_reason(order.reason, "missing_quote")
                    else:
                        order.reason = "missing_quote"
                    order.sync_status()
                    still_pending.append(order)
                    continue
                result: FillResult = broker.execute(
                    order, quote, rules[order.code], portfolio, trade_date
                )
                if result.filled and result.trade is not None:
                    trades.append(result.trade)
                    # 部分成交：保留 partial，把剩余数量继续挂到下一交易日
                    if order.filled_quantity < int(order.quantity):
                        if self.config.max_defer_days > 0:
                            still_pending.append(order)
                        else:
                            order.sync_status()
                            order.reason = append_reason(order.reason, "remainder_cancelled")
                elif result.deferred and order.deferred_days <= self.config.max_defer_days:
                    still_pending.append(order)
                elif result.deferred:
                    # 已经部分成交的订单过期时保留 partial，不降级为完全未成交
                    if order.has_fill:
                        order.reason = append_reason(order.reason, "max_defer_exceeded")
                    order.sync_status(terminal="expired")
                else:
                    # 剩余部分被拒绝：有成交的订单只拒绝剩余，状态保持 partial
                    if order.has_fill:
                        order.reason = append_reason(order.reason, "remainder_rejected")
                    order.sync_status(terminal="rejected")
            # 已处理的订单移出待撮合队列；orders 里保留同一对象的引用，不重复追加。
            pending = still_pending

            # 2) 收盘估值：只用当日原始收盘价；缺失则沿用最近有效收盘并标记
            prices: dict[str, float] = {}
            price_status: dict[str, str] = {}
            for code, data in bars.items():
                if trade_date in data.frame.index:
                    close = data.frame.loc[trade_date, "close"]
                    if pd.notna(close) and float(close) > 0:
                        prices[code] = float(close)
                        price_status[code] = "ok"
                        continue
                history = data.frame.loc[data.frame.index <= trade_date, "close"].dropna()
                if history.empty:
                    price_status[code] = "no_price"
                    continue
                prices[code] = float(history.iloc[-1])
                price_status[code] = "stale_price"
            missing = [code for code in self.codes if code not in prices]
            if missing:
                raise BacktestError(f"{trade_date} 缺少估值价格：{missing}")

            # 权益登记日的份额在「当日成交完成后、收盘估值前」锁定：
            # 登记在册的份额以当日收盘后的登记结果为准。
            self._capture_dividend_shares(trade_date, record_index, portfolio)
            total = portfolio.total_assets(prices)
            snapshot = portfolio.snapshot(
                trade_date=trade_date,
                prices=prices,
                nav_base=nav_base,
                previous_nav=previous_nav,
                price_status=price_status,
            )
            daily.append(snapshot)
            previous_nav = snapshot.nav

            # 3) 收盘后生成下一批订单（signal_date = trade_date）
            context = self._signal_context(trade_date, bars, indicators, portfolio, prices, total)
            raw_targets = self.strategy.target_weights(context)
            # None = 本日无意见（维持现有仓位）；[] = 明确要求空仓
            if raw_targets is None:
                raw_targets = None
            targets = list(raw_targets) if raw_targets is not None else None
            new_orders = (
                self._orders_from_weights(
                    trade_date, targets, portfolio, prices, total, rules, bool(indicators)
                )
                if targets is not None
                else []
            )
            for order in new_orders:
                order_seq += 1
                order.order_id = order_seq
            orders.extend(new_orders)
            pending.extend(new_orders)

        # 收盘后仍未成交的订单标记为未成交；部分成交的保留 partial
        for order in pending:
            if order.has_fill:
                if order.remaining_quantity > 0:
                    order.reason = append_reason(order.reason, "partial_not_completed")
                order.sync_status()
            else:
                order.sync_status(terminal="unfilled")

        actions_digest = ca.compute_events_digest(actions)
        self.corporate_action_digest = actions_digest
        input_hash = _input_hash(
            self.config, self.strategy, self.codes, indicator_version, snapshot_ids,
            _frame_hash(bars),
            corporate_action_version=ca_version,
            corporate_action_digest=actions_digest,
        )
        return BacktestResult(
            run_id=run_id or uuid.uuid4().hex[:16],
            config=self.config,
            strategy_name=self.strategy.name,
            strategy_version=self.strategy.version,
            codes=self.codes,
            indicator_version=indicator_version,
            snapshot_ids=snapshot_ids,
            rules=rules,
            daily=daily,
            orders=orders,
            trades=trades,
            initial_cash=self.config.initial_cash,
            input_hash=input_hash,
            notes=self.notes,
        )
