"""阶段3B-4.1.1 验收修正：基金类型分类与证据等级口径校准（只读）。

范围严格受限：
- 不重新扫描 844 个代码
- 不新增公告采集（只重读已有的 43 条公告原文，用于修正基金全称与类型）
- 不改 app/fund/、不改 migrations/、不写正式库、不做回测

修正两件事：
1. 43 条清盘记录的基金类型（产品结构 + 投资类型两个独立维度）
2. 43 条清盘记录的证据等级（东财转载 ≠ 官方原始公告）
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

from scripts.research_3b4_1_1_roster_fee_audit import (  # noqa: E402
    fetch_doc_text, _compact_cn,
)

NOW = datetime.now()
BASE_JSON = ROOT / "reports" / "phase3B4_1_1_historical_roster_fee_audit.json"
OUT_JSON = ROOT / "reports" / "phase3B4_1_1_types_evidence_calibration.json"
MERGE_INTO = ROOT / "reports" / "phase3B4_1_1_historical_roster_fee_audit.json"

# ---------------------------------------------------------------- 分类枚举
PRODUCT_STRUCTURE = {
    "ordinary_open_ended": "普通开放式（场外，无场内交易代码）",
    "etf_linked": "ETF 联接基金（场外申购，投资于目标 ETF）",
    "etf": "场内 ETF（交易所上市交易）",
    "lof": "LOF（上市开放式，场内场外均可）",
    "other": "其他结构",
    "unknown": "无法确认",
}

INVESTMENT_TYPE = {
    "money_market": "货币市场",
    "bond": "债券",
    "mixed": "混合",
    "equity": "股票",
    "index": "指数（无法归入股/债/混时的兜底）",
    "other": "其他",
    "unknown": "无法确认",
}

# 证据等级：按**发布渠道**判，不按「能否下载」
EVIDENCE_LEVELS = {
    "A": "基金管理人官网 / 交易所官网 / 证监会电子披露平台的原始公告",
    "B": "第三方转载（东方财富等），原文完整可读、可追溯，但发布主体非官方",
    "C": "可靠第三方结构化摘要，无原文",
    "D": "无法确认来源",
}

# ---------------------------------------------------------------- 名称规范化
# 用正文首行/标题里的有效基金全称替换掉被截断的错误名称。
_FULLNAME_STOP = re.compile(
    r"(清算报告|基金合同终止|终止基金合同|终止上市|基金财产清算|"
    r"份额持有人大会|提示性公告|公告)$")


_NAME_NOISE = (
    r"^\d+\s*",                      # 页码
    r"^(?:临时公告|公司公告|公告)\s*",
    r"^(?:关于|有关|就)",
    r"^.*?(?:基金管理|基金管理有限责任)[^，。]{0,20}?(?:有限公司|公司)(?:关于)?",
    r"的?(?:特别)?(?:提示性)?公告.*$",
    r"(?:清算报告|基金合同终止|终止基金合同|终止上市|基金财产清算).*$",
    r"第[一二三四五六七八九十]+次",
    r"[（(]?\d{4}[/年]\d{1,2}[/月]\d{1,2}日?[）)]?",
)


def _clean_name(raw: str) -> str | None:
    """清洗基金全称：去页码/前缀/公告后缀/重复的「联接基金」/多余空格。"""
    if not raw:
        return None
    t = _compact_cn(raw)
    t = re.sub(r"[\s\u3000]+", "", t)
    for _ in range(3):                       # 多轮清洗，前缀可能层层剥开
        before = t
        for pat in _NAME_NOISE:
            t = re.sub(pat, "", t)
        if t == before:
            break
    t = t.strip("的：:，,。 ")
    # 「联接基金联接基金」是正文标题与全称叠加造成的
    t = re.sub(r"(联接基金)+$", "联接基金", t)
    t = re.sub(r"(证券投资基金)(证券投资基金)+", r"\1", t)
    # 「…证券投资基金基金」是正文与标题叠加造成的重复尾字
    t = re.sub(r"(证券投资基金)基金+$", r"\1", t)
    t = re.sub(r"(证券投资基金)基金$", r"\1", t)
    if len(t) < 8 or len(t) > 60:
        return None
    if not t.endswith(("证券投资基金", "基金")):
        return None
    return t


def extract_full_name(text: str, fallback_title: str) -> tuple[str | None, str]:
    """从公告正文提取基金全称，正文抽不到再用标题。

    返回 (全称, 来源)。来源 ∈ {"body", "title", "fallback"}。
    """
    if text:
        head = _compact_cn(text)[:300]
        m = re.match(r"^[\s\d]*(.{6,80}?(?:证券投资基金|基金))(?:清算报告|基金合同终止|"
                     r"终止基金合同|终止上市|基金财产清算)", head)
        if m:
            name = m.group(1)
            # 原文若在「证券投资基金」后紧跟「联接基金」，补完整
            tail = head[m.end(1):m.end(1) + 6]
            if "联接" in tail:
                name += "联接基金"
            cleaned = _clean_name(name)
            if cleaned:
                return cleaned, "body"

    if fallback_title:
        # 标题里若直接写明「联接基金」，优先保留
        t = _compact_cn(fallback_title)
        if "联接基金" in t:
            t = re.sub(r"^[\s\d]*", "", t)
            cleaned = _clean_name(t)
            if cleaned:
                return cleaned, "title"
        cleaned = _clean_name(t)
        if cleaned:
            return cleaned, "title"
    return None, "fallback"


# ---------------------------------------------------------------- 类型判定
def classify_structure(name: str, text: str,
                       title: str | None = None) -> tuple[str, list[str]]:
    """产品结构（交易形式）。返回 (结构, 证据标记列表)。

    判定优先级：联接 > ETF > LOF > 普通开放式。
    **不得仅凭代码前缀推断**；线索只能来自基金全称、公告标题、公告正文。
    """
    ev = []
    blob = name or ""
    tl = title or ""
    body = (text or "")[:3000]
    pool = blob + " " + tl + " " + body

    has_lianjie = ("联接" in blob) or ("联接" in tl)
    has_etf_full = "交易型开放式指数证券投资基金" in blob
    has_lof = (("(LOF)" in pool) or ("（LOF）" in pool)
               or ("上市开放式基金" in pool) or ("上市型开放式基金" in pool)
               or ("上市开放式" in blob) or ("上市型开放式" in blob))

    if has_lianjie:
        ev.append("基金全称或公告标题含「联接」")
        return "etf_linked", ev
    if has_etf_full:
        ev.append("基金全称含「交易型开放式指数证券投资基金」且无「联接」")
        return "etf", ev
    if has_lof:
        ev.append("基金全称/标题/正文含 LOF 或「上市开放式基金」")
        return "lof", ev
    if blob:
        ev.append("基金全称为普通形态，无 ETF/LOF/联接标记")
        return "ordinary_open_ended", ev
    return "unknown", ["既无基金全称也无公告标题"]


def classify_investment(name: str, text: str) -> tuple[str, bool, list[str]]:
    """投资类型。返回 (类型, 是否指数, 证据标记)。"""
    ev = []
    blob = name or ""
    if not blob:
        return "unknown", False, ["无名称"]

    is_index = ("指数" in blob) or ("指数" in (text or "")[:800])

    if "货币市场基金" in blob or "货币市场" in blob:
        ev.append("名称含「货币市场」")
        return "money_market", is_index, ev
    if "债券" in blob:
        ev.append("名称含「债券」")
        return "bond", is_index, ev
    if "混合" in blob:
        ev.append("名称含「混合」")
        return "mixed", is_index, ev
    if "股票" in blob:
        ev.append("名称含「股票」")
        return "equity", is_index, ev
    if is_index:
        ev.append("名称含「指数」但无股/债/混限定")
        return "index", True, ev
    ev.append("名称无法归入股/债/混/货币")
    return "other", is_index, ev


# 代码前缀只能作为「线索」记录，**不得据此改判定**。
PREFIX_HINTS = {
    "51": "ETF（上交所）",
    "15": "分级子份额（深交所）",
    "16": "LOF（深交所）",
    "50": "LOF（上交所）",
    "501": "LOF（上交所）",
    "18": "封闭式（深交所）",
}


def prefix_hint(codes: list[str]) -> str | None:
    """代码前缀给出的结构线索——只记录，不采信。"""
    for c in codes:
        for pfx in ("501", "51", "50", "16", "18", "15"):
            if c.startswith(pfx):
                return PREFIX_HINTS[pfx]
    return None


# 关键口径：这是「**产品结构**是否属于场外范围」，不是「支付宝能不能买」。
# 支付宝实际可购买状态全部是 unknown，没有任何官方或可靠接口证据。
ALIPAY_STATUS = "unknown"
ALIPAY_EVIDENCE = "not_obtainable"


def in_offmarket_structure(structure: str) -> bool:
    """该产品结构是否属于**场外结构范围**。

    - etf（场内）：❌ 不在场外结构范围内
    - etf_linked：✅ 场外申购型
    - lof：✅ 有场外份额
    - ordinary_open_ended：✅
    - other / unknown：不确定，保守算 ❌

    **注意：属于场外结构 ≠ 支付宝当前可购买。**
    这只是筛掉场内 ETF，用于确定研究对象的产品结构范围，
    不代表这些历史清盘基金曾在支付宝上架、也不代表现在还能买。
    """
    return structure in ("etf_linked", "lof", "ordinary_open_ended")


# 兼容旧名（测试与外部引用），语义已收窄为「结构范围」
offmarket_eligible = in_offmarket_structure


# ---------------------------------------------------------------- 证据分级
# 关键修正：所有 43 条公告链接都是 pdf.dfcfw.com（东方财富转载），
# 即使原文 PDF 里是基金公司盖章文本，发布渠道仍是第三方 → 不能给 A。
OFFICIAL_HOSTS = (
    "csrc.gov.cn",        # 证监会
    "eid.csrc.gov.cn",    # 证监会基金电子披露平台
    "sse.com.cn",         # 上交所
    "szse.cn",            # 深交所
)


def grade_evidence(url: str, *, official_verified: bool = False) -> tuple[str, str]:
    """按**发布渠道**判证据等级，不按「PDF 能否下载」。

    返回 (等级, 理由)。
    """
    if not url:
        return "D", "无公告链接"
    host = re.sub(r"^https?://", "", url).split("/")[0].lower()
    if any(h in host for h in OFFICIAL_HOSTS):
        if official_verified:
            return "A", f"官方域名（{host}）且已回源验证"
        return "B", f"官方域名（{host}）但未回源验证"
    if "dfcfw.com" in host or "eastmoney.com" in host:
        return "B", f"第三方转载（{host}），原文完整可读、可追溯，但发布主体非官方"
    return "D", f"无法确认发布机构（{host}）"


# ---------------------------------------------------------------- 主流程
def main() -> dict:
    src = json.loads(BASE_JSON.read_text(encoding="utf-8"))
    events = src["roster"]["events"]
    liq = [e for e in events if e["event_type"] == "liquidation"]

    print(f"只重读已有 {len(liq)} 条清盘公告原文，不重新扫描代码、不新增采集", flush=True)

    calibrated = []
    for i, e in enumerate(liq, 1):
        if i % 10 == 0:
            print(f"  {i}/{len(liq)}", flush=True)
        doc = fetch_doc_text(e["announcement_id"], pages=6)
        text = doc["text"] or ""
        time.sleep(0.3)

        full_name, name_src = extract_full_name(text, e["announcement_title"])
        use_name = full_name or e["fund_entity"]

        structure, s_ev = classify_structure(use_name, text, e["announcement_title"])
        inv, is_index, i_ev = classify_investment(use_name, text)
        level, level_reason = grade_evidence(e["announcement_url"])

        rec = {
            "event_key": e["event_key"],
            "codes_in_event": e["codes_in_event"],
            "fund_entity_old": e["fund_entity"],
            "fund_entity": use_name,
            "name_source": name_src,
            "name_changed": use_name != e["fund_entity"],
            "announcement_id": e["announcement_id"],
            "announcement_title": e["announcement_title"],
            "announcement_date": e["announcement_date"],
            "announcement_url": e["announcement_url"],
            "event_date": e["event_date"],
            "doc_ok": doc["ok"],
            "doc_format": doc["format"],
            "product_structure": structure,
            "product_structure_reason": s_ev,
            "investment_type": inv,
            "investment_type_reason": i_ev,
            "prefix_hint": prefix_hint(e["codes_in_event"]),
            "prefix_conflict": (prefix_hint(e["codes_in_event"]) is not None
                                and structure != "lof"
                                and structure != "etf"),
            "is_index_fund": is_index,
            "is_onshore_etf": structure == "etf",
            "in_offmarket_structure": in_offmarket_structure(structure),
            "offmarket_eligible": in_offmarket_structure(structure),
            "alipay_purchasable": ALIPAY_STATUS,
            "alipay_evidence": ALIPAY_EVIDENCE,
            "evidence_level": level,
            "evidence_reason": level_reason,
        }
        calibrated.append(rec)

    # 统计
    by_struct = {}
    for r in calibrated:
        by_struct[r["product_structure"]] = by_struct.get(r["product_structure"], 0) + 1
    by_inv = {}
    for r in calibrated:
        by_inv[r["investment_type"]] = by_inv.get(r["investment_type"], 0) + 1
    by_level = {}
    for r in calibrated:
        by_level[r["evidence_level"]] = by_level.get(r["evidence_level"], 0) + 1

    offmarket = [r for r in calibrated if r["in_offmarket_structure"]]
    onshore_etf = [r for r in calibrated if r["is_onshore_etf"]]
    unknown_type = [r for r in calibrated if r["product_structure"] == "unknown"]

    print(f"  结构分布: {by_struct}", flush=True)
    print(f"  投资类型分布: {by_inv}", flush=True)
    print(f"  证据分布: {by_level}", flush=True)

    payload = {
        "phase": "3B-4.1.1-calibration",
        "baseline_head": "22b8fc993cd37fce4fcc68671eb07145654c330e",
        "generated_at": NOW.isoformat(timespec="seconds"),
        "scope": (
            "验收修正：只对已有 43 条清盘事件重新判定基金类型与证据等级。"
            "未重新扫描 844 个代码、未新增公告采集、未改数据层与迁移、未入库、未回测。"),
        "corrections": {
            "what_was_wrong": [
                "43 条清盘全部标 A 级——错。公告链接全部是 pdf.dfcfw.com（东财转载），"
                "即使原文是基金公司正式文本，发布渠道仍是第三方，不能给 A。",
                "基金类型未区分场内 ETF / ETF 联接 / LOF / 普通开放式，"
                "导致把场内 ETF（511000、511050）也算进「支付宝场外基金」样本。",
                "部分基金名称被截断，漏掉「联接基金」四处（020025、020035、000087、000088）。",
            ],
            "what_was_kept": [
                "费率解析器的三个 Bug 修复（比较符顺序、闭区间连续性、首档下界推断）。",
                "去重规则（同公告=同事件、披露链归并、终止上市并入清盘）。",
                "天天基金 F10 费率 = C 级的定级。",
            ],
        },
        "field_semantics": {
            "offmarket_structure_count": (
                "属于**场外产品结构范围**的清盘基金本体数量（普通开放式 + ETF联接 + LOF）。"
                "**不是**支付宝可购买数量。"),
            "alipay_purchasable_count": (
                "支付宝实际可购买数量。恒为 0，因为全部状态 unknown、无官方或可靠接口证据。"),
            "alipay_status": (
                "支付宝可购买状态。恒为 unknown（3B-4.1 结论 not_obtainable）。"),
            "note": (
                "结构分类 ≠ 支付宝上架状态。ETF联接/LOF/普通开放式可以纳入场外**研究范围**，"
                "但不代表这些历史清盘基金曾在支付宝销售，也不代表现在仍可买。"),
        },
        "enums": {
            "product_structure": PRODUCT_STRUCTURE,
            "investment_type": INVESTMENT_TYPE,
            "evidence_level": EVIDENCE_LEVELS,
        },
        "calibration": calibrated,
        "stats": {
            "liquidation_total": len(calibrated),
            "by_product_structure": by_struct,
            "by_investment_type": by_inv,
            "by_evidence_level": by_level,
            "offmarket_structure_count": len(offmarket),
            "offmarket_count": len(offmarket),   # 兼容旧名，语义 = 场外结构范围
            "alipay_purchasable_count": 0,
            "alipay_status": ALIPAY_STATUS,
            "onshore_etf_count": len(onshore_etf),
            "unknown_type_count": len(unknown_type),
            "name_changed_count": sum(1 for r in calibrated if r["name_changed"]),
            "etf_linked_count": by_struct.get("etf_linked", 0),
            "lof_count": by_struct.get("lof", 0),
            "ordinary_count": by_struct.get("ordinary_open_ended", 0),
        },
        "offmarket_samples": [
            {"codes": r["codes_in_event"], "name": r["fund_entity"],
             "structure": r["product_structure"],
             "investment_type": r["investment_type"],
             "evidence_level": r["evidence_level"]}
            for r in offmarket
        ],
        "onshore_etf_samples": [
            {"codes": r["codes_in_event"], "name": r["fund_entity"],
             "evidence_level": r["evidence_level"]}
            for r in onshore_etf
        ],
        "unresolved": [
            "43 条公告均来自东方财富转载，未逐条回源到基金公司官网/交易所官网，"
            "因此全部只能给 B 级；若日后回源验证可升 A。",
            "ETF 联接基金与目标 ETF 的对应关系未建立（公告未写目标 ETF 代码）。",
            "合并事件仍为 0 个。",
            "清盘名录覆盖率仍不可量化。",
            "支付宝实际可购买状态全部 unknown：结构分类不等于平台上架状态，"
            "41 只只是「场外结构范围」，不是「支付宝可买」。",
        ],
    }

    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    print(f"JSON -> {OUT_JSON}", flush=True)

    # 把校准结果并入 3B-4.1.1 主 JSON，供测试与报告共用同一份数据。
    base = json.loads(MERGE_INTO.read_text(encoding="utf-8"))
    base["types_evidence_calibration"] = payload
    MERGE_INTO.write_text(json.dumps(base, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    print(f"merged -> {MERGE_INTO}", flush=True)
    return payload


if __name__ == "__main__":
    main()
