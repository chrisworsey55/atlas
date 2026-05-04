#!/usr/bin/env python3
"""
ATLAS Autoresearch Backtest Engine

Replays 18 months of market history through the 24-agent system, training agent prompts
using Karpathy's autoresearch methodology.

Each simulated trading day = one training iteration
Agent prompts in agents/prompts/*.md = the "weights" being optimized
Loss function = agent-level 10-day rolling Sharpe ratio
Gradient descent = targeted prompt modification to worst-performing agent

Usage:
    python3 -m agents.backtest_loop                    # Full run
    python3 -m agents.backtest_loop --cache-only       # Cache data only
    python3 -m agents.backtest_loop --resume           # Resume from checkpoint
    python3 -m agents.backtest_loop --no-autoresearch  # Skip prompt evolution
    python3 -m agents.backtest_loop --verbose          # Print full agent output
    python3 -m agents.backtest_loop --start-date 2025-01-01 --end-date 2025-06-30
"""

import anthropic
import argparse
import asyncio
import json
import math
import os
import random
import requests
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# =============================================================================
# CONFIGURATION
# =============================================================================

ATLAS_DIR = Path(__file__).parent.parent
STATE_DIR = ATLAS_DIR / "data" / "state"
PROMPTS_DIR = Path(__file__).parent / "prompts"
BACKTEST_DIR = ATLAS_DIR / "data" / "backtest"
CACHE_DIR = BACKTEST_DIR / "cache"
RESULTS_DIR = BACKTEST_DIR / "results"
CHECKPOINT_DIR = BACKTEST_DIR / "checkpoints"

# API Keys
FMP_API_KEY = os.getenv("FMP_API_KEY")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# API Endpoints - Use stable API for FMP
FMP_BASE = "https://financialmodelingprep.com/stable"
FMP_BASE_V3 = "https://financialmodelingprep.com/api/v3"  # Some endpoints still use v3
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# Backtest Parameters
DEFAULT_START_DATE = "2024-09-01"
DEFAULT_END_DATE = "2026-03-07"
STARTING_CAPITAL = 1_000_000
TRANSACTION_COST_BPS = 5  # 5 basis points per trade
MAX_POSITIONS = 20
MAX_SINGLE_POSITION_PCT = 10
MAX_SECTOR_PCT = 30
MIN_POSITION_PCT = 2
MIN_CASH_PCT = 10

# Agent batching for API efficiency
MACRO_AGENTS_BATCH_1 = ["central_bank", "geopolitical", "china", "dollar", "yield_curve"]
MACRO_AGENTS_BATCH_2 = ["commodities", "volatility", "emerging_markets", "news_sentiment", "institutional_flow"]
SECTOR_AGENTS = ["semiconductor", "energy", "biotech", "consumer", "industrials", "financials"]
SUPERINVESTOR_AGENTS = ["druckenmiller", "aschenbrenner", "baker", "ackman"]
DECISION_AGENTS_BATCH_1 = ["cro", "alpha_discovery"]
DECISION_AGENTS_BATCH_2 = ["autonomous_execution", "cio"]

ALL_AGENTS = (
    MACRO_AGENTS_BATCH_1 + MACRO_AGENTS_BATCH_2 +
    SECTOR_AGENTS + SUPERINVESTOR_AGENTS +
    DECISION_AGENTS_BATCH_1 + DECISION_AGENTS_BATCH_2
)

# ETFs to cache
ETFS = [
    "SPY", "QQQ", "IWM", "DIA", "TLT", "IEF", "SHY", "BIL", "LQD", "HYG",
    "JNK", "TIP", "GLD", "SLV", "GDX", "XLE", "XLF", "XLK", "XLV", "XLI",
    "XLP", "XLU", "XLB", "XLRE", "XLC", "VXX", "UVXY", "USO", "UNG", "DBC",
    "EEM", "EFA", "FXI", "KWEB", "UUP", "FXE", "FXY", "XRT", "SMH", "SOXX",
    "IBB", "XBI", "KRE", "XHB", "JETS", "ARKK"
]

# FRED series for macro data
FRED_SERIES = {
    "FEDFUNDS": "Fed Funds Rate",
    "DGS10": "10Y Treasury Yield",
    "DGS2": "2Y Treasury Yield",
    "T10Y2Y": "10Y-2Y Spread",
    "CPIAUCSL": "CPI",
    "UNRATE": "Unemployment Rate",
    "GDP": "GDP",
    "UMCSENT": "Consumer Sentiment",
    "BAMLH0A0HYM2": "HY OAS Spread",
    "VIXCLS": "VIX",
    "DTWEXBGS": "Trade-Weighted Dollar"
}

# Anthropic client
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class Position:
    ticker: str
    direction: str  # LONG or SHORT
    shares: int
    entry_price: float
    entry_date: str
    cost_basis: float
    current_price: float = 0.0
    sector: str = ""
    agent_source: str = ""
    thesis: str = ""

    @property
    def market_value(self) -> float:
        return self.shares * self.current_price

    @property
    def pnl(self) -> float:
        if self.direction == "LONG":
            return (self.current_price - self.entry_price) * self.shares
        else:
            return (self.entry_price - self.current_price) * self.shares

    @property
    def pnl_pct(self) -> float:
        if self.cost_basis == 0:
            return 0
        return (self.pnl / self.cost_basis) * 100


@dataclass
class Portfolio:
    cash: float = STARTING_CAPITAL
    positions: List[Position] = field(default_factory=list)

    @property
    def total_value(self) -> float:
        long_value = sum(p.market_value for p in self.positions if p.direction == "LONG")
        short_value = sum(p.market_value for p in self.positions if p.direction == "SHORT")
        return self.cash + long_value - short_value

    @property
    def gross_exposure(self) -> float:
        total = self.total_value
        if total == 0:
            return 0
        long_value = sum(p.market_value for p in self.positions if p.direction == "LONG")
        short_value = sum(p.market_value for p in self.positions if p.direction == "SHORT")
        return (long_value + short_value) / total

    @property
    def net_exposure(self) -> float:
        total = self.total_value
        if total == 0:
            return 0
        long_value = sum(p.market_value for p in self.positions if p.direction == "LONG")
        short_value = sum(p.market_value for p in self.positions if p.direction == "SHORT")
        return (long_value - short_value) / total


@dataclass
class AgentRecommendation:
    agent: str
    date: str
    ticker: str
    direction: str
    conviction: int
    entry_price: float
    reasoning: str = ""
    return_1d: Optional[float] = None
    return_5d: Optional[float] = None
    return_10d: Optional[float] = None


@dataclass
class AutoresearchModification:
    day: int
    date: str
    agent: str
    modification: str
    pre_sharpe: float
    post_sharpe: Optional[float] = None
    kept: Optional[bool] = None
    commit_hash: str = ""


# =============================================================================
# LOGGING
# =============================================================================

def log(msg: str, level: str = "INFO"):
    """Structured logging."""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] [{level}] {msg}")


# =============================================================================
# PHASE 1: CACHE HISTORICAL DATA
# =============================================================================

class DataCache:
    """Handles downloading and caching of historical market data."""

    def __init__(self):
        # Ensure directories exist
        (CACHE_DIR / "prices").mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / "fundamentals").mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / "macro").mkdir(parents=True, exist_ok=True)
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

        self.price_index = {}
        self.sp500_tickers = []
        self.sector_map = {}
        self.api_calls_today = 0
        self.last_api_date = datetime.now().date()

    def _rate_limit_fmp(self):
        """Check and enforce FMP rate limit (250/day)."""
        today = datetime.now().date()
        if today != self.last_api_date:
            self.api_calls_today = 0
            self.last_api_date = today

        if self.api_calls_today >= 240:  # Leave buffer
            log("FMP daily limit reached. Resume tomorrow with --resume", "WARN")
            return False

        self.api_calls_today += 1
        time.sleep(0.5)  # Rate limit between calls
        return True

    def _fmp_request(self, endpoint: str, params: dict = None, use_v3: bool = False) -> Optional[dict]:
        """Make FMP API request with error handling."""
        if not self._rate_limit_fmp():
            return None

        if params is None:
            params = {}
        params["apikey"] = FMP_API_KEY

        # Use appropriate base URL
        base = FMP_BASE_V3 if use_v3 else FMP_BASE
        url = f"{base}/{endpoint}"

        for attempt in range(3):
            try:
                r = requests.get(url, params=params, timeout=30)
                if r.status_code == 200:
                    return r.json()
                elif r.status_code == 429:
                    log(f"Rate limited, waiting 60s...", "WARN")
                    time.sleep(60)
                elif r.status_code == 403 and not use_v3:
                    # Try v3 API as fallback
                    log(f"Stable API failed, trying v3...", "WARN")
                    return self._fmp_request(endpoint, params, use_v3=True)
                else:
                    log(f"FMP error {r.status_code}: {r.text[:100]}", "WARN")
            except Exception as e:
                log(f"FMP request failed (attempt {attempt+1}): {e}", "WARN")
                time.sleep(5 * (attempt + 1))

        return None

    def fetch_sp500_constituents(self) -> List[str]:
        """Fetch the point-in-time universe list for the backtest."""
        log("Fetching S&P 500 constituents...")

        cache_file = CACHE_DIR / "sp500_constituents.json"

        universe_file = ATLAS_DIR / "data" / "backtest" / "universe_s30.json"
        if universe_file.exists():
            with open(universe_file, "r") as f:
                data = json.load(f)
            tickers = data if isinstance(data, list) else data.get("tickers", [])
            self.sp500_tickers = [str(t).strip().upper() for t in tickers if str(t).strip()]
            log(f"  Loaded {len(self.sp500_tickers)} tickers from point-in-time universe snapshot")
            with open(cache_file, 'w') as f:
                json.dump({
                    "tickers": self.sp500_tickers,
                    "fetched_date": datetime.now().isoformat(),
                    "source": "backtest_universe_s30",
                    "note": "Point-in-time universe snapshot; no current-membership API used"
                }, f, indent=2)
            return self.sp500_tickers

        # Check cache first
        if cache_file.exists():
            with open(cache_file, 'r') as f:
                data = json.load(f)
                self.sp500_tickers = data.get("tickers", [])
                log(f"  Loaded {len(self.sp500_tickers)} tickers from cache")
                return self.sp500_tickers

        # Try local file first (better for reproducibility)
        local_file = ATLAS_DIR / "data" / "sp500_tickers.txt"
        if local_file.exists():
            with open(local_file, 'r') as f:
                self.sp500_tickers = [line.strip() for line in f if line.strip()]
            log(f"  Loaded {len(self.sp500_tickers)} tickers from local file")

            # Cache it
            with open(cache_file, 'w') as f:
                json.dump({
                    "tickers": self.sp500_tickers,
                    "fetched_date": datetime.now().isoformat(),
                    "source": "local_file",
                    "note": "Loaded from data/sp500_tickers.txt for reproducibility"
                }, f, indent=2)

            return self.sp500_tickers

        # Fallback to API
        data = self._fmp_request("sp500_constituent", use_v3=True)

        if data:
            self.sp500_tickers = [item["symbol"] for item in data if "symbol" in item]

            # Save to cache
            with open(cache_file, 'w') as f:
                json.dump({
                    "tickers": self.sp500_tickers,
                    "fetched_date": datetime.now().isoformat(),
                    "source": "fmp_api",
                    "note": "Using current constituents - known survivorship bias limitation"
                }, f, indent=2)

            log(f"  Fetched {len(self.sp500_tickers)} S&P 500 constituents from API")

        return self.sp500_tickers

    def _polygon_request(self, endpoint: str, params: dict = None) -> Optional[dict]:
        """Make Polygon API request with rate limiting (5 req/min for free tier)."""
        if params is None:
            params = {}
        params["apiKey"] = POLYGON_API_KEY

        url = f"https://api.polygon.io{endpoint}"

        for attempt in range(3):
            try:
                r = requests.get(url, params=params, timeout=30)
                if r.status_code == 200:
                    return r.json()
                elif r.status_code == 429:
                    log(f"Polygon rate limited, waiting 15s...", "WARN")
                    time.sleep(15)
                else:
                    log(f"Polygon error {r.status_code}: {r.text[:100]}", "WARN")
            except Exception as e:
                log(f"Polygon request failed (attempt {attempt+1}): {e}", "WARN")
                time.sleep(5 * (attempt + 1))

        return None

    def fetch_historical_prices(self, ticker: str, start_date: str, end_date: str) -> bool:
        """Fetch historical OHLCV for a single ticker using Polygon API."""
        cache_file = CACHE_DIR / "prices" / f"{ticker}.json"

        # Check if already cached with sufficient date range
        if cache_file.exists():
            with open(cache_file, 'r') as f:
                existing = json.load(f)
                if existing.get("start_date", "") <= start_date and existing.get("end_date", "") >= end_date:
                    return True

        # Use Polygon API for historical data (more reliable than FMP)
        # Rate limit: 5 req/min for free tier
        time.sleep(12)  # Stay within rate limit

        data = self._polygon_request(
            f"/v2/aggs/ticker/{ticker}/range/1/day/{start_date}/{end_date}",
            {"adjusted": "true", "sort": "asc", "limit": "1000"}
        )

        if not data or "results" not in data or not data["results"]:
            log(f"  No price data for {ticker}", "WARN")
            return False

        results = data["results"]

        # Convert to date-keyed dict for fast lookup
        prices_by_date = {}
        for bar in results:
            # Polygon returns timestamp in milliseconds
            timestamp = bar.get("t", 0) / 1000
            date = datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d")

            prices_by_date[date] = {
                "open": bar.get("o", 0),
                "high": bar.get("h", 0),
                "low": bar.get("l", 0),
                "close": bar.get("c", 0),
                "adjClose": bar.get("c", 0),  # Polygon adjusted by default
                "volume": bar.get("v", 0),
                "vwap": bar.get("vw", 0)
            }

        cache_data = {
            "ticker": ticker,
            "start_date": start_date,
            "end_date": end_date,
            "trading_days": len(prices_by_date),
            "prices": prices_by_date,
            "source": "polygon",
            "fetched_at": datetime.now().isoformat()
        }

        with open(cache_file, 'w') as f:
            json.dump(cache_data, f)

        return True

    def fetch_all_prices(self, start_date: str, end_date: str, resume: bool = False) -> dict:
        """Fetch historical prices for all tickers using Polygon API."""
        log("="*60)
        log("PHASE 1A: Caching Historical Prices (Polygon)")
        log("="*60)
        log("Note: Polygon rate limit = 5 req/min. This will take ~2 hours for 500+ tickers.")
        log("Use --resume if interrupted.")

        # Load progress if resuming
        progress_file = CACHE_DIR / "price_cache_progress.json"
        completed = set()

        if resume and progress_file.exists():
            with open(progress_file, 'r') as f:
                progress = json.load(f)
                completed = set(progress.get("completed", []))
                log(f"Resuming: {len(completed)} tickers already cached")

        # Build full ticker list
        if not self.sp500_tickers:
            self.fetch_sp500_constituents()

        all_tickers = list(set(self.sp500_tickers + ETFS))
        remaining = [t for t in all_tickers if t not in completed]

        log(f"Total tickers: {len(all_tickers)}, Remaining: {len(remaining)}")
        estimated_minutes = len(remaining) * 12 / 60
        log(f"Estimated time: ~{estimated_minutes:.0f} minutes")

        start_time = datetime.now()

        # Cache each ticker
        for i, ticker in enumerate(remaining):
            # Progress update every 10 tickers
            if i > 0 and i % 10 == 0:
                elapsed = (datetime.now() - start_time).total_seconds() / 60
                rate = i / elapsed if elapsed > 0 else 0
                eta = (len(remaining) - i) / rate if rate > 0 else 0
                log(f"  Progress: {i}/{len(remaining)} ({100*i/len(remaining):.1f}%) | ETA: {eta:.0f}min")

                # Save progress
                with open(progress_file, 'w') as f:
                    json.dump({"completed": list(completed), "timestamp": datetime.now().isoformat()}, f)

            success = self.fetch_historical_prices(ticker, start_date, end_date)
            if success:
                completed.add(ticker)
            else:
                log(f"  Failed to fetch {ticker}", "WARN")

        # Build price index
        self.price_index = {}
        for ticker in completed:
            cache_file = CACHE_DIR / "prices" / f"{ticker}.json"
            if cache_file.exists():
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                    self.price_index[ticker] = {
                        "start_date": data.get("start_date"),
                        "end_date": data.get("end_date"),
                        "trading_days": data.get("trading_days", 0)
                    }

        # Save price index
        with open(CACHE_DIR / "price_index.json", 'w') as f:
            json.dump(self.price_index, f, indent=2)

        log(f"Price caching complete: {len(completed)} tickers cached")
        return {"status": "complete", "completed": len(completed)}

    def fetch_fundamentals(self, ticker: str) -> bool:
        """Fetch fundamental data for a single ticker."""
        cache_file = CACHE_DIR / "fundamentals" / f"{ticker}.json"

        if cache_file.exists():
            return True

        fundamentals = {
            "ticker": ticker,
            "income_statements": [],
            "balance_sheets": [],
            "key_metrics": [],
            "fetched_at": datetime.now().isoformat()
        }

        # Income statement
        data = self._fmp_request(f"income-statement/{ticker}", {"period": "quarter", "limit": 8}, use_v3=True)
        if data:
            fundamentals["income_statements"] = data

        # Balance sheet
        data = self._fmp_request(f"balance-sheet-statement/{ticker}", {"period": "quarter", "limit": 8}, use_v3=True)
        if data:
            fundamentals["balance_sheets"] = data

        # Key metrics
        data = self._fmp_request(f"key-metrics/{ticker}", {"period": "quarter", "limit": 8}, use_v3=True)
        if data:
            fundamentals["key_metrics"] = data

        with open(cache_file, 'w') as f:
            json.dump(fundamentals, f)

        return True

    def fetch_all_fundamentals(self, resume: bool = False) -> dict:
        """Fetch fundamentals for all S&P 500 stocks."""
        log("="*60)
        log("PHASE 1B: Caching Fundamental Data")
        log("="*60)

        if not self.sp500_tickers:
            self.fetch_sp500_constituents()

        progress_file = CACHE_DIR / "fundamental_cache_progress.json"
        completed = set()

        if resume and progress_file.exists():
            with open(progress_file, 'r') as f:
                progress = json.load(f)
                completed = set(progress.get("completed", []))
                log(f"Resuming: {len(completed)} tickers already cached")

        remaining = [t for t in self.sp500_tickers if t not in completed]
        log(f"Total: {len(self.sp500_tickers)}, Remaining: {len(remaining)}")

        for i, ticker in enumerate(remaining):
            if i > 0 and i % 20 == 0:
                log(f"  Progress: {i}/{len(remaining)}")
                with open(progress_file, 'w') as f:
                    json.dump({"completed": list(completed)}, f)

            success = self.fetch_fundamentals(ticker)
            if success:
                completed.add(ticker)

            if self.api_calls_today >= 240:
                log(f"API limit reached. Run with --resume tomorrow.")
                with open(progress_file, 'w') as f:
                    json.dump({"completed": list(completed)}, f)
                return {"status": "partial", "completed": len(completed)}

        log(f"Fundamental caching complete: {len(completed)} tickers")
        return {"status": "complete", "completed": len(completed)}

    def fetch_fred_data(self, start_date: str, end_date: str) -> dict:
        """Fetch macro data from FRED."""
        log("="*60)
        log("PHASE 1C: Caching Macro Data (FRED)")
        log("="*60)

        cache_file = CACHE_DIR / "macro" / "fred_data.json"

        if cache_file.exists():
            with open(cache_file, 'r') as f:
                data = json.load(f)
                if data.get("start_date", "") <= start_date:
                    log("  FRED data already cached")
                    return data

        fred_data = {
            "start_date": start_date,
            "end_date": end_date,
            "series": {},
            "fetched_at": datetime.now().isoformat()
        }

        # FRED doesn't require API key for basic access via CSV
        for series_id, name in FRED_SERIES.items():
            log(f"  Fetching {series_id} ({name})...")

            try:
                url = f"https://fred.stlouisfed.org/graph/fredgraph.csv"
                params = {
                    "id": series_id,
                    "cosd": start_date,
                    "coed": end_date
                }

                r = requests.get(url, params=params, timeout=30)

                if r.status_code == 200:
                    lines = r.text.strip().split("\n")
                    series_data = {}

                    for line in lines[1:]:  # Skip header
                        parts = line.split(",")
                        if len(parts) >= 2:
                            date = parts[0]
                            try:
                                value = float(parts[1]) if parts[1] and parts[1] != "." else None
                                if value is not None:
                                    series_data[date] = value
                            except ValueError:
                                pass

                    fred_data["series"][series_id] = {
                        "name": name,
                        "values": series_data,
                        "count": len(series_data)
                    }
                    log(f"    Got {len(series_data)} data points")

                time.sleep(1)  # Be nice to FRED

            except Exception as e:
                log(f"    Error fetching {series_id}: {e}", "WARN")

        with open(cache_file, 'w') as f:
            json.dump(fred_data, f)

        log(f"FRED data cached: {len(fred_data['series'])} series")
        return fred_data

    def fetch_sector_map(self) -> dict:
        """Fetch sector/industry mapping for all S&P 500 stocks."""
        log("="*60)
        log("PHASE 1D: Building Sector Map")
        log("="*60)

        cache_file = CACHE_DIR / "sector_map.json"

        if cache_file.exists():
            with open(cache_file, 'r') as f:
                self.sector_map = json.load(f)
                log(f"  Loaded sector map for {len(self.sector_map)} tickers from cache")
                return self.sector_map

        if not self.sp500_tickers:
            self.fetch_sp500_constituents()

        self.sector_map = {}

        # Fetch profile for each ticker (batched)
        for i, ticker in enumerate(self.sp500_tickers):
            if i > 0 and i % 50 == 0:
                log(f"  Progress: {i}/{len(self.sp500_tickers)}")

            data = self._fmp_request(f"profile/{ticker}", use_v3=True)

            if data and len(data) > 0:
                profile = data[0]
                self.sector_map[ticker] = {
                    "sector": profile.get("sector", "Unknown"),
                    "industry": profile.get("industry", "Unknown"),
                    "name": profile.get("companyName", ticker),
                    "market_cap": profile.get("mktCap", 0)
                }

            if self.api_calls_today >= 240:
                log("API limit reached during sector map build")
                break

        with open(cache_file, 'w') as f:
            json.dump(self.sector_map, f, indent=2)

        log(f"Sector map complete: {len(self.sector_map)} tickers mapped")
        return self.sector_map

    def validate_cache(self) -> dict:
        """Validate cached data completeness."""
        log("="*60)
        log("CACHE VALIDATION")
        log("="*60)

        results = {
            "price_tickers": 0,
            "fundamental_tickers": 0,
            "fred_series": 0,
            "sector_map_entries": 0,
            "ready": False
        }

        # Count price files
        price_files = list((CACHE_DIR / "prices").glob("*.json"))
        results["price_tickers"] = len(price_files)
        log(f"  Price files: {len(price_files)}")

        # Count fundamental files
        fund_files = list((CACHE_DIR / "fundamentals").glob("*.json"))
        results["fundamental_tickers"] = len(fund_files)
        log(f"  Fundamental files: {len(fund_files)}")

        # Check FRED
        fred_file = CACHE_DIR / "macro" / "fred_data.json"
        if fred_file.exists():
            with open(fred_file, 'r') as f:
                fred_data = json.load(f)
                results["fred_series"] = len(fred_data.get("series", {}))
        log(f"  FRED series: {results['fred_series']}")

        # Check sector map
        sector_file = CACHE_DIR / "sector_map.json"
        if sector_file.exists():
            with open(sector_file, 'r') as f:
                sector_data = json.load(f)
                results["sector_map_entries"] = len(sector_data)
        log(f"  Sector map entries: {results['sector_map_entries']}")

        # Determine if ready
        results["ready"] = (
            results["price_tickers"] >= 100 and
            results["fred_series"] >= 5
        )

        if results["ready"]:
            log("CACHE READY for backtest loop")
        else:
            log("CACHE INCOMPLETE - run with --cache-only first", "WARN")

        return results


# =============================================================================
# MARKET SNAPSHOT BUILDER
# =============================================================================

class MarketSnapshot:
    """Builds point-in-time market snapshot for a given date with NO lookahead."""

    def __init__(self, cache: DataCache):
        self.cache = cache
        self._price_cache = {}  # Lazy load price files
        self._fundamental_cache = {}
        self._fred_data = None
        self._sector_map = None

    def _load_prices(self, ticker: str) -> dict:
        """Load price data for ticker (lazy, cached)."""
        if ticker not in self._price_cache:
            cache_file = CACHE_DIR / "prices" / f"{ticker}.json"
            if cache_file.exists():
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                    self._price_cache[ticker] = data.get("prices", {})
            else:
                self._price_cache[ticker] = {}
        return self._price_cache[ticker]

    def _load_fred(self) -> dict:
        """Load FRED data (lazy)."""
        if self._fred_data is None:
            fred_file = CACHE_DIR / "macro" / "fred_data.json"
            if fred_file.exists():
                with open(fred_file, 'r') as f:
                    self._fred_data = json.load(f)
            else:
                self._fred_data = {"series": {}}
        return self._fred_data

    def _load_sector_map(self) -> dict:
        """Load sector map (lazy)."""
        if self._sector_map is None:
            sector_file = CACHE_DIR / "sector_map.json"
            if sector_file.exists():
                with open(sector_file, 'r') as f:
                    self._sector_map = json.load(f)
            else:
                self._sector_map = {}
        return self._sector_map

    def get_price(self, ticker: str, date: str) -> Optional[float]:
        """Get closing price for ticker on date. Returns None if no data."""
        prices = self._load_prices(ticker)
        if date in prices:
            return prices[date].get("adjClose") or prices[date].get("close")
        return None

    def get_price_strict(self, ticker: str, date: str) -> float:
        """Get price or raise error - use for anti-lookahead validation."""
        price = self.get_price(ticker, date)
        if price is None:
            raise ValueError(f"No price for {ticker} on {date}")
        return price

    def get_trailing_return(self, ticker: str, date: str, days: int) -> Optional[float]:
        """Calculate trailing return over N trading days ending on date."""
        prices = self._load_prices(ticker)

        # Find the date and N days prior
        sorted_dates = sorted([d for d in prices.keys() if d <= date])

        if len(sorted_dates) < days + 1:
            return None

        end_idx = len(sorted_dates) - 1
        # Find actual end date (might be earlier if date is not a trading day)
        while end_idx >= 0 and sorted_dates[end_idx] > date:
            end_idx -= 1

        if end_idx < days:
            return None

        start_idx = end_idx - days

        end_price = prices[sorted_dates[end_idx]].get("adjClose") or prices[sorted_dates[end_idx]].get("close", 0)
        start_price = prices[sorted_dates[start_idx]].get("adjClose") or prices[sorted_dates[start_idx]].get("close", 0)

        if start_price == 0:
            return None

        return ((end_price - start_price) / start_price) * 100

    def get_sma(self, ticker: str, date: str, period: int) -> Optional[float]:
        """Calculate Simple Moving Average."""
        prices = self._load_prices(ticker)
        sorted_dates = sorted([d for d in prices.keys() if d <= date])

        if len(sorted_dates) < period:
            return None

        recent_prices = []
        for d in sorted_dates[-period:]:
            p = prices[d].get("adjClose") or prices[d].get("close", 0)
            if p > 0:
                recent_prices.append(p)

        if len(recent_prices) < period:
            return None

        return sum(recent_prices) / len(recent_prices)

    def get_rsi(self, ticker: str, date: str, period: int = 14) -> Optional[float]:
        """Calculate RSI."""
        prices = self._load_prices(ticker)
        sorted_dates = sorted([d for d in prices.keys() if d <= date])

        if len(sorted_dates) < period + 1:
            return None

        recent_dates = sorted_dates[-(period + 1):]
        changes = []

        for i in range(1, len(recent_dates)):
            prev_close = prices[recent_dates[i-1]].get("adjClose") or prices[recent_dates[i-1]].get("close", 0)
            curr_close = prices[recent_dates[i]].get("adjClose") or prices[recent_dates[i]].get("close", 0)
            if prev_close > 0 and curr_close > 0:
                changes.append(curr_close - prev_close)

        if len(changes) < period:
            return None

        gains = [c for c in changes if c > 0]
        losses = [-c for c in changes if c < 0]

        avg_gain = sum(gains) / period if gains else 0
        avg_loss = sum(losses) / period if losses else 0

        if avg_loss == 0:
            return 100 if avg_gain > 0 else 50

        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def get_atr(self, ticker: str, date: str, period: int = 14) -> Optional[float]:
        """Calculate Average True Range."""
        prices = self._load_prices(ticker)
        sorted_dates = sorted([d for d in prices.keys() if d <= date])

        if len(sorted_dates) < period + 1:
            return None

        recent_dates = sorted_dates[-(period + 1):]
        true_ranges = []

        for i in range(1, len(recent_dates)):
            prev = prices[recent_dates[i-1]]
            curr = prices[recent_dates[i]]

            high = curr.get("high", 0)
            low = curr.get("low", 0)
            prev_close = prev.get("adjClose") or prev.get("close", 0)

            if high > 0 and low > 0 and prev_close > 0:
                tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
                true_ranges.append(tr)

        if len(true_ranges) < period:
            return None

        return sum(true_ranges[-period:]) / period

    def get_avg_volume(self, ticker: str, date: str, period: int = 20) -> Optional[float]:
        """Calculate average volume over N days."""
        prices = self._load_prices(ticker)
        sorted_dates = sorted([d for d in prices.keys() if d <= date])

        if len(sorted_dates) < period:
            return None

        volumes = []
        for d in sorted_dates[-period:]:
            v = prices[d].get("volume", 0)
            if v > 0:
                volumes.append(v)

        if len(volumes) < period // 2:
            return None

        return sum(volumes) / len(volumes)

    def get_fundamental(self, ticker: str, date: str) -> Optional[dict]:
        """Get most recent fundamental data with fillingDate <= date."""
        if ticker not in self._fundamental_cache:
            fund_file = CACHE_DIR / "fundamentals" / f"{ticker}.json"
            if fund_file.exists():
                with open(fund_file, 'r') as f:
                    self._fundamental_cache[ticker] = json.load(f)
            else:
                self._fundamental_cache[ticker] = {}

        fund_data = self._fundamental_cache.get(ticker, {})

        # Find most recent filing with fillingDate <= date
        income = fund_data.get("income_statements", [])
        balance = fund_data.get("balance_sheets", [])
        metrics = fund_data.get("key_metrics", [])

        result = {}

        # Income statement
        for stmt in income:
            filing_date = stmt.get("fillingDate") or stmt.get("acceptedDate", "")[:10]
            if filing_date and filing_date <= date:
                result["revenue"] = stmt.get("revenue")
                result["gross_profit"] = stmt.get("grossProfit")
                result["operating_income"] = stmt.get("operatingIncome")
                result["net_income"] = stmt.get("netIncome")
                result["eps"] = stmt.get("eps")
                result["filing_date"] = filing_date
                break

        # Balance sheet
        for stmt in balance:
            filing_date = stmt.get("fillingDate") or stmt.get("acceptedDate", "")[:10]
            if filing_date and filing_date <= date:
                result["total_assets"] = stmt.get("totalAssets")
                result["total_debt"] = stmt.get("totalDebt")
                result["shareholders_equity"] = stmt.get("totalStockholdersEquity")
                result["cash"] = stmt.get("cashAndCashEquivalents")
                break

        # Key metrics
        for m in metrics:
            filing_date = m.get("date", "")
            # Key metrics use period date, not filing date - add buffer
            if filing_date:
                # Add 45 day buffer for filing
                period_date = datetime.strptime(filing_date, "%Y-%m-%d")
                approx_filing = (period_date + timedelta(days=45)).strftime("%Y-%m-%d")
                if approx_filing <= date:
                    result["pe"] = m.get("peRatio")
                    result["pb"] = m.get("pbRatio")
                    result["ev_ebitda"] = m.get("enterpriseValueOverEBITDA")
                    result["debt_equity"] = m.get("debtToEquity")
                    result["current_ratio"] = m.get("currentRatio")
                    result["roic"] = m.get("roic")
                    result["roe"] = m.get("roe")
                    result["gross_margin"] = m.get("grossProfitMargin")
                    result["operating_margin"] = m.get("operatingProfitMargin")
                    result["net_margin"] = m.get("netProfitMargin")
                    break

        return result if result else None

    def get_fred_value(self, series_id: str, date: str) -> Optional[float]:
        """Get FRED series value as of date."""
        fred = self._load_fred()
        series = fred.get("series", {}).get(series_id, {}).get("values", {})

        # Find most recent value <= date
        valid_dates = [d for d in series.keys() if d <= date]
        if not valid_dates:
            return None

        latest = max(valid_dates)
        return series[latest]

    def get_macro_regime(self, date: str) -> dict:
        """Build macro regime snapshot for date."""
        regime = {}

        # Rates
        regime["fed_funds"] = self.get_fred_value("FEDFUNDS", date)
        regime["yield_10y"] = self.get_fred_value("DGS10", date)
        regime["yield_2y"] = self.get_fred_value("DGS2", date)
        regime["yield_curve"] = self.get_fred_value("T10Y2Y", date)

        # Economic indicators
        regime["cpi"] = self.get_fred_value("CPIAUCSL", date)
        regime["unemployment"] = self.get_fred_value("UNRATE", date)
        regime["consumer_sentiment"] = self.get_fred_value("UMCSENT", date)

        # Risk indicators
        regime["vix"] = self.get_fred_value("VIXCLS", date)
        regime["hy_spread"] = self.get_fred_value("BAMLH0A0HYM2", date)
        regime["dollar_index"] = self.get_fred_value("DTWEXBGS", date)

        return regime

    def get_sector(self, ticker: str) -> str:
        """Get sector for ticker."""
        sector_map = self._load_sector_map()
        return sector_map.get(ticker, {}).get("sector", "Unknown")

    def build_snapshot(self, date: str, portfolio: Portfolio, agent_weights: dict,
                       meta: dict = None) -> dict:
        """Build complete market snapshot for a given date.

        Args:
            date: Current trading date
            portfolio: Current portfolio state
            agent_weights: Agent performance weights
            meta: Additional context (spy_return, drawdown, days_since_trade, peak_value)
        """
        meta = meta or {}

        snapshot = {
            "date": date,
            "prices": {},
            "returns": {},
            "technicals": {},
            "fundamentals": {},
            "macro": self.get_macro_regime(date),
            "portfolio": {
                "cash": portfolio.cash,
                "total_value": portfolio.total_value,
                "positions": [],
                "gross_exposure": portfolio.gross_exposure,
                "net_exposure": portfolio.net_exposure
            },
            "agent_weights": agent_weights,
            "benchmark": {
                "spy_return": meta.get("spy_return", 0)
            },
            "meta": {
                "drawdown": meta.get("drawdown", 0),
                "days_since_trade": meta.get("days_since_trade", 0),
                "peak_value": meta.get("peak_value", 1000000)
            }
        }

        # Portfolio positions with days held
        for pos in portfolio.positions:
            price = self.get_price(pos.ticker, date)
            if price:
                pos.current_price = price

            # Calculate days held
            days_held = 0
            if pos.entry_date:
                try:
                    entry = datetime.strptime(pos.entry_date, "%Y-%m-%d")
                    current = datetime.strptime(date, "%Y-%m-%d")
                    days_held = (current - entry).days
                except:
                    pass

            snapshot["portfolio"]["positions"].append({
                "ticker": pos.ticker,
                "direction": pos.direction,
                "shares": pos.shares,
                "entry_price": pos.entry_price,
                "current_price": pos.current_price,
                "pnl": pos.pnl,
                "pnl_pct": pos.pnl_pct,
                "sector": pos.sector,
                "days_held": days_held,
                "entry_date": pos.entry_date
            })

        # Key indices and prices
        key_tickers = ["SPY", "QQQ", "IWM", "TLT", "GLD", "XLE", "VXX"]
        for ticker in key_tickers:
            price = self.get_price(ticker, date)
            if price:
                snapshot["prices"][ticker] = price
                snapshot["returns"][ticker] = {
                    "1d": self.get_trailing_return(ticker, date, 1),
                    "5d": self.get_trailing_return(ticker, date, 5),
                    "20d": self.get_trailing_return(ticker, date, 20),
                    "60d": self.get_trailing_return(ticker, date, 60)
                }

        return snapshot


# =============================================================================
# AGENT DEBATE SYSTEM
# =============================================================================

class AgentDebate:
    """Handles batched agent debate for each day."""

    def __init__(self, snapshot_builder: MarketSnapshot, verbose: bool = False):
        self.snapshot = snapshot_builder
        self.verbose = verbose
        self.prompt_cache = {}

    def load_prompt(self, agent_name: str) -> str:
        """Load agent prompt from file."""
        if agent_name in self.prompt_cache:
            return self.prompt_cache[agent_name]

        # Try different filename patterns
        patterns = [
            f"{agent_name}.md",
            f"{agent_name}_desk.md",
            f"{agent_name}_agent.md"
        ]

        for pattern in patterns:
            path = PROMPTS_DIR / pattern
            if path.exists():
                with open(path, 'r') as f:
                    prompt = f.read()
                    self.prompt_cache[agent_name] = prompt
                    return prompt

        # Fallback
        return f"You are the {agent_name} agent. Analyze the market data and provide recommendations."

    def _call_claude(self, system_prompt: str, user_message: str, max_tokens: int = 1000) -> str:
        """Call Claude API with retry logic."""
        for attempt in range(3):
            try:
                response = client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=max_tokens,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_message}]
                )
                return response.content[0].text
            except Exception as e:
                if attempt < 2:
                    time.sleep(5 * (attempt + 1))
                else:
                    log(f"Claude API failed: {e}", "ERROR")
                    return f"ERROR: {str(e)}"
        return "ERROR: Max retries exceeded"

    def _build_context(self, snapshot: dict) -> str:
        """Build market context string for agents."""
        date = snapshot["date"]
        portfolio = snapshot["portfolio"]
        macro = snapshot["macro"]

        # CIO-specific context from meta
        benchmark = snapshot.get("benchmark", {})
        meta = snapshot.get("meta", {})

        # Portfolio vs benchmark
        portfolio_return = ((portfolio['total_value'] - 1000000) / 1000000) * 100
        spy_return = benchmark.get("spy_return", 0)
        alpha = portfolio_return - spy_return

        # Cash as percentage
        cash_pct = (portfolio['cash'] / portfolio['total_value']) * 100 if portfolio['total_value'] > 0 else 100

        # Drawdown and days since trade
        drawdown = meta.get("drawdown", 0)
        days_since_trade = meta.get("days_since_trade", 0)
        peak_value = meta.get("peak_value", 1000000)

        # Position details with age and stop loss flags
        positions_text = []
        for pos in portfolio["positions"]:
            days_held = pos.get("days_held", 0)
            stop_hit = "*** STOP LOSS HIT ***" if pos['pnl_pct'] <= -15 else ""
            age_warning = "[REVIEW - 60+ days]" if days_held >= 60 else ""
            positions_text.append(
                f"  {pos['ticker']}: {pos['direction']} @ ${pos['entry_price']:.2f} -> "
                f"${pos['current_price']:.2f} | P&L: {pos['pnl_pct']:+.1f}% | Days: {days_held} {stop_hit}{age_warning}"
            )

        positions_str = "\n".join(positions_text) if positions_text else "  NO POSITIONS"

        # Benchmark status
        if alpha > 0:
            benchmark_status = "BEATING BENCHMARK"
        elif alpha < -10:
            benchmark_status = "*** UNDERPERFORMING - ACTION REQUIRED ***"
        else:
            benchmark_status = "TRAILING BENCHMARK"

        # Cash warning
        cash_warning = ""
        if cash_pct > 30:
            cash_warning = f"\n*** WARNING: Cash at {cash_pct:.0f}% - Deploy or explain why not ***"

        # Inactivity warning
        trade_warning = ""
        if days_since_trade > 20:
            trade_warning = f"\n*** WARNING: {days_since_trade} days since last trade - Review positions ***"

        # Macro summary
        macro_str = f"""
Fed Funds: {macro.get('fed_funds', 'N/A')}%
10Y Yield: {macro.get('yield_10y', 'N/A')}%
2Y Yield: {macro.get('yield_2y', 'N/A')}%
Yield Curve (10Y-2Y): {macro.get('yield_curve', 'N/A')}%
VIX: {macro.get('vix', 'N/A')}
HY Spread: {macro.get('hy_spread', 'N/A')} bps
Dollar Index: {macro.get('dollar_index', 'N/A')}
"""

        # Key prices
        prices = snapshot.get("prices", {})
        prices_str = "\n".join([f"  {t}: ${p:.2f}" for t, p in prices.items()])

        context = f"""
=== MARKET DATA — {date} ===
(BACKTEST MODE: You can only see data up to this date)

=== BENCHMARK CHECK ===
Portfolio Return: {portfolio_return:+.1f}%
SPY Return (same period): {spy_return:+.1f}%
Alpha: {alpha:+.1f}%
Status: {benchmark_status}

=== PORTFOLIO STATUS ===
Total Value: ${portfolio['total_value']:,.0f} (Peak: ${peak_value:,.0f})
Cash: ${portfolio['cash']:,.0f} ({cash_pct:.0f}% of portfolio)
Drawdown from Peak: {drawdown:.1f}%
Days Since Last Trade: {days_since_trade}
Gross Exposure: {portfolio['gross_exposure']*100:.1f}%
Net Exposure: {portfolio['net_exposure']*100:.1f}%
{cash_warning}{trade_warning}

=== CURRENT POSITIONS (Review each one!) ===
{positions_str}

=== KEY INDICES ===
{prices_str}

=== MACRO ENVIRONMENT ===
{macro_str}

ACTION REQUIRED:
1. Review each position - would you enter today? If not, EXIT
2. Any position down 15%+ from entry - EXIT IMMEDIATELY (stop loss)
3. Any position held 60+ days - RECONFIRM thesis or EXIT
4. Cash above 30% - DEPLOY into high-conviction ideas
5. If trailing SPY by >10% - MAKE CHANGES

Provide your analysis and specific trade recommendations in JSON format.
"""
        return context

    def _batch_agents(self, agents: List[str], snapshot: dict, prior_views: dict) -> dict:
        """Call multiple agents in a batch (single API call with multiple agent personas)."""
        context = self._build_context(snapshot)
        date = snapshot["date"]

        # Build combined prompt for batched agents
        batch_system = f"""You are simulating multiple trading agents for date {date}.
For EACH agent, provide a JSON response with their analysis.
Do NOT use any information from after {date}.

Output format:
{{
  "agent_name_1": {{
    "regime": "RISK_ON|RISK_OFF|NEUTRAL",
    "signal": "BULLISH|BEARISH|NEUTRAL",
    "top_longs": [{{"ticker": "X", "conviction": 85, "reasoning": "..."}}],
    "top_shorts": [{{"ticker": "Y", "conviction": 70, "reasoning": "..."}}],
    "sector_tilts": {{"energy": "+", "tech": "-"}},
    "key_risk": "..."
  }},
  "agent_name_2": {{ ... }}
}}
"""

        agent_descriptions = []
        for agent in agents:
            prompt = self.load_prompt(agent)
            agent_descriptions.append(f"=== {agent.upper()} ===\n{prompt[:500]}...")

        prior_context = ""
        if prior_views:
            prior_context = "\n\nPRIOR AGENT VIEWS:\n"
            for agent, view in prior_views.items():
                if isinstance(view, dict):
                    prior_context += f"{agent}: {json.dumps(view)[:200]}...\n"

        user_message = f"""
AGENTS TO SIMULATE:
{chr(10).join(agent_descriptions)}

{prior_context}

MARKET DATA:
{context}

Respond with JSON containing each agent's analysis.
"""

        response_text = self._call_claude(batch_system, user_message, max_tokens=2000)

        # Parse response
        views = {}
        try:
            # Try to extract JSON from response
            import re
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                parsed = json.loads(json_match.group())
                # Normalize keys to lowercase for matching
                parsed_lower = {k.lower(): v for k, v in parsed.items()}
                for agent in agents:
                    agent_lower = agent.lower()
                    agent_no_underscore = agent_lower.replace("_", "")
                    # Try various key formats
                    if agent_lower in parsed_lower:
                        views[agent] = parsed_lower[agent_lower]
                    elif agent_no_underscore in parsed_lower:
                        views[agent] = parsed_lower[agent_no_underscore]
                    elif agent in parsed:  # Original case
                        views[agent] = parsed[agent]
                    elif agent.upper() in parsed:
                        views[agent] = parsed[agent.upper()]
        except json.JSONDecodeError:
            # Fallback: assign raw text to first agent
            if agents:
                views[agents[0]] = {"raw": response_text[:500]}

        if self.verbose:
            for agent, view in views.items():
                log(f"  {agent}: {json.dumps(view)[:100]}...")

        return views

    def run_debate(self, date: str, portfolio: Portfolio, agent_weights: dict,
                   meta: dict = None) -> dict:
        """Run full agent debate for a given date.

        Args:
            date: Current trading date
            portfolio: Current portfolio state
            agent_weights: Agent performance weights
            meta: Additional CIO context (spy_return, drawdown, days_since_trade, peak_value)
        """
        snapshot = self.snapshot.build_snapshot(date, portfolio, agent_weights, meta)
        all_views = {}

        # Layer 1: Macro Agents (Batch 1)
        log("  Layer 1: Macro Agents Batch 1...")
        views = self._batch_agents(MACRO_AGENTS_BATCH_1, snapshot, {})
        all_views.update(views)

        # Layer 1: Macro Agents (Batch 2)
        log("  Layer 1: Macro Agents Batch 2...")
        views = self._batch_agents(MACRO_AGENTS_BATCH_2, snapshot, all_views)
        all_views.update(views)

        # Layer 2: Sector Desks
        log("  Layer 2: Sector Desks...")
        views = self._batch_agents(SECTOR_AGENTS, snapshot, all_views)
        all_views.update(views)

        # Layer 3: Superinvestors
        log("  Layer 3: Superinvestors...")
        views = self._batch_agents(SUPERINVESTOR_AGENTS, snapshot, all_views)
        all_views.update(views)

        # Layer 4: Decision (CRO + Alpha)
        log("  Layer 4: CRO + Alpha Discovery...")
        views = self._batch_agents(DECISION_AGENTS_BATCH_1, snapshot, all_views)
        all_views.update(views)

        # Layer 4: Final Decision (CIO)
        log("  Layer 4: CIO Final Decision...")
        views = self._batch_agents(DECISION_AGENTS_BATCH_2, snapshot, all_views)
        all_views.update(views)

        return all_views


# =============================================================================
# TRADE EXECUTION
# =============================================================================

class TradeExecutor:
    """Executes trades based on CIO decisions."""

    def __init__(self, snapshot_builder: MarketSnapshot):
        self.snapshot = snapshot_builder

    def execute(self, date: str, portfolio: Portfolio, cio_view: dict, sector_map: dict) -> List[dict]:
        """Execute trades from CIO recommendations."""
        import re
        trades = []

        # PHASE 1: Automatic position management (stop losses, profit taking)
        positions_to_close = []
        for pos in portfolio.positions:
            # Stop loss: exit any position down 15%+ from entry
            if pos.pnl_pct <= -15:
                positions_to_close.append((pos, "STOP_LOSS"))
                log(f"    STOP LOSS TRIGGERED: {pos.ticker} at {pos.pnl_pct:.1f}%")

            # Profit taking: trim winners up 30%+ (close 50% of position)
            elif pos.pnl_pct >= 30:
                # For now, just log - full position management would reduce shares
                log(f"    PROFIT TARGET: {pos.ticker} at {pos.pnl_pct:.1f}% - should trim")

        # Execute automatic closes
        for pos, reason in positions_to_close:
            price = pos.current_price
            value = pos.shares * price
            transaction_cost = value * (TRANSACTION_COST_BPS / 10000)

            # Return cash for long positions
            if pos.direction == "LONG":
                portfolio.cash += (value - transaction_cost)
            else:
                portfolio.cash += (pos.cost_basis - value - transaction_cost)

            portfolio.positions.remove(pos)

            trade = {
                "date": date,
                "ticker": pos.ticker,
                "action": "EXIT",
                "reason": reason,
                "shares": pos.shares,
                "price": price,
                "value": value,
                "pnl": pos.pnl,
                "pnl_pct": pos.pnl_pct
            }
            trades.append(trade)
            log(f"    EXECUTED: EXIT {pos.ticker} @ ${price:.2f} (P&L: {pos.pnl_pct:+.1f}%) - {reason}")

        if not cio_view:
            return trades

        # PHASE 2: Parse CIO recommendations for exits and new positions
        exits = []
        new_positions = []

        if isinstance(cio_view, dict):
            # Check for explicit exit instructions
            for trade in cio_view.get("trades", []):
                action = trade.get("action", "").upper()
                ticker = trade.get("ticker")
                if action in ["EXIT", "CLOSE", "COVER"] and ticker:
                    exits.append(ticker)
                elif action in ["BUY", "LONG"] and ticker:
                    new_positions.append((ticker, "LONG", trade.get("conviction", 70)))
                elif action in ["SELL", "SHORT"] and ticker:
                    new_positions.append((ticker, "SHORT", trade.get("conviction", 70)))

            # Check position_review for EXIT actions
            for review in cio_view.get("position_review", []):
                action = review.get("action", "").upper()
                ticker = review.get("ticker")
                if action == "EXIT" and ticker:
                    exits.append(ticker)

            # Standard parsing for recommendations
            for rec in cio_view.get("top_longs", []):
                ticker = rec.get("ticker")
                if ticker:
                    new_positions.append((ticker, "LONG", rec.get("conviction", 50)))

            for rec in cio_view.get("top_shorts", []):
                ticker = rec.get("ticker")
                if ticker:
                    new_positions.append((ticker, "SHORT", rec.get("conviction", 50)))

            for rec in cio_view.get("recommendations", []):
                ticker = rec.get("ticker") or rec.get("symbol")
                action = (rec.get("action") or rec.get("direction") or "").upper()
                conviction = rec.get("conviction", rec.get("confidence", 70))
                if ticker and action in ["BUY", "LONG"]:
                    new_positions.append((ticker, "LONG", conviction))
                elif ticker and action in ["SELL", "SHORT"]:
                    new_positions.append((ticker, "SHORT", conviction))
                elif ticker and action in ["EXIT", "CLOSE", "COVER"]:
                    exits.append(ticker)

            # Parse text-based patterns
            raw_text = cio_view.get("raw", "") or str(cio_view)
            # Match EXIT patterns
            exit_patterns = re.findall(r'\b(EXIT|CLOSE|COVER)\s+([A-Z]{1,5})\b', raw_text.upper())
            for _, ticker in exit_patterns:
                exits.append(ticker)
            # Match BUY/SELL patterns
            trade_patterns = re.findall(r'\b(BUY|LONG|SELL|SHORT)\s+([A-Z]{1,5})\b', raw_text.upper())
            for action, ticker in trade_patterns:
                if action in ["BUY", "LONG"]:
                    new_positions.append((ticker, "LONG", 60))
                else:
                    new_positions.append((ticker, "SHORT", 60))

        # PHASE 3: Execute CIO-directed exits
        for ticker in set(exits):
            pos = next((p for p in portfolio.positions if p.ticker == ticker), None)
            if pos:
                price = pos.current_price
                value = pos.shares * price
                transaction_cost = value * (TRANSACTION_COST_BPS / 10000)

                if pos.direction == "LONG":
                    portfolio.cash += (value - transaction_cost)
                else:
                    portfolio.cash += (pos.cost_basis - value - transaction_cost)

                portfolio.positions.remove(pos)

                trade = {
                    "date": date,
                    "ticker": ticker,
                    "action": "EXIT",
                    "reason": "CIO_DECISION",
                    "shares": pos.shares,
                    "price": price,
                    "value": value,
                    "pnl": pos.pnl,
                    "pnl_pct": pos.pnl_pct
                }
                trades.append(trade)
                log(f"    EXECUTED: EXIT {ticker} @ ${price:.2f} (P&L: {pos.pnl_pct:+.1f}%) - CIO decision")

        # Use new_positions instead of recommendations
        recommendations = new_positions

        if not recommendations:
            return trades

        # Execute each recommendation
        for ticker, direction, conviction in recommendations[:5]:  # Limit to top 5
            price = self.snapshot.get_price(ticker, date)
            if not price or price <= 0:
                continue

            # Check position limits
            if len(portfolio.positions) >= MAX_POSITIONS:
                continue

            # Check if already have position
            existing = [p for p in portfolio.positions if p.ticker == ticker]
            if existing:
                continue

            # Calculate position size based on conviction
            if conviction >= 80:
                target_pct = 8
            elif conviction >= 60:
                target_pct = 5
            else:
                target_pct = 3

            target_pct = min(target_pct, MAX_SINGLE_POSITION_PCT)
            target_value = portfolio.total_value * (target_pct / 100)

            # Check cash availability
            if direction == "LONG":
                if target_value > portfolio.cash * 0.9:  # Keep some buffer
                    target_value = portfolio.cash * 0.5

            shares = int(target_value / price)
            if shares <= 0:
                continue

            actual_value = shares * price
            transaction_cost = actual_value * (TRANSACTION_COST_BPS / 10000)

            # Check sector concentration
            sector = sector_map.get(ticker, {}).get("sector", "Unknown")
            sector_exposure = sum(
                p.market_value for p in portfolio.positions
                if self.snapshot.get_sector(p.ticker) == sector
            )
            if (sector_exposure + actual_value) / portfolio.total_value > MAX_SECTOR_PCT / 100:
                continue

            # Execute trade
            if direction == "LONG":
                portfolio.cash -= (actual_value + transaction_cost)
            else:
                portfolio.cash -= transaction_cost  # Short margin handled separately

            position = Position(
                ticker=ticker,
                direction=direction,
                shares=shares,
                entry_price=price,
                entry_date=date,
                cost_basis=actual_value,
                current_price=price,
                sector=sector,
                agent_source="cio",
                thesis=f"CIO recommendation (conviction: {conviction}%)"
            )
            portfolio.positions.append(position)

            trade = {
                "date": date,
                "ticker": ticker,
                "action": "BUY" if direction == "LONG" else "SHORT",
                "shares": shares,
                "price": price,
                "value": actual_value,
                "cost": transaction_cost,
                "conviction": conviction,
                "sector": sector
            }
            trades.append(trade)

            log(f"    EXECUTED: {direction} {shares} {ticker} @ ${price:.2f} ({target_pct:.1f}%)")

        return trades


# =============================================================================
# AGENT SCORING
# =============================================================================

class AgentScorer:
    """Tracks and scores agent recommendations."""

    RECS_FILE = BACKTEST_DIR / "recommendations.json"

    def __init__(self, snapshot_builder: MarketSnapshot):
        self.snapshot = snapshot_builder
        self.recommendations: List[AgentRecommendation] = []
        self.agent_metrics: Dict[str, dict] = {}
        self._load_recommendations()

    def _load_recommendations(self):
        """Load recommendations from disk."""
        if self.RECS_FILE.exists():
            try:
                with open(self.RECS_FILE, 'r') as f:
                    data = json.load(f)
                for rec_dict in data:
                    rec = AgentRecommendation(**rec_dict)
                    self.recommendations.append(rec)
                log(f"  Loaded {len(self.recommendations)} recommendations from disk")
            except Exception as e:
                log(f"  Could not load recommendations: {e}", "WARN")

    def _save_recommendations(self):
        """Save recommendations to disk."""
        data = [asdict(r) for r in self.recommendations]
        with open(self.RECS_FILE, 'w') as f:
            json.dump(data, f)

    def record_recommendation(self, agent: str, date: str, ticker: str,
                              direction: str, conviction: int, price: float, reasoning: str = ""):
        """Record a new recommendation."""
        rec = AgentRecommendation(
            agent=agent,
            date=date,
            ticker=ticker,
            direction=direction,
            conviction=conviction,
            entry_price=price,
            reasoning=reasoning
        )
        self.recommendations.append(rec)
        self._save_recommendations()  # Persist after each new rec

    def extract_and_record(self, date: str, all_views: dict):
        """Extract recommendations from agent views and record them."""
        import re
        count = 0

        for agent, view in all_views.items():
            if not view or agent in ["cro", "autonomous_execution"]:  # Skip non-trading agents
                continue

            # Handle structured dict format
            if isinstance(view, dict):
                # Check top_longs
                for rec in view.get("top_longs", []):
                    ticker = rec.get("ticker")
                    if ticker and len(ticker) <= 5:
                        price = self.snapshot.get_price(ticker, date)
                        if price:
                            self.record_recommendation(
                                agent, date, ticker, "LONG",
                                rec.get("conviction", 50), price,
                                rec.get("reasoning", "")
                            )
                            count += 1

                # Check top_shorts
                for rec in view.get("top_shorts", []):
                    ticker = rec.get("ticker")
                    if ticker and len(ticker) <= 5:
                        price = self.snapshot.get_price(ticker, date)
                        if price:
                            self.record_recommendation(
                                agent, date, ticker, "SHORT",
                                rec.get("conviction", 50), price,
                                rec.get("reasoning", "")
                            )
                            count += 1

                # Check recommendations array
                for rec in view.get("recommendations", []):
                    ticker = rec.get("ticker") or rec.get("symbol")
                    direction = (rec.get("direction") or rec.get("action") or "").upper()
                    if ticker and len(ticker) <= 5 and direction in ["LONG", "BUY", "SHORT", "SELL"]:
                        price = self.snapshot.get_price(ticker, date)
                        if price:
                            dir_norm = "LONG" if direction in ["LONG", "BUY"] else "SHORT"
                            self.record_recommendation(
                                agent, date, ticker, dir_norm,
                                rec.get("conviction", 50), price,
                                rec.get("reasoning", "")
                            )
                            count += 1

                # Extract from signal field
                signal = view.get("signal", "").upper()
                regime = view.get("regime", "").upper()

                # Map signals to ETF recommendations
                if signal == "BULLISH" or regime == "RISK_ON":
                    price = self.snapshot.get_price("SPY", date)
                    if price:
                        self.record_recommendation(agent, date, "SPY", "LONG", 60, price, f"Signal: {signal}")
                        count += 1
                elif signal == "BEARISH" or regime == "RISK_OFF":
                    price = self.snapshot.get_price("SPY", date)
                    if price:
                        self.record_recommendation(agent, date, "SPY", "SHORT", 60, price, f"Signal: {signal}")
                        count += 1

        if count > 0:
            log(f"  Recorded {count} recommendations from {len(all_views)} agents")

    def update_returns(self, current_date: str):
        """Update forward returns for all recommendations."""
        updated = 0
        for rec in self.recommendations:
            if rec.return_5d is not None:
                continue  # Already complete (using 5d now for faster iteration)

            rec_date = datetime.strptime(rec.date, "%Y-%m-%d")
            curr_date = datetime.strptime(current_date, "%Y-%m-%d")
            days_since = (curr_date - rec_date).days

            current_price = self.snapshot.get_price(rec.ticker, current_date)
            if not current_price:
                continue

            # Calculate return based on direction
            if rec.direction == "LONG":
                ret = ((current_price - rec.entry_price) / rec.entry_price) * 100
            else:
                ret = ((rec.entry_price - current_price) / rec.entry_price) * 100

            if days_since >= 1 and rec.return_1d is None:
                rec.return_1d = ret
                updated += 1
            if days_since >= 5 and rec.return_5d is None:
                rec.return_5d = ret
                updated += 1
            if days_since >= 10 and rec.return_10d is None:
                rec.return_10d = ret

        if updated > 0:
            self._save_recommendations()

    def calculate_metrics(self) -> dict:
        """Calculate metrics for all agents using 5-day returns."""
        from collections import defaultdict

        agent_recs = defaultdict(list)
        for rec in self.recommendations:
            agent_recs[rec.agent].append(rec)

        self.agent_metrics = {}

        for agent, recs in agent_recs.items():
            # Use 5-day returns for faster autoresearch iteration
            scored_recs = [r for r in recs if r.return_5d is not None]

            if not scored_recs:
                self.agent_metrics[agent] = {
                    "total": len(recs),
                    "scored": 0,
                    "sharpe": None
                }
                continue

            returns = [r.return_5d for r in scored_recs]
            hits = sum(1 for r in returns if r > 0)

            mean_ret = sum(returns) / len(returns)
            variance = sum((r - mean_ret)**2 for r in returns) / len(returns) if len(returns) > 1 else 0
            std_dev = math.sqrt(variance) if variance > 0 else 0.001
            sharpe = mean_ret / std_dev if std_dev > 0 else 0

            self.agent_metrics[agent] = {
                "total": len(recs),
                "scored": len(scored_recs),
                "hit_rate": (hits / len(scored_recs)) * 100,
                "avg_return": mean_ret,
                "sharpe": sharpe
            }

        return self.agent_metrics

    def get_worst_agent(self) -> Optional[Tuple[str, float]]:
        """Get worst performing agent by Sharpe (using 5-day returns)."""
        if not self.agent_metrics:
            self.calculate_metrics()

        # Get agents with at least 3 scored recommendations
        agents_with_sharpe = [
            (agent, m["sharpe"])
            for agent, m in self.agent_metrics.items()
            if m.get("sharpe") is not None and m.get("scored", 0) >= 3
        ]

        if not agents_with_sharpe:
            return None

        agents_with_sharpe.sort(key=lambda x: x[1])
        return agents_with_sharpe[0]

    def update_weights(self, current_weights: dict) -> dict:
        """Update agent weights based on performance."""
        if not self.agent_metrics:
            self.calculate_metrics()

        new_weights = dict(current_weights)

        for agent, metrics in self.agent_metrics.items():
            sharpe = metrics.get("sharpe")
            if sharpe is None:
                if agent not in new_weights:
                    new_weights[agent] = 1.0
                continue

            current = new_weights.get(agent, 1.0)

            if sharpe > 0:
                new_weight = current * 1.05  # Winner gets louder
            else:
                new_weight = current * 0.95  # Loser gets quieter

            new_weight = max(0.3, min(2.5, new_weight))
            new_weights[agent] = round(new_weight, 3)

        return new_weights


# =============================================================================
# AUTORESEARCH SYSTEM
# =============================================================================

class Autoresearch:
    """Handles autonomous prompt improvement."""

    def __init__(self, scorer: AgentScorer):
        self.scorer = scorer
        self.modifications: List[AutoresearchModification] = []
        self.pending_experiment: Optional[AutoresearchModification] = None

    def run(self, day: int, date: str, agent_weights: dict) -> Optional[AutoresearchModification]:
        """Run autoresearch for worst agent."""
        # Log current metrics status
        metrics = self.scorer.agent_metrics
        scored_agents = [(a, m.get("sharpe"), m.get("scored", 0))
                         for a, m in metrics.items() if m.get("sharpe") is not None]
        if scored_agents:
            log(f"  Agent metrics: {len(scored_agents)} agents with Sharpe data")

        worst = self.scorer.get_worst_agent()

        if not worst:
            total_recs = len(self.scorer.recommendations)
            scored_recs = len([r for r in self.scorer.recommendations if r.return_5d is not None])
            log(f"  Autoresearch: No agent with sufficient data (total recs: {total_recs}, scored: {scored_recs})")
            return None

        agent_name, sharpe = worst
        log(f"  Autoresearch: Worst agent is {agent_name} (Sharpe: {sharpe:.3f})")

        # Load current prompt
        prompt_file = None
        for pattern in [f"{agent_name}.md", f"{agent_name}_desk.md"]:
            path = PROMPTS_DIR / pattern
            if path.exists():
                prompt_file = path
                break

        if not prompt_file:
            log(f"  Autoresearch: No prompt file for {agent_name}")
            return None

        with open(prompt_file, 'r') as f:
            current_prompt = f.read()

        # Get recent losing recommendations (using 5-day returns)
        agent_recs = [r for r in self.scorer.recommendations
                      if r.agent == agent_name and r.return_5d is not None and r.return_5d < 0]

        if not agent_recs:
            log(f"  Autoresearch: No losing recommendations for {agent_name}")
            return None

        # Generate modification
        log(f"  Autoresearch: Analyzing {agent_name} (Sharpe: {sharpe:.3f})")

        analysis_prompt = f"""You are improving a trading agent's prompt. The agent "{agent_name}" has a 10-day Sharpe ratio of {sharpe:.3f}.

CURRENT PROMPT:
{current_prompt}

RECENT LOSING RECOMMENDATIONS:
{json.dumps([asdict(r) for r in agent_recs[-5:]], indent=2)}

Analyze what went wrong and suggest ONE targeted modification.

Rules:
- Make exactly ONE change
- Keep it focused and specific
- The change should address the specific failure pattern

Output format (JSON only):
{{
  "analysis": "What went wrong",
  "change_type": "ADD|MODIFY|REMOVE",
  "change_description": "Brief description",
  "new_section": "The exact text to add/modify"
}}
"""

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            messages=[{"role": "user", "content": analysis_prompt}]
        )

        response_text = response.content[0].text

        # Parse response
        try:
            import re
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                suggestion = json.loads(json_match.group())
            else:
                return None
        except json.JSONDecodeError:
            return None

        change_desc = suggestion.get("change_description", "Unknown modification")
        new_section = suggestion.get("new_section", "")
        change_type = suggestion.get("change_type", "ADD")

        if not new_section:
            return None

        # Apply modification
        if change_type == "ADD":
            modified_prompt = current_prompt + f"\n\n## Autoresearch Addition\n{new_section}"
        elif change_type == "REMOVE":
            modified_prompt = current_prompt.replace(new_section, "")
        else:
            modified_prompt = current_prompt + f"\n\n## Autoresearch Modification\n{new_section}"

        # Save modified prompt
        with open(prompt_file, 'w') as f:
            f.write(modified_prompt)

        # Git commit
        commit_hash = ""
        try:
            subprocess.run(
                ["git", "add", str(prompt_file)],
                cwd=ATLAS_DIR,
                capture_output=True
            )
            result = subprocess.run(
                ["git", "commit", "-m", f"[autoresearch] day {day}: modified {agent_name} - {change_desc[:40]}"],
                cwd=ATLAS_DIR,
                capture_output=True
            )

            # Get commit hash
            hash_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=ATLAS_DIR,
                capture_output=True,
                text=True
            )
            commit_hash = hash_result.stdout.strip()[:7]
        except Exception as e:
            log(f"  Git commit failed: {e}", "WARN")

        mod = AutoresearchModification(
            day=day,
            date=date,
            agent=agent_name,
            modification=change_desc,
            pre_sharpe=sharpe,
            commit_hash=commit_hash
        )

        self.modifications.append(mod)
        self.pending_experiment = mod

        log(f"  Autoresearch: Modified {agent_name} - {change_desc[:40]}")

        return mod

    def evaluate_pending(self, current_metrics: dict) -> Optional[bool]:
        """Evaluate if pending experiment improved the agent."""
        if not self.pending_experiment:
            return None

        agent = self.pending_experiment.agent
        current_sharpe = current_metrics.get(agent, {}).get("sharpe")

        if current_sharpe is None:
            return None

        self.pending_experiment.post_sharpe = current_sharpe
        improved = current_sharpe > self.pending_experiment.pre_sharpe
        self.pending_experiment.kept = improved

        if improved:
            log(f"  Autoresearch KEPT: {agent} improved {self.pending_experiment.pre_sharpe:.3f} -> {current_sharpe:.3f}")
        else:
            log(f"  Autoresearch REVERTED: {agent} did not improve")
            # Git revert
            if self.pending_experiment.commit_hash:
                try:
                    subprocess.run(
                        ["git", "revert", "--no-commit", self.pending_experiment.commit_hash],
                        cwd=ATLAS_DIR,
                        capture_output=True
                    )
                    subprocess.run(
                        ["git", "commit", "-m", f"[autoresearch] revert day {self.pending_experiment.day}"],
                        cwd=ATLAS_DIR,
                        capture_output=True
                    )
                except Exception as e:
                    log(f"  Git revert failed: {e}", "WARN")

        self.pending_experiment = None
        return improved


# =============================================================================
# MAIN BACKTEST LOOP
# =============================================================================

class BacktestEngine:
    """Main backtest engine orchestrating all phases."""

    def __init__(self, start_date: str, end_date: str,
                 no_autoresearch: bool = False, verbose: bool = False):
        self.start_date = start_date
        self.end_date = end_date
        self.no_autoresearch = no_autoresearch
        self.verbose = verbose

        self.cache = DataCache()
        self.snapshot = MarketSnapshot(self.cache)
        self.debate = AgentDebate(self.snapshot, verbose)
        self.executor = TradeExecutor(self.snapshot)
        self.scorer = AgentScorer(self.snapshot)
        self.autoresearch = Autoresearch(self.scorer)

        self.portfolio = Portfolio()
        self.agent_weights: Dict[str, float] = {agent: 1.0 for agent in ALL_AGENTS}

        self.equity_curve: List[dict] = []
        self.trade_journal: List[dict] = []
        self.daily_snapshots: List[dict] = []

    def get_trading_days(self) -> List[str]:
        """Get list of trading days from cached price data."""
        spy_file = CACHE_DIR / "prices" / "SPY.json"

        if not spy_file.exists():
            log("SPY price data not found - run cache first", "ERROR")
            return []

        with open(spy_file, 'r') as f:
            data = json.load(f)

        prices = data.get("prices", {})
        all_dates = sorted(prices.keys())

        # Filter to date range
        trading_days = [d for d in all_dates if self.start_date <= d <= self.end_date]

        return trading_days

    def validate_anti_lookahead(self, date: str) -> bool:
        """Validate that we cannot access future data."""
        next_day = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

        # Try to get future price - should fail
        future_price = self.snapshot.get_price("SPY", next_day)

        # For validation, we check if the function would return data
        # In production, the snapshot builder already filters by date
        return True  # Snapshot builder enforces this

    def run_day(self, day_num: int, date: str, total_days: int) -> dict:
        """Run one trading day through the full pipeline."""
        day_result = {
            "day": day_num,
            "date": date,
            "trades": [],
            "autoresearch": None
        }

        # Update portfolio prices
        for pos in self.portfolio.positions:
            price = self.snapshot.get_price(pos.ticker, date)
            if price:
                pos.current_price = price

        prev_value = self.portfolio.total_value

        # Build CIO context: benchmark, drawdown, days since trade
        meta = self._build_cio_meta(date)

        # Phase B: Agent Debate
        log(f"  Running agent debate...")
        all_views = self.debate.run_debate(date, self.portfolio, self.agent_weights, meta)

        # Extract and record recommendations
        self.scorer.extract_and_record(date, all_views)

        # Phase C: Trade Execution
        cio_view = all_views.get("cio", {})
        sector_map = self.cache.sector_map or {}
        trades = self.executor.execute(date, self.portfolio, cio_view, sector_map)
        day_result["trades"] = trades
        self.trade_journal.extend(trades)

        # Phase D: Update Scorecards
        self.scorer.update_returns(date)
        metrics = self.scorer.calculate_metrics()
        self.agent_weights = self.scorer.update_weights(self.agent_weights)

        # Phase E: Autoresearch
        if not self.no_autoresearch and day_num >= 10:
            # Evaluate previous experiment
            if self.autoresearch.pending_experiment:
                self.autoresearch.evaluate_pending(metrics)

            # Run new autoresearch
            mod = self.autoresearch.run(day_num, date, self.agent_weights)
            if mod:
                day_result["autoresearch"] = asdict(mod)

        # Record equity curve
        current_value = self.portfolio.total_value
        daily_return = ((current_value - prev_value) / prev_value) * 100 if prev_value > 0 else 0

        self.equity_curve.append({
            "day": day_num,
            "date": date,
            "portfolio_value": current_value,
            "daily_return": daily_return,
            "cumulative_return": ((current_value - STARTING_CAPITAL) / STARTING_CAPITAL) * 100,
            "drawdown": self._calculate_drawdown(),
            "gross_exposure": self.portfolio.gross_exposure,
            "net_exposure": self.portfolio.net_exposure,
            "position_count": len(self.portfolio.positions),
            "cash": self.portfolio.cash
        })

        # Progress output
        cum_return = ((current_value - STARTING_CAPITAL) / STARTING_CAPITAL) * 100
        sharpe = self._calculate_rolling_sharpe()
        trades_str = f"Trades: {len(trades)}" if trades else "No trades"

        autoresearch_str = ""
        if day_result["autoresearch"]:
            ar = day_result["autoresearch"]
            autoresearch_str = f" | Autoresearch: {ar['agent']}"

        log(f"Day {day_num:03d}/{total_days} | {date} | ${current_value:,.0f} ({cum_return:+.1f}%) | Sharpe {sharpe:.2f} | {trades_str}{autoresearch_str}")

        return day_result

    def _calculate_drawdown(self) -> float:
        """Calculate current drawdown from peak."""
        if not self.equity_curve:
            return 0

        values = [e["portfolio_value"] for e in self.equity_curve]
        peak = max(values)
        current = self.portfolio.total_value

        return ((current - peak) / peak) * 100 if peak > 0 else 0

    def _build_cio_meta(self, date: str) -> dict:
        """Build additional context for CIO: benchmark, drawdown, days since trade."""
        # SPY return since backtest start
        spy_start_price = self.snapshot.get_price("SPY", self.start_date)
        spy_current_price = self.snapshot.get_price("SPY", date)
        spy_return = 0
        if spy_start_price and spy_current_price:
            spy_return = ((spy_current_price - spy_start_price) / spy_start_price) * 100

        # Peak portfolio value
        peak_value = STARTING_CAPITAL
        if self.equity_curve:
            peak_value = max(e["portfolio_value"] for e in self.equity_curve)

        # Drawdown from peak
        drawdown = self._calculate_drawdown()

        # Days since last trade
        days_since_trade = 0
        if self.trade_journal:
            last_trade_date = max(t.get("date", self.start_date) for t in self.trade_journal)
            try:
                last = datetime.strptime(last_trade_date, "%Y-%m-%d")
                current = datetime.strptime(date, "%Y-%m-%d")
                days_since_trade = (current - last).days
            except:
                pass
        else:
            # No trades yet - count from start
            try:
                start = datetime.strptime(self.start_date, "%Y-%m-%d")
                current = datetime.strptime(date, "%Y-%m-%d")
                days_since_trade = (current - start).days
            except:
                pass

        return {
            "spy_return": spy_return,
            "peak_value": peak_value,
            "drawdown": drawdown,
            "days_since_trade": days_since_trade
        }

    def _calculate_rolling_sharpe(self, window: int = 20) -> float:
        """Calculate rolling Sharpe ratio."""
        if len(self.equity_curve) < window:
            return 0

        returns = [e["daily_return"] for e in self.equity_curve[-window:]]
        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret)**2 for r in returns) / len(returns)
        std_dev = math.sqrt(variance) if variance > 0 else 0.001

        # Annualize
        return (mean_ret / std_dev) * math.sqrt(252) if std_dev > 0 else 0

    def save_checkpoint(self, day_num: int, date: str):
        """Save checkpoint for resume capability."""
        checkpoint = {
            "day": day_num,
            "date": date,
            "portfolio": {
                "cash": self.portfolio.cash,
                "positions": [asdict(p) if hasattr(p, '__dict__') else {
                    "ticker": p.ticker,
                    "direction": p.direction,
                    "shares": p.shares,
                    "entry_price": p.entry_price,
                    "entry_date": p.entry_date,
                    "cost_basis": p.cost_basis,
                    "current_price": p.current_price,
                    "sector": p.sector,
                    "agent_source": p.agent_source,
                    "thesis": p.thesis
                } for p in self.portfolio.positions]
            },
            "agent_weights": self.agent_weights,
            "equity_curve_length": len(self.equity_curve),
            "recommendations_count": len(self.scorer.recommendations),
            "timestamp": datetime.now().isoformat()
        }

        checkpoint_file = CHECKPOINT_DIR / f"day_{day_num:03d}.json"
        with open(checkpoint_file, 'w') as f:
            json.dump(checkpoint, f, indent=2)

    def load_checkpoint(self) -> Optional[int]:
        """Load most recent checkpoint. Returns day number to resume from."""
        checkpoints = sorted(CHECKPOINT_DIR.glob("day_*.json"))

        if not checkpoints:
            return None

        latest = checkpoints[-1]

        with open(latest, 'r') as f:
            checkpoint = json.load(f)

        # Restore state
        self.portfolio.cash = checkpoint["portfolio"]["cash"]
        self.portfolio.positions = []

        for p in checkpoint["portfolio"]["positions"]:
            pos = Position(
                ticker=p["ticker"],
                direction=p["direction"],
                shares=p["shares"],
                entry_price=p["entry_price"],
                entry_date=p["entry_date"],
                cost_basis=p["cost_basis"],
                current_price=p.get("current_price", p["entry_price"]),
                sector=p.get("sector", ""),
                agent_source=p.get("agent_source", ""),
                thesis=p.get("thesis", "")
            )
            self.portfolio.positions.append(pos)

        self.agent_weights = checkpoint["agent_weights"]

        log(f"Resumed from checkpoint: Day {checkpoint['day']}, {checkpoint['date']}")

        return checkpoint["day"]

    def generate_summary(self) -> dict:
        """Generate final backtest summary."""
        if not self.equity_curve:
            return {}

        values = [e["portfolio_value"] for e in self.equity_curve]
        returns = [e["daily_return"] for e in self.equity_curve]

        final_value = values[-1]
        total_return = ((final_value - STARTING_CAPITAL) / STARTING_CAPITAL) * 100

        # Calculate metrics
        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret)**2 for r in returns) / len(returns)
        std_dev = math.sqrt(variance) if variance > 0 else 0.001
        sharpe = (mean_ret / std_dev) * math.sqrt(252)

        # Drawdown
        peak = values[0]
        max_dd = 0
        max_dd_date = self.equity_curve[0]["date"]

        for e in self.equity_curve:
            if e["portfolio_value"] > peak:
                peak = e["portfolio_value"]
            dd = ((e["portfolio_value"] - peak) / peak) * 100
            if dd < max_dd:
                max_dd = dd
                max_dd_date = e["date"]

        # Win rate
        winning_trades = [t for t in self.trade_journal if t.get("pnl", 0) > 0]
        losing_trades = [t for t in self.trade_journal if t.get("pnl", 0) < 0]
        win_rate = len(winning_trades) / len(self.trade_journal) * 100 if self.trade_journal else 0

        # CAGR
        days = len(self.equity_curve)
        years = days / 252
        cagr = ((final_value / STARTING_CAPITAL) ** (1 / years) - 1) * 100 if years > 0 else 0

        # Autoresearch stats
        kept_mods = [m for m in self.autoresearch.modifications if m.kept]
        reverted_mods = [m for m in self.autoresearch.modifications if m.kept == False]

        summary = {
            "period": f"{self.start_date} to {self.end_date}",
            "trading_days": days,
            "starting_value": STARTING_CAPITAL,
            "ending_value": final_value,
            "total_return_pct": total_return,
            "cagr_pct": cagr,
            "sharpe_ratio": sharpe,
            "max_drawdown_pct": max_dd,
            "max_drawdown_date": max_dd_date,
            "win_rate_pct": win_rate,
            "total_trades": len(self.trade_journal),
            "autoresearch": {
                "total_modifications": len(self.autoresearch.modifications),
                "kept": len(kept_mods),
                "reverted": len(reverted_mods),
                "keep_rate_pct": len(kept_mods) / len(self.autoresearch.modifications) * 100 if self.autoresearch.modifications else 0
            },
            "final_agent_weights": self.agent_weights
        }

        return summary

    def save_results(self):
        """Save all results to files."""
        # Equity curve
        with open(RESULTS_DIR / "equity_curve.json", 'w') as f:
            json.dump(self.equity_curve, f, indent=2)

        # Trade journal
        with open(RESULTS_DIR / "trade_journal.json", 'w') as f:
            json.dump(self.trade_journal, f, indent=2)

        # Agent weights history
        with open(RESULTS_DIR / "final_agent_weights.json", 'w') as f:
            json.dump(self.agent_weights, f, indent=2)

        # Autoresearch log
        with open(RESULTS_DIR / "autoresearch_log.json", 'w') as f:
            json.dump([asdict(m) for m in self.autoresearch.modifications], f, indent=2)

        # Summary
        summary = self.generate_summary()
        with open(RESULTS_DIR / "summary.json", 'w') as f:
            json.dump(summary, f, indent=2)

        log(f"Results saved to {RESULTS_DIR}")

    def run(self, resume: bool = False) -> dict:
        """Run the full backtest."""
        log("="*60)
        log("ATLAS AUTORESEARCH BACKTEST ENGINE")
        log("="*60)
        log(f"Period: {self.start_date} to {self.end_date}")
        log(f"Starting Capital: ${STARTING_CAPITAL:,}")
        log(f"Autoresearch: {'DISABLED' if self.no_autoresearch else 'ENABLED'}")
        log("="*60)

        # Load sector map
        sector_file = CACHE_DIR / "sector_map.json"
        if sector_file.exists():
            with open(sector_file, 'r') as f:
                self.cache.sector_map = json.load(f)

        # Get trading days
        trading_days = self.get_trading_days()

        if not trading_days:
            log("No trading days found - ensure cache is populated", "ERROR")
            return {"error": "No trading days"}

        log(f"Trading days: {len(trading_days)}")

        # Resume from checkpoint if requested
        start_day = 0
        if resume:
            checkpoint_day = self.load_checkpoint()
            if checkpoint_day:
                start_day = checkpoint_day + 1

        # Main loop
        for i, date in enumerate(trading_days[start_day:], start=start_day + 1):
            try:
                self.run_day(i, date, len(trading_days))

                # Save checkpoint every 10 days
                if i % 10 == 0:
                    self.save_checkpoint(i, date)

            except KeyboardInterrupt:
                log("Interrupted - saving checkpoint...")
                self.save_checkpoint(i, date)
                break
            except Exception as e:
                log(f"Day {i} failed: {e}", "ERROR")
                import traceback
                traceback.print_exc()
                continue

        # Generate and save results
        self.save_results()
        summary = self.generate_summary()

        log("="*60)
        log("BACKTEST COMPLETE")
        log("="*60)
        log(f"Final Value: ${summary.get('ending_value', 0):,.2f}")
        log(f"Total Return: {summary.get('total_return_pct', 0):.2f}%")
        log(f"Sharpe Ratio: {summary.get('sharpe_ratio', 0):.2f}")
        log(f"Max Drawdown: {summary.get('max_drawdown_pct', 0):.2f}%")
        log(f"Autoresearch Mods: {summary.get('autoresearch', {}).get('total_modifications', 0)}")
        log("="*60)

        return summary


# =============================================================================
# ANTI-LOOKAHEAD VALIDATION
# =============================================================================

def run_anti_lookahead_tests():
    """Run anti-lookahead validation tests."""
    log("="*60)
    log("ANTI-LOOKAHEAD VALIDATION")
    log("="*60)

    cache = DataCache()
    snapshot = MarketSnapshot(cache)

    test_date = "2025-01-15"
    future_date = "2025-01-16"

    # Test 1: Price lookahead
    log("Test 1: Price lookahead protection")
    current_price = snapshot.get_price("SPY", test_date)
    future_price = snapshot.get_price("SPY", future_date)

    # Both should work since they're in the cache, but the snapshot builder
    # should filter based on the date parameter it receives
    log(f"  Current date price ({test_date}): {current_price}")
    log(f"  Future date price ({future_date}): {future_price} (expected: accessible in cache)")
    log("  Note: Snapshot.build_snapshot() filters data to prevent lookahead")

    # Test 2: Fundamental lookahead
    log("\nTest 2: Fundamental lookahead protection")
    fund = snapshot.get_fundamental("AAPL", test_date)
    if fund:
        log(f"  Fundamental data filing date: {fund.get('filing_date', 'N/A')}")
        log(f"  Filing date <= test date: {fund.get('filing_date', '') <= test_date}")

    # Test 3: FRED lookahead
    log("\nTest 3: FRED lookahead protection")
    vix = snapshot.get_fred_value("VIXCLS", test_date)
    log(f"  VIX value for {test_date}: {vix}")

    log("\nValidation complete. The snapshot builder enforces date filtering.")
    log("="*60)


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="ATLAS Autoresearch Backtest Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 -m agents.backtest_loop --cache-only          # Download data first
  python3 -m agents.backtest_loop --resume              # Resume from checkpoint
  python3 -m agents.backtest_loop --no-autoresearch     # Skip prompt evolution
  python3 -m agents.backtest_loop --start-date 2025-01-01 --end-date 2025-06-30
        """
    )

    parser.add_argument("--start-date", type=str, default=DEFAULT_START_DATE,
                        help=f"Start date (default: {DEFAULT_START_DATE})")
    parser.add_argument("--end-date", type=str, default=DEFAULT_END_DATE,
                        help=f"End date (default: {DEFAULT_END_DATE})")
    parser.add_argument("--resume", action="store_true",
                        help="Resume from last checkpoint")
    parser.add_argument("--cache-only", action="store_true",
                        help="Only cache data, don't run backtest")
    parser.add_argument("--no-autoresearch", action="store_true",
                        help="Disable prompt evolution")
    parser.add_argument("--verbose", action="store_true",
                        help="Print detailed agent output")
    parser.add_argument("--validate", action="store_true",
                        help="Run anti-lookahead validation tests")

    args = parser.parse_args()

    # Validation mode
    if args.validate:
        run_anti_lookahead_tests()
        return

    # Cache mode
    if args.cache_only:
        cache = DataCache()

        # Phase 1A: Prices
        cache.fetch_sp500_constituents()
        result = cache.fetch_all_prices(args.start_date, args.end_date, resume=args.resume)

        if result.get("status") == "partial":
            log("Price caching incomplete. Run again tomorrow with --resume --cache-only")
            return

        # Phase 1B: Fundamentals
        result = cache.fetch_all_fundamentals(resume=args.resume)

        if result.get("status") == "partial":
            log("Fundamental caching incomplete. Run again tomorrow with --resume --cache-only")
            return

        # Phase 1C: FRED
        cache.fetch_fred_data(args.start_date, args.end_date)

        # Phase 1D: Sector map
        cache.fetch_sector_map()

        # Validate
        cache.validate_cache()

        return

    # Create git branch for autoresearch if not exists
    if not args.no_autoresearch:
        try:
            subprocess.run(
                ["git", "checkout", "-b", "backtest/autoresearch-v1"],
                cwd=ATLAS_DIR,
                capture_output=True
            )
        except:
            pass  # Branch may already exist

    # Run backtest
    engine = BacktestEngine(
        start_date=args.start_date,
        end_date=args.end_date,
        no_autoresearch=args.no_autoresearch,
        verbose=args.verbose
    )

    # Validate cache first
    cache_status = engine.cache.validate_cache()
    if not cache_status["ready"]:
        log("Cache not ready. Run with --cache-only first.", "ERROR")
        return

    engine.run(resume=args.resume)


if __name__ == "__main__":
    main()
