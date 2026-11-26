"""阶段3B-6.2.3.0.3 H30184 历史零值异常官方复核与最小修复。

**唯一允许修改的正式库记录**：
``index_daily`` 中 ``index_code='H30184' AND trade_date='2013-06-28'``。

处置方式（三选一，由官方证据决定）：

- A：官方能确认真实收盘 → 修复 close，但**不得补造 OHLC**
- B：官方无法确认 → 标记 ``suspect``，保留原值可追溯
- C：发现更复杂问题 → 停止修改，只提交证据

本模块默认 **不执行任何写入**，必须显式调用 :func:`apply_repair`。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EVID = ROOT / "reports" / "evidence" / "phase3B6_2_3_0_3"

TARGET_INDEX = "H30184"
TARGET_DATE = "2013-06-28"

# 修复决策（由官方证据确定，见 reports/phase3B6_2_3_0_3_repair_report.md）
DECISION = "B"
DECISION_REASON = (
    "官方接口对 2013-06-28 返回 close=0.0 且 open/high/low 全为 null；"
    "单一日期查询返回空数组。**官方未提供可确认的真实收盘点位**，"
    "按情况 B 标记 suspect，不做任何插值或推算")


def db_path() -> str:
    from app.config import settings
    return str(settings.database_path)


def connect_ro() -> sqlite3.Connection:
    p = db_path().replace("\\", "/")
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    conn.execute("pragma temp_store = memory")
    return conn


def connect_rw() -> sqlite3.Connection:
    return sqlite3.connect(db_path())


def file_sha256(path: str | None = None) -> str:
    p = path or db_path()
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_target(conn: sqlite3.Connection) -> dict | None:
    """读取目标记录全部字段。"""
    cols = [r[1] for r in conn.execute("pragma table_info(index_daily)")]
    row = conn.execute(
        "select * from index_daily where index_code=? and trade_date=?",
        (TARGET_INDEX, TARGET_DATE)).fetchone()
    return dict(zip(cols, row)) if row else None


def index_fingerprints(conn: sqlite3.Connection) -> dict:
    """各指数 (trade_date, close) 序列指纹，用于确认其他指数未受影响。"""
    out = {}
    for (code,) in conn.execute(
            "select distinct index_code from index_daily order by index_code"):
        fp = hashlib.sha256()
        n = 0
        for r in conn.execute(
                "select trade_date, close from index_daily "
                "where index_code=? order by trade_date", (code,)):
            fp.update(f"{r[0]}|{r[1]}\n".encode())
            n += 1
        out[code] = {"rows": n, "fingerprint": fp.hexdigest()}
    return out


def snapshot(conn: sqlite3.Connection) -> dict:
    """修复前/后的完整状态快照。"""
    total = conn.execute("select count(*) from index_daily").fetchone()[0]
    return {
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "database_path": db_path(),
        "database_sha256": file_sha256(),
        "index_daily_total_rows": total,
        "integrity_check": conn.execute(
            "pragma integrity_check").fetchone()[0],
        "foreign_key_violations": len(
            conn.execute("pragma foreign_key_check").fetchall()),
        "target_record": read_target(conn),
        "index_fingerprints": index_fingerprints(conn),
        "suspect_rows": [
            {"index_code": r[0], "trade_date": r[1], "close": r[2],
             "quality_status": r[3]}
            for r in conn.execute(
                "select index_code, trade_date, close, quality_status "
                "from index_daily where quality_status<>'valid' "
                "order by index_code")],
    }


def is_anomaly(rec: dict | None) -> bool:
    """判定目标记录是否为异常（零值 + OHLC 缺失 + 标记 valid）。"""
    if not rec:
        return False
    return (rec.get("close") is not None and rec["close"] <= 0)


def validate_decision(decision: str, official: dict) -> None:
    """拒绝在证据不足时执行修复。

    - 情况 A 必须有官方真实收盘值
    - 情况 B/C 不得改动 close
    """
    if decision == "A":
        close = official.get("official_close")
        if close is None or close <= 0:
            raise ValueError(
                "情况 A 需要官方确认的真实收盘点位，当前证据不足，拒绝修复")
    elif decision in ("B", "C"):
        if official.get("official_close") not in (None, 0.0):
            # 官方其实给了正值 → 应走 A，不能静默按 B 处理
            raise ValueError(
                "官方已提供正值收盘，不应按 B/C 处理，请复核决策")
    else:
        raise ValueError(f"未知决策 {decision}")


def apply_repair(official: dict, *, decision: str = DECISION,
                 dry_run: bool = True) -> dict:
    """执行最小修复。

    - 情况 A：只更新 ``close``（不补造 OHLC）
    - 情况 B：只把 ``quality_status`` 改为 ``suspect`` 并写明原因，
      **保留原 close 与原始质量状态到 quality_note**
    - 情况 C：不修改

    返回修复结果（含前后记录）。
    """
    validate_decision(decision, official)

    conn = connect_ro()
    try:
        before = snapshot(conn)
    finally:
        conn.close()

    result = {
        "decision": decision,
        "decision_reason": DECISION_REASON,
        "dry_run": dry_run,
        "before": before,
        "affected_rows": 0,
        "after": None,
        "modified": False,
    }
    if decision == "C" or dry_run:
        return result

    conn = connect_rw()
    try:
        with conn:                     # 事务
            if decision == "A":
                cur = conn.execute(
                    "update index_daily set close=?, quality_status='valid', "
                    "quality_note=? where index_code=? and trade_date=?",
                    (float(official["official_close"]),
                     f"按官方证据修复收盘点位（来源 {official.get('url')}）",
                     TARGET_INDEX, TARGET_DATE))
            else:                      # B
                note = (
                    "**官方无法确认真实收盘点位**：中证指数官网接口对该日返回 "
                    "close=0.0 且 OHLC 全为 null，单一日期查询返回空数组；"
                    "原值 close=0.0、原质量状态 valid 予以保留，"
                    "本条不再参与有效行情与收益计算（3B-6.2.3.0.3）")
                cur = conn.execute(
                    "update index_daily set quality_status='suspect', "
                    "quality_note=? where index_code=? and trade_date=?",
                    (note, TARGET_INDEX, TARGET_DATE))
            affected = cur.rowcount
            if affected != 1:
                raise RuntimeError(
                    f"影响行数 {affected} != 1，已回滚事务")
            result["affected_rows"] = affected
    finally:
        conn.close()

    conn = connect_ro()
    try:
        result["after"] = snapshot(conn)
    finally:
        conn.close()
    result["modified"] = True
    return result


def load_official_evidence() -> dict:
    """读取本轮保存的官方原始响应。"""
    out: dict = {"evidence_dir": str(EVID.relative_to(ROOT)).replace("\\", "/")}
    single = EVID / "single_20130628.json"
    rng = EVID / "range_20130624_20130703.json"
    if single.exists():
        raw = single.read_bytes()
        d = json.loads(raw.decode("utf-8"))
        out["single_date_url"] = (
            "https://www.csindex.com.cn/csindex-home/perf/"
            "index-perf?indexCode=H30184&startDate=20130628&endDate=20130628")
        out["single_date_rows"] = len(d.get("data") or [])
        out["single_date_sha256"] = hashlib.sha256(raw).hexdigest()
    if rng.exists():
        raw = rng.read_bytes()
        d = json.loads(raw.decode("utf-8"))
        rows = {r["tradeDate"]: r for r in (d.get("data") or [])}
        target = rows.get("20130628")
        out["range_url"] = (
            "https://www.csindex.com.cn/csindex-home/perf/"
            "index-perf?indexCode=H30184&startDate=20130624&endDate=20130703")
        out["range_sha256"] = hashlib.sha256(raw).hexdigest()
        out["range_row_count"] = len(rows)
        out["official_close"] = target.get("close") if target else None
        out["official_open"] = target.get("open") if target else None
        out["official_name"] = target.get("indexNameCnAll") if target else None
        out["prev_day_close"] = (
            rows.get("20130627") or {}).get("close")
        out["next_day_close"] = (
            rows.get("20130701") or {}).get("close")
    out["evidence_grade"] = "L1"
    out["evidence_grade_reason"] = "中证指数有限公司官网行情接口原始响应"
    return out
