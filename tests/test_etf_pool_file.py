from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from app.config import settings
from app.data.validators.etf_validator import CATEGORIES

POOL_PATH = settings.etf_pool_path


@pytest.mark.skipif(not POOL_PATH.exists(), reason="尚未生成 data/etf_pool.csv")
def test_pool_file_shape_and_categories() -> None:
    pool = pd.read_csv(POOL_PATH, dtype={"code": str})
    assert 30 <= len(pool) <= 50
    assert pool["code"].nunique() == len(pool)
    assert set(pool["category"]) == set(CATEGORIES)
    assert pool["code"].str.fullmatch(r"\d{6}").all()
    assert pool["name"].notna().all()
    assert pool["data_source"].notna().all()
    assert pool["listing_date"].notna().all()


@pytest.mark.skipif(not POOL_PATH.exists(), reason="尚未生成 data/etf_pool.csv")
def test_pool_dates_are_valid() -> None:
    pool = pd.read_csv(POOL_PATH, dtype={"code": str})
    listing = pd.to_datetime(pool["listing_date"], errors="coerce")
    last_trade = pd.to_datetime(pool["last_trade_date"], errors="coerce")
    assert listing.notna().all()
    assert last_trade.notna().all()
    assert (listing <= last_trade).all()


@pytest.mark.skipif(not POOL_PATH.exists(), reason="尚未生成 data/etf_pool.csv")
def test_pool_has_tracking_index() -> None:
    pool = pd.read_csv(POOL_PATH, dtype={"code": str})
    assert pool["tracking_index"].notna().all()
    assert (pool["tracking_index"].str.len() > 0).all()
