"""
Commodities Desk Agent Runner
Macro desk for energy and agricultural commodity analysis using FRED and yfinance.
"""
import json
import logging
from typing import Optional
from datetime import datetime
from pathlib import Path

import anthropic
import yfinance as yf

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL
from data.macro_client import MacroClient
from agents.prompts.commodities_desk import (
    SYSTEM_PROMPT,
    build_analysis_prompt,
    COMMODITIES_DESK_TICKERS,
)

logger = logging.getLogger(__name__)

# State file for persisting briefs
STATE_DIR = Path(__file__).resolve().parent.parent / "data" / "state"
COMMODITIES_STATE_FILE = STATE_DIR / "commodities_desk_briefs.json"


class CommoditiesDeskAgent:
    """
    Commodities desk agent that analyzes energy and agricultural markets.
    Uses FRED for macro data and yfinance for commodity prices.
    """

    def __init__(self):
        self.desk_name = "commodities"
        self.macro = MacroClient()
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self._ensure_state_dir()

    def _ensure_state_dir(self):
        """Ensure state directory exists."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)

    def _load_previous_analysis(self) -> Optional[dict]:
        """Load the most recent analysis from state file."""
        if COMMODITIES_STATE_FILE.exists():
            try:
                with open(COMMODITIES_STATE_FILE, "r") as f:
                    briefs = json.load(f)
                if briefs:
                    return briefs[-1]
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load previous analysis: {e}")
        return None

    def _save_analysis(self, analysis: dict):
        """Save analysis to state file."""
        briefs = []
        if COMMODITIES_STATE_FILE.exists():
            try:
                with open(COMMODITIES_STATE_FILE, "r") as f:
                    briefs = json.load(f)
            except (json.JSONDecodeError, IOError):
                briefs = []

        briefs.append(analysis)
        briefs = briefs[-30:]  # Keep last 30 days

        with open(COMMODITIES_STATE_FILE, "w") as f:
            json.dump(briefs, f, indent=2, default=str)

        logger.info(f"[{self.desk_name}] Saved analysis to {COMMODITIES_STATE_FILE}")

    def _get_commodity_prices(self) -> dict:
        """Get current commodity prices from yfinance."""
        prices = {}
        for name, ticker in COMMODITIES_DESK_TICKERS.items():
            try:
                stock = yf.Ticker(ticker)
                hist = stock.history(period="1d")
                if hist.empty:
                    hist = stock.history(period="5d")
                if not hist.empty:
                    prices[name] = float(hist["Close"].iloc[-1])
            except Exception as e:
                logger.warning(f"Could not fetch {name} ({ticker}): {e}")
        return prices

    def analyze(self, persist: bool = True) -> Optional[dict]:
        """
        Run full commodities market analysis.

        Args:
            persist: If True, save result to local JSON state file

        Returns:
            Structured analysis dict or None if analysis fails
        """
        logger.info(f"[{self.desk_name}] Starting commodities market analysis...")

        # 1. Get macro snapshot from FRED
        logger.info(f"[{self.desk_name}] Fetching macro data from FRED...")
        macro_data = self.macro.get_macro_snapshot()

        # 2. Get commodity prices from yfinance
        logger.info(f"[{self.desk_name}] Fetching commodity prices...")
        commodity_data = self._get_commodity_prices()

        # 3. Load previous analysis for context
        previous = self._load_previous_analysis()

        # 4. Build the user prompt
        user_prompt = build_analysis_prompt(
            macro_data=macro_data,
            commodity_data=commodity_data,
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

            # Add raw commodity data for reference
            analysis["raw_data"] = {
                "wti": commodity_data.get("wti"),
                "brent": commodity_data.get("brent"),
                "natgas": commodity_data.get("natgas"),
                "dollar_index": macro_data.get("dollar_index"),
                "vix": macro_data.get("vix"),
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

    def get_brief_for_cio(self) -> Optional[dict]:
        """
        Get a brief summary suitable for the CIO agent.
        Either uses cached recent analysis or runs new analysis.

        Returns:
            Dict with signal, confidence, and brief, or None
        """
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
                            "crude_oil": previous.get("crude_oil"),
                            "natural_gas": previous.get("natural_gas"),
                            "analyzed_at": analyzed_at,
                        }
                except (ValueError, TypeError):
                    pass

        analysis = self.analyze(persist=True)
        if analysis:
            return {
                "desk": self.desk_name,
                "signal": analysis.get("signal"),
                "confidence": analysis.get("confidence"),
                "brief": analysis.get("brief_for_cio"),
                "positioning": analysis.get("positioning"),
                "crude_oil": analysis.get("crude_oil"),
                "natural_gas": analysis.get("natural_gas"),
                "analyzed_at": analysis.get("analyzed_at"),
            }
        return None


def run_commodities_analysis(persist: bool = True) -> Optional[dict]:
    """
    Convenience function to run commodities desk analysis.
    """
    desk = CommoditiesDeskAgent()
    return desk.analyze(persist=persist)


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    parser = argparse.ArgumentParser(description="ATLAS Commodities Desk Analysis")
    parser.add_argument("--test", action="store_true", help="Run test analysis")
    parser.add_argument("--no-persist", action="store_true", help="Don't save results")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("ATLAS Commodities Desk - Energy & Agriculture Analysis")
    print("=" * 60 + "\n")

    desk = CommoditiesDeskAgent()

    if args.test:
        print("Running commodities market analysis...\n")
        result = desk.analyze(persist=not args.no_persist)

        if result:
            print("\n" + "=" * 60)
            print("ANALYSIS RESULT")
            print("=" * 60)
            print(f"\nSignal: {result.get('signal')}")
            print(f"Confidence: {result.get('confidence', 0):.0%}")

            crude = result.get("crude_oil", {})
            print(f"\nCrude Oil:")
            print(f"  WTI: ${crude.get('wti_price')}")
            print(f"  Brent: ${crude.get('brent_price')}")
            print(f"  Curve: {crude.get('curve_structure')}")
            print(f"  Signal: {crude.get('signal')}")

            natgas = result.get("natural_gas", {})
            print(f"\nNatural Gas:")
            print(f"  Price: ${natgas.get('price')}")
            print(f"  Signal: {natgas.get('signal')}")

            positioning = result.get("positioning", {})
            print(f"\nPositioning:")
            print(f"  Crude: {positioning.get('crude_stance')}")
            print(f"  Gas: {positioning.get('gas_stance')}")

            print(f"\nCIO Brief: {result.get('brief_for_cio')}")

            print("\n" + "-" * 60)
            print("Full JSON output:")
            print(json.dumps(result, indent=2, default=str))
        else:
            print("Analysis failed - check logs for details")
    else:
        print("Use --test to run analysis")
        print("Example: python -m agents.commodities_desk_agent --test")
