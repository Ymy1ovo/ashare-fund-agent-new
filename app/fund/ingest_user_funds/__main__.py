"""CLI：python -m app.fund.ingest_user_funds

显式受控接入，与只读查询命令完全分离。

用法：
    python -m app.fund.ingest_user_funds --code 012345
    python -m app.fund.ingest_user_funds --codes-file my_funds.txt
    python -m app.fund.ingest_user_funds --codes-file f.txt --json out.json
    python -m app.fund.ingest_user_funds --code 012345 --dry-run
    python -m app.fund.ingest_user_funds --code 012345 --no-backup
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.fund.ingest_user_funds._impl import (
    ST_INGESTED, UserFundIngestor, backup_database, db_fingerprint, gate,
)


def _json_default(o):
    if isinstance(o, (set, tuple)):
        return list(o)
    return str(o)


def _read_codes_file(path: str) -> tuple[list[str], list[str]]:
    p = Path(path)
    if not p.is_file():
        return [], [f"文件不存在：{path}"]
    codes, problems = [], []
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        c = line.strip()
        if not c or c.startswith("#"):
            continue
        if not c.isdigit() or len(c) != 6:
            problems.append(f"第 {i} 行非法代码已跳过：{c[:20]}")
            continue
        codes.append(c)
    return codes, problems


def _make_ingestor(dry_run: bool) -> UserFundIngestor:
    ing = UserFundIngestor()
    if dry_run:
        from app.fund.ingest_user_funds._impl import IngestResult, ST_INGESTED

        def preview(code, **kw):
            """dry-run：只做格式/范围/库内存在性预检，绝不写库。"""
            code_s = str(code or "").strip()
            st, why = ing.precheck(code_s)
            if st != ST_INGESTED:
                return IngestResult(code=code_s, status=st, reason=why)
            existing = ing._existing_fund(code_s)
            if existing is not None:
                r = IngestResult(code=code_s, status="already_present",
                                 reason="库内已存在；dry-run 未写入")
                r.fund_id = existing["fund_id"]
                r.share_codes = existing["share_codes"]
                r.product_class = existing["product_class"]
                if existing["share_ids"]:
                    from app.fund.ingest_user_funds._impl import audit_new_nav
                    q = audit_new_nav(None, existing["share_ids"][0])
                    r.quality = q
                    r.nav_rows_total = q.get("rows", 0)
                    r.nav_kind = q.get("nav_kind")
                    r.date_min = q.get("date_min")
                    r.date_max = q.get("date_max")
                return r
            r = IngestResult(code=code_s, status="dry_run_preview",
                             reason=("预检通过，库内尚不存在；"
                                     "dry-run 未调用外部接口、未写入任何数据"))
            return r
        ing.ingest_one = preview
    return ing


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m app.fund.ingest_user_funds",
        description="用户自选场外基金受控数据接入（唯一写入入口）")
    ap.add_argument("--code", help="单只 6 位基金代码")
    ap.add_argument("--codes-file", help="批量代码文件（一行一个）")
    ap.add_argument("--json", help="结果写入 JSON 文件")
    ap.add_argument("--dry-run", action="store_true",
                    help="只做预检，不写库")
    ap.add_argument("--no-backup", action="store_true",
                    help="跳过接入前备份（不推荐）")
    args = ap.parse_args(argv)

    if not args.code and not args.codes_file:
        ap.print_help()
        return 1

    before = db_fingerprint()
    backup_path = None
    if not args.dry_run and not args.no_backup:
        backup_path = backup_database(tag="3b5_3_user_ingest")
        print(f"备份 -> {backup_path}")

    ing = _make_ingestor(args.dry_run)

    if args.code:
        results = [ing.ingest_one(args.code).as_dict()]
        problems = []
    else:
        codes, problems = _read_codes_file(args.codes_file)
        results = []
        seen = set()
        for c in codes:
            if c in seen:
                results.append({"code": c, "status": "duplicate_skipped",
                                "reason": "同批次重复代码"})
                continue
            seen.add(c)
            try:
                results.append(ing.ingest_one(c).as_dict())
            except Exception as exc:
                results.append({"code": c, "status": "failed",
                                "reason": f"{type(exc).__name__}: {exc}"})

    after = db_fingerprint()
    summary = {}
    for r in results:
        summary[r["status"]] = summary.get(r["status"], 0) + 1

    doc = {
        "phase": "3B-5.3",
        "dry_run": args.dry_run,
        "backup_path": str(backup_path) if backup_path else None,
        "file_problems": problems,
        "result_count": len(results),
        "status_summary": summary,
        "fingerprint_before": before,
        "fingerprint_after": after,
        "database_changed": before["sha256"] != after["sha256"],
        "results": results,
        "gate": gate(),
    }
    text = json.dumps(doc, ensure_ascii=False, indent=1, default=_json_default)
    if args.json:
        Path(args.json).write_text(text, encoding="utf-8")
        print(f"JSON -> {args.json}")
    else:
        print(text)

    print(f"\n接入结果：{len(results)} 只")
    for r in results:
        print(f"  {r['code']:8} {r['status']:18} "
              f"{str(r.get('product_class')):16} "
              f"净值 {r.get('nav_rows_total', 0):5} 行")
    if problems:
        for x in problems:
            print(x, file=sys.stderr)
    print(f"数据库指纹变化：{doc['database_changed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
