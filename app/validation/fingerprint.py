"""行情数据指纹。

算法版本 v2：对参与策略计算的全部关键字段做确定性序列化后 SHA256。
v1（阶段3A.2）只用行数/close 和/volume 和，无法发现单行字段变更，已废弃。

字段清单固定写入 FIELD_LIST，升级须同时升 FINGERPRINT_VERSION。
"""
from __future__ import annotations

import hashlib
import math
from decimal import Decimal
from typing import Any, Iterable

FINGERPRINT_VERSION = "market-fingerprint-v2"

# 参与指纹的列；顺序固定，变更必须升版本号
FIELD_LIST: tuple[str, ...] = (
    "code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "adjusted_close",
    "adjustment_snapshot_id",
)

# 价格类字段保留的小数位；不足补零，避免 1.1 与 1.10 产生不同结果
_PRICE_DECIMALS = 6
_VOLUME_DECIMALS = 3


class FingerprintError(RuntimeError):
    """指纹计算失败。"""


def _normalize(value: Any, field: str) -> str:
    """把单个字段规范成稳定字符串。

    - None / NaN / 空字符串 → 'null'（统一编码，避免 None 与 NaN 产生分歧）
    - 日期 → ISO 字符串
    - 浮点 → 定点小数，消除二进制浮点差异
    - 其他 → str()
    """
    if value is None:
        return "null"
    if isinstance(value, float) and math.isnan(value):
        return "null"
    if field == "trade_date":
        try:
            return str(value)[:10]
        except Exception:  # noqa: BLE001
            return "null"
    if field in ("code", "adjustment_snapshot_id"):
        text = str(value).strip()
        return text if text else "null"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float, Decimal)):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "null"
        if math.isnan(number):
            return "null"
        if math.isinf(number):
            return "inf" if number > 0 else "-inf"
        decimals = _VOLUME_DECIMALS if field == "volume" else _PRICE_DECIMALS
        return f"{number:.{decimals}f}"
    text = str(value).strip()
    return text if text else "null"


def serialize_row(row: Iterable[Any]) -> str:
    """把一行规范成 '字段1|字段2|...' 的稳定字符串。"""
    values = list(row)
    if len(values) != len(FIELD_LIST):
        raise FingerprintError(
            f"字段数不匹配：期望 {len(FIELD_LIST)}，实际 {len(values)}"
        )
    return "|".join(_normalize(value, field) for value, field in zip(values, FIELD_LIST))


def compute_fingerprint(rows: Iterable[Iterable[Any]]) -> tuple[str, int]:
    """计算指纹，返回 (sha256, 行数)。

    rows 必须已按 (code, trade_date) 排序；本函数不排序，以保证
    「调用方决定顺序」并且顺序变化时能被测试直接观察到。
    """
    digest = hashlib.sha256()
    digest.update(FINGERPRINT_VERSION.encode("utf-8"))
    count = 0
    for row in rows:
        digest.update(serialize_row(row).encode("utf-8"))
        digest.update(b"\n")
        count += 1
    return digest.hexdigest(), count


def normalize_rows(rows: list[tuple]) -> list[tuple]:
    """按 (code, trade_date) 稳定排序，消除行顺序差异。"""
    return sorted(rows, key=lambda row: (str(row[0]), str(row[1])))


def fingerprint_from_rows(rows: list[tuple]) -> dict:
    """从原始行计算指纹摘要。"""
    ordered = normalize_rows(rows)
    sha, count = compute_fingerprint(ordered)
    return {
        "algorithm": FINGERPRINT_VERSION,
        "fields": list(FIELD_LIST),
        "rows": count,
        "sha256": sha,
    }


def fingerprint_from_db(
    *, code_filter: list[str] | None = None, db_path=None
) -> dict:
    """从数据库读取行情并计算指纹。

    只读操作，不修改任何数据。code_filter 用于子集校验。
    """
    from app.database.db import get_connection

    columns = ", ".join(FIELD_LIST)
    with get_connection(db_path) as conn:
        if code_filter:
            placeholders = ",".join("?" for _ in code_filter)
            cursor = conn.execute(
                f"SELECT {columns} FROM etf_daily_prices "
                f"WHERE code IN ({placeholders}) ORDER BY code, trade_date",
                tuple(code_filter),
            )
        else:
            cursor = conn.execute(
                f"SELECT {columns} FROM etf_daily_prices ORDER BY code, trade_date"
            )
        rows = [tuple(row) for row in cursor.fetchall()]
    return fingerprint_from_rows(rows)


def compare_fingerprints(before: dict, after: dict) -> dict:
    """对比两个指纹，返回是否一致及差异说明。"""
    same = (
        before.get("sha256") == after.get("sha256")
        and before.get("rows") == after.get("rows")
    )
    payload = {
        "unchanged": same,
        "before": before,
        "after": after,
    }
    if not same:
        if before.get("rows") != after.get("rows"):
            payload["reason"] = (
                f"行数变化：{before.get('rows')} -> {after.get('rows')}"
            )
        else:
            payload["reason"] = "行数相同但内容哈希不同"
    return payload
