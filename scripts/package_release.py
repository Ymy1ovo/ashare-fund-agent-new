"""生成不含虚拟环境和缓存的交付 ZIP。

用法：
    .venv\\Scripts\\python.exe scripts\\package_release.py
"""
from __future__ import annotations

import sys
import zipfile
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = PROJECT_ROOT / "dist"

EXCLUDE_DIRS = {
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".git",
    "dist",
    "data/backups",
    "data/cache",
}
EXCLUDE_NAMES = {".env"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".zip"}
EXCLUDE_PREFIXES = (
    "pytest-of-",
    "pip-build-tracker-",
    "pip-ephem-wheel-cache-",
    "pip-install-",
    "pip-unpack-",
)


def _included(path: Path) -> bool:
    relative = path.relative_to(PROJECT_ROOT)
    parts = set(relative.parts)
    posix = relative.as_posix()
    if parts & EXCLUDE_DIRS:
        return False
    if posix.startswith(("data/backups/", "data/cache/")):
        return False
    if path.suffix == ".db" and posix != "data/fund_agent.db":
        return False
    if any(part.startswith(EXCLUDE_PREFIXES) for part in relative.parts):
        return False
    if path.name in EXCLUDE_NAMES or path.suffix in EXCLUDE_SUFFIXES:
        return False
    return True


def main() -> int:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d")
    zip_path = DIST_DIR / f"Ashare-Fund-Agent_phase2.2_{timestamp}.zip"
    if zip_path.exists():
        zip_path.unlink()

    files = sorted(
        path for path in PROJECT_ROOT.rglob("*") if path.is_file() and _included(path)
    )
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(PROJECT_ROOT).as_posix())

    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
    forbidden = [
        name
        for name in names
        if ".venv/" in name
        or "__pycache__/" in name
        or name.endswith((".pyc", ".pyo"))
        or name == ".env"
    ]
    if forbidden:
        print(f"打包失败，ZIP 含禁止文件：{forbidden[:10]}", file=sys.stderr)
        return 1
    print(f"zip={zip_path}")
    print(f"files={len(files)} size_mb={zip_path.stat().st_size / 1024 / 1024:.2f}")
    print(f"contains_database={any(name == 'data/fund_agent.db' for name in names)}")
    print(f"contains_pool={any(name == 'data/etf_pool.csv' for name in names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
