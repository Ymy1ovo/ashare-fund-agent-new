"""参数敏感性分析。

只在样本内扫描网格，样本外只对训练期最优参数做一次最终验证。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.validation.config import ValidationConfig


class SensitivityError(RuntimeError):
    """参数网格或结果不满足要求。"""


# 稳定性判定阈值：相邻档位的 Sharpe 相对最优值的保留比例
STABILITY_RETAIN_RATIO = 0.6
STABILITY_MIN_POSITIVE_RATIO = 0.5


@dataclass
class GridCell:
    """网格中的一个参数组合结果。"""

    ma_window: int
    status: str
    metrics: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None

    def as_dict(self) -> dict:
        return {
            "ma_window": self.ma_window,
            "status": self.status,
            "metrics": self.metrics,
            "reason": self.reason,
        }


@dataclass
class SensitivityResult:
    """参数敏感性完整结果。"""

    grid: list[GridCell]
    best_param: int | None
    best_sharpe: float | None
    positive_count: int
    total_count: int
    stable_neighbors: list[int]
    risk_flags: list[str]
    oos_result: GridCell | None = None

    def as_dict(self) -> dict:
        return {
            "grid": [cell.as_dict() for cell in self.grid],
            "best_param": self.best_param,
            "best_sharpe": self.best_sharpe,
            "positive_count": self.positive_count,
            "total_count": self.total_count,
            "positive_ratio": (
                round(self.positive_count / self.total_count, 4)
                if self.total_count else None
            ),
            "stable_neighbors": self.stable_neighbors,
            "risk_flags": self.risk_flags,
            "oos_result": self.oos_result.as_dict() if self.oos_result else None,
        }

    def metrics_table(self) -> list[dict]:
        """全部组合的指标表，报告必须展示全表而不是只展示最优。"""
        rows = []
        for cell in self.grid:
            row = {"ma_window": cell.ma_window, "status": cell.status}
            row.update({key: cell.metrics.get(key) for key in (
                "total_return", "cagr", "max_drawdown", "sharpe_ratio",
                "sortino_ratio", "trade_count", "turnover", "calmar_ratio",
            )})
            rows.append(row)
        return rows


def _sort_key(cell: GridCell) -> tuple:
    metrics = cell.metrics
    sharpe = metrics.get("sharpe_ratio")
    drawdown = metrics.get("max_drawdown")
    return (
        -float(sharpe) if sharpe is not None else float("inf"),
        abs(float(drawdown)) if drawdown is not None else float("inf"),
        cell.ma_window,
    )


def analyze_grid(
    grid: list[GridCell],
    *,
    grid_order: tuple[int, ...] | None = None,
) -> SensitivityResult:
    """分析网格结果，给出稳定性与过拟合风险提示。

    只接收样本内网格结果，样本外结果通过 attach_oos() 单独挂上。
    """
    if not grid:
        raise SensitivityError("参数网格为空")

    usable = [cell for cell in grid if cell.status == "success"]
    ordered = sorted(usable, key=_sort_key)
    best = ordered[0] if ordered else None
    best_param = best.ma_window if best else None
    best_sharpe = (
        float(best.metrics["sharpe_ratio"]) if best and best.metrics.get("sharpe_ratio") is not None
        else None
    )

    positive = [
        cell for cell in usable
        if (cell.metrics.get("total_return") or 0) > 0
    ]
    total = len(grid)

    order = grid_order or tuple(sorted(cell.ma_window for cell in usable))
    neighbors: list[int] = []
    if best_param is not None and best_sharpe is not None and best_sharpe > 0:
        position = order.index(best_param) if best_param in order else -1
        for offset in (-1, 1):
            index = position + offset
            if 0 <= index < len(order):
                candidate_param = order[index]
                candidate = next(
                    (cell for cell in usable if cell.ma_window == candidate_param), None
                )
                if candidate is None:
                    continue
                sharpe = candidate.metrics.get("sharpe_ratio")
                if sharpe is None:
                    continue
                if float(sharpe) / best_sharpe >= STABILITY_RETAIN_RATIO:
                    neighbors.append(candidate_param)

    risk_flags: list[str] = []
    if total and len(positive) / total < STABILITY_MIN_POSITIVE_RATIO:
        risk_flags.append(
            f"仅 {len(positive)}/{total} 个参数组合在样本内取得正收益，"
            f"存在过拟合风险"
        )
    if best_param is not None and not neighbors:
        risk_flags.append(
            f"最优参数 MA{best_param} 的相邻档位表现明显衰减，"
            f"说明该参数点缺乏稳定区域（过拟合风险高）"
        )
    if len(usable) < 3:
        risk_flags.append(f"有效参数组合只有 {len(usable)} 个，不足以判断稳健性")
    if best_sharpe is not None and best_sharpe <= 0:
        risk_flags.append("样本内最优参数的 Sharpe 不为正，策略在样本内即无风险调整后收益")

    return SensitivityResult(
        grid=grid,
        best_param=best_param,
        best_sharpe=best_sharpe,
        positive_count=len(positive),
        total_count=total,
        stable_neighbors=neighbors,
        risk_flags=risk_flags,
    )


def attach_oos(result: SensitivityResult, cell: GridCell) -> SensitivityResult:
    """把样本外最终验证结果挂到分析结果上（不作为选参依据）。"""
    result.oos_result = cell
    return result
