"""观察池 CSV 快照导出。

数据库是运行期事实源；建池、全量入库、增量同步后统一从此处导出 CSV，
避免 CSV 的 latest_price 落后于数据库。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from app.database.db import get_connection

POOL_COLUMNS = [
    "code",
    "name",
    "category",
    "fund_type",
    "tracking_index",
    "established_date",
    "listing_date",
    "listing_date_source",
    "last_trade_date",
    "history_rows",
    "latest_price",
    "data_source",
    "source_tested_at",
    "status",
]


def export_pool_csv(path: Path, db_path: Path | None = None) -> int:
    """把 SQLite 中的观察池导出为 UTF-8 BOM CSV，返回行数。"""
    with get_connection(db_path) as conn:
        rows: list[dict[str, Any]] = [
            dict(row)
            for row in conn.execute(
                f"SELECT {', '.join(POOL_COLUMNS)} FROM etf_pool ORDER BY category, code"
            )
        ]
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=POOL_COLUMNS).to_csv(path, index=False, encoding="utf-8-sig")
    return len(rows)
