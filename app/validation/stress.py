"""压力测试场景。

所有场景只改 BacktestConfig 的成本参数，绝不修改历史行情。
"""
from __future__ import annotations

from dataclasses import dataclass

from app.validation.config import ValidationConfig


class StressError(RuntimeError):
    """压力场景配置非法。"""


@dataclass
class StressScenario:
    """一个压力场景。"""

    key: str
    name: str
    kind: str                       # cost / slippage / data
    commission_multiplier: float = 1.0
    min_commission_multiplier: float = 1.0
    slippage_multiplier: float = 1.0
    is_hypothetical: bool = True
    notes: str = ""

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "kind": self.kind,
            "commission_multiplier": self.commission_multiplier,
            "min_commission_multiplier": self.min_commission_multiplier,
            "slippage_multiplier": self.slippage_multiplier,
            "is_hypothetical": self.is_hypothetical,
            "notes": self.notes,
        }

    def apply(self, config: ValidationConfig) -> dict:
        """把场景换算成 BacktestConfig 覆盖参数。"""
        return {
            "commission_rate": config.commission_rate * self.commission_multiplier,
            "min_commission": config.min_commission * self.min_commission_multiplier,
            "slippage_bps": config.slippage_bps * self.slippage_multiplier,
        }


def default_scenarios() -> list[StressScenario]:
    """提示词要求的 7 个场景。"""
    return [
        StressScenario(
            key="base", name="基础成本", kind="cost", is_hypothetical=False,
            notes="项目默认：万2.5 佣金 + 5bp 滑点 + 5 元最低佣金",
        ),
        StressScenario(
            key="cost_plus_50", name="交易成本提高 50%", kind="cost",
            commission_multiplier=1.5, min_commission_multiplier=1.5,
            notes="佣金与最低佣金同时 ×1.5（模拟假设）",
        ),
        StressScenario(
            key="cost_plus_100", name="交易成本提高 100%", kind="cost",
            commission_multiplier=2.0, min_commission_multiplier=2.0,
            notes="佣金与最低佣金同时 ×2（模拟假设）",
        ),
        StressScenario(
            key="slippage_x2", name="滑点提高一倍", kind="slippage",
            slippage_multiplier=2.0,
            notes="滑点 5bp → 10bp（模拟假设）",
        ),
        StressScenario(
            key="slippage_x3", name="滑点提高两倍", kind="slippage",
            slippage_multiplier=3.0,
            notes="滑点 5bp → 15bp（模拟假设）",
        ),
        StressScenario(
            key="sparse_data", name="行情稀疏（剔除历史不足标的）", kind="data",
            is_hypothetical=False,
            notes="只保留覆盖达标的 ETF，剔除上市较晚的标的",
        ),
        StressScenario(
            key="insufficient", name="数据不足区间", kind="data",
            is_hypothetical=False,
            notes="人为把区间缩短到不足最小样本，验证系统正确标记数据不足",
        ),
    ]


def build_scenarios(keys: list[str] | None = None) -> list[StressScenario]:
    scenarios = default_scenarios()
    if not keys:
        return scenarios
    known = {scenario.key for scenario in scenarios}
    unknown = [key for key in keys if key not in known]
    if unknown:
        raise StressError(f"未知压力场景：{unknown}；可用：{sorted(known)}")
    return [scenario for scenario in scenarios if scenario.key in keys]


def assert_no_data_mutation(baseline: dict, after: dict, scenario_key: str) -> None:
    """压力测试前后行情指纹必须一致；不一致立即报错。"""
    if baseline != after:
        raise StressError(
            f"压力场景 {scenario_key} 修改了历史数据：{baseline} -> {after}"
        )
