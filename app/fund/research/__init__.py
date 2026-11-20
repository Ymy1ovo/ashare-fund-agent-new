"""场外公募基金研究性分析引擎（阶段 3B-5.1）。

只读分析层：不写库、不采集、不排名、不出信号。
与场内 ETF 侧（app/backtest、app/validation）完全隔离。
"""
from __future__ import annotations

from app.fund.research.classification import (
    PRODUCT_TAXONOMY, classify_fund, is_offmarket_pool,
)
from app.fund.research.data_access import (
    NavSeries, QualityReport, load_universe, load_nav_series,
)
from app.fund.research.indicators import compute_nav_indicators, compute_money_indicators
from app.fund.research.engine import analyze_fund, analyze_universe

__all__ = [
    "PRODUCT_TAXONOMY",
    "classify_fund",
    "is_offmarket_pool",
    "NavSeries",
    "QualityReport",
    "load_universe",
    "load_nav_series",
    "compute_nav_indicators",
    "compute_money_indicators",
    "analyze_fund",
    "analyze_universe",
]
