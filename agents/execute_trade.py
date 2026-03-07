#!/usr/bin/env python3
"""
Execute a paper trade with full documentation.
Skill: /trade BUY/SELL/SHORT/COVER TICKER SHARES PRICE
"""
import argparse
import json
from pathlib import Path
from datetime import datetime

STATE_DIR = Path(__file__).parent.parent / "data" / "state"
JOURNAL_DIR = Path(__file__).parent.parent / "data" / "trade_journal"


def execute_trade(
    action: str,
    ticker: str,
    shares: int,
    price: float,
    agent: str = 'manual',
    thesis: str = 'Manual trade',
    stop_loss: float = None,
    target: float = None,
    confidence: int = 80
):
    """
    Execute a paper trade and update all relevant files.

    Args:
        action: BUY, SELL, SHORT, or COVER
        ticker: Stock ticker symbol
        shares: Number of shares
        price: Execution price
        agent: Agent source (default: manual)
        thesis: Investment thesis
        stop_loss: Stop loss price
        target: Target price
        confidence: Conviction level (0-100)
    """
    action = action.upper()
    ticker = ticker.upper()

    # ================================================================
    # UPDATE POSITIONS.JSON
    # ================================================================
    positions_file = STATE_DIR / "positions.json"

    with open(positions_file) as f:
        data = json.load(f)

    # Handle nested structure
    if isinstance(data, dict) and 'positions' in data:
        positions = data['positions']
        is_nested = True
    else:
        positions = data if isinstance(data, list) else list(data.values())
        is_nested = False

    # Calculate allocation
    portfolio_value = data.get('portfolio_value', 1000000) if is_nested else 1000000
    value = shares * price
    alloc = round(value / portfolio_value * 100, 1)

    direction = 'SHORT' if action in ['SHORT', 'SELL'] else 'LONG'

    if action in ['BUY', 'SHORT']:
        # Opening a position
        new_position = {
            'ticker': ticker,
            'direction': direction,
            'shares': shares,
            'entry_price': price,
            'current_price': price,
            'allocation_pct': alloc,
            'thesis': thesis,
            'agent_source': agent,
            'conviction': confidence,
            'stop_loss': stop_loss,
            'target': target,
            'invalidation': None,
            'date_opened': datetime.now().strftime('%Y-%m-%d'),
            'unrealized_pnl': 0
        }

        # Check if position already exists
        existing_idx = None
        for i, pos in enumerate(positions):
            if pos['ticker'] == ticker:
                existing_idx = i
                break

        if existing_idx is not None:
            # Adding to existing position
            old_pos = positions[existing_idx]
            total_shares = old_pos['shares'] + shares
            avg_price = ((old_pos['shares'] * old_pos['entry_price']) + (shares * price)) / total_shares
            new_alloc = round((total_shares * avg_price) / portfolio_value * 100, 1)

            old_pos['shares'] = total_shares
            old_pos['entry_price'] = round(avg_price, 2)
            old_pos['allocation_pct'] = new_alloc
            old_pos['thesis'] = thesis  # Update thesis
            positions[existing_idx] = old_pos
            print(f"  Added to existing position. New avg price: ${avg_price:.2f}")
        else:
            positions.append(new_position)

        # Reduce BIL (cash)
        for pos in positions:
            if pos['ticker'] == 'BIL':
                pos['allocation_pct'] = round(pos['allocation_pct'] - alloc, 1)
                pos['shares'] = int(pos['allocation_pct'] / 100 * portfolio_value / pos.get('entry_price', 91.39))
                break

    elif action in ['SELL', 'COVER']:
        # Closing a position
        for i, pos in enumerate(positions):
            if pos['ticker'] == ticker:
                # Calculate P&L
                entry = pos['entry_price']
                if pos['direction'] == 'SHORT':
                    pnl = (entry - price) * pos['shares']
                else:
                    pnl = (price - entry) * pos['shares']

                # Move closed position to journal
                _close_position_journal(ticker, pos, price, pnl)

                # Remove from positions
                positions.pop(i)

                # Add cash back to BIL
                for p in positions:
                    if p['ticker'] == 'BIL':
                        p['allocation_pct'] = round(p['allocation_pct'] + pos['allocation_pct'], 1)
                        p['shares'] = int(p['allocation_pct'] / 100 * portfolio_value / p.get('entry_price', 91.39))
                        break

                print(f"  Position closed. P&L: ${pnl:,.2f}")
                break
        else:
            print(f"  ERROR: No position found for {ticker}")
            return

    # Save positions
    if is_nested:
        data['positions'] = positions
        data['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M')
    else:
        data = positions

    with open(positions_file, 'w') as f:
        json.dump(data, f, indent=2)

    # ================================================================
    # UPDATE DECISIONS.JSON
    # ================================================================
    decisions_file = STATE_DIR / "decisions.json"

    try:
        with open(decisions_file) as f:
            decisions = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        decisions = []

    decision_record = {
        "date": datetime.now().strftime('%Y-%m-%d'),
        "ticker": ticker,
        "action": action,
        "shares": shares,
        "price": price,
        "agent": agent,
        "thesis": thesis,
        "status": "OPEN" if action in ['BUY', 'SHORT'] else "CLOSED"
    }

    if action in ['SELL', 'COVER']:
        decision_record['close_price'] = price

    decisions.append(decision_record)

    with open(decisions_file, 'w') as f:
        json.dump(decisions, f, indent=2)

    # ================================================================
    # CREATE/UPDATE TRADE JOURNAL
    # ================================================================
    if action in ['BUY', 'SHORT']:
        _create_trade_journal(ticker, direction, shares, price, agent, thesis, stop_loss, target, confidence)

    # ================================================================
    # SUMMARY
    # ================================================================
    print(f"\n{'='*60}")
    print(f"  TRADE EXECUTED")
    print(f"{'='*60}")
    print(f"  Action:     {action}")
    print(f"  Ticker:     {ticker}")
    print(f"  Shares:     {shares:,}")
    print(f"  Price:      ${price:.2f}")
    print(f"  Value:      ${value:,.0f}")
    print(f"  Allocation: {alloc}%")
    print(f"  Agent:      {agent}")
    print(f"  Stop Loss:  ${stop_loss:.2f}" if stop_loss else "  Stop Loss:  Not set")
    print(f"  Target:     ${target:.2f}" if target else "  Target:     Not set")
    print(f"{'='*60}")


def _create_trade_journal(ticker, direction, shares, price, agent, thesis, stop_loss, target, confidence):
    """Create a trade journal entry for an open position."""
    journal_dir = JOURNAL_DIR / "open"
    journal_dir.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime('%Y%m%d')
    filename = f"{ticker}_{direction}_{date_str}.md"

    journal_content = f"""# {ticker} {direction} — {datetime.now().strftime('%Y-%m-%d')}

## Entry
- **Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}
- **Price:** ${price:.2f}
- **Shares:** {shares:,}
- **Value:** ${shares * price:,.0f}
- **Agent:** {agent}
- **Confidence:** {confidence}%

## Thesis
{thesis}

## Key Levels
- **Entry:** ${price:.2f}
- **Stop Loss:** ${stop_loss:.2f if stop_loss else 'TBD'}
- **Target:** ${target:.2f if target else 'TBD'}

## Performance Log
| Date | Event | Price | P&L | Notes |
|------|-------|-------|-----|-------|
| {datetime.now().strftime('%Y-%m-%d')} | ENTRY | ${price:.2f} | $0 | Initial position |

## Outcome
- **Status:** OPEN
- **Exit Date:** --
- **Exit Price:** --
- **Final P&L:** --
"""

    with open(journal_dir / filename, 'w') as f:
        f.write(journal_content)

    print(f"  Journal created: data/trade_journal/open/{filename}")


def _close_position_journal(ticker, position, close_price, pnl):
    """Move trade journal from open to closed."""
    open_dir = JOURNAL_DIR / "open"
    closed_dir = JOURNAL_DIR / "closed"
    closed_dir.mkdir(parents=True, exist_ok=True)

    # Find the open journal
    direction = position.get('direction', 'LONG')

    # Look for any matching journal file
    journal_file = None
    for f in open_dir.glob(f"{ticker}_{direction}_*.md"):
        journal_file = f
        break

    if journal_file:
        # Read existing journal
        with open(journal_file) as f:
            content = f.read()

        # Update outcome section
        entry_price = position.get('entry_price', close_price)
        pnl_pct = (pnl / (entry_price * position.get('shares', 1))) * 100

        content = content.replace("- **Status:** OPEN", f"- **Status:** CLOSED")
        content = content.replace("- **Exit Date:** --", f"- **Exit Date:** {datetime.now().strftime('%Y-%m-%d')}")
        content = content.replace("- **Exit Price:** --", f"- **Exit Price:** ${close_price:.2f}")
        content = content.replace("- **Final P&L:** --", f"- **Final P&L:** ${pnl:,.2f} ({pnl_pct:+.2f}%)")

        # Add exit to performance log
        log_entry = f"\n| {datetime.now().strftime('%Y-%m-%d')} | EXIT | ${close_price:.2f} | ${pnl:,.2f} | Position closed |"
        content = content.replace("## Outcome", f"{log_entry}\n\n## Outcome")

        # Move to closed directory
        new_filename = f"{ticker}_{direction}_{datetime.now().strftime('%Y%m%d')}_closed.md"
        with open(closed_dir / new_filename, 'w') as f:
            f.write(content)

        # Remove from open
        journal_file.unlink()

        print(f"  Journal moved to: data/trade_journal/closed/{new_filename}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Execute a paper trade')
    parser.add_argument('action', choices=['BUY', 'SELL', 'SHORT', 'COVER'],
                        help='Trade action')
    parser.add_argument('ticker', help='Stock ticker symbol')
    parser.add_argument('shares', type=int, help='Number of shares')
    parser.add_argument('price', type=float, help='Execution price')
    parser.add_argument('--agent', default='manual', help='Agent source')
    parser.add_argument('--thesis', default='Manual trade', help='Investment thesis')
    parser.add_argument('--stop', type=float, default=None, help='Stop loss price')
    parser.add_argument('--target', type=float, default=None, help='Target price')
    parser.add_argument('--confidence', type=int, default=80, help='Conviction level (0-100)')

    args = parser.parse_args()

    execute_trade(
        args.action,
        args.ticker,
        args.shares,
        args.price,
        args.agent,
        args.thesis,
        args.stop,
        args.target,
        args.confidence
    )
