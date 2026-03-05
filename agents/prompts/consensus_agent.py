"""
Consensus Agent Prompt
Meta-analyst that analyzes what other analysts think.

Your job is to find the gap between consensus expectations and reality.
That gap is where alpha lives.
"""
import json
from typing import Optional, Dict, List

SYSTEM_PROMPT = """You are a meta-analyst at a top hedge fund.

You don't generate your own estimates — you analyze what OTHER analysts think, and more importantly, where they're WRONG. Your job is to find the gap between consensus expectations and reality. That gap is where alpha lives.

You're skeptical of consensus. When everyone agrees, ask why. When estimates are rising, ask if they're rising fast enough. When a stock has 100% buy ratings, that's a red flag, not a green one.

## Your Framework

### 1. Consensus Snapshot
- How many analysts cover the stock?
- What's the buy/hold/sell distribution?
- Where is the average price target?
- What's the range from low to high target?

### 2. Estimate Revisions
This is one of the MOST predictive signals:
- Are EPS estimates going UP or DOWN over 30/60/90 days?
- Are revenue estimates rising or falling?
- RISING estimates = positive momentum, analysts underestimating
- FALLING estimates = negative momentum, analysts capitulating

### 3. ATLAS vs Consensus
Compare our fundamental valuation to analyst targets:
- If ATLAS says $385 and consensus says $340, we're MORE BULLISH than the street
- If consensus says $400 and ATLAS says $385, we're CLOSE to consensus (less edge)
- The BIGGER the disagreement, the bigger the potential edge

### 4. Earnings Surprise History
Does this company consistently beat or miss?
- 8 beats in a row = "beat and raise" muscle memory
- Management guides conservatively then beats = different animal
- History of misses = set bar low expectations

### 5. Crowding Assessment
If 95% of analysts say "buy," the stock is CROWDED:
- Everyone's already in
- Any disappointment causes violent selling
- Room for upgrades is limited
If only 40% say buy, there's room for positive re-rating.

### 6. Contrarian Signals
Where does ATLAS disagree most with consensus?
- These are potential opportunities
- Being contrarian alone isn't enough — you need a REASON to disagree

## Output Format

Respond with valid JSON:

```json
{
  "ticker": "AVGO",
  "analyst_count": 38,
  "consensus_rating": "STRONG_BUY|BUY|HOLD|SELL|STRONG_SELL",
  "buy_hold_sell": {
    "buy": 32,
    "hold": 5,
    "sell": 1
  },
  "buy_pct": 84.2,
  "price_target": {
    "mean": 365,
    "median": 360,
    "low": 280,
    "high": 440
  },
  "current_price": 340,
  "upside_to_target_pct": 7.4,
  "atlas_vs_consensus": {
    "atlas_intrinsic": 385,
    "consensus_target": 365,
    "atlas_position": "MORE_BULLISH|MORE_BEARISH|ALIGNED",
    "divergence_pct": 5.5,
    "edge_assessment": "Small edge — we're slightly above consensus. Not a contrarian trade."
  },
  "estimate_revisions": {
    "eps_current_q_30d": "+3.2%",
    "eps_next_q_30d": "+1.8%",
    "revenue_current_q_30d": "+2.1%",
    "direction": "IMPROVING|STABLE|DETERIORATING",
    "interpretation": "Estimates are rising — analysts are catching up to reality"
  },
  "earnings_history": {
    "beat_rate_8q": 87.5,
    "avg_surprise_pct": 4.2,
    "pattern": "CONSISTENT_BEATER|MIXED|UNDERPERFORMER",
    "interpretation": "Management guides conservatively then beats — trust the pattern"
  },
  "crowding": {
    "buy_pct": 84.2,
    "assessment": "CROWDED|MODERATELY_CROWDED|BALANCED|UNLOVED",
    "risk": "High buy ratio but not extreme. Some room for upgrades.",
    "positioning_risk": "If earnings disappoint, crowded positioning means violent selloff"
  },
  "recent_changes": [
    {
      "date": "2026-03-02",
      "firm": "RBC Capital",
      "action": "Lowered target $370→$340",
      "note": "Cautious into earnings"
    }
  ],
  "contrarian_opportunity": {
    "is_contrarian": false,
    "atlas_edge": "Small — we're close to consensus, not contrarian here",
    "potential_catalyst": "Earnings beat could trigger upgrade cycle"
  },
  "signal": "BULLISH|BEARISH|NEUTRAL",
  "confidence": 0.0-1.0,
  "verdict": "One paragraph: Consensus is bullish but not extreme. Estimate revisions are positive. Our ATLAS valuation is slightly above consensus, so we're not being contrarian here — we're riding momentum. The risk is the crowded positioning if earnings disappoint.",
  "brief_for_cio": "50-word max executive summary for portfolio decisions"
}
```
"""


def build_analysis_prompt(
    ticker: str,
    consensus_data: Dict,
    estimate_revisions: Dict,
    earnings_history: Dict,
    rating_changes: List[Dict],
    atlas_valuation: Optional[Dict] = None,
    portfolio_position: Optional[Dict] = None,
) -> str:
    """
    Build the user prompt for consensus analysis.

    Args:
        ticker: Stock ticker symbol
        consensus_data: Consensus snapshot from ConsensusClient
        estimate_revisions: Revision data from ConsensusClient
        earnings_history: Beat/miss history from ConsensusClient
        rating_changes: Recent rating changes
        atlas_valuation: ATLAS fundamental valuation (if available)
        portfolio_position: Current position in portfolio (if any)

    Returns:
        Formatted user prompt string
    """
    parts = []

    # Header
    parts.append(f"# Consensus Analysis: {ticker}")
    parts.append(f"Company: {consensus_data.get('company_name', ticker)}")
    parts.append(f"Sector: {consensus_data.get('sector', 'Unknown')}")
    parts.append("")

    # Consensus snapshot
    parts.append("## Wall Street Consensus")
    parts.append(f"Analyst Count: {consensus_data.get('analyst_count', 'N/A')}")
    parts.append(f"Consensus Rating: {consensus_data.get('consensus_rating', 'N/A')}")
    parts.append(f"Buy %: {consensus_data.get('buy_pct', 'N/A')}%")

    rating_dist = consensus_data.get("rating_distribution", {})
    if rating_dist:
        parts.append(f"Distribution: Strong Buy={rating_dist.get('strong_buy', 0)}, "
                    f"Buy={rating_dist.get('buy', 0)}, Hold={rating_dist.get('hold', 0)}, "
                    f"Sell={rating_dist.get('sell', 0)}, Strong Sell={rating_dist.get('strong_sell', 0)}")

    parts.append("")

    # Price targets
    parts.append("## Price Targets")
    parts.append(f"Current Price: ${consensus_data.get('current_price', 'N/A')}")
    targets = consensus_data.get("price_target", {})
    parts.append(f"Target Mean: ${targets.get('mean', 'N/A')}")
    parts.append(f"Target Low: ${targets.get('low', 'N/A')}")
    parts.append(f"Target High: ${targets.get('high', 'N/A')}")
    parts.append(f"Upside to Mean Target: {consensus_data.get('upside_to_target_pct', 'N/A')}%")
    parts.append("")

    # ATLAS valuation comparison
    if atlas_valuation:
        parts.append("## ATLAS Fundamental Valuation (Internal)")
        dcf = atlas_valuation.get("dcf_valuation", {})
        parts.append(f"DCF Base Case: ${dcf.get('base_case', 'N/A')}")
        parts.append(f"DCF Bull Case: ${dcf.get('bull_case', 'N/A')}")
        parts.append(f"DCF Bear Case: ${dcf.get('bear_case', 'N/A')}")

        triangulated = atlas_valuation.get("triangulated_valuation", {})
        parts.append(f"Triangulated Fair Value: ${triangulated.get('fair_value', 'N/A')}")
        parts.append(f"ATLAS Signal: {triangulated.get('signal', 'N/A')}")
        parts.append("")
        parts.append("Use this to compare ATLAS view vs consensus view.")
        parts.append("")

    # Estimate revisions
    parts.append("## Estimate Revisions")
    parts.append(f"30-Day Revision Trend: {estimate_revisions.get('revision_trend', 'N/A')}")
    parts.append(f"Upgrades (30d): {estimate_revisions.get('upgrades_30d', 'N/A')}")
    parts.append(f"Downgrades (30d): {estimate_revisions.get('downgrades_30d', 'N/A')}")

    eps_data = estimate_revisions.get("eps_current_q", {})
    if eps_data:
        parts.append(f"Current Q EPS Estimate: ${eps_data.get('avg', 'N/A')} "
                    f"(range: ${eps_data.get('low', 'N/A')} - ${eps_data.get('high', 'N/A')})")
    parts.append("")

    # Earnings history
    parts.append("## Earnings Surprise History")
    parts.append(f"Beat Rate: {earnings_history.get('beat_rate', 'N/A')}%")
    parts.append(f"Pattern: {earnings_history.get('pattern', 'N/A')}")
    parts.append(f"Average Surprise: {earnings_history.get('average_surprise_pct', 'N/A')}%")

    history = earnings_history.get("history", [])
    if history:
        parts.append("Recent Quarters:")
        for h in history[:4]:
            beat_str = "BEAT" if h.get("beat") else "MISS" if h.get("beat") is not None else "N/A"
            parts.append(f"  {h.get('date')}: EPS ${h.get('eps_actual', 'N/A')} vs ${h.get('eps_estimate', 'N/A')} ({beat_str})")
    parts.append("")

    # Recent rating changes
    if rating_changes:
        parts.append("## Recent Rating Changes (30 days)")
        for change in rating_changes[:10]:
            parts.append(f"  {change.get('date')} | {change.get('firm', 'N/A')}: {change.get('action')} → {change.get('to_grade')}")
        parts.append("")

    # Current position
    if portfolio_position:
        parts.append("## Current ATLAS Position")
        parts.append(f"Direction: {portfolio_position.get('direction', 'N/A')}")
        parts.append(f"Shares: {portfolio_position.get('shares', 'N/A')}")
        parts.append(f"Entry Price: ${portfolio_position.get('entry_price', 'N/A')}")
        parts.append(f"Current P&L: ${portfolio_position.get('unrealized_pnl', 'N/A')}")
        parts.append("")

    # Analysis instruction
    parts.append("---")
    parts.append("")
    parts.append("Analyze this consensus data as a meta-analyst.")
    parts.append("Focus on:")
    parts.append("1. Where does consensus stand? Is it crowded?")
    parts.append("2. Are estimates rising or falling? (momentum)")
    parts.append("3. Does ATLAS agree or disagree with consensus?")
    parts.append("4. Is there a contrarian opportunity here?")
    parts.append("5. What's the earnings surprise history tell us?")
    parts.append("")
    parts.append("Respond with JSON only.")

    return "\n".join(parts)


# Chat prompt for conversational mode
CONSENSUS_CHAT_PROMPT = """You are the ATLAS Consensus Agent having a conversation.

You are a meta-analyst. You analyze what other analysts think, and more importantly, where they're WRONG. Your job is to find the gap between consensus expectations and reality.

When discussing consensus:
- Cite specific numbers: analyst counts, buy %, price targets
- Compare ATLAS valuation to consensus view
- Highlight estimate revision trends
- Flag crowding risks
- Identify contrarian opportunities

You're skeptical of consensus. When everyone agrees, you ask why.

Your latest analysis is provided. Use it to ground your responses."""
