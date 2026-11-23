"""CLI 入口：python -m app.fund.research

只读分析，不写库、不采集、不排名、不出信号。

用法：
    python -m app.fund.research --list            # 列出研究池
    python -m app.fund.research --code 110022     # 分析单只基金
    python -m app.fund.research --all             # 分析全部研究池
    python -m app.fund.research --all --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.fund.research.data_access import load_universe
from app.fund.research.engine import analyze_by_code, analyze_universe


def _json_default(o):
    if isinstance(o, (set, tuple)):
        return list(o)
    return str(o)


def cmd_list(args) -> int:
    universe = load_universe()
    print(f"研究池：{len(universe)} 个份额 / "
          f"{len({e['fund_id'] for e in universe})} 个基金本体")
    print()
    print(f"{'份额代码':10} {'本体':8} {'产品分类':16} {'子类型':10} {'同类组':32} 名称")
    print("-" * 108)
    for e in universe:
        print(f"{e['share_code']:10} {e['fund_code']:8} "
              f"{e['product_class']:16} {str(e['investment_subtype']):10} "
              f"{e['peer_group']['peer_key']:32} {e['fund_name'][:24]}")
    return 0


def cmd_code(args) -> int:
    """按代码直接查库（不再限于默认研究池）。"""
    report = analyze_by_code(args.code)
    text = json.dumps(report, ensure_ascii=False, indent=1, default=_json_default)
    if args.json:
        Path(args.json).write_text(text, encoding="utf-8")
        print(f"JSON -> {args.json}")
    else:
        print(text)
    if report["status"] != "found":
        print(f"\n状态：{report['status']} —— {report['reason']}", file=sys.stderr)
        return 2 if report["status"] in ("not_found", "invalid_code") else 3
    m = report.get("merged") or {}
    print(f"\n基金本体 {m.get('fund_code')} {m.get('fund_name')}")
    print(f"份额数：{report.get('share_count')}  代表份额：{m.get('representative_share')}")
    return 0


def _read_codes_file(path: str) -> tuple[list[str], list[str]]:
    """读取代码文件：一行一个。返回 (有效代码, 问题说明)。"""
    p = Path(path)
    if not p.is_file():
        return [], [f"文件不存在：{path}"]
    problems = []
    codes = []
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        c = line.strip()
        if not c or c.startswith("#"):
            continue
        if not c.isdigit() or len(c) != 6:
            problems.append(f"第 {i} 行非法代码已跳过：{c[:20]}")
            continue
        codes.append(c)
    return codes, problems


def cmd_codes_file(args) -> int:
    """批量查询：逐只报告，单只失败不影响其他基金。"""
    codes, problems = _read_codes_file(args.codes_file)
    results = []
    seen = set()
    duplicates = []
    for c in codes:
        if c in seen:
            duplicates.append(c)
            continue
        seen.add(c)
        try:
            r = analyze_by_code(c)
        except Exception as exc:  # 单只失败不得中断
            r = {"phase": "3B-5.2",
                 "query": {"code": c, "by": "auto"},
                 "status": "error",
                 "reason": f"分析异常：{type(exc).__name__}: {exc}",
                 "fund_entity": None, "reports": [], "merged": None}
        results.append(r)

    summary = {}
    for r in results:
        summary[r["status"]] = summary.get(r["status"], 0) + 1

    doc = {
        "phase": "3B-5.2",
        "source_file": str(args.codes_file),
        "requested_codes": codes,
        "unique_codes": list(seen),
        "duplicates": duplicates,
        "file_problems": problems,
        "result_count": len(results),
        "status_summary": summary,
        "results": results,
        "gate": {
            "ready_for_research_analysis": True,
            "ready_for_backtest": False,
            "ready_for_formal_ranking": False,
        },
    }
    text = json.dumps(doc, ensure_ascii=False, indent=1, default=_json_default)
    if args.json:
        Path(args.json).write_text(text, encoding="utf-8")
        print(f"JSON -> {args.json}")
    else:
        print(text)

    print(f"\n批量查询：{len(results)} 只（去重后）")
    for r in results:
        ent = r.get("fund_entity") or {}
        print(f"  {r['query']['code']:8} {r['status']:18} "
              f"{str(ent.get('fund_name'))[:20]:22} 份额 {ent.get('share_count', 0)}")
    if duplicates:
        print(f"重复代码已合并：{duplicates}")
    if problems:
        for x in problems:
            print(x, file=sys.stderr)
    return 0 if results else 2


def cmd_all(args) -> int:
    result = analyze_universe()
    text = json.dumps(result, ensure_ascii=False, indent=1, default=_json_default)
    out = Path(args.json) if args.json else None
    if out:
        out.write_text(text, encoding="utf-8")
        print(f"JSON -> {out}")
    else:
        print(text)
    u = result["universe"]
    print(f"\n研究池：{u['share_count']} 份额 / {u['fund_count']} 本体")
    print(f"产品分类：{json.dumps(u['by_product_class'], ensure_ascii=False)}")
    print(f"同类组：{result['peer_analysis']['group_count']} 个")
    print(f"门禁：研究分析={result['gate']['ready_for_research_analysis']} "
          f"回测={result['gate']['ready_for_backtest']} "
          f"排名={result['gate']['ready_for_formal_ranking']}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m app.fund.research",
        description="支付宝场外公募基金研究性分析引擎（只读，不排名不出信号）")
    ap.add_argument("--list", action="store_true", help="列出研究池")
    ap.add_argument("--code", help="分析单只基金（份额代码或本体代码）")
    ap.add_argument("--all", action="store_true", help="分析全部研究池")
    ap.add_argument("--codes-file",
                    help="批量查询代码文件（一行一个 6 位代码）")
    ap.add_argument("--json", help="结果写入 JSON 文件")
    args = ap.parse_args(argv)

    if args.list:
        return cmd_list(args)
    if args.code:
        return cmd_code(args)
    if args.all:
        return cmd_all(args)
    if args.codes_file:
        return cmd_codes_file(args)
    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
