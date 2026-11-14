"""盘点历史回测 / 验证记录，输出分类与待重放清单（阶段3A.3.2.3.1）。

只读数据库。所有数字都能由本脚本重新算出：

    python scripts/audit_replay_history.py
    python scripts/audit_replay_history.py --json data/replay_manifest_3a3_2_3_1.json
    python scripts/audit_replay_history.py --pending-only
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.replay.manifest import (  # noqa: E402
    ALL_CLASSES,
    BACKTEST,
    CLASS_CURRENT_FORMAL,
    CLASS_LEGACY,
    CLASS_NON_REPLAYABLE,
    CLASS_REPLAYED,
    CLASS_UNKNOWN_LEGACY,
    VALIDATION,
    backtest_manifest,
    summarize,
    validation_manifest,
)
from app.replay.registry import (  # noqa: E402
    init_replay_schema,
    list_attempts,
    success_map,
)

LABELS = {
    CLASS_CURRENT_FORMAL: "current_formal（已是当前正式口径）",
    CLASS_REPLAYED: "replayed（已存在成功重放）",
    CLASS_LEGACY: "legacy（旧口径，参数可证，待重放）",
    CLASS_UNKNOWN_LEGACY: "unknown_legacy（口径不可确认）",
    CLASS_NON_REPLAYABLE: "non_replayable（参数缺失或源记录不可用）",
}


def _collect(db_path=None):
    init_replay_schema(db_path)
    bt = backtest_manifest(db_path, successes=success_map(BACKTEST, db_path))
    vl = validation_manifest(db_path, successes=success_map(VALIDATION, db_path))
    return bt, vl


def build_payload(db_path=None) -> dict:
    bt, vl = _collect(db_path)
    payload = {
        "phase": "3A.3.2.3.1",
        "classification_rules": {
            CLASS_CURRENT_FORMAL: "accounting_version == ca-v2-receivable",
            CLASS_REPLAYED: "replay_attempts 中存在 status=success 的记录",
            CLASS_LEGACY: (
                "accounting_version == legacy_corporate_action_accounting "
                "且全部关键参数可证明"
            ),
            CLASS_UNKNOWN_LEGACY: "accounting_version 为空或非已知值",
            CLASS_NON_REPLAYABLE: "缺少关键参数，或源记录本身失败/不可用",
        },
        "backtest": {
            "summary": summarize(bt),
            "records": bt,
        },
        "validation": {
            "summary": summarize(vl),
            "records": vl,
        },
        "pending": {
            BACKTEST: [item["source_id"] for item in bt
                       if item["classification"] == CLASS_LEGACY],
            VALIDATION: [item["source_id"] for item in vl
                         if item["classification"] == CLASS_LEGACY],
        },
        "attempts": list_attempts(limit=500, db_path=db_path),
    }
    return payload


def _print_section(title: str, records: list[dict], summary: dict) -> None:
    print(f"\n=== {title} ===")
    print(f"总数 {summary['total']}；分类合计校验 {summary['sum_matches_total']}")
    for klass in ALL_CLASSES:
        print(f"  {LABELS[klass]:42} {summary['counts'].get(klass, 0):>4}")
    print(f"  待重放 {summary['pending_replay']} / 已重放 {summary['already_replayed']} "
          f"/ 可重放 {summary['replayable']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="历史回测与验证记录盘点")
    parser.add_argument("--json", default=None, help="输出 JSON 路径")
    parser.add_argument("--pending-only", action="store_true", help="只打印待重放清单")
    parser.add_argument("--show", choices=("all", "legacy", "non_replayable", "none"),
                        default="legacy", help="逐条打印哪一类")
    args = parser.parse_args()

    payload = build_payload()
    bt, vl = payload["backtest"], payload["validation"]

    if args.pending_only:
        print("待重放 backtest：")
        for item in payload["pending"][BACKTEST]:
            print(f"  {item}")
        print("待重放 validation：")
        for item in payload["pending"][VALIDATION]:
            print(f"  {item}")
        return 0

    _print_section("backtest_runs", bt["records"], bt["summary"])
    _print_section("validation_runs", vl["records"], vl["summary"])

    targets = {
        "all": ALL_CLASSES,
        "legacy": (CLASS_LEGACY,),
        "non_replayable": (CLASS_NON_REPLAYABLE,),
        "none": (),
    }[args.show]

    if targets:
        print("\n=== 逐条明细 ===")
        for label, section in (("backtest", bt), ("validation", vl)):
            for item in section["records"]:
                if item["classification"] not in targets:
                    continue
                codes = item.get("etf_count")
                span = (f"{item.get('start_date')}~{item.get('end_date')}"
                        if label == "backtest"
                        else f"{item.get('is_start')}~{item.get('is_end')} | "
                             f"{item.get('oos_start')}~{item.get('oos_end')}")
                print(f"[{label}] {item['source_id']} {item['strategy_name']} "
                      f"codes={codes} {span}")
                print(f"    {item['classification']}：{item['classification_reason']}")

    if args.json:
        out = PROJECT_ROOT / args.json if not Path(args.json).is_absolute() else Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                       encoding="utf-8")
        print(f"\n输出 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
