"""
Macro Data Client for ATLAS
Fetches economic indicators from FRED API and market data from yfinance.

Designed for Druckenmiller-style macro analysis:
- Liquidity indicators (Fed funds, M2, reverse repo)
- Yield curve and credit spreads
- Growth and inflation data
- Market sentiment (VIX, dollar, etc.)
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd

try:
    from fredapi import Fred
    FRED_AVAILABLE = True
except ImportError:
    FRED_AVAILABLE = False
    Fred = None

import yfinance as yf

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import FRED_API_KEY

logger = logging.getLogger(__name__)


# FRED Series IDs for Druckenmiller-style macro analysis
FRED_SERIES = {
    # Liquidity & Fed Policy
    "fed_funds_rate": "FEDFUNDS",
    "fed_funds_upper": "DFEDTARU",
    "fed_funds_lower": "DFEDTARL",
    "m2_money_supply": "M2SL",
    "reverse_repo": "RRPONTSYD",
    "fed_balance_sheet": "WALCL",

    # Treasury Yields
    "treasury_3m": "GS3M",
    "treasury_2y": "GS2",
    "treasury_5y": "GS5",
    "treasury_10y": "GS10",
    "treasury_30y": "GS30",

    # Yield Curve Spreads
    "yield_curve_10y_2y": "T10Y2Y",
    "yield_curve_10y_3m": "T10Y3M",

    # Credit Spreads
    "high_yield_spread": "BAMLH0A0HYM2",
    "investment_grade_spread": "BAMLC0A4CBBB",
    "aaa_spread": "BAMLC0A1CAAA",
    "bbb_spread": "BAMLC0A4CBBB",

    # Growth Indicators
    "real_gdp": "GDPC1",
    "industrial_production": "INDPRO",
    "capacity_utilization": "TCU",
    "retail_sales": "RSAFS",
    "retail_sales_ex_auto": "RSFSXMV",
    "housing_starts": "HOUST",
    "building_permits": "PERMIT",
    "durable_goods_orders": "DGORDER",
    "new_home_sales": "HSN1F",
    "existing_home_sales": "EXHOSLUSM495S",

    # Inflation
    "cpi": "CPIAUCSL",
    "core_cpi": "CPILFESL",
    "pce": "PCEPI",
    "core_pce": "PCEPILFE",
    "breakeven_5y": "T5YIE",
    "breakeven_10y": "T10YIE",
    "ppi": "PPIACO",

    # Labor Market
    "unemployment_rate": "UNRATE",
    "initial_claims": "ICSA",
    "continuing_claims": "CCSA",
    "nonfarm_payrolls": "PAYEMS",
    "jolts_openings": "JTSJOL",
    "jolts_quits": "JTSQUR",
    "avg_hourly_earnings": "CES0500000003",
    "labor_force_participation": "CIVPART",

    # Financial Conditions
    "chicago_fed_nfci": "NFCI",
    "st_louis_fed_fsi": "STLFSI4",
    "ted_spread": "TEDRATE",

    # Consumer
    "consumer_sentiment_michigan": "UMCSENT",
    "consumer_confidence_cb": "CSCICP03USM665S",
    "personal_saving_rate": "PSAVERT",
    "consumer_credit": "TOTALSL",

    # Business
    "ism_manufacturing": "MANEMP",  # Manufacturing employment as proxy
    "ism_services": "TEMPHELPS",    # Temp help as proxy
    "small_business_optimism": "NFIB",
}

# yfinance tickers for real-time market data
MARKET_TICKERS = {
    "sp500": "^GSPC",
    "nasdaq": "^IXIC",
    "dow": "^DJI",
    "russell2000": "^RUT",
    "vix": "^VIX",
    "dollar_index": "DX-Y.NYB",
    "gold": "GC=F",
    "silver": "SI=F",
    "oil_wti": "CL=F",
    "oil_brent": "BZ=F",
    "natural_gas": "NG=F",
    "copper": "HG=F",
    "bitcoin": "BTC-USD",
    "ethereum": "ETH-USD",
    "treasury_20y_etf": "TLT",
    "high_yield_etf": "HYG",
    "investment_grade_etf": "LQD",
}


class MacroClient:
    """
    Client for fetching macroeconomic data from FRED and market data from yfinance.
    """

    def __init__(self, fred_api_key: str = None):
        """
        Initialize the macro client.

        Args:
            fred_api_key: FRED API key. If not provided, uses FRED_API_KEY from settings.
        """
        self.fred_api_key = fred_api_key or FRED_API_KEY
        self._fred = None
        self._cache = {}
        self._cache_expiry = {}
        self._cache_ttl = timedelta(hours=1)  # Cache for 1 hour

    @property
    def fred(self) -> Optional["Fred"]:
        """Lazy initialization of FRED client."""
        if self._fred is None and FRED_AVAILABLE and self.fred_api_key:
            try:
                self._fred = Fred(api_key=self.fred_api_key)
            except Exception as e:
                logger.error(f"Failed to initialize FRED client: {e}")
        return self._fred

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

    def get_fred_series(
        self,
        series_id: str,
        start_date: str = None,
        end_date: str = None,
        periods: int = 1
    ) -> Optional[pd.Series]:
        """
        Fetch a FRED series.

        Args:
            series_id: FRED series ID
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            periods: Number of recent observations to return

        Returns:
            pandas Series or None if failed
        """
        cache_key = f"fred_{series_id}_{start_date}_{end_date}_{periods}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        if not self.fred:
            logger.warning("FRED client not available")
            return None

        try:
            if start_date:
                series = self.fred.get_series(series_id, start_date, end_date)
            else:
                # Get last N years of data
                start = (datetime.now() - timedelta(days=365*5)).strftime("%Y-%m-%d")
                series = self.fred.get_series(series_id, start)

            if series is not None and len(series) > 0:
                result = series.tail(periods) if periods else series
                self._set_cached(cache_key, result)
                return result
            return None
        except Exception as e:
            logger.error(f"Failed to fetch FRED series {series_id}: {e}")
            return None

    def get_fred_latest(self, series_id: str) -> Optional[float]:
        """Get the most recent value for a FRED series."""
        series = self.get_fred_series(series_id, periods=1)
        if series is not None and len(series) > 0:
            return float(series.iloc[-1])
        return None

    def get_fred_yoy_change(self, series_id: str) -> Optional[float]:
        """Calculate year-over-year percentage change for a FRED series."""
        series = self.get_fred_series(series_id, periods=13)  # 13 months to ensure YoY
        if series is not None and len(series) >= 12:
            current = series.iloc[-1]
            year_ago = series.iloc[-12] if len(series) >= 12 else series.iloc[0]
            if year_ago != 0:
                return ((current - year_ago) / abs(year_ago)) * 100
        return None

    def get_market_price(self, ticker: str) -> Optional[float]:
        """Get current price for a market ticker."""
        cache_key = f"market_{ticker}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="1d")
            if hist.empty:
                hist = stock.history(period="5d")
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
                self._set_cached(cache_key, price)
                return price
            return None
        except Exception as e:
            logger.error(f"Failed to fetch market price for {ticker}: {e}")
            return None

    def get_market_returns(self, ticker: str, days: int = 252) -> Optional[float]:
        """Get return over N trading days."""
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period=f"{days + 10}d")
            if hist is not None and len(hist) >= days:
                start_price = float(hist["Close"].iloc[-days])
                end_price = float(hist["Close"].iloc[-1])
                return ((end_price - start_price) / start_price) * 100
            return None
        except Exception as e:
            logger.error(f"Failed to fetch returns for {ticker}: {e}")
            return None

    def get_52w_high_pct(self, ticker: str) -> Optional[float]:
        """Get percentage below 52-week high."""
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="1y")
            if hist is not None and len(hist) > 0:
                current = float(hist["Close"].iloc[-1])
                high_52w = float(hist["High"].max())
                return ((current - high_52w) / high_52w) * 100
            return None
        except Exception as e:
            logger.error(f"Failed to fetch 52w high for {ticker}: {e}")
            return None

    def get_macro_snapshot(self) -> dict:
        """
        Get a comprehensive macro data snapshot for Druckenmiller-style analysis.

        Returns:
            Dict with all macro indicators
        """
        snapshot = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "timestamp": datetime.now().isoformat(),
        }

        # Liquidity & Fed
        logger.info("Fetching liquidity indicators...")
        snapshot["fed_funds_rate"] = self.get_fred_latest("FEDFUNDS")
        snapshot["fed_funds_upper"] = self.get_fred_latest("DFEDTARU")
        snapshot["fed_funds_lower"] = self.get_fred_latest("DFEDTARL")
        snapshot["m2_money_supply"] = self.get_fred_latest("M2SL")
        snapshot["m2_yoy_change"] = self.get_fred_yoy_change("M2SL")
        snapshot["reverse_repo"] = self.get_fred_latest("RRPONTSYD")
        snapshot["fed_balance_sheet"] = self.get_fred_latest("WALCL")

        # Treasury Yields
        logger.info("Fetching yield data...")
        snapshot["treasury_3m"] = self.get_fred_latest("GS3M")
        snapshot["treasury_2y"] = self.get_fred_latest("GS2")
        snapshot["treasury_5y"] = self.get_fred_latest("GS5")
        snapshot["treasury_10y"] = self.get_fred_latest("GS10")
        snapshot["treasury_30y"] = self.get_fred_latest("GS30")
        snapshot["yield_curve_10y_2y"] = self.get_fred_latest("T10Y2Y")
        snapshot["yield_curve_10y_3m"] = self.get_fred_latest("T10Y3M")

        # Credit Spreads
        logger.info("Fetching credit spreads...")
        snapshot["high_yield_spread"] = self.get_fred_latest("BAMLH0A0HYM2")
        snapshot["investment_grade_spread"] = self.get_fred_latest("BAMLC0A4CBBB")

        # Growth Indicators
        logger.info("Fetching growth indicators...")
        snapshot["real_gdp"] = self.get_fred_latest("GDPC1")
        snapshot["gdp_yoy"] = self.get_fred_yoy_change("GDPC1")
        snapshot["industrial_production"] = self.get_fred_latest("INDPRO")
        snapshot["industrial_production_yoy"] = self.get_fred_yoy_change("INDPRO")
        snapshot["capacity_utilization"] = self.get_fred_latest("TCU")
        snapshot["retail_sales"] = self.get_fred_latest("RSAFS")
        snapshot["retail_sales_yoy"] = self.get_fred_yoy_change("RSAFS")
        snapshot["housing_starts"] = self.get_fred_latest("HOUST")
        snapshot["building_permits"] = self.get_fred_latest("PERMIT")

        # Inflation
        logger.info("Fetching inflation data...")
        snapshot["cpi_yoy"] = self.get_fred_yoy_change("CPIAUCSL")
        snapshot["core_cpi_yoy"] = self.get_fred_yoy_change("CPILFESL")
        snapshot["pce_yoy"] = self.get_fred_yoy_change("PCEPI")
        snapshot["core_pce_yoy"] = self.get_fred_yoy_change("PCEPILFE")
        snapshot["breakeven_5y"] = self.get_fred_latest("T5YIE")
        snapshot["breakeven_10y"] = self.get_fred_latest("T10YIE")

        # Labor Market
        logger.info("Fetching labor market data...")
        snapshot["unemployment_rate"] = self.get_fred_latest("UNRATE")
        snapshot["initial_claims"] = self.get_fred_latest("ICSA")
        snapshot["continuing_claims"] = self.get_fred_latest("CCSA")
        snapshot["nonfarm_payrolls"] = self.get_fred_latest("PAYEMS")
        snapshot["nonfarm_payrolls_yoy"] = self.get_fred_yoy_change("PAYEMS")

        # Financial Conditions
        logger.info("Fetching financial conditions...")
        snapshot["nfci"] = self.get_fred_latest("NFCI")
        snapshot["fsi"] = self.get_fred_latest("STLFSI4")

        # Consumer Sentiment
        snapshot["consumer_sentiment"] = self.get_fred_latest("UMCSENT")

        # Market Data from yfinance
        logger.info("Fetching market data...")
        snapshot["sp500"] = self.get_market_price("^GSPC")
        snapshot["sp500_yoy"] = self.get_market_returns("^GSPC", 252)
        snapshot["sp500_52w_high_pct"] = self.get_52w_high_pct("^GSPC")
        snapshot["nasdaq"] = self.get_market_price("^IXIC")
        snapshot["russell2000"] = self.get_market_price("^RUT")
        snapshot["vix"] = self.get_market_price("^VIX")
        snapshot["dollar_index"] = self.get_market_price("DX-Y.NYB")
        snapshot["gold"] = self.get_market_price("GC=F")
        snapshot["oil_wti"] = self.get_market_price("CL=F")
        snapshot["bitcoin"] = self.get_market_price("BTC-USD")
        snapshot["tlt"] = self.get_market_price("TLT")  # 20Y Treasury ETF

        # Calculate derived metrics
        if snapshot.get("treasury_10y") and snapshot.get("treasury_2y"):
            # Already have from FRED, but backup calculation
            if snapshot["yield_curve_10y_2y"] is None:
                snapshot["yield_curve_10y_2y"] = snapshot["treasury_10y"] - snapshot["treasury_2y"]

        logger.info(f"Macro snapshot complete: {sum(1 for v in snapshot.values() if v is not None)} indicators populated")
        return snapshot

    def get_liquidity_regime(self, snapshot: dict = None) -> str:
        """
        Assess current liquidity regime based on Druckenmiller's framework.

        Returns:
            "EASING", "NEUTRAL", or "TIGHTENING"
        """
        if snapshot is None:
            snapshot = self.get_macro_snapshot()

        signals = []

        # M2 growth
        m2_yoy = snapshot.get("m2_yoy_change")
        if m2_yoy is not None:
            if m2_yoy > 5:
                signals.append("EASING")
            elif m2_yoy < 0:
                signals.append("TIGHTENING")
            else:
                signals.append("NEUTRAL")

        # Yield curve
        curve = snapshot.get("yield_curve_10y_2y")
        if curve is not None:
            if curve > 1.0:
                signals.append("EASING")
            elif curve < 0:
                signals.append("TIGHTENING")
            else:
                signals.append("NEUTRAL")

        # Credit spreads
        hy_spread = snapshot.get("high_yield_spread")
        if hy_spread is not None:
            if hy_spread < 3.5:
                signals.append("EASING")
            elif hy_spread > 5.0:
                signals.append("TIGHTENING")
            else:
                signals.append("NEUTRAL")

        # Financial conditions
        nfci = snapshot.get("nfci")
        if nfci is not None:
            if nfci < -0.5:
                signals.append("EASING")
            elif nfci > 0.5:
                signals.append("TIGHTENING")
            else:
                signals.append("NEUTRAL")

        # Count signals
        if not signals:
            return "NEUTRAL"

        easing = signals.count("EASING")
        tightening = signals.count("TIGHTENING")

        if easing > tightening + 1:
            return "EASING"
        elif tightening > easing + 1:
            return "TIGHTENING"
        else:
            return "NEUTRAL"

    def get_cycle_position(self, snapshot: dict = None) -> str:
        """
        Assess current economic cycle position.

        Returns:
            "EARLY", "MID", "LATE", or "RECESSION"
        """
        if snapshot is None:
            snapshot = self.get_macro_snapshot()

        signals = []

        # Unemployment trend
        unemployment = snapshot.get("unemployment_rate")
        if unemployment is not None:
            if unemployment < 4.0:
                signals.append("LATE")
            elif unemployment > 6.0:
                signals.append("EARLY")
            else:
                signals.append("MID")

        # Yield curve (inverted = late/recession)
        curve = snapshot.get("yield_curve_10y_2y")
        if curve is not None:
            if curve < -0.5:
                signals.append("RECESSION")
            elif curve < 0:
                signals.append("LATE")
            elif curve > 1.5:
                signals.append("EARLY")
            else:
                signals.append("MID")

        # Capacity utilization
        cap_util = snapshot.get("capacity_utilization")
        if cap_util is not None:
            if cap_util > 80:
                signals.append("LATE")
            elif cap_util < 75:
                signals.append("EARLY")
            else:
                signals.append("MID")

        # Industrial production YoY
        ip_yoy = snapshot.get("industrial_production_yoy")
        if ip_yoy is not None:
            if ip_yoy < -2:
                signals.append("RECESSION")
            elif ip_yoy > 5:
                signals.append("EARLY")
            else:
                signals.append("MID")

        if not signals:
            return "MID"

        # Count signals
        from collections import Counter
        counts = Counter(signals)
        return counts.most_common(1)[0][0]


if __name__ == "__main__":
    import json

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    print("\n" + "="*60)
    print("ATLAS Macro Client - Druckenmiller-Style Analysis")
    print("="*60 + "\n")

    client = MacroClient()

    if not client.fred:
        print("WARNING: FRED API key not configured. Set FRED_API_KEY in .env")
        print("Only market data will be available.\n")

    print("Fetching macro snapshot...")
    snapshot = client.get_macro_snapshot()

    print("\n--- LIQUIDITY & FED ---")
    print(f"Fed Funds Rate: {snapshot.get('fed_funds_rate', 'N/A')}")
    print(f"M2 YoY Change: {snapshot.get('m2_yoy_change', 'N/A'):.2f}%" if snapshot.get('m2_yoy_change') else "M2 YoY: N/A")
    print(f"Yield Curve (10Y-2Y): {snapshot.get('yield_curve_10y_2y', 'N/A')}")
    print(f"HY Spread: {snapshot.get('high_yield_spread', 'N/A')}")

    print("\n--- GROWTH ---")
    print(f"GDP YoY: {snapshot.get('gdp_yoy', 'N/A'):.2f}%" if snapshot.get('gdp_yoy') else "GDP YoY: N/A")
    print(f"Industrial Production YoY: {snapshot.get('industrial_production_yoy', 'N/A'):.2f}%" if snapshot.get('industrial_production_yoy') else "IP YoY: N/A")
    print(f"Housing Starts: {snapshot.get('housing_starts', 'N/A')}")

    print("\n--- INFLATION ---")
    print(f"CPI YoY: {snapshot.get('cpi_yoy', 'N/A'):.2f}%" if snapshot.get('cpi_yoy') else "CPI YoY: N/A")
    print(f"Core PCE YoY: {snapshot.get('core_pce_yoy', 'N/A'):.2f}%" if snapshot.get('core_pce_yoy') else "Core PCE: N/A")
    print(f"5Y Breakeven: {snapshot.get('breakeven_5y', 'N/A')}")

    print("\n--- LABOR ---")
    print(f"Unemployment: {snapshot.get('unemployment_rate', 'N/A')}")
    print(f"Initial Claims: {snapshot.get('initial_claims', 'N/A')}")

    print("\n--- MARKETS ---")
    print(f"S&P 500: {snapshot.get('sp500', 'N/A'):,.2f}" if snapshot.get('sp500') else "S&P 500: N/A")
    print(f"VIX: {snapshot.get('vix', 'N/A')}")
    print(f"Dollar Index: {snapshot.get('dollar_index', 'N/A')}")
    print(f"Gold: {snapshot.get('gold', 'N/A')}")
    print(f"Oil (WTI): {snapshot.get('oil_wti', 'N/A')}")

    print("\n--- REGIME ASSESSMENT ---")
    print(f"Liquidity Regime: {client.get_liquidity_regime(snapshot)}")
    print(f"Cycle Position: {client.get_cycle_position(snapshot)}")

    # Count populated fields
    populated = sum(1 for v in snapshot.values() if v is not None)
    total = len(snapshot)
    print(f"\nData Coverage: {populated}/{total} fields populated")
