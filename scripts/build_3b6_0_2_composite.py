"""阶段3B-6.0.2 复合基准结构入库（只建结构与校验，不算收益）。

数据来源：3B-6.0.1 审计解析出的基准文字 + 成分权重。
证据等级一律 ``platform``（库内 benchmark 是第三方转述，非合同原文）。
缺权重/缺数据的成分如实记录，**不补造**。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.fund.benchmark_component_spec import BENCHMARK_SPECS  # noqa: E402
from app.fund.composite_benchmark import (                     # noqa: E402
    COMPONENT_CASH, COMPONENT_FIXED, COMPONENT_INDEX, COMPONENT_BOND,
    add_component, create_composite, evaluate_composite,
)
from app.fund.index_layer import get_index_connection             # noqa: E402

TYPE_MAP = {"index": COMPONENT_INDEX, "bond_index": COMPONENT_BOND,
            "cash": COMPONENT_CASH, "fixed_rate": COMPONENT_FIXED}

# 指数族 → 已接入的指数代码
FAMILY_TO_CODE = {
    "沪深300": "000300", "中证500": "000905", "中证800": "000906",
    "上证50": "000016", "中证白酒": "399997",
    "中证全指半导体": "H30184", "中证内地消费主题": "000942",
    "上证国债": "000012", "中证红利": "000922",
    "中证港股通综合": "930930",
}


def main(argv=None) -> int:
    doc = {"phase": "3B-6.0.2", "part": "composite_benchmark",
           "generated_at": datetime.now().isoformat(timespec="seconds"),
           "evidence_source": "platform",
           "note": ("库内 benchmark 来自第三方接口转述，未核对合同原文，"
                    "故证据等级统一为 platform"),
           "composites": []}

    with get_index_connection() as conn:
        conn.execute("DELETE FROM benchmark_composite_component")
        conn.execute("DELETE FROM benchmark_composite")
        for spec in BENCHMARK_SPECS:
            cid = create_composite(
                conn, benchmark_name=spec["fund_code"] + " " + spec["fund_name"],
                benchmark_raw_text=spec["benchmark_raw"],
                evidence_source="platform")
            comps_out = []
            for comp in spec["components"]:
                ctype = TYPE_MAP[comp["component_type"]]
                code = (FAMILY_TO_CODE.get(comp.get("family"))
                        if ctype == COMPONENT_INDEX else None)
                weight = comp.get("weight")
                add_component(
                    conn, cid, component_type=ctype,
                    component_label=comp.get("family") or comp["component_type"],
                    index_code=code, weight=weight,
                    weight_evidence=("来自库内 benchmark 文字中的百分比"
                                     if weight is not None else None))
                comps_out.append({"type": ctype, "label": comp.get("family"),
                                  "index_code": code, "weight": weight})
            verdict = evaluate_composite(conn, cid)
            doc["composites"].append({
                "composite_id": cid, "fund_code": spec["fund_code"],
                "fund_name": spec["fund_name"],
                "benchmark_raw": spec["benchmark_raw"],
                "components": comps_out,
                **verdict})
            print(f'  {spec["fund_code"]} {spec["fund_name"][:16]:18} '
                  f'成分={len(comps_out)} 完整={verdict["is_complete"]} '
                  f'可复现={verdict["is_reproducible"]}')

        total = conn.execute(
            "SELECT COUNT(*) FROM benchmark_composite").fetchone()[0]
        repro = conn.execute(
            "SELECT COUNT(*) FROM benchmark_composite "
            "WHERE is_reproducible=1").fetchone()[0]
        complete = conn.execute(
            "SELECT COUNT(*) FROM benchmark_composite "
            "WHERE is_complete=1").fetchone()[0]

    doc["summary"] = {"total_composites": total,
                      "is_complete": complete,
                      "is_reproducible": repro}
    print()
    print(json.dumps(doc["summary"], ensure_ascii=False))
    out = ROOT / ".tmp602" / "composite.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
