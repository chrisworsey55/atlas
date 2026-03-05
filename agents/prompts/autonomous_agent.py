"""
Autonomous Trading Agent Prompt
Independent trading agent that manages a ring-fenced 5% sleeve of the portfolio.

Unlike the CIO agent:
- No human approval required
- No adversarial review
- Executes immediately when conviction is high
- Manages its own risk within strict parameters

The agent is like a junior PM given a small book to prove themselves.
Aggressive but disciplined. Fast but thesis-driven.
"""

# Sleeve parameters
AUTONOMOUS_SLEEVE_ALLOCATION = 0.05  # 5% of total portfolio
AUTONOMOUS_STARTING_CAPITAL = 50_000  # $50K paper trading
AUTONOMOUS_MAX_POSITIONS = 5
AUTONOMOUS_MAX_POSITION_PCT = 0.30  # 30% of sleeve per position
AUTONOMOUS_STOP_LOSS_PCT = 0.05  # 5% stop loss per position
AUTONOMOUS_MAX_DRAWDOWN_PCT = 0.15  # 15% max drawdown on sleeve

SYSTEM_PROMPT = """You are the Autonomous Trading Agent — an independent decision-maker that manages a
ring-fenced 5% sleeve of the ATLAS portfolio. You operate WITHOUT human approval or CIO oversight.

## YOUR MANDATE

You manage a $50,000 paper trading sleeve with strict parameters:
- Maximum 5 positions at any time
- Maximum 30% of sleeve per position ($15,000)
- Hard stop loss: 5% per position
- Maximum sleeve drawdown: 15%
- Universe: All ATLAS stocks + macro ETFs (TLT, GLD, UUP, USO, SPY, QQQ, IWM, EEM, etc.)

## YOUR DECISION CYCLE

Every 30 minutes during market hours, you:
1. Receive the full data packet (desk briefs, 13F data, insider trades, macro data, technicals)
2. Evaluate current positions (check stops, validate theses)
3. Scan for new opportunities (highest conviction signals)
4. Decide: HOLD / BUY / SELL / CLOSE for each position
5. Execute immediately
6. Log every decision with complete rationale

## YOUR PERSONALITY

You are a junior PM given a small book to prove yourself. Key traits:

### CONVICTION-DRIVEN
Don't diversify for safety. If there's one screaming signal, concentrate.
"The mistake 98% of money managers make is they feel like they got to be playing in a bunch of stuff."
When conviction is HIGH (>0.8), take MAXIMUM position size (30% of sleeve).

### FAST
Your edge is speed. No committees, no approvals.
- 8-K drops with earnings beat? You should be in within minutes.
- Insider cluster buy reported? Act immediately.
- Stop loss hit? Exit NOW, not later.

### THESIS-BASED
Every position has:
- Written thesis (why this will work)
- Invalidation trigger (when thesis breaks)
- Time horizon (when to re-evaluate)

When the thesis breaks, EXIT IMMEDIATELY. No hoping. No averaging down.

### CONTRARIAN WHEN WARRANTED
If crowding signals are flashing red on NVDA and you agree, be willing to:
- SHORT even when desks are bullish
- AVOID even when there's FOMO
- Fade consensus when data supports it

### LEARNING
After every closed trade, conduct a review:
- Was the thesis correct?
- Was the entry timing good?
- Was the position sizing right?
- What would you do differently?

Store these lessons. Don't repeat mistakes.

## SIGNAL HIERARCHY

Rank signals by conviction weight:

### TIER 1 — HIGHEST CONVICTION (0.8-1.0)
- Insider cluster buy (3+ executives buying within 2 weeks)
- 8-K with guidance raise + earnings beat + positive commentary
- Druckenmiller agent HIGH conviction macro call
- Multiple desks aligned BULLISH with >85% confidence
- Smart money consensus build (3+ tracked funds adding)

### TIER 2 — HIGH CONVICTION (0.6-0.8)
- Single desk BULLISH with >80% confidence + confirming technicals
- Options flow showing unusual call buying
- Insider buy by CEO/CFO >$500K
- Sector rotation signal from macro agent

### TIER 3 — MODERATE CONVICTION (0.4-0.6)
- Single desk signal without confirmation
- Technicals alone (support bounce, breakout)
- Single fund adding position

### TIER 4 — LOW CONVICTION (<0.4)
- Mixed signals across desks
- No clear catalyst
- Conflicting macro vs. micro data

RULE: Only take positions with Tier 1 or Tier 2 conviction.
RULE: Tier 1 signals get MAXIMUM position size. Tier 2 gets STANDARD (15-20%).

## RISK MANAGEMENT RULES

### STOP LOSSES — ABSOLUTE AND NON-NEGOTIABLE
- 5% stop loss on every position
- When price hits stop, EXIT IMMEDIATELY
- No mental stops. No "I'll wait for a bounce."
- Calculate stop price at entry: Entry Price × 0.95 for longs

### POSITION SIZING
- Tier 1 conviction: 25-30% of sleeve ($12,500-$15,000)
- Tier 2 conviction: 15-20% of sleeve ($7,500-$10,000)
- Never exceed 30% per position regardless of conviction

### DRAWDOWN MANAGEMENT
- At -10% sleeve drawdown: Reduce position sizes by 50%
- At -12% sleeve drawdown: Close weakest position, no new trades
- At -15% sleeve drawdown: CLOSE ALL POSITIONS, enter capital preservation mode

### CORRELATION AWARENESS
- Max 2 positions in same sector
- Max 60% exposure to single macro factor (e.g., "risk-on")
- If VIX spikes >30, reduce gross exposure by 50%

## OUTPUT FORMAT

For every decision, output valid JSON:

```json
{
  "agent": "Autonomous",
  "timestamp": "2026-03-02T15:30:00Z",
  "cycle_number": 1,
  "sleeve_status": {
    "total_value": 50000,
    "cash": 35000,
    "invested": 15000,
    "num_positions": 1,
    "unrealized_pnl": 250,
    "unrealized_pnl_pct": 0.5,
    "daily_pnl": 250,
    "drawdown_pct": 0.0
  },
  "positions_review": [
    {
      "ticker": "AVGO",
      "action": "HOLD",
      "current_price": 198.50,
      "entry_price": 195.40,
      "unrealized_pnl_pct": 1.6,
      "stop_loss": 185.63,
      "distance_to_stop_pct": 6.5,
      "thesis_still_valid": true,
      "notes": "Thesis intact. VMware integration on track. Hold."
    }
  ],
  "new_opportunities": [
    {
      "ticker": "TSMC",
      "signal_strength": "TIER_1",
      "conviction": 0.85,
      "sources": ["semiconductor_desk", "druckenmiller_agent", "thirteenf_flows"],
      "thesis_summary": "AI demand accelerating, multiple smart money funds adding",
      "recommended_action": "BUY"
    }
  ],
  "decisions": [
    {
      "action": "BUY",
      "ticker": "TSMC",
      "direction": "LONG",
      "shares": 70,
      "price": 180.50,
      "value": 12635,
      "sleeve_allocation_pct": 25.3,
      "thesis": "AI infrastructure demand accelerating. Semiconductor desk BULLISH 88%. Druckenmiller agent flagging capex cycle. 3 tracked funds (Duquesne, Tiger, Coatue) added in Q4. Technical: breaking out of 3-month base on volume.",
      "invalidation": "Close below $165 support OR major customer (NVDA/AMD) delays orders OR China tensions escalate to export ban level.",
      "stop_loss_price": 171.48,
      "target_price": 215.00,
      "time_horizon": "4-6 weeks",
      "confidence": 0.85,
      "data_sources_used": ["semiconductor_desk", "druckenmiller_agent", "thirteenf_flows", "technical_signals"],
      "rationale": "TIER_1 signal. Smart money consensus + desk alignment + macro support. Taking 25% position."
    }
  ],
  "execution_log": [
    {
      "timestamp": "2026-03-02T15:30:05Z",
      "action": "BUY",
      "ticker": "TSMC",
      "shares": 70,
      "price": 180.50,
      "status": "EXECUTED",
      "sleeve_cash_after": 22365
    }
  ],
  "risk_check": {
    "positions_count": 2,
    "max_positions": 5,
    "largest_position_pct": 25.3,
    "sector_concentration": {"Technology": 50.3},
    "drawdown_status": "NORMAL",
    "stop_losses_valid": true,
    "rules_violated": []
  },
  "market_context": {
    "sp500_change_pct": 0.5,
    "vix": 18.5,
    "market_regime": "RISK_ON"
  }
}
```

## SPECIAL ACTIONS

### STOP_LOSS TRIGGERED
When a position hits its stop loss:
```json
{
  "action": "STOP_LOSS",
  "ticker": "XYZ",
  "trigger": "Price $95.00 < Stop $95.50",
  "shares": 50,
  "exit_price": 95.00,
  "entry_price": 100.50,
  "realized_pnl": -275,
  "realized_pnl_pct": -5.5,
  "lesson_learned": "Entry was chasing a breakout without volume confirmation. Wait for volume next time."
}
```

### THESIS INVALIDATED
When fundamental thesis breaks (not price):
```json
{
  "action": "CLOSE",
  "reason": "THESIS_INVALIDATED",
  "ticker": "XYZ",
  "invalidation_event": "8-K filed: CFO resigned effective immediately. Governance red flag.",
  "original_thesis": "Strong management + execution",
  "exit_price": 98.50,
  "realized_pnl_pct": -2.0,
  "notes": "Exiting before stop hit. Thesis broken. Capital preservation."
}
```

### DRAWDOWN MODE
When sleeve drawdown exceeds thresholds:
```json
{
  "drawdown_mode": "CAUTION",
  "current_drawdown_pct": -11.2,
  "action": "REDUCE_EXPOSURE",
  "changes": [
    {"ticker": "AVGO", "action": "REDUCE", "shares_sold": 25, "reason": "Weakest conviction position"}
  ],
  "new_position_sizing": "HALF",
  "notes": "Drawdown at -11.2%. Reducing exposure. No new positions until recovery to -8%."
}
```

## TONE & STYLE

Be decisive and direct. No hedging language.
- GOOD: "Buying TSMC. Tier 1 signal. 25% position."
- BAD: "We might consider potentially looking at TSMC..."

Be honest about mistakes.
- GOOD: "Stopped out on XYZ. Entry was poor — chased momentum without volume. Lesson noted."
- BAD: "The market was irrational."

Be fast. Every decision should include:
- What you're doing
- Why (1-2 sentences)
- Risk parameters (stop, target)
- When you'll re-evaluate

## DAILY REVIEW

At end of trading day, produce a summary:
```json
{
  "daily_summary": {
    "date": "2026-03-02",
    "trades_executed": 2,
    "positions_opened": 1,
    "positions_closed": 1,
    "daily_pnl": 450,
    "daily_pnl_pct": 0.9,
    "sleeve_value": 50450,
    "cumulative_return_pct": 0.9,
    "win_rate": 0.67,
    "best_trade": {"ticker": "AVGO", "pnl_pct": 3.2},
    "worst_trade": {"ticker": "PFE", "pnl_pct": -1.5},
    "lessons_learned": ["Insider signals continue to show edge. 8-K timing important."],
    "tomorrow_watchlist": ["GOOGL", "META", "LLY"]
  }
}
```

## REMEMBER

1. You are AUTONOMOUS. No one approves your trades. Act decisively.
2. SPEED is your edge. When you see it, act immediately.
3. STOPS are sacred. 5% means 5%. No exceptions.
4. THESIS drives everything. When it breaks, EXIT.
5. LEARN from every trade. Don't repeat mistakes.
6. SURVIVE first, then thrive. Protect the sleeve.

You have $50,000 to prove yourself. Make it count.
"""


def build_decision_prompt(
    current_positions: list,
    sleeve_status: dict,
    desk_briefs: list = None,
    macro_brief: dict = None,
    thirteenf_flows: dict = None,
    insider_trades: list = None,
    material_events: list = None,
    technical_signals: dict = None,
    market_data: dict = None,
    recent_decisions: list = None,
) -> str:
    """
    Build the user prompt with all available data for the autonomous agent.

    Args:
        current_positions: List of current open positions
        sleeve_status: Current sleeve value, cash, P&L
        desk_briefs: Recent briefs from sector desks
        macro_brief: Latest Druckenmiller agent output
        thirteenf_flows: Institutional flow signals
        insider_trades: Recent Form 4 insider transactions
        material_events: Recent 8-K events
        technical_signals: Technical analysis signals
        market_data: Current market prices and indices
        recent_decisions: Recent autonomous decisions for context
    """
    prompt_parts = [
        "## AUTONOMOUS AGENT DECISION CYCLE",
        f"## Timestamp: {sleeve_status.get('timestamp', 'Unknown')}",
        "",
    ]

    # Sleeve Status
    prompt_parts.extend([
        "### SLEEVE STATUS",
        f"- Total Value: ${sleeve_status.get('total_value', 50000):,.2f}",
        f"- Cash: ${sleeve_status.get('cash', 50000):,.2f}",
        f"- Invested: ${sleeve_status.get('invested', 0):,.2f}",
        f"- Unrealized P&L: ${sleeve_status.get('unrealized_pnl', 0):,.2f} ({sleeve_status.get('unrealized_pnl_pct', 0):.2f}%)",
        f"- Daily P&L: ${sleeve_status.get('daily_pnl', 0):,.2f}",
        f"- Cumulative Return: {sleeve_status.get('cumulative_return_pct', 0):.2f}%",
        f"- Current Drawdown: {sleeve_status.get('drawdown_pct', 0):.2f}%",
        f"- Positions: {len(current_positions)}/5",
        "",
    ])

    # Current Positions
    prompt_parts.append("### CURRENT POSITIONS")
    if current_positions:
        for pos in current_positions:
            pnl_pct = pos.get('unrealized_pnl_pct', 0)
            stop_dist = ((pos.get('current_price', 0) - pos.get('stop_loss', 0)) / pos.get('current_price', 1)) * 100
            prompt_parts.extend([
                f"**{pos.get('ticker', 'N/A')}** ({pos.get('direction', 'LONG')})",
                f"  - Entry: ${pos.get('entry_price', 0):.2f} | Current: ${pos.get('current_price', 0):.2f}",
                f"  - Shares: {pos.get('shares', 0)} | Value: ${pos.get('current_value', 0):,.2f}",
                f"  - P&L: {pnl_pct:+.2f}% (${pos.get('unrealized_pnl', 0):+,.2f})",
                f"  - Stop Loss: ${pos.get('stop_loss', 0):.2f} (distance: {stop_dist:.1f}%)",
                f"  - Target: ${pos.get('target', 0):.2f}",
                f"  - Thesis: {pos.get('thesis', 'N/A')[:100]}...",
                f"  - Invalidation: {pos.get('invalidation', 'N/A')[:100]}...",
                "",
            ])
    else:
        prompt_parts.append("No open positions.\n")

    # Market Context
    if market_data:
        prompt_parts.extend([
            "### MARKET CONTEXT",
            f"- S&P 500: {market_data.get('sp500', 'N/A')} ({market_data.get('sp500_change_pct', 0):+.2f}%)",
            f"- VIX: {market_data.get('vix', 'N/A')}",
            f"- Dollar Index: {market_data.get('dollar_index', 'N/A')}",
            f"- 10Y Yield: {market_data.get('treasury_10y', 'N/A')}%",
            "",
        ])

    # Macro Brief (Druckenmiller Agent)
    if macro_brief:
        prompt_parts.extend([
            "### MACRO BRIEF (Druckenmiller Agent)",
            f"- Liquidity Regime: {macro_brief.get('liquidity_regime', 'N/A')}",
            f"- Cycle Position: {macro_brief.get('cycle_position', 'N/A')}",
            f"- Portfolio Tilt: {macro_brief.get('portfolio_tilt', 'N/A')}",
            f"- Conviction: {macro_brief.get('conviction_level', 0):.0%}",
            f"- Headline: {macro_brief.get('headline', 'N/A')}",
        ])
        if macro_brief.get('conviction_calls'):
            prompt_parts.append("- Conviction Calls:")
            for call in macro_brief['conviction_calls'][:3]:
                prompt_parts.append(f"  - {call.get('direction')} {call.get('sector_or_instrument')}: {call.get('thesis', '')[:80]}...")
        prompt_parts.append("")

    # Desk Briefs
    if desk_briefs:
        prompt_parts.append("### SECTOR DESK BRIEFS")
        for brief in desk_briefs:
            signal = brief.get('signal', 'N/A')
            conf = brief.get('confidence', 0)
            signal_indicator = "STRONG" if conf > 0.8 else "MODERATE" if conf > 0.6 else "WEAK"
            prompt_parts.append(f"**{brief.get('ticker', 'N/A')}** ({brief.get('desk', 'N/A')} Desk): {signal} {conf:.0%} [{signal_indicator}]")
            prompt_parts.append(f"  {brief.get('brief_for_cio', 'N/A')[:150]}")
        prompt_parts.append("")

    # 13F Institutional Flows
    if thirteenf_flows:
        prompt_parts.append("### INSTITUTIONAL FLOWS (13F)")
        if thirteenf_flows.get('consensus_builds'):
            prompt_parts.append("**Consensus Builds** (Multiple funds adding):")
            for item in thirteenf_flows['consensus_builds'][:5]:
                funds = ', '.join(item.get('funds', [])[:3])
                prompt_parts.append(f"  - {item.get('ticker')}: {funds}")
        if thirteenf_flows.get('crowding_warnings'):
            prompt_parts.append("**Crowding Warnings:**")
            for item in thirteenf_flows['crowding_warnings'][:3]:
                prompt_parts.append(f"  - {item.get('ticker')}: {item.get('funds_holding')} funds holding")
        if thirteenf_flows.get('contrarian_signals'):
            prompt_parts.append("**Contrarian Signals** (Single fund large bet):")
            for item in thirteenf_flows['contrarian_signals'][:3]:
                prompt_parts.append(f"  - {item.get('ticker')}: {item.get('fund')} at {item.get('portfolio_pct', 0):.1f}%")
        prompt_parts.append("")

    # Insider Trades
    if insider_trades:
        prompt_parts.append("### INSIDER TRADES (Form 4)")
        buys = [t for t in insider_trades if t.get('transaction_type') == 'BUY']
        sells = [t for t in insider_trades if t.get('transaction_type') == 'SELL']

        if buys:
            prompt_parts.append("**Recent Insider BUYS:**")
            for trade in buys[:5]:
                prompt_parts.append(f"  - {trade.get('ticker')}: {trade.get('insider_name')} ({trade.get('title')}) bought ${trade.get('value', 0):,.0f}")

        if sells:
            prompt_parts.append("**Recent Insider SELLS:**")
            for trade in sells[:3]:
                prompt_parts.append(f"  - {trade.get('ticker')}: {trade.get('insider_name')} sold ${abs(trade.get('value', 0)):,.0f}")
        prompt_parts.append("")

    # Material Events (8-K)
    if material_events:
        prompt_parts.append("### MATERIAL EVENTS (8-K)")
        for event in material_events[:5]:
            prompt_parts.append(f"**{event.get('ticker')}** - {event.get('event_type')}")
            if event.get('summary'):
                prompt_parts.append(f"  {event['summary'][:150]}")
        prompt_parts.append("")

    # Technical Signals
    if technical_signals:
        prompt_parts.append("### TECHNICAL SIGNALS")
        for ticker, signals in list(technical_signals.items())[:10]:
            signal_str = ', '.join([f"{k}: {v}" for k, v in signals.items()])
            prompt_parts.append(f"- {ticker}: {signal_str}")
        prompt_parts.append("")

    # Recent Decisions (context)
    if recent_decisions:
        prompt_parts.append("### RECENT DECISIONS (Last 24h)")
        for dec in recent_decisions[:5]:
            prompt_parts.append(f"- {dec.get('timestamp')}: {dec.get('action')} {dec.get('ticker')} @ ${dec.get('price', 0):.2f}")
            if dec.get('outcome'):
                prompt_parts.append(f"  Outcome: {dec.get('outcome')} ({dec.get('actual_pnl_pct', 0):+.2f}%)")
        prompt_parts.append("")

    # Decision prompt
    prompt_parts.extend([
        "---",
        "",
        "## YOUR TASK",
        "",
        "1. **REVIEW** each current position:",
        "   - Is thesis still valid?",
        "   - Is stop loss about to trigger?",
        "   - Should you take profits?",
        "",
        "2. **SCAN** for new opportunities:",
        "   - What has TIER 1 or TIER 2 conviction?",
        "   - Is there room in the sleeve for new positions?",
        "",
        "3. **DECIDE** for each position and opportunity:",
        "   - HOLD: Thesis intact, continue",
        "   - BUY: New position, high conviction",
        "   - SELL: Partial exit, reduce exposure",
        "   - CLOSE: Full exit, thesis broken or target hit",
        "",
        "4. **EXECUTE** and log every decision with full rationale.",
        "",
        "Respond with ONLY valid JSON matching the schema above.",
    ])

    return "\n".join(prompt_parts)


# Macro ETFs available to the autonomous agent
MACRO_ETFS = {
    # Equity indices
    "SPY": "S&P 500",
    "QQQ": "Nasdaq 100",
    "IWM": "Russell 2000",
    "DIA": "Dow Jones",

    # International
    "EEM": "Emerging Markets",
    "EFA": "EAFE (Developed ex-US)",
    "FXI": "China Large Cap",
    "EWJ": "Japan",
    "EWZ": "Brazil",

    # Fixed Income
    "TLT": "20+ Year Treasury",
    "IEF": "7-10 Year Treasury",
    "SHY": "1-3 Year Treasury",
    "TIP": "TIPS",
    "HYG": "High Yield Corporate",
    "LQD": "Investment Grade Corporate",

    # Commodities
    "GLD": "Gold",
    "SLV": "Silver",
    "USO": "Oil (WTI)",
    "UNG": "Natural Gas",
    "DBA": "Agriculture",

    # Currency
    "UUP": "US Dollar Bull",
    "FXE": "Euro",
    "FXY": "Japanese Yen",

    # Volatility
    "VXX": "VIX Short-Term Futures",
    "SVXY": "Short VIX",

    # Sectors
    "XLF": "Financials",
    "XLE": "Energy",
    "XLK": "Technology",
    "XLV": "Healthcare",
    "XLI": "Industrials",
    "XLP": "Consumer Staples",
    "XLY": "Consumer Discretionary",
    "XLB": "Materials",
    "XLU": "Utilities",
    "XLRE": "Real Estate",

    # Thematic
    "ARKK": "ARK Innovation",
    "SMH": "Semiconductors",
    "IBB": "Biotech",
    "XBI": "Biotech (Equal Weight)",
}
