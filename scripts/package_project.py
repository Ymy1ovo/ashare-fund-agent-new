"""项目交付打包器：source-only / data-snapshot / full-release。

用法：
    python scripts/package_project.py --mode source-only
    python scripts/package_project.py --mode data-snapshot
    python scripts/package_project.py --mode full-release

数据库快照使用 sqlite3 backup API，不直接复制正在写入的数据库。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "dist"
DEFAULT_DB = PROJECT_ROOT / "data" / "fund_agent.db"

SOURCE_DIRS = ("app", "dashboard", "scripts", "tests", "migrations")
SOURCE_ROOT_FILES = (
    "README.md",
    "requirements.txt",
    ".env.example",
    ".gitignore",
    "CHANGELOG.md",
    "RELEASE_NOTES.md",
)
SOURCE_DATA_WHITELIST = ("data/etf_pool.csv",)
REPORT_SUFFIXES = {".md"}
FORBIDDEN_PARTS = {
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".git",
    "dist",
    "logs",
}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".log", ".db", ".zip", ".env"}
TEMP_PREFIXES = (
    "pytest-of-",
    "pip-build-tracker-",
    "pip-ephem-wheel-cache-",
    "pip-install-",
    "pip-unpack-",
)


class PackageError(RuntimeError):
    pass


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _allowed_path(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    parts = relative.parts
    if any(part in FORBIDDEN_PARTS for part in parts):
        return False
    if any(part.startswith(TEMP_PREFIXES) for part in parts):
        return False
    if path.name == ".env" or path.suffix in FORBIDDEN_SUFFIXES:
        return False
    return True


def collect_source_files(root: Path = PROJECT_ROOT) -> list[Path]:
    files: set[Path] = set()
    for directory in SOURCE_DIRS:
        base = root / directory
        if not base.exists():
            raise PackageError(f"缺少源码目录：{directory}")
        for path in base.rglob("*"):
            if path.is_file() and _allowed_path(path, root):
                if directory == "migrations" and path.suffix != ".sql":
                    continue
                files.add(path)
    for name in SOURCE_ROOT_FILES:
        path = root / name
        if not path.exists():
            raise PackageError(f"缺少必要文件：{name}")
        files.add(path)
    for name in SOURCE_DATA_WHITELIST:
        path = root / name
        if not path.exists():
            raise PackageError(f"缺少必要数据白名单文件：{name}")
        files.add(path)
    reports = root / "reports"
    if reports.exists():
        for path in reports.rglob("*"):
            if path.is_file() and path.suffix in REPORT_SUFFIXES and _allowed_path(path, root):
                files.add(path)
    return sorted(files)


def _manifest_files(files: Iterable[tuple[str, Path]]) -> list[dict]:
    result = []
    for arcname, path in files:
        result.append(
            {
                "path": arcname,
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return result


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _zip_add(zf: zipfile.ZipFile, arcname: str, path: Path) -> None:
    zf.write(path, arcname)


def _verify_zip(zip_path: Path, required: Iterable[str]) -> None:
    if not zip_path.exists() or zip_path.stat().st_size == 0:
        raise PackageError(f"ZIP 未生成或为空：{zip_path}")
    with zipfile.ZipFile(zip_path) as zf:
        bad = zf.testzip()
        if bad:
            raise PackageError(f"ZIP 损坏：{bad}")
        names = set(zf.namelist())
        missing = set(required) - names
        if missing:
            raise PackageError(f"ZIP 缺少必要条目：{sorted(missing)}")
        forbidden = [
            name
            for name in names
            if name == ".env"
            or "__pycache__/" in name
            or name.endswith((".pyc", ".pyo"))
            or name.startswith(("logs/", "data/backups/", "pytest-of-"))
        ]
        if forbidden:
            raise PackageError(f"ZIP 包含禁止文件：{forbidden[:5]}")


def _finalize(
    zip_path: Path,
    manifest: dict,
    mode: str,
    output_dir: Path,
) -> dict:
    manifest["archive"] = zip_path.name
    manifest["archive_size"] = zip_path.stat().st_size
    _verify_zip(zip_path, ["manifest.json"])
    digest = sha256_file(zip_path)
    manifest["archive_sha256"] = digest
    sidecar = zip_path.with_suffix(zip_path.suffix + ".manifest.json")
    _write_json(sidecar, manifest)
    zip_path.with_suffix(zip_path.suffix + ".sha256").write_text(
        f"{digest}  {zip_path.name}\n", encoding="utf-8"
    )
    print(f"mode={mode} zip={zip_path}")
    print(f"files={manifest['file_count']} size_bytes={manifest['total_size']} zip_bytes={zip_path.stat().st_size}")
    print(f"sha256={digest}")
    print(f"manifest={sidecar}")
    return manifest


def build_source_package(
    output_dir: Path = DEFAULT_OUTPUT,
    *,
    root: Path = PROJECT_ROOT,
    timestamp: str | None = None,
) -> Path:
    timestamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    files = collect_source_files(root)
    total = sum(path.stat().st_size for path in files)
    print(f"[source-only] files={len(files)} estimated_size={total}")
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f"Ashare-Fund-Agent_source-only_{timestamp}.zip"
    if zip_path.exists():
        zip_path.unlink()
    entries = [(path.relative_to(root).as_posix(), path) for path in files]
    try:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for arcname, path in entries:
                _zip_add(zf, arcname, path)
            manifest = {
                "mode": "source-only",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "file_count": len(entries),
                "total_size": total,
                "files": _manifest_files(entries),
            }
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        return zip_path
    except Exception:
        zip_path.unlink(missing_ok=True)
        raise


def _source_shas(entries: list[tuple[str, Path]]) -> dict[str, str]:
    return {arcname: sha256_file(path) for arcname, path in entries}


def build_data_snapshot(
    output_dir: Path = DEFAULT_OUTPUT,
    *,
    root: Path = PROJECT_ROOT,
    db_path: Path | None = None,
    timestamp: str | None = None,
) -> Path:
    timestamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    source_db = Path(db_path) if db_path else root / "data" / "fund_agent.db"
    if not source_db.exists():
        raise PackageError(f"数据库不存在：{source_db}")
    print(f"[data-snapshot] db={source_db} db_size={source_db.stat().st_size}")
    source_hash_before = sha256_file(source_db)
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f"Ashare-Fund-Agent_data-snapshot_{timestamp}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with tempfile.TemporaryDirectory(prefix="dsh-snapshot-") as tmp:
        temp_db = Path(tmp) / "fund_agent.db"
        source_conn = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)
        target_conn = sqlite3.connect(temp_db)
        try:
            source_conn.backup(target_conn)
        finally:
            source_conn.close()
            target_conn.close()
        integrity_conn = sqlite3.connect(temp_db)
        try:
            integrity = integrity_conn.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            integrity_conn.close()
        if integrity != "ok":
            raise PackageError(f"数据库快照 integrity_check 失败：{integrity}")
        conn = sqlite3.connect(temp_db)
        conn.row_factory = sqlite3.Row
        try:
            counts = {
                "etf_pool": conn.execute("SELECT COUNT(*) FROM etf_pool").fetchone()[0],
                "market_rows": conn.execute("SELECT COUNT(*) FROM etf_daily_prices").fetchone()[0],
                "indicator_rows": conn.execute("SELECT COUNT(*) FROM etf_indicator_daily").fetchone()[0],
                "current_adjustment_snapshots": conn.execute(
                    "SELECT COUNT(*) FROM etf_adjustment_snapshots WHERE is_current=1"
                ).fetchone()[0],
                "adjustment_snapshots_total": conn.execute(
                    "SELECT COUNT(*) FROM etf_adjustment_snapshots"
                ).fetchone()[0],
                "indicator_runs": conn.execute("SELECT COUNT(*) FROM indicator_runs").fetchone()[0],
            }
            latest_version = conn.execute(
                "SELECT calculation_version FROM indicator_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            tables = [
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
            ]
            user_version = conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()
        db_hash = sha256_file(temp_db)
        metadata = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "database_version": f"sqlite_user_version={user_version}; phase=2.2",
            "sqlite_user_version": int(user_version),
            "latest_indicator_version": latest_version[0] if latest_version else None,
            "schema_tables": tables,
            "counts": counts,
            "integrity_check": integrity,
            "database_sha256": db_hash,
            "database_size": temp_db.stat().st_size,
            "source_database": str(source_db),
            "source_database_sha256_before": source_hash_before,
            "migrations": sorted(
                str(path.relative_to(root)) for path in (root / "migrations").rglob("*.sql")
            ),
        }
        migrations = sorted((root / "migrations").rglob("*.sql"))
        entries = [("data/fund_agent.db", temp_db)]
        entries += [("migrations/" + path.relative_to(root / "migrations").as_posix(), path) for path in migrations]
        manifest = {
            "mode": "data-snapshot",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "database": metadata,
            "file_count": len(entries),
            "total_size": sum(path.stat().st_size for _, path in entries),
            "files": _manifest_files(entries),
        }
        try:
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for arcname, path in entries:
                    _zip_add(zf, arcname, path)
                zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        except Exception:
            zip_path.unlink(missing_ok=True)
            raise
    source_hash_after = sha256_file(source_db)
    if source_hash_before != source_hash_after:
        raise PackageError("备份期间源数据库发生变化，快照不可信")
    _verify_zip(zip_path, ["data/fund_agent.db", "manifest.json"])
    return zip_path


def build_full_release(
    output_dir: Path = DEFAULT_OUTPUT,
    *,
    root: Path = PROJECT_ROOT,
    db_path: Path | None = None,
    timestamp: str | None = None,
) -> Path:
    timestamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    print("[full-release] 先构建 source-only，再构建 data-snapshot，最后封装里程碑包")
    source_zip = build_source_package(output_dir, root=root, timestamp=timestamp)
    data_zip = build_data_snapshot(output_dir, root=root, db_path=db_path, timestamp=timestamp)
    output_dir.mkdir(parents=True, exist_ok=True)
    full_zip = output_dir / f"Ashare-Fund-Agent_full-release_{timestamp}.zip"
    if full_zip.exists():
        full_zip.unlink()
    reports = [
        root / "reports" / "phase2.2_test_report.md",
        root / "reports" / "phase2_indicator_quality.md",
        root / "reports" / "phase2.2_risk_comparison.md",
        root / "reports" / "phase2.2_spot_check.md",
    ]
    root_files = [root / "README.md", root / "CHANGELOG.md", root / "RELEASE_NOTES.md"]
    entries: list[tuple[str, Path]] = [
        (f"packages/source-only/{source_zip.name}", source_zip),
        (f"packages/data-snapshot/{data_zip.name}", data_zip),
    ]
    entries += [("reports/" + path.name, path) for path in reports if path.exists()]
    entries += [("release/" + path.name, path) for path in root_files if path.exists()]
    try:
        with zipfile.ZipFile(full_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for arcname, path in entries:
                _zip_add(zf, arcname, path)
            manifest = {
                "mode": "full-release",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "source_package": source_zip.name,
                "data_snapshot_package": data_zip.name,
                "file_count": len(entries),
                "total_size": sum(path.stat().st_size for _, path in entries),
                "files": _manifest_files(entries),
            }
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    except Exception:
        full_zip.unlink(missing_ok=True)
        raise
    _verify_zip(full_zip, ["packages/source-only/" + source_zip.name, "packages/data-snapshot/" + data_zip.name, "manifest.json"])
    return full_zip


def build(mode: str, output_dir: Path = DEFAULT_OUTPUT, *, root: Path = PROJECT_ROOT, db_path: Path | None = None) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if mode == "source-only":
        path = build_source_package(output_dir, root=root, timestamp=timestamp)
    elif mode == "data-snapshot":
        path = build_data_snapshot(output_dir, root=root, db_path=db_path, timestamp=timestamp)
    elif mode == "full-release":
        path = build_full_release(output_dir, root=root, db_path=db_path, timestamp=timestamp)
    else:
        raise PackageError(f"未知模式：{mode}")
    # 为单一模式生成外层 manifest/sha；full-release 的 components 也各自有。
    if mode == "source-only":
        files = collect_source_files(root)
        entries = [(p.relative_to(root).as_posix(), p) for p in files]
        manifest = {
            "mode": "source-only",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "file_count": len(entries),
            "total_size": sum(p.stat().st_size for _, p in entries),
            "files": _manifest_files(entries),
        }
    elif mode == "data-snapshot":
        with zipfile.ZipFile(path) as zf:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    else:
        with zipfile.ZipFile(path) as zf:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    _finalize(path, manifest, mode, output_dir)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="项目交付打包器")
    parser.add_argument("--mode", choices=("source-only", "data-snapshot", "full-release"), default="source-only")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--db", default=None, help="数据库路径，默认 data/fund_agent.db")
    args = parser.parse_args()
    try:
        build(
            args.mode,
            output_dir=Path(args.output_dir),
            root=PROJECT_ROOT,
            db_path=Path(args.db) if args.db else None,
        )
    except Exception as exc:
        print(f"PACKAGE FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
