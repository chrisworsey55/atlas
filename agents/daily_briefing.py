"""
Daily Briefing Agent for ATLAS
Generates comprehensive morning reports by synthesizing all data sources and agent views.

The briefing pulls together:
- Overnight news (via news sentiment client)
- Pre-market/current prices for all positions (via yfinance)
- Latest macro data from FRED
- SEC EDGAR overnight filings on portfolio companies
- Earnings calendar - portfolio companies reporting today
- Superinvestor agent views (Druckenmiller, Aschenbrenner, Baker, Ackman)
- Adversarial agent review of current portfolio
- CIO synthesis and recommendation

Output saved to data/state/briefings/ as JSON + markdown, emailed, and served via API.
"""
import json
import logging
import os
import smtplib
from datetime import datetime, date, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from pathlib import Path
from typing import Optional, Dict, List, Any
import argparse

import anthropic

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL_PREMIUM

logger = logging.getLogger(__name__)

# Directory paths
STATE_DIR = Path(__file__).resolve().parent.parent / "data" / "state"
BRIEFINGS_DIR = STATE_DIR / "briefings"

# SMTP Configuration (loaded from environment)
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
BRIEFING_FROM = os.getenv("BRIEFING_FROM", "atlas@generalintelligence.capital")
BRIEFING_TO = os.getenv("BRIEFING_TO", "chris@generalintelligencecapital.com")


class DailyBriefingAgent:
    """
    Generates comprehensive daily morning briefings for ATLAS.
    """

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = CLAUDE_MODEL_PREMIUM
        self._ensure_directories()

    def _ensure_directories(self):
        """Ensure required directories exist."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        BRIEFINGS_DIR.mkdir(parents=True, exist_ok=True)

    def generate(self, is_eod: bool = False) -> Optional[Dict]:
        """
        Generate a complete morning briefing.

        Args:
            is_eod: If True, generate end-of-day summary instead of morning briefing

        Returns:
            Complete briefing data structure
        """
        briefing_type = "EOD" if is_eod else "Morning"
        logger.info(f"[Briefing] Starting {briefing_type} briefing generation...")

        today = date.today()
        now = datetime.now()

        # Initialize briefing structure
        briefing = {
            "date": today.isoformat(),
            "generated_at": now.isoformat(),
            "type": "EOD" if is_eod else "MORNING",
            "portfolio_snapshot": {},
            "positions": [],
            "overnight_news": [],
            "earnings_today": [],
            "sec_filings": [],
            "macro_snapshot": {},
            "agent_views": {},
            "cio_recommendation": {},
            "fundamental_screen_update": {},
        }

        # 1. Load portfolio snapshot
        logger.info("[Briefing] Loading portfolio snapshot...")
        briefing["portfolio_snapshot"] = self._get_portfolio_snapshot()
        briefing["positions"] = self._get_positions_with_prices()

        # 2. Get overnight news
        logger.info("[Briefing] Fetching overnight news...")
        briefing["overnight_news"] = self._get_overnight_news()

        # 3. Check earnings calendar
        logger.info("[Briefing] Checking earnings calendar...")
        briefing["earnings_today"] = self._get_earnings_today()

        # 4. Check SEC filings
        logger.info("[Briefing] Checking SEC EDGAR for overnight filings...")
        briefing["sec_filings"] = self._get_overnight_filings()

        # 5. Get macro snapshot
        logger.info("[Briefing] Loading macro data from FRED...")
        briefing["macro_snapshot"] = self._get_macro_snapshot()

        # 6. Run superinvestor agents
        logger.info("[Briefing] Running superinvestor agent views...")
        briefing["agent_views"] = self._get_agent_views()

        # 7. Run adversarial review
        logger.info("[Briefing] Running adversarial portfolio review...")
        briefing["agent_views"]["adversarial"] = self._get_adversarial_review()

        # 8. Get fundamental screen update
        logger.info("[Briefing] Getting fundamental screen status...")
        briefing["fundamental_screen_update"] = self._get_fundamental_screen_status()

        # 9. CIO synthesis
        logger.info("[Briefing] Generating CIO synthesis...")
        briefing["cio_recommendation"] = self._generate_cio_synthesis(briefing)

        # 10. Save to files
        logger.info("[Briefing] Saving briefing to files...")
        self._save_briefing(briefing)

        logger.info(f"[Briefing] {briefing_type} briefing complete!")
        return briefing

    def _get_portfolio_snapshot(self) -> Dict:
        """Load current portfolio snapshot from state."""
        try:
            meta_file = STATE_DIR / "portfolio_meta.json"
            pnl_file = STATE_DIR / "pnl_history.json"

            meta = {}
            if meta_file.exists():
                with open(meta_file) as f:
                    meta = json.load(f)

            pnl_history = []
            if pnl_file.exists():
                with open(pnl_file) as f:
                    pnl_history = json.load(f)

            latest = pnl_history[-1] if pnl_history else {}
            starting_value = meta.get("starting_value", 1000000)
            total_value = latest.get("portfolio_value", starting_value)
            days_elapsed = latest.get("days_elapsed", 0)

            # Calculate hurdle
            hurdle_rate = meta.get("hurdle_rate_annual", 0.045)
            hurdle_return = (hurdle_rate / 365) * days_elapsed * starting_value
            actual_return = total_value - starting_value
            alpha = actual_return - hurdle_return

            return {
                "total_value": round(total_value, 2),
                "starting_value": starting_value,
                "day_pnl": round(latest.get("day_pnl", 0), 2),
                "day_pnl_pct": round(latest.get("day_pnl_pct", 0), 4),
                "total_pnl": round(latest.get("total_pnl", 0), 2),
                "total_pnl_pct": round((latest.get("total_pnl", 0) / starting_value) * 100, 4) if starting_value else 0,
                "alpha_vs_hurdle": round(alpha, 2),
                "days_since_inception": days_elapsed,
                "high_water_mark": meta.get("high_water_mark", starting_value),
            }
        except Exception as e:
            logger.error(f"Error loading portfolio snapshot: {e}")
            return {
                "total_value": 1000000,
                "starting_value": 1000000,
                "day_pnl": 0,
                "day_pnl_pct": 0,
                "total_pnl": 0,
                "total_pnl_pct": 0,
                "alpha_vs_hurdle": 0,
                "days_since_inception": 0,
                "high_water_mark": 1000000,
            }

    def _get_positions_with_prices(self) -> List[Dict]:
        """Load positions and fetch current prices."""
        try:
            positions_file = STATE_DIR / "positions.json"
            if not positions_file.exists():
                return []

            with open(positions_file) as f:
                positions = json.load(f)

            # Try to get current prices via yfinance
            try:
                from data.price_client import PriceClient
                price_client = PriceClient()
                tickers = [p.get("ticker") for p in positions if p.get("ticker")]
                if tickers:
                    current_prices = price_client.get_bulk_prices(tickers)
                else:
                    current_prices = {}
            except Exception as e:
                logger.warning(f"Could not fetch prices: {e}")
                current_prices = {}

            # Enrich positions with current prices and signals
            enriched = []
            for pos in positions:
                ticker = pos.get("ticker", "")
                current_price = current_prices.get(ticker) or pos.get("current_price", 0)
                entry_price = pos.get("entry_price", 0)
                shares = pos.get("shares", 0)
                direction = pos.get("direction", "LONG")

                # Calculate P&L
                if direction == "SHORT":
                    pnl = (entry_price - current_price) * shares
                else:
                    pnl = (current_price - entry_price) * shares

                entry_value = entry_price * shares
                pnl_pct = (pnl / entry_value * 100) if entry_value else 0

                # Determine signal based on P&L and thesis status
                if pnl_pct >= 5:
                    signal = "GREEN"
                elif pnl_pct <= -5:
                    signal = "RED"
                else:
                    signal = "AMBER"

                enriched.append({
                    "ticker": ticker,
                    "direction": direction,
                    "shares": shares,
                    "entry": round(entry_price, 2),
                    "current": round(current_price, 2),
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "signal": signal,
                    "note": pos.get("note", ""),
                    "thesis": pos.get("thesis", ""),
                    "stop_loss": pos.get("stop_loss"),
                    "target": pos.get("target"),
                })

            return enriched

        except Exception as e:
            logger.error(f"Error loading positions: {e}")
            return []

    def _get_overnight_news(self) -> List[Dict]:
        """Fetch overnight news for portfolio companies and macro."""
        try:
            from data.news_sentiment_client import NewsSentimentClient
            news_client = NewsSentimentClient()

            # Get portfolio tickers
            positions = self._get_positions_with_prices()
            tickers = [p["ticker"] for p in positions if p.get("ticker")]

            all_news = []

            # Get macro headlines first
            try:
                macro_news = news_client.get_macro_headlines()
                for item in macro_news[:5]:
                    all_news.append({
                        "headline": item.get("headline", ""),
                        "source": item.get("source", ""),
                        "urgency": "MEDIUM",
                        "impact_score": 50,
                        "portfolio_impact": "General market news",
                        "emoji": self._urgency_emoji("MEDIUM"),
                    })
            except Exception as e:
                logger.warning(f"Could not fetch macro news: {e}")

            # Get news for each position
            for ticker in tickers[:10]:  # Limit to avoid rate limits
                try:
                    ticker_news = news_client.get_news_with_sentiment(ticker, hours=16)
                    for item in ticker_news[:2]:
                        impact = item.get("impact_score", 50)
                        urgency = "HIGH" if impact > 70 else "MEDIUM" if impact > 40 else "LOW"
                        all_news.append({
                            "headline": item.get("headline", ""),
                            "source": item.get("source", ""),
                            "ticker": ticker,
                            "urgency": urgency,
                            "impact_score": impact,
                            "portfolio_impact": f"Affects {ticker} position",
                            "emoji": self._urgency_emoji(urgency),
                            "sentiment": item.get("sentiment", "NEUTRAL"),
                        })
                except Exception as e:
                    logger.debug(f"News fetch failed for {ticker}: {e}")

            # Sort by impact score
            all_news.sort(key=lambda x: x.get("impact_score", 0), reverse=True)
            return all_news[:15]

        except Exception as e:
            logger.error(f"Error fetching overnight news: {e}")
            return []

    def _urgency_emoji(self, urgency: str) -> str:
        """Return emoji for urgency level."""
        return {
            "HIGH": "\U0001F534",    # Red circle
            "MEDIUM": "\U0001F7E1",  # Yellow circle
            "LOW": "\U0001F7E2",     # Green circle
        }.get(urgency, "\U0001F7E1")

    def _get_earnings_today(self) -> List[Dict]:
        """Check if any portfolio companies are reporting earnings today."""
        try:
            from data.earnings_client import EarningsClient
            earnings_client = EarningsClient()

            # Get upcoming earnings
            upcoming = earnings_client.get_upcoming_earnings(days_ahead=1)

            # Filter to portfolio tickers
            positions = self._get_positions_with_prices()
            portfolio_tickers = {p["ticker"] for p in positions}

            reporting_today = []
            for earning in upcoming:
                if earning.get("ticker") in portfolio_tickers:
                    reporting_today.append({
                        "ticker": earning.get("ticker"),
                        "company_name": earning.get("company_name"),
                        "time": earning.get("time_of_day", "Unknown"),
                        "eps_estimate": earning.get("eps_estimate"),
                        "revenue_estimate": earning.get("revenue_estimate"),
                    })

            return reporting_today

        except Exception as e:
            logger.error(f"Error checking earnings calendar: {e}")
            return []

    def _get_overnight_filings(self) -> List[Dict]:
        """Check SEC EDGAR for overnight filings on portfolio companies."""
        try:
            from data.edgar_client import EdgarClient
            edgar = EdgarClient()

            positions = self._get_positions_with_prices()
            portfolio_tickers = [p["ticker"] for p in positions if p.get("ticker")]

            filings = []
            for ticker in portfolio_tickers[:10]:  # Limit API calls
                try:
                    recent_filings = edgar.get_recent_filings(ticker, days=1)
                    for filing in recent_filings[:2]:
                        filing_type = filing.get("form", "")
                        # Flag material filings
                        is_material = filing_type in ["8-K", "10-K", "10-Q", "4", "SC 13D", "SC 13G"]
                        filings.append({
                            "ticker": ticker,
                            "form": filing_type,
                            "filed_date": filing.get("filed", ""),
                            "description": filing.get("description", ""),
                            "is_material": is_material,
                            "url": filing.get("url", ""),
                        })
                except Exception as e:
                    logger.debug(f"EDGAR check failed for {ticker}: {e}")

            # Sort by materiality
            filings.sort(key=lambda x: x.get("is_material", False), reverse=True)
            return filings

        except Exception as e:
            logger.error(f"Error checking SEC filings: {e}")
            return []

    def _get_macro_snapshot(self) -> Dict:
        """Load latest macro data from FRED."""
        try:
            from data.macro_client import MacroClient
            macro = MacroClient()
            snapshot = macro.get_macro_snapshot()

            return {
                "fed_funds_rate": snapshot.get("fed_funds_rate"),
                "yield_curve_10y_2y": snapshot.get("yield_curve_10y_2y"),
                "vix": snapshot.get("vix"),
                "sp500": snapshot.get("sp500"),
                "dollar_index": snapshot.get("dollar_index"),
                "oil_wti": snapshot.get("oil_wti"),
                "gold": snapshot.get("gold"),
                "liquidity_regime": macro.get_liquidity_regime(snapshot),
                "cycle_position": macro.get_cycle_position(snapshot),
            }

        except Exception as e:
            logger.error(f"Error loading macro data: {e}")
            return {}

    def _get_agent_views(self) -> Dict:
        """Get views from superinvestor agents."""
        views = {}

        # Druckenmiller
        try:
            from agents.druckenmiller_agent import DruckenmillerAgent
            druck = DruckenmillerAgent()
            latest = druck.load_latest_brief()
            if latest:
                views["druckenmiller"] = {
                    "tilt": latest.get("portfolio_tilt", "NEUTRAL"),
                    "summary": latest.get("headline", ""),
                    "key_action": latest.get("brief_for_cio", "")[:200] if latest.get("brief_for_cio") else "",
                    "conviction_level": latest.get("conviction_level", 0.5),
                }
            else:
                views["druckenmiller"] = {"tilt": "NO_DATA", "summary": "No recent analysis"}
        except Exception as e:
            logger.warning(f"Could not load Druckenmiller view: {e}")
            views["druckenmiller"] = {"tilt": "ERROR", "summary": str(e)}

        # Aschenbrenner (AI/compute thesis)
        views["aschenbrenner"] = self._get_aschenbrenner_view()

        # Baker (quantitative)
        views["baker"] = self._get_baker_view()

        # Ackman (activist)
        views["ackman"] = self._get_ackman_view()

        return views

    def _get_aschenbrenner_view(self) -> Dict:
        """Get AI/compute-focused view (Leopold Aschenbrenner style)."""
        # Check for AI-related positions
        positions = self._get_positions_with_prices()
        ai_tickers = {"NVDA", "AMD", "AVGO", "TSM", "MSFT", "GOOGL", "META", "AMZN", "BE"}
        ai_positions = [p for p in positions if p.get("ticker") in ai_tickers]

        if not ai_positions:
            return {
                "tilt": "NEUTRAL",
                "summary": "No AI-related positions to analyze",
                "key_action": "Consider adding AI infrastructure exposure",
            }

        # Summarize AI exposure
        total_ai_value = sum(
            abs(p.get("pnl", 0)) + (p.get("entry", 0) * p.get("shares", 0))
            for p in ai_positions
        )

        return {
            "tilt": "HOLD" if ai_positions else "NEUTRAL",
            "summary": f"AI infrastructure exposure via {len(ai_positions)} positions",
            "key_action": "Monitor compute buildout pace and hyperscaler capex guidance",
        }

    def _get_baker_view(self) -> Dict:
        """Get quantitative/factor-based view."""
        positions = self._get_positions_with_prices()
        if not positions:
            return {"tilt": "NEUTRAL", "summary": "No positions", "key_action": "N/A"}

        # Simple factor analysis
        long_positions = [p for p in positions if p.get("direction") == "LONG"]
        short_positions = [p for p in positions if p.get("direction") == "SHORT"]

        avg_long_pnl = sum(p.get("pnl_pct", 0) for p in long_positions) / len(long_positions) if long_positions else 0
        avg_short_pnl = sum(p.get("pnl_pct", 0) for p in short_positions) / len(short_positions) if short_positions else 0

        if avg_long_pnl > 2 and avg_short_pnl > 0:
            tilt = "BULLISH"
        elif avg_long_pnl < -2 and avg_short_pnl < 0:
            tilt = "BEARISH"
        else:
            tilt = "NEUTRAL"

        return {
            "tilt": tilt,
            "summary": f"Long avg: {avg_long_pnl:.1f}%, Short avg: {avg_short_pnl:.1f}%",
            "key_action": "Maintain factor balance" if tilt == "NEUTRAL" else f"Consider {tilt.lower()} tilt adjustment",
        }

    def _get_ackman_view(self) -> Dict:
        """Get activist/concentrated view (Bill Ackman style)."""
        positions = self._get_positions_with_prices()
        if not positions:
            return {"tilt": "NEUTRAL", "summary": "No positions", "key_action": "N/A"}

        # Find highest conviction position
        sorted_by_value = sorted(
            positions,
            key=lambda p: abs(p.get("entry", 0) * p.get("shares", 0)),
            reverse=True
        )

        top_position = sorted_by_value[0] if sorted_by_value else {}
        top_ticker = top_position.get("ticker", "")
        top_pnl = top_position.get("pnl_pct", 0)

        return {
            "tilt": "HOLD",
            "summary": f"Top position: {top_ticker} ({top_pnl:+.1f}%)",
            "key_action": "Look for catalyst-driven entry points in quality compounders",
        }

    def _get_adversarial_review(self) -> Dict:
        """Run adversarial review on current portfolio."""
        try:
            positions = self._get_positions_with_prices()
            if not positions:
                return {
                    "warning_level": "LOW",
                    "summary": "No positions to review",
                    "biggest_risk": "No portfolio risk - 100% cash",
                }

            # Check for concentration risk
            total_value = sum(
                abs(p.get("entry", 0) * p.get("shares", 0))
                for p in positions
            )

            if total_value == 0:
                return {
                    "warning_level": "LOW",
                    "summary": "Empty portfolio",
                    "biggest_risk": "No exposure risk",
                }

            # Check correlation risk (simplified - same direction tickers)
            long_count = sum(1 for p in positions if p.get("direction") == "LONG")
            short_count = sum(1 for p in positions if p.get("direction") == "SHORT")

            # Check sector concentration
            tech_tickers = {"NVDA", "AMD", "AVGO", "TSM", "MSFT", "GOOGL", "META", "AMZN", "AAPL"}
            tech_positions = [p for p in positions if p.get("ticker") in tech_tickers]
            tech_exposure = len(tech_positions) / len(positions) if positions else 0

            # Calculate drawdown positions
            red_positions = [p for p in positions if p.get("pnl_pct", 0) < -5]

            # Determine warning level
            if tech_exposure > 0.6 or len(red_positions) >= 3:
                warning_level = "ELEVATED"
            elif tech_exposure > 0.4 or len(red_positions) >= 2:
                warning_level = "MODERATE"
            else:
                warning_level = "LOW"

            biggest_risk = "Tech concentration" if tech_exposure > 0.4 else "Correlation risk" if long_count > 3 and short_count == 0 else "Position drawdowns" if red_positions else "General market exposure"

            return {
                "warning_level": warning_level,
                "summary": f"{len(positions)} positions, {long_count}L/{short_count}S, {tech_exposure*100:.0f}% tech",
                "biggest_risk": biggest_risk,
                "red_positions": [p.get("ticker") for p in red_positions],
            }

        except Exception as e:
            logger.error(f"Error in adversarial review: {e}")
            return {
                "warning_level": "UNKNOWN",
                "summary": f"Review failed: {e}",
                "biggest_risk": "Unknown - review error",
            }

    def _get_fundamental_screen_status(self) -> Dict:
        """Get status of fundamental screening pipeline."""
        try:
            valuations_file = STATE_DIR / "fundamental_valuations.json"
            if valuations_file.exists():
                with open(valuations_file) as f:
                    valuations = json.load(f)

                if isinstance(valuations, list) and valuations:
                    # Find best opportunity
                    undervalued = [
                        v for v in valuations
                        if v.get("synthesis", {}).get("verdict") == "UNDERVALUED"
                    ]
                    undervalued.sort(
                        key=lambda x: x.get("synthesis", {}).get("upside_to_midpoint_pct", 0),
                        reverse=True
                    )

                    top_opp = undervalued[0] if undervalued else None

                    return {
                        "completed": len(valuations),
                        "total": 503,  # S&P 500 + some additions
                        "top_opportunity": {
                            "ticker": top_opp.get("ticker"),
                            "upside": top_opp.get("synthesis", {}).get("upside_to_midpoint_pct"),
                            "confidence": top_opp.get("synthesis", {}).get("confidence"),
                        } if top_opp else None,
                    }

            return {"completed": 0, "total": 503, "top_opportunity": None}

        except Exception as e:
            logger.error(f"Error loading fundamental screen: {e}")
            return {"completed": 0, "total": 503, "top_opportunity": None}

    def _generate_cio_synthesis(self, briefing: Dict) -> Dict:
        """Use Claude to synthesize all data into CIO recommendation."""
        try:
            # Build context for Claude
            context = f"""You are the CIO of a systematic hedge fund. Generate a brief recommendation based on this morning briefing data:

PORTFOLIO SNAPSHOT:
- Total Value: ${briefing['portfolio_snapshot'].get('total_value', 0):,.0f}
- Day P&L: ${briefing['portfolio_snapshot'].get('day_pnl', 0):,.0f} ({briefing['portfolio_snapshot'].get('day_pnl_pct', 0):.2f}%)
- Alpha vs Hurdle: ${briefing['portfolio_snapshot'].get('alpha_vs_hurdle', 0):,.0f}
- Days Since Inception: {briefing['portfolio_snapshot'].get('days_since_inception', 0)}

POSITIONS ({len(briefing['positions'])}):
{json.dumps(briefing['positions'][:5], indent=2)}

OVERNIGHT NEWS ({len(briefing['overnight_news'])} items):
{json.dumps(briefing['overnight_news'][:5], indent=2)}

EARNINGS TODAY:
{json.dumps(briefing['earnings_today'], indent=2)}

MACRO:
{json.dumps(briefing['macro_snapshot'], indent=2)}

AGENT VIEWS:
{json.dumps(briefing['agent_views'], indent=2)}

FUNDAMENTAL SCREEN:
{json.dumps(briefing['fundamental_screen_update'], indent=2)}

Based on this data, provide a JSON response with:
{{
  "action": "HOLD" or "ADD" or "REDUCE" or "REBALANCE",
  "rationale": "2-3 sentence summary of your recommendation",
  "watchlist": ["ticker1", "ticker2"],
  "next_catalyst": "What to watch for today",
  "risk_flag": "Primary risk to monitor" or null
}}"""

            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[{"role": "user", "content": context}]
            )

            raw = response.content[0].text

            # Parse JSON
            if "```json" in raw:
                json_str = raw.split("```json")[1].split("```")[0]
            elif "```" in raw:
                json_str = raw.split("```")[1].split("```")[0]
            else:
                json_str = raw

            return json.loads(json_str.strip())

        except Exception as e:
            logger.error(f"CIO synthesis failed: {e}")
            return {
                "action": "HOLD",
                "rationale": f"Synthesis failed: {e}. Recommend holding current positions.",
                "watchlist": [],
                "next_catalyst": "Monitor market open",
                "risk_flag": "Synthesis error - manual review required",
            }

    def _save_briefing(self, briefing: Dict):
        """Save briefing to JSON and markdown files."""
        date_str = briefing["date"]

        # Save JSON
        json_path = BRIEFINGS_DIR / f"{date_str}.json"
        with open(json_path, "w") as f:
            json.dump(briefing, f, indent=2, default=str)
        logger.info(f"[Briefing] Saved JSON to {json_path}")

        # Save markdown
        md_path = BRIEFINGS_DIR / f"{date_str}.md"
        md_content = self._render_markdown(briefing)
        with open(md_path, "w") as f:
            f.write(md_content)
        logger.info(f"[Briefing] Saved markdown to {md_path}")

    def _render_markdown(self, briefing: Dict) -> str:
        """Render briefing as markdown."""
        lines = [
            f"# ATLAS Morning Briefing - {briefing['date']}",
            f"*Generated: {briefing['generated_at']}*",
            "",
            "---",
            "",
            "## Portfolio Snapshot",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total Value | ${briefing['portfolio_snapshot'].get('total_value', 0):,.0f} |",
            f"| Day P&L | ${briefing['portfolio_snapshot'].get('day_pnl', 0):,.0f} ({briefing['portfolio_snapshot'].get('day_pnl_pct', 0):.2f}%) |",
            f"| Total P&L | ${briefing['portfolio_snapshot'].get('total_pnl', 0):,.0f} ({briefing['portfolio_snapshot'].get('total_pnl_pct', 0):.2f}%) |",
            f"| Alpha vs Hurdle | ${briefing['portfolio_snapshot'].get('alpha_vs_hurdle', 0):,.0f} |",
            f"| Days Since Inception | {briefing['portfolio_snapshot'].get('days_since_inception', 0)} |",
            "",
            "## Positions",
            "",
            "| Ticker | Dir | Shares | Entry | Current | P&L | Signal |",
            "|--------|-----|--------|-------|---------|-----|--------|",
        ]

        for pos in briefing.get("positions", []):
            signal_emoji = {"GREEN": "\U0001F7E2", "AMBER": "\U0001F7E1", "RED": "\U0001F534"}.get(pos.get("signal", ""), "")
            lines.append(
                f"| {pos.get('ticker')} | {pos.get('direction')} | {pos.get('shares')} | "
                f"${pos.get('entry', 0):.2f} | ${pos.get('current', 0):.2f} | "
                f"${pos.get('pnl', 0):,.0f} ({pos.get('pnl_pct', 0):.1f}%) | {signal_emoji} |"
            )

        lines.extend([
            "",
            "## Overnight News",
            "",
        ])

        for news in briefing.get("overnight_news", [])[:10]:
            emoji = news.get("emoji", "")
            lines.append(f"- {emoji} **{news.get('headline', '')}** ({news.get('source', '')})")

        lines.extend([
            "",
            "## Agent Views",
            "",
        ])

        for agent, view in briefing.get("agent_views", {}).items():
            lines.append(f"### {agent.title()}")
            lines.append(f"- **Tilt:** {view.get('tilt', 'N/A')}")
            lines.append(f"- **Summary:** {view.get('summary', 'N/A')}")
            if view.get("key_action"):
                lines.append(f"- **Key Action:** {view.get('key_action')}")
            lines.append("")

        lines.extend([
            "## CIO Recommendation",
            "",
            f"**Action:** {briefing.get('cio_recommendation', {}).get('action', 'HOLD')}",
            "",
            f"{briefing.get('cio_recommendation', {}).get('rationale', '')}",
            "",
            f"**Watchlist:** {', '.join(briefing.get('cio_recommendation', {}).get('watchlist', []))}",
            "",
            f"**Next Catalyst:** {briefing.get('cio_recommendation', {}).get('next_catalyst', '')}",
            "",
        ])

        if briefing.get("cio_recommendation", {}).get("risk_flag"):
            lines.append(f"**Risk Flag:** {briefing['cio_recommendation']['risk_flag']}")

        lines.extend([
            "",
            "---",
            "*Generated by ATLAS | General Intelligence Capital*",
        ])

        return "\n".join(lines)

    def send_email(self, briefing: Dict, pdf_path: str = None) -> bool:
        """Send briefing via email."""
        if not SMTP_USER or not SMTP_PASS:
            logger.warning("[Briefing] SMTP not configured, skipping email")
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = BRIEFING_FROM
            msg["To"] = BRIEFING_TO
            msg["Subject"] = f"ATLAS Morning Briefing - {briefing['date']}"

            # Plain text version
            text_body = self._render_markdown(briefing)
            msg.attach(MIMEText(text_body, "plain"))

            # HTML version
            html_body = self._render_html(briefing)
            msg.attach(MIMEText(html_body, "html"))

            # Attach PDF if provided
            if pdf_path and os.path.exists(pdf_path):
                with open(pdf_path, "rb") as f:
                    pdf = MIMEApplication(f.read(), _subtype="pdf")
                    pdf.add_header(
                        "Content-Disposition",
                        "attachment",
                        filename=f"ATLAS_Briefing_{briefing['date']}.pdf"
                    )
                    msg.attach(pdf)

            # Send
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
                server.send_message(msg)

            logger.info(f"[Briefing] Email sent to {BRIEFING_TO}")
            return True

        except Exception as e:
            logger.error(f"[Briefing] Email failed: {e}")
            return False

    def _render_html(self, briefing: Dict) -> str:
        """Render briefing as HTML email."""
        # Portfolio snapshot
        snapshot = briefing.get("portfolio_snapshot", {})
        pnl_color = "#10b981" if snapshot.get("day_pnl", 0) >= 0 else "#ef4444"

        # Positions table rows
        position_rows = ""
        for pos in briefing.get("positions", []):
            signal_color = {"GREEN": "#10b981", "AMBER": "#f59e0b", "RED": "#ef4444"}.get(pos.get("signal", ""), "#6b7280")
            pnl_val_color = "#10b981" if pos.get("pnl", 0) >= 0 else "#ef4444"
            position_rows += f"""
            <tr>
                <td style="padding: 8px; border-bottom: 1px solid #1e2433;">{pos.get('ticker')}</td>
                <td style="padding: 8px; border-bottom: 1px solid #1e2433;">{pos.get('direction')}</td>
                <td style="padding: 8px; border-bottom: 1px solid #1e2433;">{pos.get('shares')}</td>
                <td style="padding: 8px; border-bottom: 1px solid #1e2433;">${pos.get('entry', 0):.2f}</td>
                <td style="padding: 8px; border-bottom: 1px solid #1e2433;">${pos.get('current', 0):.2f}</td>
                <td style="padding: 8px; border-bottom: 1px solid #1e2433; color: {pnl_val_color};">${pos.get('pnl', 0):,.0f} ({pos.get('pnl_pct', 0):.1f}%)</td>
                <td style="padding: 8px; border-bottom: 1px solid #1e2433; color: {signal_color}; font-weight: bold;">{pos.get('signal')}</td>
            </tr>
            """

        # News items
        news_items = ""
        for news in briefing.get("overnight_news", [])[:8]:
            urgency_color = {"HIGH": "#ef4444", "MEDIUM": "#f59e0b", "LOW": "#10b981"}.get(news.get("urgency", ""), "#6b7280")
            news_items += f"""
            <div style="padding: 10px; margin: 5px 0; background: #1a1b1e; border-left: 3px solid {urgency_color}; border-radius: 4px;">
                <strong>{news.get('headline', '')}</strong>
                <div style="color: #6b7280; font-size: 12px; margin-top: 4px;">{news.get('source', '')} | Impact: {news.get('impact_score', 'N/A')}</div>
            </div>
            """

        # Agent views
        agent_views = ""
        for agent, view in briefing.get("agent_views", {}).items():
            tilt = view.get("tilt", "N/A")
            tilt_color = "#10b981" if "BULL" in str(tilt).upper() or tilt == "AGGRESSIVE" else "#ef4444" if "BEAR" in str(tilt).upper() else "#f59e0b"
            agent_views += f"""
            <div style="padding: 12px; margin: 8px 0; background: #1a1b1e; border-radius: 8px;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                    <strong style="text-transform: capitalize;">{agent}</strong>
                    <span style="color: {tilt_color}; font-weight: bold;">{tilt}</span>
                </div>
                <div style="color: #9ca3af;">{view.get('summary', '')}</div>
            </div>
            """

        # CIO recommendation
        cio = briefing.get("cio_recommendation", {})
        action_color = {"HOLD": "#f59e0b", "ADD": "#10b981", "REDUCE": "#ef4444", "REBALANCE": "#3b82f6"}.get(cio.get("action", ""), "#6b7280")

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0a0b0d; color: #e5e7eb; margin: 0; padding: 20px;">
    <div style="max-width: 800px; margin: 0 auto;">
        <!-- Header -->
        <div style="text-align: center; padding: 20px 0; border-bottom: 1px solid #1e2433;">
            <h1 style="margin: 0; font-size: 28px; background: linear-gradient(135deg, #3db27f 0%, #2563eb 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">ATLAS Morning Briefing</h1>
            <p style="color: #6b7280; margin: 8px 0 0 0;">{briefing['date']} | Generated {briefing['generated_at'][:16]}</p>
        </div>

        <!-- Portfolio Snapshot -->
        <div style="padding: 20px; margin: 20px 0; background: #111217; border: 1px solid #1e2433; border-radius: 12px;">
            <h2 style="margin: 0 0 15px 0; color: #3db27f;">Portfolio Snapshot</h2>
            <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 15px;">
                <div>
                    <div style="color: #6b7280; font-size: 12px;">Total Value</div>
                    <div style="font-size: 24px; font-weight: bold;">${snapshot.get('total_value', 0):,.0f}</div>
                </div>
                <div>
                    <div style="color: #6b7280; font-size: 12px;">Day P&L</div>
                    <div style="font-size: 24px; font-weight: bold; color: {pnl_color};">${snapshot.get('day_pnl', 0):,.0f} ({snapshot.get('day_pnl_pct', 0):.2f}%)</div>
                </div>
                <div>
                    <div style="color: #6b7280; font-size: 12px;">Alpha vs Hurdle</div>
                    <div style="font-size: 18px;">${snapshot.get('alpha_vs_hurdle', 0):,.0f}</div>
                </div>
                <div>
                    <div style="color: #6b7280; font-size: 12px;">Days Since Inception</div>
                    <div style="font-size: 18px;">{snapshot.get('days_since_inception', 0)}</div>
                </div>
            </div>
        </div>

        <!-- Positions -->
        <div style="padding: 20px; margin: 20px 0; background: #111217; border: 1px solid #1e2433; border-radius: 12px;">
            <h2 style="margin: 0 0 15px 0; color: #3db27f;">Positions</h2>
            <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                <thead>
                    <tr style="color: #6b7280; text-align: left;">
                        <th style="padding: 8px; border-bottom: 2px solid #1e2433;">Ticker</th>
                        <th style="padding: 8px; border-bottom: 2px solid #1e2433;">Dir</th>
                        <th style="padding: 8px; border-bottom: 2px solid #1e2433;">Shares</th>
                        <th style="padding: 8px; border-bottom: 2px solid #1e2433;">Entry</th>
                        <th style="padding: 8px; border-bottom: 2px solid #1e2433;">Current</th>
                        <th style="padding: 8px; border-bottom: 2px solid #1e2433;">P&L</th>
                        <th style="padding: 8px; border-bottom: 2px solid #1e2433;">Signal</th>
                    </tr>
                </thead>
                <tbody>
                    {position_rows}
                </tbody>
            </table>
        </div>

        <!-- Overnight News -->
        <div style="padding: 20px; margin: 20px 0; background: #111217; border: 1px solid #1e2433; border-radius: 12px;">
            <h2 style="margin: 0 0 15px 0; color: #3db27f;">Overnight News</h2>
            {news_items if news_items else '<p style="color: #6b7280;">No significant overnight news</p>'}
        </div>

        <!-- Agent Views -->
        <div style="padding: 20px; margin: 20px 0; background: #111217; border: 1px solid #1e2433; border-radius: 12px;">
            <h2 style="margin: 0 0 15px 0; color: #3db27f;">Agent Views</h2>
            {agent_views}
        </div>

        <!-- CIO Recommendation -->
        <div style="padding: 20px; margin: 20px 0; background: #111217; border: 2px solid {action_color}; border-radius: 12px;">
            <h2 style="margin: 0 0 15px 0; color: #3db27f;">CIO Recommendation</h2>
            <div style="display: inline-block; padding: 8px 16px; background: {action_color}20; color: {action_color}; border-radius: 20px; font-weight: bold; margin-bottom: 15px;">
                {cio.get('action', 'HOLD')}
            </div>
            <p style="margin: 10px 0; line-height: 1.6;">{cio.get('rationale', '')}</p>
            <div style="margin-top: 15px; padding-top: 15px; border-top: 1px solid #1e2433;">
                <p style="margin: 5px 0;"><strong>Watchlist:</strong> {', '.join(cio.get('watchlist', [])) or 'None'}</p>
                <p style="margin: 5px 0;"><strong>Next Catalyst:</strong> {cio.get('next_catalyst', 'N/A')}</p>
                {f'<p style="margin: 5px 0; color: #ef4444;"><strong>Risk Flag:</strong> {cio.get("risk_flag")}</p>' if cio.get('risk_flag') else ''}
            </div>
        </div>

        <!-- Footer -->
        <div style="text-align: center; padding: 20px; color: #6b7280; font-size: 12px; border-top: 1px solid #1e2433;">
            Generated by ATLAS | General Intelligence Capital | Confidential
        </div>
    </div>
</body>
</html>
        """
        return html


def generate_briefing_pdf(briefing_data: Dict) -> str:
    """
    Generate a branded PDF briefing.

    Args:
        briefing_data: The briefing JSON data

    Returns:
        Path to generated PDF file
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
    except ImportError:
        logger.error("reportlab not installed. Run: pip install reportlab")
        return None

    pdf_path = f"/tmp/ATLAS_Briefing_{briefing_data['date']}.pdf"

    doc = SimpleDocTemplate(pdf_path, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=72)
    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=12,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#3db27f'),
    )

    header_style = ParagraphStyle(
        'CustomHeader',
        parent=styles['Heading2'],
        fontSize=14,
        spaceAfter=6,
        textColor=colors.HexColor('#3db27f'),
    )

    body_style = ParagraphStyle(
        'CustomBody',
        parent=styles['Normal'],
        fontSize=10,
        spaceAfter=6,
    )

    story = []

    # Title
    story.append(Paragraph("ATLAS Morning Briefing", title_style))
    story.append(Paragraph(f"<font color='#6b7280'>{briefing_data['date']} | Generated {briefing_data['generated_at'][:16]}</font>", ParagraphStyle('Subtitle', alignment=TA_CENTER, fontSize=10, textColor=colors.gray)))
    story.append(Spacer(1, 20))

    # Portfolio Snapshot
    story.append(Paragraph("Portfolio Snapshot", header_style))
    snapshot = briefing_data.get("portfolio_snapshot", {})
    snapshot_data = [
        ["Metric", "Value"],
        ["Total Value", f"${snapshot.get('total_value', 0):,.0f}"],
        ["Day P&L", f"${snapshot.get('day_pnl', 0):,.0f} ({snapshot.get('day_pnl_pct', 0):.2f}%)"],
        ["Total P&L", f"${snapshot.get('total_pnl', 0):,.0f}"],
        ["Alpha vs Hurdle", f"${snapshot.get('alpha_vs_hurdle', 0):,.0f}"],
        ["Days", str(snapshot.get('days_since_inception', 0))],
    ]
    snapshot_table = Table(snapshot_data, colWidths=[2*inch, 3*inch])
    snapshot_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e2433')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#1e2433')),
    ]))
    story.append(snapshot_table)
    story.append(Spacer(1, 15))

    # Positions
    story.append(Paragraph("Positions", header_style))
    positions = briefing_data.get("positions", [])
    if positions:
        pos_data = [["Ticker", "Dir", "Entry", "Current", "P&L", "Signal"]]
        for pos in positions[:10]:
            pnl_str = f"${pos.get('pnl', 0):,.0f} ({pos.get('pnl_pct', 0):.1f}%)"
            pos_data.append([
                pos.get('ticker', ''),
                pos.get('direction', ''),
                f"${pos.get('entry', 0):.2f}",
                f"${pos.get('current', 0):.2f}",
                pnl_str,
                pos.get('signal', ''),
            ])
        pos_table = Table(pos_data, colWidths=[0.8*inch, 0.6*inch, 0.9*inch, 0.9*inch, 1.3*inch, 0.7*inch])
        pos_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e2433')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#1e2433')),
        ]))
        story.append(pos_table)
    story.append(Spacer(1, 15))

    # CIO Recommendation
    story.append(Paragraph("CIO Recommendation", header_style))
    cio = briefing_data.get("cio_recommendation", {})
    story.append(Paragraph(f"<b>Action:</b> {cio.get('action', 'HOLD')}", body_style))
    story.append(Paragraph(f"<b>Rationale:</b> {cio.get('rationale', '')}", body_style))
    story.append(Paragraph(f"<b>Watchlist:</b> {', '.join(cio.get('watchlist', []))}", body_style))
    story.append(Paragraph(f"<b>Next Catalyst:</b> {cio.get('next_catalyst', '')}", body_style))
    if cio.get('risk_flag'):
        story.append(Paragraph(f"<b>Risk Flag:</b> <font color='red'>{cio.get('risk_flag')}</font>", body_style))

    story.append(Spacer(1, 30))

    # Footer
    story.append(Paragraph("<font color='#6b7280'>Generated by ATLAS | General Intelligence Capital | Confidential</font>", ParagraphStyle('Footer', alignment=TA_CENTER, fontSize=8, textColor=colors.gray)))

    doc.build(story)
    logger.info(f"[Briefing] Generated PDF at {pdf_path}")
    return pdf_path


def run_briefing(
    send: bool = False,
    is_eod: bool = False,
    save_only: bool = False,
    preview: bool = False,
) -> Optional[Dict]:
    """
    Convenience function to run the daily briefing.

    Args:
        send: If True, send email after generating
        is_eod: If True, generate EOD summary instead of morning briefing
        save_only: If True, only save to state files
        preview: If True, print to terminal without saving

    Returns:
        The generated briefing data
    """
    agent = DailyBriefingAgent()
    briefing = agent.generate(is_eod=is_eod)

    if not briefing:
        return None

    if preview:
        print("\n" + "=" * 70)
        print("ATLAS BRIEFING PREVIEW")
        print("=" * 70)
        print(agent._render_markdown(briefing))
        return briefing

    if send and not save_only:
        # Send via Resend
        try:
            from agents.email_alerts import send_daily_briefing
            send_daily_briefing(briefing)
        except Exception as e:
            logger.error(f"[Briefing] Resend email failed: {e}")
            # Fall back to SMTP if configured
            pdf_path = generate_briefing_pdf(briefing)
            agent.send_email(briefing, pdf_path)

    return briefing


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    parser = argparse.ArgumentParser(description="ATLAS Daily Briefing Generator")
    parser.add_argument("--preview", action="store_true", help="Show in terminal, don't send")
    parser.add_argument("--send", action="store_true", help="Generate, save, and email")
    parser.add_argument("--eod", action="store_true", help="Generate end of day version")
    parser.add_argument("--save", action="store_true", help="Save to dashboard state only")
    parser.add_argument("--pdf", type=str, help="Generate PDF for specific date (YYYY-MM-DD)")

    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("ATLAS Daily Briefing Generator")
    print("=" * 70 + "\n")

    if args.pdf:
        # Generate PDF for specific date
        briefing_path = BRIEFINGS_DIR / f"{args.pdf}.json"
        if briefing_path.exists():
            with open(briefing_path) as f:
                briefing_data = json.load(f)
            pdf_path = generate_briefing_pdf(briefing_data)
            print(f"Generated PDF: {pdf_path}")
        else:
            print(f"No briefing found for {args.pdf}")
    else:
        briefing = run_briefing(
            send=args.send,
            is_eod=args.eod,
            save_only=args.save,
            preview=args.preview,
        )

        if briefing and not args.preview:
            print(f"\nBriefing generated for {briefing['date']}")
            print(f"JSON saved to: {BRIEFINGS_DIR / briefing['date']}.json")
            print(f"Markdown saved to: {BRIEFINGS_DIR / briefing['date']}.md")
            if args.send:
                print(f"Email sent to: {BRIEFING_TO}")
