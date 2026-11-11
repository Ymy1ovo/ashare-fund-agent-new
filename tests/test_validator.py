from __future__ import annotations

from app.data.validators.etf_validator import CATEGORIES, validate_pool


def _row(code: str, category: str = "宽基指数ETF") -> dict:
    return {
        "code": code,
        "name": f"基金{code}",
        "category": category,
        "tracking_index": "测试指数",
        "listing_date": "2020-01-02",
        "data_source": "test",
    }


def test_valid_pool_passes() -> None:
    rows = [_row(f"5100{index:02d}", CATEGORIES[index % len(CATEGORIES)]) for index in range(6)]
    result = validate_pool(rows, spot_codes={row["code"] for row in rows}, min_count=6, max_count=10)
    assert result["ok"], result["errors"]


def test_duplicate_code_fails() -> None:
    rows = [_row("510300")] * 6
    result = validate_pool(rows, min_count=1, max_count=10)
    assert not result["ok"]
    assert any("重复" in error for error in result["errors"])


def test_bad_category_fails() -> None:
    rows = [_row("510300", "不存在的分类")]
    result = validate_pool(rows, min_count=1, max_count=10)
    assert not result["ok"]
    assert any("分类" in error for error in result["errors"])


def test_spot_missing_fails() -> None:
    rows = [_row("510300")]
    result = validate_pool(rows, spot_codes=set(), min_count=1, max_count=10)
    assert not result["ok"]
    assert any("实时列表" in error for error in result["errors"])
