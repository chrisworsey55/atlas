"""
Performance Tracker
Analytics for portfolio returns, risk metrics, and benchmarking.
"""
import logging
from datetime import datetime, date, timedelta
from typing import Optional
from pathlib import Path
import json

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger(__name__)


class PerformanceTracker:
    """
    Tracks and calculates portfolio performance metrics.
    """
    
    def __init__(self):
        self.snapshots = []  # List of daily snapshots
        self.benchmark_ticker = "^GSPC"  # S&P 500
    
    def add_snapshot(self, snapshot: dict):
        """Add a daily portfolio snapshot."""
        self.snapshots.append(snapshot)
        # Keep sorted by date
        self.snapshots.sort(key=lambda x: x.get('date', ''))
    
    def load_snapshots_from_db(self, days: int = 365):
        """Load snapshots from database."""
        try:
            from database import get_session, AtlasPortfolioSnapshot
            
            session = get_session()
            cutoff = date.today() - timedelta(days=days)
            
            db_snapshots = session.query(AtlasPortfolioSnapshot).filter(
                AtlasPortfolioSnapshot.date >= cutoff
            ).order_by(AtlasPortfolioSnapshot.date).all()
            
            self.snapshots = []
            for s in db_snapshots:
                self.snapshots.append({
                    'date': s.date.isoformat(),
                    'total_value': s.total_value,
                    'cash': s.cash,
                    'daily_return': s.daily_return,
                    'cumulative_return': s.cumulative_return,
                    'num_positions': s.num_positions,
                    'positions': s.positions_json,
                })
            
            session.close()
            logger.info(f"Loaded {len(self.snapshots)} snapshots from database")
            
        except Exception as e:
            logger.error(f"Failed to load snapshots: {e}")
    
    def calculate_returns(self) -> dict:
        """Calculate various return metrics."""
        if len(self.snapshots) < 2:
            return {'error': 'Need at least 2 snapshots for return calculation'}
        
        # Daily returns
        daily_returns = []
        for i in range(1, len(self.snapshots)):
            prev_value = self.snapshots[i-1].get('total_value', 1)
            curr_value = self.snapshots[i].get('total_value', 1)
            daily_return = (curr_value - prev_value) / prev_value if prev_value > 0 else 0
            daily_returns.append(daily_return)
        
        # Cumulative return
        first_value = self.snapshots[0].get('total_value', 1)
        last_value = self.snapshots[-1].get('total_value', 1)
        cumulative_return = (last_value - first_value) / first_value if first_value > 0 else 0
        
        # Annualized return (if we have enough data)
        days = len(self.snapshots)
        annualized_return = ((1 + cumulative_return) ** (365 / days) - 1) if days > 0 else 0
        
        # Average daily return
        avg_daily_return = sum(daily_returns) / len(daily_returns) if daily_returns else 0
        
        # Win rate
        wins = sum(1 for r in daily_returns if r > 0)
        win_rate = wins / len(daily_returns) if daily_returns else 0
        
        # Best and worst days
        best_day = max(daily_returns) if daily_returns else 0
        worst_day = min(daily_returns) if daily_returns else 0
        
        return {
            'cumulative_return': cumulative_return,
            'annualized_return': annualized_return,
            'avg_daily_return': avg_daily_return,
            'win_rate': win_rate,
            'best_day': best_day,
            'worst_day': worst_day,
            'trading_days': len(daily_returns),
        }
    
    def calculate_risk_metrics(self) -> dict:
        """Calculate risk metrics (volatility, Sharpe, max drawdown)."""
        if len(self.snapshots) < 10:
            return {'error': 'Need at least 10 snapshots for risk calculation'}
        
        # Daily returns
        daily_returns = []
        for i in range(1, len(self.snapshots)):
            prev_value = self.snapshots[i-1].get('total_value', 1)
            curr_value = self.snapshots[i].get('total_value', 1)
            daily_return = (curr_value - prev_value) / prev_value if prev_value > 0 else 0
            daily_returns.append(daily_return)
        
        # Volatility (annualized)
        import math
        mean_return = sum(daily_returns) / len(daily_returns)
        variance = sum((r - mean_return) ** 2 for r in daily_returns) / len(daily_returns)
        daily_vol = math.sqrt(variance)
        annualized_vol = daily_vol * math.sqrt(252)
        
        # Sharpe ratio (assuming 5% risk-free rate)
        risk_free_daily = 0.05 / 252
        excess_returns = [r - risk_free_daily for r in daily_returns]
        mean_excess = sum(excess_returns) / len(excess_returns)
        sharpe_ratio = (mean_excess / daily_vol * math.sqrt(252)) if daily_vol > 0 else 0
        
        # Maximum drawdown
        peak = self.snapshots[0].get('total_value', 1)
        max_drawdown = 0
        
        for snapshot in self.snapshots:
            value = snapshot.get('total_value', 1)
            if value > peak:
                peak = value
            drawdown = (value - peak) / peak if peak > 0 else 0
            max_drawdown = min(max_drawdown, drawdown)
        
        # Sortino ratio (downside deviation)
        negative_returns = [r for r in daily_returns if r < 0]
        if negative_returns:
            downside_variance = sum(r ** 2 for r in negative_returns) / len(negative_returns)
            downside_dev = math.sqrt(downside_variance) * math.sqrt(252)
            sortino_ratio = (mean_excess * 252 / downside_dev) if downside_dev > 0 else 0
        else:
            sortino_ratio = float('inf')
        
        return {
            'daily_volatility': daily_vol,
            'annualized_volatility': annualized_vol,
            'sharpe_ratio': sharpe_ratio,
            'sortino_ratio': sortino_ratio,
            'max_drawdown': max_drawdown,
        }
    
    def calculate_trade_stats(self, trades: list) -> dict:
        """Calculate trade-level statistics."""
        if not trades:
            return {'error': 'No trades to analyze'}
        
        # Closed trades only
        closed = [t for t in trades if t.get('pnl') is not None]
        if not closed:
            return {'total_trades': len(trades), 'closed_trades': 0}
        
        # Win/loss stats
        winners = [t for t in closed if t.get('pnl', 0) > 0]
        losers = [t for t in closed if t.get('pnl', 0) < 0]
        
        win_rate = len(winners) / len(closed) if closed else 0
        
        # Average win/loss
        avg_win = sum(t['pnl'] for t in winners) / len(winners) if winners else 0
        avg_loss = sum(t['pnl'] for t in losers) / len(losers) if losers else 0
        
        # Profit factor
        gross_profit = sum(t['pnl'] for t in winners)
        gross_loss = abs(sum(t['pnl'] for t in losers))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        # Expectancy
        expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)
        
        # Largest win/loss
        largest_win = max((t['pnl'] for t in winners), default=0)
        largest_loss = min((t['pnl'] for t in losers), default=0)
        
        return {
            'total_trades': len(trades),
            'closed_trades': len(closed),
            'winners': len(winners),
            'losers': len(losers),
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'expectancy': expectancy,
            'largest_win': largest_win,
            'largest_loss': largest_loss,
            'total_pnl': sum(t.get('pnl', 0) for t in closed),
        }
    
    def get_benchmark_returns(self, start_date: str, end_date: str) -> dict:
        """Get S&P 500 returns for comparison."""
        try:
            from data.price_client import PriceClient
            
            prices = PriceClient()
            # Use yfinance for historical data
            import yfinance as yf
            
            ticker = yf.Ticker(self.benchmark_ticker)
            hist = ticker.history(start=start_date, end=end_date)
            
            if len(hist) < 2:
                return {'error': 'Insufficient benchmark data'}
            
            first_close = hist['Close'].iloc[0]
            last_close = hist['Close'].iloc[-1]
            benchmark_return = (last_close - first_close) / first_close
            
            return {
                'ticker': self.benchmark_ticker,
                'return': benchmark_return,
                'start_price': first_close,
                'end_price': last_close,
            }
            
        except Exception as e:
            logger.error(f"Failed to get benchmark data: {e}")
            return {'error': str(e)}
    
    def generate_report(self, trades: list = None) -> dict:
        """Generate comprehensive performance report."""
        report = {
            'generated_at': datetime.now().isoformat(),
            'period': {
                'start': self.snapshots[0].get('date') if self.snapshots else None,
                'end': self.snapshots[-1].get('date') if self.snapshots else None,
                'days': len(self.snapshots),
            },
        }
        
        # Current state
        if self.snapshots:
            latest = self.snapshots[-1]
            report['current'] = {
                'portfolio_value': latest.get('total_value'),
                'cash': latest.get('cash'),
                'num_positions': latest.get('num_positions'),
            }
        
        # Returns
        report['returns'] = self.calculate_returns()
        
        # Risk metrics
        report['risk'] = self.calculate_risk_metrics()
        
        # Trade stats
        if trades:
            report['trades'] = self.calculate_trade_stats(trades)
        
        # Benchmark comparison
        if self.snapshots and len(self.snapshots) >= 2:
            benchmark = self.get_benchmark_returns(
                self.snapshots[0].get('date'),
                self.snapshots[-1].get('date')
            )
            if 'error' not in benchmark:
                portfolio_return = report['returns'].get('cumulative_return', 0)
                report['benchmark'] = {
                    'ticker': benchmark['ticker'],
                    'return': benchmark['return'],
                    'alpha': portfolio_return - benchmark['return'],
                }
        
        return report
    
    def format_report(self, report: dict = None) -> str:
        """Format report as readable text."""
        if report is None:
            report = self.generate_report()
        
        lines = [
            "=" * 60,
            "ATLAS PERFORMANCE REPORT",
            "=" * 60,
            "",
        ]
        
        # Period
        period = report.get('period', {})
        lines.extend([
            f"Period: {period.get('start', 'N/A')} to {period.get('end', 'N/A')} ({period.get('days', 0)} days)",
            "",
        ])
        
        # Current state
        current = report.get('current', {})
        if current:
            lines.extend([
                "CURRENT STATE",
                f"  Portfolio Value: ${current.get('portfolio_value', 0):,.0f}",
                f"  Cash: ${current.get('cash', 0):,.0f}",
                f"  Positions: {current.get('num_positions', 0)}",
                "",
            ])
        
        # Returns
        returns = report.get('returns', {})
        if 'error' not in returns:
            lines.extend([
                "RETURNS",
                f"  Cumulative: {returns.get('cumulative_return', 0):+.1%}",
                f"  Annualized: {returns.get('annualized_return', 0):+.1%}",
                f"  Win Rate: {returns.get('win_rate', 0):.1%}",
                f"  Best Day: {returns.get('best_day', 0):+.1%}",
                f"  Worst Day: {returns.get('worst_day', 0):+.1%}",
                "",
            ])
        
        # Risk
        risk = report.get('risk', {})
        if 'error' not in risk:
            lines.extend([
                "RISK METRICS",
                f"  Volatility (ann.): {risk.get('annualized_volatility', 0):.1%}",
                f"  Sharpe Ratio: {risk.get('sharpe_ratio', 0):.2f}",
                f"  Sortino Ratio: {risk.get('sortino_ratio', 0):.2f}",
                f"  Max Drawdown: {risk.get('max_drawdown', 0):.1%}",
                "",
            ])
        
        # Benchmark
        benchmark = report.get('benchmark', {})
        if benchmark:
            lines.extend([
                "VS BENCHMARK (S&P 500)",
                f"  S&P 500 Return: {benchmark.get('return', 0):+.1%}",
                f"  Alpha: {benchmark.get('alpha', 0):+.1%}",
                "",
            ])
        
        # Trade stats
        trades = report.get('trades', {})
        if trades and 'error' not in trades:
            lines.extend([
                "TRADE STATISTICS",
                f"  Total Trades: {trades.get('total_trades', 0)}",
                f"  Closed: {trades.get('closed_trades', 0)}",
                f"  Win Rate: {trades.get('win_rate', 0):.1%}",
                f"  Profit Factor: {trades.get('profit_factor', 0):.2f}",
                f"  Total P&L: ${trades.get('total_pnl', 0):+,.0f}",
                "",
            ])
        
        lines.append("=" * 60)
        
        return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    
    print("\n" + "="*60)
    print("ATLAS Performance Tracker - Test")
    print("="*60 + "\n")
    
    tracker = PerformanceTracker()
    
    # Add test snapshots
    test_snapshots = [
        {'date': '2026-02-01', 'total_value': 1000000},
        {'date': '2026-02-02', 'total_value': 1010000},
        {'date': '2026-02-03', 'total_value': 1005000},
        {'date': '2026-02-04', 'total_value': 1015000},
        {'date': '2026-02-05', 'total_value': 1020000},
        {'date': '2026-02-06', 'total_value': 1018000},
        {'date': '2026-02-07', 'total_value': 1025000},
        {'date': '2026-02-08', 'total_value': 1030000},
        {'date': '2026-02-09', 'total_value': 1028000},
        {'date': '2026-02-10', 'total_value': 1035000},
    ]
    
    for s in test_snapshots:
        tracker.add_snapshot(s)
    
    # Generate report
    report = tracker.generate_report()
    print(tracker.format_report(report))
