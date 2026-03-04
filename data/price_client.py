"""
Price Data Client for ATLAS
Uses yfinance (free, no API key) for historical and current prices.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)


class PriceClient:
    def __init__(self):
        self._cache = {}

    def get_current_price(self, ticker: str) -> Optional[float]:
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="1d")
            if hist.empty:
                hist = stock.history(period="5d")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
            return None
        except Exception as e:
            logger.error(f"Price fetch failed for {ticker}: {e}")
            return None

    def get_price_history(self, ticker: str, days: int = 365) -> Optional[pd.DataFrame]:
        try:
            stock = yf.Ticker(ticker)
            start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            hist = stock.history(start=start)
            return hist if not hist.empty else None
        except Exception as e:
            logger.error(f"History fetch failed for {ticker}: {e}")
            return None

    def get_bulk_prices(self, tickers: list[str]) -> dict[str, float]:
        prices = {}
        try:
            data = yf.download(tickers, period="1d", group_by="ticker", progress=False, threads=True)
            for ticker in tickers:
                try:
                    if len(tickers) == 1:
                        price = float(data["Close"].iloc[-1])
                    else:
                        price = float(data[ticker]["Close"].iloc[-1])
                    prices[ticker] = price
                except (KeyError, IndexError):
                    pass
        except Exception as e:
            logger.error(f"Bulk price fetch failed: {e}")
        for ticker in tickers:
            if ticker not in prices:
                price = self.get_current_price(ticker)
                if price:
                    prices[ticker] = price
        return prices

    def get_market_cap(self, ticker: str) -> Optional[float]:
        try:
            return yf.Ticker(ticker).info.get("marketCap")
        except Exception:
            return None

    def get_sector_info(self, ticker: str) -> dict:
        try:
            info = yf.Ticker(ticker).info
            return {
                "sector": info.get("sector", "Unknown"),
                "industry": info.get("industry", "Unknown"),
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "dividend_yield": info.get("dividendYield"),
                "beta": info.get("beta"),
                "52w_high": info.get("fiftyTwoWeekHigh"),
                "52w_low": info.get("fiftyTwoWeekLow"),
            }
        except Exception as e:
            logger.error(f"Sector info failed for {ticker}: {e}")
            return {}

    def get_returns(self, ticker: str, days: int = 30) -> Optional[float]:
        """Calculate return over N days."""
        try:
            hist = self.get_price_history(ticker, days + 5)
            if hist is not None and len(hist) >= 2:
                start_price = float(hist["Close"].iloc[0])
                end_price = float(hist["Close"].iloc[-1])
                return (end_price - start_price) / start_price
            return None
        except Exception as e:
            logger.error(f"Returns calc failed for {ticker}: {e}")
            return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    client = PriceClient()
    print("--- Current Prices ---")
    prices = client.get_bulk_prices(["NVDA", "AMD", "INTC", "AVGO", "TSM"])
    for ticker, price in prices.items():
        print(f"  {ticker}: ${price:.2f}")
    print("\n--- NVDA Sector Info ---")
    info = client.get_sector_info("NVDA")
    for k, v in info.items():
        print(f"  {k}: {v}")
    print("\n--- NVDA 30-day Return ---")
    ret = client.get_returns("NVDA", 30)
    if ret:
        print(f"  {ret*100:.2f}%")
