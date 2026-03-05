"""
News & Sentiment Scanner for ATLAS
Real-time news monitoring with AI-powered sentiment scoring.

The agents need to know what happened TODAY, not last quarter.
This client monitors multiple free news sources and uses Claude to
score sentiment and impact for each headline.

Data Sources:
- RSS Feeds: Reuters, Bloomberg (public), CNBC, MarketWatch, Yahoo Finance
- Finviz news scraper
- Google News RSS
- yfinance news API

Sentiment Scoring:
- Headlines passed to Claude with simple prompt for POSITIVE/NEGATIVE/NEUTRAL
- Impact score 0-100 based on materiality
"""
import time
import logging
import xml.etree.ElementTree as ET
import re
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote_plus
import requests
from bs4 import BeautifulSoup

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import ANTHROPIC_API_KEY
from config.universe import UNIVERSE

logger = logging.getLogger(__name__)


# RSS Feed URLs for major financial news
RSS_FEEDS = {
    "yahoo_finance": "https://finance.yahoo.com/news/rssindex",
    "cnbc_markets": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258",
    "cnbc_earnings": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839135",
    "marketwatch": "https://feeds.marketwatch.com/marketwatch/topstories/",
    "reuters_business": "https://news.google.com/rss/search?q=site:reuters.com+business&hl=en-US&gl=US&ceid=US:en",
    "wsj_markets": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
}

# Sector-specific RSS feeds
SECTOR_FEEDS = {
    "Technology": [
        "https://news.google.com/rss/search?q=tech+stocks+earnings&hl=en-US&gl=US&ceid=US:en",
        "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19854910",  # CNBC Tech
    ],
    "Healthcare": [
        "https://news.google.com/rss/search?q=pharma+biotech+FDA&hl=en-US&gl=US&ceid=US:en",
    ],
    "Financials": [
        "https://news.google.com/rss/search?q=banking+financial+stocks&hl=en-US&gl=US&ceid=US:en",
    ],
    "Energy": [
        "https://news.google.com/rss/search?q=oil+gas+energy+stocks&hl=en-US&gl=US&ceid=US:en",
    ],
}

# Macro news feeds
MACRO_FEEDS = {
    "fed": "https://news.google.com/rss/search?q=federal+reserve+interest+rates&hl=en-US&gl=US&ceid=US:en",
    "economy": "https://news.google.com/rss/search?q=US+economy+GDP+inflation&hl=en-US&gl=US&ceid=US:en",
    "jobs": "https://news.google.com/rss/search?q=jobs+report+unemployment&hl=en-US&gl=US&ceid=US:en",
    "geopolitical": "https://news.google.com/rss/search?q=trade+war+tariffs+sanctions&hl=en-US&gl=US&ceid=US:en",
}


class NewsSentimentClient:
    """
    Real-time news monitoring with AI sentiment scoring.
    """

    FINVIZ_NEWS_URL = "https://finviz.com/quote.ashx?t={ticker}"
    GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

    def __init__(self, anthropic_api_key: str = None):
        """
        Initialize news sentiment client.

        Args:
            anthropic_api_key: Anthropic API key for Claude sentiment scoring
        """
        self.anthropic_api_key = anthropic_api_key or ANTHROPIC_API_KEY
        self._anthropic = None

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        })

        self._cache = {}
        self._cache_expiry = {}
        self._cache_ttl = timedelta(minutes=5)  # Short TTL for news

    @property
    def anthropic(self):
        """Lazy initialization of Anthropic client."""
        if self._anthropic is None and ANTHROPIC_AVAILABLE and self.anthropic_api_key:
            self._anthropic = Anthropic(api_key=self.anthropic_api_key)
        return self._anthropic

    def _get_cached(self, key: str) -> Optional[any]:
        """Get value from cache if not expired."""
        if key in self._cache:
            if datetime.now() < self._cache_expiry.get(key, datetime.min):
                return self._cache[key]
        return None

    def _set_cached(self, key: str, value: any) -> None:
        """Set value in cache with expiry."""
        self._cache[key] = value
        self._cache_expiry[key] = datetime.now() + self._cache_ttl

    def get_latest_news(self, ticker: str, hours: int = 24) -> list:
        """
        Get headlines and summaries from last N hours for a ticker.

        Args:
            ticker: Stock ticker symbol
            hours: Look back this many hours

        Returns:
            List of news dicts with keys: headline, summary, source,
            published_date, url, sentiment, impact_score
        """
        cache_key = f"news_{ticker}_{hours}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        all_news = []
        cutoff_time = datetime.now() - timedelta(hours=hours)

        # 1. Try yfinance news
        try:
            yf_news = self._get_yfinance_news(ticker)
            all_news.extend(yf_news)
        except Exception as e:
            logger.debug(f"yfinance news failed for {ticker}: {e}")

        # 2. Scrape Finviz news
        try:
            finviz_news = self._scrape_finviz_news(ticker)
            all_news.extend(finviz_news)
        except Exception as e:
            logger.debug(f"Finviz news failed for {ticker}: {e}")

        # 3. Google News RSS for this ticker
        try:
            company_name = UNIVERSE.get(ticker, {}).get("name", ticker)
            google_news = self._fetch_google_news(f"{ticker} stock {company_name}")
            all_news.extend(google_news)
        except Exception as e:
            logger.debug(f"Google News failed for {ticker}: {e}")

        # Deduplicate by headline similarity
        seen_headlines = set()
        unique_news = []
        for news in all_news:
            headline_key = news.get("headline", "")[:50].lower()
            if headline_key not in seen_headlines:
                seen_headlines.add(headline_key)
                unique_news.append(news)

        # Filter by time
        filtered_news = []
        for news in unique_news:
            pub_date = news.get("published_date")
            if pub_date:
                try:
                    if isinstance(pub_date, str):
                        # Try to parse date
                        for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z"]:
                            try:
                                pub_datetime = datetime.strptime(pub_date[:19], fmt[:len(pub_date)])
                                break
                            except:
                                continue
                        else:
                            pub_datetime = datetime.now()
                    else:
                        pub_datetime = pub_date

                    if pub_datetime >= cutoff_time:
                        filtered_news.append(news)
                except:
                    filtered_news.append(news)  # Include if can't parse date
            else:
                filtered_news.append(news)

        # Sort by date descending
        filtered_news.sort(key=lambda x: x.get("published_date", ""), reverse=True)

        # Add ticker reference
        for news in filtered_news:
            news["ticker"] = ticker

        self._set_cached(cache_key, filtered_news)
        logger.info(f"{ticker}: Found {len(filtered_news)} news items in last {hours} hours")
        return filtered_news

    def _get_yfinance_news(self, ticker: str) -> list:
        """Get news from yfinance."""
        if not YFINANCE_AVAILABLE:
            return []

        try:
            stock = yf.Ticker(ticker)
            news = stock.news

            if not news:
                return []

            items = []
            for item in news[:20]:  # Limit to recent 20
                pub_time = item.get("providerPublishTime", 0)
                pub_date = datetime.fromtimestamp(pub_time).strftime("%Y-%m-%d %H:%M:%S") if pub_time else ""

                items.append({
                    "headline": item.get("title", ""),
                    "summary": item.get("summary", "")[:500] if item.get("summary") else "",
                    "source": item.get("publisher", "yfinance"),
                    "published_date": pub_date,
                    "url": item.get("link", ""),
                })
            return items
        except Exception as e:
            logger.debug(f"yfinance news error: {e}")
            return []

    def _scrape_finviz_news(self, ticker: str) -> list:
        """Scrape news headlines from Finviz."""
        try:
            url = self.FINVIZ_NEWS_URL.format(ticker=ticker)
            resp = self.session.get(url, timeout=10)
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")

            # Find news table
            news_table = soup.find("table", {"id": "news-table"})
            if not news_table:
                return []

            items = []
            current_date = ""

            for row in news_table.find_all("tr")[:20]:
                cells = row.find_all("td")
                if len(cells) < 2:
                    continue

                # First cell is date/time
                date_cell = cells[0].get_text(strip=True)
                if len(date_cell) > 7:  # Has date
                    current_date = date_cell.split()[0]
                    time_str = date_cell.split()[-1] if len(date_cell.split()) > 1 else ""
                else:
                    time_str = date_cell

                # Second cell is headline with link
                headline_cell = cells[1]
                link = headline_cell.find("a")
                if link:
                    headline = link.get_text(strip=True)
                    url = link.get("href", "")
                    source = headline_cell.find("span")
                    source_text = source.get_text(strip=True) if source else "Finviz"

                    # Combine date and time
                    pub_date = f"{current_date} {time_str}" if current_date else time_str

                    items.append({
                        "headline": headline,
                        "summary": "",
                        "source": source_text,
                        "published_date": pub_date,
                        "url": url,
                    })

            return items
        except Exception as e:
            logger.debug(f"Finviz scrape error: {e}")
            return []

    def _fetch_google_news(self, query: str, limit: int = 10) -> list:
        """Fetch news from Google News RSS."""
        try:
            url = self.GOOGLE_NEWS_RSS.format(query=quote_plus(query))
            resp = self.session.get(url, timeout=10)
            if resp.status_code != 200:
                return []

            root = ET.fromstring(resp.content)
            items = []

            for item in root.findall(".//item")[:limit]:
                title = item.find("title")
                link = item.find("link")
                pub_date = item.find("pubDate")
                source = item.find("source")

                items.append({
                    "headline": title.text if title is not None else "",
                    "summary": "",
                    "source": source.text if source is not None else "Google News",
                    "published_date": pub_date.text if pub_date is not None else "",
                    "url": link.text if link is not None else "",
                })

            return items
        except Exception as e:
            logger.debug(f"Google News RSS error: {e}")
            return []

    def _fetch_rss_feed(self, url: str, limit: int = 10) -> list:
        """Fetch and parse an RSS feed."""
        try:
            resp = self.session.get(url, timeout=10)
            if resp.status_code != 200:
                return []

            root = ET.fromstring(resp.content)
            items = []

            # Handle both RSS and Atom formats
            for item in (root.findall(".//item") + root.findall(".//{http://www.w3.org/2005/Atom}entry"))[:limit]:
                # RSS format
                title = item.find("title")
                if title is None:
                    title = item.find("{http://www.w3.org/2005/Atom}title")

                link = item.find("link")
                if link is None:
                    link = item.find("{http://www.w3.org/2005/Atom}link")
                    if link is not None:
                        link_url = link.get("href", "")
                    else:
                        link_url = ""
                else:
                    link_url = link.text if link.text else ""

                pub_date = item.find("pubDate")
                if pub_date is None:
                    pub_date = item.find("{http://www.w3.org/2005/Atom}published")

                description = item.find("description")
                if description is None:
                    description = item.find("{http://www.w3.org/2005/Atom}summary")

                items.append({
                    "headline": title.text if title is not None else "",
                    "summary": (description.text or "")[:500] if description is not None else "",
                    "source": url.split("/")[2],  # Domain as source
                    "published_date": pub_date.text if pub_date is not None else "",
                    "url": link_url,
                })

            return items
        except Exception as e:
            logger.debug(f"RSS fetch error for {url}: {e}")
            return []

    def get_market_moving_news(self) -> list:
        """
        Scan all universe tickers for significant news.
        Categories: M&A, earnings, analyst changes, regulatory, product launches.

        Returns:
            List of news items that are likely market-moving
        """
        market_moving = []

        # Keywords indicating market-moving news
        keywords = [
            "merger", "acquisition", "acquire", "buyout", "takeover",
            "earnings", "profit", "revenue", "guidance", "forecast",
            "upgrade", "downgrade", "price target", "analyst",
            "FDA", "approval", "trial", "phase 3",
            "layoff", "restructur", "CEO", "CFO", "resign",
            "lawsuit", "investigation", "SEC", "DOJ",
            "dividend", "buyback", "share repurchase",
        ]

        for ticker in list(UNIVERSE.keys())[:30]:  # Limit to avoid rate limits
            try:
                news = self.get_latest_news(ticker, hours=24)

                for item in news:
                    headline_lower = item.get("headline", "").lower()
                    if any(kw in headline_lower for kw in keywords):
                        item["market_moving"] = True
                        market_moving.append(item)
            except Exception as e:
                logger.debug(f"Error scanning news for {ticker}: {e}")
                continue

        logger.info(f"Found {len(market_moving)} market-moving news items")
        return market_moving

    def get_sector_news(self, sector: str) -> list:
        """
        Get sector-level news and trends.

        Args:
            sector: Sector name (Technology, Healthcare, Financials, etc.)

        Returns:
            List of sector-relevant news items
        """
        cache_key = f"sector_news_{sector}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        news = []

        # Get sector-specific RSS feeds
        sector_feeds = SECTOR_FEEDS.get(sector, [])
        for feed_url in sector_feeds:
            try:
                items = self._fetch_rss_feed(feed_url, limit=15)
                for item in items:
                    item["sector"] = sector
                news.extend(items)
            except Exception as e:
                logger.debug(f"Sector feed error: {e}")

        # Also get news for tickers in this sector
        sector_tickers = [t for t, info in UNIVERSE.items() if info.get("sector") == sector]
        for ticker in sector_tickers[:5]:  # Limit per sector
            try:
                ticker_news = self.get_latest_news(ticker, hours=24)
                news.extend(ticker_news[:3])  # Top 3 per ticker
            except:
                continue

        # Deduplicate
        seen = set()
        unique_news = []
        for item in news:
            key = item.get("headline", "")[:50].lower()
            if key not in seen:
                seen.add(key)
                unique_news.append(item)

        self._set_cached(cache_key, unique_news)
        logger.info(f"{sector}: Found {len(unique_news)} news items")
        return unique_news

    def get_macro_headlines(self) -> list:
        """
        Get Fed, ECB, BOJ decisions, economic data releases, geopolitical events.

        Returns:
            List of macro news items
        """
        cache_key = "macro_headlines"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        macro_news = []

        for topic, feed_url in MACRO_FEEDS.items():
            try:
                items = self._fetch_rss_feed(feed_url, limit=10)
                for item in items:
                    item["macro_topic"] = topic
                macro_news.extend(items)
            except Exception as e:
                logger.debug(f"Macro feed error for {topic}: {e}")

        # Also fetch from general market RSS
        for name, url in RSS_FEEDS.items():
            try:
                items = self._fetch_rss_feed(url, limit=5)
                macro_news.extend(items)
            except:
                continue

        # Deduplicate
        seen = set()
        unique_news = []
        for item in macro_news:
            key = item.get("headline", "")[:50].lower()
            if key not in seen:
                seen.add(key)
                unique_news.append(item)

        self._set_cached(cache_key, unique_news)
        logger.info(f"Found {len(unique_news)} macro headlines")
        return unique_news

    def score_sentiment(self, headlines: list, ticker: str = None) -> list:
        """
        Use Claude to score sentiment for a list of headlines.

        Args:
            headlines: List of news dicts with 'headline' key
            ticker: Optional ticker for context

        Returns:
            Same list with 'sentiment' and 'impact_score' added
        """
        if not self.anthropic:
            logger.warning("Anthropic client not available for sentiment scoring")
            return headlines

        # Batch headlines for efficiency
        for item in headlines:
            if "sentiment" not in item:
                try:
                    headline = item.get("headline", "")
                    ticker_context = ticker or item.get("ticker", "")

                    prompt = f"""Rate this financial news headline for {ticker_context}:
"{headline}"

Respond with ONLY a JSON object (no other text):
{{"sentiment": "POSITIVE" or "NEGATIVE" or "NEUTRAL", "impact_score": 0-100, "reason": "brief reason"}}

Impact score guide:
- 0-20: Minor news, no price impact expected
- 21-50: Moderate news, small price movement possible
- 51-80: Significant news, noticeable price impact likely
- 81-100: Major news (M&A, earnings miss/beat, FDA decision), large price movement expected"""

                    response = self.anthropic.messages.create(
                        model="claude-3-5-haiku-20241022",  # Fast and cheap for this task
                        max_tokens=200,
                        messages=[{"role": "user", "content": prompt}]
                    )

                    # Parse response
                    content = response.content[0].text.strip()
                    # Extract JSON from response
                    import json
                    try:
                        result = json.loads(content)
                        item["sentiment"] = result.get("sentiment", "NEUTRAL")
                        item["impact_score"] = result.get("impact_score", 50)
                        item["sentiment_reason"] = result.get("reason", "")
                    except json.JSONDecodeError:
                        # Try to extract from text
                        if "POSITIVE" in content.upper():
                            item["sentiment"] = "POSITIVE"
                        elif "NEGATIVE" in content.upper():
                            item["sentiment"] = "NEGATIVE"
                        else:
                            item["sentiment"] = "NEUTRAL"
                        item["impact_score"] = 50

                except Exception as e:
                    logger.debug(f"Sentiment scoring error: {e}")
                    item["sentiment"] = "NEUTRAL"
                    item["impact_score"] = 50

        return headlines

    def get_news_with_sentiment(self, ticker: str, hours: int = 24) -> list:
        """
        Get news for a ticker with AI sentiment scoring.

        Args:
            ticker: Stock ticker symbol
            hours: Look back this many hours

        Returns:
            List of news items with sentiment scores
        """
        news = self.get_latest_news(ticker, hours)
        return self.score_sentiment(news, ticker)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    print("\n" + "="*60)
    print("ATLAS News Sentiment Client")
    print("="*60 + "\n")

    client = NewsSentimentClient()

    # Test news for NVDA
    print("--- NVDA News (24 hours) ---")
    news = client.get_latest_news("NVDA", hours=24)
    for item in news[:5]:
        print(f"  [{item.get('source', 'Unknown')[:15]}] {item.get('headline', '')[:60]}...")

    # Test market-moving news
    print("\n--- Market-Moving News ---")
    moving = client.get_market_moving_news()
    for item in moving[:5]:
        print(f"  [{item.get('ticker', 'N/A')}] {item.get('headline', '')[:50]}...")

    # Test sector news
    print("\n--- Technology Sector News ---")
    tech_news = client.get_sector_news("Technology")
    for item in tech_news[:5]:
        print(f"  {item.get('headline', '')[:60]}...")

    # Test macro headlines
    print("\n--- Macro Headlines ---")
    macro = client.get_macro_headlines()
    for item in macro[:5]:
        topic = item.get("macro_topic", "general")
        print(f"  [{topic}] {item.get('headline', '')[:50]}...")

    # Test sentiment scoring (if API key available)
    if client.anthropic:
        print("\n--- News with Sentiment (NVDA) ---")
        scored_news = client.get_news_with_sentiment("NVDA", hours=24)
        for item in scored_news[:3]:
            print(f"  [{item.get('sentiment', 'N/A')}|{item.get('impact_score', 'N/A')}] {item.get('headline', '')[:40]}...")
