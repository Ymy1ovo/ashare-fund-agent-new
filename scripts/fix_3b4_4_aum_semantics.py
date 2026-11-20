"""阶段3B-4.4 验收修正：修正规模记录的日期语义元数据（幂等）。

背景：原导入把 675 条规模记录的 detail 写成
`report_date_is_period_end = true`，但平台日期里有 2013-03-15、
2010-08-23 这类周频/月频非季末日期，缺乏证据支持「报告期末」结论。

本脚本只改 detail 元数据，**不动** report_date / aum_total /
shares_total / source / evidence_level。

用法：
    python scripts/fix_3b4_4_aum_semantics.py --dry-run
    python scripts/fix_3b4_4_aum_semantics.py
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database.db import get_connection, settings  # noqa: E402
from app.fund.ingest_3b4_4 import DATE_SEMANTICS, DISCLAIMER_AUM  # noqa: E402

DB = Path(settings.database_path)


def backup(db: Path) -> Path:
    d = db.parent / "backups"
    d.mkdir(parents=True, exist_ok=True)
    dst = d / f"fund_agent_before_aum_meta_fix_{datetime.now():%Y%m%d_%H%M%S}.db"
    s = sqlite3.connect(str(db)); t = sqlite3.connect(str(dst))
    s.backup(t); t.close(); s.close()
    return dst


def new_detail() -> str:
    return json.dumps({
        "date_semantics": DATE_SEMANTICS,
        "period_end_verified": False,
        "publication_date_verified": False,
        "point_in_time_usable": False,
        "disclosed_at_null_reason": "公告发布日期与实际公开可见时间均未取得",
        "not_publication_date": True,
        "disclaimer": DISCLAIMER_AUM,
    }, ensure_ascii=False)


def fingerprint(conn) -> dict:
    """业务数据指纹：只覆盖本次不应改动的字段。"""
    rows = conn.execute(
        """SELECT aum_id, report_date, aum_total, shares_total, source,
                  evidence_level, disclosed_at
           FROM fund_aum_history ORDER BY aum_id""").fetchall()
    return {"count": len(rows),
            "hash": hash(tuple(tuple(r) for r in rows)),
            "rows": [tuple(r) for r in rows]}


def stale_detail_count(conn) -> int:
    return conn.execute(
        """SELECT COUNT(*) FROM fund_aum_history
           WHERE detail LIKE '%report_date_is_period_end%'""").fetchone()[0]


def needs_fix_count(conn) -> int:
    """只统计有证据等级的记录——原有 8 条无证据快照不属于本次修正范围。"""
    return conn.execute(
        """SELECT COUNT(*) FROM fund_aum_history
           WHERE evidence_level IS NOT NULL
             AND (detail IS NULL
                  OR detail NOT LIKE '%point_in_time_usable%'
                  OR detail LIKE '%report_date_is_period_end%')""").fetchone()[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", default=str(ROOT / "reports"
                                          / "phase3B4_4_aum_semantics_fix.json"))
    args = ap.parse_args()

    with get_connection(DB) as conn:
        before = fingerprint(conn)
        stale = stale_detail_count(conn)
        need = needs_fix_count(conn)
        with_level = conn.execute(
            "SELECT COUNT(*) FROM fund_aum_history WHERE evidence_level IS NOT NULL"
        ).fetchone()[0]

    print(f"规模记录 {before['count']} 条，其中有证据 {with_level} 条")
    print(f"含旧语义 report_date_is_period_end 的记录：{stale} 条")
    print(f"需要修正的记录：{need} 条")

    if args.dry_run:
        print("dry-run，不写库")
        return 0

    bak = backup(DB)
    print("备份 ->", bak, bak.stat().st_size)

    detail = new_detail()
    with get_connection(DB) as conn:
        # 只对已有证据等级的记录改语义；原有 8 条无证据快照不动
        cur = conn.execute(
            """UPDATE fund_aum_history SET detail=?
               WHERE evidence_level IS NOT NULL
                 AND (detail IS NULL
                      OR detail NOT LIKE '%point_in_time_usable%'
                      OR detail LIKE '%report_date_is_period_end%')""",
            (detail,))
        changed = cur.rowcount
        after = fingerprint(conn)
        still_stale = stale_detail_count(conn)
        still_need = needs_fix_count(conn)
        ic = conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk = len(conn.execute("PRAGMA foreign_key_check").fetchall())

    # 逐行一致性：只比业务字段
    same_business = before["rows"] == after["rows"]

    payload = {
        "phase": "3B-4.4-aum-semantics-fix",
        "baseline_head": "3307a9befe64cba925f9f258491c10049115767e",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "scope": ("只修正规模记录的 detail 日期语义元数据；"
                  "不改 report_date / aum_total / shares_total / source / evidence_level。"),
        "records_total": before["count"],
        "records_with_evidence": with_level,
        "stale_detail_before": stale,
        "needs_fix_before": need,
        "rows_changed": changed,
        "stale_detail_after": still_stale,
        "needs_fix_after": still_need,
        "business_fields_unchanged": same_business,
        "date_semantics": DATE_SEMANTICS,
        "period_end_verified": False,
        "publication_date_verified": False,
        "point_in_time_usable": False,
        "disclosed_at_all_null": conn.execute(
            "SELECT COUNT(*) FROM fund_aum_history WHERE disclosed_at IS NOT NULL"
        ).fetchone()[0] == 0 if False else None,
        "integrity_check": ic,
        "foreign_key_violations": fk,
        "backup": {"path": str(bak), "size_bytes": bak.stat().st_size},
    }

    # disclosed_at 是否全 NULL（单独查，避免上面三元表达式歧义）
    with get_connection(DB) as conn:
        non_null = conn.execute(
            "SELECT COUNT(*) FROM fund_aum_history WHERE disclosed_at IS NOT NULL"
        ).fetchone()[0]
    payload["disclosed_at_all_null"] = (non_null == 0)
    payload["disclosed_at_non_null_count"] = non_null

    Path(args.json).write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print("JSON ->", args.json)
    print(f"变更 {changed} 条；业务字段一致: {same_business}")
    print(f"残留旧语义 {still_stale} 条；待修正 {still_need} 条")
    print("integrity:", ic, "| fk:", fk)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
