"""项目级配置。

所有路径都相对于项目根目录推导，不依赖本机绝对路径。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"环境变量 {name} 必须是整数，实际为 {raw!r}") from exc


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
    fetch_timeout_seconds: int = _env_int("FETCH_TIMEOUT_SECONDS", 60)
    fetch_max_retries: int = _env_int("FETCH_MAX_RETRIES", 2)
    fetch_max_concurrency: int = _env_int("FETCH_MAX_CONCURRENCY", 1)

    project_root: Path = PROJECT_ROOT
    data_dir: Path = PROJECT_ROOT / "data"
    log_dir: Path = PROJECT_ROOT / "logs"
    report_dir: Path = PROJECT_ROOT / "reports"
    database_path: Path = PROJECT_ROOT / "data" / "fund_agent.db"
    etf_pool_path: Path = PROJECT_ROOT / "data" / "etf_pool.csv"


settings = Settings()


def ensure_runtime_dirs() -> None:
    """确保运行期目录存在。"""
    for path in (settings.data_dir, settings.log_dir, settings.report_dir):
        path.mkdir(parents=True, exist_ok=True)
