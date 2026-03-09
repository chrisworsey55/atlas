#!/usr/bin/env python3
"""
ATLAS Autonomous Loop

The master script that runs the entire autonomous trading system.
Adapted from Karpathy's autoresearch concept: trade, learn, self-improve, never stop.

Usage:
    python3 -m agents.autonomous_loop --once   # Run one cycle (for testing)
    python3 -m agents.autonomous_loop          # Run indefinitely (production)
"""
import anthropic
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import pytz
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# Paths
ATLAS_DIR = Path(__file__).parent.parent
STATE_DIR = ATLAS_DIR / "data" / "state"
AUTONOMOUS_DIR = ATLAS_DIR / "data" / "autonomous"
PROMPTS_DIR = Path(__file__).parent / "prompts"
AUTORESEARCH_LOG = STATE_DIR / "autoresearch_results.tsv"

# Ensure autonomous directory exists
AUTONOMOUS_DIR.mkdir(parents=True, exist_ok=True)

# API client
client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

# Timezone
ET = pytz.timezone('America/New_York')


def log(msg: str, level: str = "INFO"):
    """Structured logging."""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] [{level}] {msg}")


def is_market_day() -> bool:
    """Check if today is a trading day (Mon-Fri, not a holiday)."""
    now = datetime.now(ET)
    # Weekend check
    if now.weekday() >= 5:
        return False
    # Could add holiday check here
    return True


def wait_for_market_close():
    """Wait until 4:30pm ET (market close + 30 min for data settlement)."""
    target_time = datetime.now(ET).replace(hour=16, minute=30, second=0, microsecond=0)
    now = datetime.now(ET)

    # If it's past 4:30pm today, wait until tomorrow
    if now >= target_time:
        target_time += timedelta(days=1)

    # Skip weekends
    while target_time.weekday() >= 5:
        target_time += timedelta(days=1)

    wait_seconds = (target_time - now).total_seconds()
    if wait_seconds > 0:
        log(f"Waiting until {target_time.strftime('%Y-%m-%d %H:%M %Z')} ({wait_seconds/3600:.1f} hours)")
        time.sleep(wait_seconds)


def load_positions() -> dict:
    """Load AUTONOMOUS portfolio positions (NOT Chris's portfolio)."""
    pos_file = AUTONOMOUS_DIR / "positions.json"
    if pos_file.exists():
        with open(pos_file, 'r') as f:
            return json.load(f)
    # Start fresh with $1M cash, ZERO positions
    return {"portfolio_value": 1000000, "cash": 1000000, "positions": [], "mode": "AUTONOMOUS"}


def save_positions(data: dict):
    """Save AUTONOMOUS portfolio positions."""
    data["last_updated"] = datetime.now().strftime('%Y-%m-%d %H:%M')
    data["mode"] = "AUTONOMOUS"
    with open(AUTONOMOUS_DIR / "positions.json", 'w') as f:
        json.dump(data, f, indent=2)


def load_agent_weights() -> dict:
    """Load agent weights."""
    weights_file = STATE_DIR / "agent_weights.json"
    if weights_file.exists():
        with open(weights_file, 'r') as f:
            return json.load(f)
    return {}


# ============================================================
# PHASE A: MARKET DATA
# ============================================================

def fetch_market_data() -> dict:
    """Fetch live market data from multiple sources."""
    log("PHASE A: Fetching market data...")

    try:
        from agents.market_data import (
            get_validated_quote,
            get_market_snapshot,
            get_sector_data
        )

        data = {
            "timestamp": datetime.now().isoformat(),
            "indices": {},
            "sectors": {},
            "portfolio_prices": {}
        }

        # Market overview
        try:
            overview = get_market_snapshot()
            data["indices"] = overview
            spy_price = overview.get('SPY', {}).get('price', 'N/A')
            log(f"  Indices: SPY={spy_price}")
        except Exception as e:
            log(f"  Error fetching overview: {e}", "WARN")

        # Sector performance
        try:
            sectors = get_sector_data()
            data["sectors"] = sectors
        except Exception as e:
            log(f"  Error fetching sectors: {e}", "WARN")

        # Portfolio positions prices
        positions = load_positions()
        for pos in positions.get("positions", []):
            ticker = pos.get("ticker")
            if ticker:
                try:
                    quote = get_validated_quote(ticker)
                    if quote and quote.get("price"):
                        data["portfolio_prices"][ticker] = quote["price"]
                except Exception as e:
                    log(f"  Error fetching {ticker}: {e}", "WARN")

        log(f"  Fetched {len(data['portfolio_prices'])} portfolio prices")
        return data

    except Exception as e:
        log(f"Market data fetch failed: {e}", "ERROR")
        return {"error": str(e), "timestamp": datetime.now().isoformat()}


# ============================================================
# PHASE B: AGENT DEBATE (AUTONOMOUS - uses own positions)
# ============================================================

def build_autonomous_context(positions: dict, market_data: dict) -> str:
    """Build market context for autonomous portfolio (NOT Chris's portfolio)."""
    today = datetime.now().strftime('%Y-%m-%d %H:%M')

    portfolio_value = positions.get("portfolio_value", 1000000)
    cash = positions.get("cash", portfolio_value)
    pos_list = positions.get("positions", [])

    # Calculate P&L
    total_pnl = 0
    position_lines = []

    for p in pos_list:
        ticker = p.get("ticker", "?")
        entry = p.get("entry_price", 0) or 0
        current = p.get("current_price", entry) or entry
        shares = p.get("shares", 0) or 0
        direction = p.get("direction", "LONG")

        if entry and current and shares:
            if direction == "SHORT":
                pnl = (entry - current) * shares
            else:
                pnl = (current - entry) * shares
            pnl_pct = (pnl / (entry * shares) * 100) if entry * shares > 0 else 0
            total_pnl += pnl
            position_lines.append(
                f"  {ticker}: {direction} {shares} shares @ ${entry:.2f} -> ${current:.2f} | "
                f"P&L: ${pnl:,.2f} ({pnl_pct:.2f}%) | Thesis: {p.get('thesis', '')[:60]}"
            )

    if not position_lines:
        position_lines = ["  NO POSITIONS — 100% CASH — READY TO DEPLOY"]

    # Market data summary
    indices = market_data.get("indices", {})
    spy_data = indices.get("SPY", {})
    spy_price = spy_data.get("price", "N/A") if isinstance(spy_data, dict) else "N/A"

    context = f"""
=== AUTONOMOUS PORTFOLIO STATUS ===
Date: {today}
Mode: FULLY AUTONOMOUS — AI agents decide everything
Starting Capital: $1,000,000
Current Value: ${portfolio_value:,.2f}
Cash Available: ${cash:,.2f}
Total P&L: ${total_pnl:,.2f} ({total_pnl/10000:.2f}%)

CURRENT POSITIONS:
{chr(10).join(position_lines)}

MARKET CONDITIONS:
SPY: {spy_price}
Oil: ~$108 (Iran war premium)
VIX: 29+ (elevated fear)
Futures: Down 1.5%+

YOUR MISSION: You are an autonomous AI hedge fund. You have $1M to deploy.
Analyze the market and recommend what to BUY, SELL, or SHORT.
Be specific: ticker, direction, size, conviction, stop loss, target.
"""
    return context


def call_agent(system_prompt: str, user_message: str, max_tokens: int = 1000) -> str:
    """Call Claude with a system prompt and user message."""
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}]
    )
    return response.content[0].text


def load_prompt(agent_name: str) -> str:
    """Load an agent's system prompt from its .md file."""
    patterns = [f"{agent_name}.md", f"{agent_name}_desk.md", f"{agent_name}_agent.md"]
    for pattern in patterns:
        path = PROMPTS_DIR / pattern
        if path.exists():
            with open(path, 'r') as f:
                return f.read()
    return f"You are the {agent_name} agent for an autonomous AI hedge fund. Provide your analysis."


def run_agent_debate(market_data: dict) -> dict:
    """Run the full 20-agent debate using AUTONOMOUS positions."""
    log("PHASE B: Running agent debate (AUTONOMOUS PORTFOLIO)...")

    try:
        # Load AUTONOMOUS positions (not Chris's)
        positions = load_positions()
        context = build_autonomous_context(positions, market_data)

        log(f"  Portfolio: ${positions.get('portfolio_value', 1000000):,.0f}, {len(positions.get('positions', []))} positions")

        all_views = {}

        # LAYER 1: DATA AGENTS
        log("  Layer 1: Data Agents...")
        all_views['news'] = call_agent(
            load_prompt("news_sentiment"),
            f"What market events should drive our trading decisions today?\n\n{context}"
        )
        all_views['flow'] = call_agent(
            load_prompt("institutional_flow"),
            f"What institutional flow signals should we act on?\n\n{context}"
        )

        # LAYER 2: SECTOR DESKS
        log("  Layer 2: Sector Desks...")
        all_views['bond'] = call_agent(load_prompt("bond"), f"Rates and credit analysis. What should we trade?\n\n{context}")
        all_views['currency'] = call_agent(load_prompt("currency"), f"FX analysis. What should we trade?\n\n{context}")
        all_views['commodities'] = call_agent(load_prompt("commodities"), f"Commodities analysis. Oil at $108. What should we trade?\n\n{context}")
        all_views['metals'] = call_agent(load_prompt("metals"), f"Precious metals analysis. What should we trade?\n\n{context}")
        all_views['semiconductor'] = call_agent(load_prompt("semiconductor"), f"Semiconductor analysis. What should we trade?\n\n{context}")
        all_views['biotech'] = call_agent(load_prompt("biotech"), f"Healthcare/biotech analysis. What should we trade?\n\n{context}")
        all_views['energy'] = call_agent(load_prompt("energy"), f"Energy sector analysis. Iran war. What should we trade?\n\n{context}")
        all_views['consumer'] = call_agent(load_prompt("consumer"), f"Consumer sector analysis. What should we trade?\n\n{context}")
        all_views['industrials'] = call_agent(load_prompt("industrials"), f"Industrials analysis. What should we trade?\n\n{context}")
        all_views['microcap'] = call_agent(load_prompt("microcap"), f"Microcap opportunities. What should we trade?\n\n{context}")

        # LAYER 3: SUPERINVESTORS
        log("  Layer 3: Superinvestor Agents...")
        all_views['druckenmiller'] = call_agent(load_prompt("druckenmiller"), f"Macro view. What's the big trade?\n\n{context}")
        all_views['aschenbrenner'] = call_agent(load_prompt("aschenbrenner"), f"AI infrastructure thesis. What should we own?\n\n{context}")
        all_views['baker'] = call_agent(load_prompt("baker"), f"Deep tech analysis. What should we trade?\n\n{context}")
        all_views['ackman'] = call_agent(load_prompt("ackman"), f"Quality compounder view. What should we own?\n\n{context}")

        # LAYER 4: RISK AND DECISION
        log("  Layer 4: Risk and Decision...")

        # CRO sees all views
        views_summary = "\n\n".join([f"=== {k.upper()} ===\n{v[:500]}" for k, v in all_views.items()])
        all_views['cro'] = call_agent(
            load_prompt("cro"),
            f"Review all agent views and identify risks:\n\n{views_summary}\n\n{context}"
        )

        # Alpha Discovery
        all_views['alpha'] = call_agent(
            load_prompt("alpha_discovery"),
            f"Find alpha opportunities from agent convergence:\n\n{views_summary}\n\n{context}"
        )

        # Autonomous Execution Agent
        all_views['autonomous'] = call_agent(
            load_prompt("autonomous_execution"),
            f"Based on all views, what trades should we EXECUTE right now?\n\n{views_summary}\n\nCRO RISK VIEW:\n{all_views['cro']}\n\n{context}",
            max_tokens=1500
        )

        # CIO Final Synthesis
        all_views['cio'] = call_agent(
            load_prompt("cio"),
            f"FINAL DECISION. You have $1M. What do we buy/sell/short? Be specific.\n\n{views_summary}\n\nAUTONOMOUS EXECUTION:\n{all_views['autonomous']}\n\nCRO RISKS:\n{all_views['cro']}\n\n{context}",
            max_tokens=2000
        )

        # Save views
        with open(STATE_DIR / "autonomous_agent_views.json", 'w') as f:
            json.dump(all_views, f, indent=2)

        log(f"  Debate complete: {len(all_views)} agent views")
        return all_views

    except Exception as e:
        log(f"Agent debate failed: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}


# ============================================================
# PHASE C: TRADE (FULLY AUTONOMOUS - NO HUMAN GATES)
# ============================================================

def execute_trades(all_views: dict, market_data: dict) -> list:
    """
    Execute trades based on CIO decisions.
    RULE: NO HUMAN APPROVAL GATES. The CIO decides, the system executes.
    """
    log("PHASE C: Executing CIO decisions (FULLY AUTONOMOUS)...")
    import re
    from agents.market_data import get_validated_quote

    trades_executed = []
    positions = load_positions()
    cio_view = all_views.get("cio", "")
    portfolio_value = positions.get("portfolio_value", 1000000)

    # Parse trade recommendations from CIO view
    recommendations = []

    # Find BUY/LONG recommendations
    for match in re.finditer(r'(?:BUY|LONG|ADD)\s+([A-Z]{1,5})', cio_view, re.IGNORECASE):
        ticker = match.group(1).upper()
        if len(ticker) >= 2 and ticker not in ['THE', 'AND', 'FOR', 'ALL', 'ARE', 'NOT', 'WITH', 'THIS']:
            alloc_match = re.search(rf'{ticker}.*?(\d+)%', cio_view[match.start():match.start()+200])
            allocation = int(alloc_match.group(1)) if alloc_match else 5
            recommendations.append((ticker, 'LONG', allocation))

    # Find SELL/SHORT recommendations
    for match in re.finditer(r'(?:SELL|SHORT|TRIM|EXIT)\s+([A-Z]{1,5})', cio_view, re.IGNORECASE):
        ticker = match.group(1).upper()
        if len(ticker) >= 2 and ticker not in ['THE', 'AND', 'FOR', 'ALL', 'ARE', 'NOT', 'WITH', 'THIS']:
            alloc_match = re.search(rf'{ticker}.*?(\d+)%', cio_view[match.start():match.start()+200])
            allocation = int(alloc_match.group(1)) if alloc_match else 3
            recommendations.append((ticker, 'SHORT', allocation))

    # Deduplicate
    seen = set()
    unique_recs = []
    for ticker, direction, alloc in recommendations:
        if ticker not in seen:
            seen.add(ticker)
            unique_recs.append((ticker, direction, alloc))

    if not unique_recs:
        log("  CIO decided: HOLD current positions (no new trades)")
        return trades_executed

    log(f"  CIO recommendations: {len(unique_recs)} trades")

    # Execute each trade
    for ticker, direction, allocation in unique_recs[:10]:
        try:
            quote = get_validated_quote(ticker)
            price = quote.get("price") if quote else None

            if not price or price <= 0:
                log(f"    Skip {ticker}: No valid price")
                continue

            # Calculate shares (cap at 15% per position)
            allocation = min(allocation, 15)
            target_value = portfolio_value * (allocation / 100)
            shares = int(target_value / price)

            if shares <= 0:
                continue

            position_value = shares * price
            position_pct = (position_value / portfolio_value) * 100

            # Create trade record
            trade = {
                "timestamp": datetime.now().isoformat(),
                "ticker": ticker,
                "direction": direction,
                "shares": shares,
                "price": price,
                "value": position_value,
                "allocation_pct": position_pct,
                "agent_source": "cio",
                "executed": True
            }

            # Update positions
            existing_pos = None
            for i, pos in enumerate(positions.get("positions", [])):
                if pos.get("ticker") == ticker:
                    existing_pos = i
                    break

            if direction == "LONG":
                if existing_pos is not None:
                    positions["positions"][existing_pos]["shares"] += shares
                    positions["positions"][existing_pos]["allocation_pct"] += position_pct
                else:
                    positions["positions"].append({
                        "ticker": ticker,
                        "direction": "LONG",
                        "shares": shares,
                        "entry_price": price,
                        "current_price": price,
                        "allocation_pct": position_pct,
                        "thesis": "CIO autonomous execution",
                        "agent_source": "cio",
                        "date_opened": datetime.now().strftime('%Y-%m-%d'),
                        "status": "OPEN"
                    })
            elif direction == "SHORT":
                if existing_pos is not None:
                    positions["positions"][existing_pos]["shares"] -= shares
                    if positions["positions"][existing_pos]["shares"] <= 0:
                        positions["positions"].pop(existing_pos)
                else:
                    positions["positions"].append({
                        "ticker": ticker,
                        "direction": "SHORT",
                        "shares": shares,
                        "entry_price": price,
                        "current_price": price,
                        "allocation_pct": position_pct,
                        "thesis": "CIO autonomous execution - SHORT",
                        "agent_source": "cio",
                        "date_opened": datetime.now().strftime('%Y-%m-%d'),
                        "status": "OPEN"
                    })

            trades_executed.append(trade)
            _log_trade(trade)
            log(f"    EXECUTED: {direction} {shares} {ticker} @ ${price:.2f} ({position_pct:.1f}%)")

        except Exception as e:
            log(f"    Error executing {ticker}: {e}")
            continue

    # Save updated positions
    if trades_executed:
        save_positions(positions)

    return trades_executed


def _extract_confidence(text: str) -> int:
    """Extract confidence level from CIO synthesis."""
    import re
    match = re.search(r'CONVICTION\s*(?:LEVEL)?[:\s]*(\d{1,3})', text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r'(\d{1,3})%?\s*confidence', text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return 70


def _log_trade(trade: dict):
    """Log trade to autonomous journal file."""
    journal_dir = AUTONOMOUS_DIR / "trade_journal"
    journal_dir.mkdir(parents=True, exist_ok=True)

    journal_file = journal_dir / f"{datetime.now().strftime('%Y-%m')}_trades.json"
    trades = []
    if journal_file.exists():
        with open(journal_file, 'r') as f:
            trades = json.load(f)

    trades.append(trade)

    with open(journal_file, 'w') as f:
        json.dump(trades, f, indent=2)


# ============================================================
# PHASE D: LEARN
# ============================================================

def update_scorecards(all_views: dict) -> dict:
    """Update agent scorecards and weights."""
    log("PHASE D: Updating scorecards...")

    try:
        from agents.scorecard import (
            extract_recommendations_from_views,
            record_recommendation,
            run_scorecard_update,
            get_worst_agent
        )
        from agents.market_data import get_validated_quote

        # Extract and record recommendations from agent views
        positions = load_positions()
        portfolio_tickers = [p.get("ticker") for p in positions.get("positions", [])]

        recs = extract_recommendations_from_views(all_views, portfolio_tickers)
        log(f"  Extracted {len(recs)} recommendations")

        for agent, ticker, direction, conviction in recs:
            try:
                quote = get_validated_quote(ticker)
                price = quote.get("price") if quote else None
                if price:
                    record_recommendation(agent, ticker, direction, conviction, price)
            except Exception as e:
                log(f"  Error recording {ticker}: {e}", "WARN")

        # Run full scorecard update
        metrics, weights = run_scorecard_update()

        # Get worst agent for autoresearch
        worst = get_worst_agent()
        if worst:
            log(f"  Worst agent: {worst[0]} (Sharpe: {worst[1]:.3f})")

        return {"metrics": metrics, "weights": weights, "worst_agent": worst}

    except Exception as e:
        log(f"Scorecard update failed: {e}", "ERROR")
        return {"error": str(e)}


def send_briefing(all_views: dict, trades: list, scorecard_data: dict):
    """Send daily briefing email."""
    log("  Sending briefing email...")

    try:
        from agents.email_alerts import send_daily_briefing

        positions = load_positions()
        portfolio_value = positions.get("portfolio_value", 1000000)

        briefing_data = {
            "date": datetime.now().strftime('%Y-%m-%d'),
            "portfolio_snapshot": {
                "total_pnl": 0,  # Would calculate from positions
                "total_pnl_pct": 0,
                "position_count": len(positions.get("positions", [])),
                "cash_pct": sum(p.get("allocation_pct", 0) for p in positions.get("positions", []) if p.get("ticker") == "BIL")
            },
            "cio_synthesis": {
                "stance": "See synthesis",
                "conviction": _extract_confidence(all_views.get("cio", "")),
                "recommendation": all_views.get("cio", "")[:500]
            },
            "trades_executed": trades,
            "agent_leaderboard": scorecard_data.get("metrics", {}),
            "worst_agent": scorecard_data.get("worst_agent")
        }

        send_daily_briefing(briefing_data)
        log("  Briefing sent")

    except Exception as e:
        log(f"  Briefing failed: {e}", "WARN")


# ============================================================
# PHASE E: IMPROVE (Autoresearch)
# ============================================================

def run_autoresearch(scorecard_data: dict) -> dict:
    """Run the autoresearch self-improvement loop."""
    log("PHASE E: Running autoresearch...")

    # Check if we have enough data
    worst = scorecard_data.get("worst_agent")
    if not worst:
        log("  Skipping: Not enough data for autoresearch")
        return {"skipped": True, "reason": "insufficient_data"}

    agent_name, sharpe, weight = worst

    # Check if this agent has had 3 failed attempts recently
    recent_attempts = _count_recent_attempts(agent_name)
    if recent_attempts >= 3:
        log(f"  Skipping {agent_name}: 3 failed attempts, moving to next")
        # Could implement logic to find next worst agent
        return {"skipped": True, "reason": "too_many_failures"}

    # Load the agent's prompt
    prompt_file = PROMPTS_DIR / f"{agent_name}.md"
    if not prompt_file.exists():
        # Try alternative names
        for alt_name in [f"{agent_name}_desk.md", f"{agent_name}_agent.md"]:
            alt_file = PROMPTS_DIR / alt_name
            if alt_file.exists():
                prompt_file = alt_file
                break

    if not prompt_file.exists():
        log(f"  Prompt file not found for {agent_name}")
        return {"skipped": True, "reason": "prompt_not_found"}

    with open(prompt_file, 'r') as f:
        current_prompt = f.read()

    # Get recent losing recommendations
    from agents.scorecard import get_agent_recommendations
    recent_recs = get_agent_recommendations(agent_name, limit=10)
    losing_recs = [r for r in recent_recs if r.get("return_10d", 0) < 0]

    if not losing_recs:
        log(f"  No losing recommendations to analyze for {agent_name}")
        return {"skipped": True, "reason": "no_losing_recs"}

    # Call Claude to analyze and suggest improvement
    log(f"  Analyzing {agent_name}'s losing trades...")

    analysis_prompt = f"""You are improving an AI trading agent's prompt. The agent "{agent_name}" has been underperforming with a 10-day Sharpe ratio of {sharpe:.3f}.

CURRENT PROMPT:
{current_prompt}

RECENT LOSING RECOMMENDATIONS:
{json.dumps(losing_recs, indent=2)}

Analyze what went wrong with these recommendations. Then suggest ONE targeted modification to the prompt that would help avoid similar losses in the future.

Rules:
- Make exactly ONE change (add, modify, or remove a single instruction)
- Keep the change focused and specific
- Simpler prompts are better - removing unhelpful instructions is valid
- The change should address the specific failure pattern you identified

Output format:
ANALYSIS: [What went wrong]
CHANGE_TYPE: [ADD | MODIFY | REMOVE]
CHANGE_LOCATION: [Which section of the prompt]
CHANGE_DESCRIPTION: [Brief description of the change]
NEW_PROMPT_SECTION: [The exact text to add/modify, or the text to remove]
"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{"role": "user", "content": analysis_prompt}]
        )
        analysis = response.content[0].text

        # Parse the suggested change
        change_desc = _extract_change_description(analysis)

        # Apply the change to the prompt
        # This is simplified - a real implementation would parse and apply the change
        # For now, we'll append a note about what to change
        modified_prompt = _apply_prompt_change(current_prompt, analysis)

        if modified_prompt == current_prompt:
            log(f"  No valid change extracted from analysis")
            return {"skipped": True, "reason": "no_valid_change"}

        # Save the modified prompt
        prompt_version = _get_prompt_version(agent_name) + 1
        backup_file = prompt_file.with_suffix(f".v{prompt_version-1}.bak")

        # Backup current prompt
        with open(backup_file, 'w') as f:
            f.write(current_prompt)

        # Write new prompt
        with open(prompt_file, 'w') as f:
            f.write(modified_prompt)

        # Git commit
        try:
            subprocess.run(
                ["git", "add", str(prompt_file)],
                cwd=ATLAS_DIR,
                capture_output=True
            )
            subprocess.run(
                ["git", "commit", "-m", f"[{agent_name}] v{prompt_version}: {change_desc[:50]}"],
                cwd=ATLAS_DIR,
                capture_output=True
            )
            log(f"  Committed: [{agent_name}] v{prompt_version}")
        except Exception as e:
            log(f"  Git commit failed: {e}", "WARN")

        # Log to autoresearch results
        _log_autoresearch(agent_name, prompt_version, sharpe, weight, "pending", change_desc)

        return {
            "agent": agent_name,
            "version": prompt_version,
            "change": change_desc,
            "status": "pending"
        }

    except Exception as e:
        log(f"  Autoresearch failed: {e}", "ERROR")
        return {"error": str(e)}


def check_previous_experiment() -> Optional[dict]:
    """Check if a previous experiment should be kept or reverted."""
    if not AUTORESEARCH_LOG.exists():
        return None

    with open(AUTORESEARCH_LOG, 'r') as f:
        lines = f.readlines()

    # Find the most recent pending experiment
    for line in reversed(lines):
        if not line.strip():
            continue
        parts = line.strip().split('\t')
        if len(parts) >= 6 and parts[5] == "pending":
            return {
                "date": parts[0],
                "agent": parts[1],
                "commit": parts[2],
                "sharpe_before": float(parts[3]),
                "weight": float(parts[4]),
                "status": parts[5],
                "description": parts[6] if len(parts) > 6 else ""
            }

    return None


def evaluate_experiment(prev_experiment: dict, current_metrics: dict) -> bool:
    """Evaluate if the previous experiment improved the agent."""
    agent = prev_experiment["agent"]
    sharpe_before = prev_experiment["sharpe_before"]

    current_sharpe = current_metrics.get(agent, {}).get("sharpe_10d")

    if current_sharpe is None:
        log(f"  Cannot evaluate {agent}: no current Sharpe")
        return False

    improved = current_sharpe > sharpe_before

    if improved:
        log(f"  KEEP: {agent} improved from {sharpe_before:.3f} to {current_sharpe:.3f}")
        _update_autoresearch_status(agent, "keep")
    else:
        log(f"  REVERT: {agent} did not improve ({sharpe_before:.3f} -> {current_sharpe:.3f})")
        _revert_prompt(agent)
        _update_autoresearch_status(agent, "discard")

    return improved


def _extract_change_description(analysis: str) -> str:
    """Extract change description from Claude's analysis."""
    import re
    match = re.search(r'CHANGE_DESCRIPTION:\s*(.+?)(?:\n|$)', analysis, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return "Prompt modification"


def _apply_prompt_change(current_prompt: str, analysis: str) -> str:
    """Apply the suggested change to the prompt."""
    import re

    # Extract the new section
    match = re.search(r'NEW_PROMPT_SECTION:\s*(.+?)(?:\n\n|$)', analysis, re.IGNORECASE | re.DOTALL)
    if not match:
        return current_prompt

    new_section = match.group(1).strip()

    # Determine change type
    change_type_match = re.search(r'CHANGE_TYPE:\s*(ADD|MODIFY|REMOVE)', analysis, re.IGNORECASE)
    if not change_type_match:
        return current_prompt

    change_type = change_type_match.group(1).upper()

    if change_type == "ADD":
        # Append new section before the Rules section if it exists
        if "## Rules" in current_prompt:
            return current_prompt.replace("## Rules", f"{new_section}\n\n## Rules")
        else:
            return current_prompt + f"\n\n{new_section}"

    elif change_type == "REMOVE":
        # Remove the specified text
        return current_prompt.replace(new_section, "")

    elif change_type == "MODIFY":
        # For modify, we need the location too
        location_match = re.search(r'CHANGE_LOCATION:\s*(.+?)(?:\n|$)', analysis, re.IGNORECASE)
        if location_match:
            location = location_match.group(1).strip()
            # Simple replacement - append note at the location
            if location in current_prompt:
                return current_prompt.replace(location, new_section)

    return current_prompt


def _get_prompt_version(agent_name: str) -> int:
    """Get current version number for an agent's prompt."""
    if not AUTORESEARCH_LOG.exists():
        return 0

    with open(AUTORESEARCH_LOG, 'r') as f:
        lines = f.readlines()

    max_version = 0
    for line in lines:
        parts = line.strip().split('\t')
        if len(parts) >= 2 and parts[1] == agent_name:
            try:
                version = int(parts[2].replace('v', ''))
                max_version = max(max_version, version)
            except:
                pass

    return max_version


def _log_autoresearch(agent: str, version: int, sharpe: float, weight: float, status: str, description: str):
    """Log autoresearch result to TSV file."""
    with open(AUTORESEARCH_LOG, 'a') as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d')}\t{agent}\tv{version}\t{sharpe:.4f}\t{weight:.3f}\t{status}\t{description}\n")


def _update_autoresearch_status(agent: str, new_status: str):
    """Update the status of the most recent experiment for an agent."""
    if not AUTORESEARCH_LOG.exists():
        return

    with open(AUTORESEARCH_LOG, 'r') as f:
        lines = f.readlines()

    # Find and update the most recent pending entry for this agent
    for i in range(len(lines) - 1, -1, -1):
        parts = lines[i].strip().split('\t')
        if len(parts) >= 6 and parts[1] == agent and parts[5] == "pending":
            parts[5] = new_status
            lines[i] = '\t'.join(parts) + '\n'
            break

    with open(AUTORESEARCH_LOG, 'w') as f:
        f.writelines(lines)


def _revert_prompt(agent: str):
    """Revert to the previous prompt version."""
    prompt_file = PROMPTS_DIR / f"{agent}.md"
    if not prompt_file.exists():
        for alt in [f"{agent}_desk.md", f"{agent}_agent.md"]:
            alt_file = PROMPTS_DIR / alt
            if alt_file.exists():
                prompt_file = alt_file
                break

    # Git reset the file
    try:
        subprocess.run(
            ["git", "checkout", "HEAD~1", "--", str(prompt_file)],
            cwd=ATLAS_DIR,
            capture_output=True
        )
        log(f"  Reverted {agent} prompt to previous version")
    except Exception as e:
        log(f"  Failed to revert {agent}: {e}", "WARN")


def _count_recent_attempts(agent: str, days: int = 7) -> int:
    """Count recent failed autoresearch attempts for an agent."""
    if not AUTORESEARCH_LOG.exists():
        return 0

    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    count = 0

    with open(AUTORESEARCH_LOG, 'r') as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) >= 6:
                if parts[1] == agent and parts[0] >= cutoff and parts[5] == "discard":
                    count += 1

    return count


# ============================================================
# MAIN LOOP
# ============================================================

def run_cycle() -> dict:
    """Run one complete cycle of the autonomous loop."""
    cycle_start = datetime.now()
    log("=" * 60)
    log(f"ATLAS AUTONOMOUS CYCLE - {cycle_start.strftime('%Y-%m-%d %H:%M')}")
    log("=" * 60)

    results = {
        "start": cycle_start.isoformat(),
        "phases": {}
    }

    # Phase A: Market Data
    market_data = fetch_market_data()
    results["phases"]["market_data"] = {"status": "ok" if "error" not in market_data else "error"}

    # Phase B: Agent Debate
    all_views = run_agent_debate(market_data)
    results["phases"]["debate"] = {"status": "ok" if "error" not in all_views else "error", "agents": len(all_views)}

    # Phase C: Trade
    trades = execute_trades(all_views, market_data)
    results["phases"]["trade"] = {"status": "ok", "trades_executed": len(trades)}

    # Phase D: Learn
    scorecard_data = update_scorecards(all_views)
    results["phases"]["learn"] = {"status": "ok" if "error" not in scorecard_data else "error"}

    # Check previous experiment before running new one
    prev_experiment = check_previous_experiment()
    if prev_experiment:
        log(f"  Evaluating previous experiment on {prev_experiment['agent']}...")
        metrics = scorecard_data.get("metrics", {})
        evaluate_experiment(prev_experiment, metrics)

    # Send briefing
    send_briefing(all_views, trades, scorecard_data)

    # Phase E: Improve (Autoresearch)
    autoresearch_result = run_autoresearch(scorecard_data)
    results["phases"]["improve"] = autoresearch_result

    # Summary
    cycle_end = datetime.now()
    duration = (cycle_end - cycle_start).total_seconds()
    results["end"] = cycle_end.isoformat()
    results["duration_seconds"] = duration

    log("=" * 60)
    log(f"CYCLE COMPLETE - Duration: {duration:.1f}s")
    log("=" * 60)

    return results


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="ATLAS Autonomous Loop")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    args = parser.parse_args()

    log("ATLAS AUTONOMOUS LOOP STARTING")
    log(f"Mode: {'Single cycle' if args.once else 'Continuous'}")

    # Initialize autoresearch log if needed
    if not AUTORESEARCH_LOG.exists():
        with open(AUTORESEARCH_LOG, 'w') as f:
            f.write("date\tagent\tcommit\tsharpe_10d\tweight\tstatus\tdescription\n")

    if args.once:
        # Run one cycle and exit
        if not is_market_day():
            log("Not a market day - exiting")
            return

        result = run_cycle()
        log(f"Result: {json.dumps(result, indent=2)}")
    else:
        # Continuous mode
        while True:
            try:
                if is_market_day():
                    # Wait for market close
                    wait_for_market_close()

                    # Run the cycle
                    result = run_cycle()

                    # Save result
                    result_file = STATE_DIR / "last_cycle_result.json"
                    with open(result_file, 'w') as f:
                        json.dump(result, f, indent=2)
                else:
                    log("Weekend - sleeping until Monday")
                    # Sleep until Monday
                    now = datetime.now(ET)
                    days_until_monday = (7 - now.weekday()) % 7 or 7
                    sleep_until = now + timedelta(days=days_until_monday)
                    sleep_until = sleep_until.replace(hour=16, minute=30, second=0)
                    sleep_seconds = (sleep_until - now).total_seconds()
                    time.sleep(sleep_seconds)

            except KeyboardInterrupt:
                log("Interrupted by user - shutting down")
                break
            except Exception as e:
                log(f"Cycle error: {e}", "ERROR")
                # Sleep 5 minutes and retry
                time.sleep(300)


if __name__ == "__main__":
    main()
