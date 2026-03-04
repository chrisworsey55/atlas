"""
News & Geopolitical Intelligence Agent
Real-time news scanning and portfolio impact assessment.
"""
import json
import logging
import os
import xml.etree.ElementTree as ET
from typing import Optional, List
from datetime import datetime, timedelta
from pathlib import Path
import urllib.request
import urllib.error

import anthropic

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL
from agents.prompts.news_agent import (
    SYSTEM_PROMPT,
    build_scan_prompt,
    build_chat_prompt,
    NEWS_FEEDS,
)

logger = logging.getLogger(__name__)


class NewsAgent:
    """
    News & Geopolitical Intelligence Agent.
    Scans news sources and produces portfolio impact assessments.
    """

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = CLAUDE_MODEL
        self.agent_name = "news"
        self.state_path = Path(__file__).parent.parent / "data" / "state" / "news_briefs.json"

    def _load_portfolio(self) -> dict:
        """Load current portfolio state."""
        try:
            portfolio_path = Path(__file__).parent.parent / "data" / "state" / "positions.json"
            with open(portfolio_path) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load portfolio: {e}")
            return {}

    def _load_previous_brief(self) -> dict:
        """Load previous news brief."""
        try:
            with open(self.state_path) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load previous brief: {e}")
            return {}

    def _save_brief(self, brief: dict):
        """Save news brief to state."""
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_path, 'w') as f:
                json.dump(brief, f, indent=2)
            logger.info(f"Saved news brief to {self.state_path}")
        except Exception as e:
            logger.error(f"Failed to save brief: {e}")

    def _fetch_rss_feed(self, url: str, source_name: str) -> List[dict]:
        """Fetch and parse an RSS feed."""
        headlines = []
        try:
            req = urllib.request.Request(
                url,
                headers={'User-Agent': 'ATLAS News Agent/1.0'}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                content = response.read()

            root = ET.fromstring(content)

            # Handle different RSS formats
            items = root.findall('.//item') or root.findall('.//{http://www.w3.org/2005/Atom}entry')

            for item in items[:15]:  # Limit to 15 items per feed
                title = item.find('title')
                if title is None:
                    title = item.find('{http://www.w3.org/2005/Atom}title')

                pub_date = item.find('pubDate')
                if pub_date is None:
                    pub_date = item.find('{http://www.w3.org/2005/Atom}published')

                description = item.find('description')
                if description is None:
                    description = item.find('{http://www.w3.org/2005/Atom}summary')

                link = item.find('link')
                if link is None:
                    link = item.find('{http://www.w3.org/2005/Atom}link')
                    if link is not None:
                        link_url = link.get('href', '')
                    else:
                        link_url = ''
                else:
                    link_url = link.text if link.text else ''

                headlines.append({
                    "title": title.text if title is not None and title.text else "No title",
                    "source": source_name,
                    "published": pub_date.text if pub_date is not None and pub_date.text else "",
                    "summary": description.text[:300] if description is not None and description.text else "",
                    "url": link_url,
                })

            logger.info(f"Fetched {len(headlines)} headlines from {source_name}")

        except Exception as e:
            logger.warning(f"Failed to fetch {source_name}: {e}")

        return headlines

    def scan(self, feeds: List[str] = None) -> dict:
        """
        Scan news feeds and produce portfolio impact assessment.

        Args:
            feeds: List of feed names to scan (defaults to all)

        Returns:
            News brief with impact assessment
        """
        logger.info("Starting news scan...")

        # Fetch headlines from all feeds
        all_headlines = []
        feeds_to_scan = feeds or list(NEWS_FEEDS.keys())

        for feed_name in feeds_to_scan:
            if feed_name in NEWS_FEEDS:
                headlines = self._fetch_rss_feed(NEWS_FEEDS[feed_name], feed_name)
                all_headlines.extend(headlines)

        if not all_headlines:
            logger.warning("No headlines fetched")
            return {
                "agent": self.agent_name,
                "timestamp": datetime.utcnow().isoformat(),
                "alert_level": "NORMAL",
                "error": "No headlines available",
            }

        logger.info(f"Total headlines fetched: {len(all_headlines)}")

        # Load context
        portfolio = self._load_portfolio()
        previous_brief = self._load_previous_brief()

        # Build prompt
        user_prompt = build_scan_prompt(
            headlines=all_headlines,
            portfolio=portfolio,
            previous_brief=previous_brief,
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
            logger.error(f"[News] Claude API error: {e}")
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
            result["timestamp"] = datetime.utcnow().isoformat()
            result["last_scan"] = datetime.utcnow().isoformat()
            result["headlines_scanned"] = len(all_headlines)

            # Save to state
            self._save_brief(result)

            logger.info(f"[News] Scan complete. Alert level: {result.get('alert_level', 'UNKNOWN')}")
            return result

        except json.JSONDecodeError as e:
            logger.error(f"[News] Failed to parse response: {e}")
            return {
                "agent": self.agent_name,
                "raw_response": raw_response,
                "parse_error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            }

    def impact(self, ticker: str = None) -> dict:
        """
        Get portfolio impact assessment for current news.

        Args:
            ticker: Optional specific ticker to focus on
        """
        brief = self._load_previous_brief()

        if not brief or not brief.get("top_stories"):
            # Run a scan first
            brief = self.scan()

        if ticker:
            # Filter to stories affecting this ticker
            relevant_stories = []
            for story in brief.get("top_stories", []):
                if ticker in story.get("affected_positions", []):
                    relevant_stories.append(story)

            return {
                "agent": self.agent_name,
                "ticker": ticker,
                "relevant_stories": relevant_stories,
                "timestamp": datetime.utcnow().isoformat(),
            }

        return brief

    def chat(self, message: str, include_context: bool = True) -> Optional[dict]:
        """
        Chat with the News agent.

        Args:
            message: User's question or request
            include_context: Whether to include recent news context

        Returns:
            Structured response dict
        """
        logger.info(f"[News] Processing: {message[:50]}...")

        # Load context
        portfolio = self._load_portfolio() if include_context else None
        recent_brief = self._load_previous_brief() if include_context else None
        recent_news = recent_brief.get("top_stories", []) if recent_brief else []

        # Build prompt
        user_prompt = build_chat_prompt(
            message=message,
            portfolio=portfolio,
            recent_news=recent_news,
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
            logger.error(f"[News] Claude API error: {e}")
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

            return result

        except json.JSONDecodeError as e:
            logger.error(f"[News] Failed to parse response: {e}")
            return {
                "agent": self.agent_name,
                "raw_response": raw_response,
                "parse_error": str(e),
                "generated_at": datetime.utcnow().isoformat(),
            }

    def brief(self) -> dict:
        """
        Get the current 24h news brief.
        """
        brief = self._load_previous_brief()

        if not brief or not brief.get("24h_summary"):
            # Run a scan first
            brief = self.scan()

        return brief


def run_news_scan() -> dict:
    """Convenience function for news scan."""
    agent = NewsAgent()
    return agent.scan()


def run_news_chat(message: str) -> dict:
    """Convenience function for chat."""
    agent = NewsAgent()
    return agent.chat(message)


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    parser = argparse.ArgumentParser(description="News & Geopolitical Intelligence Agent")
    parser.add_argument("--scan", action="store_true", help="Scan news feeds")
    parser.add_argument("--impact", action="store_true", help="Get portfolio impact assessment")
    parser.add_argument("--brief", action="store_true", help="Get 24h news brief")
    parser.add_argument("--chat", type=str, help="Chat message")
    parser.add_argument("--ticker", type=str, help="Filter impact to specific ticker")
    args = parser.parse_args()

    print("\n" + "="*60)
    print("NEWS & GEOPOLITICAL INTELLIGENCE AGENT")
    print("="*60 + "\n")

    agent = NewsAgent()

    if args.scan:
        result = agent.scan()
    elif args.impact:
        result = agent.impact(ticker=args.ticker)
    elif args.brief:
        result = agent.brief()
    elif args.chat:
        result = agent.chat(args.chat)
    else:
        # Default: scan
        result = agent.scan()

    if result:
        print("\n" + "="*60)
        print("RESPONSE")
        print("="*60)
        print(json.dumps(result, indent=2))
    else:
        print("Failed to get response")
