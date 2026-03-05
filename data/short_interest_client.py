"""
Short Interest & Borrowing Data Client for ATLAS
Tracks short interest, days to cover, and short % of float.

Short interest tells you where smart money is betting against stocks.
High short interest can indicate:
- Validated bear thesis (smart money agrees stock is overvalued)
- Short squeeze potential (too much crowding)

Data Sources:
- Finviz: Free short interest data
- FINRA: Bi-monthly short interest publication
- yfinance: Basic share statistics
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
import requests
from bs4 import BeautifulSoup

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.universe import UNIVERSE

logger = logging.getLogger(__name__)


class ShortInterestClient:
    """
    Client for tracking short interest and borrowing data.
    """

    FINVIZ_URL = "https://finviz.com/quote.ashx?t={ticker}"

    # Short interest thresholds
    HIGH_SHORT_INTEREST_PCT = 15.0  # >15% short interest is high
    SQUEEZE_RISK_DAYS_TO_COVER = 5.0  # >5 days to cover = squeeze risk
    EXTREME_SHORT_INTEREST_PCT = 25.0  # >25% = extreme, high squeeze potential

    def __init__(self):
        """Initialize short interest client."""
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        })
        self._cache = {}
        self._cache_expiry = {}
        self._cache_ttl = timedelta(hours=6)  # Short interest updates infrequently

    def _get_cached(self, key: str) -> Optional[any]:
        """Get value from cache if not expired."""
        if key in self._cache:
            if datetime.now() < self._cache_expiry.get(key, datetime.min):
                return self._cache[key]
        return None

    def _set_cached(self, key: str, value: any) -> None:
        """Set value in cache with expiry."""
        self._cache[key] = value
        self._cache_expiry[key] = datetime.now() + self._cache_ttl

    def get_short_interest(self, ticker: str) -> dict:
        """
        Get short interest data for a ticker.

        Args:
            ticker: Stock ticker symbol

        Returns:
            Dict with keys: short_interest, short_pct_float, days_to_cover,
            short_pct_shares, float_shares, avg_volume, squeeze_risk
        """
        cache_key = f"short_interest_{ticker}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        result = {
            "ticker": ticker,
            "company_name": UNIVERSE.get(ticker, {}).get("name", ticker),
            "sector": UNIVERSE.get(ticker, {}).get("sector", ""),
            "data_date": datetime.now().strftime("%Y-%m-%d"),
        }

        # Try Finviz first (best source for short interest)
        finviz_data = self._scrape_finviz_short(ticker)
        if finviz_data:
            result.update(finviz_data)

        # Supplement with yfinance data
        if YFINANCE_AVAILABLE:
            yf_data = self._get_yfinance_short(ticker)
            # Only add yf data if finviz didn't have it
            for key, value in yf_data.items():
                if key not in result or result[key] is None:
                    result[key] = value

        # Calculate squeeze risk
        result["squeeze_risk"] = self._assess_squeeze_risk(result)
        result["short_interest_signal"] = self._assess_signal(result)

        self._set_cached(cache_key, result)
        return result

    def _scrape_finviz_short(self, ticker: str) -> Optional[dict]:
        """Scrape short interest data from Finviz."""
        try:
            url = self.FINVIZ_URL.format(ticker=ticker)
            resp = self.session.get(url, timeout=10)
            if resp.status_code != 200:
                return None

            soup = BeautifulSoup(resp.text, "html.parser")

            # Find the snapshot table
            table = soup.find("table", class_="snapshot-table2")
            if not table:
                return None

            data = {}
            cells = table.find_all("td")

            # Parse key-value pairs
            for i in range(0, len(cells) - 1, 2):
                key = cells[i].get_text(strip=True)
                value = cells[i + 1].get_text(strip=True)

                if key == "Short Float":
                    try:
                        data["short_pct_float"] = float(value.replace("%", ""))
                    except:
                        pass
                elif key == "Short Ratio":
                    try:
                        data["days_to_cover"] = float(value)
                    except:
                        pass
                elif key == "Shs Float":
                    try:
                        # Parse values like "1.50B" or "500M"
                        data["float_shares"] = self._parse_number(value)
                    except:
                        pass
                elif key == "Shs Outstand":
                    try:
                        data["shares_outstanding"] = self._parse_number(value)
                    except:
                        pass
                elif key == "Avg Volume":
                    try:
                        data["avg_volume"] = self._parse_number(value)
                    except:
                        pass

            # Calculate short interest shares if we have the data
            if data.get("short_pct_float") and data.get("float_shares"):
                data["short_interest_shares"] = int(data["float_shares"] * data["short_pct_float"] / 100)

            if data:
                data["source"] = "finviz"

            return data if data else None

        except Exception as e:
            logger.debug(f"Finviz scrape error for {ticker}: {e}")
            return None

    def _get_yfinance_short(self, ticker: str) -> dict:
        """Get short interest data from yfinance."""
        if not YFINANCE_AVAILABLE:
            return {}

        try:
            stock = yf.Ticker(ticker)
            info = stock.info

            data = {}

            # Short interest
            if "shortPercentOfFloat" in info:
                data["short_pct_float"] = info["shortPercentOfFloat"] * 100  # Convert to percentage

            if "sharesShort" in info:
                data["short_interest_shares"] = info["sharesShort"]

            if "sharesShortPreviousMonthDate" in info:
                data["short_data_date"] = info["sharesShortPreviousMonthDate"]

            if "shortRatio" in info:
                data["days_to_cover"] = info["shortRatio"]

            if "floatShares" in info:
                data["float_shares"] = info["floatShares"]

            if "sharesOutstanding" in info:
                data["shares_outstanding"] = info["sharesOutstanding"]

            if "averageVolume" in info:
                data["avg_volume"] = info["averageVolume"]

            if "averageVolume10days" in info:
                data["avg_volume_10d"] = info["averageVolume10days"]

            if "currentPrice" in info:
                data["current_price"] = info["currentPrice"]
            elif "regularMarketPrice" in info:
                data["current_price"] = info["regularMarketPrice"]

            if data.get("short_interest_shares") and data.get("current_price"):
                data["short_interest_value"] = data["short_interest_shares"] * data["current_price"]

            if data:
                data["source"] = data.get("source", "yfinance")

            return data

        except Exception as e:
            logger.debug(f"yfinance short interest error for {ticker}: {e}")
            return {}

    def _parse_number(self, value: str) -> float:
        """Parse number strings like '1.5B', '500M', '2.3K'."""
        value = value.strip().upper()

        multipliers = {
            "K": 1_000,
            "M": 1_000_000,
            "B": 1_000_000_000,
            "T": 1_000_000_000_000,
        }

        for suffix, mult in multipliers.items():
            if value.endswith(suffix):
                return float(value[:-1]) * mult

        # Try plain number
        return float(value.replace(",", ""))

    def _assess_squeeze_risk(self, data: dict) -> str:
        """Assess short squeeze risk based on metrics."""
        short_pct = data.get("short_pct_float", 0) or 0
        days_to_cover = data.get("days_to_cover", 0) or 0

        if short_pct >= self.EXTREME_SHORT_INTEREST_PCT and days_to_cover >= self.SQUEEZE_RISK_DAYS_TO_COVER:
            return "HIGH"
        elif short_pct >= self.HIGH_SHORT_INTEREST_PCT or days_to_cover >= self.SQUEEZE_RISK_DAYS_TO_COVER:
            return "MODERATE"
        elif short_pct >= 10:
            return "LOW"
        else:
            return "MINIMAL"

    def _assess_signal(self, data: dict) -> str:
        """Assess overall short interest signal."""
        short_pct = data.get("short_pct_float", 0) or 0

        if short_pct >= self.EXTREME_SHORT_INTEREST_PCT:
            return "EXTREME_BEARISH_OR_SQUEEZE"
        elif short_pct >= self.HIGH_SHORT_INTEREST_PCT:
            return "HIGH_SHORT_INTEREST"
        elif short_pct >= 10:
            return "ELEVATED"
        elif short_pct >= 5:
            return "MODERATE"
        else:
            return "LOW"

    def get_most_shorted(self, min_short_pct: float = 10.0) -> list:
        """
        Get highest short interest stocks in the universe.
        These are potential squeeze candidates or validated bear theses.

        Args:
            min_short_pct: Minimum short % of float to include

        Returns:
            List of short interest dicts sorted by short % descending
        """
        results = []

        for ticker in UNIVERSE.keys():
            try:
                data = self.get_short_interest(ticker)
                short_pct = data.get("short_pct_float", 0) or 0

                if short_pct >= min_short_pct:
                    results.append(data)
            except Exception as e:
                logger.debug(f"Error getting short interest for {ticker}: {e}")
                continue

        # Sort by short % descending
        results.sort(key=lambda x: x.get("short_pct_float", 0) or 0, reverse=True)

        logger.info(f"Found {len(results)} stocks with >={min_short_pct}% short interest")
        return results

    def get_squeeze_candidates(self) -> list:
        """
        Find stocks with high squeeze potential.

        Criteria:
        - High short % of float (>15%)
        - High days to cover (>5)
        - Elevated options activity would add to the signal

        Returns:
            List of squeeze candidate dicts
        """
        candidates = []

        for ticker in UNIVERSE.keys():
            try:
                data = self.get_short_interest(ticker)

                squeeze_risk = data.get("squeeze_risk", "MINIMAL")
                if squeeze_risk in ["HIGH", "MODERATE"]:
                    candidates.append(data)
            except Exception as e:
                logger.debug(f"Error checking squeeze for {ticker}: {e}")
                continue

        # Sort by squeeze risk (HIGH first) then by short %
        risk_order = {"HIGH": 0, "MODERATE": 1, "LOW": 2, "MINIMAL": 3}
        candidates.sort(key=lambda x: (
            risk_order.get(x.get("squeeze_risk", "MINIMAL"), 4),
            -(x.get("short_pct_float", 0) or 0)
        ))

        logger.info(f"Found {len(candidates)} squeeze candidates")
        return candidates

    def get_short_interest_changes(self, ticker: str) -> dict:
        """
        Track changes in short interest over time.
        Note: This requires historical data storage to be fully functional.

        Args:
            ticker: Stock ticker symbol

        Returns:
            Dict with current and change metrics
        """
        current = self.get_short_interest(ticker)

        # For now, we just return current data
        # Historical tracking would require database storage
        result = {
            "ticker": ticker,
            "current": current,
            "change_available": False,
            "note": "Historical tracking requires database. Current snapshot only.",
        }

        return result

    def get_sector_short_summary(self) -> dict:
        """
        Get short interest summary by sector.

        Returns:
            Dict mapping sector -> summary stats
        """
        by_sector = {}

        for ticker, info in UNIVERSE.items():
            sector = info.get("sector", "Unknown")
            if sector not in by_sector:
                by_sector[sector] = {
                    "tickers": [],
                    "total_short_pct": 0,
                    "high_short_count": 0,
                    "squeeze_risk_count": 0,
                }

            try:
                data = self.get_short_interest(ticker)
                short_pct = data.get("short_pct_float", 0) or 0

                by_sector[sector]["tickers"].append(ticker)
                by_sector[sector]["total_short_pct"] += short_pct

                if short_pct >= self.HIGH_SHORT_INTEREST_PCT:
                    by_sector[sector]["high_short_count"] += 1

                if data.get("squeeze_risk") in ["HIGH", "MODERATE"]:
                    by_sector[sector]["squeeze_risk_count"] += 1
            except:
                by_sector[sector]["tickers"].append(ticker)
                continue

        # Calculate averages
        for sector, stats in by_sector.items():
            count = len(stats["tickers"])
            if count > 0:
                stats["avg_short_pct"] = stats["total_short_pct"] / count
            else:
                stats["avg_short_pct"] = 0
            stats["ticker_count"] = count

        return by_sector


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    print("\n" + "="*60)
    print("ATLAS Short Interest Client")
    print("="*60 + "\n")

    client = ShortInterestClient()

    # Test short interest for NVDA
    print("--- NVDA Short Interest ---")
    data = client.get_short_interest("NVDA")
    print(f"  Short % of Float: {data.get('short_pct_float', 'N/A')}%")
    print(f"  Days to Cover: {data.get('days_to_cover', 'N/A')}")
    print(f"  Float Shares: {data.get('float_shares', 'N/A'):,}" if data.get('float_shares') else "  Float: N/A")
    print(f"  Squeeze Risk: {data.get('squeeze_risk', 'N/A')}")
    print(f"  Signal: {data.get('short_interest_signal', 'N/A')}")

    # Test most shorted
    print("\n--- Most Shorted Stocks ---")
    shorted = client.get_most_shorted(min_short_pct=5.0)
    for s in shorted[:5]:
        print(f"  {s['ticker']} | Short: {s.get('short_pct_float', 'N/A'):.1f}% | DTC: {s.get('days_to_cover', 'N/A')}")

    # Test squeeze candidates
    print("\n--- Squeeze Candidates ---")
    squeeze = client.get_squeeze_candidates()
    for s in squeeze[:5]:
        print(f"  {s['ticker']} | Risk: {s.get('squeeze_risk')} | Short: {s.get('short_pct_float', 'N/A'):.1f}%")

    # Test sector summary
    print("\n--- Sector Short Summary ---")
    summary = client.get_sector_short_summary()
    for sector, stats in sorted(summary.items(), key=lambda x: x[1].get("avg_short_pct", 0), reverse=True):
        print(f"  {sector}: Avg Short {stats.get('avg_short_pct', 0):.1f}% | High: {stats.get('high_short_count', 0)}")
