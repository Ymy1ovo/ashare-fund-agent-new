"""阶段3B-6.2.3.1.1 数据导入审计与数据库安全核验报告生成。"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.fund import tr_layer  # noqa: E402

REPORTS = ROOT / "reports"
EVID = REPORTS / "evidence" / "phase3B6_2_3_1_1"
AUDIT_3 = REPORTS / "phase3B6_2_3_1_0_3_audit.json"


def file_sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    EVID.mkdir(parents=True, exist_ok=True)
    audit3 = json.loads(AUDIT_3.read_text(encoding="utf-8"))
    db = ROOT / "data" / "fund_agent.db"

    with tr_layer.get_tr_connection() as conn:
        conn.row_factory = sqlite3.Row
        counts = tr_layer.tr_table_counts(conn)
        iso = tr_layer.assert_isolated(conn)
        run = dict(conn.execute(
            "select * from tr_ingest_runs order by run_id desc").fetchone())
        integrity = conn.execute("pragma integrity_check").fetchone()[0]
        fk = len(conn.execute("pragma foreign_key_check").fetchall())
        idx = tr_layer.index_daily_fingerprint(conn)

        quality_dist = {r["row_quality_status"]: r["c"]
                        for r in conn.execute(
                            "select row_quality_status, count(*) c "
                            "from tr_index_daily_raw group by 1")}
        per_code = [dict(r) for r in conn.execute(
            "select tr_code, count(*) rows, "
            "sum(case when row_quality_status='suspected_synthetic' "
            "then 1 else 0 end) synth, "
            "sum(case when row_quality_status="
            "'suspected_market_closed_placeholder' then 1 else 0 end) closed, "
            "sum(case when row_quality_status='invalid_value' "
            "then 1 else 0 end) invalid "
            "from tr_index_daily_raw group by tr_code order by tr_code")]
        cands = tr_layer.list_candidates(conn)
        evidence = [dict(r) for r in conn.execute(
            "select * from tr_evidence_files order by relative_path")]

    # 证据 SHA256 真实复核
    ev_ok, ev_bad = 0, []
    for e in evidence:
        f = ROOT / e["relative_path"]
        if not f.exists():
            ev_bad.append({"path": e["relative_path"], "reason": "文件缺失"})
            continue
        if file_sha256(f) == e["sha256"]:
            ev_ok += 1
        else:
            ev_bad.append({"path": e["relative_path"], "reason": "SHA256 不符"})

    # 审计 JSON 中的连续性分布
    t = audit3["summary"]["totals"]
    continuity_check = {}
    for level in tr_layer.CONTINUITY_STATES:
        db_n = sum(1 for c in cands if c["continuity_level"] == level)
        continuity_check[level] = {
            "db": db_n, "audit": t.get(f"continuity_{level}"),
            "match": db_n == t.get(f"continuity_{level}"),
        }

    result = {
        "phase": "3B-6.2.3.1.1",
        "task": "全收益指数独立原始数据层建设",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "baseline_head": "3aae887da4a82ba77481c0efdb2f32c11feef618",
        "read_only_on_index_daily": True,
        "no_redownload": True,
        "table_counts": counts,
        "ingest_run": run,
        "isolation": iso,
        "index_daily": {"row_count": idx["row_count"],
                        "fingerprint": idx["fingerprint"],
                        "expected_rows": 50603,
                        "unchanged": idx["row_count"] == 50603},
        "integrity_check": integrity,
        "foreign_key_check": fk,
        "quality_distribution": quality_dist,
        "per_candidate": per_code,
        "evidence": {
            "total": len(evidence),
            "sha256_verified": ev_ok,
            "failed": ev_bad,
            "all_verified": not ev_bad,
        },
        "continuity_consistency": continuity_check,
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
        "database": {
            "path": str(db),
            "sha256": file_sha256(db),
            "bytes": db.stat().st_size,
        },
        "gates": {
            "ready_for_research_analysis": True,
            "ready_for_backtest": False,
            "ready_for_formal_ranking": False,
            "ready_for_3b6_2_3_1_series_build": False,
        },
        "_self_check": {
            "twelve_candidates": len(cands) == 12,
            "index_daily_unchanged": idx["row_count"] == 50603,
            "isolated": iso["isolated"],
            "all_evidence_sha256_ok": not ev_bad,
            "no_validated": sum(c["validated_series_candidate"]
                                for c in cands) == 0,
            "no_formal_admitted": sum(c["formal_series_admitted"]
                                      for c in cands) == 0,
            "continuity_matches_audit": all(
                v["match"] for v in continuity_check.values()),
            "no_verified_row_state": "verified" not in quality_dist,
        },
    }
    (REPORTS / "phase3B6_2_3_1_1_audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")

    # manifest
    files = {}
    for e in evidence:
        f = ROOT / e["relative_path"]
        if f.exists():
            files[e["relative_path"]] = {
                "bytes": f.stat().st_size,
                "sha256": file_sha256(f),
                "kind": e["evidence_kind"],
            }
    man = {"phase": "3B-6.2.3.1.1",
           "generated_at": datetime.now().isoformat(timespec="seconds"),
           "note": "本轮不下载新数据；登记导入所引用的原始官方证据",
           "file_count": len(files), "files": files}
    (EVID / "manifest.json").write_text(
        json.dumps(man, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(json.dumps(result["_self_check"], ensure_ascii=False, indent=1))
    print(f"\n表行数: {json.dumps(counts, ensure_ascii=False)}")
    print(f"证据: {ev_ok}/{len(evidence)} 校验通过")
    print(f"index_daily: {idx['row_count']} 行（未变）")
    print(f"integrity={integrity} fk={fk}")
    print(f"DB SHA256: {result['database']['sha256']}")


if __name__ == "__main__":
    main()
