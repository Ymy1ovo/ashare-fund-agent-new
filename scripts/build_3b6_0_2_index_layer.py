"""阶段3B-6.0.2 指数数据层建设（迁移 + 第一批 10 个指数接入）。

用法：
    python scripts/build_3b6_0_2_index_layer.py --init-only
    python scripts/build_3b6_0_2_index_layer.py --ingest
    python scripts/build_3b6_0_2_index_layer.py --json out.json

安全措施：
1. 建表前自动备份数据库（--backup 默认开启）；
2. 记录迁移前后基金表行数与内容指纹；
3. 只写 index_* / benchmark_* 表，**不触碰任何 fund_* 表**。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings                       # noqa: E402
from app.fund.ingest_user_funds import db_fingerprint  # noqa: E402
from app.fund.index_ingest import (                   # noqa: E402
    FIRST_BATCH, SOURCE_CSINDEX, collect_first_batch,
)
from app.fund.index_layer import (                    # noqa: E402
    get_index_connection, init_index_layer, table_row_counts,
)

INDEX_TABLES = ("index_master", "index_daily", "index_ingest_runs",
                "index_quality_checks", "benchmark_composite",
                "benchmark_composite_component")
FUND_TABLES = ("fund_master", "fund_share_classes", "fund_nav_daily",
               "fund_dividends", "fund_lifecycle_events")


def backup_db(tag: str = "3b6_0_2") -> Path | None:
    src = Path(settings.database_path)
    if not src.exists():
        return None
    dst = src.with_name(
        f"{src.stem}.backup_{tag}_{datetime.now():%Y%m%d_%H%M%S}{src.suffix}")
    shutil.copy2(src, dst)
    return dst


def snapshot(db_path=None) -> dict:
    """迁移/接入前后快照：基金表行数 + 内容指纹 + 指数表行数。"""
    snap = {"captured_at": datetime.now().isoformat(timespec="seconds")}
    with get_index_connection(db_path) as conn:
        snap["fund_row_counts"] = table_row_counts(conn)
        idx = {}
        for t in INDEX_TABLES:
            try:
                idx[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except Exception:
                idx[t] = None
        snap["index_row_counts"] = idx
        snap["integrity_check"] = conn.execute(
            "PRAGMA integrity_check").fetchone()[0]
        snap["foreign_key_violations"] = len(
            conn.execute("PRAGMA foreign_key_check").fetchall())
    snap["content_fingerprint"] = db_fingerprint()["sha256"]
    return snap


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="3B-6.0.2 指数数据层建设")
    ap.add_argument("--init-only", action="store_true", help="只建表不采集")
    ap.add_argument("--ingest", action="store_true", help="建表并采集第一批指数")
    ap.add_argument("--no-backup", action="store_true")
    ap.add_argument("--json", help="输出 JSON 路径")
    args = ap.parse_args(argv)

    doc = {"phase": "3B-6.0.2",
           "generated_at": datetime.now().isoformat(timespec="seconds"),
           "source": SOURCE_CSINDEX}
    if not args.no_backup:
        b = backup_db()
        doc["backup_path"] = str(b) if b else None
        print(f"备份: {b}")

    doc["before"] = snapshot()
    print("迁移前:", json.dumps(doc["before"]["fund_row_counts"],
                             ensure_ascii=False))

    with get_index_connection() as conn:
        init_index_layer(conn)
    print("建表完成")

    doc["after_migration"] = snapshot()
    doc["tables_created"] = list(INDEX_TABLES)

    if args.ingest:
        with get_index_connection() as conn:
            results = collect_first_batch(conn)
        doc["ingest_results"] = results
        for r in results:
            flag = "OK  " if r.get("ok") else "FAIL"
            print(f'  {flag} {r["index_code"]:8} rows={r.get("rows_returned", 0):5} '
                  f'{r.get("date_min")} ~ {r.get("date_max")} '
                  f'q={r.get("quality_level")}'
                  + (f'  {str(r.get("error"))[:50]}' if r.get("error") else ""))

    doc["after"] = snapshot()
    doc["fund_tables_unchanged"] = (
        doc["before"]["fund_row_counts"] == doc["after"]["fund_row_counts"])
    doc["content_fingerprint_unchanged"] = (
        doc["before"]["content_fingerprint"] == doc["after"]["content_fingerprint"])

    print("基金表未变:", doc["fund_tables_unchanged"])
    print("内容指纹未变:", doc["content_fingerprint_unchanged"])
    print("完整性:", doc["after"]["integrity_check"],
          "外键违规:", doc["after"]["foreign_key_violations"])

    if args.json:
        Path(args.json).write_text(
            json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
