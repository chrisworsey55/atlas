"""
SEC Filing Monitor Agent for ATLAS
Real-time monitoring of SEC filings with AI-powered analysis.

Monitors:
- 8-K: Material events (CEO changes, acquisitions, covenant breaches)
- Form 4: Insider trades (buy/sell signals)
- 13D/G: 5%+ ownership (activist stakes)
- 10-K/10-Q: Periodic financials
- S-1/F-1: IPO registrations

This is the highest-signal, most time-sensitive data source.
When a CEO buys $15M of stock before earnings, that's information.
"""
import json
import logging
import argparse
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from pathlib import Path

import anthropic

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_MODEL_PREMIUM
from config.universe import UNIVERSE
from data.edgar_realtime_client import EDGARRealtimeClient, EIGHT_K_ITEMS, EVENT_CATEGORIES

from agents.chat_mixin import ChatMixin

logger = logging.getLogger(__name__)

# State files
STATE_DIR = Path(__file__).resolve().parent.parent / "data" / "state"
FILING_ALERTS_FILE = STATE_DIR / "filing_alerts.json"
INSIDER_HISTORY_FILE = STATE_DIR / "insider_trades.json"


# Filing urgency classification
URGENCY_LEVELS = {
    "IMMEDIATE": ["8-K", "13D", "SC 13D"],  # Material events, activist stakes
    "HIGH": ["4", "13D/A", "13G", "SC 13G", "DEFA14A"],  # Insider trades, ownership
    "MEDIUM": ["10-Q", "S-1", "F-1", "144", "SC 13E-3"],  # Quarterlies, IPOs
    "LOW": ["10-K", "10-K/A", "13G/A"],  # Annual reports (expected)
}


FILING_MONITOR_SYSTEM_PROMPT = """You are a real-time filing analyst at a hedge fund.

You monitor SEC filings and immediately assess their investment implications.
Every filing tells a story. Your job is to extract the signal and recommend action.

## Filing Types You Analyze

### 8-K (Material Events) - IMMEDIATE URGENCY
Most critical filing. Contains:
- Item 1.01: Entry into material agreement (contracts, deals)
- Item 2.01: Acquisition or disposition of assets
- Item 2.02: Results of operations (pre-earnings release)
- Item 5.02: CEO/CFO departure or appointment
- Item 1.05: Cybersecurity incident
- Item 1.03: Bankruptcy or receivership

Red flags: Management departures, covenant breaches, restatements
Green flags: New contracts, accretive acquisitions, guidance raises

### Form 4 (Insider Trades) - HIGH URGENCY
Filed within 2 business days of transaction.
- BUY: Insider buying with own money = VERY bullish
- SELL: Could be planned (10b5-1) or discretionary
- Cluster buying: Multiple insiders buying = strong signal
- Size matters: $15M CEO buy > $50K director buy

Key context:
- Is this a 10b5-1 plan (pre-scheduled) or discretionary?
- Timing: Before earnings = they know something
- Pattern: Multiple insiders at once = coordinated signal

### 13D (Activist Stakes) - HIGH URGENCY
Filed when crossing 5% ownership with activist intent.
- New 13D: Activist taking position (potential catalyst)
- 13D/A: Amendment showing increased/decreased stake
- Check "Purpose" section for intentions

### 13G (Passive Stakes) - MEDIUM URGENCY
Passive 5%+ ownership. Less actionable but shows accumulation.

## Your Analysis Framework

For each filing:
1. CLASSIFY urgency (IMMEDIATE/HIGH/MEDIUM/LOW)
2. SUMMARIZE what happened in 1-2 sentences
3. ASSESS investment implications
4. RECOMMEND action (if any needed)

## Output Format

Respond with JSON:
```json
{
  "filing_type": "Form 4",
  "ticker": "AVGO",
  "urgency": "HIGH",
  "headline": "CEO buys $15.5M of stock ahead of earnings",
  "details": {
    "filer": "Hock Tan (CEO)",
    "action": "BUY",
    "shares": 50000,
    "price": "$310.50",
    "value": "$15,525,000",
    "transaction_date": "2026-03-03",
    "is_10b5_1": false
  },
  "analysis": "CEO open-market purchase of $15.5M one day before earnings is highly unusual. This is discretionary (not 10b5-1 plan). Historically, CEO purchases before earnings have been followed by beats 85% of the time. Combined with elevated call option activity, this is a VERY BULLISH signal.",
  "portfolio_implication": "BULLISH for existing AVGO long. Consider adding to position before earnings.",
  "action_required": true,
  "recommended_action": "Review position sizing; opportunity to add before earnings"
}
```
"""


class FilingMonitorAgent(ChatMixin):
    """
    SEC Filing Monitor Agent.

    Monitors EDGAR for new filings, classifies by urgency,
    and uses Claude to analyze investment implications.
    """

    CHAT_SYSTEM_PROMPT = """You are the ATLAS Filing Monitor having a conversation.

You monitor SEC filings in real-time and analyze their investment implications.
You know the difference between a routine 10-K and a bombshell 8-K.
You track insider trades and know when CEO buying is bullish vs routine.

When discussing filings:
- Cite specific details (shares, prices, dates)
- Explain why the filing matters
- Connect to portfolio implications
- Flag patterns (cluster buying, activist accumulation)

Your latest filing alerts are provided. Use them to ground your responses."""

    desk_name = "filing_monitor"

    def __init__(self):
        """Initialize the Filing Monitor Agent."""
        self.edgar = EDGARRealtimeClient()
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = CLAUDE_MODEL_PREMIUM
        self._ensure_state_dir()

    def _ensure_state_dir(self):
        """Ensure state directory exists."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)

    def _load_alerts(self) -> List[Dict]:
        """Load filing alerts."""
        if FILING_ALERTS_FILE.exists():
            try:
                with open(FILING_ALERTS_FILE, "r") as f:
                    return json.load(f)
            except:
                pass
        return []

    def _save_alert(self, alert: Dict):
        """Save a filing alert."""
        alerts = self._load_alerts()
        alerts.append(alert)
        alerts = alerts[-200:]  # Keep last 200 alerts

        with open(FILING_ALERTS_FILE, "w") as f:
            json.dump(alerts, f, indent=2, default=str)

    def _load_insider_history(self, ticker: str = None) -> List[Dict]:
        """Load insider trade history."""
        if INSIDER_HISTORY_FILE.exists():
            try:
                with open(INSIDER_HISTORY_FILE, "r") as f:
                    trades = json.load(f)
                    if ticker:
                        return [t for t in trades if t.get("ticker") == ticker.upper()]
                    return trades
            except:
                pass
        return []

    def _save_insider_trades(self, trades: List[Dict]):
        """Save insider trades."""
        existing = self._load_insider_history()
        existing.extend(trades)
        existing = existing[-500:]  # Keep last 500

        with open(INSIDER_HISTORY_FILE, "w") as f:
            json.dump(existing, f, indent=2, default=str)

    def load_latest_brief(self) -> Optional[Dict]:
        """Load latest alert for chat context."""
        alerts = self._load_alerts()
        return alerts[-1] if alerts else None

    def _classify_urgency(self, form_type: str) -> str:
        """Classify filing urgency."""
        form_type_upper = form_type.upper()
        for urgency, forms in URGENCY_LEVELS.items():
            if any(f.upper() in form_type_upper for f in forms):
                return urgency
        return "LOW"

    def scan(
        self,
        minutes: int = 60,
        portfolio_only: bool = False,
    ) -> List[Dict]:
        """
        Scan for new SEC filings.

        Args:
            minutes: Look back this many minutes
            portfolio_only: If True, only scan portfolio companies

        Returns:
            List of filing alerts with analysis
        """
        logger.info(f"[FilingMonitor] Scanning for filings (last {minutes} min)...")

        # Get tickers to scan
        if portfolio_only:
            # Load from positions file
            positions_file = STATE_DIR / "positions.json"
            if positions_file.exists():
                with open(positions_file, "r") as f:
                    positions = json.load(f)
                    tickers = [p.get("ticker") for p in positions]
            else:
                tickers = list(UNIVERSE.keys())[:20]  # Top 20 universe tickers
        else:
            tickers = list(UNIVERSE.keys())

        # Scan universe for filings
        all_filings = self.edgar.scan_universe_filings(
            form_types=["10-K", "10-Q", "8-K", "4", "13D", "13G", "SC 13D", "SC 13G", "144"],
            days=max(1, minutes // 1440 + 1)
        )

        # Filter to requested time window
        cutoff = datetime.now() - timedelta(minutes=minutes)
        recent_filings = []
        for filing in all_filings:
            try:
                filing_date = datetime.strptime(filing.get("filing_date", ""), "%Y-%m-%d")
                if filing_date >= cutoff.date():
                    recent_filings.append(filing)
            except:
                # Include if date parsing fails
                recent_filings.append(filing)

        logger.info(f"[FilingMonitor] Found {len(recent_filings)} recent filings")

        # Analyze high-urgency filings with Claude
        alerts = []
        for filing in recent_filings:
            urgency = self._classify_urgency(filing.get("form_type", ""))

            if urgency in ["IMMEDIATE", "HIGH"]:
                # Get detailed analysis from Claude
                alert = self._analyze_filing(filing)
                if alert:
                    alerts.append(alert)
                    self._save_alert(alert)
            else:
                # Just record without deep analysis
                alert = {
                    "timestamp": datetime.utcnow().isoformat(),
                    "filing_type": filing.get("form_type"),
                    "ticker": filing.get("ticker"),
                    "company_name": filing.get("company_name"),
                    "urgency": urgency,
                    "filing_date": filing.get("filing_date"),
                    "filing_url": filing.get("filing_url"),
                    "analysis": "Routine filing - no immediate action required",
                    "action_required": False,
                }
                alerts.append(alert)

        return alerts

    def _analyze_filing(self, filing: Dict) -> Optional[Dict]:
        """Analyze a single filing with Claude."""
        form_type = filing.get("form_type", "")
        ticker = filing.get("ticker")

        try:
            # Get filing details based on type
            if form_type == "4" and ticker:
                # Get insider trade details
                trades = self.edgar.get_insider_trades(ticker, days=7)
                filing_data = trades[0] if trades else filing
                self._save_insider_trades(trades)
            elif form_type in ["8-K", "8-K/A"] and ticker:
                # Get 8-K event details
                events = self.edgar.get_material_events(ticker, days=7)
                filing_data = events[0] if events else filing
            elif form_type in ["13D", "13G", "SC 13D", "SC 13G"] and ticker:
                # Get ownership details
                ownership = self.edgar.get_ownership_changes(ticker)
                filing_data = ownership[0] if ownership else filing
            else:
                filing_data = filing

            # Build prompt for Claude
            prompt = f"""Analyze this SEC filing and provide investment implications:

Filing Type: {form_type}
Ticker: {ticker or 'N/A'}
Company: {filing.get('company_name', 'N/A')}
Filed: {filing.get('filing_date', 'N/A')}

Filing Details:
```json
{json.dumps(filing_data, indent=2, default=str)}
```

Classify urgency, summarize the filing, and assess portfolio implications.
Respond with JSON only."""

            response = self.client.messages.create(
                model=self.model,
                max_tokens=1500,
                system=FILING_MONITOR_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}]
            )

            raw = response.content[0].text

            # Parse JSON
            if "```json" in raw:
                json_str = raw.split("```json")[1].split("```")[0]
            elif "```" in raw:
                json_str = raw.split("```")[1].split("```")[0]
            else:
                json_str = raw

            alert = json.loads(json_str.strip())
            alert["timestamp"] = datetime.utcnow().isoformat()
            alert["filing_url"] = filing.get("filing_url")
            alert["raw_filing"] = filing

            return alert

        except Exception as e:
            logger.error(f"Error analyzing {form_type} filing: {e}")
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "filing_type": form_type,
                "ticker": ticker,
                "urgency": self._classify_urgency(form_type),
                "analysis": f"Filing detected but analysis failed: {str(e)}",
                "action_required": True,
                "filing_url": filing.get("filing_url"),
            }

    def get_insider_history(self, ticker: str, days: int = 90) -> List[Dict]:
        """
        Get insider trade history for a ticker.

        Args:
            ticker: Stock ticker symbol
            days: Look back this many days

        Returns:
            List of insider trade dicts
        """
        # First check cache
        cached = self._load_insider_history(ticker)

        # Also fetch fresh data
        fresh = self.edgar.get_insider_trades(ticker, days)

        if fresh:
            self._save_insider_trades(fresh)
            return fresh
        return cached

    def analyze_insider_pattern(self, ticker: str) -> Optional[Dict]:
        """
        Analyze insider trading patterns for a ticker.

        Returns analysis of:
        - Cluster buying (multiple insiders)
        - Net direction (buying vs selling)
        - Size and timing patterns
        """
        trades = self.get_insider_history(ticker, days=90)

        if not trades:
            return {"ticker": ticker, "trades": 0, "pattern": "NO_DATA"}

        # Analyze patterns
        buys = [t for t in trades if t.get("transaction_type") == "BUY"]
        sells = [t for t in trades if t.get("transaction_type") == "SELL"]

        total_buy_value = sum(abs(t.get("value", 0)) for t in buys)
        total_sell_value = sum(abs(t.get("value", 0)) for t in sells)

        unique_buyers = len(set(t.get("insider_name", "") for t in buys))
        unique_sellers = len(set(t.get("insider_name", "") for t in sells))

        # Determine pattern
        if unique_buyers >= 3:
            pattern = "CLUSTER_BUYING"
        elif total_buy_value > total_sell_value * 2:
            pattern = "NET_BUYING"
        elif total_sell_value > total_buy_value * 2:
            pattern = "NET_SELLING"
        else:
            pattern = "MIXED"

        return {
            "ticker": ticker,
            "trades_90d": len(trades),
            "buys": len(buys),
            "sells": len(sells),
            "total_buy_value": total_buy_value,
            "total_sell_value": total_sell_value,
            "net_value": total_buy_value - total_sell_value,
            "unique_buyers": unique_buyers,
            "unique_sellers": unique_sellers,
            "pattern": pattern,
            "signal": "BULLISH" if pattern in ["CLUSTER_BUYING", "NET_BUYING"] else "BEARISH" if pattern == "NET_SELLING" else "NEUTRAL",
            "recent_trades": trades[:5],
        }

    def watch(
        self,
        interval_minutes: int = 5,
        max_cycles: int = None,
    ):
        """
        Continuous monitoring mode.

        Args:
            interval_minutes: Poll interval
            max_cycles: Max number of cycles (None = infinite)
        """
        import time

        logger.info(f"[FilingMonitor] Starting watch mode (every {interval_minutes} min)...")

        cycle = 0
        seen_accessions = set()

        while max_cycles is None or cycle < max_cycles:
            cycle += 1
            logger.info(f"[FilingMonitor] Watch cycle {cycle}...")

            try:
                alerts = self.scan(minutes=interval_minutes + 5, portfolio_only=True)

                # Filter to new filings
                new_alerts = []
                for alert in alerts:
                    acc = alert.get("raw_filing", {}).get("accession_number")
                    if acc and acc not in seen_accessions:
                        seen_accessions.add(acc)
                        new_alerts.append(alert)

                # Log high-urgency alerts
                for alert in new_alerts:
                    if alert.get("urgency") in ["IMMEDIATE", "HIGH"]:
                        logger.warning(
                            f"[ALERT] {alert.get('filing_type')} - {alert.get('ticker')} - "
                            f"{alert.get('headline', alert.get('analysis', ''))[:80]}"
                        )

                if new_alerts:
                    logger.info(f"[FilingMonitor] {len(new_alerts)} new filings detected")

            except Exception as e:
                logger.error(f"[FilingMonitor] Watch error: {e}")

            if max_cycles is None or cycle < max_cycles:
                time.sleep(interval_minutes * 60)

    def get_brief_for_cio(self) -> Dict:
        """Get simplified brief for CIO agent."""
        alerts = self._load_alerts()

        # Get alerts from last 24 hours
        cutoff = datetime.utcnow() - timedelta(hours=24)
        recent = []
        for alert in alerts:
            try:
                ts = datetime.fromisoformat(alert.get("timestamp", ""))
                if ts >= cutoff:
                    recent.append(alert)
            except:
                continue

        # Summarize by urgency
        immediate = [a for a in recent if a.get("urgency") == "IMMEDIATE"]
        high = [a for a in recent if a.get("urgency") == "HIGH"]

        return {
            "agent": "FilingMonitor",
            "period": "last_24h",
            "total_filings": len(recent),
            "immediate_alerts": len(immediate),
            "high_alerts": len(high),
            "alerts": immediate + high[:5],
            "summary": f"{len(immediate)} immediate, {len(high)} high urgency filings in last 24h",
        }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    parser = argparse.ArgumentParser(description="ATLAS Filing Monitor Agent")
    parser.add_argument("--scan", action="store_true", help="Scan for new filings")
    parser.add_argument("--portfolio", action="store_true", help="Scan only portfolio companies")
    parser.add_argument("--insider", type=str, help="Get insider trade history for ticker")
    parser.add_argument("--watch", action="store_true", help="Continuous monitoring mode")
    parser.add_argument("--minutes", type=int, default=60, help="Look back minutes")
    args = parser.parse_args()

    agent = FilingMonitorAgent()

    if args.watch:
        print("\n" + "="*70)
        print("ATLAS Filing Monitor - Watch Mode")
        print("="*70 + "\n")
        print("Press Ctrl+C to stop\n")
        try:
            agent.watch(interval_minutes=5)
        except KeyboardInterrupt:
            print("\nStopped.")

    elif args.insider:
        print("\n" + "="*70)
        print(f"ATLAS Filing Monitor - Insider Trades: {args.insider.upper()}")
        print("="*70 + "\n")

        pattern = agent.analyze_insider_pattern(args.insider.upper())
        print(f"Pattern: {pattern.get('pattern')}")
        print(f"Signal: {pattern.get('signal')}")
        print(f"Trades (90d): {pattern.get('trades_90d')}")
        print(f"Buys: {pattern.get('buys')} | Sells: {pattern.get('sells')}")
        print(f"Net Value: ${pattern.get('net_value', 0):,.0f}")
        print(f"Unique Buyers: {pattern.get('unique_buyers')} | Sellers: {pattern.get('unique_sellers')}")

        print("\nRecent Trades:")
        for trade in pattern.get("recent_trades", [])[:5]:
            print(f"  {trade.get('transaction_date')} | {trade.get('insider_name', 'N/A')[:25]} | "
                  f"{trade.get('transaction_type')} | {trade.get('shares', 0):,} shares | "
                  f"${abs(trade.get('value', 0)):,.0f}")

    elif args.scan:
        print("\n" + "="*70)
        print("ATLAS Filing Monitor - Scan")
        print("="*70 + "\n")

        alerts = agent.scan(
            minutes=args.minutes,
            portfolio_only=args.portfolio,
        )

        immediate = [a for a in alerts if a.get("urgency") == "IMMEDIATE"]
        high = [a for a in alerts if a.get("urgency") == "HIGH"]

        if immediate:
            print("IMMEDIATE ALERTS:")
            for alert in immediate:
                print(f"  {alert.get('filing_type')} | {alert.get('ticker')} | "
                      f"{alert.get('headline', alert.get('analysis', ''))[:60]}")
            print()

        if high:
            print("HIGH PRIORITY:")
            for alert in high:
                print(f"  {alert.get('filing_type')} | {alert.get('ticker')} | "
                      f"{alert.get('headline', alert.get('analysis', ''))[:60]}")
            print()

        print(f"Total filings: {len(alerts)}")
        print(f"Immediate: {len(immediate)} | High: {len(high)}")

    else:
        print("Usage:")
        print("  python3 -m agents.filing_monitor_agent --scan")
        print("  python3 -m agents.filing_monitor_agent --scan --portfolio")
        print("  python3 -m agents.filing_monitor_agent --insider AVGO")
        print("  python3 -m agents.filing_monitor_agent --watch")
