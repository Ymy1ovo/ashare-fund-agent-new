"""阶段3B-6.0.3 第一步：只读审计当前基金池，生成扩容缺口报告。

**纯只读**：不写库、不联网。只回答「现在有什么、缺什么」。

用法：
    python scripts/audit_3b6_0_3_universe_gap.py
    python scripts/audit_3b6_0_3_universe_gap.py --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database.db import get_connection                    # noqa: E402
from app.fund.ingest_user_funds import db_fingerprint          # noqa: E402
from app.fund.research.data_access import load_universe        # noqa: E402
from app.fund.research.engine import analyze_universe          # noqa: E402

# 六类场外基金
TARGET_CLASSES = ("ordinary_index", "etf_linked", "active_equity",
                  "bond_pure", "bond_mixed", "money_market", "lof")
CLASS_LABEL = {
    "ordinary_index": "普通指数基金", "etf_linked": "ETF联接基金",
    "active_equity": "主动权益基金", "bond_pure": "纯债基金",
    "bond_mixed": "混合债券基金", "money_market": "货币基金",
    "lof": "LOF 场外份额",
}


def db_inventory() -> dict:
    with get_connection() as c:
        counts = {}
        for t in ("fund_master", "fund_share_classes", "fund_nav_daily",
                  "fund_dividends", "fund_lifecycle_events",
                  "fund_manager_history", "fund_aum_history", "fund_fee_rules"):
            counts[t] = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        lifecycle = {r[0]: r[1] for r in c.execute(
            "SELECT lifecycle_status, COUNT(*) FROM fund_master "
            "GROUP BY lifecycle_status")}
        types = {r[0]: r[1] for r in c.execute(
            "SELECT COALESCE(fund_type_l1,'(NULL)'), COUNT(*) FROM fund_master "
            "GROUP BY fund_type_l1")}
        # A/C 归组证据：一个 fund_id 挂多个份额
        multi = c.execute(
            "SELECT COUNT(*) FROM (SELECT fund_id FROM fund_share_classes "
            "GROUP BY fund_id HAVING COUNT(*) > 1)").fetchone()[0]
        # 终止事件类型分布
        ev = {}
        try:
            ev = {r[0]: r[1] for r in c.execute(
                "SELECT event_type, COUNT(*) FROM fund_lifecycle_events "
                "GROUP BY event_type")}
        except Exception:
            pass
        # 净值/分红覆盖：这两张表挂 share_class_id，需 JOIN 到 fund_id
        nav = c.execute(
            "SELECT COUNT(DISTINCT sc.fund_id) FROM fund_nav_daily n "
            "JOIN fund_share_classes sc ON sc.share_class_id=n.share_class_id"
        ).fetchone()[0]
        div = c.execute(
            "SELECT COUNT(DISTINCT sc.fund_id) FROM fund_dividends d "
            "JOIN fund_share_classes sc ON sc.share_class_id=d.share_class_id"
        ).fetchone()[0]
        aum = c.execute(
            "SELECT COUNT(DISTINCT fund_id) FROM fund_aum_history").fetchone()[0]
        mgr = c.execute(
            "SELECT COUNT(DISTINCT fund_id) FROM fund_manager_history").fetchone()[0]
        integrity = c.execute("PRAGMA integrity_check").fetchone()[0]
        fk = len(c.execute("PRAGMA foreign_key_check").fetchall())
    return {"table_counts": counts, "lifecycle_distribution": lifecycle,
            "type_l1_distribution": types,
            "funds_with_multiple_shares": multi,
            "lifecycle_event_types": ev,
            "nav_covered_funds": nav, "dividend_covered_funds": div,
            "aum_covered_funds": aum, "manager_covered_funds": mgr,
            "integrity_check": integrity, "foreign_key_violations": fk,
            "content_fingerprint": db_fingerprint()["sha256"]}


def universe_stats() -> dict:
    u = load_universe()
    uni = analyze_universe()
    by_fund, by_share = Counter(), Counter()
    for e in u:
        by_share[e["product_class"]] += 1
        by_fund[e["product_class"]] = by_fund.get(e["product_class"], 0)
    seen = set()
    for e in u:
        if e["fund_id"] not in seen:
            seen.add(e["fund_id"])
            by_fund[e["product_class"]] += 1
    groups = uni["peer_analysis"]["groups"]
    return {
        "fund_count": len(seen), "share_count": len(u),
        "group_count": uni["peer_analysis"]["group_count"],
        "by_class_fund": dict(by_fund), "by_class_share": dict(by_share),
        "groups": {k: v["member_count"] for k, v in groups.items()},
        "groups_ge_5": sum(1 for v in groups.values()
                           if v["member_count"] >= 5),
        "groups_ge_10": sum(1 for v in groups.values()
                            if v["member_count"] >= 10),
        "max_group_size": max((v["member_count"] for v in groups.values()),
                              default=0),
        "share_to_fund_ratio": (round(len(u) / len(seen), 2) if seen else None),
    }


def gap_analysis(uni: dict) -> dict:
    """按类别给出缺口。"""
    gaps = []
    for cls in TARGET_CLASSES:
        n = uni["by_class_fund"].get(cls, 0)
        gaps.append({
            "product_class": cls, "label": CLASS_LABEL.get(cls, cls),
            "current_fund_count": n,
            "need_to_5": max(0, 5 - n),
            "need_to_10": max(0, 10 - n),
            "status": ("ok_10plus" if n >= 10 else
                       "ok_5plus" if n >= 5 else
                       "below_5" if n > 0 else "empty"),
        })
    return {"per_class": gaps,
            "total_need_to_5": sum(g["need_to_5"] for g in gaps),
            "total_need_to_10": sum(g["need_to_10"] for g in gaps)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="3B-6.0.3 基金池缺口审计")
    ap.add_argument("--json", help="输出 JSON 路径")
    args = ap.parse_args(argv)

    inv = db_inventory()
    uni = universe_stats()
    gap = gap_analysis(uni)

    doc = {"phase": "3B-6.0.3", "step": "1_universe_gap_audit",
           "generated_at": datetime.now().isoformat(timespec="seconds"),
           "readonly": True, "database_written": False,
           "db_inventory": inv, "universe": uni, "gap": gap}

    print("== 正式库 ==")
    for k, v in inv["table_counts"].items():
        print(f"  {k:24} {v}")
    print(f'  生命周期: {inv["lifecycle_distribution"]}')
    print(f'  内容指纹: {inv["content_fingerprint"][:16]}…')
    print()
    print("== 研究池 ==")
    print(f'  本体 {uni["fund_count"]} / 份额 {uni["share_count"]} / '
          f'同类组 {uni["group_count"]}')
    print(f'  ≥5 组: {uni["groups_ge_5"]}  ≥10 组: {uni["groups_ge_10"]}  '
          f'最大组: {uni["max_group_size"]}')
    print()
    print("== 分类缺口 ==")
    for g in gap["per_class"]:
        print(f'  {g["label"]:14} 现有 {g["current_fund_count"]:2}  '
              f'距5缺 {g["need_to_5"]:2}  距10缺 {g["need_to_10"]:2}  {g["status"]}')
    print()
    print(f'  距 5 合计缺口: {gap["total_need_to_5"]}')
    print(f'  距 10 合计缺口: {gap["total_need_to_10"]}')

    if args.json:
        Path(args.json).write_text(
            json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
