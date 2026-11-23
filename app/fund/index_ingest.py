"""阶段3B-6.0.2 指数受控采集。

规则：
1. **分段请求**：长区间拆成按年分段，避免单次超长请求返回 0 行；
2. 单个指数失败不影响其他指数；
3. 失败任务可用 ``retry_failed`` 重试；
4. 采集结果先过质量检查，硬性不过则不入库；
5. 不写基金库任何表。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from app.fund.index_layer import (
    LAYER_DEGRADED, LAYER_FAILED, LAYER_READY,
    quality_level_of,
    RETURN_BASIS_UNKNOWN,
    content_fingerprint, effective_date_range, get_index_master,
    index_date_range,
    save_quality_check, start_ingest_run, finish_ingest_run,
    upsert_index_daily, upsert_index_master,
)
from app.fund.research.index_verify import check_history_quality

SOURCE_CSINDEX = "akshare.stock_zh_index_hist_csindex"
INTERFACE_CSINDEX = "stock_zh_index_hist_csindex"

# 第一批 10 个已验证的中证指数
FIRST_BATCH = (
    ("000300", "沪深300指数", "沪深300", "中证/上证系列"),
    ("000905", "中证小盘500指数", "中证500", "中证/上证系列"),
    ("000906", "中证800指数", "中证800", "中证/上证系列"),
    ("000016", "上证50指数", "上证50", "中证/上证系列"),
    ("399997", "中证白酒指数", "中证白酒", "中证/上证系列"),
    ("H30184", "中证全指半导体产品与设备指数", "半导体", "中证/上证系列"),
    ("000942", "中证内地消费主题指数", "内地消费", "中证/上证系列"),
    ("000012", "上证国债指数", "国债指数", "中证/上证系列"),
    ("000922", "中证红利指数", "中证红利", "中证/上证系列"),
    ("930930", "中证港股通综合指数", "港股综合", "中证/上证系列"),
)

PUBLISHER = "中证指数有限公司"


def year_segments(start_year: int, end_year: int) -> list[tuple[str, str]]:
    """按自然年切分请求区间，避免单次超长请求。"""
    return [(f"{y}0101", f"{y}1231") for y in range(start_year, end_year + 1)]


DEFAULT_START = "20040101"
DEFAULT_END = "20261123"
RETRY_ATTEMPTS = 6
RETRY_SLEEP_SEC = 45
INTER_INDEX_SLEEP_SEC = 6


def _fetch(symbol: str, start: str, end: str):
    import akshare as ak
    return ak.stock_zh_index_hist_csindex(
        symbol=symbol, start_date=start, end_date=end)


def _fetch_with_retry(symbol: str, start: str, end: str, *,
                      fetcher=None, attempts: int = RETRY_ATTEMPTS,
                      sleep_sec: float = RETRY_SLEEP_SEC,
                      sleeper=None) -> tuple:
    """带重试的请求。

    中证官网接口在密集请求后会返回 403 反爬页面（表现为 JSONDecodeError），
    冷却后自动恢复——实测约 6 分钟。因此必须重试而不是直接判定无数据。
    """
    import time as _time
    sleeper = sleeper or _time.sleep
    fetcher = fetcher or _fetch
    last = None
    for i in range(attempts):
        try:
            return fetcher(symbol, start, end), None, i
        except Exception as exc:                       # noqa: BLE001
            last = (type(exc).__name__, str(exc)[:200])
            if i < attempts - 1:
                sleeper(sleep_sec)
    return None, last, attempts


def _to_rows(df, index_code: str) -> list[dict]:
    """把中证官网 DataFrame 转成 index_daily 行。

    日期用 ``日期`` 列；OHLC 缺失原样保留 None，不补、不前向填充。
    """
    rows = []
    for _, r in df.iterrows():
        d = r["日期"]
        date = d.isoformat()[:10] if hasattr(d, "isoformat") else str(d)[:10]
        rows.append({
            "index_code": index_code,
            "trade_date": date,
            "open": _f(r.get("开盘")),
            "high": _f(r.get("最高")),
            "low": _f(r.get("最低")),
            "close": _f(r.get("收盘")),
        })
    return rows


def _f(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f        # NaN → None


def collect_one(conn: sqlite3.Connection, index_code: str, *,
                index_name: str, index_short_name: str,
                index_family: str, start_year: int = 2004,
                end_year: int | None = None, fetcher=None,
                enable_master: bool = True,
                attempts: int = RETRY_ATTEMPTS,
                sleep_sec: float = RETRY_SLEEP_SEC,
                sleeper=None) -> dict:
    """采集单个指数。返回结果字典，**不抛异常**，保证单指数失败不影响整体。

    重要：中证官网 ``index-perf`` 接口实际**忽略** start/end 区间参数，
    一次请求即返回该指数全部历史。因此这里只发一次请求（带重试），
    不再按年分段——分段只会重复拉取全量并被反爬拦截。
    真实返回区间由响应内容决定，并如实记录。
    """
    fetcher = fetcher or _fetch
    result = {
        "index_code": index_code, "ok": False, "rows_returned": 0,
        "rows_written": 0, "date_min": None, "date_max": None,
        "quality_level": None, "quality_hard_passed": None,
        "run_ids": [], "error": None, "attempts_used": 0,
        "requested_range": f"{DEFAULT_START}~{DEFAULT_END}",
    }

    run_id = start_ingest_run(
        conn, index_code=index_code, source=SOURCE_CSINDEX,
        interface_name=INTERFACE_CSINDEX,
        request_start_date=DEFAULT_START, request_end_date=DEFAULT_END,
        ingest_mode="full")
    result["run_ids"].append(run_id)

    df, err, used = _fetch_with_retry(
        index_code, DEFAULT_START, DEFAULT_END, fetcher=fetcher,
        attempts=attempts, sleep_sec=sleep_sec, sleeper=sleeper)
    result["attempts_used"] = used

    if err or df is None or len(df) == 0:
        result["error"] = (f"{err[0]}: {err[1]}" if err else "接口返回空数据")
        finish_ingest_run(conn, run_id, status="failed",
                          error_type=(err[0] if err else "EmptyResult"),
                          error_message=result["error"][:200])
        if enable_master:
            upsert_index_master(
                conn, index_code=index_code, index_name=index_name,
                index_short_name=index_short_name, index_family=index_family,
                publisher=PUBLISHER, data_source=SOURCE_CSINDEX,
                return_basis=RETURN_BASIS_UNKNOWN,
                return_basis_evidence="未取得数据，无法判定口径",
                layer_status=LAYER_FAILED)
        return result

    rows = _to_rows(df, index_code)
    # 去重：同日期只保留一条（后出现的覆盖前者）
    dedup: dict[str, dict] = {}
    for r in rows:
        dedup[r["trade_date"]] = r
    rows_sorted = [dedup[k] for k in sorted(dedup)]

    dmin = rows_sorted[0]["trade_date"]
    dmax = rows_sorted[-1]["trade_date"]
    finish_ingest_run(
        conn, run_id, status="success", returned_rows=len(rows_sorted),
        actual_date_min=dmin, actual_date_max=dmax,
        content_fp=content_fingerprint(rows_sorted),
        note=(f"接口忽略请求区间，实返 {dmin}~{dmax}；"
              f"原始 {len(rows)} 行去重后 {len(rows_sorted)} 行"))

    # 传入当前连接读交易日历：外层已持写事务，另开连接会锁等待并降级
    quality = check_history_quality(_df_from_rows(rows_sorted),
                                    calendar_conn=conn)

    if enable_master:
        upsert_index_master(
            conn, index_code=index_code, index_name=index_name,
            index_short_name=index_short_name, index_family=index_family,
            publisher=PUBLISHER, data_source=SOURCE_CSINDEX,
            inception_date=None,
            inception_date_evidence="来源未明确给出成立日，首行日期不得顶替",
            return_basis=RETURN_BASIS_UNKNOWN,
            return_basis_evidence=("来源仅提供指数收盘点位，"
                                   "无全收益口径证据，保守标记 unknown"),
            data_status="active",
            layer_status=(LAYER_READY if quality.get("hard_passed")
                          else LAYER_DEGRADED))

    # 硬性不过 → 不入库（但 master 与 run 记录保留，便于追溯失败原因）
    if not quality.get("hard_passed"):
        result["error"] = quality.get("reason")
        result["quality_level"] = "D"
        result["quality_hard_passed"] = False
        result["rows_returned"] = len(rows_sorted)
        save_quality_check(conn, index_code=index_code, run_id=run_id,
                           quality=quality)
        return result

    # 基线占位行：来源首行常为 2004-01-01 且与第二行数值相同，
    # 不是真实交易日行情。保留入库（可追溯）但标 suspect，不计入有效区间。
    baseline = (quality["checks"].get("baseline_row") or {})
    baseline_date = baseline.get("first_date") if baseline.get("detected") else None
    write = upsert_index_daily(
        conn, index_code=index_code,
        rows=[dict(r, quality_status=("suspect"
                                      if r["trade_date"] == baseline_date
                                      else "valid"),
                   quality_note=("接口基线占位行：日期与第二行间隔异常或非交易日，"
                                 "不是真实行情" if r["trade_date"] == baseline_date
                                 else None))
              for r in rows_sorted],
        source=SOURCE_CSINDEX, run_id=run_id)
    qc_id = save_quality_check(conn, index_code=index_code, run_id=run_id,
                               quality=quality)
    rng = effective_date_range(conn, index_code)
    raw_rng = index_date_range(conn, index_code)

    result.update({
        "ok": True,
        "rows_returned": len(rows_sorted),
        "rows_written": write["inserted"] + write["updated"],
        "write_detail": write,
        "date_min": rng["date_min"],
        "date_max": rng["date_max"],
        "raw_date_min": raw_rng["date_min"],
        "raw_rows": raw_rng["row_count"],
        "baseline_date": baseline_date,
        "data_status": ("active" if len(rng["date_max"] or "") == 10
                        and rng["date_max"] >= "2025-01-01" else "unknown"),
        "quality_level": quality_level_of(quality),
        "quality_hard_passed": True,
        "quality_check_id": qc_id,
        "gap_count": (quality["checks"]["gap_checked"] or {}).get("gap_count"),
        "gap_days": (quality["checks"]["gap_checked"] or {}).get(
            "total_missing_days"),
        "baseline_row_detected": (quality["checks"]["baseline_row"] or {}).get(
            "detected"),
        "ohlc_complete": (quality["checks"]["no_null_ohlc"] or {}).get("ok"),
    })
    return result


def _df_from_rows(rows: list[dict]):
    """把行还原成校验用的 DataFrame（复用 3B-6.0.1.1 的质量检查）。"""
    import pandas as pd
    return pd.DataFrame([{
        "日期": r["trade_date"], "开盘": r["open"], "最高": r["high"],
        "最低": r["low"], "收盘": r["close"],
    } for r in rows])


def collect_first_batch(conn: sqlite3.Connection, *, fetcher=None,
                        indices=None, sleeper=None,
                        inter_index_sleep_sec: float = INTER_INDEX_SLEEP_SEC
                        ) -> list[dict]:
    """采集第一批指数。**单个失败不影响其他**。

    指数之间间隔若干秒，降低触发中证官网反爬的概率。
    """
    import time as _time
    sleeper = sleeper or _time.sleep
    targets = indices or FIRST_BATCH
    results = []
    for i, (code, name, short, family) in enumerate(targets):
        if i:
            sleeper(inter_index_sleep_sec)
        try:
            r = collect_one(conn, code, index_name=name,
                            index_short_name=short, index_family=family,
                            fetcher=fetcher, sleeper=sleeper)
        except Exception as exc:                       # noqa: BLE001
            r = {"index_code": code, "ok": False,
                 "error": f"{type(exc).__name__}: {exc}"}
        results.append(r)
    return results


def retry_failed(conn: sqlite3.Connection, index_code: str, *,
                 fetcher=None) -> dict:
    """重试某个失败指数。"""
    m = get_index_master(conn, index_code)
    if m is None:
        raise ValueError(f"{index_code} 未登记")
    return collect_one(conn, index_code,
                       index_name=m["index_name"],
                       index_short_name=m["index_short_name"] or index_code,
                       index_family=m["index_family"] or "中证/上证系列",
                       fetcher=fetcher)
