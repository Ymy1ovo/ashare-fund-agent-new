"""阶段3A.3.2.3.4：validation 内部回测审计上下文与关联登记。

一次 validation 内部会跑很多次 BacktestEngine（样本内网格 / 样本外 /
Walk-Forward 训练与测试 / 基准 / 成本与滑点压力 / sparse / insufficient）。
这些运行各自有独立 run_id，且引擎会把公司行为应用与分红应收按 run_id
写进 `corporate_action_applications` / `dividend_receivables`。

本模块做三件事：

1. 用 contextvar 传递「当前 validation 上下文」，让嵌套的每一次回测都能
   自动登记，不需要在每个调用点手动传参（漏传即漏登记）。
2. 把每次回测的 run_id / 角色 / 场景 / 口径 / 指纹写进
   `validation_backtest_runs`，形成 validation → 内部回测的稳定链路。
3. 只读查询：给定 validation_id，汇总内部回测与公司行为审计明细。

失败处理原则：登记失败**不吞异常**。校验口径不通过的记录不允许登记，
登记异常向上抛出——宁可整次 validation 失败，也不留一条看起来完整的假审计。
"""
from __future__ import annotations

import contextvars
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.backtest.api import ACCOUNTING_DISABLED, ACCOUNTING_FORMAL, ACCOUNTING_UNKNOWN
from app.database.db import get_connection

VALIDATION_BACKTEST_SCHEMA = """
CREATE TABLE IF NOT EXISTS validation_backtest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    validation_id TEXT NOT NULL,
    backtest_run_id TEXT NOT NULL,
    run_role TEXT NOT NULL,
    scenario_key TEXT,
    strategy_name TEXT,
    strategy_version TEXT,
    strategy_params_json TEXT,
    start_date TEXT,
    end_date TEXT,
    indicator_version TEXT,
    initial_cash REAL,
    codes_json TEXT,
    accounting_basis TEXT,
    formal_valuation INTEGER,
    input_hash TEXT,
    corporate_action_digest TEXT,
    applied_action_count INTEGER,
    receivable_count INTEGER,
    receivable_amount REAL,
    settled_count INTEGER,
    settled_amount REAL,
    status TEXT NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(validation_id, backtest_run_id)
);
CREATE INDEX IF NOT EXISTS idx_vbr_validation
    ON validation_backtest_runs(validation_id);
CREATE INDEX IF NOT EXISTS idx_vbr_run ON validation_backtest_runs(backtest_run_id);
CREATE INDEX IF NOT EXISTS idx_vbr_role ON validation_backtest_runs(run_role);
"""

VALIDATION_REGIME_SCHEMA = """
CREATE TABLE IF NOT EXISTS validation_regime_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    validation_id TEXT NOT NULL,
    regime_label TEXT NOT NULL,
    proxy_code TEXT,
    status TEXT NOT NULL,
    total_days INTEGER,
    valid_days INTEGER,
    missing_days INTEGER,
    samples INTEGER,
    cumulative_return REAL,
    mean_daily_return REAL,
    annualized_volatility REAL,
    win_rate REAL,
    sharpe_ratio REAL,
    sortino_ratio REAL,
    cagr REAL,
    max_drawdown REAL,
    trade_count INTEGER,
    min_samples INTEGER,
    reason TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(validation_id, regime_label)
);
CREATE INDEX IF NOT EXISTS idx_vrs_validation
    ON validation_regime_stats(validation_id);
"""

# 角色常量：与任务书 §2 的九类调用一一对应
ROLE_IN_SAMPLE = "in_sample_grid"
ROLE_OOS = "out_of_sample"
ROLE_WF_TRAIN = "walkforward_train"
ROLE_WF_TEST = "walkforward_test"
ROLE_REGIME = "regime_grouping"
ROLE_BENCHMARK = "benchmark"
ROLE_STRESS_COST = "stress_cost_slippage"
ROLE_STRESS_SPARSE = "stress_sparse_data"
ROLE_STRESS_INSUFFICIENT = "stress_insufficient"

ALL_ROLES = (
    ROLE_IN_SAMPLE, ROLE_OOS, ROLE_WF_TRAIN, ROLE_WF_TEST, ROLE_REGIME,
    ROLE_BENCHMARK, ROLE_STRESS_COST, ROLE_STRESS_SPARSE,
    ROLE_STRESS_INSUFFICIENT,
)

_AUDITABLE_BASES = (ACCOUNTING_FORMAL,)


class AuditError(RuntimeError):
    """审计登记失败；不允许吞掉变成「看起来成功」。"""


def init_audit_schema(db_path=None) -> None:
    with get_connection(db_path) as conn:
        conn.executescript(VALIDATION_BACKTEST_SCHEMA)
        conn.executescript(VALIDATION_REGIME_SCHEMA)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class AuditContext:
    """一次 validation 的审计上下文。"""

    validation_id: str
    role: str = ROLE_OOS
    scenario_key: str | None = None
    notes: list[str] = field(default_factory=list)

    def child(self, role: str, scenario_key: str | None = None) -> "AuditContext":
        return AuditContext(validation_id=self.validation_id, role=role,
                            scenario_key=scenario_key)


_CURRENT: "contextvars.ContextVar[AuditContext | None]" = contextvars.ContextVar(
    "validation_audit_context", default=None
)


def current_context() -> AuditContext | None:
    return _CURRENT.get()


def bind(validation_id: str) -> tuple[AuditContext, Any]:
    """绑定上下文，返回 (ctx, token)；调用方负责 reset。"""
    ctx = AuditContext(validation_id=validation_id)
    return ctx, _CURRENT.set(ctx)


def reset(token) -> None:
    _CURRENT.reset(token)


class audit_scope:  # noqa: N801 - 用作 with 语句，语义化命名
    """`with audit_scope(ctx, ROLE_IN_SAMPLE, f"ma{window}"): ...`"""

    def __init__(self, role: str, scenario_key: str | None = None,
                 validation_id: str | None = None):
        self.role = role
        self.scenario_key = scenario_key
        self.explicit_validation_id = validation_id
        self._token = None

    def __enter__(self):
        base = current_context()
        vid = self.explicit_validation_id or (base.validation_id if base else None)
        if vid is None:
            raise AuditError("审计上下文缺少 validation_id，拒绝静默跳过登记")
        ctx = AuditContext(validation_id=vid, role=self.role,
                           scenario_key=self.scenario_key)
        self._token = _CURRENT.set(ctx)
        return ctx

    def __exit__(self, *exc_info):
        if self._token is not None:
            _CURRENT.reset(self._token)
        return False


def _int_or_none(value):
    return int(value) if value is not None else None


def register_backtest(
    result,
    *,
    role: str,
    scenario_key: str | None = None,
    validation_id: str | None = None,
    status: str = "success",
    reason: str | None = None,
    db_path=None,
    detail_db_path=None,
) -> int:
    """登记一次内部回测。返回关联行 id。

    强制校验：正式会计口径不通过就拒绝登记（不写半条）。
    """
    ctx = current_context()
    vid = validation_id or (ctx.validation_id if ctx else None)
    if not vid:
        raise AuditError("缺少 validation_id，拒绝登记内部回测")
    # 场景键缺省时从上下文取：调用点漏传不应导致场景信息丢失
    if scenario_key is None and ctx is not None:
        scenario_key = ctx.scenario_key

    basis = getattr(result, "accounting_basis", None)
    formal = getattr(result, "formal_valuation", None)
    if basis not in _AUDITABLE_BASES:
        raise AuditError(f"内部回测会计口径非正式：accounting_basis={basis!r}")
    if not isinstance(formal, bool) or formal is not True:
        raise AuditError(f"内部回测 formal_valuation 非布尔真值：{formal!r}")

    run_id = getattr(result, "run_id", None)
    if not run_id:
        raise AuditError("内部回测缺少 run_id，无法关联公司行为明细")

    cfg = getattr(result, "config", None)
    params: dict[str, Any] = {}
    if cfg is not None:
        strategy_params = getattr(cfg, "strategy_params", None)
        if isinstance(strategy_params, dict):
            params = dict(strategy_params)

    payable = getattr(result, "dividend_receivables", None)
    init_audit_schema(db_path)
    # 明细可能写在与登记不同的库（如 sparse 场景的副本库）。
    # 此时必须去明细库统计，绝不能对着主库查出 0 就当「没有发生」。
    summary_src = None
    if detail_db_path is not None and detail_db_path != db_path:
        with get_connection(detail_db_path) as detail_conn:
            summary_src = _summary_for_run(detail_conn, run_id)
        detail_source = str(detail_db_path)
    else:
        detail_source = None
    with get_connection(db_path) as conn:
        if summary_src is None:
            summary_src = _summary_for_run(conn, run_id)
        applied = summary_src["applied"]
        receivable_rows = summary_src["receivable_count"]
        receivable_amount = summary_src["receivable_amount"]
        if not applied:
            applied = len(getattr(result, "corporate_action_log", []) or [])
        try:
            conn.execute(
                "INSERT INTO validation_backtest_runs "
                "(validation_id, backtest_run_id, run_role, scenario_key, "
                " strategy_name, strategy_version, strategy_params_json, "
                " start_date, end_date, indicator_version, initial_cash, codes_json, "
                " accounting_basis, formal_valuation, input_hash, "
                " corporate_action_digest, applied_action_count, receivable_count, "
                " receivable_amount, settled_count, settled_amount, "
                " status, reason, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    vid, run_id, role, scenario_key,
                    getattr(result, "strategy_name", None),
                    getattr(result, "strategy_version", None),
                    json.dumps(params, ensure_ascii=False, sort_keys=True, default=str),
                    getattr(cfg, "start_date", None),
                    getattr(cfg, "end_date", None),
                    getattr(result, "indicator_version", None),
                    getattr(result, "initial_cash", None),
                    json.dumps(list(getattr(result, "codes", []) or []), ensure_ascii=False),
                    basis, 1 if formal else 0,
                    getattr(result, "input_hash", None),
                    getattr(result, "corporate_action_digest", None),
                    int(applied or 0), int(receivable_rows or 0),
                    float(receivable_amount or 0.0),
                    int(summary_src["settled_count"]),
                    float(summary_src["settled_amount"]),
                    status, reason, _now(),
                ),
            )
        except Exception as exc:  # noqa: BLE001 唯一约束冲突等一律上抛
            raise AuditError(
                f"登记内部回测失败（validation={vid}，run={run_id}，role={role}）：{exc}"
            ) from exc
        row = conn.execute(
            "SELECT id FROM validation_backtest_runs "
            "WHERE validation_id=? AND backtest_run_id=?", (vid, run_id)
        ).fetchone()
    return int(row[0]) if row else 0


def _summary_for_run(conn, run_id: str) -> dict:
    """统计某个 run 的公司行为明细：应用数、应收、已结算。"""
    applied = conn.execute(
        "SELECT COUNT(*) FROM corporate_action_applications WHERE run_id=?", (run_id,)
    ).fetchone()[0]
    row = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(amount), 0.0) FROM dividend_receivables "
        "WHERE run_id=?", (run_id,)
    ).fetchone()
    settled = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(amount), 0.0) FROM dividend_receivables "
        "WHERE run_id=? AND settled_at IS NOT NULL", (run_id,)
    ).fetchone()
    return {
        "applied": int(applied),
        "receivable_count": int(row[0]),
        "receivable_amount": float(row[1] or 0.0),
        "settled_count": int(settled[0]),
        "settled_amount": float(settled[1] or 0.0),
    }


def save_regime_stats(validation_id: str, regime_payload: dict, *,
                      db_path=None) -> int:
    """把已经算好的 regime 分组统计落库；不重算、不改分类算法。"""
    if not isinstance(regime_payload, dict):
        return 0
    stats = regime_payload.get("stats")
    proxy = regime_payload.get("proxy_code")
    min_samples = regime_payload.get("min_samples")
    if min_samples is None:
        min_samples = regime_payload.get("min_regime_samples")
    if not isinstance(stats, dict):
        stats = {}
    init_audit_schema(db_path)
    labels = ["bull", "bear", "range", "unclassified"]
    written = 0
    with get_connection(db_path) as conn:
        for label in labels:
            entry = stats.get(label)
            if entry is None:
                conn.execute(
                    "INSERT OR REPLACE INTO validation_regime_stats "
                    "(validation_id, regime_label, proxy_code, status, min_samples, "
                    " reason, created_at) VALUES (?,?,?,?,?,?,?)",
                    (validation_id, label, proxy, "unavailable", min_samples,
                     "该环境在该次验证中未产生统计", _now()),
                )
                written += 1
                continue
            conn.execute(
                "INSERT OR REPLACE INTO validation_regime_stats "
                "(validation_id, regime_label, proxy_code, status, total_days, "
                " valid_days, missing_days, samples, cumulative_return, "
                " mean_daily_return, annualized_volatility, win_rate, "
                " sharpe_ratio, sortino_ratio, cagr, max_drawdown, trade_count, "
                " min_samples, reason, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    validation_id, label, proxy, entry.get("status", "unknown"),
                    _int_or_none(entry.get("total_days")),
                    _int_or_none(entry.get("valid_days")),
                    _int_or_none(entry.get("missing_days")),
                    _int_or_none(entry.get("samples")),
                    entry.get("cumulative_return"),
                    entry.get("mean_daily_return"),
                    entry.get("annualized_volatility"),
                    entry.get("win_rate"),
                    entry.get("sharpe_ratio"),
                    entry.get("sortino_ratio"),
                    entry.get("cagr"),
                    entry.get("max_drawdown"),
                    _int_or_none(entry.get("trade_count")),
                    min_samples,
                    entry.get("reason"),
                    _now(),
                ),
            )
            written += 1
    return written


def init_validation_schema_compat(db_path=None) -> None:
    """建 validation 表并补齐迁移列。

    `init_validation_schema()` 只建基表；`accounting_version` / `legacy_flag`
    是由 `app.database.db._migrate()` 后加的。审计查询要读这两列，
    所以这里显式补一次（幂等，仅 ADD COLUMN）。
    """
    from app.validation.storage import init_validation_schema

    init_validation_schema(db_path)
    with get_connection(db_path) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(validation_runs)")}
        if "accounting_version" not in cols:
            conn.execute("ALTER TABLE validation_runs ADD COLUMN accounting_version TEXT")
        if "legacy_flag" not in cols:
            conn.execute("ALTER TABLE validation_runs ADD COLUMN legacy_flag TEXT")


def list_backtest_runs(validation_id: str, *, role: str | None = None,
                       db_path=None) -> list[dict]:
    init_audit_schema(db_path)
    sql = "SELECT * FROM validation_backtest_runs WHERE validation_id=?"
    params: list[Any] = [validation_id]
    if role:
        sql += " AND run_role=?"
        params.append(role)
    sql += " ORDER BY id"
    with get_connection(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def list_regime_stats(validation_id: str, *, db_path=None) -> list[dict]:
    init_audit_schema(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM validation_regime_stats WHERE validation_id=? "
            "ORDER BY regime_label", (validation_id,)
        ).fetchall()
    return [dict(row) for row in rows]


def audit_trace(validation_id: str, *, db_path=None) -> dict:
    """从 validation_id 一路追到公司行为明细与事件版本。

    链路：validation_runs → validation_backtest_runs
          → corporate_action_applications / dividend_receivables
          → corporate_actions / corporate_action_versions
    """
    init_validation_schema_compat(db_path)
    init_audit_schema(db_path)
    with get_connection(db_path) as conn:
        vr = conn.execute(
            "SELECT validation_id, status, accounting_version, input_hash, "
            "created_at, finished_at FROM validation_runs WHERE validation_id=?",
            (validation_id,),
        ).fetchone()
        if not vr:
            return {"validation_id": validation_id, "found": False,
                    "audit_status": "validation_not_found", "links": []}

        runs = conn.execute(
            "SELECT * FROM validation_backtest_runs WHERE validation_id=? ORDER BY id",
            (validation_id,),
        ).fetchall()
        if not runs:
            return {
                "validation_id": validation_id, "found": True,
                "audit_status": "unavailable_legacy",
                "validation_status": vr["status"],
                "accounting_version": vr["accounting_version"],
                "reason": "该 validation 无内部回测登记（生成于审计体系之前或未启用审计）",
                "links": [],
            }

        links: list[dict] = []
        for run in runs:
            run_id = run["backtest_run_id"]
            apps = conn.execute(
                "SELECT * FROM corporate_action_applications WHERE run_id=?", (run_id,)
            ).fetchall()
            receivables = conn.execute(
                "SELECT * FROM dividend_receivables WHERE run_id=?", (run_id,)
            ).fetchall()
            action_ids = sorted({int(a["action_id"]) for a in apps}
                                | {int(r["action_id"]) for r in receivables})
            events: list[dict] = []
            if action_ids:
                marks = ",".join("?" for _ in action_ids)
                for ev in conn.execute(
                    "SELECT action_id, code, action_type, ex_date, effective_date, "
                    "record_date, pay_date, share_ratio, cash_per_share, "
                    "evidence_status, status, version_no, event_fingerprint "
                    f"FROM corporate_actions WHERE action_id IN ({marks}) "
                    "ORDER BY action_id", action_ids):
                    events.append(dict(ev))
            settled = [r for r in receivables if r["settled_at"]]
            # 明细可能不在主库（如 sparse 场景写在稀疏副本库）。
            # 此时主库查出 0 不等于「没有发生」，必须按登记表里的实际计数
            # 呈现，并标注明细所在位置，不得用 0 冒充。
            registered_app = int(run["applied_action_count"] or 0)
            registered_recv = int(run["receivable_count"] or 0)
            off_main_db = (len(apps) == 0 and len(receivables) == 0
                           and (registered_app or registered_recv))
            if off_main_db:
                apps_n, recv_n = registered_app, registered_recv
                amt = float(run["receivable_amount"] or 0.0)
                settled_n = int(run["settled_count"] or 0)
                settled_amt = float(run["settled_amount"] or 0.0)
                detail_location = "external_copy_db"
            else:
                apps_n, recv_n = len(apps), len(receivables)
                amt = sum(float(r["amount"] or 0.0) for r in receivables)
                settled_n = len(settled)
                settled_amt = sum(float(r["amount"] or 0.0) for r in settled)
                detail_location = "main_db"
            links.append({
                "backtest_run_id": run_id,
                "run_role": run["run_role"],
                "scenario_key": run["scenario_key"],
                "status": run["status"],
                "accounting_basis": run["accounting_basis"],
                "formal_valuation": bool(run["formal_valuation"]),
                "input_hash": run["input_hash"],
                "corporate_action_digest": run["corporate_action_digest"],
                "application_count": apps_n,
                "receivable_count": recv_n,
                "receivable_amount": round(amt, 6),
                "settled_count": settled_n,
                "settled_amount": round(settled_amt, 6),
                "unsettled_count": recv_n - settled_n,
                "unsettled_amount": round(amt - settled_amt, 6),
                "detail_location": detail_location,
                "detail_note": run["reason"] if off_main_db else None,
                "events": events,
            })

    roles = {}
    for link in links:
        roles[link["run_role"]] = roles.get(link["run_role"], 0) + 1
    complete = all(link["status"] == "success" for link in links)
    return {
        "validation_id": validation_id,
        "found": True,
        "audit_status": "complete" if complete else "incomplete",
        "validation_status": vr["status"],
        "accounting_version": vr["accounting_version"],
        "input_hash": vr["input_hash"],
        "backtest_run_count": len(links),
        "role_counts": roles,
        "links": links,
        "regime": list_regime_stats(validation_id, db_path=db_path),
    }


def audit_coverage(validation_id: str, db_path=None) -> dict:
    """检查内部回测登记是否覆盖了应有的角色。

    只做事实核对：哪些角色出现在登记里、哪些没有。
    不推断「应该有几次」以外的结论——次数依赖参数网格与场景配置，
    由调用方给出期望值。
    """
    runs = list_backtest_runs(validation_id, db_path=db_path)
    seen = {}
    for run in runs:
        seen[run["run_role"]] = seen.get(run["run_role"], 0) + 1
    missing = [role for role in ALL_ROLES if role not in seen]
    return {
        "validation_id": validation_id,
        "registered": len(runs),
        "role_counts": seen,
        "roles_absent": missing,
        "complete": not missing and bool(runs),
    }


def audit_completeness(validation_id: str, *, db_path=None) -> dict:
    """核对内部回测是否「数量上也完整」，而不只是角色出现过。

    只比对**能从库内已有记录直接推出**的期望值：
    - 样本内网格档位数 = validation_runs.ma_window_grid 的长度
    - Walk-Forward 测试窗口数 = validation_windows 的窗口数
    - 压力场景数 = validation_stress 的场景数
    - 基准数 = 基准配置条数（有则比）

    推不出期望值的角色（如样本外固定 1 次）只核对是否出现。
    缺失即判 incomplete，不因为「有记录」就算完整。
    """
    init_validation_schema_compat(db_path)
    init_audit_schema(db_path)
    with get_connection(db_path) as conn:
        vr = conn.execute(
            "SELECT ma_window_grid, benchmark_config FROM validation_runs "
            "WHERE validation_id=?", (validation_id,)
        ).fetchone()
        if not vr:
            return {"validation_id": validation_id, "found": False,
                    "complete": False, "reason": "验证记录不存在"}
        try:
            grid = json.loads(vr["ma_window_grid"] or "[]")
        except json.JSONDecodeError:
            grid = []
        try:
            bench = json.loads(vr["benchmark_config"] or "[]")
        except (json.JSONDecodeError, TypeError):
            bench = []
        window_count = conn.execute(
            "SELECT COUNT(*) FROM validation_windows WHERE validation_id=?",
            (validation_id,),
        ).fetchone()[0]
        stress_count = conn.execute(
            "SELECT COUNT(*) FROM validation_stress WHERE validation_id=?",
            (validation_id,),
        ).fetchone()[0]
        run_count = conn.execute(
            "SELECT COUNT(*) FROM validation_backtest_runs WHERE validation_id=?",
            (validation_id,),
        ).fetchone()[0]

    runs = list_backtest_runs(validation_id, db_path=db_path)
    by_role: dict[str, list[dict]] = {}
    for run in runs:
        by_role.setdefault(run["run_role"], []).append(run)

    problems: list[str] = []
    expected: dict[str, int | None] = {
        ROLE_IN_SAMPLE: len(grid) if grid else None,
        ROLE_WF_TEST: window_count or None,
        ROLE_STRESS_COST: None,
        ROLE_BENCHMARK: len(bench) if bench else None,
        ROLE_OOS: 1,
        ROLE_REGIME: 1,
    }
    for role, want in expected.items():
        got = len(by_role.get(role, []))
        if want is None:
            if got == 0:
                problems.append(f"{role} 未登记")
            continue
        if got != want:
            problems.append(f"{role} 登记 {got} 条，期望 {want} 条")

    # 压力场景：按 validation_stress 的实际场景键逐个核对。
    with get_connection(db_path) as conn:
        stress_keys = [row[0] for row in conn.execute(
            "SELECT scenario_key FROM validation_stress WHERE validation_id=?",
            (validation_id,))]
    registered_keys = {run["scenario_key"] for run in runs
                       if run["run_role"].startswith("stress")}
    for key in stress_keys:
        if key not in registered_keys:
            problems.append(f"压力场景 {key} 未登记内部回测")

    failed = [run for run in runs if run["status"] != "success"]
    for run in failed:
        problems.append(
            f"{run['run_role']}({run['scenario_key']}) 状态 {run['status']}："
            f"{run['reason'] or '无原因'}"
        )

    # 样本内网格档位逐一核对，缺档比数量不符更具体
    if grid:
        seen = {run["scenario_key"] for run in by_role.get(ROLE_IN_SAMPLE, [])}
        for window in grid:
            if f"ma{window}" not in seen:
                problems.append(f"样本内 MA{window} 未登记")

    return {
        "validation_id": validation_id,
        "found": True,
        "run_count": run_count,
        "complete": not problems,
        "expected": {k: v for k, v in expected.items()},
        "actual": {k: len(v) for k, v in by_role.items()},
        "problems": problems,
    }
