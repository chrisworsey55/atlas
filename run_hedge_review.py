#!/usr/bin/env python3
"""
ATLAS Hedge Position CRO Review
Runs hedge positions through the Chief Risk Officer agent for review.
"""
import json
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# Load .env
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv(Path.home() / "gic-underwriting" / ".env")

import anthropic

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-20250514"

GAUNTLET_DIR = Path(__file__).resolve().parent.parent / "data" / "state" / "gauntlet"
GAUNTLET_DIR.mkdir(parents=True, exist_ok=True)

# Current portfolio context
CURRENT_PORTFOLIO = """Current Portfolio (as of March 5, 2026):
  - BIL: 61% (cash equivalent)
  - BE: 15% (Bloom Energy - AI power infrastructure)
  - TLT: 10% SHORT (betting against long-term treasuries)
  - AVGO: 5% (Broadcom - AI semiconductors)
  - ADBE: 3% (Adobe - creative software)
  - GOOG: 3% (Alphabet - search/cloud)
  - APO: 3% (Apollo - alternative assets)

Total Equity Long Exposure: 29%
Total AI/Infrastructure Exposure: 23% (BE + AVGO + ADBE + GOOG)
Crisis Protection: ZERO"""

CRO_SYSTEM_PROMPT = """You are the Chief Risk Officer of a $10 billion multi-strategy hedge fund. You have 25 years of experience. You lived through the dot-com crash, the GFC, the COVID crash, and the 2022 tech drawdown. You have seen every way a trade can go wrong.

Your job is to protect the fund from catastrophic loss. You are not a pessimist — you are a realist who has seen what happens when smart people convince themselves they're right and stop looking for reasons they might be wrong.

When presented with a trade thesis, you do the following:

FIRST: You steelman the bull case. You articulate why the proponent believes this trade works, better than they can themselves. This proves you understand the thesis before you attack it.

SECOND: You identify every way this trade can lose money. Not generic risks — specific, dated, quantified scenarios. Not "macro could deteriorate" but "if the Fed cuts rates by 100bps before June because of a banking crisis, this position loses approximately X% because Y." You think about:
- What event in the next 30/60/90 days would cause a 20%+ drawdown?
- What correlation does this position have with existing portfolio positions that isn't obvious?
- What is the consensus view, and what happens if consensus is wrong?
- Who is on the other side of this trade and why might they be right?
- What happened to similar setups historically? Find the closest analogue and study how it ended.
- Is the valuation discount real or is it a value trap? What does the market know that the bull case is ignoring?
- Is the catalyst priced in? Is "good" good enough, or does this need "great" to work?

THIRD: You make a clear recommendation. Not a score — a decision in plain English:
- APPROVE: The risks are real but manageable and the asymmetry favours the bull case. State what would make you change your mind.
- CONDITIONAL: You'd approve this with modifications — smaller size, a hedge, a stop loss, or waiting for a specific event.
- BLOCK: The risks are too severe or too correlated with existing positions. Explain exactly what would need to change for you to approve.

You are allowed to approve everything if everything genuinely deserves approval. You are allowed to block everything if nothing passes your bar. But you must justify each decision independently with specific reasoning, not template language.

You hate lazy analysis. You hate generic risk factors. You hate identical assessments for different companies. Every company has a unique risk profile and you will find it.

Your nightmare scenario is not blocking a good trade. Your nightmare scenario is approving a trade that blows up the fund. You size your caution accordingly.

OUTPUT FORMAT:
Respond with valid JSON containing your analysis:

```json
{
  "ticker": "SYMBOL",
  "direction": "LONG|SHORT",
  "steelman": "Your articulation of why the bull/bear case works — prove you understand it",
  "specific_risks": [
    {
      "scenario": "Specific, dated scenario with quantified impact",
      "probability": "Your honest probability estimate as a percentage",
      "impact": "Expected loss if this scenario occurs"
    }
  ],
  "historical_analogue": "The closest historical parallel and how it ended",
  "what_the_market_knows": "Why might the current price be right? What is the thesis ignoring?",
  "who_is_on_other_side": "Who disagrees with this trade and why might they be right?",
  "correlation_concerns": "How does this interact with existing portfolio positions?",
  "verdict": "APPROVE|CONDITIONAL|BLOCK",
  "conditions": "If CONDITIONAL: what modifications are required? If APPROVE/BLOCK: null",
  "would_change_mind": "What specific development would flip your verdict?",
  "one_line": "Your assessment in one brutally honest sentence"
}
```
"""


def run_cro_review(ticker: str, direction: str, prompt: str, client: anthropic.Anthropic) -> dict:
    """Run a position through the CRO for review."""
    print(f"\n{'='*60}")
    print(f"[CRO] Reviewing {ticker} {direction}")
    print(f"{'='*60}")

    full_prompt = f"""TODAY'S DATE: March 5, 2026

{CURRENT_PORTFOLIO}

HEDGE POSITION FOR REVIEW
=========================

{prompt}

Respond with ONLY valid JSON matching the schema in your system prompt."""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=3000,
            system=CRO_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": full_prompt}]
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
        result["agent"] = "cro"
        result["reviewed_at"] = datetime.utcnow().isoformat()
        return result

    except Exception as e:
        print(f"Error: {e}")
        return {
            "ticker": ticker,
            "direction": direction,
            "error": str(e),
            "verdict": "ERROR"
        }


def run_cio_decision(cro_results: list, client: anthropic.Anthropic) -> dict:
    """CIO makes final decision on hedges."""
    print(f"\n{'='*60}")
    print(f"[CIO] Making final decision on hedges")
    print(f"{'='*60}")

    # Format CRO verdicts
    cro_summary = ""
    for r in cro_results:
        cro_summary += f"""
{r['ticker']} {r['direction']}:
- Verdict: {r.get('verdict', 'ERROR')}
- Steelman: {r.get('steelman', 'N/A')[:200]}...
- Key Risk: {r.get('specific_risks', [{}])[0].get('scenario', 'N/A') if r.get('specific_risks') else 'N/A'}
- Historical Analogue: {r.get('historical_analogue', 'N/A')}
- One-Line: {r.get('one_line', 'N/A')}
- Conditions: {r.get('conditions', 'None')}
"""

    prompt = f"""TODAY'S DATE: March 5, 2026

{CURRENT_PORTFOLIO}

CRO HEDGE REVIEWS
=================
{cro_summary}

YOUR TASK AS CIO:
The CRO has reviewed three hedge positions: GLD long 3%, GLW short 2%, CIEN short 2%.

Given our current portfolio has ZERO downside protection and the adversarial agent has repeatedly flagged our AI concentration risk (23% in BE, AVGO, ADBE, GOOG), should we execute these hedges?

Consider:
1. Do we need crisis protection? Our last GLD trade lost $6K.
2. Do the shorts actually hedge our AI longs, or add new risk?
3. What's the cost of being wrong on each position?
4. Is now the right time, or should we wait for better entry?

Respond with JSON:
```json
{{
  "decision_summary": "Overall verdict on the hedge package",
  "positions": [
    {{
      "ticker": "GLD",
      "direction": "LONG",
      "decision": "EXECUTE|PASS|MODIFY",
      "size_pct": <0-5>,
      "rationale": "Why this decision"
    }},
    {{
      "ticker": "GLW",
      "direction": "SHORT",
      "decision": "EXECUTE|PASS|MODIFY",
      "size_pct": <0-5>,
      "rationale": "Why this decision"
    }},
    {{
      "ticker": "CIEN",
      "direction": "SHORT",
      "decision": "EXECUTE|PASS|MODIFY",
      "size_pct": <0-5>,
      "rationale": "Why this decision"
    }}
  ],
  "total_hedge_allocation": <total % allocated to hedges>,
  "portfolio_impact": "How this changes portfolio risk profile",
  "alternative_hedges": "If passing on any, what alternatives would you recommend?",
  "timing_considerations": "Should we execute now or wait?"
}}
```"""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2000,
            system="You are the Chief Investment Officer of ATLAS hedge fund. You make final portfolio decisions after considering all agent views. You are disciplined, risk-aware, and decisive. You learned from the $6K GLD loss that hedges need proper timing and thesis, not panic buying.",
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
        result["decided_at"] = datetime.utcnow().isoformat()
        return result

    except Exception as e:
        print(f"Error: {e}")
        return {"error": str(e), "decision_summary": "ERROR"}


def main():
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Define the three hedge positions
    hedges = [
        {
            "ticker": "GLD",
            "direction": "LONG",
            "prompt": """Ticker: GLD (SPDR Gold Shares ETF)
Direction: LONG
Proposed Size: 3% of portfolio ($30,000)
Entry Price: $473

CONTEXT:
We want to add GLD at $473 as a 3% portfolio hedge.

History: We previously bought GLD at $490 during the Iran spike and sold at $468 for a $6K loss. That trade was made without proper process — panic buying on headlines.

Current situation:
- Gold spot at $5,135/oz, pulled back 7% from all-time highs of $5,595
- Iran conflict ongoing but not escalating
- Our portfolio is 29% long equities and AI infrastructure
- We have a TLT short (betting on higher rates)
- We have ZERO crisis protection currently

Thesis: Portfolio insurance against geopolitical escalation or market dislocation. Uncorrelated to our AI/tech exposure.

Steelman the bull case for GLD as a hedge, identify every way this loses money, and give your verdict."""
        },
        {
            "ticker": "GLW",
            "direction": "SHORT",
            "prompt": """Ticker: GLW (Corning Inc)
Direction: SHORT
Proposed Size: 2% of portfolio ($20,000)
Entry Price: $148

CONTEXT:
Our fundamental agent screened the S&P 500 and rated GLW as the MOST OVERVALUED stock:
- Current Price: $148
- Intrinsic Value: $85
- Overvaluation: 42%
- Confidence: 85%

What Corning does:
- Fiber optic cables for data centers and telecom
- Display glass for TVs and smartphones
- Specialty glass for auto and life sciences

AI Infrastructure Hype Thesis: GLW has rallied on AI data center buildout narrative (fiber optic demand). Our fundamental agent believes this is overdone — the multiple expansion isn't justified by actual earnings growth.

Portfolio Hedge Angle: This short hedges our AI long exposure in AVGO (5%), BE (15%), and our pending ANET position. If AI infrastructure spending disappoints, our longs lose but this short gains.

Steelman the bull case for GLW, identify every way this short goes wrong, and give your verdict."""
        },
        {
            "ticker": "CIEN",
            "direction": "SHORT",
            "prompt": """Ticker: CIEN (Ciena Corporation)
Direction: SHORT
Proposed Size: 2% of portfolio ($20,000)
Entry Price: $333

CONTEXT:
Our fundamental agent rated CIEN as the SECOND MOST OVERVALUED stock in S&P 500:
- Current Price: $333
- Intrinsic Value: $195
- Overvaluation: 41%
- Confidence: 85%

What Ciena does:
- Optical networking equipment
- Network automation software
- Subsea cable systems

AI Infrastructure Hype Thesis: Same as GLW — CIEN has rallied on AI data center networking demand. Our fundamental agent believes current valuation prices in unrealistic growth expectations.

Portfolio Hedge Angle: Like GLW, this short hedges our AI infrastructure longs. If the AI capex cycle disappoints or pauses, this short should profit while our longs decline.

Steelman the bull case for CIEN, identify every way this short goes wrong, and give your verdict."""
        }
    ]

    # Run each through CRO
    cro_results = []
    for hedge in hedges:
        result = run_cro_review(
            hedge["ticker"],
            hedge["direction"],
            hedge["prompt"],
            client
        )
        cro_results.append(result)

        # Save individual result
        output_file = GAUNTLET_DIR / f"{hedge['ticker']}_hedge.json"
        with open(output_file, "w") as f:
            json.dump(result, f, indent=2)
        print(f"Saved: {output_file}")

    # Run CIO decision
    cio_result = run_cio_decision(cro_results, client)

    # Save CIO decision
    cio_file = GAUNTLET_DIR / "hedge_cio_decision.json"
    with open(cio_file, "w") as f:
        json.dump(cio_result, f, indent=2)
    print(f"\nSaved: {cio_file}")

    # Print summary
    print("\n" + "="*80)
    print("HEDGE REVIEW SUMMARY")
    print("="*80)

    for r in cro_results:
        print(f"\n{r['ticker']} {r['direction']}:")
        print(f"  Verdict: {r.get('verdict', 'ERROR')}")
        print(f"  One-Line: {r.get('one_line', 'N/A')}")
        if r.get('conditions'):
            print(f"  Conditions: {r.get('conditions')}")

    print(f"\n{'='*80}")
    print("CIO DECISION")
    print("="*80)
    print(f"\nSummary: {cio_result.get('decision_summary', 'ERROR')}")
    print(f"Total Hedge Allocation: {cio_result.get('total_hedge_allocation', 0)}%")

    for pos in cio_result.get('positions', []):
        print(f"\n{pos['ticker']} {pos['direction']}:")
        print(f"  Decision: {pos['decision']}")
        print(f"  Size: {pos['size_pct']}%")
        print(f"  Rationale: {pos['rationale']}")

    # Save combined results
    combined_file = GAUNTLET_DIR / "hedge_review_complete.json"
    with open(combined_file, "w") as f:
        json.dump({
            "reviewed_at": datetime.utcnow().isoformat(),
            "cro_reviews": cro_results,
            "cio_decision": cio_result
        }, f, indent=2)
    print(f"\nFull results saved to: {combined_file}")


if __name__ == "__main__":
    main()
