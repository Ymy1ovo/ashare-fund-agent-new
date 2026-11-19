"""申购赎回状态快照与费率规则仓储。"""
from __future__ import annotations

from pathlib import Path

from app.fund.models import FeeRuleRecord, SubscriptionStatusRecord
from app.fund.repo_base import get_conn


class StatusRepository:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path

    # ------------------------------------------------------------ 状态快照
    def save_subscription_status(self, share_class_id: int,
                                 rec: SubscriptionStatusRecord) -> int:
        """按 (share_class, as_of_date, source) 幂等保存当日快照。

        历史快照不会被最新值覆盖——不同日期是不同的行。
        """
        with get_conn(self.db_path) as conn:
            row = conn.execute(
                """SELECT status_id FROM fund_subscription_status
                   WHERE share_class_id=? AND as_of_date=? AND source=?""",
                (share_class_id, rec.as_of_date, rec.source)).fetchone()
            if row:
                conn.execute(
                    """UPDATE fund_subscription_status SET
                         purchase_status=?, redeem_status=?, daily_limit=?,
                         min_purchase=?, next_open_date=?, alipay_purchasable=?,
                         ingested_at=?
                       WHERE status_id=?""",
                    (rec.purchase_status, rec.redeem_status, rec.daily_limit,
                     rec.min_purchase, rec.next_open_date, rec.alipay_purchasable,
                     rec.ingested_at, int(row["status_id"])))
                return int(row["status_id"])
            cur = conn.execute(
                """INSERT INTO fund_subscription_status
                   (share_class_id, as_of_date, purchase_status, redeem_status,
                    daily_limit, min_purchase, next_open_date, alipay_purchasable,
                    source, ingested_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (share_class_id, rec.as_of_date, rec.purchase_status,
                 rec.redeem_status, rec.daily_limit, rec.min_purchase,
                 rec.next_open_date, rec.alipay_purchasable, rec.source,
                 rec.ingested_at))
            return int(cur.lastrowid)

    def list_subscription_status(self, share_class_id: int) -> list[dict]:
        with get_conn(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM fund_subscription_status WHERE share_class_id=? "
                "ORDER BY as_of_date", (share_class_id,)).fetchall()
            return [dict(r) for r in rows]

    def latest_subscription_status(self, share_class_id: int) -> dict | None:
        with get_conn(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM fund_subscription_status WHERE share_class_id=? "
                "ORDER BY as_of_date DESC LIMIT 1", (share_class_id,)).fetchone()
            return dict(row) if row else None

    def count_subscription_status(self) -> int:
        with get_conn(self.db_path) as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM fund_subscription_status").fetchone()[0]

    # ------------------------------------------------------------ 费率
    def add_fee_rule(self, share_class_id: int, rec: FeeRuleRecord) -> int:
        """费率规则幂等写入。

        rate 允许 NULL —— 表示「费率未知」，绝不填行业平均值。
        """
        with get_conn(self.db_path) as conn:
            row = conn.execute(
                """SELECT fee_rule_id FROM fund_fee_rules
                   WHERE share_class_id=? AND fee_type=? AND tier_order=?
                     AND COALESCE(effective_from,'__na__')=COALESCE(?,'__na__')""",
                (share_class_id, rec.fee_type, rec.tier_order,
                 rec.effective_from)).fetchone()
            if row:
                return int(row["fee_rule_id"])
            cur = conn.execute(
                """INSERT INTO fund_fee_rules
                   (share_class_id, fee_type, tier_order, lower_bound, upper_bound,
                    rate, holding_days_min, holding_days_max, effective_from,
                    effective_to, source, evidence_level, ingested_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (share_class_id, rec.fee_type, rec.tier_order, rec.lower_bound,
                 rec.upper_bound, rec.rate, rec.holding_days_min,
                 rec.holding_days_max, rec.effective_from, rec.effective_to,
                 rec.source, rec.evidence_level, rec.ingested_at))
            return int(cur.lastrowid)

    def find_fee_rules(self, share_class_id: int, fee_type: str, *,
                       as_of: str | None = None,
                       holding_days: int | None = None) -> list[dict]:
        """按有效日期 + 持有期限查询费率档位。"""
        sql = ("SELECT * FROM fund_fee_rules WHERE share_class_id=? AND fee_type=?")
        params: list = [share_class_id, fee_type]
        if as_of:
            sql += (" AND (effective_from IS NULL OR effective_from <= ?)"
                    " AND (effective_to IS NULL OR effective_to >= ?)")
            params += [as_of, as_of]
        if holding_days is not None:
            sql += (" AND (holding_days_min IS NULL OR holding_days_min <= ?)"
                    " AND (holding_days_max IS NULL OR holding_days_max >= ?)")
            params += [holding_days, holding_days]
        sql += " ORDER BY tier_order"
        with get_conn(self.db_path) as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def count_fee_rules(self) -> int:
        with get_conn(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) FROM fund_fee_rules").fetchone()[0]
