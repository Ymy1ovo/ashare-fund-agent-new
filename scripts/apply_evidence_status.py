"""把证据等级与公告元数据写回事件表（阶段3A.3.2.1）。

输入：data/ca_ann_match.json（scripts/match_ca_evidence.py 生成）
纪律：
- 只更新证据字段与公告元数据，不改比例、日期、金额。
- unverified 事件保留在库中，但不会被回测应用。
- 每次内容变化产生新版本（由 save_action 处理）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.backtest.corporate_actions import (  # noqa: E402
    ACTION_CASH_DISTRIBUTION,
    EVIDENCE_OFFICIAL,
    EVIDENCE_SECONDARY,
    EVIDENCE_UNVERIFIED,
    STATUS_CONFIRMED,
    STATUS_UNVERIFIED,
    build_action,
    load_actions,
    save_action,
)
from app.database.db import get_connection, init_db  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="回写证据等级")
    parser.add_argument("--match", default="data/ca_ann_match.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    path = PROJECT_ROOT / args.match
    if not path.exists():
        raise SystemExit(f"缺少匹配结果：{path}")
    rows = json.loads(path.read_text(encoding="utf-8"))

    init_db()
    existing = {item.action_id: item for item in load_actions()}
    print(f"库内事件 {len(existing)} 条，匹配结果 {len(rows)} 条")

    updated = skipped = 0
    counter: dict[str, int] = {}
    for row in rows:
        ev = row["event"]
        action_id = int(ev["action_id"])
        current = existing.get(action_id)
        if current is None:
            skipped += 1
            continue

        evidence = row["evidence_status"]
        counter[evidence] = counter.get(evidence, 0) + 1
        ann = row.get("ann") or {}
        parsed = row.get("parsed") or {}

        # 证据等级以本次匹配结果为准：既允许升级也允许降级。
        # 降级是必须的——上一阶段把 166 条全部标成 confirmed，属于过度声称。
        # unverified 时 status 也降级，确保引擎不应用
        status = STATUS_CONFIRMED if evidence in (EVIDENCE_OFFICIAL, EVIDENCE_SECONDARY) \
            else STATUS_UNVERIFIED

        new = build_action(
            action_id=action_id,
            code=current.code,
            action_type=current.action_type,
            ex_date=current.ex_date,
            effective_date=current.effective_date,
            share_ratio=current.share_ratio,
            cash_per_share=current.cash_per_share,
            record_date=current.record_date,
            pay_date=current.pay_date,
            source=ann.get("url") or current.source,
            evidence=current.evidence,
            status=status,
            notes=current.notes,
            evidence_status=evidence,
            announcement_title=ann.get("title"),
            announcement_date=ann.get("publish_date"),
            announcement_url=ann.get("url"),
            manager_name=ann.get("manager"),
        )
        if args.dry_run:
            updated += 1
            continue
        save_action(new, change_reason=f"证据等级回写：{evidence}")
        updated += 1

    print(f"更新 {updated} 条，跳过 {skipped} 条")
    print("证据等级分布：", counter)
    if args.dry_run:
        print("dry-run：未写入")

    with get_connection() as conn:
        for row in conn.execute(
            "SELECT evidence_status, COUNT(*) FROM corporate_actions "
            "GROUP BY evidence_status ORDER BY COUNT(*) DESC"
        ):
            print(f"  库内 {row[0]}: {row[1]}")
        for row in conn.execute(
            "SELECT status, COUNT(*) FROM corporate_actions GROUP BY status"
        ):
            print(f"  status {row[0]}: {row[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
