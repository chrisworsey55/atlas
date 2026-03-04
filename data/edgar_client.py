"""
SEC EDGAR Client for ATLAS
Handles all communication with the free SEC EDGAR API.
No API key required — just a User-Agent header.

Endpoints used:
- Submissions: https://data.sec.gov/submissions/CIK{cik}.json
- Company Facts (XBRL): https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json
- Filing archives: https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{doc}
- Ticker->CIK mapping: https://www.sec.gov/files/company_tickers.json
"""
import time
import json
import logging
import requests
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from bs4 import BeautifulSoup

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import (
    EDGAR_BASE_URL,
    EDGAR_USER_AGENT,
    EDGAR_RATE_LIMIT,
    DATA_DIR,
)
from config.universe import UNIVERSE, TICKER_TO_CIK

logger = logging.getLogger(__name__)


class EdgarClient:
    """
    Client for SEC EDGAR free API.
    Rate limited to 10 req/s as per SEC guidelines.
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": EDGAR_USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
        })
        self._last_request_time = 0
        self._min_interval = 1.0 / EDGAR_RATE_LIMIT
        self._cik_map = {}
        self._load_cik_map()

    def _rate_limit(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()

    def _get(self, url: str) -> Optional[dict]:
        self._rate_limit()
        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.JSONDecodeError:
            return {"_raw_text": resp.text}
        except requests.exceptions.RequestException as e:
            logger.error(f"EDGAR request failed for {url}: {e}")
            return None

    def _get_text(self, url: str) -> Optional[str]:
        self._rate_limit()
        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            return resp.text
        except requests.exceptions.RequestException as e:
            logger.error(f"EDGAR request failed for {url}: {e}")
            return None

    # --- CIK Mapping ---

    def _load_cik_map(self):
        cache_file = DATA_DIR / "company_tickers.json"
        if cache_file.exists():
            age = time.time() - cache_file.stat().st_mtime
            if age < 86400:  # Cache for 24h
                with open(cache_file) as f:
                    data = json.load(f)
                self._build_cik_lookup(data)
                return
        logger.info("Downloading SEC ticker -> CIK mapping...")
        url = "https://www.sec.gov/files/company_tickers.json"
        data = self._get(url)
        if data and "_raw_text" not in data:
            with open(cache_file, "w") as f:
                json.dump(data, f)
            self._build_cik_lookup(data)

    def _build_cik_lookup(self, data: dict):
        for entry in data.values():
            ticker = entry.get("ticker", "").upper()
            cik = str(entry.get("cik_str", ""))
            if ticker and cik:
                self._cik_map[ticker] = cik
                if ticker in UNIVERSE:
                    TICKER_TO_CIK[ticker] = cik

    def get_cik(self, ticker: str) -> Optional[str]:
        cik = self._cik_map.get(ticker.upper())
        if cik:
            return cik.zfill(10)
        return None

    # --- Submissions (Filing History) ---

    def get_submissions(self, ticker: str) -> Optional[dict]:
        cik = self.get_cik(ticker)
        if not cik:
            logger.warning(f"No CIK found for {ticker}")
            return None
        url = f"{EDGAR_BASE_URL}/submissions/CIK{cik}.json"
        return self._get(url)

    def get_recent_filings(self, ticker: str, filing_types: list[str] = None, days_back: int = 90) -> list[dict]:
        if filing_types is None:
            filing_types = ["10-K", "10-Q", "8-K"]
        submissions = self.get_submissions(ticker)
        if not submissions:
            return []
        cutoff_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        recent = submissions.get("filings", {}).get("recent", {})
        if not recent:
            return []
        filings = []
        accession_numbers = recent.get("accessionNumber", [])
        filing_dates = recent.get("filingDate", [])
        forms = recent.get("form", [])
        primary_docs = recent.get("primaryDocument", [])
        descriptions = recent.get("primaryDocDescription", [])
        cik = self.get_cik(ticker)
        for i in range(len(accession_numbers)):
            form_type = forms[i] if i < len(forms) else ""
            filing_date = filing_dates[i] if i < len(filing_dates) else ""
            if form_type not in filing_types:
                continue
            if filing_date < cutoff_date:
                continue
            accession_clean = accession_numbers[i].replace("-", "")
            primary_doc = primary_docs[i] if i < len(primary_docs) else ""
            filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{accession_clean}/{primary_doc}"
            filings.append({
                "ticker": ticker, "cik": cik,
                "accession_number": accession_numbers[i],
                "filing_date": filing_date, "form_type": form_type,
                "primary_document": primary_doc,
                "description": descriptions[i] if i < len(descriptions) else "",
                "filing_url": filing_url,
            })
        logger.info(f"{ticker}: Found {len(filings)} filings in last {days_back} days")
        return filings

    # --- Filing Content Download ---

    def download_filing_text(self, filing: dict, max_chars: int = 100_000) -> Optional[str]:
        url = filing.get("filing_url")
        if not url:
            return None
        raw_html = self._get_text(url)
        if not raw_html:
            return None
        soup = BeautifulSoup(raw_html, "html.parser")
        for element in soup(["script", "style", "meta", "link"]):
            element.decompose()
        text = soup.get_text(separator="\n", strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        clean_text = "\n".join(lines)
        if len(clean_text) > max_chars:
            half = max_chars // 2
            clean_text = clean_text[:half] + "\n\n[... FILING TRUNCATED ...]\n\n" + clean_text[-half:]
        return clean_text

    # --- XBRL Company Facts ---

    def get_company_facts(self, ticker: str) -> Optional[dict]:
        cik = self.get_cik(ticker)
        if not cik:
            return None
        url = f"{EDGAR_BASE_URL}/api/xbrl/companyfacts/CIK{cik}.json"
        return self._get(url)

    def get_key_financials(self, ticker: str) -> Optional[dict]:
        facts = self.get_company_facts(ticker)
        if not facts:
            return None
        us_gaap = facts.get("facts", {}).get("us-gaap", {})

        def _latest_value(tag: str, unit: str = "USD") -> Optional[float]:
            tag_data = us_gaap.get(tag, {})
            units = tag_data.get("units", {}).get(unit, [])
            if not units:
                return None
            sorted_vals = sorted(units, key=lambda x: x.get("end", ""), reverse=True)
            for val in sorted_vals:
                if val.get("form", "") in ("10-K", "10-Q"):
                    return val.get("val")
            return sorted_vals[0].get("val") if sorted_vals else None

        return {
            "ticker": ticker,
            "revenue": _latest_value("Revenues") or _latest_value("RevenueFromContractWithCustomerExcludingAssessedTax"),
            "net_income": _latest_value("NetIncomeLoss"),
            "total_assets": _latest_value("Assets"),
            "total_liabilities": _latest_value("Liabilities"),
            "stockholders_equity": _latest_value("StockholdersEquity"),
            "operating_income": _latest_value("OperatingIncomeLoss"),
            "cash_and_equivalents": _latest_value("CashAndCashEquivalentsAtCarryingValue"),
            "long_term_debt": _latest_value("LongTermDebt") or _latest_value("LongTermDebtNoncurrent"),
            "shares_outstanding": _latest_value("CommonStockSharesOutstanding", unit="shares"),
            "eps": _latest_value("EarningsPerShareBasic", unit="USD/shares"),
            # Semiconductor-specific XBRL tags
            "inventory": _latest_value("InventoryNet"),
            "gross_profit": _latest_value("GrossProfit"),
            "research_and_development": _latest_value("ResearchAndDevelopmentExpense"),
            "cost_of_revenue": _latest_value("CostOfRevenue") or _latest_value("CostOfGoodsAndServicesSold"),
        }

    # --- Batch Operations ---

    def scan_universe(self, tickers: list[str] = None, filing_types: list[str] = None, days_back: int = 90) -> list[dict]:
        if filing_types is None:
            filing_types = ["10-K", "10-Q", "8-K"]
        if tickers is None:
            tickers = list(UNIVERSE.keys())
        all_filings = []
        for ticker in tickers:
            try:
                filings = self.get_recent_filings(ticker, filing_types, days_back)
                all_filings.extend(filings)
            except Exception as e:
                logger.error(f"Error scanning {ticker}: {e}")
        logger.info(f"Universe scan complete: {len(all_filings)} filings across {len(tickers)} tickers")
        return all_filings


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    client = EdgarClient()
    print(f"\nNVDA CIK: {client.get_cik('NVDA')}")
    print(f"AAPL CIK: {client.get_cik('AAPL')}")
    print("\n--- Recent NVDA Filings ---")
    filings = client.get_recent_filings("NVDA", days_back=180)
    for f in filings[:5]:
        print(f"  {f['filing_date']} | {f['form_type']} | {f['description']}")
    print("\n--- NVDA Key Financials ---")
    financials = client.get_key_financials("NVDA")
    if financials:
        for k, v in financials.items():
            if v is not None and k != "ticker":
                print(f"  {k}: {v:,.0f}" if isinstance(v, (int, float)) else f"  {k}: {v}")
