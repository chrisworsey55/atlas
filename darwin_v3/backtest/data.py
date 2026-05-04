"""Point-in-time data access for Darwin v3 backtests."""

from __future__ import annotations

from dataclasses import dataclass
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import REPO_ROOT


@dataclass(frozen=True)
class Filing:
    filing_date: str
    ticker: str
    form_type: str
    accession: str | None = None
    period_end: str | None = None
    published_at: str | None = None
    payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class Transcript:
    published_at: str
    ticker: str
    quarter: str | None = None
    year: int | None = None
    payload: dict[str, Any] | None = None


class PointInTimePrices:
    def __init__(
        self,
        cache_root: Path | None = None,
        universe_file: Path | None = None,
        simulation_date: date | None = None,
    ) -> None:
        self.repo_root = REPO_ROOT
        self.cache_root = cache_root or (self.repo_root / "data" / "backtest" / "cache" / "prices")
        self.universe_file = universe_file or (self.repo_root / "data" / "backtest" / "universe_s30.json")
        self.simulation_date = simulation_date or datetime.now(tz=UTC).date()

    def get_price(self, ticker: str, date_: date) -> float:
        if date_ > self.simulation_date:
            raise ValueError(f"Cannot fetch future price for {ticker} on {date_.isoformat()} beyond simulation date {self.simulation_date.isoformat()}")
        payload = self._load_payload(ticker)
        price_map = self._price_map(payload)
        value = self._extract_close(price_map.get(date_.isoformat()))
        if value is None:
            raise KeyError(f"No cached price for {ticker} on {date_.isoformat()}")
        return value

    def get_returns(self, ticker: str, start: date, end: date) -> pd.Series:
        if end > self.simulation_date:
            raise ValueError(f"Cannot fetch returns beyond simulation date {self.simulation_date.isoformat()}")
        payload = self._load_payload(ticker)
        price_map = self._price_map(payload)
        items = []
        for key in sorted(price_map):
            current = date.fromisoformat(key)
            if start <= current <= end:
                close = self._extract_close(price_map[key])
                if close is not None:
                    items.append((key, close))
        if not items:
            return pd.Series(dtype=float)
        series = pd.Series({k: v for k, v in items}, dtype=float).sort_index()
        return series.pct_change().dropna()

    def get_universe(self, as_of: date | None = None) -> list[str]:
        if not self.universe_file.exists():
            return []
        data = json.loads(self.universe_file.read_text())
        if isinstance(data, list):
            return [str(item).upper() for item in data]
        if isinstance(data, dict):
            tickers = data.get("tickers", [])
            return [str(item).upper() for item in tickers if item]
        return []

    def coverage(self, ticker: str) -> tuple[str | None, str | None, int]:
        payload = self._load_payload(ticker)
        price_map = self._price_map(payload)
        keys = sorted(price_map)
        return (keys[0] if keys else None, keys[-1] if keys else None, len(keys))

    def _price_paths(self, ticker: str) -> list[Path]:
        return [
            self.cache_root / f"{ticker}.json",
            self.cache_root / ticker / "prices.json",
            self.cache_root / ticker / "price_history.json",
            self.cache_root / ticker / "data.json",
        ]

    def _load_payload(self, ticker: str) -> Any:
        for path in self._price_paths(ticker):
            if path.exists():
                return json.loads(path.read_text())
        raise FileNotFoundError(f"No cached price payload for {ticker}")

    def _price_map(self, payload: Any) -> dict[str, Any]:
        if isinstance(payload, dict):
            if "prices" in payload and isinstance(payload["prices"], dict):
                return payload["prices"]
            return payload
        if isinstance(payload, list):
            mapped: dict[str, Any] = {}
            for item in payload:
                if isinstance(item, dict) and item.get("date"):
                    mapped[str(item["date"])] = item
            return mapped
        return {}

    def _extract_close(self, row: Any) -> float | None:
        if not isinstance(row, dict):
            return None
        for key in ("adjClose", "close", "c"):
            value = row.get(key)
            if isinstance(value, (int, float)):
                return float(value)
        return None


class PointInTimeFundamentals:
    def __init__(
        self,
        cache_root: Path | None = None,
        simulation_date: date | None = None,
    ) -> None:
        self.repo_root = REPO_ROOT
        self.cache_root = cache_root or (self.repo_root / "data" / "backtest" / "cache" / "fundamentals")
        self.simulation_date = simulation_date or datetime.now(tz=UTC).date()

    def get_filings(self, ticker: str, before_date: date) -> list[Filing]:
        payload = self._load_payload(ticker)
        filings = payload.get("filings", []) if isinstance(payload, dict) else []
        results: list[Filing] = []
        for item in filings:
            filing_date = str(item.get("filing_date") or item.get("date") or item.get("acceptedDate", ""))[:10]
            if filing_date and filing_date < before_date.isoformat():
                results.append(
                    Filing(
                        filing_date=filing_date,
                        ticker=ticker.upper(),
                        form_type=str(item.get("form_type") or item.get("form") or item.get("type") or ""),
                        accession=item.get("accession"),
                        period_end=item.get("period_end") or item.get("period"),
                        published_at=item.get("published_at"),
                        payload=item,
                    )
                )
        return results

    def get_transcript(self, ticker: str, before_date: date) -> Transcript | None:
        payload = self._load_payload(ticker)
        transcripts = payload.get("transcripts", []) if isinstance(payload, dict) else []
        best: dict[str, Any] | None = None
        for item in transcripts:
            published_at = str(item.get("published_at") or item.get("date") or "")[:10]
            if published_at and published_at < before_date.isoformat():
                if best is None or published_at > str(best.get("published_at") or best.get("date") or "")[:10]:
                    best = item
        if best is None:
            return None
        return Transcript(
            published_at=str(best.get("published_at") or best.get("date") or "")[:10],
            ticker=ticker.upper(),
            quarter=str(best.get("quarter")) if best.get("quarter") is not None else None,
            year=int(best["year"]) if best.get("year") is not None else None,
            payload=best,
        )

    def _load_payload(self, ticker: str) -> dict[str, Any]:
        for path in [self.cache_root / f"{ticker}.json", self.cache_root / ticker / "fundamentals.json"]:
            if path.exists():
                data = json.loads(path.read_text())
                return data if isinstance(data, dict) else {}
        return {}


class PointInTimeRegime:
    def __init__(
        self,
        prices: PointInTimePrices | None = None,
        macro_cache: Path | None = None,
        simulation_date: date | None = None,
    ) -> None:
        self.prices = prices or PointInTimePrices(simulation_date=simulation_date)
        self.repo_root = REPO_ROOT
        self.macro_cache = macro_cache or (self.repo_root / "data" / "backtest" / "cache" / "macro" / "fred_data.json")
        self.simulation_date = simulation_date or datetime.now(tz=UTC).date()

    def get_regime(self, date_: date) -> str:
        if date_ > self.simulation_date:
            raise ValueError(f"Cannot classify future regime for {date_.isoformat()} beyond simulation date {self.simulation_date.isoformat()}")
        if date_ <= date.fromisoformat("2025-03-01"):
            pivot_date = date_
        else:
            pivot_date = date_ - timedelta(days=1)
        spy_close = self._price_on_or_before("SPY", pivot_date)
        if spy_close is None:
            return "bull"
        ma20 = self._moving_average("SPY", pivot_date, 20)
        ma60 = self._moving_average("SPY", pivot_date, 60)
        ma200 = self._moving_average("SPY", pivot_date, 200)
        vix = self._fred_value("VIXCLS", pivot_date)
        yield10 = self._fred_value("DGS10", pivot_date)
        prev_yield10 = self._fred_value("DGS10", pivot_date - timedelta(days=5))

        if vix is not None and vix >= 30 and ma60 is not None and spy_close < ma60:
            return "crisis"
        if vix is not None and vix <= 18 and ma20 is not None and ma60 is not None and ma200 is not None and spy_close > ma20 > ma60 > ma200:
            return "euphoria"
        if yield10 is not None and prev_yield10 is not None and yield10 > prev_yield10 + 0.15:
            return "tightening"
        if yield10 is not None and prev_yield10 is not None and yield10 < prev_yield10 - 0.15:
            return "easing"
        if ma20 is not None and ma60 is not None and ma200 is not None and spy_close > ma20 > ma60 > ma200:
            return "bull"
        if ma200 is not None and spy_close < ma200:
            return "bear"
        return "bull"

    def _price_on_or_before(self, ticker: str, pivot: date) -> float | None:
        try:
            payload = self.prices._load_payload(ticker)
        except FileNotFoundError:
            return None
        price_map = self.prices._price_map(payload)
        for key in sorted(price_map, reverse=True):
            if date.fromisoformat(key) <= pivot:
                return self.prices._extract_close(price_map[key])
        return None

    def _moving_average(self, ticker: str, pivot: date, window: int) -> float | None:
        try:
            payload = self.prices._load_payload(ticker)
        except FileNotFoundError:
            return None
        price_map = self.prices._price_map(payload)
        closes = []
        for key in sorted(price_map):
            current = date.fromisoformat(key)
            if current <= pivot:
                close = self.prices._extract_close(price_map[key])
                if close is not None:
                    closes.append(close)
        if len(closes) < window:
            return None
        return float(sum(closes[-window:]) / window)

    def _fred_value(self, series_name: str, pivot: date) -> float | None:
        if not self.macro_cache.exists():
            return None
        data = json.loads(self.macro_cache.read_text())
        series = (data.get("series") or {}).get(series_name, {})
        values = series.get("values", {}) if isinstance(series, dict) else {}
        best_date: str | None = None
        best_value: float | None = None
        for key, value in values.items():
            try:
                current = date.fromisoformat(key)
            except ValueError:
                continue
            if current <= pivot and isinstance(value, (int, float)):
                if best_date is None or key > best_date:
                    best_date = key
                    best_value = float(value)
        return best_value
