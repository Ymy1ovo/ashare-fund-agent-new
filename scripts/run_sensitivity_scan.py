"""稀疏行情删除比例敏感性扫描。

用法：
    python scripts/run_sensitivity_scan.py --pool representative
    python scripts/run_sensitivity_scan.py --pool all --modes random_scattered
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.backtest.data import load_calendar, load_pool  # noqa: E402
from app.config import settings  # noqa: E402
from app.database.db import get_connection, init_db  # noqa: E402
from app.validation.config import ValidationConfig  # noqa: E402
from app.validation.runner import _representative_pool  # noqa: E402
from app.validation.sensitivity_scan import (  # noqa: E402
    DELETION_MODES,
    DELETION_RATIOS,
    run_sensitivity_matrix,
    summarize_matrix,
)
from app.validation.split import (  # noqa: E402
    filter_codes_by_coverage,
    split_time_range,
)


def _pick_codes(pool_mode: str, cfg: ValidationConfig, calendar_days: int) -> list[str]:
    with get_connection() as conn:
        counts = {
            str(row[0]): int(row[1]) for row in conn.execute(
                "SELECT code, COUNT(*) FROM etf_daily_prices "
                "WHERE trade_date >= ? AND trade_date <= ? GROUP BY code",
                (cfg.is_start, cfg.oos_end),
            )
        }
        firsts = {
            str(row[0]): str(row[1]) for row in conn.execute(
                "SELECT code, MIN(trade_date) FROM etf_daily_prices GROUP BY code"
            )
        }
    codes, _ = filter_codes_by_coverage(
        counts, calendar_days, cfg.min_coverage_ratio,
        code_first_dates=firsts, required_first_date=cfg.is_start,
    )
    if pool_mode == "representative":
        codes = _representative_pool(codes, load_pool(), counts)
    return codes


def main() -> int:
    parser = argparse.ArgumentParser(description="删除比例敏感性扫描")
    parser.add_argument("--pool", choices=("representative", "all"),
                        default="representative")
    parser.add_argument("--ratios", nargs="*", type=float, default=list(DELETION_RATIOS))
    parser.add_argument("--modes", nargs="*", default=list(DELETION_MODES))
    parser.add_argument("--seed", type=int, default=20261112)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    init_db()
    cfg = ValidationConfig()
    calendar = load_calendar(cfg.is_start, cfg.oos_end)
    split = split_time_range(calendar, cfg)
    codes = _pick_codes(args.pool, cfg, len(calendar))

    payload = run_sensitivity_matrix(
        source_db=settings.database_path,
        codes=codes,
        start=split.oos_start,
        end=split.oos_end,
        indicator_version=cfg.indicator_version,
        initial_cash=cfg.initial_cash,
        seed=args.seed,
        ratios=tuple(args.ratios),
        modes=tuple(args.modes),
        pool_label=args.pool,
    )
    payload["summary"] = summarize_matrix(payload)

    out = Path(args.output or settings.data_dir / f"sensitivity_{args.pool}.json")
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(json.dumps({
        "pool": args.pool,
        "scenarios": payload["scenario_count"],
        "etf_count": payload["etf_count"],
        "source_unchanged": payload["source_unchanged"],
        "status_totals": payload["summary"]["status_totals"],
        "output": str(out),
    }, ensure_ascii=False, indent=2))
    return 0 if payload["source_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
