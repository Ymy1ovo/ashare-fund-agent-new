"""ETF 观察池校验规则。"""
from __future__ import annotations

import re
from collections import Counter
from datetime import date
from typing import Any, Iterable

CATEGORIES = (
    "宽基指数ETF",
    "科技成长ETF",
    "消费与医药ETF",
    "债券ETF",
    "黄金ETF",
    "跨境ETF",
)

_CODE_RE = re.compile(r"^\d{6}$")


def validate_pool(
    records: Iterable[dict[str, Any]],
    *,
    spot_codes: set[str] | None = None,
    min_count: int = 30,
    max_count: int = 50,
) -> dict[str, Any]:
    """校验基金池：代码、必填字段、分类覆盖、数量与数据源交叉验证。"""
    rows = list(records)
    errors: list[str] = []
    warnings: list[str] = []
    codes = [str(row.get("code", "")) for row in rows]

    duplicates = [code for code, count in Counter(codes).items() if count > 1]
    if duplicates:
        errors.append(f"基金代码重复：{duplicates}")

    for row in rows:
        code = str(row.get("code", ""))
        if not _CODE_RE.match(code):
            errors.append(f"基金代码格式错误：{code!r}")
        if not row.get("name"):
            errors.append(f"{code} 缺少基金名称")
        if row.get("category") not in CATEGORIES:
            errors.append(f"{code} 分类非法：{row.get('category')!r}")
        if not row.get("data_source"):
            errors.append(f"{code} 缺少数据来源")
        listing_date = row.get("listing_date")
        if listing_date:
            try:
                if date.fromisoformat(str(listing_date)) > date.today():
                    errors.append(f"{code} 上市日期晚于今天：{listing_date}")
            except ValueError:
                errors.append(f"{code} 上市日期格式错误：{listing_date!r}")
        else:
            warnings.append(f"{code} 上市日期为空")
        if not row.get("tracking_index"):
            warnings.append(f"{code} 跟踪指数为空")

    if spot_codes is not None:
        missing = sorted(set(codes) - spot_codes)
        if missing:
            errors.append(f"以下代码未在 ETF 实时列表中验证到：{missing}")

    if len(rows) < min_count:
        errors.append(f"基金池数量不足：{len(rows)} < {min_count}")
    if len(rows) > max_count:
        errors.append(f"基金池数量超限：{len(rows)} > {max_count}")

    counts = Counter(str(row.get("category")) for row in rows)
    missing_categories = [category for category in CATEGORIES if counts.get(category, 0) == 0]
    if missing_categories:
        errors.append(f"分类覆盖不足：{missing_categories}")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "count": len(rows),
        "category_counts": dict(counts),
    }
