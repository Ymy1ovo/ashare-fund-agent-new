from __future__ import annotations

import json
import zipfile
from pathlib import Path

from app.database.db import init_db
from scripts.package_project import build


def test_source_only_excludes_db_and_logs(tmp_path) -> None:
    zip_path = build("source-only", tmp_path, root=Path.cwd())
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    assert "app/main.py" in names
    assert "dashboard/app.py" in names
    assert "data/etf_pool.csv" in names
    assert "README.md" in names
    assert "CHANGELOG.md" in names
    assert "reports/phase2.2_test_report.md" in names
    assert "data/fund_agent.db" not in names
    assert not any(name.startswith("logs/") for name in names)
    assert not any("__pycache__" in name for name in names)
    assert manifest["mode"] == "source-only"
    assert zip_path.with_suffix(zip_path.suffix + ".sha256").exists()
    assert zip_path.with_suffix(zip_path.suffix + ".manifest.json").exists()


def test_data_snapshot_is_consistent_and_does_not_touch_source(tmp_path) -> None:
    db_path = tmp_path / "source.db"
    init_db(db_path=db_path)
    before = db_path.read_bytes()
    zip_path = build("data-snapshot", tmp_path, root=Path.cwd(), db_path=db_path)
    assert db_path.read_bytes() == before
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        db_bytes = zf.read("data/fund_agent.db")
    assert "data/fund_agent.db" in names
    assert "migrations/phase2_indicators.sql" in names
    assert manifest["database"]["integrity_check"] == "ok"
    assert manifest["database"]["database_sha256"]
    assert len(db_bytes) > 0
    assert zip_path.with_suffix(zip_path.suffix + ".sha256").exists()


def test_full_release_contains_both_packages_and_reports(tmp_path) -> None:
    db_path = tmp_path / "source.db"
    init_db(db_path=db_path)
    zip_path = build("full-release", tmp_path, root=Path.cwd(), db_path=db_path)
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    assert any(name.startswith("packages/source-only/") for name in names)
    assert any(name.startswith("packages/data-snapshot/") for name in names)
    assert "reports/phase2.2_test_report.md" in names
    assert "release/CHANGELOG.md" in names
    assert "release/RELEASE_NOTES.md" in names
    assert manifest["mode"] == "full-release"
    assert zip_path.with_suffix(zip_path.suffix + ".sha256").exists()
