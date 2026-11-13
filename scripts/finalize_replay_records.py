"""给新口径记录打上会计版本标记（阶段3A.3.2.1）。

只更新版本标记列，不改任何数值。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.database.db import get_connection  # noqa: E402

CURRENT = "ca-v2-receivable"
VALIDATION_IDS = ("6e310be0193643c1", "e0ac2b1b3b9748ac")
BACKTEST_RUN_IDS = (
    "67591d0431654109", "2e9ec68a18b54670", "8b7454df421d4e8d",
    "b7ef48255d5a40c0", "c8ae9aa8175e4cf3", "60e9203bf89143ab",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="标记新口径记录")
    parser.add_argument("--json", default="data/replay_3a3_2_1.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    payload_path = PROJECT_ROOT / args.json
    digests: dict[str, str] = {}
    if payload_path.exists():
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        for label, run in (payload.get("runs") or {}).items():
            if run.get("corporate_action_digest"):
                digests[run["run_id"]] = run["corporate_action_digest"]

    with get_connection() as conn:
        if args.dry_run:
            print(f"将标记 validation {len(VALIDATION_IDS)} 条、backtest {len(BACKTEST_RUN_IDS)} 条")
            return 0

        for vid in VALIDATION_IDS:
            row = conn.execute(
                "SELECT summary_json FROM validation_runs WHERE validation_id=?", (vid,)
            ).fetchone()
            if not row:
                print(f"  跳过不存在的 validation {vid}")
                continue
            conn.execute(
                "UPDATE validation_runs SET accounting_version=?, legacy_flag=? "
                "WHERE validation_id=?",
                (CURRENT, "current_corporate_action_accounting", vid),
            )
            print(f"  validation {vid} -> {CURRENT}")

        for run_id in BACKTEST_RUN_IDS:
            row = conn.execute(
                "SELECT run_id FROM backtest_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if not row:
                continue
            conn.execute(
                "UPDATE backtest_runs SET accounting_version=?, evidence_version=? "
                "WHERE run_id=?",
                (CURRENT, digests.get(run_id, "unknown"), run_id),
            )
        conn.commit()

        print()
        for row in conn.execute(
            "SELECT accounting_version, COUNT(*) FROM validation_runs GROUP BY accounting_version"
        ):
            print(f"  validation {row[0]}: {row[1]}")
        for row in conn.execute(
            "SELECT accounting_version, COUNT(*) FROM backtest_runs GROUP BY accounting_version"
        ):
            print(f"  backtest {row[0]}: {row[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
