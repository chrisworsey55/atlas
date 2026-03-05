"""
Druckenmiller Agent Runner
Macro strategist agent that analyzes economic conditions using Druckenmiller's framework.

Unlike sector desk agents (bottom-up, company-specific), the Druckenmiller Agent:
- Operates top-down on macro conditions
- Focuses on liquidity, Fed policy, and cycle positioning
- Recommends portfolio-level tilts and asset allocation
- Identifies "fat pitch" opportunities for outsized positions

Output feeds into the CIO Agent alongside sector desk briefs.
"""
import json
import logging
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from pathlib import Path

import anthropic

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_MODEL_PREMIUM
from data.macro_client import MacroClient

from agents.prompts.druckenmiller_agent import (
    SYSTEM_PROMPT,
    build_analysis_prompt,
)
from agents.chat_mixin import ChatMixin, DRUCKENMILLER_CHAT_PROMPT

logger = logging.getLogger(__name__)

# State file for persisting briefs
STATE_DIR = Path(__file__).resolve().parent.parent / "data" / "state"
DRUCK_STATE_FILE = STATE_DIR / "druckenmiller_briefs.json"


class DruckenmillerAgent(ChatMixin):
    """
    Macro strategist agent modeled on Stanley Druckenmiller's investment philosophy.

    Analyzes macro conditions (Fed policy, liquidity, cycle position) and produces
    a macro briefing for the CIO that recommends portfolio-level positioning.
    """

    CHAT_SYSTEM_PROMPT = DRUCKENMILLER_CHAT_PROMPT
    desk_name = "druckenmiller"

    def __init__(self, use_premium_model: bool = True):
        """
        Initialize the Druckenmiller Agent.

        Args:
            use_premium_model: If True, uses the premium model for more nuanced analysis.
                              Default True because macro calls are high-stakes.
        """
        self.macro = MacroClient()
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = CLAUDE_MODEL_PREMIUM if use_premium_model else CLAUDE_MODEL
        self._ensure_state_dir()

    def _ensure_state_dir(self):
        """Ensure state directory exists."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)

    def _load_previous_analysis(self) -> Optional[dict]:
        """Load the most recent analysis from state file."""
        if DRUCK_STATE_FILE.exists():
            try:
                with open(DRUCK_STATE_FILE, "r") as f:
                    briefs = json.load(f)
                if briefs:
                    return briefs[-1]
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load previous Druckenmiller analysis: {e}")
        return None

    def _save_analysis(self, analysis: dict):
        """Save analysis to state file."""
        briefs = []
        if DRUCK_STATE_FILE.exists():
            try:
                with open(DRUCK_STATE_FILE, "r") as f:
                    briefs = json.load(f)
            except (json.JSONDecodeError, IOError):
                briefs = []

        briefs.append(analysis)
        briefs = briefs[-30:]

        with open(DRUCK_STATE_FILE, "w") as f:
            json.dump(briefs, f, indent=2, default=str)

        logger.info(f"[Druckenmiller] Saved analysis to {DRUCK_STATE_FILE}")

    def load_latest_brief(self) -> Optional[dict]:
        """Load the most recent analysis for chat context."""
        return self._load_previous_analysis()

    def analyze(
        self,
        portfolio_positions: dict = None,
        desk_briefs: list = None,
        thirteenf_flows: dict = None,
        persist: bool = False,
    ) -> Optional[dict]:
        """
        Run macro analysis using Druckenmiller's framework.

        Args:
            portfolio_positions: Current portfolio holdings (optional)
            desk_briefs: List of briefs from sector desk agents (optional)
            thirteenf_flows: Institutional flow data from 13F analysis (optional)
            persist: If True, save result to database

        Returns:
            Structured macro briefing or None if analysis fails
        """
        logger.info("[Druckenmiller] Starting macro analysis...")

        # 1. Fetch macro data
        logger.info("[Druckenmiller] Fetching macro snapshot...")
        try:
            macro_data = self.macro.get_macro_snapshot()
        except Exception as e:
            logger.error(f"[Druckenmiller] Failed to fetch macro data: {e}")
            macro_data = {"date": datetime.now().strftime("%Y-%m-%d")}

        # 2. Get preliminary regime assessment
        liquidity_regime = self.macro.get_liquidity_regime(macro_data)
        cycle_position = self.macro.get_cycle_position(macro_data)

        logger.info(f"[Druckenmiller] Preliminary assessment: {liquidity_regime} liquidity, {cycle_position} cycle")

        # 3. Build the user prompt
        user_prompt = build_analysis_prompt(
            macro_data=macro_data,
            portfolio_positions=portfolio_positions,
            desk_briefs=desk_briefs,
            thirteenf_flows=thirteenf_flows,
        )

        # 4. Call Claude
        logger.info(f"[Druckenmiller] Calling Claude ({self.model})...")
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}]
            )
            raw_response = response.content[0].text
        except Exception as e:
            logger.error(f"[Druckenmiller] Claude API error: {e}")
            return None

        # 5. Parse JSON response
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
            analysis["macro_data_snapshot"] = {
                "fed_funds": macro_data.get("fed_funds_rate"),
                "m2_yoy": macro_data.get("m2_yoy_change"),
                "yield_curve": macro_data.get("yield_curve_10y_2y"),
                "vix": macro_data.get("vix"),
                "sp500": macro_data.get("sp500"),
            }

            logger.info(f"[Druckenmiller] Analysis complete: {analysis.get('headline', 'No headline')}")
            logger.info(f"[Druckenmiller] Conviction: {analysis.get('conviction_level', 0):.0%}, Tilt: {analysis.get('portfolio_tilt', 'N/A')}")

            # 6. Save to local state file
            self._save_analysis(analysis)

            # 7. Persist to database if requested
            if persist:
                self._persist_briefing(analysis)

            return analysis

        except json.JSONDecodeError as e:
            logger.error(f"[Druckenmiller] Failed to parse Claude response: {e}")
            logger.debug(f"Raw response: {raw_response[:500]}...")
            return None

    def _persist_briefing(self, analysis: dict):
        """
        Save the macro briefing to the database.
        """
        try:
            from database import get_session, AtlasMacroBrief
            from sqlalchemy.exc import IntegrityError

            session = get_session()

            try:
                brief = AtlasMacroBrief(
                    analysis_date=date.today(),
                    liquidity_regime=analysis.get("liquidity_regime"),
                    cycle_position=analysis.get("cycle_position"),
                    conviction_level=analysis.get("conviction_level"),
                    portfolio_tilt=analysis.get("portfolio_tilt"),
                    headline=analysis.get("headline"),
                    brief_json=analysis,
                    model_used=analysis.get("model_used"),
                )
                session.add(brief)
                session.commit()

                logger.info(f"[Druckenmiller] Persisted macro brief (id={brief.id})")

            except IntegrityError:
                session.rollback()
                logger.warning("[Druckenmiller] Macro brief already exists for today, skipping")
            except Exception as e:
                session.rollback()
                logger.error(f"[Druckenmiller] Failed to persist brief: {e}")
            finally:
                session.close()

        except ImportError:
            logger.warning("Database not configured, skipping persistence")

    def get_brief_for_cio(
        self,
        portfolio_positions: dict = None,
        desk_briefs: list = None,
        thirteenf_flows: dict = None,
    ) -> dict:
        """
        Run analysis and return a simplified brief for the CIO agent.

        Returns dict with:
        - headline
        - liquidity_regime
        - cycle_position
        - conviction_level
        - portfolio_tilt
        - conviction_calls (list)
        - risk_flags (list)
        - brief_for_cio (50 words)
        """
        analysis = self.analyze(
            portfolio_positions=portfolio_positions,
            desk_briefs=desk_briefs,
            thirteenf_flows=thirteenf_flows,
        )

        if not analysis:
            return {
                "agent": "Druckenmiller",
                "status": "FAILED",
                "error": "Analysis failed",
            }

        return {
            "agent": "Druckenmiller",
            "date": analysis.get("date"),
            "headline": analysis.get("headline"),
            "liquidity_regime": analysis.get("liquidity_regime"),
            "cycle_position": analysis.get("cycle_position"),
            "conviction_level": analysis.get("conviction_level"),
            "portfolio_tilt": analysis.get("portfolio_tilt"),
            "conviction_calls": analysis.get("conviction_calls", []),
            "risk_flags": analysis.get("risk_flags", []),
            "asset_allocation": analysis.get("asset_allocation_suggestion"),
            "brief_for_cio": analysis.get("brief_for_cio"),
        }


def run_macro_analysis(
    portfolio_positions: dict = None,
    desk_briefs: list = None,
    thirteenf_flows: dict = None,
    persist: bool = False,
) -> Optional[dict]:
    """
    Convenience function to run Druckenmiller macro analysis.

    Args:
        portfolio_positions: Current portfolio holdings (optional)
        desk_briefs: List of briefs from sector desk agents (optional)
        thirteenf_flows: Institutional flow data from 13F analysis (optional)
        persist: If True, save result to database

    Returns:
        Structured macro briefing or None if analysis fails
    """
    agent = DruckenmillerAgent()
    return agent.analyze(
        portfolio_positions=portfolio_positions,
        desk_briefs=desk_briefs,
        thirteenf_flows=thirteenf_flows,
        persist=persist,
    )


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    parser = argparse.ArgumentParser(description="ATLAS Druckenmiller Macro Agent")
    parser.add_argument("--persist", action="store_true", help="Save results to database")
    parser.add_argument("--test", action="store_true", help="Run test with mock data")
    args = parser.parse_args()

    print("\n" + "="*70)
    print("ATLAS Druckenmiller Agent - Macro Analysis")
    print("="*70 + "\n")

    agent = DruckenmillerAgent()

    # Sample desk briefs for testing
    sample_desk_briefs = None
    sample_flows = None

    if args.test:
        sample_desk_briefs = [
            {
                "desk": "Semiconductor",
                "ticker": "NVDA",
                "signal": "BULLISH",
                "confidence": 0.85,
                "brief_for_cio": "AI datacenter demand remains strong. Gross margins expanding.",
            },
            {
                "desk": "Biotech",
                "ticker": "LLY",
                "signal": "BULLISH",
                "confidence": 0.80,
                "brief_for_cio": "GLP-1 franchise continues to exceed expectations.",
            },
        ]
        sample_flows = {
            "consensus_builds": [
                {"ticker": "TSMC", "funds": ["Druckenmiller", "Tepper", "Tiger Global"]},
            ],
            "crowding_warnings": [
                {"ticker": "NVDA", "funds_holding": 14},
            ],
            "contrarian_signals": [
                {"ticker": "PFE", "fund": "Baupost", "portfolio_pct": 8.2},
            ],
        }

    result = agent.analyze(
        desk_briefs=sample_desk_briefs,
        thirteenf_flows=sample_flows,
        persist=args.persist,
    )

    if result:
        print("\n" + "="*70)
        print("MACRO BRIEFING")
        print("="*70)

        print(f"\nHEADLINE: {result.get('headline', 'N/A')}")
        print(f"\nLiquidity Regime: {result.get('liquidity_regime', 'N/A')}")
        print(f"Cycle Position: {result.get('cycle_position', 'N/A')}")
        print(f"Conviction Level: {result.get('conviction_level', 0):.0%}")
        print(f"Portfolio Tilt: {result.get('portfolio_tilt', 'N/A')}")

        if result.get("conviction_calls"):
            print("\nCONVICTION CALLS:")
            for call in result["conviction_calls"]:
                print(f"  - {call.get('direction', 'N/A')} {call.get('sector_or_instrument', 'N/A')}: {call.get('thesis', 'N/A')[:80]}...")
                print(f"    Size: {call.get('suggested_size', 'N/A')}")

        if result.get("risk_flags"):
            print("\nRISK FLAGS:")
            for flag in result["risk_flags"]:
                print(f"  - [{flag.get('probability', 'N/A')}] {flag.get('risk', 'N/A')}")

        if result.get("asset_allocation_suggestion"):
            print("\nSUGGESTED ALLOCATION:")
            alloc = result["asset_allocation_suggestion"]
            for key, val in alloc.items():
                print(f"  - {key.title()}: {val}")

        print("\nBRIEF FOR CIO:")
        print(f"  {result.get('brief_for_cio', 'N/A')}")

        print("\n" + "="*70)
        print("FULL JSON OUTPUT")
        print("="*70)
        print(json.dumps(result, indent=2, default=str))

    else:
        print("Analysis failed. Check logs for details.")
