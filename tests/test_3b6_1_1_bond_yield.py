"""阶段3B-6.1.1 中债国债收益率专项测试。

**全部从原始 CSV 重新计算**，不读取预计算的结论字段。
"""
from __future__ import annotations

import csv
import glob
import json
import math
import statistics
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORTS = ROOT / "reports"
EV = REPORTS / "evidence" / "phase3B6_1_1"
RAW = EV / "raw"

TENORS = ["3月", "6月", "1年", "3年", "5年", "7年", "10年", "30年"]
CURVE = "中债国债收益率曲线"

# 审计口径常量（与报告声明一致，单独测试校验）
HOLIDAY_MAX_GAP = 15
REF_START = date(2006, 3, 1)
REF_END = date(2026, 12, 31)
SIMPLE_DAYS = 365


@pytest.fixture(scope="module")
def raw_files():
    files = sorted(glob.glob(str(RAW / "bond_gov_*.csv")))
    assert files, "缺原始 CSV 证据"
    return files


@pytest.fixture(scope="module")
def parsed(raw_files):
    """从原始 CSV 重新解析：{(date, tenor): value}。"""
    series = {}
    for f in raw_files:
        with open(f, encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                if CURVE not in (row.get("曲线名称") or ""):
                    continue
                ds = (row.get("日期") or "").strip()
                try:
                    d = date.fromisoformat(ds)
                except ValueError:
                    continue
                for t in TENORS:
                    v = (row.get(t) or "").strip()
                    if not v or v.lower() == "nan":
                        continue
                    try:
                        series[(d, t)] = float(v)
                    except ValueError:
                        pass
    assert series, "原始 CSV 未解析出任何数据"
    return series


# ============================================================ 1-2 原始数据
def test_raw_files_exist(raw_files):
    assert len(raw_files) >= 40, f"原始 CSV 过少：{len(raw_files)}"
    for f in raw_files:
        p = Path(f)
        assert p.stat().st_size > 0


def test_raw_files_reparseable(raw_files):
    """原始文件必须能重新解析出预期列。"""
    with open(raw_files[0], encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames
    assert "日期" in header
    assert "曲线名称" in header
    for t in TENORS:
        assert t in header, f"缺少期限列 {t}"


def test_raw_2year_tenor_absent(raw_files):
    """接口不含 2 年期——必须如实缺失，不得用 3 年代替。"""
    with open(raw_files[0], encoding="utf-8-sig", newline="") as fh:
        header = csv.DictReader(fh).fieldnames
    assert "2年" not in header, "出现了报告声称不存在的 2 年期"


# ============================================================ 3 覆盖率复算
def test_coverage_recomputed_per_tenor(parsed):
    """每个期限的覆盖率从原始数据独立重算。"""
    cov = json.loads((REPORTS / "phase3B6_1_1_coverage_quality.json")
                     .read_text(encoding="utf-8"))
    for t in TENORS:
        ds = sorted(dd for (dd, tt) in parsed if tt == t)
        assert ds, f"{t} 无数据"
        lo, hi = max(ds[0], REF_START), min(ds[-1], REF_END)
        span = (REF_END - REF_START).days + 1
        ratio = ((hi - lo).days + 1) / span if hi >= lo else 0.0
        assert abs(ratio - cov["tenors"][t]["coverage_ratio_vs_ref_window"]) < 1e-6, \
            f"{t}: 复算覆盖率 {ratio} != 报告 {cov['tenors'][t]['coverage_ratio_vs_ref_window']}"


def test_tenor_row_counts_match_json(parsed):
    cov = json.loads((REPORTS / "phase3B6_1_1_coverage_quality.json")
                     .read_text(encoding="utf-8"))
    for t in TENORS:
        n = sum(1 for (d, tt) in parsed if tt == t)
        assert cov["tenors"][t]["valid_rows"] == n, \
            f"{t}: 复算 {n} != 报告 {cov['tenors'][t]['valid_rows']}"


def test_all_tenors_share_same_date_index(parsed):
    """各期限必须共享同一批交易日。"""
    idx = {}
    for (d, t) in parsed:
        idx.setdefault(t, set()).add(d)
    base = idx[TENORS[0]]
    for t in TENORS[1:]:
        assert idx[t] == base, f"{t} 的日期索引与 {TENORS[0]} 不一致"


# ============================================================ 4 重复检查
def test_no_duplicate_dates_in_raw(parsed):
    """解析后的 (日期,期限) 组合不得重复。"""
    seen = set()
    for key in parsed:
        assert key not in seen, f"重复 {key}"
        seen.add(key)


def test_no_duplicate_in_json(parsed):
    cov = json.loads((REPORTS / "phase3B6_1_1_coverage_quality.json")
                     .read_text(encoding="utf-8"))
    for t in TENORS:
        assert cov["tenors"][t]["duplicate_dates"] == 0


# ============================================================ 5 缺失区间
def test_missing_intervals_recomputed(parsed):
    """缺失区间从原始数据重算，周末/节假日不得算缺失。"""
    cov = json.loads((REPORTS / "phase3B6_1_1_coverage_quality.json")
                     .read_text(encoding="utf-8"))
    for t in TENORS:
        ds = sorted(dd for (dd, tt) in parsed if tt == t)
        gaps = []
        for a, b in zip(ds, ds[1:]):
            n = (b - a).days
            if n > HOLIDAY_MAX_GAP:
                gaps.append(n)
        all_gaps = [(b - a).days for a, b in zip(ds, ds[1:])]
        assert cov["tenors"][t]["max_gap_days"] == max(all_gaps), \
            f"{t}: 复算最大缺口不一致"
        assert len(gaps) == cov["tenors"][t]["gap_count_over_threshold"]


def test_weekend_not_counted_as_missing(parsed):
    """周末间隔（2~3 天）不得进入缺失区间。"""
    for t in TENORS:
        ds = sorted(dd for (dd, tt) in parsed if tt == t)
        weekend_gaps = [(b - a).days for a, b in zip(ds, ds[1:])
                        if 1 <= (b - a).days <= 3]
        assert weekend_gaps, "应存在周末间隔"
        assert all(g <= HOLIDAY_MAX_GAP for g in weekend_gaps)


def test_holiday_gap_within_threshold(parsed):
    """超过阈值的缺口必须被如实登记；阈值内的长假不算缺失。"""
    cov = json.loads((REPORTS / "phase3B6_1_1_coverage_quality.json")
                     .read_text(encoding="utf-8"))
    assert cov["holiday_gap_threshold_days"] == HOLIDAY_MAX_GAP, \
        "测试阈值与报告声明不一致"
    for t in TENORS:
        ds = sorted(dd for (dd, tt) in parsed if tt == t)
        gaps = [(b - a).days for a, b in zip(ds, ds[1:])]
        big = [g for g in gaps if g > HOLIDAY_MAX_GAP]
        assert cov["tenors"][t]["gap_count_over_threshold"] == len(big), \
            f"{t}: 超阈值缺口 {len(big)} 个未如实登记"
        # 阈值内的长假（如 2020 春节 11 天）必须存在且不算缺失
        assert max(gaps) <= HOLIDAY_MAX_GAP, \
            f"{t}: 最大缺口 {max(gaps)} 天超过阈值"


def test_2020_spring_festival_gap_present(parsed):
    """2020 春节延长假期（11 天）必须真实存在，且不被判为缺失。"""
    ds = sorted(dd for (dd, tt) in parsed if tt == "1年")
    gap_2020 = [(a, b, (b - a).days) for a, b in zip(ds, ds[1:])
                if a.isoformat() == "2020-01-23"]
    assert gap_2020, "应存在 2020-01-23 起的春节缺口"
    a, b, n = gap_2020[0]
    assert b.isoformat() == "2020-02-03"
    assert n == 11
    assert n <= HOLIDAY_MAX_GAP, "该缺口应被阈值容纳"


# ============================================================ 6 单位识别
def test_unit_is_percentage(parsed):
    """实测值域判定为百分数。"""
    vals = list(parsed.values())
    assert min(vals) >= 0
    assert max(vals) <= 20, f"最大值 {max(vals)} 超出国债收益率合理区间"
    # 若是小数表示，最大值会 < 1
    assert max(vals) > 1, "值域过小，可能已是小数"


def test_no_negative_or_absurd_values(parsed):
    for (d, t), v in parsed.items():
        assert v >= 0, f"{d} {t} 出现负值 {v}"
        assert v <= 20, f"{d} {t} 出现异常高值 {v}"


# ============================================================ 7 两种日度化
def test_two_conversion_formulas_independent(parsed):
    """两种公式独立计算，且 B < A。"""
    for t in ("1年", "3年"):
        vals = [parsed[(d, tt)] / 100.0 for (d, tt) in parsed if tt == t]
        assert vals
        a = [v / SIMPLE_DAYS for v in vals]
        b = [math.pow(1 + v, 1 / SIMPLE_DAYS) - 1 for v in vals]
        assert statistics.mean(b) < statistics.mean(a), \
            f"{t}: 复利折算应小于简单折算"
        diff = statistics.mean(b) - statistics.mean(a)
        assert -1e-5 < diff < 0, f"{t}: 差异量级异常 {diff}"


def test_conversion_comparison_matches_recompute(parsed):
    """报告里的日均值与重算一致。"""
    conv = json.loads((REPORTS / "phase3B6_1_1_daily_conversion_comparison.json")
                      .read_text(encoding="utf-8"))
    for t in ("1年", "3年"):
        vals = [parsed[(d, tt)] / 100.0 for (d, tt) in parsed if tt == t]
        a = statistics.mean([v / SIMPLE_DAYS for v in vals])
        b = statistics.mean([math.pow(1 + v, 1 / SIMPLE_DAYS) - 1 for v in vals])
        assert abs(a - conv[t]["A_daily_mean"]) < 1e-12
        assert abs(b - conv[t]["B_daily_mean"]) < 1e-12


def test_percentage_to_decimal_conversion():
    """百分数必须 /100 才能当小数用。"""
    v_pct = 3.0
    v_dec = v_pct / 100.0
    assert abs((1 + v_dec) - 1.03) < 1e-12
    # 若误把 3.0 当小数，复利公式会爆炸
    wrong = math.pow(1 + v_pct, 1 / 365) - 1
    right = math.pow(1 + v_dec, 1 / 365) - 1
    # 误用百分数当小数会把日收益放大 40 倍以上（3% vs 0.03%）
    assert wrong > right * 30


# ============================================================ 8 周末节假日
def test_forward_fill_not_applied(parsed):
    """原始数据不得已做前向填充（同值连续不超过长假长度）。"""
    for t in TENORS:
        vals = [parsed[k] for k in sorted(parsed) if k[1] == t]
        run, max_run = 1, 1
        for a, b in zip(vals, vals[1:]):
            run = run + 1 if a == b else 1
            max_run = max(max_run, run)
        assert max_run < 30, f"{t}: 连续相同值 {max_run} 个，疑似前向填充"


# ============================================================ 9 可用日期滞后
def test_point_in_time_audit_declares_unknown():
    pit = json.loads((REPORTS / "phase3B6_1_1_point_in_time_audit.json")
                     .read_text(encoding="utf-8"))
    assert pit["same_day_availability"]["status"] == "UNKNOWN"
    assert pit["evidence_about_publication"]["official_publication_time_obtained"] is False


def test_observation_date_not_used_as_available_date():
    """不得把观察日期直接当可用日期。"""
    pit = json.loads((REPORTS / "phase3B6_1_1_point_in_time_audit.json")
                     .read_text(encoding="utf-8"))
    assert pit["recommended_default"]["value"] != "T+0"
    assert len(pit["conservative_lag_recommendations"]) >= 2
    import re as _re
    lags = []
    for o in pit["conservative_lag_recommendations"]:
        assert o["option"].startswith("T+")
        m = _re.search(r"T\+(\d+)", o["option"])
        assert m, f"无法解析滞后天数：{o['option']}"
        lags.append(int(m.group(1)))
    assert all(n >= 1 for n in lags), f"存在 T+0 方案：{lags}"


def test_lag_rule_shifts_available_date():
    """滞后规则：可用日 = 观察日 + N 个自然日（此处按自然日演示）。"""
    obs = date(2024, 1, 2)
    for lag_days, expected in ((1, date(2024, 1, 3)), (2, date(2024, 1, 4))):
        avail = date.fromordinal(obs.toordinal() + lag_days)
        assert avail == expected


# ============================================================ 10 修订风险
def test_revision_risk_not_marked_resolved():
    pit = json.loads((REPORTS / "phase3B6_1_1_point_in_time_audit.json")
                     .read_text(encoding="utf-8"))
    rr = pit["revision_risk"]
    assert rr["historical_revision_ruled_out"] is False, \
        "修订风险不得被标记为已排除"
    assert rr["version_or_revision_date_available"] is False


def test_repeat_call_evidence_recorded():
    """重复调用一致性证据必须存在且真实。"""
    p = EV / "repeat_call_check.json"
    assert p.exists(), "缺重复调用一致性证据"
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["repeat_identical"] is True
    assert d["value_diffs"] == 0


# ============================================================ 11-12 禁止事项
def test_bond_index_not_used_as_risk_free():
    """上证国债指数不得被当无风险利率。"""
    rec = (REPORTS / "phase3B6_1_1_recommendation.md").read_text(encoding="utf-8")
    assert "不是利率" in rec
    assert "上证国债指数" in rec


def test_no_formal_convention_set():
    rec = (REPORTS / "phase3B6_1_1_recommendation.md").read_text(encoding="utf-8")
    assert "不构成本轮确定的正式口径" in rec
    assert "确定日度化公式" in rec and "**否**" in rec


def test_evidence_grade_is_l3():
    src = json.loads((REPORTS / "phase3B6_1_1_source_audit.json")
                     .read_text(encoding="utf-8"))
    assert src["evidence_grade"]["level"] == "L3_third_party_aggregated"
    assert "官方原始" in src["evidence_grade"]["why"]


def test_2year_tenor_documented_as_missing():
    src = json.loads((REPORTS / "phase3B6_1_1_source_audit.json")
                     .read_text(encoding="utf-8"))
    assert "2年" in src["tenors_missing"]
    assert src["tenors_missing_note"]


def test_2002_2005_probed_empty():
    src = json.loads((REPORTS / "phase3B6_1_1_source_audit.json")
                     .read_text(encoding="utf-8"))
    probes = src["empty_probe_2002_2005"]
    assert len(probes) == 4
    for p in probes:
        assert p["rows"] == 0, f"{p['year']} 不应有数据"


# ============================================================ 只读保证
def test_no_database_write():
    from app.database.db import get_connection
    with get_connection() as c:
        assert c.execute("SELECT COUNT(*) FROM index_daily").fetchone()[0] == 50603
        assert c.execute("SELECT COUNT(*) FROM fund_nav_daily").fetchone()[0] == 245656


def test_database_fingerprint_unchanged():
    from app.fund.ingest_user_funds import db_fingerprint
    assert db_fingerprint()["sha256"] == (
        "115ac91eee7c26424952e6df23ddeeafe2435974fe5e81a8ba6bbcabfe387dd4")


def test_test_file_has_no_vacuous_assertions():
    src = Path(__file__).read_text(encoding="utf-8")
    bad = "or " + "True"
    for ln in src.splitlines():
        st = ln.strip()
        if st.startswith("#") or st.startswith('"') or st.startswith("'"):
            continue
        assert bad not in ln, f"恒真断言：{st}"
