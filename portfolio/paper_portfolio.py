"""
Paper Portfolio Engine
Simulated trading with real market prices.
"""
import json
import logging
from datetime import datetime, date
from typing import Optional
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import STARTING_CAPITAL
from data.price_client import PriceClient

logger = logging.getLogger(__name__)


class PaperPortfolio:
    """
    Paper trading portfolio engine.
    Tracks positions, executes trades, calculates P&L.
    """
    
    def __init__(self, starting_capital: float = None):
        self.starting_capital = starting_capital or STARTING_CAPITAL
        self.cash = self.starting_capital
        self.positions = {}  # ticker -> Position dict
        self.trade_history = []
        self.prices = PriceClient()
        
        logger.info(f"Paper portfolio initialized with ${self.starting_capital:,.0f}")
    
    def get_portfolio_value(self) -> float:
        """Calculate total portfolio value (cash + positions at current prices)."""
        position_value = 0
        
        for ticker, pos in self.positions.items():
            current_price = self.prices.get_current_price(ticker)
            if current_price:
                if pos['direction'] == 'LONG':
                    position_value += pos['shares'] * current_price
                else:  # SHORT
                    # Short P&L = entry_price - current_price per share
                    position_value += pos['shares'] * (2 * pos['entry_price'] - current_price)
        
        return self.cash + position_value
    
    def get_position_value(self, ticker: str) -> float:
        """Get current value of a specific position."""
        if ticker not in self.positions:
            return 0
        
        pos = self.positions[ticker]
        current_price = self.prices.get_current_price(ticker) or pos['entry_price']
        
        if pos['direction'] == 'LONG':
            return pos['shares'] * current_price
        else:  # SHORT
            return pos['shares'] * (2 * pos['entry_price'] - current_price)
    
    def get_positions(self) -> list[dict]:
        """Get all open positions with current P&L."""
        result = []
        portfolio_value = self.get_portfolio_value()
        
        for ticker, pos in self.positions.items():
            current_price = self.prices.get_current_price(ticker) or pos['entry_price']
            
            if pos['direction'] == 'LONG':
                pnl_dollars = (current_price - pos['entry_price']) * pos['shares']
                pnl_pct = (current_price - pos['entry_price']) / pos['entry_price']
                current_value = pos['shares'] * current_price
            else:  # SHORT
                pnl_dollars = (pos['entry_price'] - current_price) * pos['shares']
                pnl_pct = (pos['entry_price'] - current_price) / pos['entry_price']
                current_value = pos['shares'] * pos['entry_price']  # Collateral value
            
            size_pct = current_value / portfolio_value if portfolio_value > 0 else 0
            
            result.append({
                'ticker': ticker,
                'direction': pos['direction'],
                'shares': pos['shares'],
                'entry_price': pos['entry_price'],
                'entry_date': pos['entry_date'],
                'current_price': current_price,
                'current_value': current_value,
                'size_pct': size_pct,
                'pnl_dollars': pnl_dollars,
                'pnl_pct': pnl_pct,
                'stop_loss_pct': pos.get('stop_loss_pct', -0.08),
                'thesis_id': pos.get('thesis_id'),
            })
        
        return result
    
    def execute_trade(self, trade_decision: dict) -> dict:
        """
        Execute a trade decision from the CIO.
        
        Args:
            trade_decision: Dict with ticker, action, size_pct, stop_loss_pct
        
        Returns:
            Trade execution result
        """
        ticker = trade_decision.get('ticker')
        action = trade_decision.get('action', '').upper()
        size_pct = trade_decision.get('size_pct', 0)
        stop_loss_pct = trade_decision.get('stop_loss_pct', -0.08)
        
        if not ticker or action in ('HOLD', 'AVOID', 'WATCH'):
            return {'status': 'skipped', 'reason': f'No action required: {action}'}
        
        current_price = self.prices.get_current_price(ticker)
        if not current_price:
            return {'status': 'failed', 'reason': f'Could not get price for {ticker}'}
        
        portfolio_value = self.get_portfolio_value()
        
        if action == 'BUY':
            return self._execute_buy(ticker, size_pct, current_price, portfolio_value, stop_loss_pct, trade_decision)
        elif action == 'SELL':
            return self._execute_sell(ticker, trade_decision)
        elif action == 'SHORT':
            return self._execute_short(ticker, size_pct, current_price, portfolio_value, stop_loss_pct, trade_decision)
        elif action == 'COVER':
            return self._execute_cover(ticker, trade_decision)
        else:
            return {'status': 'failed', 'reason': f'Unknown action: {action}'}
    
    def _execute_buy(self, ticker: str, size_pct: float, price: float, 
                     portfolio_value: float, stop_loss_pct: float, decision: dict) -> dict:
        """Execute a BUY order."""
        target_value = portfolio_value * size_pct
        shares = int(target_value / price)
        cost = shares * price
        
        if cost > self.cash:
            return {'status': 'failed', 'reason': f'Insufficient cash: need ${cost:,.0f}, have ${self.cash:,.0f}'}
        
        # Execute
        self.cash -= cost
        
        if ticker in self.positions:
            # Add to existing position
            old_pos = self.positions[ticker]
            total_shares = old_pos['shares'] + shares
            avg_price = (old_pos['shares'] * old_pos['entry_price'] + shares * price) / total_shares
            self.positions[ticker] = {
                'direction': 'LONG',
                'shares': total_shares,
                'entry_price': avg_price,
                'entry_date': old_pos['entry_date'],
                'stop_loss_pct': stop_loss_pct,
                'thesis_id': decision.get('thesis_id'),
            }
        else:
            self.positions[ticker] = {
                'direction': 'LONG',
                'shares': shares,
                'entry_price': price,
                'entry_date': datetime.now().isoformat(),
                'stop_loss_pct': stop_loss_pct,
                'thesis_id': decision.get('thesis_id'),
            }
        
        trade = {
            'status': 'executed',
            'ticker': ticker,
            'action': 'BUY',
            'shares': shares,
            'price': price,
            'value': cost,
            'timestamp': datetime.now().isoformat(),
        }
        self.trade_history.append(trade)
        logger.info(f"BUY {shares} {ticker} @ ${price:.2f} = ${cost:,.0f}")
        
        return trade
    
    def _execute_sell(self, ticker: str, decision: dict) -> dict:
        """Execute a SELL order (close or reduce long position)."""
        if ticker not in self.positions:
            return {'status': 'failed', 'reason': f'No position in {ticker}'}
        
        pos = self.positions[ticker]
        if pos['direction'] != 'LONG':
            return {'status': 'failed', 'reason': f'{ticker} is not a long position'}
        
        current_price = self.prices.get_current_price(ticker) or pos['entry_price']
        shares = pos['shares']
        proceeds = shares * current_price
        
        # Calculate P&L
        cost_basis = shares * pos['entry_price']
        pnl = proceeds - cost_basis
        
        # Execute
        self.cash += proceeds
        del self.positions[ticker]
        
        trade = {
            'status': 'executed',
            'ticker': ticker,
            'action': 'SELL',
            'shares': shares,
            'price': current_price,
            'value': proceeds,
            'pnl': pnl,
            'timestamp': datetime.now().isoformat(),
        }
        self.trade_history.append(trade)
        logger.info(f"SELL {shares} {ticker} @ ${current_price:.2f} = ${proceeds:,.0f} (P&L: ${pnl:+,.0f})")
        
        return trade
    
    def _execute_short(self, ticker: str, size_pct: float, price: float,
                       portfolio_value: float, stop_loss_pct: float, decision: dict) -> dict:
        """Execute a SHORT order."""
        target_value = portfolio_value * size_pct
        shares = int(target_value / price)
        collateral = shares * price  # Cash collateral for short
        
        if collateral > self.cash:
            return {'status': 'failed', 'reason': f'Insufficient collateral: need ${collateral:,.0f}'}
        
        # Execute (cash is held as collateral)
        self.cash -= collateral
        self.positions[ticker] = {
            'direction': 'SHORT',
            'shares': shares,
            'entry_price': price,
            'entry_date': datetime.now().isoformat(),
            'stop_loss_pct': stop_loss_pct,
            'collateral': collateral,
            'thesis_id': decision.get('thesis_id'),
        }
        
        trade = {
            'status': 'executed',
            'ticker': ticker,
            'action': 'SHORT',
            'shares': shares,
            'price': price,
            'value': collateral,
            'timestamp': datetime.now().isoformat(),
        }
        self.trade_history.append(trade)
        logger.info(f"SHORT {shares} {ticker} @ ${price:.2f} (collateral: ${collateral:,.0f})")
        
        return trade
    
    def _execute_cover(self, ticker: str, decision: dict) -> dict:
        """Execute a COVER order (close short position)."""
        if ticker not in self.positions:
            return {'status': 'failed', 'reason': f'No position in {ticker}'}
        
        pos = self.positions[ticker]
        if pos['direction'] != 'SHORT':
            return {'status': 'failed', 'reason': f'{ticker} is not a short position'}
        
        current_price = self.prices.get_current_price(ticker) or pos['entry_price']
        shares = pos['shares']
        cover_cost = shares * current_price
        
        # Calculate P&L
        pnl = (pos['entry_price'] - current_price) * shares
        
        # Return collateral and settle P&L
        self.cash += pos.get('collateral', shares * pos['entry_price']) + pnl
        del self.positions[ticker]
        
        trade = {
            'status': 'executed',
            'ticker': ticker,
            'action': 'COVER',
            'shares': shares,
            'price': current_price,
            'value': cover_cost,
            'pnl': pnl,
            'timestamp': datetime.now().isoformat(),
        }
        self.trade_history.append(trade)
        logger.info(f"COVER {shares} {ticker} @ ${current_price:.2f} (P&L: ${pnl:+,.0f})")
        
        return trade
    
    def check_stop_losses(self) -> list[dict]:
        """Check all positions against their stop losses."""
        triggered = []
        
        for ticker, pos in list(self.positions.items()):
            current_price = self.prices.get_current_price(ticker)
            if not current_price:
                continue
            
            stop_loss_pct = pos.get('stop_loss_pct', -0.08)
            
            if pos['direction'] == 'LONG':
                pnl_pct = (current_price - pos['entry_price']) / pos['entry_price']
                if pnl_pct <= stop_loss_pct:
                    logger.warning(f"STOP LOSS triggered for {ticker}: {pnl_pct:.1%}")
                    result = self._execute_sell(ticker, {'reason': 'stop_loss'})
                    result['trigger'] = 'stop_loss'
                    triggered.append(result)
            else:  # SHORT
                pnl_pct = (pos['entry_price'] - current_price) / pos['entry_price']
                if pnl_pct <= stop_loss_pct:
                    logger.warning(f"STOP LOSS triggered for short {ticker}: {pnl_pct:.1%}")
                    result = self._execute_cover(ticker, {'reason': 'stop_loss'})
                    result['trigger'] = 'stop_loss'
                    triggered.append(result)
        
        return triggered
    
    def take_snapshot(self) -> dict:
        """Take a snapshot of current portfolio state."""
        portfolio_value = self.get_portfolio_value()
        positions = self.get_positions()
        
        long_exposure = sum(p['current_value'] for p in positions if p['direction'] == 'LONG')
        short_exposure = sum(p['current_value'] for p in positions if p['direction'] == 'SHORT')
        
        snapshot = {
            'date': date.today().isoformat(),
            'timestamp': datetime.now().isoformat(),
            'total_value': portfolio_value,
            'cash': self.cash,
            'cash_pct': self.cash / portfolio_value if portfolio_value > 0 else 1,
            'long_exposure': long_exposure,
            'short_exposure': short_exposure,
            'net_exposure': long_exposure - short_exposure,
            'gross_exposure': long_exposure + short_exposure,
            'num_positions': len(self.positions),
            'positions': positions,
            'daily_return': (portfolio_value - self.starting_capital) / self.starting_capital,
        }
        
        return snapshot
    
    def persist_snapshot(self, snapshot: dict = None):
        """Save snapshot to database."""
        if snapshot is None:
            snapshot = self.take_snapshot()
        
        try:
            from database import get_session, AtlasPortfolioSnapshot
            
            session = get_session()
            
            db_snapshot = AtlasPortfolioSnapshot(
                date=date.today(),
                total_value=snapshot['total_value'],
                cash=snapshot['cash'],
                long_exposure=snapshot['long_exposure'],
                short_exposure=snapshot['short_exposure'],
                net_exposure=snapshot['net_exposure'],
                gross_exposure=snapshot['gross_exposure'],
                positions_json=snapshot['positions'],
                num_positions=snapshot['num_positions'],
                daily_return=snapshot['daily_return'],
            )
            
            session.merge(db_snapshot)  # Upsert
            session.commit()
            session.close()
            
            logger.info(f"Portfolio snapshot saved: ${snapshot['total_value']:,.0f}")
            
        except Exception as e:
            logger.error(f"Failed to persist snapshot: {e}")
    
    def to_dict(self) -> dict:
        """Export portfolio state as dict."""
        return {
            'starting_capital': self.starting_capital,
            'cash': self.cash,
            'positions': self.positions,
            'trade_history': self.trade_history,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'PaperPortfolio':
        """Load portfolio from dict."""
        portfolio = cls(starting_capital=data.get('starting_capital', STARTING_CAPITAL))
        portfolio.cash = data.get('cash', portfolio.starting_capital)
        portfolio.positions = data.get('positions', {})
        portfolio.trade_history = data.get('trade_history', [])
        return portfolio


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    
    print("\n" + "="*60)
    print("ATLAS Paper Portfolio - Test")
    print("="*60 + "\n")
    
    portfolio = PaperPortfolio(starting_capital=1_000_000)
    
    # Test BUY
    result = portfolio.execute_trade({
        'ticker': 'NVDA',
        'action': 'BUY',
        'size_pct': 0.05,
        'stop_loss_pct': -0.08,
    })
    print(f"BUY result: {result}")
    
    # Test another BUY
    result = portfolio.execute_trade({
        'ticker': 'LLY',
        'action': 'BUY',
        'size_pct': 0.04,
        'stop_loss_pct': -0.08,
    })
    print(f"BUY result: {result}")
    
    # Snapshot
    snapshot = portfolio.take_snapshot()
    print(f"\nPortfolio Value: ${snapshot['total_value']:,.0f}")
    print(f"Cash: ${snapshot['cash']:,.0f}")
    print(f"Positions: {snapshot['num_positions']}")
    for pos in snapshot['positions']:
        print(f"  {pos['ticker']}: {pos['size_pct']:.1%} @ ${pos['entry_price']:.2f}, P&L: {pos['pnl_pct']:.1%}")
