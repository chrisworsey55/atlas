#!/usr/bin/env python3
"""
ATLAS End-of-Day Mega Cycle
Runs all 20 agents with live closing data. Full debate. Briefing. Email.
"""
import anthropic
import json
import os
import yfinance as yf
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

STATE_DIR = Path(__file__).parent.parent / "data" / "state"
client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))


def call_agent(system_prompt, user_message, max_tokens=1000):
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}]
    )
    return response.content[0].text


def update_prices():
    """Fetch closing prices for all positions"""
    print("Updating closing prices...")
    with open(STATE_DIR / "positions.json") as f:
        data = json.load(f)

    positions = data.get("positions", [])
    tickers = [p["ticker"] for p in positions if p["ticker"] != 'BIL']

    if not tickers:
        return positions

    price_data = yf.download(tickers, period='1d', progress=False)

    for pos in positions:
        t = pos["ticker"]
        if t == 'BIL':
            continue
        try:
            if len(tickers) == 1:
                price = float(price_data['Close'].iloc[-1])
            else:
                price = float(price_data['Close'][t].iloc[-1])
            pos['current_price'] = round(price, 2)
        except Exception:
            pass

    # Save updated positions
    data["positions"] = positions
    data["last_updated"] = datetime.now().strftime('%Y-%m-%d %H:%M')
    with open(STATE_DIR / "positions.json", 'w') as f:
        json.dump(data, f, indent=2)

    return positions


def calculate_pnl(positions):
    """Calculate P&L for all positions"""
    total_pnl = 0
    position_pnl = {}
    for p in positions:
        t = p["ticker"]
        entry = p.get('entry_price', 0)
        current = p.get('current_price', entry)
        shares = p.get('shares', 0)
        direction = p.get('direction', 'LONG')

        if direction == 'SHORT':
            pnl = (entry - current) * shares
        else:
            pnl = (current - entry) * shares

        pnl_pct = (pnl / (entry * shares) * 100) if entry * shares > 0 else 0
        position_pnl[t] = {'pnl': round(pnl, 2), 'pnl_pct': round(pnl_pct, 2), 'current': current}
        total_pnl += pnl

    return total_pnl, position_pnl


def build_market_context(positions, total_pnl, position_pnl):
    """Build the market context string all agents will receive"""
    today = datetime.now().strftime('%Y-%m-%d')

    portfolio_lines = []
    for p in positions:
        t = p["ticker"]
        pp = position_pnl.get(t, {})
        portfolio_lines.append(
            f"  {t}: {p.get('direction','LONG')} {p.get('shares',0)} shares @ ${p.get('entry_price',0)} "
            f"-> ${p.get('current_price',0)} | P&L: ${pp.get('pnl',0):,.2f} ({pp.get('pnl_pct',0):.2f}%) | "
            f"Agent: {p.get('agent_source','unknown')} | Thesis: {p.get('thesis','')[:80]}"
        )

    context = f"""
TODAY: {today} — US market just closed.
PORTFOLIO VALUE: $1,000,000 base | Total P&L: ${total_pnl:,.2f} ({total_pnl/10000:.2f}%)

CURRENT POSITIONS:
{chr(10).join(portfolio_lines)}

Provide your analysis based on TODAY's closing data. Be specific about what changed today, what it means for our positions, and what action you recommend for tomorrow.
"""
    return context


def run_eod_cycle():
    print(f"\n{'='*80}")
    print(f"ATLAS END-OF-DAY MEGA CYCLE — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*80}")

    # Step 1: Update prices
    positions = update_prices()
    total_pnl, position_pnl = calculate_pnl(positions)
    context = build_market_context(positions, total_pnl, position_pnl)

    print(f"\nPortfolio P&L: ${total_pnl:,.2f}")
    for t, pp in position_pnl.items():
        if t != 'BIL':
            print(f"  {t}: ${pp['pnl']:,.2f} ({pp['pnl_pct']:.2f}%)")

    # Step 2: Save P&L snapshot
    history = []
    history_file = STATE_DIR / "pnl_history.json"
    if history_file.exists():
        with open(history_file) as f:
            history = json.load(f)
    history.append({
        'date': datetime.now().strftime('%Y-%m-%d'),
        'total_pnl': round(total_pnl, 2),
        'positions': position_pnl
    })
    with open(history_file, 'w') as f:
        json.dump(history, f, indent=2)

    all_views = {}

    # ================================================================
    # LAYER 1: DATA AGENTS — Scan for raw information
    # ================================================================
    print(f"\n{'='*60}")
    print("LAYER 1: DATA AGENTS")
    print(f"{'='*60}")

    # News Agent
    print("\n[1/20] News Sentiment Agent...")
    all_views['news'] = call_agent(
        "You are a financial news analyst. Scan today's major market events, geopolitical developments, economic data releases, and sector-moving headlines. Score each by urgency: IMMEDIATE, TODAY, THIS_WEEK, BACKGROUND. Focus on events that affect our portfolio positions.",
        f"What were the most important market events today? How do they affect our portfolio?\n\n{context}"
    )
    print(f"  Done: {all_views['news'][:100]}...")

    # Institutional Flow Agent
    print("\n[2/20] Institutional Flow Agent...")
    all_views['flow'] = call_agent(
        "You are an institutional flow analyst. You track 13F filings, dark pool activity, options flow, and unusual volume. Identify where smart money is moving and what it means for our positions.",
        f"What institutional flow signals are relevant to our portfolio today?\n\n{context}"
    )
    print(f"  Done: {all_views['flow'][:100]}...")

    # ================================================================
    # LAYER 2: SECTOR DESKS — Analyse each market segment
    # ================================================================
    print(f"\n{'='*60}")
    print("LAYER 2: SECTOR DESKS")
    print(f"{'='*60}")

    # Bond Desk
    print("\n[3/20] Bond Desk...")
    all_views['bond'] = call_agent(
        "You are a fixed income analyst covering rates, credit spreads, yield curve, and Fed policy. Provide your signal: BULLISH_DURATION, BEARISH_DURATION, or NEUTRAL with confidence percentage. Explain what changed today.",
        f"What happened in rates and credit today? Signal and confidence for our TLT short.\n\n{context}"
    )
    print(f"  Done: {all_views['bond'][:100]}...")

    # Currency Desk
    print("\n[4/20] Currency Desk...")
    all_views['currency'] = call_agent(
        "You are an FX analyst covering G10 and EM currencies. Track dollar strength, rate differentials, and capital flows. Provide your signal: BULLISH_USD, BEARISH_USD, or NEUTRAL with confidence.",
        f"What happened in FX markets today? How does dollar direction affect our portfolio?\n\n{context}"
    )
    print(f"  Done: {all_views['currency'][:100]}...")

    # Commodities Desk
    print("\n[5/20] Commodities Desk...")
    all_views['commodities'] = call_agent(
        "You are a commodities analyst covering energy, agriculture, and soft commodities. Track oil, natural gas, and supply chain signals. Provide your signal with confidence.",
        f"What happened in commodities today? Focus on oil and energy given Iran conflict and any energy positions we hold.\n\n{context}"
    )
    print(f"  Done: {all_views['commodities'][:100]}...")

    # Metals Desk
    print("\n[6/20] Metals Desk...")
    all_views['metals'] = call_agent(
        "You are a precious and industrial metals analyst. Track gold, silver, copper using real rates, dollar correlation, and safe haven flows. Provide your signal with confidence.",
        f"What happened in metals today? Gold as a hedge for our portfolio?\n\n{context}"
    )
    print(f"  Done: {all_views['metals'][:100]}...")

    # Semiconductor Desk
    print("\n[7/20] Semiconductor Desk...")
    all_views['semiconductor'] = call_agent(
        "You are a semiconductor analyst. You track chip cycles, AI demand, inventory levels, TSMC utilisation, packaging capacity, and hyperscaler capex. Cover AVGO, NVDA, AMD, INTC, and the broader semi supply chain.",
        f"What happened in semiconductors today? Specifically how does it affect AVGO?\n\n{context}"
    )
    print(f"  Done: {all_views['semiconductor'][:100]}...")

    # Biotech Desk
    print("\n[8/20] Biotech Desk...")
    all_views['biotech'] = call_agent(
        "You are a biotech and healthcare analyst. Track FDA catalysts, pipeline readouts, M&A, and drug pricing policy. Cover any healthcare positions in the portfolio.",
        f"What happened in healthcare/biotech today? Any impact on portfolio healthcare positions?\n\n{context}"
    )
    print(f"  Done: {all_views['biotech'][:100]}...")

    # Energy Desk
    print("\n[9/20] Energy Desk...")
    all_views['energy'] = call_agent(
        "You are an energy sector analyst. Cover oil majors, refiners, E&Ps, renewables, and the energy transition. Track geopolitical supply risks, OPEC decisions, and US production data.",
        f"What happened in energy stocks today? Focus on any energy positions we hold and the Iran/oil dynamic.\n\n{context}"
    )
    print(f"  Done: {all_views['energy'][:100]}...")

    # Consumer Desk
    print("\n[10/20] Consumer Desk...")
    all_views['consumer'] = call_agent(
        "You are a consumer sector analyst covering retail, restaurants, luxury, and consumer staples. Track consumer spending, sentiment, credit card data, and employment trends.",
        f"What happened in the consumer sector today? Any signals from consumer data that affect our macro view?\n\n{context}"
    )
    print(f"  Done: {all_views['consumer'][:100]}...")

    # Industrials Desk
    print("\n[11/20] Industrials Desk...")
    all_views['industrials'] = call_agent(
        "You are an industrials analyst covering manufacturing, aerospace, defence, transportation, and infrastructure. Track PMI data, order books, capex cycles, and government spending.",
        f"What happened in industrials today? Any signals for the broader economy?\n\n{context}"
    )
    print(f"  Done: {all_views['industrials'][:100]}...")

    # Microcap Discovery Desk
    print("\n[12/20] Microcap Discovery Desk...")
    all_views['microcap'] = call_agent(
        "You are a microcap analyst. You find undiscovered companies under $2B market cap with asymmetric upside. Look for insider buying clusters, 13F accumulation by smart money, and companies where the fundamental screen shows massive undervaluation that larger funds can't own due to size constraints.",
        f"Any microcap discoveries worth investigating? Cross-reference with our fundamental screen results.\n\n{context}"
    )
    print(f"  Done: {all_views['microcap'][:100]}...")

    # ================================================================
    # LAYER 3: SUPERINVESTOR AGENTS — Strategic views
    # ================================================================
    print(f"\n{'='*60}")
    print("LAYER 3: SUPERINVESTOR AGENTS")
    print(f"{'='*60}")

    # Druckenmiller
    print("\n[13/20] Druckenmiller Macro Agent...")
    all_views['druckenmiller'] = call_agent(
        "You are Stanley Druckenmiller. Top-down macro trader. You look for asymmetric bets where the risk/reward is 4-5x. You keep powder dry for fat pitches. You read the macro tea leaves better than anyone. Give your view on the portfolio and what to do tomorrow. Be specific — ticker, direction, size.",
        context, max_tokens=1500
    )
    print(f"  Done: {all_views['druckenmiller'][:100]}...")

    # Aschenbrenner
    print("\n[14/20] Aschenbrenner AI Infra Agent...")
    all_views['aschenbrenner'] = call_agent(
        "You are an AI infrastructure investor modelled on Leopold Aschenbrenner. You track the AI compute value chain: chips -> packaging -> power -> cooling -> data centres. You find the current bottleneck and invest there. Concentrated positions when conviction is high. Give your view on portfolio AI positions and any new ideas.",
        context, max_tokens=1500
    )
    print(f"  Done: {all_views['aschenbrenner'][:100]}...")

    # Baker
    print("\n[15/20] Baker Deep Tech Agent...")
    all_views['baker'] = call_agent(
        "You are a deep tech investor modelled on Gavin Baker of Atreides Management. You know every semiconductor roadmap, every hyperscaler capex plan, every networking protocol transition. You invest based on deep product-level knowledge. Give your view on our tech positions and any new opportunities.",
        context, max_tokens=1500
    )
    print(f"  Done: {all_views['baker'][:100]}...")

    # Ackman
    print("\n[16/20] Ackman Quality Compounder Agent...")
    all_views['ackman'] = call_agent(
        "You are a quality compounder investor modelled on Bill Ackman. You own 8-12 simple, predictable, free-cash-flow-generative businesses for 3-5 years. You overlay macro hedges when risk is asymmetric. Give your view on portfolio quality and any defensive adjustments needed.",
        context, max_tokens=1500
    )
    print(f"  Done: {all_views['ackman'][:100]}...")

    # ================================================================
    # LAYER 4: RISK AND DECISION
    # ================================================================
    print(f"\n{'='*60}")
    print("LAYER 4: RISK AND DECISION")
    print(f"{'='*60}")

    # Compile all views for the risk and decision agents
    all_views_summary = "\n\n".join([f"=== {name.upper()} ===\n{view[:500]}" for name, view in all_views.items()])

    # Adversarial / CRO
    print("\n[17/20] CRO / Adversarial Agent...")
    all_views['cro'] = call_agent(
        "You are the Chief Risk Officer of a $10 billion multi-strategy hedge fund with 25 years of experience. You lived through the dot-com crash, the GFC, COVID, and the 2022 drawdown. Review the full agent debate below. For each position in the portfolio, identify the biggest risk that the bulls are ignoring. Find hidden correlations between positions. Identify the scenario that kills multiple positions simultaneously. Rank positions from least to most risky. Give a clear verdict on the overall portfolio: HOLD / REDUCE RISK / ADD RISK.",
        f"FULL AGENT DEBATE:\n{all_views_summary}\n\nPORTFOLIO:\n{context}", max_tokens=2000
    )
    print(f"  Done: {all_views['cro'][:100]}...")

    # Alpha Discovery Agent
    print("\n[18/20] Alpha Discovery Agent...")
    all_views['alpha'] = call_agent(
        "You are an alpha discovery agent. Your job is to find non-obvious patterns by reading across all 16 agent views simultaneously. Look for: cross-agent signal convergence (3+ agents flagging the same thing independently), contradictions between agents that reveal hidden information, and regime change signals where agent patterns shift from recent history. What is the one insight that emerges from the full debate that no single agent would see alone?",
        f"FULL AGENT DEBATE:\n{all_views_summary}\n\n{context}", max_tokens=1500
    )
    print(f"  Done: {all_views['alpha'][:100]}...")

    # Autonomous Execution Agent
    print("\n[19/20] Autonomous Execution Agent...")
    all_views['autonomous'] = call_agent(
        "You are the autonomous execution agent. Based on the full agent debate, CRO review, and CIO synthesis, determine if any trades should be executed automatically. Rules: only execute if CIO confidence > 80%, adversarial risk < 0.6, and at least 3 agents agree on the trade. If no trades meet the bar, say HOLD. If a trade qualifies, specify: ticker, direction, shares, price, stop loss, target.",
        f"FULL DEBATE:\n{all_views_summary}\n\nCRO:\n{all_views.get('cro', '')}\n\n{context}", max_tokens=1000
    )
    print(f"  Done: {all_views['autonomous'][:100]}...")

    # CIO Final Synthesis
    print("\n[20/20] CIO Synthesis Agent...")
    all_views['cio'] = call_agent(
        """You are the CIO of ATLAS, a $1M AI-native hedge fund. You have just received analysis from all 20 agents. Synthesise everything into a clear, actionable brief.

Your output MUST include:
1. EXECUTIVE SUMMARY — one paragraph on today's market and portfolio
2. WHAT CHANGED TODAY — bullet points on material developments
3. AGENT DISAGREEMENTS — where agents disagree and who you side with
4. RECOMMENDED ACTIONS — specific trades for tomorrow (or HOLD if no action needed). For each trade: ticker, direction, size, stop loss, target, and which agents support it
5. WHAT TO WATCH TOMORROW — key events and levels
6. RISK ASSESSMENT — max drawdown scenario and probability
7. CONVICTION LEVEL — 0-100% overall portfolio confidence""",
        f"FULL 20-AGENT DEBATE:\n{all_views_summary}\n\nCRO REVIEW:\n{all_views.get('cro', '')}\n\nALPHA DISCOVERY:\n{all_views.get('alpha', '')}\n\n{context}", max_tokens=2500
    )
    print(f"  Done: {all_views['cio'][:100]}...")

    # ================================================================
    # SAVE AND SEND
    # ================================================================
    print(f"\n{'='*60}")
    print("SAVING AND SENDING")
    print(f"{'='*60}")

    # Save all views
    with open(STATE_DIR / "eod_agent_views.json", 'w') as f:
        json.dump({
            'date': datetime.now().strftime('%Y-%m-%d'),
            'timestamp': datetime.now().isoformat(),
            'total_pnl': round(total_pnl, 2),
            'position_pnl': position_pnl,
            'views': all_views
        }, f, indent=2)

    # Save CIO synthesis separately for dashboard
    with open(STATE_DIR / "cio_synthesis.json", 'w') as f:
        json.dump({
            'date': datetime.now().strftime('%Y-%m-%d'),
            'synthesis': all_views.get('cio', ''),
            'stance': 'See synthesis',
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M')
        }, f, indent=2)

    # Save desk briefs for dashboard
    desk_briefs = {}
    for desk in ['bond', 'currency', 'commodities', 'metals', 'semiconductor', 'biotech', 'energy', 'consumer', 'industrials']:
        desk_briefs[desk] = {
            'view': all_views.get(desk, ''),
            'updated': datetime.now().strftime('%Y-%m-%d %H:%M')
        }
    with open(STATE_DIR / "desk_briefs.json", 'w') as f:
        json.dump(desk_briefs, f, indent=2)

    # Generate and send briefing email
    print("\nGenerating briefing email...")
    try:
        from agents.email_alerts import send_email

        # Build the email HTML
        html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 700px; margin: 0 auto;">
            <div style="background: #0a0a1a; padding: 30px; border-radius: 12px;">
                <h1 style="color: #00d4aa; margin-top: 0;">ATLAS Daily Briefing</h1>
                <p style="color: #888;">{datetime.now().strftime('%A, %B %d, %Y')} — Market Close</p>

                <div style="background: #1a1a2e; padding: 20px; border-radius: 8px; margin: 20px 0;">
                    <h3 style="color: #00d4aa; margin-top: 0;">Portfolio Snapshot</h3>
                    <p style="font-size: 28px; margin: 5px 0; color: {'#00ff88' if total_pnl >= 0 else '#ff4444'};">
                        ${total_pnl:,.2f} ({total_pnl/10000:.2f}%)
                    </p>
                </div>

                <div style="background: #1a1a2e; padding: 20px; border-radius: 8px; margin: 20px 0;">
                    <h3 style="color: #00d4aa; margin-top: 0;">Position P&L</h3>
                    {''.join([f'<p style="color: {"#00ff88" if pp["pnl"] >= 0 else "#ff4444"};">{t}: ${pp["pnl"]:,.2f} ({pp["pnl_pct"]:.2f}%)</p>' for t, pp in position_pnl.items() if t != 'BIL'])}
                </div>

                <div style="background: #1a1a2e; padding: 20px; border-radius: 8px; margin: 20px 0;">
                    <h3 style="color: #00d4aa; margin-top: 0;">CIO Synthesis</h3>
                    <div style="color: #ccc; white-space: pre-wrap;">{all_views.get('cio', 'No synthesis available')}</div>
                </div>

                <div style="background: #1a1a2e; padding: 20px; border-radius: 8px; margin: 20px 0;">
                    <h3 style="color: #ff6b6b; margin-top: 0;">CRO Risk Review</h3>
                    <div style="color: #ccc; white-space: pre-wrap;">{all_views.get('cro', 'No review available')[:1000]}</div>
                </div>

                <div style="background: #1a1a2e; padding: 20px; border-radius: 8px; margin: 20px 0;">
                    <h3 style="color: #ffd700; margin-top: 0;">Alpha Discovery</h3>
                    <div style="color: #ccc; white-space: pre-wrap;">{all_views.get('alpha', 'No insights')[:500]}</div>
                </div>

                <div style="background: #1a1a2e; padding: 20px; border-radius: 8px; margin: 20px 0;">
                    <h3 style="color: #00d4aa; margin-top: 0;">Superinvestor Views</h3>
                    <p><strong style="color: #4ecdc4;">Druckenmiller:</strong> <span style="color: #ccc;">{all_views.get('druckenmiller', '')[:300]}...</span></p>
                    <p><strong style="color: #4ecdc4;">Aschenbrenner:</strong> <span style="color: #ccc;">{all_views.get('aschenbrenner', '')[:300]}...</span></p>
                    <p><strong style="color: #4ecdc4;">Baker:</strong> <span style="color: #ccc;">{all_views.get('baker', '')[:300]}...</span></p>
                    <p><strong style="color: #4ecdc4;">Ackman:</strong> <span style="color: #ccc;">{all_views.get('ackman', '')[:300]}...</span></p>
                </div>

                <div style="background: #1a1a2e; padding: 20px; border-radius: 8px; margin: 20px 0;">
                    <h3 style="color: #00d4aa; margin-top: 0;">Sector Desk Signals</h3>
                    {''.join([f'<p><strong style="color: #4ecdc4;">{desk.title()}:</strong> <span style="color: #ccc;">{all_views.get(desk, "")[:150]}...</span></p>' for desk in ['bond', 'currency', 'commodities', 'metals', 'semiconductor', 'energy']])}
                </div>

                <p style="color: #888; text-align: center; margin-top: 30px;">
                    <a href="https://meetvalis.com/atlas" style="color: #00d4aa;">Open Dashboard</a> |
                    20 agents analysed | API cost: ~$5
                </p>
            </div>
        </div>
        """

        send_email(
            f"ATLAS Briefing — {datetime.now().strftime('%b %d')} | P&L: ${total_pnl:+,.0f}",
            html
        )
        print("Briefing email sent!")
    except Exception as e:
        print(f"Email failed: {e}")

    # Ensure briefings directory exists
    briefings_dir = STATE_DIR / "briefings"
    briefings_dir.mkdir(parents=True, exist_ok=True)

    # Save briefing to file for dashboard
    with open(briefings_dir / f"{datetime.now().strftime('%Y-%m-%d')}.json", 'w') as f:
        json.dump({
            'date': datetime.now().strftime('%Y-%m-%d'),
            'total_pnl': round(total_pnl, 2),
            'position_pnl': position_pnl,
            'views': {k: v[:500] for k, v in all_views.items()},
            'full_cio': all_views.get('cio', ''),
            'full_cro': all_views.get('cro', '')
        }, f, indent=2)

    print(f"\n{'='*80}")
    print(f"ATLAS EOD MEGA CYCLE COMPLETE — {datetime.now().strftime('%H:%M')}")
    print(f"20 agents ran. Debate complete. Briefing sent.")
    print(f"All data saved to data/state/")
    print(f"{'='*80}")

    return all_views


if __name__ == '__main__':
    # Ensure briefings directory exists
    (STATE_DIR / "briefings").mkdir(parents=True, exist_ok=True)
    run_eod_cycle()
