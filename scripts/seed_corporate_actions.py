"""把已核实的公司行为事件写入数据库（阶段3A.3.2）。

纪律：
- 只写 `corporate_actions` 表，不动任何行情、回测、验证记录。
- 事件全部来自官方来源（天天基金分红送配页 / 券商转发基金公告），
  报告中逐条标注来源 URL。
- 未确认事件不得写入 `confirmed`；确实存在但无官方证据的记为 `unverified`。
- 幂等：重复运行按 (code, action_type, ex_date) 更新，不产生重复行。

用法：
    python scripts/seed_corporate_actions.py --dry-run
    python scripts/seed_corporate_actions.py
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
    ACTION_REVERSE_SPLIT,
    ACTION_SPLIT,
    STATUS_CONFIRMED,
    build_action,
    save_action,
)
from app.database.db import get_connection, init_db  # noqa: E402

SOURCE_EM = "天天基金分红送配 https://fundf10.eastmoney.com/fhsp_{code}.html"
SOURCE_511030 = "国投证券转发平安基金公告 https://www.essence.com.cn/news/2533946?columnId=003005"


def _next_trading_day(conn, day: str) -> str | None:
    row = conn.execute(
        "SELECT trade_date FROM trade_calendar WHERE trade_date > ? ORDER BY trade_date LIMIT 1",
        (day,),
    ).fetchone()
    return str(row[0]) if row else None


def build_events(raw: dict, conn) -> list:
    """把抓取结果转换为事件对象（只保留回测区间内、已确认的）。"""
    events = []
    for code, info in raw.items():
        if "error" in info:
            continue
        source = SOURCE_511030 if code == "511030" else SOURCE_EM.format(code=code)
        for item in info.get("splits", []):
            ex = item["date"]
            eff = _next_trading_day(conn, ex)
            if not eff:
                continue
            ratio = float(item["ratio"])
            action_type = ACTION_SPLIT if ratio > 1 else ACTION_REVERSE_SPLIT
            events.append(build_action(
                code=code, action_type=action_type, ex_date=ex, effective_date=eff,
                share_ratio=ratio, source=source,
                evidence=f"{info['name']} {item['type']} 1:{ratio}",
                status=STATUS_CONFIRMED,
                notes=f"官方类型：{item['type']}",
            ))
        for item in info.get("dividends", []):
            ex = item["ex_date"]
            eff = _next_trading_day(conn, ex)
            if not eff:
                continue
            events.append(build_action(
                code=code, action_type=ACTION_CASH_DISTRIBUTION,
                ex_date=ex, effective_date=eff,
                cash_per_share=float(item["per10"]) / 10.0,
                record_date=item.get("record_date"), pay_date=item.get("pay_date"),
                source=source,
                evidence=f"{info['name']} 每10份派现 {item['per10']} 元",
                status=STATUS_CONFIRMED,
            ))
    return events


def main() -> int:
    parser = argparse.ArgumentParser(description="写入已核实公司行为事件")
    parser.add_argument("--raw", default="data/corporate_action_all46.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    raw_path = PROJECT_ROOT / args.raw
    if not raw_path.exists():
        raise SystemExit(f"缺少抓取结果：{raw_path}（先运行 scripts/audit_corporate_actions.py）")

    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    init_db()
    with get_connection() as conn:
        events = build_events(raw, conn)

    events.sort(key=lambda item: (item.effective_date, item.code))
    print(f"待写入事件 {len(events)} 条")
    by_type: dict[str, int] = {}
    for item in events:
        by_type[item.action_type] = by_type.get(item.action_type, 0) + 1
    for key, value in sorted(by_type.items()):
        print(f"  {key}: {value}")

    if args.dry_run:
        for item in events[:5]:
            print("  sample:", item.as_dict())
        print("dry-run：未写入")
        return 0

    written = 0
    for item in events:
        save_action(item)
        written += 1
    print(f"已写入 {written} 条")

    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM corporate_actions").fetchone()[0]
        confirmed = conn.execute(
            "SELECT COUNT(*) FROM corporate_actions WHERE status='confirmed'"
        ).fetchone()[0]
    print(f"表内合计 {total} 条，其中 confirmed {confirmed} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
