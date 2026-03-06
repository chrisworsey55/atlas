"""
CRO Gauntlet Runner
Runs the full 4-step investment gauntlet:
1. Fundamental Agent - confirms/refutes valuation thesis
2. Sector Desk - identifies catalysts (up or down)
3. CRO (Adversarial) - steelmans opposition, finds all ways to lose money
4. CIO - final sizing decision given portfolio context

Usage:
  python -m agents.cro_gauntlet --tickers NOW,CRM,UNH --direction LONG
  python -m agents.cro_gauntlet --tickers STX,GLW,AAL --direction SHORT
"""
import json
import logging
import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any

import anthropic
import yfinance as yf

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL
from agents.prompts.adversarial_agent import SYSTEM_PROMPT as CRO_SYSTEM_PROMPT
from agents.prompts.cio_agent import SYSTEM_PROMPT as CIO_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# Output directory
GAUNTLET_DIR = Path(__file__).resolve().parent.parent / "data" / "state" / "gauntlet"
GAUNTLET_DIR.mkdir(parents=True, exist_ok=True)


def get_current_price(ticker: str) -> float:
    """Get current price for a ticker."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info or {}
        return info.get("currentPrice") or info.get("regularMarketPrice") or 0
    except Exception as e:
        logger.warning(f"Could not get price for {ticker}: {e}")
        return 0


def get_sector(ticker: str) -> str:
    """Get sector for a ticker."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info or {}
        return info.get("sector", "Unknown")
    except Exception:
        return "Unknown"


def load_sp500_valuation(ticker: str) -> Optional[dict]:
    """Load valuation from the S&P 500 screen results."""
    valuations_file = Path(__file__).resolve().parent.parent / "data" / "state" / "sp500_valuations.json"
    if valuations_file.exists():
        try:
            with open(valuations_file, "r") as f:
                data = json.load(f)
                for item in data:
                    if item.get("ticker") == ticker:
                        return item
        except Exception as e:
            logger.warning(f"Could not load SP500 valuations: {e}")
    return None


class GauntletRunner:
    """Runs the full 4-step CRO gauntlet on a trade thesis."""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def run_fundamental_check(self, ticker: str, direction: str,
                               existing_valuation: dict = None) -> dict:
        """
        Step 1: Fundamental agent confirms/refutes the thesis at current price.
        """
        logger.info(f"[GAUNTLET] Step 1: Fundamental check for {ticker} ({direction})")

        # Get current price
        current_price = get_current_price(ticker)

        # Use existing valuation if available
        if existing_valuation:
            synthesis = existing_valuation.get("synthesis", {})
            return {
                "ticker": ticker,
                "direction": direction,
                "current_price": current_price,
                "intrinsic_value": synthesis.get("intrinsic_value_midpoint"),
                "upside_pct": synthesis.get("upside_to_midpoint_pct"),
                "verdict": synthesis.get("verdict"),
                "confidence": synthesis.get("confidence"),
                "key_risks": synthesis.get("key_risks", []),
                "key_catalysts": synthesis.get("key_catalysts", []),
                "what_market_missing": synthesis.get("what_market_is_missing"),
                "brief": existing_valuation.get("brief_for_cio"),
                "source": "sp500_screen"
            }

        # Run fresh fundamental analysis via Claude
        stock = yf.Ticker(ticker)
        info = stock.info or {}

        prompt = f"""Provide a quick fundamental check for {ticker} at ${current_price:.2f}.

Company: {info.get('longName', ticker)}
Sector: {info.get('sector', 'Unknown')}
Market Cap: ${info.get('marketCap', 0)/1e9:.1f}B
P/E: {info.get('trailingPE', 'N/A')}
Forward P/E: {info.get('forwardPE', 'N/A')}
EV/EBITDA: {info.get('enterpriseToEbitda', 'N/A')}
Revenue Growth: {info.get('revenueGrowth', 0)*100:.1f}%
Profit Margin: {info.get('profitMargins', 0)*100:.1f}%
FCF Yield: {(info.get('freeCashflow', 0) / info.get('marketCap', 1) * 100):.1f}%

Direction proposed: {direction}

Provide a brief (200 words max) fundamental assessment. Is the {direction} thesis supported at current valuation?

Respond with JSON:
{{
  "ticker": "{ticker}",
  "current_price": {current_price},
  "estimated_fair_value": <your estimate>,
  "upside_pct": <upside to fair value>,
  "verdict": "UNDERVALUED|FAIRLY_VALUED|OVERVALUED",
  "confidence": <0-100>,
  "thesis_supported": true/false,
  "brief": "<one paragraph assessment>"
}}"""

        try:
            response = self.client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}]
            )
            raw = response.content[0].text
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0]
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0]
            result = json.loads(raw.strip())
            result["source"] = "fresh_analysis"
            return result
        except Exception as e:
            logger.error(f"Fundamental check failed: {e}")
            return {"ticker": ticker, "error": str(e)}

    def run_sector_catalyst(self, ticker: str, direction: str, sector: str) -> dict:
        """
        Step 2: Sector desk identifies catalyst (upward for longs, downward for shorts).
        """
        logger.info(f"[GAUNTLET] Step 2: Catalyst identification for {ticker} ({direction})")

        current_price = get_current_price(ticker)
        stock = yf.Ticker(ticker)
        info = stock.info or {}

        catalyst_direction = "upward" if direction == "LONG" else "downward"

        prompt = f"""You are a sector specialist analyst. Identify the key {catalyst_direction} catalyst for {ticker}.

Company: {info.get('longName', ticker)}
Sector: {sector}
Industry: {info.get('industry', 'Unknown')}
Current Price: ${current_price:.2f}
Direction: {direction}

For a {direction} position, identify:
1. The single most important {catalyst_direction} catalyst in the next 3-6 months
2. The timing of this catalyst
3. The expected magnitude of price impact
4. What could delay or prevent the catalyst

Respond with JSON:
{{
  "ticker": "{ticker}",
  "primary_catalyst": "<specific catalyst with dates if possible>",
  "catalyst_timing": "<when this catalyst should materialize>",
  "expected_impact": "<expected % move if catalyst plays out>",
  "catalyst_probability": <0-100>,
  "risks_to_catalyst": ["<what could prevent it>"],
  "secondary_catalysts": ["<other potential catalysts>"],
  "one_line": "<one sentence summary>"
}}"""

        try:
            response = self.client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}]
            )
            raw = response.content[0].text
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0]
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0]
            return json.loads(raw.strip())
        except Exception as e:
            logger.error(f"Catalyst identification failed: {e}")
            return {"ticker": ticker, "error": str(e)}

    def run_cro_review(self, ticker: str, direction: str,
                       fundamental: dict, catalyst: dict,
                       portfolio_context: dict) -> dict:
        """
        Step 3: CRO steelmans opposition and identifies all ways the trade loses money.
        """
        logger.info(f"[GAUNTLET] Step 3: CRO adversarial review for {ticker} ({direction})")

        current_price = get_current_price(ticker)

        # Build trade decision dict for CRO
        trade_decision = {
            "ticker": ticker,
            "action": "BUY" if direction == "LONG" else "SHORT",
            "current_price": current_price,
            "intrinsic_value": fundamental.get("estimated_fair_value") or fundamental.get("intrinsic_value"),
            "upside_pct": fundamental.get("upside_pct"),
            "confidence": fundamental.get("confidence"),
            "bull_case" if direction == "LONG" else "bear_case": fundamental.get("brief"),
            "catalyst": catalyst.get("primary_catalyst"),
            "catalyst_timing": catalyst.get("catalyst_timing"),
            "rationale": f"{direction} thesis: {fundamental.get('brief', 'N/A')}"
        }

        # Format portfolio positions
        positions = portfolio_context.get("positions", [])
        portfolio_str = "\n".join([
            f"  - {p['ticker']}: {p['allocation_pct']}% ({p.get('direction', 'LONG')})"
            for p in positions
        ])

        prompt = f"""TODAY'S DATE: {datetime.now().strftime('%B %d, %Y')}

TRADE THESIS FOR CRO REVIEW
============================

Ticker: {ticker}
Proposed Action: {trade_decision['action']}
Current Price: ${current_price:.2f}

BULL CASE SUMMARY:
{trade_decision['rationale']}

FUNDAMENTAL VIEW:
- Intrinsic Value: ${trade_decision.get('intrinsic_value', 'N/A')}
- Current Price: ${current_price:.2f}
- Upside/Downside: {trade_decision.get('upside_pct', 'N/A')}%
- Confidence: {trade_decision.get('confidence', 'N/A')}%

CATALYST:
{catalyst.get('primary_catalyst', 'Not specified')}
Timing: {catalyst.get('catalyst_timing', 'Not specified')}
Probability: {catalyst.get('catalyst_probability', 'N/A')}%

CURRENT PORTFOLIO:
{portfolio_str}

Total Equity Exposure: {portfolio_context.get('equity_pct', 39)}%
Cash Available: {portfolio_context.get('cash_pct', 0)}%

YOUR TASK:
Review this trade thesis as a 25-year veteran CRO. You've lived through dot-com, GFC, COVID, and 2022.

1. STEELMAN the {'bull' if direction == 'LONG' else 'bear'} case - prove you understand it
2. IDENTIFY every specific way this trade loses money - not generic risks, dated scenarios with quantified impacts
3. FIND the closest historical analogue and how it ended
4. STATE what the market knows that the thesis ignores
5. GIVE your verdict: APPROVE, CONDITIONAL, or BLOCK

Respond with ONLY valid JSON:
{{
  "ticker": "{ticker}",
  "steelman": "<your articulation of why the {'bull' if direction == 'LONG' else 'bear'} case works>",
  "specific_risks": [
    {{
      "scenario": "<specific, dated scenario>",
      "probability": "<X%>",
      "impact": "<expected loss if occurs>"
    }}
  ],
  "historical_analogue": "<closest historical parallel and how it ended>",
  "what_the_market_knows": "<why the current price might be right>",
  "correlation_concerns": "<interaction with existing portfolio positions>",
  "verdict": "APPROVE|CONDITIONAL|BLOCK",
  "conditions": "<if CONDITIONAL: what modifications required>",
  "would_change_mind": "<what would flip your verdict>",
  "one_line": "<brutally honest one-sentence assessment>"
}}"""

        try:
            response = self.client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=2048,
                system=CRO_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}]
            )
            raw = response.content[0].text
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0]
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0]
            return json.loads(raw.strip())
        except Exception as e:
            logger.error(f"CRO review failed: {e}")
            return {"ticker": ticker, "error": str(e), "verdict": "ERROR"}

    def run_cio_sizing(self, ticker: str, direction: str,
                       fundamental: dict, catalyst: dict, cro: dict,
                       portfolio_context: dict) -> dict:
        """
        Step 4: CIO makes final sizing decision given portfolio context.
        """
        logger.info(f"[GAUNTLET] Step 4: CIO sizing decision for {ticker} ({direction})")

        current_price = get_current_price(ticker)

        # Format current positions
        positions = portfolio_context.get("positions", [])
        position_str = "\n".join([
            f"  - {p['ticker']}: {p['allocation_pct']}% @ ${p.get('current_price', 0):.2f}"
            for p in positions
        ])

        prompt = f"""CIO SIZING DECISION REQUEST
============================

Date: {datetime.now().strftime('%Y-%m-%d')}
Ticker: {ticker}
Direction: {direction}
Current Price: ${current_price:.2f}

FUNDAMENTAL ASSESSMENT:
{fundamental.get('brief', 'N/A')}
- Fair Value: ${fundamental.get('estimated_fair_value') or fundamental.get('intrinsic_value', 'N/A')}
- Upside: {fundamental.get('upside_pct', 'N/A')}%
- Confidence: {fundamental.get('confidence', 'N/A')}%

CATALYST:
{catalyst.get('primary_catalyst', 'N/A')}
- Timing: {catalyst.get('catalyst_timing', 'N/A')}
- Probability: {catalyst.get('catalyst_probability', 'N/A')}%

CRO VERDICT: {cro.get('verdict', 'N/A')}
CRO Assessment: {cro.get('one_line', 'N/A')}
{f"CRO Conditions: {cro.get('conditions')}" if cro.get('conditions') else ""}

CURRENT PORTFOLIO:
{position_str}

Portfolio Value: ${portfolio_context.get('portfolio_value', 1000000):,.0f}
Cash: {portfolio_context.get('cash_pct', 0):.1f}%
Total Equity Exposure: {portfolio_context.get('equity_pct', 39)}%

CONSTRAINTS:
- Max single position: 10%
- Max sector: 30%
- Min cash buffer: 10%
- Must honor CRO verdict (if BLOCK, cannot proceed)

Given the fundamental case, catalyst, CRO review, and current portfolio composition, what is your sizing decision?

Respond with JSON:
{{
  "ticker": "{ticker}",
  "direction": "{direction}",
  "approved": true/false,
  "position_size_pct": <recommended % of portfolio, 0 if not approved>,
  "rationale": "<why this size>",
  "entry_strategy": "<immediate, scale in, wait for pullback>",
  "stop_loss_pct": <stop loss level as negative %>,
  "take_profit_pct": <take profit level as positive %>,
  "rebalancing_required": "<what positions to trim if any>",
  "risk_flags": ["<any concerns>"],
  "final_verdict": "<one sentence final decision>"
}}"""

        try:
            response = self.client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=1024,
                system=CIO_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}]
            )
            raw = response.content[0].text
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0]
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0]
            return json.loads(raw.strip())
        except Exception as e:
            logger.error(f"CIO sizing failed: {e}")
            return {"ticker": ticker, "error": str(e), "approved": False}

    def run_full_gauntlet(self, ticker: str, direction: str,
                          portfolio_context: dict) -> dict:
        """
        Run the complete 4-step gauntlet on a single ticker.
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"RUNNING FULL GAUNTLET: {ticker} ({direction})")
        logger.info(f"{'='*60}")

        result = {
            "ticker": ticker,
            "direction": direction,
            "timestamp": datetime.now().isoformat(),
            "current_price": get_current_price(ticker),
        }

        # Load existing valuation from SP500 screen if available
        existing_val = load_sp500_valuation(ticker)

        # Step 1: Fundamental
        fundamental = self.run_fundamental_check(ticker, direction, existing_val)
        result["fundamental"] = fundamental

        # Step 2: Catalyst
        sector = get_sector(ticker)
        catalyst = self.run_sector_catalyst(ticker, direction, sector)
        result["catalyst"] = catalyst

        # Step 3: CRO
        cro = self.run_cro_review(ticker, direction, fundamental, catalyst, portfolio_context)
        result["cro"] = cro

        # Step 4: CIO (only if CRO doesn't BLOCK)
        if cro.get("verdict") == "BLOCK":
            cio = {
                "ticker": ticker,
                "approved": False,
                "position_size_pct": 0,
                "rationale": f"CRO BLOCKED: {cro.get('one_line', 'Risk too high')}",
                "final_verdict": "BLOCKED by CRO"
            }
        else:
            cio = self.run_cio_sizing(ticker, direction, fundamental, catalyst, cro, portfolio_context)
        result["cio"] = cio

        # Save individual result
        output_file = GAUNTLET_DIR / f"{ticker}_{direction}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(output_file, "w") as f:
            json.dump(result, f, indent=2, default=str)
        logger.info(f"Saved gauntlet result to {output_file}")

        return result


def run_batch_gauntlet(tickers_longs: List[str], tickers_shorts: List[str],
                       tickers_hedge: List[str], portfolio_context: dict) -> List[dict]:
    """
    Run the gauntlet on multiple tickers.
    """
    runner = GauntletRunner()
    results = []

    # Run longs
    for ticker in tickers_longs:
        try:
            result = runner.run_full_gauntlet(ticker, "LONG", portfolio_context)
            results.append(result)
        except Exception as e:
            logger.error(f"Gauntlet failed for {ticker}: {e}")
            results.append({"ticker": ticker, "direction": "LONG", "error": str(e)})

    # Run shorts
    for ticker in tickers_shorts:
        try:
            result = runner.run_full_gauntlet(ticker, "SHORT", portfolio_context)
            results.append(result)
        except Exception as e:
            logger.error(f"Gauntlet failed for {ticker}: {e}")
            results.append({"ticker": ticker, "direction": "SHORT", "error": str(e)})

    # Run hedges
    for ticker in tickers_hedge:
        try:
            result = runner.run_full_gauntlet(ticker, "HEDGE", portfolio_context)
            results.append(result)
        except Exception as e:
            logger.error(f"Gauntlet failed for {ticker}: {e}")
            results.append({"ticker": ticker, "direction": "HEDGE", "error": str(e)})

    return results


def generate_summary_table(results: List[dict]) -> str:
    """Generate a summary table of all gauntlet results."""
    lines = [
        "",
        "=" * 100,
        "CRO GAUNTLET SUMMARY",
        "=" * 100,
        "",
        f"{'Ticker':<8} {'Dir':<6} {'Price':>10} {'Fair Val':>10} {'Upside':>8} {'CRO':>12} {'Size':>6} {'Final Verdict':<30}",
        "-" * 100,
    ]

    for r in results:
        ticker = r.get("ticker", "???")
        direction = r.get("direction", "???")
        price = r.get("current_price", 0)

        fundamental = r.get("fundamental", {})
        fair_val = fundamental.get("estimated_fair_value") or fundamental.get("intrinsic_value") or 0
        upside = fundamental.get("upside_pct", 0)

        cro = r.get("cro", {})
        cro_verdict = cro.get("verdict", "ERROR")

        cio = r.get("cio", {})
        size = cio.get("position_size_pct", 0)
        final = cio.get("final_verdict", "N/A")[:30]

        lines.append(
            f"{ticker:<8} {direction:<6} ${price:>8.2f} ${fair_val:>8.0f} {upside:>+7.1f}% {cro_verdict:>12} {size:>5.1f}% {final:<30}"
        )

    lines.extend([
        "-" * 100,
        "",
        "CRO VERDICTS:",
    ])

    for r in results:
        ticker = r.get("ticker", "???")
        cro = r.get("cro", {})
        lines.append(f"  {ticker}: {cro.get('one_line', 'N/A')}")

    lines.extend(["", "=" * 100])

    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    parser = argparse.ArgumentParser(description="CRO Gauntlet Runner")
    parser.add_argument("--longs", help="Comma-separated list of LONG tickers")
    parser.add_argument("--shorts", help="Comma-separated list of SHORT tickers")
    parser.add_argument("--hedges", help="Comma-separated list of HEDGE tickers")
    parser.add_argument("--all", action="store_true", help="Run full gauntlet from user request")
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("ATLAS CRO GAUNTLET - Full Risk Review Process")
    print("=" * 70 + "\n")

    # Current portfolio context
    portfolio_context = {
        "portfolio_value": 1000000,
        "positions": [
            {"ticker": "BIL", "allocation_pct": 61.0, "current_price": 91.39, "direction": "LONG"},
            {"ticker": "BE", "allocation_pct": 15.0, "current_price": 160.36, "direction": "LONG"},
            {"ticker": "TLT", "allocation_pct": 10.0, "current_price": 89.40, "direction": "SHORT"},
            {"ticker": "AVGO", "allocation_pct": 5.0, "current_price": 317.53, "direction": "LONG"},
            {"ticker": "ADBE", "allocation_pct": 3.0, "current_price": 450.00, "direction": "LONG"},
            {"ticker": "GOOG", "allocation_pct": 3.0, "current_price": 175.00, "direction": "LONG"},
            {"ticker": "APO", "allocation_pct": 3.0, "current_price": 150.00, "direction": "LONG"},
        ],
        "cash_pct": 0.0,
        "equity_pct": 39.0,  # Total non-BIL exposure
    }

    if args.all:
        # Full gauntlet as specified by user
        longs = ["NOW", "CRM", "UNH", "GDDY"]
        shorts = ["STX", "GLW", "AAL", "WDC"]
        hedges = ["GLD"]
    else:
        longs = [t.strip() for t in args.longs.split(",")] if args.longs else []
        shorts = [t.strip() for t in args.shorts.split(",")] if args.shorts else []
        hedges = [t.strip() for t in args.hedges.split(",")] if args.hedges else []

    print(f"LONGS: {longs}")
    print(f"SHORTS: {shorts}")
    print(f"HEDGES: {hedges}")
    print()

    # Run the gauntlet
    results = run_batch_gauntlet(longs, shorts, hedges, portfolio_context)

    # Generate and print summary
    summary = generate_summary_table(results)
    print(summary)

    # Save full results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_file = GAUNTLET_DIR / f"gauntlet_summary_{timestamp}.json"
    with open(summary_file, "w") as f:
        json.dump({
            "timestamp": timestamp,
            "portfolio_context": portfolio_context,
            "results": results,
            "summary": summary,
        }, f, indent=2, default=str)

    print(f"\nFull results saved to: {summary_file}")
