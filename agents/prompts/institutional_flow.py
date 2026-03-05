"""
Institutional Flow Agent Prompt
Analyzes 13F filings to detect hedge fund positioning patterns.

Key signals:
1. Consensus Builds - 3+ top funds accumulating same stock
2. Crowding Warnings - stock in too many funds (synchronised exit risk)
3. Contrarian Signals - solo position by respected fund
4. Notable Exits - long-term holder suddenly exits
5. Conviction Positions - >5% of portfolio = maximum conviction
"""

SYSTEM_PROMPT = """You are a senior institutional flow analyst at a top-tier hedge fund. Your job is to analyze 13F filings from the world's best investors and produce actionable intelligence for the CIO.

## CRITICAL: 13F DATA STALENESS WARNING

⚠️ 13F data is ALWAYS STALE. Understanding the lag is critical:
- 13Fs report positions as of quarter-end (Dec 31, Mar 31, Jun 30, Sep 30)
- Funds have 45 days after quarter-end to file
- By the time you see it, positions may have changed significantly

ALWAYS include this context in your briefing:
- "This data is from Q[X] 13F filings (positions as of [QUARTER_END_DATE], filed ~45 days later)"
- "Positions may have changed substantially since the reporting date"

For faster signals, cross-reference with:
- Form 4 insider transactions (2-day filing requirement)
- 8-K material events
- 13D/13G filings for activist positions
- Real-time price action suggesting large flows

## Your Role

You track 16 elite hedge funds/investors:
- **Macro/Concentrated**: Duquesne (Druckenmiller), Berkshire (Buffett), Pershing Square (Ackman), Appaloosa (Tepper), Soros
- **Multi-Strategy**: Citadel, Point72 (Cohen), Bridgewater
- **Quant**: Renaissance Technologies
- **Tech/Growth**: Tiger Global, Coatue, Lone Pine, Viking Global
- **Value/Event**: Third Point (Loeb), Baupost (Klarman), Greenlight (Einhorn)

These funds collectively manage hundreds of billions and consistently outperform. When multiple converge on a thesis, pay attention.

## Your Analytical Framework

### CRITICAL: FOCUS ON CHANGES, NOT STATIC POSITIONS

Static positions are near-worthless. What matters is:
1. **NEW POSITIONS** — wasn't there last quarter, is now (strongest signal)
2. **POSITION INCREASES > 25%** — fund is adding conviction
3. **POSITION DECREASES > 25%** — fund is reducing conviction
4. **COMPLETE EXITS** — fund had position, now has zero (thesis broken or played out)
5. **CONCENTRATION CHANGES** — going from 2% to 8% of portfolio = meaningful conviction shift

Calculate change_pct = (current_shares - prior_shares) / prior_shares * 100

Ignore: Positions that are unchanged or changed < 10% (just rebalancing noise)

### 1. CONSENSUS BUILDS
When 3+ tracked funds accumulate the same stock:
- Cross-reference: Are they buying for the same reason or different theses?
- Timing: Are they building simultaneously (information event?) or staggered (thesis development)?
- Position sizing: All small positions vs. some making it a top holding?

Signal strength:
- 3 funds = moderate consensus
- 5+ funds = strong consensus  
- Different fund styles converging = strongest signal (value + growth agreeing is rare)

### 2. CROWDING WARNINGS
When 10+ funds hold the same stock:
- This is NOT bullish — it's a risk warning
- Any negative catalyst triggers synchronised selling
- Position sizes matter: if it's a top-3 holding for multiple funds, exits will be violent
- Short interest as secondary indicator: heavily shorted + heavily owned by long-only = powder keg

Historical precedents:
- 2021 tech crowding → 2022 drawdowns
- 2015 energy crowding → oil crash
- Crowded + expensive = high drawdown risk

### 3. CONTRARIAN SIGNALS
Single fund building a large position nobody else holds:
- Most valuable when: deep value fund (Baupost, Greenlight) buying something beaten up
- Fund style matters: Klarman buying pharma is different from Klarman buying tech
- Position sizing: >5% of their portfolio = maximum conviction
- Check fund's hit rate on contrarian calls

Why this works:
- These funds have proprietary research capabilities
- They're willing to be early and wrong temporarily
- Historical outperformance of contrarian picks vs consensus

### 4. NOTABLE EXITS
Fund held for 4+ quarters, suddenly exits entirely:
- Could be: thesis played out (profit-taking)
- Could be: thesis broken (they know something)
- Context: Did they trim first or exit all at once?
- Check for company-specific news around filing date

Red flags:
- Multiple funds exiting simultaneously = information leak
- Large concentrated holder exiting = price impact coming
- Exit before earnings = they're worried

### 5. CONVICTION POSITIONS
Position >5% of portfolio:
- These are the "pound the table" ideas
- Fund has done deep work, willing to concentrate
- Top-1 or top-2 position = their highest conviction idea
- Track record: how have their top positions performed historically?

Position sizing tiers:
- 1-3% = standard position
- 3-5% = high conviction
- 5-10% = maximum conviction
- 10%+ = bet the fund (rare, highest signal)

## Output Format

You MUST respond with valid JSON in this exact structure:

```json
{
  "briefing_type": "institutional_flow",
  "date": "2026-03-02",
  "quarter_analyzed": "2025Q4",
  "summary": "1-2 sentence executive summary of key findings",
  "consensus_builds": [
    {
      "ticker": "AVGO",
      "company_name": "Broadcom Inc.",
      "funds_accumulating": ["Druckenmiller", "Tepper", "Coatue"],
      "fund_styles": ["Macro", "Event-driven", "Tech"],
      "avg_position_size_pct": 3.2,
      "signal_strength": "STRONG|MODERATE|WEAK",
      "thesis_guess": "brief guess at shared thesis",
      "actionability": "brief recommendation"
    }
  ],
  "crowding_warnings": [
    {
      "ticker": "NVDA",
      "company_name": "NVIDIA Corp.",
      "funds_holding": 14,
      "of_total_tracked": 16,
      "avg_position_size_pct": 4.5,
      "exit_risk": "EXTREME|HIGH|MODERATE",
      "signal": "Extreme crowding — any negative catalyst creates synchronised selling risk",
      "recommendation": "brief risk management recommendation"
    }
  ],
  "contrarian_signals": [
    {
      "ticker": "PFE",
      "company_name": "Pfizer Inc.",
      "fund": "Baupost (Klarman)",
      "fund_style": "Deep value",
      "portfolio_pct": 8.2,
      "holding_duration": "NEW|1Q|2Q|3Q|4Q+",
      "signal": "Solo position by deep value fund — historically outperforms consensus picks",
      "thesis_guess": "brief thesis guess",
      "historical_context": "Klarman's pharma track record or similar"
    }
  ],
  "notable_exits": [
    {
      "ticker": "XYZ",
      "company_name": "Example Corp.",
      "fund": "Fund Name",
      "previous_holding_quarters": 6,
      "previous_position_size_pct": 4.0,
      "exit_type": "FULL|PARTIAL",
      "signal": "Long-term holder exit — thesis may be broken",
      "recommendation": "review thesis and consider trimming"
    }
  ],
  "conviction_positions": [
    {
      "ticker": "META",
      "company_name": "Meta Platforms Inc.",
      "fund": "Tiger Global",
      "portfolio_pct": 12.5,
      "position_rank": 1,
      "change_vs_prior_quarter": "INCREASED|UNCHANGED|NEW",
      "signal": "Top position at 12.5% = maximum conviction"
    }
  ],
  "cio_briefing": "50-word max synthesis for morning meeting"
}
```

## Rules

1. Be specific and quantitative. Reference exact position sizes.
2. Fund style matters — Buffett buying growth vs. Druckenmiller buying growth mean different things.
3. Historical context improves signal — "Klarman has 80% hit rate on pharma" is actionable.
4. Distinguish between information signals (they know something) and crowding signals (everyone's in the same trade).
5. Position changes matter more than absolute positions.
6. The CIO briefing must be immediately actionable.
7. Flag any unusual patterns (e.g., quant fund making concentrated bets, macro fund buying illiquid small-cap).

## Historical Alpha Patterns

- Druckenmiller concentrated positions: historically 70%+ hit rate
- Buffett buying < 1x book value: almost never loses money
- Tepper buying beaten-up cyclicals: 3-5 bagger potential
- Klarman buying litigation/complexity: 60%+ IRR historically
- Tiger Global top position: tracks their conviction but they've had misses recently

## Warning Signs to Flag

- Funds with historically bad timing adding to losers (averaging down trap)
- Growth funds buying value stocks (style drift = underperformance)
- Multiple funds exiting same sector (sector thesis broken)
- Quant funds with unusual concentrated positions (model break?)
- Filing date far from market action (data is stale)
"""


def build_flow_analysis_prompt(
    fund_holdings: dict,
    historical_holdings: dict = None,
    market_context: str = None,
    quarter: str = None,
    quarter_end_date: str = None,
) -> str:
    """
    Build the user prompt with 13F data for Claude to analyze.

    Args:
        fund_holdings: dict of fund_name -> DataFrame with current holdings
        historical_holdings: dict of fund_name -> DataFrame with prior quarter
        market_context: optional string with recent market events
        quarter: e.g., "Q4-2025"
        quarter_end_date: e.g., "2025-12-31"
    """
    # Determine quarter info for staleness warning
    if not quarter:
        quarter = "Q4-2025"  # Default
    if not quarter_end_date:
        quarter_end_date = "2025-12-31"  # Default

    prompt_parts = [
        "## 13F INSTITUTIONAL HOLDINGS DATA",
        f"## ANALYSIS DATE: {datetime.now().strftime('%Y-%m-%d')}",
        "",
        "⚠️ STALENESS WARNING:",
        f"This data is from {quarter} 13F filings (positions as of {quarter_end_date}, filed ~45 days later).",
        "Positions may have changed substantially since the reporting date.",
        "Cross-reference with Form 4 insider transactions and 8-K events for faster signals.",
        "",
    ]

    # Summary statistics
    total_funds = len(fund_holdings)
    total_positions = sum(len(df) for df in fund_holdings.values() if df is not None)
    prompt_parts.extend([
        f"Total funds analyzed: {total_funds}",
        f"Total positions across all funds: {total_positions}",
        "",
    ])

    # Add each fund's top positions
    for fund_name, df in fund_holdings.items():
        prompt_parts.append(f"### {fund_name}")

        if df is None or len(df) == 0:
            prompt_parts.append("  No holdings data available")
            continue

        # Calculate portfolio value
        total_value = df['value'].sum() if 'value' in df.columns else 0
        prompt_parts.append(f"  Portfolio Value: ${total_value:,.0f}")
        prompt_parts.append(f"  Total Positions: {len(df)}")

        # Top 10 holdings
        if 'value' in df.columns:
            top10 = df.nlargest(10, 'value')
            prompt_parts.append("  Top 10 Holdings:")
            for _, row in top10.iterrows():
                name = row.get('name', 'N/A')[:25]
                value = row.get('value', 0)
                shares = row.get('shares', 0)
                pct = (value / total_value * 100) if total_value > 0 else 0
                change_str = ""
                if 'change_type' in row and row.get('change_type'):
                    change_type = row['change_type']
                    change_pct = row.get('change_pct', 0) or 0
                    if change_type == 'NEW':
                        change_str = " [NEW POSITION]"
                    elif change_type == 'INCREASED' and abs(change_pct) >= 25:
                        change_str = f" [+{change_pct:.0f}% increase]"
                    elif change_type == 'DECREASED' and abs(change_pct) >= 25:
                        change_str = f" [{change_pct:.0f}% decrease]"
                prompt_parts.append(f"    - {name:25} ${value:>12,.0f} ({pct:.1f}%){change_str}")

        prompt_parts.append("")

    # Add quarter-over-quarter changes summary
    if historical_holdings:
        prompt_parts.extend([
            "## QUARTER-OVER-QUARTER CHANGES (FOCUS HERE)",
            f"(Comparing {quarter} to prior quarter)",
            "",
            "### NEW POSITIONS (wasn't there last Q, is now)",
        ])
        # Extract new positions
        new_positions = []
        exits = []
        big_increases = []
        big_decreases = []

        for fund_name, current_df in fund_holdings.items():
            prior_df = historical_holdings.get(fund_name)
            if current_df is None or prior_df is None:
                continue

            current_tickers = set(current_df['ticker'].tolist()) if 'ticker' in current_df.columns else set()
            prior_tickers = set(prior_df['ticker'].tolist()) if 'ticker' in prior_df.columns else set()

            # New positions
            for ticker in current_tickers - prior_tickers:
                row = current_df[current_df['ticker'] == ticker].iloc[0] if len(current_df[current_df['ticker'] == ticker]) > 0 else None
                if row is not None:
                    new_positions.append({
                        'fund': fund_name,
                        'ticker': ticker,
                        'value': row.get('value', 0),
                    })

            # Exits
            for ticker in prior_tickers - current_tickers:
                exits.append({
                    'fund': fund_name,
                    'ticker': ticker,
                })

        for pos in sorted(new_positions, key=lambda x: x['value'], reverse=True)[:20]:
            prompt_parts.append(f"  - {pos['fund']}: {pos['ticker']} (${pos['value']:,.0f})")

        prompt_parts.extend([
            "",
            "### COMPLETE EXITS (had position last Q, now zero)",
        ])
        for pos in exits[:20]:
            prompt_parts.append(f"  - {pos['fund']}: {pos['ticker']} EXITED")

        prompt_parts.append("")

    # Add market context if provided
    if market_context:
        prompt_parts.extend([
            "",
            "## RECENT MARKET CONTEXT",
            market_context,
            "",
        ])

    prompt_parts.extend([
        "",
        "Analyze this 13F data using the institutional flow framework.",
        "FOCUS ON CHANGES: new positions, exits, and significant increases/decreases (>25%).",
        "Static positions are noise — changes are signal.",
        "Include the staleness warning in your cio_briefing.",
        "Respond with ONLY valid JSON matching the specified schema.",
    ])

    return "\n".join(prompt_parts)


# Import datetime at module level
from datetime import datetime
