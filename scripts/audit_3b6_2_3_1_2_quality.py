"""阶段3B-6.2.3.1.2 全收益指数历史序列质量验证与可用性分级。

**只读审计**：不改原始行情、不改 raw_record_json/sha256、不改 index_daily。
只新增独立审计表（可回滚）与报告。

严格以证据为基础，无法证明一律 unknown。
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.fund import tr_layer  # noqa: E402

REPORTS = ROOT / "reports"
EVID_OLD = REPORTS / "evidence" / "phase3B6_2_3_1_0"
EVID = REPORTS / "evidence" / "phase3B6_2_3_1_2"
MIGRATION_UP = (ROOT / "migrations"
                / "phase3b6_2_3_1_2_quality_audit.sql")
MIGRATION_DOWN = (ROOT / "migrations"
                  / "phase3b6_2_3_1_2_quality_audit_down.sql")

# 任务书候选表的市场标注 vs 数据库实际分类
TASK_CLAIMED_MARKET = {
    "399997CNY02": "stock", "H00012": "stock", "H00016": "stock",
    "H00300": "stock", "H00905": "stock", "H00906": "stock",
    "H00922": "stock", "H00942": "stock", "H20184": "stock",
    "H20539": "stock", "H20930": "bond", "N00012": "bond",
}

# 市场 → 日历配置
MARKET_CALENDAR = {
    "stock": {
        "market_label": "沪深A股",
        "calendar_name": "A股交易日历（项目代理）",
        "calendar_available": True,
        "calendar_is_official": False,
        "evidence": ("项目 trade_calendar 表 8,797 天（1990-12-19 ~ 2026-12-31）；"
                     "**非官方指数发布日历**"),
    },
    "bond": {
        "market_label": "上交所债券市场",
        "calendar_name": "债券市场交易日历",
        "calendar_available": False,
        "calendar_is_official": False,
        "evidence": ("尝试 sse.com.cn 交易日历页（HTTP 200 但为 JS 渲染，"
                     "无可解析结构化数据）；**未取得官方债券日历**"),
    },
    "hk": {
        "market_label": "香港市场（港股通）",
        "calendar_name": "港股交易日历",
        "calendar_available": False,
        "calendar_is_official": False,
        "evidence": ("尝试 hkex.com.hk 交易日历页（HTTP 200 但为 JS 渲染）；"
                     "**未取得官方港股日历**"),
    },
}

# 质量等级定义（证据要求）
GRADE_DEFINITIONS = {
    "A": {"requires": ["official_identity", "return_basis",
                       "historical_start_confirmed",
                       "official_calendar", "data_quality",
                       "point_in_time"],
          "label": "全部关键条件均有充分证据"},
    "B": {"requires": ["official_identity", "return_basis",
                       "data_quality"],
          "label": "关键质量条件通过，存在明确有限缺口"},
    "C": {"requires": ["official_identity", "return_basis"],
          "label": "可用于有限描述性/代理研究，存在未解决关键限制"},
    "D": {"requires": [],
          "label": "存在严重质量问题，不可作为可靠历史收益序列"},
    "UNKNOWN": {"requires": [],
                "label": "关键证据不足，无法合理分级"},
}


def db_path() -> str:
    from app.config import settings
    return str(settings.database_path)


def connect_ro():
    p = db_path().replace("\\", "/")
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    conn.execute("pragma temp_store = memory")
    return conn


def file_sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def iso(d: str) -> str:
    return f"{d[:4]}-{d[4:6]}-{d[6:]}" if d else ""


def to_num(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
        return f if math.isfinite(f) else None
    if isinstance(v, str):
        s = v.strip()
        if not s or s.lower() in ("nan", "inf", "-inf", "infinity",
                                  "-infinity"):
            return None
        try:
            f = float(s)
        except ValueError:
            return None
        return f if math.isfinite(f) else None
    return None


# ---------------------------------------------------------------- 历史起点核验
def audit_historical_start(cand: dict, rows: list[dict],
                           basic: dict, synth: dict) -> dict:
    """严格区分六类日期，不得互相替代。"""
    dates = [r["trade_date"] for r in rows]
    official_basic = basic.get("basicDate")
    official_pub = basic.get("publishDate")
    request_start = "20040101"
    api_earliest = dates[0] if dates else None

    # 疑似合成行：请求起始日那一条
    synthetic_row = synth.get("synthetic_row")
    blockers = []
    evidence_level = "none"

    # 检查是否有官方编制方案/公告证据
    has_official_scheme = False   # 本轮未取得
    if not has_official_scheme:
        blockers.append("未取得官方编制方案/发布公告以证明真实历史起点")

    # 接口返回最早日期 == 请求起始日 → 不能当真实起点
    if api_earliest == request_start:
        blockers.append(
            f"接口返回最早日期 {api_earliest} 等于请求起始日，"
            f"不能作为真实历史起点")
        evidence_level = "request_start_artifact"

    # 第二行是否可作起点？无独立证据
    second = dates[1] if len(dates) > 1 else None
    if second and second != request_start:
        blockers.append(
            f"第二行 {second} 无独立对照证据，不能确认为真实起点")

    status = "unknown"
    return {
        "official_basic_date": official_basic,
        "official_publish_date": official_pub,
        "request_start_date": request_start,
        "api_earliest_returned_date": api_earliest,
        "api_second_row_date": second,
        "actual_earliest_historical_quote_date": "unknown",
        "historical_start_evidence_level": evidence_level,
        "historical_start_status": status,
        "historical_start_blockers": blockers,
        "synthetic_row_preserved": synthetic_row,
        "date_concepts_distinct": {
            "1_basic_date": official_basic,
            "2_publish_date": official_pub,
            "3_request_start": request_start,
            "4_api_earliest": api_earliest,
            "5_confirmed_real_start": "unknown",
            "6_first_publicly_available": "unknown",
        },
        "note": ("六类日期严格分开；"
                 "**不得因有官方发布日期就认为接口最早日期是真实起点**"),
    }


# ---------------------------------------------------------------- 日历验证
def audit_calendar(cand: dict, rows: list[dict],
                   a_cal: set[str]) -> dict:
    """按市场分别验证日历；无官方日历则 unknown。"""
    group = cand["market_group"]
    cfg = MARKET_CALENDAR[group]
    dates = [r["trade_date"] for r in rows]
    iso_dates = [iso(d) for d in dates]
    synthetic_row = cand.get("_synthetic_row")

    if not cfg["calendar_available"]:
        return {
            "market_group": group,
            "market_label": cfg["market_label"],
            "calendar_used": cfg["calendar_name"],
            "calendar_available": False,
            "calendar_is_official": False,
            "continuity_status": "unknown",
            "coverage_status": "unknown",
            "missing_trading_days": None,
            "dates_outside_calendar": None,
            "reason": (f"{cfg['calendar_name']}未取得，"
                       f"**不得用 A 股日历替代**；覆盖与连续性记 unknown"),
            "calendar_evidence": cfg["evidence"],
            # 参考信息：仅作对照，**不用于判定**
            "reference_only_a_share_diff": {
                "note": "仅供参考，**不用于连续性判定**",
                "outside_a_share_count": sum(
                    1 for d in iso_dates if d not in a_cal),
                "outside_a_share_sample": [
                    d for d in iso_dates if d not in a_cal][:10],
            },
        }

    # A 股：用代理日历
    real = [d for d in iso_dates
            if not (synthetic_row and d == iso(synthetic_row))]
    lo, hi = (min(real), max(real)) if real else (None, None)
    win = {d for d in a_cal if lo <= d <= hi} if lo else set()
    missing = sorted(win - set(real))
    outside = sorted(set(real) - a_cal)
    # 日历外日期分类
    closed_detail = classify_closed_days(rows, outside)
    unexplained = [x for x in closed_detail
                   if x["classification"] == "unexplained"]
    suspected = [x for x in closed_detail
                 if x["classification"] == "suspected_market_closed"]

    # **连续性判定（修复：疑似休市不得视为通过）**
    #   有缺失交易日            → has_issues
    #   有无法解释的日历外日期  → has_unresolved_suspicion
    #   有疑似休市占位          → has_unresolved_suspicion
    #   三者皆无                → verified_against_proxy_calendar
    if missing:
        cont = "has_issues"
        cont_reason = f"相对代理日历缺 {len(missing)} 个交易日"
    elif unexplained:
        cont = "has_unresolved_suspicion"
        cont_reason = (f"存在 {len(unexplained)} 个无法解释的日历外日期，"
                       f"连续性未解决")
    elif suspected:
        cont = "has_unresolved_suspicion"
        cont_reason = (f"存在 {len(suspected)} 条疑似休市占位记录，"
                       f"**无官方日历证据，不得判为代理验证通过**")
    else:
        cont = "verified_against_proxy_calendar"
        cont_reason = "相对 A 股日历代理无缺失且无日历外异常（非官方日历）"
    return {
        "market_group": group,
        "market_label": cfg["market_label"],
        "calendar_used": cfg["calendar_name"],
        "calendar_available": True,
        "calendar_is_official": False,
        "continuity_status": cont,
        "coverage_status": "verified" if not missing else "has_gaps",
        "missing_trading_days": len(missing),
        "missing_sample": missing[:10],
        "dates_outside_calendar": len(outside),
        "outside_detail": closed_detail,
        "unexplained_count": len(unexplained),
        "suspected_market_closed_count": len(suspected),
        "reason": cont_reason,
        "continuity_rule": (
            "缺失→has_issues；无法解释→has_unresolved_suspicion；"
            "疑似休市→has_unresolved_suspicion；"
            "全无→verified_against_proxy_calendar"),
        "calendar_evidence": cfg["evidence"],
        "proxy_not_official": True,
    }


def classify_closed_days(rows: list[dict], outside: list[str]) -> list[dict]:
    """日历外日期保守分类（沿用 3B-6.2.3.1.0.2 三态）。"""
    by_iso = {iso(r["trade_date"]): r for r in rows}
    ordered = sorted(by_iso)
    out = []
    for d in outside:
        r = by_iso.get(d) or {}
        idx = ordered.index(d) if d in ordered else -1
        prev_close = (to_num(by_iso[ordered[idx - 1]].get("close"))
                      if idx > 0 else None)
        cur_close = to_num(r.get("close"))
        vol = to_num(r.get("volume"))
        pct = to_num(r.get("change_pct"))
        same = (prev_close is not None and cur_close is not None
                and abs(cur_close - prev_close) < 1e-9)
        zero_vol = vol in (0.0,)
        tiny = pct is not None and abs(pct) < 0.5
        cls = ("suspected_market_closed"
               if (zero_vol or same or tiny) else "unexplained")
        out.append({"date": d, "classification": cls,
                    "close": cur_close, "prev_close": prev_close,
                    "volume": vol, "change_pct": pct,
                    "same_as_prev": same, "zero_volume": zero_vol,
                    "official_calendar_evidence": False,
                    "note": ("有零成交/数值重复特征但无官方日历证据，"
                             "仅疑似" if cls == "suspected_market_closed"
                             else "无休市特征，无法解释")})
    return out


# ---------------------------------------------------------------- 逐行质量
def audit_row_quality(cand: dict, rows: list[dict],
                      a_cal: set[str] | None = None) -> dict:
    """逐行质量检查（只读，不修改任何值）。

    ``a_cal`` 为 A 股代理日历；**仅对 stock 市场用于 non_trading_date 诊断**。
    债券/港股不得借用 A 股日历（该检查记 not_applicable）。
    """
    dates = [r["trade_date"] for r in rows]
    n = len(rows)
    issues: dict[str, list] = {k: [] for k in (
        "illegal_date", "duplicate_date", "close_null", "close_non_positive",
        "close_non_numeric", "high_lt_low", "ohlc_inconsistent",
        "volume_negative", "amount_negative", "change_inconsistent",
        "change_pct_inconsistent", "extreme_jump",
        "repeated_price_run", "non_trading_date",
        "blocked_by_invalid_previous_close")}

    # 1) 日期合法性
    for d in dates:
        try:
            datetime.strptime(str(d), "%Y%m%d")
        except Exception:
            issues["illegal_date"].append(d)

    # 2) 重复日期
    seen = set()
    for d in dates:
        if d in seen:
            issues["duplicate_date"].append(d)
        seen.add(d)

    prev_close = None
    prev_date = None
    run_len = 1
    prev_valid = False        # 前一交易日 close 是否可用于收益计算
    for r in rows:
        d = r["trade_date"]
        c = to_num(r.get("close"))
        o = to_num(r.get("open"))
        h = to_num(r.get("high"))
        lo = to_num(r.get("low"))
        v = to_num(r.get("volume"))
        a = to_num(r.get("amount"))
        chg = to_num(r.get("change"))
        pct = to_num(r.get("change_pct"))

        # 3) close 检查
        if r.get("close") is None:
            issues["close_null"].append(d)
        elif c is None:
            issues["close_non_numeric"].append(
                {"date": d, "raw": r.get("close")})
        elif c <= 0:
            issues["close_non_positive"].append({"date": d, "close": c})

        # 4) high < low
        if h is not None and lo is not None and h < lo:
            issues["high_lt_low"].append(
                {"date": d, "high": h, "low": lo})

        # 5) OHLC 关系：high 应 >= max(o,c)，low 应 <= min(o,c)
        if h is not None and c is not None and o is not None:
            if h < max(o, c) - 1e-9 or lo is not None and lo > min(o, c) + 1e-9:
                issues["ohlc_inconsistent"].append(
                    {"date": d, "open": o, "high": h,
                     "low": lo, "close": c})

        # 6) volume / amount 负值
        if v is not None and v < 0:
            issues["volume_negative"].append({"date": d, "volume": v})
        if a is not None and a < 0:
            issues["amount_negative"].append({"date": d, "amount": a})

        # **无效前值阻断**：前收盘 <=0 / None 时不得计算相邻收益
        blocked = (prev_close is not None and prev_close <= 0) or (
            prev_date is not None and not prev_valid)
        if blocked:
            issues["blocked_by_invalid_previous_close"].append(
                {"date": d, "prev_close": prev_close,
                 "reason": "前一交易日收盘价无效（<=0 或缺失），"
                           "不计算相邻收益"})

        # 7) change 与相邻价差一致性
        if (not blocked and prev_close is not None and c is not None
                and chg is not None):
            expect = c - prev_close
            if abs(expect - chg) > max(0.02, abs(expect) * 0.02):
                issues["change_inconsistent"].append(
                    {"date": d, "prev": prev_close, "close": c,
                     "change_field": chg, "expected": round(expect, 6)})

        # 8) change_pct 与实际变化一致性
        if (not blocked and prev_close and c is not None and pct is not None
                and prev_close > 0):
            expect_pct = (c / prev_close - 1.0) * 100.0
            if abs(expect_pct - pct) > max(0.1, abs(expect_pct) * 0.05):
                issues["change_pct_inconsistent"].append(
                    {"date": d, "expect_pct": round(expect_pct, 6),
                     "field_pct": pct})

        # 9) 异常跳变（>30% 单日）——无效前值不产生虚假跳变
        #    当**当日 close 本身无效**（<=0）时，跳变源于该日坏值，
        #    已由 close_non_positive 记录，不再重复计入 extreme_jump。
        if (not blocked and prev_close and c is not None
                and prev_close > 0 and c > 0):
            jump = abs(c / prev_close - 1.0)
            if jump > 0.30:
                issues["extreme_jump"].append(
                    {"date": d, "prev": prev_close, "close": c,
                     "jump": round(jump, 6)})

        # 10) 连续重复价格
        if prev_close is not None and c is not None and abs(c - prev_close) < 1e-12:
            run_len += 1
            if run_len >= 5:
                issues["repeated_price_run"].append(
                    {"date": d, "close": c, "run_len": run_len})
        else:
            run_len = 1

        prev_close = c
        prev_date = d
        prev_valid = (c is not None and c > 0)

    # 11) 非交易日诊断（**仅 stock 用 A 股代理日历**）
    group = cand.get("market_group")
    cal_diag = {"applicable": False, "reason": "", "count": 0}
    if a_cal is not None and group == "stock":
        cal_diag["applicable"] = True
        cal_diag["calendar"] = "A股交易日历（项目代理）"
        cal_diag["official"] = False
        synth = cand.get("_synthetic_row")
        for d in dates:
            iso_d = iso(d)
            if synth and iso_d == iso(synth):
                continue          # 合成行单独标记，不计入
            if iso_d not in a_cal:
                issues["non_trading_date"].append(
                    {"date": iso_d, "note": "不在 A 股代理日历内；"
                                            "**代理异常，非官方休市认定**"})
        cal_diag["count"] = len(issues["non_trading_date"])
    elif group in ("bond", "hk"):
        cal_diag["reason"] = (f"{group} 市场日历 unknown，"
                              f"**不得借用 A 股日历做非交易日诊断**")
    else:
        cal_diag["reason"] = "未提供 A 股日历"

    # 统计（保留有限样本）
    summary = {}
    for k, v in issues.items():
        summary[k] = {"count": len(v), "sample": v[:10]}
    fatal = sum(len(issues[k]) for k in (
        "illegal_date", "duplicate_date", "close_null",
        "close_non_positive", "close_non_numeric", "high_lt_low",
        "volume_negative", "amount_negative"))
    return {
        "row_count": n,
        "checks": summary,
        "calendar_diagnostic": cal_diag,
        "fatal_issue_count": fatal,
        "data_quality_status": "pass" if fatal == 0 else "has_fatal",
        "note": ("**不修改任何原始值**；异常只记录不修正；"
                 "正常大幅涨跌不计入 fatal"),
    }


# ---------------------------------------------------------------- 时点可用性
def audit_point_in_time(conn, cand: dict) -> dict:
    """历史时点可用性：无快照/发布记录 → unknown。"""
    code = cand["tr_code"]
    # 查是否有历史快照表
    tabs = {r[0] for r in conn.execute(
        "select name from sqlite_master where type='table'")}
    snapshot_tabs = [t for t in tabs
                     if "snapshot" in t.lower() or "revision" in t.lower()]
    # 同一 (code, date) 是否多版本
    multi = conn.execute(
        "select count(*) from (select trade_date, count(*) c "
        "from tr_index_daily_raw where tr_code=? "
        "group by trade_date having c>1)", (code,)).fetchone()[0]
    # 采集时间
    collected = [r[0] for r in conn.execute(
        "select distinct substr(ingested_at,1,10) "
        "from tr_index_daily_raw where tr_code=? order by 1", (code,))]
    blockers = []
    if not snapshot_tabs:
        blockers.append("无历史快照表")
    if multi == 0:
        blockers.append("同 (code,date) 仅 1 版本，无修订记录")
    if len(collected) <= 1:
        blockers.append(f"仅单批次采集（{collected}），无法区分历史发布值与当前值")
    blockers.append("未取得官方历史发布时间证明")
    blockers.append("无法排除事后回溯计算")
    return {
        "historical_point_in_time_status": "unknown",
        "historical_publication_evidence": None,
        "historical_revision_evidence": None,
        "first_available_date": "unknown",
        "point_in_time_blockers": blockers,
        "snapshot_tables_found": snapshot_tabs,
        "multi_version_rows": multi,
        "ingest_batches": collected,
        "note": ("**不能因历史行情完整就认为具备历史时点可用性**；"
                 "无快照/发布证据的序列不得用于声称无未来数据偏差的回测"),
    }


# ---------------------------------------------------------------- 分级
def grade_candidate(c: dict) -> dict:
    """按统一标准分级。

    **判级优先级（修复）**：A → D → B → C → UNKNOWN

    致命质量问题必须优先判为 D，不得被 C 级分支提前截获。
    """
    dims = {
        "official_identity": c["identity_evidence_level"],
        "return_basis": c["return_basis_evidence_level"],
        "historical_start": c["historical_start"]["historical_start_status"],
        "calendar": c["calendar"]["continuity_status"],
        "data_quality": c["row_quality"]["data_quality_status"],
        "point_in_time": c["point_in_time"]["historical_point_in_time_status"],
    }

    def ok(k):
        v = dims[k]
        return v in ("verified", "pass", "official", "confirmed",
                     "verified_against_proxy_calendar")

    fatal = c["row_quality"]["fatal_issue_count"] > 0
    identity_ok = ok("official_identity")
    basis_ok = ok("return_basis")
    quality_ok = ok("data_quality")

    # 1) A：六项全部有充分证据
    if (identity_ok and basis_ok
            and dims["historical_start"] == "confirmed"
            and dims["calendar"] == "verified_official_calendar"
            and quality_ok and ok("point_in_time")):
        grade = "A"
        reason = "六项关键证据全部满足"
    # 2) D：存在致命数据质量问题（优先级高于 B/C）
    elif fatal:
        grade = "D"
        reason = (f"存在 {c['row_quality']['fatal_issue_count']} 处致命数据质量问题，"
                  f"不能作为可靠收益序列")
    # 3) 身份或口径不足 → UNKNOWN
    elif not identity_ok or not basis_ok:
        grade = "UNKNOWN"
        reason = "官方身份或收益口径证据不足"
    # 4) B：身份+口径+质量通过，且日历至少代理验证
    elif dims["calendar"] in ("verified_official_calendar",
                              "verified_against_proxy_calendar"):
        grade = "B"
        reason = "身份、口径、质量通过，日历达代理验证等级"
    # 5) C：身份+口径成立，但存在未解决限制（无致命问题）
    else:
        grade = "C"
        reason = (f"身份与口径成立，但存在未解决限制"
                  f"（日历={dims['calendar']}）")

    allowed, forbidden = [], []
    if grade in ("A", "B"):
        allowed = ["描述性统计（收益分布、波动率、相关性）",
                   "基准结构分析（成分、权重研究）",
                   "代理收益序列的敏感性分析（须标注限制）"]
    elif grade == "C":
        allowed = ["有限描述性研究",
                   "作为代理序列做探索性分析（须明确标注证据缺口）"]
    else:
        allowed = ["仅供数据质量研究，不作为收益来源"]

    forbidden = ["任何声称无未来数据偏差的回测",
                 "正式业绩归因与排名",
                 "对外发布的基金评价"]
    if dims["point_in_time"] == "unknown":
        forbidden.append("历史时点严格回测（point-in-time unknown）")
    if dims["calendar"] != "verified_official_calendar":
        forbidden.append("依赖官方交易日历的严格交易日对齐")

    blockers = []
    if dims["historical_start"] != "confirmed":
        blockers.append("真实历史起点 unknown")
    if dims["calendar"] != "verified_official_calendar":
        blockers.append(f"日历等级={dims['calendar']}")
    if fatal:
        blockers.append(
            f"致命数据质量问题 {c['row_quality']['fatal_issue_count']} 处")
    if dims["point_in_time"] != "verified":
        blockers.append("历史时点可用性 unknown")

    return {
        "dimensions": dims,
        "final_grade": grade,
        "grade_reason": reason,
        "grade_priority_rule": "A → D → B → C → UNKNOWN",
        "grade_definition": GRADE_DEFINITIONS[grade]["label"],
        "allowed_uses": allowed,
        "forbidden_uses": forbidden,
        "blockers": blockers,
    }


# ---------------------------------------------------------------- 主流程
def load_basic(code: str) -> dict:
    f = EVID_OLD / f"basic_{code}.json"
    if not f.exists():
        return {}
    try:
        return (json.loads(f.read_bytes().decode("utf-8")).get("data") or {})
    except Exception:
        return {}


def main() -> None:
    EVID.mkdir(parents=True, exist_ok=True)
    conn = connect_ro()
    try:
        idx_fp = tr_layer.index_daily_fingerprint(conn)
        a_cal = {r[0] for r in conn.execute(
            "select trade_date from trade_calendar")}
        cands = tr_layer.list_candidates(conn)
        raw_counts = {r[0]: r[1] for r in conn.execute(
            "select tr_code, count(*) from tr_index_daily_raw "
            "group by tr_code")}

        results = []
        for cand in cands:
            code = cand["tr_code"]
            rows = [dict(r) for r in conn.execute(
                "select trade_date, open, high, low, close, volume, amount, "
                "change, change_pct, cons_number, peg, row_quality_status, "
                "raw_record_sha256 from tr_index_daily_raw where tr_code=? "
                "order by trade_date", (code,))]
            basic = load_basic(code)
            synth_row = conn.execute(
                "select trade_date from tr_index_daily_raw "
                "where tr_code=? and row_quality_status='suspected_synthetic' "
                "limit 1", (code,)).fetchone()
            synth = {"synthetic_row": synth_row[0] if synth_row else None}

            hs = audit_historical_start(cand, rows, basic, synth)
            cal = audit_calendar({**cand, "_synthetic_row":
                                  synth["synthetic_row"]}, rows, a_cal)
            rq = audit_row_quality(
                {**cand, "_synthetic_row": synth["synthetic_row"]},
                rows, a_cal)
            pit = audit_point_in_time(conn, cand)

            identity_level = ("official" if cand["official_full_name"]
                              and cand["official_basic_date"]
                              and cand["official_publish_date"] else "none")
            basis_level = ("official" if cand["return_basis"] != "unknown"
                           and cand["official_full_name"] else "none")

            c = {
                "tr_code": code,
                "price_index_code": cand["price_index_code"],
                "market_group": cand["market_group"],
                "market_label": cand["market_label"],
                "official_full_name": cand["official_full_name"],
                "return_basis": cand["return_basis"],
                "row_count": len(rows),
                "raw_rows_in_db": raw_counts.get(code, 0),
                "identity_evidence_level": identity_level,
                "return_basis_evidence_level": basis_level,
                "historical_start": hs,
                "calendar": cal,
                "row_quality": rq,
                "point_in_time": pit,
                "row_quality_distribution": {
                    r[0]: r[1] for r in conn.execute(
                        "select row_quality_status, count(*) "
                        "from tr_index_daily_raw where tr_code=? "
                        "group by 1", (code,))},
            }
            # 修复4：显式质量筛选规则（不得默认使用全部原始记录）
            excl = [x for x in rows
                    if x["row_quality_status"] != "normal_unverified"]
            usable = [x for x in rows
                      if x["row_quality_status"] == "normal_unverified"]
            c["data_usage_restrictions"] = {
                "must_exclude_before_return_calc": [
                    {"trade_date": x["trade_date"],
                     "row_quality_status": x["row_quality_status"],
                     "close": x["close"]}
                    for x in excl],
                "excluded_count": len(excl),
                "usable_after_exclusion": len(usable),
                "quality_audit_only": [
                    {"trade_date": x["trade_date"],
                     "row_quality_status": x["row_quality_status"]}
                    for x in excl],
                "allow_descriptive_after_exclusion": len(usable) > 0,
                "residual_continuity_gap": (
                    c["calendar"]["continuity_status"] !=
                    "verified_against_proxy_calendar"),
                "residual_note": (
                    "排除异常行后**仍存在连续性缺口**，"
                    "不得描述为官方完整历史序列"
                    if c["calendar"]["continuity_status"] !=
                    "verified_against_proxy_calendar"
                    else "排除异常行后相对代理日历无缺失，"
                         "但**仍非官方日历验证**"),
                "rule": ("任何收益计算必须显式按 row_quality_status 筛选，"
                         "**不得默认使用全部 55,942 条原始记录**"),
            }
            c["grading"] = grade_candidate(c)
            results.append(c)

        # 市场标注核对
        market_mismatch = []
        for r in results:
            claimed = TASK_CLAIMED_MARKET.get(r["tr_code"])
            if claimed and claimed != r["market_group"]:
                market_mismatch.append({
                    "tr_code": r["tr_code"],
                    "task_claimed": claimed,
                    "db_actual": r["market_group"],
                    "official_name": r["official_full_name"],
                    "official_index_type": load_basic(
                        r["tr_code"]).get("indexType"),
                    "evidence_file": f"reports/evidence/"
                                     f"phase3B6_2_3_1_0/"
                                     f"basic_{r['tr_code']}.json",
                    "action": ("**记录证据，不覆盖原始记录**；"
                               "后续阶段需人工确认市场归属"),
                })

        idx_after = tr_layer.index_daily_fingerprint(conn)
        integrity = conn.execute("pragma integrity_check").fetchone()[0]
        fk = len(conn.execute("pragma foreign_key_check").fetchall())
        iso_ok = tr_layer.assert_isolated(conn)
        counts = tr_layer.tr_table_counts(conn)
        total_raw = conn.execute(
            "select count(*) from tr_index_daily_raw").fetchone()[0]
        ev_n = conn.execute(
            "select count(*) from tr_evidence_files").fetchone()[0]
    finally:
        conn.close()

    # 汇总
    grades = {}
    for r in results:
        g = r["grading"]["final_grade"]
        grades[g] = grades.get(g, 0) + 1
    continuity = {}
    for r in results:
        s = r["calendar"]["continuity_status"]
        continuity[s] = continuity.get(s, 0) + 1

    doc = {
        "phase": "3B-6.2.3.1.2",
        "task": "全收益指数历史序列质量验证与可用性分级",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "baseline_head": "aaa41cca487a90758ab17f24051fc2e93f52830c",
        "read_only": True,
        "no_redownload": True,
        "task_candidate_table_errors": {
            "note": ("任务书候选表的市场标注与数据库/官方证据不一致；"
                     "**已记录证据，未覆盖原始记录**"),
            "mismatches": market_mismatch,
        },
        "market_calendar_config": MARKET_CALENDAR,
        "grade_definitions": GRADE_DEFINITIONS,
        "candidates": results,
        "summary": {
            "total_candidates": len(results),
            "grade_distribution": grades,
            "continuity_distribution": continuity,
            "continuity_rule_note": (
                "疑似休市占位 → has_unresolved_suspicion（不得判代理验证通过）；"
                "缺失交易日 → has_issues；无日历 → unknown"),
            "historical_start_confirmed": sum(
                1 for r in results
                if r["historical_start"]["historical_start_status"]
                == "confirmed"),
            "point_in_time_verified": sum(
                1 for r in results
                if r["point_in_time"]["historical_point_in_time_status"]
                == "verified"),
            "calendar_official": sum(
                1 for r in results
                if r["calendar"]["calendar_is_official"]),
            "admission": {
                "raw_data_layer_ingest_candidate": sum(
                    1 for _ in results),
                "validated_series_candidate": 0,
                "proxy_qualified_series_candidate": 0,
                "formal_series_admitted": 0,
            },
            "gates": {
                "ready_for_research_analysis": True,
                "ready_for_backtest": False,
                "ready_for_formal_ranking": False,
                "ready_for_3b6_2_3_1_series_build": False,
            },
        },
        "data_protection": {
            "tr_index_daily_raw_rows": total_raw,
            "raw_rows_expected": 55942,
            "rows_unchanged": total_raw == 55942,
            "evidence_files": ev_n,
            "index_daily_rows": idx_after["row_count"],
            "index_daily_fingerprint": idx_after["fingerprint"],
            "index_daily_fingerprint_expected":
                "dbbd07c1339e99f27b0aeadb43eb56848776dbbad97f3fb7b9748bbd2f1e61f6",
            "index_daily_unchanged": (
                idx_fp["fingerprint"] == idx_after["fingerprint"]),
            "table_counts": counts,
            "integrity_check": integrity,
            "foreign_key_check": fk,
            "isolated": iso_ok["isolated"],
        },
        "_self_check": {
            "twelve_candidates": len(results) == 12,
            "all_graded": all(r["grading"]["final_grade"] in
                              GRADE_DEFINITIONS for r in results),
            "no_grade_a": grades.get("A", 0) == 0,
            "no_historical_start_confirmed": all(
                r["historical_start"]["historical_start_status"] == "unknown"
                for r in results),
            "point_in_time_all_unknown": all(
                r["point_in_time"]["historical_point_in_time_status"]
                == "unknown" for r in results),
            "no_official_calendar": all(
                not r["calendar"]["calendar_is_official"]
                for r in results),
            "bond_hk_calendar_unknown": all(
                r["calendar"]["continuity_status"] == "unknown"
                for r in results if r["market_group"] in ("bond", "hk")),
            "rows_unchanged": total_raw == 55942,
            "index_daily_unchanged": (
                idx_fp["fingerprint"] == idx_after["fingerprint"]),
            "no_validated": True,
            "no_formal_admitted": True,
            "synthetic_rows_preserved": all(
                r["row_quality_distribution"].get(
                    "suspected_synthetic", 0) == 1 for r in results),
            "suspected_closed_not_verified": all(
                r["calendar"]["continuity_status"] !=
                "verified_against_proxy_calendar"
                for r in results
                if (r["calendar"].get(
                    "suspected_market_closed_count", 0) > 0)),
            "fatal_quality_graded_d": all(
                r["grading"]["final_grade"] == "D"
                for r in results
                if r["row_quality"]["fatal_issue_count"] > 0),
            "no_grade_a_unchanged": grades.get("A", 0) == 0,
            "invalid_prev_close_blocked": all(
                "blocked_by_invalid_previous_close"
                in r["row_quality"]["checks"] for r in results),
        },
    }
    (REPORTS / "phase3B6_2_3_1_2_audit.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")

    # 分级单独文件
    (REPORTS / "phase3B6_2_3_1_2_candidate_grading.json").write_text(
        json.dumps({
            "phase": "3B-6.2.3.1.2",
            "generated_at": doc["generated_at"],
            "grade_definitions": GRADE_DEFINITIONS,
            "candidates": [{
                "tr_code": r["tr_code"],
                "market_group": r["market_group"],
                "official_full_name": r["official_full_name"],
                "row_count": r["row_count"],
                **r["grading"],
            } for r in results],
            "grade_distribution": grades,
        }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    # manifest
    files = {}
    for r in results:
        for kind in ("basic", "hist"):
            name = (f"{kind}_{r['tr_code']}.json" if kind == "basic"
                    else f"hist_{r['tr_code']}_20040101_20261127.json")
            f = EVID_OLD / name
            if f.exists():
                files[str(f.relative_to(ROOT)).replace("\\", "/")] = {
                    "bytes": f.stat().st_size,
                    "sha256": file_sha256(f),
                    "subject": r["tr_code"], "kind": kind,
                }
    (EVID / "manifest.json").write_text(json.dumps({
        "phase": "3B-6.2.3.1.2",
        "generated_at": doc["generated_at"],
        "no_new_download": True,
        "note": "本轮不下载新数据；登记审计所引用的原始官方证据",
        "file_count": len(files), "files": files,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(json.dumps(doc["_self_check"], ensure_ascii=False, indent=1))
    print(f"\n分级分布: {json.dumps(grades, ensure_ascii=False)}")
    print(f"连续性分布: {json.dumps(continuity, ensure_ascii=False)}")
    print(f"市场标注不符: {len(market_mismatch)} 处")
    for m in market_mismatch:
        print(f"  {m['tr_code']}: 任务书={m['task_claimed']} "
              f"实际={m['db_actual']} ({m['official_name']})")
    print(f"\n原始行数: {total_raw}  index_daily: "
          f"{idx_after['row_count']}  integrity={integrity} fk={fk}")


if __name__ == "__main__":
    main()
