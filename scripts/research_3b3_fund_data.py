"""阶段3B-3 支付宝场外基金数据体系可行性审计（只读研究）。

严格只读：不写项目数据库、不修改 app/backtest / app/validation / app/quant、
不修改公司行为/分红/会计/撮合模块、不写正式 backtest_runs / validation_runs。

本脚本只做三件事：
1. 审计 AKShare 基金数据接口的可用性、覆盖范围与限制；
2. 对 11 只以上样本基金做真实数据验证（净值、分红、A/C 份额、异常值）；
3. 输出机器可读的审计结果，供报告与后续架构设计引用。

不做任何策略开发，不产生任何投资结论。
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import akshare as ak          # noqa: E402
import pandas as pd           # noqa: E402

# ---------------------------------------------------------------- 样本基金
# 覆盖任务的 7 类；A/C 成对选取以验证份额区分。
SAMPLE_FUNDS = [
    # (代码, 分类, 期望名称)
    ("000051", "宽基指数", "华夏沪深300ETF联接A"),
    ("110020", "宽基指数", "易方达沪深300ETF联接A"),
    ("161725", "行业指数", "招商中证白酒指数(LOF)A"),
    ("012414", "行业指数", "招商中证白酒指数(LOF)C"),
    ("007300", "ETF联接", "国联安中证半导体ETF联接A"),
    ("007301", "ETF联接", "国联安中证半导体ETF联接C"),
    ("110022", "主动权益", "易方达消费行业股票"),
    ("161005", "主动权益", "富国天惠成长混合(LOF)A"),
    ("000478", "指数增强", "建信中证500指数增强A"),
    ("000015", "债券", "华夏纯债债券A"),
    ("000016", "债券", "华夏纯债债券C"),
    ("000198", "货币", "天弘余额宝货币"),
]

# A/C 配对：用于验证「同一基金不同份额不等于不同标的」
SHARE_PAIRS = [
    ("161725", "012414", "招商中证白酒指数(LOF)"),
    ("007300", "007301", "国联安中证半导体ETF联接"),
    ("000015", "000016", "华夏纯债债券"),
    ("110022", None, "易方达消费行业（无 C 类在样本内）"),
]


def _retry(fn, *, attempts: int = 3, wait: float = 1.2, label: str = ""):
    """公开接口偶发 SSLError / 连接重置，重试 3 次再放弃。

    网络抖动不等于「数据源不可用」——不重试就把结果写成 failed 会误导审计结论。
    """
    last = None
    for i in range(attempts):
        try:
            return fn(), None
        except Exception as exc:  # noqa: BLE001
            last = exc
            if i + 1 < attempts:
                time.sleep(wait * (i + 1))
    return None, f"{type(last).__name__}: {str(last)[:160]}"


def _pause(sec: float = 0.25) -> None:
    """礼貌间隔，避免对公开接口造成压力。"""
    time.sleep(sec)


def _num(x, nd=6):
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if pd.isna(v):
        return None
    return round(v, nd)


def _fetch_dividends_stable(code: str, attempts: int = 4) -> tuple:
    """分红列表多次抓取并按「除息日+分红额」取并集。

    实测同一代码多次调用可能返回不同条数（如 000016 一次 9 条一次 5 条），
    单纯取「条数最多的一次」仍可能漏记录。正确做法是**按记录内容取并集**，
    用「连续两次并集不再增长」作为停止条件，并记录 stable 标志。
    """
    merged: dict[tuple, dict] = {}
    stable = False
    prev = -1
    last_err = None
    for _ in range(attempts):
        df, err = _retry(
            lambda: ak.fund_open_fund_info_em(
                symbol=code, indicator="分红送配详情"),
            attempts=2, label="dividends")
        if df is None:
            last_err = err
            continue
        for _, r in df.iterrows():
            key = (str(r.get("除息日")), str(r.get("每10份分红")))
            merged[key] = r.to_dict()
        if len(merged) == prev:
            stable = True
            break
        prev = len(merged)
        time.sleep(0.7)
    if not merged and last_err:
        return None, last_err, False
    out = pd.DataFrame(list(merged.values()))
    return out, None, stable


def _parse_cash_per_10(text) -> float | None:
    """从「每10份派现金0.1000元」解析出每份现金分红。

    必须精确锚定「派现金」后面的数字。早期写法用第一个数字匹配，
    会把「每10份」里的 10 当成分红额，导致每份分红恒为 1.0 元——
    这是必须避免的静默错误。
    """
    if text is None:
        return None
    m = re.search(r"派现金\s*([0-9]+(?:\.[0-9]+)?)", str(text))
    if not m:
        return None
    try:
        return round(float(m.group(1)) / 10.0, 8)
    except ValueError:
        return None


# ---------------------------------------------------------------- 数据源审计
def audit_sources() -> dict:
    """逐个探测数据源，记录可用性、覆盖、限制。

    「本次可访问」不等于「长期稳定可用」，每个源都显式标注稳定性判断。
    """
    out = []

    def probe(name, fn, *, note="", stable=None, stability_reason=""):
        entry = {
            "source": name,
            "public": True,
            "auth_required": False,
            "probed_at": datetime.now().isoformat(timespec="seconds"),
            "status": "unknown",
            "rows": None,
            "columns": None,
            "sample": None,
            "error": None,
            "note": note,
            "long_term_stable": stable,
            "stability_reason": stability_reason,
        }
        try:
            df = fn()
            entry["rows"] = int(len(df)) if df is not None else 0
            entry["columns"] = list(df.columns)[:20] if df is not None else []
            if df is not None and len(df):
                entry["sample"] = {
                    str(k): str(v)[:80] for k, v in df.iloc[0].to_dict().items()
                }
            entry["status"] = "ok" if entry["rows"] else "empty"
        except Exception as exc:  # noqa: BLE001 单个源失败不影响整体审计
            entry["status"] = "failed"
            entry["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        out.append(entry)
        _pause()
        return entry

    probe("akshare.fund_name_em 全量基金代码表",
          lambda: ak.fund_name_em(),
          note="东方财富基金代码总表；只含当前清单，不含已清盘",
          stable="中", stability_reason="东财公开 JS，长期存在但无 SLA")

    probe("akshare.fund_open_fund_daily_em 开放式基金当日净值全表",
          lambda: ak.fund_open_fund_daily_em(),
          note="只含最近 2 个交易日，不能替代历史序列",
          stable="中", stability_reason="天天基金行情页结构化数据，字段稳定但只给近两日")

    probe("akshare.fund_purchase_em 申购/赎回状态与限额",
          lambda: ak.fund_purchase_em(),
          note="含申购状态、赎回状态、购买起点、日累计限额、手续费",
          stable="中", stability_reason="天天基金申购状态页，长期存在；状态本身每日变化")

    probe("akshare.fund_manager_em 基金经理任职",
          lambda: ak.fund_manager_em(),
          note="按「经理-基金」展开，无历任起止日期",
          stable="中", stability_reason="东财经理库，结构稳定但字段有限")

    probe("akshare.fund_scale_open_sina 开放式基金规模",
          lambda: ak.fund_scale_open_sina(symbol="股票型基金"),
          note="含总募集规模、最近总份额、成立日期、基金经理",
          stable="中", stability_reason="新浪基金数据中心，长期存在；实测部分标的净值/更新日期为 NaN")

    probe("akshare.fund_scale_close_sina 封闭式基金规模",
          lambda: ak.fund_scale_close_sina(),
          note="封闭式基金，不是「已清盘基金」",
          stable="中", stability_reason="新浪封闭式基金列表；极易被误读为清盘基金")

    probe("akshare.fund_hold_structure_em 持有人结构",
          lambda: ak.fund_hold_structure_em(),
          note="全市场汇总，不是单只基金",
          stable="中", stability_reason="东财季度汇总，低频更新")

    # 单只基金历史净值（关键接口）
    probe("akshare.fund_open_fund_info_em(indicator=单位净值走势)",
          lambda: ak.fund_open_fund_info_em(
              symbol="000051", indicator="单位净值走势"),
          note="单只基金全历史单位净值；是本阶段最关键的历史数据来源",
          stable="高", stability_reason="东财 F10 净值接口，多年稳定；是本阶段核心数据源")

    probe("akshare.fund_open_fund_info_em(indicator=累计净值走势)",
          lambda: ak.fund_open_fund_info_em(
              symbol="000051", indicator="累计净值走势"),
          note="累计净值，与单位净值必须分开使用",
          stable="高", stability_reason="与单位净值同源 F10 接口，稳定性一致")

    probe("akshare.fund_open_fund_info_em(indicator=分红送配详情)",
          lambda: ak.fund_open_fund_info_em(
              symbol="161725", indicator="分红送配详情"),
          note="含权益登记日、除息日、每10份分红、发放日",
          stable="高", stability_reason="同源 F10；但实测存在两次返回条数不一致，需取并集")

    probe("akshare.fund_open_fund_info_em(indicator=拆分详情)",
          lambda: ak.fund_open_fund_info_em(
              symbol="161725", indicator="拆分详情"),
          note="份额折算/拆分记录",
          stable="高", stability_reason="同源 F10，拆分记录完整")

    probe("akshare.fund_money_fund_info_em 货币基金收益序列",
          lambda: ak.fund_money_fund_info_em(symbol="000198"),
          note="货币基金用「每万份收益+7日年化」，没有单位净值",
          stable="高", stability_reason="东财货币基金专用接口；实测偶发 SSLError，需重试")

    probe("akshare.fund_individual_basic_info_xq 基金基本信息",
          lambda: ak.fund_individual_basic_info_xq(symbol="110022"),
          note="含成立时间、规模、公司、经理、类型、业绩比较基准",
          stable="中", stability_reason="雪球接口；实测货币基金返回 KeyError，需兜底")

    probe("akshare.fund_portfolio_hold_em 基金持仓",
          lambda: ak.fund_portfolio_hold_em(symbol="110022", date="2025"),
          note="季度前十大重仓，按年查询",
          stable="中", stability_reason="东财季报持仓，按年查询，滞后于季报披露")

    # 直接探测：已清盘基金能否取到历史净值
    liquidation = []
    for code in ("000581", "519505"):
        try:
            df = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")
            liquidation.append({
                "code": code,
                "type": "货币基金（无单位净值序列）",
                "rows": int(len(df)),
                "error": None,
            })
        except Exception as exc:  # noqa: BLE001
            liquidation.append({
                "code": code,
                "rows": None,
                "error": f"{type(exc).__name__}: {str(exc)[:120]}",
            })
        _pause()

    return {
        "probes": out,
        "money_fund_special_case": liquidation,
        "summary": {
            "total": len(out),
            "ok": sum(1 for x in out if x["status"] == "ok"),
            "empty": sum(1 for x in out if x["status"] == "empty"),
            "failed": sum(1 for x in out if x["status"] == "failed"),
        },
    }


# ---------------------------------------------------------------- 幸存者偏差
def audit_survivorship() -> dict:
    """调查能否获取已清盘/已合并基金。

    结论必须诚实：只拿当前存续基金回测历史 = 幸存者偏差未解决。
    """
    nm = ak.fund_name_em()
    all_codes = set(nm["基金代码"].astype(str))
    _pause()

    purchase = ak.fund_purchase_em()
    purch_codes = set(purchase["基金代码"].astype(str))
    _pause()

    # 名称里带「清算/终止/清盘」的，是名字巧合，不是清盘状态
    name_hits = nm[nm["基金简称"].str.contains("清盘|终止|清算", na=False)]

    # 申购状态里是否有「已终止/清盘」这类取值
    status_values = sorted(
        {str(x) for x in purchase["申购状态"].dropna().unique()})

    return {
        "fund_name_em_total": len(all_codes),
        "fund_purchase_em_total": len(purch_codes),
        "purchase_status_values": status_values,
        "has_liquidated_status": any(
            k in v for v in status_values for k in ("终止", "清盘", "清算")),
        "name_keyword_hits": int(len(name_hits)),
        "name_keyword_sample": name_hits.head(5)[["基金代码", "基金简称"]]
        .to_dict("records") if len(name_hits) else [],
        "liquidated_fund_source_available": False,
        "conclusion": "survivorship_bias_unresolved",
        "reason": (
            "AKShare 提供的 fund_name_em / fund_open_fund_daily_em / "
            "fund_purchase_em 都只覆盖「当前清单」，没有任何接口返回"
            "已清盘、已合并或已终止运作的基金名录。"
            "fund_scale_close_sina 是「封闭式基金」而非「已清盘基金」，"
            "容易被误读，必须在架构里显式区分。"
        ),
        "mitigation": [
            "短期：明确标注 survivorship_bias_unresolved，"
            "所有历史回测结论必须附带该限制。",
            "中期：从基金业协会 / 证监会公告 / 天天基金清盘公告页"
            "自行构建 fund_lifecycle_events 表，按公告逐条补录。",
            "长期：建立「历史基金全量快照」机制，"
            "每期抓取全量清单留档，用快照差异反推清盘时点。",
        ],
    }


# ---------------------------------------------------------------- 样本验证
def _basic_info_fallback(code: str, category: str, exc) -> dict:
    """雪球接口失败时的兜底：用 fund_name_em + 新浪规模拼基本信息。

    明确记录来源不同，不冒充与雪球接口等价。
    """
    info = {
        "name": None, "full_name": None, "established": None, "scale": None,
        "company": None, "manager": None, "type": None, "benchmark": None,
        "custodian": None,
    }
    errs = []
    try:
        nm = ak.fund_name_em()
        row = nm[nm["基金代码"] == code]
        if len(row):
            info["name"] = str(row.iloc[0]["基金简称"])
            info["type"] = str(row.iloc[0]["基金类型"])
        else:
            errs.append("fund_name_em 无此代码")
    except Exception as e:  # noqa: BLE001
        errs.append(f"fund_name_em: {type(e).__name__}")
    try:
        sina = ak.fund_scale_open_sina(symbol="货币型基金")
        row = sina[sina["基金代码"] == code]
        if len(row):
            info["established"] = str(row.iloc[0]["成立日期"])
            info["manager"] = str(row.iloc[0]["基金经理"])
            info["scale"] = str(row.iloc[0]["最近总份额"])
    except Exception as e:  # noqa: BLE001
        errs.append(f"fund_scale_open_sina: {type(e).__name__}")
    ok = bool(info["name"])
    return {
        "ok": ok,
        "info": info,
        "source": "fund_name_em + fund_scale_open_sina（非雪球）",
        "error": "; ".join(errs) if errs else None,
    }


def verify_fund(code: str, category: str, expected_name: str) -> dict:
    """对单只基金做真实数据验证。"""
    out = {
        "code": code,
        "category": category,
        "expected_name": expected_name,
        "name_matched": None,
        "unit_nav": None,
        "acc_nav": None,
        "dividends": None,
        "splits": None,
        "basic_info": None,
        "anomalies": [],
        "status": "unknown",
    }

    # 1) 基本信息
    # 雪球接口对货币基金返回 KeyError('data')，这类标的改由
    # fund_name_em（名称/类型）+ fund_scale_open_sina（成立日/规模/经理）拼装，
    # 不阻断验证，但必须记录「来源不同」这一事实。
    try:
        if category == "货币":
            raise KeyError("雪球接口不支持货币基金，改用 fund_name_em + sina")
        info = ak.fund_individual_basic_info_xq(symbol=code)
        kv = {str(r["item"]): str(r["value"]) for _, r in info.iterrows()}
        if not kv:
            raise KeyError("基本信息为空")
        actual = kv.get("基金名称") or ""
        out["basic_info"] = {
            "name": actual,
            "full_name": kv.get("基金全称"),
            "established": kv.get("成立时间"),
            "scale": kv.get("最新规模"),
            "company": kv.get("基金公司"),
            "manager": kv.get("基金经理"),
            "type": kv.get("基金类型"),
            "benchmark": kv.get("业绩比较基准"),
            "custodian": kv.get("托管银行"),
        }
        # 名称匹配用「去噪后双向包含」：
        # 接口名常省略「中证/ETF」等词，也常在括号全半角上不一致。
        # 严格相等会把同一只基金误判成不匹配。
        def _norm(x: str) -> str:
            return (x.replace("（", "(").replace("）", ")")
                     .replace("(LOF)", "").replace("LOF", "")
                     .replace("中证", "").replace("ETF", "").replace(" ", ""))

        na, ne = _norm(actual), _norm(expected_name)
        out["name_matched"] = bool(na and (na in ne or ne in na))
        out["name_match_basis"] = "去噪后双向包含（忽略中证/ETF/全半角括号）"
        out["name_actual"] = actual
    except Exception as exc:  # noqa: BLE001
        fallback = _basic_info_fallback(code, category, exc)
        if fallback["ok"]:
            out["basic_info"] = fallback["info"]
            out["name_actual"] = fallback["info"].get("name")
            fn = fallback["info"].get("name") or ""
            out["name_matched"] = bool(fn and (fn in expected_name or
                                               expected_name in fn))
            out["basic_info_source"] = fallback["source"]
        else:
            out["anomalies"].append(
                f"基本信息获取失败: {type(exc).__name__}；兜底也失败: "
                f"{fallback['error']}")
    _pause()

    # 2) 单位净值 / 累计净值（货币基金走单独接口）
    if category == "货币":
        try:
            m, m_err = _retry(
                lambda: ak.fund_money_fund_info_em(symbol=code), label="money")
            if m is None:
                raise RuntimeError(m_err)
            m = m.dropna(subset=["每万份收益"])
            out["unit_nav"] = {
                "type": "money_fund_yield",
                "rows": int(len(m)),
                "first_date": str(m.iloc[0]["净值日期"]),
                "last_date": str(m.iloc[-1]["净值日期"]),
                "note": "货币基金无单位净值，用每万份收益与 7 日年化",
                "latest_7d_annual": _num(m.iloc[-1]["7日年化收益率"], 4),
            }
        except Exception as exc:  # noqa: BLE001
            out["anomalies"].append(f"货币收益序列失败: {type(exc).__name__}")
        _pause()
    else:
        try:
            nav, nav_err = _retry(
                lambda: ak.fund_open_fund_info_em(
                    symbol=code, indicator="单位净值走势"),
                label="unit_nav")
            if nav is None:
                raise RuntimeError(nav_err)
            nav = nav.dropna(subset=["单位净值"])
            # 必须把日期设为索引：否则 pct_change() 的 index 是 RangeIndex，
            # 后面拿它当日期用会得到 '570' 这种假日期。
            nav = nav.set_index("净值日期").sort_index()
            values = pd.to_numeric(nav["单位净值"], errors="coerce").dropna()
            out["unit_nav"] = {
                "rows": int(len(nav)),
                # set_index 之后「净值日期」列已不存在，日期要从索引取
                "first_date": str(nav.index[0]),
                "last_date": str(nav.index[-1]),
                "first_value": _num(values.iloc[0], 4),
                "last_value": _num(values.iloc[-1], 4),
                "min": _num(values.min(), 4),
                "max": _num(values.max(), 4),
                "non_positive_count": int((values <= 0).sum()),
            }
            # 连续性检查：相邻净值变动 > 20% 视为可疑（可能是拆分未处理）
            # 大幅跳变必须与拆分/折算记录对齐后再定性：
            # 有对应拆分记录的跳变是「正常折算」，没有才是「异常」。
            pct = values.pct_change().dropna()
            big = pct[abs(pct) > 0.20]
            out["nav_jumps"] = {
                "count": int(len(big)),
                "max_abs_pct": _num(float(big.abs().max()) * 100, 2) if len(big) else None,
                "dates": [str(x) for x in big.index[:10].tolist()] if len(big) else [],
            }
            # big.index 已经是日期，直接用它；早期写成 values.index[big.index]
            # 会把日期当整数位置索引，得到 '277' 这种假日期。
            out["nav_jump_dates"] = [str(d) for d in big.index] if len(big) else []
            # 同时记录跳变发生日与前一日的净值，便于人工复核是分红还是拆分
            out["nav_jump_detail"] = [
                {
                    "date": str(d),
                    "prev_nav": _num(values.shift(1).loc[d], 4),
                    "this_nav": _num(values.loc[d], 4),
                    "pct": _num(float(pct.loc[d]), 6),
                }
                for d in big.index[:10]
            ]
        except Exception as exc:  # noqa: BLE001
            out["anomalies"].append(f"单位净值失败: {type(exc).__name__}")
        _pause()

        try:
            acc, acc_err = _retry(
                lambda: ak.fund_open_fund_info_em(
                    symbol=code, indicator="累计净值走势"),
                label="acc_nav")
            if acc is None:
                raise RuntimeError(acc_err)
            acc = acc.dropna(subset=["累计净值"])
            acc = acc.set_index("净值日期").sort_index()
            out["acc_nav"] = {
                "rows": int(len(acc)),
                "first_date": str(acc.index[0]),
                "last_date": str(acc.index[-1]),
                "first_value": _num(acc["累计净值"].iloc[0], 4),
                "last_value": _num(acc["累计净值"].iloc[-1], 4),
            }
        except Exception as exc:  # noqa: BLE001
            out["anomalies"].append(f"累计净值失败: {type(exc).__name__}")
        _pause()

        # 3) 分红
        try:
            div, div_err, div_stable = _fetch_dividends_stable(code)
            if div is None:
                raise RuntimeError(div_err)
            rows = []
            for _, r in div.iterrows():
                rows.append({
                    "record_date": str(r.get("权益登记日")),
                    "ex_date": str(r.get("除息日")),
                    "pay_date": str(r.get("分红发放日")),
                    "cash_per_share": _parse_cash_per_10(r.get("每10份分红")),
                    "raw": str(r.get("每10份分红")),
                })
            out["dividends"] = {
                "count": len(rows),
                "rows": rows[:30],
                "fetch_stable": div_stable,
                "note": ("两次抓取条数一致" if div_stable
                         else "两次抓取条数不一致，已取并集；接口可能返回不完整列表"),
            }
            if not div_stable:
                out.setdefault("notes", []).append(
                    "分红接口两次返回条数不一致，已取并集，需人工复核")
        except Exception as exc:  # noqa: BLE001
            out["anomalies"].append(f"分红数据失败: {type(exc).__name__}")
        _pause()

        # 4) 拆分
        try:
            sp, sp_err = _retry(
                lambda: ak.fund_open_fund_info_em(
                    symbol=code, indicator="拆分详情"),
                label="splits")
            if sp is None:
                raise RuntimeError(sp_err)
            out["splits"] = {
                "count": int(len(sp)),
                "rows": sp.head(20).to_dict("records") if len(sp) else [],
            }
        except Exception as exc:  # noqa: BLE001
            out["anomalies"].append(f"拆分数据失败: {type(exc).__name__}")
        _pause()

        # 5) 跳变归因：拆分 / 分红 都能解释的是「正常事件」，都对不上才是「异常」
        jumps = out.get("nav_jump_dates") or []
        split_dates = {str(r.get("拆分折算日")) for r in
                       (out["splits"]["rows"] if out.get("splits") else [])}
        div_dates = {str(r.get("ex_date")) for r in
                     ((out.get("dividends") or {}).get("rows") or [])}
        by_split = [d for d in jumps if d in split_dates]
        by_div = [d for d in jumps if d in div_dates and d not in split_dates]
        unexplained = [d for d in jumps
                       if d not in split_dates and d not in div_dates]
        if jumps:
            out["nav_jump_attribution"] = {
                "total": len(jumps),
                "explained_by_splits": len(by_split),
                "explained_by_dividends": len(by_div),
                "unexplained": len(unexplained),
                "unexplained_dates": unexplained[:10],
                "note": (
                    "除息日单位净值会因分红下跌，属于正常事件；"
                    "拆分/折算日净值跳变也正常。只有两类记录都对不上的跳变才算数据异常。"),
            }
            out.setdefault("notes", [])
            if by_split:
                out["notes"].append(f"{len(by_split)} 次跳变由份额折算/拆分解释")
            if by_div:
                out["notes"].append(f"{len(by_div)} 次跳变由现金分红除息解释")
            if unexplained:
                out["anomalies"].append(
                    f"{len(unexplained)} 次日变动超 ±20% 无拆分也无分红记录解释："
                    f"{unexplained[:3]}")

    # 5) 单位净值 vs 累计净值 的关系自检
    if out.get("unit_nav") and out.get("acc_nav") and category != "货币":
        u = out["unit_nav"]["last_value"]
        a = out["acc_nav"]["last_value"]
        if u is not None and a is not None:
            if a + 1e-9 < u:
                out["anomalies"].append(
                    f"累计净值({a}) 小于单位净值({u})，口径或数据异常")
            out["unit_vs_acc"] = {
                "unit_last": u, "acc_last": a,
                "diff": _num(a - u, 4),
                "interpretation": (
                    "差额即历史累计现金分红（未含拆分）" if a > u else "无分红或口径一致"),
            }

    if not out.get("unit_nav"):
        out["status"] = "failed"
    elif out["anomalies"]:
        out["status"] = "ok_with_anomalies"
    else:
        out["status"] = "ok"
    return out


def audit_share_classes() -> dict:
    """验证 A/C 份额：同基金不同份额不是不同标的。"""
    nm = ak.fund_name_em()
    pairs = []
    for a, c, base in SHARE_PAIRS:
        def pick(code):
            if code is None:
                return None
            row = nm[nm["基金代码"] == code]
            return row.iloc[0]["基金简称"] if len(row) else None
        pairs.append({
            "base_name": base,
            "a_code": a, "a_name": pick(a),
            "c_code": c, "c_name": pick(c),
            "note": "同一基金本体的不同份额类别，不得计为两个投资标的",
        })

    # 统计名称里带 A/C 后缀的份额
    suffix_a = int(nm["基金简称"].str.endswith("A", na=False).sum())
    suffix_c = int(nm["基金简称"].str.endswith("C", na=False).sum())
    return {
        "pairs": pairs,
        "suffix_a_count": suffix_a,
        "suffix_c_count": suffix_c,
        "total_funds": int(len(nm)),
        "conclusion": (
            "A/C 在 fund_name_em 里是**独立代码、独立名称后缀**，"
            "但同属一个基金本体。架构必须拆成 fund_master（本体）"
            "与 fund_share_classes（份额）两级，否则基金会重复计数。"),
    }


def audit_fee_and_status(sample_codes: list[str]) -> dict:
    """审计申购/赎回状态与费率可得性。"""
    purchase = ak.fund_purchase_em()
    _pause()
    sub = purchase[purchase["基金代码"].isin(sample_codes)]
    rows = []
    for _, r in sub.iterrows():
        rows.append({
            "code": str(r["基金代码"]),
            "name": str(r["基金简称"]),
            "purchase_status": str(r["申购状态"]),
            "redeem_status": str(r["赎回状态"]),
            "min_purchase": _num(r["购买起点"], 2),
            "daily_limit": _num(r["日累计限定金额"], 2),
            "fee_pct": _num(r["手续费"], 4),
        })
    return {
        "sample_rows": rows,
        "status_values": sorted(
            {str(x) for x in purchase["申购状态"].dropna().unique()}),
        "fee_field": "手续费（百分数，来自天天基金列表页，非合同费率）",
        "has_redemption_fee_field": False,
        "has_holding_period_rule": False,
        "limitation": (
            "接口只给「申购手续费」一个数，没有赎回费阶梯、"
            "没有持有期限规则、没有 A/C 费率差异的结构化数据。"
            "这些必须从基金合同/招募说明书人工核实或另建数据源。"),
    }


def audit_trading_rules() -> dict:
    """场外基金交易规则：区分「可证实 / 可获取 / 需人工核实 / 无法确认」。"""
    rules = [
        {
            "id": "T1",
            "rule": "15:00 申购赎回截止时间",
            "detail": "T 日 15:00 前提交按 T 日净值成交，之后按 T+1 日净值",
            "evidence_level": "行业通则，基金合同普遍载明",
            "data_source_available": False,
            "needs_manual_verification": True,
            "note": "AKShare 无此字段；属交易规则而非数据字段",
        },
        {
            "id": "T2",
            "rule": "不同提交时间对应的净值日期",
            "detail": "15:00 前后分属不同净值日；节假日顺延",
            "evidence_level": "行业通则",
            "data_source_available": False,
            "needs_manual_verification": True,
            "note": "需按基金合同 + 交易所日历联合判定",
        },
        {
            "id": "T3",
            "rule": "申购确认时间",
            "detail": "通常 T+1 确认份额，QDII 为 T+2",
            "evidence_level": "行业通则，个别基金不同",
            "data_source_available": False,
            "needs_manual_verification": True,
            "note": "不能对所有基金统一假设 T+1",
        },
        {
            "id": "T4",
            "rule": "赎回确认与到账时间",
            "detail": "股票型通常 T+1 确认、T+3~T+7 到账；货币基金 T+1",
            "evidence_level": "行业通则，各基金差异大",
            "data_source_available": False,
            "needs_manual_verification": True,
            "note": "到账时间受销售渠道影响，支付宝与直销可能不同",
        },
        {
            "id": "T5",
            "rule": "申购费及平台折扣",
            "detail": "合同费率 1.5% 左右，第三方平台常打 1 折",
            "evidence_level": "合同费率可查；平台折扣是动态的",
            "data_source_available": True,
            "needs_manual_verification": True,
            "note": "fund_purchase_em 的「手续费」是列表页展示值，"
                    "不等于合同费率，也不保证与支付宝一致",
        },
        {
            "id": "T6",
            "rule": "按持有期限变化的赎回费",
            "detail": "常见 <7天 1.5%、7天~1年 0.5%、1~2年 0.25%、>2年 0",
            "evidence_level": "合同可证实，各基金不同",
            "data_source_available": False,
            "needs_manual_verification": True,
            "note": "**AKShare 完全没有赎回费阶梯字段**，必须人工或另建数据源",
        },
        {
            "id": "T7",
            "rule": "A类与C类份额费用差异",
            "detail": "A 类收申购费、不收销售服务费；C 类免申购费、按年收销售服务费",
            "evidence_level": "合同可证实",
            "data_source_available": False,
            "needs_manual_verification": True,
            "note": "接口只能看到 A/C 申购手续费不同（C 常为 0），"
                    "销售服务费没有字段",
        },
        {
            "id": "T8",
            "rule": "暂停申购、限购、巨额赎回",
            "detail": "暂停申购/限大额可由接口获取；巨额赎回是事件性的",
            "evidence_level": "部分可获取",
            "data_source_available": True,
            "needs_manual_verification": True,
            "note": "状态是**当日快照**，没有历史状态序列；"
                    "巨额赎回无接口",
        },
        {
            "id": "T9",
            "rule": "基金转换规则",
            "detail": "同公司基金间可转换，费率与限制各家不同",
            "evidence_level": "合同可证实",
            "data_source_available": False,
            "needs_manual_verification": True,
            "note": "**完全没有接口**，且支付宝是否支持转换属平台功能，"
                    "无可靠证据时必须标 unknown",
        },
        {
            "id": "T10",
            "rule": "支付宝可购买状态",
            "detail": "平台代销名单是动态信息",
            "evidence_level": "无法证实",
            "data_source_available": False,
            "needs_manual_verification": True,
            "note": "**unknown**。没有可靠证据，不得声称某基金一定能在支付宝买到",
        },
    ]
    return {
        "rules": rules,
        "summary": {
            "total": len(rules),
            "data_source_available": sum(1 for r in rules if r["data_source_available"]),
            "needs_manual_verification": sum(
                1 for r in rules if r["needs_manual_verification"]),
            "fully_unknown": sum(
                1 for r in rules if r["evidence_level"] == "无法证实"),
        },
    }


# ---------------------------------------------------------------- 架构设计
def design_schema() -> dict:
    """场外基金独立数据模型设计。只输出设计，不执行迁移。"""
    tables = [
        {
            "table": "fund_master",
            "purpose": "基金本体（一只基金一行，A/C 份额共用）",
            "key": "fund_id (surrogate) + fund_code_primary",
            "columns": [
                "fund_id", "fund_code_primary", "fund_name", "fund_full_name",
                "fund_company", "custodian", "fund_type_l1", "fund_type_l2",
                "invest_scope", "benchmark", "established_date", "terminated_date",
                "lifecycle_status", "is_index_fund", "tracking_index",
                "source", "source_updated_at", "data_version",
            ],
            "note": "terminated_date 是清盘日的落点；当前数据源拿不到，必须先留字段",
        },
        {
            "table": "fund_share_classes",
            "purpose": "份额类别（A/C/E/I 等），一个基金本体多行",
            "key": "share_class_id + (fund_id, share_class_code) UNIQUE",
            "columns": [
                "share_class_id", "fund_id", "share_class_code", "share_class_name",
                "share_class_type", "currency", "is_primary",
                "management_fee", "custody_fee", "sales_service_fee",
                "min_purchase", "min_holding", "listed_date", "terminated_date",
                "source", "source_updated_at",
            ],
            "note": "**A/C 在这里区分，不在 fund_master 里**，避免基金数量重复计数",
        },
        {
            "table": "fund_nav_daily",
            "purpose": "每日净值（单位净值 + 累计净值，分开存）",
            "key": "(share_class_id, nav_date) PK",
            "columns": [
                "share_class_id", "nav_date", "unit_nav", "acc_nav",
                "daily_return", "nav_status", "source", "ingested_at",
            ],
            "note": "**单位净值与累计净值必须是两列**，混用是本项目已知的历史错误来源",
        },
        {
            "table": "fund_dividends",
            "purpose": "分红记录",
            "key": "(share_class_id, ex_date) PK",
            "columns": [
                "share_class_id", "record_date", "ex_date", "pay_date",
                "cash_per_share", "dividend_type", "reinvest_nav",
                "source", "ingested_at",
            ],
            "note": "每10份分红必须归一化为每份，否则与净值口径差 10 倍",
        },
        {
            "table": "fund_manager_history",
            "purpose": "基金经理任职历史",
            "key": "(fund_id, manager_name, start_date)",
            "columns": [
                "fund_id", "manager_name", "company", "start_date", "end_date",
                "tenure_days", "source", "ingested_at",
            ],
            "note": "**当前接口只给现任经理，没有起止日期**，start_date 需人工/公告补录",
        },
        {
            "table": "fund_aum_history",
            "purpose": "规模历史",
            "key": "(share_class_id 或 fund_id, report_date)",
            "columns": [
                "fund_id", "share_class_id", "report_date", "aum_total",
                "shares_total", "aum_unit", "source", "ingested_at",
            ],
            "note": "接口只给「最新规模」，历史规模要按季报补",
        },
        {
            "table": "fund_fee_rules",
            "purpose": "费率规则（申购/赎回/销售服务）",
            "key": "(share_class_id, fee_type, tier_order)",
            "columns": [
                "share_class_id", "fee_type", "tier_order", "lower_bound",
                "upper_bound", "rate", "holding_days_min", "holding_days_max",
                "effective_from", "effective_to", "source", "evidence_level",
            ],
            "note": "**赎回费阶梯必须有**，当前数据源完全没有",
        },
        {
            "table": "fund_subscription_status",
            "purpose": "申购/赎回状态快照",
            "key": "(share_class_id, as_of_date)",
            "columns": [
                "share_class_id", "as_of_date", "purchase_status",
                "redeem_status", "daily_limit", "min_purchase",
                "next_open_date", "source", "ingested_at",
            ],
            "note": "必须**按日留快照**才有历史，单次抓取只是当日状态",
        },
        {
            "table": "fund_lifecycle_events",
            "purpose": "生命周期事件（成立/清盘/合并/份额变更）",
            "key": "event_id + (fund_id, event_date, event_type)",
            "columns": [
                "event_id", "fund_id", "event_type", "event_date",
                "announcement_date", "announcement_url", "detail",
                "successor_fund_id", "evidence_level", "source", "ingested_at",
            ],
            "note": "**清盘/合并就落这张表**；当前无数据源，是架构的第一优先补齐项",
        },
        {
            "table": "fund_data_quality",
            "purpose": "数据质量状态",
            "key": "(table_name, record_key, check_name)",
            "columns": [
                "table_name", "record_key", "check_name", "status",
                "detail", "checked_at", "severity",
            ],
            "note": "沿用项目已有 data_quality 思路，独立于 ETF 侧",
        },
    ]
    return {
        "tables": tables,
        "table_count": len(tables),
        "principles": [
            "基金本体与份额分两级，A/C 不重复计数",
            "单位净值与累计净值分列，禁止混用",
            "所有表保留 source / ingested_at / data_version",
            "生命周期事件单独建表，清盘与合并有落点",
            "申购状态按日快照，才有历史可回溯",
            "费率按阶梯存，赎回费必须有 holding_days 区间",
        ],
        "not_migrated": True,
        "migration_note": "本阶段只输出设计，**未执行任何数据库迁移**",
    }


def design_reuse() -> dict:
    """现有模块复用分析。"""
    reuse = [
        {"module": "指标计算（MA/RSI/MACD/波动率）", "decision": "可复用",
         "note": "算法本身与标的是场内还是场外无关；需要新的数据适配层喂入"},
        {"module": "风险指标（Sharpe/Sortino/Calmar/最大回撤）", "decision": "可复用",
         "note": "基于净值序列，场外基金同样适用"},
        {"module": "组合分析（权重、再平衡、归因）", "decision": "可复用",
         "note": "逻辑层与执行层解耦后可复用"},
        {"module": "报告生成", "decision": "可复用",
         "note": "仅需替换数据来源与字段名"},
        {"module": "数据质量检查框架", "decision": "可复用",
         "note": "检查规则需新增场外基金特有项（如净值停更、份额拆分）"},
        {"module": "研究框架（脚本 + JSON + 报告 + 测试）", "decision": "可复用",
         "note": "3B-1/3B-2/3B-3 已形成稳定范式"},
    ]
    rebuild = [
        {"module": "场外基金净值数据层", "reason": "标的、频率、字段全部不同"},
        {"module": "申购赎回执行模型", "reason": "T+1 确认、15:00 截止、按净值成交，"
                                                "与场内撮合完全不同"},
        {"module": "基金费率模型", "reason": "申购费/赎回费阶梯/销售服务费，场内没有"},
        {"module": "基金经理与份额管理", "reason": "场内 ETF 没有这个概念"},
        {"module": "场外基金回测适配层", "reason": "把现有引擎的撮合换成绩效确认模型"},
    ]
    return {
        "reusable": reuse,
        "to_build": rebuild,
        "hard_boundary": (
            "**不把场内 ETF 回测引擎改造成场外基金引擎。** "
            "两者交易模型差异是结构性的（撮合 vs 确认、日内 vs T+1、"
            "价格 vs 净值），改造成本高于重建。"),
    }


# ---------------------------------------------------------------- 主流程
def main(out_dir: Path) -> dict:
    print("审计数据源...", flush=True)
    sources = audit_sources()

    print("审计幸存者偏差...", flush=True)
    survivorship = audit_survivorship()

    print("审计 A/C 份额...", flush=True)
    share = audit_share_classes()

    print(f"验证 {len(SAMPLE_FUNDS)} 只样本基金...", flush=True)
    funds = []
    for code, cat, name in SAMPLE_FUNDS:
        print(f"  {code} {cat}...", flush=True)
        funds.append(verify_fund(code, cat, name))

    codes = [f[0] for f in SAMPLE_FUNDS]
    print("审计费率与状态...", flush=True)
    fees = audit_fee_and_status(codes)

    print("审计交易规则...", flush=True)
    trading = audit_trading_rules()

    print("生成架构设计...", flush=True)
    schema = design_schema()
    reuse = design_reuse()

    ok_funds = [f for f in funds if f["status"].startswith("ok")]
    summary = {
        "sample_target": len(SAMPLE_FUNDS),
        "sample_verified": len(ok_funds),
        "sample_failed": len(funds) - len(ok_funds),
        "with_anomalies": sum(1 for f in funds if f["anomalies"]),
        "categories_covered": sorted({f["category"] for f in funds}),
        "with_dividends": sum(1 for f in funds
                              if (f.get("dividends") or {}).get("count")),
        "with_splits": sum(1 for f in funds
                           if (f.get("splits") or {}).get("count")),
    }

    payload = {
        "phase": "3B-3",
        "baseline_head": "e14a8fa6e5a3294ce00d2c2168756130fa4dee32",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "akshare_version": ak.__version__,
        "scope": (
            "只做数据源审计、覆盖验证与架构设计；"
            "不开发策略、不改回测引擎、不写正式库"),
        "sources": sources,
        "survivorship": survivorship,
        "share_classes": share,
        "sample_funds": funds,
        "fees_and_status": fees,
        "trading_rules": trading,
        "schema": schema,
        "reuse": reuse,
        "summary": summary,
        "unresolved": [
            "survivorship_bias_unresolved：无已清盘基金名录",
            "清盘/合并基金的净值历史无法系统性获取",
            "赎回费阶梯、销售服务费、持有期限规则无结构化数据源",
            "基金转换规则完全无接口",
            "支付宝可购买状态 = unknown，无可信证据",
            "基金成立日期在部分接口缺失或不一致",
            "基金经理历任起止日期需从公告补录",
        ],
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    jp = out_dir / "phase3B3_fund_data_feasibility.json"
    jp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"JSON -> {jp}", flush=True)
    return payload


if __name__ == "__main__":
    main(ROOT / "reports")
