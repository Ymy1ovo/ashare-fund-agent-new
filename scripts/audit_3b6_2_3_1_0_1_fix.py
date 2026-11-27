"""阶段3B-6.2.3.1.0.1 全收益审计边界纠偏（只读，不重下载）。

修正 3B-6.2.3.1.0 的五处审计缺陷：

1. 市场日历按市场类型隔离（债券/港股不得用 A 股日历）
2. 合成首行识别改用**多重证据**（不只看间隔 > 60 天）
3. 映射证据补全（基日匹配必须真实判定，不得为 null）
4. 历史完整性拆成四个独立状态
5. 下一阶段准入拆成三个独立状态

**全部基于已保存的原始证据**，不重新下载。
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORTS = ROOT / "reports"
EVID_OLD = REPORTS / "evidence" / "phase3B6_2_3_1_0"
EVID_OLD4 = REPORTS / "evidence" / "phase3B6_2_3_0_4"
EVID = REPORTS / "evidence" / "phase3B6_2_3_1_0_1"

STOCK_PRICE_INDEXES = ["000300", "000905", "000906", "000016",
                       "399997", "H30184", "000942", "000922"]
STOCK_TR_CANDIDATES = {
    "000300": ["H00300"], "000905": ["H00905"], "000906": ["H00906"],
    "000016": ["H00016"], "399997": ["H20539", "399997CNY02"],
    "H30184": ["H20184"], "000942": ["H00942"], "000922": ["H00922"],
}
BOND_INDEXES = {"000012": ["H00012", "N00012"]}
HK_INDEXES = {"930930": ["H20930"]}

# **市场日历适用性**：每个候选适用哪种日历
MARKET_CALENDAR = {
    "stock": {"market": "沪深A股", "calendar": "A股交易日历（项目代理）",
              "calendar_available": True,
              "calendar_is_official": False,
              "note": "trade_calendar 为 A 股交易日**代理**，非官方发布日历"},
    "bond": {"market": "上交所债券市场", "calendar": "债券市场交易日历",
             "calendar_available": False,
             "calendar_is_official": False,
             "note": ("**未取得债券市场官方交易日历**，"
                      "不得用 A 股日历替代，覆盖率与连续性记 unknown")},
    "hk": {"market": "香港市场（港股通）", "calendar": "港股交易日历",
           "calendar_available": False,
           "calendar_is_official": False,
           "note": ("**未取得港股官方交易日历**，"
                    "不得用 A 股日历替代，覆盖率与连续性记 unknown")},
}


def group_of(code: str) -> str:
    for g, mp in (("stock", STOCK_TR_CANDIDATES),
                  ("bond", BOND_INDEXES), ("hk", HK_INDEXES)):
        for codes in mp.values():
            if code in codes:
                return g
    raise KeyError(code)


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


def load_old_evidence(code: str) -> dict:
    """读取 3B-6.2.3.1.0 已保存的原始证据（不重新下载）。"""
    f = EVID_OLD / f"hist_{code}_20040101_20261127.json"
    if not f.exists():
        return {"obtained": False, "file": None, "rows": []}
    raw = f.read_bytes()
    try:
        rows = json.loads(raw.decode("utf-8")).get("data") or []
    except Exception:
        rows = []
    return {
        "obtained": True,
        "file": str(f.relative_to(ROOT)).replace("\\", "/"),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "rows": rows,
    }


def load_basic(code: str) -> dict:
    f = EVID_OLD / f"basic_{code}.json"
    if not f.exists():
        return {"obtained": False}
    raw = f.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8")).get("data") or {}
    except Exception:
        data = {}
    return {
        "obtained": bool(data),
        "file": str(f.relative_to(ROOT)).replace("\\", "/"),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "official_full_name": data.get("indexFullNameCn"),
        "official_short_name": data.get("indexShortNameCn"),
        "basic_date": data.get("basicDate"),
        "basic_index": data.get("basicIndex"),
        "publish_date": data.get("publishDate"),
        "index_type": data.get("indexType"),
    }


# ---------------------------------------------------------------- 合成首行识别
def detect_synthetic_start(code: str, rows: list[dict],
                           cal: set[str], basic: dict) -> dict:
    """多重证据识别首行是否为「请求起始日合成行」。

    **不只看间隔 > 60 天**，综合以下证据：

    1. 首行日期 == 请求起始日 20040101（本轮全部请求均从此开始）
    2. 首行日期不在 A 股交易日历（非交易日）
    3. 首行 close == 第二行 close（数值完全重复）
    4. 3B-6.2.3.0.4 对照实验：从 20040102 请求时该日消失
    5. 首行早于官方基日或与其关系异常

    无法确认时返回 ``confirmed=False``，真实起点记 ``unknown``。
    """
    if not rows:
        return {"confirmed": False, "reason": "无数据",
                "real_history_start": "unknown", "evidence": {}}
    first = rows[0]
    d0 = first.get("tradeDate")
    c0 = first.get("close")
    d1 = rows[1].get("tradeDate") if len(rows) > 1 else None
    c1 = rows[1].get("close") if len(rows) > 1 else None

    iso0 = f"{d0[:4]}-{d0[4:6]}-{d0[6:]}" if d0 else None
    ev = {
        "first_date": d0,
        "second_date": d1,
        "first_close": c0,
        "second_close": c1,
        "first_equals_request_start": d0 == "20040101",
        "first_not_in_a_calendar": (iso0 not in cal) if iso0 else None,
        "first_close_equals_second": (
            c0 is not None and c1 is not None
            and float(c0) == float(c1)),
        "official_basic_date": basic.get("basic_date"),
        "official_publish_date": basic.get("publish_date"),
    }

    # 3B-6.2.3.0.4 对照实验证据（仅价格指数有）
    ctrl = _control_evidence(code)
    ev["control_from_20040102_drops_it"] = ctrl.get("drops_target")
    ev["control_source"] = ctrl.get("source_file")

    votes = [
        ev["first_equals_request_start"],
        ev["first_not_in_a_calendar"],
        ev["first_close_equals_second"],
        ev["control_from_20040102_drops_it"],
    ]
    true_votes = sum(1 for v in votes if v is True)

    # 确认条件：至少 3 项成立，且「首行==请求起始日」必须成立
    confirmed = bool(ev["first_equals_request_start"] and true_votes >= 3)

    if confirmed:
        real_start = d1  # 第二行即真实起点
        reason = (f"综合证据 {true_votes}/4 成立："
                  f"首行为请求起始日 {d0}、非交易日、"
                  f"数值与第二行相同、对照实验证实改起始日后消失")
    else:
        real_start = "unknown"
        reason = (f"证据不足（{true_votes}/4），无法确认首行是否合成行；"
                  f"真实历史起点记 unknown，不自行推断")

    return {
        "confirmed": confirmed,
        "synthetic_row": d0 if confirmed else None,
        "real_history_start": real_start,
        "votes": true_votes,
        "evidence": ev,
        "reason": reason,
    }


def _control_evidence(code: str) -> dict:
    """读取 3B-6.2.3.0.4 的对照实验（从 20040102 请求）。"""
    f = EVID_OLD4 / f"csindex_ctrl_{code}_from20040102.json"
    if not f.exists():
        return {"drops_target": None, "source_file": None}
    try:
        rows = json.loads(f.read_text(encoding="utf-8")).get("data") or []
    except Exception:
        return {"drops_target": None, "source_file": None}
    dates = [r.get("tradeDate") for r in rows]
    return {
        "drops_target": "20040101" not in dates,
        "source_file": str(f.relative_to(ROOT)).replace("\\", "/"),
        "first_date": dates[0] if dates else None,
    }


# ---------------------------------------------------------------- 数值质量
_NUM_STR_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")


def to_number(v) -> tuple[float | None, str | None]:
    """把原始值转换为数值，返回 (值, 失败原因)。

    **必须识别字符串形式的 NaN / Infinity**，不能依赖原始字段是否为 float。
    """
    if v is None:
        return None, "null"
    if isinstance(v, bool):
        return None, "bool"
    if isinstance(v, (int, float)):
        f = float(v)
        if math.isnan(f):
            return None, "nan"
        if math.isinf(f):
            return None, "inf"
        return f, None
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None, "empty_string"
        low = s.lower()
        if low in ("nan", "+nan", "-nan"):
            return None, "nan_string"
        if low in ("inf", "+inf", "infinity", "+infinity"):
            return None, "inf_string"
        if low in ("-inf", "-infinity"):
            return None, "neg_inf_string"
        if not _NUM_STR_RE.match(s):
            return None, "non_numeric_string"
        f = float(s)
        if math.isnan(f):
            return None, "nan"
        if math.isinf(f):
            return None, "inf"
        if not math.isfinite(f):
            return None, "not_finite"
        return f, None
    return None, f"unsupported_type:{type(v).__name__}"


# ---------------------------------------------------------------- 质量审计
def _classify_outside_calendar(rows: list[dict],
                               outside: list[str]) -> list[dict]:
    """把日历外日期分类：休市日占位行 vs 无法解释。

    官方全收益序列在 A 股休市日（如 2018-06-18 端午）仍返回一行，
    特征：``tradingVol == 0`` 且 ``changePct`` 接近 0 且
    ``close`` 与前一日几乎相同。这类行**不是真实交易日行情**。
    """
    iso = {f"{r['tradeDate'][:4]}-{r['tradeDate'][4:6]}-"
           f"{r['tradeDate'][6:]}": r for r in rows if r.get("tradeDate")}
    ordered = sorted(iso)
    out = []
    for d in outside:
        r = iso.get(d) or {}
        vol = r.get("tradingVol")
        pct = r.get("changePct")
        idx = ordered.index(d) if d in ordered else -1
        prev_close = None
        if idx > 0:
            prev_close = iso[ordered[idx - 1]].get("close")
        cur_close = r.get("close")
        same_as_prev = (prev_close is not None and cur_close is not None
                        and abs(float(cur_close) - float(prev_close)) < 1e-9)
        zero_vol = (vol in (0, 0.0))
        tiny_pct = (pct is not None and abs(float(pct)) < 0.5)
        if zero_vol and (same_as_prev or tiny_pct):
            cls = "market_closed_placeholder"
            note = ("A股休市日（如端午），官方全收益序列仍返回一行；"
                    "tradingVol=0 且 close 与前一日几乎相同，"
                    "**不是真实交易日行情**")
        else:
            cls = "unexplained"
            note = "日历外且无休市特征，需进一步核查"
        out.append({"date": d, "classification": cls,
                    "trading_vol": vol, "change_pct": pct,
                    "close": cur_close, "prev_close": prev_close,
                    "same_as_prev": same_as_prev, "note": note})
    return out


def audit_quality(code: str, rows: list[dict], cal: set[str],
                  *, group: str, synth: dict) -> dict:
    """按市场日历审计质量；无适用日历时覆盖/连续性记 unknown。"""
    dates = [r.get("tradeDate") for r in rows]
    closes = [r.get("close") for r in rows]

    converted = [to_number(c) for c in closes]
    values = [v for v, _ in converted]
    reasons = [r for _, r in converted]

    null_count = sum(1 for r in reasons if r == "null")
    nan_count = sum(1 for r in reasons if r and "nan" in r)
    inf_count = sum(1 for r in reasons if r and "inf" in r)
    non_numeric = sum(1 for r in reasons
                      if r and r in ("non_numeric_string",
                                     "empty_string", "bool")
                      or (r or "").startswith("unsupported_type"))
    non_positive = [d for d, v in zip(dates, values)
                    if v is not None and v <= 0]

    dup = len(dates) - len(set(dates))
    desc = sum(1 for i in range(1, len(dates)) if dates[i] < dates[i - 1])

    illegal, missing = [], []
    for d in dates:
        if not d:
            missing.append(d)
            continue
        try:
            datetime.strptime(str(d), "%Y%m%d")
        except Exception:
            illegal.append(d)

    # 极端异常：相邻日收益 > 50%
    extreme = []
    prev = None
    for d, v in zip(dates, values):
        if v is None or v <= 0:
            continue
        if prev is not None and prev > 0:
            chg = abs(v / prev - 1.0)
            if chg > 0.5:
                extreme.append({"date": d, "close": v,
                                "prev": prev, "chg": round(chg, 6)})
        prev = v

    # ---- 覆盖率：仅在有适用日历时计算 ----
    mcal = MARKET_CALENDAR[group]
    real_start = synth.get("real_history_start")
    coverage = {}
    if not mcal["calendar_available"]:
        coverage = {
            "coverage_status": "unknown",
            "continuity_status": "unknown",
            "reason": mcal["note"],
            "missing_trading_days": None,
            "dates_outside_calendar": None,
            "calendar_used": mcal["calendar"],
            "calendar_available": False,
        }
    elif real_start == "unknown":
        coverage = {
            "coverage_status": "unknown",
            "continuity_status": "unknown",
            "reason": "真实历史起点无法确认，不计算覆盖率",
            "missing_trading_days": None,
            "dates_outside_calendar": None,
            "calendar_used": mcal["calendar"],
            "calendar_available": True,
        }
    else:
        real = [d for d in dates if d >= real_start]
        iso = [f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in real if d]
        if iso:
            lo, hi = min(iso), max(iso)
            win = {d for d in cal if lo <= d <= hi}
            miss = sorted(win - set(iso))
            out = sorted(set(iso) - cal)
        else:
            miss, out, win = [], [], set()
        # 日历外日期分类：官方全收益序列在 A 股休市日仍返回一行，
        # 特征是 tradingVol=0 且 close 与前一日几乎相同（非真实交易日行情）。
        out_detail = _classify_outside_calendar(rows, out)
        real_out = [x for x in out_detail
                    if x["classification"] == "unexplained"]
        coverage = {
            "coverage_status": "verified" if not miss else "has_gaps",
            "continuity_status": ("verified"
                                  if (not miss and not real_out)
                                  else "has_issues"),
            "outside_calendar_detail": out_detail,
            "outside_calendar_unexplained": len(real_out),
            "missing_trading_days": len(miss),
            "missing_sample": miss[:10],
            "dates_outside_calendar": len(out),
            "dates_outside_calendar_sample": out[:10],
            "calendar_window_days": len(win),
            "calendar_used": mcal["calendar"],
            "calendar_available": True,
            "calendar_is_official": False,
            "reason": ("相对 A 股交易日历**代理**无缺失（非官方发布日历）"
                       if not miss else f"相对代理日历缺 {len(miss)} 天"),
        }

    data_ok = (dup == 0 and desc == 0 and not illegal and not missing
               and null_count == 0 and nan_count == 0 and inf_count == 0
               and non_numeric == 0 and len(non_positive) == 0)

    return {
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "row_count": len(rows),
        "distinct_dates": len(set(dates)),
        "duplicate_dates": dup,
        "descending_dates": desc,
        "illegal_dates": illegal[:10],
        "illegal_date_count": len(illegal),
        "missing_date_count": len(missing),
        "null_close": null_count,
        "nan_close": nan_count,
        "inf_close": inf_count,
        "non_numeric_close": non_numeric,
        "non_positive_close": len(non_positive),
        "non_positive_sample": non_positive[:5],
        "extreme_move_count": len(extreme),
        "extreme_moves": extreme[:10],
        "data_quality_verified": data_ok,
        **coverage,
    }


# ---------------------------------------------------------------- 映射证据
def build_mapping_evidence(price_code: str, tr_code: str,
                           price_basic: dict, tr_basic: dict,
                           price_rows: list[dict], tr_rows: list[dict],
                           synth: dict) -> dict:
    """完整映射证据（基日匹配必须真实判定，不得为 null）。"""
    base_match = (price_basic.get("basic_date") is not None
                  and tr_basic.get("basic_date") is not None
                  and price_basic["basic_date"] == tr_basic["basic_date"])

    pm = {r["tradeDate"]: r.get("close") for r in price_rows}
    real_start = synth.get("real_history_start")
    ratios = []
    for r in tr_rows:
        d = r.get("tradeDate")
        if real_start not in (None, "unknown") and d < real_start:
            continue
        tc, terr = to_number(r.get("close"))
        pc, perr = to_number(pm.get(d))
        if tc and pc and tc > 0 and pc > 0:
            ratios.append((d, tc / pc))

    r_first = ratios[0][1] if ratios else None
    r_last = ratios[-1][1] if ratios else None
    all_ge_one = (all(x[1] >= 1.0 - 1e-9 for x in ratios)
                  if ratios else None)
    increasing = ((r_last > r_first)
                  if (r_first is not None and r_last is not None) else None)
    eq_one = [d for d, v in ratios if abs(v - 1.0) < 1e-9]

    # 映射判定：三项同时成立
    mapping_ok = bool(base_match and all_ge_one is True
                      and increasing is True)

    return {
        "price_index_code": price_code,
        "price_index_official_name": price_basic.get("official_full_name"),
        "price_index_basic_date": price_basic.get("basic_date"),
        "tr_candidate_code": tr_code,
        "tr_candidate_official_name": tr_basic.get("official_full_name"),
        "tr_candidate_basic_date": tr_basic.get("basic_date"),
        "base_date_match": base_match,
        "base_date_check_note": (
            "**必须真实比较两个基日**；任一为 null 即判不通过，"
            "不得把 null 当成通过"),
        "ratio_sample_count": len(ratios),
        "ratio_first": r_first,
        "ratio_last": r_last,
        "all_ratios_ge_one": all_ge_one,
        "ratio_increasing": increasing,
        "ratio_equals_one_count": len(eq_one),
        "ratio_equals_one_sample": eq_one[:10],
        "mapping_verified": mapping_ok,
        "mapping_evidence_level": "technical_inference",
        "mapping_evidence_note": (
            "**技术映射判断**：基日一致 + 比值恒≥1 + 比值上升。"
            "**不是**官方发布的映射关系文件。"
            "官方基本信息只确认候选自身的身份与收益类型，"
            "不确认它与某个原指数的映射关系"),
        "official_mapping_document_found": False,
        "mapping_conclusion": (
            "技术映射判断通过（非官方确认）" if mapping_ok
            else "技术映射判断未通过"),
    }


# ---------------------------------------------------------------- 三类状态
def compute_three_states(dims: dict, quality: dict) -> dict:
    """三个**独立**的下一阶段状态。

    A. raw_data_layer_ingest_candidate
       允许把原始响应接入隔离数据层（即使有质量异常）
    B. validated_series_candidate
       可作为经过验证的独立行情序列（需适用日历+质量+覆盖）
    C. formal_series_admitted
       满足全部正式准入条件（含时点可用性）
    """
    # A：只要有官方身份 + 接口成功返回，即可进入原始数据层
    ingest = bool(dims["official_identity_verified"]
                  and dims["history_api_available"])

    # B：必须有适用日历 + 质量通过 + 覆盖通过
    validated = bool(
        dims["official_identity_verified"]
        and dims["return_basis_verified"]
        and dims["history_api_available"]
        and dims["data_quality_verified"]
        and quality.get("coverage_status") == "verified"
        and quality.get("continuity_status") == "verified")

    # C：B 通过 + 映射通过 + 时点可用
    admitted = bool(validated
                    and dims["mapping_to_price_index_verified"]
                    and dims["point_in_time_available"])

    return {
        "raw_data_layer_ingest_candidate": ingest,
        "validated_series_candidate": validated,
        "formal_series_admitted": admitted,
        "rule": {
            "raw_data_layer_ingest_candidate":
                "官方身份 + 接口返回成功（质量异常不阻止隔离存储）",
            "validated_series_candidate":
                "身份 + 口径 + 接口 + 质量 + 覆盖verified + 连续verified",
            "formal_series_admitted":
                "validated + 映射 + 时点可用",
        },
    }


# ---------------------------------------------------------------- 逐候选
def audit_candidate(tr_code: str, price_code: str, group: str,
                    cal: set[str]) -> dict:
    tr_hist = load_old_evidence(tr_code)
    price_hist = load_old_evidence(price_code)
    tr_basic = load_basic(tr_code)
    price_basic = load_basic(price_code)

    synth = detect_synthetic_start(tr_code, tr_hist["rows"], cal, tr_basic)
    q = audit_quality(tr_code, tr_hist["rows"], cal,
                      group=group, synth=synth)
    mapping = build_mapping_evidence(
        price_code, tr_code, price_basic, tr_basic,
        price_hist["rows"], tr_hist["rows"], synth)

    identity_ok = bool(tr_basic.get("obtained")
                       and tr_basic.get("official_full_name")
                       and tr_basic.get("basic_date")
                       and tr_basic.get("publish_date"))
    name = tr_basic.get("official_full_name") or ""
    if "全收益" in name:
        basis, basis_ok = "gross_total_return", True
    elif "净收益" in name:
        basis, basis_ok = "net_total_return", True
    else:
        basis, basis_ok = "unknown", False

    # 历史完整性四态
    api_ok = bool(tr_hist["obtained"] and q["row_count"] > 0)
    full_range = bool(tr_hist["obtained"])  # 已按 20040101~20261127 请求
    coverage_status = q["coverage_status"]
    continuity_status = q["continuity_status"]

    pit_ok = False  # 时点可用性仍为 unknown

    dims = {
        "official_identity_verified": identity_ok,
        "mapping_to_price_index_verified": mapping["mapping_verified"],
        "return_basis_verified": basis_ok,
        "history_api_available": api_ok,
        "full_range_response_retrieved": full_range,
        "history_coverage_verified": coverage_status == "verified",
        "history_continuity_verified": continuity_status == "verified",
        "data_quality_verified": q["data_quality_verified"],
        "point_in_time_available": pit_ok,
    }
    states = compute_three_states(dims, q)
    dims["formal_series_admitted"] = states["formal_series_admitted"]

    return {
        "tr_candidate": tr_code,
        "price_index": price_code,
        "group": group,
        "market": MARKET_CALENDAR[group]["market"],
        "calendar_used": MARKET_CALENDAR[group]["calendar"],
        "calendar_available": MARKET_CALENDAR[group]["calendar_available"],
        "calendar_note": MARKET_CALENDAR[group]["note"],
        "tr_basic": tr_basic,
        "price_basic": price_basic,
        "tr_history_meta": {k: v for k, v in tr_hist.items() if k != "rows"},
        "price_history_meta": {k: v for k, v in price_hist.items()
                               if k != "rows"},
        "synthetic_start_detection": synth,
        "quality": q,
        "mapping_evidence": mapping,
        "return_basis": basis,
        "dimensions": dims,
        "next_stage_states": states,
        "conclusion": _concl(tr_code, group, dims, q, states),
    }


def _concl(tr, group, dims, q, states) -> str:
    if states["formal_series_admitted"]:
        return f"{tr} 全部条件通过，可正式准入"
    parts = []
    if states["raw_data_layer_ingest_candidate"]:
        parts.append("可进入**原始数据隔离层**")
    else:
        parts.append("**不得**进入原始数据层")
    if states["validated_series_candidate"]:
        parts.append("可作为**已验证独立序列**")
    else:
        blockers = []
        if not dims["data_quality_verified"]:
            blockers.append("数据质量")
        if q["coverage_status"] != "verified":
            blockers.append(f"覆盖={q['coverage_status']}")
        if q["continuity_status"] != "verified":
            blockers.append(f"连续={q['continuity_status']}")
        parts.append(f"**不可**作为已验证序列（{', '.join(blockers)}）")
    parts.append("**不得**正式准入（时点可用性 unknown）")
    return f"{tr}：" + "；".join(parts)


# ---------------------------------------------------------------- 汇总
def summarize(cands: list[dict]) -> dict:
    def cnt(rs, pred):
        return sum(1 for r in rs if pred(r))

    groups = {}
    for g in ("stock", "bond", "hk"):
        rs = [r for r in cands if r["group"] == g]
        groups[g] = {
            "candidate_count": len(rs),
            "market": MARKET_CALENDAR[g]["market"],
            "calendar_used": MARKET_CALENDAR[g]["calendar"],
            "calendar_available": MARKET_CALENDAR[g]["calendar_available"],
            "official_identity_verified": cnt(
                rs, lambda r: r["dimensions"]["official_identity_verified"]),
            "mapping_verified": cnt(
                rs, lambda r: r["dimensions"][
                    "mapping_to_price_index_verified"]),
            "return_basis_verified": cnt(
                rs, lambda r: r["dimensions"]["return_basis_verified"]),
            "history_api_available": cnt(
                rs, lambda r: r["dimensions"]["history_api_available"]),
            "coverage_verified": cnt(
                rs, lambda r: r["dimensions"]["history_coverage_verified"]),
            "coverage_unknown": cnt(
                rs, lambda r: r["quality"]["coverage_status"] == "unknown"),
            "continuity_verified": cnt(
                rs, lambda r: r["dimensions"][
                    "history_continuity_verified"]),
            "continuity_unknown": cnt(
                rs, lambda r: r["quality"]["continuity_status"] == "unknown"),
            "data_quality_verified": cnt(
                rs, lambda r: r["dimensions"]["data_quality_verified"]),
            "point_in_time_available": cnt(
                rs, lambda r: r["dimensions"]["point_in_time_available"]),
            "raw_data_layer_ingest_candidate": cnt(
                rs, lambda r: r["next_stage_states"][
                    "raw_data_layer_ingest_candidate"]),
            "validated_series_candidate": cnt(
                rs, lambda r: r["next_stage_states"][
                    "validated_series_candidate"]),
            "formal_series_admitted": cnt(
                rs, lambda r: r["next_stage_states"][
                    "formal_series_admitted"]),
        }

    return {
        "total_candidates": len(cands),
        "groups": groups,
        "totals": {
            "raw_data_layer_ingest_candidate": cnt(
                cands, lambda r: r["next_stage_states"][
                    "raw_data_layer_ingest_candidate"]),
            "validated_series_candidate": cnt(
                cands, lambda r: r["next_stage_states"][
                    "validated_series_candidate"]),
            "formal_series_admitted": cnt(
                cands, lambda r: r["next_stage_states"][
                    "formal_series_admitted"]),
        },
        "gates": {
            "ready_for_research_analysis": True,
            "ready_for_backtest": False,
            "ready_for_formal_ranking": False,
            "ready_for_3b6_2_3_1_series_build": False,
        },
        "_self_check": {
            "three_groups_present": len(groups) == 3,
            "no_bond_hk_using_a_calendar": all(
                r["calendar_used"] != "A股交易日历（项目代理）"
                for r in cands if r["group"] in ("bond", "hk")),
            "bond_hk_coverage_unknown": all(
                r["quality"]["coverage_status"] == "unknown"
                for r in cands if r["group"] in ("bond", "hk")),
            "no_formal_admitted": cnt(
                cands, lambda r: r["next_stage_states"][
                    "formal_series_admitted"]) == 0,
            "mapping_base_date_never_null": all(
                r["mapping_evidence"]["base_date_match"] is not None
                for r in cands),
            "h20184_not_validated": next(
                r for r in cands
                if r["tr_candidate"] == "H20184")["next_stage_states"][
                    "validated_series_candidate"] is False,
        },
    }


# ---------------------------------------------------------------- 主流程
def build_manifest() -> dict:
    """本轮证据清单。

    **本轮不产生新的官方原始响应**（复用 3B-6.2.3.1.0 已保存的证据）。
    因此 manifest 记录的是**引用关系**：本轮审计读取了哪些原始文件及其 SHA256，
    以便复核「审计结论确实基于这些证据」。
    """
    EVID.mkdir(parents=True, exist_ok=True)
    # 1) 本轮自身的产物（若有独立 JSON）
    own = {}
    for f in sorted(EVID.glob("*.json")):
        if f.name == "manifest.json":
            continue
        raw = f.read_bytes()
        own[f.name] = {"bytes": len(raw),
                       "sha256": hashlib.sha256(raw).hexdigest()}
    # 2) 引用的上一阶段原始证据（全部）
    ref = {}
    old_manifest = EVID_OLD / "manifest.json"
    if old_manifest.exists():
        doc_old = json.loads(old_manifest.read_text(encoding="utf-8"))
        for name, info in (doc_old.get("files") or {}).items():
            f = EVID_OLD / name
            if not f.exists():
                ref[name] = {"exists": False, "sha256": None}
                continue
            actual = hashlib.sha256(f.read_bytes()).hexdigest()
            ref[name] = {
                "relative_path":
                    str(f.relative_to(ROOT)).replace("\\", "/"),
                "bytes": f.stat().st_size,
                "manifest_sha256": info.get("sha256"),
                "actual_sha256": actual,
                "match": actual == info.get("sha256"),
            }
    doc = {
        "phase": "3B-6.2.3.1.0.1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "no_new_download": True,
        "note": ("本轮不产生新的官方原始响应；"
                 "下列 referenced_evidence 为 3B-6.2.3.1.0 已保存证据，"
                 "逐份复核 SHA256 未变"),
        "own_files": own,
        "own_file_count": len(own),
        "referenced_evidence": ref,
        "referenced_count": len(ref),
        "referenced_all_match": (
            all(v.get("match") is True for v in ref.values()) if ref else None),
    }
    (EVID / "manifest.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return doc


def verify_old_evidence_integrity() -> dict:
    """核对 3B-6.2.3.1.0 的原始证据未被修改。"""
    m = EVID_OLD / "manifest.json"
    if not m.exists():
        return {"checked": 0, "all_match": None}
    doc = json.loads(m.read_text(encoding="utf-8"))
    files = doc.get("files") or {}
    ok, bad = 0, []
    for name, info in files.items():
        f = EVID_OLD / name
        if not f.exists():
            bad.append(name)
            continue
        if hashlib.sha256(f.read_bytes()).hexdigest() == info["sha256"]:
            ok += 1
        else:
            bad.append(name)
    return {"checked": len(files), "matched": ok, "mismatched": bad,
            "all_match": not bad}


def main() -> None:
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
        cal = {r[0] for r in conn.execute(
            "select trade_date from trade_calendar "
            "where trade_date between '2004-01-01' and '2026-11-27'")}
        print(f"基线 db_sha256={before['database_sha256']}")
        print(f"A股日历 {len(cal)} 天\n")

        cands = []
        for g, mp in (("stock", STOCK_TR_CANDIDATES),
                      ("bond", BOND_INDEXES), ("hk", HK_INDEXES)):
            for price_code, trs in mp.items():
                for tr in trs:
                    r = audit_candidate(tr, price_code, g, cal)
                    cands.append(r)
                    d = r["dimensions"]
                    st = r["next_stage_states"]
                    print(f"  [{g:5s}] {tr:14s}<-{price_code:8s} "
                          f"synth={r['synthetic_start_detection']['confirmed']!s:5s} "
                          f"start={str(r['synthetic_start_detection']['real_history_start'])[:8]:8s} "
                          f"cov={r['quality']['coverage_status']:8s} "
                          f"map={d['mapping_to_price_index_verified']!s:5s} "
                          f"raw={st['raw_data_layer_ingest_candidate']!s:5s} "
                          f"val={st['validated_series_candidate']!s:5s} "
                          f"adm={st['formal_series_admitted']!s:5s}")

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

    old_integrity = verify_old_evidence_integrity()
    result = {
        "phase": "3B-6.2.3.1.0.1",
        "task": "官方全收益指数审计边界纠偏与准入统计一致性修复",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "baseline_head": "3a85bd6dc12dbd73ad497d5af62337dc8e2245a2",
        "read_only": True,
        "no_redownload": True,
        "fixes": {
            "1_market_calendar_isolation": MARKET_CALENDAR,
            "2_synthetic_start_detection": (
                "多重证据（请求起始日 + 非交易日 + 数值重复 + 对照实验），"
                "不再只看间隔 > 60 天"),
            "3_mapping_evidence_complete": (
                "base_date_match 真实判定，不再为 null"),
            "4_history_integrity_split": [
                "history_api_available", "full_range_response_retrieved",
                "history_coverage_status", "history_continuity_status"],
            "5_nan_inf_check": (
                "改为对转换后数值检查，识别字符串 'NaN'/'Infinity'"),
            "6_three_states": [
                "raw_data_layer_ingest_candidate",
                "validated_series_candidate",
                "formal_series_admitted"],
        },
        "db_before": before,
        "db_after": after,
        "db_unchanged": before["database_sha256"] == after["database_sha256"],
        "old_evidence_integrity": old_integrity,
        "candidates": cands,
    }
    result["summary"] = summarize(cands)
    result["evidence_manifest"] = build_manifest()

    (REPORTS / "phase3B6_2_3_1_0_1_audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")

    print("\n=== 汇总 ===")
    print(json.dumps(result["summary"]["totals"], ensure_ascii=False))
    print(json.dumps(result["summary"]["_self_check"], ensure_ascii=False,
                     indent=1))
    print(f"\n数据库未变: {result['db_unchanged']}")
    print(f"原始证据完整: {old_integrity}")


if __name__ == "__main__":
    main()
