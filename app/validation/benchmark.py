"""基准策略构建与区间对齐。

数据库没有独立指数表，只能使用 ETF 代理，报告中必须标注口径差异。
"""
from __future__ import annotations

from dataclasses import dataclass

from app.validation.config import (
    BENCHMARK_HS300_PROXY,
    BENCHMARK_ZZ500_PROXY,
    ValidationConfig,
)


class BenchmarkError(RuntimeError):
    """基准无法构建。"""


@dataclass
class BenchmarkSpec:
    """一个基准的定义。"""

    key: str
    name: str
    kind: str                     # buy_and_hold / ma_trend
    codes: list[str]
    ma_window: int | None = None
    proxy_for: str | None = None  # 代理的真实指数名称
    notes: str = ""

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "kind": self.kind,
            "codes": self.codes,
            "ma_window": self.ma_window,
            "proxy_for": self.proxy_for,
            "notes": self.notes,
        }


def build_benchmarks(
    codes: list[str],
    config: ValidationConfig,
    *,
    best_ma_window: int | None = None,
    extra_codes: list[str] | None = None,
) -> list[BenchmarkSpec]:
    """构造基准清单。

    沪深300 / 中证500 使用 ETF 代理，proxy_for 字段标明代理关系，
    报告据此说明「ETF 跟踪误差 + 交易费用」与纯指数的差异。
    """
    if not codes:
        raise BenchmarkError("ETF 池为空，无法构造基准")

    specs: list[BenchmarkSpec] = []

    specs.append(
        BenchmarkSpec(
            key="buy_and_hold",
            name="买入持有（等权）",
            kind="buy_and_hold",
            codes=list(codes),
            notes="同池等权买入并持有，含佣金与滑点",
        )
    )

    available = set(codes) | set(extra_codes or [])
    if BENCHMARK_HS300_PROXY in available:
        specs.append(
            BenchmarkSpec(
                key="hs300",
                name="沪深300（510300 ETF 代理）",
                kind="buy_and_hold",
                codes=[BENCHMARK_HS300_PROXY],
                proxy_for="沪深300指数",
                notes="数据库无独立指数表，用沪深300ETF代理；含跟踪误差与交易费用",
            )
        )
    if BENCHMARK_ZZ500_PROXY in available:
        specs.append(
            BenchmarkSpec(
                key="zz500",
                name="中证500（510500 ETF 代理）",
                kind="buy_and_hold",
                codes=[BENCHMARK_ZZ500_PROXY],
                proxy_for="中证500指数",
                notes="数据库无独立指数表，用中证500ETF代理；含跟踪误差与交易费用",
            )
        )

    specs.append(
        BenchmarkSpec(
            key="ma_trend",
            name=(
                f"MA{best_ma_window}趋势" if best_ma_window else "MA趋势策略"
            ),
            kind="ma_trend",
            codes=list(codes),
            ma_window=best_ma_window,
            notes="现有 ma_trend 策略，参数来自样本内选择",
        )
    )
    return specs


def align_ranges(specs: list[BenchmarkSpec], available: dict[str, tuple[str, str]]) -> list[dict]:
    """检查各基准的数据覆盖，标记无法对齐的基准。

    available: {code: (first_date, last_date)}
    返回每项的区间与状态，不完整的基准标记 insufficient_data 而不是硬跑。
    """
    rows: list[dict] = []
    for spec in specs:
        missing = [code for code in spec.codes if code not in available]
        if missing:
            rows.append(
                {
                    "key": spec.key,
                    "name": spec.name,
                    "status": "insufficient_data",
                    "reason": f"缺少行情：{missing}",
                    "codes": spec.codes,
                }
            )
            continue
        firsts = [available[code][0] for code in spec.codes]
        lasts = [available[code][1] for code in spec.codes]
        rows.append(
            {
                "key": spec.key,
                "name": spec.name,
                "status": "ok",
                "coverage_start": max(firsts),
                "coverage_end": min(lasts),
                "codes": spec.codes,
                "proxy_for": spec.proxy_for,
                "notes": spec.notes,
            }
        )
    return rows


def common_range(rows: list[dict]) -> tuple[str | None, str | None, list[str]]:
    """求所有 ok 基准的公共区间；区间不一致时报告原因。"""
    ok = [row for row in rows if row["status"] == "ok"]
    if not ok:
        return None, None, ["没有任何可用基准"]
    start = max(row["coverage_start"] for row in ok)
    end = min(row["coverage_end"] for row in ok)
    notes: list[str] = []
    if start >= end:
        notes.append(f"公共区间无效：{start} >= {end}")
        return None, None, notes
    for row in ok:
        if row["coverage_start"] < start:
            notes.append(
                f"{row['name']} 自身起点 {row['coverage_start']} 早于公共起点 {start}，"
                f"已按公共区间截取（截掉前段）"
            )
        elif row["coverage_start"] > start:
            notes.append(
                f"{row['name']} 自身起点 {row['coverage_start']} 晚于公共起点 {start}，"
                f"区间已对齐到公共起点"
            )
        if row["coverage_end"] > end:
            notes.append(
                f"{row['name']} 自身终点 {row['coverage_end']} 晚于公共终点 {end}，"
                f"已按公共区间截取（截掉后段）"
            )
        elif row["coverage_end"] < end:
            notes.append(
                f"{row['name']} 自身终点 {row['coverage_end']} 早于公共终点 {end}，"
                f"区间已对齐到公共终点"
            )
    return start, end, notes
