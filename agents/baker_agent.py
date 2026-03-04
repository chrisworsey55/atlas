"""
Gavin Baker Deep Tech Agent
Deep tech fundamental analysis with product-level knowledge.
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
from agents.prompts.baker_agent import SYSTEM_PROMPT, build_chat_prompt, build_analysis_prompt

logger = logging.getLogger(__name__)


class BakerAgent:
    """
    Gavin Baker style deep tech agent.
    Product-level knowledge, competitive dynamics expertise.
    """

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = CLAUDE_MODEL
        self.agent_name = "baker"

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
        Chat with the Baker agent.

        Args:
            message: User's question or request
            include_context: Whether to include portfolio and news context

        Returns:
            Structured response dict
        """
        logger.info(f"[Baker] Processing: {message[:50]}...")

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
            logger.error(f"[Baker] Claude API error: {e}")
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

            logger.info(f"[Baker] Response generated: {result.get('headline', 'No headline')[:50]}")
            return result

        except json.JSONDecodeError as e:
            logger.error(f"[Baker] Failed to parse response: {e}")
            return {
                "agent": self.agent_name,
                "raw_response": raw_response,
                "parse_error": str(e),
                "generated_at": datetime.utcnow().isoformat(),
            }

    def analyze(self, ticker: str, include_filing: bool = False) -> Optional[dict]:
        """
        Run Baker-style deep tech analysis on a ticker.
        """
        logger.info(f"[Baker] Analyzing: {ticker}")

        # Get price data
        price_data = None
        try:
            from data.price_client import PriceClient
            prices = PriceClient()
            info = prices.get_sector_info(ticker)
            price_data = {
                "price": prices.get_current_price(ticker),
                "market_cap": info.get("market_cap"),
                "pe_ratio": info.get("pe_ratio"),
                "return_30d": prices.get_returns(ticker, 30),
            }
        except Exception as e:
            logger.warning(f"Could not get price data: {e}")

        # Get filing text if requested
        filing_text = None
        xbrl_financials = None
        if include_filing:
            try:
                from data.edgar_client import EdgarClient
                edgar = EdgarClient()
                filings = edgar.get_recent_filings(ticker, ["10-K", "10-Q"], 180)
                if filings:
                    filing_text = edgar.download_filing_text(filings[0], max_chars=30000)
                    xbrl_financials = edgar.get_key_financials(ticker)
            except Exception as e:
                logger.warning(f"Could not get filing data: {e}")

        # Build prompt
        user_prompt = build_analysis_prompt(
            ticker=ticker,
            filing_text=filing_text,
            xbrl_financials=xbrl_financials,
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
            logger.error(f"[Baker] Claude API error: {e}")
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

            return result

        except json.JSONDecodeError as e:
            logger.error(f"[Baker] Failed to parse response: {e}")
            return None


def run_baker_chat(message: str) -> dict:
    """Convenience function for chat."""
    agent = BakerAgent()
    return agent.chat(message)


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    parser = argparse.ArgumentParser(description="Gavin Baker Deep Tech Agent")
    parser.add_argument("--test", action="store_true", help="Run test query")
    parser.add_argument("--chat", type=str, help="Chat message")
    parser.add_argument("--ticker", type=str, help="Analyze specific ticker")
    args = parser.parse_args()

    print("\n" + "="*60)
    print("GAVIN BAKER DEEP TECH AGENT")
    print("="*60 + "\n")

    agent = BakerAgent()

    if args.test:
        result = agent.chat("Is ALAB better than MRVL for AI networking?")
    elif args.chat:
        result = agent.chat(args.chat)
    elif args.ticker:
        result = agent.analyze(ticker=args.ticker)
    else:
        result = agent.chat("What's your current view on the semiconductor cycle?")

    if result:
        print("\n" + "="*60)
        print("RESPONSE")
        print("="*60)
        print(json.dumps(result, indent=2))
    else:
        print("Failed to get response")
