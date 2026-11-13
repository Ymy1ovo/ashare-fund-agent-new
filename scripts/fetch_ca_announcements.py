"""抓取基金管理人原始公告，为每条公司行为事件建立独立证据。

来源：东方财富基金公告接口（转载基金管理人公告全文）
  https://api.fund.eastmoney.com/f10/JJGG            公告列表
  https://np-cnotice-fund.eastmoney.com/api/content/ann   公告正文

纪律：
- 只读，不写数据库。
- 每条事件保留独立公告 ID、标题、日期、正文摘要。
- 解析不出关键要素的事件保持未匹配，不得推断补齐。
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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://fundf10.eastmoney.com/",
}
# type=2 是「分红送配」类公告（分红 / 收益分配 / 份额拆分 / 份额折算）
LIST_API = ("https://api.fund.eastmoney.com/f10/JJGG?callback=jQuery"
            "&fundCode={code}&pageIndex={page}&pageSize=50&type={type}")
TEXT_API = ("https://np-cnotice-fund.eastmoney.com/api/content/ann"
            "?art_code={art}&client_source=fund&page_index=1")
ANN_URL = "https://fund.eastmoney.com/gonggao/{code},{art}.html"

SPLIT_KEYWORDS = ("份额拆分", "份额折算", "拆分", "折算")
DIV_KEYWORDS = ("分红", "收益分配", "利润分配")


def _get(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")


def list_announcements(code: str, *, max_pages: int = 10,
                       stop_before: str = "2005-01-01",
                       ann_type: str = "2"):
    """翻页拉取某只基金的公告，返回 [(publish_date, title, art_code)]。"""
    out: list[tuple[str, str, str]] = []
    for page in range(1, max_pages + 1):
        url = LIST_API.format(code=code, page=page, type=ann_type)
        try:
            raw = _get(url)
        except Exception:
            break
        match = re.search(r"jQuery\((.*)\)\s*$", raw, re.S)
        if not match:
            break
        try:
            obj = json.loads(match.group(1))
        except Exception:
            break
        data = obj.get("Data") or []
        if not data:
            break
        for item in data:
            out.append((
                str(item.get("PUBLISHDATEDesc") or ""),
                str(item.get("TITLE") or ""),
                str(item.get("ID") or ""),
            ))
        if min(str(item.get("PUBLISHDATEDesc") or "9999") for item in data) < stop_before:
            break
        if len(data) < 50 or page >= max_pages:
            break
        time.sleep(0.2)
    return out


def announcement_text(art_code: str) -> str:
    try:
        raw = _get(TEXT_API.format(art=art_code))
        obj = json.loads(raw)
        return str((obj.get("data") or {}).get("notice_content") or "")
    except Exception:
        return ""


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _date_after(label: str, text: str) -> str | None:
    """在正文中找「标签：2021年1月15日」这类日期。

    必须先匹配带冒号的分隔写法，再退回宽松写法：
    否则「1、权益登记日、份额拆分日  权益登记日：2月23日」这种小标题行
    会把「份额拆分日」误配到权益登记日的日期上。
    """
    strict = (label + r"\s*[:：]\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
    match = re.search(strict, text)
    if not match:
        match = re.search(label + r"\s*[:：]\s*(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if not match:
        loose = label + r"[^0-9]{0,12}(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
        match = re.search(loose, text)
    if not match:
        return None
    year, month, day = (int(g) for g in match.groups())
    return f"{year:04d}-{month:02d}-{day:02d}"


CJK = "一-龥"
NUM = r"(\d+(?:\s*\.\s*\d+)?)"


def _num(text: str) -> float:
    """把可能被空格拆开的数字（如 1 . 14539）还原成 float。"""
    return float(re.sub(r"\s+", "", text))


def _has_dual_field(text: str) -> bool:
    """公告是否把同一字段拆成「（场内）...（场外）」两段。"""
    return "（场内）" in text and "（场外）" in text


def _date_any(label: str, text: str) -> str | None:
    return _date_after(label, text)


def parse_dividend(text: str) -> dict:
    """从分红公告正文抽取关键字段。

    已知格式（按优先级）：
      本次分红方案（单位：元/10 0.11 份基金份额）   <- 金额夹在「元/10」与「份」之间
      本次分红方案（单位：元/10 份基金份额） 0.47
      每 10 份派现金 3.50 元
      每份基金份额派发现金红利 0.072 元
    """
    flat = _norm(text)
    result: dict = {}
    per_share = None

    # A) 表格被拍平时数字插在「元/10」和「份基金份额」中间
    match = re.search(r"元\s*/\s*10\s*" + NUM + r"\s*份", flat)
    if match:
        per_share = _num(match.group(1)) / 10.0
    # B) 「元/10 份基金份额）X」
    if per_share is None:
        match = re.search(r"元\s*/\s*10\s*份[^0-9]{0,24}" + NUM, flat)
        if match:
            per_share = _num(match.group(1)) / 10.0
    # C) 每 10 份派现金 X 元
    if per_share is None:
        for pattern in (r"每\s*10\s*份[^0-9]{0,14}" + NUM + r"\s*元",
                        r"每十份[^0-9]{0,14}" + NUM + r"\s*元"):
            match = re.search(pattern, flat)
            if match:
                per_share = _num(match.group(1)) / 10.0
                break
    # D) 每份基金份额 X 元
    if per_share is None:
        match = re.search(r"每份(?:基金)?份额[^0-9]{0,20}" + NUM + r"\s*元", flat)
        if match:
            per_share = _num(match.group(1))

    if per_share is not None:
        result["cash_per_share"] = round(per_share, 8)

    if _has_dual_field(flat):
        result["dual_date_layout"] = True
    result["record_date"] = _date_any("权益登记日", flat)
    result["ex_date"] = _date_any("除息日", flat) or _date_any("除权除息日", flat)
    result["pay_date"] = (_date_any("现金红利发放日", flat)
                          or _date_any("红利发放日", flat)
                          or _date_any("现金红利到账日", flat)
                          or _date_any("发放日", flat))
    return {k: v for k, v in result.items() if v is not None}


def _ratio_from_label(flat: str, labels: tuple[str, ...]) -> float | None:
    """从「<标签>比例为 X」这类句式里取比例。

    必须排除「保留到小数点后 N 位」里的数字：
    判据是数字前面紧邻的文字里出现「保留」或「小数点后」。
    """
    for label in labels:
        for match in re.finditer(label + r"[^0-9]{0,20}" + NUM, flat):
            prefix = flat[max(0, match.start() - 24): match.start()]
            if "保留" in prefix or "小数点后" in prefix:
                continue
            candidate = _num(match.group(1))
            if candidate > 0:
                return candidate
    return None


def parse_split(text: str) -> dict:
    """从拆分/折算/合并公告正文抽取关键字段。

    统一换算成「每 1 份变成几份」：
      1:10 拆分             -> 10.0
      10:1 合并             -> 0.1
      份额拆分比例为 2       -> 2.0
      折算比例为0.40739099   -> 0.40739099
      份额 = 原份额/100      -> 0.01
    """
    flat = _norm(text)
    result: dict = {}
    ratio: float | None = None

    # A) a:b 形式（最可靠，先做）
    for pattern in (
        NUM + r"\s*[:：]\s*" + NUM + r"\s*(?:的)?\s*(?:拆分|合并|折算)\s*比例",
        r"(?:拆分|合并|折算)\s*比例[^0-9]{0,8}" + NUM + r"\s*[:：]\s*" + NUM,
        r"按\s*" + NUM + r"\s*[:：]\s*" + NUM + r"\s*的(?:拆分|合并|折算)",
    ):
        match = re.search(pattern, flat)
        if match:
            left, right = _num(match.group(1)), _num(match.group(2))
            if left > 0 and right > 0:
                ratio = right / left
                break

    # B) 「本次基金份额（拆分|合并|折算）比例为 X」
    if ratio is None:
        ratio = _ratio_from_label(flat, (
            "本次基金份额拆分比例", "本次基金份额合并比例", "本次基金份额折算比例",
            "基金份额拆分比例", "基金份额合并比例", "基金份额折算比例",
            "拆分比例", "合并比例", "折算比例",
        ))

    # C) 「份额 = 原份额/100」这类除法表述
    if ratio is None:
        match = re.search(r"基金份额\s*[/÷]\s*(\d+(?:\.\d+)?)", flat)
        if match:
            divisor = _num(match.group(1))
            if divisor > 0:
                ratio = 1.0 / divisor

    if ratio is not None:
        result["share_ratio"] = round(ratio, 8)

    result["record_date"] = (_date_any("权益登记日", flat)
                             or _date_any("份额拆分权益登记日", flat)
                             or _date_any("份额折算权益登记日", flat))
    result["ex_date"] = (_date_any("份额拆分日", flat)
                         or _date_any("份额合并日", flat)
                         or _date_any("份额折算日", flat)
                         or _date_any("拆分日", flat))
    return {k: v for k, v in result.items() if v is not None}


def main() -> int:
    parser = argparse.ArgumentParser(description="抓取公司行为原始公告证据（只读）")
    parser.add_argument("--db", default="data/fund_agent.db")
    parser.add_argument("--out", default="data/ca_announcements.json")
    parser.add_argument("--sleep", type=float, default=0.25)
    parser.add_argument("--max-pages", type=int, default=6)
    parser.add_argument("--full-pages", type=int, default=14)
    args = parser.parse_args()

    db = PROJECT_ROOT / args.db
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    codes = sorted({row[0] for row in conn.execute(
        "SELECT DISTINCT code FROM corporate_actions ORDER BY code")})
    print(f"需核对公告的标的 {len(codes)} 只")

    payload: dict = {}
    for index, code in enumerate(codes, 1):
        listing = list_announcements(code, max_pages=args.max_pages)
        # type=2 只覆盖「分红送配」分类；份额合并结果公告等可能落在全量类目里，
        # 再扫一遍全量列表（只保留命中关键词的条目），避免漏证据。
        full = list_announcements(code, max_pages=args.full_pages, ann_type="0")
        seen = {art for _, _, art in listing}
        for pub, title, art in full:
            if art in seen:
                continue
            if any(k in title for k in ("份额拆分", "份额合并", "份额折算", "拆分结果",
                                        "合并结果", "折算结果", "分红", "收益分配",
                                        "利润分配")):
                listing.append((pub, title, art))
                seen.add(art)
        candidates = []
        for pub, title, art in listing:
            if any(k in title for k in SPLIT_KEYWORDS):
                candidates.append(("split", pub, title, art))
            elif any(k in title for k in DIV_KEYWORDS):
                candidates.append(("dividend", pub, title, art))
            elif "基金份额" in title:
                candidates.append(("split", pub, title, art))
        print(f"  [{index}/{len(codes)}] {code}: 公告 {len(listing)} 条，"
              f"相关 {len(candidates)} 条")
        enriched = []
        for kind, pub, title, art in candidates:
            text = announcement_text(art)
            parsed = parse_split(text) if kind == "split" else parse_dividend(text)
            enriched.append({
                "kind": kind,
                "publish_date": pub,
                "title": title,
                "art_code": art,
                "url": ANN_URL.format(code=code, art=art),
                "manager": _extract_manager(text),
                "parsed": parsed,
                "text_full": _norm(text),
            })
            time.sleep(args.sleep)
        payload[code] = enriched

    out = PROJECT_ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(len(v) for v in payload.values())
    with_parse = sum(1 for v in payload.values() for item in v if item["parsed"])
    print(f"\n已保存 {out}：公告 {total} 条，可解析 {with_parse} 条")
    return 0


def _extract_manager(text: str) -> str | None:
    flat = _norm(text)
    match = re.search(r"基金管理人名称\s*([^\s]{4,30}?公司)", flat)
    if match:
        return match.group(1)
    match = re.search(r"([\u4e00-\u9fa5]{2,20}基金管理(?:有限)?公司)", flat)
    return match.group(1) if match else None


if __name__ == "__main__":
    raise SystemExit(main())
