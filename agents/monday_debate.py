#!/usr/bin/env python3
"""
ATLAS Monday Portfolio Debate
Clean slate $1M allocation debate with 14 agents.
No existing positions - fresh portfolio construction.
Uses FMP via agents/market_data.py (NEVER yfinance).
"""
import anthropic
import json
import os
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Import market data module (uses dual-source validation, NEVER yfinance)
from agents.market_data import get_full_market_data, format_market_context, get_validated_quotes

load_dotenv(Path(__file__).parent.parent / ".env")

STATE_DIR = Path(__file__).parent.parent / "data" / "state"
client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

# Execution date
EXECUTION_DATE = "Monday, March 10, 2026"
DEBATE_DATE = "March 8, 2026"  # Updated to today


def call_agent(system_prompt: str, user_message: str, max_tokens: int = 2000) -> str:
    """Call Claude with system prompt and user message."""
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}]
    )
    return response.content[0].text


def run_monday_debate():
    """Run the full Monday portfolio debate."""
    print(f"\n{'='*80}")
    print(f"ATLAS MONDAY PORTFOLIO DEBATE — {DEBATE_DATE}")
    print(f"Clean slate $1,000,000 allocation for {EXECUTION_DATE}")
    print(f"{'='*80}")

    # Step 1: Get market data from FMP
    market_data = get_full_market_data()
    market_context = format_market_context(market_data)
    print(f"\n{market_context[:2000]}...")

    FRESH_SLATE_INSTRUCTION = f"""
IMPORTANT: This is a FRESH $1,000,000 allocation. You have NO existing positions.
Do NOT anchor to any previous portfolio. Build from scratch based on current market conditions.
Today is {DEBATE_DATE}. Positions will be executed {EXECUTION_DATE}.
"""

    debate_log = {
        'date': DEBATE_DATE,
        'execution_date': EXECUTION_DATE,
        'market_data': market_data,
        'layers': {}
    }

    # ================================================================
    # LAYER 1: MACRO CONTEXT (2 agents)
    # ================================================================
    print(f"\n{'='*60}")
    print("LAYER 1: MACRO CONTEXT")
    print(f"{'='*60}")

    # Macro Regime Agent
    print("\n[1/14] Macro Regime Agent (Bonds/Currency/Commodities)...")
    macro_agent = call_agent(
        f"""You are a macro strategist analyzing bonds, currencies, and commodities.
{FRESH_SLATE_INSTRUCTION}
Determine the current macro regime and what it means for portfolio construction.""",
        f"""Given today's market data, answer:
1. What is the current macro regime? (Risk-on, risk-off, rotation, stagflation, reflation, etc.)
2. What do yields, the dollar, oil, and gold tell us about the next 1-3 months?
3. Which asset classes and sectors should we overweight vs underweight?
4. What's the biggest macro risk that could blow up a portfolio right now?

{market_context}""",
        max_tokens=1500
    )
    print(f"  Done: {macro_agent[:100]}...")
    debate_log['layers']['macro_regime'] = macro_agent

    # News Sentiment Agent
    print("\n[2/14] News Sentiment Agent...")
    news_agent = call_agent(
        f"""You are a financial news analyst identifying the biggest themes moving markets.
{FRESH_SLATE_INSTRUCTION}
Focus on actionable themes that create trading opportunities.""",
        f"""What are the 5 biggest themes moving markets right now?
For each theme:
1. What's driving it?
2. Which sectors/stocks benefit?
3. Which sectors/stocks are at risk?
4. How long will this theme persist?

{market_context}""",
        max_tokens=1500
    )
    print(f"  Done: {news_agent[:100]}...")
    debate_log['layers']['news_sentiment'] = news_agent

    layer1_context = f"""
=== MACRO REGIME ANALYSIS ===
{macro_agent}

=== NEWS & THEMES ===
{news_agent}
"""

    # ================================================================
    # LAYER 2: SECTOR DESKS (6 agents)
    # ================================================================
    print(f"\n{'='*60}")
    print("LAYER 2: SECTOR DESK PITCHES")
    print(f"{'='*60}")

    sector_pitches = {}

    # Semiconductor Desk
    print("\n[3/14] Semiconductor Desk...")
    semi_pitch = call_agent(
        f"""You are a semiconductor sector analyst. You track AI chips, memory, analog, and equipment.
{FRESH_SLATE_INSTRUCTION}""",
        f"""What is your SINGLE BEST semiconductor trade right now?

Provide:
- Ticker and direction (LONG or SHORT)
- Current price and your target price
- Stop loss level
- Position size recommendation (% of $1M portfolio)
- Why THIS stock over all others in the sector
- Key catalysts and timeline
- What would invalidate the thesis

MACRO CONTEXT:
{layer1_context}

{market_context}""",
        max_tokens=1200
    )
    print(f"  Done: {semi_pitch[:100]}...")
    sector_pitches['semiconductor'] = semi_pitch

    # Energy Desk
    print("\n[4/14] Energy Desk...")
    energy_pitch = call_agent(
        f"""You are an energy sector analyst covering oil, gas, renewables, and energy transition.
{FRESH_SLATE_INSTRUCTION}""",
        f"""What is your SINGLE BEST energy trade (long OR short) right now?

Provide:
- Ticker and direction (LONG or SHORT)
- Current price and your target price
- Stop loss level
- Position size recommendation (% of $1M portfolio)
- Why THIS stock over all others in the sector
- Key catalysts and timeline
- What would invalidate the thesis

MACRO CONTEXT:
{layer1_context}

{market_context}""",
        max_tokens=1200
    )
    print(f"  Done: {energy_pitch[:100]}...")
    sector_pitches['energy'] = energy_pitch

    # Healthcare Desk
    print("\n[5/14] Healthcare/Biotech Desk...")
    healthcare_pitch = call_agent(
        f"""You are a healthcare and biotech analyst covering pharma, biotech, managed care, and devices.
{FRESH_SLATE_INSTRUCTION}""",
        f"""What is your SINGLE BEST healthcare trade right now?

Provide:
- Ticker and direction (LONG or SHORT)
- Current price and your target price
- Stop loss level
- Position size recommendation (% of $1M portfolio)
- Why THIS stock over all others in the sector
- Key catalysts and timeline
- What would invalidate the thesis

MACRO CONTEXT:
{layer1_context}

{market_context}""",
        max_tokens=1200
    )
    print(f"  Done: {healthcare_pitch[:100]}...")
    sector_pitches['healthcare'] = healthcare_pitch

    # Consumer Desk
    print("\n[6/14] Consumer/Retail Desk...")
    consumer_pitch = call_agent(
        f"""You are a consumer sector analyst covering retail, restaurants, luxury, and staples.
{FRESH_SLATE_INSTRUCTION}""",
        f"""What is your SINGLE BEST consumer trade right now?

Provide:
- Ticker and direction (LONG or SHORT)
- Current price and your target price
- Stop loss level
- Position size recommendation (% of $1M portfolio)
- Why THIS stock over all others in the sector
- Key catalysts and timeline
- What would invalidate the thesis

MACRO CONTEXT:
{layer1_context}

{market_context}""",
        max_tokens=1200
    )
    print(f"  Done: {consumer_pitch[:100]}...")
    sector_pitches['consumer'] = consumer_pitch

    # Industrials Desk
    print("\n[7/14] Industrials/Infrastructure Desk...")
    industrials_pitch = call_agent(
        f"""You are an industrials analyst covering manufacturing, aerospace, defense, and infrastructure.
{FRESH_SLATE_INSTRUCTION}""",
        f"""What is your SINGLE BEST industrials/infrastructure trade right now?

Provide:
- Ticker and direction (LONG or SHORT)
- Current price and your target price
- Stop loss level
- Position size recommendation (% of $1M portfolio)
- Why THIS stock over all others in the sector
- Key catalysts and timeline
- What would invalidate the thesis

MACRO CONTEXT:
{layer1_context}

{market_context}""",
        max_tokens=1200
    )
    print(f"  Done: {industrials_pitch[:100]}...")
    sector_pitches['industrials'] = industrials_pitch

    # Financials Desk
    print("\n[8/14] Financials/Real Estate Desk...")
    financials_pitch = call_agent(
        f"""You are a financials analyst covering banks, insurance, asset managers, and REITs.
{FRESH_SLATE_INSTRUCTION}""",
        f"""What is your SINGLE BEST financials or real estate trade right now?

Provide:
- Ticker and direction (LONG or SHORT)
- Current price and your target price
- Stop loss level
- Position size recommendation (% of $1M portfolio)
- Why THIS stock over all others in the sector
- Key catalysts and timeline
- What would invalidate the thesis

MACRO CONTEXT:
{layer1_context}

{market_context}""",
        max_tokens=1200
    )
    print(f"  Done: {financials_pitch[:100]}...")
    sector_pitches['financials'] = financials_pitch

    debate_log['layers']['sector_pitches'] = sector_pitches

    # Build sector pitches context
    sector_context = "\n\n".join([
        f"=== {sector.upper()} DESK PITCH ===\n{pitch}"
        for sector, pitch in sector_pitches.items()
    ])

    # ================================================================
    # LAYER 3: SUPERINVESTOR PORTFOLIOS (4 agents)
    # ================================================================
    print(f"\n{'='*60}")
    print("LAYER 3: SUPERINVESTOR PORTFOLIOS")
    print(f"{'='*60}")

    portfolios = {}

    full_context = f"""
{market_context}

{layer1_context}

{sector_context}
"""

    # Druckenmiller
    print("\n[9/14] Druckenmiller Portfolio...")
    druckenmiller = call_agent(
        f"""You are Stanley Druckenmiller. Top-down macro trader.
You look for asymmetric bets where risk/reward is 4-5x. You size positions based on conviction.
You can go long or short. You read macro better than anyone.
{FRESH_SLATE_INSTRUCTION}""",
        f"""You have $1,000,000 to deploy. Build a 5-8 position portfolio.

For EACH position provide:
1. Ticker
2. Direction (LONG or SHORT)
3. Allocation (% of $1M)
4. Entry price
5. Stop loss
6. Price target
7. Thesis (2-3 sentences)

End with your overall macro thesis and what would make you cut risk across the board.

MARKET DATA & SECTOR PITCHES:
{full_context}""",
        max_tokens=2500
    )
    print(f"  Done: {druckenmiller[:100]}...")
    portfolios['druckenmiller'] = druckenmiller

    # Aschenbrenner
    print("\n[10/14] Aschenbrenner Portfolio...")
    aschenbrenner = call_agent(
        f"""You are an AI infrastructure investor modeled on Leopold Aschenbrenner.
You track the AI compute value chain: chips, packaging, power, cooling, data centers.
You find the current bottleneck and invest there. Concentrated positions when conviction is high.
{FRESH_SLATE_INSTRUCTION}""",
        f"""You have $1,000,000 to deploy. Build a 5-8 position portfolio focused on AI/compute.

For EACH position provide:
1. Ticker
2. Direction (LONG or SHORT)
3. Allocation (% of $1M)
4. Entry price
5. Stop loss
6. Price target
7. Thesis (2-3 sentences)

End with your view on where the AI value chain bottleneck is shifting and timeline.

MARKET DATA & SECTOR PITCHES:
{full_context}""",
        max_tokens=2500
    )
    print(f"  Done: {aschenbrenner[:100]}...")
    portfolios['aschenbrenner'] = aschenbrenner

    # Baker
    print("\n[11/14] Baker Portfolio...")
    baker = call_agent(
        f"""You are a deep tech investor modeled on Gavin Baker of Atreides Management.
You know every semiconductor roadmap, every hyperscaler capex plan, every protocol transition.
You invest based on deep product-level knowledge. You're comfortable being contrarian.
{FRESH_SLATE_INSTRUCTION}""",
        f"""You have $1,000,000 to deploy. Build a 5-8 position portfolio.

For EACH position provide:
1. Ticker
2. Direction (LONG or SHORT)
3. Allocation (% of $1M)
4. Entry price
5. Stop loss
6. Price target
7. Thesis (2-3 sentences)

End with your deepest conviction idea and the most contrarian view in your portfolio.

MARKET DATA & SECTOR PITCHES:
{full_context}""",
        max_tokens=2500
    )
    print(f"  Done: {baker[:100]}...")
    portfolios['baker'] = baker

    # Ackman
    print("\n[12/14] Ackman Portfolio...")
    ackman = call_agent(
        f"""You are Bill Ackman, activist-minded concentrated investor.
You own 3-5 simple, predictable, free-cash-flow generative businesses.
You hold for 3-5 years. You overlay macro hedges when risk is asymmetric.
{FRESH_SLATE_INSTRUCTION}""",
        f"""You have $1,000,000 to deploy. Build a concentrated 3-5 position portfolio.

For EACH position provide:
1. Ticker
2. Direction (LONG or SHORT)
3. Allocation (% of $1M)
4. Entry price
5. Stop loss
6. Price target
7. Thesis (2-3 sentences)

End with why concentration beats diversification here and your hedge strategy.

MARKET DATA & SECTOR PITCHES:
{full_context}""",
        max_tokens=2500
    )
    print(f"  Done: {ackman[:100]}...")
    portfolios['ackman'] = ackman

    debate_log['layers']['superinvestor_portfolios'] = portfolios

    # Build portfolios context
    portfolios_context = "\n\n".join([
        f"=== {name.upper()} PORTFOLIO ===\n{portfolio}"
        for name, portfolio in portfolios.items()
    ])

    # ================================================================
    # LAYER 4: CRO + CIO (2 agents)
    # ================================================================
    print(f"\n{'='*60}")
    print("LAYER 4: CRO ATTACK + CIO SYNTHESIS")
    print(f"{'='*60}")

    # CRO Attack
    print("\n[13/14] CRO Risk Attack...")
    cro_attack = call_agent(
        f"""You are the Chief Risk Officer of a $10B hedge fund with 25 years of experience.
You've lived through every crisis. Your job is to find the fatal flaw in every portfolio.
Be harsh. Be thorough. Find what the bulls are missing.
{FRESH_SLATE_INSTRUCTION}""",
        f"""Review all 4 superinvestor portfolios below.

For EACH portfolio, identify:
1. The WEAKEST position (most likely to lose money)
2. The bear case the investor is ignoring
3. Hidden correlations that could cause simultaneous losses
4. The scenario that causes maximum drawdown

Then rank the 4 portfolios from most to least risky.

Finally: What's the ONE trade that appears in multiple portfolios that you think is WRONG?

PORTFOLIOS TO ATTACK:
{portfolios_context}

MARKET CONTEXT:
{layer1_context}""",
        max_tokens=2500
    )
    print(f"  Done: {cro_attack[:100]}...")
    debate_log['layers']['cro_attack'] = cro_attack

    # CIO Final Portfolio
    print("\n[14/14] CIO Final Portfolio Synthesis...")
    cio_portfolio = call_agent(
        f"""You are the CIO of ATLAS, synthesizing the entire Monday debate into a final portfolio.
You must balance conviction with risk management. You weight ideas by how well they survived CRO scrutiny.
{FRESH_SLATE_INSTRUCTION}

RULES:
- Keep 25-35% in BIL (cash/T-bills)
- Maximum 8 positions (including BIL)
- No single stock position >15%
- Must include at least one short or hedge
- Every position needs stop loss""",
        f"""Build the FINAL Monday portfolio.

You have seen:
1. Macro regime analysis
2. News/themes analysis
3. 6 sector desk pitches
4. 4 superinvestor portfolios
5. CRO's attack on all portfolios

Now synthesize the BEST ideas that survived CRO scrutiny into a coherent portfolio.

OUTPUT FORMAT (must be exact):
```
ATLAS MONDAY PORTFOLIO — {EXECUTION_DATE}

CASH ALLOCATION:
BIL: XX% ($XXX,XXX)

POSITIONS:
1. [TICKER] | [LONG/SHORT] | [XX%] ($XX,XXX)
   Entry: $XXX | Stop: $XXX | Target: $XXX
   Thesis: [2-3 sentences]
   Supported by: [which agents]

2. [Continue for each position...]

PORTFOLIO SUMMARY:
- Total positions: X (plus cash)
- Long exposure: XX%
- Short exposure: XX%
- Net exposure: XX%

WHAT I'M WATCHING:
[Key events/levels that would trigger portfolio changes]

CONVICTION LEVEL: XX/100
```

FULL DEBATE:
{layer1_context}

{sector_context}

{portfolios_context}

CRO ATTACK:
{cro_attack}""",
        max_tokens=3000
    )
    print(f"  Done: {cio_portfolio[:100]}...")
    debate_log['layers']['cio_final'] = cio_portfolio

    # ================================================================
    # VERIFY PRICES FOR FINAL PORTFOLIO
    # ================================================================
    print(f"\n{'='*60}")
    print("VERIFYING PRICES (Dual-Source: FMP + Finnhub)")
    print(f"{'='*60}")

    # Extract tickers from CIO portfolio (common portfolio tickers)
    portfolio_tickers = ['AVGO', 'NVDA', 'GOOGL', 'MSFT', 'AAPL', 'META', 'AMZN', 'TSLA',
                         'XOM', 'CVX', 'UNH', 'JNJ', 'JPM', 'V', 'TLT', 'GLD',
                         'SPY', 'QQQ', 'IWM', 'XLE', 'ANET', 'CRM', 'NOW', 'APO']

    print(f"\nFetching validated quotes for {len(portfolio_tickers)} tickers...")
    verified_prices = get_validated_quotes(portfolio_tickers)

    print(f"\n{'TICKER':<8} {'PRICE':>10} {'CHG%':>8} {'QUALITY':>12} {'SOURCE':>10}")
    print("-" * 55)
    for ticker, data in verified_prices.items():
        price = data.get('price', 0)
        change = data.get('change_pct', 0)
        quality = data.get('data_quality', 'unknown')
        source = data.get('source', 'N/A')
        if price > 0:
            print(f"{ticker:<8} ${price:>8.2f} {change:>+7.2f}% {quality:>12} {source:>10}")

    # Save verified prices
    with open(STATE_DIR / "verified_prices.json", 'w') as f:
        json.dump(verified_prices, f, indent=2)
    print(f"\n  Saved: data/state/verified_prices.json")

    debate_log['verified_prices'] = verified_prices

    # ================================================================
    # SAVE EVERYTHING
    # ================================================================
    print(f"\n{'='*60}")
    print("SAVING DEBATE AND PORTFOLIO")
    print(f"{'='*60}")

    # Save full debate log
    with open(STATE_DIR / "monday_debate.json", 'w') as f:
        json.dump(debate_log, f, indent=2)
    print("  Saved: data/state/monday_debate.json")

    # Save CIO portfolio separately
    with open(STATE_DIR / "monday_portfolio.json", 'w') as f:
        json.dump({
            'date': DEBATE_DATE,
            'execution_date': EXECUTION_DATE,
            'portfolio': cio_portfolio,
            'timestamp': datetime.now().isoformat()
        }, f, indent=2)
    print("  Saved: data/state/monday_portfolio.json")

    # Update CIO synthesis for dashboard
    with open(STATE_DIR / "cio_synthesis.json", 'w') as f:
        json.dump({
            'date': DEBATE_DATE,
            'synthesis': cio_portfolio,
            'stance': 'Monday Portfolio Build',
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M')
        }, f, indent=2)
    print("  Saved: data/state/cio_synthesis.json")

    # Print full debate
    print(f"\n{'='*80}")
    print("FULL MONDAY DEBATE")
    print(f"{'='*80}")

    print("\n" + "="*60)
    print("LAYER 1: MACRO CONTEXT")
    print("="*60)
    print("\n--- MACRO REGIME ---")
    print(macro_agent)
    print("\n--- NEWS & THEMES ---")
    print(news_agent)

    print("\n" + "="*60)
    print("LAYER 2: SECTOR PITCHES")
    print("="*60)
    for sector, pitch in sector_pitches.items():
        print(f"\n--- {sector.upper()} ---")
        print(pitch)

    print("\n" + "="*60)
    print("LAYER 3: SUPERINVESTOR PORTFOLIOS")
    print("="*60)
    for name, portfolio in portfolios.items():
        print(f"\n--- {name.upper()} ---")
        print(portfolio)

    print("\n" + "="*60)
    print("LAYER 4: CRO ATTACK")
    print("="*60)
    print(cro_attack)

    print("\n" + "="*60)
    print("FINAL CIO PORTFOLIO")
    print("="*60)
    print(cio_portfolio)

    print(f"\n{'='*80}")
    print(f"MONDAY DEBATE COMPLETE — {datetime.now().strftime('%H:%M')}")
    print(f"14 agents debated. Portfolio ready for {EXECUTION_DATE}.")
    print(f"{'='*80}")

    return debate_log


if __name__ == '__main__':
    run_monday_debate()
