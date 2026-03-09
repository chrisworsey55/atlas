#!/usr/bin/env python3
"""
ATLAS End-of-Day Mega Cycle
Runs all 20 agents with live closing data. Full debate. Briefing. Email.
"""
import anthropic
import json
import os
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

STATE_DIR = Path(__file__).parent.parent / "data" / "state"
PROMPTS_DIR = Path(__file__).parent / "prompts"
client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))


def load_prompt(agent_name: str) -> str:
    """Load an agent's system prompt from its .md file."""
    # Try various filename patterns
    patterns = [
        f"{agent_name}.md",
        f"{agent_name}_desk.md",
        f"{agent_name}_agent.md",
    ]

    for pattern in patterns:
        path = PROMPTS_DIR / pattern
        if path.exists():
            with open(path, 'r') as f:
                return f.read()

    # Fallback: return a basic prompt
    return f"You are the {agent_name} agent. Provide your analysis based on the data provided."


def load_agent_weights() -> dict:
    """Load agent weights from JSON file."""
    weights_file = STATE_DIR / "agent_weights.json"
    if weights_file.exists():
        with open(weights_file, 'r') as f:
            return json.load(f)
    # Default weights (all agents start at 1.0)
    return {}


def call_agent(system_prompt, user_message, max_tokens=1000):
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}]
    )
    return response.content[0].text


def update_prices():
    """Fetch closing prices for all positions using validated quotes"""
    print("Updating closing prices...")
    from agents.market_data import get_validated_quote

    with open(STATE_DIR / "positions.json") as f:
        data = json.load(f)

    positions = data.get("positions", [])

    for pos in positions:
        t = pos["ticker"]
        if t == 'BIL':
            continue
        try:
            quote = get_validated_quote(t)
            if quote and quote.get("price"):
                pos['current_price'] = round(quote["price"], 2)
        except Exception as e:
            print(f"  Warning: Could not fetch price for {t}: {e}")

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
        entry = p.get('entry_price') or 0
        current = p.get('current_price') or entry or 0
        shares = p.get('shares') or 0
        direction = p.get('direction', 'LONG')

        # Skip if we don't have valid prices
        if not entry or not current:
            position_pnl[t] = {'pnl': 0, 'pnl_pct': 0, 'current': current}
            continue

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
        load_prompt("news_sentiment"),
        f"What were the most important market events today? How do they affect our portfolio?\n\n{context}"
    )
    print(f"  Done: {all_views['news'][:100]}...")

    # Institutional Flow Agent
    print("\n[2/20] Institutional Flow Agent...")
    all_views['flow'] = call_agent(
        load_prompt("institutional_flow"),
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
        load_prompt("bond"),
        f"What happened in rates and credit today? Signal and confidence for our TLT short.\n\n{context}"
    )
    print(f"  Done: {all_views['bond'][:100]}...")

    # Currency Desk
    print("\n[4/20] Currency Desk...")
    all_views['currency'] = call_agent(
        load_prompt("currency"),
        f"What happened in FX markets today? How does dollar direction affect our portfolio?\n\n{context}"
    )
    print(f"  Done: {all_views['currency'][:100]}...")

    # Commodities Desk
    print("\n[5/20] Commodities Desk...")
    all_views['commodities'] = call_agent(
        load_prompt("commodities"),
        f"What happened in commodities today? Focus on oil and energy given Iran conflict and any energy positions we hold.\n\n{context}"
    )
    print(f"  Done: {all_views['commodities'][:100]}...")

    # Metals Desk
    print("\n[6/20] Metals Desk...")
    all_views['metals'] = call_agent(
        load_prompt("metals"),
        f"What happened in metals today? Gold as a hedge for our portfolio?\n\n{context}"
    )
    print(f"  Done: {all_views['metals'][:100]}...")

    # Semiconductor Desk
    print("\n[7/20] Semiconductor Desk...")
    all_views['semiconductor'] = call_agent(
        load_prompt("semiconductor"),
        f"What happened in semiconductors today? Specifically how does it affect AVGO?\n\n{context}"
    )
    print(f"  Done: {all_views['semiconductor'][:100]}...")

    # Biotech Desk
    print("\n[8/20] Biotech Desk...")
    all_views['biotech'] = call_agent(
        load_prompt("biotech"),
        f"What happened in healthcare/biotech today? Any impact on portfolio healthcare positions?\n\n{context}"
    )
    print(f"  Done: {all_views['biotech'][:100]}...")

    # Energy Desk
    print("\n[9/20] Energy Desk...")
    all_views['energy'] = call_agent(
        load_prompt("energy"),
        f"What happened in energy stocks today? Focus on any energy positions we hold and the Iran/oil dynamic.\n\n{context}"
    )
    print(f"  Done: {all_views['energy'][:100]}...")

    # Consumer Desk
    print("\n[10/20] Consumer Desk...")
    all_views['consumer'] = call_agent(
        load_prompt("consumer"),
        f"What happened in the consumer sector today? Any signals from consumer data that affect our macro view?\n\n{context}"
    )
    print(f"  Done: {all_views['consumer'][:100]}...")

    # Industrials Desk
    print("\n[11/20] Industrials Desk...")
    all_views['industrials'] = call_agent(
        load_prompt("industrials"),
        f"What happened in industrials today? Any signals for the broader economy?\n\n{context}"
    )
    print(f"  Done: {all_views['industrials'][:100]}...")

    # Microcap Discovery Desk
    print("\n[12/20] Microcap Discovery Desk...")
    all_views['microcap'] = call_agent(
        load_prompt("microcap"),
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
        load_prompt("druckenmiller"),
        context, max_tokens=1500
    )
    print(f"  Done: {all_views['druckenmiller'][:100]}...")

    # Aschenbrenner
    print("\n[14/20] Aschenbrenner AI Infra Agent...")
    all_views['aschenbrenner'] = call_agent(
        load_prompt("aschenbrenner"),
        context, max_tokens=1500
    )
    print(f"  Done: {all_views['aschenbrenner'][:100]}...")

    # Baker
    print("\n[15/20] Baker Deep Tech Agent...")
    all_views['baker'] = call_agent(
        load_prompt("baker"),
        context, max_tokens=1500
    )
    print(f"  Done: {all_views['baker'][:100]}...")

    # Ackman
    print("\n[16/20] Ackman Quality Compounder Agent...")
    all_views['ackman'] = call_agent(
        load_prompt("ackman"),
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
        load_prompt("cro"),
        f"FULL AGENT DEBATE:\n{all_views_summary}\n\nPORTFOLIO:\n{context}", max_tokens=2000
    )
    print(f"  Done: {all_views['cro'][:100]}...")

    # Alpha Discovery Agent
    print("\n[18/20] Alpha Discovery Agent...")
    all_views['alpha'] = call_agent(
        load_prompt("alpha_discovery"),
        f"FULL AGENT DEBATE:\n{all_views_summary}\n\n{context}", max_tokens=1500
    )
    print(f"  Done: {all_views['alpha'][:100]}...")

    # Autonomous Execution Agent
    print("\n[19/20] Autonomous Execution Agent...")
    all_views['autonomous'] = call_agent(
        load_prompt("autonomous_execution"),
        f"FULL DEBATE:\n{all_views_summary}\n\nCRO:\n{all_views.get('cro', '')}\n\n{context}", max_tokens=1000
    )
    print(f"  Done: {all_views['autonomous'][:100]}...")

    # CIO Final Synthesis
    print("\n[20/20] CIO Synthesis Agent...")
    # Load agent weights for CIO to reference
    agent_weights = load_agent_weights()
    weights_summary = json.dumps(agent_weights, indent=2) if agent_weights else "All agents at weight 1.0 (no history yet)"
    all_views['cio'] = call_agent(
        load_prompt("cio"),
        f"AGENT WEIGHTS:\n{weights_summary}\n\nFULL 20-AGENT DEBATE:\n{all_views_summary}\n\nCRO REVIEW:\n{all_views.get('cro', '')}\n\nALPHA DISCOVERY:\n{all_views.get('alpha', '')}\n\n{context}", max_tokens=2500
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
