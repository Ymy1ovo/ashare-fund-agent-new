"""阶段3B-6.1.0.1 任务4：生成仓库级可复现的指数探测证据附件。

**只读**：只调用公开行情接口，把结果写成仓库内的正式证据文件，
不写正式数据库、不改任何业务数据。

产物：``reports/evidence/phase3B6_1_0_index_probe_evidence.json``

用法：
    python scripts/build_3b6_1_0_1_evidence.py [--probe]

不带 --probe 时不联网，只做结构自检。
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

EVIDENCE_PATH = (ROOT / "reports" / "evidence"
                 / "phase3B6_1_0_index_probe_evidence.json")
SOURCE = "akshare.stock_zh_index_hist_csindex"
PROBE_START = "20240102"
PROBE_END = "20240110"
SLEEP_SEC = 7

# 10 个指数 + 各自实测到的变体（代码 → 语义标签）
INDEX_VARIANTS = [
    {"index_code": "000300", "index_name": "沪深300指数", "provider": "中证指数有限公司",
     "variants": [("000300", "price"), ("H00300", "total"), ("N00300", "net")]},
    {"index_code": "000905", "index_name": "中证小盘500指数", "provider": "中证指数有限公司",
     "variants": [("000905", "price"), ("H00905", "total"), ("N00905", "net")]},
    {"index_code": "000906", "index_name": "中证800指数", "provider": "中证指数有限公司",
     "variants": [("000906", "price"), ("H00906", "total"), ("N00906", "net")]},
    {"index_code": "000016", "index_name": "上证50指数", "provider": "中证指数有限公司",
     "variants": [("000016", "price"), ("H00016", "total"), ("N00016", "net")]},
    {"index_code": "399997", "index_name": "中证白酒指数", "provider": "中证指数有限公司",
     "variants": [("399997", "price"),
                  ("H39997", "guess_by_stock_convention"),   # 3B-6.1.0 的错误猜测
                  ("H20539", "total_official"),              # 官方 factsheet 披露
                  ("399997CNY02", "net_official")]},
    {"index_code": "H30184", "index_name": "中证全指半导体产品与设备指数",
     "provider": "中证指数有限公司",
     "variants": [("H30184", "price"),
                  ("H20184", "total_official")]},
    {"index_code": "000942", "index_name": "中证内地消费主题指数",
     "provider": "中证指数有限公司",
     "variants": [("000942", "price"), ("H00942", "total"), ("N00942", "net_attempt")]},
    {"index_code": "000012", "index_name": "上证国债指数", "provider": "上海证券交易所",
     "variants": [("000012", "full_price"), ("H00012", "clean_price"),
                  ("N00012", "interest_and_reinvestment")]},
    {"index_code": "000922", "index_name": "中证红利指数", "provider": "中证指数有限公司",
     "variants": [("000922", "price"), ("H00922", "total"),
                  ("000922CNY020", "net_official")]},
    {"index_code": "930930", "index_name": "中证港股通综合指数",
     "provider": "中证指数有限公司",
     "variants": [("930930", "price"),
                  ("H930930", "guess_by_stock_convention"),
                  ("H20930", "total_official")]},
]


def probe(code: str) -> dict:
    """单次探测，记录完整可复核元数据。"""
    rec = {
        "request_code": code, "request_start": PROBE_START,
        "request_end": PROBE_END, "source": SOURCE,
        "called_at": datetime.now().isoformat(timespec="seconds"),
        "status": None, "index_code_returned": None,
        "index_name_returned": None, "rows": 0,
        "date_min": None, "date_max": None, "duplicate_dates": 0,
        "null_close": 0, "non_positive_close": 0,
        "sample": [], "error": None,
    }
    try:
        import akshare as ak
        df = ak.stock_zh_index_hist_csindex(
            symbol=code, start_date=PROBE_START, end_date=PROBE_END)
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
    closes = df["收盘"].tolist()
    rec["date_min"] = dates[0]
    rec["date_max"] = dates[-1]
    rec["duplicate_dates"] = int(len(dates) - len(set(dates)))
    rec["null_close"] = int(sum(1 for c in closes if c is None))
    rec["non_positive_close"] = int(
        sum(1 for c in closes if c is not None and c <= 0))
    rec["sample"] = [
        {"date": dates[i],
         "close": (None if closes[i] is None else round(float(closes[i]), 4))}
        for i in range(min(3, len(dates)))]
    return rec


def run() -> dict:
    doc = {
        "phase": "3B-6.1.0.1",
        "purpose": "指数探测证据附件（供仓库级测试复核，不依赖本地缓存）",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": SOURCE,
        "probe_window": [PROBE_START, PROBE_END],
        "note": ("仅保留元数据与 3 条样例收盘值；"
                 "不包含完整行情序列，不含任何密钥或个人信息"),
        "call_count": 0,
        "indexes": [],
        "same_day_comparison": {},
        "correction_of_prior_audit": {
            "prior_conclusion_3b6_1_0": "399997/H30184/930930 无全收益序列",
            "why_wrong": ("3B-6.1.0 按「H+后5位」的股票指数命名惯例猜测代码"
                           "（H39997/H30930），全部返回空，据此误判为「不存在」。"),
            "actual_finding": ("中证官方 factsheet 的「衍生指数」栏披露了真实代码："
                                "399997→H20539（全收益）/ 399997CNY02（净收益）；"
                                "H30184→H20184（全收益）；"
                                "930930→H20930（全收益）；"
                                "000922→000922CNY020（净收益）。"),
            "lesson": "不得按代码前缀惯例推断官方衍生指数代码，必须以官方文件为准。",
        },
    }

    for item in INDEX_VARIANTS:
        entry = {"index_code": item["index_code"],
                 "index_name": item["index_name"],
                 "provider": item["provider"], "variants": []}
        for code, semantic in item["variants"]:
            rec = probe(code)
            rec["semantic"] = semantic
            entry["variants"].append(rec)
            doc["call_count"] += 1
            time.sleep(SLEEP_SEC)
        doc["indexes"].append(entry)

    # 同日对比：价格 vs 全收益 vs 净价 vs 利息再投资
    def first_close(idx_code, variant_code):
        for e in doc["indexes"]:
            if e["index_code"] != idx_code:
                continue
            for v in e["variants"]:
                if (v["request_code"] == variant_code
                        and v["status"] == "ok" and v["sample"]):
                    return v["sample"][0]
        return None

    doc["same_day_comparison"] = {
        "date": "2024-01-02",
        "csi300_price_vs_total": {
            "price": {"code": "000300", "close": first_close("000300", "000300")},
            "total": {"code": "H00300", "close": first_close("000300", "H00300")},
            "note": "价格与全收益是不同序列，数值必然不同",
        },
        "sh_gov_bond_three_variants": {
            "000012": {"semantic": "full_price",
                        "close": first_close("000012", "000012")},
            "H00012": {"semantic": "clean_price",
                        "close": first_close("000012", "H00012")},
            "N00012": {"semantic": "interest_and_reinvestment",
                        "close": first_close("000012", "N00012")},
            "note": ("H 前缀在上证国债指数代表**净价**，不是全收益；"
                     "N 前缀才是利息及再投资。不能套用股票指数惯例。"),
        },
    }

    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(
        json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return doc


def selfcheck() -> int:
    """不联网的结构自检。"""
    if not EVIDENCE_PATH.exists():
        print("证据文件不存在，请先跑 --probe")
        return 1
    doc = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    print(f'indexes={len(doc["indexes"])} calls={doc["call_count"]}')
    for e in doc["indexes"]:
        ok = [v["semantic"] for v in e["variants"] if v["status"] == "ok"]
        print(f'  {e["index_code"]:8} {ok}')
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="3B-6.1.0.1 证据附件生成")
    ap.add_argument("--probe", action="store_true")
    args = ap.parse_args(argv)
    if args.probe:
        doc = run()
        print(f'生成完成：{doc["call_count"]} 次调用 -> {EVIDENCE_PATH}')
    return selfcheck()


if __name__ == "__main__":
    raise SystemExit(main())
