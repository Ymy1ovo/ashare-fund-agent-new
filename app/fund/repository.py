"""基金本体与份额的仓储。

只负责 master / share_classes / lifecycle / manager / aum 这五类；
净值与分红在 repo_nav，状态与费率在 repo_status。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from app.fund.models import (
    AumRecord, FundMasterRecord, FundShareClassRecord,
    LifecycleEventRecord, ManagerRecord,
)
from app.fund.repo_base import get_conn, now_iso, should_overwrite, use_conn


class FundRepository:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path

    # ------------------------------------------------------------ master
    def upsert_master(self, rec: FundMasterRecord, *,
                      conn: sqlite3.Connection | None = None) -> int:
        """按主代码幂等写入基金本体，返回 fund_id。

        conn 非空时复用该连接（不自行 commit/rollback），用于调用方掌控事务。
        """
        with use_conn(self.db_path, conn) as conn:
            row = conn.execute(
                "SELECT fund_id, source FROM fund_master WHERE fund_code_primary=?",
                (rec.fund_code_primary,)).fetchone()
            if row is None:
                cur = conn.execute(
                    """INSERT INTO fund_master
                       (fund_code_primary, fund_name, fund_full_name, fund_company,
                        custodian, fund_type_l1, fund_type_l2, invest_scope, benchmark,
                        established_date, terminated_date, lifecycle_status,
                        is_index_fund, tracking_index, needs_review, source,
                        source_updated_at, ingested_at, data_version)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (rec.fund_code_primary, rec.fund_name, rec.fund_full_name,
                     rec.fund_company, rec.custodian, rec.fund_type_l1,
                     rec.fund_type_l2, rec.invest_scope, rec.benchmark,
                     rec.established_date, rec.terminated_date,
                     rec.lifecycle_status, rec.is_index_fund, rec.tracking_index,
                     rec.needs_review, rec.source, rec.source_updated_at,
                     rec.ingested_at, rec.data_version))
                return int(cur.lastrowid)
            fund_id = int(row["fund_id"])
            if not should_overwrite(str(row["source"]), rec.source):
                return fund_id
            conn.execute(
                """UPDATE fund_master SET
                     fund_name=?, fund_full_name=?, fund_company=?, custodian=?,
                     fund_type_l1=?, fund_type_l2=?, invest_scope=?, benchmark=?,
                     established_date=?, terminated_date=?, lifecycle_status=?,
                     is_index_fund=?, tracking_index=?, needs_review=?,
                     source=?, source_updated_at=?, ingested_at=?, data_version=?
                   WHERE fund_id=?""",
                (rec.fund_name, rec.fund_full_name, rec.fund_company, rec.custodian,
                 rec.fund_type_l1, rec.fund_type_l2, rec.invest_scope, rec.benchmark,
                 rec.established_date, rec.terminated_date, rec.lifecycle_status,
                 rec.is_index_fund, rec.tracking_index, rec.needs_review,
                 rec.source, rec.source_updated_at, rec.ingested_at,
                 rec.data_version, fund_id))
            return fund_id

    def get_master_by_code(self, code: str) -> dict | None:
        with get_conn(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM fund_master WHERE fund_code_primary=?", (code,)).fetchone()
            return dict(row) if row else None

    def get_master(self, fund_id: int) -> dict | None:
        with get_conn(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM fund_master WHERE fund_id=?", (fund_id,)).fetchone()
            return dict(row) if row else None

    def count_master(self) -> int:
        with get_conn(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) FROM fund_master").fetchone()[0]

    # ------------------------------------------------------------ share classes
    def upsert_share_class(self, fund_id: int, rec: FundShareClassRecord, *,
                           conn: sqlite3.Connection | None = None) -> int:
        """按份额代码幂等写入，返回 share_class_id。

        conn 非空时复用该连接（不自行 commit/rollback）。
        """
        with use_conn(self.db_path, conn) as conn:
            row = conn.execute(
                "SELECT share_class_id, source FROM fund_share_classes "
                "WHERE share_class_code=?", (rec.share_class_code,)).fetchone()
            if row is None:
                cur = conn.execute(
                    """INSERT INTO fund_share_classes
                       (fund_id, share_class_code, share_class_name, share_class_type,
                        currency, is_primary, management_fee, custody_fee,
                        sales_service_fee, min_purchase, min_holding, listed_date,
                        terminated_date, source, source_updated_at, ingested_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (fund_id, rec.share_class_code, rec.share_class_name,
                     rec.share_class_type, rec.currency, rec.is_primary,
                     rec.management_fee, rec.custody_fee, rec.sales_service_fee,
                     rec.min_purchase, rec.min_holding, rec.listed_date,
                     rec.terminated_date, rec.source, rec.source_updated_at,
                     rec.ingested_at))
                return int(cur.lastrowid)
            sc_id = int(row["share_class_id"])
            if not should_overwrite(str(row["source"]), rec.source):
                return sc_id
            conn.execute(
                """UPDATE fund_share_classes SET
                     fund_id=?, share_class_name=?, share_class_type=?, currency=?,
                     is_primary=?, management_fee=?, custody_fee=?, sales_service_fee=?,
                     min_purchase=?, min_holding=?, listed_date=?, terminated_date=?,
                     source=?, source_updated_at=?, ingested_at=?
                   WHERE share_class_id=?""",
                (fund_id, rec.share_class_name, rec.share_class_type, rec.currency,
                 rec.is_primary, rec.management_fee, rec.custody_fee,
                 rec.sales_service_fee, rec.min_purchase, rec.min_holding,
                 rec.listed_date, rec.terminated_date, rec.source,
                 rec.source_updated_at, rec.ingested_at, sc_id))
            return sc_id

    def get_share_class(self, code: str) -> dict | None:
        with get_conn(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM fund_share_classes WHERE share_class_code=?",
                (code,)).fetchone()
            return dict(row) if row else None

    def get_share_class_by_id(self, share_class_id: int) -> dict | None:
        with get_conn(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM fund_share_classes WHERE share_class_id=?",
                (share_class_id,)).fetchone()
            return dict(row) if row else None

    def list_shares_of_fund(self, fund_id: int) -> list[dict]:
        with get_conn(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM fund_share_classes WHERE fund_id=? "
                "ORDER BY is_primary DESC, share_class_code", (fund_id,)).fetchall()
            return [dict(r) for r in rows]

    def get_fund_with_shares(self, fund_code: str) -> dict | None:
        """基金本体 + 全部份额的关联查询。"""
        master = self.get_master_by_code(fund_code)
        if master is None:
            return None
        master["share_classes"] = self.list_shares_of_fund(master["fund_id"])
        return master

    def count_share_classes(self) -> int:
        with get_conn(self.db_path) as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM fund_share_classes").fetchone()[0]

    # ------------------------------------------------------------ lifecycle
    def add_lifecycle_event(self, fund_id: int, rec: LifecycleEventRecord) -> int:
        """生命周期事件幂等写入（同一 fund+type+date+source 不重复）。"""
        with get_conn(self.db_path) as conn:
            row = conn.execute(
                """SELECT event_id FROM fund_lifecycle_events
                   WHERE fund_id=? AND event_type=?
                     AND COALESCE(event_date,'__unknown__')=COALESCE(?,'__unknown__')
                     AND source=?""",
                (fund_id, rec.event_type, rec.event_date, rec.source)).fetchone()
            if row:
                return int(row["event_id"])
            cur = conn.execute(
                """INSERT INTO fund_lifecycle_events
                   (fund_id, event_type, event_date, announcement_date,
                    announcement_url, detail, successor_fund_id, evidence_level,
                    source, ingested_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (fund_id, rec.event_type, rec.event_date, rec.announcement_date,
                 rec.announcement_url, rec.detail, rec.successor_fund_id,
                 rec.evidence_level, rec.source, rec.ingested_at))
            return int(cur.lastrowid)

    def list_lifecycle_events(self, fund_id: int) -> list[dict]:
        with get_conn(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM fund_lifecycle_events WHERE fund_id=? "
                "ORDER BY COALESCE(event_date,'9999')", (fund_id,)).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------ managers
    def add_manager(self, fund_id: int, rec: ManagerRecord) -> int:
        with get_conn(self.db_path) as conn:
            row = conn.execute(
                """SELECT manager_id FROM fund_manager_history
                   WHERE fund_id=? AND manager_name=?
                     AND COALESCE(start_date,'__unknown__')=COALESCE(?,'__unknown__')""",
                (fund_id, rec.manager_name, rec.start_date)).fetchone()
            if row:
                conn.execute(
                    """UPDATE fund_manager_history SET company=?, end_date=?,
                         tenure_days=?, source=?, ingested_at=?
                       WHERE manager_id=?""",
                    (rec.company, rec.end_date, rec.tenure_days, rec.source,
                     rec.ingested_at, int(row["manager_id"])))
                return int(row["manager_id"])
            cur = conn.execute(
                """INSERT INTO fund_manager_history
                   (fund_id, manager_name, company, start_date, end_date,
                    tenure_days, source, ingested_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (fund_id, rec.manager_name, rec.company, rec.start_date,
                 rec.end_date, rec.tenure_days, rec.source, rec.ingested_at))
            return int(cur.lastrowid)

    def list_managers(self, fund_id: int) -> list[dict]:
        with get_conn(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM fund_manager_history WHERE fund_id=?", (fund_id,)).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------ aum
    def add_aum(self, rec: AumRecord, *, fund_id: int | None = None,
                share_class_id: int | None = None) -> int:
        with get_conn(self.db_path) as conn:
            row = conn.execute(
                """SELECT aum_id FROM fund_aum_history
                   WHERE COALESCE(fund_id,-1)=COALESCE(?,-1)
                     AND COALESCE(share_class_id,-1)=COALESCE(?,-1)
                     AND report_date=? AND source=?""",
                (fund_id, share_class_id, rec.report_date, rec.source)).fetchone()
            if row:
                return int(row["aum_id"])
            cur = conn.execute(
                """INSERT INTO fund_aum_history
                   (fund_id, share_class_id, report_date, aum_total, shares_total,
                    aum_unit, source, ingested_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (fund_id, share_class_id, rec.report_date, rec.aum_total,
                 rec.shares_total, rec.aum_unit, rec.source, rec.ingested_at))
            return int(cur.lastrowid)

    def list_aum(self, fund_id: int) -> list[dict]:
        with get_conn(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM fund_aum_history WHERE fund_id=? ORDER BY report_date",
                (fund_id,)).fetchall()
            return [dict(r) for r in rows]
