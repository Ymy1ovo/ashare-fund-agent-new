"""运行阶段3A.2 策略可信度验证。

用法：
    python scripts/run_validation.py --all
    python scripts/run_validation.py --is-start 2021-01-01 --is-end 2024-12-31 \
        --oos-start 2025-01-01 --oos-end 2026-11-09
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402
from app.database.db import init_db  # noqa: E402
from app.validation.config import ValidationConfig  # noqa: E402
from app.validation.report import render_validation_report  # noqa: E402
from app.validation.runner import ValidationError, run_validation  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="阶段3A.2 策略可信度验证")
    parser.add_argument("--is-start", default="2021-01-01")
    parser.add_argument("--is-end", default="2024-12-31")
    parser.add_argument("--oos-start", default="2025-01-01")
    parser.add_argument("--oos-end", default="2026-11-09")
    parser.add_argument("--cash", type=float, default=1_000_000.0)
    parser.add_argument("--stress", nargs="*", help="只跑指定压力场景")
    parser.add_argument("--no-save-report", action="store_true")
    parser.add_argument("--validation-id", default=None)
    args = parser.parse_args()

    init_db()
    config = ValidationConfig(
        is_start=args.is_start,
        is_end=args.is_end,
        oos_start=args.oos_start,
        oos_end=args.oos_end,
        initial_cash=args.cash,
    )
    try:
        result = run_validation(
            config, validation_id=args.validation_id, stress_keys=args.stress
        )
    except ValidationError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    report = render_validation_report(result)
    report_path = settings.report_dir / f"validation_{result.validation_id}.md"
    if not args.no_save_report:
        report_path.write_text(report, encoding="utf-8")

    payload = {
        "validation_id": result.validation_id,
        "status": result.status,
        "conclusion": result.conclusion,
        "etf_count": len(result.codes),
        "excluded": len(result.excluded),
        "is_days": result.split["is_days"],
        "oos_days": result.split["oos_days"],
        "best_param": result.grid.get("best_param"),
        "is_metrics": {
            key: result.is_metrics.get(key)
            for key in ("total_return", "cagr", "sharpe_ratio", "max_drawdown")
        },
        "oos_metrics": {
            key: result.oos_metrics.get(key)
            for key in ("total_return", "cagr", "sharpe_ratio", "max_drawdown")
        },
        "windows": len(result.windows),
        "windows_success": sum(1 for w in result.windows if w["status"] == "success"),
        "report": str(report_path),
    }
    summary_path = settings.data_dir / f"validation_summary_{result.validation_id}.json"
    summary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
