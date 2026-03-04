"""
CIO Agent
Chief Investment Officer — synthesizes desk briefs into portfolio decisions.
"""
import json
import logging
from typing import Optional
from datetime import datetime, date
from pathlib import Path

import anthropic

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL_PREMIUM
from agents.prompts.cio_agent import SYSTEM_PROMPT, build_cio_prompt

logger = logging.getLogger(__name__)


class CIOAgent:
    """
    Chief Investment Officer agent.
    Synthesizes all desk briefs and flow data into portfolio decisions.
    """
    
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = CLAUDE_MODEL_PREMIUM  # Use opus for CIO decisions
    
    def run(
        self,
        desk_briefs: list[dict] = None,
        flow_briefing: dict = None,
        current_portfolio: dict = None,
        active_theses: list[dict] = None,
        market_context: str = None,
    ) -> Optional[dict]:
        """
        Run the CIO synthesis and generate trade decisions.
        
        Args:
            desk_briefs: List of structured briefs from sector desks
            flow_briefing: Institutional flow analysis
            current_portfolio: Current portfolio state
            active_theses: Active investment theses
            market_context: Optional macro context string
        
        Returns:
            CIO decision package with trade recommendations
        """
        # Default values
        if desk_briefs is None:
            desk_briefs = self._fetch_latest_briefs()
        
        if flow_briefing is None:
            flow_briefing = self._fetch_latest_flow()
        
        if current_portfolio is None:
            current_portfolio = self._get_current_portfolio()
        
        if active_theses is None:
            active_theses = self._fetch_active_theses()
        
        logger.info(f"CIO synthesizing {len(desk_briefs)} desk briefs...")
        
        # Build the mega prompt
        user_prompt = build_cio_prompt(
            desk_briefs=desk_briefs,
            flow_briefing=flow_briefing,
            current_portfolio=current_portfolio,
            active_theses=active_theses,
            market_context=market_context,
        )
        
        # Call Claude (opus for CIO)
        logger.info(f"Calling {self.model} for CIO synthesis...")
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}]
            )
            raw_response = response.content[0].text
        except Exception as e:
            logger.error(f"CIO Claude API error: {e}")
            return None
        
        # Parse JSON response
        try:
            if "```json" in raw_response:
                json_str = raw_response.split("```json")[1].split("```")[0]
            elif "```" in raw_response:
                json_str = raw_response.split("```")[1].split("```")[0]
            else:
                json_str = raw_response
            
            decisions = json.loads(json_str.strip())
            decisions["generated_at"] = datetime.utcnow().isoformat()
            decisions["model_used"] = self.model
            decisions["briefs_analyzed"] = len(desk_briefs)
            
            # Log summary
            num_trades = len(decisions.get("trade_decisions", []))
            logger.info(f"CIO generated {num_trades} trade decisions")
            
            return decisions
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse CIO response: {e}")
            logger.debug(f"Raw response: {raw_response[:500]}...")
            return None
    
    def _fetch_latest_briefs(self) -> list[dict]:
        """Fetch latest desk briefs from database."""
        try:
            from database import get_session, AtlasDeskBrief
            
            session = get_session()
            # Get briefs from last 7 days
            from datetime import timedelta
            cutoff = date.today() - timedelta(days=7)
            
            briefs = session.query(AtlasDeskBrief).filter(
                AtlasDeskBrief.analysis_date >= cutoff
            ).order_by(AtlasDeskBrief.analysis_date.desc()).all()
            
            result = []
            seen = set()
            for brief in briefs:
                # Get latest per ticker per desk
                key = (brief.company_id, brief.desk_name)
                if key not in seen:
                    seen.add(key)
                    result.append(brief.brief_json)
            
            session.close()
            logger.info(f"Fetched {len(result)} briefs from database")
            return result
            
        except Exception as e:
            logger.warning(f"Could not fetch briefs from DB: {e}")
            return []
    
    def _fetch_latest_flow(self) -> dict:
        """Fetch latest institutional flow briefing."""
        try:
            from agents.institutional_flow_agent import InstitutionalFlowAgent
            agent = InstitutionalFlowAgent()
            return agent.thirteenf.build_consensus_report(
                agent.thirteenf.get_all_fund_holdings(cache_hours=24)
            )
        except Exception as e:
            logger.warning(f"Could not fetch flow briefing: {e}")
            return {}
    
    def _get_current_portfolio(self) -> dict:
        """Get current portfolio state."""
        try:
            from database import get_session, AtlasPortfolioSnapshot
            
            session = get_session()
            latest = session.query(AtlasPortfolioSnapshot).order_by(
                AtlasPortfolioSnapshot.date.desc()
            ).first()
            session.close()
            
            if latest:
                return {
                    "total_value": latest.total_value,
                    "cash": latest.cash,
                    "cash_pct": (latest.cash / latest.total_value * 100) if latest.total_value else 10,
                    "num_positions": latest.num_positions,
                    "positions": latest.positions_json or [],
                }
        except Exception as e:
            logger.warning(f"Could not fetch portfolio from DB: {e}")
        
        # Default: starting portfolio
        from config.settings import STARTING_CAPITAL
        return {
            "total_value": STARTING_CAPITAL,
            "cash": STARTING_CAPITAL,
            "cash_pct": 100,
            "num_positions": 0,
            "positions": [],
        }
    
    def _fetch_active_theses(self) -> list[dict]:
        """Fetch active investment theses."""
        try:
            from database import get_session, AtlasThesis, AtlasCompany
            
            session = get_session()
            theses = session.query(AtlasThesis).filter(
                AtlasThesis.status == "ACTIVE"
            ).all()
            
            result = []
            for thesis in theses:
                company = session.query(AtlasCompany).get(thesis.company_id)
                result.append({
                    "ticker": company.ticker if company else "UNKNOWN",
                    "direction": thesis.direction,
                    "confidence": thesis.confidence,
                    "catalyst": thesis.catalyst,
                    "invalidation": thesis.invalidation_criteria,
                })
            
            session.close()
            return result
            
        except Exception as e:
            logger.warning(f"Could not fetch theses from DB: {e}")
            return []
    
    def persist_decisions(self, decisions: dict):
        """Save CIO decisions to database (for audit trail)."""
        # TODO: Create atlas_cio_decisions table and persist
        logger.info("CIO decisions persistence not yet implemented")

    def _load_portfolio_state(self) -> dict:
        """Load portfolio state from JSON file."""
        try:
            portfolio_path = Path(__file__).parent.parent / "data" / "state" / "positions.json"
            with open(portfolio_path) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load portfolio state: {e}")
            return self._get_current_portfolio()

    def _load_news_context(self) -> str:
        """Load news context from JSON file."""
        try:
            news_path = Path(__file__).parent.parent / "data" / "state" / "news_briefs.json"
            with open(news_path) as f:
                news = json.load(f)
                return news.get("24h_summary", "")
        except Exception as e:
            logger.warning(f"Could not load news context: {e}")
            return ""

    def chat(self, message: str, include_context: bool = True) -> Optional[dict]:
        """
        Chat with the CIO agent, synthesizing multiple superinvestor perspectives.

        The CIO synthesizes views from:
        - Druckenmiller: Top-down macro, concentrated bets, 1-6 month horizon
        - Aschenbrenner: AI infrastructure bottleneck thesis, extreme concentration
        - Baker: Deep tech fundamental, product-level analysis
        - Ackman: Quality compounders, 3-5 year horizon, activist mindset

        Args:
            message: User's question or request
            include_context: Whether to include portfolio and news context

        Returns:
            Synthesized CIO response
        """
        logger.info(f"[CIO] Processing: {message[:50]}...")

        # Load all context
        portfolio = self._load_portfolio_state() if include_context else {}
        news_context = self._load_news_context() if include_context else ""
        flow_briefing = self._fetch_latest_flow() if include_context else {}

        # Build comprehensive prompt with 4 superinvestor framework
        prompt_parts = [
            f"## CIO CHAT SESSION",
            f"## DATE: {datetime.now().strftime('%Y-%m-%d')}",
            "",
        ]

        if portfolio:
            prompt_parts.extend([
                "## CURRENT ATLAS PORTFOLIO",
                f"Total Value: ${portfolio.get('total_value', 0):,.0f}",
                f"Cash: ${portfolio.get('cash', 0):,.0f} ({portfolio.get('cash_pct', 0):.1f}%)",
                "",
            ])
            if portfolio.get('positions'):
                prompt_parts.append("### Positions:")
                for pos in portfolio['positions']:
                    pnl = pos.get('pnl_pct', 0)
                    pnl_str = f"+{pnl:.1f}%" if pnl >= 0 else f"{pnl:.1f}%"
                    prompt_parts.append(
                        f"- {pos['ticker']} ({pos['direction']}): {pos.get('allocation_pct', pos.get('size_pct', 0)):.1f}% | "
                        f"Entry ${pos.get('entry_price', 0):.2f} | Current ${pos.get('current_price', 0):.2f} | "
                        f"P&L {pnl_str} | {pos.get('thesis', '')}"
                    )
                prompt_parts.append("")

        if news_context:
            prompt_parts.extend([
                "## NEWS CONTEXT",
                news_context,
                "",
            ])

        if flow_briefing and flow_briefing.get('consensus_builds'):
            prompt_parts.extend([
                "## INSTITUTIONAL FLOW SIGNALS",
            ])
            for item in flow_briefing.get('consensus_builds', [])[:3]:
                prompt_parts.append(f"- Consensus Build: {item.get('ticker', 'N/A')}")
            for item in flow_briefing.get('crowding_warnings', [])[:3]:
                prompt_parts.append(f"- Crowding Warning: {item.get('ticker', 'N/A')}")
            prompt_parts.append("")

        prompt_parts.extend([
            "## SUPERINVESTOR SYNTHESIS FRAMEWORK",
            "",
            "You must consider ALL FOUR perspectives when responding:",
            "",
            "### 1. DRUCKENMILLER (Macro)",
            "- Style: Top-down macro, concentrated bets",
            "- Horizon: 1-6 months",
            "- Key question: What's the Fed doing? Where is liquidity flowing?",
            "",
            "### 2. ASCHENBRENNER (AI Infrastructure)",
            "- Style: Thesis-driven, bottleneck-chasing, extreme concentration",
            "- Horizon: 6-24 months",
            "- Key question: What's the current bottleneck in the AI value chain?",
            "",
            "### 3. BAKER (Deep Tech)",
            "- Style: Product-level fundamental analysis",
            "- Horizon: 3-12 months",
            "- Key question: Why does this product win? What's the competitive moat?",
            "",
            "### 4. ACKMAN (Quality Compounder)",
            "- Style: Concentrated, long-duration, activist",
            "- Horizon: 3-5 years",
            "- Key question: Is this a simple, predictable, FCF-generative business?",
            "",
            "## USER QUESTION",
            message,
            "",
            "## YOUR TASK",
            "Synthesize all four superinvestor perspectives into a unified CIO response.",
            "If they disagree, explain the tension and make a judgment call.",
            "Always be specific about portfolio implications.",
            "",
            "Respond with valid JSON matching the CIO output schema.",
        ])

        user_prompt = "\n".join(prompt_parts)

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
            logger.error(f"[CIO] Claude API error: {e}")
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
            result["agent"] = "cio"
            result["generated_at"] = datetime.utcnow().isoformat()
            result["model_used"] = self.model
            result["perspectives_synthesized"] = ["druckenmiller", "aschenbrenner", "baker", "ackman"]

            logger.info(f"[CIO] Response generated successfully")
            return result

        except json.JSONDecodeError as e:
            logger.error(f"[CIO] Failed to parse response: {e}")
            return {
                "agent": "cio",
                "raw_response": raw_response,
                "parse_error": str(e),
                "generated_at": datetime.utcnow().isoformat(),
            }


def run_cio_synthesis(
    desk_briefs: list[dict] = None,
    flow_briefing: dict = None,
    market_context: str = None,
) -> dict:
    """
    Convenience function to run CIO synthesis.
    """
    agent = CIOAgent()
    return agent.run(
        desk_briefs=desk_briefs,
        flow_briefing=flow_briefing,
        market_context=market_context,
    )


if __name__ == "__main__":
    import argparse
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )
    
    parser = argparse.ArgumentParser(description="ATLAS CIO Agent")
    parser.add_argument("--test", action="store_true", help="Run with test data")
    args = parser.parse_args()
    
    print("\n" + "="*60)
    print("ATLAS CIO Agent")
    print("="*60 + "\n")
    
    if args.test:
        # Test with sample briefs
        test_briefs = [
            {
                "ticker": "NVDA",
                "desk": "Semiconductor",
                "signal": "BULLISH",
                "confidence": 0.85,
                "brief_for_cio": "Strong AI datacenter demand. China risk at $19.7B. Customer concentration at 22%. Inventory healthy.",
                "bull_case": "AI capex cycle extending. Dominant position in training and inference.",
                "bear_case": "Valuation stretched. China restrictions could tighten. Customer concentration risk.",
                "catalysts": {
                    "upcoming": ["Q4 earnings Feb 21", "GTC conference March"],
                    "risks": ["China export controls", "Hyperscaler custom silicon"]
                }
            },
            {
                "ticker": "LLY",
                "desk": "Biotech",
                "signal": "BULLISH",
                "confidence": 0.85,
                "brief_for_cio": "GLP-1 franchise driving exceptional growth. $65B revenue. 46x P/E is expensive but justified by pipeline.",
                "bull_case": "Dominant GLP-1 position. Obesity market expanding. Strong pipeline depth.",
                "bear_case": "High valuation. Competition from Novo. Manufacturing capacity constraints.",
                "catalysts": {
                    "upcoming": ["Tirzepatide label expansion", "Oral GLP-1 data"],
                    "risks": ["Competitor readouts", "Pricing pressure"]
                }
            }
        ]
        
        test_flow = {
            "consensus_builds": [
                {"ticker": "AVGO", "funds_accumulating": ["Druckenmiller", "Tepper", "Coatue"]},
            ],
            "crowding_warnings": [
                {"ticker": "NVDA", "funds_holding": 14, "of_total": 16, "signal": "Extreme crowding"}
            ],
            "contrarian_signals": [
                {"ticker": "PFE", "fund": "Baupost (Klarman)", "portfolio_pct": 8.2}
            ],
            "conviction_positions": [
                {"ticker": "AAPL", "fund": "Berkshire (Buffett)", "portfolio_pct": 45.0}
            ]
        }
        
        decisions = run_cio_synthesis(
            desk_briefs=test_briefs,
            flow_briefing=test_flow,
            market_context="Risk-on environment. Fed signaling rate cuts. AI narrative strong."
        )
    else:
        # Run with real data from database
        decisions = run_cio_synthesis()
    
    if decisions:
        print("\n" + "="*60)
        print("CIO DECISIONS")
        print("="*60)
        print(json.dumps(decisions, indent=2))
    else:
        print("CIO synthesis failed")
