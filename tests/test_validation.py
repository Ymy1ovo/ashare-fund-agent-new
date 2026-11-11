"""阶段3A.2 策略验证体系测试。

全部使用人工构造数据，不依赖网络与真实行情库。
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.validation.config import (
    MA_WINDOW_GRID,
    ValidationConfig,
    ValidationConfigError,
    coverage_ok,
)
from app.validation.split import (
    SplitError,
    filter_codes_by_coverage,
    split_time_range,
    warmup_note,
)


def _calendar(start: str, end: str) -> list[date]:
    """生成工作日日历（人工构造，不含节假日逻辑）。"""
    begin = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    days = []
    current = begin
    while current <= stop:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def _config(**kwargs) -> ValidationConfig:
    base = dict(
        is_start="2021-01-01", is_end="2021-12-31",
        oos_start="2022-01-01", oos_end="2022-12-31",
    )
    base.update(kwargs)
    return ValidationConfig(**base)


# ---------------------------------------------------------- 配置校验

def test_config_rejects_overlapping_is_and_oos() -> None:
    """样本内外时间必须严格分离。"""
    with pytest.raises(ValidationConfigError, match="严格分离"):
        ValidationConfig(
            is_start="2021-01-01", is_end="2024-12-31",
            oos_start="2024-06-01", oos_end="2026-11-09",
        ).validate()


def test_config_rejects_inverted_range() -> None:
    with pytest.raises(ValidationConfigError, match="必须早于"):
        ValidationConfig(is_start="2024-01-01", is_end="2021-01-01").validate()


def test_config_rejects_negative_costs() -> None:
    with pytest.raises(ValidationConfigError, match="成本参数"):
        _config(commission_rate=-0.001).validate()


def test_config_params_hash_is_reproducible() -> None:
    """相同配置必须产生相同 hash；不同配置必须不同。"""
    a = _config()
    b = _config()
    c = _config(ma_window_grid=(5, 20))
    assert a.params_hash() == b.params_hash()
    assert a.params_hash() != c.params_hash()


def test_config_default_grid_comes_from_real_indicator_columns() -> None:
    """参数网格必须取自项目已有指标列，不是凭空创造的参数。"""
    assert MA_WINDOW_GRID == (5, 10, 20, 30, 60, 120, 250)


def test_coverage_ok_threshold() -> None:
    assert coverage_ok(950, 1000, 0.95) is True
    assert coverage_ok(949, 1000, 0.95) is False
    assert coverage_ok(10, 0, 0.95) is False


# ---------------------------------------------------------- 时间切分

def test_split_produces_disjoint_ranges() -> None:
    """样本内外不得有日期重叠。"""
    calendar = _calendar("2021-01-01", "2022-12-31")
    split = split_time_range(calendar, _config(), min_days=50)
    assert split.has_overlap is False
    assert not (set(split.in_sample) & set(split.out_of_sample))
    assert split.in_sample[0] == calendar[0]


def test_split_is_entirely_before_oos() -> None:
    """样本内最后一天必须严格早于样本外第一天。"""
    split = split_time_range(
        _calendar("2021-01-01", "2022-12-31"), _config(), min_days=50
    )
    assert split.in_sample[-1] < split.out_of_sample[0]


def test_split_preserves_calendar_order() -> None:
    """切分不得打乱交易日顺序。"""
    calendar = _calendar("2021-01-01", "2022-12-31")
    split = split_time_range(calendar, _config(), min_days=50)
    assert split.in_sample == sorted(split.in_sample)
    assert split.out_of_sample == sorted(split.out_of_sample)
    assert split.in_sample == [d for d in calendar if d <= date(2021, 12, 31)]


def test_split_rejects_insufficient_in_sample() -> None:
    """样本内交易日不足时必须报错，不允许缩小阈值硬跑。"""
    with pytest.raises(SplitError, match="样本内交易日不足"):
        split_time_range(_calendar("2021-01-01", "2021-01-10"),
                         _config(), min_days=120)


def test_split_rejects_insufficient_out_of_sample() -> None:
    with pytest.raises(SplitError, match="样本外交易日不足"):
        split_time_range(_calendar("2021-01-01", "2022-01-10"),
                         _config(), min_days=120)


def test_split_rejects_empty_calendar() -> None:
    with pytest.raises(SplitError, match="交易日历为空"):
        split_time_range([], _config(), min_days=1)


def test_split_rejects_duplicate_dates() -> None:
    days = _calendar("2021-01-01", "2021-12-31")
    with pytest.raises(SplitError, match="重复日期"):
        split_time_range(days + days[:5], _config(), min_days=50)


def test_split_records_actual_boundaries_when_config_not_trading_day() -> None:
    """配置日期落在非交易日时，报告须使用真实交易日。"""
    split = split_time_range(
        _calendar("2021-01-02", "2022-12-31"),
        _config(is_start="2021-01-01"),
        min_days=50,
    )
    assert split.is_start == "2021-01-04"
    assert any("非交易日" in note for note in split.notes)


def test_split_as_dict_exposes_no_overlap() -> None:
    split = split_time_range(_calendar("2021-01-01", "2022-12-31"), _config(), min_days=50)
    payload = split.as_dict()
    assert payload["overlap"] is False
    assert payload["is_days"] > 0 and payload["oos_days"] > 0


def test_warmup_note_excludes_warmup_returns() -> None:
    """预热说明必须明确预热期收益不计入验证期。"""
    text = warmup_note(20)
    assert "19" in text
    assert "不计入验证期收益" in text


def test_filter_codes_by_coverage_drops_insufficient() -> None:
    keep, dropped = filter_codes_by_coverage(
        {"510300": 990, "513180": 500}, calendar_days=1000, ratio=0.95
    )
    assert keep == ["510300"]
    assert len(dropped) == 1
    assert dropped[0]["code"] == "513180"
    assert dropped[0]["reason"] == "insufficient_history"


def test_filter_codes_by_coverage_zero_calendar() -> None:
    keep, dropped = filter_codes_by_coverage({"510300": 10}, calendar_days=0, ratio=0.95)
    assert keep == []
    assert len(dropped) == 1


# ---------------------------------------------------------- Walk-Forward

def test_walkforward_windows_advance_and_do_not_overlap() -> None:
    """窗口必须向前滚动，训练期不得与验证期重叠，验证窗互不重叠。"""
    from app.validation.walkforward import assert_no_leakage, build_windows

    windows = build_windows(_calendar("2021-01-01", "2026-11-09"), _config(
        is_start="2021-01-01", is_end="2024-12-31",
        oos_start="2025-01-01", oos_end="2026-11-09",
    ), min_test_days=60)
    assert len(windows) >= 4
    assert_no_leakage(windows)
    for position, window in enumerate(windows):
        assert window.train_end < window.test_start
        if position:
            assert window.train_start > windows[position - 1].train_start
            assert window.test_start > windows[position - 1].test_end


def test_walkforward_window_respects_data_boundary() -> None:
    """最后一个窗口的验证期不得越过真实数据边界。"""
    from app.validation.walkforward import build_windows

    calendar = _calendar("2021-01-01", "2026-11-09")
    windows = build_windows(calendar, _config(), min_test_days=10)
    assert windows[-1].test_end <= calendar[-1]
    assert windows[-1].test_end == calendar[-1]


def test_walkforward_marks_insufficient_window() -> None:
    """验证窗交易日不足时必须标记 insufficient_data，不能静默丢弃。"""
    from app.validation.walkforward import build_windows

    windows = build_windows(_calendar("2021-01-01", "2024-12-31"), _config(),
                            min_test_days=500)
    assert all(window.status == "insufficient_data" for window in windows)
    assert all("交易日不足" in (window.reason or "") for window in windows)


def test_walkforward_rejects_mismatched_step() -> None:
    """验证窗与步长不一致会导致重叠，必须拒绝。"""
    from app.validation.walkforward import build_windows

    with pytest.raises(ValidationConfigError, match="必须等于"):
        build_windows(_calendar("2021-01-01", "2026-11-09"),
                      _config(train_months=24, test_months=6, step_months=3))


def test_walkforward_rejects_empty_calendar() -> None:
    from app.validation.walkforward import WalkForwardError, build_windows

    with pytest.raises(WalkForwardError, match="交易日历为空"):
        build_windows([], _config())


def test_select_best_param_prefers_sharpe() -> None:
    """参数选择只看训练窗结果。"""
    from app.validation.walkforward import select_best_param

    results = {
        5: {"status": "success", "sharpe_ratio": 0.5, "max_drawdown": -0.1},
        20: {"status": "success", "sharpe_ratio": 0.9, "max_drawdown": -0.3},
        60: {"status": "success", "sharpe_ratio": 0.9, "max_drawdown": -0.1},
        120: {"status": "failed"},
    }
    param, reason = select_best_param(results)
    assert param == 60, "Sharpe 相同时应选最大回撤更小的"
    assert "Sharpe" in reason


def test_select_best_param_ignores_failed_and_returns_none() -> None:
    from app.validation.walkforward import select_best_param

    param, reason = select_best_param({
        5: {"status": "failed"},
        20: {"status": "insufficient_data"},
    })
    assert param is None
    assert "没有可比较" in reason


def test_select_best_param_signature_only_accepts_train_results() -> None:
    """选参函数只接收一个结果字典，无法在结构上接触验证窗数据。"""
    import inspect

    from app.validation.walkforward import select_best_param

    params = list(inspect.signature(select_best_param).parameters)
    assert params == ["train_results"], f"选参函数不应接受其他输入：{params}"


# ---------------------------------------------------------- 市场环境

def test_regime_classification_has_no_lookahead() -> None:
    """环境分类只依赖 T 日及之前的价格；修改 T 日之后的价格不影响 T 日分类。"""
    import pandas as pd

    from app.validation.regime import build_regime_series

    dates = pd.bdate_range("2021-01-04", periods=400)
    prices = [10.0 + index * 0.01 for index in range(400)]
    series = pd.Series(prices, index=[d.date() for d in dates])
    baseline = build_regime_series(series, code="510300")

    cutoff = 350
    modified = prices[:cutoff] + [price * 3 for price in prices[cutoff:]]
    changed = build_regime_series(
        pd.Series(modified, index=[d.date() for d in dates]), code="510300"
    )
    for position in range(cutoff):
        day = dates[position].date()
        assert baseline.label_at(day) == changed.label_at(day), (
            f"{day} 的分类被未来价格影响，存在未来函数"
        )


def test_regime_insufficient_samples_marked_unclassified() -> None:
    """样本不足不强行分类。"""
    import pandas as pd

    from app.validation.regime import REGIME_UNCLASSIFIED, build_regime_series

    dates = pd.bdate_range("2021-01-04", periods=300)
    series = pd.Series([10.0] * 300, index=[d.date() for d in dates])
    result = build_regime_series(series, code="510300", ma_window=250)
    assert sum(1 for label in result.labels.values()
               if label == REGIME_UNCLASSIFIED) == 249
    assert any("未强行归类" in note for note in result.notes)


def test_regime_empty_series_raises() -> None:
    import pandas as pd

    from app.validation.regime import RegimeError, build_regime_series

    with pytest.raises(RegimeError, match="没有可用收盘价"):
        build_regime_series(pd.Series(dtype=float), code="510300")


def test_regime_stats_marks_insufficient_sample() -> None:
    from app.validation.regime import REGIME_BULL, regime_stats

    stats = regime_stats({date(2024, 1, 2): 0.01}, {date(2024, 1, 2): REGIME_BULL},
                         min_samples=20)
    assert stats[REGIME_BULL]["status"] == "insufficient_sample"


# ---------------------------------------------------------- 参数敏感性

def test_sensitivity_analysis_selects_best_and_lists_all() -> None:
    """必须展示全部组合，不只展示最优。"""
    from app.validation.sensitivity import GridCell, analyze_grid

    grid = [
        GridCell(5, "success", {"sharpe_ratio": 0.3, "total_return": 0.1, "max_drawdown": -0.2}),
        GridCell(20, "success", {"sharpe_ratio": 0.8, "total_return": 0.4, "max_drawdown": -0.15}),
        GridCell(60, "success", {"sharpe_ratio": 0.7, "total_return": 0.35, "max_drawdown": -0.2}),
    ]
    result = analyze_grid(grid)
    assert result.best_param == 20
    assert len(result.metrics_table()) == 3, "报告必须包含全部参数组合"
    assert result.positive_count == 3


def test_sensitivity_flags_overfitting_when_few_profitable() -> None:
    """只有少数组合赚钱时必须提示过拟合风险。"""
    from app.validation.sensitivity import GridCell, analyze_grid

    grid = [
        GridCell(5, "success", {"sharpe_ratio": 0.1, "total_return": -0.2, "max_drawdown": -0.3}),
        GridCell(20, "success", {"sharpe_ratio": 0.2, "total_return": -0.1, "max_drawdown": -0.3}),
        GridCell(60, "success", {"sharpe_ratio": 1.5, "total_return": 0.5, "max_drawdown": -0.05}),
        GridCell(120, "success", {"sharpe_ratio": 0.05, "total_return": -0.3, "max_drawdown": -0.4}),
    ]
    result = analyze_grid(grid)
    assert result.best_param == 60
    assert any("过拟合风险" in flag for flag in result.risk_flags)


def test_sensitivity_flags_no_stable_neighbor() -> None:
    """最优参数相邻档位大幅衰减时必须提示缺乏稳定区域。"""
    from app.validation.sensitivity import GridCell, analyze_grid

    grid = [
        GridCell(5, "success", {"sharpe_ratio": 0.0, "total_return": 0.01, "max_drawdown": -0.3}),
        GridCell(20, "success", {"sharpe_ratio": 2.0, "total_return": 0.5, "max_drawdown": -0.05}),
        GridCell(60, "success", {"sharpe_ratio": 0.1, "total_return": 0.02, "max_drawdown": -0.3}),
    ]
    result = analyze_grid(grid, grid_order=(5, 20, 60))
    assert result.stable_neighbors == []
    assert any("缺乏稳定区域" in flag for flag in result.risk_flags)


def test_sensitivity_reproducible() -> None:
    """相同网格必须产生相同分析结果。"""
    from app.validation.sensitivity import GridCell, analyze_grid

    def build():
        return [
            GridCell(5, "success", {"sharpe_ratio": 0.5, "total_return": 0.2, "max_drawdown": -0.2}),
            GridCell(20, "success", {"sharpe_ratio": 0.9, "total_return": 0.4, "max_drawdown": -0.1}),
        ]

    first = analyze_grid(build()).as_dict()
    second = analyze_grid(build()).as_dict()
    assert first == second


def test_sensitivity_rejects_empty_grid() -> None:
    from app.validation.sensitivity import SensitivityError, analyze_grid

    with pytest.raises(SensitivityError, match="参数网格为空"):
        analyze_grid([])


def test_sensitivity_oos_is_attached_not_used_for_selection() -> None:
    """样本外结果只能附加，不参与最优参数选择。"""
    from app.validation.sensitivity import GridCell, analyze_grid, attach_oos

    grid = [
        GridCell(5, "success", {"sharpe_ratio": 0.9, "total_return": 0.4, "max_drawdown": -0.1}),
        GridCell(20, "success", {"sharpe_ratio": 0.5, "total_return": 0.2, "max_drawdown": -0.2}),
    ]
    result = analyze_grid(grid)
    assert result.best_param == 5
    attach_oos(result, GridCell(20, "success", {"sharpe_ratio": 1.8, "total_return": 0.9}))
    assert result.best_param == 5, "样本外表现再好也不能改变样本内选出的参数"


# ---------------------------------------------------------- 基准

def test_benchmarks_include_required_set() -> None:
    from app.validation.benchmark import build_benchmarks

    specs = build_benchmarks(["510300", "510500", "159915"], _config(), best_ma_window=20)
    keys = {spec.key for spec in specs}
    assert {"buy_and_hold", "hs300", "zz500", "ma_trend"} <= keys
    hs300 = next(spec for spec in specs if spec.key == "hs300")
    assert hs300.proxy_for == "沪深300指数", "必须标明 ETF 代理关系"


def test_benchmarks_skip_missing_proxy() -> None:
    """ETF 池里没有代理标的时不得伪造基准。"""
    from app.validation.benchmark import build_benchmarks

    specs = build_benchmarks(["159915"], _config(), best_ma_window=20)
    keys = {spec.key for spec in specs}
    assert "hs300" not in keys and "zz500" not in keys


def test_benchmarks_reject_empty_pool() -> None:
    from app.validation.benchmark import BenchmarkError, build_benchmarks

    with pytest.raises(BenchmarkError, match="ETF 池为空"):
        build_benchmarks([], _config())


def test_benchmark_range_alignment_marks_incomplete() -> None:
    from app.validation.benchmark import align_ranges, build_benchmarks

    specs = build_benchmarks(["510300"], _config(), best_ma_window=20)
    rows = align_ranges(specs, {})
    assert all(row["status"] == "insufficient_data" for row in rows)


def test_benchmark_common_range_is_intersection() -> None:
    from app.validation.benchmark import common_range

    rows = [
        {"name": "A", "status": "ok", "coverage_start": "2021-01-04", "coverage_end": "2026-11-09"},
        {"name": "B", "status": "ok", "coverage_start": "2022-03-01", "coverage_end": "2025-12-31"},
    ]
    start, end, notes = common_range(rows)
    assert start == "2022-03-01"
    assert end == "2025-12-31"
    assert any("截取" in note for note in notes)


# ---------------------------------------------------------- 压力测试

def test_stress_scenarios_cover_required_set() -> None:
    from app.validation.stress import default_scenarios

    keys = {scenario.key for scenario in default_scenarios()}
    assert {"base", "cost_plus_50", "cost_plus_100",
            "slippage_x2", "slippage_x3", "sparse_data", "insufficient"} <= keys


def test_stress_cost_multiplier_applies_to_config_only() -> None:
    """压力场景只改成本参数，不碰行情。"""
    from app.validation.stress import build_scenarios

    config = _config()
    scenario = build_scenarios(["cost_plus_100"])[0]
    overrides = scenario.apply(config)
    assert overrides["commission_rate"] == pytest.approx(config.commission_rate * 2)
    assert overrides["min_commission"] == pytest.approx(config.min_commission * 2)
    assert set(overrides) == {"commission_rate", "min_commission", "slippage_bps"}


def test_stress_slippage_doubling() -> None:
    from app.validation.stress import build_scenarios

    config = _config()
    doubled = build_scenarios(["slippage_x2"])[0].apply(config)
    assert doubled["slippage_bps"] == pytest.approx(config.slippage_bps * 2)
    tripled = build_scenarios(["slippage_x3"])[0].apply(config)
    assert tripled["slippage_bps"] == pytest.approx(config.slippage_bps * 3)


def test_stress_rejects_unknown_scenario() -> None:
    from app.validation.stress import StressError, build_scenarios

    with pytest.raises(StressError, match="未知压力场景"):
        build_scenarios(["no_such_scenario"])


def test_stress_detects_data_mutation() -> None:
    """行情指纹变化必须立即报错，防止压力测试偷偷改历史数据。"""
    from app.validation.stress import StressError, assert_no_data_mutation

    baseline = {"rows": 116609, "hash": "abc"}
    assert_no_data_mutation(baseline, {"rows": 116609, "hash": "abc"}, "base")
    with pytest.raises(StressError, match="修改了历史数据"):
        assert_no_data_mutation(baseline, {"rows": 116609, "hash": "xyz"}, "cost_plus_50")


# ---------------------------------------------------------- 存储与可复现

def test_validation_schema_is_idempotent(temp_db) -> None:
    """迁移可重复执行，不破坏既有表。"""
    from app.database.db import get_connection
    from app.validation.storage import init_validation_schema

    init_validation_schema(temp_db)
    init_validation_schema(temp_db)
    with get_connection(temp_db) as conn:
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"validation_runs", "validation_windows",
            "validation_grid", "validation_stress"} <= tables
    assert "backtest_runs" in tables, "不得破坏既有回测表"


def test_validation_history_not_overwritten(temp_db) -> None:
    """不同 validation_id 的历史记录不得互相覆盖。"""
    from app.validation.storage import (
        ValidationRecord,
        get_validation,
        save_validation_run,
    )

    def make(vid: str):
        return ValidationRecord(
            validation_id=vid, strategy_name="ma_trend", strategy_version="1.0.0",
            config_hash="cfg1", eth_codes=["510300"], ma_window_grid=[20],
            is_start="2021-01-04", is_end="2024-12-31",
            oos_start="2025-01-02", oos_end="2026-11-09",
            status="success", conclusion="不通过", input_hash="h1",
        )

    save_validation_run(make("val_a"), db_path=temp_db)
    save_validation_run(make("val_b"), db_path=temp_db)
    first = get_validation("val_a", db_path=temp_db)
    second = get_validation("val_b", db_path=temp_db)
    assert first is not None and second is not None
    assert first["validation_id"] == "val_a"
    assert second["validation_id"] == "val_b"


def test_validation_same_id_updates_only_itself(temp_db) -> None:
    """同一 validation_id 重跑只更新自己，不影响其他记录。"""
    from app.validation.storage import (
        ValidationRecord,
        get_validation,
        save_validation_run,
    )

    def make(vid: str, conclusion: str):
        return ValidationRecord(
            validation_id=vid, strategy_name="ma_trend", strategy_version="1.0.0",
            config_hash="cfg", eth_codes=["510300"], ma_window_grid=[20],
            is_start="2021-01-04", is_end="2024-12-31",
            oos_start="2025-01-02", oos_end="2026-11-09",
            status="success", conclusion=conclusion,
        )

    save_validation_run(make("val_x", "不通过"), db_path=temp_db)
    save_validation_run(make("val_y", "通过"), db_path=temp_db)
    save_validation_run(make("val_x", "有条件通过"), db_path=temp_db)
    assert get_validation("val_x", db_path=temp_db)["conclusion"] == "有条件通过"
    assert get_validation("val_y", db_path=temp_db)["conclusion"] == "通过"


def test_validation_subrecords_persist(temp_db) -> None:
    """窗口、网格、压力明细必须能读回。"""
    from app.validation.storage import (
        ValidationRecord,
        get_validation,
        save_grid,
        save_stress,
        save_validation_run,
        save_windows,
    )

    record = ValidationRecord(
        validation_id="val_sub", strategy_name="ma_trend", strategy_version="1.0.0",
        config_hash="cfg", eth_codes=["510300"], ma_window_grid=[5, 20],
        is_start="2021-01-04", is_end="2024-12-31",
        oos_start="2025-01-02", oos_end="2026-11-09", status="success",
    )
    save_validation_run(record, db_path=temp_db)
    save_windows("val_sub", [{
        "index": 0, "train_start": "2021-01-04", "train_end": "2023-01-03",
        "test_start": "2023-01-04", "test_end": "2023-07-03",
        "train_days": 520, "test_days": 129, "selected_param": 20,
        "status": "success", "test_metrics": {"total_return": 0.1},
    }], db_path=temp_db)
    save_grid("val_sub", "in_sample", [
        {"ma_window": 5, "status": "success", "metrics": {"sharpe_ratio": 0.2}},
        {"ma_window": 20, "status": "success", "metrics": {"sharpe_ratio": 0.8}},
    ], db_path=temp_db)
    save_stress("val_sub", [{
        "key": "base", "name": "基础成本", "is_hypothetical": False,
        "status": "success", "metrics": {"total_return": 0.05},
    }], db_path=temp_db)

    payload = get_validation("val_sub", db_path=temp_db)
    assert len(payload["windows"]) == 1
    assert len(payload["grid"]) == 2
    assert len(payload["stress"]) == 1


def test_validation_failed_status_recorded(temp_db) -> None:
    """失败任务必须有明确状态和错误原因。"""
    from app.validation.storage import ValidationRecord, get_validation, save_validation_run

    record = ValidationRecord(
        validation_id="val_fail", strategy_name="ma_trend", strategy_version="1.0.0",
        config_hash="cfg", eth_codes=[], ma_window_grid=[20],
        is_start="2021-01-04", is_end="2024-12-31",
        oos_start="2025-01-02", oos_end="2026-11-09",
        status="failed", error_message="可用 ETF 不足：0 只",
    )
    save_validation_run(record, db_path=temp_db)
    payload = get_validation("val_fail", db_path=temp_db)
    assert payload["status"] == "failed"
    assert "ETF 不足" in payload["error_message"]


def test_input_hash_reproducible_and_sensitive() -> None:
    """相同输入产生相同 hash；参数变化必须改变 hash。"""
    from app.validation.runner import _input_hash

    fingerprint = {"rows": 100, "close_sum": 1.5, "volume_sum": 2.5}
    a = _input_hash(_config(), ["510300", "510500"], fingerprint)
    b = _input_hash(_config(), ["510500", "510300"], fingerprint)
    c = _input_hash(_config(commission_rate=0.0005), ["510300", "510500"], fingerprint)
    assert a == b, "ETF 顺序不应影响 hash"
    assert a != c, "参数变化必须改变 hash"


def test_data_fingerprint_detects_change(temp_db) -> None:
    """行情指纹能检测出行情变化。"""
    from app.database.db import get_connection
    from app.validation.runner import _data_fingerprint

    with get_connection(temp_db) as conn:
        conn.execute(
            "INSERT INTO etf_daily_prices (code, trade_date, open, high, low, close, volume, "
            "amount, adjusted_close, adjustment_type, quality_status, source, collected_at) "
            "VALUES ('510300','2024-01-02',10,10.5,9.5,10,1000,10000,10,'qfq','valid','t','2024-01-02')"
        )
    first = _data_fingerprint(temp_db)
    with get_connection(temp_db) as conn:
        conn.execute("UPDATE etf_daily_prices SET close=11 WHERE code='510300'")
    second = _data_fingerprint(temp_db)
    assert first != second


def test_decide_conclusion_returns_only_three_values() -> None:
    """结论只能是三类之一。"""
    from app.validation.runner import decide_conclusion
    from app.validation.sensitivity import GridCell, analyze_grid

    analysis = analyze_grid([
        GridCell(20, "success", {"sharpe_ratio": 0.8, "total_return": 0.3, "max_drawdown": -0.2}),
        GridCell(60, "success", {"sharpe_ratio": 0.7, "total_return": 0.2, "max_drawdown": -0.25}),
    ])
    windows = [{"status": "success", "test_metrics": {"total_return": 0.1}}] * 4
    regime = {"labels_available": True, "stats": {
        "bull": {"status": "ok"}, "bear": {"status": "ok"}, "range": {"status": "ok"}}}
    conclusion, reasons = decide_conclusion(
        analysis, {"sharpe_ratio": 0.6, "total_return": 0.2, "max_drawdown": -0.1},
        windows, regime, [{"status": "success"}],
    )
    assert conclusion in ("通过", "有条件通过", "不通过")
    assert reasons


def test_decide_conclusion_rejects_negative_oos() -> None:
    """样本外为负时必须不通过或有条件通过，不能给通过。"""
    from app.validation.runner import decide_conclusion
    from app.validation.sensitivity import GridCell, analyze_grid

    analysis = analyze_grid([
        GridCell(20, "success", {"sharpe_ratio": 0.9, "total_return": 0.4, "max_drawdown": -0.1}),
    ])
    conclusion, _ = decide_conclusion(
        analysis, {"sharpe_ratio": -0.3, "total_return": -0.15, "max_drawdown": -0.3},
        [{"status": "success", "test_metrics": {"total_return": -0.05}}] * 3,
        {"labels_available": False}, [],
    )
    assert conclusion != "通过"
