"""
Bond Desk Agent Runner
Macro desk for fixed income analysis using FRED data and yfinance prices.
"""
import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
from pathlib import Path

import anthropic

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL
from data.macro_client import MacroClient
from data.price_client import PriceClient
from agents.prompts.bond_desk import (
    SYSTEM_PROMPT,
    build_analysis_prompt,
    BOND_DESK_TICKERS,
)
from agents.chat_mixin import ChatMixin, BOND_DESK_CHAT_PROMPT

logger = logging.getLogger(__name__)

# State file for persisting briefs
STATE_DIR = Path(__file__).resolve().parent.parent / "data" / "state"
BOND_STATE_FILE = STATE_DIR / "bond_desk_briefs.json"


class BondDeskAgent(ChatMixin):
    """
    Bond/Rates desk agent that analyzes fixed income markets.
    Uses FRED for macro data and yfinance for ETF prices.
    """

    CHAT_SYSTEM_PROMPT = BOND_DESK_CHAT_PROMPT

    def __init__(self):
        self.desk_name = "bond"
        self.macro = MacroClient()
        self.prices = PriceClient()
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self._ensure_state_dir()

    def _ensure_state_dir(self):
        """Ensure state directory exists."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)

    def _load_previous_analysis(self) -> Optional[dict]:
        """Load the most recent analysis from state file."""
        if BOND_STATE_FILE.exists():
            try:
                with open(BOND_STATE_FILE, "r") as f:
                    briefs = json.load(f)
                if briefs:
                    return briefs[-1]  # Most recent
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load previous analysis: {e}")
        return None

    def _save_analysis(self, analysis: dict):
        """Save analysis to state file."""
        briefs = []
        if BOND_STATE_FILE.exists():
            try:
                with open(BOND_STATE_FILE, "r") as f:
                    briefs = json.load(f)
            except (json.JSONDecodeError, IOError):
                briefs = []

        briefs.append(analysis)
        # Keep last 30 days of briefs
        briefs = briefs[-30:]

        with open(BOND_STATE_FILE, "w") as f:
            json.dump(briefs, f, indent=2, default=str)

        logger.info(f"[{self.desk_name}] Saved analysis to {BOND_STATE_FILE}")

    def _get_bond_etf_prices(self) -> dict:
        """Get current prices for bond-related ETFs."""
        prices = {}
        for name, ticker in BOND_DESK_TICKERS.items():
            price = self.prices.get_current_price(ticker)
            if price:
                prices[name] = price
        return prices

    def analyze(self, persist: bool = True) -> Optional[dict]:
        """
        Run full bond market analysis.

        Args:
            persist: If True, save result to local JSON state file

        Returns:
            Structured analysis dict or None if analysis fails
        """
        logger.info(f"[{self.desk_name}] Starting bond market analysis...")

        # 1. Get macro snapshot from FRED
        logger.info(f"[{self.desk_name}] Fetching macro data from FRED...")
        macro_data = self.macro.get_macro_snapshot()

        # 2. Get bond ETF prices from yfinance
        logger.info(f"[{self.desk_name}] Fetching bond ETF prices...")
        price_data = self._get_bond_etf_prices()

        # Add VIX and S&P from macro snapshot
        price_data["vix"] = macro_data.get("vix")
        price_data["sp500"] = macro_data.get("sp500")

        # 3. Load previous analysis for context
        previous = self._load_previous_analysis()

        # 4. Build the user prompt
        user_prompt = build_analysis_prompt(
            macro_data=macro_data,
            price_data=price_data,
            previous_analysis=previous,
        )

        # 5. Call Claude
        logger.info(f"[{self.desk_name}] Calling Claude for analysis...")
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
            analysis["desk"] = self.desk_name
            analysis["analyzed_at"] = datetime.utcnow().isoformat()
            analysis["model_used"] = CLAUDE_MODEL

            # Add raw macro data for reference
            analysis["raw_data"] = {
                "treasury_2y": macro_data.get("treasury_2y"),
                "treasury_10y": macro_data.get("treasury_10y"),
                "yield_curve_10y_2y": macro_data.get("yield_curve_10y_2y"),
                "fed_funds_rate": macro_data.get("fed_funds_rate"),
                "high_yield_spread": macro_data.get("high_yield_spread"),
            }

            logger.info(f"[{self.desk_name}] Analysis complete: {analysis.get('signal', 'UNKNOWN')} (confidence: {analysis.get('confidence', 0):.2f})")

            # 7. Persist if requested
            if persist:
                self._save_analysis(analysis)

            return analysis

        except json.JSONDecodeError as e:
            logger.error(f"[{self.desk_name}] Failed to parse Claude response: {e}")
            logger.debug(f"Raw response: {raw_response[:500]}...")
            return None

    def load_latest_brief(self) -> Optional[dict]:
        """Load the most recent analysis for chat context."""
        return self._load_previous_analysis()

    def get_brief_for_cio(self) -> Optional[dict]:
        """
        Get a brief summary suitable for the CIO agent.
        Either uses cached recent analysis or runs new analysis.

        Returns:
            Dict with signal, confidence, and brief, or None
        """
        # Check for recent analysis (within last 4 hours)
        previous = self._load_previous_analysis()
        if previous:
            analyzed_at = previous.get("analyzed_at", "")
            if analyzed_at:
                try:
                    analysis_time = datetime.fromisoformat(analyzed_at)
                    age_hours = (datetime.utcnow() - analysis_time).total_seconds() / 3600
                    if age_hours < 4:
                        logger.info(f"[{self.desk_name}] Using cached analysis from {age_hours:.1f} hours ago")
                        return {
                            "desk": self.desk_name,
                            "signal": previous.get("signal"),
                            "confidence": previous.get("confidence"),
                            "brief": previous.get("brief_for_cio"),
                            "positioning": previous.get("positioning"),
                            "catalysts": previous.get("catalysts"),
                            "analyzed_at": analyzed_at,
                        }
                except (ValueError, TypeError):
                    pass

        # Run fresh analysis
        analysis = self.analyze(persist=True)
        if analysis:
            return {
                "desk": self.desk_name,
                "signal": analysis.get("signal"),
                "confidence": analysis.get("confidence"),
                "brief": analysis.get("brief_for_cio"),
                "positioning": analysis.get("positioning"),
                "catalysts": analysis.get("catalysts"),
                "analyzed_at": analysis.get("analyzed_at"),
            }
        return None


def run_bond_analysis(persist: bool = True) -> Optional[dict]:
    """
    Convenience function to run bond desk analysis.
    """
    desk = BondDeskAgent()
    return desk.analyze(persist=persist)


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    parser = argparse.ArgumentParser(description="ATLAS Bond Desk Analysis")
    parser.add_argument("--test", action="store_true", help="Run test analysis")
    parser.add_argument("--no-persist", action="store_true", help="Don't save results")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("ATLAS Bond Desk - Fixed Income Analysis")
    print("=" * 60 + "\n")

    desk = BondDeskAgent()

    if args.test:
        print("Running bond market analysis...\n")
        result = desk.analyze(persist=not args.no_persist)

        if result:
            print("\n" + "=" * 60)
            print("ANALYSIS RESULT")
            print("=" * 60)
            print(f"\nSignal: {result.get('signal')}")
            print(f"Confidence: {result.get('confidence', 0):.0%}")

            yield_curve = result.get("yield_curve", {})
            print(f"\nYield Curve:")
            print(f"  Shape: {yield_curve.get('shape')}")
            print(f"  2Y: {yield_curve.get('2y_yield')}%")
            print(f"  10Y: {yield_curve.get('10y_yield')}%")
            print(f"  2s10s: {yield_curve.get('2s10s_spread')}bps")

            positioning = result.get("positioning", {})
            print(f"\nPositioning:")
            print(f"  Duration: {positioning.get('duration_stance')}")
            print(f"  Curve Trade: {positioning.get('curve_trade')}")
            print(f"  Credit: {positioning.get('credit_stance')}")

            print(f"\nCIO Brief: {result.get('brief_for_cio')}")

            print("\n" + "-" * 60)
            print("Full JSON output:")
            print(json.dumps(result, indent=2, default=str))
        else:
            print("Analysis failed - check logs for details")
    else:
        print("Use --test to run analysis")
        print("Example: python -m agents.bond_desk_agent --test")
