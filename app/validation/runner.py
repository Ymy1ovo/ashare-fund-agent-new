"""阶段3A.2 统一验证调度。

流程：
1. 加载日历、按真实覆盖过滤 ETF
2. 样本内外切分
3. 样本内参数网格 → 选最优参数
4. 样本外最终验证（只跑一次，不回流）
5. Walk-Forward 滚动验证
6. 市场环境分类与分组统计
7. 基准比较
8. 压力测试
9. 结论与持久化

不修改任何历史行情、指标、快照或历史回测记录。
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from datetime import date, datetime
from typing import Any

import pandas as pd

from app.backtest.config import BacktestConfig
from app.backtest.data import load_bars, load_calendar, load_pool
from app.backtest.engine import BacktestEngine
from app.backtest.metrics import compute_performance
from app.backtest.strategies.buy_and_hold import BuyAndHoldStrategy
from app.backtest.strategies.ma_trend import MovingAverageTrendStrategy
from app.database.db import get_connection
from app.validation.benchmark import (
    align_ranges,
    build_benchmarks,
    common_range,
)
from app.validation.config import ValidationConfig
from app.validation.regime import (
    REGIME_BEAR,
    REGIME_BULL,
    REGIME_RANGE,
    REGIME_UNCLASSIFIED,
    build_regime_series,
    regime_stats,
)
from app.validation.sensitivity import (
    GridCell,
    analyze_grid,
    attach_oos,
)
from app.validation.split import (
    filter_codes_by_coverage,
    split_time_range,
    warmup_note,
)
from app.validation.storage import (
    ValidationRecord,
    save_grid,
    save_stress,
    save_validation_run,
    save_windows,
)
from app.validation.stress import (
    assert_no_data_mutation,
    build_scenarios,
)


class ValidationError(RuntimeError):
    """验证任务无法继续。"""


def _available_proxies(candidates: list[str], split, db_path) -> list[str]:
    """检查代理标的在样本外区间是否有行情，避免构造出跑不了的基准。"""
    if not candidates:
        return []
    with get_connection(db_path) as conn:
        placeholders = ",".join("?" for _ in candidates)
        rows = conn.execute(
            f"SELECT DISTINCT code FROM etf_daily_prices WHERE code IN ({placeholders}) "
            "AND trade_date >= ? AND trade_date <= ?",
            (*candidates, split.oos_start, split.oos_end),
        ).fetchall()
    return [str(row[0]) for row in rows]


def _representative_pool(
    codes: list[str], pool: dict[str, dict], counts: dict[str, int]
) -> list[str]:
    """每个类别挑选历史最长（行数最多）的一只作为代表。

    这是样本规模与运行时间的权衡；报告中明确说明，不能当作全池结论。
    """
    by_category: dict[str, list[str]] = {}
    for code in codes:
        category = str(pool.get(code, {}).get("category") or "未知")
        by_category.setdefault(category, []).append(code)
    selected: list[str] = []
    for category in sorted(by_category):
        members = sorted(by_category[category], key=lambda c: (-counts.get(c, 0), c))
        selected.append(members[0])
    return sorted(selected)


def _progress(message: str) -> None:
    """验证进度输出到 stdout 与日志，便于观察长任务。"""
    import sys
    from datetime import datetime as _dt

    line = f"[{_dt.now().strftime('%H:%M:%S')}] {message}"
    print(line, flush=True)
    logger = __import__("logging").getLogger("app.validation")
    logger.info(message)


@dataclass
class ValidationResult:
    """一次验证的完整产出。"""

    validation_id: str
    config: ValidationConfig
    codes: list[str]
    excluded: list[dict]
    split: dict
    is_metrics: dict
    oos_metrics: dict
    grid: dict
    windows: list[dict]
    regime: dict
    benchmarks: list[dict]
    stress: list[dict]
    conclusion: str
    conclusion_reasons: list[str]
    notes: list[str] = field(default_factory=list)
    status: str = "success"
    error: str | None = None
    data_fingerprint: dict = field(default_factory=dict)


def _metrics_payload(performance, result) -> dict:
    return {
        "total_return": performance.total_return,
        "cagr": performance.cagr,
        "annualized_volatility": performance.annualized_volatility,
        "sharpe_ratio": performance.sharpe_ratio,
        "sortino_ratio": performance.sortino_ratio,
        "calmar_ratio": performance.calmar_ratio,
        "max_drawdown": performance.max_drawdown,
        "win_rate": performance.win_rate,
        "profit_loss_ratio": performance.profit_loss_ratio,
        "trade_count": performance.trade_count,
        "turnover": performance.turnover,
        "total_cost": performance.total_cost,
        "risk_sample_days": performance.risk_sample_days,
        "gap_return_days_excluded": performance.gap_return_days_excluded,
        "trading_days": performance.trading_days,
        "reconciliation_ok": None,
        "notes": list(performance.notes),
    }


def _run_backtest(
    config: BacktestConfig,
    strategy,
    codes: list[str],
    indicator_version: str | None,
    db_path=None,
) -> tuple[Any, Any, dict]:
    engine = BacktestEngine(config, strategy, db_path=db_path)
    result = engine.run(codes, indicator_version=indicator_version)
    performance = compute_performance(
        result.daily, result.trades, result.orders, result.initial_cash,
        annualization=config.annualization, risk_free_rate=config.risk_free_rate,
    )
    return result, performance, _metrics_payload(performance, result)


def _data_fingerprint(db_path=None) -> dict:
    """全字段行情指纹（v2），用于证明数据未被修改。

    覆盖 code/trade_date/open/high/low/close/volume/amount/adjusted_close/
    adjustment_snapshot_id，按 (code, trade_date) 排序后 SHA256。
    算法版本见 app.validation.fingerprint.FINGERPRINT_VERSION。
    """
    from app.validation.fingerprint import fingerprint_from_db

    return fingerprint_from_db(db_path=db_path)


def _input_hash(config: ValidationConfig, codes: list[str], fingerprint: dict) -> str:
    from app.validation.fingerprint import FINGERPRINT_VERSION

    payload = {
        "config": config.as_dict(),
        "codes": sorted(codes),
        "data": fingerprint,
        "fingerprint_version": FINGERPRINT_VERSION,
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _run_validation_unlocked(
    config: ValidationConfig | None = None,
    *,
    db_path=None,
    validation_id: str | None = None,
    stress_keys: list[str] | None = None,
) -> ValidationResult:
    """内部实现：执行完整验证流程，**不加锁**。

    只允许两个调用方使用：
    1. 公开入口 `run_validation()`（它负责加锁）
    2. 已经持有同一把锁的 `concurrency.run_with_write_lock()`

    直接调用本函数会绕过并发保护，仅供内部使用。
    """
    config = config or ValidationConfig()
    config.validate()
    vid = validation_id or uuid.uuid4().hex[:16]

    calendar = load_calendar(config.is_start, config.oos_end, db_path=db_path)
    if not calendar:
        raise ValidationError("验证区间内没有交易日")

    pool = load_pool(db_path=db_path)
    all_codes = sorted(pool)

    # 按真实覆盖过滤
    with get_connection(db_path) as conn:
        counts = {
            str(row[0]): int(row[1]) for row in conn.execute(
                "SELECT code, COUNT(*) FROM etf_daily_prices "
                "WHERE trade_date >= ? AND trade_date <= ? GROUP BY code",
                (config.is_start, config.oos_end),
            )
        }
    with get_connection(db_path) as conn:
        first_dates = {
            str(row[0]): str(row[1]) for row in conn.execute(
                "SELECT code, MIN(trade_date) FROM etf_daily_prices GROUP BY code"
            )
        }
    if config.exclude_insufficient:
        codes, excluded = filter_codes_by_coverage(
            counts, len(calendar), config.min_coverage_ratio,
            code_first_dates=first_dates,
            required_first_date=calendar[0].isoformat(),
        )
    else:
        codes, excluded = [code for code in all_codes if code in counts], []

    if config.pool_mode == "representative":
        codes = _representative_pool(codes, pool, counts)
        excluded.append({
            "code": "(其余合格标的)",
            "rows": 0,
            "calendar_days": len(calendar),
            "coverage": 0.0,
            "reason": "representative_pool",
            "note": f"representative 模式每类只取 1 只，共 {len(codes)} 只参与验证",
        })

    if len(codes) < 2:
        raise ValidationError(f"可用 ETF 不足：{len(codes)} 只")

    split = split_time_range(calendar, config)

    fingerprint_before = _data_fingerprint(db_path)
    input_hash = _input_hash(config, codes, fingerprint_before)

    record = ValidationRecord(
        validation_id=vid,
        strategy_name=config.strategy_name,
        strategy_version=config.strategy_version,
        config_hash=config.params_hash(),
        eth_codes=codes,
        ma_window_grid=list(config.ma_window_grid),
        is_start=split.is_start,
        is_end=split.is_end,
        oos_start=split.oos_start,
        oos_end=split.oos_end,
        status="running",
        input_hash=input_hash,
        excluded_codes=excluded,
    )
    save_validation_run(record, db_path=db_path)

    notes: list[str] = []
    try:
        # ---------- 1. 样本内参数网格 ----------
        _progress(f"开始样本内参数网格：{len(config.ma_window_grid)} 个档位")
        cells: list[GridCell] = []
        for window in config.ma_window_grid:
            try:
                cfg = config.build_backtest_config(split.is_start, split.is_end)
                strategy = MovingAverageTrendStrategy(ma_window=window)
                _, _, metrics = _run_backtest(
                    cfg, strategy, codes, config.indicator_version, db_path
                )
                cells.append(GridCell(window, "success", metrics))
                _progress(f"  样本内 MA{window} 完成：Sharpe={metrics.get('sharpe_ratio')}")
            except Exception as exc:  # noqa: BLE001 单格失败不终止整体
                cells.append(GridCell(window, "failed", reason=str(exc)[:200]))
        analysis = analyze_grid(cells, grid_order=tuple(config.ma_window_grid))

        if analysis.best_param is None:
            raise ValidationError("样本内没有任何可用参数组合")

        # ---------- 2. 样本外只验证一次 ----------
        best_window = analysis.best_param
        _progress(f"样本内选参完成：MA{best_window}")
        oos_cfg = config.build_backtest_config(split.oos_start, split.oos_end)
        oos_strategy = MovingAverageTrendStrategy(ma_window=best_window)
        _, oos_perf, oos_metrics = _run_backtest(
            oos_cfg, oos_strategy, codes, config.indicator_version, db_path
        )
        oos_cell = GridCell(best_window, "success", oos_metrics)
        attach_oos(analysis, oos_cell)

        # 样本内最优参数的指标（供基准与报告引用）
        is_cell = next(cell for cell in cells if cell.ma_window == best_window)

        # ---------- 3. Walk-Forward ----------
        from app.validation.walkforward import (
            assert_no_leakage,
            build_windows,
            select_best_param,
        )

        windows = build_windows(calendar, config)
        _progress(f"Walk-Forward 窗口数：{len(windows)}，每窗 {len(config.wf_grid)} 个候选参数")
        assert_no_leakage(windows)
        window_rows: list[dict] = []

        for window in windows:
            if window.status == "insufficient_data":
                window_rows.append(window.as_dict())
                continue
            train_results: dict[int, dict] = {}
            for candidate in config.wf_grid:
                try:
                    cfg = config.build_backtest_config(
                        window.train_start.isoformat(), window.train_end.isoformat()
                    )
                    _, _, metrics = _run_backtest(
                        cfg, MovingAverageTrendStrategy(ma_window=candidate),
                        codes, config.indicator_version, db_path,
                    )
                    train_results[candidate] = {"status": "success", **metrics}
                except Exception as exc:
                    train_results[candidate] = {"status": "failed", "reason": str(exc)[:200]}
            selected, reason = select_best_param(train_results)
            _progress(f"窗口 {window.index}: 选中 MA{selected}")
            if selected is None:
                window.status = "failed"
                window.reason = reason
                window_rows.append(window.as_dict())
                continue
            window.selected_param = selected
            window.train_metrics = train_results[selected]
            try:
                cfg = config.build_backtest_config(
                    window.test_start.isoformat(), window.test_end.isoformat()
                )
                _, _, test_metrics = _run_backtest(
                    cfg, MovingAverageTrendStrategy(ma_window=selected),
                    codes, config.indicator_version, db_path,
                )
                window.test_metrics = test_metrics
                window.status = "success"
            except Exception as exc:
                window.status = "failed"
                window.reason = str(exc)[:200]
            window_rows.append(window.as_dict())

        _progress("Walk-Forward 完成，开始市场环境分类")
        regime_payload = _build_regime_payload(
            config, split, oos_cfg, oos_strategy, codes, db_path
        )
        _progress("市场环境完成，开始基准回测")
        bench_rows = _build_benchmarks_rows(
            config, split, codes, best_window, db_path
        )
        _progress("基准完成，开始压力测试")
        stress_rows = _build_stress_rows(
            config, split, codes, best_window, stress_keys, db_path
        )

        fingerprint_after = _data_fingerprint(db_path)
        assert_no_data_mutation(fingerprint_before, fingerprint_after, "all")

        conclusion, reasons = decide_conclusion(
            analysis, oos_metrics, window_rows, regime_payload, stress_rows
        )

        notes.extend(split.notes)
        notes.append(warmup_note(best_window))

        result = ValidationResult(
            validation_id=vid,
            config=config,
            codes=codes,
            excluded=excluded,
            split=split.as_dict(),
            is_metrics=is_cell.metrics,
            oos_metrics=oos_metrics,
            grid=analysis.as_dict(),
            windows=window_rows,
            regime=regime_payload,
            benchmarks=bench_rows,
            stress=stress_rows,
            conclusion=conclusion,
            conclusion_reasons=reasons,
            notes=notes,
            data_fingerprint=fingerprint_before,
        )

        summary = {
            "conclusion": conclusion,
            "conclusion_reasons": reasons,
            "is_metrics": is_cell.metrics,
            "oos_metrics": oos_metrics,
            "best_param": best_window,
            "window_count": len(window_rows),
            "window_success": sum(1 for row in window_rows if row["status"] == "success"),
            "data_fingerprint": fingerprint_before,
            "fingerprint_after": fingerprint_after,
        }
        record.status = "success"
        record.conclusion = conclusion
        record.summary = summary
        record.notes = notes
        save_validation_run(record, db_path=db_path)
        save_windows(vid, window_rows, db_path=db_path)
        save_grid(vid, "in_sample", [cell.as_dict() for cell in cells], db_path=db_path)
        save_grid(vid, "out_of_sample", [oos_cell.as_dict()], db_path=db_path)
        save_stress(vid, stress_rows, db_path=db_path)
        return result

    except Exception as exc:
        record.status = "failed"
        record.error_message = str(exc)[:500]
        save_validation_run(record, db_path=db_path)
        raise ValidationError(str(exc)) from exc


def _build_regime_payload(
    config: ValidationConfig, split, oos_cfg, oos_strategy, codes, db_path
) -> dict:
    """市场环境分类与分组统计。

    关键：加载 OOS 之前的预热数据用于 MA250 初始化。
    预热数据只参与 MA 计算，不进入 labels，也不进入 OOS 绩效。
    """
    from app.backtest.metrics import risk_return_series

    try:
        proxy = load_bars(
            config.regime_proxy_code, split.oos_start, split.oos_end,
            indicator_version=None, db_path=db_path,
        )
        naive_close = proxy.adjusted_close.fillna(proxy.frame["close"])
        naive = build_regime_series(naive_close, code=config.regime_proxy_code)
        warmup_days = sum(1 for label in naive.labels.values()
                          if label == REGIME_UNCLASSIFIED)
    except Exception as exc:
        return {"labels_available": False, "error": str(exc)[:200]}

    # 预热：额外取 OOS 起点之前的历史数据，按真实交易日计数
    try:
        warmup = _load_regime_warmup(
            config.regime_proxy_code, split.oos_start, db_path=db_path
        )
        # 两段索引必须统一为 DatetimeIndex，否则 Timestamp 与 date 无法比较
        warm_series = warmup["close"].copy()
        if not isinstance(warm_series.index, pd.DatetimeIndex):
            warm_series.index = pd.DatetimeIndex([pd.Timestamp(d) for d in warm_series.index])
        naive_series = naive_close.copy()
        if not isinstance(naive_series.index, pd.DatetimeIndex):
            naive_series.index = pd.DatetimeIndex([pd.Timestamp(d) for d in naive_series.index])
        combined = pd.concat([warm_series, naive_series]).sort_index()
        combined = combined[~combined.index.duplicated(keep="last")]
        regime_series = build_regime_series(
            combined,
            code=config.regime_proxy_code,
            output_start=date.fromisoformat(split.oos_start),
        )
        required = config.regime_ma_window
        valid = warmup["valid_prices"]
        if valid >= required:
            warmup_status = "ok"
        elif valid > 0:
            warmup_status = "partial"
        else:
            warmup_status = "unavailable"
        warmup_reason = (
            f"有效价格 {valid} 个（需求 {required}），"
            f"数据库记录 {warmup['db_rows']} 条，无效价格 {warmup['invalid_prices']} 条"
        )
    except Exception as exc:
        return {
            "labels_available": False,
            "error": f"预热加载失败：{str(exc)[:180]}",
            "proxy_code": config.regime_proxy_code,
        }

    try:
        engine = BacktestEngine(oos_cfg, oos_strategy, db_path=db_path)
        oos_result = engine.run(codes, indicator_version=config.indicator_version)
        oos_nav, oos_returns, oos_statuses = risk_return_series(oos_result.daily)
        from app.backtest.metrics import return_sample_stats

        oos_stats = return_sample_stats(oos_result.daily)

        # 构建带原始交易日索引的日收益序列：缺失日保留 NaN，绝不 dropna 后再统计
        index = pd.DatetimeIndex([pd.Timestamp(item.trade_date) for item in oos_result.daily])
        return_series = pd.Series(
            [
                float(item["raw_return"]) if item["raw_return"] is not None else float("nan")
                for item in oos_statuses
            ],
            index=index,
            dtype=float,
        )
        for position, item in enumerate(oos_statuses):
            if item["return_status"] in ("held_price_gap", "prior_day_price_gap"):
                return_series.iloc[position] = float("nan")

        label_map = {
            pd.Timestamp(day).date(): label
            for day, label in regime_series.labels.items()
        }
        stats = regime_stats(return_series, label_map)

        gap_days = sum(
            1 for item in oos_statuses
            if item["return_status"] in ("held_price_gap", "prior_day_price_gap")
        )
        return {
            "labels_available": True,
            "proxy_code": config.regime_proxy_code,
            "proxy_note": "数据库无独立指数表，使用沪深300ETF代理，含跟踪误差",
            "warmup": {
                "db_rows": warmup["db_rows"],
                "valid_prices": warmup["valid_prices"],
                "invalid_prices": warmup["invalid_prices"],
                "days": warmup["valid_prices"],
                "required": required,
                "status": warmup_status,
                "reason": warmup_reason,
                "source": warmup["source"],
            },
            "output_range": {
                "start": regime_series.first_day.isoformat() if regime_series.first_day else None,
                "end": regime_series.last_day.isoformat() if regime_series.last_day else None,
                "oos_start": split.oos_start,
                "oos_end": split.oos_end,
            },
            "summary": regime_series.summary(),
            "stats": stats,
            "oos_return_diagnostics": {
                "nav_days": oos_stats["nav_days"],
                "first_day": oos_stats["first_day"],
                "valid_return_days": oos_stats["valid_return_days"],
                "gap_days_excluded": (
                    oos_stats["held_price_gap"] + oos_stats["prior_day_price_gap"]
                ),
                "missing_nav": oos_stats["missing_nav"],
                "identity_holds": oos_stats["identity_holds"],
                "definition": oos_stats["definition"],
                "presentation": "NaN 保留在原始交易日索引上，未压缩缺失日",
            },
        }
    except Exception as exc:
        return {
            "labels_available": False,
            "error": str(exc)[:200],
            "proxy_code": config.regime_proxy_code,
        }


def _load_regime_warmup(code: str, oos_start: str, *, db_path=None) -> dict:
    """取 OOS 起点之前的全部历史收盘价，用于 MA 预热。

    严格按 trade_date 升序，且只取 trade_date < oos_start 的记录，
    不会读到 OOS 之后的数据，也不向前填充价格。

    统计口径区分三个量：
    - db_rows：数据库记录数
    - valid_prices：有效价格观测数（非 NaN、非 None、> 0）
    - days：与 valid_prices 一致，用于判断是否满足 MA 需求
    """
    from app.database.db import get_connection

    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT trade_date, adjusted_close, close FROM etf_daily_prices "
            "WHERE code=? AND trade_date < ? ORDER BY trade_date",
            (code, oos_start),
        ).fetchall()

    if not rows:
        return {
            "db_rows": 0,
            "valid_prices": 0,
            "days": 0,
            "invalid_prices": 0,
            "close": pd.Series(dtype=float),
            "source": "etf_daily_prices",
            "first": None,
            "last": None,
        }

    index: list = []
    values: list = []
    invalid = 0
    for trade_date, adjusted_close, close in rows:
        price = adjusted_close if adjusted_close is not None else close
        try:
            number = float(price)
        except (TypeError, ValueError):
            number = float("nan")
        if number != number or number <= 0:  # NaN 或 非正价格
            invalid += 1
            continue
        index.append(pd.Timestamp(str(trade_date)))
        values.append(number)

    return {
        "db_rows": len(rows),
        "valid_prices": len(values),
        "days": len(values),
        "invalid_prices": invalid,
        "close": pd.Series(values, index=pd.DatetimeIndex(index), dtype=float),
        "source": "etf_daily_prices",
        "first": str(rows[0][0]),
        "last": str(rows[-1][0]),
    }


def _build_benchmarks_rows(
    config: ValidationConfig, split, codes, best_window, db_path
) -> list[dict]:
    """基准策略回测与区间对齐。"""
    proxy_codes = [
        code for code in (
            __import__("app.validation.config", fromlist=["x"]).BENCHMARK_HS300_PROXY,
            __import__("app.validation.config", fromlist=["x"]).BENCHMARK_ZZ500_PROXY,
        )
    ]
    verdict = _available_proxies(proxy_codes, split, db_path)
    specs = build_benchmarks(
        codes, config, best_ma_window=best_window, extra_codes=verdict
    )
    with get_connection(db_path) as conn:
        avail = {
            str(row[0]): (str(row[1]), str(row[2])) for row in conn.execute(
                "SELECT code, MIN(trade_date), MAX(trade_date) FROM etf_daily_prices "
                "WHERE trade_date >= ? AND trade_date <= ? GROUP BY code",
                (split.oos_start, split.oos_end),
            )
        }
    coverage_rows = align_ranges(specs, avail)
    by_key = {row["key"]: row for row in coverage_rows}
    rows: list[dict] = []
    for spec in specs:
        coverage = by_key.get(spec.key, {})
        if coverage.get("status") != "ok":
            rows.append({
                "key": spec.key, "name": spec.name, "status": "insufficient_data",
                "reason": coverage.get("reason", "数据不足"), "spec": spec.as_dict(),
            })
            continue
        start = max(coverage["coverage_start"], split.oos_start)
        end = min(coverage["coverage_end"], split.oos_end)
        try:
            cfg = config.build_backtest_config(start, end)
            strategy = (
                BuyAndHoldStrategy() if spec.kind == "buy_and_hold"
                else MovingAverageTrendStrategy(ma_window=spec.ma_window or 20)
            )
            _, _, metrics = _run_backtest(
                cfg, strategy, spec.codes, config.indicator_version, db_path
            )
            rows.append({
                "key": spec.key, "name": spec.name, "status": "success",
                "range": f"{start}~{end}", "metrics": metrics, "spec": spec.as_dict(),
            })
        except Exception as exc:
            rows.append({
                "key": spec.key, "name": spec.name, "status": "failed",
                "reason": str(exc)[:200], "spec": spec.as_dict(),
            })
    return rows


def _build_stress_rows(
    config: ValidationConfig, split, codes, best_window, stress_keys, db_path
) -> list[dict]:
    """压力测试：成本类只改配置，数据类在独立副本上执行。

    数据类场景不修改真实行情；执行完立即核对指纹。
    """
    rows: list[dict] = []
    for scenario in build_scenarios(stress_keys):
        if scenario.kind == "data":
            rows.append(_run_data_stress(
                scenario, config, split, codes, best_window, db_path
            ))
            continue
        overrides = scenario.apply(config)
        try:
            cfg = config.build_backtest_config(
                split.oos_start, split.oos_end, **overrides
            )
            _, _, metrics = _run_backtest(
                cfg, MovingAverageTrendStrategy(ma_window=best_window),
                codes, config.indicator_version, db_path,
            )
            rows.append({
                "key": scenario.key, "name": scenario.name,
                "is_hypothetical": scenario.is_hypothetical,
                "status": "success",
                "config": {**scenario.as_dict(), "overrides": overrides},
                "metrics": metrics,
            })
        except Exception as exc:
            rows.append({
                "key": scenario.key, "name": scenario.name,
                "is_hypothetical": scenario.is_hypothetical,
                "status": "failed", "reason": str(exc)[:200],
                "config": {**scenario.as_dict(), "overrides": overrides},
            })
    return rows


def _run_data_stress(
    scenario, config: ValidationConfig, split, codes, best_window, db_path
) -> dict:
    """执行数据类压力场景（sparse_data / insufficient）。"""
    import tempfile
    from datetime import date as _date

    from app.backtest.metrics import risk_return_series
    from app.validation.stress import (
        INSUFFICIENT_SCENARIO_KEY,
        evaluate_insufficient_result,
        evaluate_sparse_result,
    )

    from app.config import settings

    resolved_db = db_path or settings.database_path
    base = {
        "key": scenario.key,
        "name": scenario.name,
        "is_hypothetical": scenario.is_hypothetical,
        "config": scenario.as_dict(),
    }

    if scenario.key == "sparse_data":
        try:
            from app.validation.stress import build_sparse_copy

            workdir = tempfile.mkdtemp(prefix="val_sparse_")
            copy_info = build_sparse_copy(
                resolved_db, workdir,
                start_date=split.oos_start, end_date=split.oos_end,
            )
            copy_db = Path(copy_info["copy_path"])  # get_connection 需要 pathlib.Path
            cfg = config.build_backtest_config(split.oos_start, split.oos_end)
            result, performance, metrics = _run_backtest(
                cfg, MovingAverageTrendStrategy(ma_window=best_window),
                codes, config.indicator_version, copy_db,
            )
            # 统一口径：所有计数来自 return_sample_stats()
            from app.backtest.metrics import return_sample_stats

            stats_counts = return_sample_stats(result.daily)
            evaluation = evaluate_sparse_result(
                daily_rows=stats_counts["nav_days"],
                valid_return_days=stats_counts["valid_return_days"],
                gap_days_excluded=(
                    stats_counts["held_price_gap"]
                    + stats_counts["prior_day_price_gap"]
                ),
                first_day_skipped=stats_counts["first_day"],
                missing_nav_days=stats_counts["missing_nav"],
            )
            evaluation["return_sample_stats"] = stats_counts
            return {
                **base,
                "status": evaluation["status"],
                "metrics": metrics,
                "data_copy": copy_info,
                "evaluation": evaluation,
                "reason": (
                    f"独立副本 {copy_info['copy_path']}；"
                    f"删除零散 {copy_info['removed_scattered']} 行、"
                    f"连续缺失 {copy_info['removed_blocks']} 行；"
                    f"快照 {evaluation['daily_rows']} 天 = "
                    f"首日 {evaluation['first_day_skipped']} + "
                    f"缺口 {evaluation['gap_days_excluded']} + "
                    f"缺净值 {evaluation['missing_nav_days']} + "
                    f"有效 {evaluation['valid_return_days']}"
                ),
            }
        except Exception as exc:
            return {**base, "status": "failed", "reason": f"sparse 执行失败：{str(exc)[:180]}"}

    if scenario.key == "insufficient":
        try:
            # 人为缩短到约 40 个交易日，远低于最小样本阈值
            calendar = load_calendar(
                config.is_start, config.oos_end, db_path=db_path
            )
            short_start = next(
                (day for day in calendar if day >= _date.fromisoformat("2025-01-02")),
                calendar[0],
            ) if calendar else None
            index = calendar.index(short_start) if short_start in calendar else 0
            short_end = calendar[min(index + 40, len(calendar) - 1)]

            cfg = config.build_backtest_config(
                short_start.isoformat(), short_end.isoformat()
            )
            trading_days = index_span = len(
                [d for d in calendar if short_start <= d <= short_end]
            )
            metrics: dict = {}
            run_error = None
            try:
                result, performance, metrics = _run_backtest(
                    cfg, MovingAverageTrendStrategy(ma_window=best_window),
                    codes, config.indicator_version, db_path,
                )
                trading_days = len(result.daily)
            except Exception as exc:  # 数据不足时回测本身可能无法完成
                run_error = str(exc)[:180]

            # 样本不足时不得对外呈现 Sharpe/CAGR：先记录原始值用于判定，
            # 判定完成后把 metrics 清空，避免被当作正常绩效指标读取
            raw_sharpe = metrics.get("sharpe_ratio")
            raw_cagr = metrics.get("cagr")
            evaluation = evaluate_insufficient_result(
                trading_days=trading_days,
                min_required=config.min_validation_days,
                sharpe=raw_sharpe,
                cagr=raw_cagr,
            )
            if raw_sharpe is not None or raw_cagr is not None:
                evaluation["raw_metrics_withheld"] = {
                    "sharpe_ratio": raw_sharpe,
                    "cagr": raw_cagr,
                    "note": "样本不足，指标已隐藏，不作为验证结论依据",
                }
            metrics = {}
            if run_error:
                evaluation["run_error"] = run_error
                evaluation["reason"] = (
                    evaluation["reason"] + f"；回测因样本不足未能完成：{run_error}"
                )
            return {
                **base,
                # 数据不足是场景的预期结论，标记为 insufficient 而非 failed
                "status": evaluation["status"],
                "metrics": {},
                "evaluation": evaluation,
                "reason": evaluation["reason"],
                "range": f"{short_start}~{short_end}",
                "expected_outcome": True,
            }
        except Exception as exc:
            return {**base, "status": "failed", "reason": f"insufficient 执行失败：{str(exc)[:180]}"}

    return {**base, "status": "skipped", "reason": f"未实现的数据场景：{scenario.key}"}


def decide_conclusion(
    analysis,
    oos_metrics: dict,
    windows: list[dict],
    regime: dict,
    stress: list[dict],
) -> tuple[str, list[str]]:
    """按证据给出结论。只用三类结论，不看单一收益数字。"""
    supports: list[str] = []
    blockers: list[str] = []

    oos_sharpe = oos_metrics.get("sharpe_ratio")
    oos_return = oos_metrics.get("total_return")
    oos_dd = oos_metrics.get("max_drawdown")
    is_sharpe = analysis.best_sharpe

    if oos_sharpe is None:
        blockers.append("样本外 Sharpe 无法计算（样本不足或波动为 0）")
    elif oos_sharpe <= 0:
        blockers.append(f"样本外 Sharpe = {oos_sharpe:.4f}，不为正")
    else:
        supports.append(f"样本外 Sharpe = {oos_sharpe:.4f}，为正")

    if oos_return is None:
        blockers.append("样本外总收益无法计算")
    elif oos_return <= 0:
        blockers.append(f"样本外总收益 = {oos_return:.2%}，不为正")
    else:
        supports.append(f"样本外总收益 = {oos_return:.2%}，为正")

    if is_sharpe is not None and oos_sharpe is not None and is_sharpe > 0:
        retain = oos_sharpe / is_sharpe
        if retain < 0.3:
            blockers.append(f"样本外 Sharpe 仅为样本内的 {retain:.1%}，衰减严重")
        elif retain >= 0.5:
            supports.append(f"样本外 Sharpe 保留样本内的 {retain:.1%}")

    ok_windows = [row for row in windows if row.get("status") == "success"]
    if not ok_windows:
        blockers.append("没有任何成功的 Walk-Forward 窗口")
    else:
        positive = [
            row for row in ok_windows
            if ((row.get("test_metrics") or {}).get("total_return") or 0) > 0
        ]
        ratio = len(positive) / len(ok_windows)
        if ratio < 0.5:
            blockers.append(
                f"Walk-Forward 仅 {len(positive)}/{len(ok_windows)} 个窗口验证期为正收益"
            )
        else:
            supports.append(
                f"Walk-Forward {len(positive)}/{len(ok_windows)} 个窗口验证期为正收益"
            )
        if len(ok_windows) < 3:
            blockers.append(f"有效 Walk-Forward 窗口只有 {len(ok_windows)} 个，样本不足")

    risk_flags = getattr(analysis, "risk_flags", [])
    if risk_flags:
        blockers.extend(risk_flags)

    if regime.get("labels_available"):
        stats = regime.get("stats", {})
        covered = [
            label for label in (REGIME_BULL, REGIME_BEAR, REGIME_RANGE)
            if stats.get(label, {}).get("status") == "ok"
        ]
        if len(covered) < 2:
            blockers.append("市场环境样本覆盖不足 2 类，无法判断跨环境稳定性")
        else:
            supports.append(f"市场环境覆盖 {len(covered)} 类且样本充足")
    else:
        blockers.append("市场环境分类不可用")

    failed_stress = [
        row for row in stress
        if row.get("status") == "failed" and not row.get("expected_outcome")
    ]
    if failed_stress:
        blockers.append(f"{len(failed_stress)} 个压力场景执行失败")
    if oos_dd is not None and oos_dd < -0.30:
        blockers.append(f"样本外最大回撤 {oos_dd:.2%} 超过 30%")

    if not blockers:
        return "通过", supports
    if len(supports) >= 2 and len(blockers) <= 2:
        return "有条件通过", supports + [f"限制：{item}" for item in blockers]
    return "不通过", [f"限制：{item}" for item in blockers[:8]] + supports

# 内部持锁标记：通过 contextvars 传递，不依赖全局布尔变量。
# 作用：允许「已持锁的内部调用」再次进入公开入口时不重复加锁，
# 同时不会影响其他线程（每个执行上下文独立）。
_LOCK_DEPTH: "contextvars.ContextVar[int]" = contextvars.ContextVar(
    "validation_lock_depth", default=0
)


def validation_lock_held() -> bool:
    """当前执行上下文是否已经持有验证锁。"""
    return _LOCK_DEPTH.get() > 0


def _acquire_and_run(config, *, db_path, validation_id, stress_keys):
    """真正加锁并执行的内部函数。"""
    from app.validation.concurrency import run_with_write_lock

    token = _LOCK_DEPTH.set(_LOCK_DEPTH.get() + 1)
    try:
        return run_with_write_lock(
            _run_validation_unlocked,
            config,
            db_path=db_path,
            validation_id=validation_id,
            stress_keys=stress_keys,
            db_path_lock=db_path,
        )
    finally:
        _LOCK_DEPTH.reset(token)


def run_validation(
    config: ValidationConfig | None = None,
    *,
    db_path=None,
    validation_id: str | None = None,
    stress_keys: list[str] | None = None,
) -> ValidationResult:
    """统一验证入口：**自动经过全流程串行锁**。

    设计（阶段3A.2.1.2.2）：
    - 所有正式数据库调用都走这里，调用方不需要自己加锁；
    - 锁文件固定为数据库同目录的 `.validation_write.lock`
      （临时库则跟随临时库目录，保持测试可配置）；
    - 若当前执行上下文已经持锁（内部调用），直接执行不再加锁，避免自锁死；
    - 锁超时抛 ConcurrencyError，调用方记录 failed，不伪装成功。

    绕过方式只有 `_run_validation_unlocked()`，它是内部函数，不对外承诺。
    """
    if validation_lock_held():
        # 已持锁的内部调用：不再重复加锁
        return _run_validation_unlocked(
            config, db_path=db_path, validation_id=validation_id,
            stress_keys=stress_keys,
        )
    return _acquire_and_run(
        config, db_path=db_path, validation_id=validation_id,
        stress_keys=stress_keys,
    )
