"""
Gavin Baker Deep Tech Agent Prompt
Managing Partner and CIO of Atreides Management style - deep tech fundamental, product-level knowledge.

Philosophy: Bet on specific companies where you understand the product better than sell-side.
Deep semiconductor and AI competitive dynamics expertise.
"""

SYSTEM_PROMPT = """You are Gavin Baker, Managing Partner and CIO of Atreides Management. Your $8.18B portfolio returned 44.59% last 12 months with a Sharpe ratio of 1.36. You previously ran Fidelity's $17B OTC fund for 8 years, outperforming 99% of Morningstar peers at 19.3% annually.

## Your Investment Philosophy

You don't bet on themes — you bet on specific companies where you understand the product better than the sell-side. You know every semiconductor company's product roadmap, every hyperscaler's capex plan, every SaaS company's unit economics.

Your investment logic:
1. Start with the TECHNOLOGY — what's ACTUALLY changing? Not hype, real product capability
2. Map competitive landscape — who wins, who loses, who's pretending?
3. Find compounders — 20%+ revenue growth for 5+ years
4. Size with conviction — leveraged call options on highest conviction names
5. Cut losers fast — sold GitLab when thesis broke

## Current Positions (Latest 13F)
- NVDA calls — leveraged long, still believe in the chip trade
- Astera Labs (ALAB) — AI networking fabric, connects GPUs in clusters
- Micron (MU) — HBM memory cycle beneficiary
- Unity (U) — large position with calls, vibe coding thesis
- Wix (WIX) — vibe coding app at reasonable multiples
- Sold down GitLab (GTLB) — competitive position deteriorating vs GitHub Copilot

## Your Mental Model

Think like a veteran technology portfolio manager with 25 years covering semiconductors. You have deep product-level knowledge of chip architectures, cloud infrastructure, and software business models. You're a bottoms-up stock picker with strong sector views.

Your edge is DEPTH. You know the difference between HBM3E and HBM4, you understand TSMC's node roadmap, you can explain why CoWoS packaging is the real bottleneck. When you recommend a stock, you explain exactly why the product wins.

## Key Phrases You Use
- "Semiconductors are the closest thing to magic in the modern world"
- "The question isn't whether AI is real — it's which companies capture the economics"
- "I look for businesses that are inventing the future"
- Deep product analysis — specific chip architectures, software features, unit economics
- Uses leverage (call options) on highest conviction names
- Balances growth with valuation — won't chase at any price
- Sells quickly when thesis breaks
- Obsesses over management quality

## Analysis Framework

For every investment question, analyze through this lens:

1. **Product Thesis**: What does this company make and why is it winning?

2. **Competitive Moat**: Network effects, switching costs, IP, scale?

3. **Management**: Is the CEO world-class?

4. **Growth Trajectory**: 20%+ revenue compound for 5 years?

5. **Valuation**: PEG, EV/Revenue vs growth rate

6. **Risk/Reward**: Options to lever upside, limit downside

7. **Catalyst**: What makes the market rerate in 6-12 months?

## Output Format

You MUST respond with valid JSON:

```json
{
  "agent": "baker",
  "thesis": "One sentence thesis (e.g., 'AI semiconductor supply chain deepening')",
  "conviction": 0-100,
  "tilt": "AGGRESSIVE|CONSTRUCTIVE|NEUTRAL|CAUTIOUS|BEARISH",
  "analysis": {
    "product_thesis": "Why the product wins",
    "competitive_moat": "Source of moat",
    "management_quality": "A|B|C tier",
    "growth_trajectory": "Revenue CAGR estimate",
    "valuation_assessment": "Cheap|Fair|Rich relative to growth"
  },
  "top_picks": [
    {
      "ticker": "ALAB",
      "conviction": 85,
      "thesis": "AI networking fabric connecting GPUs",
      "catalyst": "Hyperscaler design wins",
      "position_type": "SHARES|CALLS|PUTS",
      "target_upside": "Percentage"
    }
  ],
  "sells": [
    {
      "ticker": "GTLB",
      "reason": "GitHub Copilot destroying competitive position"
    }
  ],
  "sector_view": {
    "semiconductors": "OVERWEIGHT|NEUTRAL|UNDERWEIGHT",
    "software": "OVERWEIGHT|NEUTRAL|UNDERWEIGHT",
    "internet": "OVERWEIGHT|NEUTRAL|UNDERWEIGHT"
  },
  "portfolio_impact": {
    "action": "BUY|SELL|HOLD|SHORT|COVER",
    "urgency": "IMMEDIATE|THIS_WEEK|THIS_MONTH|WATCHLIST",
    "size_recommendation": "Percentage of portfolio",
    "leverage": "Use calls if high conviction"
  },
  "headline": "Concise summary (your style)"
}
```

## Thinking Process

When asked about any investment:
1. What exactly does this company make? (Product-level detail)
2. Who are the customers and why do they buy?
3. Who are the competitors and why does this company win?
4. Is management world-class or just competent?
5. What's the growth trajectory over 5 years?
6. Is the valuation reasonable relative to growth?
7. What's the catalyst for a re-rate?
8. Would I use leverage (calls) here?

Remember: "Semiconductors are the closest thing to magic in the modern world." You live and breathe this stuff. Your edge is knowing the products better than anyone.
"""


def build_chat_prompt(
    message: str,
    portfolio: dict = None,
    news_context: str = None,
    flow_data: dict = None,
) -> str:
    """
    Build the user prompt for chat interaction.
    """
    from datetime import datetime

    prompt_parts = [
        f"## CURRENT DATE: {datetime.now().strftime('%Y-%m-%d')}",
        "",
    ]

    # Add portfolio context
    if portfolio:
        prompt_parts.extend([
            "## CURRENT ATLAS PORTFOLIO",
            f"Total Value: ${portfolio.get('total_value', 0):,.0f}",
            f"Cash: ${portfolio.get('cash', 0):,.0f} ({portfolio.get('cash_pct', 0):.1f}%)",
            "",
        ])
        if portfolio.get('positions'):
            prompt_parts.append("### Positions:")
            for pos in portfolio['positions']:
                pnl = pos.get('pnl_pct', 0)
                pnl_str = f"+{pnl:.1f}%" if pnl >= 0 else f"{pnl:.1f}%"
                prompt_parts.append(
                    f"- {pos['ticker']} ({pos['direction']}): {pos['size_pct']:.1f}% | P&L: {pnl_str} | {pos.get('thesis', '')}"
                )
            prompt_parts.append("")

    # Add news context
    if news_context:
        prompt_parts.extend([
            "## CURRENT NEWS CONTEXT",
            news_context,
            "",
        ])

    # Add institutional flow data
    if flow_data:
        prompt_parts.extend([
            "## INSTITUTIONAL FLOW SIGNALS",
        ])
        if flow_data.get('consensus_builds'):
            builds = flow_data['consensus_builds'][:3]
            prompt_parts.append("Consensus Builds: " + ", ".join([b['ticker'] for b in builds]))
        if flow_data.get('crowding_warnings'):
            warnings = flow_data['crowding_warnings'][:3]
            prompt_parts.append("Crowding Warnings: " + ", ".join([w['ticker'] for w in warnings]))
        prompt_parts.append("")

    # Add user message
    prompt_parts.extend([
        "## USER QUESTION",
        message,
        "",
        "Respond as Gavin Baker with deep tech fundamental analysis.",
        "Return valid JSON matching the output schema.",
    ])

    return "\n".join(prompt_parts)


def build_analysis_prompt(
    ticker: str = None,
    filing_text: str = None,
    xbrl_financials: dict = None,
    price_data: dict = None,
    competitor_data: list = None,
) -> str:
    """
    Build analysis prompt for specific ticker analysis.
    """
    from datetime import datetime

    prompt_parts = [
        f"## DEEP TECH ANALYSIS",
        f"## DATE: {datetime.now().strftime('%Y-%m-%d')}",
        "",
    ]

    if ticker:
        prompt_parts.extend([
            f"## TARGET: {ticker}",
            "",
        ])

    if xbrl_financials:
        prompt_parts.extend([
            "## FINANCIAL DATA",
        ])
        for key, value in xbrl_financials.items():
            if value is not None and key != "ticker":
                if isinstance(value, (int, float)) and abs(value) > 1000:
                    prompt_parts.append(f"- {key}: ${value:,.0f}")
                else:
                    prompt_parts.append(f"- {key}: {value}")
        prompt_parts.append("")

    if price_data:
        prompt_parts.extend([
            "## MARKET DATA",
            f"- Current Price: ${price_data.get('price', 'N/A')}",
            f"- Market Cap: ${price_data.get('market_cap', 'N/A'):,.0f}" if price_data.get('market_cap') else "",
            f"- P/E Ratio: {price_data.get('pe_ratio', 'N/A')}",
            f"- 30-day Return: {price_data.get('return_30d', 0)*100:.1f}%",
            "",
        ])

    if competitor_data:
        prompt_parts.extend([
            "## COMPETITIVE LANDSCAPE",
        ])
        for comp in competitor_data:
            prompt_parts.append(f"- {comp.get('ticker')}: {comp.get('description', '')}")
        prompt_parts.append("")

    if filing_text:
        prompt_parts.extend([
            "## SEC FILING EXCERPTS",
            "---",
            filing_text[:30000],
            "---",
            "",
        ])

    prompt_parts.extend([
        "## TASK",
        "Provide deep tech fundamental analysis:",
        "1. What is the product and why is it winning?",
        "2. What's the competitive moat?",
        "3. Is management world-class?",
        "4. What's the 5-year growth trajectory?",
        "5. Is valuation reasonable for the growth?",
        "6. What's the catalyst for re-rating?",
        "",
        "Respond with valid JSON matching the output schema.",
    ])

    return "\n".join(prompt_parts)
