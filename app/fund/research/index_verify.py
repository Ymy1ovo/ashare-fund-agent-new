"""阶段3B-6.0.1.1 指数历史数据验证与质量审计（只读）。

**核心原则：三种状态严格分开，绝不因为「代码已登记」就宣称「历史已验证」。**

| 状态 | 含义 | 证据要求 |
| --- | --- | --- |
| ``code_mapping_verified`` | 代码 ↔ 指数名称映射已核实 | 官方接口返回的指数中文全称/简称与预期一致 |
| ``history_api_verified`` | 历史数据接口**实际调用成功** | 本次真的发出请求并拿到非空 DataFrame |
| ``history_quality_verified`` | 历史数据**通过质量检查** | 日期解析/升序/重复/空值/数值/缺口全部检查通过 |
| ``unknown`` | 证据不足 | 以上任一环节缺失 |

三者是**递进关系**，不能跳级，也不能互相替代：

- 代码能查到 ≠ 接口能调通；
- 接口能调通 ≠ 数据质量合格；
- 单指数质量合格 ≠ 基金整条复合基准可复现。
"""
from __future__ import annotations

from datetime import datetime

# ---------------------------------------------------------------- 状态常量
ST_CODE_VERIFIED = "code_mapping_verified"
ST_HISTORY_VERIFIED = "history_api_verified"
ST_QUALITY_VERIFIED = "history_quality_verified"
ST_UNKNOWN = "unknown"

STATE_MEANING = {
    ST_CODE_VERIFIED: "代码与指数名称映射已核实（仅此而已）",
    ST_HISTORY_VERIFIED: "历史数据接口已实际调用成功（尚未做质量检查）",
    ST_QUALITY_VERIFIED: "历史数据通过日期/重复/空值/数值/缺口质量检查",
    ST_UNKNOWN: "证据不足，不得宣称任何验证通过",
}

# 质量检查项：分「硬性」与「警告」两类
# 硬性失败 → 不能标 history_quality_verified
# 警告项失败 → 如实记录，但不阻断（因为不影响收盘价收益序列）
HARD_CHECKS = (
    "date_parsed",
    "date_ascending",
    "no_duplicate_dates",
    "no_null_dates",
    "no_null_close",
    "numeric_values_sane",
    "range_sane",
    "baseline_row",
)
SOFT_CHECKS = (
    "no_null_ohlc",
    "gap_checked",
)
QUALITY_CHECKS = HARD_CHECKS + SOFT_CHECKS

HARD_CHECK_NOTE = (
    "硬性检查只看**收盘价**序列完整性——"
    "指数基准只能用于计算收盘收益，因此收盘价必须完整；"
    "OHLC 部分缺失只影响日内分析，记为警告而不阻断"
)

# 缺口检查用的「交易日历代理」
CALENDAR_PROXY = "workdays_proxy"
CALENDAR_PROXY_NOTE = (
    "日历代理 = 按工作日（周一至周五）推算的**潜在**交易日，"
    "仅用于发现疑似缺口；**不能**冒充指数官方实际公布日历，"
    "因此缺口一律保留 `is_real_missing=null`（无法确定）"
)

CALENDAR_TRADE_TABLE = "trade_calendar_table_proxy"
CALENDAR_TRADE_TABLE_NOTE = (
    "日历代理 = 本项目 `trade_calendar` 表（A 股交易日），"
    "仅用于发现疑似缺口；**仍不是指数官方公布日历**"
    "（指数可能有停编、临时调整等情形），"
    "因此缺口一律保留 `is_real_missing=null`（无法确定）"
)


# ---------------------------------------------------------------- 单指数据取
def fetch_csindex_history(code: str, *, start_date: str = "20040101",
                          end_date: str = "20261123"):
    """实际调用中证官网历史接口。返回 (df, error)。

    失败时 df 为 None，error 为 (类型名, 消息)。
    """
    try:
        import akshare as ak
        df = ak.stock_zh_index_hist_csindex(
            symbol=code, start_date=start_date, end_date=end_date)
        return df, None
    except Exception as exc:
        return None, (type(exc).__name__, str(exc)[:200])


def verify_code_mapping(code: str, df, expected_name_tokens) -> dict:
    """核实代码 ↔ 名称映射。

    证据来源：官方接口返回的 ``指数中文全称`` / ``指数中文简称``。
    必须与预期名称有交集，否则 mapping 不成立。
    """
    if df is None or len(df) == 0:
        return {
            "verified": False,
            "official_full_name": None,
            "official_short_name": None,
            "reason": "接口未返回数据，无法核实名称映射",
        }
    cols = list(df.columns)
    full = short = None
    if "指数中文全称" in cols:
        full = str(df.iloc[0]["指数中文全称"])
    if "指数中文简称" in cols:
        short = str(df.iloc[0]["指数中文简称"])

    hay = f"{full or ''} {short or ''}"
    hit = [t for t in (expected_name_tokens or []) if t and t in hay]
    return {
        "verified": bool(hit),
        "official_full_name": full,
        "official_short_name": short,
        "matched_tokens": hit,
        "reason": (None if hit
                   else f"官方名称「{hay.strip()}」不含预期关键词 {list(expected_name_tokens or [])}"),
    }


# ---------------------------------------------------------------- 质量检查
def _to_date(v):
    """把各种日期表示统一成 ISO 字符串；失败返回 None。"""
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        try:
            return v.isoformat()[:10]
        except Exception:
            return None
    s = str(v).strip()
    if not s or s.lower() in ("nan", "none", "nat"):
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(s[:10] if fmt != "%Y%m%d" else s[:8],
                                     fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _load_trade_calendar(date_min: str, date_max: str,
                         conn=None) -> set[str] | None:
    """读项目内 `trade_calendar` 表作为**日历代理**（只读）。

    读不到（无表 / 无数据 / 区间不覆盖）返回 None，调用方降级为工作日代理。

    ``conn`` 可传入已打开的连接：采集时外层持有写事务，
    再开新连接读同一 SQLite 文件会锁等待失败并静默降级为工作日代理，
    导致缺口统计口径不一致。
    """
    try:
        if conn is not None:
            rows = conn.execute(
                "SELECT trade_date FROM trade_calendar "
                "WHERE trade_date BETWEEN ? AND ?",
                (date_min, date_max)).fetchall()
        else:
            from app.database.db import get_connection
            with get_connection() as own:
                rows = own.execute(
                    "SELECT trade_date FROM trade_calendar "
                    "WHERE trade_date BETWEEN ? AND ?",
                    (date_min, date_max)).fetchall()
    except Exception:
        return None
    days = {str(r[0])[:10] for r in rows}
    return days or None


def detect_baseline_row(valid_dates: list[str],
                        trading_days: set[str] | None = None) -> dict:
    """探测「基线占位行」。

    中证官网接口有个已知特性：无论 `start_date` 填什么，
    返回的首行都可能是 **2004-01-01** 的基线值，而指数本身成立日晚得多。

    实测证据（本库 10 个指数，2026-11-23 调用）：

    | 代码 | 首行 | 第二行 | 间隔 | 判定 |
    | --- | --- | --- | ---: | --- |
    | 000300 | 2004-01-01 | 2004-01-02 | 1 | 非基线（但首行非交易日） |
    | 000905 | 2004-01-01 | 2004-12-31 | 365 | **基线** |
    | 399997 | 2004-01-01 | 2009-01-05 | 1831 | **基线** |
    | 930930 | 2004-01-01 | 2014-11-14 | 3970 | **基线** |

    判定规则（任一成立即判为基线行）：
    1. 首行与第二行间隔 ≥ 365 天；
    2. 首行日期**不在交易日历**里（是节假日）。

    第 2 条覆盖 000300 这类「间隔只有 1 天、但首行是元旦」的情形。
    """
    if len(valid_dates) < 2:
        return {"detected": False, "reason": "数据不足 2 行"}
    from datetime import date as _d
    first = _d.fromisoformat(valid_dates[0])
    second = _d.fromisoformat(valid_dates[1])
    gap = (second - first).days

    reasons = []
    if gap >= 365:
        reasons.append(f"首行与第二行间隔 {gap} 天 ≥ 365")
    if trading_days is not None and valid_dates[0] not in trading_days:
        reasons.append(f"首行 {valid_dates[0]} 不在交易日历中（非交易日）")

    detected = bool(reasons)
    return {
        "detected": detected,
        "first_date": valid_dates[0],
        "second_date": valid_dates[1],
        "gap_days": gap,
        "threshold_days": 365,
        "reasons": reasons,
        "reason": ("；".join(reasons) + "，判定为接口基线占位行，"
                   "不计入缺口统计与区间起点") if detected else None,
    }


def _gap_scan(have: set[str], date_min: str, date_max: str,
              calendar: set[str] | None, *, calendar_name: str,
              calendar_note: str) -> dict:
    """用给定日历扫描缺口。**只报疑似，不判定真实缺失，不填充。**"""
    from datetime import date as _d, timedelta as _td

    gaps: list[dict] = []
    if calendar is not None:
        missing = sorted(calendar - have)
        # 连续缺失合并成区间
        if missing:
            run_start = prev = missing[0]
            for m in missing[1:]:
                cur_d = _d.fromisoformat(m)
                if (cur_d - _d.fromisoformat(prev)).days == 1:
                    prev = m
                    continue
                gaps.append({"from": run_start, "to": prev,
                             "missing_count": (_d.fromisoformat(prev)
                                               - _d.fromisoformat(run_start)).days + 1})
                run_start = prev = m
            gaps.append({"from": run_start, "to": prev,
                         "missing_count": (_d.fromisoformat(prev)
                                           - _d.fromisoformat(run_start)).days + 1})
        extra = sorted(have - calendar)
    else:
        cur = _d.fromisoformat(date_min)
        end = _d.fromisoformat(date_max)
        run_start = prev = None
        while cur <= end:
            if cur.weekday() < 5 and cur.isoformat() not in have:
                if run_start is None:
                    run_start = cur
                prev = cur
            else:
                if run_start is not None and prev is not None:
                    gaps.append({"from": run_start.isoformat(),
                                 "to": prev.isoformat(),
                                 "missing_count": (prev - run_start).days + 1})
                run_start = None
            cur += _td(days=1)
        if run_start is not None and prev is not None:
            gaps.append({"from": run_start.isoformat(), "to": prev.isoformat(),
                         "missing_count": (prev - run_start).days + 1})
        extra = []

    for g in gaps:
        g["is_real_missing"] = None
        g["reason"] = ("日历代理发现缺口，无法确认是否为真实缺失"
                       "（可能是指数停编/临时调整）")

    return {
        "ok": True,
        "calendar": calendar_name,
        "calendar_note": calendar_note,
        "gap_count": len(gaps),
        "gaps_sample": gaps[:10],
        "total_missing_days": sum(g["missing_count"] for g in gaps),
        "dates_outside_calendar": len(extra),
        "dates_outside_calendar_sample": extra[:5],
        "is_real_missing": None,
    }


def check_history_quality(df, *, calendar_proxy: str = CALENDAR_PROXY,
                          use_trade_calendar: bool = True,
                          calendar_conn=None) -> dict:
    """对历史序列做质量检查。

    **不填充、不插值、不把缺失日当 0 收益、不把缺口判定为真实缺失。**

    检查分两类：

    | 类别 | 项 | 失败后果 |
    | --- | --- | --- |
    | 硬性 | 日期解析/升序/重复/空日期/收盘空值/数值/起止 | 不能标 quality_verified |
    | 警告 | OHLC 部分空值、缺口 | 如实记录，不阻断 |

    为什么 OHLC 部分缺失不阻断：指数基准只用于**收盘收益**，
    收盘价完整即可算基准收益；OHLC 缺失只影响日内分析。
    """
    if df is None or len(df) == 0:
        return {
            "status": ST_UNKNOWN,
            "all_passed": False,
            "hard_passed": False,
            "checks": {k: {"ok": False, "reason": "无数据"} for k in QUALITY_CHECKS},
            "hard_check_note": HARD_CHECK_NOTE,
            "rows": 0,
            "reason": "接口未返回数据，无法做质量检查",
        }

    cols = {str(c) for c in df.columns}
    date_col = "日期" if "日期" in cols else ("date" if "date" in cols else None)
    open_col = "开盘" if "开盘" in cols else ("open" if "open" in cols else None)
    high_col = "最高" if "最高" in cols else ("high" if "high" in cols else None)
    low_col = "最低" if "最低" in cols else ("low" if "low" in cols else None)
    close_col = "收盘" if "收盘" in cols else ("close" if "close" in cols else None)
    has_ohlc_cols = all([open_col, high_col, low_col, close_col])

    checks: dict[str, dict] = {}
    rows = int(len(df))

    # ① 日期解析
    raw_dates = list(df[date_col]) if date_col else []
    parsed = [_to_date(x) for x in raw_dates]
    null_dates = sum(1 for x in parsed if x is None)
    checks["date_parsed"] = {
        "ok": bool(date_col) and null_dates == 0,
        "total": rows, "null_count": null_dates,
        "reason": None if date_col else "无日期列",
    }
    checks["no_null_dates"] = {"ok": null_dates == 0, "null_count": null_dates}

    valid = [x for x in parsed if x]
    asc_ok = valid == sorted(valid)
    desc_pairs = sum(1 for a, b in zip(valid, valid[1:]) if b <= a)
    checks["date_ascending"] = {
        "ok": asc_ok, "out_of_order_count": desc_pairs,
        "reason": None if asc_ok else f"{desc_pairs} 处非升序",
    }

    dups = len(valid) - len(set(valid))
    checks["no_duplicate_dates"] = {
        "ok": dups == 0, "duplicate_count": dups,
        "reason": None if dups == 0 else f"{dups} 条重复日期",
    }

    def nulls_of(col):
        return None if not col else int(df[col].isna().sum())

    null_map = {c: nulls_of(c) for c in (open_col, high_col, low_col, close_col)}
    ohlc_ok = has_ohlc_cols and all(v == 0 for v in null_map.values())
    checks["no_null_ohlc"] = {
        "ok": ohlc_ok,
        "severity": "warning",
        "has_ohlc_columns": has_ohlc_cols,
        "null_counts": {k: v for k, v in null_map.items() if k},
        "reason": (None if ohlc_ok
                   else ("缺少 OHLC 列" if not has_ohlc_cols
                         else "OHLC 部分列存在空值（不影响收盘收益计算，记为警告）")),
    }

    close_nulls = nulls_of(close_col)
    checks["no_null_close"] = {
        "ok": bool(close_col) and close_nulls == 0,
        "close_col": close_col, "null_count": close_nulls,
        "reason": (None if (close_col and close_nulls == 0)
                   else ("无收盘列" if not close_col else f"{close_nulls} 条收盘空值")),
    }

    bad_numeric = negative = 0
    if close_col:
        for v in df[close_col]:
            try:
                f = float(v)
            except (TypeError, ValueError):
                bad_numeric += 1
                continue
            if f < 0:
                negative += 1
    checks["numeric_values_sane"] = {
        "ok": bad_numeric == 0 and negative == 0,
        "non_numeric": bad_numeric, "negative_close": negative,
        "reason": (None if (bad_numeric == 0 and negative == 0)
                   else f"非数值 {bad_numeric} 条，负值 {negative} 条"),
    }

    _cal_for_baseline = None
    if use_trade_calendar and len(valid) >= 2:
        _cal_for_baseline = _load_trade_calendar(valid[0], valid[-1],
                                                 calendar_conn)
    _baseline_for_range = detect_baseline_row(valid, _cal_for_baseline)
    _real = valid[1:] if _baseline_for_range["detected"] else valid
    checks["range_sane"] = {
        "ok": bool(valid) and valid == sorted(valid),
        "date_min": _real[0] if _real else None,
        "date_max": _real[-1] if _real else None,
        "raw_date_min": valid[0] if valid else None,
        "raw_date_max": valid[-1] if valid else None,
        "baseline_row_excluded": _baseline_for_range["detected"],
    }

    # ⑦ 缺口（优先用项目交易日历代理，降级为工作日代理）
    baseline = _baseline_for_range
    scan_dates = valid[1:] if baseline["detected"] else valid
    checks["baseline_row"] = {
        "ok": True, **baseline,
    }
    have = set(scan_dates)
    gap_cell = None
    if len(scan_dates) >= 2:
        dmin, dmax = scan_dates[0], scan_dates[-1]
        cal = (_load_trade_calendar(dmin, dmax, calendar_conn)
               if use_trade_calendar else None)
        if cal:
            gap_cell = _gap_scan(have, dmin, dmax, cal,
                                 calendar_name=CALENDAR_TRADE_TABLE,
                                 calendar_note=CALENDAR_TRADE_TABLE_NOTE)
        else:
            gap_cell = _gap_scan(have, dmin, dmax, None,
                                 calendar_name=calendar_proxy,
                                 calendar_note=CALENDAR_PROXY_NOTE)
    checks["gap_checked"] = gap_cell or {
        "ok": True, "calendar": calendar_proxy,
        "calendar_note": CALENDAR_PROXY_NOTE, "gap_count": 0,
        "gaps_sample": [], "total_missing_days": 0, "is_real_missing": None,
    }
    checks["gap_checked"]["severity"] = "warning"

    hard_passed = all(checks[k].get("ok") for k in HARD_CHECKS)
    all_passed = all(checks[k].get("ok") for k in QUALITY_CHECKS)
    warnings = [k for k in SOFT_CHECKS if not checks[k].get("ok")]

    return {
        "status": (ST_QUALITY_VERIFIED if hard_passed else ST_UNKNOWN),
        "all_passed": all_passed,
        "hard_passed": hard_passed,
        "warning_checks": warnings,
        "hard_check_note": HARD_CHECK_NOTE,
        "checks": checks,
        "rows": rows,
        "date_min": checks["range_sane"]["date_min"],
        "date_max": checks["range_sane"]["date_max"],
        "reason": (None if hard_passed
                   else "存在未通过的硬性质量检查项"
                        + (f"；警告项：{warnings}" if warnings else "")),
    }


# ---------------------------------------------------------------- 单指数完整验证
def verify_index_entry(family: str, code: str, *, expected_tokens,
                       fetcher=None, checked_at: str | None = None) -> dict:
    """对单个指数执行 代码映射 → 历史接口 → 质量检查 三步验证。

    ``fetcher`` 可注入（测试用），默认真调中证官网接口。
    """
    fetcher = fetcher or fetch_csindex_history
    ts = checked_at or datetime.now().isoformat(timespec="seconds")

    rec = {
        "family": family,
        "code": code,
        "source": "akshare.stock_zh_index_hist_csindex",
        "checked_at": ts,
        "code_mapping_verified": False,
        "history_api_verified": False,
        "history_quality_verified": False,
        "rows": 0,
        "date_min": None,
        "date_max": None,
        "ohlc_available": False,
        "quality": None,
        "final_state": ST_UNKNOWN,
        "failure_reason": None,
    }

    df, err = fetcher(code)
    if err:
        rec["failure_reason"] = f"{err[0]}: {err[1]}"
        rec["official_name"] = None
        return rec

    if df is None or len(df) == 0:
        rec["failure_reason"] = "接口返回空数据"
        rec["official_name"] = None
        return rec

    # ① 代码映射
    mapping = verify_code_mapping(code, df, expected_tokens)
    rec["code_mapping_verified"] = mapping["verified"]
    rec["official_name"] = mapping.get("official_full_name")
    rec["official_short_name"] = mapping.get("official_short_name")
    rec["code_mapping_evidence"] = mapping

    # ② 历史接口（拿到了非空数据即为已验证）
    rec["history_api_verified"] = True
    rec["rows"] = int(len(df))

    # ③ 质量检查
    quality = check_history_quality(df)
    rec["quality"] = quality
    rec["date_min"] = quality.get("date_min")
    rec["date_max"] = quality.get("date_max")
    rec["ohlc_available"] = bool(
        quality["checks"]["no_null_ohlc"].get("has_ohlc_columns"))
    rec["ohlc_complete"] = bool(
        quality["checks"]["no_null_ohlc"].get("ok"))
    rec["quality_warnings"] = quality.get("warning_checks") or []
    rec["history_quality_verified"] = bool(quality.get("hard_passed"))

    # 递进状态
    if rec["history_quality_verified"]:
        rec["final_state"] = ST_QUALITY_VERIFIED
    elif rec["history_api_verified"]:
        rec["final_state"] = ST_HISTORY_VERIFIED
    elif rec["code_mapping_verified"]:
        rec["final_state"] = ST_CODE_VERIFIED
    else:
        rec["final_state"] = ST_UNKNOWN

    if not rec["code_mapping_verified"]:
        rec["failure_reason"] = mapping["reason"]
    elif not rec["history_quality_verified"]:
        rec["failure_reason"] = quality.get("reason")
    return rec
