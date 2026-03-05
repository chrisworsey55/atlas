"""
Earnings & Guidance Tracker for ATLAS
Tracks earnings dates, actual vs estimate, revenue surprise, and guidance changes.

This is what moves stocks - earnings surprises and guidance are the primary
short-term price drivers for fundamentals-based trading.

Data Sources:
- yfinance: Earnings dates, EPS/revenue estimates and actuals
- Financial Modeling Prep (FMP): Estimate revisions, analyst recommendations
- Finviz (scraping): Estimate changes for companies without API coverage
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
    yf = None

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import FMP_API_KEY
from config.universe import UNIVERSE

logger = logging.getLogger(__name__)


class EarningsClient:
    """
    Client for tracking earnings dates, estimates, actuals, and guidance.
    """

    FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"
    FINVIZ_URL = "https://finviz.com/quote.ashx?t={ticker}"

    def __init__(self, fmp_api_key: str = None):
        """
        Initialize earnings client.

        Args:
            fmp_api_key: Financial Modeling Prep API key (optional)
        """
        self.fmp_api_key = fmp_api_key or FMP_API_KEY
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        })
        self._cache = {}
        self._cache_expiry = {}
        self._cache_ttl = timedelta(minutes=30)

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

    def get_upcoming_earnings(self, days_ahead: int = 14) -> list:
        """
        Get all universe tickers reporting earnings in the next N days.

        Args:
            days_ahead: Look ahead this many days

        Returns:
            List of dicts with keys: ticker, company_name, earnings_date,
            time_of_day (BMO/AMC), eps_estimate, revenue_estimate
        """
        cache_key = f"upcoming_earnings_{days_ahead}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        upcoming = []
        end_date = datetime.now() + timedelta(days=days_ahead)

        for ticker in UNIVERSE.keys():
            try:
                stock = yf.Ticker(ticker)
                calendar = stock.calendar

                if calendar is None or calendar.empty:
                    continue

                # yfinance returns earnings date as index
                if "Earnings Date" in calendar.index:
                    earnings_dates = calendar.loc["Earnings Date"]
                    if isinstance(earnings_dates, pd.Series):
                        next_date = earnings_dates.iloc[0] if len(earnings_dates) > 0 else None
                    else:
                        next_date = earnings_dates

                    if next_date and isinstance(next_date, (datetime, pd.Timestamp)):
                        if datetime.now() <= next_date <= end_date:
                            # Get estimates
                            eps_est = calendar.loc["EPS Estimate"].iloc[0] if "EPS Estimate" in calendar.index else None
                            rev_est = calendar.loc["Revenue Estimate"].iloc[0] if "Revenue Estimate" in calendar.index else None

                            upcoming.append({
                                "ticker": ticker,
                                "company_name": UNIVERSE[ticker]["name"],
                                "sector": UNIVERSE[ticker]["sector"],
                                "earnings_date": next_date.strftime("%Y-%m-%d"),
                                "days_until": (next_date - datetime.now()).days,
                                "eps_estimate": float(eps_est) if eps_est else None,
                                "revenue_estimate": float(rev_est) if rev_est else None,
                            })
            except Exception as e:
                logger.debug(f"Error getting earnings for {ticker}: {e}")
                continue

        # Sort by earnings date
        upcoming.sort(key=lambda x: x["earnings_date"])

        logger.info(f"Found {len(upcoming)} companies reporting in next {days_ahead} days")
        self._set_cached(cache_key, upcoming)
        return upcoming

    def get_recent_results(self, ticker: str) -> dict:
        """
        Get latest earnings results with actual vs estimate.

        Args:
            ticker: Stock ticker symbol

        Returns:
            Dict with keys: ticker, earnings_date, eps_actual, eps_estimate, eps_surprise,
            eps_surprise_pct, revenue_actual, revenue_estimate, revenue_surprise,
            revenue_surprise_pct, guidance_status
        """
        cache_key = f"recent_results_{ticker}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            stock = yf.Ticker(ticker)

            result = {
                "ticker": ticker,
                "company_name": UNIVERSE.get(ticker, {}).get("name", ticker),
                "sector": UNIVERSE.get(ticker, {}).get("sector", ""),
            }

            # Get earnings history
            earnings_hist = stock.earnings_history
            if earnings_hist is not None and not earnings_hist.empty:
                latest = earnings_hist.iloc[-1]

                result["earnings_date"] = latest.name.strftime("%Y-%m-%d") if hasattr(latest.name, "strftime") else str(latest.name)
                result["eps_actual"] = float(latest.get("epsActual")) if latest.get("epsActual") else None
                result["eps_estimate"] = float(latest.get("epsEstimate")) if latest.get("epsEstimate") else None

                if result["eps_actual"] is not None and result["eps_estimate"] is not None:
                    result["eps_surprise"] = result["eps_actual"] - result["eps_estimate"]
                    if result["eps_estimate"] != 0:
                        result["eps_surprise_pct"] = (result["eps_surprise"] / abs(result["eps_estimate"])) * 100
                    else:
                        result["eps_surprise_pct"] = None

            # Get quarterly financials for revenue
            quarterly = stock.quarterly_financials
            if quarterly is not None and not quarterly.empty:
                if "Total Revenue" in quarterly.index:
                    result["revenue_actual"] = float(quarterly.loc["Total Revenue"].iloc[0])

            # Try to get analyst revenue estimates
            analysis = stock.analyst_price_targets
            if analysis is not None and not analysis.empty:
                result["analyst_target_mean"] = analysis.get("targetMeanPrice")
                result["analyst_target_low"] = analysis.get("targetLowPrice")
                result["analyst_target_high"] = analysis.get("targetHighPrice")

            # Determine guidance status (requires 8-K parsing or earnings call transcript)
            # For now, we'll mark as unknown and let news client fill this in
            result["guidance_status"] = "UNKNOWN"  # RAISED, LOWERED, MAINTAINED, UNKNOWN

            self._set_cached(cache_key, result)
            return result

        except Exception as e:
            logger.error(f"Error getting earnings results for {ticker}: {e}")
            return {"ticker": ticker, "error": str(e)}

    def get_earnings_history(self, ticker: str, quarters: int = 8) -> list:
        """
        Get historical earnings for beat/miss pattern analysis.

        Args:
            ticker: Stock ticker symbol
            quarters: Number of quarters to retrieve

        Returns:
            List of quarterly earnings dicts, most recent first
        """
        try:
            stock = yf.Ticker(ticker)
            earnings_hist = stock.earnings_history

            if earnings_hist is None or earnings_hist.empty:
                return []

            history = []
            for idx, row in earnings_hist.tail(quarters).iterrows():
                eps_actual = row.get("epsActual")
                eps_est = row.get("epsEstimate")

                result = {
                    "date": idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx),
                    "eps_actual": float(eps_actual) if eps_actual else None,
                    "eps_estimate": float(eps_est) if eps_est else None,
                }

                if result["eps_actual"] is not None and result["eps_estimate"] is not None:
                    result["surprise"] = result["eps_actual"] - result["eps_estimate"]
                    result["beat"] = result["eps_actual"] > result["eps_estimate"]
                    if result["eps_estimate"] != 0:
                        result["surprise_pct"] = (result["surprise"] / abs(result["eps_estimate"])) * 100

                history.append(result)

            # Most recent first
            history.reverse()
            return history

        except Exception as e:
            logger.error(f"Error getting earnings history for {ticker}: {e}")
            return []

    def get_estimate_revisions(self, ticker: str) -> dict:
        """
        Get analyst estimate revision trends over 30/60/90 days.
        Rising estimates = bullish signal, falling estimates = bearish.

        Args:
            ticker: Stock ticker symbol

        Returns:
            Dict with estimate revision data and trend signals
        """
        cache_key = f"estimate_revisions_{ticker}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        result = {
            "ticker": ticker,
            "trend": "NEUTRAL",  # IMPROVING, STABLE, DETERIORATING
        }

        # Try FMP API first (if key available)
        if self.fmp_api_key:
            try:
                fmp_data = self._get_fmp_estimates(ticker)
                if fmp_data:
                    result.update(fmp_data)
                    self._set_cached(cache_key, result)
                    return result
            except Exception as e:
                logger.debug(f"FMP estimate fetch failed for {ticker}: {e}")

        # Fallback to yfinance recommendations
        try:
            stock = yf.Ticker(ticker)

            # Get analyst recommendations
            recs = stock.recommendations
            if recs is not None and not recs.empty:
                recent_recs = recs.tail(30)  # Last 30 recommendations

                # Count upgrades vs downgrades
                upgrades = len(recent_recs[recent_recs["To Grade"].isin(["Buy", "Overweight", "Outperform", "Strong Buy"])])
                downgrades = len(recent_recs[recent_recs["To Grade"].isin(["Sell", "Underweight", "Underperform", "Strong Sell"])])
                holds = len(recent_recs[recent_recs["To Grade"].isin(["Hold", "Neutral", "Equal-Weight"])])

                result["upgrades_30d"] = upgrades
                result["downgrades_30d"] = downgrades
                result["holds_30d"] = holds

                if upgrades > downgrades * 1.5:
                    result["trend"] = "IMPROVING"
                elif downgrades > upgrades * 1.5:
                    result["trend"] = "DETERIORATING"
                else:
                    result["trend"] = "STABLE"

            # Get recommendations summary
            rec_trend = stock.recommendations_summary
            if rec_trend is not None and not rec_trend.empty:
                result["strong_buy"] = int(rec_trend.get("strongBuy", [0])[0]) if "strongBuy" in rec_trend.columns else 0
                result["buy"] = int(rec_trend.get("buy", [0])[0]) if "buy" in rec_trend.columns else 0
                result["hold"] = int(rec_trend.get("hold", [0])[0]) if "hold" in rec_trend.columns else 0
                result["sell"] = int(rec_trend.get("sell", [0])[0]) if "sell" in rec_trend.columns else 0
                result["strong_sell"] = int(rec_trend.get("strongSell", [0])[0]) if "strongSell" in rec_trend.columns else 0

        except Exception as e:
            logger.debug(f"Error getting yfinance recommendations for {ticker}: {e}")

        # Try Finviz scraping as additional source
        try:
            finviz_data = self._scrape_finviz_estimates(ticker)
            if finviz_data:
                result.update(finviz_data)
        except Exception as e:
            logger.debug(f"Finviz scrape failed for {ticker}: {e}")

        self._set_cached(cache_key, result)
        return result

    def _get_fmp_estimates(self, ticker: str) -> Optional[dict]:
        """Get estimate data from Financial Modeling Prep API."""
        if not self.fmp_api_key:
            return None

        try:
            # Get analyst estimates
            url = f"{self.FMP_BASE_URL}/analyst-estimates/{ticker}"
            params = {"apikey": self.fmp_api_key}

            resp = self.session.get(url, params=params, timeout=10)
            if resp.status_code != 200:
                return None

            data = resp.json()
            if not data:
                return None

            latest = data[0] if data else {}

            return {
                "estimated_revenue_avg": latest.get("estimatedRevenueAvg"),
                "estimated_revenue_low": latest.get("estimatedRevenueLow"),
                "estimated_revenue_high": latest.get("estimatedRevenueHigh"),
                "estimated_eps_avg": latest.get("estimatedEpsAvg"),
                "estimated_eps_low": latest.get("estimatedEpsLow"),
                "estimated_eps_high": latest.get("estimatedEpsHigh"),
                "number_analysts_estimated_revenue": latest.get("numberAnalystsEstimatedRevenue"),
                "number_analysts_estimated_eps": latest.get("numberAnalystEstimatedEps"),
                "fmp_data": True,
            }
        except Exception as e:
            logger.error(f"FMP API error for {ticker}: {e}")
            return None

    def _scrape_finviz_estimates(self, ticker: str) -> Optional[dict]:
        """Scrape estimate data from Finviz (free, no API needed)."""
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

                if key == "EPS next Y":
                    try:
                        data["eps_estimate_next_year"] = float(value.replace("%", "")) if "%" not in value else float(value.replace("%", "")) / 100
                    except:
                        pass
                elif key == "EPS next Q":
                    try:
                        data["eps_estimate_next_quarter"] = float(value)
                    except:
                        pass
                elif key == "Sales Q/Q":
                    try:
                        data["revenue_growth_qoq"] = float(value.replace("%", ""))
                    except:
                        pass
                elif key == "EPS Q/Q":
                    try:
                        data["eps_growth_qoq"] = float(value.replace("%", ""))
                    except:
                        pass
                elif key == "Target Price":
                    try:
                        data["finviz_target_price"] = float(value)
                    except:
                        pass
                elif key == "Recom":
                    try:
                        # Finviz uses 1-5 scale: 1=Strong Buy, 5=Strong Sell
                        data["finviz_recommendation"] = float(value)
                    except:
                        pass

            if data:
                data["finviz_data"] = True

            return data if data else None

        except Exception as e:
            logger.debug(f"Finviz scrape error for {ticker}: {e}")
            return None

    def get_earnings_calendar_by_sector(self, days_ahead: int = 14) -> dict:
        """
        Get earnings calendar grouped by sector.

        Args:
            days_ahead: Look ahead this many days

        Returns:
            Dict mapping sector -> list of upcoming earnings
        """
        upcoming = self.get_upcoming_earnings(days_ahead)

        by_sector = {}
        for earning in upcoming:
            sector = earning.get("sector", "Unknown")
            if sector not in by_sector:
                by_sector[sector] = []
            by_sector[sector].append(earning)

        return by_sector

    def get_earnings_surprises(self, min_surprise_pct: float = 5.0) -> list:
        """
        Get recent earnings surprises above threshold for all universe.

        Args:
            min_surprise_pct: Minimum absolute surprise percentage to include

        Returns:
            List of earnings results with significant surprises
        """
        surprises = []

        for ticker in UNIVERSE.keys():
            try:
                result = self.get_recent_results(ticker)
                surprise_pct = result.get("eps_surprise_pct")

                if surprise_pct is not None and abs(surprise_pct) >= min_surprise_pct:
                    result["surprise_direction"] = "BEAT" if surprise_pct > 0 else "MISS"
                    surprises.append(result)
            except Exception as e:
                logger.debug(f"Error checking surprises for {ticker}: {e}")
                continue

        # Sort by absolute surprise
        surprises.sort(key=lambda x: abs(x.get("eps_surprise_pct", 0)), reverse=True)
        return surprises


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    print("\n" + "="*60)
    print("ATLAS Earnings Client")
    print("="*60 + "\n")

    client = EarningsClient()

    # Test upcoming earnings
    print("--- Upcoming Earnings (14 days) ---")
    upcoming = client.get_upcoming_earnings(days_ahead=14)
    for e in upcoming[:10]:
        print(f"  {e['earnings_date']} | {e['ticker']} | {e['company_name'][:30]} | Days: {e['days_until']}")

    # Test recent results
    print("\n--- NVDA Recent Results ---")
    results = client.get_recent_results("NVDA")
    for k, v in results.items():
        if v is not None and k != "ticker":
            print(f"  {k}: {v}")

    # Test earnings history
    print("\n--- NVDA Earnings History ---")
    history = client.get_earnings_history("NVDA", quarters=4)
    for h in history:
        beat_str = "BEAT" if h.get("beat") else "MISS" if h.get("beat") is not None else "N/A"
        print(f"  {h['date']} | EPS: {h.get('eps_actual', 'N/A')} vs {h.get('eps_estimate', 'N/A')} | {beat_str}")

    # Test estimate revisions
    print("\n--- NVDA Estimate Revisions ---")
    revisions = client.get_estimate_revisions("NVDA")
    print(f"  Trend: {revisions.get('trend')}")
    print(f"  Upgrades (30d): {revisions.get('upgrades_30d', 'N/A')}")
    print(f"  Downgrades (30d): {revisions.get('downgrades_30d', 'N/A')}")

    # Test by sector
    print("\n--- Earnings by Sector ---")
    by_sector = client.get_earnings_calendar_by_sector()
    for sector, earnings in by_sector.items():
        print(f"  {sector}: {len(earnings)} companies reporting")
