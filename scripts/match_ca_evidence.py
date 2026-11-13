"""把事件与官方公告逐条匹配并分级（阶段3A.3.2.1）。

输入：data/ca_announcements.json（scripts/fetch_ca_announcements.py 生成）
输出：data/ca_ann_match.json

分级规则：
- official_confirmed：能定位到基金管理人公告原文（独立公告 ID + 正文），
  且正文可核对出与数据库一致的除息日/比例/金额等关键要素。
- secondary_confirmed：有公告原文，但部分要素无法从正文核对
  （如早期公告只写除息日、金额在表格里被拍平），
  且至少有一项关键要素（比例/金额/除息日）一致。
- unverified：找不到公告，或公告正文无法核对任何关键要素。
- 只有 official_confirmed 与 secondary_confirmed 可进入回测；
  official 与 secondary 在报告里必须分开统计。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.backtest.corporate_actions import (  # noqa: E402
    EVIDENCE_OFFICIAL,
    EVIDENCE_SECONDARY,
    EVIDENCE_UNVERIFIED,
)
from app.database.db import get_connection  # noqa: E402

MIN_OFFICIAL_SCORE = 10


def _gap(a: str | None, b: str | None) -> int:
    if not a or not b:
        return 999
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)


def _ratio_ok(a, b, rel: float = 0.006) -> bool:
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= max(rel * abs(float(b)), 1e-9)


def score_event(event: dict, announcement: dict) -> tuple[int, dict]:
    """给一条候选公告打分，并返回核对明细。"""
    parsed = announcement.get("parsed") or {}
    checks: dict[str, bool] = {}
    score = 0
    is_cash = event["action_type"] == "cash_distribution"

    if is_cash:
        if announcement["kind"] != "dividend":
            return -1, {}
        if parsed.get("ex_date") == event["ex_date"]:
            score += 5
            checks["ex_date"] = True
        elif _gap(parsed.get("ex_date"), event["ex_date"]) <= 2:
            score += 2
            checks["ex_date"] = False
        else:
            checks["ex_date"] = False
        if parsed.get("record_date") == event["record_date"]:
            score += 2
            checks["record_date"] = True
        else:
            checks["record_date"] = False
        if parsed.get("pay_date") == event["pay_date"]:
            score += 2
            checks["pay_date"] = True
        else:
            checks["pay_date"] = False
        if _ratio_ok(parsed.get("cash_per_share"), event["cash_per_share"]):
            score += 5
            checks["amount"] = True
        else:
            checks["amount"] = False
    else:
        if announcement["kind"] != "split":
            return -1, {}
        if _ratio_ok(parsed.get("share_ratio"), event["share_ratio"]):
            score += 7
            checks["ratio"] = True
        else:
            checks["ratio"] = False
        hit = any(parsed.get(f) and parsed[f] in (event["ex_date"], event["record_date"])
                  for f in ("ex_date", "record_date"))
        checks["date"] = hit
        if hit:
            score += 3

    if _gap(announcement.get("publish_date"), event["ex_date"]) <= 20:
        score += 1
    return score, checks


def classify(event: dict, pool: list[dict]) -> dict:
    best = None
    best_score = -1
    best_checks: dict = {}
    for announcement in pool:
        score, checks = score_event(event, announcement)
        if score > best_score:
            best, best_score, best_checks = announcement, score, checks
    if best is None or best_score < 4:
        return {"ann": None, "parsed": {}, "score": best_score,
                "checks": best_checks, "evidence_status": EVIDENCE_UNVERIFIED}

    matched_keys = sum(1 for value in best_checks.values() if value)
    if best_score >= MIN_OFFICIAL_SCORE and matched_keys >= 2:
        status = EVIDENCE_OFFICIAL
    elif matched_keys >= 1:
        status = EVIDENCE_SECONDARY
    else:
        status = EVIDENCE_UNVERIFIED
    return {"ann": best, "parsed": best.get("parsed") or {}, "score": best_score,
            "checks": best_checks, "evidence_status": status}


def main() -> int:
    parser = argparse.ArgumentParser(description="事件与公告匹配并分级")
    parser.add_argument("--ann", default="data/ca_announcements.json")
    parser.add_argument("--db", default="data/fund_agent.db")
    parser.add_argument("--out", default="data/ca_ann_match.json")
    args = parser.parse_args()

    ann_path = PROJECT_ROOT / args.ann
    if not ann_path.exists():
        raise SystemExit(f"缺少公告数据：{ann_path}")
    announcements = json.loads(ann_path.read_text(encoding="utf-8"))

    db = PROJECT_ROOT / args.db
    with get_connection(db) as conn:
        conn.row_factory = sqlite3.Row
        events = [dict(row) for row in conn.execute(
            "SELECT * FROM corporate_actions ORDER BY code, ex_date")]

    rows = []
    for event in events:
        pool = announcements.get(event["code"], [])
        result = classify(event, pool)
        rows.append({"event": event, **result})

    from collections import Counter
    counter = Counter(row["evidence_status"] for row in rows)
    print(f"事件 {len(rows)} 条：{dict(counter)}")

    out = PROJECT_ROOT / args.out
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=str),
                   encoding="utf-8")
    print(f"已保存 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
