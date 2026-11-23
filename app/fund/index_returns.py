"""阶段3B-6.0.2 指数收益口径与基础收益序列。

严格规则：
1. 价格指数只能产生价格收益；
2. 全收益只有证据充分才允许，且必须显式请求；
3. ``unknown`` 口径一律拒绝用于正式总收益比较；
4. 缺口不填充、不插值、不当 0 收益；
5. 不得把指数收益与基金累计净值收益混算后宣称严格总收益超额。
"""
from __future__ import annotations

import sqlite3

from app.fund.index_layer import (
    RETURN_BASIS_NET, RETURN_BASIS_PRICE, RETURN_BASIS_TOTAL,
    RETURN_BASIS_UNKNOWN, TOTAL_RETURN_BASES,
)


class ReturnBasisError(ValueError):
    """口径不满足要求时抛出，**绝不降级放行**。"""


def assert_basis_usable_for_total_return(return_basis: str) -> None:
    """校验某口径能否用于「严格总收益」比较。

    price_return 与 unknown 一律拒绝——价格指数缺分红，unknown 无证据。
    """
    if return_basis == RETURN_BASIS_UNKNOWN:
        raise ReturnBasisError(
            "口径 unknown：没有证据证明是全收益指数，禁止用于总收益比较")
    if return_basis == RETURN_BASIS_PRICE:
        raise ReturnBasisError(
            "口径 price_return：价格指数不含分红，禁止当作全收益基准")
    if return_basis not in TOTAL_RETURN_BASES:
        raise ReturnBasisError(f"未识别的收益口径: {return_basis}")


def basis_kind(return_basis: str) -> dict:
    """返回口径的可比性说明，供报告与 UI 使用。"""
    table = {
        RETURN_BASIS_PRICE: {
            "usable_for_price_return": True,
            "usable_for_total_return": False,
            "note": "价格指数只反映价格变动，不含分红再投资",
        },
        RETURN_BASIS_TOTAL: {
            "usable_for_price_return": True,
            "usable_for_total_return": True,
            "note": "全收益指数含分红再投资，口径最接近基金累计净值",
        },
        RETURN_BASIS_NET: {
            "usable_for_price_return": True,
            "usable_for_total_return": True,
            "note": "净收益指数已扣税，与全收益口径不同，必须保留独立标识",
        },
        RETURN_BASIS_UNKNOWN: {
            "usable_for_price_return": False,
            "usable_for_total_return": False,
            "note": "口径未知，禁止用于任何正式比较",
        },
    }
    return table.get(return_basis, table[RETURN_BASIS_UNKNOWN])
