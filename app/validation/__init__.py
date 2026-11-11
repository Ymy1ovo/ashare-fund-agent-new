"""阶段3A.2 策略可信度验证体系。

只做验证，不改回测引擎、不改历史数据。
"""
from app.validation.config import (
    ValidationConfig,
    MA_WINDOW_GRID,
    ValidationConfigError,
)

__all__ = ["ValidationConfig", "MA_WINDOW_GRID", "ValidationConfigError"]
