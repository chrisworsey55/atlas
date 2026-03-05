"""
ETF Flow Data Client for ATLAS
Tracks institutional money flows into and out of sector ETFs.

Sector rotation signals show up in ETF flows before individual stocks.
This client monitors:
- Sector ETF inflows/outflows (XLK, XLF, XLE, XLV, etc.)
- ETF holdings overlap with portfolio stocks
- Rebalancing pressure indicators

Data Sources:
- yfinance for ETF price/volume data
- ETF.com and ETFdb.com for holdings data (scraping)
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd
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


# Major sector ETFs to track
SECTOR_ETFS = {
    "XLK": {"name": "Technology Select Sector", "sector": "Technology"},
    "XLF": {"name": "Financial Select Sector", "sector": "Financials"},
    "XLE": {"name": "Energy Select Sector", "sector": "Energy"},
    "XLV": {"name": "Health Care Select Sector", "sector": "Healthcare"},
    "XLI": {"name": "Industrial Select Sector", "sector": "Industrials"},
    "XLP": {"name": "Consumer Staples Select Sector", "sector": "Consumer Staples"},
    "XLY": {"name": "Consumer Discretionary Select Sector", "sector": "Consumer Discretionary"},
    "XLU": {"name": "Utilities Select Sector", "sector": "Utilities"},
    "XLRE": {"name": "Real Estate Select Sector", "sector": "Real Estate"},
    "XLC": {"name": "Communication Services Select Sector", "sector": "Communications"},
    "XLB": {"name": "Materials Select Sector", "sector": "Materials"},
}

# Thematic ETFs
THEMATIC_ETFS = {
    "QQQ": {"name": "Invesco QQQ Trust", "theme": "Nasdaq-100"},
    "SMH": {"name": "VanEck Semiconductor ETF", "theme": "Semiconductors"},
    "ARKK": {"name": "ARK Innovation ETF", "theme": "Disruptive Innovation"},
    "XBI": {"name": "SPDR S&P Biotech ETF", "theme": "Biotechnology"},
    "IGV": {"name": "iShares Expanded Tech-Software ETF", "theme": "Software"},
    "SOXX": {"name": "iShares Semiconductor ETF", "theme": "Semiconductors"},
    "XHB": {"name": "SPDR Homebuilders ETF", "theme": "Homebuilders"},
    "KRE": {"name": "SPDR S&P Regional Banking ETF", "theme": "Regional Banks"},
    "XRT": {"name": "SPDR S&P Retail ETF", "theme": "Retail"},
    "XOP": {"name": "SPDR S&P Oil & Gas Exploration ETF", "theme": "Oil & Gas"},
}

# Broad market ETFs
MARKET_ETFS = {
    "SPY": {"name": "SPDR S&P 500 ETF", "theme": "S&P 500"},
    "IWM": {"name": "iShares Russell 2000 ETF", "theme": "Small Cap"},
    "DIA": {"name": "SPDR Dow Jones Industrial ETF", "theme": "Dow 30"},
    "VTI": {"name": "Vanguard Total Stock Market ETF", "theme": "Total Market"},
    "EFA": {"name": "iShares MSCI EAFE ETF", "theme": "International Developed"},
    "EEM": {"name": "iShares MSCI Emerging Markets ETF", "theme": "Emerging Markets"},
}


class ETFFlowClient:
    """
    Client for tracking ETF flows and sector rotation.
    """

    ETFDB_URL = "https://etfdb.com/etf/{ticker}/"

    def __init__(self):
        """Initialize ETF flow client."""
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        })
        self._cache = {}
        self._cache_expiry = {}
        self._cache_ttl = timedelta(minutes=30)

        if not YFINANCE_AVAILABLE:
            logger.warning("yfinance not available - ETF data will be limited")

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

    def get_sector_flows(self, days: int = 5) -> dict:
        """
        Get net inflows/outflows for major sector ETFs.
        Uses price and volume data to estimate flows.

        Args:
            days: Number of days to analyze

        Returns:
            Dict mapping ETF ticker -> flow data
        """
        cache_key = f"sector_flows_{days}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        flows = {}

        for ticker, info in SECTOR_ETFS.items():
            try:
                flow_data = self._calculate_etf_flow(ticker, days)
                if flow_data:
                    flow_data["name"] = info["name"]
                    flow_data["sector"] = info["sector"]
                    flows[ticker] = flow_data
            except Exception as e:
                logger.debug(f"Error calculating flow for {ticker}: {e}")
                continue

        # Rank by flow direction
        sorted_flows = dict(sorted(
            flows.items(),
            key=lambda x: x[1].get("estimated_flow_pct", 0),
            reverse=True
        ))

        self._set_cached(cache_key, sorted_flows)
        return sorted_flows

    def _calculate_etf_flow(self, ticker: str, days: int) -> Optional[dict]:
        """Calculate estimated ETF flow from price/volume data."""
        if not YFINANCE_AVAILABLE:
            return None

        try:
            etf = yf.Ticker(ticker)
            hist = etf.history(period=f"{days + 10}d")

            if hist is None or len(hist) < days:
                return None

            recent = hist.tail(days)
            prev = hist.iloc[-(days+5):-days] if len(hist) > days + 5 else hist.head(5)

            # Current metrics
            current_price = float(recent["Close"].iloc[-1])
            avg_volume = float(recent["Volume"].mean())
            price_change_pct = ((recent["Close"].iloc[-1] - recent["Close"].iloc[0]) / recent["Close"].iloc[0]) * 100

            # Previous period metrics
            prev_avg_volume = float(prev["Volume"].mean()) if len(prev) > 0 else avg_volume

            # Volume change as proxy for flow
            volume_change_pct = ((avg_volume - prev_avg_volume) / prev_avg_volume * 100) if prev_avg_volume > 0 else 0

            # Estimate dollar volume
            dollar_volume = avg_volume * current_price

            # Money flow approximation (price direction * volume)
            # Positive = inflow, Negative = outflow
            if price_change_pct > 0:
                estimated_flow = dollar_volume * (price_change_pct / 100)
            else:
                estimated_flow = -dollar_volume * abs(price_change_pct / 100)

            # Determine flow signal
            if price_change_pct > 2 and volume_change_pct > 20:
                flow_signal = "STRONG_INFLOW"
            elif price_change_pct > 0.5 and volume_change_pct > 0:
                flow_signal = "INFLOW"
            elif price_change_pct < -2 and volume_change_pct > 20:
                flow_signal = "STRONG_OUTFLOW"
            elif price_change_pct < -0.5:
                flow_signal = "OUTFLOW"
            else:
                flow_signal = "NEUTRAL"

            return {
                "ticker": ticker,
                "current_price": current_price,
                "price_change_pct": price_change_pct,
                "avg_volume": int(avg_volume),
                "volume_change_pct": volume_change_pct,
                "estimated_flow": estimated_flow,
                "estimated_flow_pct": price_change_pct,  # Simplified proxy
                "flow_signal": flow_signal,
                "dollar_volume_avg": dollar_volume,
            }

        except Exception as e:
            logger.error(f"ETF flow calculation error for {ticker}: {e}")
            return None

    def get_etf_holdings_overlap(self, ticker: str) -> dict:
        """
        Get what % of major ETFs hold this ticker.
        ETF rebalancing can create buying/selling pressure.

        Args:
            ticker: Stock ticker symbol

        Returns:
            Dict with ETF holdings information
        """
        cache_key = f"holdings_overlap_{ticker}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        result = {
            "ticker": ticker,
            "company_name": UNIVERSE.get(ticker, {}).get("name", ticker),
            "etf_holdings": [],
        }

        # Check sector ETFs
        sector = UNIVERSE.get(ticker, {}).get("sector", "")
        sector_etf = None
        for etf_ticker, info in SECTOR_ETFS.items():
            if info["sector"] == sector:
                sector_etf = etf_ticker
                result["primary_sector_etf"] = etf_ticker
                break

        # Try to scrape holdings from ETFdb or use yfinance
        try:
            etf_data = self._fetch_etf_holdings_for_stock(ticker)
            result["etf_holdings"] = etf_data
            result["total_etfs_holding"] = len(etf_data)
        except Exception as e:
            logger.debug(f"Error fetching ETF holdings for {ticker}: {e}")
            result["etf_holdings"] = []
            result["total_etfs_holding"] = 0

        # Estimate rebalancing pressure
        if result["total_etfs_holding"] > 10:
            result["rebalancing_sensitivity"] = "HIGH"
        elif result["total_etfs_holding"] > 5:
            result["rebalancing_sensitivity"] = "MODERATE"
        else:
            result["rebalancing_sensitivity"] = "LOW"

        self._set_cached(cache_key, result)
        return result

    def _fetch_etf_holdings_for_stock(self, ticker: str) -> list:
        """Fetch which ETFs hold a given stock."""
        holdings = []

        # Major ETFs known to hold large cap stocks
        etfs_to_check = list(SECTOR_ETFS.keys()) + list(THEMATIC_ETFS.keys())[:5] + ["SPY", "QQQ"]

        for etf_ticker in etfs_to_check:
            try:
                # Use yfinance to check if ticker is a major holding
                # This is an approximation since yfinance doesn't provide full holdings
                etf = yf.Ticker(etf_ticker)
                info = etf.info

                # For sector ETFs, we assume they hold companies in their sector
                if etf_ticker in SECTOR_ETFS:
                    sector_match = SECTOR_ETFS[etf_ticker]["sector"]
                    stock_sector = UNIVERSE.get(ticker, {}).get("sector", "")
                    if stock_sector == sector_match:
                        holdings.append({
                            "etf": etf_ticker,
                            "etf_name": SECTOR_ETFS[etf_ticker]["name"],
                            "likely_holding": True,
                            "reason": "Sector match",
                        })

                # For thematic ETFs, do a basic match
                if etf_ticker in THEMATIC_ETFS:
                    theme = THEMATIC_ETFS[etf_ticker]["theme"]
                    # Semiconductors
                    if "Semiconductor" in theme and ticker in ["NVDA", "AMD", "INTC", "AVGO", "QCOM", "MU", "TSM"]:
                        holdings.append({
                            "etf": etf_ticker,
                            "etf_name": THEMATIC_ETFS[etf_ticker]["name"],
                            "likely_holding": True,
                            "reason": "Theme match",
                        })
                    # Nasdaq-100 (major tech companies)
                    if theme == "Nasdaq-100" and ticker in ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "AVGO"]:
                        holdings.append({
                            "etf": etf_ticker,
                            "etf_name": THEMATIC_ETFS[etf_ticker]["name"],
                            "likely_holding": True,
                            "reason": "Nasdaq-100 member",
                        })

            except Exception as e:
                logger.debug(f"Error checking {etf_ticker} holdings: {e}")
                continue

        return holdings

    def get_rotation_signals(self, days: int = 5) -> dict:
        """
        Identify sector rotation signals from ETF flows.

        Returns:
            Dict with rotation analysis
        """
        flows = self.get_sector_flows(days)

        # Separate inflows and outflows
        inflows = []
        outflows = []

        for ticker, data in flows.items():
            signal = data.get("flow_signal", "NEUTRAL")
            if "INFLOW" in signal:
                inflows.append({
                    "ticker": ticker,
                    "sector": data.get("sector"),
                    "signal": signal,
                    "price_change_pct": data.get("price_change_pct"),
                })
            elif "OUTFLOW" in signal:
                outflows.append({
                    "ticker": ticker,
                    "sector": data.get("sector"),
                    "signal": signal,
                    "price_change_pct": data.get("price_change_pct"),
                })

        # Sort by strength
        inflows.sort(key=lambda x: x["price_change_pct"], reverse=True)
        outflows.sort(key=lambda x: x["price_change_pct"])

        # Determine rotation pattern
        if len(inflows) > 0 and len(outflows) > 0:
            # Risk-on vs risk-off
            cyclical_in = any(s["sector"] in ["Technology", "Consumer Discretionary", "Financials"] for s in inflows)
            defensive_in = any(s["sector"] in ["Utilities", "Consumer Staples", "Healthcare"] for s in inflows)

            if cyclical_in and not defensive_in:
                rotation_type = "RISK_ON"
            elif defensive_in and not cyclical_in:
                rotation_type = "RISK_OFF"
            else:
                rotation_type = "MIXED"
        else:
            rotation_type = "NO_CLEAR_ROTATION"

        return {
            "timestamp": datetime.now().isoformat(),
            "period_days": days,
            "rotation_type": rotation_type,
            "sectors_with_inflows": inflows,
            "sectors_with_outflows": outflows,
            "strongest_inflow": inflows[0] if inflows else None,
            "strongest_outflow": outflows[0] if outflows else None,
        }

    def get_thematic_flows(self, days: int = 5) -> dict:
        """
        Get flows for thematic ETFs (semiconductors, biotech, etc.).

        Returns:
            Dict mapping thematic ETF -> flow data
        """
        cache_key = f"thematic_flows_{days}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        flows = {}

        for ticker, info in THEMATIC_ETFS.items():
            try:
                flow_data = self._calculate_etf_flow(ticker, days)
                if flow_data:
                    flow_data["name"] = info["name"]
                    flow_data["theme"] = info["theme"]
                    flows[ticker] = flow_data
            except Exception as e:
                logger.debug(f"Error calculating thematic flow for {ticker}: {e}")
                continue

        self._set_cached(cache_key, flows)
        return flows

    def get_market_breadth(self, days: int = 5) -> dict:
        """
        Analyze market breadth using broad ETFs.

        Returns:
            Dict with market breadth indicators
        """
        breadth = {
            "timestamp": datetime.now().isoformat(),
            "period_days": days,
        }

        try:
            # Large cap vs small cap
            spy_flow = self._calculate_etf_flow("SPY", days)
            iwm_flow = self._calculate_etf_flow("IWM", days)

            if spy_flow and iwm_flow:
                breadth["large_cap_flow"] = spy_flow.get("flow_signal")
                breadth["small_cap_flow"] = iwm_flow.get("flow_signal")
                breadth["large_cap_return"] = spy_flow.get("price_change_pct")
                breadth["small_cap_return"] = iwm_flow.get("price_change_pct")

                # Small cap outperformance = risk appetite
                if iwm_flow.get("price_change_pct", 0) > spy_flow.get("price_change_pct", 0) + 1:
                    breadth["risk_appetite"] = "HIGH"
                elif spy_flow.get("price_change_pct", 0) > iwm_flow.get("price_change_pct", 0) + 1:
                    breadth["risk_appetite"] = "LOW"
                else:
                    breadth["risk_appetite"] = "NEUTRAL"

            # US vs International
            efa_flow = self._calculate_etf_flow("EFA", days)
            eem_flow = self._calculate_etf_flow("EEM", days)

            if efa_flow:
                breadth["international_developed_return"] = efa_flow.get("price_change_pct")
            if eem_flow:
                breadth["emerging_markets_return"] = eem_flow.get("price_change_pct")

        except Exception as e:
            logger.error(f"Market breadth error: {e}")

        return breadth


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    print("\n" + "="*60)
    print("ATLAS ETF Flow Client")
    print("="*60 + "\n")

    client = ETFFlowClient()

    # Test sector flows
    print("--- Sector ETF Flows (5 days) ---")
    flows = client.get_sector_flows(days=5)
    for ticker, data in list(flows.items())[:6]:
        signal = data.get("flow_signal", "N/A")
        pct = data.get("price_change_pct", 0)
        print(f"  {ticker} ({data.get('sector', 'N/A')[:12]}): {pct:+.1f}% | {signal}")

    # Test rotation signals
    print("\n--- Rotation Signals ---")
    rotation = client.get_rotation_signals(days=5)
    print(f"  Rotation Type: {rotation.get('rotation_type')}")
    if rotation.get("strongest_inflow"):
        print(f"  Strongest Inflow: {rotation['strongest_inflow']['sector']}")
    if rotation.get("strongest_outflow"):
        print(f"  Strongest Outflow: {rotation['strongest_outflow']['sector']}")

    # Test holdings overlap
    print("\n--- NVDA ETF Holdings ---")
    holdings = client.get_etf_holdings_overlap("NVDA")
    print(f"  Total ETFs Holding: {holdings.get('total_etfs_holding')}")
    print(f"  Rebalancing Sensitivity: {holdings.get('rebalancing_sensitivity')}")
    for h in holdings.get("etf_holdings", [])[:5]:
        print(f"    {h['etf']}: {h['etf_name']}")

    # Test thematic flows
    print("\n--- Thematic ETF Flows ---")
    thematic = client.get_thematic_flows(days=5)
    for ticker, data in list(thematic.items())[:5]:
        print(f"  {ticker} ({data.get('theme', 'N/A')[:15]}): {data.get('price_change_pct', 0):+.1f}%")

    # Test market breadth
    print("\n--- Market Breadth ---")
    breadth = client.get_market_breadth(days=5)
    print(f"  Large Cap (SPY): {breadth.get('large_cap_return', 0):+.1f}%")
    print(f"  Small Cap (IWM): {breadth.get('small_cap_return', 0):+.1f}%")
    print(f"  Risk Appetite: {breadth.get('risk_appetite', 'N/A')}")
