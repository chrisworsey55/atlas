"""Equities data adapter for Darwin v2.

Uses the same cached Polygon OHLCV shape as `agents/backtest_loop.py`:
`data/backtest/cache/prices/{TICKER}.json`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from darwin_v2.config import REPO_ROOT
from darwin_v2.fitness import score_forecast_probability


ForecastKind = Literal["binary", "threshold_binary", "multi_class"]


@dataclass(frozen=True)
class OHLCVBar:
    ticker: str
    date: str
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: float


@dataclass(frozen=True)
class EquityForecast:
    agent_id: str
    role: str
    ticker: str
    issued_date: str
    horizon_days: int
    kind: ForecastKind
    probability: float | None = None
    threshold_pct: float | None = None
    bucket_probabilities: dict[str, float] | None = None
    rationale: str = ""


@dataclass(frozen=True)
class ResolvedEquityForecast:
    forecast: EquityForecast
    entry_date: str
    exit_date: str
    entry_close: float
    exit_close: float
    return_pct: float
    outcome: int | str
    score: float


class EquitiesAdapter:
    """Loads OHLCV, formats context, resolves forecasts, and scores outcomes."""

    def __init__(self, price_dir: Path | None = None) -> None:
        self.price_dir = price_dir or REPO_ROOT / "data" / "backtest" / "cache" / "prices"
        self._cache: dict[str, dict[str, OHLCVBar]] = {}

    def load_ohlcv(self, ticker: str) -> dict[str, OHLCVBar]:
        ticker = ticker.upper()
        if ticker in self._cache:
            return self._cache[ticker]
        path = self.price_dir / f"{ticker}.json"
        if not path.exists():
            self._cache[ticker] = {}
            return {}
        raw = json.loads(path.read_text())
        bars: dict[str, OHLCVBar] = {}
        for date, bar in raw.get("prices", {}).items():
            close = float(bar.get("close") or bar.get("adjClose") or 0.0)
            adj_close = float(bar.get("adjClose") or close)
            bars[date] = OHLCVBar(
                ticker=ticker,
                date=date,
                open=float(bar.get("open") or close),
                high=float(bar.get("high") or close),
                low=float(bar.get("low") or close),
                close=close,
                adj_close=adj_close,
                volume=float(bar.get("volume") or 0.0),
            )
        self._cache[ticker] = bars
        return bars

    def fetch_missing_with_atlas_cache(self, tickers: list[str], start_date: str, end_date: str) -> list[str]:
        """Use ATLAS DataCache/Polygon fetcher for missing local price files."""
        missing = [ticker.upper() for ticker in tickers if not (self.price_dir / f"{ticker.upper()}.json").exists()]
        if not missing:
            return []
        from agents.backtest_loop import DataCache

        cache = DataCache()
        failed: list[str] = []
        for ticker in missing:
            if not cache.fetch_historical_prices(ticker, start_date, end_date):
                failed.append(ticker)
        return failed

    def available_tickers(self, tickers: list[str], start_date: str, end_date: str) -> list[str]:
        available: list[str] = []
        for ticker in tickers:
            bars = self.load_ohlcv(ticker)
            if any(start_date <= date <= end_date for date in bars):
                available.append(ticker.upper())
        return available

    def trading_dates(self, tickers: list[str], start_date: str, end_date: str) -> list[str]:
        dates: set[str] = set()
        for ticker in tickers:
            dates.update(date for date in self.load_ohlcv(ticker) if start_date <= date <= end_date)
        return sorted(dates)

    def format_context(self, ticker: str, date: str, lookback: int = 5) -> dict[str, object]:
        bars = self.load_ohlcv(ticker)
        dates = sorted(d for d in bars if d <= date)
        if not dates:
            raise ValueError(f"No OHLCV data for {ticker} on or before {date}")
        recent_dates = dates[-lookback:]
        recent = [bars[d] for d in recent_dates]
        last = recent[-1]
        first = recent[0]
        trailing_return = (last.adj_close - first.adj_close) / first.adj_close if first.adj_close else 0.0
        return {
            "ticker": ticker.upper(),
            "as_of": last.date,
            "close": last.adj_close,
            "trailing_return": trailing_return,
            "avg_volume": sum(bar.volume for bar in recent) / len(recent),
            "recent_ohlcv": [bar.__dict__ for bar in recent],
        }

    def resolve_forecast(self, forecast: EquityForecast) -> ResolvedEquityForecast | None:
        bars = self.load_ohlcv(forecast.ticker)
        dates = sorted(d for d in bars if d >= forecast.issued_date)
        if len(dates) <= forecast.horizon_days:
            return None
        entry_date = dates[0]
        exit_date = dates[forecast.horizon_days]
        entry = bars[entry_date].adj_close
        exit_ = bars[exit_date].adj_close
        if entry <= 0:
            return None
        return_pct = (exit_ - entry) / entry

        if forecast.kind == "binary":
            outcome = 1 if exit_ > entry else 0
            score = score_forecast_probability(float(forecast.probability), outcome)
        elif forecast.kind == "threshold_binary":
            threshold = float(forecast.threshold_pct or 0.0) / 100.0
            outcome = 1 if abs(return_pct) > threshold else 0
            score = score_forecast_probability(float(forecast.probability), outcome)
        else:
            outcome = self.return_bucket(return_pct)
            score = self.multiclass_calibration_score(forecast.bucket_probabilities or {}, outcome)

        return ResolvedEquityForecast(
            forecast=forecast,
            entry_date=entry_date,
            exit_date=exit_date,
            entry_close=entry,
            exit_close=exit_,
            return_pct=return_pct,
            outcome=outcome,
            score=score,
        )

    @staticmethod
    def return_bucket(return_pct: float) -> str:
        if return_pct <= -0.03:
            return "down_gt_3pct"
        if return_pct < 0.0:
            return "down_0_3pct"
        if return_pct < 0.03:
            return "up_0_3pct"
        return "up_gt_3pct"

    @staticmethod
    def multiclass_calibration_score(probabilities: dict[str, float], outcome: str) -> float:
        buckets = ("down_gt_3pct", "down_0_3pct", "up_0_3pct", "up_gt_3pct")
        total = sum(max(0.0, float(probabilities.get(bucket, 0.0))) for bucket in buckets)
        if total <= 0:
            probabilities = {bucket: 1.0 / len(buckets) for bucket in buckets}
            total = 1.0
        return sum(((float(probabilities.get(bucket, 0.0)) / total) - (1.0 if bucket == outcome else 0.0)) ** 2 for bucket in buckets)
