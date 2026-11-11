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

import hashlib
import json
import uuid
from dataclasses import dataclass, field
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
    """行情指纹：用于证明压力测试没有改动历史数据。"""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(close), 0), COALESCE(SUM(volume), 0) "
            "FROM etf_daily_prices"
        ).fetchone()
    return {"rows": int(rows[0]), "close_sum": round(float(rows[1]), 4),
            "volume_sum": round(float(rows[2]), 4)}


def _input_hash(config: ValidationConfig, codes: list[str], fingerprint: dict) -> str:
    payload = {
        "config": config.as_dict(),
        "codes": sorted(codes),
        "data": fingerprint,
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def run_validation(
    config: ValidationConfig | None = None,
    *,
    db_path=None,
    validation_id: str | None = None,
    stress_keys: list[str] | None = None,
) -> ValidationResult:
    """执行完整验证流程。"""
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
    """市场环境分类与分组统计。"""
    from app.backtest.metrics import risk_return_series

    try:
        proxy = load_bars(
            config.regime_proxy_code, split.oos_start, split.oos_end,
            indicator_version=None, db_path=db_path,
        )
        close = proxy.adjusted_close.fillna(proxy.frame["close"])
        regime_series = build_regime_series(close, code=config.regime_proxy_code)

        _, oos_perf, _ = _run_backtest(
            oos_cfg, oos_strategy, codes, config.indicator_version, db_path
        )
        engine = BacktestEngine(oos_cfg, oos_strategy, db_path=db_path)
        oos_result = engine.run(codes, indicator_version=config.indicator_version)
        _, oos_returns, _ = risk_return_series(oos_result.daily)
        returns_by_day = {
            stamp.date(): float(value) for stamp, value in oos_returns.items()
        }
        stats = regime_stats(
            returns_by_day,
            {day: regime_series.label_at(day) for day in returns_by_day},
        )
        return {
            "labels_available": True,
            "proxy_code": config.regime_proxy_code,
            "proxy_note": "数据库无独立指数表，使用沪深300ETF代理，含跟踪误差",
            "summary": regime_series.summary(),
            "stats": stats,
        }
    except Exception as exc:
        return {"labels_available": False, "error": str(exc)[:200]}


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
    """压力测试：只改成本参数，不改历史数据。"""
    rows: list[dict] = []
    for scenario in build_scenarios(stress_keys):
        if scenario.kind == "data":
            rows.append({
                "key": scenario.key, "name": scenario.name,
                "is_hypothetical": scenario.is_hypothetical,
                "status": "skipped",
                "reason": "数据类场景由覆盖过滤与区间校验体现，本次不重复回测",
                "config": scenario.as_dict(),
            })
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

    failed_stress = [row for row in stress if row.get("status") == "failed"]
    if failed_stress:
        blockers.append(f"{len(failed_stress)} 个压力场景执行失败")
    if oos_dd is not None and oos_dd < -0.30:
        blockers.append(f"样本外最大回撤 {oos_dd:.2%} 超过 30%")

    if not blockers:
        return "通过", supports
    if len(supports) >= 2 and len(blockers) <= 2:
        return "有条件通过", supports + [f"限制：{item}" for item in blockers]
    return "不通过", [f"限制：{item}" for item in blockers[:8]] + supports
