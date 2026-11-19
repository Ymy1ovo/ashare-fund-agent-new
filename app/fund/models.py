"""场外基金数据层的记录结构。

全部用 dataclass，字段与迁移里的列一一对应；
未知字段一律用 None，禁止在构造时填默认的「行业平均」或「今天」。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FundMasterRecord:
    fund_code_primary: str
    fund_name: str
    source: str
    ingested_at: str
    fund_full_name: str | None = None
    fund_company: str | None = None
    custodian: str | None = None
    fund_type_l1: str | None = None
    fund_type_l2: str | None = None
    invest_scope: str | None = None
    benchmark: str | None = None
    established_date: str | None = None
    terminated_date: str | None = None
    lifecycle_status: str = "unknown"
    is_index_fund: int | None = None
    tracking_index: str | None = None
    needs_review: int = 0
    source_updated_at: str | None = None
    data_version: str = "fund-v1"


@dataclass
class FundShareClassRecord:
    share_class_code: str
    share_class_name: str
    source: str
    ingested_at: str
    share_class_type: str = "unknown"
    currency: str = "CNY"
    is_primary: int = 0
    management_fee: float | None = None
    custody_fee: float | None = None
    sales_service_fee: float | None = None
    min_purchase: float | None = None
    min_holding: float | None = None
    listed_date: str | None = None
    terminated_date: str | None = None
    source_updated_at: str | None = None


@dataclass
class NavRecord:
    """一条每日净值。nav_kind 决定哪些字段必须为空。"""
    nav_date: str
    nav_kind: str = "net_value"
    unit_nav: float | None = None
    acc_nav: float | None = None
    per_10k_yield: float | None = None
    seven_day_annual: float | None = None
    daily_return: float | None = None
    nav_status: str = "normal"
    source: str = "akshare.fund_open_fund_info_em"
    ingested_at: str = ""


@dataclass
class DividendRecord:
    ex_date: str
    cash_per_share: float
    per_10_raw: str
    source: str = "akshare.fund_open_fund_info_em"
    ingested_at: str = ""
    record_date: str | None = None
    pay_date: str | None = None
    dividend_type: str = "cash"
    reinvest_nav: float | None = None
    source_updated_at: str | None = None


@dataclass
class SubscriptionStatusRecord:
    as_of_date: str
    source: str
    ingested_at: str
    purchase_status: str | None = None
    redeem_status: str | None = None
    daily_limit: float | None = None
    min_purchase: float | None = None
    next_open_date: str | None = None
    alipay_purchasable: str = "unknown"


@dataclass
class ManagerRecord:
    manager_name: str
    source: str
    ingested_at: str
    company: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    tenure_days: int | None = None


@dataclass
class FeeRuleRecord:
    fee_type: str
    source: str
    ingested_at: str
    tier_order: int = 0
    lower_bound: float | None = None
    upper_bound: float | None = None
    rate: float | None = None
    holding_days_min: int | None = None
    holding_days_max: int | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    evidence_level: str = "unverified"


@dataclass
class LifecycleEventRecord:
    event_type: str
    source: str
    ingested_at: str
    event_date: str | None = None
    announcement_date: str | None = None
    announcement_url: str | None = None
    detail: str | None = None
    successor_fund_id: int | None = None
    evidence_level: str = "unverified"


@dataclass
class DataQualityRecord:
    table_name: str
    record_key: str
    check_name: str
    status: str
    checked_at: str
    detail: str | None = None
    severity: str = "info"


@dataclass
class AumRecord:
    report_date: str
    source: str
    ingested_at: str
    aum_total: float | None = None
    shares_total: float | None = None
    aum_unit: str | None = None
