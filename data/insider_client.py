"""
SEC Form 4 Insider Transaction Client for ATLAS
Pulls insider buying/selling data - filed within 2 days of transactions.
Much faster signal than quarterly 13F data.
"""
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Optional

from .edgar_client import EdgarClient
from config.universe import UNIVERSE

logger = logging.getLogger(__name__)


class InsiderClient:
    """
    Client for SEC Form 4 insider transaction filings.
    Form 4s are filed within 2 business days of insider trades.
    """

    def __init__(self):
        self.edgar = EdgarClient()

    def get_recent_insider_trades(self, ticker: str, days: int = 30) -> list[dict]:
        """
        Pull Form 4 filings from EDGAR for a ticker.

        Returns list of:
            {insider_name, title, transaction_type (BUY/SELL/EXERCISE),
             shares, price, value, filing_date, form_type}
        """
        filings = self.edgar.get_recent_filings(ticker, filing_types=["4", "4/A"], days_back=days)
        trades = []

        for filing in filings:
            try:
                trade_data = self._parse_form4(filing)
                if trade_data:
                    trades.extend(trade_data)
            except Exception as e:
                logger.warning(f"Error parsing Form 4 for {ticker}: {e}")
                continue

        # Filter to significant trades (>$100K to avoid noise from routine exercises)
        significant_trades = [t for t in trades if abs(t.get('value', 0)) >= 100000]

        logger.info(f"{ticker}: Found {len(significant_trades)} significant insider trades (of {len(trades)} total)")
        return significant_trades

    def _parse_form4(self, filing: dict) -> list[dict]:
        """Parse a Form 4 XML filing to extract transaction details."""
        ticker = filing.get('ticker', '')
        cik = filing.get('cik', '').lstrip('0')
        accession = filing.get('accession_number', '').replace('-', '')

        # Form 4 XML files can have various names - get from index.json
        xml_text = None

        # Get the filing index to find the actual XML filename
        index_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/index.json"
        index_data = self.edgar._get(index_url)

        if index_data:
            files = index_data.get('directory', {}).get('item', [])
            for item in files:
                name = item.get('name', '')
                # Look for Form 4 XML files (not the xsl transformed ones)
                if name.endswith('.xml') and 'form4' in name.lower():
                    xml_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{name}"
                    xml_text = self.edgar._get_text(xml_url)
                    if xml_text and '<?xml' in xml_text[:100]:
                        break

        # Fallback: try common patterns
        if not xml_text:
            primary_doc = filing.get('primary_document', '')
            # Remove xslF345X05/ prefix if present
            if 'xslF345X05/' in primary_doc:
                primary_doc = primary_doc.replace('xslF345X05/', '')
            if primary_doc and primary_doc.endswith('.xml'):
                xml_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{primary_doc}"
                xml_text = self.edgar._get_text(xml_url)

        if not xml_text:
            return []

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return []

        # Extract reporting owner info
        owner_elem = root.find('.//reportingOwner')
        if owner_elem is None:
            return []

        owner_name_elem = owner_elem.find('.//rptOwnerName')
        owner_name = owner_name_elem.text if owner_name_elem is not None else 'Unknown'

        # Get title/relationship
        relationship = owner_elem.find('.//reportingOwnerRelationship')
        title = 'Unknown'
        if relationship is not None:
            if relationship.find('.//isOfficer') is not None and relationship.find('.//isOfficer').text == '1':
                title_elem = relationship.find('.//officerTitle')
                title = title_elem.text if title_elem is not None else 'Officer'
            elif relationship.find('.//isDirector') is not None and relationship.find('.//isDirector').text == '1':
                title = 'Director'
            elif relationship.find('.//isTenPercentOwner') is not None and relationship.find('.//isTenPercentOwner').text == '1':
                title = '10% Owner'

        trades = []

        # Parse non-derivative transactions (common stock)
        for txn in root.findall('.//nonDerivativeTransaction'):
            trade = self._parse_transaction(txn, owner_name, title, ticker, filing)
            if trade:
                trades.append(trade)

        # Parse derivative transactions (options, etc.)
        for txn in root.findall('.//derivativeTransaction'):
            trade = self._parse_transaction(txn, owner_name, title, ticker, filing, is_derivative=True)
            if trade:
                trades.append(trade)

        return trades

    def _parse_transaction(self, txn_elem, owner_name: str, title: str, ticker: str,
                          filing: dict, is_derivative: bool = False) -> Optional[dict]:
        """Parse a single transaction element from Form 4 XML."""
        # Get transaction code
        code_elem = txn_elem.find('.//transactionCoding/transactionCode')
        if code_elem is None:
            return None

        txn_code = code_elem.text

        # Map transaction codes to types
        # P = Purchase, S = Sale, A = Award, M = Exercise, G = Gift, etc.
        code_map = {
            'P': 'BUY',
            'S': 'SELL',
            'A': 'AWARD',
            'M': 'EXERCISE',
            'F': 'TAX_WITHHOLD',  # Payment of exercise price or tax
            'G': 'GIFT',
            'D': 'DISPOSITION',
            'C': 'CONVERSION',
        }

        transaction_type = code_map.get(txn_code, 'OTHER')

        # Skip gifts and tax withholding - not investment signals
        if transaction_type in ('GIFT', 'TAX_WITHHOLD', 'OTHER'):
            return None

        # Get shares
        shares_elem = txn_elem.find('.//transactionAmounts/transactionShares/value')
        shares = float(shares_elem.text) if shares_elem is not None and shares_elem.text else 0

        # Get price per share
        price_elem = txn_elem.find('.//transactionAmounts/transactionPricePerShare/value')
        price = float(price_elem.text) if price_elem is not None and price_elem.text else 0

        # Get acquisition/disposition flag
        ad_elem = txn_elem.find('.//transactionAmounts/transactionAcquiredDisposedCode/value')
        acquired = ad_elem.text == 'A' if ad_elem is not None else True

        # Adjust transaction type based on A/D code
        if transaction_type == 'EXERCISE':
            # Option exercises that result in acquisition are treated as buys
            if acquired:
                transaction_type = 'EXERCISE_BUY'
            else:
                transaction_type = 'EXERCISE_SELL'

        # Calculate value
        value = shares * price

        # Make value negative for dispositions
        if not acquired:
            value = -abs(value)
            shares = -abs(shares)

        # Get transaction date
        txn_date_elem = txn_elem.find('.//transactionDate/value')
        txn_date = txn_date_elem.text if txn_date_elem is not None else filing.get('filing_date', '')

        return {
            'ticker': ticker,
            'insider_name': owner_name,
            'title': title,
            'transaction_type': transaction_type,
            'shares': int(shares),
            'price': round(price, 2),
            'value': round(value, 2),
            'transaction_date': txn_date,
            'filing_date': filing.get('filing_date', ''),
            'form_type': '4' if not is_derivative else '4-DERIV',
            'accession_number': filing.get('accession_number', ''),
        }

    def get_notable_trades(self, min_value: float = 500000, days: int = 14) -> list[dict]:
        """
        Scan all universe tickers for insider trades above threshold.
        Returns sorted by value descending.
        """
        all_trades = []

        for ticker in UNIVERSE.keys():
            try:
                trades = self.get_recent_insider_trades(ticker, days=days)
                notable = [t for t in trades if abs(t.get('value', 0)) >= min_value]
                all_trades.extend(notable)
            except Exception as e:
                logger.warning(f"Error scanning insider trades for {ticker}: {e}")
                continue

        # Sort by absolute value descending
        all_trades.sort(key=lambda x: abs(x.get('value', 0)), reverse=True)

        logger.info(f"Notable insider trades scan: {len(all_trades)} trades >= ${min_value:,.0f}")
        return all_trades

    def get_insider_sentiment(self, ticker: str, days: int = 90) -> dict:
        """
        Aggregate insider activity into a sentiment signal.
        Returns: {buy_count, sell_count, net_shares, net_value, sentiment}
        """
        trades = self.get_recent_insider_trades(ticker, days=days)

        buys = [t for t in trades if t.get('transaction_type') in ('BUY', 'EXERCISE_BUY')]
        sells = [t for t in trades if t.get('transaction_type') in ('SELL', 'EXERCISE_SELL')]

        buy_count = len(buys)
        sell_count = len(sells)
        buy_value = sum(t.get('value', 0) for t in buys)
        sell_value = sum(abs(t.get('value', 0)) for t in sells)
        net_value = buy_value - sell_value

        # Determine sentiment
        if buy_count > 0 and sell_count == 0:
            sentiment = 'STRONG_BUY'
        elif buy_value > sell_value * 2:
            sentiment = 'BULLISH'
        elif sell_value > buy_value * 2:
            sentiment = 'BEARISH'
        elif sell_count > 0 and buy_count == 0:
            sentiment = 'STRONG_SELL'
        else:
            sentiment = 'NEUTRAL'

        return {
            'ticker': ticker,
            'days': days,
            'buy_count': buy_count,
            'sell_count': sell_count,
            'buy_value': buy_value,
            'sell_value': sell_value,
            'net_value': net_value,
            'sentiment': sentiment,
            'trades': trades,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')

    client = InsiderClient()

    print("\n=== NVDA Insider Trades (last 60 days) ===")
    trades = client.get_recent_insider_trades("NVDA", days=60)
    for t in trades[:10]:
        print(f"  {t['filing_date']} | {t['insider_name'][:30]:30} | {t['title']:15} | "
              f"{t['transaction_type']:8} | {t['shares']:>10,} shares | ${t['value']:>15,.0f}")

    print("\n=== NVDA Insider Sentiment ===")
    sentiment = client.get_insider_sentiment("NVDA", days=90)
    print(f"  Buys: {sentiment['buy_count']} (${sentiment['buy_value']:,.0f})")
    print(f"  Sells: {sentiment['sell_count']} (${sentiment['sell_value']:,.0f})")
    print(f"  Net: ${sentiment['net_value']:,.0f}")
    print(f"  Sentiment: {sentiment['sentiment']}")

    print("\n=== Notable Trades Across Universe (>$500K, last 14 days) ===")
    notable = client.get_notable_trades(min_value=500000, days=14)
    for t in notable[:15]:
        print(f"  {t['ticker']:5} | {t['filing_date']} | {t['insider_name'][:25]:25} | "
              f"{t['transaction_type']:8} | ${t['value']:>12,.0f}")
