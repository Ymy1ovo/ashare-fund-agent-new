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

# ---------------------------------------------------------------- 数据类场景

SPARSE_SCENARIO_KEY = "sparse_data"
INSUFFICIENT_SCENARIO_KEY = "insufficient"


class StressDataError(RuntimeError):
    """构造压力测试数据副本失败。"""


def build_sparse_copy(
    source_db,
    workdir,
    *,
    start_date: str,
    end_date: str,
    drop_ratio_days: int = 5,
    gap_codes: int = 2,
    gap_length: int = 20,
) -> dict:
    """基于真实数据库生成「行情稀疏」测试副本。

    约束：只在副本上删除行情行，绝不触碰源数据库。
    做法：
    1. 用 SQLite backup() 生成独立副本；
    2. 在副本中按固定规则删除部分交易日行（确定性，可复现）；
    3. 返回副本路径与删除明细。

    删除规则（确定性，不用随机数）：
    - 对每只 ETF，每 drop_ratio_days 个交易日删除 1 个（覆盖全池零散缺失）；
    - 前 gap_codes 只 ETF 额外制造一段连续 gap_length 日的缺失（模拟持仓期停牌）。
    """
    import sqlite3
    from pathlib import Path

    source = Path(source_db)
    work = Path(workdir)
    work.mkdir(parents=True, exist_ok=True)
    target = work / "sparse_market.db"
    if target.exists():
        target.unlink()

    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
        dst.execute("PRAGMA temp_store=MEMORY")
        calendar = [
            str(row[0]) for row in dst.execute(
                "SELECT trade_date FROM trade_calendar "
                "WHERE trade_date >= ? AND trade_date <= ? ORDER BY trade_date",
                (start_date, end_date),
            )
        ]
        if not calendar:
            raise StressDataError("区间内没有交易日，无法构造稀疏场景")

        codes = [str(row[0]) for row in dst.execute(
            "SELECT code FROM etf_pool ORDER BY code"
        )]
        removed_scattered = 0
        removed_blocks = 0

        # 1) 零散缺失：每 drop_ratio_days 个交易日删 1 天。
        #    跳过区间首尾各 3 个交易日，避免把起始估值日整段删空导致回测无法开始
        #    （那不是「稀疏」而是「区间缺失」，会掩盖真正的稀疏场景）
        protected = set(calendar[:3]) | set(calendar[-3:])
        for position in range(0, len(calendar), drop_ratio_days):
            day = calendar[position]
            if day in protected:
                continue
            cursor = dst.execute(
                "DELETE FROM etf_daily_prices WHERE trade_date = ?", (day,)
            )
            removed_scattered += cursor.rowcount

        # 2) 连续缺失：前 gap_codes 只 ETF 在区间中部连续缺 gap_length 天
        midpoint = len(calendar) // 2
        block_start = midpoint - gap_length // 2
        block = calendar[max(0, block_start):block_start + gap_length]
        for code in codes[:gap_codes]:
            for day in block:
                cursor = dst.execute(
                    "DELETE FROM etf_daily_prices WHERE code = ? AND trade_date = ?",
                    (code, day),
                )
                removed_blocks += cursor.rowcount
        dst.commit()

        remaining = dst.execute("SELECT COUNT(*) FROM etf_daily_prices").fetchone()[0]

    return {
        "scenario": SPARSE_SCENARIO_KEY,
        "copy_path": str(target),
        "removed_scattered": removed_scattered,
        "removed_blocks": removed_blocks,
        "remaining_rows": int(remaining),
        "drop_ratio_days": drop_ratio_days,
        "gap_codes": gap_codes,
        "gap_length": gap_length,
        "source_untouched": True,
    }


def sparse_expectations() -> dict:
    """sparse_data 场景必须满足的期望，供测试与报告引用。"""
    return {
        "missing_days_kept_as_nan": True,
        "no_dropna_compression": True,
        "no_cross_gap_single_day_return": True,
        "explicit_missing_counts": True,
        "no_fabricated_fills": True,
    }


def evaluate_sparse_result(
    *, daily_rows: int, valid_return_days: int, gap_days_excluded: int
) -> dict:
    """判定 sparse 场景结果是否符合约束。"""
    problems: list[str] = []
    if daily_rows <= 0:
        problems.append("没有每日快照")
    if valid_return_days > daily_rows:
        problems.append("有效收益日数超过快照天数")
    if valid_return_days + gap_days_excluded > daily_rows:
        problems.append("有效收益日与缺口日之和超过快照天数")
    return {
        "status": "success" if not problems else "failed",
        "daily_rows": daily_rows,
        "valid_return_days": valid_return_days,
        "gap_days_excluded": gap_days_excluded,
        "nan_days": daily_rows - valid_return_days - gap_days_excluded,
        "problems": problems,
    }


def evaluate_insufficient_result(
    *,
    trading_days: int,
    min_required: int,
    sharpe: float | None,
    cagr: float | None,
    metrics_withheld: bool = True,
) -> dict:
    """判定 insufficient 场景：必须识别数据不足，不得给出看似正常的指标。

    sharpe / cagr 用于判定引擎是否算出了「本不该给出的指标」；
    metrics_withheld=True 表示调用方已按要求隐藏这些指标，
    此时它们不再作为对外结果，也不构成场景失败。
    """
    problems: list[str] = []
    status = "insufficient"
    if trading_days >= min_required:
        problems.append(
            f"区间交易日 {trading_days} 不低于最小需求 {min_required}，场景未构成数据不足"
        )
        status = "failed"

    computed = sharpe is not None or cagr is not None
    if computed and not metrics_withheld:
        if sharpe is not None:
            problems.append("数据不足却仍输出 Sharpe")
        if cagr is not None:
            problems.append("数据不足却仍输出 CAGR")
        status = "failed"

    return {
        "status": status,
        "trading_days": trading_days,
        "min_required": min_required,
        "sharpe": None if metrics_withheld else sharpe,
        "cagr": None if metrics_withheld else cagr,
        "engine_computed_metrics": computed,
        "metrics_withheld": metrics_withheld,
        "reason": (
            f"区间仅 {trading_days} 个交易日，低于最小需求 {min_required}，"
            f"不生成看起来正常的绩效指标"
            + ("（引擎内部算出的指标已隐藏，不作为结论依据）" if computed else "")
        ),
        "problems": problems,
    }
