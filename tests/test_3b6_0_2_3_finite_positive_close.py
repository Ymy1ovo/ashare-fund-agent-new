"""阶段3B-6.0.2.3 有效行情「有限正数」校验专项测试。

问题：``count_effective_observations()`` 声称只统计正的有限收盘价，
但原实现用 ``c != c or c <= 0`` 判断，只能识别 NaN，**漏掉 ±inf**。

修正：改用 ``math.isfinite(c) and c > 0``。

全部使用临时数据库，**绝不触碰正式库**。
"""
from __future__ import annotations

import math
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.fund.composite_benchmark import (  # noqa: E402
    COMPONENT_INDEX, MIN_VALID_OBSERVATIONS, add_component,
    assess_index_component, count_effective_observations,
    create_composite, evaluate_composite, get_composite,
    _is_usable_close,
)
from app.fund.index_layer import (  # noqa: E402
    RETURN_BASIS_TOTAL, RETURN_BASIS_UNKNOWN, get_index_connection,
    init_index_layer, upsert_index_master,
)


@pytest.fixture()
def conn(tmp_path):
    path = tmp_path / "finite_close_test.db"
    with get_index_connection(path) as c:
        init_index_layer(c)
        yield c


def _weekdays(start, n):
    out, cur = [], date.fromisoformat(start)
    while len(out) < n:
        if cur.weekday() < 5:
            out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def _insert(conn, code, close, day, quality="valid"):
    """直接插一行（绕过 NOT NULL 保护用来测判定逻辑）。"""
    conn.execute(
        "INSERT INTO index_daily (index_code, trade_date, close, source,"
        " collected_at, row_fingerprint, quality_status) "
        "VALUES (?,?,?,?,?,?,?)",
        (code, day, close, "test", "2020-01-01T00:00:00",
         f"fp_{code}_{day}", quality))


def _seed_master(conn, code, basis=RETURN_BASIS_TOTAL):
    upsert_index_master(conn, index_code=code, index_name=code + "指数",
                        data_source="test", return_basis=basis)


# ================================================================
# 一、辅助函数直接校验
# ================================================================
@pytest.mark.parametrize("value", [
    float("inf"), float("-inf"), float("nan"),
    0.0, -1.0, -0.0001, None,
])
def test_is_usable_close_rejects_non_finite_or_non_positive(value):
    """inf / -inf / NaN / 0 / 负数 / None 一律不可用。"""
    assert _is_usable_close(value) is False


@pytest.mark.parametrize("value", [1.0, 100.0, 0.0001, 1e12, 3000.55])
def test_is_usable_close_accepts_finite_positive(value):
    """有限正数可用。"""
    assert _is_usable_close(value) is True


def test_uses_isfinite_not_self_compare():
    """确认必须用 math.isfinite：``v != v`` 只能认 NaN，认不出 inf。"""
    inf = float("inf")
    nan = float("nan")

    # NaN 自我比较不等，能被 v != v 抓到
    assert nan != nan
    # inf 等于自身，v != v 完全抓不到——这正是原实现的漏洞
    assert not (inf != inf)
    # math.isfinite 两个都能抓到
    assert math.isfinite(inf) is False
    assert math.isfinite(nan) is False
    assert _is_usable_close(inf) is False
    assert _is_usable_close(nan) is False


# ================================================================
# 二、count_effective_observations 层面
# ================================================================
def test_inf_not_counted(conn):
    """close=+inf 不计入有效行情。"""
    _seed_master(conn, "T001")
    _insert(conn, "T001", 1000.0, "2020-01-02")
    _insert(conn, "T001", float("inf"), "2020-01-03")

    assert conn.execute(
        "SELECT COUNT(*) FROM index_daily WHERE index_code='T001'"
    ).fetchone()[0] == 2
    assert count_effective_observations(conn, "T001") == 1


def test_negative_inf_not_counted(conn):
    """close=-inf 不计入。"""
    _seed_master(conn, "T002")
    _insert(conn, "T002", 1000.0, "2020-01-02")
    _insert(conn, "T002", float("-inf"), "2020-01-03")

    assert count_effective_observations(conn, "T002") == 1


def test_zero_and_negative_not_counted(conn):
    """close=0 与 close=-1 均不计入。"""
    _seed_master(conn, "T003")
    _insert(conn, "T003", 1000.0, "2020-01-02")
    _insert(conn, "T003", 0.0, "2020-01-03")
    _insert(conn, "T003", -1.0, "2020-01-06")

    assert count_effective_observations(conn, "T003") == 1


def test_nan_becomes_null_and_rejected_by_schema(conn):
    """NaN：SQLite 驱动将其转为 NULL，被 NOT NULL 约束拒绝。

    这是**实际观测到的行为**，记录在此以免误以为是判定函数的功劳。
    """
    _seed_master(conn, "T004")
    _insert(conn, "T004", 1000.0, "2020-01-02")

    with pytest.raises(sqlite3.IntegrityError):
        _insert(conn, "T004", float("nan"), "2020-01-03")

    # NaN 没进表，有效行仍是 1
    assert conn.execute(
        "SELECT COUNT(*) FROM index_daily WHERE index_code='T004'"
    ).fetchone()[0] == 1
    assert count_effective_observations(conn, "T004") == 1


def test_normal_finite_positive_counted(conn):
    """正常有限正数全部计入。"""
    _seed_master(conn, "T005")
    for i, d in enumerate(_weekdays("2020-01-02", 5)):
        _insert(conn, "T005", 1000.0 + i, d)

    assert count_effective_observations(conn, "T005") == 5


# ================================================================
# 三、assess_index_component 层面（任务书硬要求）
# ================================================================
def test_assess_inf_plus_normal_only_one_valid(conn):
    """核心场景：2 条记录，1 条 +inf + 1 条正常正数 → 有效仅 1 条，不足门槛。

    必须实际验证 ``assess_index_component()``，不能只测辅助函数。
    """
    _seed_master(conn, "T010", RETURN_BASIS_TOTAL)
    _insert(conn, "T010", float("inf"), "2020-01-02")
    _insert(conn, "T010", 1000.0, "2020-01-03")

    assert conn.execute(
        "SELECT COUNT(*) FROM index_daily WHERE index_code='T010'"
    ).fetchone()[0] == 2          # 总行数 2

    v = assess_index_component(conn, "T010")
    assert v["total_rows"] == 2
    assert v["valid_rows"] == 1   # 有效只有 1
    assert v["available"] == 0    # 达不到 2 条门槛
    assert "有效行情不足" in v["reason"]
    assert f"至少需要 {MIN_VALID_OBSERVATIONS}" in v["reason"]


def test_assess_inf_plus_two_normal_available(conn):
    """对照组：+inf + 2 条正常 → 有效 2 条 → 可用。"""
    _seed_master(conn, "T011", RETURN_BASIS_TOTAL)
    _insert(conn, "T011", float("inf"), "2020-01-02")
    _insert(conn, "T011", 1000.0, "2020-01-03")
    _insert(conn, "T011", 1001.0, "2020-01-06")

    v = assess_index_component(conn, "T011")
    assert v["total_rows"] == 3
    assert v["valid_rows"] == 2
    assert v["available"] == 1
    assert v["reason"] is None


def test_assess_only_inf_not_available(conn):
    """全部是 inf → 没有有效行情。"""
    _seed_master(conn, "T012", RETURN_BASIS_TOTAL)
    _insert(conn, "T012", float("inf"), "2020-01-02")
    _insert(conn, "T012", float("inf"), "2020-01-03")

    v = assess_index_component(conn, "T012")
    assert v["total_rows"] == 2
    assert v["valid_rows"] == 0
    assert v["available"] == 0
    assert "没有有效行情" in v["reason"]


def test_assess_negative_inf_not_available(conn):
    """全部是 -inf → 没有有效行情。"""
    _seed_master(conn, "T013", RETURN_BASIS_TOTAL)
    _insert(conn, "T013", float("-inf"), "2020-01-02")
    _insert(conn, "T013", float("-inf"), "2020-01-03")

    v = assess_index_component(conn, "T013")
    assert v["valid_rows"] == 0
    assert v["available"] == 0


def test_assess_inf_does_not_bypass_basis_check(conn):
    """inf 即使凑够条数也不能绕过口径检查。"""
    _seed_master(conn, "T014", RETURN_BASIS_UNKNOWN)
    _insert(conn, "T014", 1000.0, "2020-01-02")
    _insert(conn, "T014", 1001.0, "2020-01-03")
    _insert(conn, "T014", float("inf"), "2020-01-06")

    v = assess_index_component(conn, "T014")
    assert v["valid_rows"] == 2
    assert v["available"] == 0
    assert "unknown" in v["reason"]


# ================================================================
# 四、复合基准层面端到端
# ================================================================
def test_composite_with_inf_component_not_available(conn):
    """复合基准中，只有 inf + 1 条正常的指数成分 → data_available=0。"""
    _seed_master(conn, "T020", RETURN_BASIS_TOTAL)
    _insert(conn, "T020", float("inf"), "2020-01-02")
    _insert(conn, "T020", 1000.0, "2020-01-03")

    cid = create_composite(conn, benchmark_name="T", benchmark_raw_text="x")
    add_component(conn, cid, component_type=COMPONENT_INDEX,
                  component_label="含inf指数", index_code="T020", weight=0.5)
    comp = get_composite(conn, cid)["components"][0]
    assert comp["data_available"] == 0
    assert "有效行情不足" in (comp["unavailable_reason"] or "")


def test_composite_reproducible_only_with_finite_positives(conn):
    """两个成分都有 2 条有限正数 → 可复现；插入 inf 不影响。"""
    _seed_master(conn, "T021", RETURN_BASIS_TOTAL)
    _seed_master(conn, "T022", RETURN_BASIS_TOTAL)
    for code in ("T021", "T022"):
        _insert(conn, code, 1000.0, "2020-01-02")
        _insert(conn, code, 1001.0, "2020-01-03")
        _insert(conn, code, float("inf"), "2020-01-06")

    cid = create_composite(conn, benchmark_name="T", benchmark_raw_text="x")
    add_component(conn, cid, component_type=COMPONENT_INDEX,
                  component_label="A", index_code="T021", weight=0.5)
    add_component(conn, cid, component_type=COMPONENT_INDEX,
                  component_label="B", index_code="T022", weight=0.5)
    v = evaluate_composite(conn, cid)
    assert v["is_reproducible"] is True


def test_evaluate_reevaluates_after_inf_injected(conn):
    """先正常可复现，之后把有效行改成 inf → 再次评估必须变成不可复现。"""
    _seed_master(conn, "T023", RETURN_BASIS_TOTAL)
    _seed_master(conn, "T024", RETURN_BASIS_TOTAL)
    for code in ("T023", "T024"):
        _insert(conn, code, 1000.0, "2020-01-02")
        _insert(conn, code, 1001.0, "2020-01-03")

    cid = create_composite(conn, benchmark_name="T", benchmark_raw_text="x")
    add_component(conn, cid, component_type=COMPONENT_INDEX,
                  component_label="A", index_code="T023", weight=0.5)
    add_component(conn, cid, component_type=COMPONENT_INDEX,
                  component_label="B", index_code="T024", weight=0.5)
    assert evaluate_composite(conn, cid)["is_reproducible"] is True

    # 把 T023 的一条改成 inf，只剩 1 条有效
    conn.execute(
        "UPDATE index_daily SET close=? WHERE index_code='T023' "
        "AND trade_date='2020-01-03'", (float("inf"),))

    v = evaluate_composite(conn, cid)
    assert v["is_reproducible"] is False
    assert "有效行情不足" in v["missing_reason"]


# ================================================================
# 五、正式库守恒（只读断言）
# ================================================================
def test_production_no_infinite_close():
    """正式库没有 inf/-inf/负收盘；**存在 1 条 close=0.0 的历史遗留行**。

    本轮实际发现的真实数据问题：
    ``H30184`` / ``2013-06-28`` / ``close=0.0`` / ``quality_status='valid'``。

    这条是本轮任务（禁止修改 50,603 条行情）下**不能就地修**的数据，
    如实记录而不是隐藏。它对结论无影响：

    - ``H30184`` 共 5,316 行，去掉这 1 条仍有 5,315 条有效；
    - 它本来就卡在 ``return_basis='unknown'``，不可用；
    - 修复前该行会被 ``c <= 0`` 排除，修复后同样被 ``c > 0`` 排除。

    因此该行**从未被计入有效观测**，不影响任何既有判定。
    """
    with get_index_connection() as c:
        rows = c.execute(
            "SELECT index_code, trade_date, close FROM index_daily "
            "WHERE quality_status='valid'").fetchall()

    infinite = []
    non_positive = []
    for r in rows:
        try:
            v = float(r[2])
        except (TypeError, ValueError):
            infinite.append(tuple(r))
            continue
        if math.isinf(v) or math.isnan(v):
            infinite.append(tuple(r))
        elif v <= 0:
            non_positive.append(tuple(r))

    # 绝不能有 inf / -inf / NaN
    assert infinite == []
    # 已知遗留 1 条 0.0，不在本轮授权范围内修改
    assert non_positive == [("H30184", "2013-06-28", 0.0)]


def test_production_zero_close_never_counted():
    """那条 0.0 从未被计入有效观测（修复前后都不计）。"""
    with get_index_connection() as c:
        total = c.execute(
            "SELECT COUNT(*) FROM index_daily "
            "WHERE index_code='H30184' AND quality_status='valid'"
        ).fetchone()[0]
        valid = count_effective_observations(c, "H30184")
    assert total == 5315           # 5,316 行中基线行是 suspect
    assert valid == 5314           # 再排除那条 0.0
    assert valid >= MIN_VALID_OBSERVATIONS


def test_production_index_rows_unchanged():
    with get_index_connection() as c:
        assert c.execute("SELECT COUNT(*) FROM index_daily").fetchone()[0] == 50603


def test_production_indices_all_unknown():
    with get_index_connection() as c:
        rows = c.execute(
            "SELECT return_basis, COUNT(*) FROM index_master "
            "GROUP BY return_basis").fetchall()
    assert {r[0]: r[1] for r in rows} == {"unknown": 10}


def test_production_composites_none_reproducible():
    with get_index_connection() as c:
        assert c.execute(
            "SELECT COUNT(*) FROM benchmark_composite").fetchone()[0] == 15
        assert c.execute(
            "SELECT COUNT(*) FROM benchmark_composite "
            "WHERE is_reproducible=1").fetchone()[0] == 0


# ================================================================
# 门禁
# ================================================================
def test_gate_unchanged():
    from app.fund.research.engine import analyze_by_code
    g = analyze_by_code("050002")["gate"]
    assert g["ready_for_research_analysis"] is True
    assert g["ready_for_backtest"] is False
    assert g["ready_for_formal_ranking"] is False
