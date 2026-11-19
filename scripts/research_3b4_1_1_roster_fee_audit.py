"""阶段3B-4.1.1 历史终止基金样本代表性修正与费率解析边界审计（只读研究）。

任务 A：重新审计历史终止样本，区分「代码 / 份额 / 基金本体 / 独立事件」四种口径。
任务 B：审计费率解析边界，确认区间表达是否完整。

严格只读：不写正式库、不改 app/fund/、不改 migrations/、
不改 app/backtest/ app/quant/ app/validation/、不做回测、不做策略。
"""
from __future__ import annotations

import io
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    "Referer": "http://fund.eastmoney.com/",
}
TIMEOUT = 20
NOW = datetime.now()

# ---------------------------------------------------------------- 事件类型
EVENT_TYPES = {
    "liquidation": "基金合同终止并清算（基金本体消失）",
    "merge": "基金合并，并入另一只基金（本体消失）",
    "transformation": "转型，基金本体继续存续（仅变更类型/名称）",
    "share_termination": "份额终止（子份额终止运作，母基金存续）",
    "delisting": "终止上市（转场外/转LOF，基金本体存续）",
    "unknown": "无法判定",
}

# ---------------------------------------------------------------- 代码域
# 用于扫描「已不在存续名册」的代码。只扫这些段，不臆造代码。
CODE_PREFIXES = [
    ("00", 1, 100), ("01", 1, 100), ("02", 1, 100),
    ("16", 1, 100), ("24", 1, 100), ("45", 1, 100),
    ("48", 1, 100), ("50", 1000, 1100), ("51", 1000, 1100),
    ("15", 900, 1000), ("18", 4600, 4800),
]

# ---------------------------------------------------------------- 分类
_TITLE_RULES = [
    ("清算报告", "liquidation"),
    ("清盘", "liquidation"),
    ("终止分级运作", "share_termination"),
    ("终止运作", "share_termination"),
    ("终止上市及转型", "transformation"),
    ("转型期间", "transformation"),
    ("基金合同终止", "liquidation"),
    ("终止基金合同", "liquidation"),
    ("终止合同", "liquidation"),
    ("合并", "merge"),
    ("终止上市", "delisting"),
    ("转型", "transformation"),
]

# 非事件类公告：正文会提到终止，但本身不是事件公告
NON_EVENT_HINTS = (
    "年度报告", "季度报告", "半年度报告", "招募说明书", "产品资料概要",
    "托管协议", "基金合同生效", "份额发售", "上市交易公告书",
    "基金合同(由", "基金合同（由",
)


def classify_event(title: str) -> str:
    """标题 → 事件类型。

    顺序极重要。实测踩过的坑：
      - 「终止分级运作变更而来」不是清盘，是份额终止；
      - 「终止上市及转型期间…变更」不是终止上市，是转型；
      - 「关于终止XX基金合同」才是清盘。
    """
    if not title:
        return "unknown"
    for kw, etype in _TITLE_RULES:
        if kw in title:
            return etype
    if "终止" in title and "合同" in title:
        return "liquidation"
    if "终止" in title and "上市" in title:
        return "delisting"
    return "unknown"


def is_non_event(title: str) -> bool:
    """是否为非事件类文档。

    「基金合同」本身是合同全文，不是事件；但「关于终止XX基金合同的公告」
    是事件公告，不能误杀。
    """
    t = title or ""
    if any(h in t for h in NON_EVENT_HINTS):
        return True
    if "基金合同" in t and "公告" not in t:
        return True
    return False


# ---------------------------------------------------------------- HTTP
def _get(url: str, *, timeout: int = TIMEOUT, attempts: int = 3):
    import requests
    last = None
    for i in range(attempts):
        try:
            return requests.get(url, headers=HEADERS, timeout=timeout), None
        except Exception as exc:  # noqa: BLE001
            last = exc
            if i + 1 < attempts:
                time.sleep(0.8 * (i + 1))
    return None, f"{type(last).__name__}: {str(last)[:100]}"


def fetch_announcements(code: str, page_size: int = 100) -> dict:
    url = (f"http://api.fund.eastmoney.com/f10/JJGG/?callback=jQuery"
           f"&fundcode={code}&pageIndex=1&pageSize={page_size}&type=0")
    r, err = _get(url, timeout=15)
    if r is None:
        return {"ok": False, "error": err, "rows": [], "total": 0}
    m = re.search(r"jQuery\((.*)\)\s*$", r.text, re.S)
    if not m:
        return {"ok": False, "error": "非 JSONP", "rows": [], "total": 0}
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"JSON 失败: {exc}", "rows": [], "total": 0}
    rows = [{"title": x.get("TITLE"), "date": x.get("PUBLISHDATEDesc"),
             "id": x.get("ID"), "code": str(x.get("FUNDCODE") or code)}
            for x in (data.get("Data") or [])]
    return {"ok": True, "error": None, "total": data.get("TotalCount") or 0,
            "rows": rows}


def _compact_cn(text: str) -> str:
    """去掉中文之间的空格——PDF 常把「终止上市日」拆成「终止上 市日」。"""
    if not text:
        return text
    return re.sub(r"(?<=[\u4e00-\u9fa5])\s+(?=[\u4e00-\u9fa5])", "", text)


def fetch_doc_text(aid: str, pages: int = 4) -> dict:
    """下载公告正文。早期公告返回 HTML，较新公告返回 PDF，两种都要支持。"""
    if not aid:
        return {"ok": False, "error": "无 ID", "text": None, "format": None}
    url = f"http://pdf.dfcfw.com/pdf/H2_{aid}_1.pdf"
    r, err = _get(url, timeout=30)
    if r is None:
        return {"ok": False, "error": err, "text": None, "format": None}
    if r.content[:4] == b"%PDF":
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(r.content))
            text = "".join((p.extract_text() or "") for p in reader.pages[:pages])
            return {"ok": True, "error": None,
                    "text": re.sub(r"\s+", " ", text), "format": "pdf"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"PDF 失败: {exc}",
                    "text": None, "format": "pdf"}
    try:
        r.encoding = r.apparent_encoding or "utf-8"
        raw = r.text
        text = re.sub(r"<script.*?</script>", " ", raw, flags=re.S | re.I)
        text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) < 80:
            return {"ok": False, "error": "HTML 过短", "text": None,
                    "format": "html"}
        return {"ok": True, "error": None, "text": text, "format": "html"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"HTML 失败: {exc}", "text": None,
                "format": "html"}


# ---------------------------------------------------------------- 日期抽取
_DATE_CN = re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_DATE_ISO = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")


def _nd(y, m, d):
    try:
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    except (TypeError, ValueError):
        return None


def extract_dates(text: str) -> dict:
    out = {"established_date": None, "last_trading_date": None,
           "liquidation_start": None, "delisting_date": None,
           "final_trading_day": None, "conversion_base_date": None}
    if not text:
        return out
    text = _compact_cn(text)

    def _near(kw: str, span: int = 60, *, backward: bool = False):
        i = text.find(kw)
        if i < 0:
            return None
        if backward:
            head = text[max(0, i - 80):i]
            found = list(_DATE_CN.finditer(head)) or list(_DATE_ISO.finditer(head))
            return _nd(*found[-1].groups()) if found else None
        m = _DATE_CN.search(text[i:i + span]) or _DATE_ISO.search(text[i:i + span])
        return _nd(*m.groups()) if m else None

    out["last_trading_date"] = _near("最后运作日", 80)
    # 「于YYYY年MM月DD日起进入清算期」——日期在关键词前面
    out["liquidation_start"] = _near("进入清算期", backward=True)
    out["delisting_date"] = _near("终止上市日", 40)
    out["final_trading_day"] = _near("最后交易日", 40)
    out["conversion_base_date"] = _near("折算基准日", 60)

    m = re.search(r"于\s*(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*成立", text)
    if m:
        out["established_date"] = _nd(*m.groups())
    return out


_BAD_NAME_HINTS = ("本基金", "备案", "表明", "投资者", "份额持有人", "开放式基金")


def extract_successor(text: str) -> dict:
    """抽取承接基金名。**代码一律不抽**——名称后的数字常是份额代码。"""
    out = {"successor_name": None, "evidence": None}
    if not text:
        return out
    text = _compact_cn(text)
    for pat in (
        r"变更为[“\"]?([\u4e00-\u9fa5A-Za-z0-9（）()]{4,50}?(?:证券投资基金|基金))[”\"]?",
        r"转型为[“\"]?([\u4e00-\u9fa5A-Za-z0-9（）()]{4,50}?(?:证券投资基金|基金))[”\"]?",
        r"更名为[“\"]?([\u4e00-\u9fa5A-Za-z0-9（）()]{4,50}?(?:证券投资基金|基金))[”\"]?",
    ):
        m = re.search(pat, text)
        if m:
            name = re.sub(r"\s+", "", m.group(1))
            if any(h in name for h in _BAD_NAME_HINTS):
                continue
            if 6 <= len(name) <= 50:
                out["successor_name"] = name
                out["evidence"] = re.sub(r"\s+", " ", m.group(0))[:100]
                break
    return out


def extract_fund_fullname(text: str) -> str | None:
    if not text:
        return None
    t = _compact_cn(text)
    m = re.search(r"([\u4e00-\u9fa5A-Za-z0-9（）()]{6,45}证券投资基金)", t)
    return re.sub(r"\s+", "", m.group(1)) if m else None


# ---------------------------------------------------------------- 费率解析
_PCT = r"([0-9]+(?:\.[0-9]+)?)\s*%"
# 比较符必须按**长度从长到短**排列，否则「小于等于6天」会被拆成
# 「小于」+「6天」，丢掉「等于」，导致首档被误判为无上限档。
_CMP = r"(小于等于|大于等于|不低于|不超过|不少于|不满|小于|大于|以内|以下|以上)"
_TIER_DAYS = re.compile(_CMP + r"?\s*([0-9]+)\s*(天|年|个月)")
_TIER_AMT = re.compile(_CMP + r"?\s*([0-9.]+)\s*(万元|元)")


def _section(text: str, start_kw: str, end_kws: tuple) -> str:
    i = text.find(start_kw)
    if i < 0:
        return ""
    seg = text[i:]
    end = len(seg)
    for kw in end_kws:
        j = seg.find(kw, len(start_kw))
        if j > 0:
            end = min(end, j)
    return seg[:end]


def parse_annual_fees(text: str) -> dict:
    def _grab(kw):
        i = text.find(kw)
        if i < 0:
            return None
        m = re.search(_PCT, text[i:i + 40])
        return round(float(m.group(1)) / 100.0, 6) if m else None
    return {
        "management_fee": _grab("管理费率"),
        "custody_fee": _grab("托管费率"),
        "sales_service_fee": _grab("销售服务费率"),
        "is_annual": True,
    }


def parse_purchase_tiers(text: str) -> list[dict]:
    """申购费阶梯：金额区间 + 原费率 + 平台优惠费率（两者必须分开）。"""
    seg = _section(text, "申购费率", ("友情提示", "赎回费率", "认购费率"))
    if not seg:
        return []
    body = seg.replace("申购费率", "", 1).replace("适用金额", "")
    body = body.replace("原费率", "").replace("天天基金优惠费率", "")
    body = body.replace("&nbsp;", "").replace("费率", "")
    parts = [x.strip() for x in body.split("|") if x.strip()]

    tiers = []
    for i, p in enumerate(parts):
        if re.search(_PCT, p):
            continue
        m = _TIER_AMT.search(p)
        if not m or m.group(3) != "万元":
            continue
        bounds = list(_TIER_AMT.finditer(p))
        if not bounds:
            continue
        lo = hi = None
        lo_inc = hi_inc = None
        for b in bounds:
            op = b.group(1) or ""
            val = float(b.group(2))
            val = val * 10000 if b.group(3) == "万元" else val
            if op in ("大于等于", "不低于", "不少于", "以上"):
                lo, lo_inc = val, True
            elif op == "大于":
                lo, lo_inc = val, False
            elif op in ("小于", "不满", "以内", "以下"):
                hi, hi_inc = val, False
            elif op in ("小于等于", "不超过"):
                hi, hi_inc = val, True
            elif lo is None:
                lo, lo_inc = val, True
        min_inferred = False
        if lo is None and hi is not None:
            lo, lo_inc, min_inferred = 0.0, True, True

        rates = []
        for q in parts[i + 1:i + 3]:
            rm = re.search(_PCT, q)
            if rm:
                rates.append(round(float(rm.group(1)) / 100.0, 6))
        if not rates:
            continue
        tiers.append({
            "condition_text": p,
            "lower_bound": lo,
            "lower_inferred": min_inferred,
            "lower_inclusive": lo_inc,
            "upper_bound": hi,
            "upper_inclusive": hi_inc,
            "is_open_ended": hi is None,
            "raw_units": [f"{b.group(1) or ''}{b.group(2)}{b.group(3)}"
                          for b in bounds],
            "original_rate": rates[0],
            "platform_rate": rates[1] if len(rates) > 1 else None,
        })
    return tiers


def parse_redeem_tiers(text: str) -> list[dict]:
    """赎回费阶梯：持有期限区间 + 费率。

    页面结构是「条件文本 | 费率」成对出现。条件里可能含**两个**期限
    （如「大于等于7天，小于365天」），因此必须成对解析，
    并把**下界与上界都保留**——只存一个数字无法完整表达区间。
    """
    seg = _section(text, "赎回费率", ("友情提示", "注："))
    if not seg:
        return []
    body = seg.replace("赎回费率", "", 1).replace("适用期限", "")
    parts = [x.strip() for x in body.split("|") if x.strip()]

    def _to_days(value: int, unit: str) -> int:
        if unit == "年":
            return value * 365
        if unit == "个月":
            return value * 30
        return value

    tiers = []
    for i, p in enumerate(parts):
        if re.search(_PCT, p):
            continue
        bounds = list(_TIER_DAYS.finditer(p))
        if not bounds:
            continue
        rate = None
        if i + 1 < len(parts):
            rm = re.search(_PCT, parts[i + 1])
            if rm:
                rate = round(float(rm.group(1)) / 100.0, 6)
        if rate is None:
            continue

        # 逐条解析条件，得下界与上界
        lo = hi = None
        lo_inclusive = hi_inclusive = None
        for b in bounds:
            op = b.group(1) or ""
            val = _to_days(int(b.group(2)), b.group(3))
            if op in ("大于等于", "不低于", "不少于", "以上"):
                lo, lo_inclusive = val, True
            elif op == "大于":
                lo, lo_inclusive = val, False
            elif op in ("小于", "不满", "以内", "以下"):
                hi, hi_inclusive = val, False
            elif op == "小于等于":
                hi, hi_inclusive = val, True
            elif op == "不超过":
                hi, hi_inclusive = val, True
            elif lo is None:
                lo, lo_inclusive = val, True
            else:
                hi, hi_inclusive = val, False

        # 「小于N天」没有显式下界，数学上从 0 开始。
        # 这是**补全**不是**猜测**，必须显式标记，否则会被当成原始数据。
        min_inferred = False
        if lo is None and hi is not None:
            lo, lo_inclusive, min_inferred = 0, True, True

        tiers.append({
            "condition_text": p,
            "holding_days_min": lo,
            "min_inclusive": lo_inclusive,
            "min_inferred": min_inferred,
            "holding_days_max": hi,
            "max_inclusive": hi_inclusive,
            "is_open_ended": hi is None,
            "rate": rate,
            "raw_units": [f"{b.group(1) or ''}{b.group(2)}{b.group(3)}"
                          for b in bounds],
        })
    return tiers


def fetch_fee_page(code: str) -> dict:
    r, err = _get(f"http://fundf10.eastmoney.com/jjfl_{code}.html")
    if r is None:
        return {"ok": False, "error": err, "text": None, "has_fee": False}
    r.encoding = "utf-8"
    t = re.sub(r"<[^>]+>", "|", r.text)
    t = re.sub(r"[|]{2,}", "|", t)
    t = re.sub(r"\s+", " ", t)
    return {"ok": True, "error": None, "text": t, "has_fee": "管理费率" in t}


def audit_fee_tiers(code: str) -> dict:
    """对单只基金的费率阶梯做边界审计。"""
    page = fetch_fee_page(code)
    out = {
        "code": code, "page_ok": page["ok"], "has_fee": page.get("has_fee", False),
        "purchase_tiers": [], "redeem_tiers": [],
        "annual_fees": None,
        "checks": {},
        "boundary_issues": [],
    }
    if not page["ok"] or not page.get("has_fee"):
        out["checks"] = {"parsed": False}
        return out

    text = page["text"]
    out["annual_fees"] = parse_annual_fees(text)
    out["purchase_tiers"] = parse_purchase_tiers(text)
    out["redeem_tiers"] = parse_redeem_tiers(text)

    redeem = out["redeem_tiers"]
    checks = {}
    issues = []

    # 1) 是否每档都同时有下界与上界（或明确无上限）
    complete = all(
        (t["holding_days_min"] is not None) and
        (t["holding_days_max"] is not None or t["is_open_ended"])
        for t in redeem) if redeem else False
    checks["all_tiers_have_bounds"] = complete

    # 2) 是否恰好一档无上限
    open_ended = [t for t in redeem if t["is_open_ended"]]
    checks["open_ended_tier_count"] = len(open_ended)
    checks["exactly_one_open_ended"] = len(open_ended) == 1
    if len(open_ended) != 1:
        issues.append(f"无上限档位数异常: {len(open_ended)}")

    # 3) 区间连续性：按下界排序后，相邻档的上界应等于下一档的下界
    ordered = sorted([t for t in redeem if t["holding_days_min"] is not None],
                     key=lambda x: x["holding_days_min"])
    gaps = []
    overlaps = []
    for a, b in zip(ordered, ordered[1:]):
        upper = a["holding_days_max"]
        lower = b["holding_days_min"]
        if upper is None:
            continue
        # 相邻档：a 的上界与 b 的下界之间不能有整数缺口
        if a["max_inclusive"]:
            expected = upper + 1
        else:
            expected = upper
        if b["min_inclusive"]:
            pass
        if expected < lower:
            gaps.append({"a_max": upper, "a_max_inclusive": a["max_inclusive"],
                         "b_min": lower, "expected_next": expected})
        elif expected > lower:
            overlaps.append({"a_max": upper, "b_min": lower})
    checks["gap_count"] = len(gaps)
    checks["overlap_count"] = len(overlaps)
    if gaps:
        issues.append(f"区间空洞 {len(gaps)} 处: {gaps[:3]}")
    if overlaps:
        issues.append(f"区间重叠 {len(overlaps)} 处: {overlaps[:3]}")

    # 4) 首档下界是否为 0
    checks["first_tier_starts_at_zero"] = bool(
        ordered and ordered[0]["holding_days_min"] == 0)
    if ordered and ordered[0]["holding_days_min"] != 0:
        issues.append(f"首档下界不是 0: {ordered[0]['holding_days_min']}")

    # 5) 阶梯是否单调不增（赎回费通常持有越久越便宜）
    rates = [t["rate"] for t in ordered]
    checks["rate_monotonic_nonincreasing"] = all(
        a >= b for a, b in zip(rates, rates[1:]))
    if not checks["rate_monotonic_nonincreasing"]:
        issues.append(f"费率非单调不增: {rates}")

    # 6) 申购原始费率与平台费率是否分开保存
    purch = out["purchase_tiers"]
    checks["purchase_keeps_both_rates"] = all(
        t["original_rate"] is not None and
        (t["platform_rate"] is not None or len(purch) == 1)
        for t in purch) if purch else None

    # 7) 年化费率是否标记
    checks["annual_fees_marked"] = bool(
        out["annual_fees"] and out["annual_fees"].get("is_annual"))

    # 8) 0 费率与「无字段」区分
    ss = (out["annual_fees"] or {}).get("sales_service_fee")
    checks["sales_service_fee_is_zero_not_missing"] = (ss is not None)
    if ss is None:
        issues.append("销售服务费为「---」（页面无此字段），不能当成 0")

    out["checks"] = checks
    out["boundary_issues"] = issues
    return out


# ---------------------------------------------------------------- 主流程
def scan_terminated_candidates(limit_codes: int = 0) -> dict:
    """扫描非存续代码，收集事件公告。"""
    import akshare as ak
    nm = ak.fund_name_em()
    alive = set(nm["基金代码"].astype(str))

    codes = []
    for prefix, lo, hi in CODE_PREFIXES:
        for i in range(lo, hi):
            codes.append(f"{prefix}{i:04d}")
    codes = [c for c in codes if c not in alive]
    if limit_codes:
        codes = codes[:limit_codes]

    events = []
    scanned = 0
    for code in codes:
        scanned += 1
        ann = fetch_announcements(code, 60)
        if not ann["ok"] or not ann["rows"]:
            continue
        for row in ann["rows"]:
            if is_non_event(row["title"]):
                continue
            etype = classify_event(row["title"])
            if etype == "unknown":
                continue
            events.append({
                "code": code,
                "event_type": etype,
                "announcement_id": row["id"],
                "announcement_title": row["title"],
                "announcement_date": row["date"],
            })
        time.sleep(0.08)
    return {
        "scanned_codes": scanned,
        "raw_events": events,
        "alive_count": len(alive),
    }


def dedupe_events(raw_events: list[dict]) -> dict:
    """按「同一公告 = 同一事件」去重，再按基金本体归并。

    规则：
    1. **同一个 announcement_id = 同一个事件**——分级 A/B 两份代码
       常常共用一条公告，绝不能算成两个事件。
    2. 同一事件下的多个代码，取其中最像母基金主代码的那个作为代表。
    3. 基金本体识别：从公告标题里抽基金全名（去掉份额后缀）。
    """
    by_ann = defaultdict(list)
    for e in raw_events:
        by_ann[e["announcement_id"]].append(e)

    events = []
    for aid, group in by_ann.items():
        codes = sorted({g["code"] for g in group})
        rep = group[0]
        # 优先级：清盘 > 合并 > 转型 > 份额终止 > 终止上市
        prio = {"liquidation": 0, "merge": 1, "transformation": 2,
                "share_termination": 3, "delisting": 4}
        best = min(group, key=lambda g: prio.get(g["event_type"], 9))
        events.append({
            "event_key": aid,
            "event_type": best["event_type"],
            "announcement_id": aid,
            "announcement_title": best["announcement_title"],
            "announcement_date": best["announcement_date"],
            "codes_in_event": codes,
            "code_count_in_event": len(codes),
            "all_event_types_seen": sorted({g["event_type"] for g in group}),
        })

    # 按（基金本体，事件类型）归并成一个**独立终止事件**。
    # 同一基金清盘会连续发「提示性公告 → 合同终止公告 → 清算报告」，
    # 这些是**同一事件的披露链**，不是多个事件。全部公告保留为证据链。
    by_entity = defaultdict(list)
    for ev in events:
        by_entity[(fund_entity_key(ev["announcement_title"]), ev["event_type"])].append(ev)

    merged = []
    for (entity, etype), group in by_entity.items():
        group.sort(key=lambda x: x["announcement_date"] or "")
        first, last = group[0], group[-1]
        codes = sorted({c for g in group for c in g["codes_in_event"]})
        merged.append({
            "event_key": f"{entity}|{etype}",
            "fund_entity": entity,
            "event_type": etype,
            "codes_in_event": codes,
            "code_count": len(codes),
            "announcement_count": len(group),
            "announcement_ids": [g["announcement_id"] for g in group],
            "first_announcement_date": first["announcement_date"],
            "last_announcement_date": last["announcement_date"],
            # 用最"晚"的那条作主公告（清算报告/合同终止公告）
            "announcement_id": last["announcement_id"],
            "announcement_title": last["announcement_title"],
            "announcement_date": last["announcement_date"],
            "all_titles": [g["announcement_title"] for g in group],
        })

    # 同一基金本体若已判定为清盘（liquidation），其「终止上市」只是清算的
    # 前置程序，不是独立事件——必须并入清盘事件，否则会把一只基金的
    # 一次清盘算成两个事件。
    by_fund = defaultdict(list)
    for e in merged:
        by_fund[e["fund_entity"]].append(e)

    absorbed = []
    for entity, group in by_fund.items():
        types = {e["event_type"] for e in group}
        if "liquidation" in types:
            liq = next(e for e in group if e["event_type"] == "liquidation")
            for e in group:
                if e["event_type"] == "delisting":
                    liq["announcement_count"] += e["announcement_count"]
                    liq["announcement_ids"] += e["announcement_ids"]
                    liq["all_titles"] += e["all_titles"]
                    liq["codes_in_event"] = sorted(
                        set(liq["codes_in_event"]) | set(e["codes_in_event"]))
                    liq["code_count"] = len(liq["codes_in_event"])
                    liq.setdefault("absorbed_events", []).append("delisting")
                    absorbed.append(f"{entity}|delisting")
    merged = [e for e in merged
              if f"{e['fund_entity']}|{e['event_type']}" not in absorbed]

    return {
        "events": merged,
        "event_count": len(merged),
        "fund_entity_count": len({e["fund_entity"] for e in merged}),
        "raw_announcement_events": len(events),
        "duplicate_collapsed": len(raw_events) - len(merged),
        "absorbed_delisting_into_liquidation": len(absorbed),
    }


_SHARE_SUFFIX = re.compile(r"[（(]?[A-Z]{1,2}[）)]?$")


def fund_entity_key(title: str) -> str:
    """从公告标题里抽出「基金本体名」，用于把同一基金的多次公告归并。

    只做保守清洗：去份额后缀、去前后缀修饰词。抽不出就返回整条标题，
    宁可多算一个本体，也不把不同基金错误合并。
    """
    if not title:
        return "__unknown__"
    t = _compact_cn(title)
    # 去掉常见前后缀
    for pat in (r"的?(?:特别)?(?:提示性)?公告.*$",
                r"第[一二三四五六七八九十]+次",
                r"[（(]?\d{4}/\d{1,2}/\d{1,2}[）)]?",
                r"^.*?基金管理[（(]?[^）)]*[）)]?(?:有限公司|股份有限公司)(?:关于)?",
                r"^(?:关于|有关)"):
        t = re.sub(pat, "", t)
    # 简称式标题（「国泰金象：保本到期转型的」）去掉「简称：」前缀
    t = re.sub(r"^[\u4e00-\u9fa5A-Za-z0-9]{2,10}：", "", t)
    t = re.sub(r"的$", "", t)
    # 再清一遍「关于」与公司名前缀（前面步骤可能刚暴露出来）
    t = re.sub(r"^.*?(?:基金管理|基金管理有限责任)[^，。]{0,20}?(?:有限公司|公司)(?:关于)?", "", t)
    t = re.sub(r"^(?:关于|有关)", "", t)
    t = _SHARE_SUFFIX.sub("", t)
    # 抽「XX证券投资基金」
    m = re.search(r"([\u4e00-\u9fa5A-Za-z0-9（）()\-]{6,50}?(?:证券投资基金|基金))", t)
    if m:
        name = re.sub(r"\s+", "", m.group(1))
        # 必须是「XX基金」形态，否则是抽错了（如把「保本到期转型」当基金名）
        if name.endswith(("证券投资基金", "基金")) and len(name) >= 6:
            return name
    # 抽不出基金名时，用整条标题作键：宁可多算本体，也不错误合并
    return "__no_name__:" + t.strip()[:70]


def verify_event(ev: dict) -> dict:
    """对单个事件抓原文，补全字段。"""
    out = dict(ev)
    out.update({
        "fund_entity": fund_entity_key(ev["announcement_title"]),
        "announcement_url": f"http://pdf.dfcfw.com/pdf/H2_{ev['announcement_id']}_1.pdf",
        "doc_format": None,
        "doc_ok": False,
        "fund_full_name": None,
        "established_date": None,
        "last_trading_date": None,
        "liquidation_start": None,
        "delisting_date": None,
        "event_date": None,
        "successor_name": None,
        "successor_code": None,
        "evidence_level": "D",
        "missing_fields": [],
        "doc_excerpt": None,
    })
    doc = fetch_doc_text(ev["announcement_id"])
    out["doc_ok"] = doc["ok"]
    out["doc_format"] = doc["format"]
    if not doc["ok"]:
        out["missing_fields"] = ["正文", "事件日期"]
        return out

    text = doc["text"]
    dates = extract_dates(text)
    out.update({k: v for k, v in dates.items() if k != "conversion_base_date"})
    succ = extract_successor(text)
    out["successor_name"] = succ["successor_name"]
    # 承接基金不能与本基金同名——那多半是公告在复述本基金全称，
    # 不是真的承接方。
    if out["successor_name"] and out["fund_entity"] and \
            out["successor_name"].startswith(out["fund_entity"][:10]):
        out["successor_name"] = None
        out.setdefault("notes", []).append("承接名与本基金同名，判为抽取误命中，置空")
    out["fund_full_name"] = extract_fund_fullname(text)
    out["doc_excerpt"] = text[:220]

    # 事件生效日期：按类型选
    if out["event_type"] == "liquidation":
        out["event_date"] = out["liquidation_start"] or out["last_trading_date"]
    elif out["event_type"] == "share_termination":
        out["event_date"] = out["delisting_date"]
    elif out["event_type"] == "delisting":
        out["event_date"] = out["delisting_date"]
    else:
        out["event_date"] = out["delisting_date"] or out["liquidation_start"]

    if out["event_date"]:
        out["evidence_level"] = "A"
    elif out["doc_ok"]:
        out["evidence_level"] = "B"

    for f in ("established_date", "event_date", "successor_name"):
        if out.get(f) is None:
            out["missing_fields"].append(f)
    return out


def main(out_dir: Path) -> dict:
    print("扫描历史终止候选...", flush=True)
    scan = scan_terminated_candidates()
    print(f"  扫描 {scan['scanned_codes']} 个非存续代码，"
          f"收集 {len(scan['raw_events'])} 条事件记录", flush=True)

    print("去重与归并...", flush=True)
    dd = dedupe_events(scan["raw_events"])
    print(f"  去重后 {dd['event_count']} 个事件 / "
          f"{dd['fund_entity_count']} 个基金本体"
          f"（合并掉 {dd['duplicate_collapsed']} 条重复代码记录）", flush=True)

    # 优先验证：清盘/合并全量 + 其他类型抽样
    by_type = defaultdict(list)
    for ev in dd["events"]:
        by_type[ev["event_type"]].append(ev)

    targets = []
    targets += by_type["liquidation"]
    targets += by_type["merge"][:15]
    targets += by_type["transformation"][:10]
    targets += by_type["share_termination"][:10]
    targets += by_type["delisting"][:10]

    print(f"抓取原文验证 {len(targets)} 个事件...", flush=True)
    verified = []
    for i, ev in enumerate(targets, 1):
        if i % 20 == 0:
            print(f"  {i}/{len(targets)}", flush=True)
        verified.append(verify_event(ev))
        time.sleep(0.35)

    # 统计
    stat = defaultdict(int)
    for v in verified:
        stat[v["event_type"]] += 1
    entities = {v["fund_entity"] for v in verified}
    a_level = [v for v in verified if v["evidence_level"] == "A"]

    print("费率边界审计...", flush=True)
    fee_codes = ["000051", "110020", "161725", "012414", "000015", "000016",
                 "007300", "007301", "110022", "161005", "000478", "000198"]
    fees = []
    for c in fee_codes:
        fees.append(audit_fee_tiers(c))
        time.sleep(0.25)

    payload = {
        "phase": "3B-4.1.1",
        "baseline_head": "472603d42ec4bc19569f8ce66feff451bd80faaf",
        "generated_at": NOW.isoformat(timespec="seconds"),
        "scope": "只做样本重新审计与费率边界审计；不改数据层、不改迁移、不入库、不做回测",
        "event_types": EVENT_TYPES,
        "roster": {
            "scanned_codes": scan["scanned_codes"],
            "raw_code_records": len(scan["raw_events"]),
            "raw_announcement_events": dd["raw_announcement_events"],
            "distinct_events": dd["event_count"],
            "distinct_fund_entities": dd["fund_entity_count"],
            "duplicate_collapsed": dd["duplicate_collapsed"],
            "absorbed_delisting_into_liquidation": dd["absorbed_delisting_into_liquidation"],
            "verified_count": len(verified),
            "verified_fund_entities": len(entities),
            "by_event_type_all": {k: len(v) for k, v in by_type.items()},
            "by_event_type_verified": dict(stat),
            "evidence_a_count": len(a_level),
            "events": verified,
            "dedupe_rules": [
                "同一 announcement_id = 同一事件（分级 A/B 共用一条公告，不得算两个）",
                "同一事件下的多个代码合并，取最具体的类型作为事件类型",
                "基金本体按公告标题抽取的基金全名归并",
                "抽不出基金名时宁可多算本体，不错误合并",
            ],
        },
        "fee_audit": {
            "samples": fees,
            "count": len(fees),
            "all_have_bounds": sum(1 for f in fees
                                   if f["checks"].get("all_tiers_have_bounds")),
            "all_have_single_open_end": sum(1 for f in fees
                                            if f["checks"].get("exactly_one_open_ended")),
            "with_gaps": sum(1 for f in fees if f["checks"].get("gap_count")),
            "with_overlaps": sum(1 for f in fees if f["checks"].get("overlap_count")),
            "with_issues": sum(1 for f in fees if f["boundary_issues"]),
        },
        "unresolved": [
            "无权威全市场已终止基金全量清单，覆盖率仍不可量化",
            "合并（merge）事件在公告标题里极少显式出现，样本稀薄",
            "承接基金代码公告里基本不写，只能靠名称对回 fund_master",
            "已终止基金的历史费率不可恢复",
            "支付宝可购买状态无公开接口",
        ],
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    jp = out_dir / "phase3B4_1_1_historical_roster_fee_audit.json"
    jp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"JSON -> {jp}", flush=True)
    return payload


if __name__ == "__main__":
    main(ROOT / "reports")
