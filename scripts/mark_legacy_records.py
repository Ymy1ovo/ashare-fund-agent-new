"""给历史回测/验证记录打口径标记（阶段3A.3.2.1）。

规则：
- 早于本次修复生成的记录，统一标记为 `legacy_corporate_action_accounting`，
  表示它们使用的是「无应收分红、拆分不调数量」的旧口径，不得作为新口径下的
  策略评价依据。
- 本次修复之后生成的记录标记为 `ca-v2`。
- 只更新标记列，不改任何数值、不删任何行。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.database.db import get_connection  # noqa: E402

CURRENT_ACCOUNTING = "ca-v2-receivable"
LEGACY_ACCOUNTING = "legacy_corporate_action_accounting"


def main() -> int:
    parser = argparse.ArgumentParser(description="标记历史记录口径")
    parser.add_argument("--current", default=CURRENT_ACCOUNTING)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with get_connection() as conn:
        runs = conn.execute(
            "SELECT run_id, created_at, accounting_version FROM backtest_runs"
        ).fetchall()
        validations = conn.execute(
            "SELECT validation_id, created_at, accounting_version FROM validation_runs"
        ).fetchall()

        backtest_legacy = sum(1 for r in runs if not r["accounting_version"])
        validation_legacy = sum(1 for r in validations if not r["accounting_version"])
        print(f"backtest_runs {len(runs)} 条，其中未标口径 {backtest_legacy} 条")
        print(f"validation_runs {len(validations)} 条，其中未标口径 {validation_legacy} 条")

        if args.dry_run:
            print("dry-run：未写入")
            return 0

        conn.execute(
            "UPDATE backtest_runs SET accounting_version=? WHERE accounting_version IS NULL",
            (LEGACY_ACCOUNTING,),
        )
        conn.execute(
            "UPDATE validation_runs SET accounting_version=?, legacy_flag=? "
            "WHERE accounting_version IS NULL",
            (LEGACY_ACCOUNTING, LEGACY_ACCOUNTING),
        )
        conn.execute(
            "UPDATE backtest_runs SET evidence_version=? WHERE evidence_version IS NULL",
            ("ca-evidence-v1",),
        )
        conn.commit()

        for row in conn.execute(
            "SELECT accounting_version, COUNT(*) FROM backtest_runs "
            "GROUP BY accounting_version"
        ):
            print(f"  backtest {row[0]}: {row[1]}")
        for row in conn.execute(
            "SELECT accounting_version, COUNT(*) FROM validation_runs "
            "GROUP BY accounting_version"
        ):
            print(f"  validation {row[0]}: {row[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
