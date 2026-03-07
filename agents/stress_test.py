#!/usr/bin/env python3
"""
Stress test the portfolio under different macro scenarios.
Skill: /stress
"""
import argparse
import json
import os
import anthropic
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Load environment
load_dotenv(Path(__file__).parent.parent / ".env")

STATE_DIR = Path(__file__).parent.parent / "data" / "state"

client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

MODEL = "claude-sonnet-4-20250514"

# Predefined stress scenarios
SCENARIOS = {
    "recession": {
        "name": "Sharp Recession",
        "description": "GDP contracts 3%. Unemployment spikes to 7%. Fed cuts rates 200bps in 6 months. 10Y treasury drops to 2.5%. S&P 500 falls 30%. Credit spreads blow out 300bps."
    },
    "ai_bust": {
        "name": "AI Bubble Pops",
        "description": "AI spending bubble bursts. Hyperscalers cut capex 40%. NVIDIA revenue declines 50%. AI-related stocks fall 50-70%. Traditional value stocks outperform. Flight to defensive sectors."
    },
    "inflation_spike": {
        "name": "Inflation Re-acceleration",
        "description": "Inflation re-accelerates to 6%. Fed raises rates to 7%. Oil hits $150/barrel. Dollar strengthens 15%. Bonds crash (TLT -25%). Gold rallies 20%. Growth stocks collapse."
    },
    "iran_escalation": {
        "name": "Iran War Escalation",
        "description": "Iran conflict escalates to full regional war. Strait of Hormuz closed. Oil hits $200/barrel. Global supply chains severely disrupted. Flight to safety. VIX spikes to 60. S&P 500 falls 20% in 2 weeks."
    },
    "soft_landing": {
        "name": "Perfect Soft Landing",
        "description": "Inflation at 2%. GDP growth steady at 3%. Fed cuts gradually to 3%. S&P 500 rallies 20%. Credit spreads tighten. Risk assets outperform. Quality growth leads."
    },
    "china_taiwan": {
        "name": "China-Taiwan Crisis",
        "description": "China blockades Taiwan. TSMC production halted. Global semiconductor shortage. All tech stocks crash 30-50%. Defense stocks surge 50%. Global equities fall 25%. Dollar rallies as safe haven."
    },
    "banking_crisis": {
        "name": "Banking Crisis 2.0",
        "description": "Regional bank failures spread. Credit contraction. CRE defaults spike. Fed emergency cuts 150bps. Financials crash 40%. Flight to quality. Treasury yields collapse."
    },
    "debt_crisis": {
        "name": "US Debt Crisis",
        "description": "US credit downgrade. Treasury auction fails. 10Y yields spike to 7%. Dollar crashes 20%. Gold surges 40%. All risk assets sell off. Global contagion."
    }
}


def load_portfolio() -> tuple[list, str]:
    """Load current portfolio positions and format for analysis."""
    positions_file = STATE_DIR / "positions.json"

    with open(positions_file) as f:
        data = json.load(f)

    if isinstance(data, dict) and 'positions' in data:
        positions = data['positions']
    else:
        positions = data if isinstance(data, list) else list(data.values())

    # Format portfolio description
    lines = []
    total_value = 0
    for pos in positions:
        ticker = pos.get('ticker', '?')
        direction = pos.get('direction', 'LONG')
        shares = pos.get('shares', 0)
        entry = pos.get('entry_price', 0)
        alloc = pos.get('allocation_pct', 0)
        thesis = pos.get('thesis', '')[:80]
        value = shares * entry
        total_value += value

        lines.append(f"- {ticker}: {direction} {shares:,} shares @ ${entry:.2f} ({alloc}% allocation)")
        lines.append(f"  Thesis: {thesis}")

    portfolio_desc = "\n".join(lines)
    portfolio_desc = f"Total Portfolio Value: ${total_value:,.0f}\n\n{portfolio_desc}"

    return positions, portfolio_desc


def run_stress_test(scenario_name: str = None):
    """Run stress test analysis on portfolio."""

    positions, portfolio_desc = load_portfolio()

    print(f"\n{'='*70}")
    print(f"  ATLAS STRESS TEST")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*70}")

    # Determine which scenarios to run
    if scenario_name:
        if scenario_name not in SCENARIOS:
            print(f"\nERROR: Unknown scenario '{scenario_name}'")
            print(f"Available scenarios: {', '.join(SCENARIOS.keys())}")
            return
        scenarios_to_run = {scenario_name: SCENARIOS[scenario_name]}
    else:
        scenarios_to_run = SCENARIOS

    results = {
        "date": datetime.now().isoformat(),
        "portfolio_tested": [p['ticker'] for p in positions],
        "scenarios": {}
    }

    system_prompt = """You are a portfolio risk analyst at a hedge fund. For each stress scenario, analyze the portfolio impact with specific, quantified estimates.

OUTPUT FORMAT (JSON):
{
  "scenario": "Scenario name",
  "total_portfolio_impact_pct": -15.5,
  "total_dollar_impact": -155000,
  "position_impacts": [
    {
      "ticker": "SYMBOL",
      "direction": "LONG|SHORT",
      "estimated_move_pct": -25.0,
      "dollar_impact": -50000,
      "reasoning": "Why this position moves this way",
      "action": "HOLD|TRIM|EXIT|ADD"
    }
  ],
  "correlation_concerns": "How positions interact",
  "hedge_recommendations": ["Recommended hedges"],
  "key_risk": "The biggest risk in this scenario",
  "silver_lining": "Any positions that benefit"
}

Be specific. Use actual dollar amounts based on the position sizes given. Don't be vague."""

    for name, scenario in scenarios_to_run.items():
        print(f"\n{'='*70}")
        print(f"  SCENARIO: {scenario['name'].upper()}")
        print(f"{'='*70}")
        print(f"  {scenario['description'][:80]}...")

        user_prompt = f"""STRESS TEST SCENARIO: {scenario['name']}

SCENARIO DESCRIPTION:
{scenario['description']}

CURRENT PORTFOLIO:
{portfolio_desc}

For each position, estimate:
1. Price change percentage in this scenario
2. Dollar P&L impact
3. Brief reasoning
4. Recommended action (HOLD/TRIM/EXIT/ADD)

Then provide:
- Total portfolio impact (% and $)
- Correlation concerns (which positions move together)
- Hedge recommendations
- Biggest single risk
- Any positions that benefit (silver lining)

Respond with ONLY valid JSON."""

        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=2000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}]
            )

            raw_response = response.content[0].text

            # Parse JSON
            try:
                analysis = json.loads(raw_response.strip().replace('```json', '').replace('```', ''))
            except json.JSONDecodeError:
                analysis = {"raw": raw_response, "error": "Failed to parse JSON"}

            results["scenarios"][name] = analysis

            # Display results
            if isinstance(analysis, dict) and 'total_portfolio_impact_pct' in analysis:
                impact_pct = analysis.get('total_portfolio_impact_pct', 0)
                impact_dollar = analysis.get('total_dollar_impact', 0)

                # Color code impact
                if impact_pct >= 0:
                    color = '\033[92m'  # Green
                elif impact_pct >= -10:
                    color = '\033[93m'  # Yellow
                else:
                    color = '\033[91m'  # Red
                reset = '\033[0m'

                print(f"\n  TOTAL IMPACT: {color}{impact_pct:+.1f}% (${impact_dollar:+,.0f}){reset}")

                # Position-level impacts
                print(f"\n  Position Impacts:")
                for pos in analysis.get('position_impacts', []):
                    ticker = pos.get('ticker', '?')
                    move = pos.get('estimated_move_pct', 0)
                    dollar = pos.get('dollar_impact', 0)
                    action = pos.get('action', 'HOLD')

                    move_color = '\033[92m' if move >= 0 else '\033[91m'
                    action_color = '\033[93m' if action in ['TRIM', 'EXIT'] else '\033[0m'

                    print(f"    {ticker:6} {move_color}{move:+6.1f}%{reset} (${dollar:+8,.0f}) — {action_color}{action}{reset}")

                # Key risk
                if 'key_risk' in analysis:
                    print(f"\n  KEY RISK: {analysis['key_risk'][:70]}...")

                # Silver lining
                if 'silver_lining' in analysis:
                    print(f"  SILVER LINING: {analysis['silver_lining'][:70]}...")

                # Hedge recommendations
                if 'hedge_recommendations' in analysis:
                    print(f"\n  HEDGE RECOMMENDATIONS:")
                    for hedge in analysis['hedge_recommendations'][:3]:
                        print(f"    - {hedge[:60]}")
            else:
                print(f"\n  Analysis: {str(analysis)[:200]}...")

        except Exception as e:
            print(f"\n  ERROR: {e}")
            results["scenarios"][name] = {"error": str(e)}

    # Save results
    output_file = STATE_DIR / "stress_test_results.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\n{'='*70}")
    print(f"  STRESS TEST COMPLETE")
    print(f"  Results saved to: {output_file}")
    print(f"{'='*70}")

    # Summary table
    print(f"\n  SCENARIO SUMMARY:")
    print(f"  {'Scenario':<25} {'Impact':>10} {'Dollar':>15}")
    print(f"  {'-'*50}")

    for name, analysis in results["scenarios"].items():
        if isinstance(analysis, dict) and 'total_portfolio_impact_pct' in analysis:
            impact = analysis['total_portfolio_impact_pct']
            dollar = analysis['total_dollar_impact']

            if impact >= 0:
                color = '\033[92m'
            elif impact >= -10:
                color = '\033[93m'
            else:
                color = '\033[91m'
            reset = '\033[0m'

            print(f"  {SCENARIOS[name]['name']:<25} {color}{impact:>+9.1f}%{reset} {color}${dollar:>+14,.0f}{reset}")

    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Stress test portfolio under different scenarios')
    parser.add_argument('--scenario', '-s',
                        choices=list(SCENARIOS.keys()),
                        default=None,
                        help='Run specific scenario (default: all)')
    parser.add_argument('--list', '-l',
                        action='store_true',
                        help='List available scenarios')

    args = parser.parse_args()

    if args.list:
        print("\nAvailable Stress Test Scenarios:")
        print("=" * 60)
        for key, scenario in SCENARIOS.items():
            print(f"\n{key}:")
            print(f"  {scenario['name']}")
            print(f"  {scenario['description'][:80]}...")
    else:
        run_stress_test(args.scenario)
