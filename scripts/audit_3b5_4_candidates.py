"""阶段3B-5.4 候选样本只读审计。

只调用已审计的 AKShare 接口，不写任何数据库。

用法：
    python scripts/audit_3b5_4_candidates.py --codes 050002,001052,001938
    python scripts/audit_3b5_4_candidates.py --codes-file codes.txt --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.fund.ingest_user_funds._impl import SOURCE_BASIC  # noqa: E402
from app.fund.research.classification import (  # noqa: E402
    classify_fund, is_offmarket_pool,
)
from app.fund.research.lookup import validate_code  # noqa: E402


def _basic(code: str) -> dict:
    import akshare as ak
    df = ak.fund_individual_basic_info_xq(symbol=code)
    return {str(r["item"]).strip(): str(r["value"]).strip()
            for _, r in df.iterrows()}


def _nav(code: str) -> dict:
    import akshare as ak
    out = {}
    for key, ind in (("unit", "单位净值走势"), ("acc", "累计净值走势")):
        try:
            df = ak.fund_open_fund_info_em(symbol=code, indicator=ind)
            out[key] = {"rows": int(len(df)),
                        "date_min": str(df.iloc[0, 0]) if len(df) else None,
                        "date_max": str(df.iloc[-1, 0]) if len(df) else None}
        except Exception as exc:
            out[key] = {"rows": 0, "error": f"{type(exc).__name__}: {exc}"[:120]}
    return out


def _money(code: str) -> dict:
    import akshare as ak
    try:
        df = ak.fund_money_fund_info_em(symbol=code)
        return {"rows": int(len(df)),
                "date_min": str(df.iloc[0, 0]) if len(df) else None,
                "date_max": str(df.iloc[-1, 0]) if len(df) else None}
    except Exception as exc:
        return {"rows": 0, "error": f"{type(exc).__name__}: {exc}"[:120]}


def audit_one(code: str) -> dict:
    got_at = datetime.now().isoformat(timespec="seconds")
    ok, why_code = validate_code(code)
    if not ok:
        return {"code": code, "status": "invalid_code",
                "reason": why_code, "fetched_at": got_at}
    b = _basic(code)
    name = b.get("基金名称") or ""
    ftype = b.get("基金类型") or ""
    if not name:
        return {"code": code, "status": "not_found", "fetched_at": got_at}

    # 与接入路径完全一致：类型字段含「指数」即 is_index_fund=1
    is_idx = 1 if "指数" in ftype else None
    cls = classify_fund({"fund_name": name, "fund_type_l1": ftype,
                         "fund_type_l2": ftype, "is_index_fund": is_idx,
                         "benchmark": b.get("业绩比较基准")})
    offmarket = is_offmarket_pool(cls, code)
    why = None if offmarket else "场内 ETF / QDII 不在场外默认范围"

    is_money = cls["product_class"] == "money_market"
    nav = {} if is_money else _nav(code)
    money = _money(code) if is_money else {}

    return {
        "code": code,
        "status": "ok" if offmarket else "excluded_product",
        "exclude_reason": None if offmarket else why,
        "name": name,
        "company": b.get("基金公司"),
        "type_field": ftype,
        "benchmark": b.get("业绩比较基准"),
        "established": b.get("成立时间"),
        "offmarket": offmarket,
        "product_class": cls["product_class"],
        "investment_subtype": cls["investment_subtype"],
        "source": SOURCE_BASIC,
        "fetched_at": got_at,
        "nav": nav,
        "money": money,
        "has_history_nav": bool(
            (nav.get("unit") or {}).get("rows") or (money or {}).get("rows")),
        "ac_identifiable": name.rstrip().endswith(("A", "C", "E")),
        "quality_notes": [],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="3B-5.4 候选样本只读审计")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--codes", help="逗号分隔的 6 位代码")
    g.add_argument("--codes-file", help="每行一个代码的文件")
    ap.add_argument("--json", help="输出 JSON 路径")
    a = ap.parse_args(argv)

    if a.codes:
        codes = [c.strip() for c in a.codes.split(",") if c.strip()]
    else:
        codes = [ln.strip() for ln in
                 Path(a.codes_file).read_text(encoding="utf-8").splitlines()
                 if ln.strip() and not ln.strip().startswith("#")]

    rows = []
    for c in codes:
        try:
            rows.append(audit_one(c))
        except Exception as exc:
            rows.append({"code": c, "status": "failed",
                         "reason": f"{type(exc).__name__}: {exc}"[:160]})
    doc = {"phase": "3B-5.4", "readonly": True,
           "database_written": False, "results": rows}
    if a.json:
        Path(a.json).write_text(
            json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in rows:
        print(f'{r.get("code")} {r.get("status"):18} '
              f'{str(r.get("product_class")):16} {str(r.get("name"))[:24]}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
