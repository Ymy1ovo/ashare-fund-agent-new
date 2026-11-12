"""公司行为事件模型与账本应用（阶段3A.3.2）。

设计要点（对应 3A.3.2 会计设计）：

1. **唯一事实来源是事件表**，不是价格跳变推断。价格跳变只用于「发现异常」，
   不能自动生成事件。未确认事件（`status != 'confirmed'`）不得被应用。
2. **拆分/合并调整持仓数量**，现金分红调整现金余额。
3. **成交与估值继续用原始价格**，不用前复权价。
4. **同一事件对同一 run 只应用一次**，由 `corporate_action_applications`
   唯一约束保证，重复应用会抛错。
5. 份额调整产生的零碎份额按「现金补偿」处理（`fractional_cash`），
   金额按当日原始收盘价折算，并在 application 记录中留痕。

事件类型：
- `split`：份额拆分（比例 > 1），持仓数量 × 比例
- `reverse_split`：份额合并（比例 < 1），持仓数量 × 比例
- `cash_distribution`：现金分红，现金 += 持仓数量 × 每份分红
- `other`：其他公司行为，不自动应用，仅记录
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

ACTION_SPLIT = "split"
ACTION_REVERSE_SPLIT = "reverse_split"
ACTION_CASH_DISTRIBUTION = "cash_distribution"
ACTION_OTHER = "other"

ACTION_TYPES = (ACTION_SPLIT, ACTION_REVERSE_SPLIT, ACTION_CASH_DISTRIBUTION, ACTION_OTHER)

STATUS_CONFIRMED = "confirmed"
STATUS_UNVERIFIED = "unverified"
STATUS_REJECTED = "rejected"

DATA_VERSION = "ca-v1"

# 份额比例允许的浮点误差；超出即视为异常事件
RATIO_TOLERANCE = 1e-6


class CorporateActionError(RuntimeError):
    """公司行为数据或应用过程不合法。"""


@dataclass(frozen=True)
class CorporateAction:
    """一条公司行为事件。"""

    action_id: int
    code: str
    action_type: str
    ex_date: date
    effective_date: date
    share_ratio: float | None = None
    cash_per_share: float | None = None
    record_date: date | None = None
    pay_date: date | None = None
    source: str = ""
    evidence: str | None = None
    status: str = STATUS_UNVERIFIED
    data_version: str = DATA_VERSION
    notes: str | None = None

    def __post_init__(self) -> None:
        if self.action_type not in ACTION_TYPES:
            raise CorporateActionError(f"未知的公司行为类型：{self.action_type}")
        if not self.code:
            raise CorporateActionError("公司行为缺少 ETF 代码")
        if self.effective_date < self.ex_date:
            raise CorporateActionError(
                f"{self.code} 生效日 {self.effective_date} 早于除权日 {self.ex_date}"
            )
        if self.action_type in (ACTION_SPLIT, ACTION_REVERSE_SPLIT):
            if self.share_ratio is None or self.share_ratio <= 0:
                raise CorporateActionError(
                    f"{self.code} {self.action_type} 缺少有效的份额比例"
                )
            if self.action_type == ACTION_SPLIT and self.share_ratio <= 1:
                raise CorporateActionError(
                    f"{self.code} 拆分比例必须 > 1，实际 {self.share_ratio}"
                )
            if self.action_type == ACTION_REVERSE_SPLIT and self.share_ratio >= 1:
                raise CorporateActionError(
                    f"{self.code} 合并比例必须 < 1，实际 {self.share_ratio}"
                )
        if self.action_type == ACTION_CASH_DISTRIBUTION:
            if self.cash_per_share is None or self.cash_per_share <= 0:
                raise CorporateActionError(
                    f"{self.code} 现金分红缺少有效的每份分红金额"
                )

    @property
    def is_confirmed(self) -> bool:
        return self.status == STATUS_CONFIRMED

    @property
    def is_share_adjustment(self) -> bool:
        return self.action_type in (ACTION_SPLIT, ACTION_REVERSE_SPLIT)

    def as_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "code": self.code,
            "action_type": self.action_type,
            "ex_date": self.ex_date.isoformat(),
            "effective_date": self.effective_date.isoformat(),
            "share_ratio": self.share_ratio,
            "cash_per_share": self.cash_per_share,
            "record_date": self.record_date.isoformat() if self.record_date else None,
            "pay_date": self.pay_date.isoformat() if self.pay_date else None,
            "source": self.source,
            "evidence": self.evidence,
            "status": self.status,
            "data_version": self.data_version,
            "notes": self.notes,
        }


def action_from_row(row) -> CorporateAction:
    """从数据库行构造事件对象。"""
    def _date(value):
        if value in (None, ""):
            return None
        return date.fromisoformat(str(value))

    return CorporateAction(
        action_id=int(row["action_id"]),
        code=str(row["code"]),
        action_type=str(row["action_type"]),
        ex_date=_date(row["ex_date"]),
        effective_date=_date(row["effective_date"]),
        share_ratio=row["share_ratio"],
        cash_per_share=row["cash_per_share"],
        record_date=_date(row["record_date"]),
        pay_date=_date(row["pay_date"]),
        source=str(row["source"]),
        evidence=row["evidence"],
        status=str(row["status"]),
        data_version=str(row["data_version"]),
        notes=row["notes"],
    )


@dataclass(frozen=True)
class ActionImpact:
    """一次事件对账本的影响（应用前计算，应用后核对）。"""

    action_id: int
    code: str
    action_type: str
    effective_date: date
    shares_before: int
    shares_after: int
    cash_delta: float
    fractional_cash: float

    @property
    def value_before(self) -> float:
        return 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "code": self.code,
            "action_type": self.action_type,
            "effective_date": self.effective_date.isoformat(),
            "shares_before": self.shares_before,
            "shares_after": self.shares_after,
            "cash_delta": round(self.cash_delta, 6),
            "fractional_cash": round(self.fractional_cash, 6),
        }


def compute_impact(
    action: CorporateAction,
    *,
    holding: int,
    price: float | None,
) -> ActionImpact:
    """计算事件对单个持仓的影响，不修改任何状态。

    - 份额调整：新数量 = floor(旧数量 × 比例)，零碎部分按价格折现金。
    - 现金分红：现金增量 = 持仓 × 每份分红；数量不变。
    - 未确认事件：抛错，禁止应用。
    """
    if not action.is_confirmed:
        raise CorporateActionError(
            f"{action.code} {action.ex_date} 事件状态为 {action.status}，不得应用"
        )
    if holding < 0:
        raise CorporateActionError(f"{action.code} 持仓数量不能为负：{holding}")

    if action.action_type == ACTION_OTHER:
        raise CorporateActionError(
            f"{action.code} {action.ex_date} 为 other 类型，不自动应用"
        )

    if action.is_share_adjustment:
        raw = holding * float(action.share_ratio)
        new_shares = int(raw // 1)
        fractional = raw - new_shares
        fractional_cash = 0.0
        if fractional > RATIO_TOLERANCE and price is not None and price > 0:
            fractional_cash = fractional * float(price)
        return ActionImpact(
            action_id=action.action_id,
            code=action.code,
            action_type=action.action_type,
            effective_date=action.effective_date,
            shares_before=holding,
            shares_after=new_shares,
            cash_delta=fractional_cash,
            fractional_cash=fractional_cash,
        )

    if action.action_type == ACTION_CASH_DISTRIBUTION:
        cash = holding * float(action.cash_per_share or 0.0)
        return ActionImpact(
            action_id=action.action_id,
            code=action.code,
            action_type=action.action_type,
            effective_date=action.effective_date,
            shares_before=holding,
            shares_after=holding,
            cash_delta=cash,
            fractional_cash=0.0,
        )

    raise CorporateActionError(f"未处理的事件类型：{action.action_type}")


def build_action(
    *,
    code: str,
    action_type: str,
    ex_date,
    effective_date,
    share_ratio: float | None = None,
    cash_per_share: float | None = None,
    record_date=None,
    pay_date=None,
    source: str = "",
    evidence: str | None = None,
    status: str = STATUS_UNVERIFIED,
    notes: str | None = None,
    action_id: int = 0,
) -> CorporateAction:
    """构造事件（字符串日期自动转换）。"""
    def _d(value):
        if value is None or isinstance(value, date):
            return value
        return date.fromisoformat(str(value))

    return CorporateAction(
        action_id=action_id,
        code=code,
        action_type=action_type,
        ex_date=_d(ex_date),
        effective_date=_d(effective_date),
        share_ratio=share_ratio,
        cash_per_share=cash_per_share,
        record_date=_d(record_date),
        pay_date=_d(pay_date),
        source=source,
        evidence=evidence,
        status=status,
        notes=notes,
    )


def now_stamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- 数据库读写

def load_actions(
    *, start: str | None = None, end: str | None = None,
    codes: list[str] | None = None, db_path=None,
) -> list[CorporateAction]:
    """读取公司行为事件（按生效日升序）。"""
    from app.database.db import get_connection

    sql = (
        "SELECT action_id, code, action_type, ex_date, effective_date, share_ratio, "
        "cash_per_share, record_date, pay_date, source, evidence, status, "
        "data_version, notes FROM corporate_actions WHERE 1=1"
    )
    params: list[Any] = []
    if start:
        sql += " AND effective_date >= ?"
        params.append(start)
    if end:
        sql += " AND effective_date <= ?"
        params.append(end)
    if codes:
        placeholders = ",".join("?" for _ in codes)
        sql += f" AND code IN ({placeholders})"
        params.extend(codes)
    sql += " ORDER BY effective_date, code, action_id"
    with get_connection(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [action_from_row(row) for row in rows]


def save_action(action: CorporateAction, *, db_path=None) -> int:
    """写入/更新一条事件（幂等：同 code+type+ex_date 覆盖，保留 data_version）。"""
    from app.database.db import get_connection

    stamp = now_stamp()
    with get_connection(db_path) as conn:
        existing = conn.execute(
            "SELECT action_id FROM corporate_actions "
            "WHERE code=? AND action_type=? AND ex_date=?",
            (action.code, action.action_type, action.ex_date.isoformat()),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE corporate_actions SET effective_date=?, share_ratio=?, "
                "cash_per_share=?, record_date=?, pay_date=?, source=?, evidence=?, "
                "status=?, data_version=?, notes=?, updated_at=? WHERE action_id=?",
                (
                    action.effective_date.isoformat(), action.share_ratio,
                    action.cash_per_share,
                    action.record_date.isoformat() if action.record_date else None,
                    action.pay_date.isoformat() if action.pay_date else None,
                    action.source, action.evidence, action.status,
                    action.data_version, action.notes, stamp,
                    int(existing["action_id"]),
                ),
            )
            return int(existing["action_id"])
        cur = conn.execute(
            "INSERT INTO corporate_actions "
            "(code, action_type, ex_date, effective_date, share_ratio, cash_per_share, "
            " record_date, pay_date, source, evidence, status, data_version, notes, "
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                action.code, action.action_type, action.ex_date.isoformat(),
                action.effective_date.isoformat(), action.share_ratio,
                action.cash_per_share,
                action.record_date.isoformat() if action.record_date else None,
                action.pay_date.isoformat() if action.pay_date else None,
                action.source, action.evidence, action.status,
                action.data_version, action.notes, stamp, stamp,
            ),
        )
        return int(cur.lastrowid)


def record_application(
    *, run_id: str, impact: ActionImpact, db_path=None,
) -> None:
    """记录一次事件应用；同一 run 同一事件重复应用会抛错。"""
    import sqlite3

    from app.database.db import get_connection

    try:
        with get_connection(db_path) as conn:
            conn.execute(
                "INSERT INTO corporate_action_applications "
                "(run_id, action_id, code, effective_date, action_type, shares_before, "
                " shares_after, cash_delta, fractional_cash, applied_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id, impact.action_id, impact.code,
                    impact.effective_date.isoformat(), impact.action_type,
                    impact.shares_before, impact.shares_after,
                    impact.cash_delta, impact.fractional_cash, now_stamp(),
                ),
            )
    except sqlite3.IntegrityError as exc:
        raise CorporateActionError(
            f"事件 {impact.action_id} 已对 run {run_id} 应用过，不得重复应用"
        ) from exc


def applied_actions(run_id: str, *, db_path=None) -> set[int]:
    """某次回测已应用的事件 ID 集合。"""
    from app.database.db import get_connection

    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT action_id FROM corporate_action_applications WHERE run_id=?",
            (run_id,),
        ).fetchall()
    return {int(row[0]) for row in rows}


def unverified_actions(*, codes: list[str] | None = None, db_path=None) -> list[CorporateAction]:
    """返回所有未确认事件（不得应用，但必须在报告中标注）。"""
    actions = load_actions(codes=codes, db_path=db_path)
    return [item for item in actions if not item.is_confirmed]
