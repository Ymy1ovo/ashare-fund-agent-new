"""指标引擎配置、版本与参数哈希。"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

ENGINE_VERSION = "1.0.2"

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": ["returns", "trend", "momentum", "volatility", "risk"],
    "return_windows": [1, 5, 10, 20, 60, 120, 250],
    "ma_windows": [5, 10, 20, 30, 60, 120, 250],
    "ema_spans": [12, 26],
    "rsi_periods": [6, 12, 24],
    "macd": {"fast": 12, "slow": 26, "signal": 9},
    "vol_windows": [20, 60, 120],
    "mdd_windows": [20, 60, 120],
    "atr_period": 14,
    "risk_window": 252,
    "risk_free_rate": 0.0,
    "annualization": 252,
    "std_ddof": 1,
}

SUPPORTED_GROUPS = {"returns", "trend", "momentum", "volatility", "risk"}


def normalize_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    result = copy.deepcopy(DEFAULT_CONFIG)
    if config:
        for key, value in config.items():
            if key not in result:
                raise ValueError(f"不支持的指标配置项：{key}")
            result[key] = value
    enabled = result.get("enabled") or []
    if not isinstance(enabled, list) or not enabled:
        raise ValueError("enabled 必须是非空指标组列表")
    unknown = set(enabled) - SUPPORTED_GROUPS
    if unknown:
        raise ValueError(f"未知指标组：{sorted(unknown)}")
    for key in ("return_windows", "ma_windows", "ema_spans", "rsi_periods", "vol_windows", "mdd_windows"):
        values = result.get(key)
        if not isinstance(values, list) or not values:
            raise ValueError(f"{key} 必须是非空列表")
        if any(not isinstance(value, int) or value < 1 for value in values):
            raise ValueError(f"{key} 必须全部为正整数")
    if int(result["atr_period"]) < 1:
        raise ValueError("atr_period 必须为正整数")
    if int(result["risk_window"]) < 2:
        raise ValueError("risk_window 必须 >= 2")
    if int(result["annualization"]) < 1:
        raise ValueError("annualization 必须为正整数")
    if int(result["std_ddof"]) not in (0, 1):
        raise ValueError("std_ddof 只能是 0 或 1")
    if float(result["risk_free_rate"]) <= -1:
        raise ValueError("risk_free_rate 必须大于 -1")
    for key in ("fast", "slow", "signal"):
        if int(result["macd"][key]) < 1:
            raise ValueError(f"macd.{key} 必须为正整数")
    return result


def config_json(config: dict[str, Any]) -> str:
    return json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def config_hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(config_json(config).encode("utf-8")).hexdigest()[:12]


def calculation_version(config: dict[str, Any]) -> str:
    return f"v{ENGINE_VERSION}-{config_hash(config)}"
