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
from app.fund.research.engine import analyze_fund, analyze_universe


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
    universe = load_universe()
    target = [e for e in universe if e["share_code"] == args.code
              or e["fund_code"] == args.code]
    if not target:
        print(f"未找到 {args.code}（可能不在场外研究池，或代码不存在）",
              file=sys.stderr)
        return 2
    entry = target[0]
    report = analyze_fund(None, entry)
    text = json.dumps(report, ensure_ascii=False, indent=1, default=_json_default)
    if args.json:
        Path(args.json).write_text(text, encoding="utf-8")
        print(f"JSON -> {args.json}")
    else:
        print(text)
    return 0


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
    ap.add_argument("--json", help="结果写入 JSON 文件")
    args = ap.parse_args(argv)

    if args.list:
        return cmd_list(args)
    if args.code:
        return cmd_code(args)
    if args.all:
        return cmd_all(args)
    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
