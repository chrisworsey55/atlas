"""
Build the complete US stock universe using NASDAQ screener API.
Much faster and more reliable than parallel yfinance lookups.
"""
import json
import requests
import time
from pathlib import Path
from datetime import datetime

# Output paths
STATE_DIR = Path(__file__).resolve().parent.parent / "data" / "state"
OUTPUT_FILE = STATE_DIR / "us_universe.json"


def fetch_nasdaq_screener():
    """
    Fetch stock data from NASDAQ screener API.
    This is the same data source as nasdaq.com/market-activity/stocks/screener
    """
    print("Fetching NASDAQ screener data...")

    # NASDAQ screener API endpoint
    url = "https://api.nasdaq.com/api/screener/stocks"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }

    params = {
        "tableonly": "true",
        "limit": 10000,  # Get all
        "offset": 0,
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=60)
        response.raise_for_status()
        data = response.json()

        if "data" in data and "table" in data["data"]:
            rows = data["data"]["table"]["rows"]
            print(f"  Found {len(rows)} total stocks")
            return rows
        else:
            print(f"  Unexpected response structure")
            return []

    except Exception as e:
        print(f"  Error: {e}")
        return []


def parse_market_cap(cap_str):
    """Parse market cap string like '$1.5B' or '$500M' to number."""
    if not cap_str or cap_str == "N/A":
        return 0

    cap_str = cap_str.strip().replace("$", "").replace(",", "")

    multiplier = 1
    if cap_str.endswith("T"):
        multiplier = 1e12
        cap_str = cap_str[:-1]
    elif cap_str.endswith("B"):
        multiplier = 1e9
        cap_str = cap_str[:-1]
    elif cap_str.endswith("M"):
        multiplier = 1e6
        cap_str = cap_str[:-1]
    elif cap_str.endswith("K"):
        multiplier = 1e3
        cap_str = cap_str[:-1]

    try:
        return float(cap_str) * multiplier
    except:
        return 0


def build_universe():
    """Build the complete US stock universe."""
    print("=" * 60)
    print("ATLAS Universe Builder v2 (NASDAQ API)")
    print("=" * 60)
    print()

    # Fetch from NASDAQ
    stocks_raw = fetch_nasdaq_screener()

    if not stocks_raw:
        print("Failed to fetch data from NASDAQ. Using fallback method...")
        return None

    # Filter and parse
    print(f"\nFiltering stocks (market cap > $500M, US-listed)...")

    stocks = []
    for row in stocks_raw:
        try:
            ticker = row.get("symbol", "")
            name = row.get("name", "")
            market_cap = parse_market_cap(row.get("marketCap", ""))
            sector = row.get("sector", "Unknown") or "Unknown"
            industry = row.get("industry", "Unknown") or "Unknown"
            country = row.get("country", "")

            # Skip if no ticker
            if not ticker:
                continue

            # Skip non-US companies
            if country and country not in ["United States", ""]:
                continue

            # Skip special characters (warrants, units)
            if any(c in ticker for c in ["^", "$", "+", "/"]):
                continue

            # Filter by market cap > $500M
            if market_cap < 500_000_000:
                continue

            # Get current price
            price_str = row.get("lastsale", "").replace("$", "")
            try:
                price = float(price_str) if price_str else 0
            except:
                price = 0

            stocks.append({
                "ticker": ticker,
                "name": name,
                "sector": sector,
                "industry": industry,
                "market_cap": market_cap,
                "market_cap_str": f"${market_cap/1e9:.1f}B" if market_cap >= 1e9 else f"${market_cap/1e6:.0f}M",
                "current_price": price,
                "exchange": "NASDAQ" if "nasdaq" in str(row.get("exchange", "")).lower() else "NYSE",
            })

        except Exception as e:
            continue

    # Sort by market cap
    stocks.sort(key=lambda x: x["market_cap"], reverse=True)

    # Add rank
    for i, stock in enumerate(stocks):
        stock["rank"] = i + 1

    # Sector breakdown
    sector_counts = {}
    for stock in stocks:
        sector = stock["sector"]
        sector_counts[sector] = sector_counts.get(sector, 0) + 1

    # Save
    output = {
        "generated_at": datetime.now().isoformat(),
        "total_stocks": len(stocks),
        "min_market_cap": "$500M",
        "sector_breakdown": sector_counts,
        "stocks": stocks,
    }

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    # Also save ticker list
    ticker_file = STATE_DIR / "us_tickers.txt"
    with open(ticker_file, "w") as f:
        for stock in stocks:
            f.write(f"{stock['ticker']}\n")

    print()
    print("=" * 60)
    print("UNIVERSE BUILD COMPLETE")
    print("=" * 60)
    print(f"Total stocks: {len(stocks)}")
    print(f"\nSector breakdown:")
    for sector, count in sorted(sector_counts.items(), key=lambda x: -x[1])[:12]:
        print(f"  {sector}: {count}")
    print(f"\nTop 10 by market cap:")
    for s in stocks[:10]:
        print(f"  {s['ticker']}: {s['market_cap_str']} - {s['name'][:40]}")
    print(f"\nSaved to: {OUTPUT_FILE}")
    print(f"Ticker list: {ticker_file}")

    return stocks


if __name__ == "__main__":
    build_universe()
