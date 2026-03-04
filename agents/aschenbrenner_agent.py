"""
Aschenbrenner AI Infrastructure Agent
Leopold Aschenbrenner style - thesis-driven, bottleneck-chasing, non-consensus AI infrastructure investing.
"""
import json
import logging
import os
from typing import Optional
from datetime import datetime
from pathlib import Path

import anthropic

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL
from agents.prompts.aschenbrenner_agent import SYSTEM_PROMPT, build_chat_prompt, build_analysis_prompt

logger = logging.getLogger(__name__)


class AschenbrennerAgent:
    """
    Leopold Aschenbrenner style AI infrastructure agent.
    Thesis-driven, bottleneck-chasing, non-consensus.
    """

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = CLAUDE_MODEL
        self.agent_name = "aschenbrenner"

    def _load_portfolio(self) -> dict:
        """Load current portfolio state."""
        try:
            portfolio_path = Path(__file__).parent.parent / "data" / "state" / "positions.json"
            with open(portfolio_path) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load portfolio: {e}")
            return {}

    def _load_news_context(self) -> str:
        """Load current news context."""
        try:
            news_path = Path(__file__).parent.parent / "data" / "state" / "news_briefs.json"
            with open(news_path) as f:
                news = json.load(f)
                return news.get("24h_summary", "")
        except Exception as e:
            logger.warning(f"Could not load news: {e}")
            return ""

    def _load_flow_data(self) -> dict:
        """Load institutional flow data."""
        try:
            from agents.institutional_flow_agent import InstitutionalFlowAgent
            agent = InstitutionalFlowAgent()
            return agent.thirteenf.build_consensus_report(
                agent.thirteenf.get_all_fund_holdings(cache_hours=24)
            )
        except Exception as e:
            logger.warning(f"Could not load flow data: {e}")
            return {}

    def chat(self, message: str, include_context: bool = True) -> Optional[dict]:
        """
        Chat with the Aschenbrenner agent.

        Args:
            message: User's question or request
            include_context: Whether to include portfolio and news context

        Returns:
            Structured response dict
        """
        logger.info(f"[Aschenbrenner] Processing: {message[:50]}...")

        # Load context if requested
        portfolio = self._load_portfolio() if include_context else None
        news_context = self._load_news_context() if include_context else None
        flow_data = self._load_flow_data() if include_context else None

        # Build prompt
        user_prompt = build_chat_prompt(
            message=message,
            portfolio=portfolio,
            news_context=news_context,
            flow_data=flow_data,
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
            logger.error(f"[Aschenbrenner] Claude API error: {e}")
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
            result["generated_at"] = datetime.utcnow().isoformat()
            result["model_used"] = self.model
            result["agent"] = self.agent_name

            logger.info(f"[Aschenbrenner] Response generated: {result.get('headline', 'No headline')[:50]}")
            return result

        except json.JSONDecodeError as e:
            logger.error(f"[Aschenbrenner] Failed to parse response: {e}")
            # Return raw response as fallback
            return {
                "agent": self.agent_name,
                "raw_response": raw_response,
                "parse_error": str(e),
                "generated_at": datetime.utcnow().isoformat(),
            }

    def analyze(self, ticker: str = None, sector: str = None) -> Optional[dict]:
        """
        Run Aschenbrenner-style analysis on a ticker or sector.
        """
        logger.info(f"[Aschenbrenner] Analyzing: {ticker or sector}")

        # Get price data if ticker provided
        price_data = None
        if ticker:
            try:
                from data.price_client import PriceClient
                prices = PriceClient()
                price_data = {
                    "price": prices.get_current_price(ticker),
                    "market_cap": prices.get_sector_info(ticker).get("market_cap"),
                    "return_30d": prices.get_returns(ticker, 30),
                }
            except Exception as e:
                logger.warning(f"Could not get price data: {e}")

        # Build prompt
        user_prompt = build_analysis_prompt(
            ticker=ticker,
            sector=sector,
            price_data=price_data,
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
            logger.error(f"[Aschenbrenner] Claude API error: {e}")
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
            result["generated_at"] = datetime.utcnow().isoformat()
            result["model_used"] = self.model
            result["agent"] = self.agent_name
            result["analyzed_ticker"] = ticker
            result["analyzed_sector"] = sector

            return result

        except json.JSONDecodeError as e:
            logger.error(f"[Aschenbrenner] Failed to parse response: {e}")
            return None


def run_aschenbrenner_chat(message: str) -> dict:
    """Convenience function for chat."""
    agent = AschenbrennerAgent()
    return agent.chat(message)


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    parser = argparse.ArgumentParser(description="Aschenbrenner AI Infrastructure Agent")
    parser.add_argument("--test", action="store_true", help="Run test query")
    parser.add_argument("--chat", type=str, help="Chat message")
    parser.add_argument("--ticker", type=str, help="Analyze specific ticker")
    args = parser.parse_args()

    print("\n" + "="*60)
    print("ASCHENBRENNER AI INFRASTRUCTURE AGENT")
    print("="*60 + "\n")

    agent = AschenbrennerAgent()

    if args.test:
        result = agent.chat("Where is the next bottleneck after power?")
    elif args.chat:
        result = agent.chat(args.chat)
    elif args.ticker:
        result = agent.analyze(ticker=args.ticker)
    else:
        result = agent.chat("What's your current thesis on AI infrastructure?")

    if result:
        print("\n" + "="*60)
        print("RESPONSE")
        print("="*60)
        print(json.dumps(result, indent=2))
    else:
        print("Failed to get response")
