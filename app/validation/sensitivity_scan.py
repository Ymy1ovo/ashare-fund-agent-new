"""稀疏行情删除比例敏感性扫描（阶段3A.2.1.2）。

在独立 SQLite 副本上按多种删除比例与删除模式制造行情缺失，
逐场景跑完整回测，记录数据质量与绩效指标。

约束：
- 只操作副本，源库零写入；
- 每个场景独立副本；
- 随机模式固定种子，可复现；
- 缺失日保留在原始交易日索引上，不 dropna 压缩。
"""
from __future__ import annotations

import hashlib
import random
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

DELETION_RATIOS: tuple[float, ...] = (0.0, 0.01, 0.03, 0.05, 0.10, 0.20)

# 删除模式
MODE_RANDOM = "random_scattered"
MODE_BLOCK = "continuous_block"
MODE_HOLDING = "holding_period"
MODE_SIGNAL = "signal_adjacent"
MODE_RECOVERY = "missing_then_recovery"

DELETION_MODES: tuple[str, ...] = (
    MODE_RANDOM, MODE_BLOCK, MODE_HOLDING, MODE_SIGNAL, MODE_RECOVERY,
)

DEFAULT_SEED = 20261112


class SensitivityError(RuntimeError):
    """敏感性扫描无法执行。"""


@dataclass
class ScenarioResult:
    """单场景结果。"""

    scenario_id: str
    deletion_ratio: float
    deletion_mode: str
    random_seed: int
    etf_count: int = 0
    deleted_rows: int = 0
    original_rows: int = 0
    remaining_rows: int = 0
    missing_trading_days: int = 0
    valid_return_days: int = 0
    missing_return_days: int = 0
    first_day_skipped: int = 0
    nan_days: int = 0
    stale_price_days: int = 0
    buy_orders: int = 0
    sell_orders: int = 0
    trade_count: int = 0
    partial_orders: int = 0
    rejected_orders: int = 0
    final_nav: float | None = None
    total_return: float | None = None
    cagr: float | None = None
    sharpe: float | None = None
    sortino: float | None = None
    max_drawdown: float | None = None
    final_cash: float | None = None
    final_positions: int = 0
    negative_cash_days: int = 0
    status: str = "pending"
    reason: str | None = None
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "deletion_ratio": self.deletion_ratio,
            "deletion_mode": self.deletion_mode,
            "random_seed": self.random_seed,
            "etf_count": self.etf_count,
            "deleted_rows": self.deleted_rows,
            "original_rows": self.original_rows,
            "remaining_rows": self.remaining_rows,
            "missing_trading_days": self.missing_trading_days,
            "valid_return_days": self.valid_return_days,
            "missing_return_days": self.missing_return_days,
            "first_day_skipped": self.first_day_skipped,
            "nan_days": self.nan_days,
            "stale_price_days": self.stale_price_days,
            "buy_orders": self.buy_orders,
            "sell_orders": self.sell_orders,
            "trade_count": self.trade_count,
            "partial_orders": self.partial_orders,
            "rejected_orders": self.rejected_orders,
            "final_nav": self.final_nav,
            "total_return": self.total_return,
            "cagr": self.cagr,
            "sharpe": self.sharpe,
            "sortino": self.sortino,
            "max_drawdown": self.max_drawdown,
            "final_cash": self.final_cash,
            "final_positions": self.final_positions,
            "negative_cash_days": self.negative_cash_days,
            "status": self.status,
            "reason": self.reason,
            "detail": self.detail,
        }


def copy_database(source_db, workdir, name: str = "scenario.db") -> Path:
    """SQLite backup API 生成独立副本，非文件复制。"""
    source = Path(source_db)
    work = Path(workdir)
    work.mkdir(parents=True, exist_ok=True)
    target = work / name
    if target.exists():
        target.unlink()
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    return target


def _trading_days(conn: sqlite3.Connection, start: str, end: str) -> list[str]:
    return [
        str(row[0]) for row in conn.execute(
            "SELECT trade_date FROM trade_calendar WHERE trade_date >= ? AND trade_date <= ? "
            "ORDER BY trade_date",
            (start, end),
        )
    ]


def delete_random_scattered(
    conn: sqlite3.Connection, codes: list[str], start: str, end: str,
    ratio: float, seed: int,
) -> tuple[int, dict]:
    """A. 随机零散删除：每只 ETF 独立随机删除 ratio 比例的行情行。"""
    rng = random.Random(seed)
    deleted = 0
    per_code: dict[str, int] = {}
    for code in codes:
        days = [
            str(row[0]) for row in conn.execute(
                "SELECT trade_date FROM etf_daily_prices WHERE code=? AND trade_date>=? "
                "AND trade_date<=? ORDER BY trade_date",
                (code, start, end),
            )
        ]
        # 保护首尾各 3 日，避免整段起始估值日被清空
        protected = set(days[:3]) | set(days[-3:])
        candidates = [d for d in days if d not in protected]
        take = int(len(candidates) * ratio)
        if take <= 0:
            per_code[code] = 0
            continue
        picked = sorted(rng.sample(candidates, take))
        conn.executemany(
            "DELETE FROM etf_daily_prices WHERE code=? AND trade_date=?",
            [(code, day) for day in picked],
        )
        deleted += len(picked)
        per_code[code] = len(picked)
    return deleted, {"per_code": per_code}


def delete_continuous_block(
    conn: sqlite3.Connection, codes: list[str], start: str, end: str,
    ratio: float, seed: int,
) -> tuple[int, dict]:
    """B. 连续区间删除：每只 ETF 在区间中部删除连续 ratio 比例的交易日。"""
    rng = random.Random(seed)
    deleted = 0
    blocks: dict[str, dict] = {}
    for code in codes:
        days = [
            str(row[0]) for row in conn.execute(
                "SELECT trade_date FROM etf_daily_prices WHERE code=? AND trade_date>=? "
                "AND trade_date<=? ORDER BY trade_date",
                (code, start, end),
            )
        ]
        if not days:
            continue
        span = int(len(days) * ratio)
        if span <= 0:
            blocks[code] = {"deleted": 0}
            continue
        # 中部区域随机起点，保证连续
        center = len(days) // 2
        max_offset = max(0, (len(days) - span) // 2)
        offset = rng.randint(0, max_offset) if max_offset else 0
        begin = max(0, center - span // 2 - offset // 2)
        block_days = days[begin:begin + span]
        conn.executemany(
            "DELETE FROM etf_daily_prices WHERE code=? AND trade_date=?",
            [(code, day) for day in block_days],
        )
        deleted += len(block_days)
        blocks[code] = {
            "deleted": len(block_days),
            "first": block_days[0] if block_days else None,
            "last": block_days[-1] if block_days else None,
        }
    return deleted, {"blocks": blocks}


def delete_holding_period(
    conn: sqlite3.Connection, codes: list[str], start: str, end: str,
    ratio: float, seed: int, holding_dates: dict[str, list[str]] | None = None,
) -> tuple[int, dict]:
    """C. 持仓期间删除：优先删除已知持仓日，不足时退化为中部连续缺失。"""
    rng = random.Random(seed)
    deleted = 0
    detail: dict[str, dict] = {}
    holding_dates = holding_dates or {}
    for code in codes:
        if code not in holding_dates:
            continue
        held = [d for d in holding_dates[code] if start <= d <= end]
        if not held:
            continue
        take = max(1, int(len(held) * ratio))
        picked = sorted(rng.sample(held, min(take, len(held))))
        conn.executemany(
            "DELETE FROM etf_daily_prices WHERE code=? AND trade_date=?",
            [(code, day) for day in picked],
        )
        deleted += len(picked)
        detail[code] = {"deleted": len(picked), "mode": "actual_holding_dates"}
    return deleted, {"holding": detail}


def delete_signal_adjacent(
    conn: sqlite3.Connection, codes: list[str], start: str, end: str,
    ratio: float, seed: int, signal_dates: dict[str, list[str]] | None = None,
) -> tuple[int, dict]:
    """D. 信号附近删除：在给定信号日（含次日）删除行情。"""
    deleted = 0
    detail: dict[str, dict] = {}
    signal_dates = signal_dates or {}
    # 保护区间首尾各 3 个交易日：起始估值日被删空会让回测无法启动，
    # 那是「区间缺失」而不是「信号附近缺失」，会掩盖本场景要考察的问题
    for code in codes:
        days = [d for d in (signal_dates.get(code) or []) if start <= d <= end]
        protected = set(sorted(days)[:3]) | set(sorted(days)[-3:]) if len(days) > 6 else set(days)
        picked = sorted({d for d in days if d not in protected})
        if not picked:
            continue
        conn.executemany(
            "DELETE FROM etf_daily_prices WHERE code=? AND trade_date=?",
            [(code, day) for day in picked],
        )
        deleted += len(picked)
        detail[code] = {"deleted": len(picked), "dates": picked[:5]}
    return deleted, {"signal": detail}


def delete_then_recovery(
    conn: sqlite3.Connection, codes: list[str], start: str, end: str,
    ratio: float, seed: int,
) -> tuple[int, dict]:
    """E. 缺失后恢复：中部删除连续一段，前后行情完整。"""
    deleted, detail = delete_continuous_block(conn, codes, start, end, ratio, seed)
    detail["mode_note"] = "中部连续缺失，前后完整，用于检验恢复日行为"
    return deleted, detail


MODE_HANDLERS = {
    MODE_RANDOM: delete_random_scattered,
    MODE_BLOCK: delete_continuous_block,
    MODE_HOLDING: delete_holding_period,
    MODE_SIGNAL: delete_signal_adjacent,
    MODE_RECOVERY: delete_then_recovery,
}


def count_rows(conn: sqlite3.Connection, start: str, end: str) -> int:
    return int(conn.execute(
        "SELECT COUNT(*) FROM etf_daily_prices WHERE trade_date >= ? AND trade_date <= ?",
        (start, end),
    ).fetchone()[0])


def missing_trading_day_count(
    conn: sqlite3.Connection, start: str, end: str, calendar: list[str]
) -> int:
    """「至少一只 ETF 在该交易日无行情」的交易日数量。"""
    present = {
        str(row[0]) for row in conn.execute(
            "SELECT DISTINCT trade_date FROM etf_daily_prices "
            "WHERE trade_date >= ? AND trade_date <= ?",
            (start, end),
        )
    }
    return sum(1 for day in calendar if day not in present)


def source_fingerprint(db_path) -> str:
    """源库稳定指纹，用于证明压力测试未污染。"""
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        rows = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(close), 0), COALESCE(SUM(volume), 0), "
            "COALESCE(SUM(adjusted_close), 0) FROM etf_daily_prices"
        ).fetchone()
    text = f"{rows[0]}|{rows[1]:.6f}|{rows[2]:.6f}|{rows[3]:.6f}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def run_single_scenario(
    *,
    source_db,
    codes: list[str],
    start: str,
    end: str,
    calendar: list[str],
    ratio: float,
    mode: str,
    seed: int,
    indicator_version: str | None,
    initial_cash: float,
    workdir: Path,
    holding_dates: dict[str, list[str]] | None = None,
    signal_dates: dict[str, list[str]] | None = None,
) -> ScenarioResult:
    """执行一个删除场景：独立副本 → 删除 → 回测 → 统计。"""
    from app.backtest.config import BacktestConfig
    from app.backtest.data import load_calendar
    from app.backtest.engine import BacktestEngine
    from app.backtest.metrics import compute_performance, return_sample_stats
    from app.backtest.strategies.ma_trend import MovingAverageTrendStrategy

    scenario_id = f"{mode}_r{int(ratio * 100):02d}_s{seed}"
    result = ScenarioResult(
        scenario_id=scenario_id,
        deletion_ratio=ratio,
        deletion_mode=mode,
        random_seed=seed,
        etf_count=len(codes),
    )

    copy_db = copy_database(source_db, workdir, name=f"{scenario_id}.db")
    try:
        with sqlite3.connect(copy_db) as conn:
            conn.execute("PRAGMA temp_store=MEMORY")
            result.original_rows = count_rows(conn, start, end)
            # ratio == 0 是完整数据基准组，任何模式都不得删除行情
            if ratio <= 0:
                deleted, detail = 0, {"baseline": True}
                handler = None
            else:
                handler = MODE_HANDLERS[mode]
            if handler is None:
                pass
            elif mode == MODE_HOLDING:
                deleted, detail = handler(
                    conn, codes, start, end, ratio, seed,
                    holding_dates=holding_dates,
                )
            elif mode == MODE_SIGNAL:
                deleted, detail = handler(
                    conn, codes, start, end, ratio, seed,
                    signal_dates=signal_dates,
                )
            else:
                deleted, detail = handler(conn, codes, start, end, ratio, seed)
            conn.commit()
            result.deleted_rows = deleted
            result.remaining_rows = count_rows(conn, start, end)
            result.missing_trading_days = missing_trading_day_count(
                conn, start, end, calendar
            )
            result.detail = detail
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            result.detail["integrity_check"] = integrity

        if result.remaining_rows == 0:
            result.status = "insufficient"
            result.reason = "副本行情被完全删除，无法回测"
            return result

        config = BacktestConfig(
            start_date=start, end_date=end, initial_cash=initial_cash,
        )
        engine = BacktestEngine(config, MovingAverageTrendStrategy(ma_window=60),
                                db_path=copy_db)
        backtest = engine.run(codes, indicator_version=indicator_version)
        perf = compute_performance(
            backtest.daily, backtest.trades, backtest.orders, backtest.initial_cash,
        )
        stats = return_sample_stats(backtest.daily)

        result.valid_return_days = stats["valid_return_days"]
        result.missing_return_days = (
            stats["held_price_gap"] + stats["prior_day_price_gap"]
        )
        result.first_day_skipped = stats["first_day"]
        result.nan_days = stats["missing_nav"]
        result.stale_price_days = sum(
            1 for item in backtest.daily
            for status in item.price_status.values() if status == "stale_price"
        )
        result.buy_orders = sum(1 for o in backtest.orders if o.side == "buy")
        result.sell_orders = sum(1 for o in backtest.orders if o.side == "sell")
        result.trade_count = len(backtest.trades)
        result.partial_orders = sum(
            1 for o in backtest.orders if o.status == "partial"
        )
        result.rejected_orders = sum(
            1 for o in backtest.orders if o.status in ("rejected", "expired", "unfilled")
        )
        result.final_nav = float(backtest.daily[-1].nav) if backtest.daily else None
        result.total_return = perf.total_return
        result.cagr = perf.cagr
        result.sharpe = perf.sharpe_ratio
        result.sortino = perf.sortino_ratio
        result.max_drawdown = perf.max_drawdown
        result.final_cash = float(backtest.daily[-1].cash) if backtest.daily else None
        result.final_positions = sum(
            1 for value in (backtest.daily[-1].positions or {}).values() if value
        ) if backtest.daily else 0
        result.negative_cash_days = sum(
            1 for item in backtest.daily if item.cash < -1e-6
        )
        result.detail["return_sample_stats"] = stats

        # 状态只反映「数据完整性」影响，与策略自身产生多少部分成交无关
        if result.negative_cash_days > 0:
            result.status = "failed"
            result.reason = f"{result.negative_cash_days} 天现金为负"
        elif result.valid_return_days < 2:
            result.status = "insufficient"
            result.reason = f"有效日收益仅 {result.valid_return_days} 天，不足以计算风险指标"
        elif result.missing_return_days > 0:
            result.status = "partial"
            result.reason = (
                f"删除行情导致 {result.missing_return_days} 天收益观测缺失，"
                f"风险指标基于 {result.valid_return_days} 个有效样本"
            )
        elif ratio > 0 and result.deleted_rows == 0:
            result.status = "insufficient"
            result.reason = "该比例下未删除任何行情，场景未构成有效缺失"
        else:
            result.status = "success"
        return result
    except Exception as exc:  # noqa: BLE001 单场景失败不终止扫描
        result.status = "failed"
        result.reason = str(exc)[:220]
        return result


def run_sensitivity_matrix(
    *,
    source_db,
    codes: list[str],
    start: str,
    end: str,
    indicator_version: str | None = None,
    initial_cash: float = 1_000_000.0,
    seed: int = DEFAULT_SEED,
    ratios: tuple[float, ...] = DELETION_RATIOS,
    modes: tuple[str, ...] = DELETION_MODES,
    pool_label: str = "unknown",
    holding_dates: dict[str, list[str]] | None = None,
    signal_dates: dict[str, list[str]] | None = None,
    workroot: Path | None = None,
) -> dict:
    """执行完整的比例 × 模式矩阵。"""
    from app.backtest.data import load_calendar

    calendar = [
        day.isoformat() for day in load_calendar(start, end, db_path=source_db)
    ]
    if not calendar:
        raise SensitivityError("区间内没有交易日")

    fp_before = source_fingerprint(source_db)
    root = Path(workroot or tempfile.mkdtemp(prefix=f"sens_{pool_label}_"))
    results: list[ScenarioResult] = []
    try:
        for mode in modes:
            for ratio in ratios:
                scenario_dir = root / f"{mode}_{int(ratio * 100):02d}"
                scenario_dir.mkdir(parents=True, exist_ok=True)
                results.append(run_single_scenario(
                    source_db=source_db, codes=codes, start=start, end=end,
                    calendar=calendar, ratio=ratio, mode=mode, seed=seed,
                    indicator_version=indicator_version,
                    initial_cash=initial_cash, workdir=scenario_dir,
                    holding_dates=holding_dates, signal_dates=signal_dates,
                ))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    fp_after = source_fingerprint(source_db)
    return {
        "pool_label": pool_label,
        "etf_count": len(codes),
        "start": start,
        "end": end,
        "seed": seed,
        "ratios": list(ratios),
        "modes": list(modes),
        "scenario_count": len(results),
        "source_fingerprint_before": fp_before,
        "source_fingerprint_after": fp_after,
        "source_unchanged": fp_before == fp_after,
        "scenarios": [item.as_dict() for item in results],
    }


def summarize_matrix(payload: dict) -> dict:
    """按比例与模式汇总，供报告使用。"""
    rows = payload["scenarios"]
    by_ratio: dict[str, dict] = {}
    by_mode: dict[str, dict] = {}

    for row in rows:
        key = f"{row['deletion_ratio'] * 100:.0f}%"
        bucket = by_ratio.setdefault(
            key, {"count": 0, "returns": [], "sharpes": [],
                  "drawdowns": [], "statuses": []}
        )
        bucket["count"] += 1
        if row["total_return"] is not None:
            bucket["returns"].append(row["total_return"])
        if row["sharpe"] is not None:
            bucket["sharpes"].append(row["sharpe"])
        if row["max_drawdown"] is not None:
            bucket["drawdowns"].append(row["max_drawdown"])
        bucket["statuses"].append(row["status"])

        mkey = row["deletion_mode"]
        mbucket = by_mode.setdefault(
            mkey, {"count": 0, "returns": [], "statuses": []}
        )
        mbucket["count"] += 1
        if row["total_return"] is not None:
            mbucket["returns"].append(row["total_return"])
        mbucket["statuses"].append(row["status"])

    def _agg(bucket: dict) -> dict:
        out = dict(bucket)
        for field in ("returns", "sharpes", "drawdowns"):
            values = out.get(field) or []
            if values:
                out[f"{field}_mean"] = sum(values) / len(values)
                out[f"{field}_min"] = min(values)
                out[f"{field}_max"] = max(values)
            else:
                out[f"{field}_mean"] = None
                out[f"{field}_min"] = None
                out[f"{field}_max"] = None
        statuses = out["statuses"]
        out["status_counts"] = {
            status: statuses.count(status) for status in set(statuses)
        }
        return out

    return {
        "by_ratio": {key: _agg(value) for key, value in by_ratio.items()},
        "by_mode": {key: _agg(value) for key, value in by_mode.items()},
        "status_totals": {
            status: sum(1 for row in rows if row["status"] == status)
            for status in ("success", "partial", "insufficient", "failed")
        },
    }


def derive_holding_and_signal_dates(
    *,
    source_db,
    codes: list[str],
    start: str,
    end: str,
    indicator_version: str | None = None,
    initial_cash: float = 1_000_000.0,
    ma_window: int = 60,
) -> dict:
    """从基准（0% 删除）回测中提取真实持仓日与信号日。

    - holding_dates：某 ETF 当日持仓数量 > 0 的交易日
    - signal_dates：该 ETF 当日出现买卖信号（目标权重变化）的交易日及其次日
    """
    from app.backtest.config import BacktestConfig
    from app.backtest.engine import BacktestEngine
    from app.backtest.strategies.ma_trend import MovingAverageTrendStrategy

    config = BacktestConfig(
        start_date=start, end_date=end, initial_cash=initial_cash,
    )
    engine = BacktestEngine(
        config, MovingAverageTrendStrategy(ma_window=ma_window), db_path=source_db
    )
    backtest = engine.run(codes, indicator_version=indicator_version)

    holding: dict[str, list[str]] = {}
    for item in backtest.daily:
        for code, qty in (item.positions or {}).items():
            if qty:
                holding.setdefault(code, []).append(item.trade_date.isoformat())

    # 信号日：订单的 signal_date 与其下一交易日（撮合日）
    calendar = [item.trade_date.isoformat() for item in backtest.daily]
    next_day = {
        calendar[index]: calendar[index + 1]
        for index in range(len(calendar) - 1)
    }
    signals: dict[str, set] = {}
    for order in backtest.orders:
        day = order.signal_date.isoformat()
        signals.setdefault(order.code, set()).add(day)
        successor = next_day.get(day)
        if successor:
            signals[order.code].add(successor)

    return {
        "holding_dates": {code: sorted(days) for code, days in holding.items()},
        "signal_dates": {code: sorted(days) for code, days in signals.items()},
        "baseline_status": "success",
        "holding_code_count": len(holding),
        "signal_code_count": len(signals),
    }
