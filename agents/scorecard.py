#!/usr/bin/env python3
"""
ATLAS Agent Scorecard System

Tracks every recommendation every agent makes and attributes P&L back to each agent.
This is the evaluation harness for the autoresearch self-improvement loop.
"""
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

STATE_DIR = Path(__file__).parent.parent / "data" / "state"
SCORECARD_FILE = STATE_DIR / "agent_scorecards.json"
WEIGHTS_FILE = STATE_DIR / "agent_weights.json"


def load_scorecards() -> dict:
    """Load existing scorecards from file."""
    default = {
        "recommendations": [],
        "agent_metrics": {},
        "last_updated": None
    }

    if not SCORECARD_FILE.exists():
        return default

    with open(SCORECARD_FILE, 'r') as f:
        data = json.load(f)

    # Handle both old format (agent-keyed) and new format (recommendations array)
    if "recommendations" in data:
        return data

    # Convert old agent-keyed format to new format
    # Old format: {"druckenmiller": {"recommendations": [...], "metrics": {...}}, ...}
    # New format: {"recommendations": [...], "agent_metrics": {...}}
    new_data = {
        "recommendations": [],
        "agent_metrics": {},
        "last_updated": datetime.now().isoformat()
    }

    for agent_name, agent_data in data.items():
        if isinstance(agent_data, dict):
            # Copy metrics
            if "metrics" in agent_data:
                new_data["agent_metrics"][agent_name] = agent_data["metrics"]

    return new_data


def save_scorecards(data: dict):
    """Save scorecards to file."""
    data["last_updated"] = datetime.now().isoformat()
    with open(SCORECARD_FILE, 'w') as f:
        json.dump(data, f, indent=2)


def load_weights() -> dict:
    """Load agent weights from file."""
    if WEIGHTS_FILE.exists():
        with open(WEIGHTS_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_weights(weights: dict):
    """Save agent weights to file."""
    with open(WEIGHTS_FILE, 'w') as f:
        json.dump(weights, f, indent=2)


def record_recommendation(
    agent: str,
    ticker: str,
    direction: str,  # LONG or SHORT
    conviction: int,  # 0-100
    entry_price: float,
    rationale: Optional[str] = None
):
    """Record a new recommendation from an agent."""
    data = load_scorecards()

    rec = {
        "id": f"{agent}_{ticker}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "agent": agent,
        "date": datetime.now().strftime('%Y-%m-%d'),
        "timestamp": datetime.now().isoformat(),
        "ticker": ticker,
        "direction": direction.upper(),
        "conviction": conviction,
        "entry_price": entry_price,
        "rationale": rationale,
        "price_1d": None,
        "price_5d": None,
        "price_10d": None,
        "return_1d": None,
        "return_5d": None,
        "return_10d": None,
        "status": "open"
    }

    data["recommendations"].append(rec)
    save_scorecards(data)
    print(f"[SCORECARD] Recorded: {agent} → {direction} {ticker} @ ${entry_price:.2f} (conviction: {conviction}%)")
    return rec


def extract_recommendations_from_views(all_views: dict, portfolio_tickers: list) -> list:
    """
    Parse agent views and extract explicit recommendations.
    Returns list of (agent, ticker, direction, conviction) tuples.
    """
    recommendations = []

    # Patterns to look for recommendations
    buy_patterns = [
        r'(?:BUY|LONG|ADD|ACCUMULATE|INITIATE)\s+(\$?[A-Z]{1,5})',
        r'(\$?[A-Z]{1,5})\s+(?:is a |looks like a |represents a )?(?:BUY|LONG)',
        r'recommend(?:ing)?\s+(?:a\s+)?(?:LONG|BUY)\s+(?:position\s+in\s+)?(\$?[A-Z]{1,5})',
    ]

    sell_patterns = [
        r'(?:SELL|SHORT|REDUCE|TRIM|EXIT)\s+(\$?[A-Z]{1,5})',
        r'(\$?[A-Z]{1,5})\s+(?:is a |looks like a )?(?:SELL|SHORT)',
        r'recommend(?:ing)?\s+(?:a\s+)?(?:SHORT|SELL)\s+(?:position\s+in\s+)?(\$?[A-Z]{1,5})',
    ]

    # Conviction patterns
    conviction_patterns = [
        r'(\d{1,3})%?\s*confidence',
        r'confidence[:\s]+(\d{1,3})%?',
        r'conviction[:\s]+(\d{1,3})%?',
    ]

    for agent, view in all_views.items():
        if not view:
            continue

        view_upper = view.upper()

        # Look for buy recommendations
        for pattern in buy_patterns:
            matches = re.findall(pattern, view_upper, re.IGNORECASE)
            for match in matches:
                ticker = match.replace('$', '').strip()
                if len(ticker) >= 1 and len(ticker) <= 5 and ticker.isalpha():
                    # Try to extract conviction
                    conviction = 70  # default
                    for conv_pattern in conviction_patterns:
                        conv_match = re.search(conv_pattern, view, re.IGNORECASE)
                        if conv_match:
                            conviction = int(conv_match.group(1))
                            break
                    recommendations.append((agent, ticker, "LONG", conviction))

        # Look for sell/short recommendations
        for pattern in sell_patterns:
            matches = re.findall(pattern, view_upper, re.IGNORECASE)
            for match in matches:
                ticker = match.replace('$', '').strip()
                if len(ticker) >= 1 and len(ticker) <= 5 and ticker.isalpha():
                    conviction = 70  # default
                    for conv_pattern in conviction_patterns:
                        conv_match = re.search(conv_pattern, view, re.IGNORECASE)
                        if conv_match:
                            conviction = int(conv_match.group(1))
                            break
                    recommendations.append((agent, ticker, "SHORT", conviction))

    return recommendations


def update_prices():
    """Update prices for all open recommendations and calculate returns."""
    from agents.market_data import get_validated_quote

    data = load_scorecards()
    updated_count = 0

    for rec in data["recommendations"]:
        if rec.get("status") != "open":
            continue

        rec_date = datetime.fromisoformat(rec["timestamp"]).date()
        today = datetime.now().date()
        days_since = (today - rec_date).days

        if days_since < 1:
            continue

        ticker = rec["ticker"]
        entry_price = rec["entry_price"]
        direction = rec["direction"]

        try:
            quote = get_validated_quote(ticker)
            current_price = quote.get("price") if quote else None
            if not current_price or current_price == 0:
                continue

            # Calculate return based on direction
            if direction == "LONG":
                ret = ((current_price - entry_price) / entry_price) * 100
            else:  # SHORT
                ret = ((entry_price - current_price) / entry_price) * 100

            # Update based on days since recommendation
            if days_since >= 1 and rec["price_1d"] is None:
                rec["price_1d"] = current_price
                rec["return_1d"] = round(ret, 2)
                updated_count += 1

            if days_since >= 5 and rec["price_5d"] is None:
                rec["price_5d"] = current_price
                rec["return_5d"] = round(ret, 2)
                updated_count += 1

            if days_since >= 10 and rec["price_10d"] is None:
                rec["price_10d"] = current_price
                rec["return_10d"] = round(ret, 2)
                rec["status"] = "closed"  # Mark as closed after 10 days
                updated_count += 1

        except Exception as e:
            print(f"[SCORECARD] Error updating {ticker}: {e}")
            continue

    save_scorecards(data)
    print(f"[SCORECARD] Updated {updated_count} price points")
    return updated_count


def calculate_agent_metrics() -> dict:
    """Calculate performance metrics for each agent."""
    data = load_scorecards()
    metrics = {}

    # Group recommendations by agent
    agent_recs = {}
    for rec in data["recommendations"]:
        agent = rec["agent"]
        if agent not in agent_recs:
            agent_recs[agent] = []
        agent_recs[agent].append(rec)

    for agent, recs in agent_recs.items():
        # Filter to recommendations with 5d returns
        recs_5d = [r for r in recs if r.get("return_5d") is not None]
        recs_10d = [r for r in recs if r.get("return_10d") is not None]

        if not recs:
            continue

        # Calculate metrics
        total_recs = len(recs)

        # Hit rates
        hits_5d = sum(1 for r in recs_5d if r["return_5d"] > 0)
        hits_10d = sum(1 for r in recs_10d if r["return_10d"] > 0)
        hit_rate_5d = (hits_5d / len(recs_5d) * 100) if recs_5d else None
        hit_rate_10d = (hits_10d / len(recs_10d) * 100) if recs_10d else None

        # Average returns
        avg_return_5d = sum(r["return_5d"] for r in recs_5d) / len(recs_5d) if recs_5d else None
        avg_return_10d = sum(r["return_10d"] for r in recs_10d) / len(recs_10d) if recs_10d else None

        # Sharpe ratio (10-day) - simplified, using 0 as risk-free rate
        if recs_10d and len(recs_10d) >= 3:
            returns = [r["return_10d"] for r in recs_10d]
            mean_return = sum(returns) / len(returns)
            variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
            std_dev = variance ** 0.5
            sharpe_10d = (mean_return / std_dev) if std_dev > 0 else 0
        else:
            sharpe_10d = None

        # Best and worst calls
        best_call = None
        worst_call = None
        if recs_10d:
            best_rec = max(recs_10d, key=lambda r: r["return_10d"])
            worst_rec = min(recs_10d, key=lambda r: r["return_10d"])
            best_call = {
                "ticker": best_rec["ticker"],
                "direction": best_rec["direction"],
                "return": best_rec["return_10d"],
                "date": best_rec["date"]
            }
            worst_call = {
                "ticker": worst_rec["ticker"],
                "direction": worst_rec["direction"],
                "return": worst_rec["return_10d"],
                "date": worst_rec["date"]
            }

        metrics[agent] = {
            "total_recommendations": total_recs,
            "recommendations_5d": len(recs_5d),
            "recommendations_10d": len(recs_10d),
            "hit_rate_5d": round(hit_rate_5d, 1) if hit_rate_5d else None,
            "hit_rate_10d": round(hit_rate_10d, 1) if hit_rate_10d else None,
            "avg_return_5d": round(avg_return_5d, 2) if avg_return_5d else None,
            "avg_return_10d": round(avg_return_10d, 2) if avg_return_10d else None,
            "sharpe_10d": round(sharpe_10d, 3) if sharpe_10d else None,
            "best_call": best_call,
            "worst_call": worst_call,
            "last_updated": datetime.now().isoformat()
        }

    data["agent_metrics"] = metrics
    save_scorecards(data)
    return metrics


def update_agent_weights() -> dict:
    """
    Update agent weights based on performance.
    Weight rules:
    - Agent Sharpe > 0 → weight * 1.1
    - Agent Sharpe <= 0 → weight * 0.9
    - Floor: 0.3 (triggers mandatory prompt rewrite)
    - Ceiling: 2.5 (prevents over-concentration)
    """
    metrics = calculate_agent_metrics()
    weights = load_weights()

    # Default weight for new agents
    default_weight = 1.0

    for agent, m in metrics.items():
        sharpe = m.get("sharpe_10d")

        # Skip if not enough data
        if sharpe is None:
            if agent not in weights:
                weights[agent] = default_weight
            continue

        current_weight = weights.get(agent, default_weight)

        # Adjust weight based on Sharpe ratio
        if sharpe > 0:
            new_weight = current_weight * 1.1
        else:
            new_weight = current_weight * 0.9

        # Apply floor and ceiling
        new_weight = max(0.3, min(2.5, new_weight))
        weights[agent] = round(new_weight, 3)

        print(f"[WEIGHTS] {agent}: {current_weight:.3f} → {new_weight:.3f} (Sharpe: {sharpe:.3f})")

    save_weights(weights)
    return weights


def get_worst_agent() -> Optional[tuple]:
    """
    Get the worst-performing agent (lowest 10-day Sharpe).
    Returns (agent_name, sharpe, weight) or None if not enough data.
    """
    metrics = calculate_agent_metrics()
    weights = load_weights()

    agents_with_sharpe = [
        (agent, m["sharpe_10d"], weights.get(agent, 1.0))
        for agent, m in metrics.items()
        if m.get("sharpe_10d") is not None
    ]

    if not agents_with_sharpe:
        return None

    # Sort by Sharpe ratio (ascending = worst first)
    agents_with_sharpe.sort(key=lambda x: x[1])
    worst = agents_with_sharpe[0]

    return worst


def get_agent_recommendations(agent: str, limit: int = 10) -> list:
    """Get recent recommendations for a specific agent."""
    data = load_scorecards()
    agent_recs = [r for r in data["recommendations"] if r["agent"] == agent]
    # Sort by date descending
    agent_recs.sort(key=lambda r: r["timestamp"], reverse=True)
    return agent_recs[:limit]


def get_leaderboard() -> list:
    """Get agent leaderboard sorted by Sharpe ratio."""
    metrics = calculate_agent_metrics()
    weights = load_weights()

    leaderboard = []
    for agent, m in metrics.items():
        leaderboard.append({
            "agent": agent,
            "weight": weights.get(agent, 1.0),
            "sharpe_10d": m.get("sharpe_10d"),
            "hit_rate_10d": m.get("hit_rate_10d"),
            "avg_return_10d": m.get("avg_return_10d"),
            "total_recommendations": m.get("total_recommendations", 0)
        })

    # Sort by Sharpe ratio (descending, None values last)
    leaderboard.sort(key=lambda x: (x["sharpe_10d"] is None, -(x["sharpe_10d"] or 0)))
    return leaderboard


def run_scorecard_update():
    """Run full scorecard update cycle."""
    print("\n" + "=" * 60)
    print("ATLAS SCORECARD UPDATE")
    print("=" * 60)

    # Update prices
    print("\n[1/3] Updating prices...")
    update_prices()

    # Calculate metrics
    print("\n[2/3] Calculating metrics...")
    metrics = calculate_agent_metrics()

    # Update weights
    print("\n[3/3] Updating weights...")
    weights = update_agent_weights()

    # Show leaderboard
    print("\n" + "-" * 60)
    print("AGENT LEADERBOARD")
    print("-" * 60)
    leaderboard = get_leaderboard()
    for i, entry in enumerate(leaderboard, 1):
        sharpe = entry["sharpe_10d"]
        sharpe_str = f"{sharpe:.3f}" if sharpe else "N/A"
        print(f"{i}. {entry['agent']:<20} | Sharpe: {sharpe_str:<8} | Weight: {entry['weight']:.2f}")

    # Show worst agent
    worst = get_worst_agent()
    if worst:
        print(f"\n[AUTORESEARCH TARGET] {worst[0]} (Sharpe: {worst[1]:.3f}, Weight: {worst[2]:.2f})")

    print("\n" + "=" * 60)
    return metrics, weights


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ATLAS Agent Scorecard System")
    parser.add_argument("--update", action="store_true", help="Run full scorecard update")
    parser.add_argument("--leaderboard", action="store_true", help="Show agent leaderboard")
    parser.add_argument("--worst", action="store_true", help="Show worst performing agent")
    parser.add_argument("--agent", type=str, help="Show recommendations for specific agent")

    args = parser.parse_args()

    if args.update:
        run_scorecard_update()
    elif args.leaderboard:
        for entry in get_leaderboard():
            print(entry)
    elif args.worst:
        worst = get_worst_agent()
        if worst:
            print(f"Worst agent: {worst[0]} (Sharpe: {worst[1]:.3f}, Weight: {worst[2]:.2f})")
        else:
            print("Not enough data to determine worst agent")
    elif args.agent:
        recs = get_agent_recommendations(args.agent)
        for r in recs:
            print(json.dumps(r, indent=2))
    else:
        run_scorecard_update()
