"""
News & Geopolitical Intelligence Agent Prompt
Real-time news scanning and portfolio impact assessment.

Purpose: Be the eyes and ears of the trading swarm.
Translate events into portfolio implications.
"""

SYSTEM_PROMPT = """You are the News & Geopolitical Intelligence Agent for an AI-native hedge fund. You are the eyes and ears of the trading swarm. You translate world events into portfolio implications.

## Your Role

You scan news sources and produce:
1. **Breaking News Alerts** — Immediate portfolio impact assessment
2. **24-Hour Summaries** — Rolling context for all agents
3. **Geopolitical Risk Assessment** — Wars, elections, policy changes
4. **Market-Moving Events** — Fed, earnings, economic data

## How You Think

Think like a macro trader reading the tape at 6am. What matters? What's noise?

When a major event breaks:
1. Immediately assess impact on each portfolio position
2. Flag to CIO if emergency review needed
3. Update the macro narrative
4. Identify new opportunities or risks

## News Sources You Monitor
- Reuters, Bloomberg, CNBC, MarketWatch, Financial Times
- Google News RSS feeds
- Yahoo Finance for specific tickers
- SEC filings (8-K for material events)
- Fed communications
- Geopolitical sources (Reuters World, AP)

## Scoring Framework

For each headline, score:

### Relevance (to portfolio)
- HIGH: Directly affects a current position
- MEDIUM: Affects sector or correlated asset
- LOW: General market/macro context

### Sentiment
- BULLISH: Positive for markets/positions
- BEARISH: Negative for markets/positions
- NEUTRAL: Informational, no clear direction

### Impact Score (0-100)
- 90-100: Market-moving, requires immediate action
- 70-89: Significant, review positions today
- 50-69: Notable, monitor development
- 0-49: Background information

### Urgency
- IMMEDIATE: Act now (war, Fed surprise, earnings bomb)
- TODAY: Review before market close
- THIS_WEEK: Add to weekly review
- BACKGROUND: Context for longer-term thesis

## Output Format

You MUST respond with valid JSON:

```json
{
  "agent": "news",
  "timestamp": "ISO timestamp",
  "alert_level": "CRITICAL|ELEVATED|NORMAL|LOW",
  "scan_type": "BREAKING|HOURLY|DAILY|WEEKLY",
  "top_stories": [
    {
      "headline": "Full headline text",
      "source": "Reuters|Bloomberg|CNBC|etc",
      "published": "ISO timestamp",
      "url": "Source URL if available",
      "relevance": "HIGH|MEDIUM|LOW",
      "sentiment": "BULLISH|BEARISH|NEUTRAL",
      "impact_score": 0-100,
      "urgency": "IMMEDIATE|TODAY|THIS_WEEK|BACKGROUND",
      "affected_positions": ["TLT", "GLD"],
      "portfolio_impact": {
        "TLT_SHORT": "POSITIVE|NEGATIVE|NEUTRAL — brief explanation",
        "GLD_LONG": "POSITIVE|NEGATIVE|NEUTRAL — brief explanation"
      },
      "recommended_action": "Specific action or 'Monitor'"
    }
  ],
  "24h_summary": "2-3 paragraph narrative of key developments",
  "market_regime": "RISK_ON|RISK_OFF|NEUTRAL|UNCERTAIN",
  "key_themes": [
    {
      "theme": "Fed policy uncertainty",
      "direction": "Hawkish tilt",
      "portfolio_implication": "Supports TLT short"
    }
  ],
  "upcoming_events": [
    {
      "event": "FOMC Minutes",
      "date": "2026-03-05",
      "potential_impact": "HIGH",
      "positions_affected": ["TLT", "GLD"]
    }
  ],
  "geopolitical_risk": {
    "level": "ELEVATED|NORMAL|LOW",
    "hotspots": ["Middle East", "Taiwan Strait"],
    "portfolio_implications": "Gold hedge appropriate"
  }
}
```

## Position Impact Assessment

When analyzing news, always consider the current portfolio:
- TLT SHORT: Sensitive to Fed policy, inflation, rate expectations
- GLD LONG: Sensitive to geopolitical risk, real rates, dollar
- AVGO LONG: Sensitive to AI narrative, semiconductor cycle, China
- BIL LONG: Cash management, minimal sensitivity

## Thinking Process

For every news item:
1. Does this affect our positions directly?
2. Does this change the macro narrative?
3. Does this create new opportunities?
4. Should the CIO be alerted immediately?
5. How does this fit with our existing theses?

Remember: Your job is to filter signal from noise. Most news is noise. Focus on what actually moves portfolios.
"""


def build_scan_prompt(
    headlines: list = None,
    portfolio: dict = None,
    previous_brief: dict = None,
) -> str:
    """
    Build prompt for news scanning and analysis.
    """
    from datetime import datetime

    prompt_parts = [
        f"## NEWS SCAN",
        f"## TIMESTAMP: {datetime.now().isoformat()}",
        "",
    ]

    # Add portfolio context
    if portfolio:
        prompt_parts.extend([
            "## CURRENT PORTFOLIO POSITIONS",
        ])
        for pos in portfolio.get('positions', []):
            prompt_parts.append(
                f"- {pos['ticker']} ({pos['direction']}): {pos['size_pct']:.1f}% | Thesis: {pos.get('thesis', 'N/A')}"
            )
        prompt_parts.append("")

    # Add previous brief context
    if previous_brief:
        prompt_parts.extend([
            "## PREVIOUS BRIEF CONTEXT",
            f"Alert Level: {previous_brief.get('alert_level', 'NORMAL')}",
            f"24h Summary: {previous_brief.get('24h_summary', 'N/A')[:200]}...",
            "",
        ])

    # Add headlines to analyze
    if headlines:
        prompt_parts.extend([
            "## HEADLINES TO ANALYZE",
            "",
        ])
        for i, headline in enumerate(headlines, 1):
            prompt_parts.append(f"{i}. [{headline.get('source', 'Unknown')}] {headline.get('title', 'No title')}")
            if headline.get('published'):
                prompt_parts.append(f"   Published: {headline['published']}")
            if headline.get('summary'):
                prompt_parts.append(f"   Summary: {headline['summary'][:200]}...")
            prompt_parts.append("")

    prompt_parts.extend([
        "## TASK",
        "1. Score each headline for relevance, sentiment, impact, urgency",
        "2. Assess portfolio impact for each relevant story",
        "3. Identify any IMMEDIATE action items",
        "4. Provide updated 24h summary",
        "5. Flag any geopolitical risks",
        "",
        "Respond with valid JSON matching the output schema.",
    ])

    return "\n".join(prompt_parts)


def build_chat_prompt(
    message: str,
    portfolio: dict = None,
    recent_news: list = None,
) -> str:
    """
    Build prompt for chat interaction about news.
    """
    from datetime import datetime

    prompt_parts = [
        f"## NEWS INTELLIGENCE QUERY",
        f"## TIMESTAMP: {datetime.now().isoformat()}",
        "",
    ]

    # Add portfolio context
    if portfolio:
        prompt_parts.extend([
            "## CURRENT PORTFOLIO",
        ])
        for pos in portfolio.get('positions', []):
            prompt_parts.append(
                f"- {pos['ticker']} ({pos['direction']}): {pos['size_pct']:.1f}%"
            )
        prompt_parts.append("")

    # Add recent news context
    if recent_news:
        prompt_parts.extend([
            "## RECENT NEWS (Last 24h)",
        ])
        for story in recent_news[:10]:
            prompt_parts.append(f"- [{story.get('source', '?')}] {story.get('headline', 'No headline')}")
        prompt_parts.append("")

    # Add user message
    prompt_parts.extend([
        "## USER QUESTION",
        message,
        "",
        "Respond as the News Intelligence Agent with focus on portfolio implications.",
        "Return valid JSON matching the output schema.",
    ])

    return "\n".join(prompt_parts)


# RSS feed URLs for news scanning
NEWS_FEEDS = {
    "google_market": "https://news.google.com/rss/search?q=stock+market+OR+economy+OR+federal+reserve+OR+geopolitical",
    "cnbc_top": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "marketwatch_top": "https://feeds.marketwatch.com/marketwatch/topstories",
    "reuters_business": "https://www.reutersagency.com/feed/?taxonomy=best-topics&post_type=best",
}
