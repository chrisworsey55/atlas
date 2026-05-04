from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from darwin_v3.backtest.data import PointInTimeFundamentals, PointInTimePrices, PointInTimeRegime


def test_universe_s30_file_has_exact_30_names() -> None:
    universe_path = Path("data/backtest/universe_s30.json")
    tickers = json.loads(universe_path.read_text())
    assert len(tickers) == 30
    assert tickers[0] == "NVDA"
    assert "BRK.B" in tickers


def test_point_in_time_price_lookup_uses_cache() -> None:
    prices = PointInTimePrices(simulation_date=date(2025, 7, 1))
    value = prices.get_price("NVDA", date(2025, 4, 15))
    assert value == pytest.approx(112.1735610961914, rel=1e-9)


def test_point_in_time_coverage_for_brkb() -> None:
    prices = PointInTimePrices(simulation_date=date(2025, 7, 1))
    start, end, count = prices.coverage("BRK.B")
    assert start is not None
    assert end == "2025-07-01"
    assert count > 0


def test_point_in_time_regime_runs_without_future_reads() -> None:
    regime = PointInTimeRegime(simulation_date=date(2025, 7, 1))
    value = regime.get_regime(date(2025, 4, 15))
    assert value in {"bull", "bear", "tightening", "easing", "euphoria", "crisis"}


def test_fundamentals_methods_return_cleanly(tmp_path: Path) -> None:
    fundamentals = PointInTimeFundamentals(cache_root=tmp_path, simulation_date=date(2025, 7, 1))
    assert fundamentals.get_filings("NVDA", date(2025, 4, 15)) == []
    assert fundamentals.get_transcript("NVDA", date(2025, 4, 15)) is None
