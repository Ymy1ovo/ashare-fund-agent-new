"""净值与分红仓储。

单位净值与累计净值分列存储，货币基金走 nav_kind='money_yield' 分支。
批量写入全部幂等；已存在记录按 (source) 置信度决定是否覆盖。
"""
from __future__ import annotations

from pathlib import Path

from app.fund.models import DividendRecord, NavRecord
from app.fund.repo_base import get_conn, should_overwrite


class NavRepository:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path

    # ------------------------------------------------------------ 净值
    def upsert_nav_batch(self, share_class_id: int,
                         records: list[NavRecord]) -> dict:
        """批量写入净值，返回统计。

        幂等键：(share_class_id, nav_date, nav_kind)。
        冲突规则：
          - 同来源 → 更新（同一数据源的新鲜抓取）；
          - 新来源置信度更高 → 覆盖；
          - 新来源置信度更低 → 跳过并计数 skipped_lower_source。
        """
        stats = {"inserted": 0, "updated": 0, "skipped": 0,
                 "skipped_lower_source": 0}
        if not records:
            return stats
        with get_conn(self.db_path) as conn:
            for rec in records:
                existing = conn.execute(
                    """SELECT source FROM fund_nav_daily
                       WHERE share_class_id=? AND nav_date=? AND nav_kind=?""",
                    (share_class_id, rec.nav_date, rec.nav_kind)).fetchone()
                if existing is None:
                    conn.execute(
                        """INSERT INTO fund_nav_daily
                           (share_class_id, nav_date, nav_kind, unit_nav, acc_nav,
                            per_10k_yield, seven_day_annual, daily_return,
                            nav_status, source, ingested_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (share_class_id, rec.nav_date, rec.nav_kind, rec.unit_nav,
                         rec.acc_nav, rec.per_10k_yield, rec.seven_day_annual,
                         rec.daily_return, rec.nav_status, rec.source,
                         rec.ingested_at))
                    stats["inserted"] += 1
                elif should_overwrite(str(existing["source"]), rec.source):
                    conn.execute(
                        """UPDATE fund_nav_daily SET
                             unit_nav=?, acc_nav=?, per_10k_yield=?,
                             seven_day_annual=?, daily_return=?, nav_status=?,
                             source=?, ingested_at=?
                           WHERE share_class_id=? AND nav_date=? AND nav_kind=?""",
                        (rec.unit_nav, rec.acc_nav, rec.per_10k_yield,
                         rec.seven_day_annual, rec.daily_return, rec.nav_status,
                         rec.source, rec.ingested_at,
                         share_class_id, rec.nav_date, rec.nav_kind))
                    stats["updated"] += 1
                else:
                    stats["skipped"] += 1
                    stats["skipped_lower_source"] += 1
        return stats

    def list_nav(self, share_class_id: int, *, start: str | None = None,
                 end: str | None = None,
                 nav_kind: str = "net_value") -> list[dict]:
        sql = ("SELECT * FROM fund_nav_daily WHERE share_class_id=? AND nav_kind=?")
        params: list = [share_class_id, nav_kind]
        if start:
            sql += " AND nav_date >= ?"
            params.append(start)
        if end:
            sql += " AND nav_date <= ?"
            params.append(end)
        sql += " ORDER BY nav_date"
        with get_conn(self.db_path) as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def list_nav_by_code(self, share_class_code: str, *, start: str | None = None,
                         end: str | None = None,
                         nav_kind: str = "net_value") -> list[dict]:
        with get_conn(self.db_path) as conn:
            row = conn.execute(
                "SELECT share_class_id FROM fund_share_classes WHERE share_class_code=?",
                (share_class_code,)).fetchone()
        if row is None:
            return []
        return self.list_nav(int(row["share_class_id"]), start=start, end=end,
                             nav_kind=nav_kind)

    def count_nav(self, nav_kind: str | None = None) -> int:
        with get_conn(self.db_path) as conn:
            if nav_kind:
                return conn.execute(
                    "SELECT COUNT(*) FROM fund_nav_daily WHERE nav_kind=?",
                    (nav_kind,)).fetchone()[0]
            return conn.execute("SELECT COUNT(*) FROM fund_nav_daily").fetchone()[0]

    # ------------------------------------------------------------ 分红
    def upsert_dividend_batch(self, share_class_id: int,
                              records: list[DividendRecord]) -> dict:
        """批量写入分红。

        幂等键：(share_class_id, ex_date, source)。
        **不同来源的同一除息日会各留一条**，用于保留差异证据。
        """
        stats = {"inserted": 0, "updated": 0, "skipped": 0}
        if not records:
            return stats
        with get_conn(self.db_path) as conn:
            for rec in records:
                existing = conn.execute(
                    """SELECT dividend_id, cash_per_share, per_10_raw
                       FROM fund_dividends
                       WHERE share_class_id=? AND ex_date=? AND source=?""",
                    (share_class_id, rec.ex_date, rec.source)).fetchone()
                if existing is None:
                    conn.execute(
                        """INSERT INTO fund_dividends
                           (share_class_id, record_date, ex_date, pay_date,
                            cash_per_share, per_10_raw, dividend_type,
                            reinvest_nav, source, source_updated_at, ingested_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (share_class_id, rec.record_date, rec.ex_date, rec.pay_date,
                         rec.cash_per_share, rec.per_10_raw, rec.dividend_type,
                         rec.reinvest_nav, rec.source, rec.source_updated_at,
                         rec.ingested_at))
                    stats["inserted"] += 1
                else:
                    conn.execute(
                        """UPDATE fund_dividends SET
                             record_date=?, pay_date=?, cash_per_share=?,
                             per_10_raw=?, dividend_type=?, reinvest_nav=?,
                             source_updated_at=?, ingested_at=?
                           WHERE dividend_id=?""",
                        (rec.record_date, rec.pay_date, rec.cash_per_share,
                         rec.per_10_raw, rec.dividend_type, rec.reinvest_nav,
                         rec.source_updated_at, rec.ingested_at,
                         int(existing["dividend_id"])))
                    stats["updated"] += 1
        return stats

    def list_dividends(self, share_class_id: int) -> list[dict]:
        with get_conn(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM fund_dividends WHERE share_class_id=? "
                "ORDER BY ex_date", (share_class_id,)).fetchall()
            return [dict(r) for r in rows]

    def list_dividends_by_code(self, share_class_code: str) -> list[dict]:
        with get_conn(self.db_path) as conn:
            row = conn.execute(
                "SELECT share_class_id FROM fund_share_classes WHERE share_class_code=?",
                (share_class_code,)).fetchone()
        if row is None:
            return []
        return self.list_dividends(int(row["share_class_id"]))

    def count_dividends(self) -> int:
        with get_conn(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) FROM fund_dividends").fetchone()[0]
