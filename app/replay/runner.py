"""重放执行器：按源记录重建配置、调用现有引擎、登记对应关系。

三条硬约束：

1. **只读源记录**：不 UPDATE / DELETE 任何历史行。
2. **参数必须可证明**：源参数由 `config_hash` 反证或直接存于源记录；
   任何一项不可证明就判 `non_replayable`，不用当前默认值去猜。
3. **正式口径**：重放一律 `apply_corporate_actions=True`，
   结果必须是 `formal_receivable` + `formal_valuation=True`；
   否则记为失败，不允许把非正式结果写进正式验证结论。
"""
from __future__ import annotations

import json
from typing import Any

from app.backtest.config import BacktestConfig, CostConfig
from app.database.db import get_connection
from app.backtest.api import ACCOUNTING_FORMAL, is_formal_run
from app.replay.manifest import (
    BACKTEST,
    CURRENT_ACCOUNTING,
    VALIDATION,
    ReplayError,
    backtest_manifest,
    validation_manifest,
)
from app.replay.registry import (
    STATUS_FAILED,
    STATUS_SKIPPED,
    STATUS_SUCCESS,
    ReplayOutcome,
    finish_attempt,
    find_success,
    start_attempt,
)


def load_backtest_source(source_id: str, db_path=None) -> dict:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM backtest_runs WHERE run_id=?", (source_id,)
        ).fetchone()
    if not row:
        raise ReplayError(f"源回测记录不存在：{source_id}")
    for item in backtest_manifest(db_path):
        if item["source_id"] == source_id:
            return item
    raise ReplayError(f"源回测记录无法盘点：{source_id}")


def load_validation_source(source_id: str, db_path=None) -> dict:
    from app.validation.storage import init_validation_schema

    init_validation_schema(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT validation_id FROM validation_runs WHERE validation_id=?", (source_id,)
        ).fetchone()
    if not row:
        raise ReplayError(f"源验证记录不存在：{source_id}")
    for item in validation_manifest(db_path):
        if item["source_id"] == source_id:
            return item
    raise ReplayError(f"源验证记录无法盘点：{source_id}")


def _stamp_replay_record(run_id: str, digest: str | None, *, db_path=None) -> None:
    """给**本次新建**的重放记录打上会计版本标记。

    只写刚创建的 run_id，不触碰任何历史行。
    这一步是必需的：`save_result()` 只写 `summary_json`，而盘点分类读的是
    `backtest_runs.accounting_version`；不标记会让新记录被判成 unknown_legacy。
    """
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE backtest_runs SET accounting_version=?, evidence_version=? "
            "WHERE run_id=?",
            (CURRENT_ACCOUNTING, digest or "unknown", run_id),
        )


def build_backtest_config(source: dict) -> BacktestConfig:
    """用源记录参数构造回测配置；缺项直接报错，不填默认值。"""
    params = source["strategy_params"]
    missing = [name for name in ("start_date", "end_date", "initial_cash", "costs")
               if name not in params]
    if missing:
        raise ReplayError(f"{source['source_id']} 缺少回测参数：{'、'.join(missing)}")
    if source["strategy_name"] == "ma_trend" and "ma_window" not in params:
        raise ReplayError(
            f"{source['source_id']} 缺少 ma_trend 的 ma_window，无法忠实重放"
        )

    costs = params["costs"] or {}
    return BacktestConfig(
        start_date=params["start_date"],
        end_date=params["end_date"],
        initial_cash=float(params["initial_cash"]),
        execution_price=params.get("execution_price", "open"),
        max_defer_days=int(params.get("max_defer_days", 3)),
        risk_free_rate=float(params.get("risk_free_rate", 0.0)),
        annualization=int(params.get("annualization", 252)),
        rebalance_tolerance=float(params.get("rebalance_tolerance", 0.02)),
        cash_shortfall_policy=params.get("cash_shortfall_policy", "reduce"),
        allow_partial_fill=bool(params.get("allow_partial_fill", False)),
        costs=CostConfig(
            commission_rate=float(costs.get("commission_rate", 0.00025)),
            min_commission=float(costs.get("min_commission", 5.0)),
            slippage_bps=float(costs.get("slippage_bps", 5.0)),
            slippage_fixed=float(costs.get("slippage_fixed", 0.0)),
            stamp_duty_rate=float(costs.get("stamp_duty_rate", 0.0)),
            transfer_fee_rate=float(costs.get("transfer_fee_rate", 0.0)),
        ),
        instrument_overrides=params.get("instrument_overrides") or {},
        lot_size_override=params.get("lot_size_override"),
        # 重放只允许正式口径；源记录若曾关闭公司行为，重放也必须打开
        apply_corporate_actions=True,
        strategy_params=dict(source["strategy_params"]),
    )


def build_validation_config(source: dict):
    """用已证实的参数重建 ValidationConfig。"""
    from app.validation.config import ValidationConfig

    params = source["resolved_params"]
    if not params:
        raise ReplayError(
            f"{source['source_id']} 参数不可证明：{source['params_proof_reason']}"
        )
    fields = {
        name: params[name] for name in (
            "is_start", "is_end", "oos_start", "oos_end", "initial_cash",
            "execution_price", "max_defer_days", "risk_free_rate", "annualization",
            "commission_rate", "min_commission", "slippage_bps",
            "rebalance_tolerance", "indicator_version", "pool_mode",
            "train_months", "test_months", "step_months", "regime_proxy_code",
            "regime_ma_window", "min_validation_days", "exclude_insufficient",
            "min_coverage_ratio",
        ) if name in params
    }
    fields["ma_window_grid"] = tuple(params["ma_window_grid"])
    fields["wf_grid"] = tuple(params["wf_grid"])
    return ValidationConfig(**fields)


def _make_strategy(source: dict):
    from app.backtest.strategies.buy_and_hold import BuyAndHoldStrategy
    from app.backtest.strategies.ma_trend import MovingAverageTrendStrategy

    if source["strategy_name"] == "ma_trend":
        window = source["strategy_params"].get("ma_window")
        if window is None:
            raise ReplayError(f"{source['source_id']} 缺少 ma_window")
        return MovingAverageTrendStrategy(ma_window=int(window))
    if source["strategy_name"] == "buy_and_hold":
        weights = source["strategy_params"].get("weights") or {}
        return BuyAndHoldStrategy(weights=weights)
    raise ReplayError(f"{source['source_id']} 策略不受支持：{source['strategy_name']}")


def replay_backtest(
    source_id: str,
    *,
    force: bool = False,
    save: bool = True,
    db_path=None,
) -> ReplayOutcome:
    """重放一条历史回测。

    `force=False` 时若已有成功重放则直接跳过（幂等）。
    """
    source = load_backtest_source(source_id, db_path)
    prior = find_success(BACKTEST, source_id, db_path)
    if prior and not force:
        return ReplayOutcome(
            source_id=source_id, status=STATUS_SKIPPED, replay_id=prior,
            reason=f"已存在成功重放 {prior}，跳过（用 --force 强制重跑）",
        )

    attempt = start_attempt(
        BACKTEST, source_id,
        source_input_hash=source["input_hash"],
        source_accounting_version=source["accounting_version"],
        replay_params=source["strategy_params"],
        db_path=db_path,
    )

    try:
        config = build_backtest_config(source)
        strategy = _make_strategy(source)
    except ReplayError as exc:
        finish_attempt(attempt, STATUS_FAILED, reason=str(exc), db_path=db_path)
        return ReplayOutcome(source_id=source_id, status=STATUS_FAILED,
                             reason=str(exc), attempt_id=attempt)

    from app.backtest.engine import BacktestEngine
    from app.backtest.metrics import compute_performance
    from app.backtest.storage import save_result

    try:
        engine = BacktestEngine(config, strategy, db_path=db_path)
        result = engine.run(list(source["etf_codes"]),
                            indicator_version=source["indicator_version"])
        # 严格白名单：两个字段必须同时精确命中，不做真值转换。
        # `1 == True` 但 `1 is not True`，非布尔真值一律拒绝。
        basis = getattr(result, "accounting_basis", None)
        formal = getattr(result, "formal_valuation", None)
        if (basis != ACCOUNTING_FORMAL
                or not isinstance(formal, bool) or formal is not True):
            raise ReplayError(
                f"重放结果不是正式口径（accounting_basis={basis!r}，"
                f"formal_valuation={formal!r}）"
            )
        performance = compute_performance(
            result.daily, result.trades, result.orders, result.initial_cash,
            annualization=config.annualization, risk_free_rate=config.risk_free_rate,
        )
        if save:
            save_result(result, performance, db_path=db_path)
            _stamp_replay_record(result.run_id, engine.corporate_action_digest,
                                 db_path=db_path)
    except Exception as exc:  # noqa: BLE001 单条失败不拖垮批量
        finish_attempt(attempt, STATUS_FAILED, reason=f"{type(exc).__name__}: {exc}",
                       db_path=db_path)
        return ReplayOutcome(source_id=source_id, status=STATUS_FAILED,
                             reason=f"{type(exc).__name__}: {exc}", attempt_id=attempt)

    finish_attempt(
        attempt, STATUS_SUCCESS,
        replay_record_id=result.run_id,
        replay_input_hash=result.input_hash,
        replay_accounting_version=result.accounting_basis,
        db_path=db_path,
    )
    return ReplayOutcome(
        source_id=source_id, status=STATUS_SUCCESS, replay_id=result.run_id,
        attempt_id=attempt,
        extra={
            "input_hash": result.input_hash,
            "accounting_basis": result.accounting_basis,
            "formal_valuation": result.formal_valuation,
            "total_return": performance.total_return,
            "corporate_action_digest": engine.corporate_action_digest,
        },
    )


def _fetch_validation_record(validation_id: str, *, db_path=None):
    """回查重放落库后的 (input_hash, accounting_version)。查不到返回 None。

    单独抽成函数，既让「查不到」与「版本异常」两条失败路径可被独立测试，
    也避免测试为了造一个 None 而整体替换数据库连接。
    """
    with get_connection(db_path) as conn:
        return conn.execute(
            "SELECT input_hash, accounting_version FROM validation_runs "
            "WHERE validation_id=?", (validation_id,)
        ).fetchone()


def replay_validation(    source_id: str,
    *,
    force: bool = False,
    db_path=None,
) -> ReplayOutcome:
    """重放一条历史验证记录。"""
    source = load_validation_source(source_id, db_path)
    prior = find_success(VALIDATION, source_id, db_path)
    if prior and not force:
        return ReplayOutcome(
            source_id=source_id, status=STATUS_SKIPPED, replay_id=prior,
            reason=f"已存在成功重放 {prior}，跳过（用 --force 强制重跑）",
        )

    attempt = start_attempt(
        VALIDATION, source_id,
        source_input_hash=source["input_hash"],
        source_accounting_version=source["accounting_version"],
        source_config_hash=source["config_hash"],
        replay_params=source["resolved_params"],
        db_path=db_path,
    )

    try:
        config = build_validation_config(source)
    except ReplayError as exc:
        finish_attempt(attempt, STATUS_FAILED, reason=str(exc), db_path=db_path)
        return ReplayOutcome(source_id=source_id, status=STATUS_FAILED,
                             reason=str(exc), attempt_id=attempt)

    from app.validation.runner import run_validation

    try:
        result = run_validation(config, db_path=db_path)
    except Exception as exc:  # noqa: BLE001 单条失败不拖垮批量
        finish_attempt(attempt, STATUS_FAILED,
                       reason=f"{type(exc).__name__}: {exc}", db_path=db_path)
        return ReplayOutcome(source_id=source_id, status=STATUS_FAILED,
                             reason=f"{type(exc).__name__}: {exc}", attempt_id=attempt)

    row = _fetch_validation_record(result.validation_id, db_path=db_path)

    # 阶段3A.3.2.3.2：三处原本会被短路放行的情况必须失败
    #   1) 落库记录查不到（row is None）
    #   2) accounting_version 为 None / 空串
    #   3) accounting_version 非 str 或不是 ca-v2-receivable
    # 旧实现 `if replay_acct and replay_acct != CURRENT` 在 (1)(2) 时
    # `replay_acct` 为 None，短路后直接落到成功分支。
    if row is None:
        finish_attempt(attempt, STATUS_FAILED,
                       replay_record_id=result.validation_id,
                       reason=f"重放后查不到新 validation 记录：{result.validation_id}",
                       db_path=db_path)
        return ReplayOutcome(
            source_id=source_id, status=STATUS_FAILED,
            replay_id=result.validation_id,
            reason=f"重放后查不到新 validation 记录：{result.validation_id}",
            attempt_id=attempt,
        )

    replay_acct = row[1]
    if not isinstance(replay_acct, str) or replay_acct != CURRENT_ACCOUNTING:
        finish_attempt(attempt, STATUS_FAILED,
                       replay_record_id=result.validation_id,
                       reason=f"重放记录会计版本异常：{replay_acct!r}", db_path=db_path)
        return ReplayOutcome(source_id=source_id, status=STATUS_FAILED,
                             replay_id=result.validation_id,
                             reason=f"重放记录会计版本异常：{replay_acct!r}",
                             attempt_id=attempt)

    replay_hash = str(row[0]) if row[0] else None

    finish_attempt(
        attempt, STATUS_SUCCESS,
        replay_record_id=result.validation_id,
        replay_input_hash=replay_hash,
        replay_accounting_version=replay_acct,
        db_path=db_path,
    )
    return ReplayOutcome(
        source_id=source_id, status=STATUS_SUCCESS, replay_id=result.validation_id,
        attempt_id=attempt,
        extra={
            "input_hash": replay_hash,
            "conclusion": result.conclusion,
            "etf_count": len(result.codes),
        },
    )


def replay_many(
    kind: str,
    source_ids: list[str],
    *,
    force: bool = False,
    save: bool = True,
    db_path=None,
    on_progress=None,
) -> list[ReplayOutcome]:
    """批量重放：单条失败不影响其他记录，中断后未做的保持未做。"""
    outcomes: list[ReplayOutcome] = []
    for source_id in source_ids:
        try:
            if kind == BACKTEST:
                outcome = replay_backtest(source_id, force=force, save=save, db_path=db_path)
            else:
                outcome = replay_validation(source_id, force=force, db_path=db_path)
        except Exception as exc:  # noqa: BLE001 单条隔离
            outcome = ReplayOutcome(
                source_id=source_id, status=STATUS_FAILED,
                reason=f"{type(exc).__name__}: {exc}",
            )
        outcomes.append(outcome)
        if on_progress:
            on_progress(outcome)
    return outcomes


def pending_sources(kind: str, db_path=None) -> list[str]:
    """待重放清单：分类为 legacy 的记录（不含已重放、不可重放、已正式）。"""
    items = backtest_manifest(db_path) if kind == BACKTEST else validation_manifest(db_path)
    return [item["source_id"] for item in items if item["classification"] == "legacy"]
