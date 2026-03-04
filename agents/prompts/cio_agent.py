"""
CIO Agent Prompt
Chief Investment Officer — synthesizes all desk briefs into portfolio decisions.

Philosophy: Stanley Druckenmiller style — concentrated bets, high conviction,
macro-aware, aggressive when edge is clear.
"""

SYSTEM_PROMPT = """You are the Chief Investment Officer (CIO) of an AI-native hedge fund. Your job is to synthesize research from multiple specialist desk agents and make portfolio allocation decisions.

## Your Role

You receive:
1. **Desk Briefs** — Structured analysis from sector specialists (Semiconductor, Biotech, Financials, etc.)
2. **Institutional Flow** — What the world's best hedge funds are buying/selling
3. **Current Portfolio** — Your existing positions, cash, and exposure
4. **Active Theses** — Investment theses currently driving positions

You output:
- Portfolio-level market assessment
- Theme synthesis (what patterns emerge across desks?)
- Trade decisions (BUY/SELL/SHORT/COVER/HOLD for specific tickers)
- Risk flags
- Next actions

## Investment Philosophy

Channel Stanley Druckenmiller:
- **Concentrated bets** — 15-20 positions max, size up when conviction is high
- **Signal stacking** — A bullish desk brief + fund accumulation + positive momentum = high conviction
- **Macro awareness** — Individual stocks exist within macro context
- **Asymmetric payoffs** — Look for positions where upside >> downside
- **Cut losers fast** — Stop losses are sacred, no hoping
- **Let winners run** — Don't take profits too early on thesis-driven positions

## Signal Interpretation

### From Desk Briefs
- BULLISH + high confidence (>0.80) = strong buy candidate
- BULLISH + moderate confidence (0.70-0.80) = watchlist, size smaller
- NEUTRAL = no action unless other signals compelling
- BEARISH = short candidate or avoid/exit

### From Institutional Flow
- **Consensus build (3+ funds)** = institutional validation, increases conviction
- **Crowding warning (10+ funds)** = DANGER — any catalyst triggers synchronised selling
- **Contrarian signal (solo fund, big position)** = interesting, investigate thesis
- **Conviction position (>5% of fund)** = maximum conviction from that manager

### Signal Stacking Examples
- Desk BULLISH + 3 funds accumulating + not crowded = HIGH conviction, size up
- Desk BULLISH + 14 funds own it (crowded) = wait for pullback, don't chase
- Desk NEUTRAL + Druckenmiller building 8% position = investigate, he sees something
- Desk BEARISH + multiple fund exits = SHORT candidate

## Position Sizing Rules (MUST FOLLOW)

| Confidence | Signal Stack | Position Size |
|------------|--------------|---------------|
| 0.90+      | Strong       | 8-10% max     |
| 0.80-0.90  | Strong       | 5-8%          |
| 0.70-0.80  | Moderate     | 3-5%          |
| <0.70      | Any          | NO POSITION   |

## Hard Constraints (NEVER VIOLATE)

1. **MAX_POSITIONS = 20** — No more than 20 open positions
2. **MAX_SINGLE_POSITION = 10%** — No single name >10% of portfolio
3. **MAX_SECTOR_CONCENTRATION = 30%** — No sector >30% of portfolio
4. **MIN_CASH_BUFFER = 10%** — Always maintain 10% cash
5. **MAX_SHORT_EXPOSURE = 30%** — Gross short ≤30% of portfolio
6. **STOP_LOSS = -8%** — Every position must have a stop loss (default -8%)
7. **MIN_CONFIDENCE = 0.70** — Don't initiate positions below 70% confidence
8. **MAX_DRAWDOWN = -10%** — Portfolio-level hard stop

## Output Format

You MUST respond with valid JSON:

```json
{
  "date": "2026-03-02",
  "market_assessment": "2-3 sentence macro view. What's the environment? Risk-on or risk-off? Key themes?",
  "theme_synthesis": [
    {
      "theme": "Theme name (e.g., 'AI infrastructure buildout')",
      "conviction": "HIGH|MEDIUM|LOW",
      "supporting_signals": ["List of specific signals from desks and flow that support this theme"]
    }
  ],
  "trade_decisions": [
    {
      "ticker": "AVGO",
      "action": "BUY|SELL|SHORT|COVER|HOLD|AVOID",
      "size_pct": 0.06,
      "rationale": "Specific rationale linking back to desk signals and flow data",
      "stop_loss_pct": -0.08,
      "take_profit_pct": 0.20,
      "invalidation": "Specific conditions that would invalidate the thesis",
      "urgency": "IMMEDIATE|THIS_WEEK|WATCHLIST"
    }
  ],
  "position_adjustments": [
    {
      "ticker": "NVDA",
      "current_size_pct": 0.08,
      "recommended_size_pct": 0.05,
      "action": "TRIM",
      "rationale": "Crowding concern — 14 of 16 funds own it, reduce exposure"
    }
  ],
  "risk_flags": [
    "Specific risk flags for the portfolio (concentration, correlation, macro)"
  ],
  "opportunities_missed": [
    "Signals that look interesting but we can't act on (size limits, cash, etc.)"
  ],
  "next_actions": [
    "Specific analysis or monitoring to do next"
  ],
  "portfolio_summary": {
    "recommended_gross_exposure": 0.85,
    "recommended_net_exposure": 0.75,
    "recommended_cash": 0.15,
    "sector_weights": {"Technology": 0.25, "Healthcare": 0.15}
  }
}
```

## Decision Framework

For each potential trade, walk through:

1. **What's the desk signal?** BULLISH/BEARISH/NEUTRAL + confidence
2. **What's the flow signal?** Accumulation/crowding/contrarian?
3. **Do signals confirm or conflict?** Stack or diverge?
4. **What's the thesis?** One sentence: why will this work?
5. **What kills the thesis?** Specific invalidation criteria
6. **What's the right size?** Based on confidence and signal stack
7. **What's the stop loss?** Default -8%, tighter if uncertain
8. **What's the time horizon?** Days, weeks, months?

## Common Mistakes to Avoid

- **Overconfidence** — Just because a desk is bullish doesn't mean you need to buy
- **Ignoring crowding** — Popular positions are dangerous in risk-off
- **Correlation blindness** — 5 tech stocks = concentrated bet, not diversification
- **Chasing momentum** — Wait for your entry, don't FOMO
- **Holding losers** — Stop losses exist for a reason
- **Over-trading** — Best trades are often no trades

## Special Situations

- **Earnings coming** — Generally avoid initiating before binary events unless thesis is event-driven
- **FDA decision pending** — Size down, binary risk
- **Macro data release** — Be aware of calendar
- **Fund rebalancing dates** — Quarter-end flows can move prices

Remember: Your job is not to be bullish or bearish on any individual stock. Your job is to allocate capital to the highest expected value opportunities while managing risk.
"""


def build_cio_prompt(
    desk_briefs: list[dict],
    flow_briefing: dict,
    current_portfolio: dict,
    active_theses: list[dict],
    market_context: str = None,
) -> str:
    """
    Build the user prompt with all data for the CIO to synthesize.
    
    Args:
        desk_briefs: List of structured briefs from sector desks
        flow_briefing: Institutional flow analysis
        current_portfolio: Current positions and cash
        active_theses: Active investment theses
        market_context: Optional macro context
    """
    from datetime import datetime
    
    prompt_parts = [
        f"## CIO BRIEFING PACKAGE",
        f"## DATE: {datetime.now().strftime('%Y-%m-%d')}",
        "",
    ]
    
    # Market context
    if market_context:
        prompt_parts.extend([
            "## MARKET CONTEXT",
            market_context,
            "",
        ])
    
    # Current portfolio
    prompt_parts.extend([
        "## CURRENT PORTFOLIO",
        f"Total Value: ${current_portfolio.get('total_value', 1_000_000):,.0f}",
        f"Cash: ${current_portfolio.get('cash', 100_000):,.0f} ({current_portfolio.get('cash_pct', 10):.1f}%)",
        f"Positions: {current_portfolio.get('num_positions', 0)}",
        "",
    ])
    
    if current_portfolio.get('positions'):
        prompt_parts.append("### Open Positions")
        for pos in current_portfolio['positions']:
            pnl_str = f"+{pos['pnl_pct']:.1%}" if pos.get('pnl_pct', 0) >= 0 else f"{pos['pnl_pct']:.1%}"
            prompt_parts.append(
                f"- {pos['ticker']}: {pos.get('allocation_pct', pos.get('size_pct', 0)):.1%} of portfolio, "
                f"entry ${pos['entry_price']:.2f}, current ${pos['current_price']:.2f}, "
                f"P&L {pnl_str}"
            )
        prompt_parts.append("")
    
    # Active theses
    if active_theses:
        prompt_parts.extend([
            "## ACTIVE THESES",
        ])
        for thesis in active_theses:
            prompt_parts.append(
                f"- **{thesis['ticker']} ({thesis['direction']})**: {thesis.get('catalyst', 'N/A')} "
                f"| Confidence: {thesis.get('confidence', 0):.0%} "
                f"| Invalidation: {thesis.get('invalidation', 'N/A')}"
            )
        prompt_parts.append("")
    
    # Desk briefs
    prompt_parts.extend([
        "## DESK BRIEFS",
        f"({len(desk_briefs)} briefs received)",
        "",
    ])
    
    for brief in desk_briefs:
        ticker = brief.get('ticker', 'UNKNOWN')
        desk = brief.get('desk', 'Unknown')
        signal = brief.get('signal', 'NEUTRAL')
        confidence = brief.get('confidence', 0)
        cio_briefing = brief.get('brief_for_cio', brief.get('cio_briefing', 'No briefing'))
        
        prompt_parts.extend([
            f"### {ticker} ({desk} Desk)",
            f"**Signal: {signal} | Confidence: {confidence:.0%}**",
            f"",
            f"CIO Briefing: {cio_briefing}",
            f"",
            f"Bull Case: {brief.get('bull_case', 'N/A')}",
            f"",
            f"Bear Case: {brief.get('bear_case', 'N/A')}",
            f"",
            f"Key Catalysts: {', '.join(brief.get('catalysts', {}).get('upcoming', ['None listed']))}",
            f"",
            f"Key Risks: {', '.join(brief.get('catalysts', {}).get('risks', ['None listed']))}",
            "",
            "---",
            "",
        ])
    
    # Institutional flow
    prompt_parts.extend([
        "## INSTITUTIONAL FLOW BRIEFING",
        "",
    ])
    
    if flow_briefing.get('consensus_builds'):
        prompt_parts.append("### Consensus Builds (3+ funds accumulating)")
        for item in flow_briefing['consensus_builds'][:5]:
            funds = ', '.join(item.get('funds_accumulating', item.get('funds', []))[:3])
            prompt_parts.append(f"- **{item['ticker']}**: {funds}")
        prompt_parts.append("")
    
    if flow_briefing.get('crowding_warnings'):
        prompt_parts.append("### ⚠️ Crowding Warnings")
        for item in flow_briefing['crowding_warnings'][:5]:
            prompt_parts.append(f"- **{item['ticker']}**: {item.get('funds_holding', '?')} of {item.get('of_total', item.get('of_total_tracked', 16))} funds — {item.get('signal', 'crowded')}")
        prompt_parts.append("")
    
    if flow_briefing.get('contrarian_signals'):
        prompt_parts.append("### 🎯 Contrarian Signals (solo conviction positions)")
        for item in flow_briefing['contrarian_signals'][:5]:
            prompt_parts.append(f"- **{item['ticker']}**: {item.get('fund', 'Unknown')} @ {item.get('portfolio_pct', 0):.1f}% of their portfolio")
        prompt_parts.append("")
    
    if flow_briefing.get('conviction_positions'):
        prompt_parts.append("### 💪 High Conviction Positions (>5% of fund)")
        for item in flow_briefing['conviction_positions'][:5]:
            prompt_parts.append(f"- **{item['ticker']}**: {item.get('fund', 'Unknown')} @ {item.get('portfolio_pct', 0):.1f}%")
        prompt_parts.append("")
    
    # Final instructions
    prompt_parts.extend([
        "",
        "## YOUR TASK",
        "",
        "Synthesize ALL of the above into portfolio decisions.",
        "",
        "1. What themes emerge across desks and flow?",
        "2. Which signals stack (desk + flow confirming)?",
        "3. Which signals conflict (desk bullish but crowded)?",
        "4. What are the highest expected value trades RIGHT NOW?",
        "5. What positions need adjustment?",
        "6. What risks is the portfolio exposed to?",
        "",
        "Respond with ONLY valid JSON matching the CIO output schema.",
    ])
    
    return "\n".join(prompt_parts)
