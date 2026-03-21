#!/usr/bin/env python3
"""
ATLAS Autoresearch — Backtest Harness

THIS IS THE IMMUTABLE EVALUATION LAYER.
The autoresearch loop CANNOT modify this file.
It is the equivalent of Karpathy's prepare.py.

Purpose: Take a set of agent recommendations and score them against
actual market outcomes.

Inputs:
- The CIO's final output from an eod_cycle run (parsed for specific
  trade recommendations: ticker, direction, size, entry price)
- Historical price data for those tickers over the next 5 trading days
  (fetched from FMP using FMP_API_KEY in .env)

Outputs:
- sharpe_30d: The key metric for keep/revert decisions
- hit_rate: % of recommendations that were profitable
- avg_return_5d: Average 5-day return across recommendations
- max_drawdown_pct: Maximum portfolio drawdown
- worst_agent: Agent with lowest Sharpe contribution
- best_agent: Agent with highest Sharpe contribution

Critical: Uses the SAME evaluation window for every experiment in a
loop session. The window only advances when a new session starts.
"""

import json
import os
import re
import time
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import numpy as np
from dotenv import load_dotenv

# Load environment
load_dotenv(Path(__file__).parent.parent / ".env")

STATE_DIR = Path(__file__).parent.parent / "data" / "state"
RESULTS_DIR = Path(__file__).parent / "results"

FMP_API_KEY = os.getenv("FMP_API_KEY")
FMP_BASE = "https://financialmodelingprep.com/stable"

# Session window tracking
SESSION_WINDOW_FILE = RESULTS_DIR / "session_window.json"


def get_session_window() -> dict:
    """
    Get the current session's evaluation window.
    Window only advances when a new session starts.
    This ensures experiments are comparable within a session.
    """
    if SESSION_WINDOW_FILE.exists():
        with open(SESSION_WINDOW_FILE) as f:
            return json.load(f)

    # Initialize new session window
    return initialize_session_window()


def initialize_session_window() -> dict:
    """Initialize a new session window based on current date."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    today = datetime.now()
    # Use last 30 trading days for evaluation
    start_date = today - timedelta(days=45)  # Extra buffer for weekends/holidays

    window = {
        "session_id": today.strftime("%Y%m%d_%H%M%S"),
        "created": today.isoformat(),
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": today.strftime("%Y-%m-%d"),
        "experiments_run": 0
    }

    with open(SESSION_WINDOW_FILE, "w") as f:
        json.dump(window, f, indent=2)

    return window


def reset_session_window():
    """Reset the session window (call when starting new session)."""
    if SESSION_WINDOW_FILE.exists():
        SESSION_WINDOW_FILE.unlink()
    return initialize_session_window()


def fetch_historical_prices(ticker: str, start_date: str, end_date: str) -> list:
    """
    Fetch historical daily prices from FMP.
    Returns list of {date, open, high, low, close, volume} dicts.
    """
    if not FMP_API_KEY:
        print(f"[backtest] Warning: No FMP_API_KEY, cannot fetch prices for {ticker}")
        return []

    url = f"{FMP_BASE}/historical-price-full/{ticker}?from={start_date}&to={end_date}&apikey={FMP_API_KEY}"

    try:
        r = requests.get(url, timeout=15)
        if r.ok:
            data = r.json()
            historical = data.get("historical", [])
            # FMP returns newest first, reverse for chronological order
            return list(reversed(historical))
        else:
            print(f"[backtest] FMP error for {ticker}: {r.status_code}")
            return []
    except Exception as e:
        print(f"[backtest] Error fetching {ticker}: {e}")
        return []


def get_price_5d_forward(ticker: str, entry_date: str, entry_price: float) -> dict:
    """
    Get the price 5 trading days forward from entry_date.
    Returns {exit_date, exit_price, return_pct} or None if unavailable.
    """
    # Parse entry date
    entry_dt = datetime.strptime(entry_date, "%Y-%m-%d")
    # Fetch extra days to account for weekends/holidays
    end_dt = entry_dt + timedelta(days=10)

    prices = fetch_historical_prices(
        ticker,
        entry_date,
        end_dt.strftime("%Y-%m-%d")
    )

    if len(prices) < 6:  # Need at least 6 days (entry + 5 forward)
        return None

    # Get 5th trading day after entry
    exit_bar = prices[5] if len(prices) > 5 else prices[-1]
    exit_price = exit_bar.get("close", 0)
    exit_date = exit_bar.get("date", "")

    if exit_price == 0 or entry_price == 0:
        return None

    return_pct = ((exit_price - entry_price) / entry_price) * 100

    return {
        "exit_date": exit_date,
        "exit_price": exit_price,
        "return_pct": return_pct
    }


def extract_cio_recommendations(cio_output: str) -> list:
    """
    Parse CIO output for specific trade recommendations.
    Returns list of {ticker, direction, size_pct, entry_price} dicts.
    """
    recommendations = []

    if not cio_output:
        return recommendations

    # Look for RECOMMENDED ACTIONS section
    sections = re.split(r'\*\*RECOMMENDED ACTIONS\*\*|\#\#\s*RECOMMENDED ACTIONS', cio_output, flags=re.IGNORECASE)

    if len(sections) > 1:
        actions_text = sections[1].split("**")[0] if "**" in sections[1] else sections[1]
    else:
        actions_text = cio_output

    # Extract recommendations in common formats
    patterns = [
        # BUY/SELL TICKER @ $PRICE
        r'(BUY|SELL|LONG|SHORT)\s+([A-Z]{1,5})\s*[@$]\s*(\d+\.?\d*)',
        # TICKER: BUY/SELL @ $PRICE
        r'([A-Z]{1,5}):\s*(BUY|SELL|LONG|SHORT)\s*[@$]\s*(\d+\.?\d*)',
        # Add/Reduce TICKER (X%) @ $PRICE
        r'(ADD|REDUCE|TRIM)\s+([A-Z]{1,5})\s*\(?\s*(\d+\.?\d*)%?\)?\s*[@$]\s*(\d+\.?\d*)',
        # Simple TICKER DIRECTION patterns
        r'([A-Z]{1,5})\s*-?\s*(LONG|SHORT|BUY|SELL)',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, actions_text, re.IGNORECASE)
        for match in matches:
            try:
                if len(match) >= 4:
                    action, ticker, size, price = match[0], match[1], match[2], match[3]
                elif len(match) == 3:
                    if match[0].upper() in ["BUY", "SELL", "LONG", "SHORT"]:
                        action, ticker, price = match
                        size = "5"
                    else:
                        ticker, action, price = match
                        size = "5"
                elif len(match) == 2:
                    ticker, action = match
                    price = "0"
                    size = "5"
                else:
                    continue

                # Normalize direction
                direction = "LONG" if action.upper() in ["BUY", "LONG", "ADD"] else "SHORT"

                # Validate ticker
                if not re.match(r'^[A-Z]{1,5}$', ticker.upper()):
                    continue
                if ticker.upper() in ["THE", "AND", "FOR", "BUY", "SELL", "ADD", "CUT"]:
                    continue

                recommendations.append({
                    "ticker": ticker.upper(),
                    "direction": direction,
                    "size_pct": float(size) if size else 5.0,
                    "entry_price": float(price) if price else 0.0
                })
            except (ValueError, IndexError):
                continue

    # Deduplicate
    seen = set()
    unique_recs = []
    for rec in recommendations:
        key = f"{rec['ticker']}_{rec['direction']}"
        if key not in seen:
            seen.add(key)
            unique_recs.append(rec)

    return unique_recs


def calculate_portfolio_metrics(returns: list) -> dict:
    """
    Calculate portfolio-level metrics from a list of returns.
    """
    if not returns:
        return {
            "sharpe_30d": 0.0,
            "hit_rate": 0.0,
            "avg_return_5d": 0.0,
            "max_drawdown_pct": 0.0,
            "total_return": 0.0,
            "volatility": 0.0
        }

    returns_array = np.array(returns)

    # Hit rate: % of positive returns
    hit_rate = np.sum(returns_array > 0) / len(returns_array)

    # Average 5-day return
    avg_return = np.mean(returns_array)

    # Volatility
    volatility = np.std(returns_array) if len(returns_array) > 1 else 0.0

    # Sharpe ratio (annualized from 5-day returns)
    # Assuming ~50 5-day periods per year
    if volatility > 0:
        sharpe_30d = (avg_return / volatility) * np.sqrt(50)
    else:
        sharpe_30d = 0.0 if avg_return == 0 else np.sign(avg_return) * 10.0

    # Total return (compounded)
    total_return = np.prod(1 + returns_array / 100) - 1

    # Max drawdown
    cumulative = np.cumprod(1 + returns_array / 100)
    running_max = np.maximum.accumulate(cumulative)
    drawdown = (cumulative - running_max) / running_max
    max_drawdown_pct = np.min(drawdown) * 100

    return {
        "sharpe_30d": round(sharpe_30d, 2),
        "hit_rate": round(hit_rate, 2),
        "avg_return_5d": round(avg_return, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "total_return": round(total_return * 100, 2),
        "volatility": round(volatility, 2)
    }


def score_recommendations(recommendations: list, window: dict) -> dict:
    """
    Score a list of recommendations against actual market outcomes.

    Args:
        recommendations: List of {ticker, direction, size_pct, entry_price}
        window: Session window with start_date and end_date

    Returns:
        Dict with portfolio metrics and per-recommendation results
    """
    results = []
    returns = []

    for rec in recommendations:
        ticker = rec["ticker"]
        direction = rec["direction"]
        entry_price = rec.get("entry_price", 0)

        # If no entry price, fetch current price
        if entry_price == 0:
            today = datetime.now().strftime("%Y-%m-%d")
            prices = fetch_historical_prices(ticker, today, today)
            if prices:
                entry_price = prices[-1].get("close", 0)

        if entry_price == 0:
            continue

        # Get 5-day forward return
        entry_date = window.get("end_date", datetime.now().strftime("%Y-%m-%d"))
        forward = get_price_5d_forward(ticker, entry_date, entry_price)

        if forward is None:
            continue

        # Adjust return for direction
        if direction == "SHORT":
            return_pct = -forward["return_pct"]
        else:
            return_pct = forward["return_pct"]

        results.append({
            "ticker": ticker,
            "direction": direction,
            "entry_price": entry_price,
            "exit_price": forward["exit_price"],
            "entry_date": entry_date,
            "exit_date": forward["exit_date"],
            "return_pct": round(return_pct, 2)
        })

        returns.append(return_pct)

        # Rate limit for FMP
        time.sleep(0.2)

    # Calculate portfolio metrics
    metrics = calculate_portfolio_metrics(returns)
    metrics["total_positions"] = len(results)
    metrics["recommendations"] = results

    return metrics


def run_backtest(cio_output: str = None, all_views: dict = None) -> dict:
    """
    Run backtest on CIO recommendations.

    Args:
        cio_output: The CIO's synthesis output text
        all_views: Dict of all agent views (for attribution)

    Returns:
        Dict with backtest results including sharpe_30d
    """
    window = get_session_window()

    # Extract recommendations from CIO output
    if cio_output:
        recommendations = extract_cio_recommendations(cio_output)
    else:
        # Try to load from saved views
        views_file = STATE_DIR / "eod_agent_views.json"
        if views_file.exists():
            with open(views_file) as f:
                views = json.load(f)
                cio_output = views.get("views", {}).get("cio", "")
                recommendations = extract_cio_recommendations(cio_output)
        else:
            recommendations = []

    if not recommendations:
        print("[backtest] No recommendations found to score")
        return {
            "sharpe_30d": 0.0,
            "hit_rate": 0.0,
            "avg_return_5d": 0.0,
            "max_drawdown_pct": 0.0,
            "total_positions": 0,
            "worst_agent": None,
            "best_agent": None
        }

    print(f"[backtest] Scoring {len(recommendations)} recommendations...")

    # Score recommendations
    results = score_recommendations(recommendations, window)

    # Get agent attribution if available
    from autoresearch.attribution import get_worst_agent, get_best_agent
    worst_agent, _ = get_worst_agent()
    best_agent, _ = get_best_agent()

    results["worst_agent"] = worst_agent
    results["best_agent"] = best_agent
    results["session_id"] = window.get("session_id")
    results["timestamp"] = datetime.now().isoformat()

    # Update session experiment count
    window["experiments_run"] = window.get("experiments_run", 0) + 1
    with open(SESSION_WINDOW_FILE, "w") as f:
        json.dump(window, f, indent=2)

    # Save detailed results
    results_file = RESULTS_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_backtest.json"
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)

    return results


def print_results(results: dict):
    """Print backtest results in greppable format."""
    print("\n---")
    print(f"sharpe_30d:         {results.get('sharpe_30d', 0):.2f}")
    print(f"hit_rate:           {results.get('hit_rate', 0):.2f}")
    print(f"avg_return_5d:      {results.get('avg_return_5d', 0):.1f}")
    print(f"max_drawdown_pct:   {results.get('max_drawdown_pct', 0):.1f}")
    print(f"total_positions:    {results.get('total_positions', 0)}")
    print(f"worst_agent:        {results.get('worst_agent', 'N/A')}")
    print(f"best_agent:         {results.get('best_agent', 'N/A')}")
    print("---")


def backtest_from_file(views_file: str = None) -> dict:
    """
    Run backtest from a saved agent views file.
    """
    if views_file is None:
        views_file = STATE_DIR / "eod_agent_views.json"
    else:
        views_file = Path(views_file)

    if not views_file.exists():
        print(f"[backtest] Views file not found: {views_file}")
        return {}

    with open(views_file) as f:
        data = json.load(f)

    cio_output = data.get("views", {}).get("cio", "")

    return run_backtest(cio_output=cio_output, all_views=data.get("views", {}))


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--reset":
        print("[backtest] Resetting session window...")
        reset_session_window()

    results = backtest_from_file()
    print_results(results)
