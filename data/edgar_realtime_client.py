"""
SEC EDGAR Real-Time Feed Client for ATLAS
Monitors EDGAR's real-time full-text search and RSS feeds for new filings.

This is the single most valuable free data source in public markets:
- 10-K / 10-Q: Annual and quarterly reports (fundamental analysis)
- 8-K: Material events (earnings, M&A, leadership changes, debt issuances)
- Form 4: Insider transactions (buy/sell within 2 business days)
- 13D/13G: Beneficial ownership crosses 5% (activist signals)
- S-1 / F-1: IPO filings
- SC 13E-3: Going-private transactions
- DEFA14A: Proxy statements (activist campaigns, board fights)
- Form 144: Restricted stock sales

Rate limited to 10 requests/sec with proper User-Agent header.
"""
import time
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Optional
from bs4 import BeautifulSoup
import requests

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import EDGAR_USER_AGENT, EDGAR_RATE_LIMIT
from config.universe import UNIVERSE, TICKER_TO_CIK
from data.edgar_client import EdgarClient

logger = logging.getLogger(__name__)


# 8-K Item codes and their meanings for event classification
EIGHT_K_ITEMS = {
    "1.01": "entry_into_material_agreement",
    "1.02": "termination_of_material_agreement",
    "1.03": "bankruptcy_or_receivership",
    "1.04": "mine_safety",
    "1.05": "material_cybersecurity_incident",
    "2.01": "acquisition_or_disposition",
    "2.02": "results_of_operations",  # Earnings
    "2.03": "creation_of_direct_obligation",
    "2.04": "triggering_events_for_obligation",
    "2.05": "exit_activity_costs",
    "2.06": "material_impairments",
    "3.01": "delisting_or_transfer",
    "3.02": "unregistered_equity_sales",
    "3.03": "material_modification_of_rights",
    "4.01": "change_in_accountant",
    "4.02": "non_reliance_on_financials",
    "5.01": "change_in_control",
    "5.02": "departure_of_directors_or_officers",  # Management changes
    "5.03": "amendments_to_articles",
    "5.04": "temporary_trading_suspension",
    "5.05": "amendments_to_code_of_ethics",
    "5.06": "change_in_shell_company_status",
    "5.07": "submission_of_matters_to_vote",
    "5.08": "shareholder_director_nominations",
    "6.01": "ads_delisting",
    "6.02": "ads_rule_12g3_2b_exemption",
    "6.03": "ads_termination",
    "6.04": "ads_failure_to_satisfy_listing",
    "6.05": "ads_written_communications",
    "7.01": "regulation_fd_disclosure",  # Material non-public info
    "8.01": "other_events",  # Catch-all
    "9.01": "financial_statements_and_exhibits",
}

# Categories for 8-K event grouping
EVENT_CATEGORIES = {
    "earnings": ["2.02"],
    "ma": ["2.01", "1.01", "1.02"],
    "management": ["5.02", "5.01"],
    "financing": ["2.03", "2.04", "3.02"],
    "governance": ["5.03", "5.07", "5.08", "4.01"],
    "risk": ["1.03", "2.05", "2.06", "4.02", "1.05"],
    "regulatory": ["7.01"],
    "other": ["8.01", "9.01"],
}


class EDGARRealtimeClient:
    """
    Real-time SEC EDGAR monitoring client.
    Polls EDGAR full-text search and RSS feeds for recent filings.
    """

    # EDGAR RSS feed URL
    RSS_FEED_URL = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type={form_type}&company=&dateb=&owner=include&count=100&output=atom"

    # EDGAR full-text search URL
    FULL_TEXT_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"

    # SEC filing search API
    FILINGS_API_URL = "https://efts.sec.gov/LATEST/search"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": EDGAR_USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
            "Accept": "application/json, application/xml, text/html, */*",
        })
        self._last_request_time = 0
        self._min_interval = 1.0 / EDGAR_RATE_LIMIT
        self._edgar_client = EdgarClient()

    def _rate_limit(self):
        """Enforce SEC's rate limit of 10 requests/second."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()

    def _get(self, url: str, params: dict = None) -> Optional[requests.Response]:
        """Make rate-limited GET request."""
        self._rate_limit()
        try:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException as e:
            logger.error(f"EDGAR request failed for {url}: {e}")
            return None

    def poll_recent_filings(self, form_types: list = None, minutes: int = 60) -> list:
        """
        Poll EDGAR full-text search for recent filings.

        Args:
            form_types: List of form types to search (e.g., ["10-K", "10-Q", "8-K", "4"])
            minutes: Look back this many minutes

        Returns:
            List of filing dicts with keys: ticker, cik, form_type, filed_date,
            accession_number, company_name, description, filing_url
        """
        if form_types is None:
            form_types = ["10-K", "10-Q", "8-K", "4", "13D", "13G", "S-1", "F-1"]

        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(minutes=minutes)

        all_filings = []

        for form_type in form_types:
            try:
                # Use the EDGAR filing search API
                params = {
                    "q": "*",
                    "dateRange": "custom",
                    "startdt": start_date.strftime("%Y-%m-%d"),
                    "enddt": end_date.strftime("%Y-%m-%d"),
                    "forms": form_type,
                }

                resp = self._get(self.FILINGS_API_URL, params=params)
                if resp is None:
                    continue

                data = resp.json()
                hits = data.get("hits", {}).get("hits", [])

                for hit in hits:
                    source = hit.get("_source", {})
                    filing = self._parse_search_result(source, form_type)
                    if filing:
                        all_filings.append(filing)

            except Exception as e:
                logger.error(f"Error polling {form_type} filings: {e}")
                continue

        # Deduplicate by accession number
        seen = set()
        unique_filings = []
        for f in all_filings:
            acc = f.get("accession_number")
            if acc and acc not in seen:
                seen.add(acc)
                unique_filings.append(f)

        logger.info(f"Found {len(unique_filings)} unique filings in last {minutes} minutes")
        return unique_filings

    def _parse_search_result(self, source: dict, form_type: str) -> Optional[dict]:
        """Parse a filing from EDGAR search results."""
        try:
            cik = str(source.get("ciks", [""])[0]).zfill(10) if source.get("ciks") else ""
            company_name = source.get("display_names", [""])[0] if source.get("display_names") else ""

            # Try to get ticker
            ticker = None
            tickers = source.get("tickers", [])
            if tickers:
                ticker = tickers[0]
            elif cik:
                # Look up ticker from CIK
                for t, c in TICKER_TO_CIK.items():
                    if c == cik or c == cik.lstrip("0"):
                        ticker = t
                        break

            accession = source.get("adsh", "").replace("-", "")
            filed_date = source.get("file_date", "")

            # Build filing URL
            filing_url = ""
            if cik and accession:
                filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{accession}"

            return {
                "ticker": ticker,
                "cik": cik,
                "form_type": source.get("form", form_type),
                "filed_date": filed_date,
                "accession_number": source.get("adsh", ""),
                "company_name": company_name,
                "description": source.get("file_description", ""),
                "filing_url": filing_url,
            }
        except Exception as e:
            logger.error(f"Error parsing search result: {e}")
            return None

    def poll_rss_feed(self, form_types: list = None) -> list:
        """
        Poll EDGAR RSS feed for latest filings.
        Fallback method if full-text search is unavailable.

        Args:
            form_types: List of form types to poll (will make one request per type)

        Returns:
            List of filing dicts
        """
        if form_types is None:
            form_types = ["10-K", "10-Q", "8-K", "4"]

        all_filings = []

        for form_type in form_types:
            try:
                url = self.RSS_FEED_URL.format(form_type=form_type)
                resp = self._get(url)
                if resp is None:
                    continue

                # Parse Atom feed
                root = ET.fromstring(resp.content)
                ns = {"atom": "http://www.w3.org/2005/Atom"}

                for entry in root.findall("atom:entry", ns):
                    try:
                        title = entry.find("atom:title", ns)
                        title_text = title.text if title is not None else ""

                        link = entry.find("atom:link", ns)
                        filing_url = link.get("href", "") if link is not None else ""

                        updated = entry.find("atom:updated", ns)
                        filed_date = updated.text[:10] if updated is not None else ""

                        summary = entry.find("atom:summary", ns)
                        summary_text = summary.text if summary is not None else ""

                        # Extract company name and form type from title
                        # Format: "Company Name (Form Type)"
                        company_name = title_text.split(" (")[0] if " (" in title_text else title_text

                        # Extract CIK from URL
                        cik_match = re.search(r"/data/(\d+)/", filing_url)
                        cik = cik_match.group(1).zfill(10) if cik_match else ""

                        # Extract accession number from URL
                        acc_match = re.search(r"/(\d{10}-\d{2}-\d{6})", filing_url)
                        accession = acc_match.group(1) if acc_match else ""

                        # Try to find ticker
                        ticker = None
                        if cik:
                            for t, c in TICKER_TO_CIK.items():
                                if c == cik or c == cik.lstrip("0"):
                                    ticker = t
                                    break

                        all_filings.append({
                            "ticker": ticker,
                            "cik": cik,
                            "form_type": form_type,
                            "filed_date": filed_date,
                            "accession_number": accession,
                            "company_name": company_name,
                            "description": summary_text,
                            "filing_url": filing_url,
                        })
                    except Exception as e:
                        logger.error(f"Error parsing RSS entry: {e}")
                        continue

            except Exception as e:
                logger.error(f"Error polling RSS for {form_type}: {e}")
                continue

        logger.info(f"Found {len(all_filings)} filings from RSS feeds")
        return all_filings

    def get_insider_trades(self, ticker: str, days: int = 30) -> list:
        """
        Get Form 4 insider transactions for a ticker.

        Args:
            ticker: Stock ticker symbol
            days: Look back this many days

        Returns:
            List of insider trade dicts with keys:
            - insider_name, title, transaction_type, shares, price, value
            - transaction_date, filing_date, accession_number
        """
        cik = self._edgar_client.get_cik(ticker)
        if not cik:
            logger.warning(f"No CIK found for {ticker}")
            return []

        # Get Form 4 filings
        filings = self._edgar_client.get_recent_filings(ticker, ["4"], days_back=days)

        trades = []
        for filing in filings:
            try:
                # Download and parse the Form 4 XML
                trade_data = self._parse_form4(filing)
                if trade_data:
                    trades.extend(trade_data)
            except Exception as e:
                logger.error(f"Error parsing Form 4 for {ticker}: {e}")
                continue

        logger.info(f"{ticker}: Found {len(trades)} insider trades in last {days} days")
        return trades

    def _parse_form4(self, filing: dict) -> list:
        """Parse a Form 4 filing to extract insider trade details."""
        trades = []

        # Get the filing URL and try to find the XML
        filing_url = filing.get("filing_url", "")
        if not filing_url:
            return trades

        # Form 4s have an XML file we can parse
        # Try to get the index page first
        self._rate_limit()
        try:
            # Get filing index
            base_url = filing_url.rsplit("/", 1)[0] if "/" in filing_url else filing_url
            index_url = f"{base_url}/index.json"

            resp = self.session.get(index_url, timeout=30)
            if resp.status_code != 200:
                return trades

            index_data = resp.json()

            # Find the XML file
            xml_file = None
            for item in index_data.get("directory", {}).get("item", []):
                name = item.get("name", "")
                if name.endswith(".xml") and "primary_doc" not in name.lower():
                    xml_file = name
                    break

            if not xml_file:
                return trades

            # Download and parse XML
            xml_url = f"{base_url}/{xml_file}"
            self._rate_limit()
            resp = self.session.get(xml_url, timeout=30)
            if resp.status_code != 200:
                return trades

            root = ET.fromstring(resp.content)

            # Extract issuer info
            issuer = root.find(".//issuer")
            ticker = issuer.find("issuerTradingSymbol").text if issuer is not None and issuer.find("issuerTradingSymbol") is not None else None

            # Extract reporting owner info
            owner = root.find(".//reportingOwner")
            if owner is not None:
                owner_id = owner.find("reportingOwnerId")
                owner_name = owner_id.find("rptOwnerName").text if owner_id is not None and owner_id.find("rptOwnerName") is not None else "Unknown"

                owner_rel = owner.find("reportingOwnerRelationship")
                titles = []
                if owner_rel is not None:
                    if owner_rel.find("isDirector") is not None and owner_rel.find("isDirector").text == "1":
                        titles.append("Director")
                    if owner_rel.find("isOfficer") is not None and owner_rel.find("isOfficer").text == "1":
                        officer_title = owner_rel.find("officerTitle")
                        titles.append(officer_title.text if officer_title is not None else "Officer")
                    if owner_rel.find("isTenPercentOwner") is not None and owner_rel.find("isTenPercentOwner").text == "1":
                        titles.append("10% Owner")
                title = ", ".join(titles) if titles else "Unknown"
            else:
                owner_name = "Unknown"
                title = "Unknown"

            # Extract transactions
            for txn in root.findall(".//nonDerivativeTransaction"):
                try:
                    security = txn.find(".//securityTitle/value")
                    security_title = security.text if security is not None else ""

                    txn_date = txn.find(".//transactionDate/value")
                    transaction_date = txn_date.text if txn_date is not None else ""

                    txn_code = txn.find(".//transactionCoding/transactionCode")
                    code = txn_code.text if txn_code is not None else ""

                    # P = Purchase, S = Sale, A = Award, M = Exercise
                    txn_type_map = {
                        "P": "BUY",
                        "S": "SELL",
                        "A": "AWARD",
                        "M": "EXERCISE",
                        "G": "GIFT",
                        "F": "TAX_WITHHOLDING",
                    }
                    transaction_type = txn_type_map.get(code, code)

                    shares_elem = txn.find(".//transactionAmounts/transactionShares/value")
                    shares = float(shares_elem.text) if shares_elem is not None else 0

                    price_elem = txn.find(".//transactionAmounts/transactionPricePerShare/value")
                    price = float(price_elem.text) if price_elem is not None and price_elem.text else 0

                    # Acquired or disposed
                    ad_elem = txn.find(".//transactionAmounts/transactionAcquiredDisposedCode/value")
                    ad_code = ad_elem.text if ad_elem is not None else ""

                    # Calculate value (negative for dispositions/sells)
                    value = shares * price
                    if ad_code == "D" or transaction_type == "SELL":
                        value = -value

                    trades.append({
                        "ticker": ticker or filing.get("ticker"),
                        "insider_name": owner_name,
                        "title": title,
                        "transaction_type": transaction_type,
                        "shares": int(shares),
                        "price": price,
                        "value": value,
                        "transaction_date": transaction_date,
                        "filing_date": filing.get("filing_date"),
                        "accession_number": filing.get("accession_number"),
                        "security_title": security_title,
                    })
                except Exception as e:
                    logger.error(f"Error parsing Form 4 transaction: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error parsing Form 4 XML: {e}")

        return trades

    def get_material_events(self, ticker: str, days: int = 30) -> list:
        """
        Get Form 8-K material events for a ticker, parsed by event type.

        Args:
            ticker: Stock ticker symbol
            days: Look back this many days

        Returns:
            List of event dicts with keys:
            - event_type, category, items, description
            - filing_date, accession_number, filing_url
        """
        filings = self._edgar_client.get_recent_filings(ticker, ["8-K"], days_back=days)

        events = []
        for filing in filings:
            try:
                event = self._parse_8k_event(filing)
                if event:
                    events.append(event)
            except Exception as e:
                logger.error(f"Error parsing 8-K for {ticker}: {e}")
                continue

        logger.info(f"{ticker}: Found {len(events)} material events in last {days} days")
        return events

    def _parse_8k_event(self, filing: dict) -> Optional[dict]:
        """Parse an 8-K filing to extract event details."""
        try:
            # Download filing text
            text = self._edgar_client.download_filing_text(filing, max_chars=20000)
            if not text:
                return None

            # Look for item numbers in the text
            items_found = []
            for item_code in EIGHT_K_ITEMS.keys():
                # Match patterns like "Item 2.02" or "ITEM 2.02"
                pattern = rf"Item\s*{re.escape(item_code)}"
                if re.search(pattern, text, re.IGNORECASE):
                    items_found.append(item_code)

            if not items_found:
                items_found = ["8.01"]  # Default to "other events"

            # Determine category from items
            category = "other"
            for cat, cat_items in EVENT_CATEGORIES.items():
                if any(item in cat_items for item in items_found):
                    category = cat
                    break

            # Get event type descriptions
            event_types = [EIGHT_K_ITEMS.get(item, item) for item in items_found]

            # Extract a brief description (first ~500 chars after item header)
            description = ""
            for item in items_found:
                pattern = rf"Item\s*{re.escape(item)}[^a-zA-Z]*([^\n]+)"
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    description = match.group(1).strip()[:500]
                    break

            return {
                "ticker": filing.get("ticker"),
                "event_type": ", ".join(event_types),
                "category": category,
                "items": items_found,
                "description": description or filing.get("description", ""),
                "filing_date": filing.get("filing_date"),
                "accession_number": filing.get("accession_number"),
                "filing_url": filing.get("filing_url"),
            }
        except Exception as e:
            logger.error(f"Error parsing 8-K: {e}")
            return None

    def get_ownership_changes(self, ticker: str) -> list:
        """
        Get 13D/13G beneficial ownership filings.
        Filed when someone crosses 5% ownership threshold.

        Args:
            ticker: Stock ticker symbol

        Returns:
            List of ownership change dicts with keys:
            - filer_name, ownership_pct, shares, filing_type
            - filing_date, accession_number, filing_url
        """
        # Get 13D and 13G filings (13D = activist, 13G = passive)
        filings = self._edgar_client.get_recent_filings(
            ticker, ["13D", "13D/A", "13G", "13G/A", "SC 13D", "SC 13G"], days_back=365
        )

        ownership_changes = []
        for filing in filings:
            try:
                # Download and parse
                text = self._edgar_client.download_filing_text(filing, max_chars=30000)
                if not text:
                    continue

                # Try to extract filer name
                filer_match = re.search(r"NAME OF REPORTING PERSON[:\s]*([^\n]+)", text, re.IGNORECASE)
                filer_name = filer_match.group(1).strip() if filer_match else "Unknown"

                # Try to extract ownership percentage
                pct_match = re.search(r"PERCENT OF CLASS[:\s]*(\d+\.?\d*)\s*%?", text, re.IGNORECASE)
                ownership_pct = float(pct_match.group(1)) if pct_match else None

                # Try to extract shares
                shares_match = re.search(r"AGGREGATE AMOUNT[:\s]*([\d,]+)", text, re.IGNORECASE)
                shares = int(shares_match.group(1).replace(",", "")) if shares_match else None

                # Determine if activist (13D) or passive (13G)
                filing_type = filing.get("form_type", "")
                is_activist = "13D" in filing_type and "13G" not in filing_type

                ownership_changes.append({
                    "ticker": ticker,
                    "filer_name": filer_name,
                    "ownership_pct": ownership_pct,
                    "shares": shares,
                    "filing_type": filing_type,
                    "is_activist": is_activist,
                    "filing_date": filing.get("filing_date"),
                    "accession_number": filing.get("accession_number"),
                    "filing_url": filing.get("filing_url"),
                })
            except Exception as e:
                logger.error(f"Error parsing 13D/13G for {ticker}: {e}")
                continue

        logger.info(f"{ticker}: Found {len(ownership_changes)} ownership changes")
        return ownership_changes

    def get_form144_sales(self, ticker: str, days: int = 90) -> list:
        """
        Get Form 144 restricted stock sale notices.
        Filed when insiders intend to sell restricted securities.

        Args:
            ticker: Stock ticker symbol
            days: Look back this many days

        Returns:
            List of Form 144 dicts
        """
        filings = self._edgar_client.get_recent_filings(ticker, ["144"], days_back=days)

        sales = []
        for filing in filings:
            sales.append({
                "ticker": ticker,
                "filing_date": filing.get("filing_date"),
                "accession_number": filing.get("accession_number"),
                "filing_url": filing.get("filing_url"),
                "description": filing.get("description", "Restricted stock sale notice"),
            })

        logger.info(f"{ticker}: Found {len(sales)} Form 144 notices in last {days} days")
        return sales

    def scan_universe_filings(self, form_types: list = None, days: int = 7) -> list:
        """
        Scan all universe tickers for recent filings.

        Args:
            form_types: List of form types to scan
            days: Look back this many days

        Returns:
            List of all filings found, sorted by date descending
        """
        if form_types is None:
            form_types = ["10-K", "10-Q", "8-K", "4", "13D", "13G"]

        all_filings = []
        for ticker in UNIVERSE.keys():
            try:
                filings = self._edgar_client.get_recent_filings(ticker, form_types, days_back=days)
                all_filings.extend(filings)
            except Exception as e:
                logger.error(f"Error scanning {ticker}: {e}")
                continue

        # Sort by filing date descending
        all_filings.sort(key=lambda x: x.get("filing_date", ""), reverse=True)

        logger.info(f"Universe scan: {len(all_filings)} filings across {len(UNIVERSE)} tickers")
        return all_filings


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    print("\n" + "="*60)
    print("ATLAS SEC EDGAR Real-Time Client")
    print("="*60 + "\n")

    client = EDGARRealtimeClient()

    # Test recent filings poll
    print("Polling recent filings (last 24 hours)...")
    recent = client.poll_recent_filings(minutes=1440)
    print(f"Found {len(recent)} recent filings")
    for f in recent[:5]:
        print(f"  {f['filed_date']} | {f['form_type']} | {f.get('ticker', 'N/A')} | {f['company_name'][:40]}")

    # Test insider trades for NVDA
    print("\n--- NVDA Insider Trades (30 days) ---")
    trades = client.get_insider_trades("NVDA", days=30)
    for t in trades[:5]:
        print(f"  {t['transaction_date']} | {t['insider_name'][:25]} | {t['transaction_type']} | {t['shares']:,} shares | ${t['value']:,.0f}")

    # Test material events for NVDA
    print("\n--- NVDA Material Events (30 days) ---")
    events = client.get_material_events("NVDA", days=30)
    for e in events[:5]:
        print(f"  {e['filing_date']} | {e['category']} | {e['event_type']}")

    # Test ownership changes
    print("\n--- NVDA Ownership Changes ---")
    ownership = client.get_ownership_changes("NVDA")
    for o in ownership[:3]:
        print(f"  {o['filing_date']} | {o['filer_name'][:30]} | {o['ownership_pct']}% | {'ACTIVIST' if o['is_activist'] else 'PASSIVE'}")
