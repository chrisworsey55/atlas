#!/usr/bin/env python3
"""
ATLAS Autoresearch — Per-Agent Attribution

Tracks each agent's individual contribution to portfolio performance.
This tells the loop WHICH agent to mutate next.

For each agent, tracks:
- What it recommended (from its output in all_views)
- Whether the CIO included that recommendation
- 5-day forward return of the recommendation
- Rolling hit rate (last 30 recommendations)
- Rolling Sharpe contribution
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import numpy as np

STATE_DIR = Path(__file__).parent.parent / "data" / "state"
RESULTS_DIR = Path(__file__).parent / "results"
SCORES_FILE = RESULTS_DIR / "agent_scores.json"

# Layer definitions for fast cycle optimization
LAYER_1_AGENTS = ["news", "flow"]  # Data agents
LAYER_2_AGENTS = [
    "bond", "currency", "commodities", "metals", "semiconductor",
    "biotech", "energy", "consumer", "industrials", "microcap"
]  # Sector desks
LAYER_3_AGENTS = ["druckenmiller", "aschenbrenner", "baker", "ackman"]  # Superinvestors
LAYER_4_AGENTS = ["cro", "alpha", "autonomous", "cio"]  # Risk & Decision

ALL_AGENTS = LAYER_1_AGENTS + LAYER_2_AGENTS + LAYER_3_AGENTS + LAYER_4_AGENTS


def load_agent_scores() -> dict:
    """Load existing agent scores from JSON file."""
    if SCORES_FILE.exists():
        with open(SCORES_FILE) as f:
            return json.load(f)
    return initialize_scores()


def save_agent_scores(scores: dict):
    """Save agent scores to JSON file."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    scores["last_updated"] = datetime.now().isoformat()
    with open(SCORES_FILE, "w") as f:
        json.dump(scores, f, indent=2)


def initialize_scores() -> dict:
    """Initialize empty score structure for all agents."""
    scores = {
        "agents": {},
        "created": datetime.now().isoformat(),
        "last_updated": datetime.now().isoformat()
    }

    for agent in ALL_AGENTS:
        scores["agents"][agent] = {
            "recommendations": [],  # List of {ticker, direction, date, entry_price, exit_price, return_5d, cio_included}
            "rolling_hit_rate": 0.0,  # Last 30 recommendations
            "rolling_sharpe": 0.0,  # Sharpe contribution
            "total_recommendations": 0,
            "cio_adoption_rate": 0.0,  # How often CIO follows this agent
            "last_updated": None
        }

    return scores


def extract_recommendations_from_view(agent_name: str, view_text: str) -> list:
    """
    Extract trade recommendations from an agent's view text.

    Returns list of {ticker, direction, conviction} dicts.
    Uses regex patterns to find common recommendation formats.
    """
    recommendations = []

    if not view_text:
        return recommendations

    # Common patterns in agent outputs
    patterns = [
        # TICKER: LONG/SHORT or BUY/SELL patterns
        r'([A-Z]{1,5}):\s*(LONG|SHORT|BUY|SELL)',
        r'(LONG|SHORT|BUY|SELL)\s+([A-Z]{1,5})',
        # Recommendation with conviction
        r'([A-Z]{1,5})\s*\([^)]*\)\s*-?\s*(LONG|SHORT|BUY|SELL)',
        # Action: TICKER patterns
        r'(BUY|SELL|LONG|SHORT):\s*([A-Z]{1,5})',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, view_text, re.IGNORECASE)
        for match in matches:
            if isinstance(match, tuple):
                if match[0].upper() in ["LONG", "SHORT", "BUY", "SELL"]:
                    direction = "LONG" if match[0].upper() in ["LONG", "BUY"] else "SHORT"
                    ticker = match[1].upper()
                else:
                    ticker = match[0].upper()
                    direction = "LONG" if match[1].upper() in ["LONG", "BUY"] else "SHORT"

                # Validate ticker (1-5 uppercase letters, no numbers)
                if re.match(r'^[A-Z]{1,5}$', ticker) and ticker not in ["THE", "AND", "FOR", "BUY", "SELL"]:
                    recommendations.append({
                        "ticker": ticker,
                        "direction": direction
                    })

    # Deduplicate
    seen = set()
    unique_recs = []
    for rec in recommendations:
        key = f"{rec['ticker']}_{rec['direction']}"
        if key not in seen:
            seen.add(key)
            unique_recs.append(rec)

    return unique_recs


def check_cio_inclusion(ticker: str, direction: str, cio_view: str) -> bool:
    """Check if the CIO's final output includes this recommendation."""
    if not cio_view:
        return False

    # Look for the ticker in CIO output
    ticker_pattern = rf'\b{ticker}\b'
    if not re.search(ticker_pattern, cio_view, re.IGNORECASE):
        return False

    # Check if direction matches
    direction_patterns = {
        "LONG": ["LONG", "BUY", "ADD", "INCREASE", "POSITION IN"],
        "SHORT": ["SHORT", "SELL", "REDUCE", "CUT", "TRIM"]
    }

    for pattern in direction_patterns.get(direction, []):
        if pattern.lower() in cio_view.lower():
            return True

    return False


def get_price_on_date(ticker: str, date: datetime) -> Optional[float]:
    """
    Get price for a ticker on a specific date.
    Uses pnl_history.json or positions.json as data source.
    """
    # Try to find in P&L history
    pnl_file = STATE_DIR / "pnl_history.json"
    if pnl_file.exists():
        with open(pnl_file) as f:
            history = json.load(f)

        # Find closest date entry
        target_str = date.strftime("%Y-%m-%d")
        for entry in history:
            entry_date = entry.get("date", "")
            if isinstance(entry_date, str) and entry_date.startswith(target_str):
                positions = entry.get("positions", {})
                if ticker in positions:
                    return positions[ticker].get("current")

    return None


def calculate_5d_return(ticker: str, direction: str, entry_date: datetime, entry_price: float) -> Optional[float]:
    """
    Calculate 5-day forward return for a recommendation.
    Returns percentage return (positive = good for the recommendation).
    """
    exit_date = entry_date + timedelta(days=5)
    exit_price = get_price_on_date(ticker, exit_date)

    if exit_price is None or entry_price is None or entry_price == 0:
        return None

    if direction == "LONG":
        return ((exit_price - entry_price) / entry_price) * 100
    else:  # SHORT
        return ((entry_price - exit_price) / entry_price) * 100


def update_agent_attribution(agent_name: str, recommendations: list, cio_view: str, date: datetime):
    """
    Update attribution for a single agent based on its recommendations.
    """
    scores = load_agent_scores()

    if agent_name not in scores["agents"]:
        scores["agents"][agent_name] = {
            "recommendations": [],
            "rolling_hit_rate": 0.0,
            "rolling_sharpe": 0.0,
            "total_recommendations": 0,
            "cio_adoption_rate": 0.0,
            "last_updated": None
        }

    agent_data = scores["agents"][agent_name]

    for rec in recommendations:
        ticker = rec["ticker"]
        direction = rec["direction"]

        # Get entry price (use current price from positions or estimate)
        entry_price = get_price_on_date(ticker, date)

        # Check if CIO included this recommendation
        cio_included = check_cio_inclusion(ticker, direction, cio_view)

        # Calculate 5-day return (may be None if insufficient data)
        return_5d = calculate_5d_return(ticker, direction, date, entry_price) if entry_price else None

        # Add to recommendations list
        rec_entry = {
            "ticker": ticker,
            "direction": direction,
            "date": date.isoformat(),
            "entry_price": entry_price,
            "return_5d": return_5d,
            "cio_included": cio_included,
            "scored": return_5d is not None
        }
        agent_data["recommendations"].append(rec_entry)

    # Keep only last 100 recommendations per agent
    agent_data["recommendations"] = agent_data["recommendations"][-100:]
    agent_data["total_recommendations"] = len(agent_data["recommendations"])
    agent_data["last_updated"] = date.isoformat()

    # Update rolling metrics
    _update_rolling_metrics(agent_data)

    save_agent_scores(scores)


def _update_rolling_metrics(agent_data: dict):
    """Update rolling hit rate and Sharpe for an agent."""
    recs = agent_data["recommendations"]

    # Only consider scored recommendations (have return_5d)
    scored_recs = [r for r in recs if r.get("scored") and r.get("return_5d") is not None]

    if not scored_recs:
        return

    # Last 30 for rolling metrics
    recent = scored_recs[-30:]

    # Hit rate: % of positive returns
    hits = sum(1 for r in recent if r["return_5d"] > 0)
    agent_data["rolling_hit_rate"] = hits / len(recent) if recent else 0.0

    # Sharpe: mean / std of returns
    returns = [r["return_5d"] for r in recent]
    if len(returns) >= 5:
        mean_return = np.mean(returns)
        std_return = np.std(returns)
        agent_data["rolling_sharpe"] = mean_return / std_return if std_return > 0 else 0.0

    # CIO adoption rate
    total_recs = len(recs[-30:])
    cio_adopted = sum(1 for r in recs[-30:] if r.get("cio_included"))
    agent_data["cio_adoption_rate"] = cio_adopted / total_recs if total_recs > 0 else 0.0


def process_eod_views(all_views: dict, date: datetime = None):
    """
    Process all agent views from an EOD cycle run.
    Extract recommendations and update attribution for each agent.
    """
    if date is None:
        date = datetime.now()

    cio_view = all_views.get("cio", "")

    for agent_name, view_text in all_views.items():
        if agent_name == "cio":
            continue  # Don't attribute CIO to itself

        recommendations = extract_recommendations_from_view(agent_name, view_text)

        if recommendations:
            update_agent_attribution(agent_name, recommendations, cio_view, date)
            print(f"[attribution] {agent_name}: {len(recommendations)} recommendations extracted")


def get_worst_agent() -> tuple[str, dict]:
    """
    Identify the worst performing agent by rolling Sharpe contribution.
    This is the mutation target for the autoresearch loop.

    Returns (agent_name, agent_data) tuple.
    """
    scores = load_agent_scores()

    worst_agent = None
    worst_sharpe = float("inf")
    worst_data = None

    # Only consider agents in Layers 2-3 (sector desks and superinvestors)
    # These are the agents we can meaningfully mutate
    mutable_agents = LAYER_2_AGENTS + LAYER_3_AGENTS

    for agent_name in mutable_agents:
        agent_data = scores["agents"].get(agent_name, {})

        # Skip agents with insufficient data
        if agent_data.get("total_recommendations", 0) < 5:
            continue

        sharpe = agent_data.get("rolling_sharpe", 0.0)

        if sharpe < worst_sharpe:
            worst_sharpe = sharpe
            worst_agent = agent_name
            worst_data = agent_data

    # If no agents have enough data, pick a random sector desk
    if worst_agent is None:
        import random
        worst_agent = random.choice(LAYER_2_AGENTS)
        worst_data = scores["agents"].get(worst_agent, {})

    return worst_agent, worst_data


def get_best_agent() -> tuple[str, dict]:
    """
    Identify the best performing agent by rolling Sharpe.
    Useful for understanding what's working.
    """
    scores = load_agent_scores()

    best_agent = None
    best_sharpe = float("-inf")
    best_data = None

    mutable_agents = LAYER_2_AGENTS + LAYER_3_AGENTS

    for agent_name in mutable_agents:
        agent_data = scores["agents"].get(agent_name, {})

        if agent_data.get("total_recommendations", 0) < 5:
            continue

        sharpe = agent_data.get("rolling_sharpe", 0.0)

        if sharpe > best_sharpe:
            best_sharpe = sharpe
            best_agent = agent_name
            best_data = agent_data

    return best_agent, best_data


def get_agent_layer(agent_name: str) -> int:
    """Return the layer number (1-4) for an agent."""
    if agent_name in LAYER_1_AGENTS:
        return 1
    elif agent_name in LAYER_2_AGENTS:
        return 2
    elif agent_name in LAYER_3_AGENTS:
        return 3
    elif agent_name in LAYER_4_AGENTS:
        return 4
    return 0


def print_agent_rankings():
    """Print agent rankings by Sharpe for debugging."""
    scores = load_agent_scores()

    rankings = []
    for agent_name in LAYER_2_AGENTS + LAYER_3_AGENTS:
        agent_data = scores["agents"].get(agent_name, {})
        rankings.append({
            "agent": agent_name,
            "sharpe": agent_data.get("rolling_sharpe", 0.0),
            "hit_rate": agent_data.get("rolling_hit_rate", 0.0),
            "recs": agent_data.get("total_recommendations", 0),
            "cio_adopt": agent_data.get("cio_adoption_rate", 0.0)
        })

    rankings.sort(key=lambda x: x["sharpe"], reverse=True)

    print("\n" + "=" * 80)
    print("AGENT RANKINGS BY SHARPE")
    print("=" * 80)
    print(f"{'Agent':<20} {'Sharpe':>10} {'Hit Rate':>10} {'Recs':>8} {'CIO Adopt':>10}")
    print("-" * 80)

    for r in rankings:
        print(f"{r['agent']:<20} {r['sharpe']:>10.2f} {r['hit_rate']*100:>9.1f}% {r['recs']:>8} {r['cio_adopt']*100:>9.1f}%")

    print("-" * 80)

    worst, _ = get_worst_agent()
    best, _ = get_best_agent()
    print(f"\nMutation target (worst): {worst}")
    print(f"Best performer: {best}")


if __name__ == "__main__":
    # Test: print current rankings
    print_agent_rankings()
