"""
Ackman Quality Compounder Agent
Bill Ackman style - concentrated, long-duration, quality compounders.
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
from agents.prompts.ackman_agent import SYSTEM_PROMPT, build_chat_prompt, build_analysis_prompt

logger = logging.getLogger(__name__)


class AckmanAgent:
    """
    Bill Ackman style quality compounder agent.
    Concentrated, long-duration, activist mindset.
    """

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = CLAUDE_MODEL
        self.agent_name = "ackman"

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

    def _load_fundamental_data(self) -> dict:
        """Load fundamental valuation data."""
        try:
            fund_path = Path(__file__).parent.parent / "data" / "state" / "fundamental_valuations.json"
            with open(fund_path) as f:
                data = json.load(f)
                return data.get("valuations", {})
        except Exception as e:
            logger.warning(f"Could not load fundamental data: {e}")
            return {}

    def chat(self, message: str, include_context: bool = True) -> Optional[dict]:
        """
        Chat with the Ackman agent.

        Args:
            message: User's question or request
            include_context: Whether to include portfolio and fundamental context

        Returns:
            Structured response dict
        """
        logger.info(f"[Ackman] Processing: {message[:50]}...")

        # Load context if requested
        portfolio = self._load_portfolio() if include_context else None
        news_context = self._load_news_context() if include_context else None
        fundamental_data = self._load_fundamental_data() if include_context else None

        # Build prompt
        user_prompt = build_chat_prompt(
            message=message,
            portfolio=portfolio,
            news_context=news_context,
            fundamental_data=fundamental_data,
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
            logger.error(f"[Ackman] Claude API error: {e}")
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

            logger.info(f"[Ackman] Response generated: {result.get('headline', 'No headline')[:50]}")
            return result

        except json.JSONDecodeError as e:
            logger.error(f"[Ackman] Failed to parse response: {e}")
            return {
                "agent": self.agent_name,
                "raw_response": raw_response,
                "parse_error": str(e),
                "generated_at": datetime.utcnow().isoformat(),
            }

    def analyze(self, ticker: str, include_filing: bool = False) -> Optional[dict]:
        """
        Run Ackman-style quality compounder analysis on a ticker.
        """
        logger.info(f"[Ackman] Analyzing: {ticker}")

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
                "52w_high": info.get("fiftyTwoWeekHigh"),
                "52w_low": info.get("fiftyTwoWeekLow"),
            }
        except Exception as e:
            logger.warning(f"Could not get price data: {e}")

        # Get fundamental metrics
        fundamental_metrics = None
        try:
            fund_data = self._load_fundamental_data()
            fundamental_metrics = fund_data.get(ticker, {})
        except Exception as e:
            logger.warning(f"Could not get fundamental data: {e}")

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
            fundamental_metrics=fundamental_metrics,
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
            logger.error(f"[Ackman] Claude API error: {e}")
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
            logger.error(f"[Ackman] Failed to parse response: {e}")
            return None


def run_ackman_chat(message: str) -> dict:
    """Convenience function for chat."""
    agent = AckmanAgent()
    return agent.chat(message)


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    parser = argparse.ArgumentParser(description="Ackman Quality Compounder Agent")
    parser.add_argument("--test", action="store_true", help="Run test query")
    parser.add_argument("--chat", type=str, help="Chat message")
    parser.add_argument("--ticker", type=str, help="Analyze specific ticker")
    args = parser.parse_args()

    print("\n" + "="*60)
    print("ACKMAN QUALITY COMPOUNDER AGENT")
    print("="*60 + "\n")

    agent = AckmanAgent()

    if args.test:
        result = agent.chat("Should we go activist on any holding?")
    elif args.chat:
        result = agent.chat(args.chat)
    elif args.ticker:
        result = agent.analyze(ticker=args.ticker)
    else:
        result = agent.chat("What quality compounders look attractive right now?")

    if result:
        print("\n" + "="*60)
        print("RESPONSE")
        print("="*60)
        print(json.dumps(result, indent=2))
    else:
        print("Failed to get response")
