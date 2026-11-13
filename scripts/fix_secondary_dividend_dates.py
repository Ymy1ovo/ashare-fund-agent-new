"""修复 5 条 secondary 分红事件的登记日/发放日（阶段3A.3.2.2.1）。

背景：
这些事件的公告是「（场内）...（场外）」双日期排版，解析器只取第一个日期列，
旧逻辑在匹配失败时把 record_date 默认写成 ex_date、pay_date 默认写成 T+1，
所以库内日期与公告原文不一致。

本脚本：
1. 从公告原文重新解析，取**场内**列（ETF 是场内品种）；
2. 核对 ex_date、cash_per_share 与库内一致；
3. 修正 record_date / pay_date；
4. 记录证据来源（公告 art_code / URL / 原文片段）。

只改日期字段，不改比例、金额、证据等级；走 save_action 版本化，旧版本保留。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.backtest.corporate_actions import (  # noqa: E402
    ACTION_CASH_DISTRIBUTION,
    build_action,
    load_actions,
    save_action,
)
from app.database.db import init_db  # noqa: E402

INSIDE = ("2021-01-04", "2026-11-09")


def main() -> int:
    parser = argparse.ArgumentParser(description="修复 secondary 分红日期")
    parser.add_argument("--db", default="data/fund_agent.db")
    parser.add_argument("--ann", default="data/ca_announcements.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = PROJECT_ROOT / args.db
    ann = json.loads((PROJECT_ROOT / args.ann).read_text(encoding="utf-8"))
    init_db(db)

    actions = {a.action_id: a for a in load_actions(db_path=db)}
    target = [a for a in actions.values()
              if a.action_type == ACTION_CASH_DISTRIBUTION
              and a.evidence_status == "secondary_confirmed"
              and INSIDE[0] <= a.ex_date.isoformat() <= INSIDE[1]]

    print(f"区间内 secondary 分红 {len(target)} 条")
    fixed = 0
    for action in sorted(target, key=lambda a: a.ex_date):
        art = (action.announcement_url or "").split(",")[-1].replace(".html", "")
        hit = next((a for a in ann.get(action.code, []) if a.get("art_code") == art), None)
        if hit is None:
            print(f"  {action.action_id} {action.code} 无公告对象，跳过")
            continue
        parsed = hit.get("parsed") or {}
        rec = parsed.get("record_date")
        pay = parsed.get("pay_date")
        amount = parsed.get("cash_per_share")
        problems = []
        if parsed.get("ex_date") != action.ex_date.isoformat():
            problems.append(f"除息日不符 公告{parsed.get('ex_date')} 库{action.ex_date}")
        if amount is not None and action.cash_per_share is not None:
            if abs(amount - action.cash_per_share) > 1e-6:
                problems.append(f"金额不符 公告{amount} 库{action.cash_per_share}")
        if not rec or not pay:
            problems.append("公告缺登记日或发放日")
        print(f"  {action.action_id} {action.code} ex={action.ex_date} "
              f"库 rec={action.record_date} pay={action.pay_date} "
              f"→ 公告 rec={rec} pay={pay}")
        if problems:
            print(f"    无法核证：{problems}")
            continue
        if action.record_date and action.record_date.isoformat() == rec \
                and action.pay_date and action.pay_date.isoformat() == pay:
            print("    已一致，无需修改")
            continue
        if args.dry_run:
            print("    dry-run：将修正")
            fixed += 1
            continue

        evidence = (
            f"{hit.get('title', '')}；公告 {hit.get('publish_date')}；"
            f"权益登记日 {rec}（场内）、现金红利发放日 {pay}（场内）；"
            f"art_code={art}"
        )
        save_action(
            build_action(
                action_id=action.action_id, code=action.code,
                action_type=action.action_type, ex_date=action.ex_date,
                effective_date=action.effective_date,
                share_ratio=action.share_ratio,
                cash_per_share=action.cash_per_share,
                record_date=rec, pay_date=pay,
                source=action.source, evidence=evidence, status=action.status,
                notes=action.notes, evidence_status=action.evidence_status,
                announcement_title=action.announcement_title,
                announcement_date=action.announcement_date,
                announcement_url=action.announcement_url,
                manager_name=action.manager_name,
                fractional_policy=action.fractional_policy,
            ),
            change_reason=f"登记日/发放日按公告场内列修正：{rec}/{pay}",
            db_path=db,
        )
        fixed += 1
        print("    已修正")

    print(f"\n修正 {fixed} 条")

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        print("\n=== 修正后核对 ===")
        for row in conn.execute(
            "SELECT action_id, code, ex_date, record_date, pay_date FROM corporate_actions "
            "WHERE evidence_status='secondary_confirmed' "
            "AND action_type='cash_distribution' ORDER BY ex_date"
        ):
            print(f"  {row['action_id']:4d} {row['code']:7s} ex={row['ex_date']} "
                  f"rec={row['record_date']} pay={row['pay_date']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
