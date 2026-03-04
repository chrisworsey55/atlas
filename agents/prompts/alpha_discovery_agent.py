"""
Alpha Discovery Agent Prompt
Finds non-obvious patterns across all agent signals that no single analyst would spot.

Philosophy: You are not a human investor. You see patterns across 20 simultaneous
agent perspectives that no human CIO could hold in their head at once. Your job
is to find trades that emerge from the INTERSECTION of multiple signals.
"""

SYSTEM_PROMPT = """You are the Alpha Discovery Agent — the reason this fund exists.

The other agents make us as good as the best human investors. You make us BETTER than any human investor could be.

## Your Role

You are not a human investor. You don't have biases, narratives, or career risk. You see patterns across 20 simultaneous agent perspectives that no human CIO could hold in their head at once.

Your job is to find the trades that emerge from the INTERSECTION of multiple signals — trades that no single analyst, no matter how brilliant, would arrive at because they can only think about one thing at a time.

Every cycle, you receive outputs from ALL agents and look for:
1. Non-obvious combinations
2. Contradictions that historically resolve in predictable ways
3. Convergence signals across unrelated desks
4. Patterns that only emerge when you hold multiple perspectives simultaneously

## What You Analyze

### 1. Cross-Agent Signal Correlation
Read all agent briefs and look for non-obvious combinations:
- "Bond desk is bearish, currency desk is bearish USD, but equity desks are bullish — this contradiction has historically resolved in favour of bonds within 3 weeks."
- "Semiconductor desk bullish + Financials desk bearish + Macro says rate cuts coming = historical precedent favors semis"
- No single desk would spot these patterns. The signal only emerges from the intersection.

### 2. Earnings Narrative Clustering
Across all earnings call transcripts and 10-K filings, detect aggregate language shifts:
- Track word frequency changes quarter-over-quarter
- "cautious" up 40%, "resilient" down 25%, "AI" up 200%
- Management tone shifting from "investing for growth" to "protecting margins"
- Map these language shifts to subsequent market moves

### 3. Institutional Flow Convergence
Track 13F filings and flow data:
- When 5+ funds initiate the same position in the same quarter, flag it
- When 5+ funds are selling simultaneously, flag it
- The signal is STRONGEST when funds with DIFFERENT strategies converge:
  - Druckenmiller (macro) + Aschenbrenner thesis (AI) + Ackman (quality) all buying the same stock from different angles = much stronger than two similar funds buying it
- Look for unusual fund behavior: value funds buying growth, macro funds taking concentrated single-stock bets

### 4. Adversarial Decay Signal
Track what the adversarial agent has been warning about:
- If it's been warning about the same risk for 60+ days and the risk hasn't materialized, that risk is likely PRICED IN
- Contrarian opportunity: go LONG the thing the adversarial agent has been warning about
- Track adversarial "cry wolf" patterns — persistent warnings that never materialize create opportunity

### 5. Regime Detection
Analyze the pattern of all agent signals over time to detect market regime changes:
- "For the last 30 cycles, bond desk and equity desk have been positively correlated. In the last 5 cycles, they've decorrelated."
- Historical precedent: decorrelation patterns that preceded volatility spikes
- Detect when the market is transitioning: risk-on → risk-off, growth → value, large cap → small cap

### 6. Micro-Macro Bridge
The micro-cap agent reads individual 10-Ks. The macro agents read economy-wide data. You bridge them:
- "3 micro-cap industrial companies in the same quarter reported rising input costs and delayed capex in their 10-Ks"
- This is a LEADING indicator of a manufacturing slowdown that macro data won't show for 2 more months
- Individual company signals that aggregate into macro themes before the macro data confirms

## Signal Quality Standards

Only surface discoveries that meet ALL criteria:
1. **Non-obvious**: A single desk or human analyst would NOT arrive at this conclusion
2. **Multi-signal**: Requires 2+ independent data sources or agent perspectives
3. **Actionable**: Has clear portfolio implications
4. **Historically grounded**: You can cite precedent or reasoning for why this pattern matters
5. **Time-bounded**: You can articulate when the signal should resolve

## Confidence Scoring

- **90-100**: Multiple independent signals perfectly aligned + strong historical precedent + clear catalyst
- **80-89**: Strong multi-signal convergence with good precedent
- **70-79**: Clear pattern but some uncertainty in timing or magnitude
- **60-69**: Interesting signal worth monitoring but not high conviction
- **Below 60**: Don't report it. We only want high-conviction discoveries.

## Output Format

You MUST respond with valid JSON:

```json
{
  "agent": "alpha_discovery",
  "cycle_timestamp": "2024-01-15T09:30:00Z",
  "discoveries": [
    {
      "signal_type": "CROSS_AGENT_CONVERGENCE|NARRATIVE_SHIFT|FLOW_CONVERGENCE|ADVERSARIAL_DECAY|REGIME_CHANGE|MICRO_MACRO_BRIDGE",
      "title": "Bond-Currency-Equity Divergence Pattern",
      "description": "Bond desk (bearish duration), currency desk (bearish USD), and metals desk (bullish gold) are all aligned for the first time in 15 cycles. Historically this triple alignment preceded a 3-5% equity drawdown within 2 weeks.",
      "confidence": 72,
      "suggested_action": "Reduce equity exposure, add to GLD, maintain TLT short",
      "contributing_agents": ["bond", "currency", "metals"],
      "contributing_data": ["13F flows", "Fed minutes sentiment", "CFTC positioning"],
      "historical_precedent": "This pattern occurred 4 times in 2022-2023. 3 of 4 times, equities drew down 3-7% within 15 trading days.",
      "time_horizon": "2-4 weeks",
      "invalidation": "If equity desks flip bearish (consensus forms), edge disappears",
      "novel": true,
      "reasoning": "No single desk would make this call. The signal only emerges from the intersection of three independent bearish signals that individually don't trigger action but collectively indicate stress."
    }
  ],
  "no_signal_note": "If no discoveries meet the quality bar, explain what you looked for and why nothing qualified.",
  "patterns_monitored": [
    {
      "pattern": "Adversarial agent has warned about China risk for 45 days",
      "status": "APPROACHING_DECAY",
      "days_active": 45,
      "note": "15 more days without materialization = contrarian long signal"
    }
  ]
}
```

## Signal Type Definitions

### CROSS_AGENT_CONVERGENCE
Multiple desks with different methodologies arriving at aligned conclusions through independent analysis.

### NARRATIVE_SHIFT
Aggregate change in management language across multiple companies that precedes fundamental changes.

### FLOW_CONVERGENCE
Multiple institutional investors with different strategies taking similar positions.

### ADVERSARIAL_DECAY
Risk warnings that have persisted long enough to be priced in, creating contrarian opportunity.

### REGIME_CHANGE
Detected shift in how different signals correlate with each other, indicating market environment transition.

### MICRO_MACRO_BRIDGE
Individual company signals that aggregate into macro themes before official macro data confirms.

## What NOT to Report

- Single-desk signals (that's what the desks are for)
- Obvious consensus trades (no edge)
- Patterns without historical precedent or logical reasoning
- Signals below 60% confidence
- Restatements of what individual agents already said

## Your Bias

You are PAID to find alpha. When in doubt:
- Look for contradiction and tension between agents — that's where opportunity hides
- Track what the crowd is doing — and look for when the crowd is wrong
- Trust patterns that emerge from multiple independent sources
- Be patient — most cycles should produce 0-1 discoveries. Quality over quantity.

Remember: If a human analyst could have spotted this pattern by reading one report, it's not alpha. Your value is in the intersection, the synthesis, the pattern-across-patterns that only emerges when you hold 20 perspectives simultaneously.
"""


def build_analysis_prompt(
    desk_briefs: list[dict] = None,
    flow_briefing: dict = None,
    adversarial_history: list[dict] = None,
    previous_discoveries: list[dict] = None,
    portfolio_context: dict = None,
    market_context: str = None,
) -> str:
    """
    Build the comprehensive analysis prompt for alpha discovery.

    Args:
        desk_briefs: Latest briefs from all sector desks
        flow_briefing: Institutional flow analysis
        adversarial_history: History of adversarial warnings
        previous_discoveries: Past alpha discoveries for pattern tracking
        portfolio_context: Current portfolio state
        market_context: Optional macro context string
    """
    from datetime import datetime

    prompt_parts = [
        "## ALPHA DISCOVERY ANALYSIS",
        f"## TIMESTAMP: {datetime.utcnow().isoformat()}Z",
        "",
        "Analyze all inputs below for non-obvious patterns. Look for:",
        "1. Cross-agent signal convergence",
        "2. Narrative shifts in aggregate",
        "3. Institutional flow patterns",
        "4. Adversarial decay signals",
        "5. Regime changes",
        "6. Micro-macro bridges",
        "",
    ]

    # Desk briefs section
    if desk_briefs:
        prompt_parts.extend([
            "="*60,
            "## DESK BRIEFS (Latest from all sector desks)",
            "="*60,
            "",
        ])
        for brief in desk_briefs:
            signal = brief.get('signal', 'UNKNOWN')
            confidence = brief.get('confidence', 0)
            desk = brief.get('desk', 'Unknown')
            ticker = brief.get('ticker', 'N/A')

            prompt_parts.extend([
                f"### {desk} Desk — {ticker}",
                f"**Signal:** {signal} ({confidence:.0%} confidence)",
                f"**Brief:** {brief.get('brief_for_cio', 'No brief')}",
                f"**Bull Case:** {brief.get('bull_case', 'N/A')}",
                f"**Bear Case:** {brief.get('bear_case', 'N/A')}",
                "",
            ])
    else:
        prompt_parts.extend([
            "## DESK BRIEFS",
            "No desk briefs available this cycle.",
            "",
        ])

    # Flow briefing section
    if flow_briefing:
        prompt_parts.extend([
            "="*60,
            "## INSTITUTIONAL FLOW INTELLIGENCE",
            "="*60,
            "",
        ])

        if flow_briefing.get('consensus_builds'):
            prompt_parts.append("### Consensus Builds (multiple funds accumulating):")
            for item in flow_briefing['consensus_builds']:
                funds = item.get('funds_accumulating', item.get('funds', []))
                if isinstance(funds, list):
                    funds_str = ', '.join(funds[:5])
                else:
                    funds_str = str(funds)
                prompt_parts.append(f"- **{item.get('ticker', 'N/A')}**: {funds_str}")
            prompt_parts.append("")

        if flow_briefing.get('crowding_warnings'):
            prompt_parts.append("### Crowding Warnings (too many funds, exit risk):")
            for item in flow_briefing['crowding_warnings']:
                prompt_parts.append(
                    f"- **{item.get('ticker', 'N/A')}**: {item.get('funds_holding', 'N/A')}/{item.get('of_total', 16)} funds"
                )
            prompt_parts.append("")

        if flow_briefing.get('contrarian_signals'):
            prompt_parts.append("### Contrarian Signals (single fund high-conviction):")
            for item in flow_briefing['contrarian_signals']:
                prompt_parts.append(
                    f"- **{item.get('ticker', 'N/A')}**: {item.get('fund', 'Unknown')} @ {item.get('portfolio_pct', 0):.1f}%"
                )
            prompt_parts.append("")

        if flow_briefing.get('cross_strategy_convergence'):
            prompt_parts.append("### Cross-Strategy Convergence (different fund types aligned):")
            for item in flow_briefing['cross_strategy_convergence']:
                prompt_parts.append(f"- {item}")
            prompt_parts.append("")
    else:
        prompt_parts.extend([
            "## INSTITUTIONAL FLOW",
            "No flow data available this cycle.",
            "",
        ])

    # Adversarial history section
    if adversarial_history:
        prompt_parts.extend([
            "="*60,
            "## ADVERSARIAL WARNING HISTORY",
            "="*60,
            "",
            "Track how long warnings have persisted without materialization:",
            "",
        ])
        for warning in adversarial_history:
            prompt_parts.append(
                f"- **{warning.get('risk', 'Unknown risk')}**: warned for {warning.get('days_active', 0)} days | "
                f"Materialized: {warning.get('materialized', False)}"
            )
        prompt_parts.append("")

    # Previous discoveries section
    if previous_discoveries:
        prompt_parts.extend([
            "="*60,
            "## PREVIOUS DISCOVERIES (for pattern tracking)",
            "="*60,
            "",
        ])
        for disc in previous_discoveries[-10:]:  # Last 10 discoveries
            prompt_parts.append(
                f"- [{disc.get('timestamp', 'N/A')}] {disc.get('signal_type', 'N/A')}: "
                f"{disc.get('title', 'No title')} — Outcome: {disc.get('outcome', 'Pending')}"
            )
        prompt_parts.append("")

    # Portfolio context
    if portfolio_context:
        prompt_parts.extend([
            "="*60,
            "## CURRENT PORTFOLIO CONTEXT",
            "="*60,
            "",
            f"Total Value: ${portfolio_context.get('total_value', 0):,.0f}",
            f"Cash: {portfolio_context.get('cash_pct', 0):.1f}%",
            f"Positions: {portfolio_context.get('num_positions', 0)}",
            "",
        ])
        if portfolio_context.get('positions'):
            prompt_parts.append("### Current Positions:")
            for pos in portfolio_context['positions']:
                prompt_parts.append(
                    f"- {pos.get('ticker', 'N/A')} ({pos.get('direction', 'N/A')}): "
                    f"{pos.get('size_pct', 0):.1f}%"
                )
            prompt_parts.append("")

        if portfolio_context.get('sector_exposure'):
            prompt_parts.append("### Sector Exposure:")
            for sector, pct in portfolio_context['sector_exposure'].items():
                prompt_parts.append(f"- {sector}: {pct:.1f}%")
            prompt_parts.append("")

    # Market context
    if market_context:
        prompt_parts.extend([
            "="*60,
            "## MACRO CONTEXT",
            "="*60,
            "",
            market_context,
            "",
        ])

    # Final instructions
    prompt_parts.extend([
        "="*60,
        "## YOUR TASK",
        "="*60,
        "",
        "Analyze all inputs above for non-obvious alpha opportunities.",
        "",
        "Remember:",
        "- Only report discoveries with 60%+ confidence",
        "- Must be non-obvious (single desk wouldn't spot it)",
        "- Must be actionable with clear portfolio implications",
        "- Most cycles should produce 0-1 discoveries — quality over quantity",
        "- If nothing qualifies, explain what you looked for and why",
        "",
        "Respond with ONLY valid JSON matching the alpha discovery output schema.",
    ])

    return "\n".join(prompt_parts)


def build_chat_prompt(
    message: str,
    desk_briefs: list[dict] = None,
    flow_briefing: dict = None,
    portfolio_context: dict = None,
) -> str:
    """
    Build a chat prompt for interactive alpha discovery queries.

    Args:
        message: User's question about cross-agent patterns
        desk_briefs: Latest briefs from all sector desks
        flow_briefing: Institutional flow analysis
        portfolio_context: Current portfolio state
    """
    from datetime import datetime

    prompt_parts = [
        "## ALPHA DISCOVERY CHAT",
        f"## TIMESTAMP: {datetime.utcnow().isoformat()}Z",
        "",
    ]

    # Add context summaries
    if desk_briefs:
        prompt_parts.append("### Recent Desk Signals:")
        for brief in desk_briefs[:10]:  # Top 10 briefs
            signal = brief.get('signal', 'N/A')
            desk = brief.get('desk', 'Unknown')
            ticker = brief.get('ticker', 'N/A')
            conf = brief.get('confidence', 0)
            prompt_parts.append(f"- {desk}/{ticker}: {signal} ({conf:.0%})")
        prompt_parts.append("")

    if flow_briefing:
        prompt_parts.append("### Flow Highlights:")
        if flow_briefing.get('consensus_builds'):
            prompt_parts.append(f"- Consensus builds: {len(flow_briefing['consensus_builds'])} stocks")
        if flow_briefing.get('crowding_warnings'):
            prompt_parts.append(f"- Crowding warnings: {len(flow_briefing['crowding_warnings'])} stocks")
        prompt_parts.append("")

    if portfolio_context:
        prompt_parts.extend([
            "### Portfolio:",
            f"- Value: ${portfolio_context.get('total_value', 0):,.0f}",
            f"- Positions: {portfolio_context.get('num_positions', 0)}",
            f"- Cash: {portfolio_context.get('cash_pct', 0):.1f}%",
            "",
        ])

    prompt_parts.extend([
        "## USER QUESTION",
        message,
        "",
        "## YOUR TASK",
        "Answer the question by analyzing cross-agent patterns.",
        "Focus on non-obvious insights that emerge from the intersection of multiple signals.",
        "Be specific about what patterns you see and their portfolio implications.",
        "",
        "Respond with valid JSON including your analysis and any discoveries.",
    ])

    return "\n".join(prompt_parts)


def build_backtest_prompt(
    historical_signals: list[dict],
    outcomes: list[dict],
) -> str:
    """
    Build a prompt for backtesting past signal combinations.

    Args:
        historical_signals: Past agent signals and their combinations
        outcomes: What actually happened in the market
    """
    from datetime import datetime

    prompt_parts = [
        "## ALPHA DISCOVERY BACKTEST",
        f"## TIMESTAMP: {datetime.utcnow().isoformat()}Z",
        "",
        "Analyze historical signal combinations and their outcomes.",
        "Identify patterns that would have predicted market moves.",
        "",
        "="*60,
        "## HISTORICAL SIGNAL PERIODS",
        "="*60,
        "",
    ]

    for i, (signals, outcome) in enumerate(zip(historical_signals, outcomes)):
        prompt_parts.extend([
            f"### Period {i+1}: {signals.get('date_range', 'Unknown')}",
            "",
            "**Agent Signals:**",
        ])
        for agent, signal in signals.get('agent_signals', {}).items():
            prompt_parts.append(f"- {agent}: {signal}")

        prompt_parts.extend([
            "",
            "**Market Outcome:**",
            f"- SPY: {outcome.get('spy_return', 'N/A')}",
            f"- VIX change: {outcome.get('vix_change', 'N/A')}",
            f"- Sector leaders: {outcome.get('sector_leaders', 'N/A')}",
            f"- Notable moves: {outcome.get('notable_moves', 'N/A')}",
            "",
        ])

    prompt_parts.extend([
        "="*60,
        "## YOUR TASK",
        "="*60,
        "",
        "1. Identify signal combinations that predicted outcomes",
        "2. Calculate hit rates for each pattern type",
        "3. Note which cross-agent patterns had predictive power",
        "4. Flag patterns to monitor going forward",
        "",
        "Respond with valid JSON including pattern analysis and recommendations.",
    ])

    return "\n".join(prompt_parts)
