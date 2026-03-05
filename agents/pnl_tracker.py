"""
ATLAS P&L Tracker
Tracks unrealized P&L for paper portfolio positions with hurdle rate and high water mark.

Usage:
    python3 -m agents.pnl_tracker
"""
import json
from datetime import datetime
from pathlib import Path

import yfinance as yf


# Paths
STATE_DIR = Path(__file__).parent.parent / "data" / "state"
POSITIONS_FILE = STATE_DIR / "positions.json"
PNL_HISTORY_FILE = STATE_DIR / "pnl_history.json"
PORTFOLIO_META_FILE = STATE_DIR / "portfolio_meta.json"


def load_portfolio_meta() -> dict:
    """Load portfolio metadata (inception, HWM, hurdle rate, fees)."""
    if not PORTFOLIO_META_FILE.exists():
        # Default values
        return {
            "inception_date": datetime.now().strftime("%Y-%m-%d"),
            "starting_value": 1_000_000,
            "high_water_mark": 1_000_000,
            "high_water_mark_date": datetime.now().strftime("%Y-%m-%d"),
            "hurdle_rate_annual": 0.045,
            "management_fee_annual": 0.015,
            "performance_fee": 0.20,
        }

    with open(PORTFOLIO_META_FILE, "r") as f:
        return json.load(f)


def save_portfolio_meta(meta: dict) -> None:
    """Save portfolio metadata."""
    with open(PORTFOLIO_META_FILE, "w") as f:
        json.dump(meta, f, indent=2)


def load_positions() -> list:
    """Load open positions from state file."""
    if not POSITIONS_FILE.exists():
        return []

    with open(POSITIONS_FILE, "r") as f:
        positions = json.load(f)

    # Filter to only OPEN positions
    return [p for p in positions if p.get("status") == "OPEN"]


def fetch_current_prices(tickers: list) -> dict:
    """Fetch current prices from yfinance."""
    if not tickers:
        return {}

    prices = {}
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            price = stock.fast_info.get("lastPrice")
            if price is None:
                hist = stock.history(period="1d")
                if not hist.empty:
                    price = hist["Close"].iloc[-1]
            prices[ticker] = price
        except Exception as e:
            print(f"Warning: Could not fetch price for {ticker}: {e}")
            prices[ticker] = None

    return prices


def calculate_pnl(position: dict, current_price: float) -> dict:
    """Calculate P&L for a single position."""
    entry_price = position["entry_price"]
    shares = position["shares"]
    direction = position["direction"]
    pos_type = position.get("type", "ACTIVE_TRADE")

    if direction == "LONG":
        pnl = (current_price - entry_price) * shares
        pnl_pct = ((current_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
        market_value = current_price * shares
    else:  # SHORT
        pnl = (entry_price - current_price) * shares
        pnl_pct = ((entry_price - current_price) / entry_price) * 100 if entry_price > 0 else 0
        market_value = current_price * shares

    return {
        "ticker": position["ticker"],
        "direction": direction,
        "shares": shares,
        "entry_price": entry_price,
        "current_price": current_price,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "market_value": market_value,
        "type": pos_type,
        "entry_value": position.get("value", entry_price * shares),
    }


def load_pnl_history() -> list:
    """Load existing P&L history."""
    if not PNL_HISTORY_FILE.exists():
        return []

    with open(PNL_HISTORY_FILE, "r") as f:
        return json.load(f)


def save_pnl_history(history: list) -> None:
    """Save P&L history to file."""
    with open(PNL_HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2, default=str)


def format_pnl_line(pos: dict) -> str:
    """Format a single position line."""
    ticker = pos["ticker"]
    direction = pos["direction"]
    shares = pos["shares"]
    entry = pos["entry_price"]
    current = pos["current_price"]
    pnl = pos["pnl"]
    pnl_pct = pos["pnl_pct"]

    pnl_sign = "+" if pnl >= 0 else ""
    pnl_pct_sign = "+" if pnl_pct >= 0 else ""

    return (
        f"{ticker:<6} {direction:<5} {shares:>6,} shares  "
        f"Entry: ${entry:>7,.2f}  Now: ${current:>7,.2f}  "
        f"P&L: {pnl_sign}${pnl:>8,.0f}  ({pnl_pct_sign}{pnl_pct:.2f}%)"
    )


def print_portfolio_summary(position_pnls: list, meta: dict) -> dict:
    """Print formatted portfolio summary with sections and return totals."""
    today = datetime.now().strftime("%Y-%m-%d")
    starting_value = meta["starting_value"]

    # Separate positions by type
    active_trades = [p for p in position_pnls if p["type"] == "ACTIVE_TRADE"]
    autonomous = [p for p in position_pnls if p["type"] == "AUTONOMOUS"]
    cash_mgmt = [p for p in position_pnls if p["type"] == "CASH_MANAGEMENT"]

    print(f"\nATLAS Paper Portfolio — {today}")
    print("=" * 70)

    # Active Trades Section
    active_pnl = 0
    active_value = 0
    if active_trades:
        print("\nACTIVE TRADES")
        print("-" * 70)
        for pos in active_trades:
            print(format_pnl_line(pos))
            active_pnl += pos["pnl"]
            active_value += pos["entry_value"]
        print("-" * 70)
        pnl_sign = "+" if active_pnl >= 0 else ""
        print(f"Active Trades P&L: {pnl_sign}${active_pnl:,.0f}")

    # Autonomous Section
    autonomous_pnl = 0
    autonomous_value = 0
    if autonomous:
        print("\nAUTONOMOUS SLEEVE ($50K)")
        print("-" * 70)
        for pos in autonomous:
            print(format_pnl_line(pos))
            autonomous_pnl += pos["pnl"]
            autonomous_value += pos["entry_value"]
        print("-" * 70)
        pnl_sign = "+" if autonomous_pnl >= 0 else ""
        print(f"Autonomous P&L: {pnl_sign}${autonomous_pnl:,.0f}")

    # Cash Management Section
    cash_value = 0
    if cash_mgmt:
        print("\nCASH MANAGEMENT")
        print("-" * 70)
        for pos in cash_mgmt:
            ticker = pos["ticker"]
            shares = pos["shares"]
            entry = pos["entry_price"]
            current = pos["current_price"]
            value = pos["market_value"]
            cash_value += value
            print(
                f"{ticker:<6} LONG  {shares:>6,} shares  "
                f"Entry: ${entry:>7,.2f}  Now: ${current:>7,.2f}  "
                f"Yield: ~4.5%"
            )
        print("-" * 70)
        print(f"Cash Value: ${cash_value:,.0f}")

    # Calculate totals
    total_pnl = active_pnl + autonomous_pnl
    portfolio_value = starting_value + total_pnl

    # Calculate hurdle
    inception_date = datetime.strptime(meta["inception_date"], "%Y-%m-%d")
    days_elapsed = (datetime.now() - inception_date).days
    if days_elapsed < 1:
        days_elapsed = 1  # Minimum 1 day

    hurdle_rate = meta["hurdle_rate_annual"]
    hurdle_return = (hurdle_rate / 365) * starting_value * days_elapsed
    hurdle_return_pct = (hurdle_return / starting_value) * 100
    portfolio_return_pct = (total_pnl / starting_value) * 100
    alpha = total_pnl - hurdle_return
    alpha_pct = portfolio_return_pct - hurdle_return_pct

    # Daily yield from BIL
    daily_yield = (hurdle_rate / 365) * cash_value

    # Portfolio Summary
    print("\nPORTFOLIO SUMMARY")
    print("=" * 70)
    pnl_sign = "+" if total_pnl >= 0 else ""
    pnl_pct_sign = "+" if portfolio_return_pct >= 0 else ""
    print(f"Total Value:     ${portfolio_value:>12,.0f}")
    print(f"Total P&L:       {pnl_sign}${total_pnl:>11,.0f} ({pnl_pct_sign}{portfolio_return_pct:.2f}%)")
    print(f"Active Trades:   ${active_value:>12,.0f} ({active_value/starting_value*100:.0f}%)")
    if autonomous_value > 0:
        print(f"Autonomous:      ${autonomous_value:>12,.0f} ({autonomous_value/starting_value*100:.0f}%)")
    print(f"Cash (BIL):      ${cash_value:>12,.0f} ({cash_value/starting_value*100:.0f}%)")
    print(f"Daily Yield:     ~${daily_yield:>11,.0f}/day from BIL")
    print("=" * 70)

    # Performance vs Hurdle
    print("\nPERFORMANCE vs HURDLE")
    print("=" * 70)
    print(f"Inception Date:     {meta['inception_date']}")
    print(f"Days Elapsed:       {days_elapsed}")
    print(f"Hurdle Rate:        {hurdle_rate*100:.2f}% annualised")
    print("-" * 70)
    pnl_sign = "+" if total_pnl >= 0 else ""
    pnl_pct_sign = "+" if portfolio_return_pct >= 0 else ""
    print(f"Portfolio Return:   {pnl_sign}${total_pnl:>11,.0f} ({pnl_pct_sign}{portfolio_return_pct:.2f}%)")
    print(f"Hurdle Return:      ${hurdle_return:>12,.0f} ({hurdle_return_pct:.2f}%)")
    alpha_sign = "+" if alpha >= 0 else ""
    alpha_pct_sign = "+" if alpha_pct >= 0 else ""
    print(f"Alpha:              {alpha_sign}${alpha:>11,.0f} ({alpha_pct_sign}{alpha_pct:.2f}%)")
    print("-" * 70)

    # Status
    if total_pnl > hurdle_return:
        status = "ABOVE HURDLE"
        perf_fee_base = total_pnl - hurdle_return
        perf_fee = perf_fee_base * meta["performance_fee"]
        print(f"Status:             {status}")
        print(f"Perf Fee Eligible:  ${perf_fee_base:,.0f} at 20% = ${perf_fee:,.0f} earned")
    else:
        status = "BELOW HURDLE"
        print(f"Status:             {status}")
        print(f"Perf Fee Eligible:  $0 (must exceed hurdle)")
    print("=" * 70)

    # High Water Mark
    hwm = meta["high_water_mark"]
    hwm_date = meta.get("high_water_mark_date", meta["inception_date"])
    distance_to_hwm = portfolio_value - hwm

    print("\nHIGH WATER MARK")
    print("-" * 70)
    print(f"Current HWM:        ${hwm:>12,.0f} (set {hwm_date})")
    print(f"Current Value:      ${portfolio_value:>12,.0f}")
    if distance_to_hwm >= 0:
        print(f"Distance to HWM:    +${distance_to_hwm:>11,.0f} above")
    else:
        print(f"Distance to HWM:    -${abs(distance_to_hwm):>11,.0f} below")
    print("=" * 70)
    print()

    return {
        "total_pnl": total_pnl,
        "portfolio_value": portfolio_value,
        "active_pnl": active_pnl,
        "autonomous_pnl": autonomous_pnl,
        "active_value": active_value,
        "autonomous_value": autonomous_value,
        "cash_value": cash_value,
        "position_count": len(position_pnls),
        "hurdle_return": hurdle_return,
        "alpha": alpha,
        "days_elapsed": days_elapsed,
    }


def update_high_water_mark(meta: dict, portfolio_value: float) -> bool:
    """Update HWM if portfolio value exceeds it. Returns True if updated."""
    if portfolio_value > meta["high_water_mark"]:
        meta["high_water_mark"] = portfolio_value
        meta["high_water_mark_date"] = datetime.now().strftime("%Y-%m-%d")
        return True
    return False


def run_tracker():
    """Main tracker function."""
    # Load portfolio metadata
    meta = load_portfolio_meta()

    # Load positions
    positions = load_positions()

    if not positions:
        print("\nNo open positions found.")
        return

    # Get unique tickers
    tickers = list(set(p["ticker"] for p in positions))

    # Fetch current prices
    print("Fetching current prices...")
    prices = fetch_current_prices(tickers)

    # Calculate P&L for each position
    position_pnls = []
    for pos in positions:
        ticker = pos["ticker"]
        current_price = prices.get(ticker)

        if current_price is None:
            print(f"Warning: No price for {ticker}, using entry price")
            current_price = pos["entry_price"]

        pnl_data = calculate_pnl(pos, current_price)
        position_pnls.append(pnl_data)

    # Print summary
    totals = print_portfolio_summary(position_pnls, meta)

    # Update high water mark if needed
    hwm_updated = update_high_water_mark(meta, totals["portfolio_value"])
    if hwm_updated:
        print(f"New High Water Mark: ${totals['portfolio_value']:,.0f}")
    save_portfolio_meta(meta)

    # Update positions file with current prices and P&L
    update_positions_with_pnl(positions, prices, position_pnls)

    # Append to P&L history
    history = load_pnl_history()

    history_entry = {
        "date": datetime.now().isoformat(),
        "total_pnl": totals["total_pnl"],
        "portfolio_value": totals["portfolio_value"],
        "active_pnl": totals["active_pnl"],
        "autonomous_pnl": totals["autonomous_pnl"],
        "cash_value": totals["cash_value"],
        "hurdle_return": totals["hurdle_return"],
        "alpha": totals["alpha"],
        "days_elapsed": totals["days_elapsed"],
        "position_count": totals["position_count"],
        "positions": [
            {
                "ticker": p["ticker"],
                "direction": p["direction"],
                "type": p["type"],
                "shares": p["shares"],
                "entry_price": p["entry_price"],
                "current_price": p["current_price"],
                "pnl": p["pnl"],
                "pnl_pct": p["pnl_pct"],
            }
            for p in position_pnls
        ],
    }

    history.append(history_entry)
    save_pnl_history(history)

    print(f"P&L history updated: {PNL_HISTORY_FILE}")

    return totals


def update_positions_with_pnl(positions: list, prices: dict, position_pnls: list) -> None:
    """Update positions.json with current prices and P&L."""
    with open(POSITIONS_FILE, "r") as f:
        all_positions = json.load(f)

    pnl_lookup = {p["ticker"]: p for p in position_pnls}

    for pos in all_positions:
        ticker = pos["ticker"]
        if ticker in pnl_lookup and pos.get("status") == "OPEN":
            pnl_data = pnl_lookup[ticker]
            pos["current_price"] = pnl_data["current_price"]
            pos["unrealized_pnl"] = pnl_data["pnl"]
            pos["unrealized_pnl_pct"] = pnl_data["pnl_pct"]

    with open(POSITIONS_FILE, "w") as f:
        json.dump(all_positions, f, indent=2)


if __name__ == "__main__":
    run_tracker()
