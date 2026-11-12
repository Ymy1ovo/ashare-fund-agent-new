"""sell_proceeds_below_fee 受控完整交易链路验证（阶段3A.2.1.2）。

在独立 SQLite 副本上构造真实表结构的行情与账户场景，
通过 BacktestEngine + Broker 完整流程触发「卖出收入不足以覆盖费用」。

策略链路（真实 Engine 交易流程）：
  第 1 天信号：全仓买入 1 份低价 ETF，把现金几乎用尽
  第 2 天信号：清仓卖出，此时 gross < 最低佣金 且 现金不足以补差
  → Broker 应拒单并标记 sell_proceeds_below_fee，不产生负现金
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from app.validation.sensitivity_scan import copy_database


class SellProbeError(RuntimeError):
    """受控场景构造或执行失败。"""


@dataclass
class SellProbeResult:
    """一个受控场景的执行结果。"""

    scenario: str
    triggered: bool = False
    order_status: str | None = None
    reason: str | None = None
    filled_quantity: int = 0
    gross_amount: float = 0.0
    commission: float = 0.0
    stamp_tax: float = 0.0
    transfer_fee: float = 0.0
    total_fees: float = 0.0
    cash_before: float = 0.0
    cash_after: float = 0.0
    position_before: int = 0
    position_after: int = 0
    trade_count: int = 0
    negative_cash_days: int = 0
    reconcile_ok: bool | None = None
    reconcile_errors: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "scenario": self.scenario,
            "triggered": self.triggered,
            "order_status": self.order_status,
            "reason": self.reason,
            "filled_quantity": self.filled_quantity,
            "gross_amount": self.gross_amount,
            "commission": self.commission,
            "stamp_tax": self.stamp_tax,
            "transfer_fee": self.transfer_fee,
            "total_fees": self.total_fees,
            "cash_before": self.cash_before,
            "cash_after": self.cash_after,
            "position_before": self.position_before,
            "position_after": self.position_after,
            "trade_count": self.trade_count,
            "negative_cash_days": self.negative_cash_days,
            "reconcile_ok": self.reconcile_ok,
            "reconcile_errors": self.reconcile_errors,
            "notes": self.notes,
        }


def build_probe_db(
    source_db,
    workdir,
    *,
    code: str = "512010",
    price: float = 0.3738,
    days: int = 8,
) -> tuple[Path, list[str], int]:
    """从真实库复制结构，写入受控的低价 ETF 行情。

    返回 (副本路径, 交易日列表, snapshot_id)。源库零写入。
    """
    work = Path(workdir)
    target = copy_database(source_db, work, name=f"probe_{code}.db")

    with sqlite3.connect(target) as conn:
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("DELETE FROM etf_daily_prices WHERE code=?", (code,))
        conn.execute(
            "INSERT OR IGNORE INTO etf_pool (code, name, category, fund_type, "
            "data_source, source_tested_at, status) "
            "VALUES (?,?,?,'指数型-股票','probe','2024-01-01','active')",
            (code, "探针ETF", "宽基指数ETF"),
        )
        # 该 ETF 若已有当前快照就复用，没有则新建
        row = conn.execute(
            "SELECT id FROM etf_adjustment_snapshots WHERE code=? AND is_current=1",
            (code,),
        ).fetchone()
        if row is None:
            run_id = conn.execute(
                "SELECT COALESCE(MIN(run_id), 1) FROM etf_adjustment_snapshots"
            ).fetchone()[0] or 1
            conn.execute(
                "INSERT INTO etf_adjustment_snapshots "
                "(run_id, code, status, collected_at, source, coverage_start, coverage_end, "
                "matched_start, matched_end, raw_rows, qfq_rows, matched_rows, missing_rows, "
                "is_current, created_at) "
                "VALUES (?,?, 'success','2024-01-01T00:00:00','probe',?,?,?,?,?,?,?,0,1,"
                "'2024-01-01T00:00:00')",
                (run_id, code, "2024-01-01", "2024-01-31",
                 "2024-01-01", "2024-01-31", days, days, days),
            )
            snapshot = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        else:
            snapshot = int(row[0])

        base = date(2024, 1, 2)
        trade_days: list[str] = []
        for offset in range(days):
            day = date(2024, 1, 2 + offset).isoformat()
            trade_days.append(day)
            conn.execute(
                "INSERT OR REPLACE INTO trade_calendar (trade_date) VALUES (?)", (day,)
            )
            conn.execute(
                "INSERT OR REPLACE INTO etf_daily_prices "
                "(code, trade_date, open, high, low, close, volume, amount, "
                "adjusted_close, adjustment_type, quality_status, source, collected_at, "
                "adjustment_snapshot_id, adjustment_collected_at, adjustment_source, "
                "adjustment_coverage_start, adjustment_coverage_end) "
                "VALUES (?,?,?,?,?,?,?,?,?,'qfq','valid','probe','2024-01-01T00:00:00',"
                "?,'2024-01-01T00:00:00','probe',?,?)",
                (code, day, price, price, price, price, 1_000_000,
                 price * 1_000_000, price, snapshot, "2024-01-01", "2024-01-31"),
            )
        conn.commit()
        stored = conn.execute(
            "SELECT COUNT(*) FROM etf_daily_prices WHERE code=?", (code,)
        ).fetchone()[0]

    if stored != days:
        raise SellProbeError(f"受控行情写入失败：期望 {days} 行，实际 {stored}")
    return target, trade_days, snapshot


class _ProbeStrategy:
    """第 1 天全仓买入，第 2 天清仓，之后无意见。"""

    name = "probe_sell"
    version = "1.0.0"

    def __init__(self, code: str, buy_day: str, sell_day: str,
                 target_weight: float = 1.0) -> None:
        self.code = code
        self.buy_day = buy_day
        self.sell_day = sell_day
        self.target_weight = float(target_weight)
        self.calls: list[str] = []

    def target_weights(self, context):
        from app.backtest.strategies.base import TargetWeight

        key = context.signal_date.isoformat()
        self.calls.append(key)
        if key == self.buy_day:
            return [TargetWeight(code=self.code, weight=self.target_weight)]
        if key == self.sell_day:
            return []
        return None


def run_controlled_sell(
    *,
    source_db,
    workdir,
    code: str = "512010",
    price: float = 0.3738,
    cash: float = 1.0,
    days: int = 8,
    label: str = "probe",
) -> SellProbeResult:
    """在受控库上跑完整 Engine 流程，验证卖出费用不足的处理。"""
    from app.backtest.config import BacktestConfig, CostConfig
    from app.backtest.engine import BacktestEngine
    from app.backtest.metrics import reconcile

    probe_db, trade_days, _ = build_probe_db(
        source_db, workdir, code=code, price=price, days=days
    )

    result = SellProbeResult(scenario=label)
    result.cash_before = float(cash)

    # 用 lot_size=1 的规则覆盖，使 1 份持仓成为可能（系统正式支持的配置项）。
    # 初始资金 = 买入 1 份的成本 + 最低佣金 + 剩余现金 cash。
    # 买入后剩余现金恰好是 cash，用于制造「卖出收入 < 最低佣金 且 现金不足」。
    # 目标权重按「只买 1 份」反推：weight = 1 份市值 / 账户总资产
    seed_cash = price * 1.05 + 5.0 + float(cash)
    target_weight = min(1.0, price / seed_cash)
    result.notes.append(
        f"seed_cash={seed_cash:.4f}, weight={target_weight:.6f}, "
        f"expect_buy_qty=1, 买入后剩余现金≈{cash:.4f}, lot_size=1"
    )
    config = BacktestConfig(
        start_date=trade_days[0], end_date=trade_days[-1],
        initial_cash=float(seed_cash), execution_price="open", max_defer_days=0,
        cash_shortfall_policy="reduce", rebalance_tolerance=0.0,
        instrument_overrides={code: {"lot_size": 1}},
        costs=CostConfig(commission_rate=0.00025, min_commission=5.0,
                         slippage_bps=5.0),
    )
    # 交易时序（严格 T+1）：
    #   days[0] 收盘信号 → days[1] 开盘买入成交，available_date = days[2]
    #   days[2] 收盘信号 → days[3] 开盘撮合卖出，此时持仓已可卖
    strategy = _ProbeStrategy(code, trade_days[0], trade_days[2], target_weight)
    engine = BacktestEngine(config, strategy, db_path=probe_db)

    try:
        backtest = engine.run([code], indicator_version=None)
    except Exception as exc:  # noqa: BLE001 受控场景允许异常但必须记录
        result.notes.append(f"engine 异常：{str(exc)[:200]}")
        result.reconcile_ok = False
        return result

    result.trade_count = len(backtest.trades)
    result.negative_cash_days = sum(
        1 for item in backtest.daily if item.cash < -1e-6
    )
    if backtest.daily:
        result.cash_after = float(backtest.daily[-1].cash)
        result.position_after = int((backtest.daily[-1].positions or {}).get(code, 0))

    sell_order = next(
        (o for o in backtest.orders if o.side == "sell"), None
    )
    buy_order = next((o for o in backtest.orders if o.side == "buy"), None)
    if buy_order is not None:
        result.notes.append(
            f"买入：qty={buy_order.quantity} filled={buy_order.filled_quantity} "
            f"status={buy_order.status} fee={buy_order.total_fees:.4f}"
        )
    if sell_order is not None:
        result.order_status = sell_order.status
        result.reason = sell_order.reason
        result.filled_quantity = int(sell_order.filled_quantity)
        result.gross_amount = float(sell_order.gross_amount)
        result.commission = float(sell_order.commission)
        result.stamp_tax = float(sell_order.stamp_tax)
        result.transfer_fee = float(sell_order.transfer_fee)
        result.total_fees = float(sell_order.total_fees)
        result.position_before = int(sell_order.quantity)
        result.triggered = "sell_proceeds_below_fee" in (sell_order.reason or "")

    check = reconcile(backtest.daily, backtest.trades, backtest.initial_cash)
    result.reconcile_ok = bool(check["ok"])
    result.reconcile_errors = list(check["errors"])
    return result
