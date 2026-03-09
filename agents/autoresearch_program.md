# ATLAS Autoresearch Program

This document governs the self-improvement loop for ATLAS agent prompts. Adapted from Karpathy's autoresearch concept: the system experiments on its own prompts overnight, keeps what works, reverts what doesn't, and never stops.

## Core Principle

The autonomous loop modifies agent prompts, tests them in live trading, and keeps only the improvements. This is Darwinian selection applied to AI trading agents.

## Rules

### What Can Be Modified
- **ONLY** files in `agents/prompts/*.md` are mutable
- These contain the system prompts for each of the 20 agents
- Everything else is infrastructure and must NOT be changed

### What Must NEVER Be Modified
- `agents/market_data.py` - data fetching infrastructure
- `agents/update_prices.py` - P&L calculation
- `agents/scorecard.py` - performance measurement
- `agents/autonomous_loop.py` - the loop itself
- Any files outside the prompts directory

### Experimentation Protocol
1. **One change per cycle** - Single variable experiments only
2. **Wait for evaluation** - Let the change run for at least one trading day
3. **Measure objectively** - Sharpe ratio (10-day rolling) is the metric
4. **Keep or revert** - No middle ground, binary decision
5. **Monotonic improvement** - Portfolio of prompts only gets better over time

## NEVER STOP

Once the loop begins, do NOT pause to ask the human anything. Do NOT ask "should I continue?" or "is this working?"

Chris might be asleep or away for days. You are fully autonomous.

If you run out of improvement ideas:
- Think harder
- Re-read the losing trades in detail
- Study what the best agents do differently
- Try combining approaches from winning agents
- Try radical framework changes
- Try making prompts simpler (often works!)

The loop runs until manually interrupted.

## Strategy for Prompt Modifications

### Finding Failure Patterns

When analyzing an underperforming agent, look for:

1. **Signal problems** - Agent looking at wrong data
   - Example: Bond desk ignoring credit spreads
   - Fix: Add explicit instructions to monitor credit

2. **Sizing problems** - Agent recommending too much or too little
   - Example: Always recommending 15% positions
   - Fix: Add conviction-based sizing rules

3. **Timing problems** - Right on direction, wrong on entry
   - Example: Buying breakouts that immediately reverse
   - Fix: Add patience rules, wait for confirmation

4. **Framework problems** - Analytical approach is flawed
   - Example: Using outdated macro framework
   - Fix: Update to current market regime

### Making Changes

When you identify a failure pattern:

1. **Be specific** - Don't make vague changes
   - Bad: "Be more careful"
   - Good: "Do not recommend >10% positions without 3+ confirming signals"

2. **Be minimal** - One instruction change per experiment
   - Bad: Rewrite the entire prompt
   - Good: Add/modify/remove ONE specific instruction

3. **Be measurable** - The change should be testable
   - Bad: "Think harder about risks"
   - Good: "List top 3 risks before any BUY recommendation"

### Simplification

Every few cycles, try removing instructions instead of adding them:
- Shorter prompts are often more effective
- Agents can be over-specified
- Remove rules that aren't being followed anyway
- Delete redundant instructions

If removing an instruction doesn't hurt performance, the removal is an improvement.

### Moving On

After 3 failed modification attempts on one agent:
- Stop trying to fix that agent for now
- Move to the next worst agent
- Return to the difficult agent later with fresh perspective

## Metrics

### Primary Metric: Sharpe Ratio (10-day)
- Higher is better
- Measures risk-adjusted returns
- Calculated as: mean(returns) / std(returns)

### Secondary Metrics
- Hit rate (5d, 10d): % of recommendations profitable
- Average return (5d, 10d): Mean return of recommendations
- Best/worst call: Track extreme outcomes

### Weight Adjustments
Based on Sharpe ratio performance:
- Sharpe > 0: weight × 1.1 (agent gets louder)
- Sharpe ≤ 0: weight × 0.9 (agent gets quieter)
- Floor: 0.3 (triggers mandatory prompt rewrite)
- Ceiling: 2.5 (prevents over-concentration)

## Logging

All experiments are logged to `data/state/autoresearch_results.tsv`:

| Column | Description |
|--------|-------------|
| date | Date of experiment |
| agent | Agent name |
| commit | Version number (v1, v2, ...) |
| sharpe_10d | Sharpe ratio at time of experiment |
| weight | Agent weight at time of experiment |
| status | keep / discard / crash / pending |
| description | Brief description of the change |

This file is NOT committed to git (untracked). It's for local analysis only.

## Success Criteria

The system is working when:
1. Agent weights diverge from 1.0 over time
2. Prompts accumulate version numbers (v3, v4, v5...)
3. Portfolio Sharpe ratio trends upward
4. Worst agent keeps changing (no permanent underperformer)

## Example Experiment

**Agent:** semiconductor
**Problem:** Recommending longs into declining chip cycle
**Analysis:** Agent ignores inventory data
**Change:** Add instruction: "Check TSMC utilization before any semiconductor recommendation. If <80%, bias toward NEUTRAL or SHORT."
**Result:** Agent stops recommending longs in weak cycle
**Status:** KEEP

## Emergency Stop

If something goes catastrophically wrong:
- The portfolio has stop losses on every position
- No single position can exceed 15%
- Cash floor of 15% is enforced
- Worst case: Chris reviews in a few days and intervenes

The system is designed to fail gracefully, not catastrophically.
