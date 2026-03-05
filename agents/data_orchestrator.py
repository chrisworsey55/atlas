"""
Data Orchestrator for ATLAS
Master orchestrator that runs all data collection on scheduled intervals.

Runs continuously and feeds fresh data to all agents:
- Real-time (1-5 min): EDGAR filings, news, options flow, technical signals, social sentiment
- Frequent (15-60 min): Earnings tracker, macro data, ETF flows
- Periodic (6-24h): Insider trades, short interest, congressional trades, 13F, econ calendar

Each agent receives a fresh data packet every time it runs.
The semiconductor desk gets SEC filings, news, options flow, insider trades,
technical signals, and social sentiment for every semiconductor ticker.
The Druckenmiller agent gets the full macro snapshot.
"""
import asyncio
import logging
import time
import threading
from datetime import datetime, timedelta
from typing import Optional, Callable
from concurrent.futures import ThreadPoolExecutor

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.universe import UNIVERSE, SEMICONDUCTOR_UNIVERSE, BIOTECH_UNIVERSE

# Import all data clients
from data.edgar_realtime_client import EDGARRealtimeClient
from data.earnings_client import EarningsClient
from data.news_sentiment_client import NewsSentimentClient
from data.options_client import OptionsClient
from data.short_interest_client import ShortInterestClient
from data.technical_client import TechnicalClient
from data.econ_calendar_client import EconCalendarClient
from data.congressional_client import CongressionalClient
from data.social_sentiment_client import SocialSentimentClient
from data.etf_flow_client import ETFFlowClient
from data.macro_client import MacroClient

logger = logging.getLogger(__name__)


class DataOrchestrator:
    """
    Runs all data collection tasks on scheduled intervals and pushes to database.
    """

    # Schedule definitions (in minutes)
    SCHEDULES = {
        # Real-time (every 1-5 minutes during market hours)
        "edgar_realtime": 1,        # New SEC filings
        "news_sentiment": 5,        # Breaking news
        "options_flow": 5,          # Unusual options activity
        "technical_signals": 5,     # Price/volume updates
        "social_sentiment": 5,      # Reddit/Twitter spikes

        # Frequent (every 15-60 minutes)
        "earnings_tracker": 15,     # Estimate revisions
        "macro_data": 15,           # Yield curves, currencies, commodities
        "etf_flows": 30,            # Sector rotation signals

        # Periodic (every few hours or daily)
        "insider_trades": 360,      # 6 hours - Form 4 filings
        "short_interest": 1440,     # 24 hours - Bi-monthly update
        "congressional": 1440,      # 24 hours - STOCK Act disclosures
        "econ_calendar": 1440,      # 24 hours - Upcoming events
    }

    def __init__(self, db_session=None):
        """
        Initialize the data orchestrator.

        Args:
            db_session: SQLAlchemy database session for persistence
        """
        self.db_session = db_session
        self._running = False
        self._executor = ThreadPoolExecutor(max_workers=5)
        self._last_run = {}
        self._data_cache = {}

        # Initialize all clients
        self.edgar_client = EDGARRealtimeClient()
        self.earnings_client = EarningsClient()
        self.news_client = NewsSentimentClient()
        self.options_client = OptionsClient()
        self.short_client = ShortInterestClient()
        self.technical_client = TechnicalClient()
        self.econ_client = EconCalendarClient()
        self.congressional_client = CongressionalClient()
        self.social_client = SocialSentimentClient()
        self.etf_client = ETFFlowClient()
        self.macro_client = MacroClient()

        # Track what data we have
        self._latest_data = {
            "edgar_filings": [],
            "insider_trades": {},
            "material_events": {},
            "news": {},
            "options": {},
            "short_interest": {},
            "technicals": {},
            "earnings": {},
            "macro_snapshot": {},
            "econ_calendar": [],
            "congressional_trades": [],
            "social_sentiment": {},
            "etf_flows": {},
        }

        logger.info("Data Orchestrator initialized")

    def _should_run(self, task_name: str) -> bool:
        """Check if a task should run based on schedule."""
        schedule_minutes = self.SCHEDULES.get(task_name, 60)
        last_run = self._last_run.get(task_name)

        if last_run is None:
            return True

        elapsed = (datetime.now() - last_run).total_seconds() / 60
        return elapsed >= schedule_minutes

    def _mark_run(self, task_name: str):
        """Mark a task as having run."""
        self._last_run[task_name] = datetime.now()

    # --- Data Collection Tasks ---

    def collect_edgar_realtime(self):
        """Collect real-time SEC EDGAR filings."""
        if not self._should_run("edgar_realtime"):
            return

        logger.info("Collecting EDGAR real-time filings...")
        try:
            # Poll for recent filings (last 5 minutes)
            filings = self.edgar_client.poll_recent_filings(
                form_types=["10-K", "10-Q", "8-K", "4", "13D", "13G"],
                minutes=5
            )
            self._latest_data["edgar_filings"] = filings

            # Store to database if session available
            if self.db_session and filings:
                self._store_filings(filings)

            logger.info(f"Collected {len(filings)} EDGAR filings")
            self._mark_run("edgar_realtime")
        except Exception as e:
            logger.error(f"EDGAR collection error: {e}")

    def collect_insider_trades(self, tickers: list = None):
        """Collect Form 4 insider trades."""
        if not self._should_run("insider_trades"):
            return

        logger.info("Collecting insider trades...")
        tickers = tickers or list(UNIVERSE.keys())

        for ticker in tickers:
            try:
                trades = self.edgar_client.get_insider_trades(ticker, days=30)
                self._latest_data["insider_trades"][ticker] = trades

                if self.db_session and trades:
                    self._store_insider_trades(ticker, trades)
            except Exception as e:
                logger.debug(f"Insider trade error for {ticker}: {e}")

        logger.info(f"Collected insider trades for {len(tickers)} tickers")
        self._mark_run("insider_trades")

    def collect_news_sentiment(self, tickers: list = None):
        """Collect news and sentiment data."""
        if not self._should_run("news_sentiment"):
            return

        logger.info("Collecting news sentiment...")
        tickers = tickers or list(UNIVERSE.keys())[:30]  # Limit for rate limits

        for ticker in tickers:
            try:
                news = self.news_client.get_latest_news(ticker, hours=24)
                self._latest_data["news"][ticker] = news

                if self.db_session and news:
                    self._store_news(ticker, news)
            except Exception as e:
                logger.debug(f"News error for {ticker}: {e}")

        # Get market-moving news
        try:
            market_moving = self.news_client.get_market_moving_news()
            self._latest_data["news"]["_market_moving"] = market_moving
        except Exception as e:
            logger.debug(f"Market-moving news error: {e}")

        logger.info(f"Collected news for {len(tickers)} tickers")
        self._mark_run("news_sentiment")

    def collect_options_flow(self, tickers: list = None):
        """Collect options flow and unusual activity."""
        if not self._should_run("options_flow"):
            return

        logger.info("Collecting options flow...")
        tickers = tickers or list(UNIVERSE.keys())[:30]

        for ticker in tickers:
            try:
                summary = self.options_client.get_options_summary(ticker)
                self._latest_data["options"][ticker] = summary

                if self.db_session:
                    self._store_options_signals(ticker, summary)
            except Exception as e:
                logger.debug(f"Options error for {ticker}: {e}")

        logger.info(f"Collected options flow for {len(tickers)} tickers")
        self._mark_run("options_flow")

    def collect_technical_signals(self, tickers: list = None):
        """Collect technical indicators."""
        if not self._should_run("technical_signals"):
            return

        logger.info("Collecting technical signals...")
        tickers = tickers or list(UNIVERSE.keys())

        for ticker in tickers:
            try:
                technicals = self.technical_client.get_technical_summary(ticker)
                self._latest_data["technicals"][ticker] = technicals

                if self.db_session:
                    self._store_technical_signals(ticker, technicals)
            except Exception as e:
                logger.debug(f"Technical error for {ticker}: {e}")

        logger.info(f"Collected technicals for {len(tickers)} tickers")
        self._mark_run("technical_signals")

    def collect_short_interest(self, tickers: list = None):
        """Collect short interest data."""
        if not self._should_run("short_interest"):
            return

        logger.info("Collecting short interest...")
        tickers = tickers or list(UNIVERSE.keys())

        for ticker in tickers:
            try:
                short_data = self.short_client.get_short_interest(ticker)
                self._latest_data["short_interest"][ticker] = short_data
            except Exception as e:
                logger.debug(f"Short interest error for {ticker}: {e}")

        logger.info(f"Collected short interest for {len(tickers)} tickers")
        self._mark_run("short_interest")

    def collect_social_sentiment(self, tickers: list = None):
        """Collect social media sentiment."""
        if not self._should_run("social_sentiment"):
            return

        logger.info("Collecting social sentiment...")
        tickers = tickers or list(UNIVERSE.keys())[:20]

        # Get trending tickers
        try:
            trending = self.social_client.get_trending_tickers(limit=20)
            self._latest_data["social_sentiment"]["_trending"] = trending
        except Exception as e:
            logger.debug(f"Trending tickers error: {e}")

        for ticker in tickers:
            try:
                sentiment = self.social_client.get_sentiment(ticker)
                wsb = self.social_client.get_wsb_activity(ticker)
                self._latest_data["social_sentiment"][ticker] = {
                    "sentiment": sentiment,
                    "wsb_activity": wsb,
                }

                if self.db_session:
                    self._store_social_sentiment(ticker, sentiment, wsb)
            except Exception as e:
                logger.debug(f"Social sentiment error for {ticker}: {e}")

        logger.info(f"Collected social sentiment for {len(tickers)} tickers")
        self._mark_run("social_sentiment")

    def collect_earnings_data(self, tickers: list = None):
        """Collect earnings data and estimate revisions."""
        if not self._should_run("earnings_tracker"):
            return

        logger.info("Collecting earnings data...")

        try:
            upcoming = self.earnings_client.get_upcoming_earnings(days_ahead=14)
            self._latest_data["earnings"]["_upcoming"] = upcoming
        except Exception as e:
            logger.debug(f"Upcoming earnings error: {e}")

        tickers = tickers or list(UNIVERSE.keys())[:20]

        for ticker in tickers:
            try:
                results = self.earnings_client.get_recent_results(ticker)
                revisions = self.earnings_client.get_estimate_revisions(ticker)
                self._latest_data["earnings"][ticker] = {
                    "results": results,
                    "revisions": revisions,
                }
            except Exception as e:
                logger.debug(f"Earnings error for {ticker}: {e}")

        logger.info(f"Collected earnings data for {len(tickers)} tickers")
        self._mark_run("earnings_tracker")

    def collect_macro_data(self):
        """Collect macro economic data."""
        if not self._should_run("macro_data"):
            return

        logger.info("Collecting macro data...")
        try:
            snapshot = self.macro_client.get_macro_snapshot()
            liquidity = self.macro_client.get_liquidity_regime(snapshot)
            cycle = self.macro_client.get_cycle_position(snapshot)

            self._latest_data["macro_snapshot"] = {
                "data": snapshot,
                "liquidity_regime": liquidity,
                "cycle_position": cycle,
                "timestamp": datetime.now().isoformat(),
            }

            logger.info(f"Collected macro data: Liquidity={liquidity}, Cycle={cycle}")
            self._mark_run("macro_data")
        except Exception as e:
            logger.error(f"Macro data error: {e}")

    def collect_etf_flows(self):
        """Collect ETF flow data."""
        if not self._should_run("etf_flows"):
            return

        logger.info("Collecting ETF flows...")
        try:
            sector_flows = self.etf_client.get_sector_flows(days=5)
            rotation = self.etf_client.get_rotation_signals(days=5)
            thematic = self.etf_client.get_thematic_flows(days=5)
            breadth = self.etf_client.get_market_breadth(days=5)

            self._latest_data["etf_flows"] = {
                "sector_flows": sector_flows,
                "rotation_signals": rotation,
                "thematic_flows": thematic,
                "market_breadth": breadth,
                "timestamp": datetime.now().isoformat(),
            }

            if self.db_session:
                self._store_etf_flows(self._latest_data["etf_flows"])

            logger.info(f"Collected ETF flows: Rotation={rotation.get('rotation_type')}")
            self._mark_run("etf_flows")
        except Exception as e:
            logger.error(f"ETF flow error: {e}")

    def collect_econ_calendar(self):
        """Collect economic calendar data."""
        if not self._should_run("econ_calendar"):
            return

        logger.info("Collecting economic calendar...")
        try:
            events = self.econ_client.get_upcoming_events(days_ahead=7)
            high_impact = self.econ_client.get_high_impact_events(days_ahead=7)
            today = self.econ_client.get_today_releases()

            self._latest_data["econ_calendar"] = {
                "upcoming": events,
                "high_impact": high_impact,
                "today_releases": today,
                "timestamp": datetime.now().isoformat(),
            }

            if self.db_session:
                self._store_econ_calendar(events)

            logger.info(f"Collected economic calendar: {len(events)} events")
            self._mark_run("econ_calendar")
        except Exception as e:
            logger.error(f"Economic calendar error: {e}")

    def collect_congressional_trades(self):
        """Collect congressional trading data."""
        if not self._should_run("congressional"):
            return

        logger.info("Collecting congressional trades...")
        try:
            trades = self.congressional_client.get_recent_trades(days=30)
            universe_trades = self.congressional_client.get_universe_trades(days=30)
            summary = self.congressional_client.get_buys_vs_sells(days=30)

            self._latest_data["congressional_trades"] = {
                "all_trades": trades,
                "universe_trades": universe_trades,
                "summary": summary,
                "timestamp": datetime.now().isoformat(),
            }

            logger.info(f"Collected congressional trades: {len(trades)} trades")
            self._mark_run("congressional")
        except Exception as e:
            logger.error(f"Congressional trades error: {e}")

    # --- Data Persistence (stubs) ---

    def _store_filings(self, filings: list):
        """Store EDGAR filings to database."""
        # TODO: Implement database storage
        pass

    def _store_insider_trades(self, ticker: str, trades: list):
        """Store insider trades to database."""
        # TODO: Implement database storage
        pass

    def _store_news(self, ticker: str, news: list):
        """Store news to database."""
        # TODO: Implement database storage
        pass

    def _store_options_signals(self, ticker: str, data: dict):
        """Store options signals to database."""
        # TODO: Implement database storage
        pass

    def _store_technical_signals(self, ticker: str, data: dict):
        """Store technical signals to database."""
        # TODO: Implement database storage
        pass

    def _store_social_sentiment(self, ticker: str, sentiment: dict, wsb: dict):
        """Store social sentiment to database."""
        # TODO: Implement database storage
        pass

    def _store_etf_flows(self, data: dict):
        """Store ETF flows to database."""
        # TODO: Implement database storage
        pass

    def _store_econ_calendar(self, events: list):
        """Store economic calendar to database."""
        # TODO: Implement database storage
        pass

    # --- Data Packet Generation ---

    def get_ticker_data_packet(self, ticker: str) -> dict:
        """
        Get comprehensive data packet for a single ticker.
        Used by sector desk agents.

        Args:
            ticker: Stock ticker symbol

        Returns:
            Dict with all available data for this ticker
        """
        return {
            "ticker": ticker,
            "company_name": UNIVERSE.get(ticker, {}).get("name", ticker),
            "sector": UNIVERSE.get(ticker, {}).get("sector", ""),
            "timestamp": datetime.now().isoformat(),
            "insider_trades": self._latest_data["insider_trades"].get(ticker, []),
            "news": self._latest_data["news"].get(ticker, []),
            "options": self._latest_data["options"].get(ticker, {}),
            "technicals": self._latest_data["technicals"].get(ticker, {}),
            "short_interest": self._latest_data["short_interest"].get(ticker, {}),
            "earnings": self._latest_data["earnings"].get(ticker, {}),
            "social_sentiment": self._latest_data["social_sentiment"].get(ticker, {}),
        }

    def get_sector_data_packet(self, sector: str) -> dict:
        """
        Get data packet for all tickers in a sector.
        Used by sector desk agents.

        Args:
            sector: Sector name

        Returns:
            Dict with ticker data and sector-level aggregations
        """
        sector_tickers = [t for t, info in UNIVERSE.items() if info.get("sector") == sector]

        ticker_data = {ticker: self.get_ticker_data_packet(ticker) for ticker in sector_tickers}

        # Get sector ETF data
        sector_etf_map = {
            "Technology": "XLK",
            "Financials": "XLF",
            "Healthcare": "XLV",
            "Energy": "XLE",
            "Consumer": "XLY",
            "Industrials": "XLI",
            "Communications": "XLC",
            "Materials": "XLB",
            "Utilities": "XLU",
            "Real Estate": "XLRE",
        }
        sector_etf = sector_etf_map.get(sector, "")

        return {
            "sector": sector,
            "timestamp": datetime.now().isoformat(),
            "tickers": sector_tickers,
            "ticker_data": ticker_data,
            "sector_etf": sector_etf,
            "sector_etf_flow": self._latest_data["etf_flows"].get("sector_flows", {}).get(sector_etf, {}),
            "market_moving_news": [n for n in self._latest_data["news"].get("_market_moving", [])
                                  if n.get("ticker") in sector_tickers],
        }

    def get_macro_data_packet(self) -> dict:
        """
        Get comprehensive macro data packet.
        Used by Druckenmiller agent.

        Returns:
            Dict with all macro data
        """
        return {
            "timestamp": datetime.now().isoformat(),
            "macro_snapshot": self._latest_data["macro_snapshot"],
            "econ_calendar": self._latest_data["econ_calendar"],
            "etf_flows": self._latest_data["etf_flows"],
            "congressional_summary": self._latest_data.get("congressional_trades", {}).get("summary", {}),
            "market_moving_news": self._latest_data["news"].get("_market_moving", []),
        }

    def get_semiconductor_packet(self) -> dict:
        """Get data packet for semiconductor desk."""
        return self.get_sector_data_packet("Technology")

    def get_biotech_packet(self) -> dict:
        """Get data packet for biotech desk."""
        return self.get_sector_data_packet("Healthcare")

    # --- Running the Orchestrator ---

    def run_once(self, tickers: list = None):
        """
        Run all data collection tasks once.
        Useful for testing or manual refresh.
        """
        logger.info("Running all data collection tasks...")

        self.collect_edgar_realtime()
        self.collect_news_sentiment(tickers)
        self.collect_options_flow(tickers)
        self.collect_technical_signals(tickers)
        self.collect_social_sentiment(tickers)
        self.collect_earnings_data(tickers)
        self.collect_macro_data()
        self.collect_etf_flows()
        self.collect_econ_calendar()
        self.collect_insider_trades(tickers)
        self.collect_short_interest(tickers)
        self.collect_congressional_trades()

        logger.info("All data collection tasks completed")

    def run(self, interval_seconds: int = 60):
        """
        Main loop - continuously run scheduled data collection tasks.

        Args:
            interval_seconds: How often to check schedules (default 60s)
        """
        self._running = True
        logger.info(f"Data Orchestrator starting (interval: {interval_seconds}s)...")

        try:
            while self._running:
                loop_start = time.time()

                # Check each task
                tasks = [
                    ("edgar_realtime", self.collect_edgar_realtime),
                    ("news_sentiment", self.collect_news_sentiment),
                    ("options_flow", self.collect_options_flow),
                    ("technical_signals", self.collect_technical_signals),
                    ("social_sentiment", self.collect_social_sentiment),
                    ("earnings_tracker", self.collect_earnings_data),
                    ("macro_data", self.collect_macro_data),
                    ("etf_flows", self.collect_etf_flows),
                    ("econ_calendar", self.collect_econ_calendar),
                    ("insider_trades", self.collect_insider_trades),
                    ("short_interest", self.collect_short_interest),
                    ("congressional", self.collect_congressional_trades),
                ]

                for task_name, task_func in tasks:
                    if self._should_run(task_name):
                        try:
                            self._executor.submit(task_func)
                        except Exception as e:
                            logger.error(f"Error submitting {task_name}: {e}")

                # Wait for next interval
                elapsed = time.time() - loop_start
                sleep_time = max(0, interval_seconds - elapsed)
                time.sleep(sleep_time)

        except KeyboardInterrupt:
            logger.info("Data Orchestrator stopping...")
            self._running = False
        finally:
            self._executor.shutdown(wait=True)

    def stop(self):
        """Stop the orchestrator."""
        self._running = False


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    print("\n" + "="*60)
    print("ATLAS Data Orchestrator")
    print("="*60 + "\n")

    orchestrator = DataOrchestrator()

    # Run once for testing
    print("Running one-time data collection (limited to 5 tickers for speed)...")
    test_tickers = ["NVDA", "AAPL", "MSFT", "META", "GOOGL"]
    orchestrator.run_once(tickers=test_tickers)

    # Print sample data packet
    print("\n--- Sample NVDA Data Packet ---")
    packet = orchestrator.get_ticker_data_packet("NVDA")
    print(f"  Timestamp: {packet.get('timestamp')}")
    print(f"  News items: {len(packet.get('news', []))}")
    print(f"  Options bias: {packet.get('options', {}).get('options_bias', 'N/A')}")
    print(f"  Technical signal: {packet.get('technicals', {}).get('overall_signal', 'N/A')}")
    print(f"  Social sentiment: {packet.get('social_sentiment', {}).get('sentiment', {}).get('overall_sentiment', 'N/A')}")

    # Print macro packet
    print("\n--- Macro Data Packet ---")
    macro = orchestrator.get_macro_data_packet()
    snapshot = macro.get("macro_snapshot", {})
    print(f"  Liquidity Regime: {snapshot.get('liquidity_regime', 'N/A')}")
    print(f"  Cycle Position: {snapshot.get('cycle_position', 'N/A')}")
    print(f"  Rotation Type: {macro.get('etf_flows', {}).get('rotation_signals', {}).get('rotation_type', 'N/A')}")

    print("\n" + "="*60)
    print("To run continuously: orchestrator.run()")
    print("="*60)
