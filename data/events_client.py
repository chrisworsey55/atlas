"""
SEC Form 8-K Material Events Client for ATLAS
Pulls material event disclosures - earnings, M&A, leadership changes, debt issuances.
8-Ks are filed within 4 business days of material events.
"""
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from .edgar_client import EdgarClient
from config.universe import UNIVERSE

logger = logging.getLogger(__name__)

# 8-K Item codes and their meanings
ITEM_CODES = {
    '1.01': ('Material Agreement', 'contract'),
    '1.02': ('Termination of Agreement', 'contract'),
    '1.03': ('Bankruptcy', 'distress'),
    '1.04': ('Mine Safety', 'regulatory'),
    '1.05': ('Material Cybersecurity Incident', 'risk'),
    '2.01': ('Asset Acquisition/Disposition', 'ma'),
    '2.02': ('Results of Operations', 'earnings'),
    '2.03': ('Debt Obligation', 'financing'),
    '2.04': ('Triggering Events', 'financing'),
    '2.05': ('Exit/Disposal Activities', 'restructuring'),
    '2.06': ('Material Impairment', 'writedown'),
    '3.01': ('Delisting', 'corporate'),
    '3.02': ('Unregistered Sales of Equity', 'financing'),
    '3.03': ('Material Modification to Rights', 'corporate'),
    '4.01': ('Auditor Change', 'governance'),
    '4.02': ('Non-Reliance on Financials', 'restatement'),
    '5.01': ('Leadership Change', 'management'),
    '5.02': ('Executive Departure/Appointment', 'management'),
    '5.03': ('Bylaws Amendment', 'governance'),
    '5.04': ('Shareholder Nomination', 'governance'),
    '5.05': ('Delisting Amendment', 'corporate'),
    '5.06': ('Shell Company Status', 'corporate'),
    '5.07': ('Shareholder Vote', 'governance'),
    '5.08': ('Shareholder Director Nomination', 'governance'),
    '6.01': ('ABS Info', 'financing'),
    '6.02': ('ABS Change of Servicer', 'financing'),
    '6.03': ('ABS Distribution Report', 'financing'),
    '6.04': ('ABS Early Amortization', 'financing'),
    '6.05': ('ABS Material Pool Characteristic', 'financing'),
    '7.01': ('Regulation FD Disclosure', 'guidance'),
    '8.01': ('Other Events', 'other'),
    '9.01': ('Financial Statements and Exhibits', 'exhibits'),
}

# Event categories that are most relevant for trading
MATERIAL_CATEGORIES = ['earnings', 'ma', 'management', 'financing', 'restructuring',
                       'distress', 'restatement', 'guidance', 'writedown']


class EventsClient:
    """
    Client for SEC Form 8-K material event filings.
    8-Ks are filed within 4 business days of material events.
    """

    def __init__(self):
        self.edgar = EdgarClient()

    def get_recent_events(self, ticker: str, days: int = 30) -> list[dict]:
        """
        Pull 8-K filings for a ticker and parse event types.

        Returns list of:
            {ticker, event_type, category, filing_date, description, url, items}
        """
        filings = self.edgar.get_recent_filings(ticker, filing_types=["8-K", "8-K/A"], days_back=days)
        events = []

        for filing in filings:
            try:
                event_data = self._parse_8k(filing)
                if event_data:
                    events.append(event_data)
            except Exception as e:
                logger.warning(f"Error parsing 8-K for {ticker}: {e}")
                continue

        logger.info(f"{ticker}: Found {len(events)} 8-K events in last {days} days")
        return events

    def _parse_8k(self, filing: dict) -> Optional[dict]:
        """Parse an 8-K filing to extract event details."""
        ticker = filing.get('ticker', '')
        filing_date = filing.get('filing_date', '')
        description = filing.get('description', '')
        url = filing.get('filing_url', '')

        # Download the filing text to extract Item numbers
        text = self.edgar.download_filing_text(filing, max_chars=50000)
        if not text:
            return {
                'ticker': ticker,
                'filing_date': filing_date,
                'event_type': 'Unknown',
                'category': 'other',
                'description': description,
                'url': url,
                'items': [],
                'summary': description,
            }

        # Extract Item numbers from the filing
        items = self._extract_items(text)

        # Determine primary event type and category
        event_type, category = self._categorize_event(items)

        # Extract a brief summary from the filing
        summary = self._extract_summary(text, items)

        return {
            'ticker': ticker,
            'filing_date': filing_date,
            'event_type': event_type,
            'category': category,
            'description': description,
            'url': url,
            'items': items,
            'summary': summary,
        }

    def _extract_items(self, text: str) -> list[str]:
        """Extract Item numbers (e.g., '2.02', '5.02') from 8-K text."""
        # Pattern to match "Item X.XX" variations
        pattern = r'Item\s+(\d+\.\d{2})'
        matches = re.findall(pattern, text, re.IGNORECASE)

        # Deduplicate while preserving order
        seen = set()
        items = []
        for item in matches:
            if item not in seen:
                seen.add(item)
                items.append(item)

        return items

    def _categorize_event(self, items: list[str]) -> tuple[str, str]:
        """Determine the primary event type and category from Item codes."""
        if not items:
            return ('Other Events', 'other')

        # Priority order for categorization
        priority = ['earnings', 'ma', 'management', 'distress', 'restatement',
                   'financing', 'restructuring', 'guidance', 'writedown']

        categories_found = {}
        for item in items:
            if item in ITEM_CODES:
                event_name, cat = ITEM_CODES[item]
                if cat not in categories_found:
                    categories_found[cat] = event_name

        # Return highest priority category
        for cat in priority:
            if cat in categories_found:
                return (categories_found[cat], cat)

        # Default to first item found
        if items and items[0] in ITEM_CODES:
            return ITEM_CODES[items[0]]

        return ('Other Events', 'other')

    def _extract_summary(self, text: str, items: list[str], max_length: int = 300) -> str:
        """Extract a brief summary from the 8-K filing text."""
        # Look for common summary sections
        summary_patterns = [
            r'(?:press release|announces|announced|reports|reported)[\s\S]{0,500}',
            r'(?:financial results|quarterly results|earnings)[\s\S]{0,500}',
            r'(?:the company|the registrant)[\s\S]{0,500}',
        ]

        for pattern in summary_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                summary = match.group(0).strip()
                # Clean up and truncate
                summary = ' '.join(summary.split())
                if len(summary) > max_length:
                    summary = summary[:max_length] + '...'
                return summary

        # Fallback: return first paragraph after Item declaration
        paragraphs = text.split('\n\n')
        for para in paragraphs:
            if len(para) > 50 and 'Item' not in para[:20]:
                para = ' '.join(para.split())
                if len(para) > max_length:
                    para = para[:max_length] + '...'
                return para

        return f"8-K filed with items: {', '.join(items)}" if items else "8-K filing"

    def get_material_events(self, days: int = 7) -> list[dict]:
        """
        Scan all universe tickers for material 8-K events.
        Returns events in material categories sorted by date.
        """
        all_events = []

        for ticker in UNIVERSE.keys():
            try:
                events = self.get_recent_events(ticker, days=days)
                material = [e for e in events if e.get('category') in MATERIAL_CATEGORIES]
                all_events.extend(material)
            except Exception as e:
                logger.warning(f"Error scanning events for {ticker}: {e}")
                continue

        # Sort by filing date descending
        all_events.sort(key=lambda x: x.get('filing_date', ''), reverse=True)

        logger.info(f"Material events scan: {len(all_events)} events in last {days} days")
        return all_events

    def get_earnings_events(self, days: int = 14) -> list[dict]:
        """Get recent earnings announcements (Item 2.02)."""
        all_events = []

        for ticker in UNIVERSE.keys():
            try:
                events = self.get_recent_events(ticker, days=days)
                earnings = [e for e in events if e.get('category') == 'earnings']
                all_events.extend(earnings)
            except Exception as e:
                logger.warning(f"Error scanning earnings for {ticker}: {e}")
                continue

        all_events.sort(key=lambda x: x.get('filing_date', ''), reverse=True)
        return all_events

    def get_management_changes(self, days: int = 30) -> list[dict]:
        """Get recent management/leadership changes (Items 5.01, 5.02)."""
        all_events = []

        for ticker in UNIVERSE.keys():
            try:
                events = self.get_recent_events(ticker, days=days)
                management = [e for e in events if e.get('category') == 'management']
                all_events.extend(management)
            except Exception as e:
                logger.warning(f"Error scanning management changes for {ticker}: {e}")
                continue

        all_events.sort(key=lambda x: x.get('filing_date', ''), reverse=True)
        return all_events

    def get_ma_events(self, days: int = 30) -> list[dict]:
        """Get recent M&A / asset acquisition events (Item 2.01)."""
        all_events = []

        for ticker in UNIVERSE.keys():
            try:
                events = self.get_recent_events(ticker, days=days)
                ma = [e for e in events if e.get('category') == 'ma']
                all_events.extend(ma)
            except Exception as e:
                logger.warning(f"Error scanning M&A events for {ticker}: {e}")
                continue

        all_events.sort(key=lambda x: x.get('filing_date', ''), reverse=True)
        return all_events


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')

    client = EventsClient()

    print("\n=== NVDA 8-K Events (last 60 days) ===")
    events = client.get_recent_events("NVDA", days=60)
    for e in events[:10]:
        print(f"  {e['filing_date']} | {e['event_type']:30} | {e['category']:12} | Items: {e['items']}")
        if e.get('summary'):
            print(f"    Summary: {e['summary'][:100]}...")

    print("\n=== Recent Earnings Announcements (last 14 days) ===")
    earnings = client.get_earnings_events(days=14)
    for e in earnings[:10]:
        print(f"  {e['ticker']:5} | {e['filing_date']} | {e['summary'][:60]}...")

    print("\n=== Recent Management Changes (last 30 days) ===")
    management = client.get_management_changes(days=30)
    for e in management[:10]:
        print(f"  {e['ticker']:5} | {e['filing_date']} | {e['summary'][:60]}...")

    print("\n=== All Material Events (last 7 days) ===")
    material = client.get_material_events(days=7)
    for e in material[:15]:
        print(f"  {e['ticker']:5} | {e['filing_date']} | {e['event_type']:25} | {e['category']}")
