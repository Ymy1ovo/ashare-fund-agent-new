"""子进程内的数据源任务分发。

该模块只能放可被 spawn 导入的顶层函数，不能把 requests.Session、
AKShare 客户端对象等不可序列化对象跨进程传递。
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import requests

from app.data.processors.fund_profile import parse_fund_profile

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://fundf10.eastmoney.com/",
}


def run_akshare_job(job: str, params: dict[str, Any]) -> Any:
    """在子进程中执行一个受控的数据源任务。"""
    if job == "fund_profile":
        code = str(params["code"])
        timeout = float(params.get("timeout_seconds", 20))
        response = requests.get(
            f"https://fundf10.eastmoney.com/jbgk_{code}.html",
            headers=_HEADERS,
            timeout=timeout,
        )
        response.raise_for_status()
        response.encoding = "utf-8"
        return parse_fund_profile(response.text, code)

    import akshare as ak

    if job == "etf_spot":
        return ak.fund_etf_spot_em()
    if job == "etf_history":
        return ak.fund_etf_hist_em(
            symbol=str(params["symbol"]),
            period=str(params.get("period", "daily")),
            start_date=str(params.get("start_date", "20000101")),
            end_date=str(params["end_date"]),
            adjust=str(params.get("adjust", "")),
        )
    if job == "index_history":
        return ak.index_zh_a_hist(
            symbol=str(params["symbol"]),
            period=str(params.get("period", "daily")),
            start_date=str(params.get("start_date", "20000101")),
            end_date=str(params["end_date"]),
        )
    if job == "index_fund_info":
        return ak.fund_info_index_em(
            symbol=str(params.get("symbol", "沪深指数")),
            indicator=str(params.get("indicator", "被动指数型")),
        )
    if job == "open_fund_nav":
        return ak.fund_open_fund_info_em(
            symbol=str(params["symbol"]),
            indicator=str(params.get("indicator", "单位净值走势")),
        )
    if job == "fund_name_list":
        return ak.fund_name_em()
    if job == "exchange_fund_rank":
        return ak.fund_exchange_rank_em()
    if job == "trade_calendar":
        return ak.tool_trade_date_hist_sina()
    raise ValueError(f"未知数据源任务：{job}")


def run_dataframe_job(job: str, params: dict[str, Any]) -> pd.DataFrame:
    """测试/兼容用包装：断言任务返回 DataFrame。"""
    result = run_akshare_job(job, params)
    if not isinstance(result, pd.DataFrame):
        raise TypeError(f"{job} 返回类型不是 DataFrame：{type(result).__name__}")
    return result
