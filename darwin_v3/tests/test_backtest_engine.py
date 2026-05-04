from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from darwin_v3.backtest.engine import DarwinV3Backtest, Position


def test_trade_simulator_rejects_oversized_position(tmp_path: Path) -> None:
    engine = DarwinV3Backtest(variant="A", start_date=date(2025, 3, 1), end_date=date(2025, 3, 7), gene_pool_path=tmp_path / "gene_pool_backtest.db")
    with pytest.raises(AssertionError):
        engine.simulator.reject_if_oversized(Position("TEST", 10_000, 100.0, date(2025, 3, 1)), nav=100_000.0, sector_notional=0.0)


def test_information_barriers_raise_on_violation(tmp_path: Path) -> None:
    engine = DarwinV3Backtest(variant="A", start_date=date(2025, 3, 1), end_date=date(2025, 3, 7), gene_pool_path=tmp_path / "gene_pool_backtest.db")
    with pytest.raises(AssertionError):
        engine._assert_no_lookahead(date(2025, 3, 10), date(2025, 3, 7), barrier_days=3, label="postmortem")


def test_dry_run_writes_daily_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import requests

    def _blocked(*args, **kwargs):
        raise AssertionError("network access blocked in dry run")

    monkeypatch.setattr(requests, "get", _blocked)
    engine = DarwinV3Backtest(variant="A", start_date=date(2025, 3, 1), end_date=date(2025, 3, 7), gene_pool_path=tmp_path / "gene_pool_backtest.db")
    summary = engine.run(dry_run_days=5)
    assert summary["trading_days"] == 5
    assert engine.equity_path.exists()
    assert engine.trades_path.exists()
    assert len(engine.daily_rows) == 5
    assert summary["api_cost_usd"] == 0.0
