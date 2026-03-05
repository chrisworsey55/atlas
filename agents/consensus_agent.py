"""
Consensus Agent for ATLAS
Meta-analyst that tracks what Wall Street thinks.

Knowing the consensus is how you bet against it.
If 40 analysts have NVDA at "buy" with average target of $200,
and ATLAS thinks it's fairly valued at $178, you know you're contrarian.
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

from config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL
from config.universe import UNIVERSE
from data.consensus_client import ConsensusClient

from agents.prompts.consensus_agent import (
    SYSTEM_PROMPT,
    build_analysis_prompt,
    CONSENSUS_CHAT_PROMPT,
)
from agents.chat_mixin import ChatMixin, load_portfolio_state, load_fundamental_valuations

logger = logging.getLogger(__name__)

# State files
STATE_DIR = Path(__file__).resolve().parent.parent / "data" / "state"
CONSENSUS_STATE_FILE = STATE_DIR / "consensus_briefs.json"


class ConsensusAgent(ChatMixin):
    """
    Consensus tracking and analysis agent.

    Analyzes:
    - Analyst rating distribution
    - Price target vs current price
    - Estimate revisions (momentum)
    - ATLAS vs consensus divergence
    - Crowding assessment
    - Contrarian opportunities
    """

    CHAT_SYSTEM_PROMPT = CONSENSUS_CHAT_PROMPT
    desk_name = "consensus"

    def __init__(self):
        """Initialize the Consensus Agent."""
        self.consensus_client = ConsensusClient()
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = CLAUDE_MODEL
        self._ensure_state_dir()

    def _ensure_state_dir(self):
        """Ensure state directory exists."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)

    def _load_briefs(self) -> List[Dict]:
        """Load consensus briefs."""
        if CONSENSUS_STATE_FILE.exists():
            try:
                with open(CONSENSUS_STATE_FILE, "r") as f:
                    return json.load(f)
            except:
                pass
        return []

    def _save_brief(self, brief: Dict):
        """Save a consensus brief."""
        briefs = self._load_briefs()
        briefs.append(brief)
        briefs = briefs[-100:]  # Keep last 100

        with open(CONSENSUS_STATE_FILE, "w") as f:
            json.dump(briefs, f, indent=2, default=str)

    def load_latest_brief(self, ticker: str = None) -> Optional[Dict]:
        """Load most recent analysis."""
        briefs = self._load_briefs()
        if not briefs:
            return None
        if ticker:
            for brief in reversed(briefs):
                if brief.get("ticker", "").upper() == ticker.upper():
                    return brief
            return None
        return briefs[-1]

    def analyze(self, ticker: str) -> Optional[Dict]:
        """
        Analyze consensus for a ticker.

        Args:
            ticker: Stock ticker symbol

        Returns:
            Structured consensus analysis or None
        """
        logger.info(f"[Consensus] Analyzing {ticker}...")

        # 1. Get consensus data
        consensus = self.consensus_client.get_consensus_snapshot(ticker)
        if not consensus:
            logger.error(f"[Consensus] No data for {ticker}")
            return None

        # 2. Get estimate revisions
        revisions = self.consensus_client.get_estimate_revisions(ticker)

        # 3. Get earnings history
        earnings_history = self.consensus_client.get_earnings_history(ticker)

        # 4. Get recent rating changes
        rating_changes = self.consensus_client.get_recent_rating_changes(ticker, days=30)

        # 5. Get ATLAS valuation if available
        atlas_valuation = None
        valuations = load_fundamental_valuations(ticker)
        if valuations.get("loaded") and valuations.get("valuation"):
            atlas_valuation = valuations["valuation"]

        # 6. Get current position if any
        portfolio_position = None
        portfolio = load_portfolio_state()
        if portfolio.get("loaded"):
            for pos in portfolio.get("positions", []):
                if pos.get("ticker", "").upper() == ticker.upper():
                    portfolio_position = pos
                    break

        # 7. Build prompt
        user_prompt = build_analysis_prompt(
            ticker=ticker,
            consensus_data=consensus,
            estimate_revisions=revisions,
            earnings_history=earnings_history,
            rating_changes=rating_changes,
            atlas_valuation=atlas_valuation,
            portfolio_position=portfolio_position,
        )

        # 8. Call Claude
        logger.info(f"[Consensus] Calling Claude...")
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2500,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}]
            )
            raw_response = response.content[0].text
        except Exception as e:
            logger.error(f"[Consensus] Claude API error: {e}")
            return None

        # 9. Parse JSON
        try:
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
            analysis["raw_consensus"] = consensus
            analysis["raw_revisions"] = revisions
            analysis["raw_earnings_history"] = earnings_history

            # Log summary
            logger.info(f"[Consensus] {ticker}: {analysis.get('consensus_rating')} "
                       f"({analysis.get('buy_pct', 'N/A')}% buy), "
                       f"Crowding: {analysis.get('crowding', {}).get('assessment', 'N/A')}")

            # Save
            self._save_brief(analysis)

            return analysis

        except json.JSONDecodeError as e:
            logger.error(f"[Consensus] Failed to parse response: {e}")
            return None

    def analyze_portfolio(self) -> List[Dict]:
        """
        Analyze consensus for all portfolio positions.

        Returns:
            List of consensus analyses
        """
        portfolio = load_portfolio_state()
        if not portfolio.get("loaded"):
            logger.warning("[Consensus] No portfolio loaded")
            return []

        results = []
        for position in portfolio.get("positions", []):
            ticker = position.get("ticker")
            if ticker:
                try:
                    analysis = self.analyze(ticker)
                    if analysis:
                        results.append(analysis)
                except Exception as e:
                    logger.error(f"Error analyzing {ticker}: {e}")
                    continue

        return results

    def find_biggest_revisions(self, tickers: List[str] = None) -> List[Dict]:
        """
        Find stocks with biggest estimate revisions.

        Args:
            tickers: List of tickers to check (defaults to UNIVERSE)

        Returns:
            List of stocks sorted by revision momentum
        """
        if tickers is None:
            tickers = list(UNIVERSE.keys())[:30]  # Top 30 for efficiency

        revisions = []
        for ticker in tickers:
            try:
                rev = self.consensus_client.get_estimate_revisions(ticker)
                if rev:
                    rev["ticker"] = ticker
                    revisions.append(rev)
            except:
                continue

        # Sort by number of upgrades - downgrades
        revisions.sort(
            key=lambda x: (x.get("upgrades_30d", 0) or 0) - (x.get("downgrades_30d", 0) or 0),
            reverse=True
        )

        return revisions

    def find_contrarian_opportunities(self, tickers: List[str] = None) -> List[Dict]:
        """
        Find stocks where ATLAS disagrees with consensus.

        Returns:
            List of contrarian opportunities
        """
        if tickers is None:
            tickers = list(UNIVERSE.keys())[:30]

        opportunities = []

        for ticker in tickers:
            try:
                # Get consensus
                consensus = self.consensus_client.get_consensus_snapshot(ticker)
                if not consensus:
                    continue

                # Get ATLAS valuation
                valuations = load_fundamental_valuations(ticker)
                if not valuations.get("loaded") or not valuations.get("valuation"):
                    continue

                atlas_val = valuations["valuation"]
                dcf = atlas_val.get("dcf_valuation", {})
                atlas_fair = dcf.get("base_case", 0)

                consensus_target = consensus.get("price_target", {}).get("mean", 0)
                current_price = consensus.get("current_price", 0)

                if not atlas_fair or not consensus_target or not current_price:
                    continue

                # Calculate divergence
                divergence_pct = (atlas_fair / consensus_target - 1) * 100 if consensus_target else 0

                if abs(divergence_pct) > 10:
                    opportunities.append({
                        "ticker": ticker,
                        "current_price": current_price,
                        "atlas_fair_value": atlas_fair,
                        "consensus_target": consensus_target,
                        "divergence_pct": round(divergence_pct, 1),
                        "atlas_position": "MORE_BULLISH" if divergence_pct > 0 else "MORE_BEARISH",
                        "consensus_rating": consensus.get("consensus_rating"),
                        "buy_pct": consensus.get("buy_pct"),
                    })

            except Exception as e:
                logger.debug(f"Error checking {ticker}: {e}")
                continue

        # Sort by absolute divergence
        opportunities.sort(key=lambda x: abs(x.get("divergence_pct", 0)), reverse=True)

        return opportunities

    def get_brief_for_cio(self, ticker: str = None) -> Dict:
        """Get simplified brief for CIO agent."""
        analysis = self.load_latest_brief(ticker)

        if not analysis:
            return {
                "agent": "Consensus",
                "status": "NO_DATA",
            }

        return {
            "agent": "Consensus",
            "ticker": analysis.get("ticker"),
            "consensus_rating": analysis.get("consensus_rating"),
            "buy_pct": analysis.get("buy_pct"),
            "analyst_count": analysis.get("analyst_count"),
            "price_target_mean": analysis.get("price_target", {}).get("mean"),
            "upside_pct": analysis.get("upside_to_target_pct"),
            "atlas_vs_consensus": analysis.get("atlas_vs_consensus", {}).get("atlas_position"),
            "divergence_pct": analysis.get("atlas_vs_consensus", {}).get("divergence_pct"),
            "estimate_trend": analysis.get("estimate_revisions", {}).get("direction"),
            "crowding": analysis.get("crowding", {}).get("assessment"),
            "earnings_beat_rate": analysis.get("earnings_history", {}).get("beat_rate_8q"),
            "signal": analysis.get("signal"),
            "confidence": analysis.get("confidence"),
            "brief_for_cio": analysis.get("brief_for_cio"),
        }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    parser = argparse.ArgumentParser(description="ATLAS Consensus Agent")
    parser.add_argument("--ticker", "-t", type=str, help="Analyze specific ticker")
    parser.add_argument("--portfolio", action="store_true", help="Analyze all portfolio companies")
    parser.add_argument("--revisions", action="store_true", help="Show stocks with biggest estimate revisions")
    parser.add_argument("--contrarian", action="store_true", help="Show where ATLAS disagrees with consensus")
    args = parser.parse_args()

    agent = ConsensusAgent()

    if args.revisions:
        print("\n" + "="*70)
        print("ATLAS Consensus Agent - Biggest Estimate Revisions")
        print("="*70 + "\n")

        revisions = agent.find_biggest_revisions()
        print("Stocks with most positive revision momentum:\n")
        for i, r in enumerate(revisions[:10], 1):
            upgrades = r.get("upgrades_30d", 0) or 0
            downgrades = r.get("downgrades_30d", 0) or 0
            net = upgrades - downgrades
            print(f"  {i}. {r['ticker']:6} | Upgrades: {upgrades} | Downgrades: {downgrades} | Net: {'+' if net > 0 else ''}{net}")

    elif args.contrarian:
        print("\n" + "="*70)
        print("ATLAS Consensus Agent - Contrarian Opportunities")
        print("="*70 + "\n")

        opps = agent.find_contrarian_opportunities()
        if opps:
            print("Stocks where ATLAS disagrees most with consensus:\n")
            for o in opps[:10]:
                print(f"  {o['ticker']:6} | ATLAS: ${o['atlas_fair_value']:,.0f} vs Consensus: ${o['consensus_target']:,.0f}")
                print(f"         | Divergence: {o['divergence_pct']:+.1f}% ({o['atlas_position']})")
                print(f"         | Consensus: {o['consensus_rating']} ({o['buy_pct']}% buy)")
                print()
        else:
            print("No significant divergences found. Need ATLAS valuations in state.")

    elif args.portfolio:
        print("\n" + "="*70)
        print("ATLAS Consensus Agent - Portfolio Analysis")
        print("="*70 + "\n")

        results = agent.analyze_portfolio()
        for r in results:
            print(f"\n{r['ticker']}:")
            print(f"  Consensus: {r.get('consensus_rating')} ({r.get('buy_pct')}% buy)")
            print(f"  Target: ${r.get('price_target', {}).get('mean', 'N/A')}")
            print(f"  Crowding: {r.get('crowding', {}).get('assessment', 'N/A')}")
            print(f"  Signal: {r.get('signal')}")

    elif args.ticker:
        print("\n" + "="*70)
        print(f"ATLAS Consensus Agent - {args.ticker.upper()}")
        print("="*70 + "\n")

        result = agent.analyze(args.ticker.upper())

        if result:
            print(f"Ticker: {result.get('ticker')}")
            print(f"Analyst Count: {result.get('analyst_count')}")
            print(f"Consensus Rating: {result.get('consensus_rating')}")
            print(f"Buy %: {result.get('buy_pct')}%")

            print(f"\nPRICE TARGET:")
            targets = result.get("price_target", {})
            print(f"  Mean: ${targets.get('mean', 'N/A')}")
            print(f"  Range: ${targets.get('low', 'N/A')} - ${targets.get('high', 'N/A')}")
            print(f"  Upside: {result.get('upside_to_target_pct', 'N/A')}%")

            atlas_vs = result.get("atlas_vs_consensus", {})
            if atlas_vs:
                print(f"\nATLAS VS CONSENSUS:")
                print(f"  ATLAS Value: ${atlas_vs.get('atlas_intrinsic', 'N/A')}")
                print(f"  Position: {atlas_vs.get('atlas_position', 'N/A')}")
                print(f"  Divergence: {atlas_vs.get('divergence_pct', 'N/A')}%")
                print(f"  Edge: {atlas_vs.get('edge_assessment', 'N/A')}")

            revisions = result.get("estimate_revisions", {})
            print(f"\nESTIMATE REVISIONS:")
            print(f"  Direction: {revisions.get('direction', 'N/A')}")

            crowding = result.get("crowding", {})
            print(f"\nCROWDING:")
            print(f"  Assessment: {crowding.get('assessment', 'N/A')}")
            print(f"  Risk: {crowding.get('positioning_risk', 'N/A')}")

            history = result.get("earnings_history", {})
            print(f"\nEARNINGS HISTORY:")
            print(f"  Beat Rate: {history.get('beat_rate_8q', 'N/A')}%")
            print(f"  Pattern: {history.get('pattern', 'N/A')}")

            print(f"\nSIGNAL: {result.get('signal')} | Confidence: {result.get('confidence', 0):.0%}")

            print(f"\nVERDICT:")
            print(f"  {result.get('verdict', 'N/A')}")

            print(f"\nBRIEF FOR CIO:")
            print(f"  {result.get('brief_for_cio', 'N/A')}")

        else:
            print("Analysis failed. Check logs.")

    else:
        print("Usage:")
        print("  python3 -m agents.consensus_agent --ticker AVGO")
        print("  python3 -m agents.consensus_agent --portfolio")
        print("  python3 -m agents.consensus_agent --revisions")
        print("  python3 -m agents.consensus_agent --contrarian")
