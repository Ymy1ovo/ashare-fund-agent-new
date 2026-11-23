"""阶段3B-6.0.1 指数与无风险利率数据源连通性审计。

**真实调用**公开接口，记录行数 / 起止日期 / 字段 / 是否含 OHLC。
不写任何数据库。

用法：
    python scripts/audit_3b6_0_1_index_sources.py
    python scripts/audit_3b6_0_1_index_sources.py --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 每次请求之间休眠，避免被限流
SLEEP_SEC = 1.5


def _probe(label: str, fn, *, expect_cols=None) -> dict:
    started = time.time()
    try:
        df = fn()
        cols = [str(c) for c in getattr(df, "columns", [])]
        rows = int(len(df))
        first = last = None
        date_col = next((c for c in cols
                         if c in ("date", "日期", "净值日期")), None)
        if rows and date_col:
            first = str(df.iloc[0][date_col])[:10]
            last = str(df.iloc[-1][date_col])[:10]
        return {
            "label": label, "ok": True, "rows": rows,
            "date_min": first, "date_max": last,
            "columns": cols,
            "has_ohlc": all(k in cols for k in ("open", "high", "low", "close"))
            or all(k in cols for k in ("开盘", "最高", "最低", "收盘")),
            "elapsed_sec": round(time.time() - started, 2),
        }
    except Exception as exc:
        return {
            "label": label, "ok": False, "rows": 0,
            "error_type": type(exc).__name__,
            "error": str(exc)[:200],
            "traceback_head": traceback.format_exc(limit=1).splitlines()[-1][:200],
            "elapsed_sec": round(time.time() - started, 2),
        }


def probe_indices() -> list[dict]:
    import akshare as ak

    cases = [
        ("中证官网 · 沪深300 000300",
         lambda: ak.stock_zh_index_hist_csindex(
             symbol="000300", start_date="20040101", end_date="20261123")),
        ("中证官网 · 中证500 000905",
         lambda: ak.stock_zh_index_hist_csindex(
             symbol="000905", start_date="20040101", end_date="20261123")),
        ("中证官网 · 上证50 000016",
         lambda: ak.stock_zh_index_hist_csindex(
             symbol="000016", start_date="20040101", end_date="20261123")),
        ("中证官网 · 上证国债 000012",
         lambda: ak.stock_zh_index_hist_csindex(
             symbol="000012", start_date="20040101", end_date="20261123")),
        ("中证官网 · 中证全指半导体 H30184",
         lambda: ak.stock_zh_index_hist_csindex(
             symbol="H30184", start_date="20040101", end_date="20261123")),
        ("中证官网 · 中证白酒 399997",
         lambda: ak.stock_zh_index_hist_csindex(
             symbol="399997", start_date="20040101", end_date="20261123")),
        ("新浪 · 沪深300 sh000300",
         lambda: ak.stock_zh_index_daily(symbol="sh000300")),
        ("新浪 · 中证500 sh000905",
         lambda: ak.stock_zh_index_daily(symbol="sh000905")),
        ("新浪 · 恒生指数 HSI（港股）",
         lambda: ak.stock_hk_index_daily_sina(symbol="HSI")),
        ("中债 · 新综合指数（财富）",
         lambda: ak.bond_new_composite_index_cbond(indicator="财富", period="总值")),
        ("国证 · 深证系列 index_hist_sw",
         lambda: ak.index_hist_sw(symbol="801010", period="day")),
        ("东财 · index_zh_a_hist（易被限流）",
         lambda: ak.index_zh_a_hist(symbol="000300", period="daily",
                                    start_date="20200101", end_date="20200110")),
    ]
    out = []
    for label, fn in cases:
        out.append(_probe(label, fn))
        time.sleep(SLEEP_SEC)
    return out


def probe_riskfree() -> list[dict]:
    import akshare as ak

    cases = [
        ("中美国债收益率（2/5/10/30年）",
         lambda: ak.bond_zh_us_rate(start_date="20100101")),
        ("中债收益率曲线（多期限多点）",
         lambda: ak.bond_china_yield(start_date="20200101", end_date="20200110")),
        ("Shibor 全期限",
         lambda: ak.macro_china_shibor_all()),
    ]
    out = []
    for label, fn in cases:
        out.append(_probe(label, fn))
        time.sleep(SLEEP_SEC)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="3B-6.0.1 数据源连通性审计")
    ap.add_argument("--json", help="输出 JSON 路径")
    args = ap.parse_args(argv)

    doc = {
        "phase": "3B-6.0.1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "readonly": True,
        "database_written": False,
        "note": ("本脚本**真实调用**公开接口，只统计连通性与字段；"
                 "不写库、不落盘行情、不做批量采集"),
        "index_sources": probe_indices(),
        "risk_free_sources": probe_riskfree(),
    }

    if args.json:
        Path(args.json).write_text(
            json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

    for group in ("index_sources", "risk_free_sources"):
        print(f"== {group} ==")
        for r in doc[group]:
            if r["ok"]:
                print(f'  OK   {r["label"]:34} rows={r["rows"]:5} '
                      f'{r["date_min"]} ~ {r["date_max"]} '
                      f'ohlc={r["has_ohlc"]}')
            else:
                print(f'  FAIL {r["label"]:34} {r["error_type"]}: '
                      f'{r["error"][:60]}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
