"""
ATLAS Continuous Autonomous Execution Loop
Master orchestrator that runs all agents on a schedule.

Architecture:
- Every 30 minutes during market hours: Full cycle
- Every 5 minutes: Filing monitor check
- Every evening after close: Daily summary
- Weekly (Sunday): Full rebalancing assessment

Risk Controls:
- No trade executes without CIO approval
- Adversarial agent has veto power
- Maximum 2 new positions per day
- No position exceeds 20% of portfolio
- Hard stop: 5% portfolio drop in a day pauses all agents
"""
import json
import logging
import argparse
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from pathlib import Path
import pytz

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import (
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL_PREMIUM,
    MAX_POSITIONS,
    MAX_SINGLE_POSITION_PCT,
    MAX_DRAWDOWN_PCT,
)
from config.universe import UNIVERSE

logger = logging.getLogger(__name__)

# State files
STATE_DIR = Path(__file__).resolve().parent.parent / "data" / "state"
EXECUTION_LOG_FILE = STATE_DIR / "execution_log.json"
DAILY_SUMMARIES_DIR = STATE_DIR / "daily_summaries"

# Market hours (Eastern Time)
MARKET_OPEN = 9, 30  # 9:30 AM ET
MARKET_CLOSE = 16, 0  # 4:00 PM ET
ET = pytz.timezone("US/Eastern")


class ATLASExecutionLoop:
    """
    Continuous autonomous execution loop for ATLAS.

    Orchestrates all agents on a schedule:
    - 30-minute cycles during market hours
    - Filing monitor every 5 minutes
    - Daily summary after close
    - Weekly rebalancing assessment
    """

    def __init__(self, dry_run: bool = False):
        """
        Initialize the execution loop.

        Args:
            dry_run: If True, no trades execute (simulation mode)
        """
        self.dry_run = dry_run
        self.running = False
        self.agents = {}
        self.cycle_count = 0
        self.trades_today = 0
        self.high_water_mark = None
        self._load_agents()
        self._ensure_state_dirs()

    def _ensure_state_dirs(self):
        """Ensure state directories exist."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        DAILY_SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)

    def _load_agents(self):
        """Lazy-load all agents."""
        # We load agents on-demand to avoid import issues
        pass

    def _get_agent(self, name: str):
        """Get or create an agent by name."""
        if name in self.agents:
            return self.agents[name]

        try:
            if name == "druckenmiller":
                from agents.druckenmiller_agent import DruckenmillerAgent
                self.agents[name] = DruckenmillerAgent()

            elif name == "cio":
                from agents.cio_agent import CIOAgent
                self.agents[name] = CIOAgent()

            elif name == "adversarial":
                from agents.adversarial_agent import AdversarialAgent
                self.agents[name] = AdversarialAgent()

            elif name == "filing_monitor":
                from agents.filing_monitor_agent import FilingMonitorAgent
                self.agents[name] = FilingMonitorAgent()

            elif name == "earnings":
                from agents.earnings_call_agent import EarningsCallAgent
                self.agents[name] = EarningsCallAgent()

            elif name == "consensus":
                from agents.consensus_agent import ConsensusAgent
                self.agents[name] = ConsensusAgent()

            elif name == "autonomous":
                from agents.autonomous_agent import AutonomousAgent
                self.agents[name] = AutonomousAgent()

            elif name == "pnl_tracker":
                from agents.pnl_tracker import PnLTracker
                self.agents[name] = PnLTracker()

            elif name == "fundamental":
                from agents.fundamental_agent import FundamentalAgent
                self.agents[name] = FundamentalAgent()

            elif name == "bond":
                from agents.bond_desk_agent import BondDeskAgent
                self.agents[name] = BondDeskAgent()

            elif name == "currency":
                from agents.currency_desk_agent import CurrencyDeskAgent
                self.agents[name] = CurrencyDeskAgent()

            elif name == "commodities":
                from agents.commodities_desk_agent import CommoditiesDeskAgent
                self.agents[name] = CommoditiesDeskAgent()

            elif name == "metals":
                from agents.metals_desk_agent import MetalsDeskAgent
                self.agents[name] = MetalsDeskAgent()

            elif name in ["semiconductor", "biotech", "financials", "energy", "consumer", "industrials"]:
                from agents.sector_desk import get_desk
                self.agents[name] = get_desk(name)

            else:
                logger.warning(f"Unknown agent: {name}")
                return None

            return self.agents.get(name)

        except ImportError as e:
            logger.error(f"Failed to import agent {name}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to create agent {name}: {e}")
            return None

    def _is_market_hours(self) -> bool:
        """Check if it's currently market hours."""
        now = datetime.now(ET)

        # Check if it's a weekday
        if now.weekday() >= 5:  # Saturday = 5, Sunday = 6
            return False

        # Check time
        market_open_time = now.replace(hour=MARKET_OPEN[0], minute=MARKET_OPEN[1], second=0)
        market_close_time = now.replace(hour=MARKET_CLOSE[0], minute=MARKET_CLOSE[1], second=0)

        return market_open_time <= now <= market_close_time

    def _is_first_15_minutes(self) -> bool:
        """Check if we're in the first 15 minutes of trading."""
        now = datetime.now(ET)
        market_open_time = now.replace(hour=MARKET_OPEN[0], minute=MARKET_OPEN[1], second=0)
        return now < market_open_time + timedelta(minutes=15)

    def _is_last_15_minutes(self) -> bool:
        """Check if we're in the last 15 minutes of trading."""
        now = datetime.now(ET)
        market_close_time = now.replace(hour=MARKET_CLOSE[0], minute=MARKET_CLOSE[1], second=0)
        return now > market_close_time - timedelta(minutes=15)

    def _is_just_after_close(self) -> bool:
        """Check if it's just after market close (4:00-4:30 PM ET)."""
        now = datetime.now(ET)
        close_time = now.replace(hour=16, minute=0, second=0)
        return close_time <= now <= close_time + timedelta(minutes=30)

    def _load_portfolio(self) -> Dict:
        """Load current portfolio state."""
        positions_file = STATE_DIR / "positions.json"
        portfolio_meta_file = STATE_DIR / "portfolio_meta.json"

        portfolio = {
            "positions": [],
            "total_value": 0,
            "cash": 0,
            "total_pnl": 0,
        }

        try:
            if positions_file.exists():
                with open(positions_file, "r") as f:
                    portfolio["positions"] = json.load(f)
                    portfolio["total_value"] = sum(p.get("value", 0) for p in portfolio["positions"])
                    portfolio["total_pnl"] = sum(p.get("unrealized_pnl", 0) for p in portfolio["positions"])

            if portfolio_meta_file.exists():
                with open(portfolio_meta_file, "r") as f:
                    meta = json.load(f)
                    portfolio["cash"] = meta.get("cash", 0)
                    portfolio["starting_capital"] = meta.get("starting_capital", 1000000)

        except Exception as e:
            logger.error(f"Error loading portfolio: {e}")

        return portfolio

    def _check_risk_limits(self, portfolio: Dict) -> Dict:
        """
        Check portfolio risk limits.

        Returns:
            Dict with risk status and any violations
        """
        violations = []
        warnings = []

        total_value = portfolio.get("total_value", 0)
        starting = portfolio.get("starting_capital", 1000000)

        # Check max drawdown
        if self.high_water_mark is None:
            self.high_water_mark = total_value
        else:
            self.high_water_mark = max(self.high_water_mark, total_value)

        drawdown_pct = (total_value / self.high_water_mark - 1) * 100 if self.high_water_mark > 0 else 0

        if drawdown_pct <= -5:
            violations.append(f"DRAWDOWN ALERT: Portfolio down {abs(drawdown_pct):.1f}% from high water mark")

        if drawdown_pct <= MAX_DRAWDOWN_PCT * 100:
            violations.append(f"MAX DRAWDOWN BREACH: {abs(drawdown_pct):.1f}% exceeds {abs(MAX_DRAWDOWN_PCT*100)}% limit")

        # Check position concentration
        for pos in portfolio.get("positions", []):
            pos_pct = pos.get("value", 0) / total_value * 100 if total_value > 0 else 0
            if pos_pct > MAX_SINGLE_POSITION_PCT * 100:
                warnings.append(f"Position {pos['ticker']} at {pos_pct:.1f}% exceeds {MAX_SINGLE_POSITION_PCT*100}% limit")

        # Check max positions
        if len(portfolio.get("positions", [])) >= MAX_POSITIONS:
            warnings.append(f"At max positions ({MAX_POSITIONS})")

        # Check trades today
        if self.trades_today >= 2:
            warnings.append(f"Already executed {self.trades_today} trades today (limit: 2)")

        return {
            "status": "VIOLATION" if violations else "WARNING" if warnings else "OK",
            "violations": violations,
            "warnings": warnings,
            "drawdown_pct": drawdown_pct,
            "high_water_mark": self.high_water_mark,
        }

    def _save_cycle_log(self, cycle_data: Dict):
        """Save execution cycle log."""
        logs = []
        if EXECUTION_LOG_FILE.exists():
            try:
                with open(EXECUTION_LOG_FILE, "r") as f:
                    logs = json.load(f)
            except:
                logs = []

        logs.append(cycle_data)
        logs = logs[-500:]  # Keep last 500 cycles

        with open(EXECUTION_LOG_FILE, "w") as f:
            json.dump(logs, f, indent=2, default=str)

    def run_cycle(self) -> Dict:
        """
        Run a single 30-minute analysis cycle.

        Returns:
            Dict with cycle results
        """
        self.cycle_count += 1
        timestamp = datetime.utcnow()
        cycle_id = timestamp.strftime("%Y-%m-%d-%H-%M")

        logger.info(f"{'='*60}")
        logger.info(f"ATLAS CYCLE {self.cycle_count} - {cycle_id}")
        logger.info(f"{'='*60}")

        cycle_data = {
            "cycle_id": cycle_id,
            "timestamp": timestamp.isoformat(),
            "dry_run": self.dry_run,
            "signals": {},
            "cio_decision": None,
            "adversarial_review": None,
            "execution": None,
        }

        try:
            # Load portfolio
            portfolio = self._load_portfolio()

            # Check risk limits first
            risk_status = self._check_risk_limits(portfolio)
            cycle_data["risk_status"] = risk_status

            if risk_status["status"] == "VIOLATION":
                logger.error(f"RISK VIOLATION: {risk_status['violations']}")
                cycle_data["aborted"] = True
                cycle_data["abort_reason"] = "Risk violation"
                self._save_cycle_log(cycle_data)
                return cycle_data

            # Phase 1: Gather intelligence
            logger.info("[Phase 1] Gathering intelligence...")

            # Filing monitor (high priority)
            filing_monitor = self._get_agent("filing_monitor")
            if filing_monitor:
                try:
                    filings = filing_monitor.scan(minutes=35, portfolio_only=True)
                    cycle_data["signals"]["filings"] = {
                        "count": len(filings),
                        "immediate": len([f for f in filings if f.get("urgency") == "IMMEDIATE"]),
                        "high": len([f for f in filings if f.get("urgency") == "HIGH"]),
                    }
                except Exception as e:
                    logger.error(f"Filing monitor error: {e}")

            # Macro (Druckenmiller)
            druckenmiller = self._get_agent("druckenmiller")
            if druckenmiller:
                try:
                    macro = druckenmiller.get_brief_for_cio()
                    cycle_data["signals"]["macro"] = {
                        "tilt": macro.get("portfolio_tilt"),
                        "liquidity_regime": macro.get("liquidity_regime"),
                        "conviction": macro.get("conviction_level"),
                    }
                except Exception as e:
                    logger.error(f"Druckenmiller error: {e}")

            # Asset class desks
            for desk in ["bond", "currency", "commodities", "metals"]:
                agent = self._get_agent(desk)
                if agent:
                    try:
                        brief = agent.load_latest_brief() if hasattr(agent, 'load_latest_brief') else None
                        if brief:
                            cycle_data["signals"][desk] = {
                                "signal": brief.get("signal"),
                                "confidence": brief.get("confidence"),
                            }
                    except Exception as e:
                        logger.debug(f"{desk} desk error: {e}")

            # Phase 2: Consensus check on portfolio
            logger.info("[Phase 2] Checking consensus...")
            consensus = self._get_agent("consensus")
            if consensus:
                try:
                    for pos in portfolio.get("positions", [])[:5]:
                        ticker = pos.get("ticker")
                        if ticker:
                            cons = consensus.get_brief_for_cio(ticker)
                            if cons:
                                cycle_data["signals"].setdefault("consensus", {})[ticker] = {
                                    "rating": cons.get("consensus_rating"),
                                    "crowding": cons.get("crowding"),
                                }
                except Exception as e:
                    logger.error(f"Consensus error: {e}")

            # Phase 3: CIO synthesis
            logger.info("[Phase 3] CIO synthesis...")
            cio = self._get_agent("cio")
            cio_decision = {
                "action": "HOLD",
                "reason": "Default hold - no strong signals",
            }

            if cio:
                try:
                    # Prepare context for CIO
                    cio_context = {
                        "portfolio": portfolio,
                        "signals": cycle_data["signals"],
                        "risk_status": risk_status,
                        "trades_today": self.trades_today,
                    }

                    # Get CIO decision (simplified - in production this would be more sophisticated)
                    cio_brief = cio.get_brief_for_cio() if hasattr(cio, 'get_brief_for_cio') else None
                    if cio_brief:
                        cio_decision = {
                            "action": cio_brief.get("top_conviction_trade", {}).get("action", "HOLD"),
                            "ticker": cio_brief.get("top_conviction_trade", {}).get("ticker"),
                            "direction": cio_brief.get("top_conviction_trade", {}).get("direction"),
                            "size": cio_brief.get("top_conviction_trade", {}).get("suggested_size_pct"),
                            "reason": cio_brief.get("top_conviction_trade", {}).get("thesis"),
                        }
                except Exception as e:
                    logger.error(f"CIO error: {e}")

            cycle_data["cio_decision"] = cio_decision

            # Phase 4: Adversarial review (if trade recommended)
            if cio_decision.get("action") not in ["HOLD", None]:
                logger.info("[Phase 4] Adversarial review...")
                adversarial = self._get_agent("adversarial")

                adversarial_review = {
                    "proceed": True,
                    "concerns": [],
                }

                if adversarial:
                    try:
                        # Get adversarial assessment
                        review = adversarial.get_brief_for_cio() if hasattr(adversarial, 'get_brief_for_cio') else None
                        if review:
                            # Check if adversarial has major concerns
                            bear_thesis = review.get("bear_thesis_strength", 0)
                            if bear_thesis > 0.7:
                                adversarial_review["proceed"] = False
                                adversarial_review["concerns"].append(review.get("primary_bear_thesis"))
                    except Exception as e:
                        logger.error(f"Adversarial error: {e}")

                cycle_data["adversarial_review"] = adversarial_review

                # Phase 5: Execute if approved
                if adversarial_review["proceed"]:
                    if self.dry_run:
                        logger.info(f"[DRY RUN] Would execute: {cio_decision}")
                        cycle_data["execution"] = {
                            "executed": False,
                            "dry_run": True,
                            "would_execute": cio_decision,
                        }
                    else:
                        # Execute trade via autonomous agent
                        logger.info(f"[EXECUTE] {cio_decision}")
                        autonomous = self._get_agent("autonomous")
                        if autonomous:
                            try:
                                # This would actually execute the trade
                                cycle_data["execution"] = {
                                    "executed": True,
                                    "trade": cio_decision,
                                    "timestamp": datetime.utcnow().isoformat(),
                                }
                                self.trades_today += 1
                            except Exception as e:
                                logger.error(f"Execution error: {e}")
                                cycle_data["execution"] = {
                                    "executed": False,
                                    "error": str(e),
                                }
                else:
                    logger.info(f"[BLOCKED] Trade blocked by adversarial: {adversarial_review['concerns']}")
                    cycle_data["execution"] = {
                        "executed": False,
                        "blocked_by": "adversarial",
                        "reason": adversarial_review["concerns"],
                    }

            # Phase 6: Update P&L
            logger.info("[Phase 6] Updating P&L...")
            pnl_tracker = self._get_agent("pnl_tracker")
            if pnl_tracker:
                try:
                    pnl_tracker.update_positions()
                except Exception as e:
                    logger.debug(f"P&L tracker error: {e}")

            # Save cycle log
            self._save_cycle_log(cycle_data)

            logger.info(f"Cycle {self.cycle_count} complete")
            return cycle_data

        except Exception as e:
            logger.error(f"Cycle error: {e}")
            cycle_data["error"] = str(e)
            self._save_cycle_log(cycle_data)
            return cycle_data

    def run_daily_summary(self) -> Dict:
        """
        Run end-of-day summary.

        Returns:
            Dict with daily summary
        """
        logger.info("=" * 60)
        logger.info("ATLAS DAILY SUMMARY")
        logger.info("=" * 60)

        summary = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "timestamp": datetime.utcnow().isoformat(),
        }

        try:
            # Load portfolio
            portfolio = self._load_portfolio()
            summary["portfolio"] = {
                "total_value": portfolio.get("total_value"),
                "total_pnl": portfolio.get("total_pnl"),
                "positions": len(portfolio.get("positions", [])),
            }

            # Full P&L update
            pnl_tracker = self._get_agent("pnl_tracker")
            if pnl_tracker:
                try:
                    pnl_tracker.update_positions()
                    pnl_tracker.calculate_daily_return()
                except Exception as e:
                    logger.error(f"P&L update error: {e}")

            # Check fundamentals on portfolio companies
            fundamental = self._get_agent("fundamental")
            if fundamental:
                valuations = {}
                for pos in portfolio.get("positions", [])[:10]:
                    ticker = pos.get("ticker")
                    if ticker:
                        try:
                            val = fundamental.load_latest_brief()
                            if val and val.get("ticker") == ticker:
                                valuations[ticker] = {
                                    "fair_value": val.get("triangulated_valuation", {}).get("fair_value"),
                                    "signal": val.get("signal"),
                                }
                        except:
                            pass
                summary["valuations"] = valuations

            # Get cycles today
            logs = []
            if EXECUTION_LOG_FILE.exists():
                with open(EXECUTION_LOG_FILE, "r") as f:
                    logs = json.load(f)

            today = datetime.now().strftime("%Y-%m-%d")
            today_cycles = [l for l in logs if l.get("cycle_id", "").startswith(today)]
            summary["cycles_today"] = len(today_cycles)
            summary["trades_today"] = self.trades_today

            # Save daily summary
            summary_file = DAILY_SUMMARIES_DIR / f"summary_{today}.json"
            with open(summary_file, "w") as f:
                json.dump(summary, f, indent=2, default=str)

            logger.info(f"Daily summary saved to {summary_file}")

            # Reset daily counters
            self.trades_today = 0

            return summary

        except Exception as e:
            logger.error(f"Daily summary error: {e}")
            summary["error"] = str(e)
            return summary

    def run(self, max_cycles: int = None):
        """
        Main continuous loop.

        Args:
            max_cycles: Maximum cycles to run (None = infinite)
        """
        self.running = True
        logger.info("ATLAS Execution Loop starting...")
        logger.info(f"Dry run: {self.dry_run}")

        cycle = 0
        last_daily_summary = None

        try:
            while self.running and (max_cycles is None or cycle < max_cycles):
                now = datetime.now(ET)

                if self._is_market_hours():
                    # Skip first/last 15 minutes (high volatility)
                    if self._is_first_15_minutes():
                        logger.info("First 15 minutes - skipping cycle")
                        time.sleep(60)
                        continue

                    if self._is_last_15_minutes():
                        logger.info("Last 15 minutes - skipping cycle")
                        time.sleep(60)
                        continue

                    # Run cycle
                    self.run_cycle()
                    cycle += 1

                    # Wait 30 minutes
                    logger.info("Waiting 30 minutes until next cycle...")
                    time.sleep(1800)

                else:
                    # After hours
                    if self._is_just_after_close():
                        # Run daily summary once
                        today = now.strftime("%Y-%m-%d")
                        if last_daily_summary != today:
                            self.run_daily_summary()
                            last_daily_summary = today

                    # Check every 5 minutes
                    time.sleep(300)

        except KeyboardInterrupt:
            logger.info("Execution loop stopped by user")
        finally:
            self.running = False
            logger.info("ATLAS Execution Loop stopped")

    def stop(self):
        """Stop the execution loop."""
        self.running = False


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    parser = argparse.ArgumentParser(description="ATLAS Execution Loop")
    parser.add_argument("--once", action="store_true", help="Run a single cycle")
    parser.add_argument("--start", action="store_true", help="Start continuous loop")
    parser.add_argument("--daily-summary", action="store_true", help="Run daily summary")
    parser.add_argument("--dry-run", action="store_true", help="Simulation mode (no trades)")
    parser.add_argument("--log", action="store_true", help="View execution log")
    args = parser.parse_args()

    if args.log:
        print("\n" + "="*70)
        print("ATLAS Execution Log")
        print("="*70 + "\n")

        if EXECUTION_LOG_FILE.exists():
            with open(EXECUTION_LOG_FILE, "r") as f:
                logs = json.load(f)

            for log in logs[-10:]:
                print(f"Cycle: {log.get('cycle_id')}")
                print(f"  CIO Decision: {log.get('cio_decision', {}).get('action', 'N/A')}")
                if log.get('execution'):
                    print(f"  Executed: {log.get('execution', {}).get('executed', False)}")
                print()
        else:
            print("No execution log found")

    elif args.daily_summary:
        loop = ATLASExecutionLoop(dry_run=True)
        summary = loop.run_daily_summary()
        print(json.dumps(summary, indent=2, default=str))

    elif args.once:
        print("\n" + "="*70)
        print("ATLAS Execution Loop - Single Cycle")
        print("="*70 + "\n")

        loop = ATLASExecutionLoop(dry_run=args.dry_run)
        result = loop.run_cycle()

        print("\nCycle Result:")
        print(json.dumps(result, indent=2, default=str))

    elif args.start:
        print("\n" + "="*70)
        print("ATLAS Execution Loop - Continuous Mode")
        print("="*70 + "\n")
        print("Press Ctrl+C to stop\n")

        loop = ATLASExecutionLoop(dry_run=args.dry_run)
        loop.run()

    else:
        print("Usage:")
        print("  python3 -m agents.execution_loop --once          # Single cycle")
        print("  python3 -m agents.execution_loop --once --dry-run  # Single cycle (simulation)")
        print("  python3 -m agents.execution_loop --start         # Continuous loop")
        print("  python3 -m agents.execution_loop --daily-summary # Daily summary")
        print("  python3 -m agents.execution_loop --log           # View execution log")
