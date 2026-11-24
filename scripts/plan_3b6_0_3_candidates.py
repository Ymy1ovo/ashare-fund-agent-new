"""阶段3B-6.0.3 第二步：按明确规则从全市场名单里筛候选基金。

规则（全部可复核）：
1. 只取场外可申购基金（排除场内 ETF 代码）；
2. 六类分别筛选，类别判定复用 3B-5.0 分类规则；
3. 目标：主要同类组 ≥5 本体，条件允许争取 ≥10；
4. **不按近期业绩排序**——只按成立时间（历史覆盖）与代码稳定排序，
   避免人为制造幸存者偏差；
5. 每类留出冗余候选，接入失败可替换。

纯只读：只读全市场名单接口，不写库。

用法：
    python scripts/plan_3b6_0_3_candidates.py --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.fund.research.classification import (      # noqa: E402
    classify_fund, index_scope, is_offmarket_pool,
)

# 每类目标接入数量（含冗余）
TARGETS = {
    "ordinary_index": {"沪深300": 4, "中证500": 4, "上证50": 2,
                       "中证A500": 3, "创业板指": 2, "科创50": 2},
    "etf_linked": {"沪深300": 4, "中证500": 4, "上证50": 2,
                   "中证A500": 3, "创业板指": 2, "科创50": 2},
    "active_equity": {"__any__": 8},
    "bond_pure": {"__any__": 8},
    "bond_mixed": {"__any__": 6},
    "money_market": {"__any__": 6},
    "lof": {"__any__": 6},
}

# 指数族关键词 → 归一化族名
FAMILY_PATTERNS = (
    ("中证A500", ("中证A500", "A500")),
    ("沪深300", ("沪深300",)),
    ("中证500", ("中证500",)),
    ("中证1000", ("中证1000",)),
    ("上证50", ("上证50",)),
    ("创业板指", ("创业板",)),
    ("科创50", ("科创50", "科创板50")),
    ("中证800", ("中证800",)),
)

BOND_MIXED_HINTS = ("二级", "转债", "可转债")

# 份额后缀：同一基金本体的不同份额代码必须归并，不能各占一个候选名额
_SHARE_SUFFIX_RE = None


def base_fund_name(name: str) -> str:
    """剥离份额后缀，得到基金本体基础名。

    A/C/E/I/B/R 等只是**份额类别**，不是独立基金。
    候选阶段就按基础名去重，接入后还会再按 fund_id 归并一次（双保险）。
    """
    import re
    n = str(name or "").strip()
    n = re.sub(r"[（(]后端[）)]", "", n)
    n = re.sub(r"[（(]LOF[）)]", "(LOF)", n)
    # 末尾单个字母份额标记
    n = re.sub(r"(人民币|美元|美元现汇|美元现钞)$", "", n)
    n = re.sub(r"[A-Za-z]$", "", n)
    n = re.sub(r"[（(][^）)]{0,4}[）)]$", "", n)
    return n.strip()


def detect_index_family(name: str) -> str:
    for fam, pats in FAMILY_PATTERNS:
        if any(p in name for p in pats):
            return fam
    return "unknown"


def load_all_funds() -> list[dict]:
    import akshare as ak
    df = ak.fund_name_em()
    df.columns = ["code", "pinyin_abbr", "name", "type", "pinyin"]
    out = []
    for _, r in df.iterrows():
        out.append({"code": str(r["code"]).zfill(6),
                    "name": str(r["name"]).strip(),
                    "type": str(r["type"]).strip()})
    return out


def classify_row(f: dict) -> dict:
    row = {"fund_name": f["name"], "fund_type_l1": f["type"],
           "fund_type_l2": f["type"],
           "is_index_fund": (1 if "指数" in f["type"] else None)}
    cls = classify_fund(row)
    return cls


def pick_candidates(funds: list[dict]) -> dict:
    """按规则挑候选，**不按业绩排序**。"""
    picked = defaultdict(list)
    seen_codes = set()
    base_seen = set()
    for f in sorted(funds, key=lambda x: x["code"]):
        code, name, typ = f["code"], f["name"], f["type"]
        if code in seen_codes:
            continue
        if not is_offmarket_pool({"product_class": "unknown",
                                  "in_default_pool": True}, code):
            continue
        cls = classify_row(f)
        pc = cls["product_class"]
        if not is_offmarket_pool(cls, code):
            continue

        # 债券细分：混合债券单列
        if pc == "bond_pure" and any(h in typ for h in BOND_MIXED_HINTS):
            pc = "bond_mixed"

        # 债券/货币/主动权益/LOF 用 __any__ 桶
        fam = detect_index_family(name) if pc in (
            "ordinary_index", "etf_linked") else "__any__"
        if fam == "unknown" and pc in ("ordinary_index", "etf_linked"):
            continue

        targets = TARGETS.get(pc) or {}
        limit = targets.get(fam) or targets.get("__any__")
        if not limit:
            continue
        if len(picked[(pc, fam)]) >= limit:
            continue

        # 排除明显不适合的（名称含 C 类等不影响，A/C 归组在接入时按 fund_id 处理）
        bkey = (pc, base_fund_name(name))
        if bkey in base_seen:
            continue          # 同一基金本体的其他份额，跳过
        base_seen.add(bkey)

        picked[(pc, fam)].append({
            "code": code, "name": name, "fund_type": typ,
            "product_class": pc, "index_family": fam,
            "index_scope": (index_scope(name)
                            if pc in ("ordinary_index", "etf_linked")
                            else None),
            "classify_basis": cls.get("basis"),
        })
        seen_codes.add(code)
    return {f"{k[0]}|{k[1]}": v for k, v in picked.items()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="3B-6.0.3 候选筛选")
    ap.add_argument("--json", help="输出 JSON 路径")
    args = ap.parse_args(argv)

    funds = load_all_funds()
    picked = pick_candidates(funds)

    total = sum(len(v) for v in picked.values())
    doc = {"phase": "3B-6.0.3", "step": "2_candidate_plan",
           "generated_at": datetime.now().isoformat(timespec="seconds"),
           "readonly": True, "database_written": False,
           "market_universe_size": len(funds),
           "selection_rule": ("按成立时间/代码稳定排序，**不按近期业绩排序**，"
                              "避免幸存者偏差"),
           "bucket_count": len(picked), "candidate_total": total,
           "candidates": picked}

    print(f"全市场名单: {len(funds)}")
    print(f"分类桶: {len(picked)}  候选合计: {total}")
    print()
    for k in sorted(picked):
        print(f'  {k:32} {len(picked[k]):2}')
    print()
    for k in sorted(picked):
        print(f'== {k} ==')
        for c in picked[k]:
            print(f'  {c["code"]} {c["name"][:26]:28} {c["fund_type"][:14]:16} '
                  f'{c["index_family"] or c["index_scope"] or ""}')

    if args.json:
        Path(args.json).write_text(
            json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
