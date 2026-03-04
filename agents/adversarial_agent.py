"""
Adversarial Agent
Challenges every CIO trade decision before execution.
"""
import json
import logging
from typing import Optional
from datetime import datetime
from pathlib import Path

import anthropic

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL_PREMIUM
from agents.prompts.adversarial_agent import SYSTEM_PROMPT, build_adversarial_prompt

logger = logging.getLogger(__name__)


class AdversarialAgent:
    """
    Adversarial agent that challenges trade decisions.
    Acts as the fund's internal risk committee.
    """
    
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = CLAUDE_MODEL_PREMIUM  # Use opus for adversarial review
    
    def review(
        self,
        trade_decision: dict,
        portfolio_context: dict = None,
    ) -> Optional[dict]:
        """
        Review a single trade decision from the CIO.
        
        Args:
            trade_decision: The CIO's trade decision to challenge
            portfolio_context: Current portfolio state for correlation analysis
        
        Returns:
            Adversarial review with verdict (APPROVE/MODIFY/BLOCK)
        """
        ticker = trade_decision.get('ticker', 'UNKNOWN')
        action = trade_decision.get('action', 'UNKNOWN')
        
        logger.info(f"Adversarial review: {action} {ticker}...")
        
        # Build the challenge prompt
        user_prompt = build_adversarial_prompt(
            trade_decision=trade_decision,
            portfolio_context=portfolio_context,
        )
        
        # Call Claude (opus for adversarial)
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}]
            )
            raw_response = response.content[0].text
        except Exception as e:
            logger.error(f"Adversarial Claude API error: {e}")
            # Fail safe: BLOCK on API error
            return {
                "ticker": ticker,
                "cio_action": action,
                "verdict": "BLOCK",
                "fatal_flaw": f"Adversarial review failed: {e}",
                "risk_score": 1.0,
            }
        
        # Parse JSON response
        try:
            if "```json" in raw_response:
                json_str = raw_response.split("```json")[1].split("```")[0]
            elif "```" in raw_response:
                json_str = raw_response.split("```")[1].split("```")[0]
            else:
                json_str = raw_response
            
            review = json.loads(json_str.strip())
            review["reviewed_at"] = datetime.utcnow().isoformat()
            review["model_used"] = self.model
            
            verdict = review.get("verdict", "BLOCK")
            risk_score = review.get("risk_score", 0.5)
            logger.info(f"Adversarial verdict for {ticker}: {verdict} (risk: {risk_score:.2f})")
            
            return review
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse adversarial response: {e}")
            # Fail safe: BLOCK on parse error
            return {
                "ticker": ticker,
                "cio_action": action,
                "verdict": "BLOCK",
                "fatal_flaw": f"Could not parse adversarial review: {e}",
                "risk_score": 1.0,
            }
    
    def chat(self, message: str, include_context: bool = True) -> Optional[dict]:
        """
        Chat with the adversarial agent for risk assessment.
        """
        logger.info(f"[Adversarial] Processing: {message[:50]}...")

        # Load portfolio context
        portfolio = None
        if include_context:
            try:
                portfolio_path = Path(__file__).parent.parent / "data" / "state" / "positions.json"
                with open(portfolio_path) as f:
                    portfolio = json.load(f)
            except Exception as e:
                logger.warning(f"Could not load portfolio: {e}")
                portfolio = {}

        # Build prompt for chat-style interaction
        prompt_parts = [
            f"## DATE: {datetime.utcnow().strftime('%Y-%m-%d')}",
            "",
        ]

        if portfolio:
            prompt_parts.extend([
                "## CURRENT PORTFOLIO",
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
                        f"- {pos['ticker']} ({pos['direction']}): {pos.get('allocation_pct', pos.get('size_pct', 0)):.1f}% | P&L: {pnl_str}"
                    )
                prompt_parts.append("")

        prompt_parts.extend([
            "## USER QUESTION",
            message,
            "",
            "Respond with risk analysis, identifying potential flaws and blind spots.",
        ])

        # Call Claude
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": "\n".join(prompt_parts)}]
            )
            raw_response = response.content[0].text
        except Exception as e:
            logger.error(f"[Adversarial] Claude API error: {e}")
            return None

        return {
            "agent": "adversarial",
            "response": raw_response,
            "generated_at": datetime.utcnow().isoformat(),
            "model_used": self.model,
        }

    def review_all(
        self,
        trade_decisions: list[dict],
        portfolio_context: dict = None,
    ) -> list[dict]:
        """
        Review all trade decisions from a CIO package.
        
        Args:
            trade_decisions: List of CIO trade decisions
            portfolio_context: Current portfolio state
        
        Returns:
            List of adversarial reviews
        """
        reviews = []
        
        for decision in trade_decisions:
            # Skip HOLD and AVOID actions (no trade to review)
            action = decision.get('action', '').upper()
            if action in ('HOLD', 'AVOID', 'WATCH', 'WATCHLIST'):
                logger.info(f"Skipping adversarial review for {decision.get('ticker')}: {action}")
                continue
            
            review = self.review(decision, portfolio_context)
            if review:
                reviews.append(review)
        
        # Summary
        approved = sum(1 for r in reviews if r.get('verdict') == 'APPROVE')
        modified = sum(1 for r in reviews if r.get('verdict') == 'MODIFY')
        blocked = sum(1 for r in reviews if r.get('verdict') == 'BLOCK')
        
        logger.info(f"Adversarial review complete: {approved} approved, {modified} modified, {blocked} blocked")
        
        return reviews


def merge_decision_with_review(decision: dict, review: dict) -> dict:
    """
    Merge a CIO decision with its adversarial review.
    Returns the final trade to execute (or None if blocked).
    """
    verdict = review.get('verdict', 'BLOCK')
    
    if verdict == 'BLOCK':
        return None
    
    merged = decision.copy()
    merged['adversarial_review'] = review
    
    if verdict == 'MODIFY':
        mods = review.get('modifications', {})
        
        # Apply modifications
        if mods.get('new_size_pct') is not None:
            merged['size_pct'] = mods['new_size_pct']
        
        if mods.get('new_stop_loss_pct') is not None:
            merged['stop_loss_pct'] = mods['new_stop_loss_pct']
        
        merged['conditions'] = mods.get('conditions', [])
        merged['modified_by_adversarial'] = True
    
    merged['monitoring_requirements'] = review.get('monitoring_requirements', [])
    
    return merged


if __name__ == "__main__":
    import argparse
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )
    
    parser = argparse.ArgumentParser(description="ATLAS Adversarial Agent")
    parser.add_argument("--test", action="store_true", help="Run with test data")
    args = parser.parse_args()
    
    print("\n" + "="*60)
    print("ATLAS Adversarial Agent")
    print("="*60 + "\n")
    
    if args.test:
        # Test trade to challenge
        test_trade = {
            "ticker": "NVDA",
            "action": "BUY",
            "size_pct": 0.08,
            "rationale": "Semi desk BULLISH (0.85 confidence). AI datacenter demand strong. China risk acknowledged but manageable.",
            "stop_loss_pct": -0.08,
            "invalidation": "Gross margin decline >200bps or loss of major hyperscaler customer",
            "urgency": "THIS_WEEK"
        }
        
        test_portfolio = {
            "num_positions": 5,
            "cash_pct": 15,
            "positions": [
                {"ticker": "AMD", "size_pct": 0.05},
                {"ticker": "AVGO", "size_pct": 0.06},
                {"ticker": "MSFT", "size_pct": 0.04},
            ],
            "sector_exposure": {
                "Technology": 0.15,
                "Healthcare": 0.05,
            }
        }
        
        agent = AdversarialAgent()
        review = agent.review(test_trade, test_portfolio)
        
        print("\n" + "="*60)
        print("ADVERSARIAL REVIEW")
        print("="*60)
        print(json.dumps(review, indent=2))
    else:
        print("Run with --test for test mode")
