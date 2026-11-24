"""阶段3B-6.0.3 第三 / 四步：先在临时库验证，再写正式库。

流程：
1. 读候选清单；
2. 复制正式库到临时库（或从空库建 schema）；
3. 在临时库逐只接入，记录结果与质量；
4. 通过的才写正式库；
5. 全程记录指纹前后变化。

用法：
    python scripts/ingest_3b6_0_3_batch.py --stage temp    # 只跑临时库
    python scripts/ingest_3b6_0_3_batch.py --stage formal  # 写正式库
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings                        # noqa: E402
from app.database.db import init_db                    # noqa: E402
from app.fund.ingest_user_funds import (               # noqa: E402
    UserFundIngestor, backup_database, db_fingerprint, ingest_many,
)


def load_plan(path: Path) -> list[dict]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for bucket, items in doc["candidates"].items():
        for it in items:
            out.append({**it, "bucket": bucket})
    return out


def make_temp_db(tmp_path: Path) -> Path:
    """从正式库完整复制一份，保证 schema 与数据一致。"""
    src = Path(settings.database_path)
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    if tmp_path.exists():
        tmp_path.unlink()
    shutil.copy2(src, tmp_path)
    return tmp_path


def run_batch(db_path: Path, candidates: list[dict], *,
              tag: str) -> dict:
    before = db_fingerprint(db_path)
    codes = [c["code"] for c in candidates]
    result = ingest_many(codes, db_path)
    after = db_fingerprint(db_path)

    # 逐只补充类别信息
    by_code = {c["code"]: c for c in candidates}
    enriched = []
    for r in result["results"]:
        meta = by_code.get(r["code"], {})
        enriched.append({**r,
                         "bucket": meta.get("bucket"),
                         "name_planned": meta.get("name"),
                         "product_class_planned": meta.get("product_class"),
                         "index_family": meta.get("index_family")})

    return {
        "tag": tag,
        "db_path": str(db_path),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "requested": len(codes),
        "status_summary": result["status_summary"],
        "fingerprint_before": before,
        "fingerprint_after": after,
        "fingerprint_changed": before["sha256"] != after["sha256"],
        "results": enriched,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="3B-6.0.3 分批接入")
    ap.add_argument("--plan", default=".tmp603/plan.json")
    ap.add_argument("--stage", choices=("temp", "formal"), default="temp")
    ap.add_argument("--json", help="输出 JSON 路径")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 只（调试）")
    args = ap.parse_args(argv)

    candidates = load_plan(Path(args.plan))
    if args.limit:
        candidates = candidates[:args.limit]

    if args.stage == "temp":
        tmp_db = Path(".tmp603/temp_stage.db")
        make_temp_db(tmp_db)
        doc = run_batch(tmp_db, candidates, tag="temp")
    else:
        backup = backup_database()
        doc = run_batch(Path(settings.database_path), candidates, tag="formal")
        doc["backup_path"] = str(backup) if backup else None

    doc["phase"] = "3B-6.0.3"
    doc["stage"] = args.stage

    print(f"== {args.stage} ==")
    print(f'  请求 {doc["requested"]}  状态汇总 {doc["status_summary"]}')
    print(f'  指纹变化: {doc["fingerprint_changed"]}')
    for r in doc["results"]:
        st = r["status"]
        flag = "OK  " if st in ("ingested", "already_present") else "FAIL"
        print(f'  {flag} {r["code"]} {str(r.get("name_planned"))[:22]:24} '
              f'{st:16} {str(r.get("reason") or "")[:50]}')

    if args.json:
        Path(args.json).write_text(
            json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
