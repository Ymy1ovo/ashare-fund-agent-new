"""阶段3B-4.0：把 12 只样本基金的真实数据导入场外基金数据层。

只读外部接口，只写 fund_* 新表；不触碰任何 ETF 表。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.fund.ingest import FundIngestor, IngestStats  # noqa: E402
from app.fund.migration import ensure_fund_schema  # noqa: E402
from app.fund.normalize import is_money_fund, to_float  # noqa: E402
from app.fund.repo_nav import NavRepository  # noqa: E402
from app.fund.repo_quality import QualityRepository  # noqa: E402
from app.fund.repo_status import StatusRepository  # noqa: E402
from app.fund.repository import FundRepository  # noqa: E402

# 按「基金本体」分组：同一组内的代码共享一个 master，各自一个 share_class。
# 分组依据是去掉份额后缀后名称一致（A/C 配对）。单只的组就是独立本体。
GROUPS = [
    ("宽基指数", ["000051"]),
    ("宽基指数", ["110020"]),
    ("行业指数", ["161725", "012414"]),      # 招商中证白酒 A/C
    ("ETF联接", ["007300", "007301"]),        # 国联安半导体 A/C
    ("主动权益", ["110022"]),
    ("主动权益", ["161005"]),
    ("指数增强", ["000478"]),
    ("债券", ["000015", "000016"]),           # 华夏纯债 A/C
    ("货币", ["000198"]),
]

SOURCE_NAME_EM = "akshare.fund_name_em"
SOURCE_BASIC_XQ = "akshare.fund_individual_basic_info_xq"


def _retry(fn, attempts=3, wait=1.2):
    last = None
    for i in range(attempts):
        try:
            return fn(), None
        except Exception as exc:  # noqa: BLE001
            last = exc
            if i + 1 < attempts:
                time.sleep(wait * (i + 1))
    return None, f"{type(last).__name__}: {str(last)[:160]}"


def parse_scale(value) -> float | None:
    """「114.34亿」→ 114.34。单位统一存亿元，另记 aum_unit。"""
    if value is None:
        return None
    s = str(value).strip()
    if s in ("", "--", "nan", "None"):
        return None
    mult = 1.0
    if s.endswith("亿"):
        s, mult = s[:-1], 1.0
    elif s.endswith("万"):
        s, mult = s[:-1], 0.0001
    f = to_float(s)
    return None if f is None else round(f * mult, 6)


def main() -> dict:
    print("建表（幂等）...", flush=True)
    schema_before = ensure_fund_schema()

    ing = FundIngestor()
    stats = IngestStats()
    detail = []

    print("拉取全量代码表...", flush=True)
    name_table, err = _retry(lambda: ing._fetch_name_table())
    if name_table is None:
        raise RuntimeError(f"代码表获取失败: {err}")
    name_map = {r["fund_code"]: r for r in name_table}
    print(f"  代码表 {len(name_map)} 条", flush=True)

    print("拉取申购状态表...", flush=True)
    purchase_map, _ = _retry(lambda: ing._fetch_purchase())
    purchase_map = purchase_map or {}
    today = time.strftime("%Y-%m-%d")

    for cat, codes in GROUPS:
        print(f"  组 {cat} {codes}...", flush=True)
        members, basics = [], {}
        for code in codes:
            name_row = name_map.get(code)
            if name_row is None:
                detail.append({"code": code, "category": cat,
                               "status": "failed",
                               "notes": ["代码表里没有该基金"]})
                continue
            members.append(name_row)
            basic, basic_err = _retry(lambda: ing._fetch_basic(code))
            basics[code] = basic
            if basic is None:
                print(f"    {code} 基本信息失败: {basic_err}", flush=True)

        if not members:
            continue

        group_res = ing.ingest_fund_group(members, basics=basics, stats=stats)
        fund_id = group_res["fund_id"]

        for code in codes:
            name_row = name_map.get(code)
            if name_row is None:
                continue
            sc_id = group_res["share_ids"].get(code)
            basic = basics.get(code)
            item = {
                "code": code, "category": cat, "status": "ok", "notes": [],
                "fund_id": fund_id, "share_class_id": sc_id,
                "group_merged": group_res["merged"],
                "group_primary": group_res.get("primary_code"),
                "needs_review": group_res.get("needs_review"),
                "is_money": is_money_fund(name_row.get("fund_type")),
            }
            if basic is None:
                item["notes"].append("基本信息接口失败，字段保持 NULL")

            money = item["is_money"]
            item["nav"] = ing.ingest_nav(code, sc_id, is_money=money, stats=stats)
            if not money:
                item["dividends"] = ing.ingest_dividends(code, sc_id, stats=stats)

            st = ing.ingest_status(code, sc_id,
                                   purchase_row=purchase_map.get(code), stats=stats)
            item["status_rows"] = st.get("written", 0)

            if basic:
                mgr_text = basic.get("manager") or ""
                names = [x for x in mgr_text.replace("、", ",").split(",") if x.strip()]
                ing.ingest_manager(code, fund_id,
                                   managers=[{"manager_name": n.strip(),
                                              "company": basic.get("company")}
                                             for n in names],
                                   stats=stats)
                ing.ingest_aum(code, fund_id,
                               aum_total=parse_scale(basic.get("scale")),
                               report_date=today, stats=stats)

            detail.append(item)
            time.sleep(0.2)

    print("写数据质量总览...", flush=True)
    qr = QualityRepository()
    nav_repo = NavRepository()
    funds_repo = FundRepository()
    sr = StatusRepository()

    qr.record_many([
        _dq("fund_lifecycle_events", "global:liquidated_names",
            "liquidated_fund_list_missing", "missing",
            "当前无清盘基金名录数据源，survivorship_bias_unresolved 未解决",
            "warning"),
        _dq("fund_fee_rules", "global:redemption_fee",
            "redemption_fee_tier_missing", "missing",
            "赎回费阶梯无任何数据源，rate 保持 NULL，未填行业平均", "warning"),
        _dq("fund_subscription_status", "global:alipay",
            "alipay_purchasable_unknown", "missing",
            "支付宝可购买状态无可靠证据，全部保持 unknown", "info"),
    ])
    stats.quality_written += 3

    summary = {
        "schema_before": schema_before,
        "stats": stats.as_dict(),
        "samples": detail,
        "db_counts": {
            "fund_master": funds_repo.count_master(),
            "fund_share_classes": funds_repo.count_share_classes(),
            "fund_nav_daily": nav_repo.count_nav(),
            "fund_nav_daily_net_value": nav_repo.count_nav("net_value"),
            "fund_nav_daily_money_yield": nav_repo.count_nav("money_yield"),
            "fund_dividends": nav_repo.count_dividends(),
            "fund_subscription_status": sr.count_subscription_status(),
            "fund_fee_rules": sr.count_fee_rules(),
            "fund_data_quality": qr.count(),
        },
        "quality_summary": qr.summary(),
        "share_grouping": _grouping_report(funds_repo, GROUPS),
    }

    out = ROOT / "reports" / "phase3B4_fund_data_layer.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"JSON -> {out}", flush=True)
    return summary



def _grouping_report(repo, groups) -> list:
    """验证 A/C 归到同一个基金本体。"""
    out = []
    for cat, codes in groups:
        masters = {}
        for code in codes:
            sc = repo.get_share_class(code)
            if sc:
                masters.setdefault(sc["fund_id"], []).append(code)
        out.append({
            "category": cat,
            "codes": codes,
            "distinct_fund_ids": len(masters),
            "fund_id_to_codes": {str(k): v for k, v in masters.items()},
            "correctly_grouped": len(masters) == 1,
        })
    return out


def _dq(table, key, check, status, detail, severity):
    from app.fund.models import DataQualityRecord
    return DataQualityRecord(table_name=table, record_key=key, check_name=check,
                             status=status, detail=detail, severity=severity,
                             checked_at=time.strftime("%Y-%m-%dT%H:%M:%S"))


if __name__ == "__main__":
    main()
