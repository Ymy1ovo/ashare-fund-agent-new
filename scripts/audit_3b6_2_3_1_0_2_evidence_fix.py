"""阶段3B-6.2.3.1.0.2 全收益候选合成行证据溯源与休市日分类保守化。

**只读**：不重新下载、不修改数据库、不开始正式序列建设。

四项修正：

1. 对照文件映射修正（用 price_code 而非 tr_code）+ 区分「原指数对照」与「候选自身对照」
2. 合成行结论分级：confirmed / strong_inference / unknown
3. 对照文件纳入引用式 manifest（含缺失记录）
4. 休市日占位行分类保守化：confirmed / suspected / unexplained
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
EVID_OLD = REPORTS / "evidence" / "phase3B6_2_3_1_0"
EVID_OLD4 = REPORTS / "evidence" / "phase3B6_2_3_0_4"
EVID_OLD1 = REPORTS / "evidence" / "phase3B6_2_3_1_0_1"
EVID = REPORTS / "evidence" / "phase3B6_2_3_1_0_2"

STOCK_TR_CANDIDATES = {
    "000300": ["H00300"], "000905": ["H00905"], "000906": ["H00906"],
    "000016": ["H00016"], "399997": ["H20539", "399997CNY02"],
    "H30184": ["H20184"], "000942": ["H00942"], "000922": ["H00922"],
}
BOND_INDEXES = {"000012": ["H00012", "N00012"]}
HK_INDEXES = {"930930": ["H20930"]}

MARKET_CALENDAR = {
    "stock": {"market": "沪深A股", "calendar": "A股交易日历（项目代理）",
              "calendar_available": True, "calendar_is_official": False},
    "bond": {"market": "上交所债券市场", "calendar": "债券市场交易日历",
             "calendar_available": False, "calendar_is_official": False},
    "hk": {"market": "香港市场（港股通）", "calendar": "港股交易日历",
           "calendar_available": False, "calendar_is_official": False},
}


def price_code_of(tr_code: str) -> str:
    for price, trs in {**STOCK_TR_CANDIDATES, **BOND_INDEXES,
                       **HK_INDEXES}.items():
        if tr_code in trs:
            return price
    raise KeyError(tr_code)


def group_of(tr_code: str) -> str:
    for g, mp in (("stock", STOCK_TR_CANDIDATES),
                  ("bond", BOND_INDEXES), ("hk", HK_INDEXES)):
        for trs in mp.values():
            if tr_code in trs:
                return g
    raise KeyError(tr_code)


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


def load_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_bytes().decode("utf-8")).get("data") or []
    except Exception:
        return []


def load_basic(code: str) -> dict:
    f = EVID_OLD / f"basic_{code}.json"
    if not f.exists():
        return {"obtained": False}
    try:
        data = json.loads(f.read_bytes().decode("utf-8")).get("data") or {}
    except Exception:
        data = {}
    return {"obtained": bool(data),
            "official_full_name": data.get("indexFullNameCn"),
            "basic_date": data.get("basicDate"),
            "basic_index": data.get("basicIndex"),
            "publish_date": data.get("publishDate")}


# ---------------------------------------------------------------- 对照证据
def control_evidence(tr_code: str) -> dict:
    """区分两种对照证据，**不得混淆**。

    A. price_index_control_drops_request_start
       原**价格指数**的对照请求是否确认 20040101 消失。
       只能证明原价格指数接口的行为。

    B. tr_candidate_control_drops_request_start
       **全收益候选自身**的独立对照请求证据。
       本轮**没有任何全收益候选**的对照文件 → 必须为 unknown。
    """
    price = price_code_of(tr_code)

    # A：原价格指数对照（文件按价格指数代码命名）
    ctrl_path = EVID_OLD4 / f"csindex_ctrl_{price}_from20040102.json"
    if ctrl_path.exists():
        rows = load_rows(ctrl_path)
        dates = [r.get("tradeDate") for r in rows]
        price_ctrl = {
            "available": True,
            "drops_20040101": "20040101" not in dates,
            "row_count": len(rows),
            "first_date": dates[0] if dates else None,
            "file": str(ctrl_path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": hashlib.sha256(ctrl_path.read_bytes()).hexdigest(),
            "bytes": ctrl_path.stat().st_size,
            "scope": "原价格指数",
            "proves": f"仅证明 {price} 接口行为，"
                      f"**不能自动证明 {tr_code} 具有相同行为**",
        }
    else:
        price_ctrl = {
            "available": False,
            "drops_20040101": None,
            "file": None,
            "sha256": None,
            "scope": "原价格指数",
            "reason": f"缺 csindex_ctrl_{price}_from20040102.json",
        }

    # B：全收益候选自身对照
    tr_ctrl_path = EVID_OLD4 / f"csindex_ctrl_{tr_code}_from20040102.json"
    if tr_ctrl_path.exists():
        rows = load_rows(tr_ctrl_path)
        dates = [r.get("tradeDate") for r in rows]
        tr_ctrl = {
            "available": True,
            "drops_20040101": "20040101" not in dates,
            "row_count": len(rows),
            "file": str(tr_ctrl_path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": hashlib.sha256(tr_ctrl_path.read_bytes()).hexdigest(),
            "scope": "全收益候选自身",
        }
    else:
        tr_ctrl = {
            "available": False,
            "drops_20040101": None,
            "file": None,
            "sha256": None,
            "scope": "全收益候选自身",
            "reason": (f"**本轮无 {tr_code} 自身的对照请求证据**"
                       f"（未保存 csindex_ctrl_{tr_code}_from20040102.json）；"
                       f"不得把原价格指数的对照结论套用到候选自身"),
        }

    return {
        "price_code": price,
        "price_index_control": price_ctrl,
        "tr_candidate_control": tr_ctrl,
    }


# ---------------------------------------------------------------- 合成行分级
def detect_synthetic_start(tr_code: str, rows: list[dict],
                           cal: set[str], basic: dict) -> dict:
    """合成行结论三级：confirmed / strong_inference / unknown。

    **逐项判定，不允许出现「证据不存在却声称通过」的文字。**
    """
    group = group_of(tr_code)
    mcal = MARKET_CALENDAR[group]
    if not rows:
        return {"status": "unknown", "confirmed": False,
                "synthetic_row": None, "real_history_start": "unknown",
                "votes": 0, "evidence": {},
                "reason": "无数据，无法判定"}

    first = rows[0]
    d0 = first.get("tradeDate")
    c0 = first.get("close")
    d1 = rows[1].get("tradeDate") if len(rows) > 1 else None
    c1 = rows[1].get("close") if len(rows) > 1 else None
    iso0 = f"{d0[:4]}-{d0[4:6]}-{d0[6:]}" if d0 else None

    ctrl = control_evidence(tr_code)

    # ---- 逐项证据（每项明确 true/false/None）----
    ev = {
        "first_date": d0,
        "second_date": d1,
        "first_close": c0,
        "second_close": c1,
        # 1) 首行 == 请求起始日
        "first_equals_request_start": (d0 == "20040101"),
        # 2) 首行是否非对应市场交易日
        #    仅在**有适用日历**时才可判定；债券/港股不得用 A 股日历
        "market_calendar_available": mcal["calendar_available"],
        "first_not_in_market_calendar": (
            (iso0 not in cal) if (iso0 and mcal["calendar_available"])
            else None),
        "market_calendar_note": (
            mcal["calendar"] if mcal["calendar_available"]
            else f"{mcal['calendar']} 未取得，**不得用 A 股日历判定**"),
        # 3) 首行与第二行数值是否完全一致
        "first_close_equals_second": (
            (c0 is not None and c1 is not None and float(c0) == float(c1))),
        # 4) 官方基日与首行/第二行关系
        "official_basic_date": basic.get("basic_date"),
        "first_before_basic_date": _before(d0, basic.get("basic_date")),
        # 5) 官方发布日期
        "official_publish_date": basic.get("publish_date"),
        # 6) 对照实验归属
        "price_index_control_drops": ctrl["price_index_control"].get(
            "drops_20040101"),
        "tr_candidate_control_drops": ctrl["tr_candidate_control"].get(
            "drops_20040101"),
        "tr_candidate_control_available": ctrl["tr_candidate_control"][
            "available"],
    }

    # ---- 分级 ----
    # confirmed：候选**自身**对照证据存在且确认消失
    self_ctrl = ev["tr_candidate_control_drops"]
    if self_ctrl is True:
        status = "confirmed"
        reason = (f"{tr_code} 自身对照请求（从 20040102 起）确认 "
                  f"{d0} 消失，属直接证据")
    else:
        # strong_inference：至少 3 项独立证据，且首行为请求起始日
        votes = [
            ev["first_equals_request_start"],
            ev["first_not_in_market_calendar"],
            ev["first_close_equals_second"],
            ev["first_before_basic_date"],
        ]
        n = sum(1 for v in votes if v is True)
        unknown_cnt = sum(1 for v in votes if v is None)
        if ev["first_equals_request_start"] and n >= 3:
            status = "strong_inference"
            reason = (f"{n} 项独立证据支持合成行"
                      f"（请求起始日/非交易日/数值重复/早于基日），"
                      f"但**无 {tr_code} 自身对照证据**，"
                      f"故为高置信推断，**非官方确认**")
        elif n >= 2 and unknown_cnt <= 2:
            status = "strong_inference"
            reason = (f"仅 {n} 项证据支持，且 {unknown_cnt} 项无法判定；"
                      f"列为高置信推断，**非官方确认**")
        else:
            status = "unknown"
            reason = (f"证据不足（{n} 项成立 / {unknown_cnt} 项无法判定），"
                      f"无法判定首行是否合成行")

    # ---- 真实历史起点 ----
    if status == "confirmed":
        real_start = d1
        start_note = "由候选自身对照证据确认，第二行即真实起点"
    else:
        real_start = "unknown"
        start_note = ("**未确认**：不得自动把第二行当成真实最早历史行情；"
                      "无独立证据证明真实起点")

    return {
        "status": status,
        "confirmed": status == "confirmed",
        "synthetic_row": d0 if status in ("confirmed", "strong_inference")
        else None,
        "real_history_start": real_start,
        "real_history_start_note": start_note,
        "votes": sum(1 for v in [
            ev["first_equals_request_start"],
            ev["first_not_in_market_calendar"],
            ev["first_close_equals_second"],
            ev["first_before_basic_date"]] if v is True),
        "evidence": ev,
        "control": ctrl,
        "reason": reason,
    }


def _before(d: str | None, basic: str | None) -> bool | None:
    if not d or not basic:
        return None
    try:
        a = datetime.strptime(d, "%Y%m%d")
        b = datetime.strptime(basic.replace("-", ""), "%Y%m%d")
        return a < b
    except Exception:
        return None


# ---------------------------------------------------------------- 休市日分类（保守化）
def classify_outside_calendar(rows: list[dict],
                              outside: list[str]) -> list[dict]:
    """休市日占位行分类：**保守化三态**。

    - `confirmed_market_closed_placeholder`：有官方交易日历/发布规则/足够直接证据
    - `suspected_market_closed_placeholder`：有零成交量、数值重复等特征，但无足够直接证据
    - `unexplained`：无法解释

    **零成交量本身不能证明占位；小幅涨跌本身不能证明占位。**
    """
    iso = {f"{r['tradeDate'][:4]}-{r['tradeDate'][4:6]}-{r['tradeDate'][6:]}": r
           for r in rows if r.get("tradeDate")}
    ordered = sorted(iso)
    out = []
    for d in outside:
        r = iso.get(d) or {}
        vol = r.get("tradingVol")
        pct = r.get("changePct")
        idx = ordered.index(d) if d in ordered else -1
        prev_close = (iso[ordered[idx - 1]].get("close")
                      if idx > 0 else None)
        cur_close = r.get("close")
        same_as_prev = (prev_close is not None and cur_close is not None
                        and abs(float(cur_close) - float(prev_close)) < 1e-9)
        zero_vol = (vol in (0, 0.0))
        tiny_pct = (pct is not None and abs(float(pct)) < 0.5)

        # 本轮**没有**官方交易日历/发布规则证明这些日期为休市占位
        has_official_calendar_evidence = False

        if has_official_calendar_evidence and zero_vol and same_as_prev:
            cls = "confirmed_market_closed_placeholder"
            note = "有官方日历证据 + 零成交 + 数值重复，确认为休市占位"
        elif zero_vol or same_as_prev or tiny_pct:
            cls = "suspected_market_closed_placeholder"
            feats = []
            if zero_vol:
                feats.append("零成交量")
            if same_as_prev:
                feats.append("收盘值与前日完全相同")
            if tiny_pct:
                feats.append(f"changePct={pct}（<0.5）")
            note = (f"具备疑似特征（{'、'.join(feats)}），"
                    f"但**无官方交易日历或发布规则直接证据**，"
                    f"只能列为疑似，**不得当作已证实的休市占位行**")
        else:
            cls = "unexplained"
            note = "无任何休市特征，无法解释"

        out.append({
            "date": d, "classification": cls,
            "trading_vol": vol, "change_pct": pct,
            "close": cur_close, "prev_close": prev_close,
            "same_as_prev": same_as_prev,
            "zero_volume": zero_vol, "tiny_change_pct": tiny_pct,
            "official_calendar_evidence": has_official_calendar_evidence,
            "note": note,
        })
    return out


def continuity_after_classification(base_status: str,
                                    detail: list[dict]) -> tuple[str, str]:
    """根据分类结果决定连续性状态。

    **suspected 不得直接使连续性 verified。**
    """
    if base_status == "unknown":
        return "unknown", "适用日历未取得，连续性 unknown"
    unresolved = [x for x in detail
                  if x["classification"] !=
                  "confirmed_market_closed_placeholder"]
    suspected = [x for x in detail
                 if x["classification"] ==
                 "suspected_market_closed_placeholder"]
    unexplained = [x for x in detail
                   if x["classification"] == "unexplained"]
    if unexplained:
        return "has_issues", f"存在 {len(unexplained)} 个无法解释的日历外日期"
    if suspected:
        return "has_unresolved_suspicion", (
            f"存在 {len(suspected)} 个疑似休市占位行，"
            f"**无官方日历证据，不得判为 verified**")
    if unresolved:
        return "has_issues", "存在未解决的日历外日期"
    return "verified", "无日历外日期"


# ---------------------------------------------------------------- 逐候选
def audit_candidate(tr_code: str, price_code: str, group: str,
                    cal: set[str]) -> dict:
    tr_rows = load_rows(EVID_OLD / f"hist_{tr_code}_20040101_20261127.json")
    price_rows = load_rows(
        EVID_OLD / f"hist_{price_code}_20040101_20261127.json")
    tr_basic = load_basic(tr_code)
    price_basic = load_basic(price_code)

    synth = detect_synthetic_start(tr_code, tr_rows, cal, tr_basic)

    # 质量与覆盖：**不把「真实起点 unknown」等同于「覆盖 unknown」**
    # 覆盖率只依赖适用日历；真实起点未知时用第二行作为保守起点，
    # 但明确标注 `coverage_anchor=second_row_unconfirmed`
    from scripts.audit_3b6_2_3_1_0_1_fix import audit_quality
    synth_for_quality = dict(synth)
    if synth.get("real_history_start") == "unknown":
        second = (tr_rows[1].get("tradeDate") if len(tr_rows) > 1 else None)
        synth_for_quality["real_history_start"] = (
            second if second else "unknown")
        synth_for_quality["coverage_anchor"] = (
            "second_row_unconfirmed"
            if second else "none")
    else:
        synth_for_quality["coverage_anchor"] = "confirmed_by_own_control"
    q = audit_quality(tr_code, tr_rows, cal, group=group,
                      synth=synth_for_quality)
    q["coverage_anchor"] = synth_for_quality["coverage_anchor"]
    q["coverage_anchor_note"] = (
        "覆盖核验起点为第二行，但**第二行未被确认为真实历史起点**；"
        "覆盖率结论仅表示「自该行起相对日历无缺失」，"
        "不代表真实历史起点已确认"
        if synth_for_quality["coverage_anchor"] == "second_row_unconfirmed"
        else "覆盖核验起点已由候选自身对照证据确认")

    # 用保守分类重算连续性
    outside = q.get("dates_outside_calendar_sample") or []
    if q["coverage_status"] == "unknown":
        detail = []
        cont, cont_note = "unknown", "适用日历未取得"
    else:
        detail = classify_outside_calendar(tr_rows, outside)
        cont, cont_note = continuity_after_classification(
            q["coverage_status"], detail)

    return {
        "tr_candidate": tr_code,
        "price_index": price_code,
        "group": group,
        "market": MARKET_CALENDAR[group]["market"],
        "calendar_used": MARKET_CALENDAR[group]["calendar"],
        "calendar_available": MARKET_CALENDAR[group]["calendar_available"],
        "synthetic_start_detection": synth,
        "quality": {**q,
                    "continuity_status": cont,
                    "continuity_note": cont_note,
                    "outside_calendar_detail": detail},
    }


# ---------------------------------------------------------------- 汇总与 manifest
def summarize(cands: list[dict]) -> dict:
    def cnt(rs, pred):
        return sum(1 for r in rs if pred(r))

    def status_cnt(rs, st):
        return sum(1 for r in rs
                   if r["synthetic_start_detection"]["status"] == st)

    groups = {}
    for g in ("stock", "bond", "hk"):
        rs = [r for r in cands if r["group"] == g]
        groups[g] = {
            "candidate_count": len(rs),
            "market": MARKET_CALENDAR[g]["market"],
            "calendar_available": MARKET_CALENDAR[g]["calendar_available"],
            "synthetic_confirmed": status_cnt(rs, "confirmed"),
            "synthetic_strong_inference": status_cnt(rs, "strong_inference"),
            "synthetic_unknown": status_cnt(rs, "unknown"),
            "tr_candidate_control_available": cnt(
                rs, lambda r: r["synthetic_start_detection"]["control"][
                    "tr_candidate_control"]["available"]),
            "price_index_control_available": cnt(
                rs, lambda r: r["synthetic_start_detection"]["control"][
                    "price_index_control"]["available"]),
            "real_history_start_unknown": cnt(
                rs, lambda r: r["synthetic_start_detection"][
                    "real_history_start"] == "unknown"),
            "continuity_verified": cnt(
                rs, lambda r: r["quality"]["continuity_status"] == "verified"),
            "continuity_has_unresolved_suspicion": cnt(
                rs, lambda r: r["quality"]["continuity_status"]
                == "has_unresolved_suspicion"),
            "continuity_unknown": cnt(
                rs, lambda r: r["quality"]["continuity_status"] == "unknown"),
        }

    return {
        "total_candidates": len(cands),
        "groups": groups,
        "totals": {
            "synthetic_confirmed": status_cnt(cands, "confirmed"),
            "synthetic_strong_inference": status_cnt(
                cands, "strong_inference"),
            "synthetic_unknown": status_cnt(cands, "unknown"),
            "tr_candidate_control_available": cnt(
                cands, lambda r: r["synthetic_start_detection"]["control"][
                    "tr_candidate_control"]["available"]),
            "price_index_control_available": cnt(
                cands, lambda r: r["synthetic_start_detection"]["control"][
                    "price_index_control"]["available"]),
            "real_history_start_unknown": cnt(
                cands, lambda r: r["synthetic_start_detection"][
                    "real_history_start"] == "unknown"),
        },
        "gates": {
            "ready_for_research_analysis": True,
            "ready_for_backtest": False,
            "ready_for_formal_ranking": False,
            "ready_for_3b6_2_3_1_series_build": False,
        },
        "_self_check": {
            "no_candidate_has_own_control": cnt(
                cands, lambda r: r["synthetic_start_detection"]["control"][
                    "tr_candidate_control"]["available"]) == 0,
            "price_controls_found": cnt(
                cands, lambda r: r["synthetic_start_detection"]["control"][
                    "price_index_control"]["available"]) >= 10,
            "no_confirmed_without_own_control": all(
                r["synthetic_start_detection"]["status"] != "confirmed"
                for r in cands),
            "real_start_unknown_when_not_confirmed": all(
                r["synthetic_start_detection"]["real_history_start"]
                == "unknown"
                for r in cands
                if r["synthetic_start_detection"]["status"] != "confirmed"),
            "bond_hk_no_a_calendar_evidence": all(
                r["synthetic_start_detection"]["evidence"][
                    "first_not_in_market_calendar"] is None
                for r in cands if r["group"] in ("bond", "hk")),
            "no_continuity_verified_with_suspicion": all(
                r["quality"]["continuity_status"] != "verified"
                for r in cands
                if any(x["classification"] ==
                       "suspected_market_closed_placeholder"
                       for x in r["quality"]["outside_calendar_detail"])),
        },
    }


def build_manifest(cands: list[dict]) -> dict:
    """引用式 manifest：**包含本轮实际读取的对照文件**（含缺失记录）。"""
    EVID.mkdir(parents=True, exist_ok=True)
    ref = {}

    def _add(path: Path, purpose: str) -> None:
        name = path.name
        if path.exists():
            raw = path.read_bytes()
            ref[name] = {
                "relative_path":
                    str(path.relative_to(ROOT)).replace("\\", "/"),
                "purpose": purpose,
                "exists": True,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        else:
            ref[name] = {
                "relative_path":
                    str(path.relative_to(ROOT)).replace("\\", "/"),
                "purpose": purpose,
                "exists": False,
                "bytes": None,
                "sha256": None,
            }

    # 1) 全收益候选历史 + 基本信息
    for r in cands:
        tr = r["tr_candidate"]
        _add(EVID_OLD / f"hist_{tr}_20040101_20261127.json", "候选历史行情")
        _add(EVID_OLD / f"basic_{tr}.json", "候选官方基本信息")
    # 2) 原价格指数历史 + 基本信息
    for price in {r["price_index"] for r in cands}:
        _add(EVID_OLD / f"hist_{price}_20040101_20261127.json", "原指数历史行情")
        _add(EVID_OLD / f"basic_{price}.json", "原指数官方基本信息")
    # 3) 原价格指数对照文件
    for price in {r["price_index"] for r in cands}:
        _add(EVID_OLD4 / f"csindex_ctrl_{price}_from20040102.json",
             "原价格指数对照请求")
    # 4) 全收益候选自身对照（本轮全部缺失，必须显式记录）
    for r in cands:
        _add(EVID_OLD4 / f"csindex_ctrl_{r['tr_candidate']}_from20040102.json",
             "全收益候选自身对照请求")

    # 5) 与 3B-6.2.3.0.4 原始 manifest 核对
    old_manifest = EVID_OLD4 / "manifest.json"
    old_files = {}
    if old_manifest.exists():
        try:
            old_files = (json.loads(old_manifest.read_text(
                encoding="utf-8")).get("files") or {})
        except Exception:
            old_files = {}
    for name, info in ref.items():
        if not info["exists"]:
            info["original_manifest_sha256"] = None
            info["manifest_verified"] = None
            continue
        om = old_files.get(name)
        if om is None:
            # 属于 3B-6.2.3.1.0 而非 0.4 的文件
            old1 = EVID_OLD / "manifest.json"
            if old1.exists():
                try:
                    m1 = json.loads(old1.read_text(encoding="utf-8"))
                    om = (m1.get("files") or {}).get(name)
                except Exception:
                    om = None
        info["original_manifest_sha256"] = (om or {}).get("sha256")
        if info["original_manifest_sha256"] is None:
            info["manifest_verified"] = None
            info["manifest_note"] = (
                "**缺少原始 manifest 校验**，只有本轮计算的 SHA256，"
                "不能声称三方一致")
        else:
            info["manifest_verified"] = (
                info["original_manifest_sha256"] == info["sha256"])

    exists = sum(1 for v in ref.values() if v["exists"])
    missing = [k for k, v in ref.items() if not v["exists"]]
    verified = sum(1 for v in ref.values() if v.get("manifest_verified") is True)
    no_orig = sum(1 for v in ref.values()
                  if v["exists"] and v.get("manifest_verified") is None)

    doc = {
        "phase": "3B-6.2.3.1.0.2",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "no_new_download": True,
        "note": ("本轮不产生新的官方原始响应；"
                 "manifest 记录**实际读取**的全部文件（含对照文件）"),
        "referenced_total": len(ref),
        "referenced_exists": exists,
        "referenced_missing": missing,
        "missing_count": len(missing),
        "manifest_verified_count": verified,
        "no_original_manifest_count": no_orig,
        "files": ref,
    }
    (EVID / "manifest.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {
        "referenced_total": len(ref),
        "referenced_exists": exists,
        "missing_count": len(missing),
        "missing_files": missing,
        "manifest_verified_count": verified,
        "no_original_manifest_count": no_orig,
        "manifest_file": str((EVID / "manifest.json").relative_to(ROOT))
        .replace("\\", "/"),
    }

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
        print(f"db_sha256={before['database_sha256']}")
        print(f"A股日历 {len(cal)} 天\n")

        cands = []
        for g, mp in (("stock", STOCK_TR_CANDIDATES),
                      ("bond", BOND_INDEXES), ("hk", HK_INDEXES)):
            for price_code, trs in mp.items():
                for tr in trs:
                    r = audit_candidate(tr, price_code, g, cal)
                    cands.append(r)
                    s = r["synthetic_start_detection"]
                    print(f"  [{g:5s}] {tr:14s}<-{price_code:8s} "
                          f"status={s['status']:16s} "
                          f"votes={s['votes']} "
                          f"start={str(s['real_history_start'])[:10]:10s} "
                          f"cont={r['quality']['continuity_status']}")

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

    summary = summarize(cands)
    result = {
        "phase": "3B-6.2.3.1.0.2",
        "task": "全收益候选合成行证据溯源与休市日分类保守化",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "baseline_head": "35f056c8aefe1408e239d1e5b226d8c5531c86b0",
        "read_only": True,
        "no_redownload": True,
        "fixes": {
            "1_control_file_mapping": (
                "对照文件按**原价格指数代码**查找；"
                "并严格区分 price_index_control 与 tr_candidate_control"),
            "2_synthetic_status_levels": [
                "confirmed", "strong_inference", "unknown"],
            "3_control_files_in_manifest":
                "所有实际读取的对照文件纳入引用式 manifest（含缺失记录）",
            "4_closed_day_conservative": [
                "confirmed_market_closed_placeholder",
                "suspected_market_closed_placeholder", "unexplained"],
        },
        "db_before": before,
        "db_after": after,
        "db_unchanged": before["database_sha256"] == after["database_sha256"],
        "candidates": cands,
    }
    result["summary"] = summary
    result["evidence_manifest"] = build_manifest(cands)

    (REPORTS / "phase3B6_2_3_1_0_2_audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")

    print("\n=== 汇总 ===")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"\n数据库未变: {result['db_unchanged']}")


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()
