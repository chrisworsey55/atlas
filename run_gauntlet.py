#!/usr/bin/env python3
"""
ATLAS Agent Gauntlet Runner
Runs stocks through the full 4-agent analysis process:
1. Fundamental Agent - reconfirm valuation at today's price
2. Sector Desk - identify near-term catalyst
3. Adversarial Agent - attack the thesis
4. CIO Agent - synthesize and size
"""
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load .env from gic-underwriting directory
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv(Path.home() / "gic-underwriting" / ".env")

import anthropic
import yfinance as yf

# Setup path
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Get API key directly from environment
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-20250514"
CLAUDE_MODEL_PREMIUM = "claude-sonnet-4-20250514"

if not ANTHROPIC_API_KEY:
    raise ValueError("ANTHROPIC_API_KEY not found in environment. Check .env file.")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

# Gauntlet output directory
GAUNTLET_DIR = Path(__file__).resolve().parent.parent / "data" / "state" / "gauntlet"
GAUNTLET_DIR.mkdir(parents=True, exist_ok=True)

# Ticker to sector mapping for desk routing
TICKER_SECTORS = {
    "APO": "financials",      # Apollo Global Management - PE/Asset Management
    "GDDY": "technology",     # GoDaddy - Internet services
    "ADBE": "technology",     # Adobe - Software
    "GOOG": "technology",     # Alphabet - Internet/AI
    "ANET": "technology",     # Arista Networks - Networking
    "BLK": "financials",      # BlackRock - Asset Management
    "CMCSA": "communications" # Comcast - Media/Telecom
}

# Current portfolio for CIO context
CURRENT_PORTFOLIO = {
    "positions": [
        {"ticker": "BIL", "size_pct": 0.70, "type": "cash_equivalent"},
        {"ticker": "BE", "size_pct": 0.15, "type": "equity"},
        {"ticker": "TLT", "size_pct": 0.10, "type": "bonds"},
        {"ticker": "AVGO", "size_pct": 0.05, "type": "equity"},
    ],
    "cash_pct": 70,  # BIL is cash equivalent
    "total_value": 1_000_000,
}


def get_current_price(ticker: str) -> dict:
    """Fetch current price and basic data from yfinance."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info or {}
        return {
            "price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "52w_high": info.get("fiftyTwoWeekHigh"),
            "52w_low": info.get("fiftyTwoWeekLow"),
            "earnings_date": str(info.get("earningsDate", ["Unknown"])[0]) if info.get("earningsDate") else "Unknown",
            "sector": info.get("sector", "Unknown"),
            "industry": info.get("industry", "Unknown"),
        }
    except Exception as e:
        logger.warning(f"Could not fetch price data for {ticker}: {e}")
        return {"price": None, "error": str(e)}


def run_fundamental_agent(ticker: str, price_data: dict, client: anthropic.Anthropic) -> dict:
    """
    Step 1: Fundamental agent reconfirms valuation at today's price.
    """
    logger.info(f"[FUNDAMENTAL] Analyzing {ticker}...")

    # Format market cap nicely
    market_cap = price_data.get('market_cap')
    if market_cap and isinstance(market_cap, (int, float)):
        if market_cap >= 1e12:
            mc_str = f"${market_cap/1e12:.2f}T"
        elif market_cap >= 1e9:
            mc_str = f"${market_cap/1e9:.1f}B"
        else:
            mc_str = f"${market_cap/1e6:.0f}M"
    else:
        mc_str = "N/A"

    prompt = f"""TODAY'S DATE: March 5, 2026. Use current prices, current earnings data, and current forward estimates. Do not reference earnings dates from 2024 or 2025.

Reconfirm your valuation of {ticker}. Has anything changed since the initial screen?

## Current Market Data (as of March 5, 2026)
- Current Price: ${price_data.get('price', 'N/A')}
- Market Cap: {mc_str}
- P/E Ratio (TTM): {price_data.get('pe_ratio', 'N/A')}
- Forward P/E: {price_data.get('forward_pe', 'N/A')}
- 52-Week Range: ${price_data.get('52w_low', 'N/A')} - ${price_data.get('52w_high', 'N/A')}
- Sector: {price_data.get('sector', 'Unknown')}
- Industry: {price_data.get('industry', 'Unknown')}

## Your Task
1. Calculate intrinsic value using DCF and/or comparable multiples
2. Determine upside/downside from current price
3. Assess your confidence level (0-100%)
4. Identify what has changed vs initial screen (if anything)

Respond with JSON:
```json
{{
  "ticker": "{ticker}",
  "current_price": <current price>,
  "intrinsic_value_low": <bear case value>,
  "intrinsic_value_mid": <base case value>,
  "intrinsic_value_high": <bull case value>,
  "upside_pct": <upside to midpoint as percentage>,
  "confidence": <0-100>,
  "verdict": "STRONG BUY|BUY|HOLD|SELL|STRONG SELL",
  "valuation_method": "DCF|Comps|Both",
  "key_assumptions": ["assumption 1", "assumption 2"],
  "changes_since_screen": "What has changed or 'No material changes'",
  "brief": "2-3 sentence summary for CIO"
}}
```"""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2048,
            system="You are the Fundamental Analysis Agent for ATLAS hedge fund. You value companies using rigorous financial analysis. Be precise with numbers. Always provide structured JSON output.",
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.content[0].text

        # Parse JSON
        if "```json" in raw:
            json_str = raw.split("```json")[1].split("```")[0]
        elif "```" in raw:
            json_str = raw.split("```")[1].split("```")[0]
        else:
            json_str = raw

        result = json.loads(json_str.strip())
        result["agent"] = "fundamental"
        result["analyzed_at"] = datetime.utcnow().isoformat()
        return result

    except Exception as e:
        logger.error(f"Fundamental agent error for {ticker}: {e}")
        return {
            "agent": "fundamental",
            "ticker": ticker,
            "error": str(e),
            "verdict": "ERROR"
        }


def run_sector_desk(ticker: str, sector: str, price_data: dict, client: anthropic.Anthropic) -> dict:
    """
    Step 2: Sector desk identifies near-term catalyst.
    """
    logger.info(f"[SECTOR DESK] Analyzing {ticker} ({sector})...")

    prompt = f"""TODAY'S DATE: March 5, 2026. Use current context. Reference upcoming Q1 2026 earnings, 2026 catalysts, and forward-looking events. Do not reference earnings dates from 2024 or 2025.

What is the near-term catalyst for {ticker}?

## Company Context (as of March 5, 2026)
- Ticker: {ticker}
- Sector: {price_data.get('sector', sector)}
- Industry: {price_data.get('industry', 'Unknown')}
- Current Price: ${price_data.get('price', 'N/A')}
- Next Earnings: {price_data.get('earnings_date', 'Unknown')}

## Your Task
Identify what will move this stock in the next 3-6 months. Not just "eventually" - what's the specific catalyst?

Consider:
1. Earnings catalysts - upcoming reports, guidance changes
2. Product launches - new products, services, features
3. Regulatory changes - FDA, FTC, antitrust, sector regulation
4. Macro tailwinds - rate cuts, sector rotation, economic trends
5. M&A activity - potential acquirer or acquisition target
6. Management changes - new CEO, activist involvement
7. Competitive dynamics - market share gains/losses

Respond with JSON:
```json
{{
  "ticker": "{ticker}",
  "primary_catalyst": "The #1 catalyst",
  "catalyst_type": "EARNINGS|PRODUCT|REGULATORY|MACRO|M&A|MANAGEMENT|COMPETITIVE",
  "catalyst_timing": "Specific timeframe (e.g., 'Q1 2026 earnings', 'March FDA decision')",
  "probability": <0-100>,
  "upside_if_catalyst_hits": "Expected price impact",
  "downside_if_catalyst_misses": "Expected price impact if it doesn't happen",
  "secondary_catalysts": ["catalyst 2", "catalyst 3"],
  "sector_context": "How sector dynamics affect this stock",
  "brief": "2-3 sentence summary for CIO"
}}
```"""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2048,
            system=f"You are the {sector.title()} Sector Desk Analyst for ATLAS hedge fund. You specialize in identifying catalysts and timing for stocks in your sector. Be specific about dates and events. Always provide structured JSON output.",
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.content[0].text

        if "```json" in raw:
            json_str = raw.split("```json")[1].split("```")[0]
        elif "```" in raw:
            json_str = raw.split("```")[1].split("```")[0]
        else:
            json_str = raw

        result = json.loads(json_str.strip())
        result["agent"] = "sector_desk"
        result["desk"] = sector
        result["analyzed_at"] = datetime.utcnow().isoformat()
        return result

    except Exception as e:
        logger.error(f"Sector desk error for {ticker}: {e}")
        return {
            "agent": "sector_desk",
            "ticker": ticker,
            "desk": sector,
            "error": str(e),
            "primary_catalyst": "ERROR"
        }


def run_adversarial_agent(ticker: str, fundamental: dict, sector: dict, client: anthropic.Anthropic) -> dict:
    """
    Step 3: CRO reviews the thesis - 25 years of experience protecting capital.
    """
    logger.info(f"[CRO] Reviewing thesis for {ticker}...")

    # Format portfolio for correlation analysis
    portfolio_str = "\n".join([
        f"  - {p['ticker']}: {p['size_pct']*100:.0f}% ({p['type']})"
        for p in CURRENT_PORTFOLIO['positions']
    ])

    prompt = f"""TODAY'S DATE: March 5, 2026

TRADE THESIS FOR REVIEW
=======================

Ticker: {ticker}
Proposed Action: BUY
Proposed Size: 5% of portfolio

BULL CASE FROM FUNDAMENTAL AGENT:
- Verdict: {fundamental.get('verdict', 'N/A')}
- Intrinsic Value: ${fundamental.get('intrinsic_value_mid', 'N/A')}
- Current Price: ${fundamental.get('current_price', 'N/A')}
- Upside: {fundamental.get('upside_pct', 'N/A')}%
- Confidence: {fundamental.get('confidence', 'N/A')}%
- Key Assumptions: {fundamental.get('key_assumptions', [])}
- Brief: {fundamental.get('brief', 'N/A')}

CATALYST FROM SECTOR DESK:
- Primary Catalyst: {sector.get('primary_catalyst', 'N/A')}
- Catalyst Type: {sector.get('catalyst_type', 'N/A')}
- Timing: {sector.get('catalyst_timing', 'N/A')}
- Probability: {sector.get('probability', 'N/A')}%
- Upside if hits: {sector.get('upside_if_catalyst_hits', 'N/A')}
- Downside if misses: {sector.get('downside_if_catalyst_misses', 'N/A')}
- Brief: {sector.get('brief', 'N/A')}

CURRENT PORTFOLIO:
{portfolio_str}

Total Equity Exposure: 20% (BE 15% + AVGO 5%)
Cash Available: 70% (in BIL)

YOUR TASK:
You are the Chief Risk Officer with 25 years of experience. You've lived through dot-com, GFC, COVID, and 2022. Review this thesis.

FIRST: Steelman the bull case. Prove you understand why the proponent believes this works.

SECOND: Identify every way this trade can lose money. Be SPECIFIC:
- What event in the next 30/60/90 days causes a 20%+ drawdown?
- Who is on the other side of this trade and why might they be right?
- What's the closest historical analogue and how did it end?
- Is the valuation discount real or a value trap?
- Is the catalyst priced in? Does this need "great" or is "good" enough?

THIRD: Make a clear decision - APPROVE, CONDITIONAL, or BLOCK.

Respond with JSON:
```json
{{
  "ticker": "{ticker}",
  "steelman": "Your articulation of why the bull case works - prove you understand it",
  "specific_risks": [
    {{
      "scenario": "Specific, dated scenario (e.g., 'If X happens by April 2026...')",
      "probability": "Your honest estimate as percentage",
      "impact": "Expected loss percentage"
    }}
  ],
  "historical_analogue": "The closest historical parallel and how it ended",
  "what_market_knows": "Why might the current price be right? What are bulls ignoring?",
  "who_is_short": "Who is on the other side of this trade and why might they be right?",
  "correlation_concerns": "How does this interact with existing BE and AVGO positions?",
  "verdict": "APPROVE|CONDITIONAL|BLOCK",
  "conditions": "If CONDITIONAL: specific modifications required. Otherwise null.",
  "would_change_mind": "What specific development would flip your verdict?",
  "one_line": "Your assessment in one brutally honest sentence"
}}
```"""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL_PREMIUM,
            max_tokens=3000,
            system="""You are the Chief Risk Officer of a $10 billion multi-strategy hedge fund. You have 25 years of experience. You lived through the dot-com crash, the GFC, the COVID crash, and the 2022 tech drawdown. You have seen every way a trade can go wrong.

Your job is to protect the fund from catastrophic loss. You are not a pessimist — you are a realist who has seen what happens when smart people convince themselves they're right and stop looking for reasons they might be wrong.

You hate lazy analysis. You hate generic risk factors. You hate identical assessments for different companies. Every company has a unique risk profile and you will find it.

Your nightmare scenario is not blocking a good trade. Your nightmare scenario is approving a trade that blows up the fund. You size your caution accordingly.

You are allowed to approve everything if everything genuinely deserves approval. You are allowed to block everything if nothing passes your bar. But you must justify each decision independently with specific reasoning, not template language.""",
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.content[0].text

        if "```json" in raw:
            json_str = raw.split("```json")[1].split("```")[0]
        elif "```" in raw:
            json_str = raw.split("```")[1].split("```")[0]
        else:
            json_str = raw

        result = json.loads(json_str.strip())
        result["agent"] = "adversarial"
        result["analyzed_at"] = datetime.utcnow().isoformat()
        return result

    except Exception as e:
        logger.error(f"Adversarial agent error for {ticker}: {e}")
        return {
            "agent": "adversarial",
            "ticker": ticker,
            "error": str(e),
            "risk_level": "UNKNOWN",
            "verdict": "ERROR"
        }


def run_cio_agent(ticker: str, fundamental: dict, sector: dict, adversarial: dict,
                  portfolio: dict, client: anthropic.Anthropic) -> dict:
    """
    Step 4: CIO synthesizes all views and makes sizing decision.
    """
    logger.info(f"[CIO] Synthesizing decision for {ticker}...")

    # Format portfolio
    portfolio_str = "\n".join([
        f"- {p['ticker']}: {p['size_pct']*100:.0f}% ({p['type']})"
        for p in portfolio['positions']
    ])

    # Format CRO risks for CIO
    cro_risks = adversarial.get('specific_risks', [])
    risks_str = "\n".join([
        f"  - {r.get('scenario', 'N/A')} (Prob: {r.get('probability', 'N/A')}, Impact: {r.get('impact', 'N/A')})"
        for r in cro_risks[:3]  # Top 3 risks
    ]) if cro_risks else "None specified"

    prompt = f"""TODAY'S DATE: March 5, 2026. Make decisions based on current market conditions.

Synthesize the agent views and make a sizing decision for {ticker}.

## Agent Views

### Fundamental Agent
- Verdict: {fundamental.get('verdict', 'N/A')}
- Intrinsic Value: ${fundamental.get('intrinsic_value_mid', 'N/A')}
- Upside: {fundamental.get('upside_pct', 'N/A')}%
- Confidence: {fundamental.get('confidence', 'N/A')}%
- Key Assumptions: {fundamental.get('key_assumptions', [])}
- Brief: {fundamental.get('brief', 'N/A')}

### Sector Desk
- Primary Catalyst: {sector.get('primary_catalyst', 'N/A')}
- Catalyst Type: {sector.get('catalyst_type', 'N/A')}
- Timing: {sector.get('catalyst_timing', 'N/A')}
- Probability: {sector.get('probability', 'N/A')}%
- Brief: {sector.get('brief', 'N/A')}

### Chief Risk Officer Assessment
- Verdict: {adversarial.get('verdict', 'N/A')}
- Steelman (CRO understands the bull case): {adversarial.get('steelman', 'N/A')[:200]}...
- Historical Analogue: {adversarial.get('historical_analogue', 'N/A')}
- What Market Knows: {adversarial.get('what_market_knows', 'N/A')}
- Specific Risks:
{risks_str}
- Conditions (if CONDITIONAL): {adversarial.get('conditions', 'None')}
- One-Line Assessment: {adversarial.get('one_line', 'N/A')}

## Current Portfolio
{portfolio_str}

Available Cash: {portfolio['cash_pct']}% (in BIL, deployable)

## Your Task
As CIO, weigh all perspectives and decide:
1. Should we add {ticker}?
2. If yes, what position size? (Deploy from BIL cash)
3. If no, why not?

Consider:
- Risk/reward based on all agent views
- Portfolio concentration (don't overweight any sector)
- Catalyst timing (is now the right time?)
- Position sizing relative to conviction

Respond with JSON:
```json
{{
  "ticker": "{ticker}",
  "decision": "BUY|PASS|WATCH",
  "position_size_pct": <0-10, or 0 if PASS>,
  "deploy_from": "BIL",
  "rationale": "2-3 sentence rationale synthesizing agent views",
  "key_factors": ["Factor 1 that drove decision", "Factor 2"],
  "conditions": ["Condition 1 for entry", "Condition 2"],
  "stop_loss_pct": <negative percentage>,
  "target_price": <price target>,
  "time_horizon": "1-3 months|3-6 months|6-12 months",
  "confidence": <0-100>,
  "portfolio_impact": "How this changes portfolio composition",
  "next_review": "When to reassess this decision"
}}
```"""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL_PREMIUM,  # Use premium model for CIO
            max_tokens=2048,
            system="You are the Chief Investment Officer of ATLAS hedge fund. You synthesize all agent views into portfolio decisions. You are disciplined, risk-aware, and decisive. You deploy capital from the 70% BIL cash position based on conviction. Typical position sizes: 3-5% for moderate conviction, 5-7% for high conviction. Always provide structured JSON output.",
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.content[0].text

        if "```json" in raw:
            json_str = raw.split("```json")[1].split("```")[0]
        elif "```" in raw:
            json_str = raw.split("```")[1].split("```")[0]
        else:
            json_str = raw

        result = json.loads(json_str.strip())
        result["agent"] = "cio"
        result["analyzed_at"] = datetime.utcnow().isoformat()
        return result

    except Exception as e:
        logger.error(f"CIO agent error for {ticker}: {e}")
        return {
            "agent": "cio",
            "ticker": ticker,
            "error": str(e),
            "decision": "ERROR"
        }


def run_gauntlet(ticker: str) -> dict:
    """
    Run a single ticker through the full 4-agent gauntlet.
    """
    logger.info(f"\n{'='*60}")
    logger.info(f"GAUNTLET: {ticker}")
    logger.info(f"{'='*60}")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    sector = TICKER_SECTORS.get(ticker, "technology")

    # Get current price data
    price_data = get_current_price(ticker)

    # Run all 4 agents in sequence
    fundamental = run_fundamental_agent(ticker, price_data, client)
    sector_desk = run_sector_desk(ticker, sector, price_data, client)
    adversarial = run_adversarial_agent(ticker, fundamental, sector_desk, client)
    cio = run_cio_agent(ticker, fundamental, sector_desk, adversarial, CURRENT_PORTFOLIO, client)

    # Compile full result
    result = {
        "ticker": ticker,
        "sector": sector,
        "price_data": price_data,
        "gauntlet_run_at": datetime.utcnow().isoformat(),
        "agents": {
            "fundamental": fundamental,
            "sector_desk": sector_desk,
            "adversarial": adversarial,
            "cio": cio
        },
        "summary": {
            "fundamental_verdict": fundamental.get("verdict", "ERROR"),
            "fundamental_upside": fundamental.get("upside_pct", "N/A"),
            "fundamental_confidence": fundamental.get("confidence", "N/A"),
            "catalyst": sector_desk.get("primary_catalyst", "ERROR"),
            "catalyst_timing": sector_desk.get("catalyst_timing", "N/A"),
            "cro_verdict": adversarial.get("verdict", "ERROR"),
            "cro_one_line": adversarial.get("one_line", "N/A"),
            "cro_historical_analogue": adversarial.get("historical_analogue", "N/A"),
            "cio_decision": cio.get("decision", "ERROR"),
            "position_size": cio.get("position_size_pct", 0),
        }
    }

    # Save to file
    output_file = GAUNTLET_DIR / f"{ticker}.json"
    with open(output_file, "w") as f:
        json.dump(result, f, indent=2, default=str)

    logger.info(f"Saved: {output_file}")

    return result


def print_summary(results: list[dict]):
    """Print a formatted summary table of all gauntlet results."""
    print("\n" + "="*120)
    print("AGENT GAUNTLET RESULTS — MARCH 5, 2026")
    print("="*120)
    print(f"{'TICKER':<8} {'UPSIDE':<8} {'CRO VERDICT':<12} {'CIO':<10} {'CRO ONE-LINE ASSESSMENT':<80}")
    print("-"*120)

    approved = []
    conditional = []
    blocked = []

    for r in results:
        s = r["summary"]
        ticker = r["ticker"]

        # Format fields
        upside = f"+{s.get('fundamental_upside', 'N/A')}%"[:7]
        cro_verdict = s.get("cro_verdict", "ERR")[:11]
        one_line = str(s.get("cro_one_line", "N/A"))[:78]

        cio_decision = s.get("cio_decision", "ERR")
        size = s.get("position_size", 0)
        if cio_decision == "BUY" and size:
            cio_str = f"BUY {size}%"
        else:
            cio_str = cio_decision[:9]

        print(f"{ticker:<8} {upside:<8} {cro_verdict:<12} {cio_str:<10} {one_line}")

        if cio_decision == "BUY":
            approved.append((ticker, size))
        if cro_verdict == "CONDITIONAL":
            conditional.append(ticker)
        if cro_verdict == "BLOCK":
            blocked.append(ticker)

    print("-"*120)

    # CRO Summary
    print(f"\nCRO BREAKDOWN:")
    print(f"  APPROVE: {len([r for r in results if r['summary'].get('cro_verdict') == 'APPROVE'])}")
    print(f"  CONDITIONAL: {len(conditional)} {conditional if conditional else ''}")
    print(f"  BLOCK: {len(blocked)} {blocked if blocked else ''}")

    # CIO Summary
    if approved:
        print(f"\nCIO APPROVED FOR PORTFOLIO: {[t[0] for t in approved]}")
        total_deploy = sum(t[1] for t in approved)
        print(f"DEPLOY: {total_deploy}% from BIL cash")
    else:
        print("\nNO NEW POSITIONS APPROVED BY CIO")

    print("\n" + "="*120)


def main():
    """Run the gauntlet on all 7 tickers."""
    tickers = ["APO", "GDDY", "ADBE", "GOOG", "ANET", "BLK", "CMCSA"]

    print("\n" + "="*60)
    print("ATLAS AGENT GAUNTLET")
    print("Source → Analyse → Debate → Decide")
    print("="*60)
    print(f"\nProcessing {len(tickers)} tickers: {', '.join(tickers)}")
    print(f"Output directory: {GAUNTLET_DIR}\n")

    results = []
    for ticker in tickers:
        try:
            result = run_gauntlet(ticker)
            results.append(result)
        except Exception as e:
            logger.error(f"Failed to process {ticker}: {e}")
            results.append({
                "ticker": ticker,
                "error": str(e),
                "summary": {
                    "fundamental_verdict": "ERROR",
                    "catalyst": "ERROR",
                    "risk_level": "ERROR",
                    "cio_decision": "ERROR"
                }
            })

    # Print summary
    print_summary(results)

    # Save combined results
    combined_file = GAUNTLET_DIR / "gauntlet_summary.json"
    with open(combined_file, "w") as f:
        json.dump({
            "run_at": datetime.utcnow().isoformat(),
            "tickers": tickers,
            "results": results
        }, f, indent=2, default=str)

    print(f"\nFull results saved to: {combined_file}")
    print("\nThis is the ATLAS investment process in action.")
    print("Every step documented. Every agent view recorded.")


if __name__ == "__main__":
    main()
