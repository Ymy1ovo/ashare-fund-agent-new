"""回测相关查询仓储，供 FastAPI 使用。"""
from __future__ import annotations

import json
from typing import Any

from app.database.db import get_connection


def get_run(run_id: str, db_path=None) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM backtest_runs WHERE run_id = ?", (run_id,)).fetchone()
    if not row:
        return None
    payload = dict(row)
    for key in ("config_json", "etf_codes", "snapshot_ids", "summary_json"):
        if payload.get(key):
            try:
                payload[key] = json.loads(payload[key])
            except json.JSONDecodeError:
                pass
    # 阶段3A.3.2.2.3：把口径标记提到顶层，调用方不需要钻进 summary_json
    summary = payload.get("summary_json")
    payload["accounting_basis"] = accounting_basis_of(summary)
    payload["formal_valuation"] = formal_valuation_of(summary)
    return payload


def list_runs(limit: int = 20, db_path=None) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT run_id, strategy_name, strategy_version, initial_cash, start_date, "
            "end_date, indicator_version, input_hash, created_at, summary_json "
            "FROM backtest_runs ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
    payload = []
    for row in rows:
        item = dict(row)
        raw = item.pop("summary_json", None)
        summary = None
        if raw:
            try:
                summary = json.loads(raw)
            except json.JSONDecodeError:
                summary = None
        item["accounting_basis"] = accounting_basis_of(summary)
        item["formal_valuation"] = formal_valuation_of(summary)
        payload.append(item)
    return payload


def get_nav(run_id: str, db_path=None) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT trade_date, cash, market_value, total_assets, nav, daily_return, price_status "
            "FROM backtest_daily_nav WHERE run_id = ? ORDER BY trade_date",
            (run_id,),
        ).fetchall()
    payload = []
    for row in rows:
        item = dict(row)
        if item.get("price_status"):
            try:
                item["price_status"] = json.loads(item["price_status"])
            except json.JSONDecodeError:
                pass
        payload.append(item)
    return payload


def get_trades(run_id: str, db_path=None) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM backtest_trades WHERE run_id = ? ORDER BY trade_date, trade_id",
            (run_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_orders(run_id: str, db_path=None) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM backtest_orders WHERE run_id = ? ORDER BY signal_date, seq, order_id"
            if False else
            "SELECT * FROM backtest_orders WHERE run_id = ? ORDER BY signal_date, order_id",
            (run_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_positions(run_id: str, trade_date: str | None = None, db_path=None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM backtest_positions_daily WHERE run_id = ?"
    params: list[Any] = [run_id]
    if trade_date:
        sql += " AND trade_date = ?"
        params.append(trade_date)
    sql += " ORDER BY trade_date, code"
    with get_connection(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def get_cash(run_id: str, db_path=None) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT trade_date, cash, market_value, total_assets FROM backtest_daily_nav "
            "WHERE run_id = ? ORDER BY trade_date",
            (run_id,),
        ).fetchall()
    return [dict(row) for row in rows]

# 成本语义版本标记：
#   cost_semantics = "commission+taxes+slippage"  → 新记录（阶段3A.2.1.1.2.1.1 起）
#   历史记录缺少该字段 → 旧语义 total_cost = commission + slippage
COST_SEMANTICS = "commission+taxes+slippage"

# 会计口径标记（阶段3A.3.2.2.3）：
#   formal_receivable     → 公司行为按应收口径应用的正式回测
#   disabled_non_official → apply_corporate_actions=False 的非正式回测
#   unknown_legacy        → 本字段落盘之前写入的历史记录，无法证明是正式口径
ACCOUNTING_FORMAL = "formal_receivable"
ACCOUNTING_DISABLED = "disabled_non_official"
ACCOUNTING_UNKNOWN = "unknown_legacy"


def accounting_basis_of(summary: dict | None) -> str:
    """读取一条回测记录的会计口径；缺失视为无法证明的旧记录。"""
    if isinstance(summary, dict):
        value = summary.get("accounting_basis")
        if isinstance(value, str) and value:
            return value
    return ACCOUNTING_UNKNOWN


def formal_valuation_of(summary: dict | None) -> bool:
    """该记录能否作为正式策略评价结果。

    只有显式 `formal_valuation=True` 或 `accounting_basis=formal_receivable`
    时才允许为真；其它情况一律 fail closed。
    """
    if not isinstance(summary, dict):
        return False
    value = summary.get("formal_valuation")
    if isinstance(value, bool):
        return value
    return summary.get("accounting_basis") == ACCOUNTING_FORMAL


def is_formal_run(summary: dict | None) -> bool:
    """正式口径判定：两字段必须一致，任一不满足即非正式。"""
    return (
        accounting_basis_of(summary) == ACCOUNTING_FORMAL
        and formal_valuation_of(summary) is True
    )


def cost_semantics_of(summary: dict | None) -> str:
    """判断一条回测记录的成本口径版本。"""
    if not summary:
        return "legacy"
    value = summary.get("cost_semantics")
    return value if isinstance(value, str) and value else "legacy"


def describe_cost_semantics(summary: dict | None) -> dict:
    """给 API 返回可读的口径说明，避免新旧记录被无差别混算。"""
    version = cost_semantics_of(summary)
    if version == "legacy":
        return {
            "version": "legacy",
            "includes_taxes": False,
            "note": (
                "历史记录：当时 stamp_duty_rate 与 transfer_fee_rate 均为 0，"
                "total_cost = 佣金 + 滑点，与实际总成本数值一致"
            ),
        }
    return {
        "version": version,
        "includes_taxes": True,
        "note": "total_cost = 佣金 + 印花税 + 过户费 + 滑点",
    }
