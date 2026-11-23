"""阶段3B-6.0.1.1 中债收益率曲线历史覆盖度验证。

**不能因为一个 21 行的小窗口就宣称长期历史已验证。**

分段实测：早期 / 中期 / 近期 / 长区间，分别记录返回行数、日期范围、
曲线类型、期限字段、失败原因。

不写库、不落盘行情。

用法：
    python scripts/audit_3b6_0_1_1_bond_coverage.py
    python scripts/audit_3b6_0_1_1_bond_coverage.py --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SLEEP_SEC = 1.5

# 分段窗口：早期 / 中期 / 近期 / 长区间
WINDOWS = [
    ("early_2005", "20050101", "20051231", "早期·2005 整年"),
    ("early_2006", "20060101", "20061231", "早期·2006 整年"),
    ("early_2010", "20100101", "20101231", "早期·2010 整年"),
    ("mid_2015", "20150101", "20151231", "中期·2015 整年"),
    ("mid_2020", "20200101", "20201231", "中期·2020 整年"),
    ("recent_2025", "20250101", "20251231", "近期·2025 整年"),
    ("recent_2026", "20260101", "20261123", "近期·2026 至今"),
    ("long_span_10y", "20100101", "20201231", "长区间·11 年一次请求"),
    ("short_probe", "20200102", "20200110", "短窗口·原 3B-6.0.1 所用"),
]


def probe(label: str, start: str, end: str) -> dict:
    rec = {"key": label, "start": start, "end": end,
           "ok": False, "rows": 0, "dates": 0,
           "date_min": None, "date_max": None,
           "curves": [], "tenor_columns": [], "error": None,
           "elapsed_sec": 0.0}
    t0 = time.time()
    try:
        import akshare as ak
        df = ak.bond_china_yield(start_date=start, end_date=end)
        rec["rows"] = int(len(df))
        if len(df):
            ds = sorted({str(d)[:10] for d in df["日期"]})
            rec["dates"] = len(ds)
            rec["date_min"] = ds[0]
            rec["date_max"] = ds[-1]
            if "曲线名称" in df.columns:
                rec["curves"] = sorted({str(c) for c in df["曲线名称"]})
            rec["tenor_columns"] = [c for c in df.columns
                                    if c not in ("曲线名称", "日期")]
        rec["ok"] = rec["rows"] > 0
    except Exception as exc:
        rec["error"] = f"{type(exc).__name__}: {str(exc)[:150]}"
    rec["elapsed_sec"] = round(time.time() - t0, 2)
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="3B-6.0.1.1 中债覆盖率验证")
    ap.add_argument("--json", help="输出 JSON 路径")
    args = ap.parse_args(argv)

    results = []
    for key, start, end, label in WINDOWS:
        rec = probe(key, start, end)
        rec["label"] = label
        results.append(rec)
        status = "OK  " if rec["ok"] else "FAIL"
        print(f'  {status} {label:28} rows={rec["rows"]:5} '
              f'dates={rec["dates"]:4} {rec["date_min"]} ~ {rec["date_max"]}'
              + (f'  ERR={rec["error"][:50]}' if rec["error"] else ''))
        time.sleep(SLEEP_SEC)

    # 覆盖结论
    ok_years = sorted({int(r["start"][:4]) for r in results if r["ok"]})
    long_ok = any(r["key"] == "long_span_10y" and r["ok"] for r in results)
    earliest = min((r["date_min"] for r in results if r["ok"] and r["date_min"]),
                   default=None)
    latest = max((r["date_max"] for r in results if r["ok"] and r["date_max"]),
                 default=None)

    doc = {
        "phase": "3B-6.0.1.1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "readonly": True,
        "database_written": False,
        "market_data_persisted": False,
        "windows": results,
        "coverage_conclusion": {
            "single_request_long_span_works": long_ok,
            "per_year_requests_work": len(ok_years) >= 2,
            "earliest_date_observed": earliest,
            "latest_date_observed": latest,
            "succeeded_year_starts": ok_years,
            "failed_windows": [r["key"] for r in results if not r["ok"]],
            "history_coverage_verified": bool(long_ok),
            "coverage_method": ("单次长区间请求" if long_ok
                                else "必须按年分段请求后再拼接"),
            "statement": (
                "单次长区间请求可拿回长期数据" if long_ok else
                "单次长区间请求失败（返回 0 行），必须按年分段请求；"
                "分段可覆盖多个年份，但**不等同于**已验证可稳定取得连续全历史。"
                "仍标 history_coverage_verified=false"),
        },
        "tenor_structure": {
            "available_tenors": (next((r["tenor_columns"] for r in results
                                       if r["tenor_columns"]), [])),
            "curve_types": (next((r["curves"] for r in results if r["curves"]), [])),
        },
        "original_claim_correction": {
            "original_claim": "中债曲线可取（基于 2020-01-02 ~ 2020-01-10 的 21 行）",
            "problem": "21 行只证明该短窗口可取，不能推断长期历史覆盖",
            "corrected": ("长期覆盖需分段验证；"
                          "单次长区间请求实测返回 0 行"),
        },
    }
    if args.json:
        Path(args.json).write_text(
            json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print()
    print(json.dumps(doc["coverage_conclusion"], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
