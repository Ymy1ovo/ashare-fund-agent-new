"""阶段3B-4.4 数据缺口补强：把已核验证据写入正式库（幂等）。

用法：
    python scripts/ingest_3b4_4.py --dry-run
    python scripts/ingest_3b4_4.py
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database.db import get_connection, settings  # noqa: E402
from app.fund.ingest_3b4_4 import run_all  # noqa: E402
from app.fund.migration_3b4_4 import current_schema  # noqa: E402

DB = Path(settings.database_path)

TABLES = ("fund_master", "fund_share_classes", "fund_nav_daily", "fund_dividends",
          "fund_manager_history", "fund_aum_history", "fund_fee_rules",
          "fund_subscription_status", "fund_lifecycle_events", "fund_data_quality")
ETF_TABLES = ("etf_pool", "etf_daily_prices", "backtest_runs", "validation_runs",
              "corporate_actions")


def snapshot(db: Path) -> dict:
    out = {}
    with get_connection(db) as conn:
        for t in TABLES + ETF_TABLES:
            try:
                out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except sqlite3.Error:
                out[t] = None
    return out


def backup(db: Path) -> Path:
    d = db.parent / "backups"
    d.mkdir(parents=True, exist_ok=True)
    dst = d / f"fund_agent_before_ingest_3b4_4_{datetime.now():%Y%m%d_%H%M%S}.db"
    s = sqlite3.connect(str(db)); t = sqlite3.connect(str(dst))
    s.backup(t); t.close(); s.close()
    return dst


def stats(db: Path) -> dict:
    with get_connection(db) as conn:
        def one(sql, *a):
            return conn.execute(sql, a).fetchone()[0]
        return {
            "fee_with_effective_from": one(
                "SELECT COUNT(*) FROM fund_fee_rules WHERE effective_from IS NOT NULL"),
            "fee_without_effective_from": one(
                "SELECT COUNT(*) FROM fund_fee_rules WHERE effective_from IS NULL"),
            "fee_by_level": {r[0]: r[1] for r in conn.execute(
                "SELECT evidence_level, COUNT(*) FROM fund_fee_rules GROUP BY 1")},
            "fee_with_announcement": one(
                "SELECT COUNT(*) FROM fund_fee_rules WHERE announcement_id IS NOT NULL"),
            "fee_conflicts": one(
                "SELECT COUNT(*) FROM fund_fee_rules r WHERE r.effective_from IS NOT NULL "
                "AND r.detail LIKE '%rate_before%' AND r.rate_original IS NOT NULL "
                "AND r.detail NOT LIKE '%rate_after%'"),
            "manager_total": one("SELECT COUNT(*) FROM fund_manager_history"),
            "manager_with_dates": one(
                "SELECT COUNT(*) FROM fund_manager_history WHERE start_date IS NOT NULL"),
            "manager_null_dates": one(
                "SELECT COUNT(*) FROM fund_manager_history WHERE start_date IS NULL"),
            "manager_by_level": {r[0]: r[1] for r in conn.execute(
                "SELECT COALESCE(evidence_level,'(null)'), COUNT(*) "
                "FROM fund_manager_history GROUP BY 1")},
            "aum_total": one("SELECT COUNT(*) FROM fund_aum_history"),
            "aum_distinct_report_dates": one(
                "SELECT COUNT(DISTINCT report_date) FROM fund_aum_history"),
            "aum_by_level": {r[0]: r[1] for r in conn.execute(
                "SELECT COALESCE(evidence_level,'(null)'), COUNT(*) "
                "FROM fund_aum_history GROUP BY 1")},
            "aum_funds_multi_period": one(
                "SELECT COUNT(*) FROM (SELECT fund_id FROM fund_aum_history "
                "GROUP BY fund_id HAVING COUNT(DISTINCT report_date) > 1)"),
        }


def integrity(db: Path) -> dict:
    with get_connection(db) as conn:
        return {
            "integrity_check": conn.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", default=str(ROOT / "reports" / "phase3B4_4_data_gap_research.json"))
    args = ap.parse_args()

    before = snapshot(DB)
    if args.dry_run:
        print("dry-run，不写库；当前行数:", json.dumps(before, ensure_ascii=False))
        return 0

    bak = backup(DB)
    print("备份 ->", bak, bak.stat().st_size)

    run1 = run_all(DB)
    after1 = snapshot(DB)
    run2 = run_all(DB)
    after2 = snapshot(DB)

    st = stats(DB)
    integ = integrity(DB)

    payload = {
        "phase": "3B-4.4",
        "baseline_head": "2294b4aa8f79dcb921c5fa00b1d2e12548477072",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "run1": {k: v for k, v in run1.items() if k != "migration_added"},
        "migration_added": run1["migration_added"],
        "schema": {t: current_schema(DB)[t]["indexes"] for t in current_schema(DB)},
        "run2_idempotent": {
            "fee_effective": run2["fee_effective"],
            "manager": run2["manager"],
            "aum": run2["aum"],
        },
        "counts_before": before,
        "counts_after_run1": after1,
        "counts_after_run2": after2,
        "idempotent": after1 == after2,
        "db_stats": st,
        "integrity": integ,
        "backup": {"path": str(bak), "size_bytes": bak.stat().st_size},
    }
    Path(args.json).write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print("JSON ->", args.json)
    print("幂等:", payload["idempotent"])
    print("统计:", json.dumps(st, ensure_ascii=False))
    print("完整性:", integ)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
