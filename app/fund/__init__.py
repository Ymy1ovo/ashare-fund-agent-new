"""场外公募基金数据层。

与场内 ETF 侧完全隔离：独立的表、独立的仓储、独立的导入流程。
不导入 app/backtest、app/validation、app/quant 的任何模块。
"""
from __future__ import annotations

from app.fund.migration import FUND_TABLES, ensure_fund_schema
from app.fund.models import (
    AumRecord,
    DataQualityRecord,
    DividendRecord,
    FeeRuleRecord,
    FundMasterRecord,
    FundShareClassRecord,
    LifecycleEventRecord,
    ManagerRecord,
    NavRecord,
    SubscriptionStatusRecord,
)
from app.fund.repo_nav import NavRepository
from app.fund.repo_quality import QualityRepository
from app.fund.repo_status import StatusRepository
from app.fund.repository import FundRepository

__all__ = [
    "ensure_fund_schema",
    "FUND_TABLES",
    "FundRepository",
    "NavRepository",
    "StatusRepository",
    "QualityRepository",
    "FundMasterRecord",
    "FundShareClassRecord",
    "NavRecord",
    "DividendRecord",
    "SubscriptionStatusRecord",
    "ManagerRecord",
    "FeeRuleRecord",
    "LifecycleEventRecord",
    "DataQualityRecord",
    "AumRecord",
]
