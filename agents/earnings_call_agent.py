"""
Earnings Call Agent for ATLAS
Forensic analysis of earnings call transcripts.

Analyzes management tone, guidance, key quotes, analyst concerns,
and narrative shifts to generate trading signals from qualitative data.
"""
import json
import logging
import argparse
from datetime import datetime
from typing import Optional, Dict, List
from pathlib import Path

import anthropic

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_MODEL_PREMIUM
from config.universe import UNIVERSE
from data.transcript_client import TranscriptClient
from data.earnings_client import EarningsClient

from agents.prompts.earnings_call_agent import (
    SYSTEM_PROMPT,
    build_analysis_prompt,
    EARNINGS_CALL_CHAT_PROMPT,
)
from agents.chat_mixin import ChatMixin

logger = logging.getLogger(__name__)

# State file for persisting briefs
STATE_DIR = Path(__file__).resolve().parent.parent / "data" / "state"
EARNINGS_CALLS_DIR = STATE_DIR / "earnings_calls"
EARNINGS_STATE_FILE = STATE_DIR / "earnings_call_briefs.json"


class EarningsCallAgent(ChatMixin):
    """
    Earnings call transcript analysis agent.

    Reads transcripts forensically to extract:
    - Management tone and tone shifts
    - Guidance vs consensus
    - Key quotes that move stocks
    - Analyst concerns from Q&A
    - Forward-looking signals
    - Narrative shifts from prior quarters
    """

    CHAT_SYSTEM_PROMPT = EARNINGS_CALL_CHAT_PROMPT
    desk_name = "earnings"

    def __init__(self, use_premium_model: bool = True):
        """
        Initialize the Earnings Call Agent.

        Args:
            use_premium_model: If True, uses premium model for nuanced analysis.
        """
        self.transcript_client = TranscriptClient()
        self.earnings_client = EarningsClient()
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = CLAUDE_MODEL_PREMIUM if use_premium_model else CLAUDE_MODEL
        self._ensure_state_dir()

    def _ensure_state_dir(self):
        """Ensure state directories exist."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        EARNINGS_CALLS_DIR.mkdir(parents=True, exist_ok=True)

    def _load_briefs(self) -> List[Dict]:
        """Load all earnings call briefs."""
        if EARNINGS_STATE_FILE.exists():
            try:
                with open(EARNINGS_STATE_FILE, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load earnings briefs: {e}")
        return []

    def _save_brief(self, brief: Dict):
        """Save analysis to state file."""
        briefs = self._load_briefs()
        briefs.append(brief)
        briefs = briefs[-50:]  # Keep last 50

        with open(EARNINGS_STATE_FILE, "w") as f:
            json.dump(briefs, f, indent=2, default=str)

        # Also save to individual ticker file
        ticker = brief.get("ticker", "UNKNOWN")
        ticker_file = EARNINGS_CALLS_DIR / f"{ticker}_briefs.json"
        ticker_briefs = []
        if ticker_file.exists():
            try:
                with open(ticker_file, "r") as f:
                    ticker_briefs = json.load(f)
            except:
                ticker_briefs = []
        ticker_briefs.append(brief)
        ticker_briefs = ticker_briefs[-20:]
        with open(ticker_file, "w") as f:
            json.dump(ticker_briefs, f, indent=2, default=str)

        logger.info(f"[EarningsCall] Saved analysis to {EARNINGS_STATE_FILE}")

    def load_latest_brief(self, ticker: str = None) -> Optional[Dict]:
        """Load the most recent analysis."""
        briefs = self._load_briefs()
        if not briefs:
            return None
        if ticker:
            # Find latest for specific ticker
            for brief in reversed(briefs):
                if brief.get("ticker", "").upper() == ticker.upper():
                    return brief
            return None
        return briefs[-1]

    def analyze(
        self,
        ticker: str,
        quarter: int = None,
        year: int = None,
    ) -> Optional[Dict]:
        """
        Analyze an earnings call transcript.

        Args:
            ticker: Stock ticker symbol
            quarter: Fiscal quarter (1-4). If None, gets latest.
            year: Fiscal year. If None, uses current year.

        Returns:
            Structured analysis dict or None if analysis fails
        """
        logger.info(f"[EarningsCall] Starting analysis for {ticker}...")

        # 1. Fetch transcript
        logger.info(f"[EarningsCall] Fetching transcript...")
        transcript = self.transcript_client.get_transcript(ticker, quarter, year)

        if not transcript or not transcript.get('full_text'):
            logger.error(f"[EarningsCall] No transcript found for {ticker}")
            return None

        logger.info(f"[EarningsCall] Got transcript: {len(transcript['full_text'])} chars")

        # 2. Try to get prior quarter transcript for comparison
        prior_transcript = None
        if quarter and year:
            prior_q = quarter - 1 if quarter > 1 else 4
            prior_y = year if quarter > 1 else year - 1
            try:
                prior_transcript = self.transcript_client.get_transcript(ticker, prior_q, prior_y)
            except:
                pass

        # 3. Get consensus estimates
        consensus = None
        try:
            recent = self.earnings_client.get_recent_results(ticker)
            if recent:
                consensus = {
                    "eps_estimate": recent.get("eps_estimate"),
                    "eps_actual": recent.get("eps_actual"),
                    "eps_surprise_pct": recent.get("eps_surprise_pct"),
                    "revenue_actual": recent.get("revenue_actual"),
                }
        except Exception as e:
            logger.debug(f"Could not get consensus: {e}")

        # 4. Build the analysis prompt
        user_prompt = build_analysis_prompt(
            ticker=ticker,
            transcript=transcript,
            prior_transcript=prior_transcript,
            consensus_estimates=consensus,
        )

        # 5. Call Claude
        logger.info(f"[EarningsCall] Calling Claude ({self.model})...")
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}]
            )
            raw_response = response.content[0].text
        except Exception as e:
            logger.error(f"[EarningsCall] Claude API error: {e}")
            return None

        # 6. Parse JSON response
        try:
            # Handle potential markdown code blocks
            if "```json" in raw_response:
                json_str = raw_response.split("```json")[1].split("```")[0]
            elif "```" in raw_response:
                json_str = raw_response.split("```")[1].split("```")[0]
            else:
                json_str = raw_response

            analysis = json.loads(json_str.strip())

            # Add metadata
            analysis["analyzed_at"] = datetime.utcnow().isoformat()
            analysis["model_used"] = self.model
            analysis["transcript_source"] = transcript.get("source", "Unknown")
            analysis["signal"] = self._derive_signal(analysis)
            analysis["confidence"] = analysis.get("conviction", 0.7)

            # Log summary
            tone = analysis.get("management_tone", {}).get("overall", "N/A")
            guidance = analysis.get("guidance", {}).get("signal", "N/A")
            logger.info(f"[EarningsCall] {ticker} - Tone: {tone}, Guidance: {guidance}")

            # 7. Save to state
            self._save_brief(analysis)

            return analysis

        except json.JSONDecodeError as e:
            logger.error(f"[EarningsCall] Failed to parse Claude response: {e}")
            logger.debug(f"Raw response: {raw_response[:500]}...")
            return None

    def _derive_signal(self, analysis: Dict) -> str:
        """Derive trading signal from analysis."""
        verdict = analysis.get("verdict", "").upper()
        tone = analysis.get("management_tone", {}).get("overall", "").upper()
        guidance = analysis.get("guidance", {}).get("signal", "").upper()

        if "BULLISH" in verdict:
            return "BULLISH"
        elif "BEARISH" in verdict:
            return "BEARISH"
        elif guidance == "BEAT_AND_RAISE":
            return "BULLISH"
        elif guidance == "BEAT_AND_LOWER" or guidance == "MISS":
            return "BEARISH"
        elif tone == "CONFIDENT":
            return "BULLISH"
        elif tone == "DEFENSIVE" or tone == "EVASIVE":
            return "BEARISH"
        else:
            return "NEUTRAL"

    def get_upcoming_calls(self, days_ahead: int = 14) -> List[Dict]:
        """
        Get list of upcoming earnings calls for portfolio companies.

        Args:
            days_ahead: Look ahead this many days

        Returns:
            List of upcoming earnings dicts
        """
        return self.earnings_client.get_upcoming_earnings(days_ahead)

    def analyze_batch(self, tickers: List[str]) -> List[Dict]:
        """
        Analyze earnings calls for multiple tickers.

        Args:
            tickers: List of tickers to analyze

        Returns:
            List of analysis results
        """
        results = []
        for ticker in tickers:
            try:
                analysis = self.analyze(ticker)
                if analysis:
                    results.append(analysis)
            except Exception as e:
                logger.error(f"Error analyzing {ticker}: {e}")
                continue
        return results

    def get_brief_for_cio(self, ticker: str = None) -> Optional[Dict]:
        """
        Get simplified brief for CIO agent.

        Args:
            ticker: Optional specific ticker

        Returns:
            Simplified brief dict
        """
        analysis = self.load_latest_brief(ticker)
        if not analysis:
            return None

        return {
            "agent": "EarningsCall",
            "ticker": analysis.get("ticker"),
            "quarter": analysis.get("quarter"),
            "date": analysis.get("date"),
            "management_tone": analysis.get("management_tone", {}).get("overall"),
            "tone_vs_prior": analysis.get("management_tone", {}).get("vs_prior_quarter"),
            "guidance_signal": analysis.get("guidance", {}).get("signal"),
            "signal": analysis.get("signal"),
            "conviction": analysis.get("conviction", analysis.get("confidence", 0.7)),
            "analyst_concerns": analysis.get("analyst_concerns", []),
            "red_flags": analysis.get("red_flags", []),
            "bull_signals": analysis.get("bull_signals", []),
            "narrative_shift": analysis.get("narrative_shift"),
            "brief_for_cio": analysis.get("brief_for_cio"),
        }


def run_earnings_analysis(ticker: str, quarter: int = None, year: int = None) -> Optional[Dict]:
    """Convenience function to run earnings call analysis."""
    agent = EarningsCallAgent()
    return agent.analyze(ticker, quarter, year)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    parser = argparse.ArgumentParser(description="ATLAS Earnings Call Agent")
    parser.add_argument("--ticker", "-t", type=str, help="Stock ticker to analyze")
    parser.add_argument("--quarter", "-q", type=int, help="Fiscal quarter (1-4)")
    parser.add_argument("--year", "-y", type=int, help="Fiscal year")
    parser.add_argument("--latest", action="store_true", help="Analyze latest available")
    parser.add_argument("--upcoming", action="store_true", help="List upcoming earnings")
    args = parser.parse_args()

    agent = EarningsCallAgent()

    if args.upcoming:
        print("\n" + "="*70)
        print("ATLAS Earnings Call Agent - Upcoming Earnings")
        print("="*70 + "\n")

        upcoming = agent.get_upcoming_calls(days_ahead=14)
        if upcoming:
            print(f"Found {len(upcoming)} companies reporting in next 14 days:\n")
            for e in upcoming[:20]:
                print(f"  {e['earnings_date']} | {e['ticker']:6} | {e['company_name'][:35]}")
        else:
            print("No upcoming earnings found.")

    elif args.ticker:
        print("\n" + "="*70)
        print(f"ATLAS Earnings Call Agent - {args.ticker.upper()}")
        print("="*70 + "\n")

        result = agent.analyze(
            ticker=args.ticker.upper(),
            quarter=args.quarter,
            year=args.year,
        )

        if result:
            print(f"\n{'='*70}")
            print("EARNINGS CALL ANALYSIS")
            print(f"{'='*70}\n")

            print(f"Ticker: {result.get('ticker')}")
            print(f"Quarter: {result.get('quarter')}")
            print(f"Date: {result.get('date')}")

            tone = result.get("management_tone", {})
            print(f"\nMANAGEMENT TONE:")
            print(f"  Overall: {tone.get('overall')}")
            print(f"  vs Prior Quarter: {tone.get('vs_prior_quarter')}")
            print(f"  CEO: {tone.get('ceo_tone', 'N/A')}")
            print(f"  CFO: {tone.get('cfo_tone', 'N/A')}")

            guidance = result.get("guidance", {})
            print(f"\nGUIDANCE:")
            print(f"  Revenue: {guidance.get('revenue_guide', 'N/A')}")
            print(f"  EPS: {guidance.get('eps_guide', 'N/A')}")
            print(f"  vs Consensus: {guidance.get('vs_consensus', 'N/A')}")
            print(f"  Signal: {guidance.get('signal', 'N/A')}")

            print(f"\nKEY QUOTES:")
            for quote in result.get("key_quotes", [])[:3]:
                print(f"  [{quote.get('speaker', 'N/A')}]")
                print(f"  \"{quote.get('quote', 'N/A')[:100]}...\"")
                print(f"  -> {quote.get('significance', 'N/A')}")
                print()

            print(f"ANALYST CONCERNS:")
            for concern in result.get("analyst_concerns", []):
                print(f"  - {concern}")

            print(f"\nFORWARD SIGNALS:")
            signals = result.get("forward_signals", {})
            for key, val in signals.items():
                if val:
                    print(f"  {key.title()}: {val}")

            print(f"\nNARRATIVE SHIFT:")
            print(f"  {result.get('narrative_shift', 'N/A')}")

            print(f"\nVERDICT: {result.get('verdict', 'N/A')}")
            print(f"Signal: {result.get('signal')} | Conviction: {result.get('conviction', 0):.0%}")

            print(f"\nBRIEF FOR CIO:")
            print(f"  {result.get('brief_for_cio', 'N/A')}")

            print(f"\n{'='*70}")
            print("FULL JSON OUTPUT")
            print(f"{'='*70}\n")
            print(json.dumps(result, indent=2, default=str))
        else:
            print("Analysis failed. Check logs for details.")
            print("Note: FMP API key required for transcripts. Set FMP_API_KEY in .env")

    else:
        print("Usage:")
        print("  python3 -m agents.earnings_call_agent --ticker AVGO --latest")
        print("  python3 -m agents.earnings_call_agent --ticker AVGO --quarter 1 --year 2026")
        print("  python3 -m agents.earnings_call_agent --upcoming")
