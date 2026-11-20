"""费用比较层（份额维度）。

硬性边界：
- 11 条有公告生效日的年化费率：只能在该生效日**之后**使用。
- 79 条无生效日的费率：**不能**用于历史费率还原。
- 申购费/赎回费阶梯不完整：只能当前情景估算。
- `holding_days_basis` 全 NULL：自然日/交易日口径未确认。
- 支付宝实际费率 unknown：天天基金费率**不冒充**支付宝。
- 费率缺失必须显示 unknown/not_available，**不假设 0**。
"""
from __future__ import annotations

from pathlib import Path

from app.fund.research.data_access import load_fee_info

# 已在净值中扣除、不得重复计提的费率类型
DEDUCTED_IN_NAV = ("management", "custody", "sales_service")


def compare_share_costs(db_path: Path | None = None, *,
                        fund_id: int,
                        shares: list[dict]) -> dict:
    """同一基金本体下不同份额（A/C/E）的费用比较。

    只比较**费用**，不合并表现。表现比较请按 fund_id 归并。
    """
    if not shares:
        return {"fund_id": fund_id, "shares": [],
                "status": "no_shares"}

    rows = []
    for s in shares:
        info = load_fee_info(db_path, code=s["share_code"])
        annual = info.get("annual_fees") or {}
        rows.append({
            "share_code": s["share_code"],
            "share_name": s["share_name"],
            "is_primary": s.get("is_primary"),
            "sales_service_fee": _fee_cell(annual.get("sales_service")),
            "management_fee": _fee_cell(annual.get("management")),
            "custody_fee": _fee_cell(annual.get("custody")),
            "purchase_fee": _tier_cell(info.get("purchase_fee")),
            "redemption_fee": _tier_cell(info.get("redemption_fee")),
            "alipay_fee": {"status": "unknown",
                           "note": "支付宝实际费率无公开合法数据源"},
        })

    # 差异只在「有值」时可比；任一侧 unknown 就不下结论
    diffs = []
    if len(rows) >= 2:
        base = rows[0]
        for other in rows[1:]:
            d = _diff_sales_service(base, other)
            diffs.append(d)

    return {
        "fund_id": fund_id,
        "shares": rows,
        "share_count": len(rows),
        "cost_differences": diffs,
        "comparison_rules": [
            "只比较**费用**，表现比较必须先按 fund_id 归并",
            "年化费率已在净值中扣除，不得重复计入交易成本",
            "有生效日的费率只在该日之后适用",
            "无生效日的费率不可用于历史回填",
            "申购/赎回阶梯持有期口径（自然日/交易日）未确认",
            "支付宝实际费率 unknown，不得用天天基金费率冒充",
        ],
        "historical_cost_simulation": {
            "status": "not_available",
            "reason": ("79 条费率无 effective_from、申购赎回阶梯不完整、"
                       "持有期口径未确认、支付宝费率 unknown"),
        },
    }


def _fee_cell(node: dict | None) -> dict:
    if not node:
        return {"status": "not_available", "rate": None,
                "reason": "该份额无此费率记录"}
    rate = node.get("rate_original")
    if rate is None:
        return {"status": "not_available", "rate": None,
                "reason": "页面未提供该费率字段（如 ---），保持 unknown/None，不当 0"}
    return {
        "status": "ok",
        "rate": rate,
        "rate_pct": round(rate * 100, 6),
        "is_annual": True,
        "effective_from": node.get("effective_from"),
        "evidence_level": node.get("evidence_level"),
        "announcement_id": node.get("announcement_id"),
        "usable_for_current_scenario": True,
        "usable_for_historical": node.get("effective_from") is not None,
        "deducted_in_nav": True,
        "deducted_warning": "该费率已在净值中扣除，不得在成本模拟里重复计提",
    }


def _tier_cell(node: dict | None) -> dict:
    if not node or not node.get("available"):
        return {"status": "not_available",
                "reason": (node or {}).get("reason", "无阶梯数据")}
    return {
        "status": "partial",
        "tier_count": node.get("tier_count"),
        "tiers_with_rate": node.get("tiers_with_rate"),
        "tiers_with_effective_from": node.get("tiers_with_effective_from"),
        "usable_for_current_scenario": node.get("usable_for_current_scenario"),
        "usable_for_historical": node.get("usable_for_historical"),
        "holding_days_basis": "unknown",
        "platform_note": "平台优惠费率仅代表天天基金，不代表支付宝",
    }


def _diff_sales_service(a: dict, b: dict) -> dict:
    sa, sb = a["sales_service_fee"], b["sales_service_fee"]
    if sa["status"] != "ok" or sb["status"] != "ok":
        return {
            "compare": f"{a['share_code']} vs {b['share_code']}",
            "metric": "sales_service_fee",
            "status": "not_comparable",
            "reason": "至少一侧费率缺失（unknown），不下结论",
        }
    return {
        "compare": f"{a['share_code']} vs {b['share_code']}",
        "metric": "sales_service_fee",
        "status": "ok",
        "a_rate": sa["rate"],
        "b_rate": sb["rate"],
        "difference": round(sb["rate"] - sa["rate"], 8),
        "note": ("销售服务费通常只在 C 类计提，A 类为 0；"
                 "差异仅用于**费用**比较，不代表收益优劣"),
    }
