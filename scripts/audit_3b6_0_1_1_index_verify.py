"""阶段3B-6.0.1.1 逐个指数代码的历史数据验证与质量检查。

**真实调用**中证官网接口，对 INDEX_CATALOG 中全部代码逐一验证：
① 代码映射 ② 历史接口 ③ 数据质量 三步分开记录。

不写库、不落盘行情、不做批量采集。

用法：
    python scripts/audit_3b6_0_1_1_index_verify.py
    python scripts/audit_3b6_0_1_1_index_verify.py --json out.json
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

from app.fund.research.benchmark_audit import (  # noqa: E402
    EXTERNAL_INDEX_CATALOG, INDEX_CATALOG,
)
from app.fund.research.index_verify import (  # noqa: E402
    STATE_MEANING, fetch_csindex_history, verify_index_entry,
)

SLEEP_SEC = 1.5


def expected_tokens(family: str) -> list[str]:
    """预期名称关键词（用于核实代码 ↔ 名称映射）。"""
    table = {
        "沪深300": ["沪深300"],
        "中证500": ["中证500"],
        "中证800": ["中证800"],
        "上证50": ["上证50"],
        "中证白酒": ["白酒"],
        "中证全指半导体": ["半导体"],
        "中证内地消费主题": ["消费"],
        "上证国债": ["国债"],
        "中证红利": ["红利"],
        "中证港股通综合": ["港股通"],
    }
    return table.get(family, [family])


def run_csindex() -> list[dict]:
    out = []
    for family, node in INDEX_CATALOG.items():
        code = node["codes"]["csindex"]
        rec = verify_index_entry(family, code,
                                 expected_tokens=expected_tokens(family))
        out.append(rec)
        print(f'  {family:16} {code:8} {rec["final_state"]:24} '
              f'rows={rec["rows"]:5} {rec["date_min"]} ~ {rec["date_max"]}'
              + (f'  FAIL={rec["failure_reason"][:40]}'
                 if rec["failure_reason"] else ''))
        time.sleep(SLEEP_SEC)
    return out


def run_external() -> list[dict]:
    """恒生指数：新浪源，单独登记，标 partial。"""
    out = []
    for family, node in EXTERNAL_INDEX_CATALOG.items():
        ts = datetime.now().isoformat(timespec="seconds")
        rec = {
            "family": family, "code": node["code"],
            "source": node["source"], "checked_at": ts,
            "code_mapping_verified": False,
            "history_api_verified": False,
            "history_quality_verified": False,
            "rows": 0, "date_min": None, "date_max": None,
            "ohlc_available": False, "quality": None,
            "final_state": "unknown", "failure_reason": None,
            "catalog": "external_partial",
        }
        try:
            import akshare as ak
            df = ak.stock_hk_index_daily_sina(symbol=node["code"])
            from app.fund.research.index_verify import check_history_quality
            rec["history_api_verified"] = len(df) > 0
            rec["rows"] = int(len(df))
            q = check_history_quality(df)
            rec["quality"] = q
            rec["date_min"] = q.get("date_min")
            rec["date_max"] = q.get("date_max")
            rec["ohlc_available"] = bool(
                q["checks"]["no_null_ohlc"].get("has_ohlc_columns"))
            rec["history_quality_verified"] = bool(q.get("all_passed"))
            # 外部源无法用官方中文名核实映射，保守保持 False
            rec["code_mapping_verified"] = False
            rec["code_mapping_note"] = "新浪港股接口不返回指数中文名，无法核实映射"
            rec["final_state"] = ("history_quality_verified"
                                  if rec["history_quality_verified"]
                                  else "history_api_verified")
        except Exception as exc:
            rec["failure_reason"] = f"{type(exc).__name__}: {str(exc)[:150]}"
        out.append(rec)
        print(f'  {family:16} {node["code"]:8} {rec["final_state"]:24} '
              f'rows={rec["rows"]:5} {rec["date_min"]} ~ {rec["date_max"]}')
        time.sleep(SLEEP_SEC)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="3B-6.0.1.1 指数历史验证")
    ap.add_argument("--json", help="输出 JSON 路径")
    args = ap.parse_args(argv)

    print("== 中证官网逐指数验证 ==")
    csindex = run_csindex()
    print("== 外部源（恒生）==")
    external = run_external()

    doc = {
        "phase": "3B-6.0.1.1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "readonly": True,
        "database_written": False,
        "market_data_persisted": False,
        "state_meaning": STATE_MEANING,
        "csindex_entries": csindex,
        "external_entries": external,
        "summary": {
            "total": len(csindex) + len(external),
            "code_mapping_verified": sum(
                1 for r in csindex + external if r["code_mapping_verified"]),
            "history_api_verified": sum(
                1 for r in csindex + external if r["history_api_verified"]),
            "history_quality_verified": sum(
                1 for r in csindex + external if r["history_quality_verified"]),
            "unknown": sum(1 for r in csindex + external
                           if r["final_state"] == "unknown"),
        },
    }
    if args.json:
        Path(args.json).write_text(
            json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(doc["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
