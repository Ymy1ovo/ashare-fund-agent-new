"""阶段3B-6.0.4 A/C 份额成本分析框架。

**只输出框架与不可计算原因，不给购买建议。**

铁律：

1. 未知费率**不得当作 0**；
2. 不得用当前费率**倒推**历史费率；
3. 不得仅凭 A/C 名称判断哪种更便宜；
4. 第三方费率**不等于**支付宝实际费率；
5. 赎回费阶梯与有效期不完整时，持有期成本只能给区间或 not_available。
"""
from __future__ import annotations

from app.database.db import get_connection

COST_NOT_AVAILABLE = "not_available"
COST_PARTIAL = "partial"
COST_COMPUTABLE = "computed"

# 常见持有期档位（天）
HOLDING_HORIZONS = (7, 30, 90, 180, 365, 730, 1095)

ALIPAY_FEE_UNKNOWN = {
    "status": "unknown",
    "note": ("支付宝实际费率无公开合法数据源；"
             "本框架只使用库内第三方费率，不代表支付宝实际费率"),
}


def _cell(node) -> dict:
    """把费率节点标准化。缺失 → unknown，**不填 0**。"""
    if not node:
        return {"status": "unknown", "value": None,
                "reason": "库内无该费率记录"}
    if isinstance(node, dict):
        v = node.get("value")
        st = node.get("status") or ("ok" if v is not None else "unknown")
        return {"status": st, "value": v, "reason": node.get("reason")}
    return {"status": "ok", "value": node, "reason": None}


def load_fee_tiers(db_path, *, share_code: str, fee_type: str) -> list[dict]:
    """直接读库取费率阶梯（load_fee_info 只返回摘要，不含明细）。"""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """SELECT f.tier_order, f.lower_bound, f.upper_bound, f.rate,
                      f.rate_platform, f.holding_days_min, f.holding_days_max,
                      f.lower_inclusive, f.upper_inclusive,
                      f.holding_days_min_inclusive, f.holding_days_max_inclusive,
                      f.evidence_level, f.effective_from
               FROM fund_fee_rules f
               JOIN fund_share_classes sc ON sc.share_class_id=f.share_class_id
               WHERE sc.share_class_code=? AND f.fee_type=?
               ORDER BY f.tier_order""", (share_code, fee_type)).fetchall()
    return [dict(r) for r in rows]


def redemption_fee_at(tiers: list[dict] | None, holding_days: int) -> dict:
    """按持有天数落在哪一档赎回费。

    阶梯不连续 / 区间不可判定 → unknown，**不插值**。
    """
    if not tiers:
        return {"status": "unknown", "value": None,
                "reason": "无赎回费阶梯数据"}
    matched = []
    for t in tiers:
        lo = t.get("holding_days_min")
        hi = t.get("holding_days_max")
        lo = -1 if lo is None else lo
        hi = 10**9 if hi is None else hi
        lo_incl = t.get("holding_days_min_inclusive", 1)
        hi_incl = t.get("holding_days_max_inclusive", 1)
        ok_lo = (holding_days >= lo) if lo_incl else (holding_days > lo)
        ok_hi = (holding_days <= hi) if hi_incl else (holding_days < hi)
        if ok_lo and ok_hi:
            matched.append(t)
    if not matched:
        return {"status": "unknown", "value": None,
                "reason": f"持有 {holding_days} 天未落在任何已知阶梯，不插值"}
    if len(matched) > 1:
        values = {t.get("rate") for t in matched}
        if len(values) > 1:
            return {"status": "unknown", "value": None,
                    "reason": f"持有 {holding_days} 天命中 {len(matched)} 个"
                              "费率不同的阶梯，数据存在重叠，拒绝判定"}
    return {"status": "ok", "value": matched[0].get("rate"),
            "reason": None, "tier": matched[0]}


def analyze_share_cost(db_path, *, fund_id: int,
                       shares: list[dict]) -> dict:
    """同一基金本体下各份额的成本框架。

    只做**结构呈现 + 可算性判定**，不给出「该买 A 还是 C」的结论。
    费率直接读 ``fund_fee_rules``（不依赖 load_fee_info 的完整 schema）。
    """
    if not shares:
        return {"fund_id": fund_id, "status": "no_shares", "shares": []}

    rows = []
    for s in shares:
        code = s["share_code"]
        redemption = load_fee_tiers(db_path, share_code=code,
                                    fee_type="redemption")
        purchase = load_fee_tiers(db_path, share_code=code,
                                  fee_type="purchase")
        annual = {}
        for ft in ("sales_service", "management", "custody"):
            tiers = load_fee_tiers(db_path, share_code=code, fee_type=ft)
            if not tiers:
                annual[ft] = {"status": "unknown", "value": None,
                              "reason": "库内无该费率记录"}
            else:
                rates = [t["rate"] for t in tiers if t.get("rate") is not None]
                annual[ft] = ({"status": "ok", "value": rates[0],
                               "evidence_level": tiers[0].get("evidence_level"),
                               "effective_from": tiers[0].get("effective_from")}
                              if rates else
                              {"status": "unknown", "value": None,
                               "reason": "记录存在但费率为空"})

        rows.append({
            "share_code": code,
            "share_name": s.get("share_name"),
            "share_class_type": s.get("share_class_type"),
            "is_primary": s.get("is_primary"),
            "sales_service_fee": annual["sales_service"],
            "management_fee": annual["management"],
            "custody_fee": annual["custody"],
            "purchase_fee_tiers": purchase,
            "redemption_fee_tiers": redemption,
            "alipay_fee": ALIPAY_FEE_UNKNOWN,
            "fee_evidence_level": (redemption[0].get("evidence_level")
                                   if redemption else None),
        })

    horizon_analysis = []
    for h in HOLDING_HORIZONS:
        per_share = []
        for r in rows:
            seg = redemption_fee_at(r["redemption_fee_tiers"], h)
            ss = r["sales_service_fee"]
            per_share.append({
                "share_code": r["share_code"],
                "redemption_fee": seg,
                "sales_service_fee": ss,
                "computable": (seg["status"] == "ok"
                               and ss["status"] == "ok"),
            })
        all_ok = all(x["computable"] for x in per_share)
        horizon_analysis.append({
            "holding_days": h,
            "status": COST_COMPUTABLE if all_ok else COST_NOT_AVAILABLE,
            "reason": (None if all_ok else
                       "存在缺失/重叠费率，未知费率不当作 0，不给结论"),
            "per_share": per_share,
        })

    computable_horizons = [h["holding_days"] for h in horizon_analysis
                           if h["status"] == COST_COMPUTABLE]
    return {
        "fund_id": fund_id,
        "share_count": len(rows),
        "shares": rows,
        "horizon_analysis": horizon_analysis,
        "computable_horizons": computable_horizons,
        "status": (COST_COMPUTABLE if computable_horizons
                   else COST_NOT_AVAILABLE),
        "conclusion": None,
        "conclusion_note": (
            "本模块**不输出**「该买 A 还是 C」的结论。原因："
            "① 费率来自第三方，不等于支付宝实际费率；"
            "② 赎回费阶梯与历史有效期不完整；"
            "③ 不得用当前费率倒推历史；"
            "④ 不得仅凭份额名称判断便宜。"),
        "cannot_conclude_reasons": [
            "第三方费率 ≠ 支付宝实际费率",
            "赎回费阶梯与有效期不完整",
            "禁止用当前费率倒推历史费率",
            "禁止仅凭 A/C 名称判断",
        ],
    }
