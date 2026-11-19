"""场外基金原始数据归一化。

只做纯函数转换，不碰数据库、不联网，便于单元测试。
"""
from __future__ import annotations

import re

# 份额类别识别：名称末尾或括号内的 A/C/E/I/R/D 等
_SHARE_SUFFIX = re.compile(r"[（(]?([A-Z])[）)]?$")

# 接口返回的「每10份派现金0.2100元」；必须精确锚定「派现金」后的数字，
# 否则会把「每10份」的 10 当成金额（差 10 倍）。
_PER_10 = re.compile(r"派现金\s*([0-9]+(?:\.[0-9]+)?)")


def parse_cash_per_share(text) -> float | None:
    """每 10 份分红金额 → 每份现金分红。"""
    if text is None:
        return None
    m = _PER_10.search(str(text))
    if not m:
        return None
    try:
        return round(float(m.group(1)) / 10.0, 8)
    except ValueError:
        return None


def detect_share_class_type(name: str) -> str:
    """从份额名称推断类别：A / C / E / I / R / D / plain / unknown。

    只认名称末尾的单个大写字母；认不出就返回 unknown，不猜。
    """
    if not name:
        return "unknown"
    stripped = str(name).strip()
    m = _SHARE_SUFFIX.search(stripped)
    if m:
        letter = m.group(1)
        if letter in ("A", "C", "E", "I", "R", "D", "H", "O"):
            return letter
    # 没有字母后缀但有明确中文标记
    if "后端" in stripped:
        return "backend"
    return "plain"


def base_fund_name(name: str) -> str:
    """去掉份额后缀，得到基金本体名（仅用于辅助归属，不作为唯一依据）。"""
    if not name:
        return ""
    s = str(name).strip()
    s = re.sub(r"[（(]?(?:LOF|后端)[）)]?$", "", s)
    s = re.sub(r"[（(]?[A-Z][）)]?$", "", s)
    return s.strip()


def is_money_fund(fund_type: str | None) -> bool:
    """货币基金判定。"""
    return bool(fund_type and "货币" in str(fund_type))


def to_float(value) -> float | None:
    """安全转 float；空值/非数字返回 None，绝不返回 0 冒充真实值。"""
    if value is None:
        return None
    try:
        import math
        f = float(value)
        if math.isnan(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def to_iso_date(value) -> str | None:
    """统一成 YYYY-MM-DD；无法解析返回 None。

    pandas 的 NaT 也是 datetime 子类，但它的 strftime 会直接抛错，
    所以必须先判 pd.isna，再走 strftime。
    """
    if value is None:
        return None
    try:
        import pandas as pd
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "strftime"):
        try:
            return value.strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            return None
    s = str(value).strip()
    if not s or s.lower() in ("nat", "none", "nan", "--"):
        return None
    return s[:10]
