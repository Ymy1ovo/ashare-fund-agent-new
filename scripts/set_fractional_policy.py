"""按官方公告回写零碎份额处置口径（阶段3A.3.2.2）。

纪律：
- 只判定口径，不改比例、日期、金额。
- 公告明确「上进位」→ round_up；「尾差计入基金财产/舍去」→ truncate；
  「现金补偿」→ cash_compensation。
- 公告未明说的一律 truncate（不虚构现金收入）。
- 判定不出的保持默认，并在报告中列出。
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.backtest.corporate_actions import (  # noqa: E402
    DEFAULT_FRACTION_POLICY,
    FRACTION_CASH_COMPENSATION,
    FRACTION_ROUND_UP,
    FRACTION_TRUNCATE,
    FRACTION_UNKNOWN,
    build_action,
    load_actions,
    save_action,
)
from app.database.db import get_connection, init_db  # noqa: E402

ROUND_UP_PATTERNS = ("上进位", "进位为 1 份", "进位为1份", "均进位", "进位处理")
TRUNCATE_PATTERNS = ("尾差计入基金", "小数部分舍去", "舍去部分计入基金", "舍去方式", "舍去")
CASH_PATTERNS = ("现金补偿", "以现金方式补偿", "折为现金", "现金支付")


def classify(text: str) -> tuple[str, str]:
    """从公告正文判定零碎份额处置口径。"""
    if not text:
        return FRACTION_UNKNOWN, "无公告正文"
    if any(p in text for p in CASH_PATTERNS):
        return FRACTION_CASH_COMPENSATION, "公告明示现金补偿"
    if any(p in text for p in ROUND_UP_PATTERNS):
        return FRACTION_ROUND_UP, "公告明示进位"
    if any(p in text for p in TRUNCATE_PATTERNS):
        return FRACTION_TRUNCATE, "公告明示舍去/尾差入基金"
    # 公告正文没有载明零碎份额处置方式：只能记 unknown，
    # 绝不能把「没有证据」包装成「默认按舍去处理」
    return FRACTION_UNKNOWN, "公告未载明零碎处置方式"


def main() -> int:
    parser = argparse.ArgumentParser(description="回写零碎份额处置口径")
    parser.add_argument("--ann", default="data/ca_announcements.json")
    parser.add_argument("--db", default="data/fund_agent.db")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    ann_path = PROJECT_ROOT / args.ann
    announcements = {}
    if ann_path.exists():
        announcements = json.loads(ann_path.read_text(encoding="utf-8"))

    init_db(PROJECT_ROOT / args.db)
    existing = {item.action_id: item for item in load_actions(db_path=PROJECT_ROOT / args.db)}
    print(f"库内事件 {len(existing)} 条")

    decided: dict[str, int] = {}
    skipped = 0
    changed = 0
    reasons: dict[str, list[int]] = {}
    for action_id, action in sorted(existing.items()):
        if not action.is_share_adjustment:
            continue
        # 找该事件对应的拆分/合并公告正文
        text = ""
        for a in announcements.get(action.code, []):
            if a["kind"] != "split":
                continue
            parsed = a.get("parsed") or {}
            if parsed.get("share_ratio") and action.share_ratio:
                if abs(parsed["share_ratio"] - action.share_ratio) / action.share_ratio < 0.01:
                    text = a.get("text_full", "")
                    break
        policy, reason = classify(text)
        decided[policy] = decided.get(policy, 0) + 1
        reasons.setdefault(reason, []).append(action_id)
        if policy == action.fractional_policy:
            skipped += 1
            continue
        if args.dry_run:
            changed += 1
            continue
        save_action(
            build_action(
                action_id=action.action_id,
                code=action.code,
                action_type=action.action_type,
                ex_date=action.ex_date,
                effective_date=action.effective_date,
                share_ratio=action.share_ratio,
                cash_per_share=action.cash_per_share,
                record_date=action.record_date,
                pay_date=action.pay_date,
                source=action.source,
                evidence=action.evidence,
                status=action.status,
                notes=action.notes,
                evidence_status=action.evidence_status,
                announcement_title=action.announcement_title,
                announcement_date=action.announcement_date,
                announcement_url=action.announcement_url,
                manager_name=action.manager_name,
                fractional_policy=policy,
            ),
            change_reason=f"零碎份额口径判定：{reason}",
            db_path=PROJECT_ROOT / args.db,
        )
        changed += 1

    print(f"判定结果：{decided}")
    print(f"更新 {changed} 条，未变 {skipped} 条")
    for reason, ids in reasons.items():
        print(f"  {reason}: {len(ids)} 条")
    if args.dry_run:
        print("dry-run：未写入")

    with get_connection(PROJECT_ROOT / args.db) as conn:
        for row in conn.execute(
            "SELECT fractional_policy, COUNT(*) FROM corporate_actions "
            "WHERE action_type IN ('split','reverse_split') GROUP BY fractional_policy"
        ):
            print(f"  库内 {row[0]}: {row[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
