"""阶段3B-6.0.2 复合基准结构与校验。

规则：
1. 缺成分 → 不可复现；
2. 缺权重 → 不可复现，**绝不补造历史权重**；
3. 只接一个成分就宣称整条基准可复现 = 禁止；
4. 现金/固定加项必须自身有序列，否则整条不可复现。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

COMPONENT_INDEX = "index"
COMPONENT_BOND = "bond_index"
COMPONENT_CASH = "cash"
COMPONENT_FIXED = "fixed_rate"
COMPONENT_TYPES = (COMPONENT_INDEX, COMPONENT_BOND,
                   COMPONENT_CASH, COMPONENT_FIXED)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def create_composite(conn: sqlite3.Connection, *, benchmark_name: str,
                     benchmark_raw_text: str | None,
                     evidence_source: str = "unknown") -> int:
    cur = conn.execute(
        """
        INSERT INTO benchmark_composite
            (benchmark_name, benchmark_raw_text, evidence_source,
             is_complete, is_reproducible, created_at, updated_at)
        VALUES (?, ?, ?, 0, 0, ?, ?)
        """,
        (benchmark_name, benchmark_raw_text, evidence_source, _now(), _now()))
    return int(cur.lastrowid)


def add_component(conn: sqlite3.Connection, composite_id: int, *,
                  component_type: str, component_label: str,
                  index_code: str | None = None, weight: float | None = None,
                  weight_evidence: str | None = None,
                  weight_effective_from: str | None = None,
                  weight_effective_to: str | None = None) -> int:
    """加成分。weight 为 None 表示**没有权重证据**，不补造。"""
    if component_type not in COMPONENT_TYPES:
        raise ValueError(f"非法 component_type: {component_type}")
    # 非指数成分不得挂代码；指数成分可以暂时没有代码（尚未接入），
    # 但必须如实记录为「不可用」，不得当成已具备序列。
    if component_type != COMPONENT_INDEX and index_code:
        raise ValueError(f"{component_type} 成分不能挂 index_code")

    available = 0
    reason = None
    if component_type == COMPONENT_INDEX:
        if not index_code:
            reason = "该指数尚未映射到可接入的指数代码（本阶段未接入）"
        else:
            has_data = conn.execute(
                "SELECT COUNT(*) FROM index_daily WHERE index_code=?",
                (index_code,)).fetchone()[0]
            if has_data:
                available = 1
            else:
                reason = "该指数尚未接入历史数据"
    else:
        reason = f"{component_type} 成分无可用收益序列（本阶段未接入）"

    cur = conn.execute(
        """
        INSERT INTO benchmark_composite_component
            (composite_id, component_type, index_code, component_label,
             weight, weight_evidence, weight_effective_from,
             weight_effective_to, data_available, unavailable_reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (composite_id, component_type, index_code, component_label, weight,
         weight_evidence, weight_effective_from, weight_effective_to,
         available, reason))
    return int(cur.lastrowid)


def evaluate_composite(conn: sqlite3.Connection, composite_id: int) -> dict:
    """重新评估复合基准完整性/可复现性，并写回。"""
    comps = conn.execute(
        "SELECT * FROM benchmark_composite_component WHERE composite_id=?",
        (composite_id,)).fetchall()
    comps = [dict(c) for c in comps]

    missing = []
    if not comps:
        missing.append("没有任何成分记录")
    elif len(comps) < 2:
        missing.append(
            f"只有 {len(comps)} 个成分，不构成复合基准；"
            "只接入单个成分不得宣称整条基准可复现")
    no_weight = [c for c in comps if c["weight"] is None]
    if no_weight:
        missing.append(
            f"{len(no_weight)} 个成分缺权重证据，不得补造："
            + ", ".join(str(c["component_label"]) for c in no_weight[:3]))
    no_code = [c for c in comps
               if c["component_type"] == COMPONENT_INDEX and not c["index_code"]]
    if no_code:
        missing.append(
            f"{len(no_code)} 个指数成分未映射到代码："
            + ", ".join(str(c["component_label"]) for c in no_code[:3]))
    no_data = [c for c in comps if not c["data_available"]]
    if no_data:
        missing.append(
            f"{len(no_data)} 个成分无可用收益序列："
            + ", ".join(f"{c['component_label']}({c['component_type']})"
                        for c in no_data[:3]))

    is_complete = 1 if (comps and not no_data) else 0
    is_reproducible = 1 if (comps and not missing) else 0
    reason = None if is_reproducible else "；".join(missing)

    conn.execute(
        "UPDATE benchmark_composite SET is_complete=?, is_reproducible=?, "
        "missing_reason=?, updated_at=? WHERE composite_id=?",
        (is_complete, is_reproducible, reason, _now(), composite_id))
    return {"composite_id": composite_id, "is_complete": bool(is_complete),
            "is_reproducible": bool(is_reproducible),
            "component_count": len(comps), "missing_reason": reason}


def get_composite(conn: sqlite3.Connection, composite_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM benchmark_composite WHERE composite_id=?",
        (composite_id,)).fetchone()
    if not row:
        return None
    out = dict(row)
    out["components"] = [dict(c) for c in conn.execute(
        "SELECT * FROM benchmark_composite_component WHERE composite_id=?",
        (composite_id,)).fetchall()]
    return out
