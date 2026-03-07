#!/usr/bin/env python3
"""
Run a ticker through the full CRO gauntlet: Fundamental -> Sector -> CRO -> CIO
Skill: /gauntlet TICKER
"""
import argparse
import json
import os
import anthropic
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Load environment
load_dotenv(Path(__file__).parent.parent / ".env")

STATE_DIR = Path(__file__).parent.parent / "data" / "state"
GAUNTLET_DIR = STATE_DIR / "gauntlet"
GAUNTLET_DIR.mkdir(parents=True, exist_ok=True)

client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

MODEL = "claude-sonnet-4-20250514"


def call_agent(system_prompt: str, user_message: str) -> str:
    """Call Claude with a specific agent persona."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}]
    )
    return response.content[0].text


def load_portfolio_context() -> str:
    """Load current portfolio for context."""
    positions_file = STATE_DIR / "positions.json"
    try:
        with open(positions_file) as f:
            data = json.load(f)

        if isinstance(data, dict) and 'positions' in data:
            positions = data['positions']
        else:
            positions = data if isinstance(data, list) else list(data.values())

        lines = []
        for pos in positions:
            ticker = pos.get('ticker', '?')
            direction = pos.get('direction', 'LONG')
            alloc = pos.get('allocation_pct', 0)
            thesis = pos.get('thesis', '')[:60]
            lines.append(f"  {ticker}: {direction} {alloc}% — {thesis}")

        return "\n".join(lines)
    except Exception:
        return "No current positions"


def run_gauntlet(ticker: str) -> dict:
    """Run a ticker through the full 4-agent gauntlet."""

    print(f"\n{'='*70}")
    print(f"  ATLAS GAUNTLET: {ticker}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*70}")

    results = {
        "ticker": ticker,
        "date": datetime.now().isoformat(),
        "agents": {}
    }

    portfolio_context = load_portfolio_context()
    today = datetime.now().strftime('%Y-%m-%d')

    # ================================================================
    # STEP 1: FUNDAMENTAL AGENT
    # ================================================================
    print(f"\n[1/4] Fundamental Agent analysing {ticker}...")

    fundamental_prompt = """You are a fundamental valuation analyst. Use rigorous DCF, comps, and precedent transaction analysis. Be specific with numbers.

OUTPUT FORMAT (JSON):
{
  "ticker": "SYMBOL",
  "intrinsic_value": 123.45,
  "current_price": 100.00,
  "upside_pct": 23.4,
  "confidence": 85,
  "valuation_method": "DCF with 10% WACC, 3% terminal growth",
  "key_drivers": ["driver1", "driver2", "driver3"],
  "thesis": "2-3 sentence investment thesis",
  "risks": ["risk1", "risk2"]
}"""

    fundamental_user = f"""Analyse {ticker} as of {today}.

Provide:
1. DCF-based intrinsic value estimate
2. Comparable company analysis
3. Upside/downside percentage
4. Confidence level (0-100)
5. 3-sentence investment thesis
6. Key risks

Use current market data. Be specific with numbers. Respond with ONLY valid JSON."""

    try:
        fundamental_raw = call_agent(fundamental_prompt, fundamental_user)
        results["agents"]["fundamental"] = fundamental_raw

        # Try to parse JSON
        try:
            fundamental_json = json.loads(fundamental_raw.strip().replace('```json', '').replace('```', ''))
            fundamental_thesis = fundamental_json.get('thesis', fundamental_raw[:300])
            fundamental_value = fundamental_json.get('intrinsic_value', 'N/A')
            fundamental_confidence = fundamental_json.get('confidence', 'N/A')
        except:
            fundamental_thesis = fundamental_raw[:300]
            fundamental_value = 'N/A'
            fundamental_confidence = 'N/A'

        print(f"  Intrinsic Value: ${fundamental_value}")
        print(f"  Confidence: {fundamental_confidence}%")
        print(f"  Thesis: {fundamental_thesis[:80]}...")
    except Exception as e:
        print(f"  Error: {e}")
        fundamental_raw = str(e)
        results["agents"]["fundamental"] = f"Error: {e}"

    # ================================================================
    # STEP 2: SECTOR DESK
    # ================================================================
    print(f"\n[2/4] Sector Desk identifying catalysts for {ticker}...")

    sector_prompt = """You are a sector analyst specialist. Identify the key near-term catalysts for stocks — earnings dates, product launches, regulatory changes, or macro tailwinds. Be specific about dates and expected impact.

OUTPUT FORMAT (JSON):
{
  "ticker": "SYMBOL",
  "sector": "Technology",
  "catalyst": "Description of key catalyst",
  "catalyst_date": "2026-03-15",
  "expected_impact": "+15% on positive outcome",
  "probability": 70,
  "sector_tailwinds": ["tailwind1", "tailwind2"],
  "sector_headwinds": ["headwind1", "headwind2"],
  "peer_comparison": "How this compares to sector peers"
}"""

    sector_user = f"""What is the key catalyst for {ticker} in the next 90 days?

Today is {today}. Be specific about:
1. The exact catalyst event
2. Expected date or date range
3. Expected price impact if positive/negative
4. Probability of positive outcome
5. How this compares to sector peers

Respond with ONLY valid JSON."""

    try:
        sector_raw = call_agent(sector_prompt, sector_user)
        results["agents"]["sector"] = sector_raw

        try:
            sector_json = json.loads(sector_raw.strip().replace('```json', '').replace('```', ''))
            catalyst = sector_json.get('catalyst', sector_raw[:200])
            catalyst_date = sector_json.get('catalyst_date', 'N/A')
        except:
            catalyst = sector_raw[:200]
            catalyst_date = 'N/A'

        print(f"  Catalyst: {catalyst[:70]}...")
        print(f"  Date: {catalyst_date}")
    except Exception as e:
        print(f"  Error: {e}")
        sector_raw = str(e)
        results["agents"]["sector"] = f"Error: {e}"

    # ================================================================
    # STEP 3: CRO (ADVERSARIAL)
    # ================================================================
    print(f"\n[3/4] CRO attacking thesis for {ticker}...")

    cro_prompt = """You are the Chief Risk Officer of a $10 billion hedge fund. 25 years experience. You've seen dot-com, GFC, COVID, 2022.

Your job:
1. STEELMAN the bull case — prove you understand it before attacking
2. IDENTIFY every specific, dated, quantified risk
3. FIND the historical analogue — what similar setup happened and how did it end?
4. MAKE A VERDICT: APPROVE / CONDITIONAL / BLOCK

OUTPUT FORMAT (JSON):
{
  "ticker": "SYMBOL",
  "steelman": "Why the bull case works",
  "specific_risks": [
    {"scenario": "Specific risk", "probability": "20%", "impact": "-25%"}
  ],
  "historical_analogue": "The closest historical parallel",
  "what_market_knows": "Why the current price might be right",
  "correlation_concerns": "How this interacts with existing positions",
  "verdict": "APPROVE|CONDITIONAL|BLOCK",
  "conditions": "Required modifications if CONDITIONAL",
  "would_change_mind": "What would flip your verdict",
  "one_line": "One brutally honest sentence"
}"""

    cro_user = f"""Review this trade: {ticker}

FUNDAMENTAL VIEW:
{fundamental_raw[:800]}

SECTOR VIEW:
{sector_raw[:500]}

CURRENT PORTFOLIO:
{portfolio_context}

Today is {today}.

Steelman the bull case, then attack it. Find the historical analogue. Give your verdict: APPROVE / CONDITIONAL / BLOCK.

Respond with ONLY valid JSON."""

    try:
        cro_raw = call_agent(cro_prompt, cro_user)
        results["agents"]["cro"] = cro_raw

        try:
            cro_json = json.loads(cro_raw.strip().replace('```json', '').replace('```', ''))
            verdict = cro_json.get('verdict', 'N/A')
            one_line = cro_json.get('one_line', cro_raw[:100])
            analogue = cro_json.get('historical_analogue', 'N/A')
        except:
            verdict = 'N/A'
            one_line = cro_raw[:100]
            analogue = 'N/A'

        # Color code verdict
        if verdict == 'APPROVE':
            color = '\033[92m'  # Green
        elif verdict == 'CONDITIONAL':
            color = '\033[93m'  # Yellow
        else:
            color = '\033[91m'  # Red
        reset = '\033[0m'

        print(f"  Verdict: {color}{verdict}{reset}")
        print(f"  Analogue: {analogue[:60]}...")
        print(f"  One Line: {one_line[:70]}...")
    except Exception as e:
        print(f"  Error: {e}")
        cro_raw = str(e)
        results["agents"]["cro"] = f"Error: {e}"
        verdict = 'BLOCK'

    # ================================================================
    # STEP 4: CIO (FINAL DECISION)
    # ================================================================
    print(f"\n[4/4] CIO making final decision on {ticker}...")

    cio_prompt = """You are the CIO of a $1M paper trading hedge fund. You synthesise all agent views and make final decisions.

Rules:
- Max single position: 15%
- Min confidence threshold: 80%
- Every position needs a stop loss
- Cash buffer: minimum 10%

OUTPUT FORMAT (JSON):
{
  "ticker": "SYMBOL",
  "decision": "BUY|WATCH|PASS|SHORT",
  "size_pct": 5,
  "confidence": 85,
  "entry_price": 123.45,
  "stop_loss": 105.00,
  "target_price": 160.00,
  "thesis_summary": "One paragraph summary",
  "invalidation": "What would make us exit",
  "timing": "Enter now / wait for catalyst / scale in"
}"""

    cio_user = f"""FINAL DECISION REQUIRED: {ticker}

FUNDAMENTAL VIEW:
{fundamental_raw[:600]}

SECTOR CATALYST:
{sector_raw[:400]}

CRO VERDICT:
{cro_raw[:600]}

CURRENT PORTFOLIO:
{portfolio_context}

Make your final decision: BUY (with size) / WATCH / PASS / SHORT

Include entry price, stop loss, and target. Respond with ONLY valid JSON."""

    try:
        cio_raw = call_agent(cio_prompt, cio_user)
        results["agents"]["cio"] = cio_raw

        try:
            cio_json = json.loads(cio_raw.strip().replace('```json', '').replace('```', ''))
            decision = cio_json.get('decision', 'N/A')
            size = cio_json.get('size_pct', 0)
            confidence = cio_json.get('confidence', 0)
            stop_loss = cio_json.get('stop_loss', 'N/A')
            target = cio_json.get('target_price', 'N/A')
            thesis = cio_json.get('thesis_summary', cio_raw[:200])
        except:
            decision = 'PASS'
            size = 0
            confidence = 0
            stop_loss = 'N/A'
            target = 'N/A'
            thesis = cio_raw[:200]

        # Color code decision
        if decision in ['BUY', 'SHORT']:
            color = '\033[92m' if confidence >= 80 else '\033[93m'
        else:
            color = '\033[93m'
        reset = '\033[0m'

        print(f"  Decision: {color}{decision}{reset}")
        print(f"  Size: {size}%")
        print(f"  Confidence: {confidence}%")
        print(f"  Stop Loss: ${stop_loss}")
        print(f"  Target: ${target}")
        print(f"  Thesis: {thesis[:80]}...")

        results["final_decision"] = {
            "decision": decision,
            "size_pct": size,
            "confidence": confidence,
            "stop_loss": stop_loss,
            "target_price": target
        }
    except Exception as e:
        print(f"  Error: {e}")
        results["agents"]["cio"] = f"Error: {e}"

    # ================================================================
    # SAVE RESULTS
    # ================================================================
    output_file = GAUNTLET_DIR / f"{ticker}.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\n{'='*70}")
    print(f"  GAUNTLET COMPLETE: {ticker}")
    print(f"  Results saved to: {output_file}")
    print(f"{'='*70}")

    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run ticker through full CRO gauntlet')
    parser.add_argument('--ticker', '-t', required=True, help='Ticker symbol to analyse')
    args = parser.parse_args()

    run_gauntlet(args.ticker.upper())
