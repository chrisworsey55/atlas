from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import requests
import yfinance as yf

from graham.config import MIN_AVG_DAILY_VOLUME_DOLLARS, POLYGON_API_KEY


@dataclass
class PriceData:
    ticker: str
    source: str
    current_price: float | None = None
    avg_daily_volume: float | None = None
    avg_daily_volume_shares: float | None = None
    market_cap: float | None = None
    days_to_build_500k_position: int | None = None
    asof_date: str | None = None
    data_quality: str = "UNKNOWN"
    error: str | None = None

    def is_liquid(self) -> bool:
        return bool(self.avg_daily_volume and self.avg_daily_volume >= MIN_AVG_DAILY_VOLUME_DOLLARS)


class PriceClient:
    def __init__(self, polygon_api_key: str = POLYGON_API_KEY):
        self.polygon_api_key = polygon_api_key

    def get_price(self, ticker: str) -> PriceData:
        data = self._from_yfinance(ticker)
        if data.current_price and data.avg_daily_volume is not None:
            return data
        fallback = self._from_polygon(ticker)
        if fallback.current_price:
            return fallback
        return data if data.error else fallback

    def get_prices(self, tickers: Iterable[str]) -> dict[str, PriceData]:
        return {ticker: self.get_price(ticker) for ticker in tickers}

    def _from_yfinance(self, ticker: str) -> PriceData:
        try:
            hist = yf.download(ticker, period="45d", progress=False, auto_adjust=False, threads=False)
            if hist is None or hist.empty:
                return PriceData(ticker=ticker, source="yfinance", data_quality="NO_PRICE", error="no rows")
            close = hist["Close"].dropna()
            volume = hist["Volume"].dropna()
            if close.empty or volume.empty:
                return PriceData(ticker=ticker, source="yfinance", data_quality="NO_PRICE", error="missing close/volume")
            dollars = (hist["Close"] * hist["Volume"]).dropna()
            avg_dollars = self._scalar(dollars.tail(30).mean()) if not dollars.empty else 0.0
            avg_shares = self._scalar(volume.tail(30).mean()) if not volume.empty else 0.0
            price = self._scalar(close.iloc[-1])
            market_cap = None
            try:
                info = yf.Ticker(ticker).fast_info
                market_cap = float(info.get("market_cap")) if info and info.get("market_cap") else None
            except Exception:
                market_cap = None
            return PriceData(
                ticker=ticker,
                source="yfinance",
                current_price=price,
                avg_daily_volume=avg_dollars,
                avg_daily_volume_shares=avg_shares,
                market_cap=market_cap,
                days_to_build_500k_position=self.days_to_build(avg_dollars),
                asof_date=datetime.now(timezone.utc).date().isoformat(),
                data_quality="OK" if avg_dollars > 0 else "ILLIQUID",
            )
        except Exception as exc:
            return PriceData(ticker=ticker, source="yfinance", data_quality="ERROR", error=f"{type(exc).__name__}: {exc}")

    def _from_polygon(self, ticker: str) -> PriceData:
        if not self.polygon_api_key:
            return PriceData(ticker=ticker, source="polygon", data_quality="NO_KEY", error="missing polygon key")
        try:
            to_date = datetime.now(timezone.utc).date().isoformat()
            url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/2026-01-01/{to_date}"
            resp = requests.get(
                url,
                params={"adjusted": "true", "sort": "desc", "limit": 30, "apiKey": self.polygon_api_key},
                timeout=20,
            )
            if not resp.ok:
                return PriceData(ticker=ticker, source="polygon", data_quality="ERROR", error=f"HTTP {resp.status_code}: {resp.text[:100]}")
            payload = resp.json()
            bars = payload.get("results") or []
            if not bars:
                return PriceData(ticker=ticker, source="polygon", data_quality="NO_PRICE", error="no bars")
            avg_dollars = sum(float(bar.get("c", 0)) * float(bar.get("v", 0)) for bar in bars) / len(bars)
            avg_shares = sum(float(bar.get("v", 0)) for bar in bars) / len(bars)
            price = float(bars[0].get("c", 0))
            time.sleep(0.25)
            return PriceData(
                ticker=ticker,
                source="polygon",
                current_price=price,
                avg_daily_volume=avg_dollars,
                avg_daily_volume_shares=avg_shares,
                days_to_build_500k_position=self.days_to_build(avg_dollars),
                asof_date=datetime.now(timezone.utc).date().isoformat(),
                data_quality="OK" if avg_dollars > 0 else "ILLIQUID",
            )
        except Exception as exc:
            return PriceData(ticker=ticker, source="polygon", data_quality="ERROR", error=f"{type(exc).__name__}: {exc}")

    @staticmethod
    def days_to_build(avg_dollars: float | None, position_size: float = 500_000) -> int | None:
        if not avg_dollars or avg_dollars <= 0:
            return None
        capacity = avg_dollars * 0.20
        return int(math.ceil(position_size / capacity)) if capacity > 0 else None

    @staticmethod
    def _scalar(value) -> float:
        if hasattr(value, "iloc"):
            value = value.iloc[0]
        return float(value)
