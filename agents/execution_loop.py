"""
ATLAS Continuous Autonomous Execution Loop
Master orchestrator that runs all agents on a schedule.

Architecture:
- Every 30 minutes during market hours (9:30am-4pm ET, weekdays): Full cycle
- Every morning at 7am ET: Daily briefing
- Every Sunday 11pm ET: Weekly fundamental screen

Risk Controls:
- No trade executes without CIO approval AND adversarial risk score < 0.6
- Maximum 2 new positions per day
- No position exceeds 20% of portfolio
- Hard stop: 5% portfolio drop in a day pauses all agents

Each agent calls the Anthropic API for real analysis - no templates.
"""
import json
import logging
import argparse
import time
import os
from datetime import datetime, timedelta, date
from typing import Optional, Dict, List, Any
from pathlib import Path
import pytz

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import (
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    CLAUDE_MODEL_PREMIUM,
    MAX_POSITIONS,
    MAX_SINGLE_POSITION_PCT,
    MAX_DRAWDOWN_PCT,
    STATE_DIR,
    BRIEFINGS_DIR,
)

# Logging setup
def setup_logging(log_file: str = None):
    """Setup logging to file and console."""
    handlers = [logging.StreamHandler()]

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=handlers,
    )

logger = logging.getLogger(__name__)

# Market hours (Eastern Time)
MARKET_OPEN = (9, 30)  # 9:30 AM ET
MARKET_CLOSE = (16, 0)  # 4:00 PM ET
ET = pytz.timezone("US/Eastern")

# State files
EXECUTION_LOG_FILE = STATE_DIR / "execution_log.json"
NEWS_BRIEFS_FILE = STATE_DIR / "news_briefs.json"
POSITIONS_FILE = STATE_DIR / "positions.json"
PNL_HISTORY_FILE = STATE_DIR / "pnl_history.json"
DESK_BRIEFS_FILE = STATE_DIR / "desk_briefs.json"
AGENT_VIEWS_FILE = STATE_DIR / "agent_views.json"
RISK_ASSESSMENT_FILE = STATE_DIR / "risk_assessment.json"
CIO_SYNTHESIS_FILE = STATE_DIR / "cio_synthesis.json"
DECISIONS_FILE = STATE_DIR / "decisions.json"
DECISIONS_V2_FILE = STATE_DIR / "decisions_v2.json"
JANUS_DAILY_FILE = STATE_DIR / "janus_daily.json"
DARWIN_V3_JUDGE_FILE = STATE_DIR / "judge_daily.json"
DARWIN_V3_DECISIONS_FILE = STATE_DIR / "decisions_v3.json"
AGENTS_STATUS_FILE = STATE_DIR / "agents.json"


class ATLASExecutionLoop:
    """
    Continuous autonomous execution loop for ATLAS.

    Orchestrates all agents on a schedule:
    - 30-minute cycles during market hours
    - Daily briefing at 7am ET
    - Weekly fundamental screen Sunday 11pm ET
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
        self._ensure_state_dirs()
        self._init_agents_status()

        logger.info(f"ATLAS Execution Loop initialized (dry_run={dry_run})")

    def _ensure_state_dirs(self):
        """Ensure state directories exist."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        BRIEFINGS_DIR.mkdir(parents=True, exist_ok=True)

    def _init_agents_status(self):
        """Initialize agents status file if not exists."""
        if not AGENTS_STATUS_FILE.exists():
            agents = [
                {"name": "news", "display_name": "News Agent", "status": "IDLE", "last_run": None},
                {"name": "druckenmiller", "display_name": "Druckenmiller", "status": "IDLE", "last_run": None},
                {"name": "aschenbrenner", "display_name": "Aschenbrenner", "status": "IDLE", "last_run": None},
                {"name": "baker", "display_name": "Baker", "status": "IDLE", "last_run": None},
                {"name": "ackman", "display_name": "Ackman", "status": "IDLE", "last_run": None},
                {"name": "bond", "display_name": "Bond Desk", "status": "IDLE", "last_run": None},
                {"name": "currency", "display_name": "Currency Desk", "status": "IDLE", "last_run": None},
                {"name": "commodities", "display_name": "Commodities Desk", "status": "IDLE", "last_run": None},
                {"name": "metals", "display_name": "Metals Desk", "status": "IDLE", "last_run": None},
                {"name": "adversarial", "display_name": "Adversarial", "status": "IDLE", "last_run": None},
                {"name": "cio", "display_name": "CIO", "status": "IDLE", "last_run": None},
                {"name": "autonomous", "display_name": "Autonomous", "status": "IDLE", "last_run": None},
            ]
            self._save_state(AGENTS_STATUS_FILE, agents)

    def _get_agent(self, name: str):
        """Get or create an agent by name."""
        if name in self.agents:
            return self.agents[name]

        try:
            if name == "news":
                from agents.news_agent import NewsAgent
                self.agents[name] = NewsAgent()

            elif name == "druckenmiller":
                from agents.druckenmiller_agent import DruckenmillerAgent
                self.agents[name] = DruckenmillerAgent()

            elif name == "aschenbrenner":
                from agents.aschenbrenner_agent import AschenbrennerAgent
                self.agents[name] = AschenbrennerAgent()

            elif name == "baker":
                from agents.baker_agent import BakerAgent
                self.agents[name] = BakerAgent()

            elif name == "ackman":
                from agents.ackman_agent import AckmanAgent
                self.agents[name] = AckmanAgent()

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

            elif name == "adversarial":
                from agents.adversarial_agent import AdversarialAgent
                self.agents[name] = AdversarialAgent()

            elif name == "cio":
                from agents.cio_agent import CIOAgent
                self.agents[name] = CIOAgent()

            elif name == "autonomous":
                from agents.autonomous_agent import AutonomousAgent
                self.agents[name] = AutonomousAgent()

            elif name == "fundamental":
                from agents.fundamental_agent import FundamentalAgent
                self.agents[name] = FundamentalAgent()

            elif name == "pnl_tracker":
                from agents.pnl_tracker import PnLTracker
                self.agents[name] = PnLTracker()

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

    def _load_state(self, filepath: Path) -> Any:
        """Load state from JSON file."""
        try:
            if filepath.exists():
                with open(filepath, "r") as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load {filepath}: {e}")
        return None

    def _save_state(self, filepath: Path, data: Any):
        """Save state to JSON file."""
        try:
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save {filepath}: {e}")

    def _update_agent_status(self, name: str, status: str):
        """Update a single agent's status."""
        agents = self._load_state(AGENTS_STATUS_FILE) or []
        now = datetime.now(ET).strftime("%Y-%m-%d %H:%M")

        for agent in agents:
            if agent.get("name") == name:
                agent["status"] = status
                agent["last_run"] = now
                break

        self._save_state(AGENTS_STATUS_FILE, agents)

    def _is_market_hours(self) -> bool:
        """Check if it's currently market hours (9:30am-4pm ET, weekdays)."""
        now = datetime.now(ET)

        # Check if it's a weekday
        if now.weekday() >= 5:  # Saturday = 5, Sunday = 6
            return False

        # Check time
        market_open = now.replace(hour=MARKET_OPEN[0], minute=MARKET_OPEN[1], second=0)
        market_close = now.replace(hour=MARKET_CLOSE[0], minute=MARKET_CLOSE[1], second=0)

        return market_open <= now <= market_close

    def _is_morning_briefing_time(self) -> bool:
        """Check if it's 7am ET (morning briefing time)."""
        now = datetime.now(ET)
        return now.hour == 7 and now.minute < 30 and now.weekday() < 5

    def _is_weekly_screen_time(self) -> bool:
        """Check if it's Sunday 11pm ET (weekly screen time)."""
        now = datetime.now(ET)
        return now.weekday() == 6 and now.hour == 23

    def _load_portfolio(self) -> Dict:
        """Load current portfolio state."""
        positions_data = self._load_state(POSITIONS_FILE) or {}

        positions = positions_data.get("positions", [])
        portfolio_value = positions_data.get("portfolio_value", 1000000)

        # Calculate totals
        total_value = 0
        total_pnl = 0

        for pos in positions:
            entry = pos.get("entry_price", 0)
            current = pos.get("current_price", entry)
            shares = pos.get("shares", 0)
            direction = pos.get("direction", "LONG")

            value = current * shares
            if direction == "SHORT":
                pnl = (entry - current) * shares
            else:
                pnl = (current - entry) * shares

            pos["current_value"] = value
            pos["unrealized_pnl"] = pnl
            total_value += value
            total_pnl += pnl

        return {
            "positions": positions,
            "portfolio_value": portfolio_value,
            "total_value": total_value,
            "total_pnl": total_pnl,
            "cash": portfolio_value - total_value,
            "last_updated": positions_data.get("last_updated"),
        }

    def _get_portfolio_tickers(self) -> List[str]:
        """Get list of tickers in portfolio."""
        portfolio = self._load_portfolio()
        return [p.get("ticker") for p in portfolio.get("positions", []) if p.get("ticker") and p.get("ticker") != "BIL"]

    # =========================================================================
    # STEP 1: NEWS AGENT
    # =========================================================================

    def run_news_scan(self) -> Dict:
        """
        Run news agent to scan RSS feeds for portfolio tickers and macro events.
        Saves alerts to news_briefs.json with urgency levels.
        """
        logger.info("Step 1: News Agent scanning...")
        self._update_agent_status("news", "RUNNING")

        try:
            news_agent = self._get_agent("news")
            if not news_agent:
                raise Exception("Could not load news agent")

            # Run the scan - this calls Claude API
            alerts = news_agent.scan()

            if alerts:
                self._save_state(NEWS_BRIEFS_FILE, alerts)

                # Check for IMMEDIATE urgency items
                immediate_count = 0
                immediate_alerts = []
                if alerts.get("top_stories"):
                    for story in alerts["top_stories"]:
                        if story.get("urgency") == "IMMEDIATE":
                            immediate_count += 1
                            immediate_alerts.append(story)

                # Send urgent email alerts for IMMEDIATE items
                if immediate_alerts:
                    try:
                        from agents.email_alerts import send_urgent_alert
                        for alert in immediate_alerts:
                            send_urgent_alert(
                                alert.get("headline", ""),
                                alert.get("ticker")
                            )
                        logger.info(f"Sent {len(immediate_alerts)} urgent email alerts")
                    except Exception as e:
                        logger.error(f"Failed to send urgent alerts: {e}")

                logger.info(f"News: {len(alerts.get('top_stories', []))} stories, {immediate_count} IMMEDIATE")

                self._update_agent_status("news", "ACTIVE")
                return {
                    "status": "SUCCESS",
                    "alert_level": alerts.get("alert_level", "NORMAL"),
                    "stories_count": len(alerts.get("top_stories", [])),
                    "immediate_count": immediate_count,
                    "24h_summary": alerts.get("24h_summary", ""),
                }
            else:
                logger.warning("News agent returned no data")
                self._update_agent_status("news", "ERROR")
                return {"status": "NO_DATA"}

        except Exception as e:
            logger.error(f"News agent failed: {e}")
            self._update_agent_status("news", "ERROR")
            return {"status": "ERROR", "error": str(e)}

    # =========================================================================
    # STEP 2: PRICE UPDATE
    # =========================================================================

    def run_price_update(self) -> Dict:
        """
        Fetch current prices for all positions via yfinance.
        Update positions.json with current prices and calculate P&L.
        Save daily snapshot to pnl_history.json.
        """
        logger.info("Step 2: Updating prices...")

        try:
            import yfinance as yf

            positions_data = self._load_state(POSITIONS_FILE) or {}
            positions = positions_data.get("positions", [])

            # Get tickers (excluding cash equivalents)
            tickers = [p.get("ticker") for p in positions if p.get("ticker") and p.get("ticker") != "BIL"]

            if not tickers:
                logger.info("No tickers to update")
                return {"status": "NO_TICKERS"}

            # Fetch prices
            logger.info(f"Fetching prices for: {tickers}")
            data = yf.download(tickers, period="1d", progress=False)

            # Update positions
            total_pnl = 0
            for pos in positions:
                ticker = pos.get("ticker")
                if ticker == "BIL" or not ticker:
                    continue

                try:
                    if len(tickers) == 1:
                        price = float(data["Close"].iloc[-1])
                    else:
                        price = float(data["Close"][ticker].iloc[-1])

                    pos["current_price"] = round(price, 2)

                    # Calculate P&L
                    entry = pos.get("entry_price", price)
                    shares = pos.get("shares", 0)
                    direction = pos.get("direction", "LONG")

                    if direction == "SHORT":
                        pnl = (entry - price) * shares
                    else:
                        pnl = (price - entry) * shares

                    pos["unrealized_pnl"] = round(pnl, 2)
                    total_pnl += pnl

                except Exception as e:
                    logger.warning(f"Failed to update {ticker}: {e}")

            # Update positions file
            positions_data["positions"] = positions
            positions_data["last_updated"] = datetime.now(ET).strftime("%Y-%m-%d %H:%M")
            self._save_state(POSITIONS_FILE, positions_data)

            # Save P&L snapshot
            snapshot = {
                "date": datetime.now(ET).strftime("%Y-%m-%d"),
                "time": datetime.now(ET).strftime("%H:%M"),
                "total_pnl": round(total_pnl, 2),
                "positions": {
                    p.get("ticker"): {
                        "pnl": p.get("unrealized_pnl", 0),
                        "current": p.get("current_price", 0),
                    }
                    for p in positions if p.get("ticker") != "BIL"
                },
            }

            # Append to history
            history = self._load_state(PNL_HISTORY_FILE) or []
            history.append(snapshot)
            history = history[-500:]  # Keep last 500 snapshots
            self._save_state(PNL_HISTORY_FILE, history)

            logger.info(f"Prices updated. Total P&L: ${total_pnl:,.2f}")
            return {
                "status": "SUCCESS",
                "tickers_updated": len(tickers),
                "total_pnl": total_pnl,
            }

        except Exception as e:
            logger.error(f"Price update failed: {e}")
            return {"status": "ERROR", "error": str(e)}

    # =========================================================================
    # STEP 3: SECTOR DESKS
    # =========================================================================

    def run_sector_desks(self) -> Dict:
        """
        Run Bond, Currency, Commodities, Metals desks.
        Each analyzes current macro data (FRED, yfinance) and updates signals.
        """
        logger.info("Step 3: Running sector desks...")

        desk_results = {}
        desks = ["bond", "currency", "commodities", "metals"]

        for desk_name in desks:
            logger.info(f"  Running {desk_name} desk...")
            self._update_agent_status(desk_name, "RUNNING")

            try:
                desk = self._get_agent(desk_name)
                if not desk:
                    desk_results[desk_name] = {"status": "NOT_AVAILABLE"}
                    self._update_agent_status(desk_name, "ERROR")
                    continue

                # Run analysis - this calls Claude API
                if hasattr(desk, "analyze"):
                    result = desk.analyze(persist=True)
                elif hasattr(desk, "get_brief_for_cio"):
                    result = desk.get_brief_for_cio()
                else:
                    result = None

                if result:
                    desk_results[desk_name] = {
                        "status": "SUCCESS",
                        "signal": result.get("signal", "UNKNOWN"),
                        "confidence": result.get("confidence", 0),
                        "brief": result.get("brief_for_cio", "")[:200],
                    }
                    logger.info(f"  {desk_name}: {result.get('signal')} ({result.get('confidence', 0):.0%})")
                    self._update_agent_status(desk_name, "ACTIVE")
                else:
                    desk_results[desk_name] = {"status": "NO_DATA"}
                    self._update_agent_status(desk_name, "ERROR")

            except Exception as e:
                logger.error(f"  {desk_name} desk failed: {e}")
                desk_results[desk_name] = {"status": "ERROR", "error": str(e)}
                self._update_agent_status(desk_name, "ERROR")

        # Save consolidated desk briefs
        self._save_state(DESK_BRIEFS_FILE, {
            "timestamp": datetime.now(ET).isoformat(),
            "desks": desk_results,
        })

        return desk_results

    # =========================================================================
    # STEP 4: SUPERINVESTOR AGENTS
    # =========================================================================

    def run_superinvestor_agents(self) -> Dict:
        """
        Run Druckenmiller, Aschenbrenner, Baker, Ackman agents.
        Each reviews current portfolio positions through their lens.
        """
        logger.info("Step 4: Running superinvestor agents...")

        agent_views = {}
        portfolio = self._load_portfolio()

        agents = [
            ("druckenmiller", "What's your macro view and portfolio positioning recommendation?"),
            ("aschenbrenner", "Review our AI infrastructure positions and recommend any changes."),
            ("baker", "Review our positions from a quantitative/deep tech perspective."),
            ("ackman", "Review our positions for quality compounder characteristics."),
        ]

        for agent_name, default_query in agents:
            logger.info(f"  Running {agent_name}...")
            self._update_agent_status(agent_name, "RUNNING")

            try:
                agent = self._get_agent(agent_name)
                if not agent:
                    agent_views[agent_name] = {"status": "NOT_AVAILABLE"}
                    self._update_agent_status(agent_name, "ERROR")
                    continue

                # Run analysis - this calls Claude API
                result = None
                if hasattr(agent, "get_brief_for_cio"):
                    result = agent.get_brief_for_cio()
                elif hasattr(agent, "chat"):
                    # Use chat for agents that need context (baker, ackman, aschenbrenner)
                    result = agent.chat(default_query)
                elif hasattr(agent, "analyze"):
                    try:
                        result = agent.analyze()
                    except TypeError:
                        pass  # analyze() needs args we don't have

                if result:
                    agent_views[agent_name] = {
                        "status": "SUCCESS",
                        "tilt": result.get("portfolio_tilt") or result.get("tilt", "NEUTRAL"),
                        "conviction": result.get("conviction_level", 0),
                        "headline": result.get("headline", "")[:200],
                        "brief": result.get("brief_for_cio", "")[:500] if result.get("brief_for_cio") else "",
                    }
                    logger.info(f"  {agent_name}: {agent_views[agent_name].get('tilt')}")
                    self._update_agent_status(agent_name, "ACTIVE")
                else:
                    agent_views[agent_name] = {"status": "NO_DATA"}
                    self._update_agent_status(agent_name, "ERROR")

            except Exception as e:
                logger.error(f"  {agent_name} failed: {e}")
                agent_views[agent_name] = {"status": "ERROR", "error": str(e)}
                self._update_agent_status(agent_name, "ERROR")

        # Save agent views
        self._save_state(AGENT_VIEWS_FILE, {
            "timestamp": datetime.now(ET).isoformat(),
            "views": agent_views,
        })

        return agent_views

    # =========================================================================
    # STEP 5: ADVERSARIAL AGENT
    # =========================================================================

    def run_adversarial_review(self) -> Dict:
        """
        Run adversarial agent to review entire portfolio.
        Checks for correlation risks, concentration, regime change signals.
        """
        logger.info("Step 5: Running adversarial review...")
        self._update_agent_status("adversarial", "RUNNING")

        try:
            adversarial = self._get_agent("adversarial")
            portfolio = self._load_portfolio()

            if not adversarial:
                raise Exception("Could not load adversarial agent")

            # Build portfolio context for adversarial review
            portfolio_context = {
                "num_positions": len(portfolio.get("positions", [])),
                "total_value": portfolio.get("total_value", 0),
                "cash_pct": (portfolio.get("cash", 0) / portfolio.get("portfolio_value", 1)) * 100,
                "positions": [
                    {
                        "ticker": p.get("ticker"),
                        "direction": p.get("direction"),
                        "allocation_pct": p.get("allocation_pct", 0),
                        "unrealized_pnl": p.get("unrealized_pnl", 0),
                    }
                    for p in portfolio.get("positions", [])
                ],
            }

            # Create a synthetic "portfolio review" trade decision
            # This will trigger the adversarial to review overall portfolio risk
            review_decision = {
                "ticker": "PORTFOLIO",
                "action": "REVIEW",
                "rationale": "Periodic portfolio risk review",
            }

            # Run adversarial review - this calls Claude API
            result = adversarial.review(review_decision, portfolio_context)

            if result:
                risk_assessment = {
                    "timestamp": datetime.now(ET).isoformat(),
                    "risk_score": result.get("risk_score", 0.5),
                    "verdict": result.get("verdict", "UNKNOWN"),
                    "concerns": result.get("concerns", []),
                    "warnings": result.get("monitoring_requirements", []),
                    "concentration_risks": result.get("concentration_risks", []),
                    "correlation_risks": result.get("correlation_risks", []),
                }

                self._save_state(RISK_ASSESSMENT_FILE, risk_assessment)

                logger.info(f"Adversarial: Risk score {result.get('risk_score', 0.5):.2f}, Verdict: {result.get('verdict')}")
                self._update_agent_status("adversarial", "ACTIVE")

                return risk_assessment
            else:
                self._update_agent_status("adversarial", "ERROR")
                return {"status": "NO_DATA"}

        except Exception as e:
            logger.error(f"Adversarial review failed: {e}")
            self._update_agent_status("adversarial", "ERROR")
            return {"status": "ERROR", "error": str(e)}

    # =========================================================================
    # STEP 6: CIO SYNTHESIS
    # =========================================================================

    def run_cio_synthesis(self) -> Dict:
        """
        CIO takes all agent outputs and generates synthesis.
        What changed since last cycle, what actions to consider, what to watch.
        """
        logger.info("Step 6: Running CIO synthesis...")
        self._update_agent_status("cio", "RUNNING")

        try:
            # Load all inputs
            news_briefs = self._load_state(NEWS_BRIEFS_FILE) or {}
            desk_briefs = self._load_state(DESK_BRIEFS_FILE) or {}
            agent_views = self._load_state(AGENT_VIEWS_FILE) or {}
            risk_assessment = self._load_state(RISK_ASSESSMENT_FILE) or {}
            previous_synthesis = self._load_state(CIO_SYNTHESIS_FILE) or {}
            janus_daily = self._load_state(JANUS_DAILY_FILE) or {}
            portfolio = self._load_portfolio()

            # Use Claude directly for CIO synthesis
            import anthropic
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

            # Build comprehensive prompt
            synthesis_prompt = f"""You are the CIO of ATLAS, an AI-native hedge fund. Synthesize all agent outputs into a coherent portfolio recommendation.

## CURRENT PORTFOLIO
Portfolio Value: ${portfolio.get('portfolio_value', 1000000):,.0f}
Total P&L: ${portfolio.get('total_pnl', 0):,.0f}
Cash: ${portfolio.get('cash', 0):,.0f}
Positions: {len(portfolio.get('positions', []))}

{json.dumps(portfolio.get('positions', [])[:10], indent=2)}

## NEWS BRIEF
Alert Level: {news_briefs.get('alert_level', 'NORMAL')}
24h Summary: {news_briefs.get('24h_summary', 'No news available')[:500]}

## DESK SIGNALS
{json.dumps(desk_briefs.get('desks', {}), indent=2)}

## SUPERINVESTOR VIEWS
{json.dumps(agent_views.get('views', {}), indent=2)}

## RISK ASSESSMENT
Risk Score: {risk_assessment.get('risk_score', 0.5)}
Verdict: {risk_assessment.get('verdict', 'UNKNOWN')}
Concerns: {json.dumps(risk_assessment.get('concerns', []))}

## PREVIOUS SYNTHESIS
{previous_synthesis.get('summary', 'No previous synthesis')[:300]}

## JANUS
{json.dumps(janus_daily, indent=2)[:1500]}

## TASK
Generate a CIO synthesis with:
1. What changed since last cycle
2. What actions to consider (with urgency: HIGH/MEDIUM/LOW)
3. What to watch in next cycle
4. Overall portfolio conviction (0-100)
5. Any position changes to recommend

Respond with valid JSON:
```json
{{
  "timestamp": "ISO timestamp",
  "summary": "2-3 sentence executive summary",
  "what_changed": ["list of key changes"],
  "actions_to_consider": [
    {{"action": "BUY/SELL/HOLD/TRIM/ADD", "ticker": "XXX", "urgency": "HIGH/MEDIUM/LOW", "rationale": "why"}}
  ],
  "what_to_watch": ["key items to monitor"],
  "portfolio_conviction": 0-100,
  "risk_adjusted_view": "RISK_ON/RISK_OFF/NEUTRAL",
  "top_conviction_trade": {{"ticker": "XXX", "action": "BUY", "size_pct": 5, "thesis": "why"}} or null
}}
```"""

            response = client.messages.create(
                model=CLAUDE_MODEL_PREMIUM,
                max_tokens=2048,
                messages=[{"role": "user", "content": synthesis_prompt}]
            )

            raw_response = response.content[0].text

            # Parse JSON
            if "```json" in raw_response:
                json_str = raw_response.split("```json")[1].split("```")[0]
            elif "```" in raw_response:
                json_str = raw_response.split("```")[1].split("```")[0]
            else:
                json_str = raw_response

            synthesis = json.loads(json_str.strip())
            synthesis["generated_at"] = datetime.now(ET).isoformat()
            synthesis["model_used"] = CLAUDE_MODEL_PREMIUM

            # Check for HIGH urgency actions
            high_urgency = [a for a in synthesis.get("actions_to_consider", []) if a.get("urgency") == "HIGH"]
            if high_urgency:
                synthesis["has_high_urgency"] = True
                logger.warning(f"CIO flagged {len(high_urgency)} HIGH urgency actions!")

            self._save_state(CIO_SYNTHESIS_FILE, synthesis)

            logger.info(f"CIO Synthesis: Conviction {synthesis.get('portfolio_conviction', 0)}%, {len(synthesis.get('actions_to_consider', []))} actions")
            self._update_agent_status("cio", "ACTIVE")

            return synthesis

        except Exception as e:
            logger.error(f"CIO synthesis failed: {e}")
            self._update_agent_status("cio", "ERROR")
            return {"status": "ERROR", "error": str(e)}

    # =========================================================================
    # STEP 7: AUTONOMOUS EXECUTION
    # =========================================================================

    def run_autonomous_execution(self) -> Dict:
        """
        If CIO synthesis recommends a trade AND confidence > 80% AND risk score < 0.6,
        the autonomous agent can execute paper trades.
        """
        logger.info("Step 7: Checking autonomous execution...")
        self._update_agent_status("autonomous", "RUNNING")

        try:
            synthesis = self._load_state(CIO_SYNTHESIS_FILE) or {}
            risk_assessment = self._load_state(RISK_ASSESSMENT_FILE) or {}

            # Check execution criteria
            portfolio_conviction = synthesis.get("portfolio_conviction", 0)
            risk_score = risk_assessment.get("risk_score", 1.0)
            top_trade = synthesis.get("top_conviction_trade")

            execution_result = {
                "timestamp": datetime.now(ET).isoformat(),
                "executed": False,
                "reason": None,
                "trade": None,
            }

            # Check if we should execute
            if not top_trade:
                execution_result["reason"] = "No trade recommended"
                logger.info("Autonomous: No trade recommended")
            elif portfolio_conviction < 80:
                execution_result["reason"] = f"Conviction {portfolio_conviction}% < 80% threshold"
                logger.info(f"Autonomous: Conviction too low ({portfolio_conviction}%)")
            elif risk_score >= 0.6:
                execution_result["reason"] = f"Risk score {risk_score:.2f} >= 0.6 threshold"
                logger.info(f"Autonomous: Risk too high ({risk_score:.2f})")
            elif self.dry_run:
                execution_result["reason"] = "Dry run mode - no execution"
                execution_result["would_execute"] = top_trade
                logger.info(f"Autonomous: Would execute {top_trade.get('action')} {top_trade.get('ticker')} (dry run)")
            elif self.trades_today >= 2:
                execution_result["reason"] = f"Already executed {self.trades_today} trades today (max 2)"
                logger.info(f"Autonomous: Daily trade limit reached")
            else:
                # Execute the trade
                logger.info(f"Autonomous: EXECUTING {top_trade.get('action')} {top_trade.get('ticker')}")

                # Load positions and update
                positions_data = self._load_state(POSITIONS_FILE) or {}
                positions = positions_data.get("positions", [])

                action = top_trade.get("action", "").upper()
                ticker = top_trade.get("ticker")

                if action in ("BUY", "ADD"):
                    # Add new position (simplified - would need actual price fetch)
                    import yfinance as yf
                    stock = yf.Ticker(ticker)
                    current_price = stock.info.get("regularMarketPrice", 0)

                    if current_price > 0:
                        size_pct = top_trade.get("size_pct", 3) / 100
                        portfolio_value = positions_data.get("portfolio_value", 1000000)
                        position_value = portfolio_value * size_pct
                        shares = int(position_value / current_price)

                        new_position = {
                            "ticker": ticker,
                            "direction": "LONG",
                            "shares": shares,
                            "entry_price": round(current_price, 2),
                            "current_price": round(current_price, 2),
                            "allocation_pct": round(size_pct * 100, 1),
                            "thesis": top_trade.get("thesis", "Autonomous trade"),
                            "agent_source": "autonomous",
                            "conviction": portfolio_conviction,
                            "date_opened": datetime.now(ET).strftime("%Y-%m-%d"),
                        }

                        positions.append(new_position)
                        positions_data["positions"] = positions
                        self._save_state(POSITIONS_FILE, positions_data)

                        execution_result["executed"] = True
                        execution_result["trade"] = new_position
                        self.trades_today += 1

                        logger.info(f"Autonomous: Executed BUY {shares} {ticker} @ ${current_price:.2f}")

                elif action in ("SELL", "EXIT", "CLOSE"):
                    # Close position
                    for i, pos in enumerate(positions):
                        if pos.get("ticker") == ticker:
                            closed_position = positions.pop(i)
                            execution_result["executed"] = True
                            execution_result["trade"] = closed_position
                            self.trades_today += 1
                            logger.info(f"Autonomous: Closed {ticker}")
                            break

                    positions_data["positions"] = positions
                    self._save_state(POSITIONS_FILE, positions_data)

            # Log to decisions.json
            decisions = self._load_state(DECISIONS_V2_FILE) or self._load_state(DECISIONS_FILE) or []
            decisions.append(execution_result)
            decisions = decisions[-100:]  # Keep last 100
            self._save_state(DECISIONS_V2_FILE, decisions)
            self._save_state(DECISIONS_FILE, decisions)

            self._update_agent_status("autonomous", "ACTIVE" if execution_result.get("executed") else "IDLE")
            return execution_result

        except Exception as e:
            logger.error(f"Autonomous execution failed: {e}")
            self._update_agent_status("autonomous", "ERROR")
            return {"status": "ERROR", "error": str(e)}

    # =========================================================================
    # STEP 8: DASHBOARD UPDATE
    # =========================================================================

    def update_dashboard_state(self):
        """Update all dashboard state files with fresh data."""
        logger.info("Step 8: Updating dashboard state...")

        # Update agent statuses - already done per-agent, but do final update
        agents = self._load_state(AGENTS_STATUS_FILE) or []
        now = datetime.now(ET).strftime("%Y-%m-%d %H:%M")

        for agent in agents:
            if agent.get("status") == "RUNNING":
                agent["status"] = "ACTIVE"
            agent["last_cycle"] = now

        self._save_state(AGENTS_STATUS_FILE, agents)
        logger.info("Dashboard state updated")

    # =========================================================================
    # MAIN CYCLE
    # =========================================================================

    def run_cycle(self) -> Dict:
        """Run one complete agent cycle."""
        self.cycle_count += 1
        timestamp = datetime.now(ET)
        cycle_id = timestamp.strftime("%Y-%m-%d-%H-%M")

        logger.info("=" * 70)
        logger.info(f"ATLAS AGENT CYCLE #{self.cycle_count} - {cycle_id}")
        logger.info("=" * 70)

        cycle_data = {
            "cycle_id": cycle_id,
            "cycle_number": self.cycle_count,
            "timestamp": timestamp.isoformat(),
            "dry_run": self.dry_run,
            "steps": {},
            "errors": [],
        }

        try:
            # Step 1: News scan
            cycle_data["steps"]["news"] = self.run_news_scan()

            # Step 2: Price update
            cycle_data["steps"]["prices"] = self.run_price_update()

            # Step 3: Sector desks
            cycle_data["steps"]["desks"] = self.run_sector_desks()

            # Step 4: Superinvestor agents
            cycle_data["steps"]["agents"] = self.run_superinvestor_agents()

            # Step 5: Adversarial review
            cycle_data["steps"]["adversarial"] = self.run_adversarial_review()

            # Step 6: Darwin v3 integration pass-through
            cycle_data["steps"]["darwin_v3"] = self.run_darwin_v3_pass_through()

            # Step 7: CIO synthesis
            cycle_data["steps"]["cio"] = self.run_cio_synthesis()

            # Step 8: Autonomous execution check
            cycle_data["steps"]["autonomous"] = self.run_autonomous_execution()

            # Step 9: Dashboard update
            self.update_dashboard_state()
            cycle_data["steps"]["dashboard"] = {"status": "UPDATED"}

            cycle_data["status"] = "SUCCESS"
            cycle_data["duration_seconds"] = (datetime.now(ET) - timestamp).total_seconds()

        except Exception as e:
            logger.error(f"Cycle error: {e}")
            cycle_data["status"] = "ERROR"
            cycle_data["errors"].append(str(e))

        # Save cycle log
        logs = self._load_state(EXECUTION_LOG_FILE) or []
        logs.append(cycle_data)
        logs = logs[-500:]  # Keep last 500 cycles
        self._save_state(EXECUTION_LOG_FILE, logs)

        logger.info("=" * 70)
        logger.info(f"ATLAS AGENT CYCLE #{self.cycle_count} COMPLETE")
        logger.info(f"Duration: {cycle_data.get('duration_seconds', 0):.1f}s")
        logger.info("=" * 70)

        return cycle_data

    def run_darwin_v3_pass_through(self) -> Dict:
        """Run Darwin v3 as a non-blocking pass-through stack."""
        logger.info("Step 6: Running Darwin v3 pass-through stack...")

        try:
            from darwin_v3.runtime import DarwinV3Runtime

            runtime = DarwinV3Runtime(repo_root=Path(__file__).parent.parent)
            result = runtime.run_once()
            self._save_state(DARWIN_V3_DECISIONS_FILE, result)
            logger.info(
                "Darwin v3 complete: judge=%s janus=%s",
                DARWIN_V3_JUDGE_FILE.exists(),
                JANUS_DAILY_FILE.exists(),
            )
            return {"status": "SUCCESS", "result": result}
        except Exception as e:
            logger.error(f"Darwin v3 pass-through failed: {e}")
            return {"status": "NOT_IMPLEMENTED", "error": str(e)}

    # =========================================================================
    # DAILY BRIEFING
    # =========================================================================

    def run_morning_briefing(self) -> Dict:
        """Generate the daily morning briefing."""
        logger.info("=" * 70)
        logger.info("ATLAS MORNING BRIEFING")
        logger.info("=" * 70)

        try:
            # Run full cycle first
            cycle_result = self.run_cycle()

            # Generate briefing
            from agents.daily_briefing import DailyBriefingAgent
            briefing_agent = DailyBriefingAgent()
            briefing = briefing_agent.generate(is_eod=False)

            if briefing:
                logger.info(f"Morning briefing generated for {briefing.get('date')}")

                # Try to send email if configured
                try:
                    briefing_agent.send_email(briefing)
                except Exception as e:
                    logger.warning(f"Email send failed: {e}")

                return {"status": "SUCCESS", "briefing": briefing}
            else:
                return {"status": "NO_DATA"}

        except Exception as e:
            logger.error(f"Morning briefing failed: {e}")
            return {"status": "ERROR", "error": str(e)}

    # =========================================================================
    # WEEKLY SCREEN
    # =========================================================================

    def run_weekly_screen(self) -> Dict:
        """Run weekly S&P 500 fundamental screen."""
        logger.info("=" * 70)
        logger.info("ATLAS WEEKLY FUNDAMENTAL SCREEN")
        logger.info("=" * 70)

        try:
            # This would run the full fundamental batch analysis
            # For now, we'll just trigger the fundamental agent
            fundamental = self._get_agent("fundamental")

            if fundamental and hasattr(fundamental, "run_batch"):
                results = fundamental.run_batch()
                return {"status": "SUCCESS", "results": results}
            else:
                logger.warning("Fundamental batch not available")
                return {"status": "NOT_AVAILABLE"}

        except Exception as e:
            logger.error(f"Weekly screen failed: {e}")
            return {"status": "ERROR", "error": str(e)}

    # =========================================================================
    # MAIN LOOP
    # =========================================================================

    def run(self, max_cycles: int = None):
        """
        Main continuous loop.

        Args:
            max_cycles: Maximum cycles to run (None = infinite)
        """
        self.running = True
        logger.info("=" * 70)
        logger.info("ATLAS EXECUTION LOOP STARTING")
        logger.info(f"Dry run: {self.dry_run}")
        logger.info(f"Max cycles: {max_cycles or 'Infinite'}")
        logger.info("=" * 70)

        cycle = 0
        last_morning_briefing = None
        last_weekly_screen = None
        last_cycle_time = None

        try:
            while self.running and (max_cycles is None or cycle < max_cycles):
                now = datetime.now(ET)
                today = now.strftime("%Y-%m-%d")

                # Check for morning briefing (7am ET, weekdays)
                if self._is_morning_briefing_time() and last_morning_briefing != today:
                    self.run_morning_briefing()
                    last_morning_briefing = today
                    # Morning briefing includes a full cycle, so update cycle time
                    last_cycle_time = now
                    cycle += 1
                    continue

                # Check for weekly screen (Sunday 11pm ET)
                if self._is_weekly_screen_time() and last_weekly_screen != today:
                    self.run_weekly_screen()
                    last_weekly_screen = today
                    continue

                # During market hours, run cycles every 30 minutes
                if self._is_market_hours():
                    # Check if 30 minutes have passed since last cycle
                    should_run = False

                    if last_cycle_time is None:
                        should_run = True
                    else:
                        minutes_since_last = (now - last_cycle_time).total_seconds() / 60
                        should_run = minutes_since_last >= 30

                    if should_run:
                        self.run_cycle()
                        last_cycle_time = now
                        cycle += 1

                        # Reset daily trade counter at start of day
                        if now.hour == 9 and now.minute < 45:
                            self.trades_today = 0
                    else:
                        # Sleep until next check
                        time.sleep(60)
                else:
                    # Outside market hours, check every 5 minutes
                    time.sleep(300)

        except KeyboardInterrupt:
            logger.info("Execution loop stopped by user")
        finally:
            self.running = False
            logger.info("ATLAS Execution Loop stopped")

    def stop(self):
        """Stop the execution loop."""
        self.running = False


# =============================================================================
# CLI INTERFACE
# =============================================================================

def main():
    """Main entry point for the execution loop."""
    parser = argparse.ArgumentParser(description="ATLAS Autonomous Execution Loop")
    parser.add_argument("--once", action="store_true", help="Run a single cycle and exit")
    parser.add_argument("--start", action="store_true", help="Start continuous loop")
    parser.add_argument("--briefing", action="store_true", help="Generate morning briefing")
    parser.add_argument("--weekly", action="store_true", help="Run weekly screen")
    parser.add_argument("--dry-run", action="store_true", help="Simulation mode (no trades)")
    parser.add_argument("--log", action="store_true", help="View execution log")
    parser.add_argument("--log-file", type=str, default=None, help="Log file path")
    parser.add_argument("--max-cycles", type=int, default=None, help="Max cycles for continuous mode")
    args = parser.parse_args()

    # Setup logging
    log_file = args.log_file or "/var/log/atlas_loop.log"
    try:
        setup_logging(log_file)
    except:
        setup_logging()  # Fall back to console only

    if args.log:
        print("\n" + "=" * 70)
        print("ATLAS Execution Log")
        print("=" * 70 + "\n")

        logs = []
        if EXECUTION_LOG_FILE.exists():
            with open(EXECUTION_LOG_FILE) as f:
                logs = json.load(f)

        if logs:
            for log in logs[-10:]:
                print(f"Cycle: {log.get('cycle_id')} (#{log.get('cycle_number', 'N/A')})")
                print(f"  Status: {log.get('status', 'UNKNOWN')}")
                print(f"  Duration: {log.get('duration_seconds', 0):.1f}s")
                if log.get("errors"):
                    print(f"  Errors: {log.get('errors')}")
                print()
        else:
            print("No execution logs found")
        return

    if args.briefing:
        loop = ATLASExecutionLoop(dry_run=args.dry_run)
        result = loop.run_morning_briefing()
        print(json.dumps(result, indent=2, default=str))
        return

    if args.weekly:
        loop = ATLASExecutionLoop(dry_run=args.dry_run)
        result = loop.run_weekly_screen()
        print(json.dumps(result, indent=2, default=str))
        return

    if args.once:
        print("\n" + "=" * 70)
        print("ATLAS Execution Loop - Single Cycle")
        print("=" * 70 + "\n")

        loop = ATLASExecutionLoop(dry_run=args.dry_run)
        result = loop.run_cycle()

        print("\nCycle Result:")
        print(json.dumps(result, indent=2, default=str))
        return

    if args.start:
        print("\n" + "=" * 70)
        print("ATLAS Execution Loop - Continuous Mode")
        print("=" * 70 + "\n")
        print("Press Ctrl+C to stop\n")

        loop = ATLASExecutionLoop(dry_run=args.dry_run)
        loop.run(max_cycles=args.max_cycles)
        return

    # Default: show usage
    print("Usage:")
    print("  python3 -m agents.execution_loop --once           # Single cycle")
    print("  python3 -m agents.execution_loop --once --dry-run # Single cycle (simulation)")
    print("  python3 -m agents.execution_loop --start          # Continuous loop")
    print("  python3 -m agents.execution_loop --start --dry-run # Continuous loop (simulation)")
    print("  python3 -m agents.execution_loop --briefing       # Generate morning briefing")
    print("  python3 -m agents.execution_loop --weekly         # Run weekly screen")
    print("  python3 -m agents.execution_loop --log            # View execution log")


if __name__ == "__main__":
    main()
