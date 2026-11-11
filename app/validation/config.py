"""阶段3A.2 验证配置。

所有区间、参数网格、阈值集中于此，不散落到验证逻辑里。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

# ma_trend 唯一真实参数是 ma_window；网格取自项目已有指标列 ma5~ma250。
MA_WINDOW_GRID: tuple[int, ...] = (5, 10, 20, 30, 60, 120, 250)

# Walk-Forward 默认：训练 2 年、验证 6 个月、步长 6 个月
DEFAULT_TRAIN_MONTHS = 24
DEFAULT_TEST_MONTHS = 6
DEFAULT_STEP_MONTHS = 6

# 市场环境分类阈值（相对 MA250 的偏离）
REGIME_BULL_THRESHOLD = 0.05
REGIME_BEAR_THRESHOLD = -0.05
REGIME_MA_WINDOW = 250

# 市场环境参考标的：数据库无指数表，用沪深300ETF代理
REGIME_PROXY_CODE = "510300"

# 基准代理（数据库无独立指数表）
BENCHMARK_HS300_PROXY = "510300"
BENCHMARK_ZZ500_PROXY = "510500"

# 有效性最小样本阈值
MIN_VALIDATION_TRADING_DAYS = 120
MIN_WALKFORWARD_TEST_DAYS = 60
MIN_REGIME_SAMPLES = 20


class ValidationConfigError(ValueError):
    """验证配置非法。"""


@dataclass(frozen=True)
class ValidationConfig:
    """一次验证任务的完整参数。"""

    strategy_name: str = "ma_trend"
    strategy_version: str = "1.0.0"
    is_start: str = "2021-01-01"
    is_end: str = "2024-12-31"
    oos_start: str = "2025-01-01"
    oos_end: str = "2026-11-09"
    initial_cash: float = 1_000_000.0
    execution_price: str = "open"
    max_defer_days: int = 3
    risk_free_rate: float = 0.0
    annualization: int = 252
    commission_rate: float = 0.00025
    min_commission: float = 5.0
    slippage_bps: float = 5.0
    rebalance_tolerance: float = 0.02
    indicator_version: str = "v1.0.2-30b821a1af15"
    ma_window_grid: tuple[int, ...] = MA_WINDOW_GRID
    # Walk-Forward 每窗只搜代表性档位：7 档 × 8 窗口 = 56 次回测过慢，
    # 样本内网格仍跑满全部档位，WF 只验证参数选择的时序有效性
    wf_grid: tuple[int, ...] = (5, 20, 60)
    # 池模式：all=全部合格 ETF；representative=每类取历史最长的一只
    # 41 只 ETF 单次回测 84 秒，全流程会超过 40 分钟，默认用代表性池
    pool_mode: str = "representative"
    train_months: int = DEFAULT_TRAIN_MONTHS
    test_months: int = DEFAULT_TEST_MONTHS
    step_months: int = DEFAULT_STEP_MONTHS
    regime_proxy_code: str = REGIME_PROXY_CODE
    exclude_insufficient: bool = True
    min_coverage_ratio: float = 0.95
    notes: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if self.is_start >= self.is_end:
            raise ValidationConfigError("is_start 必须早于 is_end")
        if self.oos_start >= self.oos_end:
            raise ValidationConfigError("oos_start 必须早于 oos_end")
        if not self.is_end < self.oos_start:
            raise ValidationConfigError(
                f"样本内外必须严格分离：is_end={self.is_end} 必须早于 oos_start={self.oos_start}"
            )
        if self.initial_cash <= 0:
            raise ValidationConfigError("initial_cash 必须为正")
        if not self.ma_window_grid:
            raise ValidationConfigError("ma_window_grid 不能为空")
        if any(window < 2 for window in self.ma_window_grid):
            raise ValidationConfigError("ma_window 必须 >= 2")
        if self.pool_mode not in ("all", "representative"):
            raise ValidationConfigError("pool_mode 只能是 all 或 representative")
        if not self.wf_grid:
            raise ValidationConfigError("wf_grid 不能为空")
        if any(window < 2 for window in self.wf_grid):
            raise ValidationConfigError("wf_grid 中的 ma_window 必须 >= 2")
        if self.train_months <= 0 or self.test_months <= 0 or self.step_months <= 0:
            raise ValidationConfigError("滚动窗口月份必须为正")
        if self.commission_rate < 0 or self.min_commission < 0 or self.slippage_bps < 0:
            raise ValidationConfigError("成本参数不能为负")
        if not 0 < self.min_coverage_ratio <= 1:
            raise ValidationConfigError("min_coverage_ratio 必须在 (0, 1] 内")

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ma_window_grid"] = list(self.ma_window_grid)
        payload["wf_grid"] = list(self.wf_grid)
        return payload

    def params_hash(self) -> str:
        text = json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    def build_backtest_config(self, start_date: str, end_date: str, **overrides: Any):
        """生成对应区间的回测配置；压力测试通过 overrides 改成本。"""
        from app.backtest.config import BacktestConfig, CostConfig

        costs = CostConfig(
            commission_rate=overrides.pop("commission_rate", self.commission_rate),
            min_commission=overrides.pop("min_commission", self.min_commission),
            slippage_bps=overrides.pop("slippage_bps", self.slippage_bps),
        )
        return BacktestConfig(
            start_date=start_date,
            end_date=end_date,
            initial_cash=overrides.pop("initial_cash", self.initial_cash),
            execution_price=overrides.pop("execution_price", self.execution_price),
            max_defer_days=overrides.pop("max_defer_days", self.max_defer_days),
            risk_free_rate=overrides.pop("risk_free_rate", self.risk_free_rate),
            annualization=overrides.pop("annualization", self.annualization),
            rebalance_tolerance=overrides.pop("rebalance_tolerance", self.rebalance_tolerance),
            costs=costs,
        )


def coverage_ok(code_days: int, calendar_days: int, ratio: float) -> bool:
    """ETF 在区间内的行情覆盖是否达标。"""
    if calendar_days <= 0:
        return False
    return code_days >= calendar_days * ratio
