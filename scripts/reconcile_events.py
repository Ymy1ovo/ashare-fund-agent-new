"""事件数量全量对账（阶段3A.3.2.1）。

输出即 reports/phase3A3_2_1_event_reconciliation.md 的全部表格，
每一类都能从原始抓取记录与数据库查询重新计算。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

IS_START, IS_END = "2021-01-04", "2024-12-31"
OOS_START, OOS_END = "2025-01-02", "2026-11-09"
TYPES = ("split", "reverse_split", "cash_distribution", "other")
EVIDENCE = ("official_confirmed", "secondary_confirmed", "unverified", "rejected")


def main() -> int:
    parser = argparse.ArgumentParser(description="事件数量对账")
    parser.add_argument("--db", default="data/fund_agent.db")
    parser.add_argument("--raw", default="data/corporate_action_all46.json")
    args = parser.parse_args()

    db = PROJECT_ROOT / args.db
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    checks: list[tuple[str, bool, str]] = []

    # 1. 原始抓取
    raw_path = PROJECT_ROOT / args.raw
    raw_splits = raw_divs = 0
    if raw_path.exists():
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        for value in raw.values():
            if "error" in value:
                continue
            raw_splits += len(value.get("splits", []))
            raw_divs += len(value.get("dividends", []))
    print(f"1. 原始抓取记录总数: {raw_splits + raw_divs} "
          f"(拆分 {raw_splits} + 分红 {raw_divs})")

    # 2. 去重后
    total = conn.execute("SELECT COUNT(*) FROM corporate_actions").fetchone()[0]
    print(f"2. 去重后事件总数: {total}")
    if raw_path.exists():
        checks.append(("原始抓取 == 去重后", raw_splits + raw_divs == total,
                       f"{raw_splits + raw_divs} vs {total}"))

    # 3-6. 区间
    in_win = conn.execute(
        "SELECT COUNT(*) FROM corporate_actions WHERE effective_date BETWEEN ? AND ?",
        (IS_START, OOS_END)).fetchone()[0]
    is_cnt = conn.execute(
        "SELECT COUNT(*) FROM corporate_actions WHERE effective_date BETWEEN ? AND ?",
        (IS_START, IS_END)).fetchone()[0]
    oos_cnt = conn.execute(
        "SELECT COUNT(*) FROM corporate_actions WHERE effective_date BETWEEN ? AND ?",
        (OOS_START, OOS_END)).fetchone()[0]
    out_cnt = total - in_win
    print(f"3. 回测区间内事件总数: {in_win}")
    print(f"4. 样本内事件总数: {is_cnt}")
    print(f"5. 样本外事件总数: {oos_cnt}")
    print(f"6. 回测区间外事件总数: {out_cnt}")
    checks.append(("样本内+样本外==区间内", is_cnt + oos_cnt == in_win, f"{is_cnt + oos_cnt} vs {in_win}"))
    checks.append(("区间内+区间外==总数", in_win + out_cnt == total, f"{in_win + out_cnt} vs {total}"))

    # 7-9. 类型 × 区间
    print()
    print(f"{'类型':22s} {'样本内':>7s} {'样本外':>7s} {'区间外':>7s} {'合计':>7s}")
    type_total = 0
    for action_type in TYPES:
        row = conn.execute(
            "SELECT "
            " SUM(CASE WHEN effective_date BETWEEN ? AND ? THEN 1 ELSE 0 END), "
            " SUM(CASE WHEN effective_date BETWEEN ? AND ? THEN 1 ELSE 0 END), "
            " SUM(CASE WHEN effective_date < ? OR effective_date > ? THEN 1 ELSE 0 END), "
            " COUNT(*) "
            "FROM corporate_actions WHERE action_type=?",
            (IS_START, IS_END, OOS_START, OOS_END, IS_START, OOS_END, action_type),
        ).fetchone()
        a, b, c, n = (row[0] or 0, row[1] or 0, row[2] or 0, row[3] or 0)
        type_total += n
        if n:
            print(f"{action_type:22s} {a:7d} {b:7d} {c:7d} {n:7d}")
        checks.append((f"{action_type} 分区间之和==合计", a + b + c == n, f"{a + b + c} vs {n}"))
    print(f"{'合计':22s} {is_cnt:7d} {oos_cnt:7d} {out_cnt:7d} {total:7d}")
    checks.append(("类型合计==去重总数", type_total == total, f"{type_total} vs {total}"))

    # 10-13. 证据等级
    print()
    print(f"{'证据等级':22s} {'样本内':>7s} {'样本外':>7s} {'区间外':>7s} {'合计':>7s}")
    evidence_total = 0
    for status in EVIDENCE:
        row = conn.execute(
            "SELECT "
            " SUM(CASE WHEN effective_date BETWEEN ? AND ? THEN 1 ELSE 0 END), "
            " SUM(CASE WHEN effective_date BETWEEN ? AND ? THEN 1 ELSE 0 END), "
            " SUM(CASE WHEN effective_date < ? OR effective_date > ? THEN 1 ELSE 0 END), "
            " COUNT(*) "
            "FROM corporate_actions WHERE evidence_status=?",
            (IS_START, IS_END, OOS_START, OOS_END, IS_START, OOS_END, status),
        ).fetchone()
        a, b, c, n = (row[0] or 0, row[1] or 0, row[2] or 0, row[3] or 0)
        evidence_total += n
        print(f"{status:22s} {a:7d} {b:7d} {c:7d} {n:7d}")
        checks.append((f"{status} 分区间之和==合计", a + b + c == n, f"{a + b + c} vs {n}"))
    print(f"{'合计':22s} {is_cnt:7d} {oos_cnt:7d} {out_cnt:7d} {total:7d}")
    checks.append(("证据等级合计==去重总数", evidence_total == total, f"{evidence_total} vs {total}"))

    # 14. 应用
    applied_rows = conn.execute(
        "SELECT COUNT(*) FROM corporate_action_applications").fetchone()[0]
    applied_events = conn.execute(
        "SELECT COUNT(DISTINCT action_id) FROM corporate_action_applications").fetchone()[0]
    usable_in_win = conn.execute(
        "SELECT COUNT(*) FROM corporate_actions WHERE effective_date BETWEEN ? AND ? "
        "AND evidence_status IN ('official_confirmed','secondary_confirmed')",
        (IS_START, OOS_END)).fetchone()[0]
    print()
    print(f"14. 实际应用：事件 {applied_events} 条 / 应用行 {applied_rows} 行")
    print(f"    区间内可应用事件: {usable_in_win}")
    checks.append(("应用事件数<=可应用事件数", applied_events <= usable_in_win,
                   f"{applied_events} vs {usable_in_win}"))

    # 15. 零变化
    zero_rows = conn.execute(
        "SELECT COUNT(*) FROM corporate_action_applications "
        "WHERE shares_before=shares_after AND ABS(cash_delta)<1e-12").fetchone()[0]
    print(f"15. 应用行中零账本变化: {zero_rows}")

    # 16. 未确认
    unverified_total = conn.execute(
        "SELECT COUNT(*) FROM corporate_actions "
        "WHERE evidence_status NOT IN ('official_confirmed','secondary_confirmed')"
    ).fetchone()[0]
    unverified_in_win = conn.execute(
        "SELECT COUNT(*) FROM corporate_actions WHERE effective_date BETWEEN ? AND ? "
        "AND evidence_status NOT IN ('official_confirmed','secondary_confirmed')",
        (IS_START, OOS_END)).fetchone()[0]
    print(f"16. 未确认事件: {unverified_total}（其中区间内 {unverified_in_win}）")

    print()
    print("=== 一致性校验 ===")
    failed = 0
    for name, ok, detail in checks:
        mark = "OK" if ok else "FAIL"
        print(f"  [{mark}] {name}  ({detail})")
        if not ok:
            failed += 1
    print()
    print(f"校验项 {len(checks)}，失败 {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
