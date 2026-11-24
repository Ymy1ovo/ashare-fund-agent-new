"""阶段3B-6.0.2 复合基准结构与校验。

规则：
1. 缺成分 → 不可复现；
2. 缺权重 → 不可复现，**绝不补造历史权重**；
3. 只接一个成分就宣称整条基准可复现 = 禁止；
4. 现金/固定加项必须自身有序列，否则整条不可复现。
"""
from __future__ import annotations

import math
import sqlite3
from datetime import datetime

from app.fund.index_returns import (
    TOTAL_RETURN_BASES, assert_basis_usable_for_total_return,
)

COMPONENT_INDEX = "index"
COMPONENT_BOND = "bond_index"
COMPONENT_CASH = "cash"
COMPONENT_FIXED = "fixed_rate"
COMPONENT_TYPES = (COMPONENT_INDEX, COMPONENT_BOND,
                   COMPONENT_CASH, COMPONENT_FIXED)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# 计算收益序列所需的最小有效观测数：至少需要 2 个点才能算出一期收益
MIN_VALID_OBSERVATIONS = 2


def count_effective_observations(conn: sqlite3.Connection,
                                 index_code: str) -> int:
    """统计某指数的**有效**行情条数。

    只计 ``quality_status='valid'`` 且 ``close`` 非空且为有限正数的行。

    **不得用总行数判断数据可用性**——``suspect``（如基线占位行）
    与 ``rejected`` 行都不能参与收益计算。
    """
    rows = conn.execute(
        "SELECT close FROM index_daily "
        "WHERE index_code=? AND quality_status='valid'", (index_code,))
    n = 0
    for r in rows:
        if _is_usable_close(r[0]):
            n += 1
    return n


def _is_usable_close(value) -> bool:
    """收盘价能否用于收益计算。

    必须**严格有限且大于 0**：

    | 值 | 计入 | 说明 |
    | --- | --- | --- |
    | 有限正数 | ✅ | 正常行情 |
    | ``+inf`` / ``-inf`` | ❌ | 非有限，收益计算会得到 inf/nan |
    | ``NaN`` | ❌ | 非有限（SQLite 通常已转 NULL 被 NOT NULL 拒绝） |
    | ``0`` | ❌ | 收益分母为 0 |
    | 负数 | ❌ | 指数点位不可能为负 |
    | ``None`` | ❌ | 空值 |

    用 ``math.isfinite`` 而不是 ``v != v``——后者只能识别 NaN，
    **漏掉 ±inf**。
    """
    if value is None:
        return False
    try:
        c = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(c) and c > 0


def assess_index_component(conn: sqlite3.Connection,
                           index_code: str | None) -> dict:
    """判定指数成分能否用于严格总收益基准复现。

    必须**同时**满足：
    1. 指数代码存在；
    2. ``index_master`` 收益口径为 ``total_return`` / ``net_total_return``；
    3. ``index_daily`` 至少有 2 条 ``quality_status='valid'`` 且收盘价有效。

    返回 ``{available, reason, return_basis, valid_rows, total_rows}``。
    """
    out = {"available": 0, "reason": None, "return_basis": None,
           "valid_rows": 0, "total_rows": 0}
    if not index_code:
        out["reason"] = "该指数尚未映射到可接入的指数代码（本阶段未接入）"
        return out

    master = conn.execute(
        "SELECT return_basis FROM index_master WHERE index_code=?",
        (index_code,)).fetchone()
    out["return_basis"] = master["return_basis"] if master else None

    out["total_rows"] = conn.execute(
        "SELECT COUNT(*) FROM index_daily WHERE index_code=?",
        (index_code,)).fetchone()[0]
    out["valid_rows"] = count_effective_observations(conn, index_code)

    if out["total_rows"] == 0:
        out["reason"] = "该指数尚未接入历史数据"
        return out
    if out["valid_rows"] == 0:
        out["reason"] = (f"没有有效行情：{out['total_rows']} 条记录中"
                         "quality_status 均非 valid（suspect/rejected 不可用）")
        return out
    if out["valid_rows"] < MIN_VALID_OBSERVATIONS:
        out["reason"] = (f"有效行情不足：仅 {out['valid_rows']} 条有效观测，"
                         f"至少需要 {MIN_VALID_OBSERVATIONS} 条才能计算收益序列")
        return out

    basis = out["return_basis"]
    if basis is None:
        out["reason"] = "指数未登记收益口径，无法用于总收益比较"
        return out
    if basis == "unknown":
        out["reason"] = ("收益口径 unknown：只有历史行情点位，"
                         "没有证据证明是全收益序列，不能用于严格总收益基准")
        return out
    if basis == "price_return":
        out["reason"] = ("收益口径 price_return：价格指数不含分红再投资，"
                         "不能冒充全收益基准")
        return out
    if basis not in TOTAL_RETURN_BASES:
        out["reason"] = f"未识别的收益口径: {basis}"
        return out

    out["available"] = 1
    return out


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
        # 有效行情 + 收益口径双重判定，不能用总行数代替
        verdict = assess_index_component(conn, index_code)
        available = verdict["available"]
        reason = verdict["reason"]
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

    # ---- 指数成分：**重新**按当前库状态判定，不信任历史 data_available ----
    # 历史组件可能曾标记可用，但之后有效行情被移除或质量状态被改写，
    # 因此每次评估都必须重新统计有效观测与收益口径。
    basis_fail = []
    effective_fail = []
    for c in comps:
        if c["component_type"] != COMPONENT_INDEX:
            continue
        verdict = assess_index_component(conn, c["index_code"])
        # 把最新判定写回组件，保持组件状态与当前库一致
        conn.execute(
            "UPDATE benchmark_composite_component "
            "SET data_available=?, unavailable_reason=? WHERE component_id=?",
            (verdict["available"], verdict["reason"], c["component_id"]))
        c["data_available"] = verdict["available"]

        if not verdict["available"]:
            effective_fail.append(
                f"{c['component_label']}({c['index_code'] or '未映射'}): "
                f"{verdict['reason']}")

    if effective_fail:
        missing.append(
            f"{len(effective_fail)} 个指数成分无可用收益序列："
            + "；".join(effective_fail[:3]))

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
