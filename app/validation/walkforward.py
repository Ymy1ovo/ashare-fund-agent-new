"""Walk-Forward 滚动验证。

每个窗口只用训练窗内的数据选参数，验证窗只做最终验证，不回流优化。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.validation.config import (
    MIN_WALKFORWARD_TEST_DAYS,
    ValidationConfig,
    ValidationConfigError,
)


class WalkForwardError(RuntimeError):
    """滚动窗口配置或数据不满足要求。"""


@dataclass
class WalkForwardWindow:
    """一个训练/验证窗口。"""

    index: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    train_days: int
    test_days: int
    status: str = "pending"           # pending / success / insufficient_data / failed
    selected_param: int | None = None
    train_metrics: dict = field(default_factory=dict)
    test_metrics: dict = field(default_factory=dict)
    reason: str | None = None

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "train_start": self.train_start.isoformat(),
            "train_end": self.train_end.isoformat(),
            "test_start": self.test_start.isoformat(),
            "test_end": self.test_end.isoformat(),
            "train_days": self.train_days,
            "test_days": self.test_days,
            "status": self.status,
            "selected_param": self.selected_param,
            "train_metrics": self.train_metrics,
            "test_metrics": self.test_metrics,
            "reason": self.reason,
        }


def _shift_months(value: date, months: int) -> date:
    """按自然月平移；日超出目标月天数时取月末。"""
    year = value.year + (value.month - 1 + months) // 12
    month = (value.month - 1 + months) % 12 + 1
    day = value.day
    while True:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1
            if day < 1:
                raise WalkForwardError(f"无法平移月份：{value} + {months}")


def build_windows(
    calendar: list[date],
    config: ValidationConfig,
    *,
    min_test_days: int = MIN_WALKFORWARD_TEST_DAYS,
) -> list[WalkForwardWindow]:
    """按交易日历生成滚动窗口。

    训练窗起点逐窗前移 step_months；验证窗紧接训练窗。
    数据不足的窗口保留并标记 insufficient_data，不丢弃、不填补。
    """
    if not calendar:
        raise WalkForwardError("交易日历为空，无法生成滚动窗口")
    if config.test_months != config.step_months:
        # 当前设计验证窗与步长一致以保证验证期不重叠；不一致时明确拒绝
        raise ValidationConfigError(
            "test_months 必须等于 step_months，以保证验证窗互不重叠"
        )

    ordered = sorted(calendar)
    first_day, last_day = ordered[0], ordered[-1]
    windows: list[WalkForwardWindow] = []

    train_start = _shift_months(first_day, 0)
    index = 0
    while True:
        train_end = _shift_months(train_start, config.train_months) - timedelta_day()
        test_start = train_end + timedelta_day()
        test_end = _shift_months(test_start, config.test_months) - timedelta_day()
        if test_start > last_day:
            break

        # 验证窗不得越过真实数据边界：超出部分按实际最后一个交易日截断
        effective_test_end = min(test_end, last_day)
        train_days = [d for d in ordered if train_start <= d <= train_end]
        test_days = [d for d in ordered if test_start <= d <= effective_test_end]

        window = WalkForwardWindow(
            index=index,
            train_start=train_start,
            train_end=train_end,
            test_start=test_start,
            test_end=effective_test_end,
            train_days=len(train_days),
            test_days=len(test_days),
        )
        if effective_test_end < test_end:
            window.reason = (
                f"验证窗按数据边界截断至 {effective_test_end.isoformat()}"
                f"（原定 {test_end.isoformat()}）"
            )
        if len(train_days) == 0:
            window.status = "insufficient_data"
            window.reason = "训练窗内没有交易日"
        elif len(test_days) < min_test_days:
            window.status = "insufficient_data"
            window.reason = (
                f"验证窗交易日不足：{len(test_days)} < {min_test_days}"
            )
        windows.append(window)

        index += 1
        train_start = _shift_months(train_start, config.step_months)
        if train_start > last_day:
            break

    if not windows:
        raise WalkForwardError("区间内无法生成任何滚动窗口")
    return windows


def timedelta_day():
    """一天，避免顶部再导入 timedelta。"""
    from datetime import timedelta as _td

    return _td(days=1)


def assert_no_leakage(windows: list[WalkForwardWindow]) -> None:
    """校验窗口顺序与时间隔离，防止未来数据泄漏。"""
    for position, window in enumerate(windows):
        if window.train_end >= window.test_start:
            raise WalkForwardError(
                f"窗口 {window.index} 训练期与验证期重叠："
                f"{window.train_end} >= {window.test_start}"
            )
        if position > 0:
            previous = windows[position - 1]
            if window.train_start <= previous.train_start:
                raise WalkForwardError(
                    f"窗口 {window.index} 训练窗未向前滚动："
                    f"{window.train_start} <= {previous.train_start}"
                )
            if window.test_start <= previous.test_end:
                raise WalkForwardError(
                    f"窗口 {window.index} 验证窗与前窗重叠："
                    f"{window.test_start} <= {previous.test_end}"
                )


def select_best_param(train_results: dict[int, dict]) -> tuple[int | None, str]:
    """在训练窗结果中选参数：先比 Sharpe，再比最大回撤，最后比窗口大小。

    只接收训练窗结果，函数签名保证无法接触验证窗数据。
    """
    usable = {
        param: metrics for param, metrics in train_results.items()
        if metrics.get("status") == "success"
        and metrics.get("sharpe_ratio") is not None
    }
    if not usable:
        return None, "训练窗内没有可比较的有效结果"

    def sort_key(param: int):
        metrics = usable[param]
        drawdown = metrics.get("max_drawdown")
        return (
            -float(metrics["sharpe_ratio"]),
            abs(float(drawdown)) if drawdown is not None else float("inf"),
            param,
        )

    best = sorted(usable, key=sort_key)[0]
    return best, "按训练窗 Sharpe 最优选择"
