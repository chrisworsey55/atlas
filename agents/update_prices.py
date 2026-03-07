#!/usr/bin/env python3
"""
Update all position prices and display current P&L.
Skill: /pnl
"""
import json
import yfinance as yf
from pathlib import Path
from datetime import datetime

STATE_DIR = Path(__file__).parent.parent / "data" / "state"


def update_prices():
    """Update all position prices from yfinance and display P&L summary."""
    positions_file = STATE_DIR / "positions.json"

    with open(positions_file) as f:
        data = json.load(f)

    # Handle both flat dict and nested positions array formats
    if isinstance(data, dict) and 'positions' in data:
        positions = data['positions']
        is_nested = True
    else:
        positions = data if isinstance(data, list) else list(data.values())
        is_nested = False

    # Get tickers to update (exclude BIL which is stable)
    tickers = [p['ticker'] for p in positions if p['ticker'] != 'BIL']

    if not tickers:
        print("No positions to update")
        return

    # Fetch latest prices
    print(f"Fetching prices for {len(tickers)} tickers...")
    try:
        prices_data = yf.download(tickers, period='1d', progress=False)
    except Exception as e:
        print(f"Error fetching prices: {e}")
        return

    # Extract closing prices
    current_prices = {}
    for ticker in tickers:
        try:
            if len(tickers) == 1:
                price = float(prices_data['Close'].iloc[-1])
            else:
                price = float(prices_data['Close'][ticker].iloc[-1])
            current_prices[ticker] = round(price, 2)
        except Exception:
            pass  # Keep existing price

    total_pnl = 0
    total_value = 0

    print(f"\n{'='*90}")
    print(f"ATLAS PORTFOLIO — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*90}")
    print(f"{'Ticker':<8} {'Dir':<6} {'Shares':>8} {'Entry':>10} {'Current':>10} {'Value':>12} {'P&L':>12} {'P&L%':>8}")
    print(f"{'-'*90}")

    for pos in positions:
        ticker = pos['ticker']
        entry = pos.get('entry_price', 0)
        shares = pos.get('shares', 0)
        direction = pos.get('direction', 'LONG')

        # Update price if we have a new one
        if ticker in current_prices:
            pos['current_price'] = current_prices[ticker]

        price = pos.get('current_price', entry)
        value = price * shares

        # Calculate P&L based on direction
        if direction == 'SHORT':
            pnl = (entry - price) * shares
        else:
            pnl = (price - entry) * shares

        pos['unrealized_pnl'] = round(pnl, 2)
        pnl_pct = (pnl / (entry * shares) * 100) if entry * shares > 0 else 0

        total_pnl += pnl
        total_value += value

        # Color coding
        color = '\033[92m' if pnl >= 0 else '\033[91m'  # Green/Red
        reset = '\033[0m'

        print(f"{ticker:<8} {direction:<6} {shares:>8,} ${entry:>9.2f} ${price:>9.2f} ${value:>11,.0f} {color}${pnl:>11,.0f}{reset} {color}{pnl_pct:>7.2f}%{reset}")

    print(f"{'-'*90}")

    # Total row
    color = '\033[92m' if total_pnl >= 0 else '\033[91m'
    reset = '\033[0m'
    starting_value = data.get('portfolio_value', 1000000) if is_nested else 1000000
    total_pnl_pct = (total_pnl / starting_value) * 100

    print(f"{'TOTAL':<8} {'':6} {'':>8} {'':>10} {'':>10} ${total_value:>11,.0f} {color}${total_pnl:>11,.0f}{reset} {color}{total_pnl_pct:>7.2f}%{reset}")
    print(f"\nPortfolio Value: ${total_value:,.0f}")
    print(f"Starting Value:  $1,000,000")
    print(f"Total Return:    {color}{'+' if total_pnl >= 0 else ''}${total_pnl:,.0f} ({total_pnl_pct:+.2f}%){reset}")

    # Update the data structure
    if is_nested:
        data['positions'] = positions
        data['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M')

    # Save updated prices
    with open(positions_file, 'w') as f:
        json.dump(data, f, indent=2)

    print(f"\nPrices saved to {positions_file}")

    # Also update pnl_history
    pnl_history_file = STATE_DIR / "pnl_history.json"
    try:
        with open(pnl_history_file) as f:
            pnl_history = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pnl_history = []

    # Add snapshot
    pnl_history.append({
        "date": datetime.now().isoformat(),
        "portfolio_value": round(total_value, 2),
        "total_pnl": round(total_pnl, 2),
        "pnl_pct": round(total_pnl_pct, 2)
    })

    # Keep last 500 snapshots
    pnl_history = pnl_history[-500:]

    with open(pnl_history_file, 'w') as f:
        json.dump(pnl_history, f, indent=2)


if __name__ == '__main__':
    update_prices()
