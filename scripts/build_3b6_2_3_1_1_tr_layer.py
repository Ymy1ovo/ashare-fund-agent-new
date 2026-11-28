"""阶段3B-6.2.3.1.1 全收益指数独立原始数据层建设与导入。

**只读原始证据，只写 tr_* 表**，不触碰 index_daily。

数据来源：
- reports/phase3B6_2_3_1_0_3_audit.json（候选状态与准入）
- reports/evidence/phase3B6_2_3_1_0/basic_*.json（官方基本信息）
- reports/evidence/phase3B6_2_3_1_0/hist_*.json（原始历史行情）
- reports/evidence/phase3B6_2_3_0_4/csindex_ctrl_*.json（对照证据）

**不重新下载任何数据。**
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
EVID_CTRL = REPORTS / "evidence" / "phase3B6_2_3_0_4"
AUDIT_3 = REPORTS / "phase3B6_2_3_1_0_3_audit.json"
AUDIT_1 = REPORTS / "phase3B6_2_3_1_0_1_audit.json"

BATCH_KEY = "3B-6.2.3.1.1-tr-raw-layer-v1"

# 市场分组 → 中文标签
MARKET_LABEL = {"stock": "沪深A股", "bond": "上交所债券市场",
                "hk": "香港市场（港股通）"}

# 债券/港股无适用日历
CALENDAR_NOTE = {
    "stock": "A股交易日历（项目代理），非官方发布日历",
    "bond": "**债券市场官方交易日历未取得**，不得用 A 股日历替代",
    "hk": "**港股官方交易日历未取得**，不得用 A 股日历替代",
}


def load_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def file_sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def official_name(code: str) -> tuple[str | None, str | None]:
    f = EVID_TR / f"basic_{code}.json"
    if not f.exists():
        return None, None
    try:
        data = json.loads(f.read_bytes().decode("utf-8")).get("data") or {}
    except Exception:
        return None, None
    return data.get("indexFullNameCn"), data.get("indexShortNameCn")


def classify_basis(code: str, group: str) -> str:
    """收益口径（严格区分，不得混用）。"""
    name, _ = official_name(code)
    if not name:
        return "unknown"
    if "净价" in name:
        return "bond_clean_price"
    if "利息及再投资" in name:
        return "bond_interest_reinvestment"
    if "全收益" in name:
        return "gross_total_return"
    if "净收益" in name:
        return "net_total_return"
    return "unknown"


def row_quality_for(tr_code: str, rec: dict, *, synth_row: str | None,
                    closed_dates: set[str]) -> tuple[str, str | None]:
    """逐行质量标记。

    **未验证行不默认有效**：
    - 请求起始日合成行 → suspected_synthetic
    - 休市占位日 → suspected_market_closed_placeholder
    - close <= 0 或非数值 → invalid_value
    - 其余 → normal_unverified（仍非 verified）
    """
    d = rec.get("tradeDate")
    close = rec.get("close")
    if d and synth_row and d == synth_row:
        return ("suspected_synthetic",
                "请求起始日疑似合成行（strong_inference，非官方确认）")
    if d and d in closed_dates:
        return ("suspected_market_closed_placeholder",
                "疑似休市占位行（无官方日历证据，仅疑似）")
    if close is None:
        return "invalid_value", "close 缺失"
    try:
        v = float(close)
    except (TypeError, ValueError):
        return "invalid_value", f"close 非数值：{close!r}"
    if v <= 0:
        return "invalid_value", f"close 非正值：{v}"
    return "normal_unverified", "原始值未经验证，不得视为有效行情"


def main() -> None:
    audit3 = load_json(AUDIT_3)
    audit1 = load_json(AUDIT_1)
    by1 = {r["tr_candidate"]: r for r in audit1["candidates"]}

    with tr_layer.get_tr_connection() as conn:
        tr_layer.enable_foreign_keys(conn)
        tr_layer.init_tr_layer(conn)

        idx_before = tr_layer.index_daily_fingerprint(conn)
        run_id = tr_layer.start_run(conn, BATCH_KEY)

        cand_count = 0
        rows_inserted = 0
        rows_skipped = 0
        evidence_count = 0
        quality_rows = []
        mapping_rows = []

        for c in audit3["candidates"]:
            code = c["tr_candidate"]
            group = c["group"]
            adm = c["admission"]
            snap = adm["evidence_snapshot"]
            full, short = official_name(code)
            r1 = by1.get(code, {})
            q = c["quality_020"]
            synth = c["synthetic_020"]

            basic_f = EVID_TR / f"basic_{code}.json"
            basic_data = {}
            if basic_f.exists():
                try:
                    basic_data = (json.loads(basic_f.read_bytes().decode(
                        "utf-8")).get("data") or {})
                except Exception:
                    basic_data = {}

            cand = {
                "tr_code": code,
                "price_index_code": c["price_index"],
                "official_full_name": full,
                "official_short_name": short,
                "publisher": "中证指数有限公司",
                "official_basic_date": basic_data.get("basicDate"),
                "official_publish_date": basic_data.get("publishDate"),
                "official_basic_index": basic_data.get("basicIndex"),
                "market_group": group,
                "market_label": MARKET_LABEL[group],
                "return_basis": classify_basis(code, group),
                "calendar_type": c["calendar_used"],
                "calendar_available": 1 if q.get("calendar_available") else 0,
                "calendar_is_official": 1 if c["calendar_is_official"] else 0,
                "calendar_note": CALENDAR_NOTE[group],
                "mapping_verified": 1 if snap[
                    "mapping_to_price_index_verified"] else 0,
                "mapping_evidence_level": "technical_inference",
                "base_date_match": (r1.get("mapping_evidence") or {}).get(
                    "base_date_match"),
                "continuity_level": c["continuity_level"],
                "real_history_start": snap["real_history_start"],
                "synthetic_start_status": snap["synthetic_status"],
                "data_quality_verified": 1 if snap[
                    "data_quality_verified"] else 0,
                "non_positive_close_count": (r1.get("quality") or {}).get(
                    "non_positive_close", 0),
                "raw_data_layer_ingest_candidate": 1 if adm[
                    "raw_data_layer_ingest_candidate"] else 0,
                "validated_series_candidate": 1 if adm[
                    "validated_series_candidate"] else 0,
                "proxy_qualified_series_candidate": 1 if adm[
                    "proxy_qualified_series_candidate"] else 0,
                "formal_series_admitted": 1 if adm[
                    "formal_series_admitted"] else 0,
                "source_audit_json": str(
                    AUDIT_3.relative_to(ROOT)).replace("\\", "/"),
                "source_evidence_manifest": "reports/evidence/"
                                            "phase3B6_2_3_1_0/manifest.json",
                "layer_version": "tr-v1",
            }
            tr_layer.upsert_candidate(conn, cand)
            cand_count += 1

            # ---- 历史行情 ----
            hist_f = EVID_TR / f"hist_{code}_20040101_20261127.json"
            if not hist_f.exists():
                print(f"  [WARN] {code} 缺历史文件")
                continue
            raw = hist_f.read_bytes()
            hist_sha = hashlib.sha256(raw).hexdigest()
            hist_rows = json.loads(raw.decode("utf-8")).get("data") or []

            synth_row = synth.get("synthetic_row")
            # 日历外日期：统一规范化为 YYYYMMDD（与接口 tradeDate 一致）
            raw_closed = {x["date"] for x in
                          (q.get("outside_calendar_detail") or [])}
            if not raw_closed:
                raw_closed = set(
                    q.get("dates_outside_calendar_sample") or [])
            closed_dates = {d.replace("-", "") for d in raw_closed if d}
            for rec in hist_rows:
                rq, note = row_quality_for(code, rec, synth_row=synth_row,
                                           closed_dates=closed_dates)
                rec["_row_quality"] = rq
                rec["_row_quality_note"] = note

            res = tr_layer.insert_raw_rows(
                conn, code, hist_rows, run_id=run_id,
                source_interface="csindex-home/perf/index-perf",
                request_url=(f"https://www.csindex.com.cn/csindex-home/perf/"
                             f"index-perf?indexCode={code}"
                             f"&startDate=20040101&endDate=20261127"),
                evidence_relative_path=str(
                    hist_f.relative_to(ROOT)).replace("\\", "/"),
                evidence_sha256=hist_sha)
            rows_inserted += res["inserted"]
            rows_skipped += res["skipped"]
            # 幂等重跑：修正已存在行的质量标记（不改原始数值）
            tr_layer.relabel_existing_rows(conn, code, synth_row,
                                           closed_dates)

            # ---- 证据登记 ----
            for f, kind, subj in (
                    (basic_f, "basic_info", code),
                    (hist_f, "history", code)):
                if f.exists():
                    tr_layer.upsert_evidence(conn, {
                        "relative_path": str(f.relative_to(ROOT)).replace(
                            "\\", "/"),
                        "evidence_kind": kind, "subject_code": subj,
                        "bytes": f.stat().st_size,
                        "sha256": file_sha256(f),
                        "obtained_at": None,
                        "manifest_verified": None,
                    })
                    evidence_count += 1
            # 对照文件（原价格指数）
            ctrl_f = EVID_CTRL / (
                f"csindex_ctrl_{c['price_index']}_from20040102.json")
            if ctrl_f.exists():
                tr_layer.upsert_evidence(conn, {
                    "relative_path": str(ctrl_f.relative_to(ROOT)).replace(
                        "\\", "/"),
                    "evidence_kind": "control",
                    "subject_code": c["price_index"],
                    "bytes": ctrl_f.stat().st_size,
                    "sha256": file_sha256(ctrl_f),
                    "manifest_verified": None,
                })
                evidence_count += 1

            # ---- 质量快照 ----
            dist = tr_layer.row_quality_distribution(conn, code)
            tr_layer.save_quality_snapshot(
                conn, code, run_id=run_id,
                row_count=tr_layer.count_raw_rows(conn, code),
                distribution=dist,
                coverage_status=q["coverage_status"],
                continuity_status=c["continuity_level"],
                missing_trading_days=q.get("missing_trading_days"),
                dates_outside_calendar=q.get("dates_outside_calendar"),
                real_history_start=snap["real_history_start"],
                detail={"synthetic_status": snap["synthetic_status"],
                        "calendar_note": CALENDAR_NOTE[group]})
            quality_rows.append(code)

            # ---- 映射 ----
            m = r1.get("mapping_evidence") or {}
            if m:
                tr_layer.save_mapping(conn, {
                    "tr_code": code,
                    "price_index_code": c["price_index"],
                    "price_index_official_name":
                        m.get("price_index_official_name"),
                    "price_index_basic_date": m.get("price_index_basic_date"),
                    "tr_basic_date": m.get("tr_candidate_basic_date"),
                    "base_date_match": m.get("base_date_match"),
                    "ratio_sample_count": m.get("ratio_sample_count"),
                    "ratio_first": m.get("ratio_first"),
                    "ratio_last": m.get("ratio_last"),
                    "all_ratios_ge_one": m.get("all_ratios_ge_one"),
                    "ratio_increasing": m.get("ratio_increasing"),
                    "ratio_equals_one_count": m.get(
                        "ratio_equals_one_count"),
                    "mapping_verified": m.get("mapping_verified"),
                    "evidence_level": "technical_inference",
                    "official_mapping_document_found": False,
                    "note": m.get("mapping_evidence_note"),
                })
                mapping_rows.append(code)

        # 证据数按**数据库实际唯一文件数**统计，
        # 不累加 upsert 调用次数（同一对照文件可能被多个候选引用）
        evidence_count = conn.execute(
            "select count(*) from tr_evidence_files").fetchone()[0]
        idx_after = tr_layer.index_daily_fingerprint(conn)
        tr_layer.finish_run(
            conn, run_id, status="success",
            candidate_count=cand_count, rows_inserted=rows_inserted,
            rows_skipped=rows_skipped, evidence_count=evidence_count,
            index_daily_before=idx_before["row_count"],
            index_daily_after=idx_after["row_count"],
            index_daily_fingerprint_before=idx_before["fingerprint"],
            index_daily_fingerprint_after=idx_after["fingerprint"])

        counts = tr_layer.tr_table_counts(conn)
        iso = tr_layer.assert_isolated(conn)

    print(f"候选注册: {cand_count}")
    print(f"原始行情: 插入 {rows_inserted} / 跳过 {rows_skipped}")
    print(f"证据登记: {evidence_count}")
    print(f"质量快照: {len(quality_rows)}  映射: {len(mapping_rows)}")
    print(f"表行数: {json.dumps(counts, ensure_ascii=False)}")
    print(f"index_daily 前后: {idx_before['row_count']} -> "
          f"{idx_after['row_count']}")
    print(f"index_daily 指纹一致: "
          f"{idx_before['fingerprint'] == idx_after['fingerprint']}")
    print(f"隔离检查: {iso['isolated']}")


if __name__ == "__main__":
    main()
