"""抓取官方公司行为数据（只读，供核查使用）。

来源：天天基金「分红送配」页（东方财富 Choice 数据）
      https://fundf10.eastmoney.com/fhsp_<code>.html

输出：data/corporate_action_all46.json（运行产物，不进 Git）

纪律：
- 只抓取公开数据，不写数据库。
- 抓取结果必须与券商公告交叉验证后才可标记 confirmed；
  本脚本不自动写入企业行为表，写入由 seed_corporate_actions.py 负责。
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
SOURCE = "https://fundf10.eastmoney.com/fhsp_{code}.html"


def fetch(code: str, name: str) -> dict:
    url = SOURCE.format(code=code)
    req = urllib.request.Request(url, headers=HEADERS)
    html = urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "ignore")
    splits = re.findall(
        r"<td[^>]*>\s*(\d{4})年\s*</td>\s*<td[^>]*>\s*(\d{4}-\d{2}-\d{2})\s*</td>\s*"
        r"<td[^>]*>\s*([^<]*?)\s*</td>\s*<td[^>]*>\s*1:([\d.]+)\s*</td>", html)
    divs = re.findall(
        r"<td[^>]*>\s*(\d{4})年\s*</td>\s*<td[^>]*>\s*(\d{4}-\d{2}-\d{2})\s*</td>\s*"
        r"<td[^>]*>\s*(\d{4}-\d{2}-\d{2})\s*</td>\s*<td[^>]*>\s*每10份派现金([\d.]+)元\s*</td>\s*"
        r"<td[^>]*>\s*(\d{4}-\d{2}-\d{2})\s*</td>", html)
    return {
        "name": name,
        "source": url,
        "splits": [{"date": d, "type": t, "ratio": float(r)} for _, d, t, r in splits],
        "dividends": [
            {"record_date": rd, "ex_date": ed, "per10": float(a), "pay_date": p}
            for _, rd, ed, a, p in divs
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="抓取官方公司行为数据（只读）")
    parser.add_argument("--db", default="data/fund_agent.db")
    parser.add_argument("--out", default="data/corporate_action_all46.json")
    parser.add_argument("--sleep", type=float, default=0.35)
    args = parser.parse_args()

    db = PROJECT_ROOT / args.db
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    codes = [(r[0], r[1]) for r in conn.execute("SELECT code, name FROM etf_pool ORDER BY code")]
    print(f"待抓取 {len(codes)} 只")

    out: dict = {}
    for index, (code, name) in enumerate(codes, 1):
        try:
            out[code] = fetch(code, name)
        except Exception as exc:  # noqa: BLE001 单只失败不阻断
            out[code] = {"name": name, "error": f"{type(exc).__name__}: {exc}"}
            print(f"  [{index}/{len(codes)}] {code} ERR")
            continue
        ns = len(out[code]["splits"])
        nd = len(out[code]["dividends"])
        if ns or nd:
            print(f"  [{index}/{len(codes)}] {code} {name[:16]:16s} splits={ns} divs={nd}")
        time.sleep(args.sleep)

    path = PROJECT_ROOT / args.out
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    errors = sum(1 for value in out.values() if "error" in value)
    print(f"\n已保存 {path}（失败 {errors} 只）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
