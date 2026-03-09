#!/usr/bin/env python3
"""
ATLAS Market Data Module — Three-Source Validation
Fetches prices from FMP, Finnhub, and Polygon.io for cross-validation.

Priority: Finnhub (real-time) > FMP (real-time) > Polygon (end-of-day tiebreaker)

Rules:
- FMP + Finnhub agree within 3% → "verified", use FMP price
- FMP + Finnhub disagree → fetch Polygon prev close as tiebreaker → use whichever is closest to Polygon
- Any source returns $0 or null → ignore it, use the others
- All three disagree → flag "unverified", log all three prices, use Finnhub
- DON'T use Polygon for batch quotes (5/min rate limit) — only for tiebreaker
- Data quality flags: "verified", "tiebreaker", "unverified", "conflict", "single_source"
- NEVER use yfinance
"""
import os
import json
import time
import requests
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

FMP_API_KEY = os.getenv("FMP_API_KEY")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY")
STATE_DIR = Path(__file__).parent.parent / "data" / "state"

FMP_BASE = "https://financialmodelingprep.com/stable"
FINNHUB_BASE = "https://finnhub.io/api/v1"
POLYGON_BASE = "https://api.polygon.io"

# Conflict threshold (3%)
CONFLICT_THRESHOLD = 0.03


def _fmp_quote(symbol: str) -> dict:
    """Get quote from FMP stable API."""
    if not FMP_API_KEY:
        return {}

    url = f"{FMP_BASE}/quote?symbol={symbol}&apikey={FMP_API_KEY}"
    try:
        r = requests.get(url, timeout=10)
        if r.ok:
            data = r.json()
            if isinstance(data, list) and len(data) > 0:
                return {
                    "price": data[0].get("price", 0),
                    "change": data[0].get("change", 0),
                    "change_pct": data[0].get("changesPercentage", 0),
                    "name": data[0].get("name", ""),
                    "source": "fmp"
                }
        return {}
    except Exception as e:
        print(f"[FMP] Error fetching {symbol}: {e}")
        return {}


def _finnhub_quote(symbol: str) -> dict:
    """Get quote from Finnhub API."""
    if not FINNHUB_API_KEY:
        return {}

    url = f"{FINNHUB_BASE}/quote?symbol={symbol}&token={FINNHUB_API_KEY}"
    try:
        r = requests.get(url, timeout=10)
        if r.ok:
            data = r.json()
            # Finnhub returns: c=current, d=change, dp=change%, pc=prev close, o=open, h=high, l=low
            if data.get("c", 0) > 0:
                return {
                    "price": data.get("c", 0),
                    "change": data.get("d", 0),
                    "change_pct": data.get("dp", 0),
                    "prev_close": data.get("pc", 0),
                    "source": "finnhub"
                }
        return {}
    except Exception as e:
        print(f"[Finnhub] Error fetching {symbol}: {e}")
        return {}


def _polygon_prev_close(symbol: str) -> dict:
    """
    Get previous close from Polygon.io (Massive) API.
    Rate limit: 5 req/min — use ONLY as tiebreaker, not for batch quotes.
    """
    if not POLYGON_API_KEY:
        return {}

    url = f"{POLYGON_BASE}/v2/aggs/ticker/{symbol}/prev?apiKey={POLYGON_API_KEY}"
    try:
        r = requests.get(url, timeout=10)
        if r.ok:
            data = r.json()
            results = data.get("results", [])
            if results and len(results) > 0:
                bar = results[0]
                return {
                    "prev_close": bar.get("c", 0),  # close price
                    "open": bar.get("o", 0),
                    "high": bar.get("h", 0),
                    "low": bar.get("l", 0),
                    "volume": bar.get("v", 0),
                    "source": "polygon"
                }
        return {}
    except Exception as e:
        print(f"[Polygon] Error fetching {symbol}: {e}")
        return {}


def get_validated_quote(symbol: str) -> dict:
    """
    Get quote with three-source validation.

    Logic:
    - FMP + Finnhub agree within 3% → "verified", use FMP price
    - FMP + Finnhub disagree → fetch Polygon prev close as tiebreaker → use whichever is closest to Polygon
    - Any source returns $0 or null → ignore it, use the others
    - All three disagree → flag "unverified", log all three prices, use Finnhub

    Returns price, change, data_quality flag, and source used.
    """
    fmp = _fmp_quote(symbol)
    time.sleep(0.1)  # Rate limit between sources
    finnhub = _finnhub_quote(symbol)

    fmp_price = fmp.get("price", 0) or 0
    finnhub_price = finnhub.get("price", 0) or 0

    # Handle null/zero prices
    if fmp_price <= 0 and finnhub_price <= 0:
        # No data from either real-time source
        return {
            "ticker": symbol,
            "price": 0,
            "change": 0,
            "change_pct": 0,
            "data_quality": "no_data",
            "source": None,
            "fmp_price": None,
            "finnhub_price": None,
            "polygon_price": None
        }

    if fmp_price <= 0:
        # Only Finnhub available
        return {
            "ticker": symbol,
            "price": finnhub_price,
            "change": finnhub.get("change", 0),
            "change_pct": finnhub.get("change_pct", 0),
            "data_quality": "single_source",
            "source": "finnhub",
            "fmp_price": None,
            "finnhub_price": finnhub_price,
            "polygon_price": None
        }

    if finnhub_price <= 0:
        # Only FMP available
        return {
            "ticker": symbol,
            "price": fmp_price,
            "change": fmp.get("change", 0),
            "change_pct": fmp.get("change_pct", 0),
            "data_quality": "single_source",
            "source": "fmp",
            "fmp_price": fmp_price,
            "finnhub_price": None,
            "polygon_price": None
        }

    # Both sources available - check for conflict
    diff_pct = abs(fmp_price - finnhub_price) / max(fmp_price, finnhub_price)

    if diff_pct <= CONFLICT_THRESHOLD:
        # Verified - FMP and Finnhub agree within 3%, use FMP price
        return {
            "ticker": symbol,
            "price": fmp_price,
            "change": fmp.get("change", 0),
            "change_pct": fmp.get("change_pct", 0),
            "data_quality": "verified",
            "source": "fmp",
            "fmp_price": fmp_price,
            "finnhub_price": finnhub_price,
            "polygon_price": None,
            "diff_pct": round(diff_pct * 100, 2)
        }

    # Conflict detected - fetch Polygon as tiebreaker
    print(f"[CONFLICT] {symbol}: FMP=${fmp_price:.2f} vs Finnhub=${finnhub_price:.2f} (diff={diff_pct*100:.1f}%) → Fetching Polygon tiebreaker")
    time.sleep(0.2)  # Rate limit for Polygon (5/min)
    polygon = _polygon_prev_close(symbol)
    polygon_price = polygon.get("prev_close", 0) or 0

    if polygon_price <= 0:
        # Polygon unavailable - use Finnhub as fallback
        print(f"[CONFLICT] {symbol}: Polygon unavailable → Using Finnhub")
        return {
            "ticker": symbol,
            "price": finnhub_price,
            "change": finnhub.get("change", 0),
            "change_pct": finnhub.get("change_pct", 0),
            "data_quality": "conflict",
            "source": "finnhub",
            "fmp_price": fmp_price,
            "finnhub_price": finnhub_price,
            "polygon_price": None,
            "diff_pct": round(diff_pct * 100, 2)
        }

    # Use Polygon as tiebreaker - pick whichever is closest
    fmp_diff = abs(fmp_price - polygon_price)
    finnhub_diff = abs(finnhub_price - polygon_price)

    # Check if all three disagree significantly
    fmp_polygon_pct = fmp_diff / polygon_price if polygon_price > 0 else 1
    finnhub_polygon_pct = finnhub_diff / polygon_price if polygon_price > 0 else 1

    if fmp_polygon_pct > CONFLICT_THRESHOLD and finnhub_polygon_pct > CONFLICT_THRESHOLD:
        # All three sources disagree significantly - flag as unverified, use Finnhub
        print(f"[UNVERIFIED] {symbol}: All three disagree → FMP=${fmp_price:.2f}, Finnhub=${finnhub_price:.2f}, Polygon=${polygon_price:.2f} → Using Finnhub")
        return {
            "ticker": symbol,
            "price": finnhub_price,
            "change": finnhub.get("change", 0),
            "change_pct": finnhub.get("change_pct", 0),
            "data_quality": "unverified",
            "source": "finnhub",
            "fmp_price": fmp_price,
            "finnhub_price": finnhub_price,
            "polygon_price": polygon_price,
            "diff_pct": round(diff_pct * 100, 2)
        }

    # Polygon successfully resolved the tiebreaker
    if fmp_diff <= finnhub_diff:
        # FMP closer to Polygon
        print(f"[TIEBREAKER] {symbol}: FMP=${fmp_price:.2f} closer to Polygon=${polygon_price:.2f} than Finnhub=${finnhub_price:.2f}")
        return {
            "ticker": symbol,
            "price": fmp_price,
            "change": fmp.get("change", 0),
            "change_pct": fmp.get("change_pct", 0),
            "data_quality": "tiebreaker",
            "source": "fmp",
            "fmp_price": fmp_price,
            "finnhub_price": finnhub_price,
            "polygon_price": polygon_price,
            "diff_pct": round(diff_pct * 100, 2)
        }
    else:
        # Finnhub closer to Polygon
        print(f"[TIEBREAKER] {symbol}: Finnhub=${finnhub_price:.2f} closer to Polygon=${polygon_price:.2f} than FMP=${fmp_price:.2f}")
        return {
            "ticker": symbol,
            "price": finnhub_price,
            "change": finnhub.get("change", 0),
            "change_pct": finnhub.get("change_pct", 0),
            "data_quality": "tiebreaker",
            "source": "finnhub",
            "fmp_price": fmp_price,
            "finnhub_price": finnhub_price,
            "polygon_price": polygon_price,
            "diff_pct": round(diff_pct * 100, 2)
        }


def get_validated_quotes(symbols: list) -> dict:
    """Get validated quotes for multiple symbols."""
    quotes = {}
    for i, symbol in enumerate(symbols):
        q = get_validated_quote(symbol)
        quotes[symbol] = q
        if i < len(symbols) - 1:
            time.sleep(0.2)  # Rate limit
    return quotes


def get_market_snapshot() -> dict:
    """Get market snapshot with validated prices."""
    print("[market_data] Fetching dual-source validated quotes...")

    # Key indices and benchmarks
    core_tickers = ["SPY", "QQQ", "TLT", "GLD", "XLE", "IWM"]
    quotes = get_validated_quotes(core_tickers)

    spy = quotes.get("SPY", {})

    return {
        "spy": spy,
        "indices": quotes,
        "market_direction": "UP" if spy.get("change_pct", 0) > 0 else "DOWN",
        "market_change_pct": spy.get("change_pct", 0)
    }


def get_portfolio_pnl() -> dict:
    """Calculate P&L for current portfolio positions using validated prices."""
    try:
        with open(STATE_DIR / "positions.json") as f:
            data = json.load(f)
    except:
        return {"error": "Could not load positions.json", "total_pnl": 0, "positions": {}}

    positions = data.get("positions", [])
    tickers = [p["ticker"] for p in positions if p["ticker"] != "BIL"]

    if not tickers:
        return {"total_pnl": 0, "positions": {}}

    quotes = get_validated_quotes(tickers)

    total_pnl = 0
    position_pnl = {}

    for p in positions:
        ticker = p["ticker"]
        if ticker == "BIL":
            continue

        entry = p.get("entry_price", 0)
        q = quotes.get(ticker, {})
        current = q.get("price", 0) if q.get("price", 0) > 0 else p.get("current_price", entry)
        shares = p.get("shares", 0)
        direction = p.get("direction", "LONG")

        if direction == "SHORT":
            pnl = (entry - current) * shares
        else:
            pnl = (current - entry) * shares

        pnl_pct = (pnl / (entry * shares) * 100) if entry * shares > 0 else 0

        position_pnl[ticker] = {
            "entry": entry,
            "current": round(current, 2),
            "shares": shares,
            "direction": direction,
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "data_quality": q.get("data_quality", "unknown"),
            "source": q.get("source", "cached")
        }
        total_pnl += pnl

    return {
        "total_pnl": round(total_pnl, 2),
        "positions": position_pnl
    }


def get_top_undervalued() -> list:
    """Get top undervalued stocks from DCF screen."""
    try:
        with open(STATE_DIR / "sp500_valuations.json") as f:
            valuations = json.load(f)

        undervalued = []
        for v in valuations:
            if v.get('dcf_valuation') and v.get('current_price'):
                dcf = v['dcf_valuation'].get('base_case', 0)
                price = v['current_price']
                if dcf and price and dcf > price:
                    upside = ((dcf - price) / price) * 100
                    undervalued.append({
                        'ticker': v['ticker'],
                        'company': v.get('company_name', ''),
                        'sector': v['sector'],
                        'price': price,
                        'dcf_value': dcf,
                        'upside_pct': round(upside, 1)
                    })

        undervalued.sort(key=lambda x: x['upside_pct'], reverse=True)
        return undervalued[:20]
    except Exception as e:
        print(f"[market_data] Could not load valuations: {e}")
        return []


def get_sector_data() -> dict:
    """Get sector allocation from our DCF screen data."""
    try:
        with open(STATE_DIR / "sp500_valuations.json") as f:
            valuations = json.load(f)

        sectors = {}
        for v in valuations:
            sector = v.get("sector", "Unknown")
            if sector not in sectors:
                sectors[sector] = {"count": 0, "total_upside": 0, "tickers": []}
            sectors[sector]["count"] += 1
            if v.get("dcf_valuation") and v.get("current_price"):
                dcf = v['dcf_valuation'].get('base_case', 0)
                price = v['current_price']
                if dcf and price:
                    upside = ((dcf - price) / price) * 100
                    sectors[sector]["total_upside"] += upside
                    if upside > 20:
                        sectors[sector]["tickers"].append(v["ticker"])

        for sector in sectors:
            if sectors[sector]["count"] > 0:
                sectors[sector]["avg_upside"] = round(sectors[sector]["total_upside"] / sectors[sector]["count"], 1)

        return sectors
    except:
        return {}


def get_full_market_data() -> dict:
    """Get complete market data package for agent analysis."""
    print("[market_data] Building validated market data package...")

    market = get_market_snapshot()
    portfolio = get_portfolio_pnl()
    undervalued = get_top_undervalued()
    sectors = get_sector_data()

    data = {
        "timestamp": datetime.now().isoformat(),
        "market": market,
        "portfolio_pnl": portfolio,
        "top_undervalued": undervalued,
        "sector_opportunities": sectors
    }

    spy = market.get("spy", {})
    print(f"[market_data] SPY=${spy.get('price', 'N/A')} ({spy.get('data_quality', 'unknown')})")
    return data


def format_market_context(data: dict) -> str:
    """Format market data into readable context for agents."""
    lines = [
        f"# MARKET DATA — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        ""
    ]

    # Market snapshot
    market = data.get("market", {})
    spy = market.get("spy", {})
    direction = "UP" if spy.get("change_pct", 0) > 0 else "DOWN"
    quality = spy.get("data_quality", "unknown")
    lines.append(f"## MARKET: {direction} SPY ${spy.get('price', 0):,.2f} ({spy.get('change_pct', 0):+.2f}%) [{quality}]")
    lines.append("")

    # Index prices
    lines.append("## KEY INDICES (dual-source validated)")
    for ticker, vals in market.get("indices", {}).items():
        quality_tag = f"[{vals.get('data_quality', '?')}]"
        lines.append(f"  {ticker}: ${vals.get('price', 0):,.2f} ({vals.get('change_pct', 0):+.2f}%) {quality_tag}")

    # Portfolio P&L
    pnl = data.get("portfolio_pnl", {})
    total = pnl.get("total_pnl", 0)
    emoji = "+" if total > 0 else ""
    lines.append(f"\n## PORTFOLIO P&L: ${emoji}{total:,.2f}")
    for ticker, p in pnl.get("positions", {}).items():
        quality_tag = f"[{p.get('data_quality', '?')}]"
        lines.append(f"  {ticker}: ${p.get('current', 0):.2f} | P&L: ${p.get('pnl', 0):+,.2f} ({p.get('pnl_pct', 0):+.2f}%) {quality_tag}")

    # Sector opportunities
    lines.append("\n## SECTOR OPPORTUNITIES (from DCF screen)")
    sectors = data.get("sector_opportunities", {})
    sorted_sectors = sorted(sectors.items(), key=lambda x: x[1].get("avg_upside", 0), reverse=True)
    for sector, vals in sorted_sectors[:10]:
        avg = vals.get("avg_upside", 0)
        lines.append(f"  {sector}: Avg {avg:+.1f}% upside | Top: {', '.join(vals.get('tickers', [])[:3])}")

    # Top undervalued
    lines.append("\n## TOP 15 UNDERVALUED (DCF Screen)")
    for v in data.get("top_undervalued", [])[:15]:
        lines.append(f"  {v['ticker']} ({v['sector']}): ${v['price']:.2f} -> DCF ${v['dcf_value']:.0f} (+{v['upside_pct']}%)")

    return "\n".join(lines)


def test_triple_source(tickers: list):
    """Test three-source validation with a list of tickers."""
    print("=" * 100)
    print("THREE-SOURCE PRICE VALIDATION TEST (FMP vs Finnhub vs Polygon)")
    print("=" * 100)
    print(f"{'TICKER':<8} {'FMP':>12} {'FINNHUB':>12} {'POLYGON':>12} {'DIFF':>8} {'QUALITY':>12} {'FINAL':>12}")
    print("-" * 100)

    results = {}
    for ticker in tickers:
        q = get_validated_quote(ticker)
        results[ticker] = q

        fmp_str = f"${q.get('fmp_price', 0):.2f}" if q.get('fmp_price') else "N/A"
        finn_str = f"${q.get('finnhub_price', 0):.2f}" if q.get('finnhub_price') else "N/A"
        poly_str = f"${q.get('polygon_price', 0):.2f}" if q.get('polygon_price') else "-"
        diff_str = f"{q.get('diff_pct', 0):.1f}%" if q.get('diff_pct') is not None else "N/A"
        final_str = f"${q.get('price', 0):.2f}"

        print(f"{ticker:<8} {fmp_str:>12} {finn_str:>12} {poly_str:>12} {diff_str:>8} {q.get('data_quality', 'N/A'):>12} {final_str:>12}")

        time.sleep(0.5)  # Rate limit for Polygon

    print("-" * 100)

    # Save results
    with open(STATE_DIR / "live_prices.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults saved to data/state/live_prices.json")
    return results


# Keep old function name for backwards compatibility
test_dual_source = test_triple_source


if __name__ == "__main__":
    # Test with specified tickers
    test_tickers = ["GE", "AVGO", "TSLA", "GOOGL"]
    test_triple_source(test_tickers)
