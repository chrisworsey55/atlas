"""
Risk Manager
Pre-trade and portfolio-level risk checks.
"""
import logging
from typing import Optional
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import (
    MAX_POSITIONS,
    MAX_SINGLE_POSITION_PCT,
    MAX_SECTOR_CONCENTRATION_PCT,
    MIN_CASH_BUFFER_PCT,
    MAX_SHORT_PCT,
    MAX_DRAWDOWN_PCT,
)
from config.universe import UNIVERSE

logger = logging.getLogger(__name__)


class RiskManager:
    """
    Pre-trade risk validation and portfolio risk monitoring.
    """
    
    def __init__(self):
        self.max_positions = MAX_POSITIONS
        self.max_single_position = MAX_SINGLE_POSITION_PCT
        self.max_sector_concentration = MAX_SECTOR_CONCENTRATION_PCT
        self.min_cash_buffer = MIN_CASH_BUFFER_PCT
        self.max_short_pct = MAX_SHORT_PCT
        self.max_drawdown = MAX_DRAWDOWN_PCT
    
    def validate_trade(self, trade: dict, portfolio_snapshot: dict) -> dict:
        """
        Validate a trade against all risk rules.
        
        Args:
            trade: Trade decision from CIO
            portfolio_snapshot: Current portfolio state
        
        Returns:
            dict with 'approved' bool and list of 'violations'
        """
        violations = []
        warnings = []
        
        ticker = trade.get('ticker', 'UNKNOWN')
        action = trade.get('action', '').upper()
        size_pct = trade.get('size_pct', 0)
        
        # Skip validation for HOLD/AVOID
        if action in ('HOLD', 'AVOID', 'WATCH', 'SELL', 'COVER'):
            return {'approved': True, 'violations': [], 'warnings': []}
        
        portfolio_value = portfolio_snapshot.get('total_value', 1_000_000)
        cash = portfolio_snapshot.get('cash', 100_000)
        cash_pct = cash / portfolio_value if portfolio_value > 0 else 1
        positions = portfolio_snapshot.get('positions', [])
        num_positions = len(positions)
        
        # 1. Position count limit
        if action == 'BUY' and ticker not in [p['ticker'] for p in positions]:
            if num_positions >= self.max_positions:
                violations.append(f"MAX_POSITIONS: Already at {num_positions}/{self.max_positions} positions")
        
        # 2. Single position size limit
        if size_pct > self.max_single_position:
            violations.append(f"MAX_SINGLE_POSITION: {size_pct:.1%} exceeds {self.max_single_position:.1%} limit")
        
        # 3. Cash buffer check
        trade_cost = portfolio_value * size_pct
        post_trade_cash_pct = (cash - trade_cost) / portfolio_value if portfolio_value > 0 else 0
        
        if action in ('BUY', 'SHORT') and post_trade_cash_pct < self.min_cash_buffer:
            violations.append(f"MIN_CASH_BUFFER: Post-trade cash {post_trade_cash_pct:.1%} below {self.min_cash_buffer:.1%} minimum")
        
        # 4. Sector concentration
        ticker_sector = UNIVERSE.get(ticker, {}).get('sector', 'Unknown')
        sector_exposure = self._calculate_sector_exposure(positions)
        current_sector_pct = sector_exposure.get(ticker_sector, 0)
        post_trade_sector_pct = current_sector_pct + size_pct
        
        if post_trade_sector_pct > self.max_sector_concentration:
            violations.append(
                f"MAX_SECTOR_CONCENTRATION: {ticker_sector} would be {post_trade_sector_pct:.1%}, "
                f"exceeds {self.max_sector_concentration:.1%} limit"
            )
        elif post_trade_sector_pct > self.max_sector_concentration * 0.8:
            warnings.append(f"Sector concentration warning: {ticker_sector} at {post_trade_sector_pct:.1%}")
        
        # 5. Short exposure limit
        if action == 'SHORT':
            current_short = portfolio_snapshot.get('short_exposure', 0) / portfolio_value if portfolio_value > 0 else 0
            post_trade_short = current_short + size_pct
            
            if post_trade_short > self.max_short_pct:
                violations.append(
                    f"MAX_SHORT_EXPOSURE: Post-trade short {post_trade_short:.1%} "
                    f"exceeds {self.max_short_pct:.1%} limit"
                )
        
        # 6. Portfolio drawdown check
        starting_capital = portfolio_snapshot.get('starting_capital', portfolio_value)
        drawdown = (portfolio_value - starting_capital) / starting_capital if starting_capital > 0 else 0
        
        if drawdown <= self.max_drawdown:
            violations.append(f"MAX_DRAWDOWN: Portfolio at {drawdown:.1%}, trading halted below {self.max_drawdown:.1%}")
        
        # 7. Correlation check (basic)
        if action == 'BUY':
            existing_in_sector = [p['ticker'] for p in positions if UNIVERSE.get(p['ticker'], {}).get('sector') == ticker_sector]
            if len(existing_in_sector) >= 3:
                warnings.append(f"Correlation warning: Already have {len(existing_in_sector)} positions in {ticker_sector}")
        
        approved = len(violations) == 0
        
        result = {
            'approved': approved,
            'violations': violations,
            'warnings': warnings,
            'trade': trade,
            'checks_performed': [
                'position_count', 'single_position_size', 'cash_buffer',
                'sector_concentration', 'short_exposure', 'drawdown', 'correlation'
            ]
        }
        
        if violations:
            logger.warning(f"Trade BLOCKED for {ticker}: {violations}")
        elif warnings:
            logger.info(f"Trade APPROVED with warnings for {ticker}: {warnings}")
        else:
            logger.info(f"Trade APPROVED for {ticker}")
        
        return result
    
    def _calculate_sector_exposure(self, positions: list) -> dict:
        """Calculate current sector exposure from positions."""
        sector_exposure = {}
        
        for pos in positions:
            ticker = pos.get('ticker', '')
            sector = UNIVERSE.get(ticker, {}).get('sector', 'Unknown')
            size_pct = pos.get('size_pct', 0)
            
            sector_exposure[sector] = sector_exposure.get(sector, 0) + size_pct
        
        return sector_exposure
    
    def check_portfolio_health(self, portfolio_snapshot: dict) -> dict:
        """
        Run comprehensive portfolio health check.
        
        Returns:
            dict with health metrics and any alerts
        """
        alerts = []
        metrics = {}
        
        portfolio_value = portfolio_snapshot.get('total_value', 1_000_000)
        starting_capital = portfolio_snapshot.get('starting_capital', portfolio_value)
        cash = portfolio_snapshot.get('cash', 100_000)
        positions = portfolio_snapshot.get('positions', [])
        
        # Calculate metrics
        cash_pct = cash / portfolio_value if portfolio_value > 0 else 1
        drawdown = (portfolio_value - starting_capital) / starting_capital if starting_capital > 0 else 0
        
        long_exposure = sum(p.get('current_value', 0) for p in positions if p.get('direction') == 'LONG')
        short_exposure = sum(p.get('current_value', 0) for p in positions if p.get('direction') == 'SHORT')
        
        net_exposure = (long_exposure - short_exposure) / portfolio_value if portfolio_value > 0 else 0
        gross_exposure = (long_exposure + short_exposure) / portfolio_value if portfolio_value > 0 else 0
        
        # Sector concentration
        sector_exposure = self._calculate_sector_exposure(positions)
        max_sector = max(sector_exposure.values()) if sector_exposure else 0
        
        # Largest position
        largest_position = max((p.get('size_pct', 0) for p in positions), default=0)
        
        metrics = {
            'portfolio_value': portfolio_value,
            'cash_pct': cash_pct,
            'drawdown': drawdown,
            'net_exposure': net_exposure,
            'gross_exposure': gross_exposure,
            'num_positions': len(positions),
            'largest_position_pct': largest_position,
            'max_sector_concentration': max_sector,
            'sector_exposure': sector_exposure,
        }
        
        # Generate alerts
        if cash_pct < self.min_cash_buffer:
            alerts.append(f"🚨 LOW CASH: {cash_pct:.1%} below {self.min_cash_buffer:.1%} minimum")
        
        if drawdown <= self.max_drawdown * 0.8:
            alerts.append(f"🚨 DRAWDOWN WARNING: {drawdown:.1%} approaching {self.max_drawdown:.1%} limit")
        
        if drawdown <= self.max_drawdown:
            alerts.append(f"🛑 MAX DRAWDOWN HIT: {drawdown:.1%} — TRADING HALTED")
        
        if max_sector > self.max_sector_concentration * 0.9:
            max_sector_name = max(sector_exposure, key=sector_exposure.get) if sector_exposure else 'Unknown'
            alerts.append(f"⚠️ SECTOR CONCENTRATION: {max_sector_name} at {max_sector:.1%}")
        
        if largest_position > self.max_single_position * 0.9:
            alerts.append(f"⚠️ POSITION SIZE: Largest position at {largest_position:.1%}")
        
        # Count positions hitting stop losses
        stop_losses_near = [p for p in positions if p.get('pnl_pct', 0) < p.get('stop_loss_pct', -0.08) * 0.8]
        if stop_losses_near:
            alerts.append(f"⚠️ STOP LOSSES: {len(stop_losses_near)} positions approaching stops")
        
        return {
            'healthy': len([a for a in alerts if '🚨' in a or '🛑' in a]) == 0,
            'metrics': metrics,
            'alerts': alerts,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    
    print("\n" + "="*60)
    print("ATLAS Risk Manager - Test")
    print("="*60 + "\n")
    
    rm = RiskManager()
    
    # Test portfolio
    test_snapshot = {
        'total_value': 1_000_000,
        'starting_capital': 1_000_000,
        'cash': 150_000,
        'positions': [
            {'ticker': 'NVDA', 'size_pct': 0.08, 'direction': 'LONG', 'pnl_pct': 0.05},
            {'ticker': 'AMD', 'size_pct': 0.06, 'direction': 'LONG', 'pnl_pct': -0.02},
            {'ticker': 'AVGO', 'size_pct': 0.07, 'direction': 'LONG', 'pnl_pct': 0.03},
            {'ticker': 'LLY', 'size_pct': 0.05, 'direction': 'LONG', 'pnl_pct': 0.01},
        ],
        'long_exposure': 850_000,
        'short_exposure': 0,
    }
    
    # Test trade validation
    test_trade = {
        'ticker': 'MSFT',
        'action': 'BUY',
        'size_pct': 0.15,  # Will fail - too large
    }
    
    result = rm.validate_trade(test_trade, test_snapshot)
    print(f"Trade validation: {result}")
    
    # Test portfolio health
    health = rm.check_portfolio_health(test_snapshot)
    print(f"\nPortfolio health: {health}")
