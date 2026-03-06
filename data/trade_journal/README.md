# ATLAS Trade Journal

This is the AI's memory. Every trade gets a markdown file. The agents read this before making new decisions so they learn from past trades.

## Structure

```
trade_journal/
├── open/       # Active positions
└── closed/     # Completed trades with lessons learned
```

## File Naming Convention

`{TICKER}_{DIRECTION}_{YYYYMMDD}.md`

Examples:
- `BE_LONG_20260303.md`
- `TLT_SHORT_20260302.md`
- `GLD_LONG_20260302.md` (closed)

## How Agents Use This

Before making any new trade recommendation, agents review:
1. **Open positions** — Current status, thesis validation, performance
2. **Closed positions** — Lessons learned, mistakes to avoid

The CRO specifically checks for:
- Similar setups that failed
- Correlated positions that created problems
- Thesis invalidations that should have triggered exits

## Template

Each file follows a standard template:
- Entry details (date, price, shares, allocation, agent)
- Original thesis
- Agent views at entry
- Key levels (stop loss, target, invalidation)
- Performance log (updated as trade progresses)
- Outcome (status, P&L, lessons learned)

## Rules

1. **Never delete a trade file** — even losses are valuable data
2. **Update performance log daily** for open positions
3. **Document lessons learned** immediately after closing a trade
4. **Be honest about mistakes** — the system learns from them
