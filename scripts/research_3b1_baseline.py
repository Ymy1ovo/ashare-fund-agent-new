"""阶段3B-1 策略有效性基线研究（只读）。

严格只读：不写数据库、不修改正式策略/会计/撮合/绩效逻辑、不落库新回测记录。
所有研究用回测一律 db_path=None，因此引擎不会写公司行为明细，
结果只留在本脚本产出的 JSON / Markdown 里。

正式记录（validation_runs / validation_grid / validation_windows /
validation_regime_stats / validation_backtest_runs）只被读取，绝不被修改。
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.backtest.engine import BacktestEngine          # noqa: E402
from app.backtest.metrics import compute_performance     # noqa: E402
from app.backtest.strategies.buy_and_hold import BuyAndHoldStrategy  # noqa: E402
from app.backtest.strategies.ma_trend import MovingAverageTrendStrategy  # noqa: E402
from app.database.db import get_connection               # noqa: E402
from app.replay.registry import list_supersessions       # noqa: E402
from app.validation.config import (                       # noqa: E402
    BENCHMARK_HS300_PROXY, BENCHMARK_ZZ500_PROXY, ValidationConfig,
)
from app.validation.fingerprint import fingerprint_from_db  # noqa: E402

# ---------------------------------------------------------------- 研究记录清单
# 每个研究单元 = (标签, 新记录 id, 源记录 id, 是否 legacy-compatible)
RESEARCH_UNITS = [
    ("G1", "ea21b9d50eb14c74", "7d884a1a03d94915", False),
    ("G2", "bde29001291a456b", "c84356bd50ca4bb5", False),
    ("G3", "df2f811d52d04155", "2b21ca9b2c434444", False),
    ("G4", "93c170ca1402419f", "f9898c695b394808", True),
    ("G5", "1c5832e27c6c4f3c", "e725034e46ff47e5", True),
    ("G7", "a52af390b0d5442e", "c5589f7dcd1a4a5d", False),
    ("G8", "c68bf2840ebf4f08", "838a58fa5f3b4025", False),
    ("G9", "c5505f0145e34bbd", "b3f1e2c89ebc4b95", False),
    ("P0a", "03410886d1f64fa7", "32aead3291734f91", False),
    ("P0b", "aad7935a2bac4cc4", "c46fa37b932944c2", False),
]

FORMAL_ACC = "ca-v2-receivable"
FORMAL_BASIS = "formal_receivable"
MA_WINDOWS = [5, 10, 20, 30, 60, 120, 250]


def _clean_metrics(d) -> dict:
    if not isinstance(d, dict):
        return {}
    out = {}
    for k, v in d.items():
        out[k] = _num(v) if isinstance(v, float) else v
    return out


# ---------------------------------------------------------------- 统计层级
def dedupe_by_config(units: list[dict]) -> tuple[list[dict], list[dict]]:
    """按 (config_hash, input_hash) 去重。

    返回 (唯一配置列表, 被合并掉的重复项明细)。被合并的记录**不从
    units 里删除**，逐条审计明细照旧保留，只是不进入汇总统计。
    """
    seen: dict[tuple, str] = {}
    uniq: list[dict] = []
    merged: list[dict] = []
    for u in units:
        key = (u["config_hash"], u["input_hash"])
        if key in seen:
            merged.append({
                "tag": u["tag"], "record_id": u["record_id"],
                "config_hash": u["config_hash"], "input_hash": u["input_hash"],
                "merged_into": seen[key], "reason": "config_hash+input_hash 完全相同",
            })
            continue
        seen[key] = u["tag"]
        uniq.append(u)
    return uniq, merged


def oos_fingerprint_groups(units: list[dict]) -> list[dict]:
    """按 OOS 结果指纹（total_return + max_drawdown）合并。

    这只是"结果是否重复"的度量，**不是独立样本数**：共享同一行情库、
    同一策略代码、同一会计口径、基本同一 OOS 区间的结果，彼此强相关。
    """
    groups: dict[tuple, list[str]] = {}
    for u in units:
        o = u.get("oos_metrics") or {}
        key = (
            round(float(o.get("total_return") or 0.0), 8),
            round(float(o.get("max_drawdown") or 0.0), 8),
        )
        groups.setdefault(key, []).append(u["tag"])
    out = []
    for (ret, mdd), tags in sorted(groups.items(), key=lambda kv: -kv[0][0]):
        out.append({
            "oos_total_return": ret, "oos_max_drawdown": mdd, "tags": sorted(tags),
        })
    return out


def count_layers(units: list[dict]) -> dict:
    """三层计数 + 独立性声明。独立样本数无法严谨定义时写 not_estimable。"""
    uniq, merged = dedupe_by_config(units)
    fps = oos_fingerprint_groups(units)
    return {
        "included_records": len(units),
        "unique_config_input_pairs": len(uniq),
        "unique_oos_result_fingerprints": len(fps),
        "statistically_independent_samples": "not_estimable",
        "not_estimable_reason": (
            "全部记录共享同一行情数据库、同一策略代码、同一成本参数、"
            "同一会计口径，且主要 OOS 时间段基本相同（2025-01-02~2026-11-09）。"
            "唯一配置数与结果指纹数都不是独立市场样本数，"
            "无法据此严谨定义独立样本量。"
        ),
        "shared_market_periods": sorted({(u["oos_start"], u["oos_end"])
                                         for u in units}),
        "shared_is_periods": sorted({(u["is_start"], u["is_end"])
                                     for u in units}),
        "shared_pools": sorted({u["etf_count"] for u in units}),
        "deduped_records": merged,
    }



def _num(x, nd=10):
    return None if x is None else round(float(x), nd)


# ---------------------------------------------------------------- 读取正式记录
def load_units():
    """读取正式记录，返回研究单元列表；缺失字段一律标 unavailable，不补造。"""
    sup = {r["superseded_record_id"]: r for r in list_supersessions()
           if r.get("superseded_record_id")}
    out = []
    with get_connection() as conn:
        for tag, vid, sid, legacy_compat in RESEARCH_UNITS:
            row = conn.execute(
                "SELECT * FROM validation_runs WHERE validation_id=?", (vid,)
            ).fetchone()
            if row is None:
                out.append({"tag": tag, "record_id": vid, "status": "missing_record",
                            "included": False})
                continue
            d = dict(row)
            src = conn.execute(
                "SELECT * FROM validation_runs WHERE validation_id=?", (sid,)
            ).fetchone()
            sd = dict(src) if src else None
            summary = json.loads(d["summary_json"]) if d["summary_json"] else {}
            codes = json.loads(d["etf_codes"]) if d["etf_codes"] else []
            grid = json.loads(d["ma_window_grid"]) if d["ma_window_grid"] else []
            wf = json.loads(d["walkforward_config"]) if d["walkforward_config"] else {}

            is_grid = {}
            for g in conn.execute(
                "SELECT ma_window, status, metrics_json, reason FROM validation_grid "
                "WHERE validation_id=? AND phase='in_sample' ORDER BY ma_window", (vid,)
            ):
                m = json.loads(g["metrics_json"]) if g["metrics_json"] else {}
                is_grid[int(g["ma_window"])] = {
                    "status": g["status"], "reason": g["reason"],
                    "total_return": _num(m.get("total_return")),
                    "cagr": _num(m.get("cagr")),
                    "sharpe_ratio": _num(m.get("sharpe_ratio")),
                    "max_drawdown": _num(m.get("max_drawdown")),
                    "annualized_volatility": _num(m.get("annualized_volatility")),
                    "trade_count": m.get("trade_count"),
                    "turnover": _num(m.get("turnover"), 4),
                    "total_cost": _num(m.get("total_cost"), 4),
                    "notes": m.get("notes") or [],
                }

            windows = []
            for w in conn.execute(
                "SELECT * FROM validation_windows WHERE validation_id=? "
                "ORDER BY window_index", (vid,)
            ):
                wd = dict(w)
                tm = json.loads(wd["train_metrics_json"]) if wd["train_metrics_json"] else {}
                sm = json.loads(wd["test_metrics_json"]) if wd["test_metrics_json"] else {}
                windows.append({
                    "window_index": wd["window_index"],
                    "train_start": wd["train_start"], "train_end": wd["train_end"],
                    "test_start": wd["test_start"], "test_end": wd["test_end"],
                    "train_days": wd["train_days"], "test_days": wd["test_days"],
                    "selected_param": wd["selected_param"], "status": wd["status"],
                    "reason": wd["reason"],
                    "train_total_return": _num(tm.get("total_return")),
                    "test_total_return": _num(sm.get("total_return")),
                    "test_cagr": _num(sm.get("cagr")),
                    "test_sharpe": _num(sm.get("sharpe_ratio")),
                    "test_max_drawdown": _num(sm.get("max_drawdown")),
                    "test_trade_count": sm.get("trade_count"),
                    "test_total_cost": _num(sm.get("total_cost"), 4),
                })

            regime = []
            for g in conn.execute(
                "SELECT * FROM validation_regime_stats WHERE validation_id=? "
                "ORDER BY regime_label", (vid,)
            ):
                rd = dict(g)
                regime.append({
                    "regime_label": rd["regime_label"], "status": rd["status"],
                    "samples": rd["samples"], "min_samples": rd["min_samples"],
                    "cumulative_return": _num(rd["cumulative_return"]),
                    "cagr": _num(rd["cagr"]),
                    "sharpe_ratio": _num(rd["sharpe_ratio"]),
                    "max_drawdown": _num(rd["max_drawdown"]),
                    "win_rate": _num(rd["win_rate"], 6),
                    "trade_count": rd["trade_count"],
                    "reason": rd["reason"],
                })

            ca_agg = conn.execute(
                "SELECT COUNT(*) n, COALESCE(SUM(applied_action_count),0) app, "
                "COALESCE(SUM(receivable_count),0) recv, "
                "COALESCE(SUM(receivable_amount),0) amt, "
                "COALESCE(SUM(settled_count),0) settled, "
                "COALESCE(SUM(settled_amount),0) settled_amt "
                "FROM validation_backtest_runs WHERE validation_id=?", (vid,)
            ).fetchone()
            role_agg = {}
            for g in conn.execute(
                "SELECT run_role, COUNT(*) n, COALESCE(SUM(applied_action_count),0) app, "
                "COALESCE(SUM(receivable_count),0) recv, "
                "COALESCE(SUM(receivable_amount),0) amt, "
                "COALESCE(SUM(settled_amount),0) settled "
                "FROM validation_backtest_runs WHERE validation_id=? GROUP BY run_role",
                (vid,)
            ):
                role_agg[g["run_role"]] = {
                    "runs": g["n"], "applied": g["app"],
                    "receivables": g["recv"], "receivable_amount": _num(g["amt"], 4),
                    "settled_amount": _num(g["settled"], 4),
                }
            basis_rows = conn.execute(
                "SELECT accounting_basis, formal_valuation, COUNT(*) FROM "
                "validation_backtest_runs WHERE validation_id=? "
                "GROUP BY accounting_basis, formal_valuation", (vid,)
            ).fetchall()

            superseded = vid in sup
            has_detail = len(basis_rows) > 0
            basis_ok = bool(has_detail) and all(
                r[0] == FORMAL_BASIS and int(r[1]) == 1 for r in basis_rows)
            acc_ok = d["accounting_version"] == FORMAL_ACC
            formal = bool(acc_ok and basis_ok)
            unit = {
                "tag": tag,
                "source_id": sid,
                "record_id": vid,
                "config_hash": d["config_hash"],
                "source_config_hash": sd["config_hash"] if sd else None,
                "input_hash": d["input_hash"],
                "source_input_hash": sd["input_hash"] if sd else None,
                "accounting_version": d["accounting_version"],
                "accounting_basis": FORMAL_BASIS if formal else "unavailable",
                "formal_valuation": bool(formal),
                "status": d["status"],
                "conclusion": d["conclusion"],
                "legacy_compatible": legacy_compat,
                "superseded": superseded,
                "etf_count": len(codes),
                "etf_codes": codes,
                "is_start": d["is_start"], "is_end": d["is_end"],
                "oos_start": d["oos_start"], "oos_end": d["oos_end"],
                "ma_window_grid": grid,
                "wf_grid": wf.get("wf_grid"),
                "wf_window_count": wf.get("window_count"),
                "regime_proxy": "510300",
                "cost_config": {
                    "commission_rate": 0.00025, "min_commission": 5.0,
                    "slippage_bps": 5.0, "execution_price": "open",
                },
                "best_param": summary.get("best_param"),
                "is_metrics": _clean_metrics(summary.get("is_metrics")),
                "oos_metrics": _clean_metrics(summary.get("oos_metrics")),
                "conclusion_reasons": summary.get("conclusion_reasons") or [],
                "is_grid": is_grid,
                "windows": windows,
                "regime": regime,
                "corporate_action_agg": {
                    "internal_runs": ca_agg["n"],
                    "applied": ca_agg["app"],
                    "receivables": ca_agg["recv"],
                    "receivable_amount": _num(ca_agg["amt"], 4),
                    "settled_count": ca_agg["settled"],
                    "settled_amount": _num(ca_agg["settled_amt"], 4),
                },
                "by_role": role_agg,
            }
            unit["included"] = bool(
                d["status"] == "success" and formal and not superseded
            )
            if unit["included"]:
                reason = None
            elif d["status"] != "success":
                reason = f"源记录 status={d['status']}，不是成功记录"
            elif superseded:
                reason = "该结果已被 supersession 标记为失效"
            elif not has_detail:
                reason = ("缺少 validation_backtest_runs 内部回测明细凭证"
                          "（无公司行为/分红应收明细可核验），"
                          "不能作为正式研究依据")
            elif not acc_ok:
                reason = f"accounting_version={d['accounting_version']}，非正式口径"
            elif not basis_ok:
                reason = "内部回测 accounting_basis/formal_valuation 不满足正式口径"
            else:
                reason = "未纳入（原因未分类）"
            unit["exclusion_reason"] = reason
            unit["has_detail_evidence"] = has_detail
            unit["detail_run_count"] = ca_agg["n"]
            out.append(unit)
    return out


# ---------------------------------------------------------------- 只读研究回测
def run_research_backtest(cfg: ValidationConfig, strategy, codes,
                          start: str, end: str) -> dict:
    """研究用只读回测：db_path=None，不写任何库表。"""
    bt = cfg.build_backtest_config(start, end)
    engine = BacktestEngine(bt, strategy, db_path=None)
    result = engine.run(codes, indicator_version=cfg.indicator_version)
    perf = compute_performance(
        result.daily, result.trades, result.orders, result.initial_cash,
        annualization=bt.annualization, risk_free_rate=bt.risk_free_rate,
    )
    return {
        "total_return": _num(perf.total_return),
        "cagr": _num(perf.cagr),
        "annualized_volatility": _num(perf.annualized_volatility),
        "sharpe_ratio": _num(perf.sharpe_ratio),
        "sortino_ratio": _num(perf.sortino_ratio),
        "max_drawdown": _num(perf.max_drawdown),
        "win_rate": _num(perf.win_rate, 6),
        "trade_count": perf.trade_count,
        "turnover": _num(perf.turnover, 4),
        "total_cost": _num(perf.total_cost, 4),
        "trading_days": perf.trading_days,
        "accounting_basis": getattr(result, "accounting_basis", None),
        "formal_valuation": bool(getattr(result, "formal_valuation", False)),
        "input_hash": getattr(result, "input_hash", None),
        "notes": list(getattr(result, "notes", []) or []),
        "range": f"{start}~{end}",
    }


def build_config_for(unit: dict) -> ValidationConfig:
    return ValidationConfig(
        is_start=unit["is_start"], is_end=unit["is_end"],
        oos_start=unit["oos_start"], oos_end=unit["oos_end"],
        ma_window_grid=list(unit["ma_window_grid"]),
        wf_grid=list(unit["wf_grid"] or [5, 20, 60]),
        pool_mode="all" if unit["etf_count"] > 20 else "representative",
    )


def study_oos_params(unit: dict) -> dict:
    """研究一：每个 MA 参数在 OOS 区间的只读表现。"""
    cfg = build_config_for(unit)
    rows = {}
    for ma in unit["ma_window_grid"]:
        try:
            rows[int(ma)] = run_research_backtest(
                cfg, MovingAverageTrendStrategy(ma_window=int(ma)),
                unit["etf_codes"], unit["oos_start"], unit["oos_end"],
            )
        except Exception as exc:  # noqa: BLE001 单参数失败不影响其他
            rows[int(ma)] = {"status": "failed",
                             "reason": f"{type(exc).__name__}: {exc}"[:200]}
    return rows


def study_benchmarks(unit: dict) -> dict:
    """研究三：同区间同口径的基准只读回测。"""
    cfg = build_config_for(unit)
    codes = unit["etf_codes"]
    out = {}
    specs = [
        ("buy_and_hold", "同池等权买入持有", codes, BuyAndHoldStrategy()),
        ("hs300", f"沪深300（{BENCHMARK_HS300_PROXY} ETF 代理）",
         [BENCHMARK_HS300_PROXY], BuyAndHoldStrategy()),
        ("zz500", f"中证500（{BENCHMARK_ZZ500_PROXY} ETF 代理）",
         [BENCHMARK_ZZ500_PROXY], BuyAndHoldStrategy()),
        ("ma_trend_best", "MA 趋势（本记录最优参数）",
         codes, MovingAverageTrendStrategy(ma_window=int(unit["best_param"]))),
    ]
    for key, name, use_codes, strat in specs:
        missing = [c for c in use_codes if c not in codes
                   and key in ("hs300", "zz500")]
        if key in ("hs300", "zz500") and use_codes[0] not in codes:
            out[key] = {"status": "unavailable",
                        "reason": f"{use_codes[0]} 不在该记录 ETF 池内，"
                                  "用代理基准会构成不同池比较"}
            continue
        try:
            r = run_research_backtest(cfg, strat, use_codes,
                                      unit["oos_start"], unit["oos_end"])
            r["name"] = name
            r["codes"] = use_codes
            out[key] = r
        except Exception as exc:  # noqa: BLE001
            out[key] = {"status": "failed",
                        "reason": f"{type(exc).__name__}: {exc}"[:200]}
    return out


# ---------------------------------------------------------------- 分析
def analyze_param_ranking(units: list[dict], *,
                         deduped: bool = False) -> dict:
    """研究一/二：参数排名稳定性 + MA250 边界效应。

    `deduped=True` 时只统计唯一 (config_hash, input_hash) 配置，
    避免 G1/G4 这类完全相同的重复记录给同一配置双倍权重。
    """
    if not deduped:
        units, _ = dedupe_by_config(units)
    rank_rows = []
    for u in units:
        # 键统一成 int：JSON 往返会把 int 键序列化成 str，
        # 不归一化会让 IS 最优(60) 与 OOS 最优('60') 比不相等。
        is_r = {int(ma): (d.get("total_return"))
                for ma, d in u["is_grid"].items()
                if d.get("status") == "success"}
        oos = u.get("oos_params") or {}
        oos_r = {int(ma): d.get("total_return") for ma, d in oos.items()
                 if d.get("status") != "failed" and d.get("total_return") is not None}
        if not is_r:
            continue
        is_order = sorted(is_r, key=lambda k: -is_r[k])
        oos_order = sorted(oos_r, key=lambda k: -oos_r[k]) if oos_r else []
        rank_rows.append({
            "tag": u["tag"], "record_id": u["record_id"],
            "etf_count": u["etf_count"],
            "is_returns": {str(k): _num(v) for k, v in sorted(is_r.items())},
            "is_ranking": [str(x) for x in is_order],
            "is_best": is_order[0],
            "is_best_on_boundary": is_order[0] in (min(is_r), max(is_r)),
            "oos_returns": {str(k): _num(v) for k, v in sorted(oos_r.items())},
            "oos_ranking": [str(x) for x in oos_order],
            "oos_best": oos_order[0] if oos_order else None,
            "is_oos_best_match": bool(oos_order and is_order[0] == oos_order[0]),
        })

    # MA250 边界分析
    ma250 = []
    for u in units:
        is_grid = {int(k): v for k, v in (u["is_grid"] or {}).items()}
        oos = {int(k): v for k, v in (u.get("oos_params") or {}).items()}
        def g(d, k):
            return (d.get(k) or {}).get("total_return")
        ma250.append({
            "tag": u["tag"],
            "is_ma120": g(is_grid, 120), "is_ma250": g(is_grid, 250),
            "oos_ma120": g(oos, 120), "oos_ma250": g(oos, 250),
            "best_param": u["best_param"],
            "grid_max": max(u["ma_window_grid"]) if u["ma_window_grid"] else None,
            "best_on_grid_max": (u["best_param"] == max(u["ma_window_grid"])
                                 if u["ma_window_grid"] else None),
        })

    n = len(rank_rows)
    boundary_hits = sum(1 for r in rank_rows if r["is_best_on_boundary"])
    ma250_first = sum(1 for r in rank_rows if r["is_best"] == 250)
    oos_match = sum(1 for r in rank_rows if r["is_oos_best_match"])
    oos_best_dist: dict[str, int] = {}
    for r in rank_rows:
        if r["oos_best"] is None:
            continue
        key = str(r["oos_best"])
        oos_best_dist[key] = oos_best_dist.get(key, 0) + 1
    oos250_first = sum(1 for r in rank_rows if r["oos_best"] == 250)
    return {
        "rows": rank_rows,
        "ma250_boundary": ma250,
        "basis": "unique_config_input_pairs" if deduped or True else "records",
        "summary": {
            "unit_count": n,
            "unit_basis": "unique (config_hash, input_hash) 配置",
            "is_best_on_boundary_count": boundary_hits,
            "is_best_on_boundary_ratio": _num(boundary_hits / n, 6) if n else None,
            "is_best_is_ma250_count": ma250_first,
            "is_best_is_ma250_ratio": _num(ma250_first / n, 6) if n else None,
            "is_oos_best_match_count": oos_match,
            "is_oos_best_match_ratio": _num(oos_match / n, 6) if n else None,
            "oos_best_param_distribution": oos_best_dist,
            "oos_best_is_ma250_count": oos250_first,
        },
    }


def analyze_walkforward(units: list[dict], *,
                        deduped: bool = True) -> dict:
    """研究五：Walk-Forward 稳定性。

    逐条窗口明细全部保留。所有汇总比例基于唯一配置，
    避免 G1/G4 这类完全相同的重复记录给同一组窗口双倍权重。
    """
    merged_note = None
    if deduped:
        units, merged = dedupe_by_config(units)
        if merged:
            merged_note = [m["tag"] for m in merged]
    rows = []
    for u in units:
        ws = [w for w in u["windows"] if w["status"] == "success"]
        if not ws:
            rows.append({"tag": u["tag"], "windows": [], "status": "unavailable"})
            continue
        rets = [w["test_total_return"] for w in ws
                if w["test_total_return"] is not None]
        params = [w["selected_param"] for w in ws]
        total = sum(rets)
        best = max(rets) if rets else None
        rows.append({
            "tag": u["tag"],
            "windows": ws,
            "window_count": len(ws),
            "params": params,
            "distinct_params": sorted(set(params)),
            "param_switch_count": sum(
                1 for a, b in zip(params, params[1:]) if a != b),
            "positive_windows": sum(1 for r in rets if r > 0),
            "negative_windows": sum(1 for r in rets if r < 0),
            "positive_ratio": _num(sum(1 for r in rets if r > 0) / len(rets), 6)
            if rets else None,
            "worst_window_return": _num(min(rets), 10) if rets else None,
            "best_window_return": _num(best, 10) if rets else None,
            "mean_window_return": _num(sum(rets) / len(rets), 10) if rets else None,
            "sum_window_return": _num(total, 10) if rets else None,
            "best_window_share_of_sum": _num(best / total, 6)
            if (best is not None and total) else None,
        })

    # 分层汇总：唯一配置层面
    ok_rows = [r for r in rows if r.get("status") != "unavailable"]
    n = len(ok_rows)
    concentrated = sum(
        1 for r in ok_rows
        if r["best_window_return"] is not None and r["sum_window_return"] is not None
        and r["best_window_return"] >= r["sum_window_return"])
    pos_ratios = [r["positive_ratio"] for r in ok_rows
                  if r["positive_ratio"] is not None]
    worst = [r["worst_window_return"] for r in ok_rows
             if r["worst_window_return"] is not None]
    # 真正不同的市场时间区间：按 (test 窗口集合) 归并
    tricky: dict[tuple, list[str]] = {}
    for r in ok_rows:
        sig = tuple((w["test_start"], w["test_end"]) for w in r["windows"])
        tricky.setdefault(sig, []).append(r["tag"])
    return {
        "rows": rows,
        "basis": "unique (config_hash, input_hash) 配置",
        "merged_for_summary": merged_note,
        "summary": {
            "unit_count": n,
            "unit_basis": "unique (config_hash, input_hash) 配置",
            "total_window_count": sum(r["window_count"] for r in ok_rows),
            "positive_ratio_min": _num(min(pos_ratios), 6) if pos_ratios else None,
            "positive_ratio_max": _num(max(pos_ratios), 6) if pos_ratios else None,
            "worst_window_return_min": _num(min(worst), 10) if worst else None,
            "worst_window_return_max": _num(max(worst), 10) if worst else None,
            "all_windows_positive_configs": sum(
                1 for r in ok_rows if r["positive_ratio"] == 1.0),
            "concentration_configs": concentrated,
            "concentration_definition": (
                "最好单窗口收益 >= 全部窗口收益之和，"
                "即扣掉最好窗口后其余窗口合计 <= 0"),
            "distinct_window_schedule_groups": len(tricky),
            "window_schedule_groups": [
                {"tags": sorted(v), "windows": len(k)}
                for k, v in sorted(tricky.items(), key=lambda kv: -len(kv[1]))
            ],
        },
    }


def analyze_dividend_cost(units: list[dict]) -> dict:
    """研究六：分红与成本贡献（用正式内部回测登记 + 只读基准对照）。"""
    rows = []
    for u in units:
        oos = u["oos_metrics"] or {}
        # 只用 OOS role 的分红明细：全角色合计会把 IS/WF/压力测试的分红
        # 混进 OOS 归因，属于重复计算，必须避免。
        oos_role = (u.get("by_role") or {}).get("out_of_sample") or {}
        bench = u.get("benchmarks") or {}
        bh = bench.get("buy_and_hold") or {}
        ma = bench.get("ma_trend_best") or {}
        oos_ret = oos.get("total_return")
        div_amt = oos_role.get("settled_amount")
        rows.append({
            "tag": u["tag"],
            "oos_total_return": oos_ret,
            "oos_total_cost": oos.get("total_cost"),
            "oos_trade_count": oos.get("trade_count"),
            "oos_turnover": oos.get("turnover"),
            "oos_applied_action_count": oos_role.get("applied"),
            "oos_receivable_count": oos_role.get("receivables"),
            "oos_dividend_settled_amount": div_amt,
            "oos_initial_cash": 1000000.0,
            "dividend_pct_of_initial": (
                _num(div_amt / 1000000.0, 6) if div_amt is not None else None),
            "return_without_dividend": (
                _num(oos_ret - div_amt / 1000000.0, 10)
                if (oos_ret is not None and div_amt is not None) else None),
            "dividend_share_of_return": (
                _num((div_amt / 1000000.0) / oos_ret, 6)
                if (oos_ret not in (None, 0) and div_amt is not None) else None),
            "buyhold_total_return": bh.get("total_return"),
            "buyhold_total_cost": bh.get("total_cost"),
            "buyhold_trade_count": bh.get("trade_count"),
            "cost_drag_pct": (
                _num((oos.get("total_cost") or 0) / 1000000.0, 6)
                if oos.get("total_cost") is not None else None),
            "ma_gross_minus_buyhold": (
                _num((ma.get("total_return") or 0) - (bh.get("total_return") or 0), 10)
                if (ma.get("total_return") is not None
                    and bh.get("total_return") is not None) else None),
        })
    return {
        "rows": rows,
        "note": ("分红金额只取 run_role='out_of_sample' 的内部回测明细；"
                 "初始资金 1,000,000 元，因此「分红占初始资金比例」可直接与"
                 "total_return 做算术比较。不使用全角色合计，避免重复计算。"),
    }


def grade_evidence(units: list[dict], ranking: dict, wf: dict, bench: dict) -> dict:
    """研究七：证据分级（严格，不因重放次数增加强度）。

    统计基础是唯一 (config_hash, input_hash) 配置，不是正式记录条数。
    独立样本数不可严谨定义，明确写 not_estimable。
    """
    uniq, merged = dedupe_by_config(units)
    layers = count_layers(units)

    # 超额收益：MA 最优 vs 同池 Buy & Hold（OOS），按唯一配置
    excess = []
    for u in uniq:
        b = (u.get("benchmarks") or {}).get("buy_and_hold") or {}
        o = (u.get("oos_metrics") or {}).get("total_return")
        if b.get("total_return") is not None and (o is not None):
            excess.append({
                "tag": u["tag"], "record_id": u["record_id"],
                "ma": _num(o, 10),
                "buyhold": _num(b["total_return"], 10),
                "excess": _num(o - b["total_return"], 10),
            })
    vals = sorted(e["excess"] for e in excess if e["excess"] is not None)
    beat = sum(1 for v in vals if v > 0)
    lose = sum(1 for v in vals if v < 0)
    median = None
    if vals:
        mid = len(vals) // 2
        median = _num(vals[mid] if len(vals) % 2
                      else (vals[mid - 1] + vals[mid]) / 2, 10)

    return {
        "included_records": layers["included_records"],
        "unique_config_input_pairs": layers["unique_config_input_pairs"],
        "unique_oos_result_fingerprints": layers["unique_oos_result_fingerprints"],
        "statistically_independent_samples": "not_estimable",
        "not_estimable_reason": layers["not_estimable_reason"],
        "shared_market_periods": layers["shared_market_periods"],
        "shared_is_periods": layers["shared_is_periods"],
        "shared_pools": layers["shared_pools"],
        "deduped_records": merged,
        "excess_vs_buyhold": excess,
        "excess_basis": "unique (config_hash, input_hash) 配置，共 %d 组" % len(excess),
        "beat_buyhold_count": beat,
        "lose_buyhold_count": lose,
        "beat_buyhold_total": len(excess),
        "excess_min": _num(min(vals), 10) if vals else None,
        "excess_max": _num(max(vals), 10) if vals else None,
        "excess_median": median,
        "note": ("统计基础为唯一配置（不是正式记录条数）。"
                 "这些配置共享同一行情库、同一策略代码、同一成本参数、"
                 "同一会计口径，主要 OOS 区间基本相同，彼此强相关；"
                 "唯一配置数与结果指纹数都不是独立样本数。"),
    }


# ---------------------------------------------------------------- 主流程
def _reuse_previous(payload: dict, units: list[dict]) -> None:
    """把上一次跑出来的 OOS 参数扫描与基准结果贴回本轮 unit。

    统计修正不需要重跑回测：`oos_params` 与 `benchmarks` 是纯只读重算的
    确定结果，同一份行情 + 同一份正式记录必然产出同一组数字。
    这里只复用这两块，其余字段（含审计明细）仍从数据库实时读取。
    """
    prev = {u["tag"]: u for u in (payload.get("units") or [])}
    for u in units:
        old = prev.get(u["tag"])
        if not old:
            continue
        if "oos_params" in old:
            u["oos_params"] = old["oos_params"]
        if "benchmarks" in old:
            u["benchmarks"] = old["benchmarks"]


def main(out_dir: Path, *, reuse_json: bool = False) -> dict:
    units = load_units()
    included = [u for u in units if u.get("included")]
    print(f"读取 {len(units)} 条研究单元，纳入 {len(included)} 条", flush=True)

    jp = out_dir / "phase3B1_strategy_effectiveness_baseline.json"
    if reuse_json and jp.exists():
        prev = json.loads(jp.read_text(encoding="utf-8"))
        _reuse_previous(prev, included)
        missing = [u["tag"] for u in included if "oos_params" not in u]
        if missing:
            raise SystemExit(f"复用失败，缺少 OOS 参数结果：{missing}")
        print("  复用上次的 OOS 参数扫描与基准回测结果（不重跑）", flush=True)
    else:
        for u in included:
            print(f"  OOS 参数扫描 {u['tag']} ({u['etf_count']} 只)...", flush=True)
            u["oos_params"] = study_oos_params(u)
            print(f"  基准回测 {u['tag']}...", flush=True)
            u["benchmarks"] = study_benchmarks(u)

    ranking = analyze_param_ranking(included)
    wf = analyze_walkforward(included)
    divcost = analyze_dividend_cost(included)
    bench_cmp = {
        "rows": [{"tag": u["tag"], "benchmarks": u.get("benchmarks")}
                 for u in included],
        "oos_metrics": [{"tag": u["tag"], "metrics": u.get("oos_metrics")}
                        for u in included],
    }
    grade = grade_evidence(included, ranking, wf, bench_cmp)

    fp = fingerprint_from_db()
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "phase": "3B-1",
        "baseline_head": "cccca5a84d1abd04eaaef01afea6462cdf140d3d",
        "market_fingerprint": fp,
        "formal_gate": {
            "accounting_version": FORMAL_ACC,
            "accounting_basis": FORMAL_BASIS,
            "formal_valuation": True,
        },
        "units": units,
        "included_units": [u["tag"] for u in included],
        "statistical_layers": count_layers(included),
        "param_ranking": ranking,
        "walkforward": wf,
        "dividend_cost": divcost,
        "benchmark": bench_cmp,
        "evidence_grading": grade,
        "limitations": [
            "OOS 逐参数表现由本脚本只读重算，未写入 validation 正式记录，"
            "属于研究数据，不构成新的正式验证结论。",
            "沪深300/中证500 用 ETF 代理（510300/510500），含跟踪误差与交易费用，"
            "不是指数本身。",
            "8 组配置共享同一行情库、同一成本参数、基本同一 OOS 区间，"
            "存在相关性，不能按 8 份独立证据计。",
            "regime 统计来自正式 validation_regime_stats，"
            "但只覆盖最优参数的一条 OOS 轨迹，不是全参数覆盖。",
            "IS 区间存在 2021-01-04 与 2021-06-01 两种起点，"
            "OOS 区间存在 2025-01-02 与 2025-06-03 两种起点，"
            "跨配置比较时必须注意不可直接拼接。",
        ],
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    jp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"JSON -> {jp}", flush=True)
    return payload


if __name__ == "__main__":
    target = ROOT / "reports"
    main(target, reuse_json="--reuse" in sys.argv)
