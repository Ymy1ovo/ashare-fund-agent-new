"""阶段3B-4.2 正式入库脚本：清盘事件 + 费率阶梯。

用法：
    python scripts/ingest_3b4_2.py            # 导入（幂等，可重复跑）
    python scripts/ingest_3b4_2.py --dry-run  # 只统计计划量，不写库
    python scripts/ingest_3b4_2.py --json reports/phase3B4_2_data_ingestion.json

严格只读数据源：
  reports/phase3B4_1_1_types_evidence_calibration.json（清盘事件，权威）
  reports/phase3B4_1_1_historical_roster_fee_audit.json（费率阶梯）
不重新采集任何网络数据。
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
from app.fund.ingest_3b4_2 import (  # noqa: E402
    CALIBRATION_JSON, DISCLAIMER, ONSHORE_ETF_CODES, load_calibration,
    load_fee_audit, run_all, select_offmarket_events,
)
from app.fund.migration_3b4_2 import current_schema  # noqa: E402

DB = Path(settings.database_path)

FUND_TABLES = (
    "fund_master", "fund_share_classes", "fund_nav_daily", "fund_dividends",
    "fund_manager_history", "fund_aum_history", "fund_fee_rules",
    "fund_subscription_status", "fund_lifecycle_events", "fund_data_quality",
)
ETF_TABLES = (
    "etf_pool", "etf_daily_prices", "etf_indicator_daily",
    "backtest_runs", "backtest_orders", "backtest_trades",
    "validation_runs", "validation_grid", "validation_windows",
    "validation_backtest_runs", "corporate_actions",
    "corporate_action_applications", "dividend_receivables",
)


def snapshot(db: Path) -> dict:
    """数一遍关键表行数。"""
    out = {}
    with get_connection(db) as conn:
        for t in FUND_TABLES + ETF_TABLES:
            try:
                out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except sqlite3.Error:
                out[t] = None
    return out


def backup(db: Path) -> Path:
    d = db.parent / "backups"
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = d / f"fund_agent_before_ingest_3b4_2_{stamp}.db"
    src_c = sqlite3.connect(str(db))
    dst_c = sqlite3.connect(str(dst))
    src_c.backup(dst_c)
    dst_c.close()
    src_c.close()
    return dst


def integrity(db: Path) -> dict:
    with get_connection(db) as conn:
        ic = conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        return {"integrity_check": ic,
                "foreign_key_violations": len(fk),
                "foreign_key_samples": [tuple(r) for r in fk[:5]]}


def fee_breakdown(db: Path) -> dict:
    with get_connection(db) as conn:
        rows = conn.execute(
            "SELECT fee_type, COUNT(*) FROM fund_fee_rules GROUP BY fee_type").fetchall()
        by_type = {r[0]: r[1] for r in rows}
        total = conn.execute("SELECT COUNT(*) FROM fund_fee_rules").fetchone()[0]
        null_rate = conn.execute(
            "SELECT COUNT(*) FROM fund_fee_rules WHERE rate_original IS NULL").fetchone()[0]
        null_eff = conn.execute(
            "SELECT COUNT(*) FROM fund_fee_rules WHERE effective_from IS NULL").fetchone()[0]
        with_platform = conn.execute(
            "SELECT COUNT(*) FROM fund_fee_rules WHERE rate_platform IS NOT NULL").fetchone()[0]
        inferred = conn.execute(
            "SELECT COUNT(*) FROM fund_fee_rules WHERE holding_days_min_inferred=1 "
            "OR lower_inferred=1").fetchone()[0]
        annual = conn.execute(
            "SELECT COUNT(*) FROM fund_fee_rules WHERE is_annual=1").fetchone()[0]
        basis_null = conn.execute(
            "SELECT COUNT(*) FROM fund_fee_rules WHERE holding_days_basis IS NULL"
        ).fetchone()[0]
    return {"total": total, "by_type": by_type, "rate_null": null_rate,
            "effective_from_null": null_eff, "with_platform_rate": with_platform,
            "inferred_lower_bound": inferred, "annual_rows": annual,
            "holding_days_basis_null": basis_null}


def lifecycle_breakdown(db: Path) -> dict:
    with get_connection(db) as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM fund_lifecycle_events "
            "WHERE event_type='terminated' AND source='dfcfw.announcement.calibrated'"
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT product_structure, COUNT(*) FROM fund_lifecycle_events "
            "WHERE source='dfcfw.announcement.calibrated' "
            "GROUP BY product_structure").fetchall()
        by_struct = {r[0]: r[1] for r in rows}
        b_level = conn.execute(
            "SELECT COUNT(*) FROM fund_lifecycle_events "
            "WHERE source='dfcfw.announcement.calibrated' AND evidence_level='B'"
        ).fetchone()[0]
        null_date = conn.execute(
            "SELECT COUNT(*) FROM fund_lifecycle_events "
            "WHERE source='dfcfw.announcement.calibrated' AND event_date IS NULL"
        ).fetchone()[0]
        with_url = conn.execute(
            "SELECT COUNT(*) FROM fund_lifecycle_events "
            "WHERE source='dfcfw.announcement.calibrated' "
            "AND announcement_url IS NOT NULL AND announcement_id IS NOT NULL"
        ).fetchone()[0]
        etf_leak = conn.execute(
            "SELECT COUNT(*) FROM fund_lifecycle_events "
            "WHERE fund_codes LIKE '%511000%' OR fund_codes LIKE '%511050%'"
        ).fetchone()[0]
        has_disclaimer = conn.execute(
            "SELECT COUNT(*) FROM fund_lifecycle_events "
            "WHERE source='dfcfw.announcement.calibrated' AND detail LIKE ?",
            (f"%{DISCLAIMER[:20]}%",)).fetchone()[0]
    return {"total": total, "by_structure": by_struct, "evidence_b": b_level,
            "event_date_null": null_date, "with_url_and_id": with_url,
            "onshore_etf_leaked": etf_leak, "with_disclaimer": has_disclaimer}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    calib = load_calibration()
    fee_audit = load_fee_audit()
    off, excluded = select_offmarket_events(calib)

    plan = {
        "lifecycle_planned": len(off),
        "lifecycle_excluded_etf": len(excluded),
        "lifecycle_excluded_codes": [c for r in excluded
                                     for c in (r.get("codes_in_event") or [])],
        "fee_samples": len(fee_audit.get("samples") or []),
        "fee_rows_planned": sum(
            (3 if (s.get("annual_fees") or {}) else 0)
            + len(s.get("purchase_tiers") or [])
            + len(s.get("redeem_tiers") or [])
            for s in (fee_audit.get("samples") or [])),
    }
    print("计划:", json.dumps(plan, ensure_ascii=False))

    if args.dry_run:
        print("dry-run，不写库")
        return 0

    before = snapshot(DB)
    bak = backup(DB)
    print("备份 ->", bak)

    result = run_all(DB)

    after1 = snapshot(DB)
    # 第二次导入验证幂等
    result2 = run_all(DB)
    after2 = snapshot(DB)

    integ = integrity(DB)
    life = lifecycle_breakdown(DB)
    fees = fee_breakdown(DB)
    schema = current_schema(DB)

    # 支付宝状态未被改动
    with get_connection(DB) as conn:
        alipay = conn.execute(
            "SELECT alipay_purchasable, COUNT(*) FROM fund_subscription_status "
            "GROUP BY alipay_purchasable").fetchall()
    alipay_map = {r[0]: r[1] for r in alipay}

    payload = {
        "phase": "3B-4.2",
        "baseline_head": "e90a2b38f851c5cf79ddbd5f6dc4240bdf45c426",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "scope": ("只把 3B-4.1.1 已审计的清盘事件与费率阶梯正式入库；"
                  "未重新采集、未开始回测、未开发策略。"),
        "plan": plan,
        "migration": {
            "file": "migrations/phase3b4_2_lifecycle_fee_ingestion.sql",
            "added_columns": result["migration_added"],
            "schema": schema,
        },
        "run1": result,
        "run2_idempotent": result2,
        "counts_before": before,
        "counts_after_run1": after1,
        "counts_after_run2": after2,
        "idempotent": after1 == after2,
        "integrity": integ,
        "lifecycle": life,
        "fees": fees,
        "alipay_status": {
            "distribution": alipay_map,
            "all_unknown": set(alipay_map) <= {"unknown"},
        },
        "backup": {"path": str(bak), "size_bytes": bak.stat().st_size},
        "excluded_onshore_etf": ONSHORE_ETF_CODES,
        "source_declaration": DISCLAIMER,
        "data_sources": {
            "lifecycle": str(CALIBRATION_JSON.relative_to(ROOT)),
            "fees": "reports/phase3B4_1_1_historical_roster_fee_audit.json#fee_audit",
        },
    }

    out = Path(args.json) if args.json else ROOT / "reports" / "phase3B4_2_data_ingestion.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"JSON -> {out}")
    print("幂等:", payload["idempotent"])
    print("生命周期:", life)
    print("费率:", fees)
    print("完整性:", integ["integrity_check"], "外键违规:", integ["foreign_key_violations"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
