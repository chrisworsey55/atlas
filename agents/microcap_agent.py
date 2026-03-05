"""
Micro-Cap Discovery Agent Runner
Discovers and analyzes undervalued micro-cap equities using SEC filings.
"""
import json
import logging
from typing import Optional, List
from datetime import datetime
from pathlib import Path

import anthropic

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL
from data.edgar_client import EdgarClient
from data.price_client import PriceClient
from agents.prompts.microcap_discovery import (
    SYSTEM_PROMPT,
    build_analysis_prompt,
)

logger = logging.getLogger(__name__)

# State file for persisting briefs
STATE_DIR = Path(__file__).resolve().parent.parent / "data" / "state"
MICROCAP_STATE_FILE = STATE_DIR / "microcap_briefs.json"

# Sample micro-cap universe for testing
# In production, this would be dynamically sourced
SAMPLE_MICROCAP_UNIVERSE = [
    "VNET",   # 21Vianet Group
    "IMXI",   # International Money Express
    "PTGX",   # Protagonist Therapeutics
    "CORT",   # Corcept Therapeutics
    "PRGS",   # Progress Software
    "ROAD",   # Construction Partners
    "KRUS",   # Kura Sushi USA
    "DOCN",   # DigitalOcean
    "RAMP",   # LiveRamp
    "HLIT",   # Harmonic Inc
]


class MicrocapAgent:
    """
    Micro-cap discovery agent that analyzes small company SEC filings.
    Identifies potential investment opportunities in the micro-cap space.
    """

    def __init__(self):
        self.desk_name = "microcap"
        self.edgar = EdgarClient()
        self.prices = PriceClient()
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self._ensure_state_dir()

    def _ensure_state_dir(self):
        """Ensure state directory exists."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)

    def _load_briefs(self) -> List[dict]:
        """Load all briefs from state file."""
        if MICROCAP_STATE_FILE.exists():
            try:
                with open(MICROCAP_STATE_FILE, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load briefs: {e}")
        return []

    def _get_previous_analysis(self, ticker: str) -> Optional[dict]:
        """Get previous analysis for a specific ticker."""
        briefs = self._load_briefs()
        for brief in reversed(briefs):
            if brief.get("ticker") == ticker:
                return brief
        return None

    def _save_analysis(self, analysis: dict):
        """Save analysis to state file."""
        briefs = self._load_briefs()
        briefs.append(analysis)
        # Keep last 100 briefs
        briefs = briefs[-100:]

        with open(MICROCAP_STATE_FILE, "w") as f:
            json.dump(briefs, f, indent=2, default=str)

        logger.info(f"[{self.desk_name}] Saved analysis for {analysis.get('ticker')} to {MICROCAP_STATE_FILE}")

    def _get_price_data(self, ticker: str) -> dict:
        """Get market data for the ticker."""
        price = self.prices.get_current_price(ticker)
        info = self.prices.get_sector_info(ticker)
        returns = self.prices.get_returns(ticker, 252)  # YTD approx

        return {
            "price": price,
            "market_cap": info.get("market_cap"),
            "pe_ratio": info.get("pe_ratio"),
            "pb_ratio": info.get("pb_ratio"),
            "avg_volume": info.get("avg_volume"),
            "52w_high": info.get("52w_high"),
            "52w_low": info.get("52w_low"),
            "return_ytd": returns * 100 if returns else None,
        }

    def analyze(self, ticker: str, persist: bool = True) -> Optional[dict]:
        """
        Run full analysis on a micro-cap ticker.

        Args:
            ticker: Stock ticker symbol
            persist: If True, save result to local JSON state file

        Returns:
            Structured analysis dict or None if analysis fails
        """
        logger.info(f"[{self.desk_name}] Analyzing {ticker}...")

        # 1. Get recent filings
        filings = self.edgar.get_recent_filings(ticker, ["10-K", "10-Q", "8-K"], days_back=180)
        if not filings:
            logger.warning(f"[{self.desk_name}] No filings found for {ticker}")
            return None

        # Get the most recent 10-K or 10-Q
        primary_filing = None
        for f in filings:
            if f["form_type"] == "10-K":
                primary_filing = f
                break
        if not primary_filing:
            for f in filings:
                if f["form_type"] == "10-Q":
                    primary_filing = f
                    break
        if not primary_filing:
            primary_filing = filings[0]

        logger.info(f"[{self.desk_name}] Using {primary_filing['form_type']} from {primary_filing['filing_date']}")

        # 2. Download filing text
        filing_text = self.edgar.download_filing_text(primary_filing, max_chars=40000)
        if not filing_text:
            logger.warning(f"[{self.desk_name}] Could not download filing text for {ticker}")
            filing_text = "Filing text not available"

        # 3. Get XBRL financials
        financials = self.edgar.get_key_financials(ticker) or {}
        financials["filing_date"] = primary_filing["filing_date"]

        # 4. Get price/market data
        price_data = self._get_price_data(ticker)

        # 5. Get previous analysis for context
        previous = self._get_previous_analysis(ticker)

        # 6. Build the user prompt
        user_prompt = build_analysis_prompt(
            ticker=ticker,
            filing_text=filing_text,
            financials=financials,
            price_data=price_data,
            previous_analysis=previous,
        )

        # 7. Call Claude
        logger.info(f"[{self.desk_name}] Calling Claude for {ticker} analysis...")
        try:
            response = self.client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}]
            )
            raw_response = response.content[0].text
        except Exception as e:
            logger.error(f"[{self.desk_name}] Claude API error: {e}")
            return None

        # 8. Parse JSON response
        try:
            if "```json" in raw_response:
                json_str = raw_response.split("```json")[1].split("```")[0]
            elif "```" in raw_response:
                json_str = raw_response.split("```")[1].split("```")[0]
            else:
                json_str = raw_response

            analysis = json.loads(json_str.strip())
            analysis["desk"] = self.desk_name
            analysis["analyzed_at"] = datetime.utcnow().isoformat()
            analysis["filing_used"] = primary_filing["form_type"]
            analysis["filing_date"] = primary_filing["filing_date"]
            analysis["model_used"] = CLAUDE_MODEL

            logger.info(f"[{self.desk_name}] {ticker}: {analysis.get('signal', 'UNKNOWN')} (confidence: {analysis.get('confidence', 0):.2f})")

            # 9. Persist if requested
            if persist:
                self._save_analysis(analysis)

            return analysis

        except json.JSONDecodeError as e:
            logger.error(f"[{self.desk_name}] Failed to parse Claude response: {e}")
            logger.debug(f"Raw response: {raw_response[:500]}...")
            return None

    def scan_universe(self, tickers: List[str] = None, persist: bool = True) -> List[dict]:
        """
        Scan a list of micro-cap tickers and return analyses.

        Args:
            tickers: List of tickers to scan (defaults to sample universe)
            persist: If True, save results to state file

        Returns:
            List of analysis dicts
        """
        if tickers is None:
            tickers = SAMPLE_MICROCAP_UNIVERSE

        results = []
        for ticker in tickers:
            try:
                analysis = self.analyze(ticker, persist=persist)
                if analysis:
                    results.append(analysis)
            except Exception as e:
                logger.error(f"Error analyzing {ticker}: {e}")

        return results

    def get_top_opportunities(self, min_confidence: float = 0.7) -> List[dict]:
        """
        Get the best opportunities from recent scans.

        Args:
            min_confidence: Minimum confidence threshold

        Returns:
            List of high-conviction opportunities sorted by confidence
        """
        briefs = self._load_briefs()

        # Filter for recent, high-conviction opportunities
        opportunities = []
        for brief in briefs:
            if brief.get("confidence", 0) >= min_confidence:
                if brief.get("signal") in ["STRONG_BUY", "BUY"]:
                    opportunities.append(brief)

        # Sort by confidence
        opportunities.sort(key=lambda x: x.get("confidence", 0), reverse=True)

        return opportunities[:10]  # Top 10

    def get_brief_for_cio(self) -> Optional[dict]:
        """
        Get a summary of micro-cap opportunities for the CIO.

        Returns:
            Dict with top opportunities or None
        """
        opportunities = self.get_top_opportunities()

        if not opportunities:
            return {
                "desk": self.desk_name,
                "signal": "NEUTRAL",
                "confidence": 0.5,
                "brief": "No high-conviction micro-cap opportunities identified in current scan.",
                "opportunities": [],
            }

        top = opportunities[0]
        return {
            "desk": self.desk_name,
            "signal": top.get("signal"),
            "confidence": top.get("confidence"),
            "brief": f"Top opportunity: {top.get('ticker')} - {top.get('brief_for_cio', 'N/A')}",
            "opportunities": [
                {
                    "ticker": o.get("ticker"),
                    "signal": o.get("signal"),
                    "confidence": o.get("confidence"),
                    "brief": o.get("brief_for_cio"),
                }
                for o in opportunities[:5]
            ],
            "analyzed_at": top.get("analyzed_at"),
        }


def run_microcap_scan(tickers: List[str] = None, persist: bool = True) -> List[dict]:
    """
    Convenience function to run micro-cap scan.
    """
    agent = MicrocapAgent()
    return agent.scan_universe(tickers, persist=persist)


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    parser = argparse.ArgumentParser(description="ATLAS Micro-Cap Discovery Agent")
    parser.add_argument("--test", action="store_true", help="Run test analysis on single ticker")
    parser.add_argument("--ticker", default="PRGS", help="Ticker to analyze (default: PRGS)")
    parser.add_argument("--scan", action="store_true", help="Scan full micro-cap universe")
    parser.add_argument("--no-persist", action="store_true", help="Don't save results")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("ATLAS Micro-Cap Discovery Agent")
    print("=" * 60 + "\n")

    agent = MicrocapAgent()

    if args.scan:
        print(f"Scanning micro-cap universe ({len(SAMPLE_MICROCAP_UNIVERSE)} stocks)...\n")
        results = agent.scan_universe(persist=not args.no_persist)
        print(f"\nScanned {len(results)} companies")
        for r in results:
            print(f"  {r['ticker']}: {r['signal']} ({r['confidence']:.0%})")

        # Show top opportunities
        print("\n" + "-" * 60)
        print("TOP OPPORTUNITIES")
        print("-" * 60)
        opps = agent.get_top_opportunities()
        for o in opps:
            print(f"  {o['ticker']}: {o['signal']} ({o['confidence']:.0%})")
            print(f"    {o.get('brief_for_cio', 'N/A')}\n")

    elif args.test:
        print(f"Analyzing {args.ticker}...\n")
        result = agent.analyze(args.ticker, persist=not args.no_persist)

        if result:
            print("\n" + "=" * 60)
            print("ANALYSIS RESULT")
            print("=" * 60)
            print(f"\nTicker: {result.get('ticker')}")
            print(f"Company: {result.get('company_name')}")
            print(f"Signal: {result.get('signal')}")
            print(f"Confidence: {result.get('confidence', 0):.0%}")

            value = result.get("value_assessment", {})
            print(f"\nValue:")
            print(f"  P/E: {value.get('pe_ratio')}")
            print(f"  P/B: {value.get('pb_ratio')}")
            print(f"  Grade: {value.get('valuation_grade')}")

            quality = result.get("quality_assessment", {})
            print(f"\nQuality:")
            print(f"  Gross Margin: {quality.get('gross_margin')}")
            print(f"  ROE: {quality.get('roe')}")
            print(f"  Grade: {quality.get('quality_grade')}")

            insider = result.get("insider_activity", {})
            print(f"\nInsider Activity: {insider.get('net_insider_flow')}")

            risks = result.get("risks", {})
            print(f"\nRisks:")
            print(f"  Liquidity: {risks.get('liquidity_risk')}")
            print(f"  Key Risks: {', '.join(risks.get('key_risks', []))}")

            print(f"\nCIO Brief: {result.get('brief_for_cio')}")

            print("\n" + "-" * 60)
            print("Full JSON output:")
            print(json.dumps(result, indent=2, default=str))
        else:
            print("Analysis failed - check logs for details")
    else:
        print("Use --test to analyze single ticker")
        print("Use --scan to scan full universe")
        print("\nExamples:")
        print("  python -m agents.microcap_agent --test --ticker PRGS")
        print("  python -m agents.microcap_agent --scan")
