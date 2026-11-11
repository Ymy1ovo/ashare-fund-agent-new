"""回测持久化与 API 测试。"""
from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.backtest.config import BacktestConfig
from app.backtest.engine import BacktestEngine
from app.backtest.metrics import compute_performance
from app.backtest.storage import save_result
from app.backtest.strategies.base import TargetWeight
from app.database.db import get_connection, replace_etf_pool
from app.main import app
from tests.conftest import make_pool_record
from tests.test_backtest_integration import _FixedStrategy, _seed_market


def _run_and_save(temp_db):
    dates = _seed_market(temp_db, {"510300": [10.0, 11.0, 12.0, 13.0]})
    strategy = _FixedStrategy({dates[0]: [TargetWeight("510300", 1.0)]})
    config = BacktestConfig(start_date=dates[0], end_date=dates[-1], initial_cash=100000)
    result = BacktestEngine(config, strategy, db_path=temp_db).run(["510300"], indicator_version=None)
    perf = compute_performance(result.daily, result.trades, result.orders, result.initial_cash)
    saved = save_result(result, perf, db_path=temp_db)
    return result, perf, saved


def test_save_and_read_back(temp_db) -> None:
    result, perf, saved = _run_and_save(temp_db)
    assert saved["reconciliation"]["ok"]
    with get_connection(temp_db) as conn:
        runs = conn.execute("SELECT COUNT(*) FROM backtest_runs").fetchone()[0]
        nav = conn.execute("SELECT COUNT(*) FROM backtest_daily_nav WHERE run_id=?",
                           (result.run_id,)).fetchone()[0]
        trades = conn.execute("SELECT COUNT(*) FROM backtest_trades WHERE run_id=?",
                              (result.run_id,)).fetchone()[0]
    assert runs == 1
    assert nav == len(result.daily)
    assert trades == len(result.trades)


def test_save_is_idempotent(temp_db) -> None:
    result, perf, _ = _run_and_save(temp_db)
    save_result(result, perf, db_path=temp_db)
    save_result(result, perf, db_path=temp_db)
    with get_connection(temp_db) as conn:
        runs = conn.execute("SELECT COUNT(*) FROM backtest_runs").fetchone()[0]
        nav = conn.execute("SELECT COUNT(*) FROM backtest_daily_nav WHERE run_id=?",
                           (result.run_id,)).fetchone()[0]
    assert runs == 1
    assert nav == len(result.daily)


def test_backtest_api_endpoints(temp_db) -> None:
    result, _, _ = _run_and_save(temp_db)
    client = TestClient(app)
    assert client.get("/api/backtests").status_code == 200
    detail = client.get(f"/api/backtests/{result.run_id}")
    assert detail.status_code == 200
    assert detail.json()["run_id"] == result.run_id
    nav = client.get(f"/api/backtests/{result.run_id}/nav")
    assert nav.status_code == 200
    assert len(nav.json()["items"]) == len(result.daily)
    trades = client.get(f"/api/backtests/{result.run_id}/trades")
    assert trades.status_code == 200
    assert len(trades.json()["items"]) == len(result.trades)
    orders = client.get(f"/api/backtests/{result.run_id}/orders")
    assert orders.status_code == 200
    positions = client.get(f"/api/backtests/{result.run_id}/positions")
    assert positions.status_code == 200
    assert client.get("/api/backtests/not-exist").status_code == 404
    assert client.get("/api/backtests/not-exist/nav").status_code == 404
