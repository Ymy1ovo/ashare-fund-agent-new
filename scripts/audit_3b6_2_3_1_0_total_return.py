"""阶段3B-6.2.3.1.0 官方全收益指数历史序列可行性审计。

**严格只读**：不写正式数据库、不建正式收益序列、不开放回测。

审计三类指数（**不得混为一个统计集合**）：

- 股票全收益候选（8 个价格指数对应的 H 系列 / N 系列）
- 债券指数（000012 及其衍生）
- 港股指数（930930 及其衍生）

九个验证维度严格分开，不得互相替代：

1. official_identity_verified     官方身份
2. mapping_to_price_index_verified 原指数映射
3. return_basis_verified          收益口径
4. history_api_available          历史接口可用性
5. history_coverage_verified      历史覆盖率
6. data_quality_verified          数据质量
7. continuity_verified            历史连续性
8. point_in_time_available        历史时点可用性
9. formal_series_admitted         正式基准序列准入
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORTS = ROOT / "reports"
EVID = REPORTS / "evidence" / "phase3B6_2_3_1_0"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
CSI_BASIC = "https://www.csindex.com.cn/csindex-home/indexInfo/index-basic-info/"
CSI_PERF = ("https://www.csindex.com.cn/csindex-home/perf/index-perf"
            "?indexCode={code}&startDate={start}&endDate={end}")

# 8 个股票价格指数（收益口径已确认）及其全收益候选
STOCK_PRICE_INDEXES = ["000300", "000905", "000906", "000016",
                       "399997", "H30184", "000942", "000922"]

STOCK_TR_CANDIDATES = {
    "000300": ["H00300"],
    "000905": ["H00905"],
    "000906": ["H00906"],
    "000016": ["H00016"],
    "399997": ["H20539", "399997CNY02"],
    "H30184": ["H20184"],
    "000942": ["H00942"],
    "000922": ["H00922"],
}

# 债券指数（独立统计，不得混入股票集合）
BOND_INDEXES = {"000012": ["H00012", "N00012"]}
# 港股指数（口径 unknown，独立处理）
HK_INDEXES = {"930930": ["H20930"]}

AUDIT_START = "20040101"
AUDIT_END = "20261127"


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


def _get(url: str, *, timeout: int = 90, retries: int = 4) -> bytes:
    import time
    last = None
    for i in range(retries + 1):
        if i:
            time.sleep(3.0 * i)
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA,
                              "Referer": "https://www.csindex.com.cn/"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as exc:
            last = exc
    raise last  # type: ignore[misc]


def _save(name: str, raw: bytes, url: str) -> dict:
    EVID.mkdir(parents=True, exist_ok=True)
    f = EVID / name
    f.write_bytes(raw)
    return {
        "file": str(f.relative_to(ROOT)).replace("\\", "/"),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "url": url,
        "obtained_at": datetime.now().isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------- 官方身份
def fetch_basic(code: str) -> dict:
    url = CSI_BASIC + code
    try:
        raw = _get(url, timeout=45)
    except Exception as exc:
        return {"index_code": code, "url": url, "obtained": False,
                "error": f"{type(exc).__name__}"}
    meta = _save(f"basic_{code}.json", raw, url)
    try:
        data = json.loads(raw.decode("utf-8")).get("data") or {}
    except Exception:
        data = {}
    return {
        "index_code": code, "url": url, "obtained": bool(data),
        **meta,
        "official_full_name": data.get("indexFullNameCn"),
        "official_short_name": data.get("indexShortNameCn"),
        "basic_date": data.get("basicDate"),
        "basic_index": data.get("basicIndex"),
        "publish_date": data.get("publishDate"),
        "index_type": data.get("indexType"),
        "currency": data.get("currencyCn"),
        "publisher": "中证指数有限公司",
    }


def fetch_history(code: str, start: str = AUDIT_START,
                  end: str = AUDIT_END) -> dict:
    url = CSI_PERF.format(code=code, start=start, end=end)
    try:
        raw = _get(url, timeout=120)
    except Exception as exc:
        return {"index_code": code, "url": url, "obtained": False,
                "error": f"{type(exc).__name__}"}
    meta = _save(f"hist_{code}_{start}_{end}.json", raw, url)
    try:
        rows = json.loads(raw.decode("utf-8")).get("data") or []
    except Exception:
        rows = []
    return {"index_code": code, "url": url, "obtained": bool(rows),
            **meta, "rows": rows, "row_count": len(rows)}


# ---------------------------------------------------------------- 质量审计
def _real_history_start(dates: list[str]) -> str | None:
    """识别真实历史起点：跳过首行合成行与基日前的空档。

    规则：若首行与后续行间隔 > 60 天，则首行为合成/占位行，
    真实起点为间隔后的第一行。
    """
    import datetime as dt
    if not dates:
        return None
    if len(dates) == 1:
        return dates[0]
    for i in range(1, len(dates)):
        a = dt.datetime.strptime(dates[i - 1], "%Y%m%d")
        b = dt.datetime.strptime(dates[i], "%Y%m%d")
        if (b - a).days > 60:
            return dates[i]
    return dates[0]


def audit_quality(code: str, rows: list[dict], cal: set[str]) -> dict:
    """逐序列数据质量审计（不修改任何数据）。"""
    import math
    dates = [r.get("tradeDate") for r in rows]
    closes = [r.get("close") for r in rows]

    def _num(v):
        try:
            f = float(v)
            return f
        except (TypeError, ValueError):
            return None

    numeric = [_num(c) for c in closes]
    non_numeric = [d for d, v in zip(dates, numeric) if v is None]
    nan_inf = [d for d, c in zip(dates, closes)
               if isinstance(c, float) and (math.isnan(c) or math.isinf(c))]
    non_positive = [d for d, v in zip(dates, numeric)
                    if v is not None and v <= 0]
    nulls = [d for d, c in zip(dates, closes) if c is None]
    dup = len(dates) - len(set(dates))
    desc = sum(1 for i in range(1, len(dates)) if dates[i] < dates[i - 1])
    illegal = []
    import datetime as dt
    for d in dates:
        try:
            if d:
                dt.datetime.strptime(str(d), "%Y%m%d")
        except Exception:
            illegal.append(d)

    # 极端异常值：相邻日收益绝对值 > 50%（指数层面极少见）
    extreme = []
    prev = None
    for d, v in zip(dates, numeric):
        if v is None or v <= 0:
            continue
        if prev is not None:
            chg = abs(v / prev - 1.0)
            if chg > 0.5:
                extreme.append({"date": d, "close": v,
                                "prev": prev, "chg": round(chg, 6)})
        prev = v

    # 交易日历核验（A 股代理）
    # **只从真实起点开始核验**：官方接口会在首行合成「请求起始日」，
    # 且全收益指数的历史回溯起点是基日（如 2004-12-31），
    # 首行 20040101 与真实起点之间的空档**不是数据缺失**。
    real_start = _real_history_start(dates)
    real_dates = [d for d in dates if d >= real_start] if real_start else dates
    iso = [f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in real_dates if d]
    if iso:
        lo, hi = min(iso), max(iso)
        cal_window = {d for d in cal if lo <= d <= hi} if cal else set()
        missing = sorted(cal_window - set(iso))
    else:
        cal_window = set()
        missing = []
    outside = sorted(set(iso) - cal) if cal else []
    # 首行合成行单独标记（不计入缺失）
    synthetic_first = (
        dates[0] if dates and real_start and dates[0] < real_start else None)

    return {
        "real_history_start": real_start,
        "synthetic_first_row": synthetic_first,
        "calendar_window_days": len(cal_window),
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "row_count": len(rows),
        "distinct_dates": len(set(dates)),
        "duplicate_dates": dup,
        "descending_dates": desc,
        "illegal_dates": illegal[:10],
        "null_close": len(nulls),
        "non_numeric_close": len(non_numeric),
        "nan_or_inf_close": len(nan_inf),
        "non_positive_close": len(non_positive),
        "non_positive_sample": non_positive[:5],
        "extreme_moves": extreme[:10],
        "extreme_move_count": len(extreme),
        "missing_trading_days": len(missing),
        "missing_sample": missing[:10],
        "dates_outside_calendar": len(outside),
        "dates_outside_calendar_sample": outside[:10],
        "calendar_source": ("项目 trade_calendar（A股交易日**代理**，"
                            "非官方指数发布日历）"),
    }


# ---------------------------------------------------------------- 映射与数值关系
def verify_mapping(price_code: str, tr_code: str, tr_basic: dict,
                   price_rows: list[dict], tr_rows: list[dict]) -> dict:
    """验证全收益候选是否真的对应原价格指数。

    **不能仅凭代码相似或名称相似判定映射成立。**
    """
    checks = []

    # 1) 名称包含关系（弱证据）
    tr_name = tr_basic.get("official_full_name") or ""
    name_has_tr = ("全收益" in tr_name) or ("净收益" in tr_name)
    checks.append({
        "check": "候选名称含「全收益/净收益」",
        "passed": name_has_tr,
        "value": tr_name,
        "strength": "弱（名称相似不足以判定映射）",
    })

    # 2) 基日一致（中强证据，由调用方注入 price_basic 后判定）
    checks.append({"check": "基日一致", "passed": None,
                   "strength": "中", "value": None})

    # 3) 数值关系：全收益应长期高于价格指数，且比值单调性合理
    pm = {r["tradeDate"]: r.get("close") for r in price_rows}
    tr_dates = [r["tradeDate"] for r in tr_rows]
    real_start = _real_history_start(tr_dates) if tr_dates else None
    ratios = []
    for r in tr_rows:
        d = r["tradeDate"]
        # 排除首行合成行（其数值是人为填充，不代表真实口径关系）
        if real_start and d < real_start:
            continue
        tc = r.get("close")
        pc = pm.get(d)
        if tc and pc and float(pc) > 0 and float(tc) > 0:
            ratios.append((d, float(tc) / float(pc)))
    ratio_first = ratios[0][1] if ratios else None
    ratio_last = ratios[-1][1] if ratios else None
    # **基日当天比值必然等于 1**（两者同基点），故判据为「>= 1」而非「> 1」
    all_at_least_one = all(x[1] >= 1.0 - 1e-9 for x in ratios) if ratios else None
    monotonic_up = (ratio_last > ratio_first) if (ratio_first and ratio_last) else None
    # 早期比值恰为 1 的区间（重要事实：早期未体现分红再投资）
    ratio_eq_one = [d for d, v in ratios if abs(v - 1.0) < 1e-9]

    checks.append({
        "check": "全收益/价格比值恒 >= 1（基日当天必然 =1）",
        "passed": all_at_least_one,
        "value": {"ratio_first": ratio_first, "ratio_last": ratio_last,
                  "sample_count": len(ratios),
                  "ratio_equals_one_count": len(ratio_eq_one)},
        "strength": "中（符合分红再投资特征，但不能证明口径）",
    })
    checks.append({
        "check": "比值随时间上升（再投资累积）",
        "passed": monotonic_up,
        "value": {"ratio_first": ratio_first, "ratio_last": ratio_last},
        "strength": "中",
    })

    return {
        "price_index": price_code,
        "tr_candidate": tr_code,
        "checks": checks,
        "ratio_first": ratio_first,
        "ratio_last": ratio_last,
        "ratio_sample_count": len(ratios),
        "all_ratios_at_least_one": all_at_least_one,
        "ratio_increasing": monotonic_up,
        "ratio_equals_one_dates": ratio_eq_one[:10],
        "ratio_equals_one_count": len(ratio_eq_one),
        "note": ("比值恒 >= 1 且随时间上升，符合「分红再投资累积」特征；"
                 "但这是**技术判断**，不能替代官方口径文件。"
                 "**早期比值恰为 1 说明该段未体现分红再投资**，"
                 "需在正式使用时注意"),
    }


def sample_ratio_across_years(price_rows: list[dict],
                              tr_rows: list[dict]) -> list[dict]:
    """选取多个不同年份的实际样本比对（不得只比最新几天）。"""
    pm = {r["tradeDate"]: r.get("close") for r in price_rows}
    out = []
    seen_years = set()
    for r in tr_rows:
        d = r["tradeDate"]
        y = d[:4]
        if y in seen_years:
            continue
        tc = r.get("close")
        pc = pm.get(d)
        if not tc or not pc:
            continue
        seen_years.add(y)
        out.append({
            "date": d,
            "price_close": float(pc),
            "tr_close": float(tc),
            "ratio": round(float(tc) / float(pc), 6),
        })
    return out


# ---------------------------------------------------------------- 时点可用性
def audit_point_in_time(conn) -> dict:
    """历史时点可用性审计（复用库内事实，不重复猜测）。"""
    import sqlite3
    tabs = {r[0] for r in conn.execute(
        "select name from sqlite_master where type='table'")}
    idx_snapshot = [t for t in tabs
                    if "index" in t.lower()
                    and any(k in t.lower()
                            for k in ("snapshot", "version", "history"))]
    multi = conn.execute("""
        select count(*) from (
            select index_code, trade_date, count(*) c from index_daily
            group by index_code, trade_date having c > 1)""").fetchone()[0]
    collected = [r[0] for r in conn.execute(
        "select distinct substr(collected_at,1,10) from index_daily "
        "order by 1")]
    return {
        "index_snapshot_tables": idx_snapshot,
        "index_daily_multi_version_rows": multi,
        "collected_at_distinct_dates": collected,
        "has_historical_snapshot": bool(idx_snapshot),
        "has_revision_records": multi > 0,
        "can_prove_published_at_the_time": False,
        "historical_point_in_time_availability": "unknown",
        "reason": (
            "无历史快照表、无修订记录、每 (index_code,trade_date) 仅 1 行；"
            "当前采集时间与当前下载数据**不能证明**历史交易日当时已公开；"
            "无法排除事后回溯计算"),
        "note": ("该结论适用于本轮全部候选序列（含股票/债券/港股），"
                 "不因序列类型不同而改变"),
    }


# ---------------------------------------------------------------- 逐候选审计
def audit_candidate(tr_code: str, price_code: str, *, conn, cal: set[str],
                    price_cache: dict, basic_cache: dict,
                    hist_cache: dict) -> dict:
    """单个候选序列的九维审计。"""
    if price_code not in price_cache:
        price_cache[price_code] = fetch_history(price_code)
    if price_code not in basic_cache:
        basic_cache[price_code] = fetch_basic(price_code)
    if tr_code not in hist_cache:
        hist_cache[tr_code] = fetch_history(tr_code)
    if tr_code not in basic_cache:
        basic_cache[tr_code] = fetch_basic(tr_code)

    price_hist = price_cache[price_code]
    price_basic = basic_cache[price_code]
    tr_hist = hist_cache[tr_code]
    tr_basic = basic_cache[tr_code]

    q = audit_quality(tr_code, tr_hist.get("rows") or [], cal)
    mapping = verify_mapping(price_code, tr_code, tr_basic,
                             price_hist.get("rows") or [],
                             tr_hist.get("rows") or [])
    samples = sample_ratio_across_years(
        price_hist.get("rows") or [], tr_hist.get("rows") or [])

    # 1) 官方身份
    identity_ok = bool(tr_basic.get("obtained")
                       and tr_basic.get("official_full_name")
                       and tr_basic.get("basic_date")
                       and tr_basic.get("publish_date"))
    # 2) 映射
    base_date_match = (tr_basic.get("basic_date")
                       == price_basic.get("basic_date"))
    mapping_ok = bool(base_date_match
                      and mapping["all_ratios_at_least_one"]
                      and mapping["ratio_increasing"])
    # 3) 收益口径：官方名称是否明确含全收益/净收益
    tr_name = tr_basic.get("official_full_name") or ""
    if "全收益" in tr_name:
        basis = "gross_total_return"
        basis_ok = True
    elif "净收益" in tr_name:
        basis = "net_total_return"
        basis_ok = True
    else:
        basis = "unknown"
        basis_ok = False
    # 4) 历史接口
    api_ok = bool(tr_hist.get("obtained") and tr_hist.get("row_count", 0) > 100)
    # 5) 覆盖率
    coverage_ok = bool(api_ok and q["missing_trading_days"] == 0)
    # 6) 数据质量
    quality_ok = bool(q["duplicate_dates"] == 0 and q["descending_dates"] == 0
                      and not q["illegal_dates"]
                      and q["non_numeric_close"] == 0
                      and q["nan_or_inf_close"] == 0
                      and q["non_positive_close"] == 0
                      and q["null_close"] == 0)
    # 7) 连续性
    continuity_ok = bool(coverage_ok and q["dates_outside_calendar"] == 0)
    # 8) 时点可用性
    pit = audit_point_in_time(conn)
    pit_ok = pit["historical_point_in_time_availability"] == "verified"
    # 9) 正式准入：必须全部通过
    admitted = bool(identity_ok and mapping_ok and basis_ok and api_ok
                    and coverage_ok and quality_ok and continuity_ok
                    and pit_ok)

    dims = {
        "official_identity_verified": identity_ok,
        "mapping_to_price_index_verified": mapping_ok,
        "return_basis_verified": basis_ok,
        "history_api_available": api_ok,
        "history_coverage_verified": coverage_ok,
        "data_quality_verified": quality_ok,
        "continuity_verified": continuity_ok,
        "point_in_time_available": pit_ok,
        "formal_series_admitted": admitted,
    }
    passed = sum(1 for v in dims.values() if v)
    grade = ("L1" if identity_ok and basis_ok and api_ok else
             "L2" if identity_ok else "L3")

    return {
        "tr_candidate": tr_code,
        "price_index": price_code,
        "tr_basic": tr_basic,
        "price_basic": price_basic,
        "tr_history_meta": {k: v for k, v in tr_hist.items()
                            if k != "rows"},
        "price_history_meta": {k: v for k, v in price_hist.items()
                               if k != "rows"},
        "quality": q,
        "mapping": mapping,
        "cross_year_samples": samples,
        "return_basis": basis,
        "dimensions": dims,
        "dimensions_passed": passed,
        "dimensions_total": len(dims),
        "evidence_grade": grade,
        "blocking_dimensions": [k for k, v in dims.items() if not v],
        "point_in_time": pit,
        "conclusion": _candidate_conclusion(tr_code, price_code, dims, q,
                                            basis, grade),
    }


def _candidate_conclusion(tr, price, dims, q, basis, grade) -> str:
    failed = [k for k, v in dims.items() if not v]
    if not failed:
        return f"{tr} 全部九维通过，可进入下一阶段独立数据层建设"
    if failed == ["point_in_time_available", "formal_series_admitted"]:
        return (f"{tr}：官方身份/映射/口径/接口/覆盖/质量/连续性**全部通过**，"
                f"仅**历史时点可用性**为 unknown，"
                f"因此不能准入正式基准序列；"
                f"可进入下一阶段**独立数据层建设**（非正式序列）")
    return (f"{tr}：未通过维度 {failed}；"
            f"其中历史覆盖 {q['missing_trading_days']} 个交易日缺失，"
            f"日历外日期 {q['dates_outside_calendar']} 条")


# ---------------------------------------------------------------- 汇总与主流程
def build_manifest() -> dict:
    """证据清单：枚举本轮全部原始文件并计算 SHA256。"""
    items = {}
    if EVID.exists():
        for f in sorted(EVID.glob("*.json")):
            if f.name == "manifest.json":
                continue
            raw = f.read_bytes()
            items[f.name] = {
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
    doc = {
        "phase": "3B-6.2.3.1.0",
        "purpose": "官方全收益指数历史序列可行性审计原始证据",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "file_count": len(items),
        "files": items,
    }
    (EVID / "manifest.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return doc


def summarize(result: dict) -> dict:
    recs = result["candidates"]
    stock = [r for r in recs if r["group"] == "stock_total_return"]
    bond = [r for r in recs if r["group"] == "bond_derivative"]
    hk = [r for r in recs if r["group"] == "hk_derivative"]

    def cnt(rs, key):
        return sum(1 for r in rs if r["dimensions"].get(key) is True)

    dims = ["official_identity_verified", "mapping_to_price_index_verified",
            "return_basis_verified", "history_api_available",
            "history_coverage_verified", "data_quality_verified",
            "continuity_verified", "point_in_time_available",
            "formal_series_admitted"]

    def block(rs):
        return {
            "candidate_count": len(rs),
            **{d: cnt(rs, d) for d in dims},
            "evidence_grade_counts": _count_grades(rs),
        }

    grades = _count_grades(recs)
    return {
        "total_candidates": len(recs),
        "stock_total_return": block(stock),
        "bond_derivative": block(bond),
        "hk_derivative": block(hk),
        "stock_price_indexes_covered": len({
            r["price_index"] for r in stock}),
        "stock_price_indexes_expected": len(STOCK_PRICE_INDEXES),
        "evidence_grade_counts": grades,
        "admitted_count": cnt(recs, "formal_series_admitted"),
        "admissible_for_next_stage_data_layer": sum(
            1 for r in recs
            if r["dimensions"]["official_identity_verified"]
            and r["dimensions"]["history_api_available"]
            and r["dimensions"]["data_quality_verified"]),
        "gates": {
            "ready_for_research_analysis": True,
            "ready_for_backtest": False,
            "ready_for_formal_ranking": False,
            "ready_for_3b6_2_3_1_series_build": False,
            "note": ("本轮只做可行性审计；"
                     "不因审计完成而开放任何门禁"),
        },
        "_self_check": {
            "groups_disjoint": (
                len({r["group"] for r in recs}) == 3
                and not (set(id(r) for r in stock)
                         & set(id(r) for r in bond))),
            "all_eight_price_indexes_have_candidate": (
                len({r["price_index"] for r in stock})
                == len(STOCK_PRICE_INDEXES)),
            "every_candidate_has_conclusion": all(
                r["conclusion"] for r in recs),
            "every_candidate_has_grade": all(
                r["evidence_grade"] in ("L1", "L2", "L3")
                for r in recs),
            "no_candidate_admitted": cnt(recs, "formal_series_admitted") == 0,
            "point_in_time_all_unknown": cnt(recs, "point_in_time_available")
            == 0,
        },
    }


def _count_grades(rs: list[dict]) -> dict:
    out: dict = {}
    for r in rs:
        g = r["evidence_grade"]
        out[g] = out.get(g, 0) + 1
    return dict(sorted(out.items()))


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()

    EVID.mkdir(parents=True, exist_ok=True)
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
        print("=== 基线 ===")
        print(f"  db_sha256={before['database_sha256']}")
        print(f"  index_daily={before['index_daily_total']}")

        cal = {r[0] for r in conn.execute(
            "select trade_date from trade_calendar "
            "where trade_date between '2004-01-01' and '2026-11-27'")}
        print(f"  交易日历（A股代理）: {len(cal)} 天")

        print("\n=== 采集与审计 ===")
        candidates = []
        price_cache: dict = {}
        basic_cache: dict = {}
        hist_cache: dict = {}
        for group, mapping in (
                ("stock_total_return", STOCK_TR_CANDIDATES),
                ("bond_derivative", BOND_INDEXES),
                ("hk_derivative", HK_INDEXES)):
            for price_code, tr_codes in mapping.items():
                for tr in tr_codes:
                    r = audit_candidate(
                        tr, price_code, conn=conn, cal=cal,
                        price_cache=price_cache, basic_cache=basic_cache,
                        hist_cache=hist_cache)
                    r["group"] = group
                    candidates.append(r)
                    d = r["dimensions"]
                    print(f"  [{group[:6]}] {tr:14s}<-{price_code:8s} "
                          f"通过 {r['dimensions_passed']}/9 "
                          f"grade={r['evidence_grade']} "
                          f"rows={r['quality']['row_count']:5d} "
                          f"miss={r['quality']['missing_trading_days']:3d} "
                          f"out={r['quality']['dates_outside_calendar']:3d}")

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
        "phase": "3B-6.2.3.1.0",
        "task": "官方全收益指数历史序列可行性审计",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "baseline_head": "3ca4d733c753898e5778767a3a89a521ae7ef58d",
        "read_only": True,
        "groups": {
            "stock_total_return": "8 个收益口径已确认的股票价格指数的全收益候选",
            "bond_derivative": "债券指数衍生序列（独立统计）",
            "hk_derivative": "港股指数衍生序列（主口径 unknown，独立统计）",
        },
        "group_separation_rule": (
            "**不得把股票指数、债券指数、港股指数混为一个统计集合**"),
        "dimension_definitions": {
            "official_identity_verified": "官方代码/全称/基日/发布日齐全",
            "mapping_to_price_index_verified":
                "基日一致 + 全收益/价格比值恒>1 且随时间上升",
            "return_basis_verified": "官方名称明确含全收益/净收益",
            "history_api_available": "官方接口返回 >100 行完整历史",
            "history_coverage_verified": "相对 A 股日历代理无缺失交易日",
            "data_quality_verified":
                "无重复/倒序/非法日期/非数值/NaN/Inf/非正值/空值",
            "continuity_verified": "覆盖通过且无日历外日期",
            "point_in_time_available": "能证明历史交易日当时已公开（本轮均 unknown）",
            "formal_series_admitted": "以上八项全部通过",
        },
        "dimension_independence_note": (
            "**九维不得互相替代**：官方身份通过 ≠ 映射通过 ≠ 接口通过 "
            "≠ 质量通过 ≠ 连续性通过 ≠ 时点可用 ≠ 正式准入"),
        "calendar_source": ("项目 trade_calendar（A股交易日**代理**，"
                            "**不是**指数官方发布日历）"),
        "db_before": before,
        "db_after": after,
        "db_unchanged": before["database_sha256"] == after["database_sha256"],
        "candidates": candidates,
    }
    result["summary"] = summarize(result)
    result["evidence_manifest"] = build_manifest()

    (REPORTS / "phase3B6_2_3_1_0_audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")

    print("\n=== 汇总 ===")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=1))
    print(f"\n数据库未变: {result['db_unchanged']}")


if __name__ == "__main__":
    main()
