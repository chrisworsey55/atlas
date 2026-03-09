#!/usr/bin/env python3
"""
ATLAS Autoresearch Loop
Inspired by Karpathy's autoresearch — agents improve through market feedback.

The loop:
1. Agent makes recommendations (the "training run")
2. Market gives us the result (the "validation loss")
3. If the agent underperforms, iterate on its prompt
4. If it outperforms, increase its weight in CIO synthesis

Usage:
    python3 -m agents.autoresearch --score        # Score all agents against market
    python3 -m agents.autoresearch --adjust       # Adjust agent weights
    python3 -m agents.autoresearch --analyze      # Analyze worst performer
    python3 -m agents.autoresearch --full         # Run full loop
    python3 -m agents.autoresearch --dashboard    # Print agent leaderboard
"""

import anthropic
import json
import os
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# Paths
STATE_DIR = Path(__file__).parent.parent / "data" / "state"
PROMPTS_DIR = Path(__file__).parent / "prompts"
ITERATIONS_DIR = STATE_DIR / "prompt_iterations"
SCORECARDS_FILE = STATE_DIR / "agent_scorecards.json"
WEIGHTS_FILE = STATE_DIR / "agent_weights.json"
ARCHITECTURE_FILE = STATE_DIR / "atlas_autoresearch_architecture.json"

# Ensure directories exist
ITERATIONS_DIR.mkdir(parents=True, exist_ok=True)

# Anthropic client
client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

# Agent definitions
SUPERINVESTOR_AGENTS = ['druckenmiller', 'aschenbrenner', 'baker', 'ackman']
DESK_AGENTS = ['bond', 'currency', 'commodities', 'metals', 'semiconductor',
               'biotech', 'energy', 'consumer', 'industrials', 'microcap']
RISK_AGENTS = ['cro', 'cio']
ALL_AGENTS = SUPERINVESTOR_AGENTS + DESK_AGENTS + RISK_AGENTS


def load_scorecards() -> Dict:
    """Load agent scorecards from disk."""
    if SCORECARDS_FILE.exists():
        with open(SCORECARDS_FILE) as f:
            return json.load(f)
    return {agent: {
        'recommendations': [],
        'metrics': {
            'total_recommendations': 0,
            'profitable_count': 0,
            'hit_rate_5d': 0.0,
            'hit_rate_10d': 0.0,
            'hit_rate_30d': 0.0,
            'avg_return': 0.0,
            'sharpe_ratio': 0.0,
            'best_call': None,
            'worst_call': None
        }
    } for agent in ALL_AGENTS}


def save_scorecards(scorecards: Dict) -> None:
    """Save agent scorecards to disk."""
    with open(SCORECARDS_FILE, 'w') as f:
        json.dump(scorecards, f, indent=2)


def load_weights() -> Dict[str, float]:
    """Load agent weights from disk."""
    if WEIGHTS_FILE.exists():
        with open(WEIGHTS_FILE) as f:
            return json.load(f)
    return {agent: 1.0 for agent in ALL_AGENTS}


def save_weights(weights: Dict[str, float]) -> None:
    """Save agent weights to disk."""
    weights['last_updated'] = datetime.now().isoformat()
    with open(WEIGHTS_FILE, 'w') as f:
        json.dump(weights, f, indent=2)


def get_price_at_date(ticker: str, date: str) -> Optional[float]:
    """Get price for ticker at specific date from P&L history."""
    history_file = STATE_DIR / "pnl_history.json"
    if not history_file.exists():
        return None

    with open(history_file) as f:
        history = json.load(f)

    for entry in history:
        if entry.get('date') == date:
            positions = entry.get('positions', {})
            if ticker in positions:
                return positions[ticker].get('current')
    return None


def extract_recommendations_from_views(views: Dict, date: str) -> List[Dict]:
    """Extract structured recommendations from agent views."""
    recommendations = []

    for agent_name, view in views.items():
        if agent_name in ['news', 'flow', 'alpha', 'autonomous']:
            continue

        # Parse the view for ticker recommendations
        rec = {
            'agent': agent_name,
            'date': date,
            'raw_view': view[:500],  # First 500 chars
            'tickers': [],
            'direction': None,
            'confidence': None
        }

        # Extract tickers mentioned (basic extraction)
        import re
        ticker_pattern = r'\b([A-Z]{2,5})\b'
        common_words = {'THE', 'AND', 'FOR', 'WITH', 'THIS', 'THAT', 'FROM', 'LONG',
                       'SHORT', 'BUY', 'SELL', 'HOLD', 'RISK', 'WHAT', 'TODAY', 'USD'}

        matches = re.findall(ticker_pattern, view)
        tickers = [t for t in matches if t not in common_words][:5]  # Top 5 tickers
        rec['tickers'] = list(set(tickers))

        # Determine direction from keywords
        view_lower = view.lower()
        if 'buy' in view_lower or 'long' in view_lower or 'bullish' in view_lower:
            rec['direction'] = 'LONG'
        elif 'sell' in view_lower or 'short' in view_lower or 'bearish' in view_lower:
            rec['direction'] = 'SHORT'

        # Extract confidence if mentioned
        confidence_match = re.search(r'(\d{1,3})%', view)
        if confidence_match:
            rec['confidence'] = int(confidence_match.group(1))

        if rec['tickers']:
            recommendations.append(rec)

    return recommendations


def score_recommendations(scorecards: Dict) -> Dict:
    """Score all agent recommendations against market results."""
    print("\nScoring agent recommendations against market results...")

    # Load historical agent views
    views_file = STATE_DIR / "eod_agent_views.json"
    if not views_file.exists():
        print("  No EOD views found. Run an EOD cycle first.")
        return scorecards

    with open(views_file) as f:
        latest_views = json.load(f)

    # Load P&L history for price validation
    history_file = STATE_DIR / "pnl_history.json"
    pnl_history = []
    if history_file.exists():
        with open(history_file) as f:
            pnl_history = json.load(f)

    # Process each agent's recommendations
    date = latest_views.get('date', datetime.now().strftime('%Y-%m-%d'))
    views = latest_views.get('views', {})

    recommendations = extract_recommendations_from_views(views, date)

    for rec in recommendations:
        agent = rec['agent']
        if agent not in scorecards:
            scorecards[agent] = {
                'recommendations': [],
                'metrics': {
                    'total_recommendations': 0,
                    'profitable_count': 0,
                    'hit_rate_5d': 0.0,
                    'hit_rate_10d': 0.0,
                    'hit_rate_30d': 0.0,
                    'avg_return': 0.0,
                    'sharpe_ratio': 0.0,
                    'best_call': None,
                    'worst_call': None
                }
            }

        # Add recommendation to scorecard
        scorecards[agent]['recommendations'].append(rec)
        scorecards[agent]['metrics']['total_recommendations'] += 1

    # Calculate metrics for each agent
    for agent, data in scorecards.items():
        recs = data['recommendations']
        if not recs:
            continue

        # Count profitable recommendations (simplified - needs price data)
        profitable = sum(1 for r in recs if r.get('pnl', 0) > 0)
        total = len(recs)

        data['metrics']['profitable_count'] = profitable
        if total > 0:
            data['metrics']['hit_rate_5d'] = profitable / total

        # Calculate average return
        returns = [r.get('return_pct', 0) for r in recs if r.get('return_pct')]
        if returns:
            data['metrics']['avg_return'] = sum(returns) / len(returns)

            # Sharpe ratio (simplified)
            import statistics
            if len(returns) > 1:
                std = statistics.stdev(returns)
                if std > 0:
                    data['metrics']['sharpe_ratio'] = (data['metrics']['avg_return'] / std)

    save_scorecards(scorecards)
    print(f"  Scored {len(recommendations)} recommendations from {date}")
    return scorecards


def rank_agents_by_performance(scorecards: Dict) -> List[Tuple[str, float]]:
    """Rank agents by risk-adjusted return (Sharpe ratio)."""
    rankings = []
    for agent, data in scorecards.items():
        sharpe = data.get('metrics', {}).get('sharpe_ratio', 0.0)
        rankings.append((agent, sharpe))

    return sorted(rankings, key=lambda x: x[1], reverse=True)


def adjust_weights(scorecards: Dict, weights: Dict[str, float], trading_days: int = 10) -> Dict[str, float]:
    """
    Darwinian agent selection:
    - Positive Sharpe: weight * 1.1
    - Negative Sharpe: weight * 0.9
    - Weight < 0.5: flag for prompt rewrite
    - Weight > 2.0: cap to prevent over-concentration
    """
    print(f"\nAdjusting agent weights (after {trading_days} trading days)...")

    for agent, data in scorecards.items():
        if agent not in weights:
            weights[agent] = 1.0

        sharpe = data.get('metrics', {}).get('sharpe_ratio', 0.0)
        total_recs = data.get('metrics', {}).get('total_recommendations', 0)

        # Only adjust if agent has made recommendations
        if total_recs < 3:
            print(f"  {agent}: insufficient data ({total_recs} recs) - keeping weight {weights[agent]:.2f}")
            continue

        old_weight = weights[agent]

        if sharpe > 0:
            weights[agent] = min(2.0, weights[agent] * 1.1)  # Cap at 2.0
            direction = "+"
        else:
            weights[agent] = weights[agent] * 0.9
            direction = "-"

        # Flag for rewrite if weight drops too low
        flag = ""
        if weights[agent] < 0.5:
            flag = " [FLAG: NEEDS PROMPT REWRITE]"

        print(f"  {agent}: {old_weight:.2f} -> {weights[agent]:.2f} ({direction}) | Sharpe: {sharpe:.3f}{flag}")

    save_weights(weights)
    return weights


def analyze_worst_performer(scorecards: Dict, weights: Dict[str, float]) -> Optional[Dict]:
    """
    Analyze the worst performing agent and generate prompt modification suggestion.
    Returns a prompt iteration suggestion for human review.
    """
    print("\nAnalyzing worst performing agent...")

    rankings = rank_agents_by_performance(scorecards)

    if not rankings:
        print("  No rankings available.")
        return None

    worst_agent, worst_sharpe = rankings[-1]
    print(f"  Worst performer: {worst_agent} (Sharpe: {worst_sharpe:.3f})")

    # Get the agent's failed recommendations
    agent_data = scorecards.get(worst_agent, {})
    recommendations = agent_data.get('recommendations', [])

    # Find losing recommendations
    losers = [r for r in recommendations if r.get('return_pct', 0) < 0 or r.get('pnl', 0) < 0]

    if not losers:
        print(f"  No losing recommendations found for {worst_agent}")
        return None

    # Load current prompt
    prompt_file = PROMPTS_DIR / f"{worst_agent}.md"
    current_prompt = ""
    if prompt_file.exists():
        with open(prompt_file) as f:
            current_prompt = f.read()

    # Generate analysis using Claude
    analysis_prompt = f"""You are an AI hedge fund prompt engineer. Analyze why this agent's recommendations lost money and suggest prompt modifications.

AGENT: {worst_agent}
CURRENT SHARPE RATIO: {worst_sharpe:.3f}

LOSING RECOMMENDATIONS:
{json.dumps(losers[:5], indent=2)}

CURRENT PROMPT:
{current_prompt[:2000]}

Provide:
1. FAILURE ANALYSIS: Why did these recommendations lose money? What pattern do you see?
2. PROMPT WEAKNESSES: What's missing or incorrect in the current prompt?
3. SPECIFIC MODIFICATIONS: Exact text changes to improve the prompt. Be specific - what should be added, removed, or changed?
4. EXPECTED IMPROVEMENT: How will these changes improve future recommendations?

Format your response as structured JSON that can be saved and reviewed."""

    print("  Generating prompt modification suggestion...")

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[{"role": "user", "content": analysis_prompt}]
    )

    suggestion = {
        'agent': worst_agent,
        'date': datetime.now().strftime('%Y-%m-%d'),
        'timestamp': datetime.now().isoformat(),
        'current_sharpe': worst_sharpe,
        'losing_recommendations': losers[:5],
        'analysis': response.content[0].text,
        'status': 'pending_review',
        'reviewed_by': None,
        'approved': None
    }

    # Save suggestion for human review
    iteration_file = ITERATIONS_DIR / f"{worst_agent}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(iteration_file, 'w') as f:
        json.dump(suggestion, f, indent=2)

    print(f"  Suggestion saved to: {iteration_file}")
    return suggestion


def analyze_best_performer(scorecards: Dict) -> Optional[Dict]:
    """
    Document what's working for the best performing agent.
    """
    print("\nAnalyzing best performing agent...")

    rankings = rank_agents_by_performance(scorecards)

    if not rankings:
        print("  No rankings available.")
        return None

    best_agent, best_sharpe = rankings[0]
    print(f"  Best performer: {best_agent} (Sharpe: {best_sharpe:.3f})")

    agent_data = scorecards.get(best_agent, {})
    recommendations = agent_data.get('recommendations', [])

    # Find winning recommendations
    winners = [r for r in recommendations if r.get('return_pct', 0) > 0 or r.get('pnl', 0) > 0]

    analysis = {
        'agent': best_agent,
        'date': datetime.now().strftime('%Y-%m-%d'),
        'sharpe': best_sharpe,
        'total_recommendations': len(recommendations),
        'winning_recommendations': len(winners),
        'hit_rate': len(winners) / len(recommendations) if recommendations else 0,
        'sample_winners': winners[:3],
        'status': 'documented'
    }

    print(f"  Hit rate: {analysis['hit_rate']:.1%}")
    print(f"  Sample winners: {[w.get('tickers', []) for w in winners[:3]]}")

    return analysis


def print_dashboard(scorecards: Dict, weights: Dict[str, float]) -> None:
    """Print agent leaderboard dashboard."""
    print("\n" + "="*80)
    print("ATLAS AUTORESEARCH — AGENT LEADERBOARD")
    print("="*80)

    rankings = rank_agents_by_performance(scorecards)

    print(f"\n{'RANK':<6}{'AGENT':<20}{'WEIGHT':<10}{'SHARPE':<10}{'HIT RATE':<12}{'RECS':<8}{'STATUS'}")
    print("-"*80)

    for i, (agent, sharpe) in enumerate(rankings, 1):
        weight = weights.get(agent, 1.0)
        metrics = scorecards.get(agent, {}).get('metrics', {})
        hit_rate = metrics.get('hit_rate_5d', 0.0)
        total_recs = metrics.get('total_recommendations', 0)

        # Determine status
        if weight < 0.5:
            status = "NEEDS REWRITE"
        elif weight > 1.5:
            status = "HIGH INFLUENCE"
        elif sharpe < -0.5:
            status = "UNDERPERFORMING"
        elif sharpe > 0.5:
            status = "OUTPERFORMING"
        else:
            status = "NORMAL"

        print(f"{i:<6}{agent:<20}{weight:<10.2f}{sharpe:<10.3f}{hit_rate:<12.1%}{total_recs:<8}{status}")

    print("\n" + "-"*80)
    print("WEIGHT LEGEND: <0.5 = needs rewrite | 0.5-1.5 = normal | >1.5 = high influence (capped at 2.0)")
    print("="*80)


def print_prompt_iterations_history() -> None:
    """Print history of prompt iterations."""
    print("\n" + "="*80)
    print("PROMPT ITERATION HISTORY")
    print("="*80)

    iterations = sorted(ITERATIONS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)

    if not iterations:
        print("\nNo prompt iterations yet.")
        return

    print(f"\n{'DATE':<12}{'AGENT':<20}{'SHARPE':<10}{'STATUS':<15}")
    print("-"*60)

    for f in iterations[:10]:  # Last 10
        with open(f) as file:
            data = json.load(file)

        print(f"{data.get('date', 'N/A'):<12}{data.get('agent', 'N/A'):<20}"
              f"{data.get('current_sharpe', 0.0):<10.3f}{data.get('status', 'N/A'):<15}")

    print("\n" + "="*80)


def run_full_loop() -> None:
    """Run the full autoresearch loop."""
    print("\n" + "="*80)
    print(f"ATLAS AUTORESEARCH LOOP — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("="*80)

    # Load current state
    scorecards = load_scorecards()
    weights = load_weights()

    # Step 1: Score recommendations
    scorecards = score_recommendations(scorecards)

    # Step 2: Adjust weights (Darwinian selection)
    weights = adjust_weights(scorecards, weights)

    # Step 3: Analyze worst performer
    worst_analysis = analyze_worst_performer(scorecards, weights)

    # Step 4: Document best performer
    best_analysis = analyze_best_performer(scorecards)

    # Step 5: Print dashboard
    print_dashboard(scorecards, weights)

    # Step 6: Print iteration history
    print_prompt_iterations_history()

    print("\n" + "="*80)
    print("AUTORESEARCH LOOP COMPLETE")
    print("="*80)

    if worst_analysis:
        print(f"\nACTION REQUIRED: Review prompt iteration for {worst_analysis['agent']}")
        print(f"  File: data/state/prompt_iterations/{worst_analysis['agent']}_*.json")
        print(f"\nTo apply changes:")
        print(f"  1. Review the suggestion in the JSON file")
        print(f"  2. Edit agents/prompts/{worst_analysis['agent']}.md")
        print(f"  3. Create a git branch: git checkout -b agent-iteration/{worst_analysis['agent']}-v2")
        print(f"  4. Run a backtest cycle and compare performance")


def create_git_branch_for_iteration(agent: str, version: int = 2) -> str:
    """Create a git branch for prompt iteration testing."""
    branch_name = f"agent-iteration/{agent}-v{version}"
    print(f"\nTo create iteration branch:")
    print(f"  git checkout -b {branch_name}")
    print(f"  # Edit agents/prompts/{agent}.md")
    print(f"  # Run test cycle: python3 -m agents.eod_cycle")
    print(f"  # Compare performance")
    print(f"  # If better: git checkout main && git merge {branch_name}")
    print(f"  # If worse: git checkout main && git branch -D {branch_name}")
    return branch_name


def save_architecture_doc() -> None:
    """Save the architecture documentation."""
    architecture = {
        "name": "ATLAS Autoresearch",
        "version": "1.0",
        "created": datetime.now().isoformat(),
        "inspired_by": "Karpathy's autoresearch loop",
        "concept": {
            "training_run": "Agent makes recommendations",
            "validation_loss": "Market gives us the result (P&L)",
            "gradient_descent": "If agent underperforms, iterate on prompt",
            "learning_rate": "Best agents get weight * 1.1, worst get weight * 0.9"
        },
        "components": {
            "prompts_directory": "agents/prompts/*.md",
            "scorecards": "data/state/agent_scorecards.json",
            "weights": "data/state/agent_weights.json",
            "iterations": "data/state/prompt_iterations/*.json"
        },
        "agents": {
            "superinvestors": SUPERINVESTOR_AGENTS,
            "sector_desks": DESK_AGENTS,
            "risk_decision": RISK_AGENTS
        },
        "darwinian_selection": {
            "starting_weight": 1.0,
            "positive_sharpe_multiplier": 1.1,
            "negative_sharpe_multiplier": 0.9,
            "rewrite_threshold": 0.5,
            "max_weight": 2.0,
            "evaluation_period_days": 10
        },
        "scorecard_metrics": [
            "total_recommendations",
            "profitable_count",
            "hit_rate_5d",
            "hit_rate_10d",
            "hit_rate_30d",
            "avg_return",
            "sharpe_ratio",
            "best_call",
            "worst_call"
        ],
        "iteration_workflow": [
            "1. Run autoresearch --score after EOD cycle",
            "2. Run autoresearch --adjust after 10 trading days",
            "3. Run autoresearch --analyze for worst performer",
            "4. Human reviews prompt suggestion in JSON file",
            "5. Create git branch: agent-iteration/{agent}-v{N}",
            "6. Edit prompt .md file with suggested changes",
            "7. Run backtest cycle",
            "8. If better, merge to main; if worse, delete branch"
        ],
        "goal": "Engineer agents that make the fastest alpha generation progress indefinitely"
    }

    with open(ARCHITECTURE_FILE, 'w') as f:
        json.dump(architecture, f, indent=2)

    print(f"\nArchitecture saved to: {ARCHITECTURE_FILE}")


def initialize_weights() -> None:
    """Initialize all agent weights to 1.0."""
    weights = {agent: 1.0 for agent in ALL_AGENTS}
    weights['initialized'] = datetime.now().isoformat()
    save_weights(weights)
    print(f"Initialized weights for {len(ALL_AGENTS)} agents")


def main():
    parser = argparse.ArgumentParser(description='ATLAS Autoresearch Loop')
    parser.add_argument('--score', action='store_true', help='Score agent recommendations')
    parser.add_argument('--adjust', action='store_true', help='Adjust agent weights')
    parser.add_argument('--analyze', action='store_true', help='Analyze worst performer')
    parser.add_argument('--full', action='store_true', help='Run full loop')
    parser.add_argument('--dashboard', action='store_true', help='Print agent leaderboard')
    parser.add_argument('--history', action='store_true', help='Print prompt iteration history')
    parser.add_argument('--init', action='store_true', help='Initialize weights and scorecards')
    parser.add_argument('--save-arch', action='store_true', help='Save architecture doc')

    args = parser.parse_args()

    if args.init:
        initialize_weights()
        save_architecture_doc()
        return

    if args.save_arch:
        save_architecture_doc()
        return

    scorecards = load_scorecards()
    weights = load_weights()

    if args.score:
        scorecards = score_recommendations(scorecards)
        print_dashboard(scorecards, weights)

    elif args.adjust:
        weights = adjust_weights(scorecards, weights)
        print_dashboard(scorecards, weights)

    elif args.analyze:
        analyze_worst_performer(scorecards, weights)
        analyze_best_performer(scorecards)

    elif args.dashboard:
        print_dashboard(scorecards, weights)

    elif args.history:
        print_prompt_iterations_history()

    elif args.full:
        run_full_loop()

    else:
        # Default: print dashboard
        print_dashboard(scorecards, weights)


if __name__ == '__main__':
    main()
