"""阶段3B-6.0.4 超额收益验证的**证据边界**。

核心结论先行：**当前不具备计算超额收益的条件。**

原因链条（任何一环不满足即不可算）：

1. 指数收益口径 10/10 为 ``unknown`` → 无法确认基准是价格还是全收益；
2. ``price_return`` 不得冒充 ``total_return``（价格指数不含分红再投资）；
3. 15 条复合基准全部不可复现（缺债券/现金/恒生成分序列，或缺口径证据）；
4. 库内没有任何基准收益序列（``index_daily`` 存的是指数点位，
   且口径 unknown，不能直接当基准收益）。

因此 ``excess_return_status`` 恒为 ``not_available``。
**同类相对表现 ≠ 超额收益，同类排名 ≠ Alpha。**
"""
from __future__ import annotations

from app.fund.index_returns import (
    RETURN_BASIS_NET, RETURN_BASIS_PRICE, RETURN_BASIS_TOTAL,
    RETURN_BASIS_UNKNOWN, TOTAL_RETURN_BASES, ReturnBasisError,
    assert_basis_usable_for_total_return,
)

EXCESS_NOT_AVAILABLE = "not_available"

# 阻断原因枚举
BLOCK_BASIS_UNKNOWN = "index_return_basis_unknown"
BLOCK_BASIS_PRICE = "index_return_basis_price_only"
BLOCK_NO_BENCHMARK_SERIES = "no_benchmark_return_series"
BLOCK_COMPOSITE_INCOMPLETE = "composite_benchmark_incomplete"
BLOCK_COMPOSITE_MISSING_WEIGHT = "composite_benchmark_missing_weight"
BLOCK_COMPOSITE_MISSING_COMPONENT = "composite_benchmark_missing_component"


def check_benchmark_usable(index_code: str | None,
                           return_basis: str | None) -> dict:
    """单指数基准可用性判定。"""
    if not index_code:
        return {"usable": False, "block": BLOCK_NO_BENCHMARK_SERIES,
                "reason": "无对应指数代码"}
    if not return_basis:
        return {"usable": False, "block": BLOCK_BASIS_UNKNOWN,
                "reason": "指数未登记收益口径"}
    try:
        assert_basis_usable_for_total_return(return_basis)
    except ReturnBasisError as exc:
        block = (BLOCK_BASIS_UNKNOWN if return_basis == RETURN_BASIS_UNKNOWN
                 else BLOCK_BASIS_PRICE)
        return {"usable": False, "block": block, "reason": str(exc)}
    return {"usable": True, "block": None, "reason": None}


def assess_composite(composite: dict | None) -> dict:
    """复合基准可复现性判定。

    必须**全部成分**齐全（含权重）才算可复现，不得只用一个成分顶替。
    """
    if not composite:
        return {"reproducible": False, "block": BLOCK_COMPOSITE_INCOMPLETE,
                "reason": "无复合基准记录"}
    comps = composite.get("components") or []
    if not comps:
        return {"reproducible": False, "block": BLOCK_COMPOSITE_INCOMPLETE,
                "reason": "复合基准无成分"}
    if len(comps) < 2:
        return {"reproducible": False, "block": BLOCK_COMPOSITE_INCOMPLETE,
                "reason": "只有 1 个成分，不构成复合基准"}
    missing_weight = [c for c in comps if c.get("weight") is None]
    if missing_weight:
        return {"reproducible": False,
                "block": BLOCK_COMPOSITE_MISSING_WEIGHT,
                "reason": (f"{len(missing_weight)} 个成分缺权重证据，"
                           "不得补造历史权重")}
    unavailable = [c for c in comps if not c.get("data_available")]
    if unavailable:
        detail = ", ".join(
            f"{c.get('component_label')}({c.get('component_type')})"
            for c in unavailable[:3])
        return {"reproducible": False,
                "block": BLOCK_COMPOSITE_MISSING_COMPONENT,
                "reason": f"{len(unavailable)} 个成分无可用收益序列：{detail}"}
    return {"reproducible": True, "block": None, "reason": None}


def evaluate_excess_return(readiness: dict) -> dict:
    """汇总判定能否计算超额收益。

    ``readiness`` 需包含：
    - ``benchmark_index_codes``: 该基金基准涉及的指数代码列表
    - ``index_bases``: {code: return_basis}
    - ``composite``: 复合基准记录（没有则 None）
    """
    codes = readiness.get("benchmark_index_codes") or []
    bases = readiness.get("index_bases") or {}
    composite = readiness.get("composite")

    if not codes and not composite:
        return {
            "excess_return_status": EXCESS_NOT_AVAILABLE,
            "block": BLOCK_NO_BENCHMARK_SERIES,
            "reason": "该基金没有可用的基准指数或复合基准记录",
            "peer_relative_is_not_alpha": True,
        }

    checks = [check_benchmark_usable(c, bases.get(c)) for c in codes]
    unusable = [c for c in checks if not c["usable"]]

    comp_verdict = None
    if composite is not None:
        comp_verdict = assess_composite(composite)
        if not comp_verdict["reproducible"]:
            return {
                "excess_return_status": EXCESS_NOT_AVAILABLE,
                "block": comp_verdict["block"],
                "reason": comp_verdict["reason"],
                "component_checks": checks,
                "peer_relative_is_not_alpha": True,
            }

    if unusable:
        return {
            "excess_return_status": EXCESS_NOT_AVAILABLE,
            "block": unusable[0]["block"],
            "reason": unusable[0]["reason"],
            "component_checks": checks,
            "unusable_count": len(unusable),
            "peer_relative_is_not_alpha": True,
        }

    # 口径全部合格，但库内**没有基准收益序列**（index_daily 是点位）
    return {
        "excess_return_status": EXCESS_NOT_AVAILABLE,
        "block": BLOCK_NO_BENCHMARK_SERIES,
        "reason": ("基准口径已核实，但库内无基准收益序列表；"
                   "指数点位序列不能直接当作基准收益"),
        "component_checks": checks,
        "peer_relative_is_not_alpha": True,
    }


def peer_relative_note() -> dict:
    """同类相对表现的解释边界，供所有报告统一引用。"""
    return {
        "peer_relative_meaning": (
            "同类相对表现 = 该基金在其可验证同类组内的描述性位置，"
            "**不是**相对于投资基准的超额收益"),
        "ranking_is_not_alpha": True,
        "no_forward_guarantee": True,
        "why_not": [
            "同类组只保证产品类型/跟踪指数可比，不保证投资策略相同",
            "库内无基准收益序列，无法计算超额收益",
            "历史相对表现不构成未来收益保证",
        ],
    }
