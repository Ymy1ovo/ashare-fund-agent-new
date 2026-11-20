"""阶段3B-4.2 验收修正：修复多份额基金的主从标记（is_primary）。

问题：`_ensure_share()` 曾用 `is_primary=1` 创建非主份额，
导致同一基金本体出现多个主份额。

修复范围严格受限：
- 只处理 3B-4.2 那 41 个清盘事件涉及的基金本体与份额代码；
- 不动其他既有样本基金（如 3B-4.0 的 12 只存续基金）；
- 用校准 JSON 的 codes_in_event + `_pick_primary_code()` 重算主代码；
- 遇到份额代码已被其他基金本体占用：记录冲突、跳过该条，不静默重连。

幂等：重复执行不改变正确结果。

用法：
    python scripts/fix_3b4_2_primary_flags.py --dry-run
    python scripts/fix_3b4_2_primary_flags.py
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
from app.fund.ingest_3b4_2 import (  # noqa: E402
    CALIBRATION_JSON, _pick_primary_code, load_calibration,
    select_offmarket_events,
)

DB = Path(settings.database_path)
SOURCE = "dfcfw.announcement.calibrated"


def backup(db: Path) -> Path:
    d = db.parent / "backups"
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = d / f"fund_agent_before_primary_fix_{stamp}.db"
    src_c = sqlite3.connect(str(db))
    dst_c = sqlite3.connect(str(dst))
    src_c.backup(dst_c)
    dst_c.close()
    src_c.close()
    return dst


def plan_fixes(conn, calibration: dict) -> tuple[list[dict], list[dict]]:
    """算出每个事件的 (主代码, 全部代码, fund_id)。返回 (修复计划, 冲突)。"""
    off, _ = select_offmarket_events(calibration)
    fixes, conflicts = [], []

    # 只处理本阶段入库的事件涉及的 fund_id
    rows = conn.execute(
        "SELECT DISTINCT fund_id, fund_codes FROM fund_lifecycle_events "
        "WHERE source=?", (SOURCE,)).fetchall()
    allowed_fids = {int(r["fund_id"]) for r in rows}

    for rec in off:
        codes = list(rec.get("codes_in_event") or [])
        primary = _pick_primary_code(codes)
        fund_row = conn.execute(
            "SELECT fund_id FROM fund_share_classes WHERE share_class_code=?",
            (primary,)).fetchone()
        if fund_row is None:
            conflicts.append({"code": primary, "reason": "主代码无对应份额记录",
                              "event_codes": codes})
            continue
        fid = int(fund_row["fund_id"])
        if fid not in allowed_fids:
            conflicts.append({
                "code": primary, "fund_id": fid,
                "reason": "基金本体不在本阶段 41 条清盘事件范围内，跳过"})
            continue

        # 每个代码的实际归属
        for code in codes:
            r = conn.execute(
                "SELECT share_class_id, fund_id FROM fund_share_classes "
                "WHERE share_class_code=?", (code,)).fetchone()
            if r is None:
                conflicts.append({"code": code, "fund_id": fid,
                                  "reason": "份额记录不存在"})
                continue
            if int(r["fund_id"]) != fid:
                conflicts.append({
                    "code": code, "expected_fund_id": fid,
                    "actual_fund_id": int(r["fund_id"]),
                    "reason": "份额已属于其他基金本体，跳过不覆盖"})
                continue
            fixes.append({
                "fund_id": fid,
                "share_class_id": int(r["share_class_id"]),
                "code": code,
                "is_primary": 1 if code == primary else 0,
            })
    return fixes, conflicts


def audit(conn, fids: set[int]) -> dict:
    """审计指定 fund_id 集合的主从关系。"""
    if not fids:
        return {"funds": 0, "primary_ok": 0, "violations": []}
    placeholders = ",".join("?" * len(fids))
    rows = conn.execute(
        f"""SELECT fund_id,
                   SUM(CASE WHEN is_primary=1 THEN 1 ELSE 0 END) AS primaries,
                   COUNT(*) AS total
            FROM fund_share_classes WHERE fund_id IN ({placeholders})
            GROUP BY fund_id""", tuple(fids)).fetchall()
    violations = []
    for r in rows:
        if r["primaries"] != 1:
            violations.append({"fund_id": int(r["fund_id"]),
                               "primaries": int(r["primaries"]),
                               "total": int(r["total"])})
    return {
        "funds": len(rows),
        "shares": sum(int(r["total"]) for r in rows),
        "primary_ok": sum(1 for r in rows if r["primaries"] == 1),
        "primaries": sum(int(r["primaries"]) for r in rows),
        "non_primary": sum(int(r["total"]) - int(r["primaries"]) for r in rows),
        "violations": violations,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", default=str(ROOT / "reports" / "phase3B4_2_primary_fix.json"))
    args = ap.parse_args()

    calib = load_calibration()

    with get_connection(DB) as conn:
        fixes, conflicts = plan_fixes(conn, calib)
        fids = {f["fund_id"] for f in fixes}
        before = audit(conn, fids)

    print(f"计划修复 {len(fixes)} 条份额记录，涉及 {len(fids)} 个基金本体，"
          f"冲突 {len(conflicts)} 条")
    print("修复前审计:", {k: before[k] for k in ("funds", "shares", "primary_ok", "primaries")})

    if args.dry_run:
        print("dry-run，不写库")
        return 0

    bak = backup(DB)
    print("备份 ->", bak)

    changed = 0
    with get_connection(DB) as conn:
        for f in fixes:
            cur = conn.execute(
                "UPDATE fund_share_classes SET is_primary=? "
                "WHERE share_class_id=? AND is_primary<>?",
                (f["is_primary"], f["share_class_id"], f["is_primary"]))
            changed += cur.rowcount

    with get_connection(DB) as conn:
        after = audit(conn, fids)
        # 幂等：再算一次，应为 0 变更
        fixes2, _ = plan_fixes(conn, calib)
        need = sum(1 for f in fixes2 if conn.execute(
            "SELECT is_primary FROM fund_share_classes WHERE share_class_id=?",
            (f["share_class_id"],)).fetchone()[0] != f["is_primary"])
        ic = conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk = len(conn.execute("PRAGMA foreign_key_check").fetchall())
        life = conn.execute(
            "SELECT COUNT(*) FROM fund_lifecycle_events WHERE source=?",
            (SOURCE,)).fetchone()[0]
        fees = conn.execute("SELECT COUNT(*) FROM fund_fee_rules").fetchone()[0]

    payload = {
        "phase": "3B-4.2-primary-fix",
        "baseline_head": "5965ae7f923e5249cce6664605a003fd47678d1f",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "scope": ("只修正 41 个清盘事件涉及基金本体的 is_primary 主从关系；"
                  "不改费率、不改迁移、不改其他基金本体。"),
        "planned_share_updates": len(fixes),
        "affected_fund_ids": sorted(fids),
        "conflicts": conflicts,
        "before": before,
        "after": after,
        "rows_changed": changed,
        "idempotent_remaining_updates": need,
        "lifecycle_count": life,
        "fee_rules_count": fees,
        "integrity_check": ic,
        "foreign_key_violations": fk,
        "backup": {"path": str(bak), "size_bytes": bak.stat().st_size},
    }
    out = Path(args.json)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"JSON -> {out}")
    print("修复后审计:", {k: after[k] for k in ("funds", "shares", "primary_ok", "primaries")})
    print("变更行数:", changed, "| 幂等剩余:", need)
    print("integrity:", ic, "| fk:", fk, "| lifecycle:", life, "| fees:", fees)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
