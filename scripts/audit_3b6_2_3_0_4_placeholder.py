"""阶段3B-6.2.3.0.4 10 条 2004-01-01 suspect 占位记录来源溯源审计。

**严格只读**：不修改正式数据库、不删除/更新任何 index_daily 记录。

四部分：

1. 逐条还原记录来源（DB 字段 + run_id + source + 原始响应）
2. 逐指数官方历史资料核验（基日/发布日/最早历史/2004-01-01 是否有效）
3. 项目内部生成逻辑排查（代码/迁移/测试 fixture）
4. 逐条证据分级与最终结论
"""
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

REPORTS = ROOT / "reports"
EVID = REPORTS / "evidence" / "phase3B6_2_3_0_4"

TARGET_DATE = "2004-01-01"
TARGET_ISO = "20040101"
EXPECTED_CODES = ["000012", "000016", "000300", "000905", "000906",
                  "000922", "000942", "399997", "930930", "H30184"]
EXPECTED_COUNT = 10

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
CSI_BASIC = "https://www.csindex.com.cn/csindex-home/indexInfo/index-basic-info/"
CSI_PERF = ("https://www.csindex.com.cn/csindex-home/perf/"
            "index-perf?indexCode={code}&startDate={d}&endDate={d}")


def db_path() -> str:
    from app.config import settings
    return str(settings.database_path)


def connect_ro() -> sqlite3.Connection:
    p = db_path().replace("\\", "/")
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    conn.execute("pragma temp_store = memory")
    return conn


def file_sha256(path: str | None = None) -> str:
    p = path or db_path()
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def baseline_snapshot(conn: sqlite3.Connection) -> dict:
    """任务开始/结束的完整基线快照，用于不变性比对。"""
    import os
    cols = [r[1] for r in conn.execute("pragma table_info(index_daily)")]
    targets = []
    for r in conn.execute(
            "select * from index_daily where trade_date=? order by index_code",
            (TARGET_DATE,)):
        rec = dict(zip(cols, r))
        # 行级指纹（全字段内容哈希）
        h = hashlib.sha256()
        for c in cols:
            h.update(f"{c}={rec[c]!r}\n".encode())
        rec["row_content_sha256"] = h.hexdigest()
        targets.append(rec)

    other = {}
    for (code,) in conn.execute(
            "select distinct index_code from index_daily order by index_code"):
        fp = hashlib.sha256()
        n = 0
        for r in conn.execute(
                "select trade_date, close from index_daily "
                "where index_code=? order by trade_date", (code,)):
            fp.update(f"{r[0]}|{r[1]}\n".encode())
            n += 1
        other[code] = {"rows": n, "fingerprint": fp.hexdigest()}

    return {
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "database_path": db_path(),
        "database_sha256": file_sha256(),
        "database_bytes": os.path.getsize(db_path()),
        "index_daily_total": conn.execute(
            "select count(*) from index_daily").fetchone()[0],
        "integrity_check": conn.execute(
            "pragma integrity_check").fetchone()[0],
        "foreign_key_check": len(
            conn.execute("pragma foreign_key_check").fetchall()),
        "target_date": TARGET_DATE,
        "target_count": len(targets),
        "target_records": targets,
        "other_index_fingerprints": other,
        "suspect_total": conn.execute(
            "select count(*) from index_daily "
            "where quality_status<>'valid'").fetchone()[0],
        "h30184_20130628": dict(zip(
            cols,
            conn.execute(
                "select * from index_daily where index_code='H30184' "
                "and trade_date='2013-06-28'").fetchone() or [None] * len(cols))),
    }


# ---------------------------------------------------------------- 官方接口
def _get(url: str, *, timeout: int = 45, retries: int = 3) -> bytes:
    import time
    import urllib.request
    last = None
    for i in range(retries + 1):
        if i:
            time.sleep(2.0 * i)
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA,
                              "Referer": "https://www.csindex.com.cn/"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as exc:
            last = exc
    raise last  # type: ignore[misc]


def _save(name: str, raw: bytes) -> dict:
    EVID.mkdir(parents=True, exist_ok=True)
    f = EVID / name
    f.write_bytes(raw)
    return {"file": str(f.relative_to(ROOT)).replace("\\", "/"),
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "obtained_at": datetime.now().isoformat(timespec="seconds")}


def fetch_official_basic(code: str) -> dict:
    """官方指数基本信息（基日 / 发布日期 / 基点）。"""
    url = CSI_BASIC + code
    try:
        raw = _get(url)
    except Exception as exc:
        return {"index_code": code, "url": url,
                "error": f"{type(exc).__name__}", "obtained": False}
    meta = _save(f"csindex_basic_{code}.json", raw)
    try:
        d = json.loads(raw.decode("utf-8")).get("data") or {}
    except Exception:
        d = {}
    return {
        "index_code": code,
        "url": url,
        "obtained": bool(d),
        **meta,
        "official_full_name": d.get("indexFullNameCn"),
        "basic_date": d.get("basicDate"),
        "basic_index": d.get("basicIndex"),
        "publish_date": d.get("publishDate"),
        "publish_channel": d.get("publishChannelCn"),
        "index_type": d.get("indexType"),
    }


def fetch_official_history(code: str, start: str = TARGET_ISO) -> dict:
    """官方历史行情（从 2004-01-01 起），检查是否含目标日。"""
    url = CSI_PERF.format(code=code, d=start)
    # 用一个足够长的区间取全量
    url = (f"https://www.csindex.com.cn/csindex-home/perf/index-perf"
           f"?indexCode={code}&startDate={start}&endDate=20261123")
    try:
        raw = _get(url)
    except Exception as exc:
        return {"index_code": code, "url": url,
                "error": f"{type(exc).__name__}", "obtained": False}
    meta = _save(f"csindex_hist_{code}_from{start}.json", raw)
    try:
        rows = json.loads(raw.decode("utf-8")).get("data") or []
    except Exception:
        rows = []
    target = next((r for r in rows if r.get("tradeDate") == TARGET_ISO), None)
    dates = [r.get("tradeDate") for r in rows]
    return {
        "index_code": code,
        "url": url,
        "obtained": bool(rows),
        **meta,
        "row_count": len(rows),
        "earliest_date": dates[0] if dates else None,
        "latest_date": dates[-1] if dates else None,
        "has_2004_01_01": target is not None,
        "row_2004_01_01": target,
        "second_row": rows[1] if len(rows) > 1 else None,
    }


def fetch_official_from_20040102(code: str) -> dict:
    """对照：从 2004-01-02 起请求，检验 2004-01-01 是否仍出现。"""
    url = (f"https://www.csindex.com.cn/csindex-home/perf/index-perf"
           f"?indexCode={code}&startDate=20040102&endDate=20261123")
    try:
        raw = _get(url)
    except Exception as exc:
        return {"index_code": code, "url": url,
                "error": f"{type(exc).__name__}", "obtained": False}
    meta = _save(f"csindex_ctrl_{code}_from20040102.json", raw)
    try:
        rows = json.loads(raw.decode("utf-8")).get("data") or []
    except Exception:
        rows = []
    dates = [r.get("tradeDate") for r in rows]
    return {
        "index_code": code,
        "url": url,
        "obtained": bool(rows),
        **meta,
        "row_count": len(rows),
        "earliest_date": dates[0] if dates else None,
        "has_2004_01_01": TARGET_ISO in dates,
        "first_row": rows[0] if rows else None,
    }


# ---------------------------------------------------------------- 内部逻辑排查
MAGIC_VALUES = ["2004-01-01", "20040101", "1000.0", "3000.0",
                "994.47", "1204.61", "1028.64", "1011.35", "99.22"]
CODE_GLOBS = ["*.py", "*.sql"]


def scan_internal_code() -> dict:
    """在项目生产代码/迁移中搜索关键值，区分生产代码与报告/证据。"""
    import subprocess
    out: dict = {"searched_values": MAGIC_VALUES, "per_value": {}}
    for v in MAGIC_VALUES:
        r = subprocess.run(
            ["git", "grep", "-n", "-F", v, "--"] + CODE_GLOBS,
            cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="ignore")
        lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
        out["per_value"][v] = {
            "production_code_hits": len(lines),
            "hits": lines[:10],
        }
    return out


def find_ingest_logic() -> dict:
    """定位采集脚本中决定 2004-01-01 出现位置的代码。"""
    import subprocess
    f = ROOT / "app" / "fund" / "index_ingest.py"
    txt = f.read_text(encoding="utf-8") if f.exists() else ""
    lines = txt.splitlines()
    found = {}
    for i, line in enumerate(lines, 1):
        if "DEFAULT_START" in line and "=" in line and "def" not in line:
            found["default_start_line"] = i
            found["default_start_text"] = line.strip()
        if "baseline" in line.lower() and "占位" in line:
            found.setdefault("baseline_comment", []).append(
                {"line": i, "text": line.strip()})
    # 提取关键代码段
    found["source_file"] = str(f.relative_to(ROOT)).replace("\\", "/")
    found["file_sha256"] = (hashlib.sha256(f.read_bytes()).hexdigest()
                            if f.exists() else None)
    # 采集接口名
    for i, line in enumerate(lines, 1):
        if "SOURCE_CSINDEX" in line and "=" in line:
            found["source_const_line"] = i
            found["source_const_text"] = line.strip()
        if "stock_zh_index_hist_csindex" in line and "def" not in line:
            found.setdefault("interface_usage", []).append(
                {"line": i, "text": line.strip()})
    return found


def read_run_records(conn: sqlite3.Connection,
                     run_ids: list[int]) -> list[dict]:
    """读取 index_ingest_runs 中对应批次记录。"""
    out = []
    for rid in run_ids:
        row = conn.execute(
            "select run_id, index_code, source, interface_name, "
            "request_start_date, request_end_date, requested_at, "
            "finished_at, status, returned_rows, actual_date_min, "
            "actual_date_max, content_fingerprint, ingest_mode, note "
            "from index_ingest_runs where run_id=?", (rid,)).fetchone()
        if not row:
            out.append({"run_id": rid, "found": False})
            continue
        cols = ["run_id", "index_code", "source", "interface_name",
                "request_start_date", "request_end_date", "requested_at",
                "finished_at", "status", "returned_rows", "actual_date_min",
                "actual_date_max", "content_fingerprint", "ingest_mode", "note"]
        out.append({"found": True, **dict(zip(cols, row))})
    return out


# ---------------------------------------------------------------- 逐条判定
def judge_record(rec: dict, basic: dict, hist: dict, ctrl: dict,
                 runs: list[dict]) -> dict:
    """单条记录的完整证据分级与结论。"""
    code = rec["index_code"]
    close = rec.get("close")

    # ---- 官方历史起点 ----
    earliest = hist.get("earliest_date")
    has_target = hist.get("has_2004_01_01")
    official_row = hist.get("row_2004_01_01") or {}

    # ---- 是否为「请求起始日合成行」 ----
    # 判据：从 20040101 请求时首行==2004-01-01；从 20040102 请求时该日消失
    synth_by_start = bool(has_target and not ctrl.get("has_2004_01_01"))

    # ---- 与第二行是否数值相同（合成行特征） ----
    second = hist.get("second_row") or {}
    same_as_second = (
        official_row.get("close") is not None
        and second.get("close") is not None
        and float(official_row["close"]) == float(second["close"]))
    # 占位特征：成交量/成交额为 0 或 null
    zero_volume = (official_row.get("tradingVol") in (0, 0.0, None)
                   and official_row.get("tradingValue") in (0, 0.0, None))

    # ---- 基点混淆判断 ----
    base_index = basic.get("basic_index")
    base_date = basic.get("basic_date")
    publish_date = basic.get("publish_date")
    base_confusion = False
    if base_index is not None and close is not None:
        try:
            base_confusion = abs(float(close) - float(base_index)) < 1e-9
        except (TypeError, ValueError):
            base_confusion = False

    # ---- 2004-01-01 是否为有效交易日（A股日历代理） ----
    cal_hit = None  # 由调用方注入

    # ---- 来源判定 ----
    if has_target and synth_by_start:
        origin = "官方接口（起始日合成行）"
        origin_key = "official_api_synthetic_start_row"
    elif has_target:
        origin = "官方接口（原始响应含该日）"
        origin_key = "official_api_actual_row"
    else:
        origin = "unknown"
        origin_key = "unknown"

    # ---- 证据等级 ----
    if has_target and hist.get("sha256"):
        grade = "L1"          # 官方接口原始响应
    elif basic.get("obtained"):
        grade = "L2"
    else:
        grade = "insufficient"

    # ---- 结论 ----
    if synth_by_start:
        conclusion = (
            f"该行由官方接口对**请求起始日**的合成行为产生：从 {TARGET_ISO} 起"
            f"请求时首行为 {TARGET_DATE}，改从 20040102 起请求后该日消失；"
            f"官方原始响应可复核（SHA256 {hist.get('sha256', '')[:16]}…）。"
            f"**不是项目内部生成的占位数据**，但也不是该指数在 "
            f"{TARGET_DATE} 的真实交易日行情。")
    elif has_target:
        conclusion = (
            f"官方原始响应确实包含 {TARGET_DATE} 且从 20040102 起请求仍存在，"
            f"需进一步核实其是否为真实交易日行情。")
    else:
        conclusion = (
            f"官方接口从 {TARGET_ISO} 起请求时**未返回** {TARGET_DATE}，"
            f"来源无法确认为官方响应。")

    # ---- 建议动作（本轮不执行） ----
    if synth_by_start:
        action = "保留（已标 suspect，不建议删除：可追溯官方合成行为）"
    else:
        action = "待核实"

    return {
        "index_code": code,
        "official_full_name": basic.get("official_full_name"),
        "official_basic_date": base_date,
        "official_publish_date": publish_date,
        "official_basic_index": base_index,
        "earliest_official_history": earliest,
        "has_2004_01_01_in_official_response": has_target,
        "synthetic_when_requested_from_20040101": synth_by_start,
        "disappears_when_requested_from_20040102": (
            not ctrl.get("has_2004_01_01")
            if ctrl.get("obtained") else None),
        "official_row_2004_01_01": official_row,
        "official_second_row": second,
        "row_equals_second_row": same_as_second,
        "row_has_zero_volume_amount": zero_volume,
        "db_close": close,
        "official_close": official_row.get("close"),
        "db_matches_official": (
            close is not None and official_row.get("close") is not None
            and abs(float(close) - float(official_row["close"])) < 1e-9),
        "base_value_confusion": base_confusion,
        "source_origin": origin,
        "source_origin_key": origin_key,
        "run_records": runs,
        "evidence_grade": grade,
        "final_conclusion": conclusion,
        "recommended_action": action,
        "is_valid_trading_day": cal_hit,
        "historical_availability": "unknown",
        "historical_availability_note": (
            "官方接口当前返回该点位，但**不能证明该点位在 2004-01-01 "
            "当时已公开**（回溯数据 / 历史修订无法排除）"),
    }


def audit(conn: sqlite3.Connection, *, online: bool = True) -> dict:
    """执行完整审计（online=False 时只用已保存证据，不联网）。"""
    snap = baseline_snapshot(conn)
    targets = snap["target_records"]

    if len(targets) != EXPECTED_COUNT:
        raise RuntimeError(
            f"目标记录数 {len(targets)} != {EXPECTED_COUNT}，立即停止")

    codes = [r["index_code"] for r in targets]
    if sorted(codes) != sorted(EXPECTED_CODES):
        raise RuntimeError(f"目标指数集合不符：{codes}")

    # 交易日历（A股代理）
    cal_hit = conn.execute(
        "select count(*) from trade_calendar where trade_date=?",
        (TARGET_DATE,)).fetchone()[0] > 0

    # 采集批次
    run_ids = sorted({r["run_id"] for r in targets if r.get("run_id")})
    runs = read_run_records(conn, run_ids)

    # 内部代码排查
    internal = scan_internal_code()
    ingest = find_ingest_logic()

    records = []
    for rec in targets:
        code = rec["index_code"]
        if online:
            basic = fetch_official_basic(code)
            hist = fetch_official_history(code)
            ctrl = fetch_official_from_20040102(code)
        else:
            basic = load_saved_basic(code)
            hist = load_saved_hist(code)
            ctrl = load_saved_ctrl(code)
        j = judge_record(rec, basic, hist, ctrl, runs)
        j["is_valid_trading_day"] = ("no" if not cal_hit else "yes")
        j["a_share_calendar_proxy_note"] = (
            "trade_calendar 是 A 股交易日**代理**，不是指数官方发布日历")
        j["db_record"] = rec
        j["official_basic"] = basic
        records.append(j)

    return {
        "phase": "3B-6.2.3.0.4",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "read_only": True,
        "target_date": TARGET_DATE,
        "target_count": len(targets),
        "baseline": snap,
        "a_share_calendar_has_2004_01_01": cal_hit,
        "ingest_runs": runs,
        "internal_code_scan": internal,
        "ingest_logic": ingest,
        "records": records,
    }


def _load_json(name: str) -> dict:
    f = EVID / name
    if not f.exists():
        return {"obtained": False}
    raw = f.read_bytes()
    try:
        d = json.loads(raw.decode("utf-8"))
    except Exception:
        d = {}
    return {"obtained": True, "sha256": hashlib.sha256(raw).hexdigest(),
            "file": str(f.relative_to(ROOT)).replace("\\", "/"),
            "raw": d}


def load_saved_basic(code: str) -> dict:
    d = _load_json(f"csindex_basic_{code}.json")
    data = (d.get("raw") or {}).get("data") or {}
    return {"index_code": code, "obtained": bool(data),
            "sha256": d.get("sha256"), "file": d.get("file"),
            "official_full_name": data.get("indexFullNameCn"),
            "basic_date": data.get("basicDate"),
            "basic_index": data.get("basicIndex"),
            "publish_date": data.get("publishDate")}


def load_saved_hist(code: str) -> dict:
    d = _load_json(f"csindex_hist_{code}_from20040101.json")
    rows = (d.get("raw") or {}).get("data") or []
    target = next((r for r in rows if r.get("tradeDate") == TARGET_ISO), None)
    dates = [r.get("tradeDate") for r in rows]
    return {"index_code": code, "obtained": bool(rows),
            "sha256": d.get("sha256"), "file": d.get("file"),
            "row_count": len(rows),
            "earliest_date": dates[0] if dates else None,
            "latest_date": dates[-1] if dates else None,
            "has_2004_01_01": target is not None,
            "row_2004_01_01": target,
            "second_row": rows[1] if len(rows) > 1 else None}


def load_saved_ctrl(code: str) -> dict:
    d = _load_json(f"csindex_ctrl_{code}_from20040102.json")
    rows = (d.get("raw") or {}).get("data") or []
    dates = [r.get("tradeDate") for r in rows]
    return {"index_code": code, "obtained": bool(rows),
            "sha256": d.get("sha256"), "file": d.get("file"),
            "row_count": len(rows),
            "earliest_date": dates[0] if dates else None,
            "has_2004_01_01": TARGET_ISO in dates,
            "first_row": rows[0] if rows else None}


# ---------------------------------------------------------------- 汇总与主流程
def summarize(result: dict) -> dict:
    recs = result["records"]

    def cnt(pred):
        return sum(1 for r in recs if pred(r))

    grades = {}
    for r in recs:
        grades[r["evidence_grade"]] = grades.get(r["evidence_grade"], 0) + 1

    return {
        "target_count": len(recs),
        "official_evidence_obtained": cnt(
            lambda r: r["has_2004_01_01_in_official_response"]),
        "synthetic_start_row_count": cnt(
            lambda r: r["synthetic_when_requested_from_20040101"]),
        "disappears_from_20040102_count": cnt(
            lambda r: r["disappears_when_requested_from_20040102"] is True),
        "db_matches_official_close": cnt(lambda r: r["db_matches_official"]),
        "row_equals_second_row": cnt(lambda r: r["row_equals_second_row"]),
        "row_zero_volume_amount": cnt(
            lambda r: r["row_has_zero_volume_amount"]),
        "base_value_confusion": cnt(lambda r: r["base_value_confusion"]),
        "all_still_suspect": cnt(
            lambda r: r["db_record"]["quality_status"] == "suspect"),
        "evidence_grade_counts": dict(sorted(grades.items())),
        "historical_availability_unknown": cnt(
            lambda r: r["historical_availability"] == "unknown"),
        "gates": {
            "ready_for_research_analysis": True,
            "ready_for_backtest": False,
            "ready_for_formal_ranking": False,
            "ready_for_3b6_2_3_1_series_build": False,
            "note": ("本轮只查明事实，不开放任何门禁"),
        },
        "_self_check": {
            "count_is_10": len(recs) == EXPECTED_COUNT,
            "all_target_date": all(
                r["db_record"]["trade_date"] == TARGET_DATE for r in recs),
            "all_suspect": all(
                r["db_record"]["quality_status"] == "suspect" for r in recs),
            "every_record_has_conclusion": all(
                r["final_conclusion"] for r in recs),
            "every_record_has_grade": all(
                r["evidence_grade"] in ("L1", "L2", "L3", "insufficient")
                for r in recs),
            "every_record_has_action": all(
                r["recommended_action"] for r in recs),
        },
    }


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true",
                    help="只用已保存证据，不联网")
    args = ap.parse_args()

    EVID.mkdir(parents=True, exist_ok=True)
    conn = connect_ro()
    try:
        print("=== 基线 ===")
        snap = baseline_snapshot(conn)
        print(f"  db_sha256={snap['database_sha256']}")
        print(f"  target_count={snap['target_count']}")
        print(f"  index_daily={snap['index_daily_total']}")
        print(f"  integrity={snap['integrity_check']} fk={snap['foreign_key_check']}")
        if snap["target_count"] != EXPECTED_COUNT:
            raise SystemExit(
                f"目标记录数 {snap['target_count']} != 10，立即停止")

        print("\n=== 审计（联网采集官方证据）===")
        result = audit(conn, online=not args.offline)
    finally:
        conn.close()

    summary = summarize(result)
    result["summary"] = summary

    (EVID / "baseline_before.json").write_text(
        json.dumps(snap, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    (REPORTS / "phase3B6_2_3_0_4_audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")

    print("\n=== 逐条结论 ===")
    for r in result["records"]:
        print(f"  {r['index_code']:8s} close={r['db_close']!s:10s} "
              f"grade={r['evidence_grade']:12s} "
              f"synth={r['synthetic_when_requested_from_20040101']!s:5s} "
              f"origin={r['source_origin_key']}")
    print("\n=== 汇总 ===")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
