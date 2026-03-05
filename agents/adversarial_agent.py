"""
Adversarial Agent
Challenges every CIO trade decision before execution.
"""
import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
from pathlib import Path

import anthropic

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL_PREMIUM
from agents.prompts.adversarial_agent import SYSTEM_PROMPT, build_adversarial_prompt
from agents.chat_mixin import ChatMixin, ADVERSARIAL_CHAT_PROMPT

logger = logging.getLogger(__name__)

# State file for persisting reviews
STATE_DIR = Path(__file__).resolve().parent.parent / "data" / "state"
ADVERSARIAL_STATE_FILE = STATE_DIR / "adversarial_reviews.json"


class AdversarialAgent(ChatMixin):
    """
    Adversarial agent that challenges trade decisions.
    Acts as the fund's internal risk committee.
    """

    CHAT_SYSTEM_PROMPT = ADVERSARIAL_CHAT_PROMPT
    desk_name = "adversarial"

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = CLAUDE_MODEL_PREMIUM  # Use opus for adversarial review
        self._ensure_state_dir()

    def _ensure_state_dir(self):
        """Ensure state directory exists."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)

    def _load_previous_analysis(self) -> Optional[dict]:
        """Load the most recent adversarial review."""
        if ADVERSARIAL_STATE_FILE.exists():
            try:
                with open(ADVERSARIAL_STATE_FILE, "r") as f:
                    reviews = json.load(f)
                if reviews:
                    return reviews[-1]
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load previous adversarial review: {e}")
        return None

    def _save_review(self, review: dict):
        """Save review to state file."""
        reviews = []
        if ADVERSARIAL_STATE_FILE.exists():
            try:
                with open(ADVERSARIAL_STATE_FILE, "r") as f:
                    reviews = json.load(f)
            except (json.JSONDecodeError, IOError):
                reviews = []

        reviews.append(review)
        reviews = reviews[-30:]

        with open(ADVERSARIAL_STATE_FILE, "w") as f:
            json.dump(reviews, f, indent=2, default=str)

    def load_latest_brief(self) -> Optional[dict]:
        """Load the most recent review for chat context."""
        return self._load_previous_analysis()
    
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
