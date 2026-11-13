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

import hashlib
import json
import math
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

# 阶段3A.3.2.1：证据等级（与 status 解耦，status 保留兼容）
EVIDENCE_OFFICIAL = "official_confirmed"
EVIDENCE_SECONDARY = "secondary_confirmed"
EVIDENCE_UNVERIFIED = "unverified"
EVIDENCE_REJECTED = "rejected"

# 零碎份额处置口径（必须与官方公告一致，不得统一套用估值）
FRACTION_CASH_COMPENSATION = "cash_compensation"   # 按公告价现金补偿
FRACTION_TRUNCATE = "truncate"                     # 尾差计入基金财产（舍去）
FRACTION_ROUND_UP = "round_up"                     # 小数点后进位补足
# 公告未载明零碎份额处置方式：不得当作任何一种已确认规则
FRACTION_UNKNOWN = "unknown"

FRACTION_POLICIES = (
    FRACTION_CASH_COMPENSATION,
    FRACTION_TRUNCATE,
    FRACTION_ROUND_UP,
    FRACTION_UNKNOWN,
)
# 已确认的处置口径（其余视为未证实）
CONFIRMED_FRACTION_POLICIES = (
    FRACTION_CASH_COMPENSATION,
    FRACTION_TRUNCATE,
    FRACTION_ROUND_UP,
)
# 默认值：没有证据时一律 unknown，不得默认成任何一种规则
DEFAULT_FRACTION_POLICY = FRACTION_UNKNOWN

EVIDENCE_LEVELS = (
    EVIDENCE_OFFICIAL, EVIDENCE_SECONDARY, EVIDENCE_UNVERIFIED, EVIDENCE_REJECTED,
)
# 只有这两级允许进入正式回测
APPLICABLE_EVIDENCE = (EVIDENCE_OFFICIAL, EVIDENCE_SECONDARY)
# 正式结论要求的最强证据等级
OFFICIAL_ONLY = (EVIDENCE_OFFICIAL,)

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
    # 阶段3A.3.2.1 证据与版本
    evidence_status: str = EVIDENCE_UNVERIFIED
    announcement_title: str | None = None
    announcement_date: str | None = None
    announcement_url: str | None = None
    manager_name: str | None = None
    event_fingerprint: str | None = None
    version_no: int = 1
    # 零碎份额处置口径（来自官方公告）
    fractional_policy: str = DEFAULT_FRACTION_POLICY
    # 官方现金补偿价格（仅在 cash_compensation 口径下有效）
    compensation_price: float | None = None
    # 补偿价格的官方依据（公告条款原文 / 计算公式），没有依据不得现金补偿
    compensation_price_source: str | None = None

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
            # 分红资格由权益登记日决定，不能用除息日冒充登记日；
            # 现金流时点由发放日决定，不能用 T+1 估计。
            if self.record_date is None:
                raise CorporateActionError(
                    f"{self.code} {self.ex_date} 现金分红缺少权益登记日（record_date），"
                    "不得用除息日替代"
                )
            if self.pay_date is None:
                raise CorporateActionError(
                    f"{self.code} {self.ex_date} 现金分红缺少现金发放日（pay_date）"
                )
            if self.record_date > self.ex_date:
                raise CorporateActionError(
                    f"{self.code} 权益登记日 {self.record_date} 晚于除息日 {self.ex_date}"
                )
            if self.pay_date < self.ex_date:
                raise CorporateActionError(
                    f"{self.code} 现金发放日 {self.pay_date} 早于除息日 {self.ex_date}"
                )
        if self.evidence_status not in EVIDENCE_LEVELS:
            raise CorporateActionError(
                f"未知的证据等级：{self.evidence_status}"
            )
        if self.fractional_policy not in FRACTION_POLICIES:
            raise CorporateActionError(
                f"未知的零碎份额处置口径：{self.fractional_policy}"
            )
        # 现金补偿必须有官方补偿价格依据，否则不得声明该口径
        if (self.fractional_policy == FRACTION_CASH_COMPENSATION
                and self.compensation_price_source is None):
            raise CorporateActionError(
                f"{self.code} {self.ex_date} 声明 cash_compensation "
                "但缺少官方补偿价格依据（compensation_price_source）"
            )
        # 现金分红必须有发放日，否则无法区分「应收」与「可用现金」
        if self.action_type == ACTION_CASH_DISTRIBUTION and self.pay_date is None:
            raise CorporateActionError(
                f"{self.code} {self.ex_date} 现金分红缺少发放日，"
                "无法确定现金到账时点"
            )
        if (self.action_type == ACTION_CASH_DISTRIBUTION and self.pay_date
                and self.pay_date < self.ex_date):
            raise CorporateActionError(
                f"{self.code} {self.ex_date} 发放日 {self.pay_date} 早于除息日"
            )

    @property
    def is_confirmed(self) -> bool:
        """能否进入正式回测：必须同时通过 status 与证据等级两道关。"""
        return (self.status == STATUS_CONFIRMED
                and self.evidence_status in APPLICABLE_EVIDENCE)

    @property
    def is_officially_confirmed(self) -> bool:
        return self.evidence_status == EVIDENCE_OFFICIAL

    @property
    def confirm_date(self) -> date:
        """经济权益确认日：分红在除息日，份额调整在实际生效日。"""
        return self.ex_date if self.action_type == ACTION_CASH_DISTRIBUTION else self.effective_date

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
            "evidence_status": self.evidence_status,
            "announcement_title": self.announcement_title,
            "announcement_date": self.announcement_date,
            "announcement_url": self.announcement_url,
            "manager_name": self.manager_name,
            "event_fingerprint": self.event_fingerprint,
            "version_no": self.version_no,
            "fractional_policy": self.fractional_policy,
            "compensation_price": self.compensation_price,
            "compensation_price_source": self.compensation_price_source,
        }


def action_from_row(row) -> CorporateAction:
    """从数据库行构造事件对象。"""
    def _date(value):
        if value in (None, ""):
            return None
        return date.fromisoformat(str(value))

    def _opt(key):
        try:
            return row[key]
        except (IndexError, KeyError):
            return None

    def _num(key):
        value = _opt(key)
        if value in (None, ""):
            return None
        return float(value)

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
        evidence_status=str(_opt("evidence_status") or EVIDENCE_UNVERIFIED),
        announcement_title=_opt("announcement_title"),
        announcement_date=_opt("announcement_date"),
        announcement_url=_opt("announcement_url"),
        manager_name=_opt("manager_name"),
        event_fingerprint=_opt("event_fingerprint"),
        version_no=int(_opt("version_no") or 1),
        fractional_policy=str(_opt("fractional_policy") or DEFAULT_FRACTION_POLICY),
        compensation_price=_num("compensation_price"),
        compensation_price_source=_opt("compensation_price_source"),
    )


@dataclass(frozen=True)
class ActionImpact:
    """一次事件对账本的影响（应用前计算，应用后核对）。

    对现金分红：
    - `cash_delta` 是应收金额，在 `confirm_date`（除息日）确认；
    - `pay_date` 为官方现金发放日，届时才变成可用现金。
    对份额调整：`shares_before/after` 在 `effective_date` 生效，无现金流入。
    """

    action_id: int
    code: str
    action_type: str
    effective_date: date
    shares_before: int
    shares_after: int
    cash_delta: float
    fractional_cash: float
    pay_date: date | None = None
    confirm_date: date | None = None
    # 阶段3A.3.2.2：官方折算比例与零碎份额处置口径
    official_ratio: float | None = None
    fractional_policy: str = "truncate"
    compensation_price: float | None = None

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
            "pay_date": self.pay_date.isoformat() if self.pay_date else None,
            "confirm_date": self.confirm_date.isoformat() if self.confirm_date else None,
            "official_ratio": self.official_ratio,
            "fractional_policy": self.fractional_policy,
            "compensation_price": self.compensation_price,
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
        ratio = float(action.share_ratio)
        raw = holding * ratio
        policy = action.fractional_policy
        fractional = raw - (raw // 1)

        if policy == FRACTION_UNKNOWN:
            # 规则未证实：只有「实际不产生零碎份额」时才可安全应用。
            # 一旦产生零碎份额，任何处置方式都是猜测，必须 fail closed。
            if fractional > RATIO_TOLERANCE:
                raise CorporateActionError(
                    f"{action.code} {action.ex_date} 零碎份额处置口径未证实"
                    f"（{policy}），但持仓 {holding} × 比例 {ratio} "
                    f"产生零碎份额 {fractional:.6f}，不得自行猜测处置方式"
                )
            new_shares = int(raw // 1)
            fractional_cash = 0.0
        elif policy == FRACTION_ROUND_UP:
            new_shares = int(math.ceil(raw - RATIO_TOLERANCE))
            fractional_cash = 0.0
        elif policy == FRACTION_CASH_COMPENSATION:
            # 现金补偿必须使用官方补偿价格，不得用事件日收盘价冒充
            if action.compensation_price is None or action.compensation_price_source is None:
                raise CorporateActionError(
                    f"{action.code} {action.ex_date} cash_compensation 缺少官方补偿价格依据，"
                    "不得使用普通收盘价替代"
                )
            new_shares = int(raw // 1)
            fractional_cash = 0.0
            if fractional > RATIO_TOLERANCE:
                fractional_cash = fractional * float(action.compensation_price)
        else:
            # truncate：尾差计入基金财产，无现金补偿
            new_shares = int(raw // 1)
            fractional_cash = 0.0
        return ActionImpact(
            action_id=action.action_id,
            code=action.code,
            action_type=action.action_type,
            effective_date=action.effective_date,
            shares_before=holding,
            shares_after=new_shares,
            cash_delta=fractional_cash,
            fractional_cash=fractional_cash,
            confirm_date=action.effective_date,
            official_ratio=ratio,
            fractional_policy=policy,
            compensation_price=(action.compensation_price
                                if policy == FRACTION_CASH_COMPENSATION else None),
        )

    if action.action_type == ACTION_CASH_DISTRIBUTION:
        # 现金分红的经济权益在除息日确定，现金流在发放日到账。
        # cash_delta 只表示「权重金额」，实际入账时点由 engine 分两步处理。
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
            confirm_date=action.ex_date,
            pay_date=action.pay_date,
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
    evidence_status: str = EVIDENCE_UNVERIFIED,
    announcement_title: str | None = None,
    announcement_date: str | None = None,
    announcement_url: str | None = None,
    manager_name: str | None = None,
    fractional_policy: str = DEFAULT_FRACTION_POLICY,
    compensation_price: float | None = None,
    compensation_price_source: str | None = None,
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
        evidence_status=evidence_status,
        announcement_title=announcement_title,
        announcement_date=announcement_date,
        announcement_url=announcement_url,
        manager_name=manager_name,
        fractional_policy=fractional_policy,
        compensation_price=compensation_price,
        compensation_price_source=compensation_price_source,
    )


def now_stamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- 数据库读写

# 各事件类型的「区间筛选日期」：
# 现金分红的经济权益在除息日确定，拆分/合并在生效交易日调整份额。
WINDOW_DATE_FIELD = {
    ACTION_CASH_DISTRIBUTION: "ex_date",
    ACTION_SPLIT: "effective_date",
    ACTION_REVERSE_SPLIT: "effective_date",
    ACTION_OTHER: "effective_date",
}


def window_date(action: CorporateAction) -> date:
    """事件在回测区间里的判定日期（经济权益日）。"""
    return action.ex_date if action.action_type == ACTION_CASH_DISTRIBUTION         else action.effective_date


def load_actions(
    *, start: str | None = None, end: str | None = None,
    codes: list[str] | None = None, db_path=None,
) -> list[CorporateAction]:
    """读取公司行为事件。

    **按事件类型分别使用实际应用日期筛选**（阶段3A.3.2.2 修正）：

    - 现金分红 → `ex_date`（除息日确认应收，必须在区间内）
    - 拆分 / 合并 → `effective_date`（实际调整份额的交易日）

    旧实现统一按 `effective_date` 筛，会漏掉「除息日在区间最后一天、
    生效日在区间之后」的分红，导致回测结束时应收凭空消失。
    """
    from app.database.db import get_connection

    sql = (
        "SELECT action_id, code, action_type, ex_date, effective_date, share_ratio, "
        "cash_per_share, record_date, pay_date, source, evidence, status, "
        "data_version, notes, evidence_status, announcement_title, announcement_date, "
        "announcement_url, manager_name, event_fingerprint, version_no, fractional_policy, "
        "compensation_price, compensation_price_source "
        "FROM corporate_actions WHERE 1=1"
    )
    params: list[Any] = []
    if start:
        # 分红的 ex_date >= start；拆分/合并的 effective_date >= start
        sql += (" AND ("
                "(action_type = 'cash_distribution' AND ex_date >= ?) OR "
                "(action_type != 'cash_distribution' AND effective_date >= ?))")
        params.extend([start, start])
    if end:
        sql += (" AND ("
                "(action_type = 'cash_distribution' AND ex_date <= ?) OR "
                "(action_type != 'cash_distribution' AND effective_date <= ?))")
        params.extend([end, end])
    if codes:
        placeholders = ",".join("?" for _ in codes)
        sql += f" AND code IN ({placeholders})"
        params.extend(codes)
    # 分红可能生效日晚于区间末尾，但仍须按 ex_date 顺序读到
    sql += " ORDER BY ex_date, effective_date, code, action_id"
    with get_connection(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [action_from_row(row) for row in rows]


def event_key(action: CorporateAction) -> str:
    """事件的稳定标识：同一标的、同一类型、同一除息日视为同一事件。"""
    return f"{action.code}|{action.action_type}|{action.ex_date.isoformat()}"


def compute_event_fingerprint(action: CorporateAction) -> str:
    """单个事件的确定性 SHA256。

    覆盖三组字段，任何一项变化都会改变指纹：

    1. **经济要素**：code / action_type / ex_date / effective_date /
       share_ratio / cash_per_share / record_date / pay_date / fractional_policy
       —— 决定账本怎么记
    2. **证据元数据**：evidence_status / source / announcement_title /
       announcement_date / announcement_url / manager_name / evidence
       —— 决定这条事件凭什么可信（阶段3A.3.2.2 新增）
    3. **数据版本**：data_version

    不含 `notes`、`version_no`、`action_id`、`event_fingerprint` 本身：
    这些是实现细节或派生字段，改动它们不应改变指纹。
    """
    payload = {
        # ---- 经济要素 ----
        "code": action.code,
        "action_type": action.action_type,
        "ex_date": action.ex_date.isoformat(),
        "effective_date": action.effective_date.isoformat(),
        "share_ratio": None if action.share_ratio is None else round(float(action.share_ratio), 10),
        "cash_per_share": (None if action.cash_per_share is None
                           else round(float(action.cash_per_share), 10)),
        "record_date": action.record_date.isoformat() if action.record_date else None,
        "pay_date": action.pay_date.isoformat() if action.pay_date else None,
        "fractional_policy": action.fractional_policy,
        "compensation_price": (None if action.compensation_price is None
                              else round(float(action.compensation_price), 10)),
        "compensation_price_source": action.compensation_price_source,
        # ---- 证据元数据（阶段3A.3.2.2 新增）----
        "evidence_status": action.evidence_status,
        "source": action.source,
        "announcement_title": action.announcement_title,
        "announcement_date": action.announcement_date,
        "announcement_url": action.announcement_url,
        "manager_name": action.manager_name,
        "evidence": action.evidence,
        # ---- 数据版本 ----
        "data_version": action.data_version,
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_events_digest(actions: list[CorporateAction]) -> str:
    """一组事件的确定性 SHA256（按稳定顺序排序后逐条哈希）。

    只包含参与本次回测的事件，因此未参与的事件不会污染指纹。
    """
    ordered = sorted(actions, key=lambda a: (a.effective_date, a.code, a.action_type,
                                             a.ex_date.isoformat()))
    digest = hashlib.sha256()
    digest.update(f"ca-events-v2|{len(ordered)}|".encode("utf-8"))
    for action in ordered:
        digest.update(compute_event_fingerprint(action).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def save_receivable(
    *, run_id: str, action: CorporateAction, shares: int, amount: float, db_path=None,
) -> None:
    """记录一笔应收分红（除息日确认，发放日结清）。"""
    from app.database.db import get_connection

    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO dividend_receivables "
            "(run_id, action_id, code, record_date, ex_date, pay_date, shares_at_ex, "
            " cash_per_share, amount, status, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,'pending',?) "
            "ON CONFLICT(run_id, action_id) DO NOTHING",
            (
                run_id, action.action_id, action.code,
                action.record_date.isoformat() if action.record_date else None,
                action.ex_date.isoformat(),
                (action.pay_date or action.effective_date).isoformat(),
                shares, float(action.cash_per_share or 0.0), round(amount, 6),
                now_stamp(),
            ),
        )


def settle_receivable(*, run_id: str, action_id: int, db_path=None) -> None:
    from app.database.db import get_connection

    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE dividend_receivables SET status='settled', settled_at=? "
            "WHERE run_id=? AND action_id=? AND status='pending'",
            (now_stamp(), run_id, action_id),
        )


def save_action(
    action: CorporateAction,
    *,
    db_path=None,
    change_reason: str | None = None,
) -> int:
    """写入事件；同一事件内容变化时**新增版本**，不覆盖历史。

    返回当前生效的 action_id。
    """
    from app.database.db import get_connection

    stamp = now_stamp()
    fingerprint = compute_event_fingerprint(action)
    key = event_key(action)

    with get_connection(db_path) as conn:
        existing = conn.execute(
            "SELECT action_id, version_no, event_fingerprint, fractional_policy, "
            "evidence_status, share_ratio, cash_per_share, effective_date, record_date, "
            "pay_date FROM corporate_actions "
            "WHERE code=? AND action_type=? AND ex_date=?",
            (action.code, action.action_type, action.ex_date.isoformat()),
        ).fetchone()

        if existing:
            action_id = int(existing["action_id"])
            old_fp = existing["event_fingerprint"]
            # 指纹相同**且**关键列确实一致才早退。
            # 只比指纹会漏掉「库内 fingerprint 已更新但其它列没落库」的脏状态，
            # 那样 subsequent 写入会被永久跳过。
            same_row = (
                old_fp == fingerprint
                and str(existing["fractional_policy"] or "") == action.fractional_policy
                and str(existing["evidence_status"] or "") == action.evidence_status
                and str(existing["effective_date"]) == action.effective_date.isoformat()
            )
            if same_row:
                return action_id
            old_version = int(existing["version_no"] or 1)
            # 先把旧版本快照写入版本表（只写一次）
            _archive_version(conn, key, old_version, action_id, change_reason, stamp)
            new_version = old_version + 1
            conn.execute(
                "UPDATE corporate_actions SET effective_date=?, share_ratio=?, "
                "cash_per_share=?, record_date=?, pay_date=?, source=?, evidence=?, "
                "status=?, data_version=?, notes=?, evidence_status=?, "
                "announcement_title=?, announcement_date=?, announcement_url=?, "
                "manager_name=?, fractional_policy=?, compensation_price=?, "
                "compensation_price_source=?, event_fingerprint=?, "
                "version_no=?, updated_at=? WHERE action_id=?",
                (
                    action.effective_date.isoformat(), action.share_ratio,
                    action.cash_per_share,
                    action.record_date.isoformat() if action.record_date else None,
                    action.pay_date.isoformat() if action.pay_date else None,
                    action.source, action.evidence, action.status,
                    action.data_version, action.notes, action.evidence_status,
                    action.announcement_title, action.announcement_date,
                    action.announcement_url, action.manager_name,
                    action.fractional_policy, action.compensation_price,
                    action.compensation_price_source, fingerprint, new_version,
                    stamp, action_id,
                ),
            )
            _write_version(conn, key, new_version, action_id, action,
                           change_reason or "内容变更", stamp)
            return action_id

        cur = conn.execute(
            "INSERT INTO corporate_actions "
            "(code, action_type, ex_date, effective_date, share_ratio, cash_per_share, "
            " record_date, pay_date, source, evidence, status, data_version, notes, "
            " created_at, updated_at, evidence_status, announcement_title, "
            " announcement_date, announcement_url, manager_name, event_fingerprint, "
            " version_no, fractional_policy, compensation_price, "
            " compensation_price_source) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                action.code, action.action_type, action.ex_date.isoformat(),
                action.effective_date.isoformat(), action.share_ratio,
                action.cash_per_share,
                action.record_date.isoformat() if action.record_date else None,
                action.pay_date.isoformat() if action.pay_date else None,
                action.source, action.evidence, action.status,
                action.data_version, action.notes, stamp, stamp,
                action.evidence_status, action.announcement_title,
                action.announcement_date, action.announcement_url,
                action.manager_name, fingerprint, 1, action.fractional_policy,
                action.compensation_price, action.compensation_price_source,
            ),
        )
        action_id = int(cur.lastrowid)
        _write_version(conn, key, 1, action_id, action,
                       change_reason or "首次写入", stamp)
        return action_id


def _snapshot_payload(action: CorporateAction) -> str:
    return json.dumps(action.as_dict(), ensure_ascii=False, sort_keys=True)


def _write_version(conn, key: str, version_no: int, action_id: int,
                   action: CorporateAction, reason: str, stamp: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO corporate_action_versions "
        "(action_key, version_no, code, action_type, ex_date, effective_date, "
        " share_ratio, cash_per_share, record_date, pay_date, source, evidence_status, "
        " data_version, change_reason, snapshot_json, created_at, fractional_policy, "
        " compensation_price, compensation_price_source) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            key, version_no, action.code, action.action_type,
            action.ex_date.isoformat(), action.effective_date.isoformat(),
            action.share_ratio, action.cash_per_share,
            action.record_date.isoformat() if action.record_date else None,
            action.pay_date.isoformat() if action.pay_date else None,
            action.source, action.evidence_status, action.data_version,
            reason, _snapshot_payload(action), stamp, action.fractional_policy,
            action.compensation_price, action.compensation_price_source,
        ),
    )


def _archive_version(conn, key: str, version_no: int, action_id: int,
                     reason: str | None, stamp: str) -> None:
    """把当前库内版本存进版本表（若尚未存过）。"""
    exists = conn.execute(
        "SELECT 1 FROM corporate_action_versions WHERE action_key=? AND version_no=?",
        (key, version_no),
    ).fetchone()
    if exists:
        return
    row = conn.execute(
        "SELECT * FROM corporate_actions WHERE action_id=?", (action_id,)
    ).fetchone()
    if row is None:
        return
    old = action_from_row(row)
    _write_version(conn, key, version_no, action_id, old,
                   reason or "历史版本归档", stamp)


def event_versions(action_key: str, *, db_path=None) -> list[dict]:
    from app.database.db import get_connection

    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT version_no, change_reason, evidence_status, created_at, snapshot_json "
            "FROM corporate_action_versions WHERE action_key=? ORDER BY version_no",
            (action_key,),
        ).fetchall()
    return [dict(row) for row in rows]


def record_application(
    *, run_id: str, impact: ActionImpact, ledger: dict | None = None, db_path=None,
) -> None:
    """记录一次事件应用；同一 run 同一事件重复应用会抛错。"""
    import sqlite3

    from app.database.db import get_connection

    ledger = ledger or {}

    try:
        with get_connection(db_path) as conn:
            conn.execute(
                "INSERT INTO corporate_action_applications "
                "(run_id, action_id, code, effective_date, action_type, shares_before, "
                " shares_after, cash_delta, fractional_cash, applied_at, "
                " fractional_shares, disposed_cost_basis, realized_pnl, official_ratio) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id, impact.action_id, impact.code,
                    impact.effective_date.isoformat(), impact.action_type,
                    impact.shares_before, impact.shares_after,
                    impact.cash_delta, impact.fractional_cash, now_stamp(),
                    float(ledger.get("fractional_shares") or 0.0),
                    float(ledger.get("disposed_cost_basis") or 0.0),
                    float(ledger.get("realized_pnl") or 0.0),
                    impact.official_ratio,
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
