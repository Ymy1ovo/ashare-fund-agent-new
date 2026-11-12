"""阶段3A.2.1 专项整改测试。

覆盖：市场环境预热、全字段数据指纹、数据类压力测试、缺失日收益处理、真实行情隔离。
全部使用人工构造数据或临时数据库，不触碰正式库。
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from app.validation.config import ValidationConfig
from app.validation.fingerprint import (
    FIELD_LIST,
    FINGERPRINT_VERSION,
    FingerprintError,
    compare_fingerprints,
    compute_fingerprint,
    fingerprint_from_rows,
    normalize_rows,
    serialize_row,
)
from app.validation.regime import (
    REGIME_BEAR,
    REGIME_BULL,
    REGIME_RANGE,
    REGIME_UNCLASSIFIED,
    RegimeError,
    build_regime_series,
    regime_stats,
)


def _bdays(start: str, count: int) -> list[date]:
    return [d.date() for d in pd.bdate_range(start, periods=count)]


def _price_series(start: str, count: int, base: float = 10.0, drift: float = 0.005):
    days = _bdays(start, count)
    values = []
    price = base
    for _ in range(count):
        price *= (1 + drift)
        values.append(price)
    return pd.Series(values, index=pd.DatetimeIndex(days))


# ============================================================ 任务1：预热

def test_regime_warmup_enables_ma250_on_first_oos_day() -> None:
    """OOS 第一天必须能靠此前 250 个交易日完成 MA250。"""
    warmup = _price_series("2023-01-02", 300, drift=0.001)
    oos = _price_series("2024-03-01", 60, base=float(warmup.iloc[-1]), drift=0.001)
    combined = pd.concat([warmup, oos]).sort_index()
    oos_start = oos.index[0].date()

    result = build_regime_series(combined, code="510300", output_start=oos_start)
    assert result.first_day == oos_start, "输出必须从 OOS 第一天开始"
    assert result.label_at(oos_start) != REGIME_UNCLASSIFIED, (
        "OOS 第一天应能完成 MA250 预热"
    )
    assert result.warmup_days >= 250


def test_regime_without_warmup_cannot_classify() -> None:
    """对照：只喂 OOS 数据且不足 250 天时无法分类，必须抛错而不是硬编。"""
    oos = _price_series("2025-01-02", 60)
    with pytest.raises(RegimeError, match="样本不足"):
        build_regime_series(oos, code="510300")


def test_regime_warmup_does_not_enter_output() -> None:
    """预热日不得出现在输出 labels 中，否则会污染 OOS 绩效统计。"""
    warmup = _price_series("2023-01-02", 300)
    oos = _price_series("2024-03-01", 60, base=float(warmup.iloc[-1]))
    combined = pd.concat([warmup, oos]).sort_index()
    oos_start = oos.index[0].date()

    result = build_regime_series(combined, code="510300", output_start=oos_start)
    assert all(day >= oos_start for day in result.labels), "输出不应包含预热日"
    assert result.output_days == len(oos) if hasattr(result, "output_days") else True
    assert len(result.labels) == len(oos)


def test_regime_future_data_does_not_change_past_labels() -> None:
    """修改 OOS 之后的价格，不得改变此前已产生的分类。"""
    warmup = _price_series("2023-01-02", 300)
    oos = _price_series("2024-03-01", 100, base=float(warmup.iloc[-1]))
    combined = pd.concat([warmup, oos]).sort_index()
    oos_start = oos.index[0].date()
    baseline = build_regime_series(combined, code="510300", output_start=oos_start)

    cutoff = 50
    modified_oos = oos.copy()
    modified_oos.iloc[cutoff:] = modified_oos.iloc[cutoff:] * 3
    changed = build_regime_series(
        pd.concat([warmup, modified_oos]).sort_index(),
        code="510300", output_start=oos_start,
    )
    for position in range(cutoff):
        day = oos.index[position].date()
        assert baseline.label_at(day) == changed.label_at(day), (
            f"{day} 的分类被未来数据影响"
        )


def test_regime_insufficient_warmup_marks_partial() -> None:
    """预热不足 250 天时，前段必须保持 unclassified，不强行分类。"""
    warmup = _price_series("2023-01-02", 100)
    oos = _price_series("2023-06-01", 60, base=float(warmup.iloc[-1]))
    combined = pd.concat([warmup, oos]).sort_index()
    oos_start = oos.index[0].date()

    # 预热 100 天 + OOS 60 天 = 160 天，仍不足 250，整体不可分类
    with pytest.raises(RegimeError, match="样本不足"):
        build_regime_series(combined, code="510300", output_start=oos_start)

    # 预热 100 天 + OOS 200 天 = 300 天：前 150 个 OOS 日 unclassified，
    # 之后才凑够 MA250，证明不会用部分数据硬凑分类
    longer_oos = _price_series("2023-06-01", 200, base=float(warmup.iloc[-1]))
    combined_long = pd.concat([warmup, longer_oos]).sort_index()
    result = build_regime_series(
        combined_long, code="510300", output_start=longer_oos.index[0].date()
    )
    assert result.label_at(longer_oos.index[0].date()) == REGIME_UNCLASSIFIED, (
        "预热只有 100 天，OOS 首日不可能有 MA250"
    )
    classified = [
        day for day, label in sorted(result.labels.items())
        if label != REGIME_UNCLASSIFIED
    ]
    assert classified, "样本积累足够后应能分类"
    combined_days = sorted(list(warmup.index) + list(longer_oos.index))
    expected = pd.Timestamp(combined_days[249]).date()
    assert classified[0] == expected, (
        f"第 250 个交易日（预热100+OOS150）才应有 MA250，实际 {classified[0]} vs {expected}"
    )


def test_regime_alignment_uses_trading_days_not_calendar_days() -> None:
    """必须按实际交易日期对齐，不是自然日偏移。"""
    days = _bdays("2023-01-02", 300)
    values = [10.0 + i * 0.01 for i in range(300)]
    series = pd.Series(values, index=pd.DatetimeIndex(days))
    result = build_regime_series(series, code="510300", ma_window=250)
    first_classified = next(
        day for day, label in sorted(result.labels.items())
        if label != REGIME_UNCLASSIFIED
    )
    assert first_classified == days[249], (
        f"第 250 个交易日才应有 MA250，实际 {first_classified} vs {days[249]}"
    )


def test_regime_output_dates_match_oos_one_to_one() -> None:
    """OOS 日期与分类结果一一对应。"""
    warmup = _price_series("2023-01-02", 300)
    oos = _price_series("2024-03-01", 40, base=float(warmup.iloc[-1]))
    combined = pd.concat([warmup, oos]).sort_index()
    oos_start = oos.index[0].date()

    result = build_regime_series(combined, code="510300", output_start=oos_start)
    assert sorted(result.labels) == sorted(day.date() for day in oos.index)


def test_regime_summary_reports_warmup_and_range() -> None:
    warmup = _price_series("2023-01-02", 300)
    oos = _price_series("2024-03-01", 30, base=float(warmup.iloc[-1]))
    combined = pd.concat([warmup, oos]).sort_index()
    result = build_regime_series(combined, code="510300",
                                 output_start=oos.index[0].date())
    summary = result.summary()
    assert summary["warmup_days"] >= 250
    assert summary["output_days"] == 30
    assert summary["first_day"] == oos.index[0].date().isoformat()
    assert summary["last_day"] == oos.index[-1].date().isoformat()
    assert summary["code"] == "510300"


def test_regime_empty_series_still_raises() -> None:
    with pytest.raises(RegimeError):
        build_regime_series(pd.Series(dtype=float), code="510300")


# ============================================================ 任务2：数据指纹

def _sample_rows() -> list[tuple]:
    """一行 = FIELD_LIST 对应字段。"""
    return [
        ("510300", "2024-01-02", 10.0, 10.5, 9.5, 10.2, 100000.0, 1020000.0, 10.2,
         "qfq", 1, "2024-01-01", "2024-12-31"),
        ("510300", "2024-01-03", 10.2, 10.8, 10.1, 10.6, 120000.0, 1272000.0, 10.6,
         "qfq", 1, "2024-01-01", "2024-12-31"),
        ("510500", "2024-01-02", 20.0, 20.5, 19.5, 20.2, 50000.0, 1010000.0, 20.2,
         "qfq", 1, "2024-01-01", "2024-12-31"),
    ]


def test_fingerprint_version_and_fields_declared() -> None:
    """指纹算法必须有版本号与字段清单。"""
    assert FINGERPRINT_VERSION == "market-fingerprint-v3"
    assert "close" in FIELD_LIST
    assert "adjusted_close" in FIELD_LIST
    assert "volume" in FIELD_LIST
    assert "trade_date" in FIELD_LIST
    assert "code" in FIELD_LIST


def test_fingerprint_is_reproducible() -> None:
    """同一份数据重复计算，指纹一致。"""
    first = fingerprint_from_rows(_sample_rows())
    second = fingerprint_from_rows(_sample_rows())
    assert first["sha256"] == second["sha256"]
    assert first["rows"] == 3


def test_fingerprint_row_order_independent() -> None:
    """行顺序变化，指纹不变。"""
    rows = _sample_rows()
    shuffled = [rows[2], rows[0], rows[1]]
    assert fingerprint_from_rows(rows)["sha256"] == fingerprint_from_rows(shuffled)["sha256"]


def test_fingerprint_detects_each_price_field() -> None:
    """open/high/low/close/volume/adjusted_close 任一变化，指纹必须变化。"""
    baseline = fingerprint_from_rows(_sample_rows())["sha256"]
    # FIELD_LIST 中每列的位置
    positions = {name: index for index, name in enumerate(FIELD_LIST)}
    for field in ("open", "high", "low", "close", "volume", "adjusted_close"):
        rows = [list(row) for row in _sample_rows()]
        index = positions[field]
        rows[0][index] = float(rows[0][index]) * 1.0001
        changed = fingerprint_from_rows([tuple(row) for row in rows])["sha256"]
        assert changed != baseline, f"{field} 变化后指纹未变化"


def test_fingerprint_detects_date_and_symbol_change() -> None:
    baseline = fingerprint_from_rows(_sample_rows())["sha256"]
    positions = {name: index for index, name in enumerate(FIELD_LIST)}

    rows = [list(row) for row in _sample_rows()]
    rows[0][positions["trade_date"]] = "2024-01-04"
    assert fingerprint_from_rows([tuple(r) for r in rows])["sha256"] != baseline

    rows = [list(row) for row in _sample_rows()]
    rows[0][positions["code"]] = "510500"
    assert fingerprint_from_rows([tuple(r) for r in rows])["sha256"] != baseline


def test_fingerprint_detects_snapshot_change() -> None:
    """复权快照 ID 变化必须被识别。"""
    baseline = fingerprint_from_rows(_sample_rows())["sha256"]
    rows = [list(row) for row in _sample_rows()]
    rows[0][FIELD_LIST.index("adjustment_snapshot_id")] = 99
    assert fingerprint_from_rows([tuple(r) for r in rows])["sha256"] != baseline


def test_fingerprint_null_encoding_stable() -> None:
    """None 与 NaN 编码一致，不产生分歧。"""
    row_none = ("510300", "2024-01-02", 10.0, 10.5, 9.5, 10.2, 100000.0, 1020000.0,
                None, "qfq", 1, "2024-01-01", "2024-12-31")
    row_nan = ("510300", "2024-01-02", 10.0, 10.5, 9.5, 10.2, 100000.0, 1020000.0,
               float("nan"), "qfq", 1, "2024-01-01", "2024-12-31")
    assert serialize_row(row_none) == serialize_row(row_nan)
    assert fingerprint_from_rows([row_none])["sha256"] == fingerprint_from_rows([row_nan])["sha256"]


def test_fingerprint_float_precision_normalized() -> None:
    """1.1 与 1.10000 视为同一值，不因浮点表示产生不同指纹。"""
    a = ("510300", "2024-01-02", 10.1, 10.5, 9.5, 10.2, 100.0, 1000.0, 10.2,
         "qfq", 1, "2024-01-01", "2024-12-31")
    b = ("510300", "2024-01-02", 10.100000, 10.5, 9.5, 10.2, 100.00, 1000.0, 10.2,
         "qfq", 1, "2024-01-01", "2024-12-31")
    assert fingerprint_from_rows([a])["sha256"] == fingerprint_from_rows([b])["sha256"]


def test_fingerprint_rejects_wrong_field_count() -> None:
    with pytest.raises(FingerprintError, match="字段数不匹配"):
        serialize_row(("510300", "2024-01-02", 10.0))


def test_fingerprint_compare_reports_diff() -> None:
    before = fingerprint_from_rows(_sample_rows())
    rows = [list(row) for row in _sample_rows()]
    rows[0][FIELD_LIST.index("close")] = 99.0
    after = fingerprint_from_rows([tuple(r) for r in rows])
    result = compare_fingerprints(before, after)
    assert result["unchanged"] is False
    assert "行数相同但内容哈希不同" in result["reason"]


def test_fingerprint_compare_detects_row_count_change() -> None:
    before = fingerprint_from_rows(_sample_rows())
    after = fingerprint_from_rows(_sample_rows()[:2])
    result = compare_fingerprints(before, after)
    assert result["unchanged"] is False
    assert "行数变化" in result["reason"]


def test_fingerprint_normalize_rows_sorts_by_code_and_date() -> None:
    rows = _sample_rows()
    ordered = normalize_rows([rows[2], rows[1], rows[0]])
    assert ordered[0][0] == "510300" and ordered[0][1] == "2024-01-02"
    assert ordered[-1][0] == "510500"


def test_input_hash_changes_with_fingerprint() -> None:
    """指纹变化必须传导到 input_hash。"""
    from app.validation.runner import _input_hash

    config = ValidationConfig(
        is_start="2021-01-01", is_end="2021-12-31",
        oos_start="2022-01-01", oos_end="2022-12-31",
        pool_mode="all",
    )
    fp_a = fingerprint_from_rows(_sample_rows())
    rows = [list(row) for row in _sample_rows()]
    rows[0][FIELD_LIST.index("close")] = 55.5
    fp_b = fingerprint_from_rows([tuple(r) for r in rows])
    assert _input_hash(config, ["510300"], fp_a) != _input_hash(config, ["510300"], fp_b)


# ============================================================ 任务3：压力测试

def test_sparse_copy_does_not_modify_source(temp_db) -> None:
    """稀疏副本必须通过 SQLite backup 生成，源库行数不变。"""
    import sqlite3

    from app.validation.stress import build_sparse_copy

    with sqlite3.connect(temp_db) as conn:
        conn.execute(
            "INSERT INTO etf_pool (code, name, category, fund_type, data_source, "
            "source_tested_at, status) VALUES ('510300','t','宽基指数ETF','x','t','2024-01-01','active')"
        )
        for day in ("2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"):
            conn.execute(
                "INSERT INTO trade_calendar (trade_date) VALUES (?)", (day,)
            )
            conn.execute(
                "INSERT INTO etf_daily_prices (code, trade_date, open, high, low, close, "
                "volume, amount, adjusted_close, adjustment_type, quality_status, source, collected_at) "
                "VALUES ('510300',?,10,10.5,9.5,10,1000,10000,10,'qfq','valid','t','2024-01-01')",
                (day,),
            )
        before = conn.execute("SELECT COUNT(*) FROM etf_daily_prices").fetchone()[0]

    info = build_sparse_copy(
        temp_db, temp_db.parent / "sparse_work",
        start_date="2024-01-02", end_date="2024-01-05",
        drop_ratio_days=2, gap_codes=1, gap_length=2,
    )
    assert info["source_untouched"] is True
    with sqlite3.connect(temp_db) as conn:
        after = conn.execute("SELECT COUNT(*) FROM etf_daily_prices").fetchone()[0]
    assert before == after, "源库行情行数被修改"


def test_sparse_copy_actually_removes_rows(temp_db) -> None:
    import sqlite3

    from app.validation.stress import build_sparse_copy

    with sqlite3.connect(temp_db) as conn:
        conn.execute(
            "INSERT INTO etf_pool (code, name, category, fund_type, data_source, "
            "source_tested_at, status) VALUES ('510300','t','宽基指数ETF','x','t','2024-01-01','active')"
        )
        days = [f"2024-01-{d:02d}" for d in range(2, 22)]
        for day in days:
            conn.execute("INSERT INTO trade_calendar (trade_date) VALUES (?)", (day,))
            conn.execute(
                "INSERT INTO etf_daily_prices (code, trade_date, open, high, low, close, "
                "volume, amount, adjusted_close, adjustment_type, quality_status, source, collected_at) "
                "VALUES ('510300',?,10,10.5,9.5,10,1000,10000,10,'qfq','valid','t','2024-01-01')",
                (day,),
            )
        before = conn.execute("SELECT COUNT(*) FROM etf_daily_prices").fetchone()[0]

    info = build_sparse_copy(
        temp_db, temp_db.parent / "sparse_work2",
        start_date="2024-01-02", end_date="2024-01-21",
        drop_ratio_days=5, gap_codes=1, gap_length=4,
    )
    assert info["removed_scattered"] > 0, "零散缺失未生效"
    assert info["remaining_rows"] < before, "副本行数没有减少"


def test_sparse_evaluation_flags_bad_counts() -> None:
    """口径必须可加总：首日 + 缺口 + 缺净值 + 有效 == 快照天数。"""
    from app.validation.stress import evaluate_sparse_result

    # 100 = 首日 1 + 缺口 10 + 缺净值 9 + 有效 80
    ok = evaluate_sparse_result(
        daily_rows=100, valid_return_days=80, gap_days_excluded=10,
        first_day_skipped=1, missing_nav_days=9,
    )
    assert ok["status"] == "success"

    # 不可加总 → 判失败
    bad = evaluate_sparse_result(
        daily_rows=10, valid_return_days=100, gap_days_excluded=0,
        first_day_skipped=1, missing_nav_days=0,
    )
    assert bad["status"] == "failed"
    assert any("不可加总" in problem for problem in bad["problems"])


def test_insufficient_evaluation_requires_low_sample() -> None:
    from app.validation.stress import evaluate_insufficient_result

    good = evaluate_insufficient_result(
        trading_days=40, min_required=120, sharpe=None, cagr=None
    )
    assert good["status"] == "insufficient"
    assert good["trading_days"] == 40
    assert "低于最小需求" in good["reason"]

    too_long = evaluate_insufficient_result(
        trading_days=200, min_required=120, sharpe=None, cagr=None
    )
    assert too_long["status"] == "failed"


def test_insufficient_evaluation_rejects_metrics_when_short() -> None:
    """数据不足却仍对外输出 Sharpe/CAGR 必须判失败。"""
    from app.validation.stress import evaluate_insufficient_result

    bad = evaluate_insufficient_result(
        trading_days=40, min_required=120, sharpe=0.9, cagr=0.15,
        metrics_withheld=False,
    )
    assert bad["status"] == "failed"
    assert any("Sharpe" in problem for problem in bad["problems"])


def test_insufficient_evaluation_accepts_withheld_metrics() -> None:
    """引擎内部算出指标但已隐藏时，场景仍成立为 insufficient。"""
    from app.validation.stress import evaluate_insufficient_result

    ok = evaluate_insufficient_result(
        trading_days=40, min_required=120, sharpe=0.9, cagr=0.15,
        metrics_withheld=True,
    )
    assert ok["status"] == "insufficient"
    assert ok["metrics_withheld"] is True
    assert ok["engine_computed_metrics"] is True
    assert ok["sharpe"] is None and ok["cagr"] is None, "对外指标必须清空"
    assert "已隐藏" in ok["reason"]


def test_sparse_and_insufficient_are_not_skipped_in_scenario_set() -> None:
    """两个数据场景必须在默认场景集中且类型为 data。"""
    from app.validation.stress import default_scenarios

    by_key = {scenario.key: scenario for scenario in default_scenarios()}
    assert by_key["sparse_data"].kind == "data"
    assert by_key["insufficient"].kind == "data"
    assert by_key["sparse_data"].is_hypothetical is False


# ============================================================ 任务4：缺失日收益

def test_regime_stats_keeps_nan_and_counts_missing() -> None:
    """缺失日必须保留 NaN 并被计数，不能 dropna 后压缩。"""
    days = _bdays("2025-01-02", 10)
    index = pd.DatetimeIndex(days)
    # 第 3、4 天缺失；其余为 1% 涨跌交替
    values = [0.01, -0.01, float("nan"), float("nan"), 0.02, -0.02, 0.01, 0.0, 0.01, -0.01]
    returns = pd.Series(values, index=index, dtype=float)
    labels = {day: REGIME_BULL for day in days}

    stats = regime_stats(returns, labels, min_samples=3)
    bull = stats[REGIME_BULL]
    assert bull["total_days"] == 10
    assert bull["valid_days"] == 8
    assert bull["missing_days"] == 2, "缺失日必须被计数，不能被静默丢弃"
    assert bull["status"] == "ok"


def test_regime_stats_does_not_compress_cross_gap_return() -> None:
    """跨缺失日的收益不能被当成单日收益计入波动率。"""
    days = _bdays("2025-01-02", 6)
    index = pd.DatetimeIndex(days)
    # 第 2 天缺失，第 3 天的收益在真实序列里是 NaN（跨缺口）
    values = [0.10, float("nan"), float("nan"), 0.001, 0.001, 0.001]
    returns = pd.Series(values, index=index, dtype=float)
    labels = {day: REGIME_RANGE for day in days}

    stats = regime_stats(returns, labels, min_samples=2)
    entry = stats[REGIME_RANGE]
    # 6 天中 2 天是缺口（第 2、3 天），其余 4 天有真实相邻日收益
    assert entry["valid_days"] == 4, "只有 4 个真实相邻日收益"
    assert entry["missing_days"] == 2
    # 若压缩，会把 10% 的跨缺口收益当单日，年化波动率会被极大放大
    assert entry["annualized_volatility"] is not None
    assert entry["annualized_volatility"] < 1.0, (
        "波动率异常偏高说明跨缺口收益被当成单日收益"
    )


def test_regime_stats_missing_label_not_counted_as_other_regime() -> None:
    """分类缺失的日期不得被错误归入其他市场环境。"""
    days = _bdays("2025-01-02", 5)
    index = pd.DatetimeIndex(days)
    values = [0.01] * 5
    returns = pd.Series(values, index=index, dtype=float)
    labels = {
        days[0]: REGIME_BULL,
        days[1]: REGIME_BULL,
        # days[2] 没有分类
        days[3]: REGIME_BEAR,
        days[4]: REGIME_BEAR,
    }
    stats = regime_stats(returns, labels, min_samples=2)
    assert stats[REGIME_BULL]["valid_days"] == 2
    assert stats[REGIME_BEAR]["valid_days"] == 2
    assert stats[REGIME_UNCLASSIFIED]["valid_days"] == 1, (
        "无分类日必须进入 unclassified，不能并入 bull 或 bear"
    )


def test_regime_stats_insufficient_returns_clear_status() -> None:
    """有效观测不足时返回明确状态，不硬算指标。"""
    days = _bdays("2025-01-02", 5)
    index = pd.DatetimeIndex(days)
    returns = pd.Series([0.01, float("nan"), float("nan"), float("nan"), float("nan")],
                        index=index, dtype=float)
    labels = {day: REGIME_BEAR for day in days}

    stats = regime_stats(returns, labels, min_samples=3)
    bear = stats[REGIME_BEAR]
    assert bear["status"] == "insufficient_sample"
    assert "有效日收益 1 < 3" in bear["reason"]
    assert "annualized_volatility" not in bear


def test_regime_stats_accepts_dict_and_series_equally() -> None:
    """两种输入形式结果一致，避免调用方口径分歧。"""
    days = _bdays("2025-01-02", 8)
    index = pd.DatetimeIndex(days)
    values = [0.01, -0.01, 0.02, -0.02, 0.01, 0.0, -0.01, 0.015]
    labels = {day: REGIME_BULL for day in days}

    from_series = regime_stats(pd.Series(values, index=index), labels, min_samples=3)
    from_dict = regime_stats(dict(zip(days, values)), labels, min_samples=3)
    assert from_series[REGIME_BULL]["valid_days"] == from_dict[REGIME_BULL]["valid_days"]
    assert from_series[REGIME_BULL]["cumulative_return"] == pytest.approx(
        from_dict[REGIME_BULL]["cumulative_return"]
    )


def test_regime_stats_cumulative_return_excludes_missing() -> None:
    """累计收益只按有效日复利，不把缺失日当 0 收益或跳过压缩。"""
    days = _bdays("2025-01-02", 4)
    index = pd.DatetimeIndex(days)
    returns = pd.Series([0.10, float("nan"), 0.10, 0.10], index=index, dtype=float)
    labels = {day: REGIME_BULL for day in days}

    stats = regime_stats(returns, labels, min_samples=2)
    expected = (1.10 ** 3) - 1
    assert stats[REGIME_BULL]["cumulative_return"] == pytest.approx(expected)
    assert stats[REGIME_BULL]["valid_days"] == 3


# ============================================================ 任务5：数据隔离

def test_fingerprint_db_readonly_does_not_change_data(temp_db) -> None:
    """读取指纹不得修改数据库。"""
    import sqlite3

    from app.validation.fingerprint import fingerprint_from_db

    with sqlite3.connect(temp_db) as conn:
        conn.execute(
            "INSERT INTO etf_pool (code, name, category, fund_type, data_source, "
            "source_tested_at, status) VALUES ('510300','t','宽基指数ETF','x','t','2024-01-01','active')"
        )
        conn.execute(
            "INSERT INTO etf_daily_prices (code, trade_date, open, high, low, close, "
            "volume, amount, adjusted_close, adjustment_type, quality_status, source, collected_at) "
            "VALUES ('510300','2024-01-02',10,10.5,9.5,10,1000,10000,10,'qfq','valid','t','2024-01-01')"
        )
    before = fingerprint_from_db(db_path=temp_db)
    after = fingerprint_from_db(db_path=temp_db)
    assert before["sha256"] == after["sha256"]
    assert before["rows"] == 1


def test_fingerprint_detects_db_change(temp_db) -> None:
    """数据库中任意关键字段变化，指纹随之变化。"""
    import sqlite3

    from app.validation.fingerprint import fingerprint_from_db

    with sqlite3.connect(temp_db) as conn:
        conn.execute(
            "INSERT INTO etf_pool (code, name, category, fund_type, data_source, "
            "source_tested_at, status) VALUES ('510300','t','宽基指数ETF','x','t','2024-01-01','active')"
        )
        conn.execute(
            "INSERT INTO etf_daily_prices (code, trade_date, open, high, low, close, "
            "volume, amount, adjusted_close, adjustment_type, quality_status, source, collected_at) "
            "VALUES ('510300','2024-01-02',10,10.5,9.5,10,1000,10000,10,'qfq','valid','t','2024-01-01')"
        )
    before = fingerprint_from_db(db_path=temp_db)
    with sqlite3.connect(temp_db) as conn:
        conn.execute("UPDATE etf_daily_prices SET adjusted_close=10.5 WHERE code='510300'")
    after = fingerprint_from_db(db_path=temp_db)
    assert before["sha256"] != after["sha256"], "adjusted_close 变化未被识别"


def test_stress_assert_no_data_mutation_still_works() -> None:
    from app.validation.stress import StressError, assert_no_data_mutation

    base = {"sha256": "abc", "rows": 10}
    assert_no_data_mutation(base, {"sha256": "abc", "rows": 10}, "base")
    with pytest.raises(StressError, match="修改了历史数据"):
        assert_no_data_mutation(base, {"sha256": "xyz", "rows": 10}, "sparse_data")


def test_validation_config_declares_regime_ma_window() -> None:
    config = ValidationConfig(
        is_start="2021-01-01", is_end="2021-12-31",
        oos_start="2022-01-01", oos_end="2022-12-31",
    )
    config.validate()
    assert config.regime_ma_window == 250
    assert config.min_validation_days == 120
    assert config.regime_ma_window in config.as_dict().values()


def test_validation_config_rejects_bad_regime_window() -> None:
    with pytest.raises(Exception, match="regime_ma_window"):
        ValidationConfig(
            is_start="2021-01-01", is_end="2021-12-31",
            oos_start="2022-01-01", oos_end="2022-12-31",
            regime_ma_window=1,
        ).validate()
