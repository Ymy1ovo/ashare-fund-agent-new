"""历史回测 / 验证记录盘点与分类。

只读数据库，不写任何历史记录。分类结果必须能由 SQL + 本模块重新算出。

分类（每条记录恰好落一个桶，并且附带独立的事实字段供交叉核对）：

- `current_formal`   ：已经使用当前正式会计口径
- `replayed`         ：旧口径，但已存在成功的重放记录
- `non_replayable`   ：缺关键参数或无法证明参数，重放会变成猜测
- `legacy`           ：旧会计口径，参数可靠，待重放
- `unknown_legacy`   ：会计版本字段缺失或无法识别
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from app.database.db import get_connection

BACKTEST = "backtest"
VALIDATION = "validation"

# 会计口径版本标记（与 scripts/finalize_replay_records.py 保持一致）
CURRENT_ACCOUNTING = "ca-v2-receivable"
LEGACY_ACCOUNTING = "legacy_corporate_action_accounting"

CLASS_CURRENT_FORMAL = "current_formal"
CLASS_REPLAYED = "replayed"
CLASS_LEGACY = "legacy"
CLASS_UNKNOWN_LEGACY = "unknown_legacy"
CLASS_NON_REPLAYABLE = "non_replayable"

ALL_CLASSES = (
    CLASS_CURRENT_FORMAL,
    CLASS_REPLAYED,
    CLASS_LEGACY,
    CLASS_UNKNOWN_LEGACY,
    CLASS_NON_REPLAYABLE,
)

# 参数来源标注：决定这个值能不能当作「源记录的真实参数」
SRC_RECORDED = "recorded"      # 直接来自源记录字段
SRC_PROVEN = "proven"          # 由 config_hash 反证等于默认值
SRC_DERIVED = "derived"        # 由源记录字段推导
SRC_MISSING = "missing"        # 源记录里不存在，无法证明
SRC_DEFAULTED = "defaulted"    # 用当前默认值兜底（禁止用于正式重放）


class ReplayError(RuntimeError):
    """重放无法安全进行。"""


def _json(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _hash_params(payload: dict) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ValidationConfig 的字段全集（顺序无关，json sort_keys 会处理）。
_VALIDATION_FIELDS_CURRENT = (
    "strategy_name", "strategy_version", "is_start", "is_end", "oos_start", "oos_end",
    "initial_cash", "execution_price", "max_defer_days", "risk_free_rate",
    "annualization", "commission_rate", "min_commission", "slippage_bps",
    "rebalance_tolerance", "indicator_version", "ma_window_grid", "wf_grid",
    "pool_mode", "train_months", "test_months", "step_months", "regime_proxy_code",
    "regime_ma_window", "min_validation_days", "exclude_insufficient",
    "min_coverage_ratio", "notes",
)

# 阶段3A.3.2.1 之前的历史字段集（没有 regime_ma_window / min_validation_days）
_VALIDATION_FIELDS_HISTORICAL = tuple(
    name for name in _VALIDATION_FIELDS_CURRENT
    if name not in ("regime_ma_window", "min_validation_days")
)

_VALIDATION_DEFAULTS = {
    "strategy_name": "ma_trend",
    "strategy_version": "1.0.0",
    "initial_cash": 1_000_000.0,
    "execution_price": "open",
    "max_defer_days": 3,
    "risk_free_rate": 0.0,
    "annualization": 252,
    "commission_rate": 0.00025,
    "min_commission": 5.0,
    "slippage_bps": 5.0,
    "rebalance_tolerance": 0.02,
    "indicator_version": "v1.0.2-30b821a1af15",
    "wf_grid": [5, 20, 60],
    "train_months": 24,
    "test_months": 6,
    "step_months": 6,
    "regime_proxy_code": "510300",
    "regime_ma_window": 250,
    "min_validation_days": 120,
    "exclude_insufficient": True,
    "min_coverage_ratio": 0.95,
    "notes": [],
}


def _month_start(value: str | None) -> str | None:
    """存储的区间端点是「请求日期对齐到下一交易日」后的结果。

    例如请求 2021-01-01（元旦）→ 存储 2021-01-04。
    反推时把「存储值」和「该月 1 日」都当作候选。
    """
    if not value:
        return None
    try:
        parts = str(value)[:10].split("-")
        return f"{parts[0]}-{parts[1]}-01"
    except (IndexError, ValueError):
        return None


def _date_candidates(row) -> list[tuple[str, str, str, str]]:
    """区间端点候选组合；只有哈希完全命中的组合才算证明。"""
    import itertools

    axes = []
    for key in ("is_start", "is_end", "oos_start", "oos_end"):
        stored = row[key]
        options = [stored]
        month = _month_start(stored)
        if month and month != stored:
            options.append(month)
        axes.append(options)
    combos = list(itertools.product(*axes))
    return combos or [(row["is_start"], row["is_end"], row["oos_start"], row["oos_end"])]


def _validation_payload(row, pool_mode: str, fields: tuple[str, ...],
                        dates: tuple[str, str, str, str] | None = None) -> dict:
    payload = dict(_VALIDATION_DEFAULTS)
    dates = dates or (row["is_start"], row["is_end"], row["oos_start"], row["oos_end"])
    payload.update({
        "is_start": dates[0],
        "is_end": dates[1],
        "oos_start": dates[2],
        "oos_end": dates[3],
        "ma_window_grid": list(_json(row["ma_window_grid"], [])),
        "pool_mode": pool_mode,
        "strategy_name": row["strategy_name"] or _VALIDATION_DEFAULTS["strategy_name"],
        "strategy_version": row["strategy_version"] or _VALIDATION_DEFAULTS["strategy_version"],
    })
    return {name: payload[name] for name in fields}


def resolve_validation_config(row) -> dict:
    """用 `config_hash` 反证源记录的验证参数。

    `validation_runs` 只存了区间、网格、代码表，成本 / 资金 / 执行价 /
    指标版本等只体现在一列 `config_hash` 里。要「忠实沿用源参数」，
    唯一诚实的做法是：把候选参数代入哈希函数，只有**完全命中**才算证明。

    命中即证明：该记录的全部参数等于候选值（包括默认值那一批）。
    未命中则参数不可证明，不能重放。
    """
    stored = row["config_hash"]
    if not stored:
        return {
            "params": None,
            "status": SRC_MISSING,
            "reason": "config_hash 缺失，参数不可证明",
        }
    attempts: list[str] = []
    for fields, version in (
        (_VALIDATION_FIELDS_CURRENT, "current"),
        (_VALIDATION_FIELDS_HISTORICAL, "historical"),
    ):
        for pool_mode in ("all", "representative"):
            for dates in _date_candidates(row):
                payload = _validation_payload(row, pool_mode, fields, dates)
                digest = _hash_params(payload)
                attempts.append(f"{version}/{pool_mode}/{dates[0]}={digest}")
                if digest == stored:
                    payload["validation_id"] = row["validation_id"]
                    return {
                        "params": payload,
                        "status": SRC_PROVEN,
                        "reason": (
                            f"config_hash 完全命中（{version} 字段集，"
                            f"pool_mode={pool_mode}，请求区间 "
                            f"{dates[0]}~{dates[1]} / {dates[2]}~{dates[3]}），"
                            "全部参数可证明"
                        ),
                        "hash_variant": version,
                    }
    return {
        "params": None,
        "status": SRC_MISSING,
        "reason": (
            "config_hash 无法由已知字段集复现，成本 / 资金 / 执行价 / 指标版本等关键参数"
            f"不可证明（stored={stored}）"
        ),
        "attempts": attempts,
    }


def _accounting_class(accounting_version: str | None, summary: dict | None = None) -> str:
    """口径版本优先看列；列缺失时才接受 summary 里的书面证据。

    `backtest_runs.accounting_version` 是权威标记。只有它为空、且
    `summary_json` 里同时写着 `accounting_basis=formal_receivable` +
    `formal_valuation=True` 时，才认作正式——这是「有证据的正式」，
    不是「默认当成正式」。
    """
    if accounting_version == CURRENT_ACCOUNTING:
        return CLASS_CURRENT_FORMAL
    if accounting_version == LEGACY_ACCOUNTING:
        return CLASS_LEGACY
    if accounting_version is None and isinstance(summary, dict):
        if (summary.get("accounting_basis") == "formal_receivable"
                and summary.get("formal_valuation") is True):
            return CLASS_CURRENT_FORMAL
    return CLASS_UNKNOWN_LEGACY


def backtest_manifest(db_path=None, *, successes: dict[str, str] | None = None) -> list[dict]:
    """盘点全部 backtest_runs。

    `successes` 是 `{source_id: replay_id}` 的成功重放映射。
    """
    successes = successes or {}
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT run_id, strategy_name, strategy_version, config_json, initial_cash, "
            "start_date, end_date, etf_codes, indicator_version, snapshot_ids, input_hash, "
            "summary_json, created_at, accounting_version, evidence_version "
            "FROM backtest_runs ORDER BY created_at, run_id"
        ).fetchall()

    records: list[dict] = []
    for row in rows:
        config = _json(row["config_json"], {})
        summary = _json(row["summary_json"], {})
        codes = _json(row["etf_codes"], [])
        snapshots = _json(row["snapshot_ids"], {})
        strategy_name = row["strategy_name"]

        missing: list[str] = []
        params: dict[str, Any] = {"strategy_name": strategy_name}
        params_source: dict[str, str] = {}

        # 策略真实参数：ma_trend 的 ma_window 从未落库
        if strategy_name == "ma_trend":
            window = (config.get("strategy_params") or {}).get("ma_window")
            if window is None:
                missing.append("strategy_param:ma_window")
                params_source["ma_window"] = SRC_MISSING
            else:
                params["ma_window"] = window
                params_source["ma_window"] = SRC_RECORDED
        elif strategy_name == "buy_and_hold":
            params["weights"] = (config.get("strategy_params") or {}).get("weights") or {}
            params_source["weights"] = SRC_RECORDED
        else:
            missing.append(f"strategy_unknown:{strategy_name}")
            params_source["strategy_name"] = SRC_MISSING

        for key in ("start_date", "end_date", "initial_cash", "execution_price",
                    "costs", "max_defer_days", "risk_free_rate", "annualization",
                    "rebalance_tolerance", "cash_shortfall_policy", "allow_partial_fill",
                    "instrument_overrides", "lot_size_override"):
            if key in config:
                params[key] = config[key]
                params_source[key] = SRC_RECORDED
            elif key in ("start_date", "end_date", "initial_cash"):
                params[key] = row[key]
                params_source[key] = SRC_RECORDED
            else:
                missing.append(f"config:{key}")
                params_source[key] = SRC_MISSING

        if not codes:
            missing.append("etf_codes")
        if not snapshots:
            missing.append("snapshot_ids")
        # 指标版本只对依赖指标的策略是必需的；buy_and_hold 不用指标，
        # 历史上就是以 indicator_version=None 运行的
        if not row["indicator_version"] and strategy_name != "buy_and_hold":
            missing.append("indicator_version")

        accounting_class = _accounting_class(row["accounting_version"], summary)
        basis = summary.get("accounting_basis")
        formal = summary.get("formal_valuation")

        if row["run_id"] in successes:
            klass = CLASS_REPLAYED
            why = f"已存在成功重放记录 {successes[row['run_id']]}"
        elif accounting_class == CLASS_CURRENT_FORMAL:
            klass = CLASS_CURRENT_FORMAL
            why = f"accounting_version={CURRENT_ACCOUNTING}，已是当前正式口径"
        elif accounting_class == CLASS_UNKNOWN_LEGACY:
            klass = CLASS_UNKNOWN_LEGACY
            why = f"accounting_version={row['accounting_version']!r}，无法确认会计口径"
        elif missing:
            klass = CLASS_NON_REPLAYABLE
            why = "缺少关键参数，重放等于猜测：" + "、".join(missing)
        else:
            klass = CLASS_LEGACY
            why = f"accounting_version={LEGACY_ACCOUNTING}，参数完整，待重放"

        records.append({
            "kind": BACKTEST,
            "source_id": row["run_id"],
            "strategy_name": strategy_name,
            "strategy_version": row["strategy_version"],
            "start_date": row["start_date"],
            "end_date": row["end_date"],
            "etf_codes": codes,
            "etf_count": len(codes),
            "initial_cash": row["initial_cash"],
            "costs": config.get("costs"),
            "execution_price": config.get("execution_price"),
            "indicator_version": row["indicator_version"],
            "snapshot_ids": snapshots,
            "accounting_basis": basis,
            "formal_valuation": formal,
            "accounting_version": row["accounting_version"],
            "evidence_version": row["evidence_version"],
            "corporate_action_digest": summary.get("corporate_action_digest"),
            "input_hash": row["input_hash"],
            "created_at": row["created_at"],
            "strategy_params": params,
            "params_source": params_source,
            "missing_params": missing,
            "replayable": not missing and accounting_class != CLASS_CURRENT_FORMAL,
            "classification": klass,
            "classification_reason": why,
            "replay_record_id": successes.get(row["run_id"]),
        })
    return records


def validation_manifest(db_path=None, *, successes: dict[str, str] | None = None) -> list[dict]:
    """盘点全部 validation_runs。"""
    from app.validation.storage import init_validation_schema

    successes = successes or {}
    init_validation_schema(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT validation_id, strategy_name, strategy_version, config_hash, input_hash, "
            "etf_codes, excluded_codes, ma_window_grid, is_start, is_end, oos_start, oos_end, "
            "walkforward_config, benchmark_config, stress_config, status, conclusion, "
            "summary_json, error_message, created_at, finished_at, accounting_version, "
            "legacy_flag FROM validation_runs ORDER BY created_at, validation_id"
        ).fetchall()

    records: list[dict] = []
    for row in rows:
        codes = _json(row["etf_codes"], [])
        summary = _json(row["summary_json"], {})
        resolved = resolve_validation_config(row)
        params = resolved["params"]

        missing: list[str] = []
        if params is None:
            missing.append("config_hash_unproven")
        if not codes:
            missing.append("etf_codes")
        if not row["ma_window_grid"]:
            missing.append("ma_window_grid")
        if row["status"] != "success":
            missing.append(f"source_status:{row['status']}")

        accounting_class = _accounting_class(row["accounting_version"])
        if row["validation_id"] in successes:
            klass = CLASS_REPLAYED
            why = f"已存在成功重放记录 {successes[row['validation_id']]}"
        elif accounting_class == CLASS_CURRENT_FORMAL:
            klass = CLASS_CURRENT_FORMAL
            why = f"accounting_version={CURRENT_ACCOUNTING}，已是当前正式口径"
        elif accounting_class == CLASS_UNKNOWN_LEGACY:
            klass = CLASS_UNKNOWN_LEGACY
            why = f"accounting_version={row['accounting_version']!r}，无法确认会计口径"
        elif missing:
            klass = CLASS_NON_REPLAYABLE
            why = "缺少关键参数或源记录本身不可用：" + "、".join(missing)
        else:
            klass = CLASS_LEGACY
            why = f"accounting_version={LEGACY_ACCOUNTING}，参数已由 config_hash 证明，待重放"

        records.append({
            "kind": VALIDATION,
            "source_id": row["validation_id"],
            "strategy_name": row["strategy_name"],
            "strategy_version": row["strategy_version"],
            "is_start": row["is_start"],
            "is_end": row["is_end"],
            "oos_start": row["oos_start"],
            "oos_end": row["oos_end"],
            "etf_codes": codes,
            "etf_count": len(codes),
            "ma_window_grid": _json(row["ma_window_grid"], []),
            "config_hash": row["config_hash"],
            "params_proof": resolved["status"],
            "params_proof_reason": resolved["reason"],
            "resolved_params": params,
            "accounting_version": row["accounting_version"],
            "legacy_flag": row["legacy_flag"],
            "input_hash": row["input_hash"],
            "status": row["status"],
            "conclusion": row["conclusion"],
            "error_message": row["error_message"],
            "created_at": row["created_at"],
            "finished_at": row["finished_at"],
            "missing_params": missing,
            "replayable": not missing and accounting_class != CLASS_CURRENT_FORMAL,
            "classification": klass,
            "classification_reason": why,
            "replay_record_id": successes.get(row["validation_id"]),
        })
    return records


def summarize(records: list[dict]) -> dict:
    """按分类汇总；同时给出交叉核对用的独立计数。"""
    counts = {name: 0 for name in ALL_CLASSES}
    for item in records:
        counts[item["classification"]] = counts.get(item["classification"], 0) + 1
    replayable = sum(1 for item in records if item["replayable"])
    return {
        "total": len(records),
        "counts": counts,
        "replayable": replayable,
        "non_replayable": sum(1 for item in records if item["missing_params"]),
        "pending_replay": counts[CLASS_LEGACY],
        "already_replayed": counts[CLASS_REPLAYED],
        "sum_matches_total": sum(counts.values()) == len(records),
    }
