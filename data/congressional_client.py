"""
Congressional Trading Client for ATLAS
Tracks stock trades by members of Congress under the STOCK Act.

Members of Congress must disclose stock trades within 45 days.
This data is public and often signals policy-informed positioning.

Data Sources:
- Capitol Trades API (free)
- Quiver Quantitative API (free tier)
- House/Senate financial disclosure websites
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
import requests

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.universe import UNIVERSE

logger = logging.getLogger(__name__)


class CongressionalClient:
    """
    Client for tracking congressional stock trades.
    """

    # Capitol Trades API (free, no key needed)
    CAPITOL_TRADES_API = "https://api.capitoltrades.com/v1"

    # Quiver Quantitative API (free tier)
    QUIVER_API = "https://api.quiverquant.com/beta"

    def __init__(self, quiver_api_key: str = None):
        """
        Initialize congressional trading client.

        Args:
            quiver_api_key: Quiver Quantitative API key (optional)
        """
        self.quiver_api_key = quiver_api_key
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        })
        self._cache = {}
        self._cache_expiry = {}
        self._cache_ttl = timedelta(hours=6)  # Congressional data updates slowly

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

    def get_recent_trades(self, days: int = 30) -> list:
        """
        Get recent congressional stock trades.

        Args:
            days: Look back this many days

        Returns:
            List of trade dicts with politician, ticker, trade_type, amount, date
        """
        cache_key = f"recent_trades_{days}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        trades = []

        # Try Capitol Trades API
        try:
            capitol_trades = self._fetch_capitol_trades(days)
            trades.extend(capitol_trades)
        except Exception as e:
            logger.debug(f"Capitol Trades API error: {e}")

        # Try Quiver API if we have a key
        if self.quiver_api_key:
            try:
                quiver_trades = self._fetch_quiver_trades(days)
                trades.extend(quiver_trades)
            except Exception as e:
                logger.debug(f"Quiver API error: {e}")

        # Deduplicate by (politician, ticker, date)
        seen = set()
        unique_trades = []
        for trade in trades:
            key = (
                trade.get("politician", ""),
                trade.get("ticker", ""),
                trade.get("transaction_date", ""),
            )
            if key not in seen:
                seen.add(key)
                unique_trades.append(trade)

        # Sort by date descending
        unique_trades.sort(key=lambda x: x.get("transaction_date", ""), reverse=True)

        # Filter to our universe tickers
        universe_trades = []
        for trade in unique_trades:
            ticker = trade.get("ticker", "")
            if ticker in UNIVERSE:
                trade["company_name"] = UNIVERSE[ticker].get("name", ticker)
                trade["sector"] = UNIVERSE[ticker].get("sector", "")
                trade["in_universe"] = True
            else:
                trade["in_universe"] = False
            universe_trades.append(trade)

        self._set_cached(cache_key, universe_trades)
        logger.info(f"Found {len(universe_trades)} congressional trades in last {days} days")
        return universe_trades

    def _fetch_capitol_trades(self, days: int) -> list:
        """Fetch trades from Capitol Trades API."""
        trades = []

        try:
            # Capitol Trades public API endpoint
            url = f"{self.CAPITOL_TRADES_API}/trades"
            params = {
                "page": 1,
                "pageSize": 100,
            }

            resp = self.session.get(url, params=params, timeout=15)
            if resp.status_code != 200:
                return trades

            data = resp.json()
            cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

            for trade in data.get("data", []):
                trade_date = trade.get("txDate", "")
                if trade_date < cutoff_date:
                    continue

                trades.append({
                    "politician": trade.get("politicianName", ""),
                    "chamber": trade.get("chamber", ""),  # house or senate
                    "party": trade.get("party", ""),
                    "state": trade.get("state", ""),
                    "ticker": trade.get("ticker", "").upper() if trade.get("ticker") else "",
                    "asset_name": trade.get("assetName", ""),
                    "trade_type": trade.get("txType", ""),  # buy, sell
                    "amount_range": trade.get("txAmount", ""),  # $1,001-$15,000
                    "transaction_date": trade_date,
                    "disclosure_date": trade.get("filingDate", ""),
                    "source": "capitol_trades",
                })

        except Exception as e:
            logger.error(f"Capitol Trades API error: {e}")

        return trades

    def _fetch_quiver_trades(self, days: int) -> list:
        """Fetch trades from Quiver Quantitative API."""
        if not self.quiver_api_key:
            return []

        trades = []

        try:
            headers = {"Authorization": f"Token {self.quiver_api_key}"}
            url = f"{self.QUIVER_API}/congressional"

            resp = self.session.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                return trades

            data = resp.json()
            cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

            for trade in data:
                trade_date = trade.get("TransactionDate", "")
                if trade_date < cutoff_date:
                    continue

                trades.append({
                    "politician": trade.get("Representative", ""),
                    "chamber": "house" if trade.get("House") else "senate",
                    "party": trade.get("Party", ""),
                    "ticker": trade.get("Ticker", "").upper() if trade.get("Ticker") else "",
                    "asset_name": trade.get("Asset", ""),
                    "trade_type": trade.get("Transaction", "").lower(),  # Purchase, Sale
                    "amount_range": trade.get("Range", ""),
                    "transaction_date": trade_date,
                    "disclosure_date": trade.get("DisclosureDate", ""),
                    "source": "quiver",
                })

        except Exception as e:
            logger.error(f"Quiver API error: {e}")

        return trades

    def get_trades_by_ticker(self, ticker: str, days: int = 90) -> list:
        """
        Get congressional trades for a specific ticker.

        Args:
            ticker: Stock ticker symbol
            days: Look back this many days

        Returns:
            List of trades for this ticker
        """
        all_trades = self.get_recent_trades(days=days)
        return [t for t in all_trades if t.get("ticker") == ticker.upper()]

    def get_universe_trades(self, days: int = 30) -> list:
        """
        Get congressional trades only for stocks in our universe.

        Args:
            days: Look back this many days

        Returns:
            List of trades for universe stocks only
        """
        all_trades = self.get_recent_trades(days=days)
        return [t for t in all_trades if t.get("in_universe", False)]

    def get_buys_vs_sells(self, days: int = 30) -> dict:
        """
        Get summary of congressional buying vs selling.

        Args:
            days: Look back this many days

        Returns:
            Dict with buy/sell counts and top traded stocks
        """
        trades = self.get_recent_trades(days=days)

        buys = [t for t in trades if t.get("trade_type", "").lower() in ["buy", "purchase"]]
        sells = [t for t in trades if t.get("trade_type", "").lower() in ["sell", "sale"]]

        # Count by ticker
        buy_counts = {}
        sell_counts = {}

        for trade in buys:
            ticker = trade.get("ticker", "")
            if ticker:
                buy_counts[ticker] = buy_counts.get(ticker, 0) + 1

        for trade in sells:
            ticker = trade.get("ticker", "")
            if ticker:
                sell_counts[ticker] = sell_counts.get(ticker, 0) + 1

        # Top bought and sold
        top_bought = sorted(buy_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        top_sold = sorted(sell_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        return {
            "total_buys": len(buys),
            "total_sells": len(sells),
            "buy_sell_ratio": len(buys) / len(sells) if sells else None,
            "top_bought": [{"ticker": t, "count": c} for t, c in top_bought],
            "top_sold": [{"ticker": t, "count": c} for t, c in top_sold],
            "net_sentiment": "BULLISH" if len(buys) > len(sells) * 1.2 else
                           "BEARISH" if len(sells) > len(buys) * 1.2 else
                           "NEUTRAL",
        }

    def get_trades_by_politician(self, politician_name: str, days: int = 90) -> list:
        """
        Get trades for a specific politician.

        Args:
            politician_name: Name of the politician (partial match)
            days: Look back this many days

        Returns:
            List of trades by this politician
        """
        all_trades = self.get_recent_trades(days=days)
        name_lower = politician_name.lower()
        return [t for t in all_trades if name_lower in t.get("politician", "").lower()]

    def get_active_politicians(self, days: int = 30) -> list:
        """
        Get most active trading politicians.

        Args:
            days: Look back this many days

        Returns:
            List of politicians sorted by trade count
        """
        trades = self.get_recent_trades(days=days)

        by_politician = {}
        for trade in trades:
            name = trade.get("politician", "")
            if name:
                if name not in by_politician:
                    by_politician[name] = {
                        "name": name,
                        "party": trade.get("party", ""),
                        "chamber": trade.get("chamber", ""),
                        "trade_count": 0,
                        "buy_count": 0,
                        "sell_count": 0,
                    }
                by_politician[name]["trade_count"] += 1
                if trade.get("trade_type", "").lower() in ["buy", "purchase"]:
                    by_politician[name]["buy_count"] += 1
                else:
                    by_politician[name]["sell_count"] += 1

        # Sort by trade count
        active = sorted(by_politician.values(), key=lambda x: x["trade_count"], reverse=True)
        return active

    def get_sector_activity(self, days: int = 30) -> dict:
        """
        Get congressional trading by sector.

        Args:
            days: Look back this many days

        Returns:
            Dict mapping sector -> trade activity
        """
        trades = self.get_universe_trades(days=days)

        by_sector = {}
        for trade in trades:
            sector = trade.get("sector", "Unknown")
            if sector not in by_sector:
                by_sector[sector] = {
                    "total_trades": 0,
                    "buys": 0,
                    "sells": 0,
                }
            by_sector[sector]["total_trades"] += 1
            if trade.get("trade_type", "").lower() in ["buy", "purchase"]:
                by_sector[sector]["buys"] += 1
            else:
                by_sector[sector]["sells"] += 1

        # Add net sentiment for each sector
        for sector, data in by_sector.items():
            if data["sells"] > 0:
                data["buy_sell_ratio"] = data["buys"] / data["sells"]
            else:
                data["buy_sell_ratio"] = data["buys"] if data["buys"] > 0 else 0

        return by_sector


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    print("\n" + "="*60)
    print("ATLAS Congressional Trading Client")
    print("="*60 + "\n")

    client = CongressionalClient()

    # Test recent trades
    print("--- Recent Congressional Trades (30 days) ---")
    trades = client.get_recent_trades(days=30)
    for t in trades[:10]:
        universe = "[UNIVERSE]" if t.get("in_universe") else ""
        print(f"  {t.get('transaction_date', 'N/A')} | {t.get('politician', 'N/A')[:20]} | {t.get('trade_type', 'N/A')} | {t.get('ticker', 'N/A')} {universe}")

    # Test universe-only trades
    print("\n--- Universe Stock Trades ---")
    universe_trades = client.get_universe_trades(days=30)
    for t in universe_trades[:5]:
        print(f"  {t.get('ticker', 'N/A')} | {t.get('politician', 'N/A')[:20]} | {t.get('trade_type', 'N/A')} | {t.get('amount_range', 'N/A')}")

    # Test buy/sell summary
    print("\n--- Buy vs Sell Summary ---")
    summary = client.get_buys_vs_sells(days=30)
    print(f"  Total Buys: {summary['total_buys']}")
    print(f"  Total Sells: {summary['total_sells']}")
    print(f"  Net Sentiment: {summary['net_sentiment']}")

    print("\n  Top Bought:")
    for item in summary["top_bought"][:5]:
        print(f"    {item['ticker']}: {item['count']} trades")

    print("\n  Top Sold:")
    for item in summary["top_sold"][:5]:
        print(f"    {item['ticker']}: {item['count']} trades")

    # Test active politicians
    print("\n--- Most Active Politicians ---")
    active = client.get_active_politicians(days=30)
    for p in active[:5]:
        print(f"  {p['name'][:25]} ({p['party']}) | {p['trade_count']} trades | B:{p['buy_count']} S:{p['sell_count']}")

    # Test sector activity
    print("\n--- Sector Activity ---")
    sectors = client.get_sector_activity(days=30)
    for sector, data in sorted(sectors.items(), key=lambda x: x[1]["total_trades"], reverse=True):
        print(f"  {sector}: {data['total_trades']} trades | B:{data['buys']} S:{data['sells']}")
