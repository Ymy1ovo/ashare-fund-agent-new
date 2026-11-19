"""场外基金仓储公共部分：连接、时间戳、幂等冲突规则。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.database.db import get_connection


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def get_conn(db_path: Path | None = None):
    """复用项目连接上下文（自动 commit/rollback）。"""
    return get_connection(db_path)


def _row_to_dict(row) -> dict:
    return dict(row) if row is not None else None


# 来源置信度：数字越大越可信。批量写入时，
# 已存在记录的 source_confidence 高于新记录则不覆盖。
SOURCE_CONFIDENCE = {
    "official_contract": 100,
    "official_announcement": 90,
    "akshare.fund_open_fund_info_em": 70,
    "akshare.fund_individual_basic_info_xq": 60,
    "akshare.fund_name_em": 50,
    "akshare.fund_purchase_em": 50,
    "manual": 40,
    "unknown": 0,
}


def source_confidence(source: str) -> int:
    return SOURCE_CONFIDENCE.get(source, 10)


def should_overwrite(existing_source: str, incoming_source: str) -> bool:
    """新来源是否允许覆盖已有记录。

    规则：置信度更高才覆盖；相同来源允许更新（同一源的新鲜抓取）。
    """
    if existing_source == incoming_source:
        return True
    return source_confidence(incoming_source) >= source_confidence(existing_source)
