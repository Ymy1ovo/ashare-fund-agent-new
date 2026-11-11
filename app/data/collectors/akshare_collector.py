"""AKShare 数据采集封装。

所有网络调用交给 `worker.run_akshare_job` 在独立子进程中执行，
父进程只负责参数、超时、重试与类型检查。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import pandas as pd

from app.data.collectors.base import DataFetchError, fetch_with_retry
from app.data.collectors.worker import run_akshare_job
from app.data.processors.fund_profile import parse_fund_profile

logger = logging.getLogger(__name__)


class AkshareCollector:
    """AKShare 与东方财富基金档案的数据采集器。"""

    def __init__(self, timeout_seconds: int = 60, max_retries: int = 2) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    def _run(
        self,
        job: str,
        params: dict[str, Any],
        *,
        description: str,
        expect_dataframe: bool = True,
    ) -> Any:
        result = fetch_with_retry(
            run_akshare_job,
            job,
            params,
            description=description,
            timeout_seconds=self.timeout_seconds,
            max_retries=self.max_retries,
        )
        if expect_dataframe and not isinstance(result, pd.DataFrame):
            raise DataFetchError(f"{description} 返回类型异常：{type(result).__name__}")
        return result

    def fetch_etf_spot(self) -> pd.DataFrame:
        """ETF 实时行情列表（含代码、名称、最新价、数据日期）。"""
        return self._run("etf_spot", {}, description="fund_etf_spot_em")

    def fetch_etf_history(
        self,
        symbol: str,
        start_date: str = "20000101",
        end_date: str | None = None,
        adjust: str = "",
    ) -> pd.DataFrame:
        """ETF 历史日线；adjust 可为空、qfq（前复权）或 hfq（后复权）。"""
        end = end_date or datetime.now().strftime("%Y%m%d")
        return self._run(
            "etf_history",
            {
                "symbol": symbol,
                "period": "daily",
                "start_date": start_date,
                "end_date": end,
                "adjust": adjust,
            },
            description=f"fund_etf_hist_em({symbol},adjust={adjust or 'raw'})",
        )

    def fetch_index_history(
        self,
        symbol: str,
        start_date: str = "20000101",
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """A 股指数历史日线。"""
        end = end_date or datetime.now().strftime("%Y%m%d")
        return self._run(
            "index_history",
            {
                "symbol": symbol,
                "period": "daily",
                "start_date": start_date,
                "end_date": end,
            },
            description=f"index_zh_a_hist({symbol})",
        )

    def fetch_index_fund_info(self, symbol: str = "沪深指数", indicator: str = "被动指数型") -> pd.DataFrame:
        """场外指数基金基础信息（含跟踪标的、净值、费率）。"""
        return self._run(
            "index_fund_info",
            {"symbol": symbol, "indicator": indicator},
            description="fund_info_index_em",
        )

    def fetch_open_fund_nav(self, symbol: str) -> pd.DataFrame:
        """场外基金历史单位净值。"""
        return self._run(
            "open_fund_nav",
            {"symbol": symbol, "indicator": "单位净值走势"},
            description=f"fund_open_fund_info_em({symbol})",
        )

    def fetch_fund_name_list(self) -> pd.DataFrame:
        """全市场基金基本信息，用于基金类型校验。"""
        return self._run("fund_name_list", {}, description="fund_name_em")

    def fetch_exchange_fund_rank(self) -> pd.DataFrame:
        """场内基金排行，含成立日期。"""
        return self._run("exchange_fund_rank", {}, description="fund_exchange_rank_em")

    def fetch_trade_calendar(self) -> pd.DataFrame:
        """A股历史交易日历。"""
        return self._run("trade_calendar", {}, description="tool_trade_date_hist_sina")

    def fetch_fund_profile(self, code: str) -> dict[str, Any]:
        """读取东方财富基金档案 F10 的跟踪标的与成立日期。"""
        result = self._run(
            "fund_profile",
            {"code": code, "timeout_seconds": min(self.timeout_seconds, 20)},
            description=f"fund_profile({code})",
            expect_dataframe=False,
        )
        if not isinstance(result, dict):
            raise DataFetchError(f"fund_profile({code}) 返回类型异常：{type(result).__name__}")
        return result

    @staticmethod
    def _parse_fund_profile(html: str, code: str) -> dict[str, Any]:
        """兼容旧测试：解析 F10 基本概况表。"""
        return parse_fund_profile(html, code)
