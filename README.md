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
