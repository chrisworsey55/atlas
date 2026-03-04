"""
13F Institutional Holdings Client for ATLAS
Parses 13F-HR filings from SEC EDGAR to track hedge fund positions.

Uses the edgartools library for easy 13F parsing:
pip install edgartools

Also includes a fallback using direct SEC API for robustness.
"""
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from collections import defaultdict

import requests
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import DATA_DIR, EDGAR_USER_AGENT
from config.universe import TRACKED_FUNDS, UNIVERSE

logger = logging.getLogger(__name__)

# Cache directory for 13F data
THIRTEENF_CACHE_DIR = DATA_DIR / "thirteenf_cache"
THIRTEENF_CACHE_DIR.mkdir(exist_ok=True)


class ThirteenFClient:
    """
    Client for parsing 13F-HR filings.
    Tracks positions across 16 top hedge funds.
    """
    
    def __init__(self, use_edgartools: bool = True):
        self.use_edgartools = use_edgartools
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": EDGAR_USER_AGENT})
        self._last_request_time = 0
        
        # Try importing edgartools
        if use_edgartools:
            try:
                from edgar import Company, set_identity
                set_identity(EDGAR_USER_AGENT)
                self.edgar_available = True
                logger.info("edgartools loaded successfully")
            except ImportError:
                logger.warning("edgartools not installed, using fallback API")
                self.edgar_available = False
        else:
            self.edgar_available = False
    
    def _rate_limit(self):
        """Respect SEC rate limits (10 req/sec)."""
        elapsed = time.time() - self._last_request_time
        if elapsed < 0.1:
            time.sleep(0.1 - elapsed)
        self._last_request_time = time.time()
    
    def get_fund_holdings_edgartools(self, cik: str, fund_name: str) -> Optional[pd.DataFrame]:
        """
        Get latest 13F holdings using edgartools library.
        Returns DataFrame with normalized columns: name, cusip, shares, value, ticker, put_call
        """
        try:
            from edgar import Company
            
            company = Company(cik)
            filings = company.get_filings(form="13F-HR")
            
            if not filings or len(filings) == 0:
                logger.warning(f"No 13F filings found for {fund_name}")
                return None
            
            # Get most recent filing
            latest = filings[0]
            report = latest.obj()
            
            if hasattr(report, 'holdings'):
                df = report.holdings.copy()
                
                # Normalize column names (edgartools returns Issuer, Value, SharesPrnAmount, etc.)
                column_map = {
                    'Issuer': 'name',
                    'nameOfIssuer': 'name',
                    'Value': 'value',
                    'SharesPrnAmount': 'shares',
                    'sshPrnamt': 'shares',
                    'Cusip': 'cusip',
                    'Ticker': 'ticker',
                    'PutCall': 'put_call',
                    'putCall': 'put_call',
                }
                df = df.rename(columns={k: v for k, v in column_map.items() if k in df.columns})
                
                df['fund_name'] = fund_name
                df['cik'] = cik
                df['filing_date'] = str(latest.filing_date) if hasattr(latest, 'filing_date') else None
                df['quarter'] = self._get_quarter_from_date(df['filing_date'].iloc[0]) if len(df) > 0 else None
                return df
            else:
                logger.warning(f"No holdings data in 13F for {fund_name}")
                return None
                
        except Exception as e:
            logger.error(f"edgartools error for {fund_name}: {e}")
            return None
    
    def get_fund_holdings_fallback(self, cik: str, fund_name: str) -> Optional[pd.DataFrame]:
        """
        Fallback method using direct SEC API.
        Parses the 13F XML directly.
        """
        self._rate_limit()
        
        # Get submissions
        cik_padded = cik.zfill(10)
        url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
        
        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"Failed to get submissions for {fund_name}: {e}")
            return None
        
        # Find latest 13F-HR
        filings = data.get("filings", {}).get("recent", {})
        forms = filings.get("form", [])
        accessions = filings.get("accessionNumber", [])
        filing_dates = filings.get("filingDate", [])
        
        latest_13f = None
        for i, form in enumerate(forms):
            if form == "13F-HR":
                latest_13f = {
                    "accession": accessions[i],
                    "filing_date": filing_dates[i],
                }
                break
        
        if not latest_13f:
            logger.warning(f"No 13F-HR found for {fund_name}")
            return None
        
        # Get the infotable.xml
        accession_clean = latest_13f["accession"].replace("-", "")
        infotable_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_clean}/infotable.xml"
        
        self._rate_limit()
        try:
            resp = self.session.get(infotable_url, timeout=30)
            if resp.status_code == 404:
                # Try primary_doc.xml pattern
                infotable_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_clean}"
                resp = self.session.get(infotable_url, timeout=30)
                # Would need to parse HTML and find XML file - skip for now
                logger.warning(f"Could not find infotable.xml for {fund_name}")
                return None
            resp.raise_for_status()
            xml_content = resp.text
        except Exception as e:
            logger.error(f"Failed to get 13F XML for {fund_name}: {e}")
            return None
        
        # Parse XML
        holdings = self._parse_13f_xml(xml_content)
        if not holdings:
            return None
        
        df = pd.DataFrame(holdings)
        df['fund_name'] = fund_name
        df['cik'] = cik
        df['filing_date'] = latest_13f["filing_date"]
        df['quarter'] = self._get_quarter_from_date(latest_13f["filing_date"])
        
        return df
    
    def _parse_13f_xml(self, xml_content: str) -> list[dict]:
        """Parse 13F infotable XML into list of holdings."""
        from xml.etree import ElementTree as ET
        
        holdings = []
        try:
            root = ET.fromstring(xml_content)
            
            # Handle namespace
            ns = {'ns': 'http://www.sec.gov/edgar/document/thirteenf/informationtable'}
            
            for info_table in root.findall('.//ns:infoTable', ns) or root.findall('.//infoTable'):
                holding = {}
                
                # Try with namespace first, then without
                for field, xpath in [
                    ('name', './/ns:nameOfIssuer'),
                    ('cusip', './/ns:cusip'),
                    ('value', './/ns:value'),
                    ('shares', './/ns:sshPrnamt'),
                    ('share_type', './/ns:sshPrnamtType'),
                    ('put_call', './/ns:putCall'),
                    ('discretion', './/ns:investmentDiscretion'),
                    ('voting_sole', './/ns:Sole'),
                    ('voting_shared', './/ns:Shared'),
                    ('voting_none', './/ns:None'),
                ]:
                    elem = info_table.find(xpath, ns)
                    if elem is None:
                        elem = info_table.find(xpath.replace('ns:', ''))
                    holding[field] = elem.text if elem is not None else None
                
                # Convert numeric fields
                if holding.get('value'):
                    holding['value'] = int(holding['value']) * 1000  # 13F values in thousands
                if holding.get('shares'):
                    holding['shares'] = int(holding['shares'])
                
                holdings.append(holding)
                
        except ET.ParseError as e:
            logger.error(f"XML parse error: {e}")
            return []
        
        return holdings
    
    def _get_quarter_from_date(self, date_str: str) -> str:
        """Convert filing date to quarter string (e.g., '2026Q1')."""
        if not date_str:
            return None
        try:
            dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
            quarter = (dt.month - 1) // 3 + 1
            return f"{dt.year}Q{quarter}"
        except:
            return None
    
    def get_fund_holdings(self, fund_name: str) -> Optional[pd.DataFrame]:
        """
        Get holdings for a tracked fund by name.
        Uses edgartools if available, fallback otherwise.
        """
        fund_info = TRACKED_FUNDS.get(fund_name)
        if not fund_info:
            logger.error(f"Unknown fund: {fund_name}")
            return None
        
        cik = fund_info["cik"]
        
        if self.edgar_available:
            df = self.get_fund_holdings_edgartools(cik, fund_name)
            if df is not None:
                return df
        
        return self.get_fund_holdings_fallback(cik, fund_name)
    
    def get_all_fund_holdings(self, cache_hours: int = 24) -> dict[str, pd.DataFrame]:
        """
        Get holdings for all tracked funds.
        Returns dict of fund_name -> DataFrame.
        Caches results to disk.
        """
        cache_file = THIRTEENF_CACHE_DIR / "all_holdings.json"
        
        # Check cache
        if cache_file.exists():
            cache_age = time.time() - cache_file.stat().st_mtime
            if cache_age < cache_hours * 3600:
                logger.info("Loading 13F holdings from cache")
                with open(cache_file) as f:
                    cached = json.load(f)
                return {name: pd.DataFrame(data) for name, data in cached.items()}
        
        # Fetch fresh data
        all_holdings = {}
        for fund_name in TRACKED_FUNDS:
            logger.info(f"Fetching 13F for {fund_name}...")
            try:
                df = self.get_fund_holdings(fund_name)
                if df is not None and len(df) > 0:
                    all_holdings[fund_name] = df
                    logger.info(f"  {fund_name}: {len(df)} positions")
                else:
                    logger.warning(f"  {fund_name}: no holdings data")
            except Exception as e:
                logger.error(f"  {fund_name}: error - {e}")
            
            # Be nice to SEC
            time.sleep(0.5)
        
        # Cache results
        if all_holdings:
            cache_data = {name: df.to_dict(orient='records') for name, df in all_holdings.items()}
            with open(cache_file, 'w') as f:
                json.dump(cache_data, f)
            logger.info(f"Cached {len(all_holdings)} fund holdings")
        
        return all_holdings
    
    def analyze_position_changes(self, fund_name: str, current_holdings: pd.DataFrame, 
                                 previous_holdings: pd.DataFrame) -> list[dict]:
        """
        Compare current vs previous quarter holdings.
        Returns list of changes: NEW, INCREASED, DECREASED, CLOSED, UNCHANGED
        """
        changes = []
        
        if current_holdings is None or len(current_holdings) == 0:
            return changes
        
        # Create lookup by CUSIP
        current_by_cusip = {row['cusip']: row for _, row in current_holdings.iterrows()}
        prev_by_cusip = {}
        if previous_holdings is not None and len(previous_holdings) > 0:
            prev_by_cusip = {row['cusip']: row for _, row in previous_holdings.iterrows()}
        
        # Check current positions
        for cusip, current in current_by_cusip.items():
            prev = prev_by_cusip.get(cusip)
            
            if prev is None:
                change_type = "NEW"
                change_pct = None
            else:
                current_shares = current.get('shares', 0) or 0
                prev_shares = prev.get('shares', 0) or 0
                
                if prev_shares == 0:
                    change_type = "NEW"
                    change_pct = None
                elif current_shares == prev_shares:
                    change_type = "UNCHANGED"
                    change_pct = 0
                elif current_shares > prev_shares:
                    change_type = "INCREASED"
                    change_pct = (current_shares - prev_shares) / prev_shares
                else:
                    change_type = "DECREASED"
                    change_pct = (current_shares - prev_shares) / prev_shares
            
            changes.append({
                "fund_name": fund_name,
                "cusip": cusip,
                "name": current.get('name'),
                "shares": current.get('shares'),
                "value": current.get('value'),
                "change_type": change_type,
                "change_pct": change_pct,
                "quarter": current.get('quarter'),
            })
        
        # Check for closed positions
        for cusip, prev in prev_by_cusip.items():
            if cusip not in current_by_cusip:
                changes.append({
                    "fund_name": fund_name,
                    "cusip": cusip,
                    "name": prev.get('name'),
                    "shares": 0,
                    "value": 0,
                    "change_type": "CLOSED",
                    "change_pct": -1.0,
                    "quarter": current_holdings['quarter'].iloc[0] if len(current_holdings) > 0 else None,
                })
        
        return changes
    
    def build_consensus_report(self, all_holdings: dict[str, pd.DataFrame]) -> dict:
        """
        Build a report analyzing:
        - Consensus builds (3+ funds accumulating same stock)
        - Crowding warnings (stock in 10+ funds)
        - Contrarian signals (top fund, solo position)
        - Conviction positions (>5% of portfolio)
        """
        # Aggregate by ticker
        ticker_holders = defaultdict(list)
        ticker_values = defaultdict(float)
        
        for fund_name, df in all_holdings.items():
            if df is None or len(df) == 0:
                continue
            
            # Calculate total portfolio value for this fund
            total_value = df['value'].sum() if 'value' in df.columns else 0
            
            for _, row in df.iterrows():
                name = row.get('name', '').upper() if row.get('name') else ''
                value = row.get('value', 0) or 0
                
                # Try to match to our universe
                ticker = self._name_to_ticker(name)
                if ticker:
                    pct_of_portfolio = (value / total_value * 100) if total_value > 0 else 0
                    ticker_holders[ticker].append({
                        "fund": fund_name,
                        "value": value,
                        "shares": row.get('shares'),
                        "pct_of_portfolio": round(pct_of_portfolio, 2),
                    })
                    ticker_values[ticker] += value
        
        # Build report sections
        consensus_builds = []
        crowding_warnings = []
        contrarian_signals = []
        conviction_positions = []
        
        for ticker, holders in ticker_holders.items():
            num_holders = len(holders)
            
            # Crowding warning: 10+ funds holding
            if num_holders >= 10:
                crowding_warnings.append({
                    "ticker": ticker,
                    "funds_holding": num_holders,
                    "of_total": len(all_holdings),
                    "signal": f"Extreme crowding — any negative catalyst creates synchronised selling risk",
                })
            
            # Consensus build: 3+ funds with significant positions
            if 3 <= num_holders < 10:
                fund_names = [h["fund"].split(" (")[0] for h in holders]  # Shorten names
                consensus_builds.append({
                    "ticker": ticker,
                    "funds_accumulating": fund_names[:5],  # Top 5
                    "signal": f"{num_holders} high-conviction funds building positions",
                })
            
            # Check for conviction positions (>5% of portfolio)
            for holder in holders:
                if holder["pct_of_portfolio"] >= 5:
                    conviction_positions.append({
                        "ticker": ticker,
                        "fund": holder["fund"],
                        "portfolio_pct": holder["pct_of_portfolio"],
                        "signal": f"Top position at {holder['pct_of_portfolio']:.1f}% of portfolio = maximum conviction",
                    })
            
            # Contrarian signal: only 1 fund holding a large position
            if num_holders == 1 and holders[0]["pct_of_portfolio"] >= 3:
                fund = holders[0]["fund"]
                style = TRACKED_FUNDS.get(fund, {}).get("style", "")
                contrarian_signals.append({
                    "ticker": ticker,
                    "fund": fund,
                    "portfolio_pct": holders[0]["pct_of_portfolio"],
                    "signal": f"Solo position by {style} fund — potentially highest alpha",
                })
        
        # Sort by relevance
        consensus_builds.sort(key=lambda x: len(x.get("funds_accumulating", [])), reverse=True)
        crowding_warnings.sort(key=lambda x: x["funds_holding"], reverse=True)
        conviction_positions.sort(key=lambda x: x["portfolio_pct"], reverse=True)
        
        return {
            "briefing_type": "institutional_flow",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "funds_analyzed": len(all_holdings),
            "consensus_builds": consensus_builds[:10],  # Top 10
            "crowding_warnings": crowding_warnings[:5],  # Top 5
            "contrarian_signals": contrarian_signals[:10],
            "notable_exits": [],  # Would need historical comparison
            "conviction_positions": conviction_positions[:15],  # Top 15
        }
    
    def _name_to_ticker(self, name: str) -> Optional[str]:
        """
        Try to match company name from 13F to our universe ticker.
        Simple heuristic matching.
        """
        name_upper = name.upper()
        
        # Direct matches
        for ticker, info in UNIVERSE.items():
            company_name = info.get("name", "").upper()
            if company_name in name_upper or name_upper in company_name:
                return ticker
        
        # Common variations
        name_map = {
            "APPLE": "AAPL",
            "MICROSOFT": "MSFT",
            "NVIDIA": "NVDA",
            "ALPHABET": "GOOGL",
            "GOOGLE": "GOOGL",
            "META PLATFORMS": "META",
            "FACEBOOK": "META",
            "AMAZON": "AMZN",
            "TAIWAN SEMICONDUCTOR": "TSM",
            "BROADCOM": "AVGO",
            "SALESFORCE": "CRM",
            "ADVANCED MICRO": "AMD",
            "JPMORGAN": "JPM",
            "J P MORGAN": "JPM",
            "VISA INC": "V",
            "MASTERCARD": "MA",
            "BANK OF AMERICA": "BAC",
            "GOLDMAN SACHS": "GS",
            "MORGAN STANLEY": "MS",
            "BLACKROCK": "BLK",
            "UNITEDHEALTH": "UNH",
            "JOHNSON & JOHNSON": "JNJ",
            "ELI LILLY": "LLY",
            "PFIZER": "PFE",
            "ABBVIE": "ABBV",
            "MERCK": "MRK",
            "THERMO FISHER": "TMO",
            "WALMART": "WMT",
            "COSTCO": "COST",
            "PROCTER & GAMBLE": "PG",
            "COCA-COLA": "KO",
            "COCA COLA": "KO",
            "PEPSICO": "PEP",
            "MCDONALD": "MCD",
            "NIKE": "NKE",
            "STARBUCKS": "SBUX",
            "CATERPILLAR": "CAT",
            "GE AEROSPACE": "GE",
            "GENERAL ELECTRIC": "GE",
            "HONEYWELL": "HON",
            "UNITED PARCEL": "UPS",
            "BOEING": "BA",
            "RAYTHEON": "RTX",
            "EXXON": "XOM",
            "CHEVRON": "CVX",
            "CONOCOPHILLIPS": "COP",
            "DISNEY": "DIS",
            "WALT DISNEY": "DIS",
            "NETFLIX": "NFLX",
            "COMCAST": "CMCSA",
            "AMERICAN TOWER": "AMT",
            "NEXTERA": "NEE",
            "LINDE": "LIN",
            "FREEPORT": "FCX",
            "INTEL": "INTC",
            "MICRON": "MU",
            "QUALCOMM": "QCOM",
        }
        
        for key, ticker in name_map.items():
            if key in name_upper:
                return ticker
        
        return None


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )
    
    print("\n" + "="*60)
    print("ATLAS 13F Client - Test Run")
    print("="*60 + "\n")
    
    client = ThirteenFClient(use_edgartools=True)
    
    # Test single fund
    print("Testing Berkshire Hathaway 13F...")
    df = client.get_fund_holdings("Berkshire Hathaway (Buffett)")
    
    if df is not None:
        print(f"\nBerkshire holdings: {len(df)} positions")
        print("\nTop 10 by value:")
        if 'value' in df.columns:
            top10 = df.nlargest(10, 'value')
            for _, row in top10.iterrows():
                print(f"  {row.get('name', 'N/A')[:30]:30} ${row.get('value', 0):>15,.0f}")
    else:
        print("Could not fetch Berkshire holdings")
    
    # Test consensus report (would need multiple funds)
    print("\n" + "-"*40)
    print("Fetching all tracked funds (this may take a minute)...")
    all_holdings = client.get_all_fund_holdings()
    
    if all_holdings:
        print(f"\nSuccessfully fetched {len(all_holdings)} funds")
        report = client.build_consensus_report(all_holdings)
        print("\n=== INSTITUTIONAL FLOW BRIEFING ===")
        print(json.dumps(report, indent=2))
