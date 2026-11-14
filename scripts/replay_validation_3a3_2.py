"""验证重放（可指定源 validation_id）。

用法：

    python scripts/replay_validation_3a3_2.py --source 32aead3291734f91
    python scripts/replay_validation_3a3_2.py --source <vid> --force
    python scripts/replay_validation_3a3_2.py --pending
    python scripts/replay_validation_3a3_2.py --source <vid> --dry-run

纪律：

- 不覆盖旧验证记录：`run_validation()` 每次生成新 validation_id。
- 源参数必须由 `config_hash` 反证；未命中即 non_replayable，拒绝猜测。
- 重放必须命中正式口径闸门，否则记为失败。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.replay.manifest import (  # noqa: E402
    CLASS_LEGACY,
    VALIDATION,
    ReplayError,
    validation_manifest,
)
from app.replay.registry import (  # noqa: E402
    STATUS_FAILED,
    STATUS_SKIPPED,
    STATUS_SUCCESS,
    init_replay_schema,
    success_map,
)
from app.replay.runner import replay_many, replay_validation  # noqa: E402
from app.validation.fingerprint import fingerprint_from_db  # noqa: E402
from app.validation.storage import get_validation  # noqa: E402

# 3A.3.2 时期的固定源记录；保留常量供旧流程引用
SOURCE_VID = "32aead3291734f91"


def _print_outcome(outcome) -> None:
    tag = {STATUS_SUCCESS: "OK  ", STATUS_SKIPPED: "SKIP", STATUS_FAILED: "FAIL"}[outcome.status]
    line = f"  [{tag}] {outcome.source_id}"
    if outcome.replay_id:
        line += f" -> {outcome.replay_id}"
    if outcome.reason:
        line += f"  （{outcome.reason}）"
    extra = outcome.extra or {}
    if "conclusion" in extra:
        line += f"  结论={extra['conclusion']}"
    print(line, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="历史验证重放（可指定源 validation_id）")
    parser.add_argument("--source", default=None, help="源 validation_id")
    parser.add_argument("--pending", action="store_true",
                        help="批量重放所有分类为 legacy 的验证记录")
    parser.add_argument("--force", action="store_true", help="忽略已有成功重放，强制重跑")
    parser.add_argument("--dry-run", action="store_true", help="只检查可重放性，不执行")
    parser.add_argument("--out", default="data/replay_validation_3a3_2.json")
    args = parser.parse_args()

    if not args.source and not args.pending:
        parser.error("必须指定 --source <validation_id> 或 --pending")

    init_replay_schema()
    fp_before = fingerprint_from_db()
    started = time.time()

    if args.source:
        manifest = {item["source_id"]: item for item in
                    validation_manifest(successes=success_map(VALIDATION))}
        item = manifest.get(args.source)
        if not item:
            print(f"源验证记录不存在：{args.source}")
            return 2
        if args.dry_run:
            print(f"{args.source}：{item['classification']}（{item['classification_reason']}）")
            print(f"  参数证明：{item['params_proof']}")
            print(f"  可重放：{item['replayable']}")
            return 0 if item["replayable"] else 1
        try:
            outcome = replay_validation(args.source, force=args.force)
        except ReplayError as exc:
            print(f"失败：{exc}")
            return 2
        _print_outcome(outcome)
        outcomes = [outcome]
    else:
        targets = [i["source_id"] for i in validation_manifest()
                   if i["classification"] == CLASS_LEGACY]
        if not targets:
            print("没有需要重放的 validation 记录。")
            return 0
        print(f"待重放 {len(targets)} 条：{'、'.join(targets)}")
        print("注意：单条验证约 24 分钟，本命令只建机制，不强制此刻跑完全部。")
        if args.dry_run:
            return 0
        outcomes = replay_many(VALIDATION, targets, force=args.force,
                               on_progress=_print_outcome)

    fp_after = fingerprint_from_db()
    same = fp_before.get("sha256") == fp_after.get("sha256")
    elapsed = round(time.time() - started, 1)
    payload = {
        "phase": "3A.3.2.3.1",
        "source_id": args.source,
        "outcomes": [
            {
                "source_id": o.source_id,
                "status": o.status,
                "replay_id": o.replay_id,
                "reason": o.reason,
                "extra": o.extra,
            }
            for o in outcomes
        ],
        "fingerprint_before": fp_before,
        "fingerprint_after": fp_after,
        "data_unchanged": same,
        "elapsed_seconds": elapsed,
    }
    out = PROJECT_ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                   encoding="utf-8")
    print(f"\n行情指纹前后一致：{same}")
    print(f"输出 {out}")
    ok = all(o.status in (STATUS_SUCCESS, STATUS_SKIPPED) for o in outcomes)
    return 0 if (ok and same) else 1


if __name__ == "__main__":
    raise SystemExit(main())
