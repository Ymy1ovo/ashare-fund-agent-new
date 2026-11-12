"""回测参数与 ETF 交易规则配置。

所有成本、规则均集中在此，不散落到撮合代码中。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


class BacktestConfigError(ValueError):
    """回测参数非法。"""


@dataclass(frozen=True)
class CostConfig:
    """交易成本。

    commission_rate: 成交金额比例佣金
    min_commission:  单笔最低佣金
    slippage_bps:    滑点（万分之几，1bp = 0.01%），买入抬价、卖出压价
    slippage_fixed:  固定滑点（元/股），与比例滑点二选一，默认用比例
    """

    commission_rate: float = 0.00025
    min_commission: float = 5.0
    slippage_bps: float = 5.0
    slippage_fixed: float = 0.0
    stamp_duty_rate: float = 0.0
    transfer_fee_rate: float = 0.0
    # 最低佣金模型：
    #   per_order（默认）：同一订单多次成交共用一份最低佣金额度，
    #                      按订单累计成交金额计算应收佣金
    #   per_fill：每笔成交独立收取 max(金额×费率, 最低佣金)
    min_commission_model: str = "per_order"

    def validate(self) -> None:
        if self.commission_rate < 0:
            raise BacktestConfigError("commission_rate 不能为负")
        if self.min_commission < 0:
            raise BacktestConfigError("min_commission 不能为负")
        if self.slippage_bps < 0 or self.slippage_fixed < 0:
            raise BacktestConfigError("滑点不能为负")
        if self.slippage_bps > 0 and self.slippage_fixed > 0:
            raise BacktestConfigError("比例滑点与固定滑点只能启用一种")
        if not 0 <= self.stamp_duty_rate < 0.01:
            raise BacktestConfigError("stamp_duty_rate 超出合理范围")
        if not 0 <= self.transfer_fee_rate < 0.01:
            raise BacktestConfigError("transfer_fee_rate 超出合理范围")
        if self.min_commission_model not in ("per_order", "per_fill"):
            raise BacktestConfigError(
                "min_commission_model 只能是 per_order 或 per_fill"
            )


@dataclass(frozen=True)
class InstrumentRule:
    """单只 ETF 的交易规则。"""

    code: str
    category: str
    settlement_days: int = 1
    lot_size: int = 100
    price_limit_pct: float = 0.10
    confirmed: bool = True
    notes: str = ""

    def validate(self) -> None:
        if self.settlement_days not in (0, 1):
            raise BacktestConfigError(f"{self.code} settlement_days 只支持 0 或 1")
        if self.lot_size <= 0:
            raise BacktestConfigError(f"{self.code} lot_size 必须为正")
        if not 0 < self.price_limit_pct <= 0.5:
            raise BacktestConfigError(f"{self.code} price_limit_pct 超出范围")


# 类别默认规则；单只代码可通过 overrides 覆盖。
CATEGORY_RULES: dict[str, dict[str, Any]] = {
    "宽基指数ETF": {"settlement_days": 1, "lot_size": 100, "price_limit_pct": 0.10, "confirmed": True},
    "科技成长ETF": {"settlement_days": 1, "lot_size": 100, "price_limit_pct": 0.10, "confirmed": True},
    "消费与医药ETF": {"settlement_days": 1, "lot_size": 100, "price_limit_pct": 0.10, "confirmed": True},
    "跨境ETF": {"settlement_days": 0, "lot_size": 100, "price_limit_pct": 0.10, "confirmed": True,
                "notes": "跨境ETF按T+0配置；额度与申赎限制未建模"},
    "债券ETF": {"settlement_days": 0, "lot_size": 100, "price_limit_pct": 0.10, "confirmed": False,
                "notes": "债券ETF涨跌幅限制未逐一确认，采用10%保守上限"},
    "黄金ETF": {"settlement_days": 0, "lot_size": 100, "price_limit_pct": 0.10, "confirmed": True,
                "notes": "黄金ETF按T+0配置"},
    "商品ETF": {"settlement_days": 0, "lot_size": 100, "price_limit_pct": 0.10, "confirmed": False,
                "notes": "商品ETF规则未逐一确认，采用保守默认"},
}

DEFAULT_CATEGORY_RULE: dict[str, Any] = {
    "settlement_days": 1,
    "lot_size": 100,
    "price_limit_pct": 0.10,
    "confirmed": False,
    "notes": "未知类别，采用T+1、10%涨跌幅的保守规则",
}

# 科创板/创业板相关 ETF 的 20% 涨跌幅（588/159/1599 等按代码前缀判断）
PRICE_LIMIT_OVERRIDES = {
    "588": (0.20, "科创板ETF，20%涨跌幅"),
}


def rule_for(code: str, category: str, overrides: dict[str, dict[str, Any]] | None = None) -> InstrumentRule:
    """按类别 + 代码覆盖生成交易规则。"""
    payload = dict(CATEGORY_RULES.get(category, DEFAULT_CATEGORY_RULE))
    for prefix, (limit, note) in PRICE_LIMIT_OVERRIDES.items():
        if code.startswith(prefix):
            payload["price_limit_pct"] = limit
            payload["notes"] = note
    if overrides and code in overrides:
        payload.update(overrides[code])
    rule = InstrumentRule(code=code, category=category, **payload)
    rule.validate()
    return rule


@dataclass(frozen=True)
class BacktestConfig:
    """一次回测的完整参数。"""

    start_date: str
    end_date: str
    initial_cash: float = 1_000_000.0
    execution_price: str = "open"          # open / close
    max_defer_days: int = 3                # 订单最多延期多少个交易日
    risk_free_rate: float = 0.0
    annualization: int = 252
    lot_size_override: int | None = None
    allow_partial_fill: bool = False
    rebalance_tolerance: float = 0.02       # 权重偏离小于该值不调仓
    cash_shortfall_policy: str = "reduce"  # reduce / reject
    costs: CostConfig = field(default_factory=CostConfig)
    instrument_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    strategy_params: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.start_date > self.end_date:
            raise BacktestConfigError("start_date 不能晚于 end_date")
        if self.initial_cash <= 0:
            raise BacktestConfigError("initial_cash 必须为正")
        if self.execution_price not in {"open", "close"}:
            raise BacktestConfigError("execution_price 只能是 open 或 close")
        if self.max_defer_days < 0:
            raise BacktestConfigError("max_defer_days 不能为负")
        if self.annualization < 1:
            raise BacktestConfigError("annualization 必须为正")
        if self.cash_shortfall_policy not in {"reduce", "reject"}:
            raise BacktestConfigError("cash_shortfall_policy 只能是 reduce 或 reject")
        if not 0 <= self.rebalance_tolerance < 1:
            raise BacktestConfigError("rebalance_tolerance 必须在 [0, 1) 内")
        if not -1 < self.risk_free_rate < 1:
            raise BacktestConfigError("risk_free_rate 超出范围")
        self.costs.validate()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def params_hash(self) -> str:
        payload = json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
