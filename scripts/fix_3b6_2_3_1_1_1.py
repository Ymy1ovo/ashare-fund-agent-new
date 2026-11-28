"""阶段3B-6.2.3.1.1.1 全收益原始归档完整性与审计计数修复。

**只读原始证据，只改 tr_* 表的指纹与完整性字段**，不动任何行情数值。

三项修复：
1. 证据计数按数据库唯一文件数统计（原为 upsert 调用次数）
2. row_fingerprint 覆盖全部原始行情字段（补 cons_number / peg）
3. 新增 raw_record_json / raw_record_sha256 并逐行回填 + 逐条核对
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.fund import tr_layer  # noqa: E402

REPORTS = ROOT / "reports"
EVID_TR = REPORTS / "evidence" / "phase3B6_2_3_1_0"
EVID = REPORTS / "evidence" / "phase3B6_2_3_1_1_1_1"


def file_sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    EVID.mkdir(parents=True, exist_ok=True)
    with tr_layer.get_tr_connection() as conn:
        conn.row_factory = __import__("sqlite3").Row
        tr_layer.enable_foreign_keys(conn)

        idx_before = tr_layer.index_daily_fingerprint(conn)
        rows_before = conn.execute(
            "select count(*) from tr_index_daily_raw").fetchone()[0]
        # 行情数值快照（用于证明未被修改）
        values_before = conn.execute(
            "select tr_code, trade_date, close, cons_number, peg "
            "from tr_index_daily_raw order by tr_code, trade_date"
        ).fetchall()
        values_before = [tuple(r) for r in values_before]

        # ---- 修复1：证据计数 ----
        ev_unique = conn.execute(
            "select count(*) from tr_evidence_files").fetchone()[0]

        # ---- 修复2：重算全部行指纹 ----
        fp_updated = 0
        rows = conn.execute(
            "select tr_code, trade_date, open, high, low, close, volume, "
            "amount, change, change_pct, cons_number, peg, "
            "returned_code, returned_name from tr_index_daily_raw").fetchall()
        for r in rows:
            rec = {
                "tr_code": r[0], "trade_date": r[1],
                "open": r[2], "high": r[3], "low": r[4], "close": r[5],
                "volume": r[6], "amount": r[7], "change": r[8],
                "change_pct": r[9], "cons_number": r[10], "peg": r[11],
                "returned_code": r[12], "returned_name": r[13],
            }
            conn.execute(
                "update tr_index_daily_raw set row_fingerprint=? "
                "where tr_code=? and trade_date=?",
                (tr_layer.row_fingerprint(rec), r[0], r[1]))
            fp_updated += 1

        # ---- 修复3：新增完整性字段并回填 ----
        mig = tr_layer.migrate_raw_record_columns(conn)
        backfill = tr_layer.backfill_raw_records(conn, EVID_TR)

        # ---- 逐行核对 ----
        verify = tr_layer.verify_raw_records(conn, EVID_TR)

        # ---- 更新批次证据计数 ----
        conn.execute(
            "update tr_ingest_runs set evidence_count=? "
            "where run_id=(select max(run_id) from tr_ingest_runs)",
            (ev_unique,))

        idx_after = tr_layer.index_daily_fingerprint(conn)
        rows_after = conn.execute(
            "select count(*) from tr_index_daily_raw").fetchone()[0]
        values_after = conn.execute(
            "select tr_code, trade_date, close, cons_number, peg "
            "from tr_index_daily_raw order by tr_code, trade_date"
        ).fetchall()
        values_after = [tuple(r) for r in values_after]

        # 质量分布与准入状态
        quality_dist = {r[0]: r[1] for r in conn.execute(
            "select row_quality_status, count(*) "
            "from tr_index_daily_raw group by 1")}
        cands = tr_layer.list_candidates(conn)
        continuity = {}
        for c in cands:
            continuity[c["continuity_level"]] = \
                continuity.get(c["continuity_level"], 0) + 1
        real_start = {c["real_history_start"] for c in cands}
        evidence_rows = [dict(r) for r in conn.execute(
            "select * from tr_evidence_files order by relative_path")]
        run = dict(conn.execute(
            "select * from tr_ingest_runs order by run_id desc").fetchone())
        integrity = conn.execute("pragma integrity_check").fetchone()[0]
        fk = len(conn.execute("pragma foreign_key_check").fetchall())
        iso = tr_layer.assert_isolated(conn)

    # 证据 SHA256 真实复核
    ev_ok, ev_bad = 0, []
    for e in evidence_rows:
        f = ROOT / e["relative_path"]
        if not f.exists():
            ev_bad.append({"path": e["relative_path"], "reason": "文件缺失"})
        elif file_sha256(f) == e["sha256"]:
            ev_ok += 1
        else:
            ev_bad.append({"path": e["relative_path"], "reason": "SHA256 不符"})

    db = ROOT / "data" / "fund_agent.db"
    all_complete = all(v.get("complete") for v in verify.values())
    total_matched = sum(v.get("matched", 0) for v in verify.values())
    # 八类异常分别汇总（**不得合并成一个笼统的「完整性」**）
    ANOMALY_KEYS = (
        "field_mismatch", "raw_record_json_missing",
        "raw_record_json_mismatch", "raw_record_sha256_missing",
        "raw_record_sha256_mismatch", "stored_json_sha_mismatch",
        "missing_in_db", "extra_in_db",
    )
    anomalies = {k: sum(v.get(k, 0) for v in verify.values())
                 for k in ANOMALY_KEYS}
    total_mismatched = anomalies["field_mismatch"]
    total_missing = anomalies["missing_in_db"]
    total_extra = anomalies["extra_in_db"]

    result = {
        "phase": "3B-6.2.3.1.1.1.1",
        "task": "原始JSON存储逐行核验闭环与迁移脚本规范化",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "baseline_head": "9cf46ab084e7ecc6e51e60572c770e698b83ad7c",
        "fixes": {
            "1_evidence_count": {
                "before": 36,
                "after": ev_unique,
                "cause": ("原逻辑累加 upsert 调用次数；"
                          "399997 有 2 个候选共用同一对照文件，"
                          "被重复计数 2 次"),
                "rule": "按 tr_evidence_files 唯一文件数统计",
            },
            "2_row_fingerprint": {
                "fields": list(tr_layer.FINGERPRINT_FIELDS),
                "updated_rows": fp_updated,
                "added_fields": ["cons_number", "peg"],
            },
            "3_raw_record_integrity": {
                "migration": mig,
                "backfill": backfill,
            },
        },
        "verification": verify,
        "verification_totals": {
            "raw_rows": sum(v.get("raw_rows", 0) for v in verify.values()),
            "db_rows": sum(v.get("db_rows", 0) for v in verify.values()),
            "matched": total_matched,
            "anomalies": anomalies,
            "field_mismatch": anomalies["field_mismatch"],
            "missing_in_db": anomalies["missing_in_db"],
            "extra_in_db": anomalies["extra_in_db"],
            "all_complete": all_complete,
        },
        "verification_layers": {
            "note": ("四层核验严格分开统计，"
                     "不得合并成一个笼统的「完整性通过」"),
            "1_field_values": "行情字段逐项比对（open/close/cons_number/peg/...）",
            "2_raw_json_content": ("实际读取数据库 raw_record_json，"
                                   "与原始 JSON 规范化结果逐字符比对"),
            "3_sha_vs_expected": "raw_record_sha256 列 vs 原始规范化 SHA",
            "4_sha_vs_stored_json": ("raw_record_sha256 列 vs "
                                     "数据库实际 JSON 自身的 SHA"),
        },
        "evidence": {
            "unique_files": ev_unique,
            "sha256_verified": ev_ok,
            "failed": ev_bad,
            "all_verified": not ev_bad,
            "batch_evidence_count": run["evidence_count"],
            "consistent": run["evidence_count"] == ev_unique,
        },
        "data_unchanged": {
            "rows_before": rows_before,
            "rows_after": rows_after,
            "rows_equal": rows_before == rows_after,
            "values_identical": values_before == values_after,
            "index_daily_rows": idx_after["row_count"],
            "index_daily_fingerprint": idx_after["fingerprint"],
            "index_daily_unchanged": (
                idx_before["fingerprint"] == idx_after["fingerprint"]),
        },
        "quality_distribution": quality_dist,
        "continuity_distribution": continuity,
        "real_history_start_values": sorted(real_start),
        "admission_totals": {
            "raw_data_layer_ingest_candidate": sum(
                c["raw_data_layer_ingest_candidate"] for c in cands),
            "validated_series_candidate": sum(
                c["validated_series_candidate"] for c in cands),
            "proxy_qualified_series_candidate": sum(
                c["proxy_qualified_series_candidate"] for c in cands),
            "formal_series_admitted": sum(
                c["formal_series_admitted"] for c in cands),
        },
        "integrity_check": integrity,
        "foreign_key_check": fk,
        "isolation": iso,
        "database": {"path": str(db), "sha256": file_sha256(db),
                     "bytes": db.stat().st_size},
        "gates": {
            "ready_for_research_analysis": True,
            "ready_for_backtest": False,
            "ready_for_formal_ranking": False,
            "ready_for_3b6_2_3_1_series_build": False,
        },
        "_self_check": {
            "evidence_count_consistent": run["evidence_count"] == ev_unique,
            "fingerprint_covers_all_fields": len(
                tr_layer.FINGERPRINT_FIELDS) == 14,
            "all_records_verified": all_complete,
            "all_anomalies_zero": all(v == 0 for v in anomalies.values()),
            "no_missing_no_extra": (total_missing == 0 and total_extra == 0),
            "values_untouched": values_before == values_after,
            "index_daily_unchanged": (
                idx_before["fingerprint"] == idx_after["fingerprint"]),
            "evidence_sha256_ok": not ev_bad,
            "no_validated": sum(c["validated_series_candidate"]
                                for c in cands) == 0,
            "no_formal_admitted": sum(c["formal_series_admitted"]
                                      for c in cands) == 0,
            "real_start_all_unknown": real_start == {"unknown"},
        },
    }
    (REPORTS / "phase3B6_2_3_1_1_1_1_audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")

    # manifest
    files = {}
    for e in evidence_rows:
        f = ROOT / e["relative_path"]
        if f.exists():
            files[e["relative_path"]] = {
                "bytes": f.stat().st_size,
                "sha256": file_sha256(f),
                "kind": e["evidence_kind"],
            }
    man = {"phase": "3B-6.2.3.1.1.1.1",
           "generated_at": datetime.now().isoformat(timespec="seconds"),
           "note": "本轮不下载新数据；登记导入所引用的原始官方证据",
           "file_count": len(files), "files": files}
    (EVID / "manifest.json").write_text(
        json.dumps(man, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(json.dumps(result["_self_check"], ensure_ascii=False, indent=1))
    print(f"\n证据唯一数: {ev_unique}（批次记录 {run['evidence_count']}）")
    print(f"指纹更新: {fp_updated} 行")
    print(f"逐行核对: 匹配 {total_matched} / 总数 "
          f"{sum(v.get('raw_rows', 0) for v in verify.values())}")
    print(f"八类异常: {json.dumps(anomalies, ensure_ascii=False)}")
    print(f"数值未变: {values_before == values_after}")
    print(f"index_daily: {idx_after['row_count']} 行 "
          f"指纹 {idx_after['fingerprint'][:16]}...")
    print(f"integrity={integrity} fk={fk}")
    print(f"DB SHA256: {result['database']['sha256']}")


if __name__ == "__main__":
    main()
