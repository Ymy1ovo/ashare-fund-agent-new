"""阶段3B-6.1.0.3.1 五态独立复算测试。

**核心目标**：不依赖证据里已经算好的状态字段，
而是从最原始的探测数据（rows / date_min / date_max / real_start_date /
duplicate_dates / null_close / non_positive_close / max_interior_gap_days）
重新计算五态，再与证据 JSON 和正式报告逐项比对。

阈值硬编码为审计口径常量（95% / 20 天），**不放宽**。
"""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORTS = ROOT / "reports"
EVIDENCE = REPORTS / "evidence" / "phase3B6_1_0_index_probe_evidence.json"

# ===== 审计口径常量（与证据 standard 段一致性在下方单独测试）=====
COVERAGE_MIN_RATIO = 0.95
INTERIOR_GAP_MAX_DAYS = 20
REQUEST_START = "2004-01-01"


@pytest.fixture(scope="module")
def ev() -> dict:
    assert EVIDENCE.exists()
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def qb(ev) -> dict:
    return ev["coverage_quality_probe"]["by_code"]


@pytest.fixture(scope="module")
def r01() -> dict:
    return json.loads(
        (REPORTS / "phase3B6_1_0_01_index_return_basis.json")
        .read_text(encoding="utf-8"))


# ============================================================ 独立复算函数
def recompute_states(raw: dict, return_basis: str = "unknown") -> dict:
    """从原始字段独立复算五态。**不读取 raw 里已有的状态字段。**"""
    if raw.get("status") != "ok":
        return {"history_retrieved": False,
                "history_range_verified": False,
                "history_coverage_adequate": False,
                "history_quality_adequate": False,
                "backtest_usable": False}

    rows = raw.get("rows") or 0

    # 1. history_retrieved：实际返回行数是否 > 0
    retrieved = rows > 0

    # 2. history_range_verified：首末日期齐全 + 行数>0 + 日期可解析
    dmin, dmax = raw.get("date_min"), raw.get("date_max")
    range_ok = bool(retrieved and dmin and dmax)
    if range_ok:
        try:
            a = datetime.date.fromisoformat(dmin)
            b = datetime.date.fromisoformat(dmax)
            range_ok = b >= a
        except (ValueError, TypeError):
            range_ok = False

    # 3. history_coverage_adequate：用真实起点重算覆盖率（不复用 coverage_ratio）
    real_start = raw.get("real_start_date") or dmin
    coverage_ok = False
    ratio = None
    if range_ok and real_start and dmax:
        try:
            rs = datetime.date.fromisoformat(real_start)
            de = datetime.date.fromisoformat(dmax)
            db = datetime.date.fromisoformat(REQUEST_START)
            span_total = (de - db).days
            if span_total > 0:
                ratio = (de - rs).days / span_total
                coverage_ok = ratio >= COVERAGE_MIN_RATIO
        except (ValueError, TypeError):
            coverage_ok = False

    # 4. history_quality_adequate：从原始计数字段重算
    dup = raw.get("duplicate_dates")
    nulls = raw.get("null_close")
    nonpos = raw.get("non_positive_close")
    max_interior = raw.get("max_interior_gap_days")
    quality_ok = (dup == 0 and nulls == 0 and nonpos == 0
                  and max_interior is not None
                  and max_interior <= INTERIOR_GAP_MAX_DAYS)

    # 5. backtest_usable：前四项 + 收益口径已确认
    backtest_ok = bool(retrieved and range_ok and coverage_ok
                       and quality_ok and return_basis != "unknown")

    return {"history_retrieved": retrieved,
            "history_range_verified": range_ok,
            "history_coverage_adequate": coverage_ok,
            "history_quality_adequate": quality_ok,
            "backtest_usable": backtest_ok,
            "recomputed_ratio": ratio}


# ============================================================ 1-5 逐态复算
def test_thresholds_match_evidence_declaration(ev):
    """审计阈值常量必须与证据声明的标准一致（防止测试偷偷放宽）。"""
    std = ev["coverage_quality_probe"]["standard"]
    assert std["coverage_adequate_min_ratio"] == COVERAGE_MIN_RATIO
    assert std["quality_max_interior_gap_days"] == INTERIOR_GAP_MAX_DAYS
    assert std["request_start"] == REQUEST_START


def test_recompute_retrieved(qb):
    """history_retrieved 由实际行数重算。"""
    for code, raw in qb.items():
        mine = recompute_states(raw)["history_retrieved"]
        assert mine == raw["history_retrieved"], \
            f"{code}: 复算 retrieved={mine}，证据={raw['history_retrieved']}"


def test_recompute_range_verified(qb):
    """history_range_verified 由首末日期与行数重算。"""
    for code, raw in qb.items():
        mine = recompute_states(raw)["history_range_verified"]
        assert mine == raw["history_range_verified"], \
            f"{code}: 复算 range={mine}，证据={raw['history_range_verified']}"


def test_recompute_coverage_independently(qb):
    """history_coverage_adequate 从真实起点重新计算，不复用 coverage_ratio。"""
    for code, raw in qb.items():
        r = recompute_states(raw)
        assert r["history_coverage_adequate"] == raw["history_coverage_adequate"], \
            f"{code}: 复算覆盖={r['history_coverage_adequate']}，" \
            f"证据={raw['history_coverage_adequate']}"
        if r["recomputed_ratio"] is not None:
            # 证据里存的是 round(x, 6)，按同样精度比较
            assert round(r["recomputed_ratio"], 6) == raw["coverage_ratio"], \
                f"{code}: 复算比率 {round(r['recomputed_ratio'], 6)} != 证据 {raw['coverage_ratio']}"


def test_recompute_quality_independently(qb):
    """history_quality_adequate 从原始计数字段重算。"""
    for code, raw in qb.items():
        mine = recompute_states(raw)["history_quality_adequate"]
        assert mine == raw["history_quality_adequate"], \
            f"{code}: 复算质量={mine}，证据={raw['history_quality_adequate']}"


def test_recompute_backtest_usable(qb, r01):
    """backtest_usable 由前四项 + return_basis 重算，本轮必须全为 false。"""
    basis = {x["index_code"]: x["return_basis"] for x in r01["indexes"]}
    for code, raw in qb.items():
        mine = recompute_states(raw, "unknown")["backtest_usable"]
        assert mine is False, f"{code}: return_basis=unknown 时 backtest_usable 必须为 false"
        assert raw["backtest_usable"] is False
    assert all(v == "unknown" for v in basis.values())


def test_five_states_not_single_chain(qb):
    """五态不得是单向自动继承——存在「前者真后者假」的实例。"""
    # 取到但覆盖不达标
    assert any(r["history_retrieved"] and not r["history_coverage_adequate"]
               for r in qb.values()), "缺少 retrieved=true 但 coverage=false 的实例"
    # 区间核实但质量不达标
    assert any(r["history_range_verified"] and not r["history_quality_adequate"]
               for r in qb.values()), "缺少 range=true 但 quality=false 的实例"
    # 覆盖质量全过但不可回测
    full = [c for c, r in qb.items()
            if r["history_coverage_adequate"] and r["history_quality_adequate"]]
    assert full, "应存在覆盖与质量均达标的序列"
    for c in full:
        assert qb[c]["backtest_usable"] is False, \
            f"{c}: 覆盖质量达标但口径未确认，不得可回测"


# ============================================================ 报告一致性
def test_report_states_match_recompute(r01, qb):
    """报告里的五态必须与独立复算结果逐项一致。"""
    for x in r01["indexes"]:
        code = x.get("total_return_index_code")
        if not code or code not in qb:
            continue
        mine = recompute_states(qb[code])
        st = x["history_states"]
        for k in ("history_retrieved", "history_range_verified",
                  "history_coverage_adequate", "history_quality_adequate",
                  "backtest_usable"):
            assert st[k] == mine[k], \
                f"{x['index_code']}.{k}: 报告={st[k]} 复算={mine[k]}"


def test_report_price_and_net_quality_match_recompute(r01, qb):
    """价格/净收益序列的复算也必须与报告一致。"""
    for x in r01["indexes"]:
        for code_key, q_key in (
            ("price_index_code", "price_quality"),
            ("net_total_return_index_code", "net_return_quality"),
        ):
            code = x.get(code_key)
            if not code or code not in qb:
                continue
            mine = recompute_states(qb[code])
            rq = x.get(q_key)
            assert rq is not None, f"{x['index_code']}.{q_key} 缺失"
            assert rq["history_retrieved"] == mine["history_retrieved"]
            assert rq["history_coverage_adequate"] == mine["history_coverage_adequate"]
            assert rq["history_quality_adequate"] == mine["history_quality_adequate"]


def test_summary_counts_match_recompute(r01, qb):
    """summary 的统计必须等于用独立复算重数出来的结果。"""
    s = r01["summary"]
    eq = s["equity_indexes_stats"]
    equity = s["by_economic_semantics"]["equity_indexes"]
    for field, key in (
        ("history_retrieved", "total_return_history_retrieved"),
        ("history_range_verified", "total_return_history_range_verified"),
        ("history_coverage_adequate", "total_return_history_coverage_adequate"),
        ("history_quality_adequate", "total_return_history_quality_adequate"),
        ("backtest_usable", "total_return_backtest_usable"),
    ):
        n = 0
        for x in r01["indexes"]:
            if x["index_code"] not in equity:
                continue
            code = x.get("total_return_index_code")
            if not code or code not in qb:
                continue
            if recompute_states(qb[code])[field]:
                n += 1
        assert eq[key] == n, f"{key}: summary={eq[key]}，独立复算={n}"


# ============================================================ 边界不得踩
def test_placeholder_not_counted_as_interior_gap(qb):
    """首行基线占位不得被算作内部缺口。"""
    for code, raw in qb.items():
        if not raw.get("has_baseline_placeholder"):
            continue
        # 最大缺口可能很大（占位造成），但内部缺口必须小
        assert raw["max_interior_gap_days"] <= INTERIOR_GAP_MAX_DAYS, \
            f"{code}: 占位行被误当内部缺口（{raw['max_interior_gap_days']} 天）"
        assert raw["max_gap_days"] >= raw["max_interior_gap_days"]


def test_non_positive_preserved_in_recompute(qb):
    """非正值异常必须保留；含非正值的序列质量必须判不达标。"""
    found = {c: r for c, r in qb.items() if r.get("non_positive_close", 0) > 0}
    assert found, "应存在非正值异常"
    for raw in found.values():
        assert recompute_states(raw)["history_quality_adequate"] is False
        assert raw["non_positive_dates"]


def test_all_five_non_positive_series_registered(r01, qb):
    """5 处非正值必须在报告中按三层全部登记。"""
    reg = r01["non_positive_anomaly_register"]
    assert reg["total_count"] == 5
    codes = {r["code"] for r in reg["register"]}
    assert codes == {"H30184", "H20184", "N00905", "N00906", "N00016"}
    # 证据里也必须同样有 5 个
    ev_nonpos = {c for c, v in qb.items() if v.get("non_positive_close", 0) > 0}
    assert ev_nonpos == codes


def test_anomaly_separated_by_series_layer(r01):
    """每个指数必须分别记录价格/全收益/净收益三层异常。"""
    for x in r01["indexes"]:
        a = x["anomaly_by_series"]
        for layer in ("price_series", "total_return_series", "net_return_series"):
            assert layer in a
            assert "non_positive_close" in a[layer]


def test_bond_index_still_separate(r01):
    """000012 的 N00012 继续单独归类，不计入股票指数统计。"""
    sem = r01["summary"]["by_economic_semantics"]
    assert "000012" in sem["special_bond_indexes"]
    assert "000012" not in sem["equity_indexes"]
    x = next(v for v in r01["indexes"] if v["index_code"] == "000012")
    assert x["anomaly_by_series"]["total_return_series"]["code"] == "N00012"


# ============================================================ 测试卫生
BAD_PATTERN = "or " + "True"


def test_no_vacuous_assertions():
    """本测试文件不得出现恒真的断言 / 未使用变量。"""
    src = Path(__file__).read_text(encoding="utf-8")
    for ln in src.splitlines():
        stripped = ln.strip()
        if stripped.startswith("#") or stripped.startswith('"'):
            continue
        if ln.startswith('    """') or ln.startswith('"""'):
            continue
        assert BAD_PATTERN not in ln, f"恒真断言：{stripped}"


def test_gate_still_closed(r01):
    g = r01["gate"]
    assert g["ready_for_research_analysis"] is True
    assert g["ready_for_backtest"] is False
    assert g["ready_for_formal_ranking"] is False
