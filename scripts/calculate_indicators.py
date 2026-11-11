"""计算 ETF 量化指标并写入 SQLite。

用法：
    .venv\\Scripts\\python.exe scripts\\calculate_indicators.py --all
    .venv\\Scripts\\python.exe scripts\\calculate_indicators.py --code 510300
    .venv\\Scripts\\python.exe scripts\\calculate_indicators.py --code 510300 --full-rebuild
    .venv\\Scripts\\python.exe scripts\\calculate_indicators.py --all --indicators returns,trend
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402
from app.database.db import get_pool_codes, init_db  # noqa: E402
from app.database.indicators import save_indicator_result  # noqa: E402
from app.logging_config import setup_logging  # noqa: E402
from app.quant.config import DEFAULT_CONFIG, SUPPORTED_GROUPS, normalize_config  # noqa: E402
from app.quant.engine import batch_exit_code, calculate_indicators  # noqa: E402

logger = logging.getLogger("phase2.indicators")


def _config(args) -> dict:
    config = normalize_config()
    if args.indicators:
        groups = [item.strip() for item in args.indicators.split(",") if item.strip()]
        unknown = set(groups) - SUPPORTED_GROUPS
        if unknown:
            raise SystemExit(f"未知指标组：{sorted(unknown)}")
        config["enabled"] = groups
    if args.risk_free_rate is not None:
        config["risk_free_rate"] = args.risk_free_rate
    if args.risk_window is not None:
        config["risk_window"] = args.risk_window
    return normalize_config(config)


def main() -> int:
    parser = argparse.ArgumentParser(description="计算 ETF 量化指标")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="计算全部观察池")
    group.add_argument("--code", action="append", help="指定 ETF 代码，可重复")
    parser.add_argument("--start", help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", help="结束日期 YYYY-MM-DD")
    parser.add_argument("--indicators", help="指标组，逗号分隔：returns,trend,momentum,volatility,risk")
    parser.add_argument("--full-rebuild", action="store_true", help="写回全区间，不按已有日期增量")
    parser.add_argument("--risk-free-rate", type=float, default=None, help="年化无风险利率，默认 0")
    parser.add_argument("--risk-window", type=int, default=None, help="滚动风险窗口，默认 252")
    parser.add_argument("--limit", type=int, default=0, help="仅处理前 N 只")
    args = parser.parse_args()

    setup_logging("phase2_indicators.log")
    init_db()
    config = _config(args)
    codes = get_pool_codes() if args.all else [str(code).zfill(6) for code in args.code]
    if not codes:
        logger.error("没有可计算的 ETF")
        return 1
    if args.limit and args.limit > 0:
        codes = codes[: args.limit]

    results = []
    failures = []
    details = []
    for code in codes:
        try:
            result = calculate_indicators(
                code,
                args.start,
                args.end,
                config,
                today=None,
            )
            written = save_indicator_result(
                result,
                incremental=not args.full_rebuild,
                full_rebuild=args.full_rebuild,
            )
            results.append(result)
            details.append({**result.as_meta(), **written})
            logger.info(
                "%s 指标完成 status=%s rows=%s written=%s version=%s snapshot=%s",
                code,
                result.status,
                len(result.data),
                written["written_rows"],
                result.calculation_version,
                result.snapshot_id,
            )
        except Exception as exc:
            reason = getattr(exc, "reason", "unexpected_error")
            failures.append({"etf_code": code, "reason": reason, "message": str(exc)})
            logger.exception("%s 指标计算失败：%s", code, exc)

    exit_code = batch_exit_code(results, failures, len(codes))
    status = "success" if exit_code == 0 else ("partial" if exit_code == 2 else "failed")
    payload = {
        "status": status,
        "exit_code": exit_code,
        "total_codes": len(codes),
        "success_codes": sum(1 for item in results if item.status == "success"),
        "partial_codes": sum(1 for item in results if item.status == "partial"),
        "failed_codes": len(failures) + sum(1 for item in results if item.status == "failed"),
        "calculation_version": results[0].calculation_version if results else None,
        "config": config,
        "details": details,
        "failures": failures,
    }
    output = settings.data_dir / "indicator_calculation_summary.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(
        f"status={status} exit_code={exit_code} total={len(codes)} "
        f"success={payload['success_codes']} partial={payload['partial_codes']} "
        f"failed={payload['failed_codes']} summary={output}"
    )
    for failure in failures:
        print(f"FAILED {failure['etf_code']} {failure['reason']} {failure['message']}")
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
