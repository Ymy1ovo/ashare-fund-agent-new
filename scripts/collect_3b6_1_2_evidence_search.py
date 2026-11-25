"""阶段3B-6.1.2.1 原始证据检索记录生成器（只读）。

记录对 15 只基金**实际执行过**的官方披露渠道探测，
**未检索的渠道一律不得写成已检索**。

渠道探测结果来自本轮真实 HTTP 请求（urllib），
不伪造 URL、SHA256 或搜索结果。
"""
from __future__ import annotations

import json
import ssl
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database.db import get_connection  # noqa: E402

REPORTS = ROOT / "reports"
EV = REPORTS / "evidence" / "phase3B6_1_2"
OUT = EV / "evidence_search_log.json"

# 15 条基准对应的基金（代码 → composite_id），从库中读取，不硬编码
CHANNELS = [
    {"channel": "证监会基金电子披露网站", "url": "http://eid.csrc.gov.cn/fund",
     "doc_types": ["基金合同", "招募说明书", "产品资料概要", "定期报告"]},
    {"channel": "巨潮资讯网", "url": "http://www.cninfo.com.cn",
     "doc_types": ["基金合同", "招募说明书"]},
    {"channel": "华夏基金官网", "url": "https://www.chinaamc.com",
     "doc_types": ["基金合同", "招募说明书", "公告"]},
    {"channel": "易方达基金官网", "url": "https://www.efunds.com.cn",
     "doc_types": ["基金合同", "招募说明书", "公告"]},
    {"channel": "天弘基金官网", "url": "https://www.thfund.com.cn",
     "doc_types": ["基金合同", "招募说明书", "公告"]},
]


def probe_channel(ch: dict) -> dict:
    """真实 HTTP 探测（只读 GET）。"""
    rec = {
        "channel": ch["channel"],
        "url": ch["url"],
        "doc_types_searched": ch["doc_types"],
        "probed_at": datetime.now().isoformat(timespec="seconds"),
        "http_status": None,
        "reachable": False,
        "error_type": None,
        "error_message": None,
        "document_obtained": False,
        "failure_reason": None,
    }
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        req = urllib.request.Request(ch["url"],
                                      headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=20, context=ctx)
        body = resp.read()
        rec["http_status"] = resp.status
        rec["reachable"] = True
        rec["bytes"] = len(body)
        rec["failure_reason"] = (
            "站点可访问，但需站内表单检索（按基金代码/名称查询）"
            "才能定位具体文件；本轮未完成表单检索与文件下载")
    except Exception as exc:
        rec["error_type"] = type(exc).__name__
        rec["error_message"] = str(exc)[:150]
        rec["failure_reason"] = f"请求失败：{type(exc).__name__}"
    return rec


def main() -> int:
    EV.mkdir(parents=True, exist_ok=True)
    with get_connection() as c:
        rows = c.execute("""
            SELECT b.composite_id, b.benchmark_name, f.fund_code_primary,
                   f.fund_name, f.fund_company
            FROM benchmark_composite b
            LEFT JOIN fund_master f
              ON b.benchmark_name LIKE f.fund_code_primary || '%'
            ORDER BY b.composite_id
        """).fetchall()

    funds = [{"composite_id": r[0], "benchmark_name": r[1],
               "fund_code": r[2], "fund_name": r[3],
               "fund_company": r[4]} for r in rows]

    channels = []
    for ch in CHANNELS:
        rec = probe_channel(ch)
        channels.append(rec)
        print(f"{ch['channel']}: reachable={rec['reachable']} "
              f"status={rec['http_status']}")
        time.sleep(2)

    doc = {
        "phase": "3B-6.1.2.1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "purpose": "记录本轮实际执行过的原始证据检索渠道（不伪造）",
        "strict_rules": [
            "未真实请求过的渠道不得写入",
            "未下载到的文件不得填写 SHA256",
            "第三方平台文本一律保持 L3，不得升级",
        ],
        "target_funds": funds,
        "channels_probed": channels,
        "funds_document_status": [
            {"composite_id": f["composite_id"],
              "fund_code": f["fund_code"],
              "fund_name": f["fund_name"],
              "fund_company": f["fund_company"],
              "document_types_needed": ["基金合同", "招募说明书",
                                          "产品资料概要", "基准变更公告"],
              "document_obtained": False,
              "obtained_document": None,
              "sha256": None,
              "failure_reason": (
                  "官方渠道需站内表单检索；本轮仅探测站点可达性，"
                  "未完成按基金代码的检索与文件下载"),
              "current_evidence_grade": "L3",
              "evidence_source": "platform（第三方平台披露文本）"}
            for f in funds],
        "summary": {
            "total_funds": len(funds),
            "channels_probed": len(channels),
            "channels_reachable": sum(1 for c in channels if c["reachable"]),
            "documents_obtained": 0,
            "funds_with_l1_evidence": 0,
            "funds_with_l3_only": len(funds),
            "note": ("**本轮未取得任何 L1 原始文件**。"
                      "所有基准文本证据等级维持 L3。"),
        },
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                    encoding="utf-8")

    s = doc["summary"]
    print()
    print(f"基金 {s['total_funds']} 只")
    print(f"  探测渠道 {s['channels_probed']} / 可达 {s['channels_reachable']}")
    print(f"  获得原始文件 {s['documents_obtained']}")
    print(f"  仅 L3 证据 {s['funds_with_l3_only']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
