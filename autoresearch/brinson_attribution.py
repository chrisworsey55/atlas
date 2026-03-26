#!/usr/bin/env python3
"""
ATLAS Autoresearch — Brinson-Fachler Attribution

Decomposes ATLAS portfolio performance into:
1. Allocation Effect: Did Layer 1 macro agents correctly identify sectors to overweight/underweight?
2. Selection Effect: Did Layer 2 sector agents pick the right stocks within each sector?
3. Interaction Effect: Combined effect of good allocation AND good selection

Additionally decomposes by ATLAS 4-layer architecture:
- Layer 1 (Macro): news_sentiment, institutional_flow
- Layer 2 (Sector Desks): bond, currency, commodities, metals, semiconductor, biotech, energy, consumer, industrials, microcap
- Layer 3 (Superinvestors): druckenmiller, aschenbrenner, baker, ackman
- Layer 4 (Decision): cro, alpha_discovery, autonomous_execution, cio
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import numpy as np
import pandas as pd

STATE_DIR = Path(__file__).parent.parent / "data" / "state"
RESULTS_DIR = Path(__file__).parent / "results"

# Layer definitions (from eod_cycle.py)
LAYER_1_AGENTS = ["news", "news_sentiment", "flow", "institutional_flow"]
LAYER_2_AGENTS = [
    "bond", "bond_desk", "currency", "currency_desk", "commodities", "commodities_desk",
    "metals", "metals_desk", "semiconductor", "semi_desk", "biotech", "biotech_desk",
    "energy", "energy_desk", "consumer", "consumer_desk", "industrials", "industrials_desk",
    "microcap", "microcap_desk"
]
LAYER_3_AGENTS = ["druckenmiller", "aschenbrenner", "baker", "ackman"]
LAYER_4_AGENTS = ["cro", "alpha", "alpha_discovery", "autonomous", "autonomous_execution", "cio"]

# Sector mapping for tickers (GICS-style)
SECTOR_MAP = {
    # Technology
    "AVGO": "Technology", "AMD": "Technology", "TEAM": "Technology", "ADBE": "Technology",
    "NVDA": "Technology", "MSFT": "Technology", "AAPL": "Technology", "CRM": "Technology",
    "GOOGL": "Technology", "GOOG": "Technology", "META": "Technology",
    # Communication Services (some tech-adjacent)
    "SRAD": "Communication Services",
    # Healthcare
    "UNH": "Healthcare", "HRMY": "Healthcare",
    # Consumer Staples
    "BRBR": "Consumer Staples",
    # Consumer Discretionary
    "AMZN": "Consumer Discretionary", "TSLA": "Consumer Discretionary",
    # Financials
    "APO": "Financials", "JPM": "Financials", "GS": "Financials",
    # Energy
    "XLE": "Energy", "XOM": "Energy", "CVX": "Energy",
    # Industrials
    "RTX": "Industrials", "BA": "Industrials", "CAT": "Industrials",
    # Fixed Income / Rates
    "TLT": "Fixed Income", "IEF": "Fixed Income", "SHY": "Fixed Income",
    # Commodities
    "GLD": "Commodities", "SLV": "Commodities", "USO": "Commodities",
    # Cash
    "BIL": "Cash",
    # Small Cap Index
    "IWM": "Small Cap",
}

# S&P 500 equal-weight sector benchmark returns (placeholder - will compute from actual data)
# In production, would fetch from market data source
SP500_SECTOR_WEIGHTS = {
    "Technology": 0.28,
    "Healthcare": 0.13,
    "Financials": 0.13,
    "Consumer Discretionary": 0.10,
    "Communication Services": 0.09,
    "Industrials": 0.08,
    "Consumer Staples": 0.07,
    "Energy": 0.04,
    "Utilities": 0.03,
    "Real Estate": 0.03,
    "Materials": 0.02,
    "Fixed Income": 0.00,  # Not in S&P 500
    "Commodities": 0.00,   # Not in S&P 500
    "Cash": 0.00,          # Not in S&P 500
    "Small Cap": 0.00,     # Not in S&P 500
}


def get_sector(ticker: str) -> str:
    """Get GICS sector for a ticker."""
    return SECTOR_MAP.get(ticker, "Unknown")


def get_agent_layer(agent_name: str) -> int:
    """Return the layer number (1-4) for an agent."""
    agent_lower = agent_name.lower().replace("_desk", "").replace("_agent", "")
    if agent_lower in [a.lower().replace("_desk", "").replace("_agent", "") for a in LAYER_1_AGENTS]:
        return 1
    elif agent_lower in [a.lower().replace("_desk", "").replace("_agent", "") for a in LAYER_2_AGENTS]:
        return 2
    elif agent_lower in LAYER_3_AGENTS:
        return 3
    elif agent_lower in [a.lower() for a in LAYER_4_AGENTS]:
        return 4
    return 0


def load_positions() -> dict:
    """Load current positions from positions.json."""
    positions_file = STATE_DIR / "positions.json"
    if positions_file.exists():
        with open(positions_file) as f:
            return json.load(f)
    return {"positions": [], "closed_positions": []}


def load_pnl_history() -> list:
    """Load P&L history from pnl_history.json."""
    pnl_file = STATE_DIR / "pnl_history.json"
    if pnl_file.exists():
        with open(pnl_file) as f:
            return json.load(f)
    return []


def load_trade_journal() -> list:
    """Load trade journal for attribution."""
    # Try the monthly file first
    journal_dir = STATE_DIR.parent / "trade_journal"
    trades = []

    # Load all monthly files
    if journal_dir.exists():
        for f in journal_dir.glob("*.json"):
            with open(f) as jf:
                trades.extend(json.load(jf))

    # Also check decisions.json
    decisions_file = STATE_DIR / "decisions.json"
    if decisions_file.exists():
        with open(decisions_file) as f:
            decisions = json.load(f)
            for d in decisions:
                if "ticker" in d and "agent" in d:
                    trades.append(d)

    return trades


def compute_portfolio_sector_weights(positions: list) -> dict:
    """
    Compute portfolio weights by sector from position list.
    Returns dict of {sector: weight} where weights sum to 1.0.
    """
    sector_values = {}
    total_value = 0

    for pos in positions:
        ticker = pos.get("ticker", "")
        shares = pos.get("shares", 0)
        price = pos.get("current_price") or pos.get("entry_price", 0)
        direction = pos.get("direction", "LONG")

        if not ticker or not shares or not price:
            continue

        # Calculate market value (absolute for both long and short)
        market_value = abs(shares * price)
        sector = get_sector(ticker)

        sector_values[sector] = sector_values.get(sector, 0) + market_value
        total_value += market_value

    # Convert to weights
    if total_value == 0:
        return {}

    return {sector: value / total_value for sector, value in sector_values.items()}


def compute_sector_returns(positions: list) -> dict:
    """
    Compute portfolio returns by sector.
    Returns dict of {sector: return_pct}.
    """
    sector_pnl = {}
    sector_cost = {}

    for pos in positions:
        ticker = pos.get("ticker", "")
        shares = pos.get("shares", 0)
        entry_price = pos.get("entry_price", 0)
        current_price = pos.get("current_price", entry_price)
        direction = pos.get("direction", "LONG")

        if not ticker or not shares or not entry_price:
            continue

        sector = get_sector(ticker)

        # Calculate P&L
        if direction == "SHORT":
            pnl = (entry_price - current_price) * shares
        else:
            pnl = (current_price - entry_price) * shares

        cost_basis = entry_price * shares

        sector_pnl[sector] = sector_pnl.get(sector, 0) + pnl
        sector_cost[sector] = sector_cost.get(sector, 0) + cost_basis

    # Convert to returns
    returns = {}
    for sector in sector_pnl:
        if sector_cost.get(sector, 0) > 0:
            returns[sector] = (sector_pnl[sector] / sector_cost[sector]) * 100
        else:
            returns[sector] = 0.0

    return returns


def get_benchmark_sector_returns(start_date: str, end_date: str) -> dict:
    """
    Get benchmark sector returns for the period.

    In production, this would fetch actual S&P 500 sector ETF returns.
    For now, uses placeholder estimates based on broad market.
    """
    # Placeholder: would integrate with market data API
    # Using simplified estimates based on typical sector performance
    return {
        "Technology": 8.5,      # XLK proxy
        "Healthcare": 3.2,      # XLV proxy
        "Financials": 5.1,      # XLF proxy
        "Consumer Discretionary": 4.8,  # XLY proxy
        "Communication Services": 6.2,  # XLC proxy
        "Industrials": 4.0,     # XLI proxy
        "Consumer Staples": 2.1,  # XLP proxy
        "Energy": 7.8,          # XLE proxy
        "Utilities": 1.5,       # XLU proxy
        "Real Estate": 2.0,     # XLRE proxy
        "Materials": 3.5,       # XLB proxy
        "Fixed Income": -2.0,   # TLT proxy (negative in rising rate env)
        "Commodities": 4.5,     # GLD proxy
        "Cash": 0.5,            # BIL proxy
        "Small Cap": 5.0,       # IWM proxy
    }


def brinson_fachler_decomposition(
    portfolio_sector_weights: dict,
    benchmark_sector_weights: dict,
    portfolio_sector_returns: dict,
    benchmark_sector_returns: dict
) -> dict:
    """
    Compute Brinson-Fachler attribution decomposition.

    Allocation Effect = Sum over sectors of:
        (portfolio_sector_weight - benchmark_sector_weight)
        * (benchmark_sector_return - benchmark_total_return)

    Selection Effect = Sum over sectors of:
        benchmark_sector_weight
        * (portfolio_sector_return - benchmark_sector_return)

    Interaction Effect = Sum over sectors of:
        (portfolio_sector_weight - benchmark_sector_weight)
        * (portfolio_sector_return - benchmark_sector_return)
    """
    # Calculate benchmark total return
    benchmark_total_return = sum(
        benchmark_sector_weights.get(s, 0) * benchmark_sector_returns.get(s, 0)
        for s in benchmark_sector_returns
    )

    # Calculate portfolio total return
    portfolio_total_return = sum(
        portfolio_sector_weights.get(s, 0) * portfolio_sector_returns.get(s, 0)
        for s in portfolio_sector_returns
    )

    # Compute effects by sector
    sector_effects = {}
    total_allocation = 0
    total_selection = 0
    total_interaction = 0

    all_sectors = set(portfolio_sector_weights.keys()) | set(benchmark_sector_weights.keys())

    for sector in all_sectors:
        p_weight = portfolio_sector_weights.get(sector, 0)
        b_weight = benchmark_sector_weights.get(sector, 0)
        p_return = portfolio_sector_returns.get(sector, 0)
        b_return = benchmark_sector_returns.get(sector, 0)

        # Allocation effect for this sector
        allocation = (p_weight - b_weight) * (b_return - benchmark_total_return)

        # Selection effect for this sector
        selection = b_weight * (p_return - b_return)

        # Interaction effect for this sector
        interaction = (p_weight - b_weight) * (p_return - b_return)

        sector_effects[sector] = {
            "portfolio_weight": p_weight * 100,
            "benchmark_weight": b_weight * 100,
            "weight_diff": (p_weight - b_weight) * 100,
            "portfolio_return": p_return,
            "benchmark_return": b_return,
            "allocation_effect": allocation,  # Already in percentage points
            "selection_effect": selection,
            "interaction_effect": interaction,
            "total_effect": allocation + selection + interaction
        }

        total_allocation += allocation
        total_selection += selection
        total_interaction += interaction

    active_return = portfolio_total_return - benchmark_total_return

    return {
        "portfolio_return": portfolio_total_return,
        "benchmark_return": benchmark_total_return,
        "active_return": active_return,
        "allocation_effect": total_allocation,  # Already in percentage points
        "selection_effect": total_selection,
        "interaction_effect": total_interaction,
        "sector_decomposition": sector_effects
    }


def compute_layer_contribution(
    positions: list,
    trades: list,
    layer: int
) -> dict:
    """
    Compute contribution of a specific ATLAS layer.

    Methodology: Calculate what portfolio return would have been
    if this layer's input was replaced with equal-weight.
    The difference is that layer's contribution.
    """
    # Get positions attributable to this layer's agents
    layer_agents = {
        1: LAYER_1_AGENTS,
        2: LAYER_2_AGENTS,
        3: LAYER_3_AGENTS,
        4: LAYER_4_AGENTS
    }[layer]

    # Normalize agent names for matching
    layer_agent_names = set()
    for agent in layer_agents:
        layer_agent_names.add(agent.lower())
        layer_agent_names.add(agent.lower().replace("_desk", ""))
        layer_agent_names.add(agent.lower().replace("_agent", ""))

    layer_pnl = 0
    layer_cost = 0
    total_pnl = 0
    total_cost = 0

    for pos in positions:
        ticker = pos.get("ticker", "")
        if ticker == "BIL":  # Skip cash
            continue

        shares = pos.get("shares", 0)
        entry_price = pos.get("entry_price", 0)
        current_price = pos.get("current_price", entry_price)
        direction = pos.get("direction", "LONG")
        agent_source = (pos.get("agent_source") or "").lower()
        agent_attribution = pos.get("agent_attribution", [])

        if not ticker or not shares or not entry_price:
            continue

        # Calculate P&L
        if direction == "SHORT":
            pnl = (entry_price - current_price) * shares
        else:
            pnl = (current_price - entry_price) * shares

        cost_basis = entry_price * shares
        total_pnl += pnl
        total_cost += cost_basis

        # Check if any agent from this layer influenced this position
        position_agents = [agent_source] + [a.lower() for a in agent_attribution]
        layer_influenced = any(
            a.lower().replace("_desk", "").replace("_agent", "") in layer_agent_names
            for a in position_agents if a
        )

        if layer_influenced:
            layer_pnl += pnl
            layer_cost += cost_basis

    # Calculate return contribution
    layer_return_contrib = (layer_pnl / total_cost * 100) if total_cost > 0 else 0
    total_return = (total_pnl / total_cost * 100) if total_cost > 0 else 0

    # Counterfactual: what if this layer's positions were equal-weight?
    # Approximation: the layer's contribution is its return minus an equal-weight benchmark
    # Here we use the layer's actual return as its contribution to alpha

    return {
        "layer": layer,
        "layer_name": {1: "Macro/Data", 2: "Sector Desks", 3: "Superinvestors", 4: "CIO/Decision"}[layer],
        "pnl": round(layer_pnl, 2),
        "cost_basis": round(layer_cost, 2),
        "return_contribution": round(layer_return_contrib, 2),
        "positions_influenced": sum(1 for pos in positions
            if any(a.lower().replace("_desk", "").replace("_agent", "") in layer_agent_names
                   for a in ([pos.get("agent_source", "")] + pos.get("agent_attribution", [])) if a))
    }


def identify_bottleneck(layer_contributions: list) -> dict:
    """
    Identify which layer is the performance bottleneck.
    Returns the worst-performing layer and diagnosis.
    """
    if not layer_contributions:
        return {"layer": None, "diagnosis": "Insufficient data"}

    # Sort by return contribution
    sorted_layers = sorted(layer_contributions, key=lambda x: x["return_contribution"])
    worst = sorted_layers[0]
    best = sorted_layers[-1]

    diagnosis = []

    if worst["return_contribution"] < 0:
        diagnosis.append(f"Layer {worst['layer']} ({worst['layer_name']}) is net negative at {worst['return_contribution']:.1f}%")
        diagnosis.append(f"This layer is destroying alpha generated by other layers.")

    if worst["layer"] == 4:
        diagnosis.append("The CIO/Decision layer is the bottleneck - sizing and timing are hurting returns.")
    elif worst["layer"] == 3:
        diagnosis.append("Superinvestor philosophical overlay is not adding value.")
    elif worst["layer"] == 2:
        diagnosis.append("Sector desk stock picking is underperforming.")
    elif worst["layer"] == 1:
        diagnosis.append("Macro regime identification is incorrect.")

    return {
        "worst_layer": worst["layer"],
        "worst_layer_name": worst["layer_name"],
        "worst_contribution": worst["return_contribution"],
        "best_layer": best["layer"],
        "best_layer_name": best["layer_name"],
        "best_contribution": best["return_contribution"],
        "diagnosis": " ".join(diagnosis) if diagnosis else "All layers contributing positively."
    }


def run_attribution(start_date: str = None, end_date: str = None) -> dict:
    """
    Run full Brinson-Fachler attribution for the specified period.

    Args:
        start_date: Start date in YYYY-MM-DD format (default: portfolio inception)
        end_date: End date in YYYY-MM-DD format (default: today)

    Returns:
        Complete attribution results dict.
    """
    # Set defaults
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    if start_date is None:
        start_date = "2026-03-03"  # Portfolio inception based on data

    # Load data
    positions_data = load_positions()
    pnl_history = load_pnl_history()
    trades = load_trade_journal()

    positions = positions_data.get("positions", [])
    closed_positions = positions_data.get("closed_positions", [])
    all_positions = positions + closed_positions

    # Compute portfolio sector weights and returns
    portfolio_sector_weights = compute_portfolio_sector_weights(positions)
    portfolio_sector_returns = compute_sector_returns(all_positions)

    # Get benchmark data
    benchmark_sector_weights = SP500_SECTOR_WEIGHTS
    benchmark_sector_returns = get_benchmark_sector_returns(start_date, end_date)

    # Run Brinson-Fachler decomposition
    bf_results = brinson_fachler_decomposition(
        portfolio_sector_weights,
        benchmark_sector_weights,
        portfolio_sector_returns,
        benchmark_sector_returns
    )

    # Compute layer contributions
    layer_contributions = []
    for layer in [1, 2, 3, 4]:
        contrib = compute_layer_contribution(all_positions, trades, layer)
        layer_contributions.append(contrib)

    # Identify bottleneck
    bottleneck = identify_bottleneck(layer_contributions)

    # Calculate total portfolio P&L
    total_pnl = 0
    total_cost = 0
    for pos in all_positions:
        if pos.get("ticker") == "BIL":
            continue
        shares = pos.get("shares", 0)
        entry = pos.get("entry_price", 0)
        current = pos.get("current_price", entry)
        direction = pos.get("direction", "LONG")

        if shares and entry:
            if direction == "SHORT":
                total_pnl += (entry - current) * shares
            else:
                total_pnl += (current - entry) * shares
            total_cost += entry * shares

    # Include realized P&L from closed positions
    for pos in closed_positions:
        realized = pos.get("realized_pnl", 0)
        total_pnl += realized

    portfolio_return_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0

    # Build results
    results = {
        "period": {
            "start_date": start_date,
            "end_date": end_date,
            "generated_at": datetime.now().isoformat()
        },
        "summary": {
            "portfolio_return": round(portfolio_return_pct, 2),
            "benchmark_return": round(bf_results["benchmark_return"], 2),
            "active_return": round(portfolio_return_pct - bf_results["benchmark_return"], 2),
            "total_pnl": round(total_pnl, 2)
        },
        "brinson_fachler": {
            "allocation_effect": round(bf_results["allocation_effect"], 2),
            "selection_effect": round(bf_results["selection_effect"], 2),
            "interaction_effect": round(bf_results["interaction_effect"], 2),
            "sector_decomposition": bf_results["sector_decomposition"]
        },
        "layer_attribution": {
            "layer_1_macro": next((l for l in layer_contributions if l["layer"] == 1), {}),
            "layer_2_sector_desks": next((l for l in layer_contributions if l["layer"] == 2), {}),
            "layer_3_superinvestors": next((l for l in layer_contributions if l["layer"] == 3), {}),
            "layer_4_cio_decision": next((l for l in layer_contributions if l["layer"] == 4), {}),
        },
        "bottleneck_analysis": bottleneck,
        "positions_analyzed": len(all_positions),
        "trades_analyzed": len(trades)
    }

    return results


def save_results(results: dict, filename: str = None):
    """Save attribution results to JSON file."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if filename is None:
        filename = f"brinson_attribution.json"

    output_path = RESULTS_DIR / filename
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    return output_path


def print_attribution_report(results: dict):
    """Print formatted attribution report to console."""
    print("\n" + "=" * 70)
    print("BRINSON-FACHLER ATTRIBUTION")
    print("=" * 70)
    print(f"Period: {results['period']['start_date']} to {results['period']['end_date']}")
    print()

    summary = results["summary"]
    print(f"Portfolio Return: {summary['portfolio_return']:+.1f}%")
    print(f"Benchmark Return: {summary['benchmark_return']:+.1f}%")
    print(f"Active Return:    {summary['active_return']:+.1f}%")
    print(f"Total P&L:        ${summary['total_pnl']:,.2f}")
    print()

    print("Decomposition:")
    bf = results["brinson_fachler"]
    print(f"  Allocation Effect:   {bf['allocation_effect']:+.1f}%  (macro regime calls)")
    print(f"  Selection Effect:    {bf['selection_effect']:+.1f}%  (stock picking)")
    print(f"  Interaction Effect:  {bf['interaction_effect']:+.1f}%  (sizing/timing)")
    print()

    print("Layer Attribution:")
    la = results["layer_attribution"]
    for key in ["layer_1_macro", "layer_2_sector_desks", "layer_3_superinvestors", "layer_4_cio_decision"]:
        layer = la.get(key, {})
        name = layer.get("layer_name", key)
        contrib = layer.get("return_contribution", 0)
        positions = layer.get("positions_influenced", 0)
        marker = " <-- BOTTLENECK" if contrib == results["bottleneck_analysis"].get("worst_contribution") and contrib < 0 else ""
        print(f"  Layer {layer.get('layer', '?')} ({name}): {contrib:+.1f}% ({positions} positions){marker}")
    print()

    print("Finding:")
    print(f"  {results['bottleneck_analysis']['diagnosis']}")
    print()

    # Sector breakdown
    print("Sector Decomposition:")
    print(f"  {'Sector':<25} {'Port Wt':>8} {'Bench Wt':>8} {'Alloc':>8} {'Select':>8} {'Total':>8}")
    print("  " + "-" * 65)

    for sector, data in sorted(
        results["brinson_fachler"]["sector_decomposition"].items(),
        key=lambda x: abs(x[1]["total_effect"]),
        reverse=True
    ):
        if abs(data["portfolio_weight"]) > 0.1 or abs(data["benchmark_weight"]) > 0.1:
            print(f"  {sector:<25} {data['portfolio_weight']:>7.1f}% {data['benchmark_weight']:>7.1f}% "
                  f"{data['allocation_effect']:>+7.1f}% {data['selection_effect']:>+7.1f}% "
                  f"{data['total_effect']:>+7.1f}%")

    print("=" * 70)


def main():
    """Run attribution and print/save results."""
    print("Running Brinson-Fachler Attribution Analysis...")

    results = run_attribution()

    # Print report
    print_attribution_report(results)

    # Save results
    output_path = save_results(results)
    print(f"\nResults saved to: {output_path}")

    return results


if __name__ == "__main__":
    main()
