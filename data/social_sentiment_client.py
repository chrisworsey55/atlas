"""
Social Sentiment Client for ATLAS
Tracks retail sentiment across Reddit, Twitter/X, and StockTwits.

Monitors:
- WallStreetBets, r/stocks, r/investing on Reddit
- Stock-related Twitter/X activity
- StockTwits sentiment

Key Signals:
- Trending tickers (sudden mention spikes)
- Bullish/bearish sentiment ratios
- Crowding risk (meme stock potential)
- Retail vs institutional divergence

Data Sources:
- Reddit API (free with app credentials)
- StockTwits API (free)
- Twitter/X API (if accessible)
"""
import logging
import re
from datetime import datetime, timedelta
from typing import Optional
import requests

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.universe import UNIVERSE

logger = logging.getLogger(__name__)


# Common stock tickers to filter (avoid false positives)
COMMON_WORDS = {
    "A", "I", "IT", "ALL", "ARE", "BE", "BY", "DD", "FOR", "GO", "HE",
    "IF", "IN", "IS", "ME", "MY", "NO", "OF", "ON", "OR", "SO", "TO",
    "UP", "US", "WE", "CEO", "CFO", "IPO", "ATH", "EOD", "OTC", "PM",
    "AM", "ET", "PT", "UK", "USA", "AI", "RE", "NEW", "NOW", "OUT",
    "CAN", "HAS", "NOT", "ONE", "ANY", "RUN", "SET", "TOP", "THE",
}


class SocialSentimentClient:
    """
    Client for tracking social media sentiment around stocks.
    """

    # StockTwits API (free, no key needed for basic access)
    STOCKTWITS_API = "https://api.stocktwits.com/api/2"

    # Reddit API endpoints
    REDDIT_API = "https://oauth.reddit.com"
    REDDIT_PUBLIC = "https://www.reddit.com"

    # Subreddits to monitor
    SUBREDDITS = [
        "wallstreetbets",
        "stocks",
        "investing",
        "options",
        "stockmarket",
    ]

    def __init__(self, reddit_client_id: str = None, reddit_client_secret: str = None):
        """
        Initialize social sentiment client.

        Args:
            reddit_client_id: Reddit app client ID
            reddit_client_secret: Reddit app client secret
        """
        self.reddit_client_id = reddit_client_id
        self.reddit_client_secret = reddit_client_secret
        self._reddit_token = None
        self._reddit_token_expiry = None

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "ATLAS-SentimentClient/1.0"
        })

        self._cache = {}
        self._cache_expiry = {}
        self._cache_ttl = timedelta(minutes=15)

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

    def _extract_tickers(self, text: str) -> list:
        """Extract stock tickers from text."""
        # Look for $TICKER pattern or all-caps 1-5 letter words
        patterns = [
            r'\$([A-Z]{1,5})\b',  # $AAPL format
            r'\b([A-Z]{2,5})\b',   # AAPL format
        ]

        tickers = []
        for pattern in patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                if match.upper() not in COMMON_WORDS:
                    # Check if it's in our universe or looks like a valid ticker
                    if match.upper() in UNIVERSE or len(match) >= 2:
                        tickers.append(match.upper())

        return list(set(tickers))

    def _get_reddit_token(self) -> Optional[str]:
        """Get Reddit OAuth token."""
        if self._reddit_token and self._reddit_token_expiry and datetime.now() < self._reddit_token_expiry:
            return self._reddit_token

        if not self.reddit_client_id or not self.reddit_client_secret:
            return None

        try:
            auth = (self.reddit_client_id, self.reddit_client_secret)
            data = {"grant_type": "client_credentials"}
            headers = {"User-Agent": "ATLAS-SentimentClient/1.0"}

            resp = requests.post(
                "https://www.reddit.com/api/v1/access_token",
                auth=auth,
                data=data,
                headers=headers,
                timeout=10
            )

            if resp.status_code == 200:
                token_data = resp.json()
                self._reddit_token = token_data.get("access_token")
                self._reddit_token_expiry = datetime.now() + timedelta(seconds=token_data.get("expires_in", 3600) - 60)
                return self._reddit_token
        except Exception as e:
            logger.error(f"Reddit auth error: {e}")

        return None

    def get_trending_tickers(self, limit: int = 20) -> list:
        """
        Get most mentioned tickers across social platforms in last 24h.

        Args:
            limit: Maximum number of tickers to return

        Returns:
            List of dicts with ticker, mention_count, sentiment, sources
        """
        cache_key = f"trending_{limit}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        ticker_mentions = {}

        # Fetch from Reddit
        try:
            reddit_data = self._fetch_reddit_trending()
            for ticker, count in reddit_data.items():
                if ticker not in ticker_mentions:
                    ticker_mentions[ticker] = {"count": 0, "sources": [], "sentiment_sum": 0, "sentiment_count": 0}
                ticker_mentions[ticker]["count"] += count
                ticker_mentions[ticker]["sources"].append("reddit")
        except Exception as e:
            logger.debug(f"Reddit fetch error: {e}")

        # Fetch from StockTwits
        try:
            stocktwits_data = self._fetch_stocktwits_trending()
            for item in stocktwits_data:
                ticker = item.get("ticker", "")
                if ticker not in ticker_mentions:
                    ticker_mentions[ticker] = {"count": 0, "sources": [], "sentiment_sum": 0, "sentiment_count": 0}
                ticker_mentions[ticker]["count"] += item.get("count", 1)
                ticker_mentions[ticker]["sources"].append("stocktwits")
                if item.get("sentiment"):
                    ticker_mentions[ticker]["sentiment_sum"] += item["sentiment"]
                    ticker_mentions[ticker]["sentiment_count"] += 1
        except Exception as e:
            logger.debug(f"StockTwits fetch error: {e}")

        # Build result list
        trending = []
        for ticker, data in ticker_mentions.items():
            avg_sentiment = data["sentiment_sum"] / data["sentiment_count"] if data["sentiment_count"] > 0 else None

            trending.append({
                "ticker": ticker,
                "mention_count": data["count"],
                "sources": list(set(data["sources"])),
                "sentiment_score": avg_sentiment,
                "in_universe": ticker in UNIVERSE,
                "company_name": UNIVERSE.get(ticker, {}).get("name", ""),
            })

        # Sort by mention count
        trending.sort(key=lambda x: x["mention_count"], reverse=True)
        trending = trending[:limit]

        self._set_cached(cache_key, trending)
        logger.info(f"Found {len(trending)} trending tickers")
        return trending

    def _fetch_reddit_trending(self) -> dict:
        """Fetch trending tickers from Reddit."""
        ticker_counts = {}

        for subreddit in self.SUBREDDITS:
            try:
                # Use public JSON API (no auth needed but rate limited)
                url = f"{self.REDDIT_PUBLIC}/r/{subreddit}/hot.json"
                params = {"limit": 50}

                resp = self.session.get(url, params=params, timeout=10)
                if resp.status_code != 200:
                    continue

                data = resp.json()
                posts = data.get("data", {}).get("children", [])

                for post in posts:
                    post_data = post.get("data", {})
                    title = post_data.get("title", "")
                    selftext = post_data.get("selftext", "")

                    # Extract tickers from title and body
                    text = f"{title} {selftext}"
                    tickers = self._extract_tickers(text)

                    for ticker in tickers:
                        ticker_counts[ticker] = ticker_counts.get(ticker, 0) + 1

            except Exception as e:
                logger.debug(f"Error fetching r/{subreddit}: {e}")
                continue

        return ticker_counts

    def _fetch_stocktwits_trending(self) -> list:
        """Fetch trending from StockTwits."""
        trending = []

        try:
            url = f"{self.STOCKTWITS_API}/trending/symbols.json"
            resp = self.session.get(url, timeout=10)

            if resp.status_code == 200:
                data = resp.json()
                symbols = data.get("symbols", [])

                for symbol in symbols:
                    ticker = symbol.get("symbol", "")
                    if ticker:
                        trending.append({
                            "ticker": ticker,
                            "count": symbol.get("watchlist_count", 0),
                            "sentiment": None,  # Would need to fetch individual streams
                        })

        except Exception as e:
            logger.debug(f"StockTwits trending error: {e}")

        return trending

    def get_sentiment(self, ticker: str) -> dict:
        """
        Get sentiment analysis for a specific ticker.

        Args:
            ticker: Stock ticker symbol

        Returns:
            Dict with bullish/bearish ratio, volume, trend
        """
        cache_key = f"sentiment_{ticker}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        result = {
            "ticker": ticker,
            "company_name": UNIVERSE.get(ticker, {}).get("name", ticker),
            "timestamp": datetime.now().isoformat(),
        }

        # StockTwits sentiment
        try:
            st_data = self._fetch_stocktwits_sentiment(ticker)
            result.update(st_data)
        except Exception as e:
            logger.debug(f"StockTwits sentiment error for {ticker}: {e}")

        # Reddit mention analysis
        try:
            reddit_data = self._fetch_reddit_sentiment(ticker)
            result["reddit_mentions"] = reddit_data.get("mentions", 0)
            result["reddit_sentiment"] = reddit_data.get("sentiment", "NEUTRAL")
        except Exception as e:
            logger.debug(f"Reddit sentiment error for {ticker}: {e}")

        # Calculate overall sentiment
        bullish = result.get("stocktwits_bullish", 0)
        bearish = result.get("stocktwits_bearish", 0)
        total = bullish + bearish

        if total > 0:
            result["bullish_pct"] = bullish / total * 100
            result["bearish_pct"] = bearish / total * 100
        else:
            result["bullish_pct"] = 50
            result["bearish_pct"] = 50

        # Determine overall sentiment
        if result["bullish_pct"] > 70:
            result["overall_sentiment"] = "VERY_BULLISH"
        elif result["bullish_pct"] > 55:
            result["overall_sentiment"] = "BULLISH"
        elif result["bearish_pct"] > 70:
            result["overall_sentiment"] = "VERY_BEARISH"
        elif result["bearish_pct"] > 55:
            result["overall_sentiment"] = "BEARISH"
        else:
            result["overall_sentiment"] = "NEUTRAL"

        self._set_cached(cache_key, result)
        return result

    def _fetch_stocktwits_sentiment(self, ticker: str) -> dict:
        """Fetch sentiment from StockTwits."""
        try:
            url = f"{self.STOCKTWITS_API}/streams/symbol/{ticker}.json"
            resp = self.session.get(url, timeout=10)

            if resp.status_code != 200:
                return {}

            data = resp.json()
            symbol = data.get("symbol", {})

            messages = data.get("messages", [])
            bullish = sum(1 for m in messages if m.get("entities", {}).get("sentiment", {}).get("basic") == "Bullish")
            bearish = sum(1 for m in messages if m.get("entities", {}).get("sentiment", {}).get("basic") == "Bearish")

            return {
                "stocktwits_bullish": bullish,
                "stocktwits_bearish": bearish,
                "stocktwits_message_volume": len(messages),
                "stocktwits_watchers": symbol.get("watchlist_count", 0),
            }

        except Exception as e:
            logger.debug(f"StockTwits fetch error: {e}")
            return {}

    def _fetch_reddit_sentiment(self, ticker: str) -> dict:
        """Analyze Reddit sentiment for a ticker."""
        mentions = 0
        bullish_keywords = 0
        bearish_keywords = 0

        bullish_words = ["buy", "calls", "moon", "rocket", "bullish", "long", "yolo", "diamond hands", "tendies"]
        bearish_words = ["sell", "puts", "short", "bearish", "crash", "dump", "paper hands"]

        for subreddit in self.SUBREDDITS[:2]:  # Limit to reduce requests
            try:
                url = f"{self.REDDIT_PUBLIC}/r/{subreddit}/search.json"
                params = {
                    "q": ticker,
                    "restrict_sr": "true",
                    "sort": "new",
                    "limit": 25,
                    "t": "day",
                }

                resp = self.session.get(url, params=params, timeout=10)
                if resp.status_code != 200:
                    continue

                data = resp.json()
                posts = data.get("data", {}).get("children", [])

                for post in posts:
                    post_data = post.get("data", {})
                    text = f"{post_data.get('title', '')} {post_data.get('selftext', '')}".lower()

                    if ticker.lower() in text or f"${ticker.lower()}" in text:
                        mentions += 1

                        for word in bullish_words:
                            if word in text:
                                bullish_keywords += 1
                        for word in bearish_words:
                            if word in text:
                                bearish_keywords += 1

            except Exception as e:
                logger.debug(f"Reddit search error: {e}")
                continue

        # Determine sentiment
        if bullish_keywords > bearish_keywords * 1.5:
            sentiment = "BULLISH"
        elif bearish_keywords > bullish_keywords * 1.5:
            sentiment = "BEARISH"
        else:
            sentiment = "NEUTRAL"

        return {
            "mentions": mentions,
            "sentiment": sentiment,
            "bullish_keywords": bullish_keywords,
            "bearish_keywords": bearish_keywords,
        }

    def get_wsb_activity(self, ticker: str) -> dict:
        """
        Get WallStreetBets specific activity for a ticker.
        YOLO posts, unusual mention spikes, crowding indicator.

        Args:
            ticker: Stock ticker symbol

        Returns:
            Dict with WSB-specific metrics
        """
        cache_key = f"wsb_{ticker}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        result = {
            "ticker": ticker,
            "timestamp": datetime.now().isoformat(),
        }

        try:
            url = f"{self.REDDIT_PUBLIC}/r/wallstreetbets/search.json"
            params = {
                "q": f"${ticker} OR {ticker}",
                "restrict_sr": "true",
                "sort": "new",
                "limit": 50,
                "t": "week",
            }

            resp = self.session.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                posts = data.get("data", {}).get("children", [])

                # Analyze posts
                total_posts = 0
                yolo_posts = 0
                dd_posts = 0
                total_upvotes = 0
                total_comments = 0

                for post in posts:
                    post_data = post.get("data", {})
                    flair = post_data.get("link_flair_text", "").lower()
                    title = post_data.get("title", "").lower()

                    total_posts += 1
                    total_upvotes += post_data.get("ups", 0)
                    total_comments += post_data.get("num_comments", 0)

                    if "yolo" in flair or "yolo" in title:
                        yolo_posts += 1
                    if "dd" in flair or "due diligence" in title:
                        dd_posts += 1

                result["wsb_posts_week"] = total_posts
                result["wsb_yolo_posts"] = yolo_posts
                result["wsb_dd_posts"] = dd_posts
                result["wsb_total_upvotes"] = total_upvotes
                result["wsb_total_comments"] = total_comments
                result["wsb_avg_engagement"] = (total_upvotes + total_comments) / total_posts if total_posts > 0 else 0

                # Crowding risk assessment
                if total_posts > 10 and yolo_posts > 2:
                    result["meme_risk"] = "HIGH"
                elif total_posts > 5 or yolo_posts > 0:
                    result["meme_risk"] = "MODERATE"
                else:
                    result["meme_risk"] = "LOW"

        except Exception as e:
            logger.debug(f"WSB activity error: {e}")
            result["wsb_posts_week"] = 0
            result["meme_risk"] = "LOW"

        self._set_cached(cache_key, result)
        return result

    def get_sentiment_summary(self) -> dict:
        """
        Get overall social sentiment summary across all platforms.

        Returns:
            Dict with platform-level summaries
        """
        trending = self.get_trending_tickers(limit=20)

        return {
            "timestamp": datetime.now().isoformat(),
            "top_trending": trending[:10],
            "universe_trending": [t for t in trending if t["in_universe"]][:10],
            "total_trending_count": len(trending),
        }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    print("\n" + "="*60)
    print("ATLAS Social Sentiment Client")
    print("="*60 + "\n")

    client = SocialSentimentClient()

    # Test trending tickers
    print("--- Trending Tickers ---")
    trending = client.get_trending_tickers(limit=10)
    for t in trending[:10]:
        universe = "[UNIVERSE]" if t.get("in_universe") else ""
        sources = ", ".join(t.get("sources", []))
        print(f"  {t['ticker']} | Mentions: {t['mention_count']} | Sources: {sources} {universe}")

    # Test sentiment for NVDA
    print("\n--- NVDA Sentiment ---")
    sentiment = client.get_sentiment("NVDA")
    print(f"  Overall: {sentiment.get('overall_sentiment', 'N/A')}")
    print(f"  Bullish %: {sentiment.get('bullish_pct', 'N/A'):.1f}%")
    print(f"  Bearish %: {sentiment.get('bearish_pct', 'N/A'):.1f}%")
    print(f"  StockTwits Watchers: {sentiment.get('stocktwits_watchers', 'N/A')}")
    print(f"  Reddit Mentions: {sentiment.get('reddit_mentions', 'N/A')}")

    # Test WSB activity
    print("\n--- NVDA WallStreetBets Activity ---")
    wsb = client.get_wsb_activity("NVDA")
    print(f"  Posts (week): {wsb.get('wsb_posts_week', 'N/A')}")
    print(f"  YOLO Posts: {wsb.get('wsb_yolo_posts', 'N/A')}")
    print(f"  DD Posts: {wsb.get('wsb_dd_posts', 'N/A')}")
    print(f"  Meme Risk: {wsb.get('meme_risk', 'N/A')}")

    # Test summary
    print("\n--- Sentiment Summary ---")
    summary = client.get_sentiment_summary()
    print(f"  Total Trending: {summary.get('total_trending_count', 0)}")
    print(f"  Universe Trending: {len(summary.get('universe_trending', []))}")
