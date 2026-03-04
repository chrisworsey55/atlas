"""
Alpha Discovery Agent
Finds non-obvious patterns across all agent signals that no single analyst would spot.

This agent runs after every CIO cycle and analyzes:
- Cross-agent signal correlations
- Earnings narrative clustering
- Institutional flow convergence
- Adversarial decay signals
- Regime detection
- Micro-macro bridges
"""
import json
import logging
from typing import Optional
from datetime import datetime, date, timedelta
from pathlib import Path

import anthropic

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL_PREMIUM
from agents.prompts.alpha_discovery_agent import (
    SYSTEM_PROMPT,
    build_analysis_prompt,
    build_chat_prompt,
    build_backtest_prompt,
)

logger = logging.getLogger(__name__)


class AlphaDiscoveryAgent:
    """
    Alpha Discovery Agent — finds trades that emerge from the intersection of multiple signals.

    This agent is the reason the fund exists. Other agents make us as good as the
    best human investors. This agent makes us better than any human could be.
    """

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = CLAUDE_MODEL_PREMIUM  # Use premium model for synthesis
        self.agent_name = "alpha_discovery"
        self.state_dir = Path(__file__).parent.parent / "data" / "state"
        self.discoveries_file = self.state_dir / "alpha_discoveries.json"

    def analyze(
        self,
        desk_briefs: list[dict] = None,
        flow_briefing: dict = None,
        adversarial_history: list[dict] = None,
        market_context: str = None,
    ) -> Optional[dict]:
        """
        Run alpha discovery analysis on all agent outputs.

        This is the main entry point called after every CIO cycle.

        Args:
            desk_briefs: Latest briefs from all sector desks
            flow_briefing: Institutional flow analysis
            adversarial_history: History of adversarial agent warnings
            market_context: Optional macro context string

        Returns:
            Alpha discovery results with 0-3 high-conviction discoveries
        """
        logger.info("[AlphaDiscovery] Starting cross-agent pattern analysis...")

        # Load data if not provided
        if desk_briefs is None:
            desk_briefs = self._load_desk_briefs()

        if flow_briefing is None:
            flow_briefing = self._load_flow_briefing()

        if adversarial_history is None:
            adversarial_history = self._load_adversarial_history()

        # Load additional context
        portfolio_context = self._load_portfolio_state()
        previous_discoveries = self._load_previous_discoveries()

        logger.info(
            f"[AlphaDiscovery] Analyzing {len(desk_briefs)} desk briefs, "
            f"{len(adversarial_history)} adversarial warnings"
        )

        # Build the comprehensive prompt
        user_prompt = build_analysis_prompt(
            desk_briefs=desk_briefs,
            flow_briefing=flow_briefing,
            adversarial_history=adversarial_history,
            previous_discoveries=previous_discoveries,
            portfolio_context=portfolio_context,
            market_context=market_context,
        )

        # Call Claude
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}]
            )
            raw_response = response.content[0].text
        except Exception as e:
            logger.error(f"[AlphaDiscovery] Claude API error: {e}")
            return None

        # Parse JSON response
        try:
            if "```json" in raw_response:
                json_str = raw_response.split("```json")[1].split("```")[0]
            elif "```" in raw_response:
                json_str = raw_response.split("```")[1].split("```")[0]
            else:
                json_str = raw_response

            result = json.loads(json_str.strip())
            result["agent"] = self.agent_name
            result["generated_at"] = datetime.utcnow().isoformat()
            result["model_used"] = self.model
            result["inputs_analyzed"] = {
                "desk_briefs": len(desk_briefs),
                "adversarial_warnings": len(adversarial_history),
                "has_flow_data": flow_briefing is not None,
            }

            # Log summary
            num_discoveries = len(result.get("discoveries", []))
            logger.info(f"[AlphaDiscovery] Found {num_discoveries} discoveries")

            # Persist discoveries for tracking
            self._persist_discoveries(result)

            return result

        except json.JSONDecodeError as e:
            logger.error(f"[AlphaDiscovery] Failed to parse response: {e}")
            return {
                "agent": self.agent_name,
                "discoveries": [],
                "error": f"Parse error: {e}",
                "raw_response": raw_response[:1000],
                "generated_at": datetime.utcnow().isoformat(),
            }

    def chat(self, message: str, include_context: bool = True) -> Optional[dict]:
        """
        Chat with the Alpha Discovery agent about cross-agent patterns.

        Args:
            message: User's question about patterns across the agent swarm
            include_context: Whether to include desk briefs and flow data

        Returns:
            Analysis response focused on non-obvious pattern discovery
        """
        logger.info(f"[AlphaDiscovery] Processing: {message[:50]}...")

        # Load context
        desk_briefs = self._load_desk_briefs() if include_context else []
        flow_briefing = self._load_flow_briefing() if include_context else {}
        portfolio_context = self._load_portfolio_state() if include_context else {}

        # Build chat prompt
        user_prompt = build_chat_prompt(
            message=message,
            desk_briefs=desk_briefs,
            flow_briefing=flow_briefing,
            portfolio_context=portfolio_context,
        )

        # Call Claude
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}]
            )
            raw_response = response.content[0].text
        except Exception as e:
            logger.error(f"[AlphaDiscovery] Claude API error: {e}")
            return None

        # Parse response
        try:
            if "```json" in raw_response:
                json_str = raw_response.split("```json")[1].split("```")[0]
                result = json.loads(json_str.strip())
            else:
                result = {"response": raw_response}

            result["agent"] = self.agent_name
            result["generated_at"] = datetime.utcnow().isoformat()
            result["model_used"] = self.model

            return result

        except json.JSONDecodeError:
            return {
                "agent": self.agent_name,
                "response": raw_response,
                "generated_at": datetime.utcnow().isoformat(),
                "model_used": self.model,
            }

    def backtest(
        self,
        lookback_days: int = 90,
    ) -> Optional[dict]:
        """
        Backtest historical signal combinations to validate pattern detection.

        Args:
            lookback_days: Number of days to analyze

        Returns:
            Backtest results with pattern hit rates
        """
        logger.info(f"[AlphaDiscovery] Running backtest over {lookback_days} days...")

        # Load historical data
        historical_signals = self._load_historical_signals(lookback_days)
        outcomes = self._load_historical_outcomes(lookback_days)

        if not historical_signals:
            logger.warning("[AlphaDiscovery] No historical data for backtest")
            return {
                "agent": self.agent_name,
                "backtest": "INSUFFICIENT_DATA",
                "message": "Not enough historical signal data for backtest",
                "generated_at": datetime.utcnow().isoformat(),
            }

        # Build backtest prompt
        user_prompt = build_backtest_prompt(
            historical_signals=historical_signals,
            outcomes=outcomes,
        )

        # Call Claude
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}]
            )
            raw_response = response.content[0].text
        except Exception as e:
            logger.error(f"[AlphaDiscovery] Backtest API error: {e}")
            return None

        # Parse response
        try:
            if "```json" in raw_response:
                json_str = raw_response.split("```json")[1].split("```")[0]
            elif "```" in raw_response:
                json_str = raw_response.split("```")[1].split("```")[0]
            else:
                json_str = raw_response

            result = json.loads(json_str.strip())
            result["agent"] = self.agent_name
            result["backtest_period_days"] = lookback_days
            result["generated_at"] = datetime.utcnow().isoformat()
            result["model_used"] = self.model

            return result

        except json.JSONDecodeError as e:
            logger.error(f"[AlphaDiscovery] Failed to parse backtest response: {e}")
            return {
                "agent": self.agent_name,
                "backtest": "PARSE_ERROR",
                "raw_response": raw_response[:1000],
                "generated_at": datetime.utcnow().isoformat(),
            }

    def _load_desk_briefs(self) -> list[dict]:
        """Load latest desk briefs from database or state files."""
        briefs = []

        # Try database first
        try:
            from database import get_session, AtlasDeskBrief

            session = get_session()
            cutoff = date.today() - timedelta(days=7)

            db_briefs = session.query(AtlasDeskBrief).filter(
                AtlasDeskBrief.analysis_date >= cutoff
            ).order_by(AtlasDeskBrief.analysis_date.desc()).all()

            seen = set()
            for brief in db_briefs:
                key = (brief.company_id, brief.desk_name)
                if key not in seen:
                    seen.add(key)
                    if brief.brief_json:
                        briefs.append(brief.brief_json)

            session.close()
            logger.info(f"[AlphaDiscovery] Loaded {len(briefs)} briefs from database")

        except Exception as e:
            logger.warning(f"[AlphaDiscovery] Could not load briefs from DB: {e}")

        # Fallback to state file
        if not briefs:
            try:
                briefs_file = self.state_dir / "desk_briefs.json"
                if briefs_file.exists():
                    with open(briefs_file) as f:
                        briefs = json.load(f)
                    logger.info(f"[AlphaDiscovery] Loaded {len(briefs)} briefs from state file")
            except Exception as e:
                logger.warning(f"[AlphaDiscovery] Could not load briefs from file: {e}")

        return briefs

    def _load_flow_briefing(self) -> dict:
        """Load institutional flow briefing."""
        try:
            from agents.institutional_flow_agent import InstitutionalFlowAgent
            agent = InstitutionalFlowAgent()
            return agent.thirteenf.build_consensus_report(
                agent.thirteenf.get_all_fund_holdings(cache_hours=24)
            )
        except Exception as e:
            logger.warning(f"[AlphaDiscovery] Could not load flow briefing: {e}")

        # Fallback to state file
        try:
            flow_file = self.state_dir / "flow_briefing.json"
            if flow_file.exists():
                with open(flow_file) as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"[AlphaDiscovery] Could not load flow from file: {e}")

        return {}

    def _load_adversarial_history(self) -> list[dict]:
        """Load history of adversarial agent warnings."""
        history = []

        try:
            history_file = self.state_dir / "adversarial_history.json"
            if history_file.exists():
                with open(history_file) as f:
                    history = json.load(f)
        except Exception as e:
            logger.warning(f"[AlphaDiscovery] Could not load adversarial history: {e}")

        return history

    def _load_portfolio_state(self) -> dict:
        """Load current portfolio state."""
        try:
            portfolio_file = self.state_dir / "positions.json"
            if portfolio_file.exists():
                with open(portfolio_file) as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"[AlphaDiscovery] Could not load portfolio: {e}")

        # Default empty portfolio
        from config.settings import STARTING_CAPITAL
        return {
            "total_value": STARTING_CAPITAL,
            "cash": STARTING_CAPITAL,
            "cash_pct": 100,
            "num_positions": 0,
            "positions": [],
        }

    def _load_previous_discoveries(self) -> list[dict]:
        """Load previous alpha discoveries for pattern tracking."""
        try:
            if self.discoveries_file.exists():
                with open(self.discoveries_file) as f:
                    data = json.load(f)
                    return data.get("discoveries", [])
        except Exception as e:
            logger.warning(f"[AlphaDiscovery] Could not load previous discoveries: {e}")

        return []

    def _persist_discoveries(self, result: dict):
        """Persist new discoveries to state file for tracking."""
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)

            existing = []
            if self.discoveries_file.exists():
                with open(self.discoveries_file) as f:
                    data = json.load(f)
                    existing = data.get("discoveries", [])

            # Add new discoveries with timestamp
            new_discoveries = result.get("discoveries", [])
            for disc in new_discoveries:
                disc["discovered_at"] = result.get("generated_at")
                disc["outcome"] = "PENDING"
                existing.append(disc)

            # Keep last 100 discoveries
            existing = existing[-100:]

            with open(self.discoveries_file, "w") as f:
                json.dump({
                    "discoveries": existing,
                    "last_updated": datetime.utcnow().isoformat(),
                }, f, indent=2)

            logger.info(f"[AlphaDiscovery] Persisted {len(new_discoveries)} new discoveries")

        except Exception as e:
            logger.warning(f"[AlphaDiscovery] Could not persist discoveries: {e}")

    def _load_historical_signals(self, lookback_days: int) -> list[dict]:
        """Load historical agent signals for backtesting."""
        # TODO: Implement historical signal loading from database
        # For now, return empty list to indicate no historical data
        return []

    def _load_historical_outcomes(self, lookback_days: int) -> list[dict]:
        """Load historical market outcomes for backtesting."""
        # TODO: Implement historical outcome loading
        # For now, return empty list
        return []


def run_alpha_analysis(
    desk_briefs: list[dict] = None,
    flow_briefing: dict = None,
    market_context: str = None,
) -> dict:
    """
    Convenience function to run alpha discovery analysis.

    Called after every CIO cycle to find non-obvious patterns.
    """
    agent = AlphaDiscoveryAgent()
    return agent.analyze(
        desk_briefs=desk_briefs,
        flow_briefing=flow_briefing,
        market_context=market_context,
    )


def run_alpha_chat(message: str) -> dict:
    """
    Convenience function for chat-style alpha discovery queries.
    """
    agent = AlphaDiscoveryAgent()
    return agent.chat(message)


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    parser = argparse.ArgumentParser(description="ATLAS Alpha Discovery Agent")
    parser.add_argument("--analyse", "--analyze", action="store_true",
                        help="Run alpha discovery analysis")
    parser.add_argument("--backtest", action="store_true",
                        help="Backtest historical signal combinations")
    parser.add_argument("--chat", type=str,
                        help="Chat with the alpha discovery agent")
    parser.add_argument("--test", action="store_true",
                        help="Run with test data")
    args = parser.parse_args()

    print("\n" + "="*60)
    print("ATLAS Alpha Discovery Agent")
    print("Finding patterns that no single analyst would spot")
    print("="*60 + "\n")

    agent = AlphaDiscoveryAgent()

    if args.analyse or args.test:
        if args.test:
            # Test with sample data
            test_briefs = [
                {
                    "ticker": "NVDA",
                    "desk": "Semiconductor",
                    "signal": "BULLISH",
                    "confidence": 0.85,
                    "brief_for_cio": "Strong AI datacenter demand. China risk at $19.7B.",
                    "bull_case": "AI capex cycle extending. Dominant position.",
                    "bear_case": "Valuation stretched. China restrictions could tighten.",
                },
                {
                    "ticker": "TLT",
                    "desk": "Bond",
                    "signal": "BEARISH",
                    "confidence": 0.72,
                    "brief_for_cio": "Duration risk elevated. Fed higher for longer.",
                    "bull_case": "Flight to safety if equities correct.",
                    "bear_case": "Inflation persistent, Fed hawkish.",
                },
                {
                    "ticker": "GLD",
                    "desk": "Metals",
                    "signal": "BULLISH",
                    "confidence": 0.68,
                    "brief_for_cio": "Central bank buying strong. USD weakness.",
                    "bull_case": "Inflation hedge, geopolitical uncertainty.",
                    "bear_case": "Real rates rising, opportunity cost.",
                },
                {
                    "ticker": "JPM",
                    "desk": "Financials",
                    "signal": "NEUTRAL",
                    "confidence": 0.55,
                    "brief_for_cio": "NII pressure but strong capital position.",
                    "bull_case": "Best positioned for any rate environment.",
                    "bear_case": "Credit cycle turning, CRE exposure.",
                },
            ]

            test_flow = {
                "consensus_builds": [
                    {"ticker": "AVGO", "funds_accumulating": ["Druckenmiller", "Tepper", "Coatue"]},
                    {"ticker": "META", "funds_accumulating": ["Ackman", "Tiger Global"]},
                ],
                "crowding_warnings": [
                    {"ticker": "NVDA", "funds_holding": 14, "of_total": 16},
                ],
                "contrarian_signals": [
                    {"ticker": "PFE", "fund": "Baupost (Klarman)", "portfolio_pct": 8.2},
                ],
            }

            test_adversarial = [
                {"risk": "China semiconductor export controls", "days_active": 45, "materialized": False},
                {"risk": "Commercial real estate defaults", "days_active": 90, "materialized": False},
                {"risk": "Consumer credit deterioration", "days_active": 30, "materialized": False},
            ]

            result = agent.analyze(
                desk_briefs=test_briefs,
                flow_briefing=test_flow,
                adversarial_history=test_adversarial,
                market_context="Risk-on environment. Fed signaling rate cuts. AI narrative dominant.",
            )
        else:
            # Run with real data
            result = agent.analyze()

        if result:
            print("\n" + "="*60)
            print("ALPHA DISCOVERY RESULTS")
            print("="*60)
            print(json.dumps(result, indent=2))

            # Summary
            discoveries = result.get("discoveries", [])
            if discoveries:
                print("\n" + "-"*40)
                print(f"FOUND {len(discoveries)} DISCOVERY/IES:")
                for i, disc in enumerate(discoveries, 1):
                    print(f"\n{i}. [{disc.get('signal_type', 'N/A')}] {disc.get('title', 'No title')}")
                    print(f"   Confidence: {disc.get('confidence', 0)}%")
                    print(f"   Action: {disc.get('suggested_action', 'N/A')}")
            else:
                print("\n" + "-"*40)
                print("No high-conviction discoveries this cycle.")
                print(f"Note: {result.get('no_signal_note', 'N/A')}")

    elif args.backtest:
        result = agent.backtest(lookback_days=90)

        if result:
            print("\n" + "="*60)
            print("BACKTEST RESULTS")
            print("="*60)
            print(json.dumps(result, indent=2))

    elif args.chat:
        result = agent.chat(args.chat)

        if result:
            print("\n" + "="*60)
            print("ALPHA DISCOVERY RESPONSE")
            print("="*60)
            print(json.dumps(result, indent=2))

    else:
        print("Usage:")
        print("  python3 -m agents.alpha_discovery_agent --analyse")
        print("  python3 -m agents.alpha_discovery_agent --backtest")
        print("  python3 -m agents.alpha_discovery_agent --test")
        print("  python3 -m agents.alpha_discovery_agent --chat 'What patterns are you seeing?'")
