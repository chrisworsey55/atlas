"""
Economic Calendar Client for ATLAS
Tracks upcoming economic data releases that move markets.

The macro desks need to know what data is coming. A CPI print or Fed meeting
changes everything. This client tracks:

- FOMC meetings and rate decisions
- CPI, PPI (inflation data)
- NFP (nonfarm payrolls)
- GDP releases
- PMI (manufacturing/services)
- Housing starts, retail sales
- Consumer confidence
- Trade balance

Data Sources:
- FRED API for historical data
- Scraping Investing.com economic calendar
- ForexFactory calendar (backup)
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
import requests
from bs4 import BeautifulSoup

try:
    from fredapi import Fred
    FRED_AVAILABLE = True
except ImportError:
    FRED_AVAILABLE = False
    Fred = None

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import FRED_API_KEY

logger = logging.getLogger(__name__)


# Key economic indicators and their importance
ECONOMIC_INDICATORS = {
    "FOMC": {"importance": "HIGH", "description": "Federal Reserve interest rate decision"},
    "NFP": {"importance": "HIGH", "description": "Nonfarm Payrolls - monthly jobs report"},
    "CPI": {"importance": "HIGH", "description": "Consumer Price Index - inflation measure"},
    "Core CPI": {"importance": "HIGH", "description": "CPI excluding food and energy"},
    "PPI": {"importance": "MEDIUM", "description": "Producer Price Index"},
    "GDP": {"importance": "HIGH", "description": "Gross Domestic Product"},
    "Retail Sales": {"importance": "MEDIUM", "description": "Monthly retail sales"},
    "PMI": {"importance": "MEDIUM", "description": "Purchasing Managers Index"},
    "ISM Manufacturing": {"importance": "MEDIUM", "description": "Manufacturing activity"},
    "ISM Services": {"importance": "MEDIUM", "description": "Services sector activity"},
    "Consumer Confidence": {"importance": "MEDIUM", "description": "Consumer sentiment"},
    "Michigan Sentiment": {"importance": "MEDIUM", "description": "University of Michigan consumer sentiment"},
    "Housing Starts": {"importance": "LOW", "description": "New residential construction"},
    "Building Permits": {"importance": "LOW", "description": "Permits for new construction"},
    "Durable Goods": {"importance": "MEDIUM", "description": "Durable goods orders"},
    "Trade Balance": {"importance": "LOW", "description": "Import/export balance"},
    "Initial Claims": {"importance": "MEDIUM", "description": "Weekly jobless claims"},
    "PCE": {"importance": "HIGH", "description": "Personal Consumption Expenditures - Fed's preferred inflation measure"},
    "Core PCE": {"importance": "HIGH", "description": "PCE excluding food and energy"},
}


class EconCalendarClient:
    """
    Client for tracking economic calendar and data releases.
    """

    INVESTING_CALENDAR_URL = "https://www.investing.com/economic-calendar/"

    def __init__(self, fred_api_key: str = None):
        """
        Initialize economic calendar client.

        Args:
            fred_api_key: FRED API key for historical data
        """
        self.fred_api_key = fred_api_key or FRED_API_KEY
        self._fred = None
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        })
        self._cache = {}
        self._cache_expiry = {}
        self._cache_ttl = timedelta(hours=1)

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

    def get_upcoming_events(self, days_ahead: int = 7) -> list:
        """
        Get upcoming economic events.

        Args:
            days_ahead: Days to look ahead

        Returns:
            List of event dicts with date, event, forecast, previous, importance
        """
        cache_key = f"upcoming_events_{days_ahead}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        events = []

        # Try to scrape Investing.com calendar
        try:
            scraped = self._scrape_investing_calendar(days_ahead)
            events.extend(scraped)
        except Exception as e:
            logger.debug(f"Investing.com scrape failed: {e}")

        # Add known recurring events based on typical schedule
        known_events = self._get_known_schedule(days_ahead)
        events.extend(known_events)

        # Deduplicate by event name and date
        seen = set()
        unique_events = []
        for event in events:
            key = (event.get("date", ""), event.get("event", ""))
            if key not in seen:
                seen.add(key)
                unique_events.append(event)

        # Sort by date
        unique_events.sort(key=lambda x: x.get("date", ""))

        self._set_cached(cache_key, unique_events)
        return unique_events

    def _scrape_investing_calendar(self, days_ahead: int) -> list:
        """Scrape economic calendar from Investing.com."""
        events = []

        try:
            # Investing.com requires specific headers and sometimes blocks scrapers
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            }

            resp = self.session.get(self.INVESTING_CALENDAR_URL, headers=headers, timeout=15)
            if resp.status_code != 200:
                return events

            soup = BeautifulSoup(resp.text, "html.parser")

            # Find economic calendar table
            table = soup.find("table", {"id": "economicCalendarData"})
            if not table:
                return events

            rows = table.find_all("tr", class_="js-event-item")

            for row in rows:
                try:
                    # Get country (filter for US only)
                    country = row.get("data-country", "")
                    if "United States" not in country and country != "5":  # 5 is US code
                        continue

                    # Get event name
                    event_cell = row.find("td", class_="event")
                    if event_cell:
                        event_name = event_cell.get_text(strip=True)
                    else:
                        continue

                    # Get date/time
                    time_cell = row.find("td", class_="time")
                    time_str = time_cell.get_text(strip=True) if time_cell else ""

                    date_attr = row.get("data-event-datetime", "")

                    # Get importance (bull icons)
                    importance_cell = row.find("td", class_="sentiment")
                    if importance_cell:
                        bulls = len(importance_cell.find_all("i", class_="grayFullBullishIcon"))
                        importance = "HIGH" if bulls >= 3 else "MEDIUM" if bulls >= 2 else "LOW"
                    else:
                        importance = "LOW"

                    # Get actual, forecast, previous
                    actual_cell = row.find("td", class_="act")
                    forecast_cell = row.find("td", class_="fore")
                    previous_cell = row.find("td", class_="prev")

                    events.append({
                        "date": date_attr[:10] if date_attr else "",
                        "time": time_str,
                        "event": event_name,
                        "country": "US",
                        "importance": importance,
                        "actual": actual_cell.get_text(strip=True) if actual_cell else None,
                        "forecast": forecast_cell.get_text(strip=True) if forecast_cell else None,
                        "previous": previous_cell.get_text(strip=True) if previous_cell else None,
                    })
                except Exception as e:
                    logger.debug(f"Error parsing calendar row: {e}")
                    continue

        except Exception as e:
            logger.debug(f"Calendar scrape error: {e}")

        return events

    def _get_known_schedule(self, days_ahead: int) -> list:
        """
        Generate known recurring events based on typical schedule.
        FOMC meets 8 times per year, NFP is first Friday, etc.
        """
        events = []
        today = datetime.now()
        end_date = today + timedelta(days=days_ahead)

        # FOMC meeting dates for 2025-2026 (approximate - these are well-known)
        fomc_dates = [
            "2026-01-29", "2026-03-19", "2026-05-07", "2026-06-18",
            "2026-07-29", "2026-09-17", "2026-11-05", "2026-12-17",
        ]

        for date_str in fomc_dates:
            try:
                date = datetime.strptime(date_str, "%Y-%m-%d")
                if today <= date <= end_date:
                    events.append({
                        "date": date_str,
                        "time": "14:00",
                        "event": "FOMC Rate Decision",
                        "country": "US",
                        "importance": "HIGH",
                        "description": ECONOMIC_INDICATORS["FOMC"]["description"],
                    })
            except:
                continue

        # NFP is typically first Friday of the month
        current_month = today.replace(day=1)
        for _ in range(3):  # Check next 3 months
            # Find first Friday
            day = current_month
            while day.weekday() != 4:  # Friday = 4
                day += timedelta(days=1)

            if today <= day <= end_date:
                events.append({
                    "date": day.strftime("%Y-%m-%d"),
                    "time": "08:30",
                    "event": "Nonfarm Payrolls",
                    "country": "US",
                    "importance": "HIGH",
                    "description": ECONOMIC_INDICATORS["NFP"]["description"],
                })

            # Move to next month
            if current_month.month == 12:
                current_month = current_month.replace(year=current_month.year + 1, month=1)
            else:
                current_month = current_month.replace(month=current_month.month + 1)

        # CPI is typically mid-month
        current_month = today.replace(day=1)
        for _ in range(3):
            cpi_date = current_month.replace(day=13)  # Approximate
            # Adjust to weekday
            while cpi_date.weekday() >= 5:
                cpi_date += timedelta(days=1)

            if today <= cpi_date <= end_date:
                events.append({
                    "date": cpi_date.strftime("%Y-%m-%d"),
                    "time": "08:30",
                    "event": "CPI",
                    "country": "US",
                    "importance": "HIGH",
                    "description": ECONOMIC_INDICATORS["CPI"]["description"],
                })

            # Move to next month
            if current_month.month == 12:
                current_month = current_month.replace(year=current_month.year + 1, month=1)
            else:
                current_month = current_month.replace(month=current_month.month + 1)

        return events

    def get_today_releases(self) -> list:
        """
        Get economic data released today and any surprises.

        Returns:
            List of today's releases with actual vs forecast
        """
        cache_key = "today_releases"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        today = datetime.now().strftime("%Y-%m-%d")
        all_events = self.get_upcoming_events(days_ahead=1)

        today_events = [e for e in all_events if e.get("date") == today]

        # Calculate surprise for released data
        for event in today_events:
            actual = event.get("actual")
            forecast = event.get("forecast")

            if actual and forecast:
                try:
                    # Parse numbers (handle percentages, etc.)
                    actual_val = float(actual.replace("%", "").replace(",", ""))
                    forecast_val = float(forecast.replace("%", "").replace(",", ""))

                    surprise = actual_val - forecast_val
                    event["surprise"] = surprise
                    event["surprise_pct"] = (surprise / abs(forecast_val) * 100) if forecast_val != 0 else None

                    if surprise > 0:
                        event["direction"] = "BEAT"
                    elif surprise < 0:
                        event["direction"] = "MISS"
                    else:
                        event["direction"] = "INLINE"
                except:
                    pass

        self._set_cached(cache_key, today_events)
        return today_events

    def get_historical_indicator(self, indicator: str, periods: int = 12) -> list:
        """
        Get historical data for an indicator from FRED.

        Args:
            indicator: Indicator name (CPI, GDP, etc.)
            periods: Number of historical periods

        Returns:
            List of historical values
        """
        if not self.fred:
            return []

        # Map indicator names to FRED series
        fred_series = {
            "CPI": "CPIAUCSL",
            "Core CPI": "CPILFESL",
            "GDP": "GDP",
            "Unemployment": "UNRATE",
            "NFP": "PAYEMS",
            "PCE": "PCEPI",
            "Core PCE": "PCEPILFE",
            "Retail Sales": "RSAFS",
            "Housing Starts": "HOUST",
            "ISM Manufacturing": "MANEMP",
            "Consumer Confidence": "UMCSENT",
        }

        series_id = fred_series.get(indicator)
        if not series_id:
            return []

        try:
            data = self.fred.get_series(series_id)
            if data is None or data.empty:
                return []

            # Get last N periods
            recent = data.tail(periods)
            result = []

            for date, value in recent.items():
                result.append({
                    "date": date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date),
                    "value": float(value),
                })

            return result
        except Exception as e:
            logger.error(f"FRED fetch error for {indicator}: {e}")
            return []

    def get_high_impact_events(self, days_ahead: int = 7) -> list:
        """
        Get only HIGH importance events.

        Args:
            days_ahead: Days to look ahead

        Returns:
            List of high-impact events
        """
        all_events = self.get_upcoming_events(days_ahead)
        return [e for e in all_events if e.get("importance") == "HIGH"]

    def get_calendar_by_week(self, days_ahead: int = 14) -> dict:
        """
        Get economic calendar organized by week.

        Returns:
            Dict mapping week start date -> list of events
        """
        events = self.get_upcoming_events(days_ahead)

        by_week = {}
        for event in events:
            date_str = event.get("date", "")
            if not date_str:
                continue

            try:
                date = datetime.strptime(date_str, "%Y-%m-%d")
                # Get Monday of that week
                week_start = date - timedelta(days=date.weekday())
                week_key = week_start.strftime("%Y-%m-%d")

                if week_key not in by_week:
                    by_week[week_key] = []
                by_week[week_key].append(event)
            except:
                continue

        return by_week


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    print("\n" + "="*60)
    print("ATLAS Economic Calendar Client")
    print("="*60 + "\n")

    client = EconCalendarClient()

    # Test upcoming events
    print("--- Upcoming Economic Events (7 days) ---")
    events = client.get_upcoming_events(days_ahead=7)
    for e in events[:10]:
        importance = e.get("importance", "")
        marker = "***" if importance == "HIGH" else "**" if importance == "MEDIUM" else "*"
        print(f"  {e.get('date', 'N/A')} | {e.get('event', 'N/A')[:30]} | {marker}{importance}")

    # Test high-impact events
    print("\n--- High-Impact Events ---")
    high_impact = client.get_high_impact_events(days_ahead=14)
    for e in high_impact[:5]:
        print(f"  {e.get('date', 'N/A')} | {e.get('event', 'N/A')}")

    # Test today's releases
    print("\n--- Today's Releases ---")
    today = client.get_today_releases()
    if today:
        for e in today:
            direction = e.get("direction", "PENDING")
            print(f"  {e.get('event', 'N/A')} | Actual: {e.get('actual', 'TBD')} | Forecast: {e.get('forecast', 'N/A')} | {direction}")
    else:
        print("  No releases today or data not yet available")

    # Test historical data
    print("\n--- Historical CPI (FRED) ---")
    cpi_history = client.get_historical_indicator("CPI", periods=6)
    for h in cpi_history:
        print(f"  {h['date']} | {h['value']:.1f}")

    # Test by week
    print("\n--- Calendar by Week ---")
    by_week = client.get_calendar_by_week(days_ahead=14)
    for week, week_events in sorted(by_week.items()):
        high_count = len([e for e in week_events if e.get("importance") == "HIGH"])
        print(f"  Week of {week}: {len(week_events)} events ({high_count} high-impact)")
