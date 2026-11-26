"""阶段3B-6.2.3.0 官方证据获取与覆盖率审计（只读，不写正式数据库）。

两部分：

1. **10 个已接入指数的收益口径官方核验** —— 下载中证指数有限公司官方
   编制方案/指数单张原件，提取官方口径定义，判断数据库实际接入序列
   对应哪个指数版本。
2. **78 只基金的 L1 合同原件获取审计** —— 通过巨潮资讯（证监会指定
   信息披露网站）逐只检索基金合同与招募说明书原件。

严格规则：

- 未真实下载到的文件不得填写 SHA256。
- 无官方来源的文件不得标 L1。
- 无法证明序列与官方口径一一对应时保持 ``unknown``。
- 不得用当前文件冒充历史版本。
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EVID = ROOT / "reports" / "evidence" / "phase3B6_2_3_0"
REPORTS = ROOT / "reports"
METH_DIR = EVID / "index_methodology"
CONTRACT_DIR = EVID / "fund_contracts"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# 中证指数官方 OSS（编制方案/指数单张正式托管域名）
CSI_OSS = ("https://oss-ch.csindex.com.cn/static/html/csindex/public/"
           "uploads/indices/detail/files/zh_CN/")
CSI_BASIC = "https://www.csindex.com.cn/csindex-home/indexInfo/index-basic-info/"

CNINFO_QUERY = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_SEARCH = "http://www.cninfo.com.cn/new/information/topSearch/query"
CNINFO_STATIC = "https://static.cninfo.com.cn/"

# 易方达基金官网披露接口（已实测可用；catalogInnerCode 为栏目代码）
EFUNDS_API = "https://api.efunds.com.cn/xcowch/front/cache/information"
EFUNDS_REFERER = "https://www.efunds.com.cn/lm/jgfw/xxpl/"
EFUNDS_CONTRACT_CAT = "006169000001000003000001"
EFUNDS_PROSPECTUS_CAT = "006169000001000003000007"

INDEX_CODES = ["000300", "000905", "000906", "000016", "399997",
               "H30184", "000942", "000012", "000922", "930930"]


# ---------------------------------------------------------------- 工具
def _get(url: str, *, timeout: int = 60, referer: str | None = None,
         retries: int = 2) -> bytes:
    """带重试的 GET：官方站点偶发连接抖动，不得据此判定文件不存在。"""
    h = {"User-Agent": UA}
    if referer:
        h["Referer"] = referer
    last: Exception | None = None
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as exc:
            last = exc
    raise last  # type: ignore[misc]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pdf_text(path: Path) -> str:
    from pypdf import PdfReader
    return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)


def _post(url: str, body: dict, *, referer: str) -> dict:
    req = urllib.request.Request(
        url, data=urllib.parse.urlencode(body).encode(),
        headers={"User-Agent": UA, "Referer": referer,
                 "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


# ---------------------------------------------------------------- 指数
def fetch_index_basic(code: str) -> dict:
    """中证指数官网指数基本信息（官方发布机构）。"""
    try:
        d = json.loads(_get(CSI_BASIC + code, timeout=30,
                            referer="https://www.csindex.com.cn/").decode("utf-8"))
        data = d.get("data") or {}
        return {
            "index_full_name": data.get("indexFullNameCn"),
            "index_short_name": data.get("indexShortNameCn"),
            "publish_date": data.get("publishDate"),
            "basic_date": data.get("basicDate"),
            "index_type": data.get("indexType"),
            "description": data.get("indexCnDesc"),
            "publisher": "中证指数有限公司",
            "source_url": CSI_BASIC + code,
            "obtained": bool(data),
        }
    except Exception as exc:
        return {"publisher": "中证指数有限公司", "source_url": CSI_BASIC + code,
                "obtained": False, "error": f"{type(exc).__name__}: {exc}"}


def fetch_methodology(code: str) -> dict:
    """下载官方编制方案；文件名有多种命名，逐个真实尝试。"""
    METH_DIR.mkdir(parents=True, exist_ok=True)
    names = [
        f"{code}_Index_Methodology_cn.pdf",
        f"20231208175434-{code}_Index_Methodology_cn.pdf",
    ]
    attempts = []
    for name in names:
        url = CSI_OSS + name
        try:
            data = _get(url, timeout=90)
        except Exception as exc:
            attempts.append({"url": url, "status": "failed",
                             "error": f"{type(exc).__name__}"})
            continue
        if not data.startswith(b"%PDF"):
            attempts.append({"url": url, "status": "not_pdf",
                             "bytes": len(data)})
            continue
        local = METH_DIR / f"{code}_Index_Methodology_cn.pdf"
        local.write_bytes(data)
        attempts.append({"url": url, "status": "ok", "bytes": len(data)})
        return {
            "document_type": "编制方案（Index Methodology）",
            "source_org": "中证指数有限公司",
            "url": url,
            "disclosed_date": _methodology_date(local),
            "obtained_at": datetime.now().isoformat(timespec="seconds"),
            "file": str(local.relative_to(ROOT)).replace("\\", "/"),
            "bytes": len(data),
            "sha256": _sha256(data),
            "readable": True,
            "evidence_grade": "L1",
            "attempts": attempts,
        }
    # 编制方案缺失 → 退到官方指数单张（同属 L1 官方发布）
    fs = fetch_factsheet(code)
    fs["attempts"] = attempts
    return fs


def fetch_factsheet(code: str) -> dict:
    METH_DIR.mkdir(parents=True, exist_ok=True)
    url = f"{CSI_OSS}{code}factsheet.pdf"
    try:
        data = _get(url, timeout=90)
    except Exception as exc:
        return {"document_type": None, "source_org": None, "url": url,
                "obtained": False, "error": f"{type(exc).__name__}",
                "evidence_grade": "L4",
                "note": "编制方案与指数单张均未取得"}
    if not data.startswith(b"%PDF"):
        return {"document_type": None, "url": url, "obtained": False,
                "evidence_grade": "L4", "note": "返回内容不是 PDF"}
    local = METH_DIR / f"{code}_factsheet.pdf"
    local.write_bytes(data)
    return {
        "document_type": "指数单张（Factsheet）",
        "source_org": "中证指数有限公司",
        "url": url,
        "disclosed_date": _methodology_date(local),
        "obtained_at": datetime.now().isoformat(timespec="seconds"),
        "file": str(local.relative_to(ROOT)).replace("\\", "/"),
        "bytes": len(data),
        "sha256": _sha256(data),
        "readable": True,
        "obtained": True,
        "evidence_grade": "L1",
        "note": "官方编制方案未公开取得，以官方指数单张作为 L1 证据",
    }


def _methodology_date(path: Path) -> str | None:
    """从编制方案/单张首页提取官方版本日期（不臆造）。"""
    try:
        head = _pdf_text(path)[:400]
    except Exception:
        return None
    m = re.search(r"(20\d{2})\s*年\s*(\d{1,2})\s*月", head)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    return None


# 官方口径判定：只在**编制方案明文**支持时才给结论，否则 unknown
BASIS_RULES = [
    # (条件函数, 结论, 依据说明)
    (lambda t: "沪深300指数不予修正" in t.replace(" ", ""),
     "price",
     "编制方案 5.2.1 明文：样本除息时沪深300指数不予修正，任其自然回落"),
    (lambda t: "全收益指数" in t and "辅指数" in t,
     "price",
     "编制方案明文：全收益/净收益指数是价格指数的**辅指数**，主指数为价格口径"),
]


def judge_basis(text: str, doc_type: str | None) -> dict:
    """根据官方文件明文判断该指数**主序列**的收益口径。"""
    flat = text.replace(" ", "").replace("\n", "")
    evidence = []
    basis = "unknown"

    if "沪深300指数不予修正" in flat:
        basis = "price"
        evidence.append(
            "编制方案「5.2.1 除息」明文：凡有样本除息，沪深300指数不予修正，"
            "任其自然回落 → 主指数为**价格指数**")
    if "全收益指数、净收益指数是沪深300指数的辅指数" in flat:
        evidence.append(
            "编制方案「4.6 全收益指数和净收益指数」明文：全收益/净收益是"
            "沪深300指数的**辅指数** → 主指数不含红利再投资")

    # 债券指数：上证国债指数
    if "上证国债指数" in flat and "净价指数" in flat:
        evidence.append(
            "官方指数单张列出「净价指数」「利息再投资指数」为**衍生指数**，"
            "主序列 000012 为全价（含应计利息、不含再投资）")
        basis = "full_price"

    # 通用：编制方案仅用「证券价格×调整股本数」且未提全收益 → 价格口径
    if basis == "unknown" and doc_type and "编制方案" in doc_type:
        if "调整市值" in flat and "证券价格×调整股本数" in flat \
                and "全收益" not in flat and "再投资" not in flat:
            basis = "price"
            evidence.append(
                "编制方案「四、指数计算」仅使用「证券价格×调整股本数」计算"
                "调整市值，全文无全收益/红利再投资表述 → 价格指数口径")

    # 中证红利：股息率加权但仍是价格指数（成分股分红不进入指数点位）
    if basis == "price" and "股息率加权" in flat:
        evidence.append(
            "中证红利为**股息率加权**，加权方式不改变「除息自然回落」的"
            "价格口径属性")

    return {"return_basis": basis, "evidence": evidence,
            "basis_confirmed": basis != "unknown"}


API_SAMPLE_FILE = EVID / "api_identity_samples.json"


def _load_api_samples() -> dict:
    if API_SAMPLE_FILE.exists():
        try:
            return json.loads(API_SAMPLE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_api_samples(data: dict) -> None:
    EVID.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True)
    content = payload + "\n"
    API_SAMPLE_FILE.write_text(content, encoding="utf-8")
    (EVID / "api_identity_samples.sha256").write_text(
        hashlib.sha256(content.encode("utf-8")).hexdigest() + "\n",
        encoding="utf-8")


def probe_series(code: str, retries: int = 3) -> dict:
    """实测数据接口返回的指数代码与正式名称。

    **只用于身份核对（代码 + 名称），不得作为数据库历史序列的验证。**
    接口取不到时返回 ``obtained=False``（对应 unknown），
    **不得记为「不匹配」**——无证据与反证据必须区分。
    """
    import time
    cache = _load_api_samples()
    if cache.get(code, {}).get("returned_code"):
        return {**cache[code], "from_cache": True}

    last = None
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(2.0 * attempt)
        try:
            import akshare as ak
            df = ak.stock_zh_index_hist_csindex(
                symbol=code, start_date="20240102", end_date="20240105")
            rec = {
                "request_code": code,
                "obtained": True,
                "returned_code": str(df["指数代码"].iloc[0]),
                "returned_full_name": str(df["指数中文全称"].iloc[0]),
                "returned_short_name": str(df["指数中文简称"].iloc[0]),
                "rows": len(df),
                "columns": df.columns.tolist(),
                "sample_close": [round(float(x), 4)
                                 for x in df["收盘"].tolist()],
                "obtained_at": datetime.now().isoformat(timespec="seconds"),
                "source": "akshare.stock_zh_index_hist_csindex",
            }
            cache[code] = rec
            _save_api_samples(cache)
            return rec
        except Exception as exc:
            last = exc
    return {"request_code": code, "obtained": False,
            "error": f"接口未取得（{type(last).__name__}）"}


# ---------------------------------------------------------------- 数据库只读审计
def _db_connect():
    """正式数据库只读连接（不写、不改 Schema）。"""
    import sqlite3
    from app.config import settings
    p = str(settings.database_path).replace("\\", "/")
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    conn.execute("pragma temp_store = memory")
    return conn


def audit_db_series(code: str, conn) -> dict:
    """只读查询正式数据库中该指数的**实际**历史行情记录。

    先读真实 Schema，不猜测表名/字段名。
    """
    cols = [r[1] for r in conn.execute("pragma table_info(index_daily)")]
    master_cols = [r[1] for r in conn.execute("pragma table_info(index_master)")]
    out: dict = {
        "table": "index_daily",
        "schema_columns_read": cols,
        "master_columns_read": master_cols,
        "exists": False,
        "rows": 0,
        "date_min": None,
        "date_max": None,
        "missing_trading_days": None,
        "sources": [],
        "run_ids": [],
        "collected_at_min": None,
        "collected_at_max": None,
        "quality_status_counts": {},
        "suspect_rows": [],
        "row_fingerprint_present": False,
        "source_traceable": False,
        "source_traceable_reason": None,
    }
    row = conn.execute(
        "select count(*), min(trade_date), max(trade_date), "
        "min(collected_at), max(collected_at) "
        "from index_daily where index_code=?", (code,)).fetchone()
    if not row or not row[0]:
        out["source_traceable_reason"] = "正式库 index_daily 无该指数任何记录"
        return out
    out.update({
        "exists": True,
        "rows": row[0],
        "date_min": row[1],
        "date_max": row[2],
        "collected_at_min": row[3],
        "collected_at_max": row[4],
    })
    out["sources"] = sorted({
        r[0] for r in conn.execute(
            "select distinct source from index_daily where index_code=?",
            (code,))})
    out["run_ids"] = sorted({
        r[0] for r in conn.execute(
            "select distinct run_id from index_daily where index_code=? "
            "and run_id is not null", (code,))})
    out["quality_status_counts"] = {
        r[0]: r[1] for r in conn.execute(
            "select quality_status, count(*) from index_daily "
            "where index_code=? group by quality_status", (code,))}
    out["suspect_rows"] = [
        {"trade_date": r[0], "close": r[1], "quality_note": r[2]}
        for r in conn.execute(
            "select trade_date, close, quality_note from index_daily "
            "where index_code=? and quality_status<>'valid' "
            "order by trade_date", (code,))]
    fp = conn.execute(
        "select count(*) from index_daily where index_code=? "
        "and row_fingerprint is not null and row_fingerprint<>''",
        (code,)).fetchone()
    out["row_fingerprint_present"] = bool(fp and fp[0] == out["rows"])

    # 可追溯性：必须同时有数据源、序列标识、采集记录
    missing = []
    if not out["sources"]:
        missing.append("无 source 字段值")
    if not out["run_ids"]:
        missing.append("无 run_id 采集批次标识")
    if not out["row_fingerprint_present"]:
        missing.append("无 row_fingerprint 行级指纹")
    if not out["collected_at_min"]:
        missing.append("无 collected_at 采集时间")
    out["source_traceable"] = not missing
    out["source_traceable_reason"] = (
        "具备数据源/批次标识/行级指纹/采集时间" if not missing
        else "；".join(missing))
    return out


def audit_master_row(code: str, conn) -> dict:
    """只读查询 index_master 中该指数的现有登记与证据字段。"""
    cols = ["index_code", "index_name", "index_short_name", "publisher",
            "data_source", "return_basis", "return_basis_evidence",
            "inception_date", "inception_date_evidence",
            "data_status", "layer_status", "data_version"]
    row = conn.execute(
        f"select {','.join(cols)} from index_master where index_code=?",
        (code,)).fetchone()
    if not row:
        return {"exists": False}
    return {"exists": True, **dict(zip(cols, row))}


# ---------------------------------------------------------------- 官方数值校验
OFFICIAL_PERF = ("https://www.csindex.com.cn/csindex-home/perf/"
                 "index-perf?indexCode={code}&startDate={d}&endDate={d}")

# 多个不同年份的抽样日（必须真实交易日；取不到则记为未命中，不得改用别的值）
PROBE_DATES = ["20240102", "20200102", "20150105", "20180102"]


_OFFICIAL_LAST_CALL = [0.0]
OFFICIAL_SAMPLE_FILE = EVID / "official_close_samples.json"


def _load_official_samples() -> dict:
    if OFFICIAL_SAMPLE_FILE.exists():
        try:
            return json.loads(OFFICIAL_SAMPLE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_official_samples(data: dict) -> None:
    """固化已取得的官方数值样本（含来源 URL、获取时间、SHA256）。"""
    EVID.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True)
    content = payload + "\n"
    OFFICIAL_SAMPLE_FILE.write_text(content, encoding="utf-8")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    (EVID / "official_close_samples.sha256").write_text(
        digest + "\n", encoding="utf-8")


def _official_sample_sha256() -> str | None:
    f = EVID / "official_close_samples.sha256"
    return f.read_text(encoding="utf-8").strip() if f.exists() else None


def official_close(code: str, yyyymmdd: str,
                   retries: int = 3, gap: float = 1.2) -> dict:
    """从中证指数官网官方行情接口取该日官方收盘值。

    官网对密集请求返回 403；此处限速 + 退避重试，
    **仍取不到时如实记录为未取得，不得改用第三方数据顶替。**
    """
    import time
    u = OFFICIAL_PERF.format(code=code, d=yyyymmdd)

    # 优先读已固化的官方样本（同一 URL 且已取得数值）
    cache = _load_official_samples()
    key = f"{code}|{yyyymmdd}"
    hit = cache.get(key)
    if hit and hit.get("close") is not None:
        return {**hit, "from_cache": True}

    last = None
    for attempt in range(retries + 1):
        wait = gap * (attempt + 1) - (time.time() - _OFFICIAL_LAST_CALL[0])
        if wait > 0:
            time.sleep(wait)
        _OFFICIAL_LAST_CALL[0] = time.time()
        try:
            raw = _get(u, timeout=30, referer="https://www.csindex.com.cn/",
                       retries=0)
            d = json.loads(raw.decode("utf-8"))
            rows = d.get("data") or []
            if not rows:
                return {"date": yyyymmdd, "close": None,
                        "reason": "官方接口该日无数据（可能非交易日）"}
            r = rows[0]
            rec = {"date": yyyymmdd, "close": r.get("close"),
                   "official_code": r.get("indexCode"),
                   "official_name": r.get("indexNameCnAll"),
                   "url": u,
                   "obtained_at": datetime.now().isoformat(timespec="seconds"),
                   "source": "中证指数有限公司官网行情接口"}
            if rec["close"] is not None:
                cache = _load_official_samples()
                cache[key] = rec
                _save_official_samples(cache)
            return rec
        except Exception as exc:
            last = exc
    return {"date": yyyymmdd, "close": None,
            "reason": f"官方接口未取得（{type(last).__name__}）", "url": u}


def numerical_verify(code: str, conn, tolerance: float = 0.01) -> dict:
    """数值级验证：数据库收盘值 vs 中证指数官网官方收盘值。

    **只有真实取得官方数值并逐日比对成功才算通过。**
    官方取不到数据的日期记为未命中，不计入通过，也不替换为其他值。
    """
    comparisons = []
    matched = 0
    for d in PROBE_DATES:
        iso = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        off = official_close(code, d)
        row = conn.execute(
            "select close, quality_status from index_daily "
            "where index_code=? and trade_date=?", (code, iso)).fetchone()
        db_close = row[0] if row else None
        db_quality = row[1] if row else None
        ok = (off.get("close") is not None and db_close is not None
              and abs(float(off["close"]) - float(db_close)) <= tolerance)
        if ok:
            matched += 1
        comparisons.append({
            "date": iso,
            "official_close": off.get("close"),
            "database_close": db_close,
            "database_quality_status": db_quality,
            "abs_diff": (round(abs(float(off["close"]) - float(db_close)), 6)
                         if ok or (off.get("close") is not None
                                   and db_close is not None) else None),
            "match": ok,
            "official_url": off.get("url"),
            "note": off.get("reason"),
        })
    official_obtained = sum(1 for c in comparisons
                            if c["official_close"] is not None)
    mismatch = sum(1 for c in comparisons
                   if c["official_close"] is not None
                   and c["database_close"] is not None
                   and not c["match"])
    # 三态：取不到官方数值 → None（unknown），不是 False
    if official_obtained == 0:
        verified = None
        verdict = ("**未取得任何官方数值样本**：接口限流或该日无数据，"
                   "按 unknown 记录，不得判定为已验证或不一致")
    elif mismatch > 0:
        verified = False
        verdict = f"**官方数值与数据库不一致**（{mismatch} 处），判定为未通过"
    elif matched >= 2:
        verified = True
        verdict = f"逐日比对 {matched} 个不同年份的官方收盘值全部一致"
    else:
        verified = None
        verdict = (f"仅取得 {official_obtained} 个官方样本，"
                   "不足 2 个不同年份，不足以判定通过")
    return {
        "tolerance": tolerance,
        "probe_dates": PROBE_DATES,
        "comparisons": comparisons,
        "official_obtained": official_obtained,
        "matched": matched,
        "mismatch": mismatch,
        "verified": verified,
        "verdict": verdict,
        "samples_file": "reports/evidence/phase3B6_2_3_0/"
                        "official_close_samples.json",
        "samples_sha256": _official_sample_sha256(),
        "method": ("逐日比对中证指数有限公司官网官方行情接口收盘值，"
                   "容差 0.01；官方无数据日不计入通过；"
                   "取不到官方数值记 unknown，不记 false"),
    }


def verify_index(code: str, conn) -> dict:
    """九个独立验证维度，逐项判定，不得互相替代。"""
    basic = fetch_index_basic(code)
    doc = fetch_methodology(code)
    text = ""
    if doc.get("file"):
        try:
            text = _pdf_text(ROOT / doc["file"])
        except Exception:
            text = ""
    judged = judge_basis(text, doc.get("document_type"))
    api = probe_series(code)
    db = audit_db_series(code, conn)
    master = audit_master_row(code, conn)
    num = numerical_verify(code, conn)

    official_name = basic.get("index_full_name")
    official_code = code

    # 1. 官方身份核验：代码 + 正式名称 + 发布机构三者齐全
    official_identity_verified = bool(
        basic.get("obtained") and official_name
        and basic.get("publisher")
        and (doc.get("file") is not None))

    # 2. 官方收益口径核验
    official_return_basis_verified = bool(judged["basis_confirmed"])

    # 3. API 代码身份（取不到 → None/unknown，不是 False）
    if not api.get("obtained"):
        api_code_identity_verified = None
        api_name_identity_verified = None
    else:
        api_code_identity_verified = bool(api.get("returned_code") == code)
        # 4. API 正式名称：必须与官方全称一致，不能只比代码
        api_name_identity_verified = bool(
            official_name and api.get("returned_full_name") == official_name)

    # 5. 数据库序列存在
    database_series_exists = bool(db["exists"])

    # 6. 数据源可追溯
    database_series_source_traceable = bool(db["source_traceable"])

    # 7. 数值级官方验证（三态：True / False / None=unknown）
    database_series_numerically_verified = num["verified"]

    # 8. 历史覆盖：本阶段未做交易日历连续性核验
    historical_coverage_verified = False
    coverage_note = ("本阶段未接入交易日历做缺失日核验，"
                     "仅记录库内首末日期与行数")

    # 9. 时点可用性：未做
    point_in_time_verified = False

    return {
        "index_code": code,
        "official": basic,
        "document": doc,
        "return_basis_judgement": judged,
        "official_identity_verified": official_identity_verified,
        "official_return_basis_verified": official_return_basis_verified,
        "api_identity": api,
        "api_code_identity_verified": api_code_identity_verified,
        "api_name_identity_verified": api_name_identity_verified,
        "database": db,
        "database_series_exists": database_series_exists,
        "database_series_source_traceable":
            database_series_source_traceable,
        "database_master_row": master,
        "numerical_verification": num,
        "database_series_numerically_verified":
            database_series_numerically_verified,
        "historical_coverage_verified": historical_coverage_verified,
        "historical_coverage_note": coverage_note,
        "point_in_time_verified": point_in_time_verified,
        "point_in_time_note": "本阶段未做时点可用性（前视偏差）审计",
        # 同一指数逐条判断：口径确认 + 数值级验证同时为真才通过
        "series_matches_official_basis": bool(
            official_return_basis_verified
            and database_series_numerically_verified is True),
    }


def audit_indexes() -> dict:
    conn = _db_connect()
    try:
        records = [verify_index(code, conn) for code in INDEX_CODES]
    finally:
        conn.close()
    return {"indexes": records}


# ---------------------------------------------------------------- 基金合同
CONTRACT_KEYS = ["基金合同", "招募说明书"]
SKIP_WORDS = ["托管协议", "季度报告", "年度报告", "中期报告",
              "资料概要", "风险提示", "分红", "费率", "上市交易"]


def cninfo_org_id(fund_code: str) -> dict:
    try:
        d = _post(CNINFO_SEARCH, {"keyWord": fund_code, "maxNum": "10"},
                  referer="http://www.cninfo.com.cn/")
        for item in d or []:
            if item.get("code") == fund_code and item.get("orgId"):
                return {"org_id": item["orgId"], "short_name": item.get("zwjc"),
                        "category": item.get("category")}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    return {"error": "巨潮未检索到该基金代码"}


def cninfo_announcements(fund_code: str, org_id: str,
                         max_pages: int = 20) -> list[dict]:
    """分页抓取该基金全部公告（只取第一页会漏掉历年基金合同）。"""
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        base = {"pageNum": page, "pageSize": 30, "column": "fund",
                "tabName": "fulltext", "plate": "",
                "stock": f"{fund_code},{org_id}",
                "searchkey": "", "secid": "", "category": "", "trade": "",
                "seDate": "", "sortName": "", "sortType": "",
                "isHLtitle": "true"}
        d = _post(CNINFO_QUERY, base, referer="http://www.cninfo.com.cn/")
        rows = d.get("announcements") or []
        if not rows:
            break
        for a in rows:
            title = re.sub(r"<[^>]+>", "", a.get("announcementTitle") or "")
            ts = a.get("announcementTime")
            out.append({"title": title, "url": a.get("adjunctUrl"),
                        "date": (datetime.fromtimestamp(ts / 1000)
                                 .strftime("%Y-%m-%d") if ts else None),
                        "sec_name": a.get("secName")})
    return out


# ---------------------------------------------------------------- 易方达官网
def efunds_query(full_name: str, catalog: str) -> list[dict]:
    """易方达官网披露检索（返回该栏目下匹配的公告，含 PDF 直链）。"""
    body = {"siteID": "1", "catalogInnerCode": catalog,
            "allCatalog": "false", "startDate": "", "endDate": "",
            "pageSize": "100", "pageIndex": "0",
            "query": urllib.parse.quote(full_name)}
    req = urllib.request.Request(
        EFUNDS_API, data=urllib.parse.urlencode(body).encode(),
        headers={"User-Agent": UA, "Referer": EFUNDS_REFERER,
                 "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=45) as r:
        d = json.loads(r.read().decode("utf-8", "ignore"))
    rows = (d.get("data") or {}).get("data") or []
    out = []
    for x in rows:
        out.append({
            "title": re.sub(r"<[^>]+>", "", x.get("title") or ""),
            "url": x.get("url"),
            "date": (x.get("publishDate") or "")[:10] or None,
            "catalog": x.get("catalogName"),
        })
    return out


def pick_documents(anns: list[dict]) -> dict:
    """从公告列表中挑出「当前合同」与「当前招募说明书」。

    **历史版本单独归类，不得当作当前版本使用。**
    """
    cur_contract = None
    cur_prospectus = None
    history = []
    for a in anns:
        title = a["title"]
        if any(w in title for w in SKIP_WORDS):
            continue
        is_contract = "基金合同" in title
        is_prospectus = "招募说明书" in title
        if not (is_contract or is_prospectus):
            continue
        if is_contract:
            if cur_contract is None or (a.get("date") or "") > (
                    cur_contract.get("date") or ""):
                if cur_contract:
                    history.append(cur_contract)
                cur_contract = {**a, "doc_type": "基金合同"}
            else:
                history.append({**a, "doc_type": "基金合同"})
        else:
            if cur_prospectus is None or (a.get("date") or "") > (
                    cur_prospectus.get("date") or ""):
                if cur_prospectus:
                    history.append(cur_prospectus)
                cur_prospectus = {**a, "doc_type": "招募说明书"}
            else:
                history.append({**a, "doc_type": "招募说明书"})
    return {"current_contract": cur_contract,
            "current_prospectus": cur_prospectus,
            "history_versions": history[:20],
            "history_count": len(history)}


def download_contract(doc: dict, fund_code: str,
                      *, absolute_url: bool = False) -> dict:
    if not doc or not doc.get("url"):
        return {"obtained": False, "reason": "未检索到官方公告"}
    CONTRACT_DIR.mkdir(parents=True, exist_ok=True)
    url = doc["url"] if absolute_url else (CNINFO_STATIC + doc["url"])
    local = CONTRACT_DIR / f"{fund_code}_{doc['doc_type']}.pdf"
    try:
        data = _get(url, timeout=120, referer="http://www.cninfo.com.cn/")
    except Exception as exc:
        return {"obtained": False, "url": url,
                "reason": f"下载失败 {type(exc).__name__}"}
    if not data.startswith(b"%PDF"):
        return {"obtained": False, "url": url,
                "reason": f"返回非 PDF（{len(data)} 字节）"}
    local.write_bytes(data)
    try:
        text = _pdf_text(local)
        readable = len(text) > 1000
    except Exception:
        text, readable = "", False
    return {
        "obtained": True,
        "url": url,
        "file": str(local.relative_to(ROOT)).replace("\\", "/"),
        "bytes": len(data),
        "sha256": _sha256(data),
        "readable": readable,
        "text_chars": len(text),
        "benchmark_excerpt": extract_benchmark(text),
        "obtained_at": datetime.now().isoformat(timespec="seconds"),
        "disclosed_date": doc.get("date"),
        "doc_type": doc["doc_type"],
        "title": doc["title"],
    }


def extract_benchmark(text: str) -> dict:
    """从合同/招募说明书原文提取「业绩比较基准」条款。

    只接受**同时含指数/利率成分与百分比**的片段，避免抓到
    「业绩比较基准的紧密跟踪……」这类不含基准定义的句子。
    """
    flat = re.sub(r"\s+", "", text)
    hits = []
    # 优先取「定义式」表述：业绩比较基准为/：……到句号结束
    for m in re.finditer(r"业绩比较基准(?:为|是|：|:)", flat):
        seg = flat[m.start():m.start() + 260]
        # 在定义结束处截断：句号，或紧随其后的正文/页脚（PDF 会插入页脚）
        ends = [seg.find(k) for k in
                ("。", "未来若", "本基金", "由于本基金", "1、", "注：", "该指数")]
        ends = [e for e in ends if e > 10]
        if ends:
            seg = seg[:min(ends) + 1]
        hits.append(seg)
        if len(hits) >= 2:
            break
    # 退一步：含百分比 + 收益率/利率成分的片段
    if not hits:
        for m in re.finditer("业绩比较基准", flat):
            seg = flat[m.start():m.start() + 240]
            if ("%" in seg or "％" in seg) and ("收益率" in seg or "利率" in seg):
                hits.append(seg)
            if len(hits) >= 3:
                break
    return {"found": bool(hits), "excerpts": hits,
            "primary": hits[0] if hits else None}


def normalize_benchmark(s: str) -> str:
    """归一化用于文本一致性比对（不改变语义）。"""
    if not s:
        return ""
    t = re.sub(r"\s+", "", s)
    t = t.replace("％", "%").replace("＋", "+").replace("×", "*")
    t = t.replace("（", "(").replace("）", ")")
    t = re.sub(r"[Xx](?=\d)", "*", t)   # 第三方常把乘号写成 X
    return t


def compare_with_l3(contract_text: str, l3_text: str) -> dict:
    """合同原文与第三方 L3 文本的一致性比对。

    不能只看「包含」：第三方文本可能只是合同基准的一个片段
    （例如只写了单一指数而合同是复合基准），这种情况同样属**冲突**。
    """
    a = normalize_benchmark(contract_text)
    b = normalize_benchmark(l3_text)
    if not a or not b:
        return {"comparable": False, "consistent": None,
                "note": "缺少可比对文本"}
    contained = b in a
    # 权重数量差异：L3 若缺了合同里的权重成分，属语义冲突
    l3_weights = re.findall(r"\d+(?:\.\d+)?%", b)
    ct_weights = re.findall(r"\d+(?:\.\d+)?%", a)
    weights_match = sorted(l3_weights) == sorted(ct_weights)
    consistent = contained and (weights_match or not l3_weights)
    if contained and not weights_match:
        note = (f"第三方文本可在合同原文中找到，但**权重成分不一致**："
                f"L3={l3_weights} / 合同={ct_weights}")
    elif contained:
        note = "第三方文本与合同原文一致"
    else:
        note = "第三方文本与合同原文**不一致**（可能为历史版本或第三方转录误差）"
    return {
        "comparable": True,
        "consistent": consistent,
        "l3_weights": l3_weights,
        "contract_weights": ct_weights,
        "normalized_l3": b[:200],
        "normalized_contract": a[:300],
        "note": note,
    }


def _fund_meta(codes: list[str]) -> dict:
    """从只读正式库取基金全称与管理人（用于官网渠道检索）。"""
    import sqlite3
    from app.config import settings
    conn = sqlite3.connect(f"file:{settings.database_path}?mode=ro", uri=True)
    try:
        q = ("select fund_code_primary, fund_company, fund_full_name "
             "from fund_master where fund_code_primary in (%s)"
             % ",".join("?" * len(codes)))
        return {r[0]: {"company": r[1], "full_name": r[2]}
                for r in conn.execute(q, codes).fetchall()}
    finally:
        conn.close()


def try_efunds(full_name: str, code: str) -> dict:
    """易方达官网渠道：分别检索基金合同与招募说明书栏目。"""
    try:
        contracts = efunds_query(full_name, EFUNDS_CONTRACT_CAT)
        pros = efunds_query(full_name, EFUNDS_PROSPECTUS_CAT)
    except Exception as exc:
        return {"available": False,
                "error": f"{type(exc).__name__}: {exc}"}
    # 按披露日期倒序，取最新为当前版本；其余归入历史版本
    contracts = sorted(contracts, key=lambda x: x.get("date") or "",
                       reverse=True)
    pros = sorted(pros, key=lambda x: x.get("date") or "", reverse=True)
    cur = contracts[0] if contracts else None
    pro = pros[0] if pros else None
    return {
        "available": True,
        "current_contract": ({**cur, "doc_type": "基金合同"} if cur else None),
        "current_prospectus": ({**pro, "doc_type": "招募说明书"}
                               if pro else None),
        "history_versions": ([{**c, "doc_type": "基金合同"}
                              for c in contracts[1:]]
                             + [{**p, "doc_type": "招募说明书"}
                                for p in pros[1:]]),
    }


def audit_funds() -> dict:
    audit = json.loads(
        (REPORTS / "phase3B6_2_2_mapping_audit.json").read_text(encoding="utf-8"))
    targets = [f for f in audit["funds"]
               if f["benchmarks"]["contract"]["name"]]
    meta = _fund_meta([f["fund_code"] for f in targets])
    records = []
    for f in targets:
        code = f["fund_code"]
        info = meta.get(code) or {}
        org = cninfo_org_id(code)
        rec = {
            "fund_id": f["fund_id"],
            "fund_code": code,
            "fund_name": f["fund_name"],
            "fund_full_name": info.get("full_name"),
            "fund_company": info.get("company"),
            "category": f["category"],
            "l3_benchmark_text": f["benchmarks"]["contract"]["name"],
            "cninfo": org,
        }

        # ---- 渠道 1：管理人官网（易方达，已实测可用）----
        if info.get("company") and "易方达" in info["company"]:
            ef = try_efunds(info.get("full_name") or "", code)
            if ef.get("available"):
                cur = download_contract(ef["current_contract"], code,
                                        absolute_url=True)
                pro = download_contract(ef["current_prospectus"], code,
                                        absolute_url=True)
                contract_ok = bool(cur.get("obtained") and cur.get("readable"))
                prospectus_ok = bool(pro.get("obtained") and pro.get("readable"))
                cmp_result = {"comparable": False}
                if contract_ok and cur.get("benchmark_excerpt", {}).get("primary"):
                    cmp_result = compare_with_l3(
                        cur["benchmark_excerpt"]["primary"],
                        rec["l3_benchmark_text"])
                rec.update({
                    "channel": "管理人官方网站（易方达基金）",
                    "contract_found": contract_ok,
                    "prospectus_found": prospectus_ok,
                    "current_contract": cur,
                    "current_prospectus": pro,
                    "history_versions": ef["history_versions"][:20],
                    "history_count": len(ef["history_versions"]),
                    "history_versions_missing": not ef["history_versions"],
                    "text_consistent_with_l3": cmp_result.get("consistent"),
                    "text_comparison": cmp_result,
                    "evidence_grade": ("L1" if contract_ok else
                                       ("L2" if prospectus_ok else "L3")),
                    "not_obtained_reason": (
                        None if contract_ok else
                        (cur.get("reason") or "官网栏目未检索到基金合同")),
                    "disclosed_date": (cur.get("disclosed_date") if contract_ok
                                       else pro.get("disclosed_date")),
                    "sha256": (cur.get("sha256") if contract_ok
                               else pro.get("sha256")),
                })
                records.append(rec)
                continue

        # ---- 渠道 2：巨潮资讯（证监会指定披露网站，仅覆盖场内品种）----
        if org.get("error"):
            rec.update({
                "channel": "未获取（巨潮基金频道仅覆盖场内品种）",
                "contract_found": False,
                "prospectus_found": False,
                "evidence_grade": "L3",
                "not_obtained_reason": (
                    "巨潮资讯基金频道仅收录 LOF/封闭式/ETF 等场内品种，"
                    "该基金为场外品种，未在巨潮收录；管理人官网渠道未实现"),
                "current_contract": None,
                "current_prospectus": None,
                "history_versions": [],
                "history_versions_missing": True,
            })
            records.append(rec)
            continue
        anns = cninfo_announcements(code, org["org_id"])
        picked = pick_documents(anns)
        cur = download_contract(picked["current_contract"], code)
        pro = download_contract(picked["current_prospectus"], code)
        contract_ok = cur.get("obtained") and cur.get("readable")
        prospectus_ok = pro.get("obtained") and pro.get("readable")
        cmp_result = {"comparable": False}
        if contract_ok and cur.get("benchmark_excerpt", {}).get("primary"):
            cmp_result = compare_with_l3(
                cur["benchmark_excerpt"]["primary"], rec["l3_benchmark_text"])
        rec.update({
            "channel": "巨潮资讯网（证监会指定信息披露网站）",
            "contract_found": bool(contract_ok),
            "prospectus_found": bool(prospectus_ok),
            "current_contract": cur,
            "current_prospectus": pro,
            "history_versions": picked["history_versions"],
            "history_count": picked["history_count"],
            "history_versions_missing": picked["history_count"] == 0,
            "text_consistent_with_l3": cmp_result.get("consistent"),
            "text_comparison": cmp_result,
            "evidence_grade": "L1" if contract_ok else (
                "L2" if prospectus_ok else "L3"),
            "not_obtained_reason": (
                None if contract_ok else
                (cur.get("reason") or "官方渠道未检索到基金合同")),
            "disclosed_date": (cur.get("disclosed_date") if contract_ok
                               else pro.get("disclosed_date")),
            "sha256": (cur.get("sha256") if contract_ok else pro.get("sha256")),
        })
        records.append(rec)
    return {"funds": records}


# ---------------------------------------------------------------- 汇总
def summarize(idx: dict, fund: dict) -> dict:
    irecs = idx["indexes"]
    frecs = fund["funds"]

    def cnt(seq, pred):
        return sum(1 for r in seq if pred(r))

    def cnt_true(pred):
        return sum(1 for r in irecs if pred(r) is True)

    def cnt_unknown(pred):
        return sum(1 for r in irecs if pred(r) is None)

    idx_summary = {
        "total_indexes": len(irecs),
        # ---- 官方证据 ----
        "official_document_obtained": cnt(
            irecs, lambda r: r["document"].get("file") is not None),
        "methodology_obtained": cnt(
            irecs, lambda r: (r["document"].get("document_type") or "")
            .startswith("编制方案")),
        "factsheet_only": cnt(
            irecs, lambda r: (r["document"].get("document_type") or "")
            .startswith("指数单张")),
        # ---- 九个独立验证维度（逐条明细自动汇总）----
        "official_identity_verified": cnt_true(
            lambda r: r["official_identity_verified"]),
        "official_return_basis_verified": cnt_true(
            lambda r: r["official_return_basis_verified"]),
        "api_code_identity_verified": cnt_true(
            lambda r: r["api_code_identity_verified"]),
        "api_name_identity_verified": cnt_true(
            lambda r: r["api_name_identity_verified"]),
        "database_series_exists": cnt_true(
            lambda r: r["database_series_exists"]),
        "database_series_source_traceable": cnt_true(
            lambda r: r["database_series_source_traceable"]),
        "database_series_numerically_verified": cnt_true(
            lambda r: r["database_series_numerically_verified"]),
        "database_series_numerically_unknown": cnt_unknown(
            lambda r: r["database_series_numerically_verified"]),
        "database_series_numerically_mismatch": sum(
            1 for r in irecs
            if r["database_series_numerically_verified"] is False),
        "historical_coverage_verified": cnt_true(
            lambda r: r["historical_coverage_verified"]),
        "point_in_time_verified": cnt_true(
            lambda r: r["point_in_time_verified"]),
        # ---- 同一指数逐条判断的复合结论 ----
        "series_matches_official_basis": cnt_true(
            lambda r: r["series_matches_official_basis"]),
        # ---- 兼容字段（语义已明确，见 deprecated_fields）----
        "return_basis_confirmed": cnt_true(
            lambda r: r["official_return_basis_verified"]),
        "return_basis_still_unknown": sum(
            1 for r in irecs if not r["official_return_basis_verified"]),
        "grade_counts": _counter(r["document"].get("evidence_grade")
                                  for r in irecs),
        "basis_counts": _counter(
            r["return_basis_judgement"]["return_basis"] for r in irecs),
    }
    idx_summary["deprecated_fields"] = {
        "series_matched": "已废弃 → api_code_identity_verified",
        "data_series_matches_official":
            "已废弃 → 不得作为数值验证结论；"
            "数值验证见 database_series_numerically_verified",
        "series_matches_official":
            "已废弃 → series_matches_official_basis（需数值级验证）",
    }

    fund_summary = {
        "total_funds": len(frecs),
        "l1_contract_obtained": cnt(frecs, lambda r: r["contract_found"]),
        "prospectus_only": cnt(
            frecs, lambda r: r["prospectus_found"] and not r["contract_found"]),
        "still_l3_only": cnt(
            frecs, lambda r: not r["contract_found"]
            and not r["prospectus_found"]),
        "not_obtained": cnt(frecs, lambda r: not r["contract_found"]),
        "text_conflict_with_l3": cnt(
            frecs, lambda r: r.get("text_consistent_with_l3") is False),
        "text_consistent_with_l3": cnt(
            frecs, lambda r: r.get("text_consistent_with_l3") is True),
        "history_versions_missing": cnt(
            frecs, lambda r: r.get("history_versions_missing", True)),
        "grade_counts": _counter(r["evidence_grade"] for r in frecs),
    }

    # 门禁：同一指数必须同时满足全部条件，**不得用两个独立计数都 >0 判定**
    gate = {
        "at_least_one_index_basis_l1": idx_summary[
            "official_return_basis_verified"] > 0,
        "at_least_one_fund_l1_contract": fund_summary[
            "l1_contract_obtained"] > 0,
        # 逐指数判断：口径确认 + 数值级官方验证为 True
        "series_matches_official_basis": (
            idx_summary["series_matches_official_basis"] > 0),
        "all_indexes_numerically_verified": (
            idx_summary["database_series_numerically_verified"]
            == idx_summary["total_indexes"]),
        "all_indexes_coverage_verified": (
            idx_summary["historical_coverage_verified"]
            == idx_summary["total_indexes"]),
        "all_indexes_point_in_time_verified": (
            idx_summary["point_in_time_verified"]
            == idx_summary["total_indexes"]),
        "ready_for_3b6_2_3_1_series_build": False,
        "note": ("历史连续覆盖与时点可用性仍未确认，"
                 "不得直接进入指数收益序列建设；"
                 "数值级验证通过也不代表可直接回测"),
    }

    return {
        "index_summary": idx_summary,
        "fund_summary": fund_summary,
        "gates": gate,
        "_self_check": {
            "index_count_matches_detail": (
                idx_summary["total_indexes"] == len(INDEX_CODES)),
            "fund_count_matches_detail": (
                fund_summary["total_funds"] == len(frecs)),
            "index_partition_ok": (
                idx_summary["official_return_basis_verified"]
                + idx_summary["return_basis_still_unknown"]
                == idx_summary["total_indexes"]),
            "numerical_partition_ok": (
                idx_summary["database_series_numerically_verified"]
                + idx_summary["database_series_numerically_unknown"]
                + idx_summary["database_series_numerically_mismatch"]
                == idx_summary["total_indexes"]),
            "fund_partition_ok": (
                fund_summary["l1_contract_obtained"]
                + fund_summary["prospectus_only"]
                + fund_summary["still_l3_only"]
                == fund_summary["total_funds"]),
        },
    }


def _counter(seq) -> dict:
    out: dict = {}
    for k in seq:
        out[str(k)] = out.get(str(k), 0) + 1
    return dict(sorted(out.items()))


def main() -> None:
    EVID.mkdir(parents=True, exist_ok=True)
    print("=== 第一部分：10 个指数九维验证 ===")
    idx = audit_indexes()
    for r in idx["indexes"]:
        j = r["return_basis_judgement"]
        num = r["numerical_verification"]
        print(f"  {r['index_code']:8s} basis={j['return_basis']:10s} "
              f"id={r['official_identity_verified']!s:5s} "
              f"basis_ok={r['official_return_basis_verified']!s:5s} "
              f"api={r['api_code_identity_verified']!s:5s} "
              f"db={r['database_series_exists']!s:5s} "
              f"trace={r['database_series_source_traceable']!s:5s} "
              f"num={r['database_series_numerically_verified']!s:5s} "
              f"({num['matched']}/{num['official_obtained']}) "
              f"cov={r['historical_coverage_verified']!s:5s} "
              f"pit={r['point_in_time_verified']!s:5s}")

    print("\n=== 第二部分：78 只基金 L1 合同原件 ===")
    fund = audit_funds()
    ok = sum(1 for r in fund["funds"] if r["contract_found"])
    pro = sum(1 for r in fund["funds"]
              if r["prospectus_found"] and not r["contract_found"])
    print(f"  合同原件 {ok} / 仅招募说明书 {pro} / 未获取 "
          f"{len(fund['funds']) - ok - pro}")

    summary = summarize(idx, fund)
    doc = {
        "phase": "3B-6.2.3.0",
        "task": "官方指数收益口径核验与基金合同原件获取审计",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "baseline_head": "bc490c339f959b6f5262c90290853612329695e3",
        "read_only": True,
        "evidence_grade_definition": {
            "L1": "指数编制机构或官方发布机构原始文件",
            "L2": "权威正式数据库或官方机构转载",
            "L3": "第三方聚合资料",
            "L4": "无法可靠核验的二手资料或推断",
        },
        "sources": {
            "csindex_oss": CSI_OSS,
            "csindex_basic": CSI_BASIC,
            "csindex_perf": OFFICIAL_PERF,
            "cninfo": "巨潮资讯网（中国证监会指定信息披露网站）",
            "cninfo_query": CNINFO_QUERY,
            "official_samples_file": (
                "reports/evidence/phase3B6_2_3_0/"
                "official_close_samples.json"),
            "official_samples_sha256": _official_sample_sha256(),
            "api_samples_file": (
                "reports/evidence/phase3B6_2_3_0/api_identity_samples.json"),
        },
        "verification_dimensions": {
            "official_identity_verified":
                "官方指数代码/正式名称/发布机构已核验（含官方文件）",
            "official_return_basis_verified":
                "官方文件明文确认收益口径",
            "api_code_identity_verified":
                "数据接口返回代码与请求代码一致（仅身份，非数值验证）",
            "api_name_identity_verified":
                "数据接口返回正式名称与官方全称一致（不能只比代码）",
            "database_series_exists":
                "只读查询正式库 index_daily，确认实际历史记录存在",
            "database_series_source_traceable":
                "库内是否具备数据源/批次标识/行级指纹/采集时间",
            "database_series_numerically_verified":
                "逐日比对中证指数官网官方收盘值；取不到记 unknown，不记 false",
            "historical_coverage_verified":
                "是否确认历史覆盖区间、缺失日期与连续性（本阶段未做）",
            "point_in_time_verified":
                "是否确认历史数据在当时真实可取得（本阶段未做）",
        },
        "deprecated_fields": {
            "series_matched": "已废弃 → api_code_identity_verified",
            "data_series_matches_official":
                "已废弃 → 仅代表接口代码匹配，不代表数据库历史序列匹配；"
                "数值验证见 database_series_numerically_verified",
            "series_matches_official":
                "已废弃 → series_matches_official_basis（需数值级验证）",
            "data_series_matches_official_removed_at": "3B-6.2.3.0.1",
        },
        "indexes": idx["indexes"],
    }
    (REPORTS / "phase3B6_2_3_0_index_evidence.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

    fdoc = {
        "phase": "3B-6.2.3.0",
        "task": "78 只基金 L1 合同原件获取审计",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "baseline_head": "bc490c339f959b6f5262c90290853612329695e3",
        "read_only": True,
        "source": "巨潮资讯网（中国证监会指定信息披露网站）",
        "strict_rules": [
            "未真实下载到的文件不得填写 SHA256",
            "无官方来源的文件不得标 L1",
            "不得用当前文件冒充历史版本",
            "无法获取原件时保留 L3，不得升级",
        ],
        "summary": summary,
        "funds": fund["funds"],
    }
    (REPORTS / "phase3B6_2_3_0_fund_contract_audit.json").write_text(
        json.dumps(fdoc, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n=== 覆盖率 ===")
    print(json.dumps(summary["index_summary"], ensure_ascii=False, indent=1))
    print(json.dumps(summary["fund_summary"], ensure_ascii=False, indent=1))
    print(json.dumps(summary["gates"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
