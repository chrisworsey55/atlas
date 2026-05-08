## 🚀 ATLAS Agents — Launching Next Week

The platform built on top of this repo is launching next week.

**Three ways to use it:**

1. **Copy ATLAS** — trade alongside the autoresearch system 
   in this repo. Live signals, auto-execution, full 
   transparency. Up 30% since launch.

2. **Build your own** — describe a strategy in plain English, 
   backtest on 18 months of real data, deploy live.

3. **Marketplace** — publish your agent, earn when others 
   copy it.

SIMONS is already live on Kalshi prediction markets. 
60% win rate.

As a thank you for all the feedback, ideas, and support 
that helped shape this project — we're giving the GitHub 
community 20% off. Forever, not just the first month.

→ **[atlasagents.co](https://atlasagents.co)**
Use code **GITHUB20** at checkout. First 100 only.

---

# ATLAS

ATLAS is an AI-native hedge fund system with a live execution loop, scoring, and prompt evolution.

## Autoresearch

Autoresearch is the legacy prompt-improvement loop. It scores agent output, adjusts weights, and rewrites prompts when a worse version is detected.

Core files:
- `agents/autonomous_loop.py`
- `agents/autoresearch_program.md`
- `agents/scorecard.py`
- `data/state/autoresearch_results.tsv`

## Darwin v3

Darwin v3 is the standalone gene-pool and rewrite-planning layer added beside the live loop.

Entry point:
- `darwin_v3/runtime.py`

Runs inside:
- `agents/execution_loop.py`

Key outputs:
- `data/state/judge_daily.json`
- `data/state/janus_daily.json`
- `data/state/decisions_v2.json`
- `data/state/decisions_v3.json`

Gene pool:
- `darwin_v3/gene_pool.db`

## GRAHAM

GRAHAM is the OTC net-net screener and diligence engine. It sources SEC-filing OTC companies, calculates NCAV, applies liquidity and shell-company filters, ranks candidates trading below 0.67x NCAV, and writes weekly diligence outputs.

Entry points:
- `python3 graham/run.py --mode test`
- `python3 graham/run.py --mode status`
- `python3 graham/run.py --mode full`

Outputs:
- `graham/output/screener_{date}.json`
- `graham/output/portfolio_candidates_{date}.md`
- `graham/output/memos/{ticker}_{date}.md`

Terminal:
- `/api/graham`
- F8 INTEL panel, GRAHAM NET-NET SCREEN section
