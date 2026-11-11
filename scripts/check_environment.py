"""依赖环境检查：Python 版本、虚拟环境、核心依赖与 SQLite。"""
from __future__ import annotations

import importlib
import importlib.metadata
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULT_PATH = PROJECT_ROOT / "logs" / "environment_check.json"
PACKAGES = [
    "pandas",
    "numpy",
    "fastapi",
    "uvicorn",
    "streamlit",
    "akshare",
    "pytest",
    "httpx",
    "requests",
    "beautifulsoup4",
    "python-dotenv",
]
IMPORT_NAMES = {"beautifulsoup4": "bs4", "python-dotenv": "dotenv"}


def main() -> int:
    result: dict[str, object] = {
        "python_version": sys.version,
        "python_executable": sys.executable,
        "in_virtualenv": sys.prefix != sys.base_prefix,
        "sqlite_version": sqlite3.sqlite_version,
        "packages": {},
        "errors": [],
    }
    for package in PACKAGES:
        try:
            importlib.import_module(IMPORT_NAMES.get(package, package.replace("-", "_")))
            result["packages"][package] = importlib.metadata.version(package)
        except Exception as exc:  # noqa: BLE001 - 检查脚本需要收集全部失败
            result["errors"].append(f"{package}: {type(exc).__name__}: {exc}")

    if sys.version_info < (3, 11):
        result["errors"].append(f"Python 版本过低：{sys.version_info.major}.{sys.version_info.minor}")
    if not result["in_virtualenv"]:
        result["errors"].append("当前不是独立虚拟环境")

    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Python: {sys.version.splitlines()[0]}")
    print(f"Executable: {sys.executable}")
    print(f"Virtualenv: {result['in_virtualenv']}")
    print(f"SQLite: {sqlite3.sqlite_version}")
    for package, version in result["packages"].items():
        print(f"{package}: {version}")
    for error in result["errors"]:
        print(f"ERROR: {error}", file=sys.stderr)
    return 0 if not result["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
