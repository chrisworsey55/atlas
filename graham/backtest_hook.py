from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BacktestResult:
    start_year: int
    end_year: int
    ncav_threshold: float


# TODO: GRAHAM historical backtest
# Methodology:
#   - Pull OTC universe for each year 2010-2025
#   - Calculate NCAV screen at year start
#   - Track 1-year returns for all passing names
#   - Compare to S&P 500 total return
#   - Validate: does buying <0.67x NCAV OTC names
#     outperform the index over 15 years?
# This is the empirical proof of the Buffett playbook.


def run_historical_backtest(
    start_year: int,
    end_year: int,
    ncav_threshold: float = 0.67,
) -> BacktestResult:
    raise NotImplementedError("GRAHAM backtest not yet built")
