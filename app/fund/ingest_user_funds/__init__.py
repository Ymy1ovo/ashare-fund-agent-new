"""阶段3B-5.3 用户自选场外基金受控数据接入。

与查询分离：`python -m app.fund.research --code` 永远只读；
本包是唯一写入入口：`python -m app.fund.ingest_user_funds ...`。
"""
from __future__ import annotations

from app.fund.ingest_user_funds._impl import (
    ST_ALREADY_PRESENT, ST_EXCLUDED, ST_FAILED, ST_INGESTED, ST_INVALID_CODE,
    ST_NOT_FOUND, ST_TIMEOUT, IngestResult, UserFundIngestor, audit_new_nav,
    backup_database, db_fingerprint, gate, ingest_many,
)

__all__ = [
    "UserFundIngestor", "IngestResult", "ingest_many",
    "audit_new_nav", "db_fingerprint", "backup_database", "gate",
    "ST_INGESTED", "ST_ALREADY_PRESENT", "ST_NOT_FOUND", "ST_INVALID_CODE",
    "ST_EXCLUDED", "ST_FAILED", "ST_TIMEOUT",
]
