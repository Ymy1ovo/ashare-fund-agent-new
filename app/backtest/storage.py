"""回测结果持久化：运行记录、每日净值、订单、成交、每日持仓。"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.backtest.engine import BacktestResult
from app.backtest.metrics import Performance, reconcile, yearly_table
from app.database.db import get_connection


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def save_result(
    result: BacktestResult,
    performance: Performance,
    *,
    db_path=None,
) -> dict[str, Any]:
    """写入回测记录；同一 run_id 重跑会覆盖该 run 的行，不覆盖历史 run。"""
    created = datetime.now().isoformat(timespec="seconds")
    check = reconcile(result.daily, result.trades, result.initial_cash)
    from app.backtest.api import COST_SEMANTICS

    # 阶段3A.3.2.2.3：口径标记一律显式落盘。缺字段的历史结果按
    # formal_receivable/True 处理会伪造正式性，因此这里不允许缺省为正式。
    accounting_basis = getattr(result, "accounting_basis", None)
    if not isinstance(accounting_basis, str) or not accounting_basis:
        accounting_basis = "unknown_legacy"
    formal = getattr(result, "formal_valuation", None)
    formal = bool(formal) if isinstance(formal, bool) else False
    if accounting_basis != "formal_receivable":
        formal = False

    summary = {
        "performance": performance.as_dict(),
        "reconciliation": check,
        "yearly": yearly_table(result.daily),
        "snapshot_ids": result.snapshot_ids,
        "rules": {code: rule.__dict__ for code, rule in result.rules.items()},
        "notes": result.notes,
        # 成本口径版本：新记录 total_cost 含佣金+印花税+过户费+滑点
        "cost_semantics": COST_SEMANTICS,
        # 阶段3A.3.2.2.3：会计口径标记必须落盘，否则读取端无法区分
        # 正式回测与 apply_corporate_actions=False 的非正式结果
        "accounting_basis": accounting_basis,
        "formal_valuation": formal,
    }
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO backtest_runs
                (run_id, strategy_name, strategy_version, config_json, initial_cash,
                 start_date, end_date, etf_codes, indicator_version, snapshot_ids,
                 input_hash, summary_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                strategy_name=excluded.strategy_name,
                strategy_version=excluded.strategy_version,
                config_json=excluded.config_json,
                initial_cash=excluded.initial_cash,
                start_date=excluded.start_date,
                end_date=excluded.end_date,
                etf_codes=excluded.etf_codes,
                indicator_version=excluded.indicator_version,
                snapshot_ids=excluded.snapshot_ids,
                input_hash=excluded.input_hash,
                summary_json=excluded.summary_json
            """,
            (
                result.run_id,
                result.strategy_name,
                result.strategy_version,
                _json(result.config.as_dict()),
                result.initial_cash,
                result.config.start_date,
                result.config.end_date,
                _json(result.codes),
                result.indicator_version,
                _json(result.snapshot_ids),
                result.input_hash,
                _json(summary),
                created,
            ),
        )
        conn.execute("DELETE FROM backtest_daily_nav WHERE run_id = ?", (result.run_id,))
        conn.execute("DELETE FROM backtest_orders WHERE run_id = ?", (result.run_id,))
        conn.execute("DELETE FROM backtest_trades WHERE run_id = ?", (result.run_id,))
        conn.execute("DELETE FROM backtest_positions_daily WHERE run_id = ?", (result.run_id,))

        conn.executemany(
            """
            INSERT INTO backtest_daily_nav
                (run_id, trade_date, cash, market_value, total_assets, nav,
                 daily_return, price_status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    result.run_id, item.trade_date.isoformat(), item.cash,
                    item.market_value, item.total_assets, item.nav,
                    item.daily_return, _json(item.price_status), created,
                )
                for item in result.daily
            ],
        )
        conn.executemany(
            """
            INSERT INTO backtest_positions_daily
                (run_id, trade_date, code, quantity, close_price, market_value, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    result.run_id, item.trade_date.isoformat(), code,
                    quantity, item.prices.get(code), quantity * item.prices.get(code, 0.0),
                    created,
                )
                for item in result.daily
                for code, quantity in item.positions.items()
            ],
        )
        conn.executemany(
            """
            INSERT INTO backtest_orders
                (run_id, order_id, code, side, signal_date, order_date, fill_date,
                 quantity, filled_quantity, remaining_quantity, fill_price, status, reason,
                 deferred_days, commission, stamp_tax, transfer_fee, fee, slippage_cost,
                 reference_price, target_weight, strategy, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    result.run_id, order.order_id, order.code, order.side,
                    order.signal_date.isoformat(), order.order_date.isoformat(),
                    order.fill_date.isoformat() if order.fill_date else None,
                    order.quantity, order.filled_quantity, order.remaining_quantity,
                    order.fill_price, order.status, order.reason, order.deferred_days,
                    order.commission, order.stamp_tax, order.transfer_fee,
                    order.fee, order.slippage_cost, order.reference_price,
                    order.target_weight, order.strategy, created,
                )
                for order in result.orders
            ],
        )
        conn.executemany(
            """
            INSERT INTO backtest_trades
                (run_id, trade_id, order_id, code, side, trade_date, quantity,
                 price, gross_amount, commission, stamp_tax, transfer_fee,
                 slippage_cost, realized_pnl, holding_days, cash_after, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    result.run_id, trade.trade_id, trade.order_id, trade.code,
                    trade.side, trade.trade_date.isoformat(), trade.quantity,
                    trade.price, trade.gross_amount, trade.commission,
                    trade.stamp_tax, trade.transfer_fee,
                    trade.slippage_cost, trade.realized_pnl, trade.holding_days,
                    trade.cash_after, created,
                )
                for trade in result.trades
            ],
        )
    return {
        "run_id": result.run_id,
        "daily": len(result.daily),
        "orders": len(result.orders),
        "trades": len(result.trades),
        "reconciliation": check,
        "accounting_basis": accounting_basis,
        "formal_valuation": formal,
    }
