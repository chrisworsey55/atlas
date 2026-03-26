#!/usr/bin/env python3
"""
ATLAS Autoresearch — Markowitz Optimal Agent Weights

Computes Sharpe-optimal blend of agents using mean-variance optimization.
Takes agent recommendation data from backtests and produces optimal weights
that can be used as a drop-in replacement for data/state/agent_weights.json.

Usage:
    python3 -m autoresearch.markowitz_weights [--min-recs N] [--max-weight W]

Outputs:
    - Console: Formatted weight table with Sharpe ratio
    - autoresearch/results/markowitz_weights.json (agent_weights.json format)
    - autoresearch/results/agent_correlation_matrix.csv
"""

import json
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import numpy as np
from scipy.optimize import minimize

# Paths
STATE_DIR = Path(__file__).parent.parent / "data" / "state"
RESULTS_DIR = Path(__file__).parent / "results"
BACKTEST_DIR = Path(__file__).parent.parent / "data" / "backtest"

# Agent definitions (from attribution.py and prompt_loader.py)
LAYER_1_AGENTS = ["news", "flow"]
LAYER_2_AGENTS = [
    "bond", "currency", "commodities", "metals", "semiconductor",
    "biotech", "energy", "consumer", "industrials", "financials", "microcap"
]
LAYER_3_AGENTS = ["druckenmiller", "aschenbrenner", "baker", "ackman"]
LAYER_4_AGENTS = ["cro", "alpha", "autonomous", "cio"]

# Agents to include in optimization (exclude decision layer)
OPTIMIZABLE_AGENTS = LAYER_1_AGENTS + LAYER_2_AGENTS + LAYER_3_AGENTS


def load_agent_scorecards() -> Dict:
    """Load agent scorecards from data/state/agent_scorecards.json."""
    scorecards_file = STATE_DIR / "agent_scorecards.json"
    if scorecards_file.exists():
        with open(scorecards_file) as f:
            return json.load(f)
    return {}


def load_agent_scores() -> Dict:
    """Load agent scores from autoresearch/results/agent_scores.json."""
    scores_file = RESULTS_DIR / "agent_scores.json"
    if scores_file.exists():
        with open(scores_file) as f:
            return json.load(f)
    return {}


def load_backtest_results() -> List[Dict]:
    """Load all backtest result files from autoresearch/results/."""
    results = []
    for f in sorted(RESULTS_DIR.glob("*_backtest.json")):
        try:
            with open(f) as fp:
                data = json.load(fp)
                results.append(data)
        except (json.JSONDecodeError, IOError):
            continue
    return results


def extract_agent_return_series(min_recommendations: int = 5) -> Dict[str, List[float]]:
    """
    Extract daily return series for each agent.

    Returns dict of {agent_name: [return_1, return_2, ...]}
    where returns are +1 if profitable, -1 if not, 0 if abstained.

    Data sources (in priority order):
    1. agent_scorecards.json - primary source with return_5d data
    2. agent_scores.json - secondary source from attribution
    3. Backtest logs - fallback parsing
    """
    agent_returns: Dict[str, List[float]] = {agent: [] for agent in OPTIMIZABLE_AGENTS}

    # Source 1: agent_scorecards.json
    scorecards = load_agent_scorecards()
    if scorecards:
        recommendations = scorecards.get("recommendations", [])
        # Group by date and agent
        date_agent_returns: Dict[str, Dict[str, float]] = {}

        for rec in recommendations:
            agent = rec.get("agent", "")
            date = rec.get("date", "")[:10]  # YYYY-MM-DD
            return_5d = rec.get("return_5d")

            if agent not in OPTIMIZABLE_AGENTS:
                continue
            if not date:
                continue

            if date not in date_agent_returns:
                date_agent_returns[date] = {}

            # Convert return to signal: +1 profitable, -1 loss, 0 if no data
            if return_5d is not None:
                signal = 1.0 if return_5d > 0 else (-1.0 if return_5d < 0 else 0.0)
                # Use actual return magnitude for better optimization
                signal = return_5d / 100.0  # Convert percentage to decimal
                date_agent_returns[date][agent] = signal

        # Convert to aligned series (all dates, all agents)
        if date_agent_returns:
            sorted_dates = sorted(date_agent_returns.keys())
            for date in sorted_dates:
                for agent in OPTIMIZABLE_AGENTS:
                    ret = date_agent_returns[date].get(agent, 0.0)
                    agent_returns[agent].append(ret)

    # Source 2: agent_scores.json (from attribution)
    scores = load_agent_scores()
    if scores and not any(agent_returns.values()):
        agents_data = scores.get("agents", {})

        for agent in OPTIMIZABLE_AGENTS:
            agent_data = agents_data.get(agent, {})
            recommendations = agent_data.get("recommendations", [])

            for rec in recommendations:
                return_5d = rec.get("return_5d")
                if return_5d is not None:
                    agent_returns[agent].append(return_5d / 100.0)
                elif rec.get("scored"):
                    agent_returns[agent].append(0.0)

    # Source 3: Parse backtest logs for per-recommendation returns
    backtest_results = load_backtest_results()
    if backtest_results and not any(agent_returns.values()):
        for result in backtest_results:
            recs = result.get("recommendations", [])
            for rec in recs:
                return_pct = rec.get("return_pct", 0)
                # Can't attribute to specific agent without more data
                # Skip this source if no agent attribution
                pass

    # Filter agents with insufficient data
    filtered_returns = {}
    for agent, returns in agent_returns.items():
        if len(returns) >= min_recommendations:
            filtered_returns[agent] = returns

    return filtered_returns


def generate_synthetic_returns(n_periods: int = 50) -> Dict[str, List[float]]:
    """
    Generate synthetic agent return series for testing when real data is insufficient.
    Uses agent characteristics to generate plausible correlations.

    This is a fallback when backtest data isn't available.
    """
    np.random.seed(42)  # Reproducibility

    synthetic_returns = {}

    # Define agent characteristics (mean, volatility, skill)
    agent_profiles = {
        # Layer 1 - Data agents (lower alpha, lower vol)
        "news": (0.001, 0.02, 0.48),
        "flow": (0.002, 0.025, 0.52),
        # Layer 2 - Sector desks (varied)
        "bond": (0.003, 0.015, 0.54),
        "currency": (0.001, 0.03, 0.50),
        "commodities": (0.004, 0.035, 0.53),
        "metals": (0.003, 0.04, 0.51),
        "semiconductor": (0.006, 0.045, 0.57),
        "biotech": (0.002, 0.05, 0.49),
        "energy": (0.004, 0.04, 0.52),
        "consumer": (0.003, 0.025, 0.55),
        "industrials": (0.002, 0.03, 0.51),
        "financials": (0.003, 0.035, 0.53),
        "microcap": (0.005, 0.055, 0.50),
        # Layer 3 - Superinvestors (higher alpha potential)
        "druckenmiller": (0.008, 0.04, 0.58),
        "aschenbrenner": (0.007, 0.05, 0.56),
        "baker": (0.006, 0.045, 0.55),
        "ackman": (0.005, 0.04, 0.57),
    }

    # Generate correlated returns using a common factor model
    market_factor = np.random.normal(0, 0.02, n_periods)
    sector_tech = np.random.normal(0, 0.015, n_periods)
    sector_value = np.random.normal(0, 0.015, n_periods)

    tech_agents = ["semiconductor", "biotech", "aschenbrenner", "baker"]
    value_agents = ["ackman", "industrials", "financials", "energy"]

    for agent in OPTIMIZABLE_AGENTS:
        profile = agent_profiles.get(agent, (0.002, 0.03, 0.52))
        mean_ret, vol, hit_rate = profile

        # Base return with market factor
        beta = 0.3 + np.random.uniform(-0.1, 0.2)
        returns = beta * market_factor

        # Add sector factor
        if agent in tech_agents:
            returns += 0.2 * sector_tech
        elif agent in value_agents:
            returns += 0.2 * sector_value

        # Add idiosyncratic component based on skill
        skill_alpha = (hit_rate - 0.5) * 0.01  # Alpha from skill
        idio_noise = np.random.normal(skill_alpha, vol * 0.7, n_periods)
        returns += idio_noise

        synthetic_returns[agent] = list(returns)

    return synthetic_returns


def compute_covariance_matrix(agent_returns: Dict[str, List[float]]) -> Tuple[np.ndarray, List[str]]:
    """
    Compute the covariance matrix across all agent return series.

    Returns:
        cov_matrix: NxN covariance matrix
        agent_names: List of agent names in matrix order
    """
    agent_names = sorted(agent_returns.keys())
    n_agents = len(agent_names)

    # Align series lengths
    min_len = min(len(agent_returns[a]) for a in agent_names)

    # Build return matrix (n_periods x n_agents)
    return_matrix = np.zeros((min_len, n_agents))
    for i, agent in enumerate(agent_names):
        return_matrix[:, i] = agent_returns[agent][:min_len]

    # Compute covariance matrix
    cov_matrix = np.cov(return_matrix, rowvar=False)

    # Handle single-agent case
    if n_agents == 1:
        cov_matrix = np.array([[cov_matrix]])

    return cov_matrix, agent_names


def compute_correlation_matrix(cov_matrix: np.ndarray) -> np.ndarray:
    """Convert covariance matrix to correlation matrix."""
    std_dev = np.sqrt(np.diag(cov_matrix))
    std_dev[std_dev == 0] = 1  # Avoid division by zero
    corr_matrix = cov_matrix / np.outer(std_dev, std_dev)
    return corr_matrix


def compute_expected_returns(agent_returns: Dict[str, List[float]], agent_names: List[str]) -> np.ndarray:
    """Compute expected (mean) returns for each agent."""
    expected = np.zeros(len(agent_names))
    for i, agent in enumerate(agent_names):
        expected[i] = np.mean(agent_returns[agent])
    return expected


def portfolio_sharpe(weights: np.ndarray, expected_returns: np.ndarray,
                     cov_matrix: np.ndarray, risk_free_rate: float = 0.0) -> float:
    """
    Calculate negative Sharpe ratio (negative because we minimize).

    Sharpe = (E[R_p] - R_f) / std(R_p)
    """
    portfolio_return = np.dot(weights, expected_returns)
    portfolio_vol = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))

    if portfolio_vol < 1e-10:
        return 0.0

    sharpe = (portfolio_return - risk_free_rate) / portfolio_vol
    return -sharpe  # Negative for minimization


def optimize_weights(expected_returns: np.ndarray, cov_matrix: np.ndarray,
                    max_weight: float = 0.15, risk_free_rate: float = 0.0) -> np.ndarray:
    """
    Run mean-variance optimization to find Sharpe-optimal weights.

    Constraints:
    - All weights sum to 1
    - No single weight exceeds max_weight (default 15%)
    - No weight below 0.0

    Uses SLSQP solver.
    """
    n_agents = len(expected_returns)

    # Initial guess: equal weights
    initial_weights = np.ones(n_agents) / n_agents

    # Constraints
    constraints = [
        {"type": "eq", "fun": lambda w: np.sum(w) - 1.0}  # Weights sum to 1
    ]

    # Bounds: 0 <= weight <= max_weight
    bounds = [(0.0, max_weight) for _ in range(n_agents)]

    # Optimize
    result = minimize(
        portfolio_sharpe,
        initial_weights,
        args=(expected_returns, cov_matrix, risk_free_rate),
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 1000, "ftol": 1e-10}
    )

    if result.success:
        # Normalize to ensure sum = 1 (numerical precision)
        weights = result.x / np.sum(result.x)
        return weights
    else:
        print(f"[markowitz] Warning: Optimization failed - {result.message}")
        return initial_weights


def save_weights_json(weights: Dict[str, float], output_path: Path):
    """Save weights in agent_weights.json format."""
    output = weights.copy()
    output["initialized"] = datetime.now().isoformat()
    output["last_updated"] = datetime.now().isoformat()

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)


def save_correlation_csv(corr_matrix: np.ndarray, agent_names: List[str], output_path: Path):
    """Save correlation matrix as CSV."""
    with open(output_path, "w") as f:
        # Header
        f.write("," + ",".join(agent_names) + "\n")
        # Rows
        for i, agent in enumerate(agent_names):
            row = [agent] + [f"{corr_matrix[i, j]:.4f}" for j in range(len(agent_names))]
            f.write(",".join(row) + "\n")


def print_results(weights: Dict[str, float], sharpe: float, n_agents_with_weight: int,
                  total_agents: int):
    """Print formatted results to stdout."""
    print("\n" + "=" * 50)
    print("MARKOWITZ OPTIMAL AGENT WEIGHTS")
    print("=" * 50)

    # Sort by weight descending
    sorted_weights = sorted(weights.items(), key=lambda x: x[1], reverse=True)

    for agent, weight in sorted_weights:
        if weight > 0.001:
            print(f"{agent + ':':<20} {weight:.3f}")
        else:
            print(f"{agent + ':':<20} {weight:.3f}  (eliminated)")

    print("-" * 50)
    print(f"Portfolio Sharpe: {sharpe:.2f}")
    print(f"Number of agents with weight > 0: {n_agents_with_weight}/{total_agents}")
    print("=" * 50)


def main():
    parser = argparse.ArgumentParser(description="Compute Markowitz optimal agent weights")
    parser.add_argument("--min-recs", type=int, default=5,
                       help="Minimum recommendations required per agent")
    parser.add_argument("--max-weight", type=float, default=0.15,
                       help="Maximum weight per agent (default: 0.15)")
    parser.add_argument("--use-synthetic", action="store_true",
                       help="Force use of synthetic data for testing")
    args = parser.parse_args()

    print("[markowitz] Loading agent return data...")

    # Extract return series from available data
    if args.use_synthetic:
        agent_returns = generate_synthetic_returns()
        print("[markowitz] Using synthetic return data for testing")
    else:
        agent_returns = extract_agent_return_series(min_recommendations=args.min_recs)

        if len(agent_returns) < 3:
            print(f"[markowitz] Insufficient real data ({len(agent_returns)} agents)")
            print("[markowitz] Falling back to synthetic data")
            agent_returns = generate_synthetic_returns()

    print(f"[markowitz] Loaded return series for {len(agent_returns)} agents")

    # Compute covariance matrix
    print("[markowitz] Computing covariance matrix...")
    cov_matrix, agent_names = compute_covariance_matrix(agent_returns)

    # Compute expected returns
    expected_returns = compute_expected_returns(agent_returns, agent_names)

    # Run optimization
    print(f"[markowitz] Running optimization (max_weight={args.max_weight})...")
    optimal_weights = optimize_weights(expected_returns, cov_matrix,
                                        max_weight=args.max_weight)

    # Calculate portfolio Sharpe
    portfolio_vol = np.sqrt(np.dot(optimal_weights.T, np.dot(cov_matrix, optimal_weights)))
    portfolio_ret = np.dot(optimal_weights, expected_returns)
    portfolio_sharpe = portfolio_ret / portfolio_vol if portfolio_vol > 0 else 0.0
    # Annualize (assuming daily returns, ~252 trading days)
    portfolio_sharpe_annual = portfolio_sharpe * np.sqrt(252)

    # Build weights dict
    weights_dict = {}
    for i, agent in enumerate(agent_names):
        weights_dict[agent] = round(optimal_weights[i], 4)

    # Add zero weight for agents not in optimization
    all_agents = (LAYER_1_AGENTS + LAYER_2_AGENTS + LAYER_3_AGENTS + LAYER_4_AGENTS)
    for agent in all_agents:
        if agent not in weights_dict:
            weights_dict[agent] = 0.0

    # Count agents with weight
    n_with_weight = sum(1 for w in optimal_weights if w > 0.001)

    # Print results
    print_results(weights_dict, portfolio_sharpe_annual, n_with_weight, len(agent_names))

    # Save outputs
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    weights_file = RESULTS_DIR / "markowitz_weights.json"
    save_weights_json(weights_dict, weights_file)
    print(f"\n[markowitz] Saved weights to: {weights_file}")

    corr_matrix = compute_correlation_matrix(cov_matrix)
    corr_file = RESULTS_DIR / "agent_correlation_matrix.csv"
    save_correlation_csv(corr_matrix, agent_names, corr_file)
    print(f"[markowitz] Saved correlation matrix to: {corr_file}")

    return weights_dict, portfolio_sharpe_annual


if __name__ == "__main__":
    main()
