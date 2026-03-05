"""
Earnings Call Transcript Client for ATLAS
Fetches and parses earnings call transcripts from free sources.

Data Sources:
1. Financial Modeling Prep (FMP) - Free tier: 250 calls/day
2. Seeking Alpha (scraping fallback)
3. Motley Fool (scraping fallback)

Transcripts are the most valuable qualitative data for understanding
management sentiment and guidance direction.
"""
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from pathlib import Path
import requests
from bs4 import BeautifulSoup

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import FMP_API_KEY
from config.universe import UNIVERSE

logger = logging.getLogger(__name__)


class TranscriptClient:
    """
    Client for fetching earnings call transcripts.
    Uses FMP API as primary source with scraping fallbacks.
    """

    FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"
    SEEKING_ALPHA_URL = "https://seekingalpha.com/symbol/{ticker}/earnings/transcripts"
    MOTLEY_FOOL_URL = "https://www.fool.com/earnings-call-transcripts/"

    def __init__(self, fmp_api_key: str = None):
        self.fmp_api_key = fmp_api_key or FMP_API_KEY
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        self._cache = {}
        self._cache_expiry = {}
        self._cache_ttl = timedelta(hours=6)
        self._last_request_time = 0

    def _rate_limit(self, min_interval: float = 0.5):
        """Enforce rate limiting."""
        elapsed = time.time() - self._last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_time = time.time()

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

    def get_transcript(
        self,
        ticker: str,
        quarter: int = None,
        year: int = None,
    ) -> Optional[Dict]:
        """
        Get earnings call transcript for a ticker.

        Args:
            ticker: Stock ticker symbol
            quarter: Fiscal quarter (1-4). If None, gets latest.
            year: Fiscal year. If None, gets current/latest year.

        Returns:
            Dict with keys:
            - ticker, quarter, year, date
            - full_text: Complete transcript text
            - participants: List of speakers (executives, analysts)
            - prepared_remarks: Management's prepared comments
            - qa_session: Analyst Q&A section
        """
        cache_key = f"transcript_{ticker}_{quarter}_{year}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        # Try FMP API first
        if self.fmp_api_key:
            transcript = self._get_fmp_transcript(ticker, quarter, year)
            if transcript:
                self._set_cached(cache_key, transcript)
                return transcript

        # Fallback to scraping
        transcript = self._scrape_transcript(ticker)
        if transcript:
            self._set_cached(cache_key, transcript)
            return transcript

        logger.warning(f"No transcript found for {ticker}")
        return None

    def _get_fmp_transcript(
        self,
        ticker: str,
        quarter: int = None,
        year: int = None,
    ) -> Optional[Dict]:
        """Get transcript from Financial Modeling Prep API."""
        if not self.fmp_api_key:
            return None

        try:
            # Get latest if quarter/year not specified
            if quarter is None or year is None:
                # Get list of available transcripts first
                list_url = f"{self.FMP_BASE_URL}/earning_call_transcript/{ticker}"
                params = {"apikey": self.fmp_api_key}

                self._rate_limit()
                resp = self.session.get(list_url, params=params, timeout=15)
                if resp.status_code != 200:
                    logger.error(f"FMP transcript list failed: {resp.status_code}")
                    return None

                transcripts = resp.json()
                if not transcripts:
                    return None

                # Get the most recent one
                latest = transcripts[0] if transcripts else None
                if latest:
                    quarter = latest.get("quarter", 1)
                    year = latest.get("year", datetime.now().year)

            # Now fetch the specific transcript
            url = f"{self.FMP_BASE_URL}/earning_call_transcript/{ticker}"
            params = {
                "quarter": quarter,
                "year": year,
                "apikey": self.fmp_api_key
            }

            self._rate_limit()
            resp = self.session.get(url, params=params, timeout=30)
            if resp.status_code != 200:
                return None

            data = resp.json()
            if not data:
                return None

            # Parse the transcript content
            transcript_data = data[0] if isinstance(data, list) else data
            full_text = transcript_data.get("content", "")

            if not full_text:
                return None

            # Parse participants and sections
            participants = self._extract_participants(full_text)
            prepared_remarks, qa_session = self._split_transcript_sections(full_text)

            return {
                "ticker": ticker,
                "quarter": quarter,
                "year": year,
                "date": transcript_data.get("date", ""),
                "full_text": full_text,
                "participants": participants,
                "prepared_remarks": prepared_remarks,
                "qa_session": qa_session,
                "source": "FMP",
            }

        except Exception as e:
            logger.error(f"FMP transcript error for {ticker}: {e}")
            return None

    def _scrape_transcript(self, ticker: str) -> Optional[Dict]:
        """
        Scrape transcript from free sources as fallback.
        Tries Seeking Alpha and Motley Fool.
        """
        # Try Motley Fool first (more reliable scraping)
        transcript = self._scrape_motley_fool(ticker)
        if transcript:
            return transcript

        logger.debug(f"No scraped transcript found for {ticker}")
        return None

    def _scrape_motley_fool(self, ticker: str) -> Optional[Dict]:
        """Scrape transcript from Motley Fool."""
        try:
            # Search for the ticker's transcripts
            search_url = f"https://www.fool.com/search/solr.aspx?q={ticker}+earnings+call+transcript"

            self._rate_limit(1.0)
            resp = self.session.get(search_url, timeout=15)
            if resp.status_code != 200:
                return None

            soup = BeautifulSoup(resp.text, "html.parser")

            # Find transcript links
            transcript_links = []
            for link in soup.find_all("a", href=True):
                href = link.get("href", "")
                if "earnings-call-transcript" in href and ticker.lower() in href.lower():
                    transcript_links.append(href)

            if not transcript_links:
                return None

            # Get the most recent transcript
            transcript_url = transcript_links[0]
            if not transcript_url.startswith("http"):
                transcript_url = f"https://www.fool.com{transcript_url}"

            self._rate_limit(1.0)
            resp = self.session.get(transcript_url, timeout=30)
            if resp.status_code != 200:
                return None

            soup = BeautifulSoup(resp.text, "html.parser")

            # Extract the article content
            article = soup.find("article") or soup.find("div", class_="article-body")
            if not article:
                return None

            full_text = article.get_text(separator="\n", strip=True)

            # Extract date from title or URL
            title = soup.find("h1")
            title_text = title.get_text() if title else ""

            # Try to extract quarter and year from title
            quarter_match = re.search(r"Q(\d)", title_text)
            year_match = re.search(r"20(\d{2})", title_text)
            quarter = int(quarter_match.group(1)) if quarter_match else None
            year = int(f"20{year_match.group(1)}") if year_match else datetime.now().year

            # Parse participants and sections
            participants = self._extract_participants(full_text)
            prepared_remarks, qa_session = self._split_transcript_sections(full_text)

            return {
                "ticker": ticker.upper(),
                "quarter": quarter,
                "year": year,
                "date": "",
                "full_text": full_text[:100000],  # Limit size
                "participants": participants,
                "prepared_remarks": prepared_remarks,
                "qa_session": qa_session,
                "source": "Motley Fool",
            }

        except Exception as e:
            logger.error(f"Motley Fool scrape error for {ticker}: {e}")
            return None

    def _extract_participants(self, text: str) -> Dict[str, List[str]]:
        """Extract participants from transcript text."""
        participants = {
            "executives": [],
            "analysts": [],
        }

        # Look for "Company Participants" or similar section
        exec_pattern = r"(?:Company Participants|Corporate Participants|Executives)[:\s]*([^Q]+?)(?:Analysts|Conference Call Participants|Questions)"
        exec_match = re.search(exec_pattern, text, re.IGNORECASE | re.DOTALL)
        if exec_match:
            exec_text = exec_match.group(1)
            # Extract names (typically "Name - Title" format)
            for line in exec_text.split("\n"):
                line = line.strip()
                if line and len(line) > 5 and " - " in line:
                    participants["executives"].append(line)

        # Look for "Analysts" section
        analyst_pattern = r"(?:Analysts|Conference Call Participants|Questions From)[:\s]*([^O]+?)(?:Operator|Presentation|Prepared Remarks)"
        analyst_match = re.search(analyst_pattern, text, re.IGNORECASE | re.DOTALL)
        if analyst_match:
            analyst_text = analyst_match.group(1)
            for line in analyst_text.split("\n"):
                line = line.strip()
                if line and len(line) > 5 and " - " in line:
                    participants["analysts"].append(line)

        return participants

    def _split_transcript_sections(self, text: str) -> tuple:
        """Split transcript into prepared remarks and Q&A session."""
        # Common patterns for Q&A start
        qa_patterns = [
            r"Question-and-Answer Session",
            r"Questions and Answers",
            r"Q&A Session",
            r"Operator\s*\[Operator Instructions\]",
            r"And our first question",
            r"We will now begin the question",
        ]

        qa_start = None
        for pattern in qa_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                qa_start = match.start()
                break

        if qa_start:
            prepared_remarks = text[:qa_start].strip()
            qa_session = text[qa_start:].strip()
        else:
            # If no clear split, assume it's all prepared remarks
            prepared_remarks = text
            qa_session = ""

        return prepared_remarks, qa_session

    def get_latest_transcripts(self, tickers: List[str] = None) -> List[Dict]:
        """
        Get latest transcripts for multiple tickers.

        Args:
            tickers: List of tickers. If None, uses UNIVERSE.

        Returns:
            List of transcript dicts
        """
        if tickers is None:
            tickers = list(UNIVERSE.keys())

        transcripts = []
        for ticker in tickers:
            try:
                transcript = self.get_transcript(ticker)
                if transcript:
                    transcripts.append(transcript)
            except Exception as e:
                logger.error(f"Error getting transcript for {ticker}: {e}")
                continue

        logger.info(f"Retrieved {len(transcripts)} transcripts")
        return transcripts

    def get_transcript_by_date(self, ticker: str, date: str) -> Optional[Dict]:
        """
        Get transcript closest to a specific date.

        Args:
            ticker: Stock ticker symbol
            date: Date string (YYYY-MM-DD)

        Returns:
            Transcript dict or None
        """
        # This is a simplified implementation
        # In production, you'd query FMP for transcripts and find the closest match
        return self.get_transcript(ticker)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    print("\n" + "="*60)
    print("ATLAS Transcript Client")
    print("="*60 + "\n")

    client = TranscriptClient()

    # Test with AVGO
    print("--- Fetching AVGO Earnings Transcript ---")
    transcript = client.get_transcript("AVGO")

    if transcript:
        print(f"Ticker: {transcript['ticker']}")
        print(f"Quarter: Q{transcript['quarter']} {transcript['year']}")
        print(f"Source: {transcript['source']}")
        print(f"Full text length: {len(transcript['full_text'])} chars")
        print(f"Executives: {len(transcript['participants']['executives'])}")
        print(f"Analysts: {len(transcript['participants']['analysts'])}")
        print(f"\nFirst 500 chars of prepared remarks:")
        print(transcript['prepared_remarks'][:500] + "...")
    else:
        print("No transcript found. FMP API key may be required.")
