"""阶段3B-6.1.0 任务1：10 个指数收益口径可行性审计（只读）。

**只读**：不写正式库、不改指数层。只做官方证据核查 + 实际接口调用 + 记录。

调用结果落到 ``.tmp610/raw/index_basis.json``，供报告生成使用。

用法：
    python scripts/audit_3b6_1_0_index_basis.py [--probe] [--out PATH]

不带 --probe 时只读已有探测结果，不联网。
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

RAW_DIR = ROOT / ".tmp610" / "raw"
DEFAULT_OUT = RAW_DIR / "index_basis.json"

# 10 个指数：代码、名称、发布机构、候选全收益/净收益变体
INDEX_CATALOG = [
    {"code": "000300", "name": "沪深300指数", "provider": "中证指数有限公司",
     "variants": {"price": "000300", "total": "H00300", "net": "N00300"}},
    {"code": "000905", "name": "中证小盘500指数", "provider": "中证指数有限公司",
     "variants": {"price": "000905", "total": "H00905", "net": "N00905"}},
    {"code": "000906", "name": "中证800指数", "provider": "中证指数有限公司",
     "variants": {"price": "000906", "total": "H00906", "net": "N00906"}},
    {"code": "000016", "name": "上证50指数", "provider": "中证指数有限公司",
     "variants": {"price": "000016", "total": "H00016", "net": "N00016"}},
    {"code": "399997", "name": "中证白酒指数", "provider": "中证指数有限公司",
     "variants": {"price": "399997", "total": None, "net": None}},
    {"code": "H30184", "name": "中证全指半导体产品与设备指数",
     "provider": "中证指数有限公司",
     "variants": {"price": "H30184", "total": None, "net": None}},
    {"code": "000942", "name": "中证内地消费主题指数",
     "provider": "中证指数有限公司",
     "variants": {"price": "000942", "total": "H00942", "net": None}},
    {"code": "000012", "name": "上证国债指数", "provider": "上海证券交易所",
     "variants": {"price": "000012", "total": "N00012", "net": "H00012"}},
    {"code": "000922", "name": "中证红利指数", "provider": "中证指数有限公司",
     "variants": {"price": "000922", "total": "H00922", "net": None}},
    {"code": "930930", "name": "中证港股通综合指数",
     "provider": "中证指数有限公司",
     "variants": {"price": "930930", "total": None, "net": None}},
]

SOURCE_AK = "akshare.stock_zh_index_hist_csindex"
PROBE_START = "20240102"
PROBE_END = "20240110"
HISTORY_START = "20040101"
HISTORY_END = "20261231"
SLEEP_SEC = 7


def _fetch(code: str, start: str, end: str):
    import akshare as ak
    return ak.stock_zh_index_hist_csindex(
        symbol=code, start_date=start, end_date=end)


def probe_one(code: str, start: str, end: str) -> dict:
    """实际调用一次接口，记录完整元数据。"""
    rec = {"request_code": code, "request_start": start, "request_end": end,
           "called_at": datetime.now().isoformat(timespec="seconds"),
           "source": SOURCE_AK, "status": None, "rows": 0,
           "index_code_returned": None, "index_name_returned": None,
           "date_min": None, "date_max": None, "duplicate_dates": 0,
           "null_close": 0, "sample": None, "error": None}
    try:
        df = _fetch(code, start, end)
    except Exception as exc:
        rec["status"] = "error"
        rec["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        return rec

    if df is None or len(df) == 0:
        rec["status"] = "empty"
        return rec

    rec["status"] = "ok"
    rec["rows"] = int(len(df))
    rec["index_code_returned"] = str(df.iloc[0].get("指数代码"))
    rec["index_name_returned"] = str(df.iloc[0].get("指数中文全称"))
    dates = [str(x) for x in df["日期"].tolist()]
    rec["date_min"] = dates[0]
    rec["date_max"] = dates[-1]
    rec["duplicate_dates"] = int(len(dates) - len(set(dates)))
    closes = df["收盘"].tolist()
    rec["null_close"] = int(sum(1 for c in closes if c is None))
    rec["sample"] = [{"date": dates[i], "close": float(closes[i])}
                     for i in range(min(3, len(dates)))]
    return rec


def run_probe() -> dict:
    """真实调用：逐指数、逐变体探测。"""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out = {"phase": "3B-6.1.0", "generated_at":
           datetime.now().isoformat(timespec="seconds"),
           "probe_window": [PROBE_START, PROBE_END],
           "source": SOURCE_AK, "call_count": 0, "indexes": []}

    for item in INDEX_CATALOG:
        entry = {"index_code": item["code"], "index_name": item["name"],
                 "provider": item["provider"], "variants": [],
                 "price": None, "total": None, "net": None}
        for kind, code in item["variants"].items():
            if not code:
                entry["variants"].append({"kind": kind, "request_code": None,
                                          "status": "not_found",
                                          "note": "未找到对应代码变体"})
                continue
            rec = probe_one(code, PROBE_START, PROBE_END)
            rec["kind"] = kind
            entry["variants"].append(rec)
            out["call_count"] += 1
            time.sleep(SLEEP_SEC)
        out["indexes"].append(entry)

    DEFAULT_OUT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    return out


def summarize() -> None:
    """打印审计摘要（不联网）。"""
    if not DEFAULT_OUT.exists():
        print("尚未探测，先跑 --probe")
        return
    doc = json.loads(DEFAULT_OUT.read_text(encoding="utf-8"))
    print(f'调用次数: {doc["call_count"]}')
    for e in doc["indexes"]:
        kinds = {}
        for v in e["variants"]:
            if v.get("status") == "ok":
                kinds[v["kind"]] = v["index_name_returned"]
        print(f'  {e["index_code"]:8} {e["index_name"][:22]:24} '
              f'{ {k: v[:16] for k, v in kinds.items()} }')


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="3B-6.1.0 指数口径审计")
    ap.add_argument("--probe", action="store_true", help="真实调用接口")
    args = ap.parse_args(argv)
    if args.probe:
        doc = run_probe()
        print(f'探测完成，调用 {doc["call_count"]} 次')
    summarize()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
