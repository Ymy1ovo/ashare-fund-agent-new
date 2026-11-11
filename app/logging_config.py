"""统一日志配置：控制台 + 文件。"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.config import ensure_runtime_dirs, settings

_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def setup_logging(log_file_name: str = "app.log") -> None:
    """初始化根日志；重复调用不会叠加 Handler。"""
    ensure_runtime_dirs()
    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.log_level, logging.INFO))

    if getattr(root, "_fund_agent_configured", False):
        return

    formatter = logging.Formatter(_LOG_FORMAT)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        settings.log_dir / log_file_name,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    root._fund_agent_configured = True  # type: ignore[attr-defined]
