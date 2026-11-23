"""按基金代码直接查询数据库（3B-5.2）。

只读：只访问 fund_master / fund_share_classes / fund_nav_daily /
fund_fee_rules / fund_subscription_status，不做任何写入。

不先调 load_universe() 再过滤——直接按代码索引查询，
因此可以查到默认研究池之外的、但已经入库的基金。
"""
from __future__ import annotations

import re
from pathlib import Path

from app.database.db import get_connection
from app.fund.research.classification import (
    ONSHORE_ETF_CODES, classify_fund, index_scope, is_offmarket_pool,
    peer_group_key,
)

# 查询状态
STATUS_FOUND = "found"
STATUS_NOT_FOUND = "not_found"
STATUS_EXCLUDED = "excluded_product"
STATUS_TERMINATED = "terminated"
STATUS_NO_NAV = "no_nav_data"
STATUS_INVALID_CODE = "invalid_code"

# 6 位数字
_CODE_RE = re.compile(r"^[0-9]{6}$")


def validate_code(code: str) -> tuple[bool, str]:
    """格式校验：必须是 6 位数字。避免任意字符串进入 SQL 参数。"""
    if code is None:
        return False, "代码为空"
    c = str(code).strip()
    if not c:
        return False, "代码为空"
    if not _CODE_RE.match(c):
        return False, f"代码格式非法（要求 6 位数字）：{c[:20]}"
    return True, c


def _row_to_entry(r: dict) -> dict:
    """库内行 → 与 load_universe() 同构的 entry。"""
    c = classify_fund(r)
    pg = peer_group_key(c, r["fund_name"], r["benchmark"],
                        tracking_index=r["tracking_index"])
    return {
        "fund_id": int(r["fund_id"]),
        "fund_code": r["fund_code_primary"],
        "fund_name": r["fund_name"],
        "fund_company": r["fund_company"],
        "fund_type_l1": r["fund_type_l1"],
        "fund_type_l2": r["fund_type_l2"],
        "benchmark": r["benchmark"],
        "tracking_index": r["tracking_index"],
        "established_date": r["established_date"],
        "lifecycle_status": r["lifecycle_status"],
        "share_class_id": int(r["share_class_id"]),
        "share_code": r["share_class_code"],
        "share_name": r["share_class_name"],
        "is_primary": r["is_primary"],
        **c,
        "index_scope": index_scope(r["fund_name"]),
        "peer_group": pg,
    }


_SELECT = """
    SELECT m.fund_id, m.fund_code_primary, m.fund_name, m.fund_company,
           m.fund_type_l1, m.fund_type_l2, m.is_index_fund,
           m.tracking_index, m.benchmark, m.established_date,
           m.lifecycle_status,
           s.share_class_id, s.share_class_code, s.share_class_name,
           s.is_primary
    FROM fund_master m
    JOIN fund_share_classes s ON s.fund_id = m.fund_id
"""


def _query(db_path: Path | None, where: str, param) -> list[dict]:
    sql = _SELECT + " WHERE " + where + " ORDER BY s.share_class_code"
    with get_connection(db_path) as conn:
        return [dict(r) for r in conn.execute(sql, (param,)).fetchall()]


def resolve_status(rows: list[dict], entry: dict | None) -> tuple[str, str]:
    """判定查询状态与原因。"""
    if not rows:
        return STATUS_NOT_FOUND, "数据库中不存在该基金代码"
    if entry is None:
        return STATUS_NOT_FOUND, "数据库中不存在该基金代码"

    if entry["lifecycle_status"] == "terminated":
        return STATUS_TERMINATED, (
            "该基金在库中标记为 terminated（已知清盘事件）；"
            "41 条清盘事件不是完整名录，不能据此判断全市场清盘情况")

    if entry["fund_code"] in ONSHORE_ETF_CODES:
        return STATUS_EXCLUDED, (
            "场内 ETF 不进入场外默认研究池，仅保留历史研究")

    if not is_offmarket_pool(entry, entry["share_code"]):
        return STATUS_EXCLUDED, (
            f"产品分类 {entry['product_class']} 不在场外默认研究池"
            f"（{'QDII 跨境口径特殊' if entry['product_class'] == 'qdii' else '见分类规则'}）")

    return STATUS_FOUND, "命中"


def lookup_by_share_code(code: str,
                          db_path: Path | None = None) -> dict:
    """按**份额代码**查询，返回该份额 + 所属基金本体的全部份额。"""
    ok, c = validate_code(code)
    if not ok:
        return {"status": STATUS_INVALID_CODE, "reason": c,
                "query": {"code": code, "by": "share_code"},
                "entries": [], "entry": None, "fund_entity": None}

    rows = _query(db_path, "s.share_class_code = ?", c)
    if not rows:
        return {"status": STATUS_NOT_FOUND,
                "reason": f"份额代码 {c} 在数据库中不存在",
                "query": {"code": c, "by": "share_code"},
                "entries": [], "entry": None, "fund_entity": None}

    target = next((r for r in rows if r["share_class_code"] == c), rows[0])
    entry = _row_to_entry(target)
    # 取**同一 fund_id 的全部份额**（A/C/E 一起返回）
    siblings = _query(db_path, "m.fund_id = ?", int(target["fund_id"]))
    entries = [_row_to_entry(r) for r in siblings]
    entries.sort(key=lambda e: e["share_code"])

    status, reason = resolve_status(rows, entry)
    return {
        "status": status,
        "reason": reason,
        "query": {"code": c, "by": "share_code"},
        "entry": entry,
        "entries": entries,
        "fund_entity": _entity(entries, entry),
    }


def lookup_by_fund_code(code: str, db_path: Path | None = None) -> dict:
    """按**基金本体代码**查询，返回该本体的全部份额。"""
    ok, c = validate_code(code)
    if not ok:
        return {"status": STATUS_INVALID_CODE, "reason": c,
                "query": {"code": code, "by": "fund_code"},
                "entries": [], "entry": None, "fund_entity": None}

    rows = _query(db_path, "m.fund_code_primary = ?", c)
    if not rows:
        # 本体代码找不到时，允许回落按份额代码查（份额代码常等于本体代码）
        alt = _query(db_path, "s.share_class_code = ?", c)
        if alt:
            return lookup_by_share_code(c, db_path)
        return {"status": STATUS_NOT_FOUND,
                "reason": f"基金本体代码 {c} 在数据库中不存在",
                "query": {"code": c, "by": "fund_code"},
                "entries": [], "entry": None, "fund_entity": None}

    entries = [_row_to_entry(r) for r in rows]
    entries.sort(key=lambda e: e["share_code"])
    # 代表 entry：优先份额代码 == 本体代码者
    entry = next((e for e in entries if e["share_code"] == c), entries[0])
    status, reason = resolve_status(rows, entry)
    return {
        "status": status,
        "reason": reason,
        "query": {"code": c, "by": "fund_code"},
        "entry": entry,
        "entries": entries,
        "fund_entity": _entity(entries, entry),
    }


def lookup_fund(code: str, db_path: Path | None = None) -> dict:
    """统一入口：按份额代码或本体代码查询。

    先按本体代码查（能一次拿到全部份额），查不到再按份额代码查。
    """
    ok, c = validate_code(code)
    if not ok:
        return {"status": STATUS_INVALID_CODE, "reason": c,
                "query": {"code": code, "by": "auto"},
                "entries": [], "entry": None, "fund_entity": None}

    by_fund = _query(db_path, "m.fund_code_primary = ?", c)
    if by_fund:
        return lookup_by_fund_code(c, db_path)
    by_share = _query(db_path, "s.share_class_code = ?", c)
    if by_share:
        return lookup_by_share_code(c, db_path)
    return {"status": STATUS_NOT_FOUND,
            "reason": f"代码 {c} 既不是库内基金本体代码，也不是份额代码",
            "query": {"code": c, "by": "auto"},
            "entries": [], "entry": None, "fund_entity": None}


def _entity(entries: list[dict], entry: dict) -> dict:
    """基金本体级摘要（份额不重复计数）。"""
    return {
        "fund_id": entry["fund_id"],
        "fund_code": entry["fund_code"],
        "fund_name": entry["fund_name"],
        "fund_company": entry["fund_company"],
        "product_class": entry["product_class"],
        "investment_subtype": entry["investment_subtype"],
        "lifecycle_status": entry["lifecycle_status"],
        "peer_group": entry["peer_group"],
        "share_count": len(entries),
        "share_codes": sorted(e["share_code"] for e in entries),
    }


def nav_coverage(share_class_id: int, db_path: Path | None = None) -> dict:
    """净值覆盖摘要（只读）。"""
    with get_connection(db_path) as conn:
        row = conn.execute(
            """SELECT COUNT(*) rows_, MIN(nav_date) dmin, MAX(nav_date) dmax,
                      SUM(CASE WHEN unit_nav IS NULL THEN 1 ELSE 0 END) null_unit,
                      SUM(CASE WHEN acc_nav IS NULL THEN 1 ELSE 0 END) null_acc,
                      SUM(CASE WHEN unit_nav IS NOT NULL AND unit_nav <= 0
                               THEN 1 ELSE 0 END) nonpositive
               FROM fund_nav_daily WHERE share_class_id=? AND nav_kind='net_value'""",
            (share_class_id,)).fetchone()
        money = conn.execute(
            """SELECT COUNT(*) FROM fund_nav_daily
               WHERE share_class_id=? AND nav_kind='money_yield'""",
            (share_class_id,)).fetchone()[0]
    d = dict(row)
    d["money_yield_rows"] = int(money or 0)
    d["rows_"] = int(d.get("rows_") or 0)
    return d


def fee_coverage(share_class_id: int, db_path: Path | None = None) -> dict:
    """费率覆盖摘要：区分有/无历史生效日。"""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """SELECT COUNT(*) total,
                      SUM(CASE WHEN effective_from IS NOT NULL THEN 1 ELSE 0 END) with_eff,
                      SUM(CASE WHEN is_annual=1 THEN 1 ELSE 0 END) annual
               FROM fund_fee_rules WHERE share_class_id=?""",
            (share_class_id,)).fetchone()
        alipay = conn.execute(
            """SELECT alipay_purchasable FROM fund_subscription_status
               WHERE share_class_id=? ORDER BY as_of_date DESC LIMIT 1""",
            (share_class_id,)).fetchone()
    d = dict(rows)
    d["total"] = int(d.get("total") or 0)
    d["with_effective_from"] = int(d.get("with_eff") or 0)
    d["annual"] = int(d.get("annual") or 0)
    d["has_historical_effective_date"] = d["with_effective_from"] > 0
    # 支付宝状态：没有可靠数据源 → 保持 unknown，不推断
    d["alipay_purchasable"] = (
        alipay["alipay_purchasable"] if alipay is not None else "unknown")
    if d["alipay_purchasable"] not in ("true", "false"):
        d["alipay_purchasable"] = "unknown"
    d["alipay_note"] = "支付宝可购买状态无可靠数据源，保持 unknown，不推断"
    return d
