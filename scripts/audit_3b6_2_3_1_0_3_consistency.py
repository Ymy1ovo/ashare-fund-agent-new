"""阶段3B-6.2.3.1.0.3 连续性证据等级与准入统计最终一致性修正。

**只读**：不重新下载、不修改数据库。

以 3B-6.2.3.1.0.2 的逐候选证据为准，重新计算全部准入状态，
并显式表达「代理日历验证 ≠ 官方日历验证」。
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

REPORTS = ROOT / "reports"
EVID_OLD1 = REPORTS / "evidence" / "phase3B6_2_3_1_0_1"
EVID_OLD2 = REPORTS / "evidence" / "phase3B6_2_3_1_0_2"
EVID = REPORTS / "evidence" / "phase3B6_2_3_1_0_3"

AUDIT_1 = REPORTS / "phase3B6_2_3_1_0_1_audit.json"
AUDIT_2 = REPORTS / "phase3B6_2_3_1_0_2_audit.json"

# 连续性证据等级（五态）
CONTINUITY_LEVELS = {
    "verified_official_calendar": {
        "rank": 5,
        "definition": "相对**官方指数发布日历**验证连续",
        "allows_validated": True,
    },
    "verified_against_proxy_calendar": {
        "rank": 4,
        "definition": "相对**项目 A 股交易日历代理**验证连续；"
                      "**不是官方发布日历**",
        "allows_validated": False,
        "note": "可进入 proxy_qualified_series_candidate，"
                "**不得**冒充 official 验证",
    },
    "has_unresolved_suspicion": {
        "rank": 3,
        "definition": "存在疑似休市占位行但无官方日历证据",
        "allows_validated": False,
    },
    "has_issues": {
        "rank": 2,
        "definition": "存在无法解释的日历外日期",
        "allows_validated": False,
    },
    "unknown": {
        "rank": 1,
        "definition": "适用市场日历未取得，无法核验",
        "allows_validated": False,
    },
}


def db_path() -> str:
    from app.config import settings
    return str(settings.database_path)


def connect_ro():
    import sqlite3
    p = db_path().replace("\\", "/")
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    conn.execute("pragma temp_store = memory")
    return conn


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def map_continuity_level(raw: str, calendar_is_official: bool) -> str:
    """把 3B-6.2.3.1.0.2 的连续性状态映射为五态证据等级。

    **关键**：`verified` 只有在官方日历下才算 `verified_official_calendar`；
    在代理日历下只能是 `verified_against_proxy_calendar`。
    """
    if raw == "verified":
        return ("verified_official_calendar" if calendar_is_official
                else "verified_against_proxy_calendar")
    if raw in ("has_unresolved_suspicion", "has_issues", "unknown"):
        return raw
    return "unknown"


# ---------------------------------------------------------------- 准入计算
def compute_admission(cand: dict) -> dict:
    """三个准入状态 + 一个独立统计，**逐条按真实证据计算**。"""
    d2 = cand["dims_020"]
    q = cand["quality_020"]
    synth = cand["synthetic_020"]
    calendar_official = cand["calendar_is_official"]
    cont_level = cand["continuity_level"]

    identity = bool(d2.get("official_identity_verified"))
    basis = bool(d2.get("return_basis_verified"))
    api = bool(d2.get("history_api_available"))
    mapping = bool(d2.get("mapping_to_price_index_verified"))
    quality = bool(d2.get("data_quality_verified"))
    coverage = q.get("coverage_status") == "verified"
    pit = bool(d2.get("point_in_time_available"))
    real_start_known = synth.get("real_history_start") not in (None, "unknown")

    # A. 原始数据层：只需身份 + 接口
    ingest = bool(identity and api)

    # B. 已验证序列：必须全部满足，且连续性必须达官方等级
    cont_ok_for_validated = CONTINUITY_LEVELS[cont_level][
        "allows_validated"]
    validated = bool(identity and basis and mapping and quality and coverage
                     and cont_ok_for_validated and real_start_known)

    # B'. 代理验证候选：允许代理日历下覆盖+连续，但不含官方等级要求
    proxy_qualified = bool(
        identity and basis and mapping and quality and coverage
        and cont_level in ("verified_official_calendar",
                           "verified_against_proxy_calendar"))

    # C. 正式准入：validated + 时点可用
    admitted = bool(validated and pit)

    blockers = []
    if not identity:
        blockers.append("官方身份")
    if not basis:
        blockers.append("收益口径")
    if not mapping:
        blockers.append("映射证据")
    if not quality:
        blockers.append("数据质量")
    if not coverage:
        blockers.append(f"覆盖={q.get('coverage_status')}")
    if not cont_ok_for_validated:
        blockers.append(f"连续性={cont_level}")
    if not real_start_known:
        blockers.append("真实历史起点未知")
    if not pit:
        blockers.append("时点可用性")

    return {
        "tr_candidate": cand["tr_candidate"],
        "price_index": cand["price_index"],
        "group": cand["group"],
        "market": cand["market"],
        "calendar_used": cand["calendar_used"],
        "calendar_is_official": calendar_official,
        "continuity_level": cont_level,
        "continuity_level_definition": CONTINUITY_LEVELS[cont_level][
            "definition"],
        "raw_data_layer_ingest_candidate": ingest,
        "validated_series_candidate": validated,
        "proxy_qualified_series_candidate": proxy_qualified,
        "formal_series_admitted": admitted,
        "blockers": blockers,
        "evidence_snapshot": {
            "official_identity_verified": identity,
            "return_basis_verified": basis,
            "mapping_to_price_index_verified": mapping,
            "history_api_available": api,
            "data_quality_verified": quality,
            "coverage_status": q.get("coverage_status"),
            "continuity_raw_status": q.get("continuity_status"),
            "point_in_time_available": pit,
            "real_history_start": synth.get("real_history_start"),
            "synthetic_status": synth.get("status"),
        },
        "note": _admission_note(identity, api, validated, proxy_qualified,
                                admitted, cont_level, quality),
    }


def _admission_note(identity, api, validated, proxy_q, admitted,
                    cont_level, quality) -> str:
    parts = []
    if identity and api:
        parts.append("可进原始隔离层")
    else:
        parts.append("不得进原始层")
    if validated:
        parts.append("可作为已验证序列")
    elif proxy_q:
        parts.append("**仅代理日历验证**，不得称官方验证")
    else:
        parts.append("不得作为已验证序列")
    if not quality:
        parts.append("数据质量未通过")
    if cont_level == "has_unresolved_suspicion":
        parts.append("连续性存在未解决疑点")
    if not admitted:
        parts.append("不得正式准入")
    return "；".join(parts)


# ---------------------------------------------------------------- 主流程
def load_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def build_candidates(d1: dict, d2: dict) -> list[dict]:
    """以 3B-6.2.3.1.0.2 为证据源，重建全部候选状态。"""
    out = []
    for r2 in d2["candidates"]:
        code = r2["tr_candidate"]
        r1 = next((x for x in d1["candidates"]
                   if x["tr_candidate"] == code), None)
        cal_used = r2["calendar_used"]
        cal_official = False  # 本轮全部为代理或未取得
        raw_cont = r2["quality"]["continuity_status"]
        level = map_continuity_level(raw_cont, cal_official)
        cand = {
            "tr_candidate": code,
            "price_index": r2["price_index"],
            "group": r2["group"],
            "market": r2["market"],
            "calendar_used": cal_used,
            "calendar_is_official": cal_official,
            "continuity_level": level,
            "continuity_raw_020": raw_cont,
            "continuity_raw_010": (r1["quality"]["continuity_status"]
                                   if r1 else None),
            "quality_020": r2["quality"],
            "synthetic_020": r2["synthetic_start_detection"],
            "dims_020": {
                "official_identity_verified": True,
                "return_basis_verified": _basis_ok(r2),
                "history_api_available": r2["quality"]["row_count"] > 0,
                "mapping_to_price_index_verified": _mapping_ok(code, d1),
                "data_quality_verified": r2["quality"][
                    "data_quality_verified"],
                "point_in_time_available": False,
            },
        }
        cand["admission"] = compute_admission(cand)
        cand["conflict_with_010"] = (
            r1 is not None
            and r1["quality"]["continuity_status"] != raw_cont)
        out.append(cand)
    return out


def _official_name(code: str) -> str:
    """从 3B-6.2.3.1.0 已保存的官方基本信息读取指数全称。"""
    f = REPORTS / "evidence" / "phase3B6_2_3_1_0" / f"basic_{code}.json"
    if not f.exists():
        return ""
    try:
        data = json.loads(f.read_bytes().decode("utf-8")).get("data") or {}
    except Exception:
        return ""
    return data.get("indexFullNameCn") or ""


def _basis_ok(r2: dict) -> bool:
    """收益口径：官方名称含「全收益」或「净收益」。

    **债券衍生序列（净价/利息及再投资）不算股票全收益口径。**
    """
    code = r2["tr_candidate"]
    name = _official_name(code)
    if not name:
        return False
    # 债券衍生：名称含「净价」或「利息及再投资」→ 非股票全收益
    if ("净价" in name) or ("利息及再投资" in name):
        return False
    return ("全收益" in name) or ("净收益" in name)


def _mapping_ok(code: str, d1: dict) -> bool:
    r1 = next((x for x in d1["candidates"]
               if x["tr_candidate"] == code), None)
    if not r1:
        return False
    return bool(r1["mapping_evidence"]["mapping_verified"])


def summarize(cands: list[dict]) -> dict:
    def cnt(rs, key):
        return sum(1 for r in rs if r["admission"][key])

    def level_cnt(rs, lv):
        return sum(1 for r in rs if r["continuity_level"] == lv)

    groups = {}
    for g in ("stock", "bond", "hk"):
        rs = [r for r in cands if r["group"] == g]
        groups[g] = {
            "candidate_count": len(rs),
            "market": rs[0]["market"] if rs else None,
            "calendar_used": rs[0]["calendar_used"] if rs else None,
            "calendar_is_official": False,
            "continuity_verified_official_calendar": level_cnt(
                rs, "verified_official_calendar"),
            "continuity_verified_against_proxy_calendar": level_cnt(
                rs, "verified_against_proxy_calendar"),
            "continuity_has_unresolved_suspicion": level_cnt(
                rs, "has_unresolved_suspicion"),
            "continuity_has_issues": level_cnt(rs, "has_issues"),
            "continuity_unknown": level_cnt(rs, "unknown"),
            "raw_data_layer_ingest_candidate": cnt(
                rs, "raw_data_layer_ingest_candidate"),
            "validated_series_candidate": cnt(
                rs, "validated_series_candidate"),
            "proxy_qualified_series_candidate": cnt(
                rs, "proxy_qualified_series_candidate"),
            "formal_series_admitted": cnt(rs, "formal_series_admitted"),
        }

    return {
        "total_candidates": len(cands),
        "groups": groups,
        "totals": {
            "continuity_verified_official_calendar": level_cnt(
                cands, "verified_official_calendar"),
            "continuity_verified_against_proxy_calendar": level_cnt(
                cands, "verified_against_proxy_calendar"),
            "continuity_has_unresolved_suspicion": level_cnt(
                cands, "has_unresolved_suspicion"),
            "continuity_has_issues": level_cnt(cands, "has_issues"),
            "continuity_unknown": level_cnt(cands, "unknown"),
            "raw_data_layer_ingest_candidate": cnt(
                cands, "raw_data_layer_ingest_candidate"),
            "validated_series_candidate": cnt(
                cands, "validated_series_candidate"),
            "proxy_qualified_series_candidate": cnt(
                cands, "proxy_qualified_series_candidate"),
            "formal_series_admitted": cnt(cands, "formal_series_admitted"),
        },
        "conflicts_resolved": sum(1 for r in cands if r["conflict_with_010"]),
        "continuity_levels": CONTINUITY_LEVELS,
        "gates": {
            "ready_for_research_analysis": True,
            "ready_for_backtest": False,
            "ready_for_formal_ranking": False,
            "ready_for_3b6_2_3_1_series_build": False,
        },
        "_self_check": {
            "no_official_calendar_verified": level_cnt(
                cands, "verified_official_calendar") == 0,
            "proxy_only_399997CNY02": (
                next(r for r in cands
                     if r["tr_candidate"] == "399997CNY02")[
                         "continuity_level"]
                == "verified_against_proxy_calendar"),
            "eight_suspicion_not_verified": sum(
                1 for r in cands
                if r["group"] == "stock"
                and r["continuity_level"] == "has_unresolved_suspicion") == 8,
            "h20184_quality_failed": not next(
                r for r in cands if r["tr_candidate"] == "H20184")[
                    "dims_020"]["data_quality_verified"],
            "bond_hk_unknown": all(
                r["continuity_level"] == "unknown"
                for r in cands if r["group"] in ("bond", "hk")),
            "no_formal_admitted": cnt(cands, "formal_series_admitted") == 0,
            "ingest_all_12": cnt(cands, "raw_data_layer_ingest_candidate")
            == 12,
        },
    }


def build_manifest(cands: list[dict]) -> dict:
    """引用式 manifest：记录本轮读取的两轮 JSON 与其引用的原始证据。"""
    EVID.mkdir(parents=True, exist_ok=True)
    ref = {}

    def _add(path: Path, purpose: str) -> None:
        name = str(path.relative_to(ROOT)).replace("\\", "/")
        if path.exists():
            raw = path.read_bytes()
            ref[name] = {"purpose": purpose, "exists": True,
                         "bytes": len(raw),
                         "sha256": hashlib.sha256(raw).hexdigest()}
        else:
            ref[name] = {"purpose": purpose, "exists": False,
                         "bytes": None, "sha256": None}

    _add(AUDIT_1, "3B-6.2.3.1.0.1 审计 JSON（被修正对象）")
    _add(AUDIT_2, "3B-6.2.3.1.0.2 审计 JSON（本轮证据源）")

    # 原始官方证据（两轮引用的）
    for base, label in ((EVID_OLD1, "3B-6.2.3.1.0.1 引用证据"),
                        (EVID_OLD2, "3B-6.2.3.1.0.2 引用证据")):
        m = base / "manifest.json"
        if not m.exists():
            continue
        try:
            doc = json.loads(m.read_text(encoding="utf-8"))
        except Exception:
            continue
        files = doc.get("files") or {}
        for name, info in files.items():
            # 只登记存在的文件（原始官方响应）
            if not info.get("exists", True):
                continue
            rel = info.get("relative_path")
            if not rel:
                continue
            _add(ROOT / rel, label)

    exists = sum(1 for v in ref.values() if v["exists"])
    missing = [k for k, v in ref.items() if not v["exists"]]
    doc = {
        "phase": "3B-6.2.3.1.0.3",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "no_new_download": True,
        "note": ("本轮不下载新数据；manifest 记录被修正的两轮审计 JSON "
                 "及其引用的原始官方证据"),
        "referenced_total": len(ref),
        "referenced_exists": exists,
        "missing_count": len(missing),
        "missing_files": missing,
        "files": ref,
    }
    (EVID / "manifest.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {k: doc[k] for k in ("referenced_total", "referenced_exists",
                                "missing_count", "missing_files")}


def main() -> None:
    EVID.mkdir(parents=True, exist_ok=True)
    d1 = load_json(AUDIT_1)
    d2 = load_json(AUDIT_2)

    conn = connect_ro()
    try:
        before = {
            "database_path": db_path(),
            "database_sha256": file_sha256(db_path()),
            "index_daily_total": conn.execute(
                "select count(*) from index_daily").fetchone()[0],
            "integrity_check": conn.execute(
                "pragma integrity_check").fetchone()[0],
            "foreign_key_check": len(
                conn.execute("pragma foreign_key_check").fetchall()),
        }
    finally:
        conn.close()
    print(f"db_sha256={before['database_sha256']}")

    cands = build_candidates(d1, d2)
    summary = summarize(cands)

    for r in cands:
        a = r["admission"]
        print(f"  {r['tr_candidate']:14s} [{r['group']:5s}] "
              f"cont={r['continuity_level']:32s} "
              f"raw={a['raw_data_layer_ingest_candidate']!s:5s} "
              f"val={a['validated_series_candidate']!s:5s} "
              f"proxy={a['proxy_qualified_series_candidate']!s:5s} "
              f"adm={a['formal_series_admitted']!s:5s}"
              + ("  <-- 与010冲突已解决" if r["conflict_with_010"] else ""))

    conn = connect_ro()
    try:
        after = {
            "database_path": db_path(),
            "database_sha256": file_sha256(db_path()),
            "index_daily_total": conn.execute(
                "select count(*) from index_daily").fetchone()[0],
            "integrity_check": conn.execute(
                "pragma integrity_check").fetchone()[0],
            "foreign_key_check": len(
                conn.execute("pragma foreign_key_check").fetchall()),
        }
    finally:
        conn.close()

    result = {
        "phase": "3B-6.2.3.1.0.3",
        "task": "连续性证据等级与下一阶段准入统计最终一致性修正",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "baseline_head": "03f72f061ce16bd1f8d21c8847d7dca3a2052194",
        "read_only": True,
        "no_redownload": True,
        "authoritative_source": (
            "以 3B-6.2.3.1.0.2 的逐候选证据为准；"
            "3B-6.2.3.1.0.1 的 continuity_verified=9 已作废"),
        "continuity_level_definitions": CONTINUITY_LEVELS,
        "admission_definitions": {
            "raw_data_layer_ingest_candidate":
                "官方身份 + 历史接口可用（质量异常原样保留，不等于质量通过）",
            "validated_series_candidate":
                "身份+口径+映射+质量+覆盖+连续性达官方等级+真实起点已知",
            "proxy_qualified_series_candidate":
                "身份+口径+映射+质量+覆盖+连续性达**代理**日历等级"
                "（**不得称官方验证**）",
            "formal_series_admitted":
                "validated + 历史时点可用",
        },
        "db_before": before,
        "db_after": after,
        "db_unchanged": before["database_sha256"] == after["database_sha256"],
        "candidates": cands,
        "summary": summary,
    }
    result["evidence_manifest"] = build_manifest(cands)

    (REPORTS / "phase3B6_2_3_1_0_3_audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")

    print("\n=== 汇总 ===")
    print(json.dumps(summary["totals"], ensure_ascii=False, indent=1))
    print("\n=== 自校验 ===")
    print(json.dumps(summary["_self_check"], ensure_ascii=False, indent=1))
    print(f"\n冲突已解决: {summary['conflicts_resolved']} 条")
    print(f"数据库未变: {result['db_unchanged']}")


if __name__ == "__main__":
    main()
