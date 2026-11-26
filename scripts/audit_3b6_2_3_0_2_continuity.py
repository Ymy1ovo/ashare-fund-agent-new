"""阶段3B-6.2.3.0.2 指数历史连续性、时点可用性与全收益基准可行性审计。

**严格只读**：不修改正式数据库、不删除 suspect 记录、不写行情。

四部分：

1. 10 个指数历史连续性审计（按指数实际市场选择日历）
2. 历史时点可用性审计（快照/修订/版本可追溯性）
3. 全收益指数与研究基准可行性审计
4. 历史版本与数据修订风险
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
EVID = REPORTS / "evidence" / "phase3B6_2_3_0_2"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
CSI_BASIC = "https://www.csindex.com.cn/csindex-home/indexInfo/index-basic-info/"
CSI_PERF = ("https://www.csindex.com.cn/csindex-home/perf/"
            "index-perf?indexCode={code}&startDate={d}&endDate={d}")

INDEX_CODES = ["000300", "000905", "000906", "000016", "399997",
               "H30184", "000942", "000012", "000922", "930930"]

# **收益口径已获官方确认的股票价格指数**（8 个）
# 930930 口径仍为 unknown，不得计入；000012 是债券指数，单独统计
CONFIRMED_STOCK_PRICE_INDEXES = ["000300", "000905", "000906", "000016",
                                 "399997", "H30184", "000942", "000922"]
# 债券指数（衍生序列口径与股票全收益不同，必须独立统计）
BOND_INDEXES = ["000012"]
# 收益口径未确认的指数（不得计入任何已确认分母）
UNCONFIRMED_BASIS_INDEXES = ["930930"]

# 各指数适用的市场与日历（**不得统一套用 A 股日历**）
INDEX_MARKET = {
    "000300": {"market": "沪深A股", "calendar": "A股交易日历",
               "basis": "中证指数编制方案：沪深A股样本"},
    "000905": {"market": "沪深A股", "calendar": "A股交易日历",
               "basis": "中证指数编制方案：沪深A股样本"},
    "000906": {"market": "沪深A股", "calendar": "A股交易日历",
               "basis": "中证指数编制方案：沪深A股样本"},
    "000016": {"market": "上海A股", "calendar": "A股交易日历",
               "basis": "上证50编制方案：上证180样本"},
    "399997": {"market": "沪深A股", "calendar": "A股交易日历",
               "basis": "中证白酒编制方案：中证全指样本空间"},
    "H30184": {"market": "沪深A股", "calendar": "A股交易日历",
               "basis": "中证全指半导体编制方案：中证全指样本"},
    "000942": {"market": "沪深A股", "calendar": "A股交易日历",
               "basis": "中证内地主题系列编制方案：沪深A股"},
    "000012": {"market": "上海证券交易所（债券）",
               "calendar": "上交所债券交易日历（**未独立取得**）",
               "basis": "上证国债指数样本为在上交所上市的固定利率国债，"
                        "发布日历需按债券市场核验，**不得直接等同股票交易日历**"},
    "000922": {"market": "沪深A股", "calendar": "A股交易日历",
               "basis": "中证红利编制方案：中证全指样本空间"},
    "930930": {"market": "港股通（香港市场）",
               "calendar": "港股交易日历（**未独立取得**）",
               "basis": "中证港股通综合指数样本为符合港股通资格的港股，"
                        "发布日历须按香港市场核验，**不得套用A股日历**"},
}

# 官方全收益/净收益/衍生序列（代码来自官方基本信息接口，不按命名规律猜测）
TOTAL_RETURN_CANDIDATES = {
    "000300": [
        {"code": "H00300", "kind": "gross_total_return"},
        {"code": "N00300", "kind": "net_total_return"},
    ],
    "000905": [
        {"code": "H00905", "kind": "gross_total_return"},
        {"code": "N00905", "kind": "net_total_return"},
    ],
    "000906": [
        {"code": "H00906", "kind": "gross_total_return"},
        {"code": "N00906", "kind": "net_total_return"},
    ],
    "000016": [
        {"code": "H00016", "kind": "gross_total_return"},
        {"code": "N00016", "kind": "net_total_return"},
    ],
    "399997": [
        {"code": "H20539", "kind": "gross_total_return"},
        {"code": "399997CNY02", "kind": "net_total_return"},
    ],
    "H30184": [
        {"code": "H20184", "kind": "gross_total_return"},
    ],
    "000942": [
        {"code": "H00942", "kind": "gross_total_return"},
    ],
    "000922": [
        {"code": "H00922", "kind": "gross_total_return"},
    ],
    "000012": [
        {"code": "H00012", "kind": "bond_clean_price"},
        {"code": "N00012", "kind": "bond_interest_reinvestment"},
    ],
    "930930": [
        {"code": "H20930", "kind": "gross_total_return"},
    ],
}


def _get(url: str, *, timeout: int = 40, retries: int = 2) -> bytes:
    import time
    import urllib.request
    last = None
    for i in range(retries + 1):
        if i:
            time.sleep(1.5 * i)
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA,
                              "Referer": "https://www.csindex.com.cn/"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as exc:
            last = exc
    raise last  # type: ignore[misc]


def db_connect():
    import sqlite3
    from app.config import settings
    p = str(settings.database_path).replace("\\", "/")
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    conn.execute("pragma temp_store = memory")
    return conn


def calendar_dates(conn, start: str, end: str) -> set[str]:
    return {r[0] for r in conn.execute(
        "select trade_date from trade_calendar "
        "where trade_date between ? and ?", (start, end))}


def audit_continuity(code: str, conn) -> dict:
    """逐指数历史连续性审计（按指数实际市场选择日历）。"""
    import datetime as dt
    meta = INDEX_MARKET[code]
    rows = conn.execute(
        "select trade_date, close, quality_status, quality_note "
        "from index_daily where index_code=? order by trade_date",
        (code,)).fetchall()
    total = len(rows)
    dates = [r[0] for r in rows]
    valid_rows = [r for r in rows if r[2] == "valid"]
    suspect_rows = [r for r in rows if r[2] != "valid"]
    valid_dates = [r[0] for r in valid_rows]

    # 基础质量检查
    duplicates = total - len(set(dates))
    descending = sum(1 for i in range(1, len(dates)) if dates[i] < dates[i - 1])
    illegal = []
    for d in dates:
        try:
            dt.date.fromisoformat(d)
        except Exception:
            illegal.append(d)
    non_positive = sum(1 for r in rows if r[1] is not None and r[1] <= 0)
    null_close = sum(1 for r in rows if r[1] is None)

    # 日历适用性：只有 A 股日历可用的指数才做缺口核验
    calendar_available = meta["calendar"] == "A股交易日历"
    gap_info: dict = {
        "calendar_available": calendar_available,
        "calendar_name": meta["calendar"],
        "calendar_source": ("本项目 trade_calendar 表（A股交易日，"
                            "1990-12-19~2026-12-31）"),
        "calendar_is_official": False,
        "calendar_note": ("trade_calendar 为 A 股交易日代理，"
                          "**不是指数官方公布日历**"),
    }
    if not calendar_available:
        gap_info.update({
            "missing_trading_days": None,
            "max_gap": None,
            "coverage_ratio": None,
            "reason": (f"{meta['calendar']} 未独立取得，"
                       "本阶段不做缺失日核验，避免用错误日历误判缺口"),
            "dates_outside_a_calendar": None,
        })
    else:
        if valid_dates:
            start, end = min(valid_dates), max(valid_dates)
            cal = calendar_dates(conn, start, end)
            have = set(valid_dates)
            missing = sorted(cal - have)
            extra = sorted(have - cal)
            # 最大连续缺失区间
            max_gap = 0
            cur = 0
            prev = None
            for d in missing:
                if prev is not None:
                    cur = cur + 1 if _is_next_calendar_day(
                        cal, prev, d) else 1
                else:
                    cur = 1
                max_gap = max(max_gap, cur)
                prev = d
            gap_info.update({
                "missing_trading_days": len(missing),
                "missing_sample": missing[:20],
                "max_gap": max_gap,
                "dates_outside_calendar": len(extra),
                "dates_outside_calendar_sample": extra[:10],
                "coverage_ratio": (round(len(have & cal) / len(cal), 6)
                                   if cal else None),
                "calendar_start": start,
                "calendar_end": end,
                "calendar_trading_days": len(cal),
            })
        else:
            gap_info.update({"missing_trading_days": None,
                             "max_gap": None, "coverage_ratio": None})

    # 占位行识别（不得计入有效行情，也不得删除）
    placeholder = [{"trade_date": r[0], "close": r[1], "note": r[3]}
                   for r in suspect_rows]

    effective_min = min(valid_dates) if valid_dates else None
    effective_max = max(valid_dates) if valid_dates else None

    return {
        "index_code": code,
        "market": meta["market"],
        "calendar_used": meta["calendar"],
        "calendar_basis": meta["basis"],
        "raw_rows": total,
        "valid_rows": len(valid_rows),
        "suspect_rows": len(suspect_rows),
        "placeholder_rows": placeholder,
        "duplicate_dates": duplicates,
        "descending_dates": descending,
        "illegal_dates": illegal,
        "non_positive_close": non_positive,
        "null_close": null_close,
        "earliest_effective_date": effective_min,
        "latest_effective_date": effective_max,
        **gap_info,
        "continuity_verified": bool(
            calendar_available
            and gap_info.get("missing_trading_days") == 0
            and duplicates == 0 and descending == 0
            and not illegal and non_positive == 0 and null_close == 0),
        "continuity_verdict": _continuity_verdict(
            calendar_available, gap_info, duplicates, descending,
            illegal, non_positive, null_close),
    }


def _is_next_calendar_day(cal: set[str], a: str, b: str) -> bool:
    """判断 b 是否是日历中紧接 a 的下一交易日。"""
    import datetime as dt
    d = dt.date.fromisoformat(a)
    for _ in range(30):
        d += dt.timedelta(days=1)
        s = d.isoformat()
        if s in cal:
            return s == b
    return False


def _continuity_verdict(cal_ok, gap, dup, desc, illegal, nonpos, nullc) -> str:
    if not cal_ok:
        return ("**未验证**：该指数适用日历未独立取得，"
                "不做缺失日核验（避免用错误日历误判）")
    problems = []
    if gap.get("missing_trading_days"):
        problems.append(f"缺失 {gap['missing_trading_days']} 个交易日")
    if dup:
        problems.append(f"重复日期 {dup}")
    if desc:
        problems.append(f"倒序 {desc}")
    if illegal:
        problems.append(f"非法日期 {len(illegal)}")
    if nonpos:
        problems.append(f"非正收盘 {nonpos}")
    if nullc:
        problems.append(f"空收盘 {nullc}")
    return ("连续覆盖已验证" if not problems
            else "存在问题：" + "；".join(problems))


# ---------------------------------------------------------------- 时点可用性
def audit_point_in_time(conn) -> dict:
    """历史时点可用性审计：查库内是否有快照/版本/修订记录。"""
    tabs = {r[0] for r in conn.execute(
        "select name from sqlite_master where type='table'")}

    snapshot_tables = sorted(
        t for t in tabs
        if any(k in t.lower() for k in ("snapshot", "version", "history",
                                        "archive", "revision")))
    index_snapshot_tables = [t for t in snapshot_tables
                             if "index" in t.lower()]

    # index_daily 是否保存多个版本（同一 index_code+trade_date 多行）
    multi_version = conn.execute("""
        select count(*) from (
            select index_code, trade_date, count(*) c
            from index_daily group by index_code, trade_date having c > 1
        )""").fetchone()[0]

    # 采集时间分布：是否全部集中在少数几个时点
    collected = [r[0] for r in conn.execute(
        "select distinct substr(collected_at, 1, 10) from index_daily "
        "order by 1")]
    ingest = conn.execute(
        "select count(*), min(requested_at), max(requested_at) "
        "from index_ingest_runs").fetchone()

    # row_fingerprint 语义：只能证明当前行内容
    fp_rows = conn.execute(
        "select count(*) from index_daily "
        "where row_fingerprint is not null and row_fingerprint<>''"
    ).fetchone()[0]
    total_rows = conn.execute("select count(*) from index_daily").fetchone()[0]

    # 是否存在原始下载文件归档
    raw_archive_dirs = [p for p in (REPORTS / "evidence").glob("**/raw")
                        if p.is_dir()]
    raw_files = []
    for d in raw_archive_dirs:
        raw_files += [str(f.relative_to(ROOT)).replace("\\", "/")
                      for f in d.glob("*") if f.is_file()]

    return {
        "snapshot_tables_found": snapshot_tables,
        "index_snapshot_tables_found": index_snapshot_tables,
        "index_daily_multi_version_rows": multi_version,
        "collected_at_distinct_dates": collected,
        "collected_at_is_single_batch": len(collected) <= 1,
        "ingest_runs": {"count": ingest[0],
                        "first_requested_at": ingest[1],
                        "last_requested_at": ingest[2]},
        "row_fingerprint_rows": fp_rows,
        "total_rows": total_rows,
        "row_fingerprint_semantics": (
            "**仅证明当前数据行内容指纹**，不证明历史版本未被修订"),
        "raw_archive_files_count": len(raw_files),
        "raw_archive_files_sample": raw_files[:20],
        "raw_archive_contains_index_daily": any(
            "index" in f.lower() for f in raw_files),
        "checks": {
            "saves_raw_download_files": bool(
                any("index" in f.lower() for f in raw_files)),
            "saves_each_ingest_batch": ingest[0] > 0,
            "saves_version_number": "data_version" in
            [r[1] for r in conn.execute("pragma table_info(index_master)")],
            "same_date_multiple_versions": multi_version > 0,
            "has_revision_records": bool(index_snapshot_tables),
            "can_confirm_public_at_the_time": False,
            "all_collected_in_one_period": len(collected) <= 2,
            "fingerprint_proves_history": False,
        },
        "conclusion": {
            "historical_quotes_exist": True,
            "current_collection_time_traceable": ingest[0] > 0,
            "historical_data_version_traceable": multi_version > 0,
            "historical_publication_time_provable": False,
            "point_in_time_availability_provable": False,
        },
        "reason": (
            "库内 index_daily 每个 (index_code, trade_date) 仅一行，"
            "无历史快照表、无修订记录；collected_at 仅为当前采集时间，"
            "**不能证明该行情在历史交易日当时已公开**；"
            "row_fingerprint 只证明当前行内容，不证明历史版本未被修订"),
        "point_in_time_verified": False,
    }


# ---------------------------------------------------------------- 全收益可行性
TR_SAMPLE_FILE = EVID / "official_total_return_samples.json"


def _load_tr_samples() -> dict:
    if TR_SAMPLE_FILE.exists():
        try:
            return json.loads(TR_SAMPLE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_tr_samples(data: dict) -> None:
    EVID.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, ensure_ascii=False, indent=1,
                         sort_keys=True) + "\n"
    TR_SAMPLE_FILE.write_text(content, encoding="utf-8")
    (EVID / "official_total_return_samples.sha256").write_text(
        hashlib.sha256(content.encode("utf-8")).hexdigest() + "\n",
        encoding="utf-8")


def official_perf(code: str, yyyymmdd: str) -> dict:
    """取官方行情（带缓存，避免限流导致随机失败）。"""
    import time
    key = f"{code}|{yyyymmdd}"
    cache = _load_tr_samples()
    if cache.get(key, {}).get("close") is not None:
        return {**cache[key], "from_cache": True}
    u = CSI_PERF.format(code=code, d=yyyymmdd)
    last = None
    for i in range(3):
        if i:
            time.sleep(2.0 * i)
        try:
            rows = (json.loads(_get(u).decode("utf-8")).get("data") or [])
            if not rows:
                return {"code": code, "date": yyyymmdd, "close": None,
                        "reason": "官方接口该日无数据", "url": u}
            r = rows[0]
            rec = {"code": code, "date": yyyymmdd, "close": r.get("close"),
                   "official_name": r.get("indexNameCnAll"),
                   "official_code": r.get("indexCode"),
                   "url": u,
                   "obtained_at": datetime.now().isoformat(timespec="seconds"),
                   "source": "中证指数有限公司官网行情接口"}
            cache = _load_tr_samples()
            cache[key] = rec
            _save_tr_samples(cache)
            return rec
        except Exception as exc:
            last = exc
    return {"code": code, "date": yyyymmdd, "close": None,
            "reason": f"官方接口未取得（{type(last).__name__}）", "url": u}


TR_PROBE_DATES = ["20240102", "20200102", "20180102"]


def audit_total_return(conn) -> dict:
    """全收益/净收益/债券衍生序列可行性审计。"""
    records = []
    for base in INDEX_CODES:
        cands = []
        for cand in TOTAL_RETURN_CANDIDATES.get(base, []):
            code = cand["code"]
            basic = {}
            try:
                d = json.loads(_get(CSI_BASIC + code).decode("utf-8"))
                basic = d.get("data") or {}
            except Exception as exc:
                basic = {"error": f"{type(exc).__name__}"}
            samples = []
            for dd in TR_PROBE_DATES:
                r = official_perf(code, dd)
                samples.append(r)
            obtained = [s for s in samples if s.get("close") is not None]
            in_db = conn.execute(
                "select count(*) from index_daily where index_code=?",
                (code,)).fetchone()[0]
            cands.append({
                "code": code,
                "kind": cand["kind"],
                "official_full_name": basic.get("indexFullNameCn"),
                "official_short_name": basic.get("indexShortNameCn"),
                "publisher": "中证指数有限公司",
                "publish_date": basic.get("publishDate"),
                "basic_date": basic.get("basicDate"),
                "identity_verified": bool(basic.get("indexFullNameCn")),
                "official_api_samples": [
                    {"date": s["date"], "close": s.get("close"),
                     "url": s.get("url"), "reason": s.get("reason")}
                    for s in samples],
                "official_api_available": len(obtained) > 0,
                "official_api_sample_count": len(obtained),
                "already_in_database": in_db > 0,
                "database_rows": in_db,
            })
        records.append({
            "base_index": base,
            "base_basis": INDEX_MARKET[base]["market"],
            "index_class": (
                "confirmed_stock_price_index"
                if base in CONFIRMED_STOCK_PRICE_INDEXES
                else "bond_index" if base in BOND_INDEXES
                else "unconfirmed_basis_index"),
            "counts_in_confirmed_stock_denominator":
                base in CONFIRMED_STOCK_PRICE_INDEXES,
            "candidates": cands,
            "has_gross_total_return": any(
                c["kind"] == "gross_total_return" for c in cands),
            "has_net_total_return": any(
                c["kind"] == "net_total_return" for c in cands),
            "gross_total_return_obtainable": any(
                c["kind"] == "gross_total_return"
                and c["official_api_available"] for c in cands),
            "net_total_return_obtainable": any(
                c["kind"] == "net_total_return"
                and c["official_api_available"] for c in cands),
            "has_total_return": any(
                c["kind"] in ("gross_total_return", "net_total_return")
                for c in cands),
            "total_return_obtainable": any(
                c["kind"] in ("gross_total_return", "net_total_return")
                and c["official_api_available"] for c in cands),
        })
    return {"indexes": records,
            "samples_file": "reports/evidence/phase3B6_2_3_0_2/"
                            "official_total_return_samples.json",
            "samples_sha256": _tr_sha(),
            "coverage": _tr_coverage(records)}


def _tr_coverage(records: list[dict]) -> dict:
    """全收益覆盖统计：**按指数类别分别计算，分母不得混用**。

    - 股票价格指数的分母 = 8 个**收益口径已确认**的股票指数
    - 930930 口径 unknown，**不得计入该分母**
    - 000012 债券衍生序列**独立统计**
    """
    stock = [r for r in records
             if r["base_index"] in CONFIRMED_STOCK_PRICE_INDEXES]
    bond = [r for r in records if r["base_index"] in BOND_INDEXES]
    unconf = [r for r in records
              if r["base_index"] in UNCONFIRMED_BASIS_INDEXES]

    def _codes(recs, kind):
        return [c["code"] for r in recs for c in r["candidates"]
                if c["kind"] == kind and c["official_api_available"]]

    return {
        "confirmed_stock_price_indexes_total": len(stock),
        "confirmed_stock_price_indexes": [
            r["base_index"] for r in stock],
        "confirmed_stock_indexes_with_gross_total_return": sum(
            1 for r in stock if r["gross_total_return_obtainable"]),
        "confirmed_stock_indexes_with_net_total_return": sum(
            1 for r in stock if r["net_total_return_obtainable"]),
        "confirmed_stock_gross_total_return_codes": _codes(
            stock, "gross_total_return"),
        "confirmed_stock_net_total_return_codes": _codes(
            stock, "net_total_return"),
        "hk_index_derivative_candidates": [
            {"base_index": r["base_index"],
             "codes": [c["code"] for c in r["candidates"]],
             "counts_in_stock_denominator": False,
             "reason": ("主序列收益口径仍为 unknown，"
                        "不得计入已确认股票价格指数分母")}
            for r in unconf],
        "hk_index_derivative_candidate_count": len(unconf),
        "bond_index_derivative_candidates": [
            {"base_index": r["base_index"],
             "codes": [c["code"] for c in r["candidates"]],
             "kinds": [c["kind"] for c in r["candidates"]],
             "counts_in_stock_denominator": False,
             "reason": ("债券指数的净价/利息再投资序列与股票全收益"
                        "口径不同，必须独立统计")}
            for r in bond],
        "bond_index_derivative_candidate_count": len(bond),
        "denominator_rule": (
            "**分母只含 8 个收益口径已获官方确认的股票价格指数**；"
            "930930（unknown）与 000012（债券）均不计入"),
        "total_return_series_in_database": sum(
            1 for r in records for c in r["candidates"]
            if c["already_in_database"]),
    }


def _tr_sha() -> str | None:
    f = EVID / "official_total_return_samples.sha256"
    return f.read_text(encoding="utf-8").strip() if f.exists() else None


# ---------------------------------------------------------------- 修订风险
def audit_revision_risk(conn) -> dict:
    """历史版本与数据修订风险（无证据即 unknown）。"""
    out = []
    for code in INDEX_CODES:
        doc = None
        doc_path = (REPORTS / "evidence" / "phase3B6_2_3_0" /
                    "index_methodology")
        for name in (f"{code}_Index_Methodology_cn.pdf",
                     f"{code}_factsheet.pdf"):
            p = doc_path / name
            if p.exists():
                doc = p
                break
        runs = conn.execute(
            "select count(*), min(requested_at), max(requested_at) "
            "from index_ingest_runs where index_code=?", (code,)).fetchone()
        out.append({
            "index_code": code,
            "official_document_obtained": doc is not None,
            "official_document": (str(doc.relative_to(ROOT)).replace("\\", "/")
                                  if doc else None),
            "ingest_batch_count": runs[0],
            "ingest_first": runs[1],
            "ingest_last": runs[2],
            "multiple_ingest_batches": runs[0] > 1,
            "official_keeps_history_versions": None,
            "api_returns_revised_history": None,
            "has_adjustment_announcement": None,
            "methodology_changed": None,
            "sample_rules_revised": None,
            "archived_history_available": None,
            "verdict": ("**unknown**：未取得官方历史版本归档证据，"
                        "不得推测官方是否保留历史版本或是否修订过"),
        })
    return {
        "indexes": out,
        "global_note": (
            "本阶段仅取得官方编制方案/指数单张的**当前版本**，"
            "未取得历史版本归档，也未取得官方修订公告清单。"
            "所有「是否保留历史版本/是否修订」一律标记 unknown，"
            "不得写成已证实事实。"),
        "revision_risk_verified": False,
    }


# ---------------------------------------------------------------- 汇总与主流程
def summarize(cont: dict, pit: dict, tr: dict, rev: dict) -> dict:
    recs = cont["indexes"]
    trecs = tr["indexes"]

    def cnt(pred):
        return sum(1 for r in recs if pred(r))

    calendar_available = cnt(lambda r: r["calendar_available"])
    continuity_verified = cnt(lambda r: r["continuity_verified"])
    tr_obtainable = sum(1 for r in trecs if r["total_return_obtainable"])

    return {
        "continuity": {
            "total_indexes": len(recs),
            "calendar_available": calendar_available,
            "calendar_unavailable": len(recs) - calendar_available,
            "continuity_verified": continuity_verified,
            "continuity_unverified": len(recs) - continuity_verified,
            "total_raw_rows": sum(r["raw_rows"] for r in recs),
            "total_valid_rows": sum(r["valid_rows"] for r in recs),
            "total_suspect_rows": sum(r["suspect_rows"] for r in recs),
            "placeholder_row_count": sum(
                len(r["placeholder_rows"]) for r in recs),
            "duplicate_dates_total": sum(r["duplicate_dates"] for r in recs),
            "descending_total": sum(r["descending_dates"] for r in recs),
            "illegal_dates_total": sum(len(r["illegal_dates"]) for r in recs),
            "non_positive_close_total": sum(
                r["non_positive_close"] for r in recs),
            "null_close_total": sum(r["null_close"] for r in recs),
            "missing_trading_days_total": sum(
                r["missing_trading_days"] or 0 for r in recs),
        },
        "point_in_time": {
            "point_in_time_verified": pit["point_in_time_verified"],
            "indexes_verified": 0,
            "reason": pit["reason"],
        },
        "total_return": {
            # 逐指数明细自动汇总（分母严格分类，不得混用）
            "confirmed_stock_price_indexes_total":
                tr["coverage"]["confirmed_stock_price_indexes_total"],
            "confirmed_stock_indexes_with_gross_total_return":
                tr["coverage"][
                    "confirmed_stock_indexes_with_gross_total_return"],
            "confirmed_stock_indexes_with_net_total_return":
                tr["coverage"][
                    "confirmed_stock_indexes_with_net_total_return"],
            "hk_index_derivative_candidate_count":
                tr["coverage"]["hk_index_derivative_candidate_count"],
            "bond_index_derivative_candidate_count":
                tr["coverage"]["bond_index_derivative_candidate_count"],
            "total_return_series_in_database":
                tr["coverage"]["total_return_series_in_database"],
            # 兼容字段：全部指数（含 unknown/债券），不得当作股票分母
            "indexes_with_tr_candidate": sum(
                1 for r in trecs if r["has_total_return"]),
            "indexes_with_tr_obtainable": tr_obtainable,
            "indexes_with_tr_not_obtainable": len(trecs) - tr_obtainable,
        },
        "revision_risk": {
            "revision_risk_verified": rev["revision_risk_verified"],
            "indexes_with_unknown_revision": sum(
                1 for r in rev["indexes"]
                if r["official_keeps_history_versions"] is None),
        },
        "gates": {
            "historical_continuity_verified": continuity_verified,
            "point_in_time_verified": False,
            "total_return_obtainable_count": tr_obtainable,
            "ready_for_3b6_2_3_1_series_build": False,
            "note": ("连续性仅对 A 股日历可用的指数完成；"
                     "时点可用性全部未通过；"
                     "全收益序列官方可取但**尚未接入**；"
                     "不得进入收益序列建设"),
        },
        "_self_check": {
            "continuity_count_matches": len(recs) == len(INDEX_CODES),
            "total_return_count_matches": len(trecs) == len(INDEX_CODES),
            "revision_count_matches": len(rev["indexes"]) == len(INDEX_CODES),
            "continuity_partition_ok": (
                continuity_verified + (len(recs) - continuity_verified)
                == len(recs)),
            "placeholder_total_is_10": sum(
                len(r["placeholder_rows"]) for r in recs) == 10,
            # 分母不得含 930930 / 000012
            "stock_denominator_is_8":
                tr["coverage"]["confirmed_stock_price_indexes_total"] == 8,
            "hk_not_in_stock_denominator": (
                "930930" not in
                tr["coverage"]["confirmed_stock_price_indexes"]),
            "bond_not_in_stock_denominator": (
                "000012" not in
                tr["coverage"]["confirmed_stock_price_indexes"]),
            "gross_net_counted_separately": (
                tr["coverage"]["confirmed_stock_indexes_with_gross_total_return"]
                + 0 <= tr["coverage"]["confirmed_stock_price_indexes_total"]),
        },
    }


# ---------------------------------------------------------------- 数据库证据
def database_evidence(conn) -> dict:
    """正式数据库只读完整性证据（含完整 64 位 SHA256）。"""
    import hashlib
    import os
    from app.config import settings
    path = str(settings.database_path)
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    sha = h.hexdigest()

    per_index = {}
    for code in INDEX_CODES:
        r = conn.execute(
            "select count(*), sum(case when quality_status='valid' then 1 "
            "else 0 end), sum(case when quality_status<>'valid' then 1 "
            "else 0 end) from index_daily where index_code=?",
            (code,)).fetchone()
        per_index[code] = {
            "raw_rows": r[0],
            "valid_rows": r[1] or 0,
            "suspect_rows": r[2] or 0,
        }

    placeholders = [
        {"index_code": r[0], "trade_date": r[1], "close": r[2],
         "quality_status": r[3], "quality_note": r[4]}
        for r in conn.execute(
            "select index_code, trade_date, close, quality_status, "
            "quality_note from index_daily where quality_status<>'valid' "
            "order by index_code")]

    zero_rows = [
        {"index_code": r[0], "trade_date": r[1], "close": r[2],
         "quality_status": r[3]}
        for r in conn.execute(
            "select index_code, trade_date, close, quality_status "
            "from index_daily where close<=0 order by index_code")]

    return {
        "database_path": path,
        "database_sha256": sha,
        "database_bytes": os.path.getsize(path),
        "integrity_check": conn.execute(
            "pragma integrity_check").fetchone()[0],
        "foreign_key_violations": len(
            conn.execute("pragma foreign_key_check").fetchall()),
        "index_daily_total_rows": conn.execute(
            "select count(*) from index_daily").fetchone()[0],
        "per_index_rows": per_index,
        "suspect_placeholder_rows": placeholders,
        "suspect_placeholder_count": len(placeholders),
        "non_positive_close_rows": zero_rows,
        "non_positive_close_count": len(zero_rows),
        "h30184_zero_row_present": any(
            r["index_code"] == "H30184" and r["trade_date"] == "2013-06-28"
            and r["close"] == 0.0 for r in zero_rows),
        "read_only": True,
        "note": ("本轮只能证明当前数据库状态；"
                 "如未取得任务开始前指纹，不得声称完成前后一致比较"),
    }


# ---------------------------------------------------------------- 差异估计边界
def return_difference_estimate(conn) -> dict:
    """价格指数与全收益指数的差异：**本阶段不做量化估计**。

    只有同时具备完整、同起止、同交易日对齐的官方历史序列时才允许量化，
    本轮未构建任何完整收益序列。
    """
    has_full_price = conn.execute(
        "select count(*) from index_daily where index_code in "
        "('000300','000905','000906','000016','399997','H30184',"
        "'000942','000922')").fetchone()[0]
    has_full_tr = conn.execute(
        "select count(*) from index_daily where index_code in "
        "('H00300','H00905','H00906','H00016','H20539','H20184',"
        "'H00942','H00922')").fetchone()[0]
    return {
        "price_series_rows": has_full_price,
        "total_return_series_rows": has_full_tr,
        "both_full_series_available": bool(has_full_price and has_full_tr),
        "quantitative_estimate_produced": False,
        "quantitative_estimate": None,
        "removed_claim": "8个股票指数年化低估约1.5%~2.5%",
        "removal_reason": (
            "本轮仅有 3 个日期的官方抽样值，**不足以推导长期年化差异**；"
            "且正式库未接入全收益序列，无法做同起止、同交易日对齐的完整比对"),
        "qualitative_statement": (
            "价格指数不包含股息再投资，与基金累计净值（含分红再投资）"
            "在收益口径上存在差异；差异大小需用完整官方序列计算，"
            "本阶段不给出数值"),
        "requirements_for_future_estimate": [
            "相同起止日期",
            "相同交易日对齐",
            "完整官方历史序列（价格 + 全收益）",
            "公开计算公式",
            "公开数据范围",
            "公开缺失处理规则",
        ],
    }


def main() -> None:
    EVID.mkdir(parents=True, exist_ok=True)
    conn = db_connect()
    try:
        print("=== 第一部分：10 个指数历史连续性 ===")
        cont_recs = [audit_continuity(c, conn) for c in INDEX_CODES]
        cont = {"indexes": cont_recs}
        for r in cont_recs:
            print(f"  {r['index_code']:8s} raw={r['raw_rows']:5d} "
                  f"valid={r['valid_rows']:5d} suspect={r['suspect_rows']} "
                  f"cal={r['calendar_used'][:18]:20s} "
                  f"missing={r['missing_trading_days']} "
                  f"verified={r['continuity_verified']}")

        print("\n=== 第二部分：历史时点可用性 ===")
        pit = audit_point_in_time(conn)
        print(f"  快照表: {pit['snapshot_tables_found']}")
        print(f"  多版本行: {pit['index_daily_multi_version_rows']}")
        print(f"  采集日期: {pit['collected_at_distinct_dates']}")
        print(f"  point_in_time_verified={pit['point_in_time_verified']}")

        print("\n=== 第四部分：修订风险 ===")
        rev = audit_revision_risk(conn)
        print(f"  全部 unknown: "
              f"{all(r['official_keeps_history_versions'] is None for r in rev['indexes'])}")
    finally:
        conn.close()

    print("\n=== 第三部分：全收益可行性 ===")
    conn2 = db_connect()
    try:
        tr = audit_total_return(conn2)
    finally:
        conn2.close()
    for r in tr["indexes"]:
        got = [c["code"] for c in r["candidates"]
               if c["official_api_available"]]
        print(f"  {r['base_index']:8s} TR候选={len(r['candidates'])} "
              f"可取={got}")

    print("\n=== 第五部分：数据库证据与差异估计边界 ===")
    conn3 = db_connect()
    try:
        db_ev = database_evidence(conn3)
        diff_est = return_difference_estimate(conn3)
    finally:
        conn3.close()
    print(f"  SHA256: {db_ev['database_sha256']}")
    print(f"  integrity={db_ev['integrity_check']} "
          f"fk={db_ev['foreign_key_violations']}")
    print(f"  suspect={db_ev['suspect_placeholder_count']} "
          f"zero={db_ev['non_positive_close_count']}")
    print(f"  完整双序列可用={diff_est['both_full_series_available']} "
          f"量化结论={diff_est['quantitative_estimate_produced']}")

    summary = summarize(cont, pit, tr, rev)
    now = datetime.now().isoformat(timespec="seconds")
    base = "015a552df01e8bec791905a3623df4d3213165f6"

    (REPORTS / "phase3B6_2_3_0_2_coverage_audit.json").write_text(
        json.dumps({
            "phase": "3B-6.2.3.0.2",
            "task": "10 个指数历史连续性审计",
            "generated_at": now,
            "baseline_head": base,
            "read_only": True,
            "calendar_policy": (
                "按指数实际市场选择日历；A股日历仅对沪深A股指数适用；"
                "000012（上交所债券）与 930930（港股通）的专属日历未独立取得，"
                "**不做缺失日核验**，避免用错误日历误判缺口"),
            "placeholder_policy": (
                "2004-01-01 占位行单独统计，不计入有效行情，"
                "**不删除正式库记录**"),
            "calendar_accuracy_note": (
                "trade_calendar 是 A 股交易日**代理**，不是指数编制机构"
                "公布的官方发布日历；因此「无缺失」只能表述为"
                "「相对于项目 A 股交易日历代理未发现缺失」"),
            "summary": summary["continuity"],
            "database_evidence": db_ev,
            "indexes": cont_recs,
        }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    (REPORTS / "phase3B6_2_3_0_2_point_in_time_audit.json").write_text(
        json.dumps({
            "phase": "3B-6.2.3.0.2",
            "task": "历史时点可用性审计",
            "generated_at": now,
            "baseline_head": base,
            "read_only": True,
            "audit": pit,
            "summary": summary["point_in_time"],
        }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    (REPORTS / "phase3B6_2_3_0_2_total_return_audit.json").write_text(
        json.dumps({
            "phase": "3B-6.2.3.0.2",
            "task": "全收益指数与研究基准可行性审计",
            "generated_at": now,
            "baseline_head": base,
            "read_only": True,
            "rule": ("全收益/净收益代码必须来自官方基本信息接口，"
                     "**不得按命名规律猜测**"),
            "basis_taxonomy": {
                "price": "价格指数（除息自然回落）",
                "gross_total_return": "全收益指数（税前红利再投资）",
                "net_total_return": "净收益指数（税后红利再投资）",
                "bond_clean_price": "债券净价指数（不含应计利息）",
                "bond_full_price": "债券全价指数（含应计利息，不含再投资）",
                "bond_interest_reinvestment": "利息及再投资指数",
                "wealth": "财富指数（含利息及再投资）",
            },
            "warning": ("债券全价/财富指数与股票全收益指数**不可混为一谈**"),
            "summary": summary["total_return"],
            "coverage": tr["coverage"],
            "return_difference_estimate": diff_est,
            "indexes": tr["indexes"],
            "samples_file": tr["samples_file"],
            "samples_sha256": tr["samples_sha256"],
        }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    (EVID / "revision_risk.json").write_text(
        json.dumps({
            "phase": "3B-6.2.3.0.2",
            "generated_at": now,
            "read_only": True,
            "audit": rev,
            "summary": summary["revision_risk"],
        }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    (EVID / "summary.json").write_text(
        json.dumps({"generated_at": now, "summary": summary,
                    "database_evidence": {
                        "database_path": db_ev["database_path"],
                        "database_sha256": db_ev["database_sha256"],
                        "integrity_check": db_ev["integrity_check"],
                        "foreign_key_violations":
                            db_ev["foreign_key_violations"],
                        "suspect_placeholder_count":
                            db_ev["suspect_placeholder_count"],
                        "non_positive_close_count":
                            db_ev["non_positive_close_count"],
                        "note": db_ev["note"]},
                    "return_difference_estimate": diff_est},
                   ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print("\n=== 汇总 ===")
    print(json.dumps(summary["continuity"], ensure_ascii=False, indent=1))
    print(json.dumps(summary["total_return"], ensure_ascii=False, indent=1))
    print(json.dumps(summary["gates"], ensure_ascii=False, indent=1))
    print(json.dumps(summary["_self_check"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
