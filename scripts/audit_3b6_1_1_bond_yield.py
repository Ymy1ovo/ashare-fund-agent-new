"""阶段3B-6.1.1 中债国债收益率数据源只读审计。

**只读**：调用公开接口，把原始响应与审计元数据写入
``reports/evidence/phase3B6_1_1/``，不写正式数据库、不改任何业务代码。

实测约束（本轮验证得出，不是猜测）：
- 接口参数必须为 ``YYYYMMDD``（传 ``YYYY-MM-DD`` 会 ``No tables found``）
- **单次请求跨度上限约 1 年**（跨 2 年返回 0 行，跨 1 年正常）
- 历史起点 **2006-03-01**，2002~2005 全部返回 0 行
- 期限列只有 ``3月/6月/1年/3年/5年/7年/10年/30年``，**没有 2 年**

用法::

    python scripts/audit_3b6_1_1_bond_yield.py --fetch
    python scripts/audit_3b6_1_1_bond_yield.py --verify
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EVIDENCE_DIR = ROOT / "reports" / "evidence" / "phase3B6_1_1"
RAW_DIR = EVIDENCE_DIR / "raw"

SOURCE = "akshare.bond_china_yield"
PROVIDER = "中债金融估值中心（中债登）"
CURVE_GOV = "中债国债收益率曲线"

# 接口实际提供的期限列（**无 2 年**）
TENORS_ACTUAL = ["3月", "6月", "1年", "3年", "5年", "7年", "10年", "30年"]
TENORS_REQUESTED = ["3月", "6月", "1年", "2年", "3年", "5年", "7年", "10年",
                    "30年"]
TENORS_MISSING = ["2年"]

# 实测单次跨度上限约 1 年 → 按半年分段（已验证 42 段全部非空）
PROBE_YEARS_EMPTY = [2002, 2003, 2004, 2005]
HISTORY_START_EXPECTED = "2006-03-01"
SLEEP_SEC = 2


def _safe(x):
    if x is None:
        return None
    if isinstance(x, (int, float, str, bool)):
        return x
    try:
        import math
        f = float(x)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return str(x)


def half_year_segments(start_year: int, end_year: int):
    for y in range(start_year, end_year + 1):
        yield (f"{y}0101", f"{y}0630")
        yield (f"{y}0701", f"{y}1231")


def fetch_segment(start: str, end: str) -> dict:
    rec = {
        "request": {"source": SOURCE, "provider": PROVIDER,
                     "curve": CURVE_GOV,
                     "start_date": start, "end_date": end},
        "called_at": datetime.now().isoformat(timespec="seconds"),
        "status": None, "rows": 0, "columns": [],
        "error": None, "raw_files": [],
    }
    try:
        import akshare as ak
        df = ak.bond_china_yield(start_date=start, end_date=end)
    except Exception as exc:
        rec["status"] = "error"
        rec["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        return rec

    if df is None or len(df) == 0:
        rec["status"] = "empty"
        return rec

    rec["status"] = "ok"
    rec["rows"] = int(len(df))
    rec["columns"] = [str(c) for c in df.columns]

    curve_col = next((c for c in df.columns if "曲线名称" in str(c)), None)
    curves = sorted({str(v) for v in df[curve_col].tolist()}) if curve_col else []
    rec["curves_present"] = curves
    gov = df[df[curve_col].astype(str).str.contains("国债", na=False)] if curve_col else df
    rec["gov_rows"] = int(len(gov))
    rec["sample"] = [
        {str(k): _safe(v) for k, v in row.items()}
        for row in gov.head(2).to_dict(orient="records")
    ]

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    fn = RAW_DIR / f"bond_gov_{start}_{end}.csv"
    gov.to_csv(fn, index=False, encoding="utf-8-sig")
    raw = fn.read_bytes()
    rec["raw_files"].append({
        "file": fn.name, "bytes": len(raw),
        "sha256_16": hashlib.sha256(raw).hexdigest()[:16],
        "rows": int(len(gov)),
    })
    return rec


def run_fetch() -> dict:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    doc = {
        "phase": "3B-6.1.1",
        "purpose": "中债国债收益率曲线只读审计证据",
        "source": SOURCE, "provider": PROVIDER, "curve": CURVE_GOV,
        "tranche": "task1_task2",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "interface_constraints": {
            "date_format": "YYYYMMDD（YYYY-MM-DD 会 No tables found）",
            "max_span_per_request": "约 1 年（跨 2 年返回 0 行）",
            "tenors_actual": TENORS_ACTUAL,
            "tenors_requested": TENORS_REQUESTED,
            "tenors_missing": TENORS_MISSING,
            "history_start_observed": HISTORY_START_EXPECTED,
            "years_probed_empty": PROBE_YEARS_EMPTY,
        },
        "note": ("仅调用公开接口；不写正式数据库；"
                  "不含密钥或个人信息"),
        "segments": [],
        "empty_probe": [],
    }

    # 1) 探测 2002~2005 是否可得的实证记录
    for y in PROBE_YEARS_EMPTY:
        rec = fetch_segment(f"{y}0101", f"{y}1231")
        doc["empty_probe"].append({
            "year": y, "status": rec["status"], "rows": rec["rows"],
            "error": rec["error"],
        })
        print(f"probe {y}: {rec['status']} rows={rec['rows']}")
        time.sleep(SLEEP_SEC)

    # 2) 2006 年起按半年分段拉全历史
    for start, end in half_year_segments(2006, 2026):
        rec = fetch_segment(start, end)
        doc["segments"].append(rec)
        print(f"[{start}~{end}] {rec['status']} rows={rec['rows']}")
        time.sleep(SLEEP_SEC)

    out = EVIDENCE_DIR / "bond_yield_raw_audit.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n证据写入 {out}")
    return doc


def verify() -> int:
    p = EVIDENCE_DIR / "bond_yield_raw_audit.json"
    if not p.exists():
        print("证据文件不存在，请先跑 --fetch")
        return 1
    doc = json.loads(p.read_text(encoding="utf-8"))
    ok = [s for s in doc["segments"] if s["status"] == "ok"]
    total = sum(s["rows"] for s in ok)
    print(f"segments={len(doc['segments'])} ok={len(ok)} "
          f"total_rows_with_dup={total} "
          f"raw_files={sum(len(s['raw_files']) for s in doc['segments'])}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="3B-6.1.1 中债国债收益率审计")
    ap.add_argument("--fetch", action="store_true")
    args = ap.parse_args(argv)
    if args.fetch:
        run_fetch()
    return verify()


if __name__ == "__main__":
    raise SystemExit(main())
