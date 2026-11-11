"""样本内/样本外时间切分。

严格按真实交易日切分，不按自然日，不打乱顺序。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.validation.config import MIN_VALIDATION_TRADING_DAYS, ValidationConfig


class SplitError(RuntimeError):
    """切分不满足约束。"""


@dataclass
class TimeSplit:
    """一次样本内外切分。"""

    in_sample: list[date]
    out_of_sample: list[date]
    is_start: str
    is_end: str
    oos_start: str
    oos_end: str
    notes: list[str]

    @property
    def is_days(self) -> int:
        return len(self.in_sample)

    @property
    def oos_days(self) -> int:
        return len(self.out_of_sample)

    @property
    def has_overlap(self) -> bool:
        return bool(set(self.in_sample) & set(self.out_of_sample))

    def as_dict(self) -> dict:
        return {
            "is_start": self.is_start,
            "is_end": self.is_end,
            "oos_start": self.oos_start,
            "oos_end": self.oos_end,
            "is_days": self.is_days,
            "oos_days": self.oos_days,
            "is_first": self.in_sample[0].isoformat() if self.in_sample else None,
            "is_last": self.in_sample[-1].isoformat() if self.in_sample else None,
            "oos_first": self.out_of_sample[0].isoformat() if self.out_of_sample else None,
            "oos_last": self.out_of_sample[-1].isoformat() if self.out_of_sample else None,
            "overlap": self.has_overlap,
            "notes": self.notes,
        }


def split_time_range(
    calendar: list[date],
    config: ValidationConfig,
    *,
    min_days: int = MIN_VALIDATION_TRADING_DAYS,
) -> TimeSplit:
    """按交易日历切分样本内外。

    - 每个日期只出现在其中一边
    - IS 全部早于 OOS
    - 交易日数不足时抛错而不是缩小阈值
    """
    if not calendar:
        raise SplitError("交易日历为空，无法切分")
    ordered = sorted(calendar)
    if len(ordered) != len(set(ordered)):
        raise SplitError("交易日历存在重复日期")

    is_start = date.fromisoformat(config.is_start)
    is_end = date.fromisoformat(config.is_end)
    oos_start = date.fromisoformat(config.oos_start)
    oos_end = date.fromisoformat(config.oos_end)

    if not is_end < oos_start:
        raise SplitError(
            f"样本内结束日 {is_end} 必须早于样本外起始日 {oos_start}"
        )

    in_sample = [day for day in ordered if is_start <= day <= is_end]
    out_of_sample = [day for day in ordered if oos_start <= day <= oos_end]

    if set(in_sample) & set(out_of_sample):
        raise SplitError("样本内外存在重叠交易日")

    notes: list[str] = []
    if len(in_sample) < min_days:
        raise SplitError(
            f"样本内交易日不足：{len(in_sample)} < {min_days}，拒绝以不足数据继续验证"
        )
    if len(out_of_sample) < min_days:
        raise SplitError(
            f"样本外交易日不足：{len(out_of_sample)} < {min_days}，拒绝以不足数据继续验证"
        )

    # 记录实际生效边界，防止配置日期落在非交易日而报告写错
    actual_is_start = in_sample[0].isoformat()
    actual_is_end = in_sample[-1].isoformat()
    actual_oos_start = out_of_sample[0].isoformat()
    actual_oos_end = out_of_sample[-1].isoformat()
    if actual_is_start != config.is_start:
        notes.append(f"样本内实际起始日 {actual_is_start}（配置 {config.is_start} 非交易日）")
    if actual_is_end != config.is_end:
        notes.append(f"样本内实际结束日 {actual_is_end}（配置 {config.is_end} 非交易日）")
    if actual_oos_start != config.oos_start:
        notes.append(f"样本外实际起始日 {actual_oos_start}（配置 {config.oos_start} 非交易日）")
    if actual_oos_end != config.oos_end:
        notes.append(f"样本外实际结束日 {actual_oos_end}（配置 {config.oos_end} 非交易日）")

    return TimeSplit(
        in_sample=in_sample,
        out_of_sample=out_of_sample,
        is_start=actual_is_start,
        is_end=actual_is_end,
        oos_start=actual_oos_start,
        oos_end=actual_oos_end,
        notes=notes,
    )


def warmup_note(ma_window: int) -> str:
    """说明预热期用途，避免把预热收益计入验证期。"""
    return (
        f"MA{ma_window} 需要 {ma_window - 1} 个历史交易日预热；"
        f"预热数据仅用于让指标在验证起点有值，其价格变动不计入验证期收益"
        f"（回测起始日仍为验证期起点，指标直接读取已算好的 ma 列）"
    )


def filter_codes_by_coverage(
    code_day_counts: dict[str, int],
    calendar_days: int,
    ratio: float,
    *,
    code_first_dates: dict[str, str] | None = None,
    required_first_date: str | None = None,
) -> tuple[list[str], list[dict]]:
    """按真实覆盖过滤 ETF，返回 (保留列表, 剔除明细)。

    覆盖率高不代表起点可用：上市较晚的 ETF 在区间起点就没有行情，
    引擎会在首日因缺少估值价格而失败。因此额外校验首日可用性。
    """
    keep: list[str] = []
    dropped: list[dict] = []
    for code in sorted(code_day_counts):
        count = code_day_counts[code]
        if calendar_days <= 0 or count < calendar_days * ratio:
            dropped.append(
                {
                    "code": code,
                    "rows": count,
                    "calendar_days": calendar_days,
                    "coverage": round(count / calendar_days, 4) if calendar_days else 0.0,
                    "reason": "insufficient_history",
                }
            )
            continue
        if required_first_date and code_first_dates is not None:
            first = code_first_dates.get(code)
            if not first or first > required_first_date:
                dropped.append(
                    {
                        "code": code,
                        "rows": count,
                        "calendar_days": calendar_days,
                        "coverage": round(count / calendar_days, 4),
                        "reason": "late_listing",
                        "first_date": first,
                        "required_first_date": required_first_date,
                    }
                )
                continue
        keep.append(code)
    return keep, dropped
