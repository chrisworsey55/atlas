"""
Build the complete US stock universe for ATLAS fundamental screening.

Sources:
1. NASDAQ trader FTP (all listed stocks)
2. NYSE listed companies
3. Filter: market cap > $500M, US-domiciled, trading

Output: data/state/us_universe.json
"""
import json
import time
import pandas as pd
import requests
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import yfinance as yf

# Output paths
STATE_DIR = Path(__file__).resolve().parent.parent / "data" / "state"
OUTPUT_FILE = STATE_DIR / "us_universe.json"


def get_nasdaq_listed():
    """Get all NASDAQ listed companies from NASDAQ trader FTP."""
    print("Fetching NASDAQ listed companies...")
    url = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
    try:
        df = pd.read_csv(url, sep="|")
        # Remove test issues and last row (file creation time)
        df = df[df['Test Issue'] == 'N']
        df = df[:-1]  # Last row is metadata
        tickers = df['Symbol'].tolist()
        print(f"  Found {len(tickers)} NASDAQ tickers")
        return tickers
    except Exception as e:
        print(f"  Error fetching NASDAQ list: {e}")
        return []


def get_nyse_listed():
    """Get all NYSE listed companies from NASDAQ trader FTP."""
    print("Fetching NYSE/other listed companies...")
    url = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
    try:
        df = pd.read_csv(url, sep="|")
        # Remove test issues and last row
        df = df[df['Test Issue'] == 'N']
        df = df[:-1]
        tickers = df['ACT Symbol'].tolist()
        print(f"  Found {len(tickers)} NYSE/other tickers")
        return tickers
    except Exception as e:
        print(f"  Error fetching NYSE list: {e}")
        return []


def get_sp500_tickers():
    """Get S&P 500 tickers from Wikipedia."""
    print("Fetching S&P 500 tickers...")
    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        tables = pd.read_html(url)
        df = tables[0]
        tickers = df['Symbol'].tolist()
        # Fix BRK.B -> BRK-B format
        tickers = [t.replace('.', '-') for t in tickers]
        print(f"  Found {len(tickers)} S&P 500 tickers")
        return tickers
    except Exception as e:
        print(f"  Error fetching S&P 500 list: {e}")
        return []


def clean_ticker(ticker):
    """Clean ticker symbol for yfinance compatibility."""
    # Remove special characters that yfinance doesn't like
    ticker = str(ticker).strip().upper()
    # Skip warrants, units, preferred shares
    if any(x in ticker for x in ['$', '^', '+', '/', ' ']):
        return None
    if len(ticker) > 5:  # Usually special instruments
        return None
    return ticker


def get_stock_info_batch(tickers, batch_size=50):
    """Get stock info for a batch of tickers using yfinance."""
    results = []
    failed = []

    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i+batch_size]
        print(f"  Processing batch {i//batch_size + 1}/{(len(tickers)-1)//batch_size + 1} ({len(batch)} tickers)...")

        # Join tickers for batch request
        ticker_str = " ".join(batch)

        try:
            data = yf.download(ticker_str, period="1d", progress=False, threads=True)

            for ticker in batch:
                try:
                    stock = yf.Ticker(ticker)
                    info = stock.info or {}

                    market_cap = info.get('marketCap', 0) or 0

                    # Filter: market cap > $500M
                    if market_cap < 500_000_000:
                        continue

                    # Filter: US-listed (check exchange or country)
                    country = info.get('country', '')
                    exchange = info.get('exchange', '')

                    # Skip non-US companies and ADRs
                    if country and country not in ['United States', 'USA', '']:
                        if 'ADR' not in info.get('quoteType', ''):
                            continue

                    results.append({
                        'ticker': ticker,
                        'name': info.get('longName') or info.get('shortName') or ticker,
                        'sector': info.get('sector', 'Unknown'),
                        'industry': info.get('industry', 'Unknown'),
                        'market_cap': market_cap,
                        'market_cap_str': f"${market_cap/1e9:.1f}B" if market_cap >= 1e9 else f"${market_cap/1e6:.0f}M",
                        'exchange': exchange,
                        'current_price': info.get('currentPrice') or info.get('regularMarketPrice', 0),
                    })

                except Exception as e:
                    failed.append(ticker)

        except Exception as e:
            print(f"    Batch error: {e}")
            failed.extend(batch)

        # Rate limit
        time.sleep(1)

    return results, failed


def get_stock_info_parallel(tickers, max_workers=10):
    """Get stock info with parallel processing."""
    results = []
    failed = []
    total = len(tickers)
    processed = 0

    def fetch_single(ticker):
        try:
            stock = yf.Ticker(ticker)
            info = stock.info or {}

            market_cap = info.get('marketCap', 0) or 0

            # Filter: market cap > $500M
            if market_cap < 500_000_000:
                return None

            # Basic US filter
            country = info.get('country', '')
            if country and country not in ['United States', 'USA', '']:
                return None

            return {
                'ticker': ticker,
                'name': info.get('longName') or info.get('shortName') or ticker,
                'sector': info.get('sector', 'Unknown'),
                'industry': info.get('industry', 'Unknown'),
                'market_cap': market_cap,
                'market_cap_str': f"${market_cap/1e9:.1f}B" if market_cap >= 1e9 else f"${market_cap/1e6:.0f}M",
                'exchange': info.get('exchange', 'Unknown'),
                'current_price': info.get('currentPrice') or info.get('regularMarketPrice', 0),
            }
        except Exception:
            return None

    print(f"Processing {total} tickers with {max_workers} workers...")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_single, t): t for t in tickers}

        for future in as_completed(futures):
            ticker = futures[future]
            processed += 1

            if processed % 100 == 0:
                print(f"  Progress: {processed}/{total} ({processed*100/total:.1f}%) - {len(results)} valid")

            try:
                result = future.result()
                if result:
                    results.append(result)
            except Exception:
                failed.append(ticker)

    return results, failed


def build_universe():
    """Build the complete US stock universe."""
    print("=" * 60)
    print("ATLAS Universe Builder")
    print("=" * 60)
    print()

    # Get all tickers from multiple sources
    all_tickers = set()

    # NASDAQ listed
    nasdaq_tickers = get_nasdaq_listed()
    all_tickers.update(nasdaq_tickers)

    # NYSE and other exchanges
    nyse_tickers = get_nyse_listed()
    all_tickers.update(nyse_tickers)

    # S&P 500 (ensure coverage)
    sp500_tickers = get_sp500_tickers()
    all_tickers.update(sp500_tickers)

    # Clean tickers
    print(f"\nCleaning {len(all_tickers)} raw tickers...")
    cleaned_tickers = []
    for t in all_tickers:
        cleaned = clean_ticker(t)
        if cleaned:
            cleaned_tickers.append(cleaned)

    print(f"  {len(cleaned_tickers)} tickers after cleaning")

    # Remove duplicates and sort
    cleaned_tickers = sorted(set(cleaned_tickers))
    print(f"  {len(cleaned_tickers)} unique tickers")

    # Get detailed info with market cap filter
    print(f"\nFetching market data (filtering for market cap > $500M)...")
    universe, failed = get_stock_info_parallel(cleaned_tickers, max_workers=20)

    # Sort by market cap
    universe.sort(key=lambda x: x['market_cap'], reverse=True)

    # Add rank
    for i, stock in enumerate(universe):
        stock['rank'] = i + 1

    # Summary by sector
    sector_counts = {}
    for stock in universe:
        sector = stock['sector']
        sector_counts[sector] = sector_counts.get(sector, 0) + 1

    # Save results
    output = {
        'generated_at': datetime.now().isoformat(),
        'total_stocks': len(universe),
        'min_market_cap': '$500M',
        'sector_breakdown': sector_counts,
        'stocks': universe,
    }

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(output, f, indent=2)

    print()
    print("=" * 60)
    print("UNIVERSE BUILD COMPLETE")
    print("=" * 60)
    print(f"Total stocks: {len(universe)}")
    print(f"Failed lookups: {len(failed)}")
    print(f"\nSector breakdown:")
    for sector, count in sorted(sector_counts.items(), key=lambda x: -x[1])[:10]:
        print(f"  {sector}: {count}")
    print(f"\nSaved to: {OUTPUT_FILE}")

    # Also save just the ticker list for quick reference
    ticker_list_file = STATE_DIR / "us_tickers.txt"
    with open(ticker_list_file, 'w') as f:
        for stock in universe:
            f.write(f"{stock['ticker']}\n")
    print(f"Ticker list: {ticker_list_file}")

    return universe


if __name__ == "__main__":
    build_universe()
