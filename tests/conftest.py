from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.database.db as db_module
from app.config import settings


@pytest.fixture(scope="session", autouse=True)
def production_db_guard():
    """防止测试误写正式数据库；测试结束若 mtime/size 变化则直接失败。"""
    db_path = settings.database_path
    before = (db_path.stat().st_mtime_ns, db_path.stat().st_size) if db_path.exists() else None
    yield
    after = (db_path.stat().st_mtime_ns, db_path.stat().st_size) if db_path.exists() else None
    assert before == after, f"测试修改了正式数据库：{db_path}，before={before}, after={after}"


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_market.db"
    monkeypatch.setattr(db_module, "settings", SimpleNamespace(database_path=db_path))
    db_module.init_db(db_path=db_path)
    return db_path


def make_pool_record(code: str = "510300", name: str = "测试ETF") -> dict:
    return {
        "code": code,
        "name": name,
        "category": "宽基指数ETF",
        "fund_type": "指数型-股票",
        "tracking_index": "测试指数",
        "established_date": "2012-05-04",
        "listing_date": "2012-05-28",
        "listing_date_source": "测试",
        "last_trade_date": "2024-01-03",
        "history_rows": 2,
        "latest_price": 1.2,
        "data_source": "test",
        "source_tested_at": "2024-01-03T15:00:00",
        "status": "active",
    }
