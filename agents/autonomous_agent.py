"""
Autonomous Trading Agent
Independent decision-maker that manages a ring-fenced 5% sleeve of the ATLAS portfolio.

Key characteristics:
- No human approval required
- No CIO oversight or adversarial review
- Executes immediately when conviction is high
- Manages its own risk within strict parameters
- Decision cycle every 30 minutes during market hours

Mandate:
- $50,000 paper trading sleeve (5% of portfolio)
- Max 5 positions
- Max 30% per position ($15,000)
- 5% stop loss per position
- 15% max drawdown on sleeve
"""
import json
import logging
from datetime import datetime, date, timedelta
from typing import Optional
from pathlib import Path

import anthropic

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_MODEL_PREMIUM
from data.price_client import PriceClient
from data.macro_client import MacroClient

from agents.prompts.autonomous_agent import (
    SYSTEM_PROMPT,
    build_decision_prompt,
    AUTONOMOUS_STARTING_CAPITAL,
    AUTONOMOUS_MAX_POSITIONS,
    AUTONOMOUS_MAX_POSITION_PCT,
    AUTONOMOUS_STOP_LOSS_PCT,
    AUTONOMOUS_MAX_DRAWDOWN_PCT,
    MACRO_ETFS,
)

logger = logging.getLogger(__name__)


class AutonomousAgent:
    """
    Autonomous trading agent that manages a ring-fenced sleeve of the portfolio.
    Operates independently without human approval or CIO oversight.
    """

    def __init__(self, starting_capital: float = None, use_premium_model: bool = True):
        """
        Initialize the Autonomous Agent.

        Args:
            starting_capital: Initial capital for the sleeve (default $50,000)
            use_premium_model: Use premium Claude model for decisions
        """
        self.starting_capital = starting_capital or AUTONOMOUS_STARTING_CAPITAL
        self.prices = PriceClient()
        self.macro = MacroClient()
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = CLAUDE_MODEL_PREMIUM if use_premium_model else CLAUDE_MODEL

        # In-memory state (in production, load from database)
        self.positions = []
        self.cash = self.starting_capital
        self.decisions = []
        self.cycle_count = 0
        self.high_water_mark = self.starting_capital
        self.current_drawdown = 0.0

    @property
    def total_value(self) -> float:
        """Calculate total sleeve value (cash + positions)."""
        invested = sum(p.get('current_value', 0) for p in self.positions)
        return self.cash + invested

    @property
    def invested_value(self) -> float:
        """Calculate total invested value."""
        return sum(p.get('current_value', 0) for p in self.positions)

    @property
    def unrealized_pnl(self) -> float:
        """Calculate total unrealized P&L."""
        return sum(p.get('unrealized_pnl', 0) for p in self.positions)

    @property
    def unrealized_pnl_pct(self) -> float:
        """Calculate unrealized P&L as percentage."""
        if self.starting_capital == 0:
            return 0.0
        return (self.unrealized_pnl / self.starting_capital) * 100

    def update_positions(self) -> None:
        """Update current prices and P&L for all open positions."""
        for pos in self.positions:
            ticker = pos.get('ticker')
            current_price = self.prices.get_current_price(ticker)
            if current_price:
                pos['current_price'] = current_price
                pos['current_value'] = current_price * pos.get('shares', 0)

                entry_price = pos.get('entry_price', current_price)
                shares = pos.get('shares', 0)

                if pos.get('direction') == 'LONG':
                    pos['unrealized_pnl'] = (current_price - entry_price) * shares
                else:  # SHORT
                    pos['unrealized_pnl'] = (entry_price - current_price) * shares

                pos['unrealized_pnl_pct'] = ((current_price - entry_price) / entry_price) * 100
                pos['last_updated'] = datetime.utcnow().isoformat()

    def check_stop_losses(self) -> list:
        """Check if any positions have hit their stop loss."""
        triggered = []
        for pos in self.positions:
            if pos.get('direction') == 'LONG':
                if pos.get('current_price', float('inf')) <= pos.get('stop_loss', 0):
                    triggered.append(pos)
            else:  # SHORT
                if pos.get('current_price', 0) >= pos.get('stop_loss', float('inf')):
                    triggered.append(pos)
        return triggered

    def update_drawdown(self) -> None:
        """Update high water mark and current drawdown."""
        total = self.total_value
        if total > self.high_water_mark:
            self.high_water_mark = total
        self.current_drawdown = ((total - self.high_water_mark) / self.high_water_mark) * 100

    def get_sleeve_status(self) -> dict:
        """Get current sleeve status for decision prompt."""
        self.update_positions()
        self.update_drawdown()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "total_value": self.total_value,
            "cash": self.cash,
            "invested": self.invested_value,
            "unrealized_pnl": self.unrealized_pnl,
            "unrealized_pnl_pct": self.unrealized_pnl_pct,
            "daily_pnl": self.unrealized_pnl,  # Simplified for paper trading
            "cumulative_return_pct": ((self.total_value - self.starting_capital) / self.starting_capital) * 100,
            "drawdown_pct": self.current_drawdown,
            "num_positions": len(self.positions),
            "max_positions": AUTONOMOUS_MAX_POSITIONS,
        }

    def get_positions_for_prompt(self) -> list:
        """Format current positions for the decision prompt."""
        return [
            {
                "ticker": pos.get('ticker'),
                "direction": pos.get('direction', 'LONG'),
                "shares": pos.get('shares'),
                "entry_price": pos.get('entry_price'),
                "current_price": pos.get('current_price'),
                "current_value": pos.get('current_value'),
                "unrealized_pnl": pos.get('unrealized_pnl'),
                "unrealized_pnl_pct": pos.get('unrealized_pnl_pct'),
                "stop_loss": pos.get('stop_loss'),
                "target": pos.get('target'),
                "thesis": pos.get('thesis'),
                "invalidation": pos.get('invalidation'),
                "entry_date": pos.get('entry_date'),
            }
            for pos in self.positions
        ]

    def execute_buy(self, ticker: str, shares: int, price: float, thesis: str,
                    invalidation: str, target: float, time_horizon: str,
                    confidence: float, direction: str = "LONG") -> dict:
        """
        Execute a buy order (paper trading).

        Returns:
            Execution result dict
        """
        value = shares * price
        stop_loss = price * (1 - AUTONOMOUS_STOP_LOSS_PCT) if direction == "LONG" else price * (1 + AUTONOMOUS_STOP_LOSS_PCT)

        # Check if we have enough cash
        if value > self.cash:
            return {
                "status": "REJECTED",
                "reason": f"Insufficient cash. Required: ${value:,.2f}, Available: ${self.cash:,.2f}"
            }

        # Check position limit
        if len(self.positions) >= AUTONOMOUS_MAX_POSITIONS:
            return {
                "status": "REJECTED",
                "reason": f"Maximum positions reached ({AUTONOMOUS_MAX_POSITIONS})"
            }

        # Check position size limit
        max_position = self.total_value * AUTONOMOUS_MAX_POSITION_PCT
        if value > max_position:
            return {
                "status": "REJECTED",
                "reason": f"Position too large. Max: ${max_position:,.2f}, Requested: ${value:,.2f}"
            }

        # Execute
        self.cash -= value
        position = {
            "ticker": ticker,
            "direction": direction,
            "shares": shares,
            "entry_price": price,
            "current_price": price,
            "current_value": value,
            "unrealized_pnl": 0,
            "unrealized_pnl_pct": 0,
            "stop_loss": stop_loss,
            "target": target,
            "thesis": thesis,
            "invalidation": invalidation,
            "time_horizon": time_horizon,
            "confidence": confidence,
            "entry_date": datetime.utcnow().isoformat(),
        }
        self.positions.append(position)

        return {
            "status": "EXECUTED",
            "ticker": ticker,
            "action": "BUY",
            "direction": direction,
            "shares": shares,
            "price": price,
            "value": value,
            "stop_loss": stop_loss,
            "sleeve_cash_after": self.cash,
        }

    def execute_close(self, ticker: str, reason: str = "THESIS_INVALIDATED") -> dict:
        """
        Close a position (paper trading).

        Returns:
            Execution result dict
        """
        position = None
        for i, pos in enumerate(self.positions):
            if pos.get('ticker') == ticker:
                position = self.positions.pop(i)
                break

        if not position:
            return {
                "status": "REJECTED",
                "reason": f"No open position in {ticker}"
            }

        # Get current price
        current_price = self.prices.get_current_price(ticker) or position.get('current_price')
        shares = position.get('shares', 0)
        exit_value = current_price * shares

        # Calculate P&L
        entry_price = position.get('entry_price', current_price)
        if position.get('direction') == 'LONG':
            realized_pnl = (current_price - entry_price) * shares
        else:
            realized_pnl = (entry_price - current_price) * shares

        realized_pnl_pct = ((current_price - entry_price) / entry_price) * 100

        # Return cash
        self.cash += exit_value

        return {
            "status": "EXECUTED",
            "ticker": ticker,
            "action": "CLOSE",
            "reason": reason,
            "shares": shares,
            "entry_price": entry_price,
            "exit_price": current_price,
            "exit_value": exit_value,
            "realized_pnl": realized_pnl,
            "realized_pnl_pct": realized_pnl_pct,
            "sleeve_cash_after": self.cash,
        }

    def run_decision_cycle(
        self,
        desk_briefs: list = None,
        macro_brief: dict = None,
        thirteenf_flows: dict = None,
        insider_trades: list = None,
        material_events: list = None,
        technical_signals: dict = None,
    ) -> Optional[dict]:
        """
        Run a complete decision cycle.

        Args:
            desk_briefs: Recent sector desk briefs
            macro_brief: Latest Druckenmiller agent output
            thirteenf_flows: Institutional flow signals
            insider_trades: Recent Form 4 transactions
            material_events: Recent 8-K events
            technical_signals: Technical analysis signals

        Returns:
            Complete decision output or None if failed
        """
        self.cycle_count += 1
        logger.info(f"[Autonomous] Starting decision cycle #{self.cycle_count}")

        # 1. Update positions and check stops
        self.update_positions()
        stop_triggered = self.check_stop_losses()

        # Execute stop losses immediately
        stop_loss_executions = []
        for pos in stop_triggered:
            logger.warning(f"[Autonomous] STOP LOSS triggered for {pos['ticker']}")
            result = self.execute_close(pos['ticker'], reason="STOP_LOSS")
            stop_loss_executions.append(result)

        # 2. Get current sleeve status
        sleeve_status = self.get_sleeve_status()

        # 3. Get market data
        market_data = self._get_market_data()

        # 4. Build the decision prompt
        user_prompt = build_decision_prompt(
            current_positions=self.get_positions_for_prompt(),
            sleeve_status=sleeve_status,
            desk_briefs=desk_briefs,
            macro_brief=macro_brief,
            thirteenf_flows=thirteenf_flows,
            insider_trades=insider_trades,
            material_events=material_events,
            technical_signals=technical_signals,
            market_data=market_data,
            recent_decisions=self.decisions[-10:] if self.decisions else None,
        )

        # 5. Call Claude for decision
        logger.info(f"[Autonomous] Calling Claude for decision...")
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}]
            )
            raw_response = response.content[0].text
        except Exception as e:
            logger.error(f"[Autonomous] Claude API error: {e}")
            return None

        # 6. Parse response
        try:
            if "```json" in raw_response:
                json_str = raw_response.split("```json")[1].split("```")[0]
            elif "```" in raw_response:
                json_str = raw_response.split("```")[1].split("```")[0]
            else:
                json_str = raw_response

            decision = json.loads(json_str.strip())
        except json.JSONDecodeError as e:
            logger.error(f"[Autonomous] Failed to parse decision: {e}")
            logger.debug(f"Raw response: {raw_response[:500]}...")
            return None

        # 7. Execute decisions
        # CRITICAL: Always use real-time prices from yfinance, never Claude's suggested prices
        execution_log = stop_loss_executions.copy()

        for action in decision.get('decisions', []):
            action_type = action.get('action')
            ticker = action.get('ticker')

            if action_type == 'BUY':
                # ALWAYS fetch real price - never trust Claude's price
                real_price = self.prices.get_current_price(ticker)
                if not real_price:
                    execution_log.append({
                        "status": "REJECTED",
                        "ticker": ticker,
                        "reason": f"Could not fetch real-time price for {ticker}"
                    })
                    continue

                # Calculate shares based on Claude's target allocation
                # Claude suggests sleeve_allocation_pct (e.g., 30%)
                target_allocation_pct = action.get('sleeve_allocation_pct', 20) / 100
                target_value = self.total_value * target_allocation_pct

                # Cap at max position size
                max_position_value = self.total_value * AUTONOMOUS_MAX_POSITION_PCT
                target_value = min(target_value, max_position_value, self.cash)

                # Calculate shares at real price
                shares = int(target_value / real_price)
                if shares <= 0:
                    execution_log.append({
                        "status": "REJECTED",
                        "ticker": ticker,
                        "reason": f"Insufficient funds for minimum position. Price: ${real_price:.2f}"
                    })
                    continue

                actual_value = shares * real_price

                # Calculate target price based on Claude's suggested upside
                claude_target = action.get('target_price', 0)
                claude_price = action.get('price', real_price)
                if claude_price > 0 and claude_target > 0:
                    # Preserve Claude's expected return percentage
                    expected_return_pct = (claude_target - claude_price) / claude_price
                    target_price = real_price * (1 + expected_return_pct)
                else:
                    target_price = real_price * 1.15  # Default 15% target

                logger.info(f"[Autonomous] {ticker}: Claude suggested ${action.get('price', 0):.2f}, "
                           f"real price ${real_price:.2f}. Buying {shares} shares = ${actual_value:,.2f}")

                result = self.execute_buy(
                    ticker=ticker,
                    shares=shares,
                    price=real_price,
                    thesis=action.get('thesis', ''),
                    invalidation=action.get('invalidation', ''),
                    target=target_price,
                    time_horizon=action.get('time_horizon', '2-4 weeks'),
                    confidence=action.get('confidence', 0.7),
                    direction=action.get('direction', 'LONG'),
                )
                execution_log.append(result)

            elif action_type in ('CLOSE', 'SELL'):
                result = self.execute_close(ticker, reason=action.get('reason', 'DECISION'))
                execution_log.append(result)

        # 8. Update decision with execution results
        decision['execution_log'] = execution_log
        decision['cycle_number'] = self.cycle_count
        decision['model_used'] = self.model
        decision['analyzed_at'] = datetime.utcnow().isoformat()

        # Update sleeve status after execution
        decision['sleeve_status_after'] = self.get_sleeve_status()

        # Store decision
        self.decisions.append(decision)

        # Log summary
        executed = [e for e in execution_log if e.get('status') == 'EXECUTED']
        logger.info(f"[Autonomous] Cycle #{self.cycle_count} complete. Executed {len(executed)} trades.")
        logger.info(f"[Autonomous] Sleeve value: ${self.total_value:,.2f} ({self.unrealized_pnl_pct:+.2f}%)")

        return decision

    def _get_market_data(self) -> dict:
        """Fetch current market data for context."""
        return {
            "sp500": self.prices.get_current_price("^GSPC"),
            "sp500_change_pct": self.prices.get_returns("^GSPC", 1) or 0,
            "vix": self.prices.get_current_price("^VIX"),
            "dollar_index": self.prices.get_current_price("DX-Y.NYB"),
            "treasury_10y": None,  # Would come from FRED
            "gold": self.prices.get_current_price("GC=F"),
            "oil": self.prices.get_current_price("CL=F"),
        }

    def get_performance_summary(self) -> dict:
        """Get performance summary for dashboard."""
        self.update_positions()

        # Calculate win rate from closed trades
        closed_trades = [d for d in self.decisions if d.get('action') in ('CLOSE', 'STOP_LOSS')]
        wins = sum(1 for d in closed_trades if d.get('realized_pnl', 0) > 0)
        win_rate = wins / len(closed_trades) if closed_trades else 0

        return {
            "total_value": self.total_value,
            "starting_capital": self.starting_capital,
            "cash": self.cash,
            "invested": self.invested_value,
            "unrealized_pnl": self.unrealized_pnl,
            "unrealized_pnl_pct": self.unrealized_pnl_pct,
            "cumulative_return_pct": ((self.total_value - self.starting_capital) / self.starting_capital) * 100,
            "current_drawdown_pct": self.current_drawdown,
            "high_water_mark": self.high_water_mark,
            "num_positions": len(self.positions),
            "max_positions": AUTONOMOUS_MAX_POSITIONS,
            "decision_cycles": self.cycle_count,
            "total_trades": len([d for d in self.decisions if d.get('action') in ('BUY', 'SELL', 'CLOSE')]),
            "win_rate": win_rate,
            "positions": self.positions,
        }

    def save_state(self, filepath: str = None) -> None:
        """Save current state to file."""
        filepath = filepath or "autonomous_state.json"
        state = {
            "positions": self.positions,
            "cash": self.cash,
            "decisions": self.decisions,
            "cycle_count": self.cycle_count,
            "high_water_mark": self.high_water_mark,
            "starting_capital": self.starting_capital,
            "saved_at": datetime.utcnow().isoformat(),
        }
        with open(filepath, 'w') as f:
            json.dump(state, f, indent=2, default=str)
        logger.info(f"[Autonomous] State saved to {filepath}")

    def load_state(self, filepath: str = None) -> bool:
        """Load state from file."""
        filepath = filepath or "autonomous_state.json"
        try:
            with open(filepath, 'r') as f:
                state = json.load(f)
            self.positions = state.get('positions', [])
            self.cash = state.get('cash', self.starting_capital)
            self.decisions = state.get('decisions', [])
            self.cycle_count = state.get('cycle_count', 0)
            self.high_water_mark = state.get('high_water_mark', self.starting_capital)
            logger.info(f"[Autonomous] State loaded from {filepath}")
            return True
        except FileNotFoundError:
            logger.warning(f"[Autonomous] No state file found at {filepath}")
            return False
        except Exception as e:
            logger.error(f"[Autonomous] Failed to load state: {e}")
            return False


def run_autonomous_cycle(
    desk_briefs: list = None,
    macro_brief: dict = None,
    thirteenf_flows: dict = None,
    persist: bool = False,
) -> Optional[dict]:
    """
    Convenience function to run a single autonomous decision cycle.
    """
    agent = AutonomousAgent()
    agent.load_state()  # Try to load previous state

    decision = agent.run_decision_cycle(
        desk_briefs=desk_briefs,
        macro_brief=macro_brief,
        thirteenf_flows=thirteenf_flows,
    )

    if persist and decision:
        agent.save_state()
        # TODO: Also persist to database

    return decision


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    parser = argparse.ArgumentParser(description="ATLAS Autonomous Trading Agent")
    parser.add_argument("--test", action="store_true", help="Run with test data")
    parser.add_argument("--persist", action="store_true", help="Save state after run")
    parser.add_argument("--load", action="store_true", help="Load previous state")
    args = parser.parse_args()

    print("\n" + "="*70)
    print("ATLAS Autonomous Trading Agent")
    print("="*70 + "\n")

    agent = AutonomousAgent()

    if args.load:
        agent.load_state()

    # Sample test data
    test_desk_briefs = None
    test_macro_brief = None
    test_flows = None

    if args.test:
        test_desk_briefs = [
            {
                "desk": "Semiconductor",
                "ticker": "AVGO",
                "signal": "BULLISH",
                "confidence": 0.88,
                "brief_for_cio": "VMware integration exceeding expectations. Data center revenue +28% YoY. AI infrastructure demand strong.",
            },
            {
                "desk": "Semiconductor",
                "ticker": "TSM",
                "signal": "BULLISH",
                "confidence": 0.85,
                "brief_for_cio": "AI chip demand accelerating. Advanced node capacity constrained. Raising capex guidance.",
            },
            {
                "desk": "Biotech",
                "ticker": "LLY",
                "signal": "BULLISH",
                "confidence": 0.82,
                "brief_for_cio": "GLP-1 franchise continues to exceed expectations. Mounjaro supply constraints easing.",
            },
        ]

        test_macro_brief = {
            "liquidity_regime": "NEUTRAL",
            "cycle_position": "LATE",
            "portfolio_tilt": "NEUTRAL",
            "conviction_level": 0.6,
            "headline": "No fat pitch, but AI infrastructure theme remains intact.",
            "conviction_calls": [
                {
                    "direction": "LONG",
                    "sector_or_instrument": "Semiconductors",
                    "thesis": "AI capex cycle extending through 2026",
                }
            ],
        }

        test_flows = {
            "consensus_builds": [
                {"ticker": "TSM", "funds": ["Duquesne", "Tiger Global", "Coatue"]},
                {"ticker": "AVGO", "funds": ["Appaloosa", "Viking"]},
            ],
            "crowding_warnings": [
                {"ticker": "NVDA", "funds_holding": 14},
            ],
            "contrarian_signals": [],
        }

    # Run decision cycle
    decision = agent.run_decision_cycle(
        desk_briefs=test_desk_briefs,
        macro_brief=test_macro_brief,
        thirteenf_flows=test_flows,
    )

    if decision:
        print("\n" + "="*70)
        print("DECISION OUTPUT")
        print("="*70)

        print(f"\nCycle #{decision.get('cycle_number', 'N/A')}")

        sleeve = decision.get('sleeve_status', {})
        print(f"\nSLEEVE STATUS:")
        print(f"  Total Value: ${sleeve.get('total_value', 0):,.2f}")
        print(f"  Cash: ${sleeve.get('cash', 0):,.2f}")
        print(f"  Invested: ${sleeve.get('invested', 0):,.2f}")
        print(f"  P&L: {sleeve.get('unrealized_pnl_pct', 0):+.2f}%")
        print(f"  Drawdown: {sleeve.get('drawdown_pct', 0):.2f}%")

        if decision.get('decisions'):
            print(f"\nDECISIONS:")
            for d in decision['decisions']:
                print(f"  - {d.get('action')} {d.get('ticker')}: {d.get('shares', 0)} shares @ ${d.get('price', 0):.2f}")
                print(f"    Thesis: {d.get('thesis', '')[:80]}...")
                print(f"    Confidence: {d.get('confidence', 0):.0%}")

        if decision.get('execution_log'):
            print(f"\nEXECUTION LOG:")
            for e in decision['execution_log']:
                status = e.get('status', 'UNKNOWN')
                if status == 'EXECUTED':
                    print(f"  - {e.get('action')} {e.get('ticker')}: {e.get('shares')} @ ${e.get('price', 0):.2f} [EXECUTED]")
                else:
                    print(f"  - {e.get('action', 'N/A')} {e.get('ticker', 'N/A')}: [{status}] {e.get('reason', '')}")

        print("\n" + "="*70)
        print("PERFORMANCE SUMMARY")
        print("="*70)
        perf = agent.get_performance_summary()
        print(f"  Sleeve Value: ${perf['total_value']:,.2f}")
        print(f"  Starting Capital: ${perf['starting_capital']:,.2f}")
        print(f"  Cumulative Return: {perf['cumulative_return_pct']:+.2f}%")
        print(f"  Current Drawdown: {perf['current_drawdown_pct']:.2f}%")
        print(f"  Positions: {perf['num_positions']}/{perf['max_positions']}")
        print(f"  Decision Cycles: {perf['decision_cycles']}")

        if args.persist:
            agent.save_state()

        print("\n" + "="*70)
        print("FULL JSON OUTPUT")
        print("="*70)
        print(json.dumps(decision, indent=2, default=str))

    else:
        print("Decision cycle failed. Check logs for details.")
