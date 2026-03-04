#!/usr/bin/env python3
"""
ATLAS Daily Scanner
Orchestrates the full investment pipeline:
1. Scan for new SEC filings
2. Route to appropriate desk agents
3. Run institutional flow analysis
4. Feed to CIO for synthesis
5. Adversarial review of trades
6. Execute approved trades
7. Check stop losses
8. Generate morning briefing
"""
import json
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config.settings import (
    STARTING_CAPITAL,
    FILING_SCAN_INTERVAL_HOURS,
    THIRTEENF_SCAN_INTERVAL_HOURS,
)
from config.universe import UNIVERSE
from data.edgar_client import EdgarClient
from agents.sector_desk import get_desk_for_sector, get_desk
from agents.institutional_flow_agent import InstitutionalFlowAgent
from agents.cio_agent import CIOAgent
from agents.adversarial_agent import AdversarialAgent, merge_decision_with_review
from portfolio.paper_portfolio import PaperPortfolio
from portfolio.risk_manager import RiskManager
from portfolio.performance import PerformanceTracker

logger = logging.getLogger(__name__)


class DailyScanner:
    """
    Main orchestrator for the ATLAS investment pipeline.
    """
    
    def __init__(self, portfolio: PaperPortfolio = None):
        self.edgar = EdgarClient()
        self.flow_agent = InstitutionalFlowAgent()
        self.cio = CIOAgent()
        self.adversarial = AdversarialAgent()
        self.risk_manager = RiskManager()
        self.portfolio = portfolio or PaperPortfolio(STARTING_CAPITAL)
        self.performance = PerformanceTracker()
    
    def scan_filings(self, days_back: int = 1) -> list[dict]:
        """
        Scan universe for new SEC filings.
        """
        logger.info(f"Scanning universe for filings in last {days_back} days...")
        new_filings = []
        
        for ticker in UNIVERSE.keys():
            try:
                filings = self.edgar.get_recent_filings(
                    ticker,
                    filing_types=["10-K", "10-Q", "8-K"],
                    days_back=days_back
                )
                if filings:
                    for f in filings:
                        f['sector'] = UNIVERSE[ticker].get('sector', 'Unknown')
                    new_filings.extend(filings)
            except Exception as e:
                logger.error(f"Error scanning {ticker}: {e}")
        
        logger.info(f"Found {len(new_filings)} new filings")
        return new_filings
    
    def analyze_filings(self, filings: list[dict], persist: bool = True) -> list[dict]:
        """
        Route filings to appropriate desks and generate briefs.
        """
        briefs = []
        
        # Group by ticker (analyze once per ticker, most recent filing)
        ticker_filings = {}
        for f in filings:
            ticker = f['ticker']
            if ticker not in ticker_filings:
                ticker_filings[ticker] = f
        
        logger.info(f"Analyzing {len(ticker_filings)} tickers...")
        
        for ticker, filing in ticker_filings.items():
            try:
                sector = filing.get('sector', 'Unknown')
                desk = get_desk_for_sector(sector)
                
                logger.info(f"  {ticker} ({sector}) -> {desk.desk_name} desk")
                brief = desk.analyze(ticker, persist=persist)
                
                if brief:
                    briefs.append(brief)
                    
            except Exception as e:
                logger.error(f"  Error analyzing {ticker}: {e}")
        
        logger.info(f"Generated {len(briefs)} briefs")
        return briefs
    
    def run_flow_analysis(self) -> dict:
        """
        Run institutional flow analysis.
        """
        logger.info("Running institutional flow analysis...")
        return self.flow_agent.analyze(use_ai=False)  # Rule-based for speed
    
    def run_cio_synthesis(self, briefs: list[dict], flow: dict) -> dict:
        """
        Feed briefs and flow to CIO for synthesis.
        """
        logger.info("Running CIO synthesis...")
        
        # Get portfolio context
        portfolio_snapshot = self.portfolio.take_snapshot()
        
        return self.cio.run(
            desk_briefs=briefs,
            flow_briefing=flow,
            current_portfolio={
                'total_value': portfolio_snapshot['total_value'],
                'cash': portfolio_snapshot['cash'],
                'cash_pct': portfolio_snapshot['cash_pct'] * 100,
                'num_positions': portfolio_snapshot['num_positions'],
                'positions': portfolio_snapshot['positions'],
            }
        )
    
    def review_and_execute(self, cio_decisions: dict) -> list[dict]:
        """
        Review trades through adversarial agent and execute approved ones.
        """
        executed_trades = []
        
        trade_decisions = cio_decisions.get('trade_decisions', [])
        logger.info(f"Reviewing {len(trade_decisions)} trade decisions...")
        
        portfolio_snapshot = self.portfolio.take_snapshot()
        
        for decision in trade_decisions:
            action = decision.get('action', '').upper()
            ticker = decision.get('ticker', 'UNKNOWN')
            
            # Skip non-trade actions
            if action in ('HOLD', 'AVOID', 'WATCH', 'WATCHLIST'):
                logger.info(f"  {ticker}: {action} - no trade")
                continue
            
            # 1. Adversarial review
            logger.info(f"  Adversarial review: {action} {ticker}...")
            review = self.adversarial.review(decision, {
                'num_positions': portfolio_snapshot['num_positions'],
                'cash_pct': portfolio_snapshot['cash_pct'] * 100,
                'positions': portfolio_snapshot['positions'],
                'sector_exposure': self._calculate_sector_exposure(portfolio_snapshot['positions']),
            })
            
            verdict = review.get('verdict', 'BLOCK')
            
            if verdict == 'BLOCK':
                logger.warning(f"  {ticker}: BLOCKED - {review.get('fatal_flaw', 'Unknown reason')}")
                continue
            
            # 2. Merge with modifications
            final_trade = merge_decision_with_review(decision, review)
            if not final_trade:
                continue
            
            # 3. Risk manager validation
            risk_check = self.risk_manager.validate_trade(final_trade, portfolio_snapshot)
            
            if not risk_check['approved']:
                logger.warning(f"  {ticker}: RISK BLOCKED - {risk_check['violations']}")
                continue
            
            # 4. Execute trade
            result = self.portfolio.execute_trade(final_trade)
            
            if result.get('status') == 'executed':
                executed_trades.append(result)
                logger.info(f"  {ticker}: EXECUTED {action} @ {result.get('price', 0):.2f}")
                # Update snapshot for next trade
                portfolio_snapshot = self.portfolio.take_snapshot()
            else:
                logger.warning(f"  {ticker}: EXECUTION FAILED - {result.get('reason', 'Unknown')}")
        
        return executed_trades
    
    def check_stop_losses(self) -> list[dict]:
        """
        Check all positions against stop losses.
        """
        logger.info("Checking stop losses...")
        triggered = self.portfolio.check_stop_losses()
        
        if triggered:
            logger.warning(f"  {len(triggered)} stop losses triggered!")
            for t in triggered:
                logger.warning(f"    {t['ticker']}: {t['action']} @ {t.get('price', 0):.2f}")
        else:
            logger.info("  No stop losses triggered")
        
        return triggered
    
    def take_daily_snapshot(self):
        """
        Take and persist daily portfolio snapshot.
        """
        logger.info("Taking daily snapshot...")
        snapshot = self.portfolio.take_snapshot()
        self.portfolio.persist_snapshot(snapshot)
        self.performance.add_snapshot(snapshot)
        
        logger.info(f"  Portfolio: ${snapshot['total_value']:,.0f}")
        logger.info(f"  Daily return: {snapshot['daily_return']:+.2%}")
        
        return snapshot
    
    def _calculate_sector_exposure(self, positions: list) -> dict:
        """Calculate sector exposure from positions."""
        exposure = {}
        for pos in positions:
            ticker = pos.get('ticker', '')
            sector = UNIVERSE.get(ticker, {}).get('sector', 'Unknown')
            size = pos.get('size_pct', 0)
            exposure[sector] = exposure.get(sector, 0) + size
        return exposure
    
    def generate_morning_briefing(
        self,
        briefs: list[dict],
        cio_decisions: dict,
        executed_trades: list[dict],
        stop_losses: list[dict],
    ) -> str:
        """
        Generate a formatted morning briefing.
        """
        snapshot = self.portfolio.take_snapshot()
        
        lines = [
            "=" * 60,
            f"ATLAS MORNING BRIEFING - {date.today().strftime('%A, %B %d, %Y')}",
            "=" * 60,
            "",
            "## PORTFOLIO STATUS",
            f"Total Value: ${snapshot['total_value']:,.0f}",
            f"Cash: ${snapshot['cash']:,.0f} ({snapshot['cash_pct']:.1%})",
            f"Positions: {snapshot['num_positions']}",
            f"Net Exposure: {snapshot['net_exposure'] / snapshot['total_value']:.1%}" if snapshot['total_value'] > 0 else "",
            "",
        ]
        
        # CIO Assessment
        if cio_decisions:
            lines.extend([
                "## CIO ASSESSMENT",
                cio_decisions.get('market_assessment', 'N/A'),
                "",
                "### THEMES",
            ])
            for theme in cio_decisions.get('theme_synthesis', [])[:3]:
                lines.append(f"- {theme.get('theme')} ({theme.get('conviction')})")
            lines.append("")
        
        # Executed trades
        if executed_trades:
            lines.extend([
                "## TRADES EXECUTED",
            ])
            for t in executed_trades:
                lines.append(f"- {t['action']} {t['ticker']} @ ${t['price']:.2f} ({t.get('shares', 0)} shares)")
            lines.append("")
        
        # Stop losses
        if stop_losses:
            lines.extend([
                "## ⚠️ STOP LOSSES TRIGGERED",
            ])
            for t in stop_losses:
                lines.append(f"- {t['ticker']}: {t['action']} @ ${t.get('price', 0):.2f} (P&L: ${t.get('pnl', 0):+,.0f})")
            lines.append("")
        
        # Risk flags
        if cio_decisions and cio_decisions.get('risk_flags'):
            lines.extend([
                "## RISK FLAGS",
            ])
            for flag in cio_decisions.get('risk_flags', [])[:5]:
                lines.append(f"- ⚠️ {flag}")
            lines.append("")
        
        # Open positions
        if snapshot['positions']:
            lines.extend([
                "## OPEN POSITIONS",
            ])
            for pos in sorted(snapshot['positions'], key=lambda x: x.get('size_pct', 0), reverse=True):
                pnl_str = f"+{pos['pnl_pct']:.1%}" if pos['pnl_pct'] >= 0 else f"{pos['pnl_pct']:.1%}"
                lines.append(f"- {pos['ticker']}: {pos['size_pct']:.1%} of portfolio, P&L: {pnl_str}")
            lines.append("")
        
        lines.append("=" * 60)
        
        return "\n".join(lines)
    
    def run_full_scan(
        self,
        filing_days_back: int = 1,
        persist_briefs: bool = True,
        execute_trades: bool = True,
    ) -> dict:
        """
        Run the full daily scan pipeline.
        
        Args:
            filing_days_back: How many days back to scan for filings
            persist_briefs: Whether to save briefs to database
            execute_trades: Whether to execute approved trades
        
        Returns:
            Summary of scan results
        """
        start_time = datetime.now()
        logger.info("=" * 60)
        logger.info("ATLAS DAILY SCAN STARTING")
        logger.info("=" * 60)
        
        results = {
            'date': date.today().isoformat(),
            'start_time': start_time.isoformat(),
        }
        
        # 1. Scan filings
        filings = self.scan_filings(days_back=filing_days_back)
        results['filings_found'] = len(filings)
        
        # 2. Analyze filings
        briefs = []
        if filings:
            briefs = self.analyze_filings(filings, persist=persist_briefs)
        results['briefs_generated'] = len(briefs)
        
        # 3. Flow analysis
        flow = self.run_flow_analysis()
        results['flow_analysis'] = bool(flow)
        
        # 4. CIO synthesis
        cio_decisions = None
        if briefs:
            cio_decisions = self.run_cio_synthesis(briefs, flow)
        results['cio_decisions'] = len(cio_decisions.get('trade_decisions', [])) if cio_decisions else 0
        
        # 5. Execute trades
        executed_trades = []
        if execute_trades and cio_decisions:
            executed_trades = self.review_and_execute(cio_decisions)
        results['trades_executed'] = len(executed_trades)
        
        # 6. Check stop losses
        stop_losses = self.check_stop_losses()
        results['stop_losses_triggered'] = len(stop_losses)
        
        # 7. Daily snapshot
        snapshot = self.take_daily_snapshot()
        results['portfolio_value'] = snapshot['total_value']
        
        # 8. Generate briefing
        briefing = self.generate_morning_briefing(
            briefs, cio_decisions, executed_trades, stop_losses
        )
        results['briefing'] = briefing
        
        # Done
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        results['duration_seconds'] = duration
        
        logger.info("=" * 60)
        logger.info(f"ATLAS DAILY SCAN COMPLETE ({duration:.1f}s)")
        logger.info("=" * 60)
        
        return results


def run_morning_scan():
    """
    Convenience function to run the morning scan.
    """
    scanner = DailyScanner()
    return scanner.run_full_scan(
        filing_days_back=1,
        persist_briefs=True,
        execute_trades=True,
    )


if __name__ == "__main__":
    import argparse
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )
    
    parser = argparse.ArgumentParser(description="ATLAS Daily Scanner")
    parser.add_argument("--days", type=int, default=1, help="Days back to scan")
    parser.add_argument("--no-execute", action="store_true", help="Don't execute trades")
    parser.add_argument("--test", action="store_true", help="Run with test data")
    args = parser.parse_args()
    
    if args.test:
        # Test mode with minimal data
        print("\n" + "="*60)
        print("ATLAS Scanner - Test Mode")
        print("="*60 + "\n")
        
        scanner = DailyScanner()
        
        # Test with a couple of tickers
        test_briefs = [
            {
                'ticker': 'NVDA',
                'desk': 'Semiconductor',
                'signal': 'BULLISH',
                'confidence': 0.85,
                'brief_for_cio': 'Strong AI demand',
                'bull_case': 'AI capex cycle',
                'bear_case': 'Valuation',
                'catalysts': {'upcoming': ['GTC'], 'risks': ['China']}
            }
        ]
        
        test_flow = {
            'consensus_builds': [],
            'crowding_warnings': [{'ticker': 'NVDA', 'funds_holding': 14, 'of_total': 16}],
            'contrarian_signals': [],
            'conviction_positions': []
        }
        
        cio = scanner.run_cio_synthesis(test_briefs, test_flow)
        if cio:
            print("\nCIO Decisions:")
            for d in cio.get('trade_decisions', []):
                print(f"  {d.get('action')} {d.get('ticker')}")
    else:
        results = run_morning_scan() if not args.no_execute else DailyScanner().run_full_scan(
            filing_days_back=args.days,
            execute_trades=False,
        )
        
        print("\n" + results.get('briefing', 'No briefing generated'))
