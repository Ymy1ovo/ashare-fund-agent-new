"""阶段3B-4.1 场外基金关键历史数据源补齐审计（只读研究）。

三个问题：
1. 历史清盘/合并基金名录能否建立；
2. 申购费/赎回费/持有期阶梯能否可靠获取，历史费率能否恢复；
3. 支付宝可购买状态能否合法稳定自动获取。

严格只读：不写正式数据库、不改 app/fund/ 正式数据层、不改迁移文件、
不开发回测、不开发策略、不接实盘。

所有网络调用都有超时与重试；普通单元测试用 Mock，不依赖网络。
"""
from __future__ import annotations

import io
import json
import re
import sys
import time
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
RETRIES = 3

# ---------------------------------------------------------------- 证据分级
EVIDENCE_LEVELS = {
    "A": "基金公司/监管机构正式公告或合同原文",
    "B": "权威官方渠道的结构化数据",
    "C": "可靠第三方数据，可追溯来源",
    "D": "无法追溯来源或仅有间接推断",
}

# ---------------------------------------------------------------- 事件类型
# 严格区分，不得混为一类
EVENT_TYPES = {
    "liquidation": "清盘（基金合同终止并清算）",
    "merge": "合并（并入其他基金）",
    "transformation": "转型（分级子份额终止、基金存续）",
    "share_termination": "份额终止（子份额终止运作/终止上市）",
    "delisting": "终止上市（转场外或转LOF）",
}

# ---------------------------------------------------------------- 样本
# 历史终止/合并基金样本：跨年份、跨类型、跨终止原因。
TERMINATED_SAMPLES = [
    # (代码, 名称, 预期类别, 备注)
    ("150008", "国投瑞银瑞和沪深300指数分级-小康", "分级子份额", "2020 清盘"),
    ("150009", "国投瑞银瑞和沪深300指数分级-远见", "分级子份额", "2020 清盘"),
    ("150019", "银华深证100指数分级-锐进", "分级子份额", "2021 转型"),
    ("150023", "申万菱信深证成指分级-进取", "分级子份额", "2021 转型"),
    ("150028", "信诚中证500指数分级-A", "分级子份额", "2021 转型"),
    ("150029", "信诚中证500指数分级-B", "分级子份额", "2021 转型"),
    ("150020", "富国汇利回报分级-汇利A", "分级子份额", "2017 终止上市"),
    ("150021", "富国汇利回报分级-汇利B", "分级子份额", "2017 终止上市"),
    ("150032", "嘉实多利分级-优先", "分级子份额", "2020 终止上市"),
    ("150033", "嘉实多利分级-进取", "分级子份额", "2020 终止上市"),
    ("150030", "银华中证等权重90分级-A", "分级子份额", "2021 转型"),
    ("150031", "银华中证等权重90分级-B", "分级子份额", "2021 转型"),
    ("150035", "泰达宏利聚利分级-B", "分级子份额", "2016 终止上市"),
    ("150001", "国投瑞银瑞福深证100分级-优先", "分级子份额", "2015 终止上市"),
    ("150002", "大成优选股票(LOF)", "LOF", "2015 转型"),
    ("150003", "建信优势动力股票", "LOF", "2015 转型"),
    ("184688", "开元证券投资基金", "老封闭式", "2014 转型"),
    ("184689", "普惠证券投资基金", "老封闭式", "2014 转型"),
    ("184690", "同益证券投资基金", "老封闭式", "2015 转型"),
    ("184691", "景宏证券投资基金", "老封闭式", "2015 转型"),
    ("184692", "裕隆证券投资基金", "老封闭式", "2015 转型"),
    ("184698", "天元证券投资基金", "老封闭式", "2014 终止上市"),
    ("184699", "同盛证券投资基金", "老封闭式", "2015 转型"),
    ("184701", "基金景福", "老封闭式", "2015 转型"),
    ("184705", "基金裕泽", "老封闭式", "2011 终止上市"),
]

# 存续基金费率样本：含 3 组 A/C 配对
FEE_SAMPLES = [
    ("000051", "华夏沪深300ETF联接A", "宽基指数"),
    ("110020", "易方达沪深300ETF联接A", "宽基指数"),
    ("161725", "招商中证白酒指数(LOF)A", "行业指数", "pair_1"),
    ("012414", "招商中证白酒指数(LOF)C", "行业指数", "pair_1"),
    ("000015", "华夏纯债债券A", "债券", "pair_2"),
    ("000016", "华夏纯债债券C", "债券", "pair_2"),
    ("007300", "国联安中证半导体ETF联接A", "ETF联接", "pair_3"),
    ("007301", "国联安中证半导体ETF联接C", "ETF联接", "pair_3"),
    ("110022", "易方达消费行业股票", "主动权益"),
    ("161005", "富国天惠成长混合(LOF)A", "主动权益"),
    ("000478", "建信中证500指数增强A", "指数增强"),
    ("000198", "天弘余额宝货币", "货币"),
]

# 已确认清盘的基金（用于验证「历史费率是否可恢复」）
DELISTED_FEE_PROBE = ["150008", "150019", "150020", "184688"]

NOW = datetime.now()


def _pause(sec: float = 0.25) -> None:
    time.sleep(sec)


def _get(url: str, *, timeout: int = TIMEOUT, attempts: int = RETRIES):
    """带重试的 GET。返回 (response, error)。"""
    import requests
    last = None
    for i in range(attempts):
        try:
            return requests.get(url, headers=HEADERS, timeout=timeout), None
        except Exception as exc:  # noqa: BLE001
            last = exc
            if i + 1 < attempts:
                time.sleep(1.2 * (i + 1))
    return None, f"{type(last).__name__}: {str(last)[:120]}"


# ---------------------------------------------------------------- 公告抓取
def fetch_announcements(code: str, page_size: int = 100) -> dict:
    """拿一只基金的全部公告列表（含已终止基金）。"""
    url = (f"http://api.fund.eastmoney.com/f10/JJGG/?callback=jQuery"
           f"&fundcode={code}&pageIndex=1&pageSize={page_size}&type=0")
    r, err = _get(url)
    if r is None:
        return {"ok": False, "error": err, "rows": [], "total": 0}
    m = re.search(r"jQuery\((.*)\)\s*$", r.text, re.S)
    if not m:
        return {"ok": False, "error": "响应不是 JSONP", "rows": [], "total": 0}
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"JSON 解析失败: {exc}", "rows": [], "total": 0}
    rows = data.get("Data") or []
    return {
        "ok": True,
        "error": None,
        "total": data.get("TotalCount") or 0,
        "rows": [{"title": x.get("TITLE"), "date": x.get("PUBLISHDATEDesc"),
                  "id": x.get("ID"), "code": x.get("FUNDCODE")} for x in rows],
    }


def fetch_pdf_text(aid: str, pages: int = 4) -> dict:
    """下载公告正文。

    实测该 PDF 直链对**早期公告**（约 2015 年前）返回的是 HTML 正文，
    对较新公告返回真正的 PDF。两种都必须支持，否则会误判为「不可读」。
    """
    if not aid:
        return {"ok": False, "error": "无公告 ID", "text": None, "pages": 0,
                "format": None}
    url = f"http://pdf.dfcfw.com/pdf/H2_{aid}_1.pdf"
    r, err = _get(url, timeout=30)
    if r is None:
        return {"ok": False, "error": err, "text": None, "pages": 0,
                "format": None}

    if r.content[:4] == b"%PDF":
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(r.content))
            total = len(reader.pages)
            text = "".join((pg.extract_text() or "") for pg in reader.pages[:pages])
            return {"ok": True, "error": None,
                    "text": re.sub(r"\s+", " ", text), "pages": total,
                    "format": "pdf"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"PDF 解析失败: {exc}",
                    "text": None, "pages": 0, "format": "pdf"}

    # 非 PDF：早期公告以 HTML 正文直出
    try:
        r.encoding = r.apparent_encoding or "utf-8"
        raw = r.text
        text = re.sub(r"<script.*?</script>", " ", raw, flags=re.S | re.I)
        text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) < 80:
            return {"ok": False, "error": "HTML 正文过短", "text": None,
                    "pages": 0, "format": "html"}
        return {"ok": True, "error": None, "text": text, "pages": 1,
                "format": "html"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"HTML 解析失败: {exc}", "text": None,
                "pages": 0, "format": "html"}


# ---------------------------------------------------------------- 事件分类
# 标题关键词 → 事件类型。顺序重要：越具体越靠前。
# 顺序极重要：越具体的越靠前。
# 实测踩过的坑：
#   「终止分级运作变更而来」曾被误判为 liquidation（因为含「终止」+「合同」）；
#   「终止上市及转型期间…变更」曾被误判为 delisting（实际是 transformation）。
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
    ("终止上市", "delisting"),
    ("转型", "transformation"),
    ("合并", "merge"),
]


def classify_event(title: str) -> str:
    if not title:
        return "unknown"
    # 先按具体规则匹配；「终止运作」「终止上市」比「终止」更具体，必须先判
    for kw, etype in _TITLE_RULES:
        if kw == "终止":
            continue
        if kw in title:
            return etype
    # 兜底：含「终止」且含「合同」= 基金合同终止 = 清盘
    if "终止" in title and "合同" in title:
        return "liquidation"
    if "终止" in title and "上市" in title:
        return "delisting"
    return "unknown"


_DATE_CN = re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_DATE_ISO = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")


def _norm_date(y, m, d) -> str | None:
    try:
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    except (TypeError, ValueError):
        return None


def _compact_cn(text: str) -> str:
    """去掉中文之间的空格。

    PDF 抽取常把「终止上市日」拆成「终止上 市日」，
    不做这步关键词就匹配不上，会漏掉终止日期。
    只合并「中文+空格+中文」，不动数字与中文之间的间隔。
    """
    if not text:
        return text
    return re.sub(r"(?<=[\u4e00-\u9fa5])\s+(?=[\u4e00-\u9fa5])", "", text)


def extract_dates_from_text(text: str) -> dict:
    """从 PDF 正文里抽关键日期。

    只在**明确语境**下抽，不做全局猜测：
      - 「最后运作日」→ last_trading_date
      - 「清算期」开始 → liquidation_start
      - 「终止上市日」→ delisting_date
      - 「成立」+ 日期 → established_date
    """
    out = {
        "established_date": None,
        "last_trading_date": None,
        "liquidation_start": None,
        "delisting_date": None,
        "final_trading_day": None,
        "conversion_base_date": None,
    }
    if not text:
        return out
    text = _compact_cn(text)

    def _near(keyword: str, span: int = 60):
        i = text.find(keyword)
        if i < 0:
            return None
        m = _DATE_CN.search(text[i:i + span])
        if m:
            return _norm_date(*m.groups())
        m = _DATE_ISO.search(text[i:i + span])
        if m:
            return _norm_date(*m.groups())
        return None

    out["last_trading_date"] = _near("最后运作日", 80)
    # 「于2020年8月28日起进入清算期」：日期在关键词**前面**，要往前找
    i = text.find("进入清算期")
    if i >= 0:
        head = text[max(0, i - 80):i]
        # 前面可能还有别的日期（如「最后运作日」），必须取**最靠近关键词**的那个
        found = list(_DATE_CN.finditer(head)) or list(_DATE_ISO.finditer(head))
        if found:
            m = found[-1]
            out["liquidation_start"] = _norm_date(*m.groups())
    out["delisting_date"] = _near("终止上市日", 40)
    out["final_trading_day"] = _near("最后交易日", 40)
    out["conversion_base_date"] = _near("折算基准日", 60)

    # 成立日期：找「于YYYY年MM月DD日成立」
    m = re.search(r"于\s*(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*成立", text)
    if m:
        out["established_date"] = _norm_date(*m.groups())
    return out


_CN_NUM = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


_BAD_NAME_HINTS = ("本基金", "本基金的", "备案", "表明", "投资者", "份额持有人")


def _clean_fund_name(raw: str) -> str:
    """清理 PDF 抽取出的基金名：去掉 PDF 换行造成的空格与多余空白。

    同时拒绝明显不是基金名的片段（如「本基金的备案并不表明…」），
    宁可返回 None 也不返回错误的承接基金名。
    """
    if not raw:
        return None
    s = re.sub(r"\s+", "", raw)
    if any(h in s for h in _BAD_NAME_HINTS):
        return None
    if len(s) < 6 or len(s) > 50:
        return None
    return s.strip()


def extract_successor(text: str) -> dict:
    """抽取承接基金信息（合并/转型场景）。

    只在正文明确写出承接基金名称时才记录，**代码不推测**：
    名称后的 6 位数字常是「份额代码」而非基金主代码，直接抓会错，
    因此代码一律留 NULL，标 missing 由人工核对。
    """
    out = {"successor_name": None, "successor_code": None, "evidence": None}
    if not text:
        return out
    text = _compact_cn(text)
    patterns = [
        r"变更为[“\"]?([\u4e00-\u9fa5A-Za-z0-9（）()\s]{4,50}?(?:证券投资基金|基金))[”\"]?",
        r"转型为[“\"]?([\u4e00-\u9fa5A-Za-z0-9（）()\s]{4,50}?(?:证券投资基金|基金))[”\"]?",
        r"更名为[“\"]?([\u4e00-\u9fa5A-Za-z0-9（）()\s]{4,50}?(?:证券投资基金|基金))[”\"]?",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            name = _clean_fund_name(m.group(1))
            if name:
                out["successor_name"] = name
                out["evidence"] = re.sub(r"\s+", " ", m.group(0))[:100]
                break
    return out


# ---------------------------------------------------------------- 费率抓取
_FEE_TEXT_CLEAN = re.compile(r"[|]{2,}")


def fetch_fee_page(code: str) -> dict:
    """抓 F10 费率页（保留原文，便于追溯）。"""
    url = f"http://fundf10.eastmoney.com/jjfl_{code}.html"
    r, err = _get(url, timeout=TIMEOUT)
    if r is None:
        return {"ok": False, "error": err, "text": None}
    r.encoding = "utf-8"
    t = re.sub(r"<[^>]+>", "|", r.text)
    t = _FEE_TEXT_CLEAN.sub("|", t)
    t = re.sub(r"\s+", " ", t)
    return {"ok": True, "error": None, "text": t,
            "has_fee": "管理费率" in t}


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


_PCT = r"([0-9]+(?:\.[0-9]+)?)\s*%"


def parse_annual_fees(text: str) -> dict:
    """解析管理费/托管费/销售服务费（年化）。"""
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
    }


_TIER_AMT = re.compile(
    r"(小于|大于等于)?([0-9.]+)(万元|元)")
_TIER_DAYS = re.compile(r"(小于|大于等于)?([0-9]+)(天|年)")


def parse_purchase_tiers(text: str) -> list[dict]:
    """解析申购费阶梯：金额区间 + 原费率 + 平台优惠费率。

    同时保留两个费率——**平台优惠不等于支付宝实际费率**。
    """
    seg = _section(text, "申购费率", ("友情提示", "赎回费率", "认购费率"))
    if not seg:
        return []
    body = seg.replace("申购费率", "", 1).replace("适用金额", "")
    body = body.replace("原费率", "").replace("天天基金优惠费率", "")
    body = body.replace("&nbsp;", "").replace("费率", "")
    parts = [x.strip() for x in body.split("|") if x.strip()]

    tiers = []
    for i, p in enumerate(parts):
        m = _TIER_AMT.search(p)
        if not m or m.group(3) != "万元":
            continue
        bound = float(m.group(2)) * 10000
        kind = m.group(1) or "大于等于"
        rates = []
        for q in parts[i + 1:i + 3]:
            rm = re.search(_PCT, q)
            if rm:
                rates.append(round(float(rm.group(1)) / 100.0, 6))
        if not rates:
            continue
        tiers.append({
            "bound_kind": kind,
            "bound_amount": bound,
            "original_rate": rates[0] if rates else None,
            "platform_rate": rates[1] if len(rates) > 1 else None,
        })
    return tiers


def parse_redeem_tiers(text: str) -> list[dict]:
    """解析赎回费阶梯：持有期限区间 + 费率。这是本项目最缺的数据。

    页面结构是「条件文本 | 费率」成对出现，但条件文本里可能含两个期限
    （如「大于等于7天，小于365天」），因此不能按单格解析——
    要按「取到条件后，紧跟的那个百分比就是该档费率」来配对。
    """
    seg = _section(text, "赎回费率", ("友情提示", "注："))
    if not seg:
        return []
    body = seg.replace("赎回费率", "", 1).replace("适用期限", "")
    parts = [x.strip() for x in body.split("|") if x.strip()]

    tiers = []
    for i, p in enumerate(parts):
        if not _TIER_DAYS.search(p):
            continue
        if re.search(_PCT, p):
            continue  # 这一格是费率不是条件
        # 取出该条件里的全部期限，取**最后一档上限**作为该档阈值
        bounds = list(_TIER_DAYS.finditer(p))
        if not bounds:
            continue
        last = bounds[-1]
        unit = last.group(3)
        value = int(last.group(2))
        days = value * 365 if unit == "年" else value
        kind = last.group(1) or "同上限"

        rate = None
        if i + 1 < len(parts):
            rm = re.search(_PCT, parts[i + 1])
            if rm:
                rate = round(float(rm.group(1)) / 100.0, 6)
        if rate is None:
            continue

        first = bounds[0]
        tiers.append({
            "condition_text": p,
            "bound_kind": kind,
            "holding_days": days,
            "holding_unit": unit,
            "holding_days_min": (
                int(first.group(2)) * 365 if first.group(3) == "年"
                else int(first.group(2))),
            "rate": rate,
        })
    return tiers


def parse_fee_page(code: str) -> dict:
    """完整解析一只基金的费率。"""
    page = fetch_fee_page(code)
    out = {
        "code": code,
        "ok": page["ok"],
        "error": page["error"],
        "page_has_fee": page.get("has_fee", False),
        "annual_fees": None,
        "purchase_tiers": [],
        "redeem_tiers": [],
        "evidence_level": "C",
        "source_url": f"http://fundf10.eastmoney.com/jjfl_{code}.html",
        "fetched_at": NOW.isoformat(timespec="seconds"),
        "note": None,
    }
    if not page["ok"] or not page.get("has_fee"):
        out["note"] = ("费率页无数据（常见于已终止基金），"
                       "历史费率在当前公开渠道**不可恢复**")
        out["evidence_level"] = "D"
        return out
    text = page["text"]
    out["annual_fees"] = parse_annual_fees(text)
    out["purchase_tiers"] = parse_purchase_tiers(text)
    out["redeem_tiers"] = parse_redeem_tiers(text)
    if not out["redeem_tiers"]:
        out["note"] = "赎回费阶梯解析为空，需人工核对页面"
    return out


# ---------------------------------------------------------------- 支付宝可行性
def audit_alipay() -> dict:
    """验证支付宝可购买状态能否合法稳定自动获取。

    只做公开页面可达性探测，**不尝试登录、不绕验证码、不用非公开接口**。
    """
    probes = []
    targets = [
        ("支付宝主站", "https://www.alipay.com/"),
        ("支付宝开放平台", "https://open.alipay.com/"),
        ("蚂蚁集团官网", "https://www.antgroup.com/"),
        ("支付宝基金子站", "https://fund.alipay.com/"),
        ("支付宝基金产品页", "https://fund.alipay.com/fund/000051"),
    ]
    for name, url in targets:
        r, err = _get(url, timeout=12, attempts=2)
        if r is None:
            probes.append({"name": name, "url": url, "reachable": False,
                           "status": None, "error": err,
                           "public_api_for_fund_status": False})
        else:
            probes.append({
                "name": name, "url": url, "reachable": True,
                "status": r.status_code,
                "error": None,
                "content_length": len(r.text),
                "public_api_for_fund_status": False,
            })
        _pause(0.3)

    return {
        "probes": probes,
        "conclusion": "not_obtainable",
        "reason": (
            "支付宝基金购买状态属于**登录态内的账户/渠道数据**，"
            "没有公开、稳定、合法的接口可以查询「某只基金在支付宝能否购买」。"
            "支付宝主站与开放平台均不提供面向第三方的基金可购买状态 API；"
            "基金子站需要登录且受访问控制。"),
        "prohibited": [
            "尝试绕过登录/验证码/风控获取状态",
            "使用非公开接口（逆向 APP 或网页私有 API）",
            "把天天基金申购状态当作支付宝状态",
        ],
        "distinction": {
            "fund_open_subscription": "基金合同层面开放申购，可用天天基金状态近似判断",
            "eastmoney_purchasable": "天天基金作为销售渠道可购买，仅代表该渠道",
            "alipay_purchasable": "支付宝作为销售渠道可购买，**无公开数据源**",
        },
        "recommendation": {
            "storage": "fund_subscription_status.alipay_purchasable 保持 'unknown'",
            "manual": (
                "建立人工核实流程：在 fund_subscription_status 增记 "
                "verified_by='manual' + as_of_date + screenshot_path，"
                "由人工在支付宝 APP 内确认后录入"),
            "never_infer": "禁止由天天基金状态、基金合同开放申购状态推断支付宝状态",
        },
    }


# ---------------------------------------------------------------- 主流程
def audit_terminated_funds() -> dict:
    """逐个验证历史终止/合并基金。"""
    results = []
    for item in TERMINATED_SAMPLES:
        code, name, cat = item[0], item[1], item[2]
        note = item[3] if len(item) > 3 else ""
        rec = {
            "code": code,
            "name_expected": name,
            "category": cat,
            "note": note,
            "in_current_name_table": False,
            "announcement_ok": False,
            "announcement_total": 0,
            "event_type": "unknown",
            "event_title": None,
            "announcement_date": None,
            "announcement_id": None,
            "announcement_url": None,
            "pdf_ok": False,
            "pdf_pages": 0,
            "doc_format": None,
            "name_actual": None,
            "established_date": None,
            "last_trading_date": None,
            "liquidation_start": None,
            "delisting_date": None,
            "final_trading_day": None,
            "successor_name": None,
            "successor_code": None,
            "evidence_level": "D",
            "automation_suitable": False,
            "missing_fields": [],
            "conflicts": [],
            "note": None,
        }

        # 1) 是否仍在存续名册
        try:
            import akshare as ak
            nm = ak.fund_name_em()
            rec["in_current_name_table"] = code in set(nm["基金代码"].astype(str))
        except Exception:  # noqa: BLE001
            rec["in_current_name_table"] = None

        # 2) 公告列表
        ann = fetch_announcements(code)
        rec["announcement_ok"] = ann["ok"]
        rec["announcement_total"] = ann["total"]
        if not ann["ok"] or not ann["rows"]:
            rec["missing_fields"] = ["全部字段（无公告）"]
            results.append(rec)
            _pause()
            continue

        # 3) 挑「事件型」公告
        # 必须先排除合同全文/托管协议/定期报告——它们正文里会提到终止，
        # 但本身不是事件公告，选错会得出错误的事件类型与日期。
        NON_EVENT = ("基金合同", "托管协议", "年度报告", "季度报告",
                     "半年度报告", "招募说明书", "产品资料概要", "基金合同生效")
        priority = ["liquidation", "share_termination", "delisting",
                    "transformation", "merge"]
        picked = None
        for ptype in priority:
            for row in ann["rows"]:
                title = row["title"] or ""
                if any(k in title for k in NON_EVENT):
                    continue
                if classify_event(title) == ptype:
                    picked = (ptype, row)
                    break
            if picked:
                break
        if picked is None:
            # 没有独立的「事件公告」时，回退到最近一条公告作为可追溯证据，
            # 事件类型保持 unknown —— 不猜。
            first = ann["rows"][0]
            rec["event_type"] = "unknown"
            rec["event_title"] = first["title"]
            rec["announcement_date"] = first["date"]
            rec["announcement_id"] = first["id"]
            rec["announcement_url"] = f"http://pdf.dfcfw.com/pdf/H2_{first['id']}_1.pdf"
            rec["evidence_level"] = "B"
            rec["missing_fields"] = ["事件型公告", "终止日期", "承接基金"]
            rec["note"] = ("该代码的公告列表里没有独立的终止/转型事件公告，"
                           "只在定期报告或合同标题里提及，回退用最近公告作可追溯证据")
            results.append(rec)
            _pause()
            continue

        etype, row = picked
        rec["event_type"] = etype
        rec["event_title"] = row["title"]
        rec["announcement_date"] = row["date"]
        rec["announcement_id"] = row["id"]
        rec["announcement_url"] = f"http://pdf.dfcfw.com/pdf/H2_{row['id']}_1.pdf"

        # 4) 读 PDF
        pdf = fetch_pdf_text(row["id"])
        rec["pdf_ok"] = pdf["ok"]
        rec["pdf_pages"] = pdf["pages"]
        rec["doc_format"] = pdf.get("format")
        if pdf["ok"]:
            dates = extract_dates_from_text(pdf["text"])
            rec.update({k: v for k, v in dates.items()
                        if k in ("established_date", "last_trading_date",
                                 "liquidation_start", "delisting_date",
                                 "final_trading_day")})
            succ = extract_successor(pdf["text"])
            rec["successor_name"] = succ["successor_name"]
            rec["successor_code"] = succ["successor_code"]
            # 从正文里找基金全称（「XX证券投资基金」）
            m = re.search(r"([\u4e00-\u9fa5A-Za-z0-9（）()]{6,40}证券投资基金)", pdf["text"])
            if m:
                rec["name_actual"] = m.group(1)

            # 有正文 + 有关键日期 = A 级证据
            if rec["last_trading_date"] or rec["delisting_date"] or rec["liquidation_start"]:
                rec["evidence_level"] = "A"
                rec["automation_suitable"] = True
            else:
                rec["evidence_level"] = "B"
        else:
            rec["missing_fields"].append("PDF 正文")

        # 5) 记录缺失字段
        for f in ("established_date", "last_trading_date", "liquidation_start",
                  "delisting_date", "successor_name"):
            if rec.get(f) is None and f not in rec["missing_fields"]:
                rec["missing_fields"].append(f)

        results.append(rec)
        _pause(0.4)

    # 统计
    by_type = {}
    by_year = {}
    for r in results:
        by_type[r["event_type"]] = by_type.get(r["event_type"], 0) + 1
        if r["announcement_date"]:
            y = str(r["announcement_date"])[:4]
            by_year[y] = by_year.get(y, 0) + 1

    with_date = [r for r in results
                 if r["last_trading_date"] or r["delisting_date"]
                 or r["liquidation_start"]]
    with_est = [r for r in results if r["established_date"]]
    with_succ = [r for r in results if r["successor_name"] or r["successor_code"]]
    a_level = [r for r in results if r["evidence_level"] == "A"]

    return {
        "samples": results,
        "count": len(results),
        "announcement_available": sum(1 for r in results if r["announcement_ok"]),
        "pdf_readable": sum(1 for r in results if r["pdf_ok"]),
        "with_terminal_date": len(with_date),
        "with_established_date": len(with_est),
        "with_successor": len(with_succ),
        "evidence_a_count": len(a_level),
        "by_event_type": by_type,
        "by_year": dict(sorted(by_year.items())),
        "not_in_current_table": sum(1 for r in results
                                    if r["in_current_name_table"] is False),
        "data_source": {
            "announcement_list": "http://api.fund.eastmoney.com/f10/JJGG/",
            "pdf": "http://pdf.dfcfw.com/pdf/H2_{announcement_id}_1.pdf",
            "evidence_level": "A（基金公司正式公告原文 PDF）",
            "note": "公告与 PDF 均为基金公司正式披露，属 A 级证据",
        },
    }


def audit_fees() -> dict:
    """验证存续基金费率可获取性 + A/C 差异 + 历史费率可恢复性。"""
    rows = []
    for item in FEE_SAMPLES:
        code, name, cat = item[0], item[1], item[2]
        pair = item[3] if len(item) > 3 else None
        rec = parse_fee_page(code)
        rec["name"] = name
        rec["category"] = cat
        rec["pair_id"] = pair
        rows.append(rec)
        _pause(0.3)

    # A/C 对比
    pairs = {}
    for r in rows:
        if r["pair_id"]:
            pairs.setdefault(r["pair_id"], []).append(r)
    pair_cmp = []
    for pid, members in pairs.items():
        if len(members) != 2:
            continue
        a = next((m for m in members if m["code"] and
                  m.get("annual_fees")), members[0])
        c = next((m for m in members if m is not a), members[1])
        af = a.get("annual_fees") or {}
        cf = c.get("annual_fees") or {}
        pair_cmp.append({
            "pair_id": pid,
            "a_code": a["code"], "a_name": a["name"],
            "c_code": c["code"], "c_name": c["name"],
            "a_purchase_rate": (a["purchase_tiers"][0]["original_rate"]
                                if a["purchase_tiers"] else None),
            "c_purchase_rate": (c["purchase_tiers"][0]["original_rate"]
                                if c["purchase_tiers"] else None),
            "a_sales_service_fee": af.get("sales_service_fee"),
            "c_sales_service_fee": cf.get("sales_service_fee"),
            "a_redeem_tier_count": len(a["redeem_tiers"]),
            "c_redeem_tier_count": len(c["redeem_tiers"]),
            "a_management_fee": af.get("management_fee"),
            "c_management_fee": cf.get("management_fee"),
        })

    # 历史费率可恢复性
    hist = []
    for code in DELISTED_FEE_PROBE:
        p = fetch_fee_page(code)
        hist.append({
            "code": code,
            "page_ok": p["ok"],
            "has_fee": p.get("has_fee", False),
            "recoverable": bool(p["ok"] and p.get("has_fee")),
            "evidence_level": "C" if (p["ok"] and p.get("has_fee")) else "D",
        })
        _pause(0.3)

    with_redeem = [r for r in rows if r["redeem_tiers"]]
    with_purchase = [r for r in rows if r["purchase_tiers"]]
    with_annual = [r for r in rows if r.get("annual_fees")]
    return {
        "samples": rows,
        "count": len(rows),
        "with_redeem_tiers": len(with_redeem),
        "with_purchase_tiers": len(with_purchase),
        "with_annual_fees": len(with_annual),
        "ac_pairs": pair_cmp,
        "ac_pair_count": len(pair_cmp),
        "historical_fee_probe": hist,
        "historical_fee_recoverable": sum(1 for h in hist if h["recoverable"]),
        "data_source": {
            "fee_page": "http://fundf10.eastmoney.com/jjfl_{code}.html",
            "evidence_level": "C",
            "note": ("天天基金 F10 费率页由基金公司提供费率数据，"
                     "但属第三方展示，不是合同原文；标注 C 级。"),
        },
    }


def audit_sources() -> dict:
    """数据源对比总表。"""
    return [
        {
            "name": "天天基金公告列表接口",
            "url": "http://api.fund.eastmoney.com/f10/JJGG/",
            "covers_terminated": True,
            "public": True,
            "auth_required": False,
            "fields": ["TITLE", "PUBLISHDATEDesc", "ID", "FUNDCODE"],
            "evidence_level": "B",
            "note": "含已终止基金的全部历史公告，是本阶段最关键发现",
            "automation_suitable": True,
        },
        {
            "name": "东财公告 PDF 原文",
            "url": "http://pdf.dfcfw.com/pdf/H2_{id}_1.pdf",
            "covers_terminated": True,
            "public": True,
            "auth_required": False,
            "fields": ["正文全文", "清算报告", "终止上市日", "最后运作日"],
            "evidence_level": "A",
            "note": "基金公司正式披露原文，可直接提取终止日期",
            "automation_suitable": True,
        },
        {
            "name": "天天基金 F10 费率页",
            "url": "http://fundf10.eastmoney.com/jjfl_{code}.html",
            "covers_terminated": False,
            "public": True,
            "auth_required": False,
            "fields": ["申购费阶梯", "赎回费阶梯", "管理费", "托管费", "销售服务费"],
            "evidence_level": "C",
            "note": "存续基金可用；已终止基金该页无数据",
            "automation_suitable": True,
        },
        {
            "name": "akshare.fund_name_em",
            "url": "akshare",
            "covers_terminated": False,
            "public": True,
            "auth_required": False,
            "fields": ["基金代码", "简称", "类型"],
            "evidence_level": "C",
            "note": "**只含存续基金**，不能用于清盘名录",
            "automation_suitable": True,
        },
        {
            "name": "支付宝基金购买状态",
            "url": "无公开接口",
            "covers_terminated": False,
            "public": False,
            "auth_required": True,
            "fields": [],
            "evidence_level": "D",
            "note": "登录态内数据，无公开合法接口，不可自动获取",
            "automation_suitable": False,
        },
    ]


def main(out_dir: Path) -> dict:
    print("审计历史终止基金...", flush=True)
    terminated = audit_terminated_funds()
    print(f"  {terminated['count']} 只，PDF 可读 {terminated['pdf_readable']}", flush=True)

    print("审计费率...", flush=True)
    fees = audit_fees()
    print(f"  {fees['count']} 只，A/C 配对 {fees['ac_pair_count']}", flush=True)

    print("审计支付宝...", flush=True)
    alipay = audit_alipay()

    print("数据源对比...", flush=True)
    sources = audit_sources()

    payload = {
        "phase": "3B-4.1",
        "baseline_head": "e02096c5ed944416c1c69182a44a73d8f282d26f",
        "generated_at": NOW.isoformat(timespec="seconds"),
        "scope": "只做数据源研究、样本验证与技术方案；不改正式数据层、不做迁移、不做回测",
        "evidence_levels": EVIDENCE_LEVELS,
        "event_types": EVENT_TYPES,
        "sources": sources,
        "terminated_funds": terminated,
        "fees": fees,
        "alipay": alipay,
        "answers": build_answers(terminated, fees, alipay),
        "unresolved": [
            "清盘名录覆盖率无法量化：没有权威的全量清单可比对",
            "净值数据源只覆盖部分已终止基金（150001 返回 404）",
            "已终止基金的历史费率在公开渠道不可恢复",
            "支付宝可购买状态无公开合法接口",
            "合并承接基金代码仅部分公告明确写出",
        ],
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    jp = out_dir / "phase3B4_1_critical_data_sources.json"
    jp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"JSON -> {jp}", flush=True)
    return payload


def build_answers(terminated: dict, fees: dict, alipay: dict) -> dict:
    t_ok = terminated["pdf_readable"]
    t_total = terminated["count"]
    return {
        "q1_liquidated_roster_reliable": {
            "answer": "partially",
            "detail": (
                f"{t_total} 只样本中 {terminated['announcement_available']} 只有公告、"
                f"{t_ok} 只 PDF 可读、{terminated['with_terminal_date']} 只能提取终止日期。"
                "名录**可以建立**，但只能「按事件建立」，不能「按全量清单建立」。"),
            "coverage": "无法量化（没有权威全量清单可比对）",
            "main_gap": "缺一个权威的「全市场已终止基金清单」；只能靠代码域扫描 + 公告反查",
        },
        "q2_redemption_fee_tiers": {
            "answer": "yes_for_living_funds",
            "detail": (
                f"{fees['count']} 只样本中 {fees['with_redeem_tiers']} 只成功解析出赎回费阶梯，"
                f"{fees['with_purchase_tiers']} 只解析出申购费阶梯，"
                f"{fees['with_annual_fees']} 只拿到年化费率。"),
            "caveat": "来源是天天基金 F10 页（C 级），不是合同原文（A 级）",
        },
        "q3_historical_fees_recoverable": {
            "answer": "no" if fees["historical_fee_recoverable"] == 0 else "partial",
            "detail": (
                f"探测 {len(fees['historical_fee_probe'])} 只已终止基金，"
                f"仅 {fees['historical_fee_recoverable']} 只费率页有数据。"),
            "conclusion": "已终止基金的历史费率在公开渠道基本不可恢复",
        },
        "q4_alipay_status_automatable": {
            "answer": "no",
            "detail": alipay["reason"],
            "recommendation": alipay["recommendation"],
        },
        "q5_worth_automating": [
            "历史清盘/合并名录（公告列表 + PDF 原文，A 级证据，可自动化）",
            "存续基金费率（F10 页可解析，C 级，可自动化但须标注非合同原文）",
        ],
        "q6_keep_manual": [
            "支付宝可购买状态（无公开接口，必须人工核实）",
            "已终止基金的历史费率（不可恢复，只能人工从合同 PDF 提取）",
            "合并承接基金代码（部分公告未明确写出，需人工核对）",
        ],
    }


if __name__ == "__main__":
    main(ROOT / "reports")
