"""阶段3B-5.2 用户自选基金代码查询与研究报告专项测试。

全部使用**临时数据库**（tmp_path），不碰正式库。
conftest 的 production_db_guard 会兜底检查正式库未被修改。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.fund.migration import ensure_fund_schema  # noqa: E402
from app.fund.migration_3b4_2 import ensure_3b4_2_schema  # noqa: E402
from app.fund.migration_3b4_4 import ensure_3b4_4_schema  # noqa: E402
from app.fund.research.engine import analyze_by_code, analyze_universe  # noqa: E402
from app.fund.research.lookup import (  # noqa: E402
    STATUS_EXCLUDED, STATUS_FOUND, STATUS_INVALID_CODE, STATUS_NOT_FOUND,
    STATUS_NO_NAV, STATUS_TERMINATED, lookup_by_fund_code,
    lookup_by_share_code, lookup_fund, validate_code,
)


# ================================================================ 临时库构造
def _make_db(tmp_path: Path) -> Path:
    db = tmp_path / "fund_research.db"
    ensure_fund_schema(db)
    # 3B-4.2 补 fee 的 rate_original / is_annual 等列；3B-4.4 再补 announcement_id
    ensure_3b4_2_schema(db)
    ensure_3b4_4_schema(db)
    return db


def _add_fund(db: Path, *, fund_code: str, name: str, l1: str = "股票型",
              is_index: int | None = None, lifecycle: str = "unknown",
              shares: list[tuple[str, str, int]], benchmark: str | None = None,
              company: str = "测试基金公司",
              established: str | None = "2015-01-01") -> int:
    with sqlite3.connect(db) as conn:
        cur = conn.execute(
            """INSERT INTO fund_master (fund_code_primary, fund_name, fund_company,
                   fund_type_l1, is_index_fund, lifecycle_status, benchmark,
                   established_date, source, ingested_at)
               VALUES (?,?,?,?,?,?,?,?,'test','2020-01-01T00:00:00')""",
            (fund_code, name, company, l1, is_index, lifecycle, benchmark,
             established))
        fund_id = cur.lastrowid
        for code, sname, primary in shares:
            conn.execute(
                """INSERT INTO fund_share_classes
                   (fund_id, share_class_code, share_class_name, is_primary,
                    share_class_type, source, ingested_at)
                   VALUES (?,?,?,?,?, 'test', '2020-01-01T00:00:00')""",
                (fund_id, code, sname, primary,
                 "A" if primary else "C"))
        conn.commit()
    return fund_id


def _add_nav(db: Path, share_code: str, rows: list[tuple[str, float, float]]):
    with sqlite3.connect(db) as conn:
        sid = conn.execute(
            "SELECT share_class_id FROM fund_share_classes WHERE share_class_code=?",
            (share_code,)).fetchone()[0]
        conn.executemany(
            """INSERT INTO fund_nav_daily (share_class_id, nav_date, nav_kind,
                   unit_nav, acc_nav, source, ingested_at)
               VALUES (?,?,'net_value',?,?, 'test', '2020-01-01T00:00:00')""",
            [(sid, d, u, a) for d, u, a in rows])
        conn.commit()


def _add_money(db: Path, share_code: str, rows: list[tuple[str, float, float]]):
    with sqlite3.connect(db) as conn:
        sid = conn.execute(
            "SELECT share_class_id FROM fund_share_classes WHERE share_class_code=?",
            (share_code,)).fetchone()[0]
        conn.executemany(
            """INSERT INTO fund_nav_daily (share_class_id, nav_date, nav_kind,
                   per_10k_yield, seven_day_annual, source, ingested_at)
               VALUES (?,?,'money_yield',?,?, 'test', '2020-01-01T00:00:00')""",
            [(sid, d, p, s) for d, p, s in rows])
        conn.commit()


def _add_fee(db: Path, share_code: str, fee_type: str, rate: float,
             effective_from: str | None = None, is_annual: int = 1):
    with sqlite3.connect(db) as conn:
        sid = conn.execute(
            "SELECT share_class_id FROM fund_share_classes WHERE share_class_code=?",
            (share_code,)).fetchone()[0]
        conn.execute(
            """INSERT INTO fund_fee_rules (share_class_id, fee_type, rate_original,
                   is_annual, effective_from, evidence_level, source, ingested_at)
               VALUES (?,?,?,?,?,?, 'test', '2020-01-01T00:00:00')""",
            (sid, fee_type, rate, is_annual, effective_from,
             "A-" if effective_from else "C"))
        conn.commit()


def _daily(start: str, n: int, base=1.0, step=0.001):
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    return [((d0 + timedelta(days=i)).isoformat(),
             round(base + i * step, 6), round(base + i * step, 6))
            for i in range(n)]


@pytest.fixture
def db(tmp_path):
    """标准测试库：一个普通主动基金 + 一个 A/C 双份额 + 一个货币 + 一个终止 + 一个无净值。"""
    d = _make_db(tmp_path)
    _add_fund(d, fund_code="100001", name="测试主动基金",
              l1="股票型", is_index=None, shares=[("100001", "测试主动A", 1)],
              benchmark="沪深300指数收益率×70%")
    _add_nav(d, "100001", _daily("2020-01-01", 400))
    _add_fee(d, "100001", "management", 0.015, "2020-01-01")

    _add_fund(d, fund_code="200001", name="测试双份额基金",
              l1="债券型-长债", shares=[("200001", "测试双份额 A", 1),
                                        ("200002", "测试双份额 C", 0)],
              benchmark="中债综合指数")
    _add_nav(d, "200001", _daily("2020-01-01", 400))
    _add_nav(d, "200002", _daily("2020-06-01", 200))
    _add_fee(d, "200001", "management", 0.008, None)
    _add_fee(d, "200002", "sales_service", 0.004, None)

    _add_fund(d, fund_code="300001", name="测试货币基金",
              l1="货币型-普通货币", shares=[("300001", "测试货币", 1)])
    _add_money(d, "300001",
               [((_daily("2020-01-01", 100)[i][0]), 0.7, 2.5) for i in range(100)])

    _add_fund(d, fund_code="400001", name="测试清盘基金",
              l1="债券型-长债", lifecycle="terminated",
              shares=[("400001", "测试清盘", 1)], benchmark="中债综合指数")
    _add_nav(d, "400001", _daily("2015-01-01", 100))

    _add_fund(d, fund_code="500001", name="测试无净值基金",
              l1="股票型", shares=[("500001", "测试无净值", 1)])
    return d


# ================================================================ 1/2/3/4 查询
def test_lookup_share_code(db):
    r = lookup_by_share_code("100001", db)
    assert r["status"] == STATUS_FOUND
    assert r["entry"]["share_code"] == "100001"
    assert r["entry"]["fund_code"] == "100001"


def test_lookup_fund_code(db):
    r = lookup_by_fund_code("200001", db)
    assert r["status"] == STATUS_FOUND
    assert len(r["entries"]) == 2
    assert {e["share_code"] for e in r["entries"]} == {"200001", "200002"}


def test_share_codes_same_fund_id(db):
    a = lookup_by_share_code("200001", db)
    b = lookup_by_share_code("200002", db)
    assert a["entry"]["fund_id"] == b["entry"]["fund_id"]
    assert len(a["entries"]) == 2
    assert len(b["entries"]) == 2


def test_multi_share_not_double_counted(db):
    """多份额基金在报告中只算一个本体。"""
    r = analyze_by_code("200001", db)
    assert r["status"] == STATUS_FOUND
    assert r["share_count"] == 2
    assert r["fund_count"] == 1
    assert r["merged"]["share_count"] == 2
    assert len(r["merged"]["cost_comparison"]["shares"]) == 2


# ================================================================ 5/6/7/8 状态
def test_not_found(db):
    r = lookup_fund("999999", db)
    assert r["status"] == STATUS_NOT_FOUND
    assert r["entry"] is None


def test_onshore_etf_excluded(db):
    from app.fund.research.classification import ONSHORE_ETF_CODES
    for code in ONSHORE_ETF_CODES:
        r = lookup_fund(code, db)
        # 库里没有 → not_found；若构造存在则应 excluded，二者都不能是 found
        assert r["status"] in (STATUS_NOT_FOUND, STATUS_EXCLUDED)


def test_qdii_excluded(tmp_path):
    d = _make_db(tmp_path)
    _add_fund(d, fund_code="600001", name="测试QDII",
              l1="QDII-股票", shares=[("600001", "测试QDII", 1)])
    _add_nav(d, "600001", _daily("2020-01-01", 100))
    r = lookup_fund("600001", d)
    assert r["status"] == STATUS_EXCLUDED
    assert "QDII" in r["reason"]


def test_terminated(db):
    r = lookup_fund("400001", db)
    assert r["status"] == STATUS_TERMINATED
    assert "terminated" in r["reason"]


def test_no_nav_data(db):
    r = analyze_by_code("500001", db)
    assert r["status"] == STATUS_NO_NAV
    assert r["reports"] == []
    assert "不补录、不填 0" in r["reason"]


# ================================================================ 9/10 质量
def test_nav_quality_gap_preserved(tmp_path):
    from datetime import date, timedelta
    d = _make_db(tmp_path)
    _add_fund(d, fund_code="700001", name="测试缺口基金", l1="股票型",
              shares=[("700001", "缺口A", 1)])
    left = _daily("2020-01-01", 100)
    right = [((date.fromisoformat("2020-09-01") + timedelta(days=i)).isoformat(),
              2.0 + i * 0.001, 2.0 + i * 0.001) for i in range(100)]
    _add_nav(d, "700001", left + right)

    r = analyze_by_code("700001", d)
    assert r["status"] == STATUS_FOUND
    q = r["reports"][0]["quality"]
    assert q["gap_count_over_threshold"] >= 1
    assert q["continuity_verification"] == "cannot_verify"
    # 覆盖率摘要也要体现
    assert r["coverage"][0]["nav_rows"] == 200


def test_null_and_out_of_order_preserved(tmp_path):
    """有净值但质量有问题时，质量警告必须保留。

    fund_nav_daily 对 (share_class_id, nav_date, nav_kind) 有 UNIQUE 约束，
    数据库层面不可能出现重复日期；因此这里构造**空值 + 乱序**。
    """
    d = _make_db(tmp_path)
    _add_fund(d, fund_code="700002", name="测试脏数据", l1="股票型",
              shares=[("700002", "脏A", 1)])
    rows = _daily("2020-01-01", 50)
    rows[10] = (rows[10][0], rows[10][1], None)  # 空 acc
    _add_nav(d, "700002", rows)
    r = analyze_by_code("700002", d)
    q = r["reports"][0]["quality"]
    assert q["null_acc_nav"] == 1
    assert "null_acc_nav" in q["quality_flags"]
    # 有净值但质量有问题：数据仍然产出，但警告保留
    assert r["status"] == STATUS_FOUND
    assert r["share_reports_available"] is True


def test_out_of_order_detected_by_engine():
    """乱序检测逻辑仍有效（SQL 已 ORDER BY，故用原始行验证）。"""
    from app.fund.research.data_access import audit_nav_series
    rows = [{"nav_date": "2020-01-03", "unit_nav": 1.2, "acc_nav": 1.2},
            {"nav_date": "2020-01-01", "unit_nav": 1.0, "acc_nav": 1.0},
            {"nav_date": "2020-01-02", "unit_nav": 1.1, "acc_nav": 1.1}]
    s = audit_nav_series("T2", 1, 1, "测试", "net_value", rows)
    assert s.quality.out_of_order == 1
    assert "out_of_order" in s.quality.quality_flags


def test_duplicate_dates_detected_by_engine():
    """重复日期检测逻辑本身仍有效（用内存 constructed rows 验证）。"""
    from app.fund.research.data_access import audit_nav_series
    rows = [{"nav_date": "2020-01-01", "unit_nav": 1.0, "acc_nav": 1.0},
            {"nav_date": "2020-01-01", "unit_nav": 1.1, "acc_nav": 1.1},
            {"nav_date": "2020-01-02", "unit_nav": 1.2, "acc_nav": 1.2}]
    s = audit_nav_series("T1", 1, 1, "测试", "net_value", rows)
    assert s.quality.duplicate_dates == 1
    assert "duplicate_dates" in s.quality.quality_flags


# ================================================================ 11 货币独立口径
def test_money_fund_independent(db):
    r = analyze_by_code("300001", db)
    assert r["status"] == STATUS_FOUND
    rep = r["reports"][0]
    assert rep["is_money_fund"] is True
    ind = rep["indicators"]
    assert ind["uses_unit_nav"] is False
    assert ind["nav_based_indicators"]["status"] == "not_applicable"


# ================================================================ 12/13 批量
def test_batch_one_failure_does_not_break_others(db, monkeypatch):
    """批量中某只失败不影响其他基金。"""
    import app.fund.research.lookup as lk

    real = lk.lookup_fund

    def boom(code, db_path=None):
        if code == "100001":
            raise RuntimeError("模拟单只失败")
        return real(code, db_path)

    monkeypatch.setattr("app.fund.research.engine.lookup_fund", boom,
                        raising=False)
    # analyze_by_code 内部 import 的是 lookup_fund，需打到 lookup 模块
    monkeypatch.setattr(lk, "lookup_fund", boom)

    from app.fund.research.__main__ import _read_codes_file  # noqa: F401
    results = []
    for c in ("100001", "200001", "999999"):
        try:
            results.append(analyze_by_code(c, db))
        except Exception as exc:
            results.append({"status": "error", "query": {"code": c},
                            "reason": str(exc)})
    assert results[0]["status"] == "error"
    assert results[1]["status"] == STATUS_FOUND
    assert results[2]["status"] == STATUS_NOT_FOUND
    assert len(results) == 3


def test_codes_file_parsing(tmp_path, db):
    from app.fund.research.__main__ import _read_codes_file
    f = tmp_path / "codes.txt"
    f.write_text("100001\n\n# 注释\n200001\nabc\n12345\n100001\n",
                 encoding="utf-8")
    codes, problems = _read_codes_file(str(f))
    assert codes == ["100001", "200001", "100001"]
    assert any("非法代码" in p for p in problems)


def test_codes_file_missing(tmp_path):
    from app.fund.research.__main__ import _read_codes_file
    codes, problems = _read_codes_file(str(tmp_path / "nope.txt"))
    assert codes == []
    assert "文件不存在" in problems[0]


def test_empty_codes_file(tmp_path):
    from app.fund.research.__main__ import _read_codes_file
    f = tmp_path / "empty.txt"
    f.write_text("", encoding="utf-8")
    codes, problems = _read_codes_file(str(f))
    assert codes == []
    assert problems == []


def test_invalid_code_format(db):
    for bad in ("abc", "12345", "1234567", "", "12a456", "'; DROP TABLE--"):
        assert validate_code(bad)[0] is False
    r = lookup_fund("'; DROP TABLE fund_master--", db)
    assert r["status"] == STATUS_INVALID_CODE
    # 表还在
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM fund_master").fetchone()[0] > 0


def test_valid_code_format(db):
    assert validate_code("110022") == (True, "110022")
    assert validate_code(" 110022 ")[0] is True


# ================================================================ 14 JSON 可解析
def test_json_serializable(db):
    r = analyze_by_code("200001", db)
    text = json.dumps(r, ensure_ascii=False, indent=1, default=str)
    back = json.loads(text)
    assert back["status"] == STATUS_FOUND
    assert "merged" in back
    assert "coverage" in back


def test_json_serializable_not_found(db):
    r = analyze_by_code("999999", db)
    assert json.loads(json.dumps(r, default=str))["status"] == STATUS_NOT_FOUND


# ================================================================ 15 只读保护
def test_lookup_is_readonly(db):
    import hashlib

    def digest():
        return hashlib.sha256(db.read_bytes()).hexdigest()

    before = digest()
    lookup_fund("100001", db)
    analyze_by_code("100001", db)
    analyze_by_code("200001", db)
    analyze_by_code("999999", db)
    assert digest() == before, "查询过程修改了数据库"


# ================================================================ 16 费用全份额
def test_cost_comparison_all_shares(db):
    r = analyze_by_code("200001", db)
    cc = r["merged"]["cost_comparison"]
    assert cc["share_count"] == 2
    codes = {s["share_code"] for s in cc["shares"]}
    assert codes == {"200001", "200002"}
    by = {s["share_code"]: s for s in cc["shares"]}
    # C 类有销售服务费；A 类没有（不是 0，是 not_available）
    assert by["200002"]["sales_service_fee"]["status"] == "ok"
    assert by["200001"]["sales_service_fee"]["status"] == "not_available"
    assert by["200001"]["management_fee"]["status"] == "ok"


def test_fee_no_historical_effective(db):
    r = analyze_by_code("200001", db)
    by = {s["share_code"]: s for s in r["merged"]["cost_comparison"]["shares"]}
    cell = by["200001"]["management_fee"]
    assert cell["status"] == "ok"
    assert cell["usable_for_historical"] is False
    assert cell["effective_from"] is None


def test_fee_with_historical_effective(db):
    r = analyze_by_code("100001", db)
    by = {s["share_code"]: s for s in r["merged"]["cost_comparison"]["shares"]}
    cell = by["100001"]["management_fee"]
    assert cell["status"] == "ok"
    assert cell["usable_for_historical"] is True
    assert cell["effective_from"] == "2020-01-01"


# ================================================================ 17 支付宝
def test_alipay_never_inferred(db):
    for code in ("100001", "200001", "300001"):
        r = analyze_by_code(code, db)
        for c in r["coverage"]:
            assert c["alipay_purchasable"] in ("true", "false", "unknown")
            assert c["alipay_purchasable"] == "unknown"
            assert "不推断" in c["alipay_note"]


# ================================================================ 真实库回归
def test_real_default_pool_unchanged():
    """原有 12 份额 / 9 本体仍在，且同类成员仍按 fund_id 去重。"""
    ORIGINAL_SHARES = {"000015", "000016", "000051", "000198", "000478",
                       "007300", "007301", "110020", "110022", "161005",
                       "012414", "161725"}
    from app.fund.research.data_access import load_universe
    r = analyze_universe()
    u = r["universe"]
    codes = {e["share_code"] for e in load_universe()}
    assert ORIGINAL_SHARES <= codes, "原有 12 份额缺失"
    original_ids = {e["fund_id"] for e in load_universe()
                    if e["share_code"] in ORIGINAL_SHARES}
    assert len(original_ids) == 9
    # 同类成员总数必须等于本体数（去重生效）
    total = sum(g["member_count"] for g in
                r["peer_analysis"]["groups"].values())
    assert total == u["fund_count"]


def test_real_lookup_161725():
    r = analyze_by_code("161725")
    assert r["status"] == STATUS_FOUND
    assert r["share_count"] == 2
    assert r["fund_count"] == 1
    assert r["merged"]["representative_share"] == "161725"


def test_real_lookup_012414_maps_to_same_fund():
    a = analyze_by_code("161725")
    b = analyze_by_code("012414")
    assert a["fund_entity"]["fund_id"] == b["fund_entity"]["fund_id"]
    assert b["fund_count"] == 1


def test_real_terminated_fund():
    r = analyze_by_code("000007")
    assert r["status"] == STATUS_TERMINATED


def test_real_not_found():
    r = analyze_by_code("999999")
    assert r["status"] == STATUS_NOT_FOUND
    assert r["reports"] == []
