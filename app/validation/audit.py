"""阶段3A.3.2.3.4 / 3A.3.2.3.4.1：validation 内部回测审计上下文、登记与追溯。

一次 validation 内部会跑很多次 BacktestEngine（样本内网格 / 样本外 /
Walk-Forward 训练与测试 / 基准 / 成本与滑点压力 / sparse / insufficient）。
这些运行各自有独立 run_id，且引擎会把公司行为应用与分红应收按 run_id
写进 `corporate_action_applications` / `dividend_receivables`。

本模块：

1. 用 contextvar 传递「当前 validation 上下文」，让嵌套的每一次回测自动登记。
2. 把每次回测写进 `backtest_runs`（存在性凭证，`run_scope='validation_internal'`）
   与 `validation_backtest_runs`（validation → 内部回测的关联）。
3. sparse 场景的逐笔明细从临时副本库复制到主库审计区并逐条对账。
4. 只读追溯：`audit_trace()` 从 validation_id 一路查到事件与版本。

铁律（3A.3.2.3.4.1 起）：

- 不存在的 run_id 不能登记，也不能被判定为完整。
- 关联表里有一条 success 记录，不等于回测真实存在。
- 没有逐笔明细，就不叫可追溯。
- 审计持久化失败不能被降级成一条 warning 后当作完整。
"""
from __future__ import annotations

import contextvars
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.backtest.api import ACCOUNTING_FORMAL
from app.database.db import get_connection
from app.validation.audit_schema import (
    SPARSE_DETAIL_SCHEMA,
    VALIDATION_BACKTEST_SCHEMA,
    VALIDATION_REGIME_SCHEMA,
)

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

# 内部回测在 backtest_runs 里的 scope 标记：与用户直接跑的回测区分开
RUN_SCOPE_INTERNAL = "validation_internal"
RUN_SCOPE_STANDALONE = "standalone"

# 明细位置
DETAIL_MAIN_DB = "main_db"
DETAIL_SPARSE_TABLE = "audit_sparse_tables"
DETAIL_EXTERNAL_MISSING = "external_copy_db"
# 生成于存在性凭证体系之前、副本已删且无法恢复的存量记录
DETAIL_UNAVAILABLE_EXTERNAL = "unavailable_external_detail"
# 生成于存在性凭证体系之前的整条记录
AUDIT_LEGACY_NO_EVIDENCE = "unavailable_legacy_evidence"

STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"


class AuditError(RuntimeError):
    """审计登记 / 持久化 / 追溯失败；不吞异常，不留半条数据。"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- schema

def init_audit_schema(db_path=None) -> None:
    with get_connection(db_path) as conn:
        conn.executescript(VALIDATION_BACKTEST_SCHEMA)
        conn.executescript(VALIDATION_REGIME_SCHEMA)
        conn.executescript(SPARSE_DETAIL_SCHEMA)


def init_validation_schema_compat(db_path=None) -> None:
    """建 validation 表并补齐迁移列（幂等，仅 ADD COLUMN）。"""
    from app.validation.storage import init_validation_schema

    init_validation_schema(db_path)
    with get_connection(db_path) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(validation_runs)")}
        if "accounting_version" not in cols:
            conn.execute("ALTER TABLE validation_runs ADD COLUMN accounting_version TEXT")
        if "legacy_flag" not in cols:
            conn.execute("ALTER TABLE validation_runs ADD COLUMN legacy_flag TEXT")


# ---------------------------------------------------------------- 上下文

@dataclass
class AuditContext:
    validation_id: str
    role: str = ROLE_OOS
    scenario_key: str | None = None


_CURRENT: "contextvars.ContextVar[AuditContext | None]" = contextvars.ContextVar(
    "validation_audit_context", default=None
)


def current_context() -> AuditContext | None:
    return _CURRENT.get()


def bind(validation_id: str) -> tuple[AuditContext, Any]:
    ctx = AuditContext(validation_id=validation_id)
    return ctx, _CURRENT.set(ctx)


def reset(token) -> None:
    _CURRENT.reset(token)


class audit_scope:  # noqa: N801 - 用作 with 语句
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


# ---------------------------------------------------------------- 存在性凭证

def register_run_evidence(result, *, db_path=None, codes=None) -> str:
    """把一次真实内部回测写进 `backtest_runs` 作为存在性凭证。

    只由真实回测路径（`_run_backtest`）调用：这里写入的 run_id 来自
    刚刚跑完的 `BacktestResult`，不是编造的。测试若要构造凭证，也必须
    走同一个入口，从而保证「凭证 ⇔ 真跑过」的语义不被绕过。

    不写 nav / orders / trades / positions：内部回测的逐日明细不在
    `backtest_runs` 的语义范围内（那是用户单次回测的产物），
    本函数只登记运行本身。
    """
    run_id = getattr(result, "run_id", None)
    if not isinstance(run_id, str) or not run_id.strip():
        raise AuditError("内部回测缺少有效 run_id，无法登记存在性凭证")

    basis = getattr(result, "accounting_basis", None)
    formal = getattr(result, "formal_valuation", None)
    if basis != ACCOUNTING_FORMAL:
        raise AuditError(f"内部回测会计口径非正式：accounting_basis={basis!r}")
    if not isinstance(formal, bool) or formal is not True:
        raise AuditError(f"内部回测 formal_valuation 非布尔真值：{formal!r}")

    cfg = getattr(result, "config", None)
    summary = {
        "accounting_basis": basis,
        "formal_valuation": True,
        "cost_semantics": "validation_internal_run",
        "notes": ["validation 内部回测存在性凭证；逐日明细不在此表"],
    }
    if cfg is not None and hasattr(cfg, "as_dict"):
        config_json = cfg.as_dict()
    elif cfg is not None:
        config_json = {
            "start_date": str(getattr(cfg, "start_date", "")),
            "end_date": str(getattr(cfg, "end_date", "")),
            "strategy_params": getattr(cfg, "strategy_params", {}) or {},
        }
    else:
        config_json = {}
    payload = (
        run_id,
        getattr(result, "strategy_name", "unknown"),
        getattr(result, "strategy_version", "unknown"),
        json.dumps(config_json, ensure_ascii=False, sort_keys=True, default=str),
        float(getattr(result, "initial_cash", 0.0) or 0.0),
        str(getattr(cfg, "start_date", "")) if cfg is not None else "",
        str(getattr(cfg, "end_date", "")) if cfg is not None else "",
        json.dumps(list(codes or getattr(result, "codes", []) or []), ensure_ascii=False),
        getattr(result, "indicator_version", None),
        json.dumps({}, ensure_ascii=False),
        getattr(result, "input_hash", "") or "",
        json.dumps(summary, ensure_ascii=False, sort_keys=True),
        _now(),
        RUN_SCOPE_INTERNAL,
    )
    with get_connection(db_path) as conn:
        _ensure_run_scope_column(conn)
        conn.execute(
            "INSERT INTO backtest_runs "
            "(run_id, strategy_name, strategy_version, config_json, initial_cash, "
            " start_date, end_date, etf_codes, indicator_version, snapshot_ids, "
            " input_hash, summary_json, created_at, run_scope) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(run_id) DO NOTHING",
            payload,
        )
        row = conn.execute(
            "SELECT run_id, run_scope FROM backtest_runs WHERE run_id=?", (run_id,)
        ).fetchone()
    if row is None:
        raise AuditError(f"存在性凭证写入后仍查不到 run_id={run_id}")
    if row["run_scope"] != RUN_SCOPE_INTERNAL:
        raise AuditError(
            f"run_id={run_id} 已作为用户回测存在，不能再作为内部回测登记"
        )
    return run_id


def _ensure_run_scope_column(conn) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(backtest_runs)")}
    if not cols:
        raise AuditError("backtest_runs 表不存在，无法登记内部回测")
    if "run_scope" not in cols:
        conn.execute(
            "ALTER TABLE backtest_runs ADD COLUMN run_scope TEXT NOT NULL "
            "DEFAULT 'standalone'"
        )


def run_exists(run_id: str, *, db_path=None) -> bool:
    if not isinstance(run_id, str) or not run_id.strip():
        return False
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM backtest_runs WHERE run_id=?", (run_id,)
        ).fetchone()
    return row is not None


# ---------------------------------------------------------------- 登记

def _int_or_none(value):
    return int(value) if value is not None else None


def register_backtest(
    result,
    *,
    role: str,
    scenario_key: str | None = None,
    validation_id: str | None = None,
    status: str = STATUS_SUCCESS,
    reason: str | None = None,
    db_path=None,
    detail_db_path=None,
    detail_location: str | None = None,
) -> int:
    """登记一次内部回测到 validation 审计链路。

    写入前逐项校验，任一不满足即抛 `AuditError`，不留半条数据。
    """
    ctx = current_context()
    vid = validation_id or (ctx.validation_id if ctx else None)
    if not vid:
        raise AuditError("缺少 validation_id，拒绝登记内部回测")
    if scenario_key is None and ctx is not None:
        scenario_key = ctx.scenario_key
    if status not in (STATUS_SUCCESS, STATUS_FAILED):
        raise AuditError(f"未知的登记状态：{status!r}")
    if status == STATUS_FAILED and not reason:
        raise AuditError("失败登记必须给出原因")

    basis = getattr(result, "accounting_basis", None)
    formal = getattr(result, "formal_valuation", None)
    if basis != ACCOUNTING_FORMAL:
        raise AuditError(f"内部回测会计口径非正式：accounting_basis={basis!r}")
    if not isinstance(formal, bool) or formal is not True:
        raise AuditError(f"内部回测 formal_valuation 非布尔真值：{formal!r}")

    run_id = getattr(result, "run_id", None)
    if not isinstance(run_id, str) or not run_id.strip():
        raise AuditError("内部回测缺少有效 run_id，无法关联公司行为明细")

    cfg = getattr(result, "config", None)
    params: dict[str, Any] = {}
    if cfg is not None and isinstance(getattr(cfg, "strategy_params", None), dict):
        params = dict(cfg.strategy_params)

    init_validation_schema_compat(db_path)
    init_audit_schema(db_path)
    with get_connection(db_path) as conn:
        vr = conn.execute(
            "SELECT validation_id, status FROM validation_runs WHERE validation_id=?",
            (vid,),
        ).fetchone()
        if vr is None:
            raise AuditError(f"validation_id={vid} 不存在，拒绝登记内部回测")

        evidence = conn.execute(
            "SELECT run_scope FROM backtest_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if evidence is None:
            raise AuditError(
                f"backtest_run_id={run_id} 在 backtest_runs 中不存在，"
                f"拒绝登记（关联表不得凭空指向未发生的回测）"
            )
        if evidence["run_scope"] != RUN_SCOPE_INTERNAL:
            raise AuditError(
                f"backtest_run_id={run_id} 是用户回测记录，不能作为 validation 内部回测"
            )

        dup = conn.execute(
            "SELECT id FROM validation_backtest_runs "
            "WHERE validation_id=? AND backtest_run_id=?", (vid, run_id)
        ).fetchone()
        if dup is not None:
            raise AuditError(
                f"同一 validation({vid}) 下已登记过 run_id={run_id}，拒绝重复登记"
            )

        if detail_db_path is not None and detail_db_path != db_path:
            with get_connection(detail_db_path) as detail_conn:
                summary_src = _summary_for_run(detail_conn, run_id)
            location = detail_location or DETAIL_EXTERNAL_MISSING
        else:
            summary_src = _summary_for_run(conn, run_id)
            location = detail_location or DETAIL_MAIN_DB

        applied = summary_src["applied"]
        if not applied:
            applied = len(getattr(result, "corporate_action_log", []) or [])

        conn.execute(
            "INSERT INTO validation_backtest_runs "
            "(validation_id, backtest_run_id, run_role, scenario_key, "
            " strategy_name, strategy_version, strategy_params_json, "
            " start_date, end_date, indicator_version, initial_cash, codes_json, "
            " accounting_basis, formal_valuation, input_hash, "
            " corporate_action_digest, applied_action_count, receivable_count, "
            " receivable_amount, settled_count, settled_amount, "
            " detail_location, detail_note, status, reason, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                int(applied or 0), int(summary_src["receivable_count"]),
                float(summary_src["receivable_amount"]),
                int(summary_src["settled_count"]),
                float(summary_src["settled_amount"]),
                location, reason, status, reason, _now(),
            ),
        )
        row = conn.execute(
            "SELECT id FROM validation_backtest_runs "
            "WHERE validation_id=? AND backtest_run_id=?", (vid, run_id)
        ).fetchone()
    return int(row["id"]) if row else 0


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


# ---------------------------------------------------------------- sparse 明细持久化

_APPLICATION_FIELDS = (
    "action_id", "code", "effective_date", "action_type", "shares_before",
    "shares_after", "cash_delta", "fractional_cash", "applied_at",
    "receivable_amount", "cash_paid_amount", "fractional_shares",
    "disposed_cost_basis", "realized_pnl", "official_ratio",
)
_RECEIVABLE_FIELDS = (
    "action_id", "code", "record_date", "ex_date", "pay_date", "shares_at_ex",
    "cash_per_share", "amount", "status", "settled_at",
)

# 数值字段比较规则：REAL 一律按绝对误差 <= 1e-6 比较，与库内 round(...,6)
# 的写入精度一致；整数与文本字段严格相等。不用更大容差掩盖真实差异。
NUMERIC_FIELDS = frozenset({
    "cash_delta", "fractional_cash", "receivable_amount", "cash_paid_amount",
    "fractional_shares", "disposed_cost_basis", "realized_pnl", "official_ratio",
    "cash_per_share", "amount",
})
NUMERIC_TOLERANCE = 1e-6


def _normalize(field: str, value):
    """把复制前后的值归一化到同一形态，避免类型差异被当成数据差异。"""
    if field in NUMERIC_FIELDS:
        if value is None:
            return None
        try:
            return round(float(value), 6)
        except (TypeError, ValueError):
            return value
    if value is None:
        return None
    return str(value)


def _values_equal(field: str, left, right) -> bool:
    a = _normalize(field, left)
    b = _normalize(field, right)
    if a is None or b is None:
        return a is None and b is None
    if field in NUMERIC_FIELDS:
        try:
            return abs(float(a) - float(b)) <= NUMERIC_TOLERANCE
        except (TypeError, ValueError):
            return a == b
    return a == b


def _reconcile_rows(kind: str, fields, src_rows, dst_rows) -> list[str]:
    """逐条逐字段对账。返回问题列表（空表示一致）。"""
    problems: list[str] = []
    src_by_key = {int(row["action_id"]): row for row in src_rows}
    dst_by_key = {int(row["action_id"]): row for row in dst_rows}

    only_src = sorted(set(src_by_key) - set(dst_by_key))
    only_dst = sorted(set(dst_by_key) - set(src_by_key))
    if only_src:
        problems.append(f"{kind} 主库缺少 action_id={only_src}")
    if only_dst:
        problems.append(f"{kind} 主库多出 action_id={only_dst}")

    for key in sorted(set(src_by_key) & set(dst_by_key)):
        for field in fields:
            if field == "action_id":
                continue
            left = src_by_key[key][field] if field in src_by_key[key].keys() else None
            right = dst_by_key[key][field] if field in dst_by_key[key].keys() else None
            if not _values_equal(field, left, right):
                problems.append(
                    f"{kind} action_id={key} 字段 {field} 不一致："
                    f"副本={_normalize(field, left)!r} 主库={_normalize(field, right)!r}"
                )
    return problems


def persist_sparse_details(validation_id: str, run_id: str, source_db, *,
                           db_path=None) -> dict:
    """把 sparse 副本库的逐笔明细复制到主库审计区，并逐条逐字段对账。

    原子性：插入与对账**在同一个连接事务内**完成。任一步失败（SQL 异常、
    条数不符、任一字段不一致）都在 `with get_connection()` 内 raise，
    由连接管理器整体 rollback，主库不留半条。

    幂等：`ON CONFLICT DO NOTHING`，已存在的历史行不被覆盖、不被删除；
    若已有行与副本不一致，对账会报出具体字段差异并整体回滚本次插入。
    """
    src = Path(source_db)
    if not src.exists():
        raise AuditError(f"sparse 副本库不存在：{src}")

    init_audit_schema(db_path)

    with get_connection(src) as src_conn:
        apps = src_conn.execute(
            "SELECT * FROM corporate_action_applications WHERE run_id=? "
            "ORDER BY action_id", (run_id,)
        ).fetchall()
        recvs = src_conn.execute(
            "SELECT * FROM dividend_receivables WHERE run_id=? ORDER BY action_id",
            (run_id,),
        ).fetchall()
        action_ids = sorted({int(r["action_id"]) for r in apps}
                            | {int(r["action_id"]) for r in recvs})
        versions: dict[int, tuple] = {}
        if action_ids:
            marks = ",".join("?" for _ in action_ids)
            for row in src_conn.execute(
                "SELECT action_id, version_no, event_fingerprint "
                f"FROM corporate_actions WHERE action_id IN ({marks})",
                action_ids,
            ):
                versions[int(row["action_id"])] = (
                    row["version_no"], row["event_fingerprint"])

    src_recv_amount = round(sum(float(r["amount"] or 0.0) for r in recvs), 6)
    src_settled = [r for r in recvs if r["settled_at"]]
    src_settled_amount = round(
        sum(float(r["amount"] or 0.0) for r in src_settled), 6)

    # ---------------- 单个事务：插入 + 逐字段对账 ----------------
    with get_connection(db_path) as conn:
        for row in apps:
            version = versions.get(int(row["action_id"]), (None, None))
            conn.execute(
                "INSERT INTO audit_sparse_applications "
                "(validation_id, run_id, action_id, code, effective_date, "
                " action_type, shares_before, shares_after, cash_delta, "
                " fractional_cash, applied_at, receivable_amount, "
                " cash_paid_amount, fractional_shares, disposed_cost_basis, "
                " realized_pnl, official_ratio, version_no, event_fingerprint, "
                " source_db, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(validation_id, run_id, action_id) DO NOTHING",
                (validation_id, run_id,
                 *(row[name] for name in _APPLICATION_FIELDS),
                 version[0], version[1], str(src), _now()),
            )
        for row in recvs:
            version = versions.get(int(row["action_id"]), (None, None))
            conn.execute(
                "INSERT INTO audit_sparse_receivables "
                "(validation_id, run_id, action_id, code, record_date, ex_date, "
                " pay_date, shares_at_ex, cash_per_share, amount, status, "
                " settled_at, version_no, event_fingerprint, source_db, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(validation_id, run_id, action_id) DO NOTHING",
                (validation_id, run_id,
                 *(row[name] for name in _RECEIVABLE_FIELDS),
                 version[0], version[1], str(src), _now()),
            )

        dst_apps = conn.execute(
            "SELECT * FROM audit_sparse_applications "
            "WHERE validation_id=? AND run_id=?", (validation_id, run_id)
        ).fetchall()
        dst_recvs = conn.execute(
            "SELECT * FROM audit_sparse_receivables "
            "WHERE validation_id=? AND run_id=?", (validation_id, run_id)
        ).fetchall()

        problems: list[str] = []
        if len(apps) != len(dst_apps):
            problems.append(
                f"application_count 副本={len(apps)} 主库={len(dst_apps)}")
        if len(recvs) != len(dst_recvs):
            problems.append(
                f"receivable_count 副本={len(recvs)} 主库={len(dst_recvs)}")

        problems.extend(_reconcile_rows(
            "应用", _APPLICATION_FIELDS, apps, dst_apps))
        problems.extend(_reconcile_rows(
            "应收", _RECEIVABLE_FIELDS, recvs, dst_recvs))

        dst_recv_amount = round(
            sum(float(r["amount"] or 0.0) for r in dst_recvs), 6)
        dst_settled = [r for r in dst_recvs if r["settled_at"]]
        dst_settled_amount = round(
            sum(float(r["amount"] or 0.0) for r in dst_settled), 6)
        if abs(src_recv_amount - dst_recv_amount) > NUMERIC_TOLERANCE:
            problems.append(
                f"receivable_amount 副本={src_recv_amount} 主库={dst_recv_amount}")
        if len(src_settled) != len(dst_settled):
            problems.append(
                f"settled_count 副本={len(src_settled)} 主库={len(dst_settled)}")
        if abs(src_settled_amount - dst_settled_amount) > NUMERIC_TOLERANCE:
            problems.append(
                f"settled_amount 副本={src_settled_amount} 主库={dst_settled_amount}")

        for row in list(apps) + list(recvs):
            key = int(row["action_id"])
            if key not in versions:
                problems.append(f"action_id={key} 在副本事件表中查不到，版本不可追溯")

        if problems:
            # 在 with 块内 raise → 连接管理器 rollback，本次插入全部回退
            raise AuditError("sparse 明细复制对账失败：" + "；".join(problems))

    return {
        "ok": True,
        "run_id": run_id,
        "application_count": len(apps),
        "receivable_count": len(recvs),
        "receivable_amount": src_recv_amount,
        "settled_count": len(src_settled),
        "settled_amount": src_settled_amount,
        "action_ids": sorted({int(r["action_id"]) for r in apps}
                             | {int(r["action_id"]) for r in recvs}),
        "source_db": str(src),
        "reconciled_fields": {
            "application": list(_APPLICATION_FIELDS),
            "receivable": list(_RECEIVABLE_FIELDS),
            "numeric_tolerance": NUMERIC_TOLERANCE,
        },
    }



def mark_sparse_detail_location(validation_id: str, run_id: str, *,
                                location: str, note: str | None,
                                applied: int | None = None,
                                receivable_count: int | None = None,
                                receivable_amount: float | None = None,
                                settled_count: int | None = None,
                                settled_amount: float | None = None,
                                db_path=None) -> None:
    """更新 sparse 关联行的明细位置与计数（对账通过后调用）。"""
    init_audit_schema(db_path)
    with get_connection(db_path) as conn:
        fields = ["detail_location=?"]
        params: list[Any] = [location]
        if note is not None:
            fields.append("detail_note=?")
            params.append(note)
        for name, value in (
            ("applied_action_count", applied),
            ("receivable_count", receivable_count),
            ("receivable_amount", receivable_amount),
            ("settled_count", settled_count),
            ("settled_amount", settled_amount),
        ):
            if value is not None:
                fields.append(f"{name}=?")
                params.append(value)
        params.extend([validation_id, run_id])
        conn.execute(
            f"UPDATE validation_backtest_runs SET {', '.join(fields)} "
            "WHERE validation_id=? AND backtest_run_id=?", params
        )


def mark_backtest_failed(validation_id: str, run_id: str, reason: str, *,
                         db_path=None) -> None:
    """把已登记的关联行降级为 failed 并写明原因。

    用于「回测本身跑完了、但审计持久化/对账失败」的场景：
    关联行必须保留（它确实发生过），但状态不能是 success。
    """
    init_audit_schema(db_path)
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE validation_backtest_runs SET status=?, reason=? "
            "WHERE validation_id=? AND backtest_run_id=?",
            (STATUS_FAILED, reason[:500], validation_id, run_id),
        )



def remove_sparse_copy(source_db) -> None:
    """删除临时副本目录。只允许在明细复制与对账全部成功后调用。"""
    src = Path(source_db).resolve()
    target = src.parent
    if "val_sparse_" not in target.name:
        raise AuditError(f"拒绝删除非 sparse 临时目录：{target}")
    shutil.rmtree(target, ignore_errors=True)


# ---------------------------------------------------------------- regime

def save_regime_stats(validation_id: str, regime_payload: dict, *,
                      db_path=None) -> int:
    """把已经算好的 regime 分组统计落库；不重算、不改分类算法。

    重复执行幂等：`INSERT OR REPLACE` 按 (validation_id, regime_label) 唯一键。
    """
    if not isinstance(regime_payload, dict):
        raise AuditError("regime payload 不是字典，拒绝落库")
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


# ---------------------------------------------------------------- 查询

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


def _sparse_detail_counts(conn, validation_id: str, run_id: str) -> dict:
    apps = conn.execute(
        "SELECT COUNT(*) FROM audit_sparse_applications "
        "WHERE validation_id=? AND run_id=?", (validation_id, run_id)
    ).fetchone()[0]
    row = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(amount), 0.0) FROM audit_sparse_receivables "
        "WHERE validation_id=? AND run_id=?", (validation_id, run_id)
    ).fetchone()
    settled = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(amount), 0.0) FROM audit_sparse_receivables "
        "WHERE validation_id=? AND run_id=? AND settled_at IS NOT NULL",
        (validation_id, run_id),
    ).fetchone()
    return {
        "applied": int(apps),
        "receivable_count": int(row[0]),
        "receivable_amount": float(row[1] or 0.0),
        "settled_count": int(settled[0]),
        "settled_amount": float(settled[1] or 0.0),
    }


# ---------------------------------------------------------------- 完整性

def audit_completeness(validation_id: str, *, db_path=None) -> dict:
    """核对审计完整性：存在性、口径、状态、角色、数量、逐笔明细。

    注意：**本函数不调用 `audit_trace()`**，避免与 `audit_trace()` 形成递归。
    明细层面的判断直接查表完成。
    """
    init_validation_schema_compat(db_path)
    init_audit_schema(db_path)
    problems: list[str] = []

    with get_connection(db_path) as conn:
        vr = conn.execute(
            "SELECT validation_id, status, ma_window_grid, benchmark_config, "
            "summary_json FROM validation_runs WHERE validation_id=?",
            (validation_id,),
        ).fetchone()
        if vr is None:
            return {
                "validation_id": validation_id, "found": False,
                "complete": False, "audit_status": "validation_not_found",
                "problems": ["验证记录不存在"], "run_count": 0,
                "expected": {}, "actual": {},
            }

        if vr["status"] != STATUS_SUCCESS:
            problems.append(f"validation 自身状态为 {vr['status']}，不得判定完整")

        try:
            summary = json.loads(vr["summary_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            summary = {}
        if isinstance(summary, dict) and summary.get("audit_warning"):
            problems.append(f"审计持久化告警：{summary['audit_warning']}")

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
        stress_keys = [row[0] for row in conn.execute(
            "SELECT scenario_key FROM validation_stress WHERE validation_id=?",
            (validation_id,),
        )]
        regime_rows = conn.execute(
            "SELECT COUNT(*) FROM validation_regime_stats WHERE validation_id=?",
            (validation_id,),
        ).fetchone()[0]

        runs = conn.execute(
            "SELECT * FROM validation_backtest_runs WHERE validation_id=? "
            "ORDER BY id", (validation_id,),
        ).fetchall()

        if not runs:
            return {
                "validation_id": validation_id, "found": True,
                "complete": False, "audit_status": "unavailable_legacy",
                "problems": ["该 validation 无内部回测登记"], "run_count": 0,
                "expected": {}, "actual": {},
            }

        evidence = {
            row["run_id"]: row["run_scope"]
            for row in conn.execute(
                "SELECT run_id, run_scope FROM backtest_runs"
            )
        }

        # 存量记录（3A.3.2.3.4.1 之前生成）没有存在性凭证。
        # 这不是「某一条丢了」，而是整条记录生成时就没有凭证体系，
        # 因此单独给出明确状态，而不是逐条刷 52 条 problem。
        missing_evidence = [r for r in runs
                            if r["backtest_run_id"] not in evidence]
        legacy_no_evidence = len(missing_evidence) == len(runs)

        for run in runs:
            run_id = run["backtest_run_id"]
            label = f"{run['run_role']}({run['scenario_key']})"
            if legacy_no_evidence:
                continue
            # 1) run_id 必须真实存在
            if run_id not in evidence:
                problems.append(f"{label} 的 run_id={run_id} 在 backtest_runs 中不存在")
            elif evidence[run_id] != RUN_SCOPE_INTERNAL:
                problems.append(f"{label} 的 run_id={run_id} 不是内部回测记录")
            # 2) 口径与状态
            if run["accounting_basis"] != ACCOUNTING_FORMAL:
                problems.append(
                    f"{label} 会计口径非正式：{run['accounting_basis']!r}")
            if int(run["formal_valuation"] or 0) != 1:
                problems.append(f"{label} formal_valuation 不为 1")
            if run["status"] != STATUS_SUCCESS:
                problems.append(
                    f"{label} 状态 {run['status']}：{run['reason'] or '无原因'}")
            # 3) 逐笔明细
            applied = int(run["applied_action_count"] or 0)
            location = run["detail_location"] or DETAIL_MAIN_DB
            if applied > 0:
                if location == DETAIL_SPARSE_TABLE:
                    counts = _sparse_detail_counts(conn, validation_id, run_id)
                else:
                    counts = _summary_for_run(conn, run_id)
                if counts["applied"] == 0 and counts["receivable_count"] == 0:
                    problems.append(
                        f"{label} 登记应用 {applied} 条，但主库查不到任何逐笔明细"
                        f"（明细位置={location}）")
                elif counts["applied"] != applied:
                    problems.append(
                        f"{label} 应用条数不一致：登记 {applied}，明细 "
                        f"{counts['applied']}")
                expected_amount = float(run["receivable_amount"] or 0.0)
                if abs(counts["receivable_amount"] - expected_amount) > 0.005:
                    problems.append(
                        f"{label} 应收金额不一致：登记 {expected_amount}，明细 "
                        f"{counts['receivable_amount']}")

    by_role: dict[str, list[Any]] = {}
    for run in runs:
        by_role.setdefault(run["run_role"], []).append(run)

    expected: dict[str, int | None] = {
        ROLE_IN_SAMPLE: len(grid) if grid else None,
        ROLE_WF_TEST: window_count or None,
        ROLE_WF_TRAIN: None,   # 逐窗口 × wf_grid 核对，不能只看总数
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

    # ---------------- Walk-Forward：训练与测试逐窗口核对 ----------------
    with get_connection(db_path) as conn:
        window_rows = conn.execute(
            "SELECT window_index, status, selected_param, train_days, test_days "
            "FROM validation_windows WHERE validation_id=? ORDER BY window_index",
            (validation_id,),
        ).fetchall()
        wf_raw = conn.execute(
            "SELECT walkforward_config FROM validation_runs WHERE validation_id=?",
            (validation_id,),
        ).fetchone()

    wf_grid: list = []
    if wf_raw is not None and wf_raw["walkforward_config"]:
        try:
            parsed = json.loads(wf_raw["walkforward_config"])
        except (json.JSONDecodeError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            wf_grid = list(parsed.get("wf_grid") or [])
        elif isinstance(parsed, list):
            wf_grid = list(parsed)

    wf_train_runs = by_role.get(ROLE_WF_TRAIN, [])
    wf_test_runs = by_role.get(ROLE_WF_TEST, [])
    train_by_scen = {run["scenario_key"]: run for run in wf_train_runs}
    test_by_scen = {run["scenario_key"]: run for run in wf_test_runs}

    executed_windows = [r for r in window_rows
                        if r["status"] != "insufficient_data"]
    skipped_windows = [r for r in window_rows
                       if r["status"] == "insufficient_data"]

    if not window_rows:
        problems.append("Walk-Forward 窗口记录缺失（validation_windows 为空）")

    for row in executed_windows:
        idx = int(row["window_index"])
        if wf_grid:
            missing_train = [c for c in wf_grid
                             if f"w{idx}-ma{c}" not in train_by_scen]
            if missing_train:
                problems.append(
                    f"Walk-Forward 训练窗口 w{idx} 缺少候选 "
                    f"{missing_train} 的执行记录")
        elif not any(k and k.startswith(f"w{idx}-") for k in train_by_scen):
            problems.append(f"Walk-Forward 训练窗口 w{idx} 没有任何执行记录")

        test_scen = f"w{idx}-ma{row['selected_param']}"
        if test_scen not in test_by_scen:
            problems.append(
                f"Walk-Forward 测试窗口 w{idx}"
                f"（选中 MA{row['selected_param']}）缺少执行记录")

        for scen, run in train_by_scen.items():
            if (scen and scen.startswith(f"w{idx}-")
                    and run["status"] != STATUS_SUCCESS):
                problems.append(
                    f"Walk-Forward 训练窗口 {scen} 状态 {run['status']}："
                    f"{run['reason'] or '无原因'}")
        test_run = test_by_scen.get(test_scen)
        if test_run is not None and test_run["status"] != STATUS_SUCCESS:
            problems.append(
                f"Walk-Forward 测试窗口 {test_scen} 状态 {test_run['status']}："
                f"{test_run['reason'] or '无原因'}")

        if row["status"] != STATUS_SUCCESS:
            problems.append(
                f"Walk-Forward 窗口 w{idx} 状态 {row['status']}："
                "该窗口未能完成训练+测试")

    for row in skipped_windows:
        problems.append(
            f"Walk-Forward 窗口 w{row['window_index']} 数据不足"
            f"（train {row['train_days']} 天 / test {row['test_days']} 天），"
            "该窗口未执行，审计不完整")

    if executed_windows and wf_grid:
        want_train = len(executed_windows) * len(wf_grid)
        if len(wf_train_runs) != want_train:
            problems.append(
                f"walkforward_train 登记 {len(wf_train_runs)} 条，"
                f"期望 {want_train} 条（{len(executed_windows)} 窗口 × "
                f"{len(wf_grid)} 候选）")

    # ---------------- 压力测试：场景必须关联到真实且成功的回测 ----------------
    with get_connection(db_path) as conn:
        stress_rows = conn.execute(
            "SELECT scenario_key, status, reason FROM validation_stress "
            "WHERE validation_id=?", (validation_id,),
        ).fetchall()
    stress_by_key = {run["scenario_key"]: run for run in runs
                     if run["run_role"].startswith("stress")}
    for row in stress_rows:
        key = row["scenario_key"]
        run = stress_by_key.get(key)
        if run is None:
            problems.append(f"压力场景 {key} 未登记内部回测")
            continue
        stress_status = row["status"]
        exec_status = run["status"]
        if stress_status in ("success", "insufficient"):
            # insufficient = 执行成功但样本不足，不是执行失败；
            # 但它也不能被当作正式成功绩效，两者必须能区分。
            if exec_status != STATUS_SUCCESS:
                problems.append(
                    f"压力场景 {key} 登记为 {stress_status}，"
                    f"但回测执行状态为 {exec_status}："
                    f"{run['reason'] or '无原因'}")
            if stress_status == "insufficient" and key != "insufficient":
                problems.append(
                    f"压力场景 {key} 标记 insufficient，"
                    "但只有样本量类场景允许该状态")
        else:
            problems.append(
                f"压力场景 {key} 状态 {stress_status}："
                f"{row['reason'] or '无原因'}")

    if grid:
        seen = {run["scenario_key"] for run in by_role.get(ROLE_IN_SAMPLE, [])}
        for window in grid:
            if f"ma{window}" not in seen:
                problems.append(f"样本内 MA{window} 未登记")

    if regime_rows == 0:
        problems.append("regime 分组统计未落库")

    if legacy_no_evidence:
        return {
            "validation_id": validation_id,
            "found": True,
            "run_count": len(runs),
            "complete": False,
            "audit_status": AUDIT_LEGACY_NO_EVIDENCE,
            "expected": expected,
            "actual": {k: len(v) for k, v in by_role.items()},
            "problems": [
                f"全部 {len(runs)} 条内部回测均无 backtest_runs 存在性凭证："
                "该记录生成于 3A.3.2.3.4.1 之前，当时未落凭证",
                *problems,
            ],
        }

    return {
        "validation_id": validation_id,
        "found": True,
        "run_count": len(runs),
        "complete": not problems,
        "audit_status": "complete" if not problems else "incomplete",
        "expected": expected,
        "actual": {k: len(v) for k, v in by_role.items()},
        "problems": problems,
    }


def audit_coverage(validation_id: str, db_path=None) -> dict:
    """只核对角色是否出现（保留旧接口，判定以 `audit_completeness` 为准）。"""
    runs = list_backtest_runs(validation_id, db_path=db_path)
    seen: dict[str, int] = {}
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


# ---------------------------------------------------------------- 追溯

def _version_of(conn, event) -> dict | None:
    """按 (code|action_type|ex_date) + version_no **精确**取事件版本快照。

    阶段3A.3.2.3.4.1.1：移除了「精确未命中就回退最新版本」的分支。
    回退会让一个历史版本已被删除的事件看起来仍有版本，从而掩盖缺失。
    精确匹配不到就返回 None，由调用方标记 `version_unavailable`。
    """
    version_no = event.get("version_no")
    if version_no is None:
        return None
    key = f"{event['code']}|{event['action_type']}|{event['ex_date']}"
    row = conn.execute(
        "SELECT version_id, action_key, version_no, share_ratio, cash_per_share, "
        "record_date, pay_date, evidence_status, data_version, change_reason, "
        "fractional_policy, compensation_price, created_at "
        "FROM corporate_action_versions WHERE action_key=? AND version_no=?",
        (key, version_no),
    ).fetchone()
    return dict(row) if row is not None else None



def audit_trace(validation_id: str, *, db_path=None) -> dict:
    """从 validation_id 一路追到内部回测、逐笔明细、事件与版本。

    状态判定**以 `audit_completeness()` 为准**，本函数不再只看
    关联表里的 status。两者结论始终一致。
    """
    init_validation_schema_compat(db_path)
    init_audit_schema(db_path)

    completeness = audit_completeness(validation_id, db_path=db_path)
    if not completeness.get("found"):
        return {"validation_id": validation_id, "found": False,
                "audit_status": "validation_not_found", "links": [],
                "problems": completeness.get("problems", [])}

    with get_connection(db_path) as conn:
        vr = conn.execute(
            "SELECT validation_id, status, accounting_version, input_hash, "
            "created_at, finished_at FROM validation_runs WHERE validation_id=?",
            (validation_id,),
        ).fetchone()
        runs = conn.execute(
            "SELECT * FROM validation_backtest_runs WHERE validation_id=? ORDER BY id",
            (validation_id,),
        ).fetchall()

        links: list[dict] = []
        for run in runs:
            run_id = run["backtest_run_id"]
            location = run["detail_location"] or DETAIL_MAIN_DB
            if location == DETAIL_SPARSE_TABLE:
                sp_apps = conn.execute(
                    "SELECT * FROM audit_sparse_applications "
                    "WHERE validation_id=? AND run_id=? ORDER BY action_id",
                    (validation_id, run_id),
                ).fetchall()
                sp_recvs = conn.execute(
                    "SELECT * FROM audit_sparse_receivables "
                    "WHERE validation_id=? AND run_id=? ORDER BY action_id",
                    (validation_id, run_id),
                ).fetchall()
                apps, receivables = sp_apps, sp_recvs
            else:
                apps = conn.execute(
                    "SELECT * FROM corporate_action_applications WHERE run_id=?",
                    (run_id,),
                ).fetchall()
                receivables = conn.execute(
                    "SELECT * FROM dividend_receivables WHERE run_id=?",
                    (run_id,),
                ).fetchall()

            action_ids = sorted({int(a["action_id"]) for a in apps}
                                | {int(r["action_id"]) for r in receivables})
            events: list[dict] = []
            versions_missing: list[int] = []
            if action_ids:
                marks = ",".join("?" for _ in action_ids)
                for ev in conn.execute(
                    "SELECT action_id, code, action_type, ex_date, effective_date, "
                    "record_date, pay_date, share_ratio, cash_per_share, "
                    "evidence_status, status, version_no, event_fingerprint "
                    f"FROM corporate_actions WHERE action_id IN ({marks}) "
                    "ORDER BY action_id", action_ids):
                    item = dict(ev)
                    version = _version_of(conn, item)
                    if version is None:
                        item["version_status"] = "version_unavailable"
                        versions_missing.append(int(item["action_id"]))
                    else:
                        item["version_status"] = "available"
                        item["version"] = version
                    events.append(item)

            settled = [r for r in receivables if r["settled_at"]]
            links.append({
                "backtest_run_id": run_id,
                "run_exists": run_id in {r["run_id"] for r in conn.execute(
                    "SELECT run_id FROM backtest_runs")},
                "run_role": run["run_role"],
                "scenario_key": run["scenario_key"],
                "status": run["status"],
                "accounting_basis": run["accounting_basis"],
                "formal_valuation": bool(run["formal_valuation"]),
                "input_hash": run["input_hash"],
                "corporate_action_digest": run["corporate_action_digest"],
                "application_count": len(apps),
                "receivable_count": len(receivables),
                "receivable_amount": round(
                    sum(float(r["amount"] or 0.0) for r in receivables), 6),
                "settled_count": len(settled),
                "settled_amount": round(
                    sum(float(r["amount"] or 0.0) for r in settled), 6),
                "unsettled_count": len(receivables) - len(settled),
                "unsettled_amount": round(
                    sum(float(r["amount"] or 0.0) for r in receivables)
                    - sum(float(r["amount"] or 0.0) for r in settled), 6),
                "detail_location": location,
                "detail_note": run["detail_note"],
                "versions_unavailable": versions_missing,
                "events": events,
            })

    problems = list(completeness.get("problems") or [])
    for link in links:
        if link["versions_unavailable"]:
            problems.append(
                f"{link['run_role']}({link['scenario_key']}) 事件版本缺失："
                f"action_id={link['versions_unavailable']}")

    status = "complete" if not problems else "incomplete"
    if completeness.get("audit_status") == "unavailable_legacy":
        status = "unavailable_legacy"
    elif completeness.get("audit_status") == AUDIT_LEGACY_NO_EVIDENCE:
        status = AUDIT_LEGACY_NO_EVIDENCE

    roles: dict[str, int] = {}
    for link in links:
        roles[link["run_role"]] = roles.get(link["run_role"], 0) + 1

    return {
        "validation_id": validation_id,
        "found": True,
        "audit_status": status,
        "validation_status": vr["status"] if vr else None,
        "accounting_version": vr["accounting_version"] if vr else None,
        "input_hash": vr["input_hash"] if vr else None,
        "backtest_run_count": len(links),
        "role_counts": roles,
        "links": links,
        "regime": list_regime_stats(validation_id, db_path=db_path),
        "problems": problems,
        "completeness": completeness,
    }
