# ATLAS TERMINAL INVENTORY

Generated: 2026-05-03

Scope: Phase 1 read-only inventory for the proposed ATLAS Terminal. No UI, API, deployment, or runtime changes were made.

## Key Findings

- The production Azure host is active at `/home/azureuser/atlas` with `atlas.service`, `atlas-loop.service`, and `atlas-tracker.service` running under systemd.
- The local repo has both `api/atlas_api.py` (Flask, broad dashboard/API) and `web/api.py` (FastAPI, chat-focused). Production `atlas.service` currently runs `api/atlas_api.py`, not `web/api.py`.
- There is no local `dashboard/` directory or `dashboard.app` module in this checkout, although `deploy/setup-azure.sh` still references `python3 -m dashboard.app`; the live Azure unit has diverged and runs Flask directly.
- Local state files are often older than production state. For operator panels, production state on Azure should be considered authoritative where available.
- The requested 12:00 and 20:00 UTC cron jobs exist on Azure, not in the local crontab.

## Existing Dashboard App

### Name

ATLAS Flask dashboard/API

### Location

- `api/atlas_api.py`
- Templates: `templates/`
- Static directory expected by Flask: `static/` at repo root, but the local tree does not show a root `static/` directory. There is `web/static/index.html` for the FastAPI dashboard.
- Secondary chat-focused FastAPI app: `web/api.py`

### Primary Entry Point

- Production Azure: `/usr/bin/python3 /home/azureuser/atlas/api/atlas_api.py`
- Local Flask file entry: `python3 api/atlas_api.py` if run directly
- Secondary FastAPI: `python3 -m web.api` or an ASGI server against `web.api:app`

### Data Outputs and Inputs

- PostgreSQL via `ATLAS_DATABASE_URL`, defaulting to `postgresql://postgres:postgres@localhost:5432/valis`
- Tables from Alembic:
  - `atlas_companies`
  - `atlas_filings`
  - `atlas_desk_briefs`
  - `atlas_institutional_holdings`
  - `atlas_theses`
  - `atlas_trades`
  - `atlas_portfolio_snapshots`
- JSON state under `data/state/`, including `positions.json`, `decisions.json`, `agent_views.json`, `agent_weights.json`, `pnl_history.json`, `briefings/`

### Current Routes and Consumers

- Browser pages:
  - `/atlas`
  - `/atlas/agents`
  - `/atlas/decisions`
  - `/atlas/chat`
  - `/atlas/company/<ticker>`
  - `/atlas/briefing`
  - `/atlas/autonomous`
  - `/atlas/compare`
- API routes include:
  - `/api/portfolio/summary`
  - `/api/portfolio/chart`
  - `/api/portfolio/positions`
  - `/api/briefs`
  - `/api/trades`
  - `/api/holdings`
  - `/api/company/<ticker>`
  - `/api/market/spy`
  - `/api/atlas/portfolio`
  - `/api/atlas/positions`
  - `/api/atlas/pnl`
  - `/api/atlas/desks`
  - `/api/atlas/agents`
  - `/api/atlas/briefing/latest`
  - `/api/atlas/briefing/generate`
  - `/api/health`

### Freshness

- Live under Azure systemd.
- File-backed panels depend on the freshness of `data/state/*`.
- PostgreSQL-backed panels depend on the live database.

### Current Consumer

Existing web dashboard and browser views. It is the best existing stack to inspect for Phase 2.

## ATLAS Portfolio

### Location

- Core state: `data/state/positions.json`
- Decisions: `data/state/decisions.json`
- Trade log: `data/state/trades.json`
- PnL history: `data/state/pnl_history.json`
- Trade journal directory: `data/trade_journal/`
- Autonomous paper portfolio mirror: `data/autonomous/positions.json`, `data/autonomous/pnl_history.json`

### Primary Entry Points

- `agents.execution_loop` updates state during cycles.
- `agents.autonomous_loop --once` runs production autonomous debates on Azure.
- Dashboard API reads via `api/atlas_api.py`.
- Portfolio helpers:
  - `portfolio/paper_portfolio.py`
  - `portfolio/performance.py`
  - `portfolio/risk_manager.py`

### Data Outputs

Local observed:

- `data/state/positions.json`
  - Local mtime: 2026-03-26 18:39:13
  - Keys include `portfolio_name`, `portfolio_value`, `last_updated`, `cash_balance`, `positions`, `closed_positions`
  - `last_updated`: `2026-03-12T12:52:00`
- `data/state/decisions.json`
  - Local mtime: 2026-03-23 10:40:00
  - 14 decision records
- `data/state/trades.json`
  - Local mtime: 2026-03-23 10:39:58
  - 2 trade records
- `data/state/pnl_history.json`
  - Local mtime: 2026-03-23 10:40:01
  - 15 snapshots

Production Azure observed:

- `/home/azureuser/atlas/data/state/positions.json`
  - mtime epoch: `1777664262.158344`
  - `last_updated`: `2026-05-01 15:37`
  - `portfolio_value`: `1000000`
  - `cash_balance`: `114823.95`
- `/home/azureuser/atlas/data/state/decisions.json`
  - 100 records
  - Last record keys include `timestamp`, `executed`, `reason`, `trade`

### Freshness

- Production: twice daily via Azure cron at 12:00 UTC and 20:00 UTC weekdays, plus `atlas-loop.service`.
- Local checkout: stale relative to production.

### Current Consumer

- Existing Flask dashboard pages and APIs.
- CLI/operator scripts.

## 24-Agent Swarm

### Location

- Agents package: `agents/`
- Prompts: `agents/prompts/`
- Execution loop: `agents/execution_loop.py`
- End-of-day cycle: `agents/eod_cycle.py`
- Gauntlet: `agents/gauntlet.py` and root `run_gauntlet.py`
- Scorecards: `data/state/agent_scorecards.json`
- Views: `data/state/agent_views.json`, `data/state/eod_agent_views.json`
- Weights: `data/state/agent_weights.json`

### Primary Entry Points

- `python3 -m agents.execution_loop --start`
- `python3 -m agents.execution_loop --once`
- `python3 -m agents.eod_cycle`
- `python3 -m agents.autonomous_loop --once` on Azure
- `python3 run_gauntlet.py <ticker>` or related gauntlet modules

### Data Outputs

Local observed:

- `data/state/agent_views.json`
  - Local mtime: 2026-03-23 10:40:00
  - `timestamp`: `2026-03-06T16:38:05.776031-05:00`
- `data/state/agent_weights.json`
  - Local mtime: 2026-03-26 18:39:13
  - Contains weights for 20 local named agents/desks, including `news`, `flow`, `bond`, `currency`, `commodities`, `metals`, `semiconductor`, `biotech`, `energy`, `consumer`, `industrials`, `financials`, `microcap`, `druckenmiller`, `aschenbrenner`, `baker`, `ackman`, `cro`, `alpha`, `autonomous`
- `data/state/agent_scorecards.json`
  - Local mtime: 2026-03-23 10:40:01
  - `last_updated`: `2026-03-09T14:35:20.695641`
  - 19 agent metric rows
  - 129 recommendations
- `data/state/execution_log.json`
  - Local mtime: 2026-03-23 10:39:59

Production Azure observed:

- `/home/azureuser/atlas/data/state/agent_views.json`
  - `timestamp`: `2026-05-01T15:40:54.929177-04:00`
- `/home/azureuser/atlas/data/state/agent_weights.json`
  - mtime epoch: `1777667602.5038757`
  - Contains current production weights
- `/home/azureuser/atlas/data/state/execution_log.json`
  - 500 cycle records
  - Last record keys include `cycle_id`, `cycle_number`, `timestamp`, `dry_run`, `steps`, `errors`, `status`, `duration_seconds`

### Freshness

- Production: updated by active `atlas-loop.service` and twice-daily autonomous cron.
- Local: stale.

### Current Consumer

- Existing Flask dashboard `/atlas/agents`
- JSON state and CLI logs
- Email briefings

## SHANNON Ingestion

### Location

- Directory: `SHANNON/`
- Orchestrator: `SHANNON/shannon.py`
- Ingestion:
  - `SHANNON/ingest/filings.py`
  - `SHANNON/ingest/transcripts.py`
  - `SHANNON/ingest/news.py`
  - `SHANNON/ingest/audio/earnings_calls.py`
- Audio processing:
  - `SHANNON/processing/transcribe.py`
  - `SHANNON/processing/diarize.py`
  - `SHANNON/processing/acoustic.py`
- Scouts:
  - `SHANNON/scouts/catalyst.py`
  - `SHANNON/scouts/thesis.py`
  - `SHANNON/scouts/contra.py`
  - `SHANNON/scouts/vocal.py`
- JANUS adapter: `SHANNON/janus_integration.py`

### Primary Entry Points

- `python3 -m SHANNON.shannon --ticker AAPL`
- `python3 -m SHANNON.shannon --universe test --once`
- `python3 -m SHANNON.shannon --universe sp100 --once`
- `python3 -m SHANNON.janus_integration`

### Data Outputs

- Filing cache: `SHANNON/cache/filings/`
- News cache: `SHANNON/cache/news/`
- Transcript cache: `SHANNON/cache/transcripts/`
- Audio cache: `SHANNON/cache/audio/`
- Memos: `SHANNON/memos/*.md`
  - Local memos: `GOOGL`, `META`, `MSFT`, `NVDA` generated 2026-04-24
- Queue: `SHANNON/queue/candidates.parquet`
  - Local mtime: 2026-04-24 21:33:48
  - 3 rows
  - Columns: `ticker`, `as_of`, `direction`, `conviction`, `catalyst_type`, `catalyst_date`, `thesis_summary`, `contra_summary`, `vocal_flag`, `vocal_note`, `suggested_size_pct`, `source_refs`, `memo_path`
  - Max `as_of`: `2026-04-24 20:33:26 UTC`
  - Rows observed: `MSFT`, `GOOGL`, `META`
- JANUS output: `data/state/recommendations_shannon.json`
  - Local mtime: 2026-04-24 21:34:05
  - `generated_at`: `2026-04-24T20:34:05.672410`
- Logs:
  - `SHANNON/logs/shannon.log`
  - `SHANNON/logs/daily_cost_20260424.txt`

### Freshness

- On-demand in local checkout.
- Production cron for SHANNON was not found in Azure crontab.
- CLAUDE.md documents SHANNON cron examples, but they are not present in the observed Azure crontab.

### Current Consumer

- CLI only plus `SHANNON/janus_integration.py`.
- Existing dashboard does not appear to consume SHANNON queue or memo data directly.

### Wiring Notes

- SEC filing ingestion preserves `filing_date`.
- Transcript ingestion stores `date`, `year`, `quarter`, `content`, and optional `audio_url`, but does not expose a `transcript_date` field by that exact name.
- News ingestion preserves the source timestamp under `datetime`, not `published_at`.
- Audio ingestion and vocal scout exist, but `SHANNON/shannon.py` still passes `vocal=None`, so the audio layer is not integrated into the main orchestrator.

## SIMONS Pattern Engine

### Location

- Main engine: `simons/simons.py`
- Backtest: `simons/simons_backtest.py`
- Live/paper: `simons/simons_live.py`
- Kalshi live tracker: `simons/kalshi_live.py`
- Patterns: `simons/simons_patterns.json`
- Results: `simons/simons_backtest_results.json`

### Primary Entry Points

- `python3 -m simons.simons`
- `python3 -m simons.simons_backtest`
- `python3 -m simons.simons_live`
- `python3 -m simons.kalshi_live`

### Data Outputs

- `simons/simons_patterns.json`
  - Local mtime: 2026-03-27 18:16:49
  - Metadata:
    - `total_hypotheses_tested`: 4864
    - `total_confirmed`: 32
    - `survivorship_bias_corrected`: false
    - training period: 2019-01-01 to 2022-12-31
    - validation period: 2023-01-01 to 2025-12-31
- `simons/simons_backtest_results.json`
  - Local mtime: 2026-03-27 19:00:46
  - `simons_metrics.total_return`: 29.564985520303294%
  - `simons_metrics.sharpe`: 0.7399380007156817
  - `simons_metrics.total_trades`: 215
  - `simons_metrics.win_rate`: 48.372093023255815%
  - `spy_metrics.total_return`: 26.712858458892175%
  - `spy_metrics.sharpe`: 0.8124357107743159
- `simons/live_state.json`
  - Local mtime: 2026-03-27 20:22:44
  - `last_updated`: `2026-03-27 20:22:44`
  - 8 open positions, 0 closed trades
- `data/simons/10y_cache/`
- `data/simons/backtest_results/`

### Freshness

- Mostly on-demand/local backtest artifacts.
- SIMONS live state last observed locally on 2026-03-27.

### Current Consumer

- CLI and email output.
- Existing backtest loop injects SIMONS signals from `simons/simons_patterns.json`.
- Existing dashboard does not appear to have a dedicated SIMONS workspace.

## JANUS Meta-Layer

### Location

- Core: `agents/janus.py`
- Tests: `tests/test_janus.py`
- SHANNON adapter: `SHANNON/janus_integration.py`

### Primary Entry Points

- `python3 -m agents.janus`
- Imported by dashboard/tests as `from agents.janus import Janus`
- SHANNON can produce `data/state/recommendations_shannon.json`

### Data Outputs

Local observed:

- `data/state/janus_daily.json`
  - Local mtime: 2026-03-23 10:40:00
  - `date`: `2026-03-14`
  - `generated_at`: `2026-03-14T21:40:56.806849`
  - `regime`: `MIXED`
  - Contains `cohort_weights`, `blended_recommendations`, `contested_tickers`, `cohort_accuracy_30d`
- `data/state/janus_history.json`
  - Local mtime: 2026-03-23 10:40:01
  - 2 entries
- Cohort input files:
  - `data/state/recommendations_18month.json`
  - `data/state/recommendations_10year.json`
  - `data/state/recommendations_5year.json`
  - `data/state/recommendations_spawning.json`
  - `data/state/recommendations_shannon.json`
- Outcomes:
  - `data/state/scored_outcomes.json`

Production Azure observed:

- `/home/azureuser/atlas/data/state/janus_daily.json` was missing in the production tree checked.

### Freshness

- Local JANUS data appears stale as of 2026-03-14.
- No dedicated JANUS cron was observed on Azure.

### Current Consumer

- CLI/tests.
- Existing dashboard may expose some agent data, but no dedicated JANUS panel was found.

## Darwin v2 Evolution Loop

### Location

- Package: `darwin_v2/`
- Main loop: `darwin_v2/loop.py`
- Equities adapter: `darwin_v2/equities_adapter.py`
- Equities evolution CLI: `darwin_v2/equities_evolution.py`
- Lineage DB: `darwin_v2/lineage/lineage.sqlite`
- Prompt lineage: `darwin_v2/lineage/prompts/`
- Embeddings: `darwin_v2/lineage/embeddings/`
- Scorecards: `darwin_v2/lineage/scorecards/`

### Primary Entry Points

- `python3 -m darwin_v2.equities_evolution --start-date ... --end-date ... --universe ...`
- `python3 -m darwin_v2.example_evolution`
- Tests under `darwin_v2/tests/`

### Data Outputs

- `darwin_v2/lineage/lineage.sqlite`
- `darwin_v2/lineage/prompts/*.json`
- `darwin_v2/lineage/embeddings/*.json`
- `darwin_v2/lineage/scorecards/equities_2025-10-01_2026-04-30.json`
  - Local mtime: 2026-05-02 16:12:20
  - 10 roles observed: `macro`, `sector_desk_semiconductor`, `sector_desk_energy`, `emerging_markets`, `sector_desk_biotech`, `sector_desk_financials`, `cio`, `cro`, `quantitative`, `value`
- `darwin_v2/lineage/scorecards/current_quotes_2026-05-02.json`
- `darwin_v2/lineage/scorecards/current_quotes_polygon_2026-05-02.json`
- `darwin_v2/lineage/scorecards/buy_recommendations_2026-05-02.json`

### Freshness

- Local Darwin v2 scorecards are fresh as of 2026-05-02.
- Branch currently checked out locally: `backtest/autoresearch-v1`.

### Current Consumer

- CLI/tests only.
- No existing dashboard consumer found.

## Backtest Engine

### Location

- Main engine: `agents/backtest_loop.py`
- Azure variant: `agents/backtest_loop_azure.py`
- Results: `data/backtest/`
- Older immutable harness: `autoresearch/backtest.py`

### Primary Entry Points

- `python3 -m agents.backtest_loop`
- `python3 -m agents.backtest_loop --cache-only`
- `python3 -m agents.backtest_loop --resume`
- `python3 -m agents.backtest_loop --no-autoresearch`
- `python3 -m agents.backtest_loop --validate`

### Data Outputs

- Cache:
  - `data/backtest/cache/prices/*.json`
  - `data/backtest/cache/fundamentals/*.json`
  - `data/backtest/cache/macro/fred_data.json`
  - `data/backtest/cache/sector_map.json`
  - `data/backtest/cache/sp500_constituents.json`
- Checkpoints:
  - `data/backtest/checkpoints/day_010.json` through `day_370.json`
- Results:
  - `data/backtest/results/summary.json`
  - `data/backtest/results/trade_journal.json`
  - `data/backtest/results/equity_curve.json`
  - `data/backtest/results/autoresearch_log.json`
  - `data/backtest/results/final_agent_weights.json`
  - `data/backtest/results.tsv`
- Logs:
  - `data/backtest/baseline_18m.log`
  - `data/backtest/evolved_6m.log`
  - PID files: `baseline_pid.txt`, `evolved_pid.txt`

Observed summary:

- Local mtime: `data/backtest/results/summary.json` at 2026-03-28 17:23:41
- Period: `2025-10-01 to 2026-03-05`
- Trading days: 107
- Ending value: `986689.4074699999`
- Total return: `-1.331059253000014%`
- Sharpe: `-5.0780985493058575`
- Total trades: 26
- Autoresearch modifications: 98 total, 21 kept, 76 reverted

### Freshness

- On-demand backtest artifacts.
- No observed production cron for this specific backtest engine.

### Current Consumer

- CLI/logs only.
- Darwin v2 equities adapter reuses `data/backtest/cache/prices/*.json`.

## Kalshi Paper Trading State

### Local Repo Locations

- Legacy/local SIMONS Kalshi tracker:
  - `simons/kalshi_live.py`
  - `simons/kalshi_state.json`
- Local ATLAS predict scripts:
  - `predict/live_paper_trading.py`
  - `predict/paper_trades/trade_history.json`
  - `predict/paper_trades/snapshot_20260408.json`
  - `predict/paper_trades/snapshot_20260409.json`
  - `predict/paper_trades/report_2026-04-08.html`

### Production Azure Locations

- Repo: `/home/azureuser/atlas-predict`
- Main scripts:
  - `/home/azureuser/atlas-predict/live_paper_trading_v3.py`
  - `/home/azureuser/atlas-predict/kalshi_live_trading.py`
  - `/home/azureuser/atlas-predict/predict_all.py`
  - `/home/azureuser/atlas-predict/settle_trades.py`
  - `/home/azureuser/atlas-predict/kalshi_status.sh`
- State:
  - `/home/azureuser/atlas-predict/paper_trades/book_a_history.json`
  - `/home/azureuser/atlas-predict/paper_trades/book_b_history.json`
  - `/home/azureuser/atlas-predict/paper_trades/combined_summary.json`
  - `/home/azureuser/atlas-predict/paper_trades/live/book_a_live.json`
  - `/home/azureuser/atlas-predict/paper_trades/live/book_b_live.json`
  - `/home/azureuser/atlas-predict/paper_trades/live/daily_state.json`

### Primary Entry Points

Local:

- `python3 predict/live_paper_trading.py`
- `python3 -m simons.kalshi_live`

Production:

- `/home/azureuser/atlas-predict/venv/bin/python /home/azureuser/atlas-predict/live_paper_trading_v3.py`
- Cron:
  - 21:55 UTC integrity check
  - 22:00 UTC main trading if integrity passes
  - 22:30 UTC git auto-backup
  - 23:05 UTC clear integrity flag
  - 09:00 UTC daily contract scan
- systemd:
  - `atlas-predict.service` exists as a oneshot but is inactive/dead at inventory time.

### Data Outputs

Local observed:

- `simons/kalshi_state.json`
  - Local mtime: 2026-04-06 10:34:47
  - Starting bankroll: 10000
  - Current bankroll: 8574.33
  - Open bets: 10
  - Closed bets: 3
- `predict/paper_trades/trade_history.json`
  - Local file exists
  - 5 trade records

Production observed:

- `paper_trades/combined_summary.json`
  - mtime epoch: `1777757403.5613134`
  - `date`: `2026-05-02T21:30:03.561053+00:00`
  - Book A:
    - total settled trades: 74
    - wins: 56
    - losses: 18
    - win rate: 75.67567567567568%
    - current bankroll: 5905.0
    - open positions: 4
  - Book B:
    - total settled trades: 73
    - wins: 47
    - losses: 26
    - win rate: 64.38356164383562%
    - current bankroll: 10532.5
    - open positions: 3
- `paper_trades/live/book_a_live.json`
  - 5 live entries, 3 settled, 0 wins in that live file
- `paper_trades/live/book_b_live.json`
  - 2 live entries, 0 settled in that live file

Note: the prompt references Book A / Book B as currently 80.9% / 58.3% with 82 settled trades. The read-only production files observed on 2026-05-03 show different values in `combined_summary.json` and should be treated as the current source of truth unless another state file is identified.

### Freshness

- Production: daily cron-driven around 22:00 UTC plus daily scan at 09:00 UTC.
- Local: stale/legacy.

### Current Consumer

- CLI/status scripts and HTML reports under `/home/azureuser/atlas-predict/paper_trades/`.
- No existing ATLAS dashboard consumer found.

## 13F and Congressional Filing Tracker

### Location

- Package: `tracker/`
- Main loop: `tracker/main.py`
- Config: `tracker/config.py`
- Rich terminal dashboard: `tracker/dashboard.py`
- SEC client: `tracker/sec_client.py`
- House client/parser: `tracker/house_client.py`, `tracker/house_parser.py`
- Alerts: `tracker/alerts.py`
- State model: `tracker/state.py`
- Service: `tracker/deploy/atlas-tracker.service`

### Primary Entry Point

- `python3 -m tracker.main --log /var/log/atlas_tracker.log`

### Data Outputs

Local:

- `state/tracker_state.json`
  - Local mtime: 2026-05-03 17:40:41
  - Local state was mostly empty: `total_polls=0`, `alerts_sent=0`, `entities={}`
- `state/baseline_q4_2025.json`
- `state/holdings/*.json`
  - `altimeter.json`
  - `coatue.json`
  - `duquesne.json`
  - `sit_awareness.json`
  - `tiger_global.json`
  - `tudor.json`
  - `whale_rock.json`

Production Azure:

- `/home/azureuser/atlas/state/tracker_state.json`
  - mtime epoch: `1777828413.0110452`
  - `total_polls`: 7
  - `alerts_sent`: 0
  - `baseline_loaded`: true
- Logs:
  - `/var/log/atlas_tracker.log`
  - `/var/log/atlas_filings.log` for filing monitor cron jobs

### Tracked Entities

13F managers:

- Situational Awareness
- Altimeter
- Coatue
- Whale Rock
- Tiger Global
- Duquesne
- Tudor

House FD:

- Nancy Pelosi
- Ro Khanna

### Deadline and Poll Window

- Target report date: `2026-03-31`
- Baseline report date: `2025-12-31`
- SEC poll window in code:
  - Start: `2026-05-14 18:00 UTC`
  - End: `2026-05-16 06:00 UTC`
- User-facing deadline: May 15, 2026
- As of 2026-05-03, May 15, 2026 is 12 calendar days away.

### Freshness

- Production: live under `atlas-tracker.service`.
- Additional Azure cron monitors:
  - Form 4 weekdays at 22:00 UTC
  - 13F in May/November, days 1-15 at 22:00 UTC
  - 13F in February/August, days 1-14 at 22:00 UTC

### Current Consumer

- Rich terminal dashboard in `tracker/dashboard.py`
- Email alerts
- JSON state files
- No existing web dashboard consumer found beyond general `/api/holdings` and `/api/company/<ticker>` in Flask.

## Cron Jobs at 12:00 and 20:00 UTC

### Local Crontab

Local crontab did not contain ATLAS 12:00 or 20:00 UTC jobs. It contained:

- 07:00 local jobs for `/Users/chrisworsey/gic-underwriting`
- 15-minute sync loop under `.openclaw`

### Azure Crontab

The requested jobs exist on Azure under `azureuser`:

- 12:00 UTC weekdays:
  - `cd /home/azureuser/atlas`
  - Loads `.env`
  - Runs `/usr/bin/python3 -m agents.autonomous_loop --once`
  - Logs to `/home/azureuser/atlas/logs/autonomous_cycle.log`
- 12:05 UTC weekdays:
  - Runs `/usr/bin/python3 -m agents.darwinian_loop --once`
  - Logs to `/home/azureuser/atlas/logs/darwinian_cycle.log`
- 20:00 UTC weekdays:
  - Runs `/usr/bin/python3 -m agents.autonomous_loop --once`
  - Logs to `/home/azureuser/atlas/logs/autonomous_cycle.log`
- 20:05 UTC weekdays:
  - Runs `/usr/bin/python3 -m agents.darwinian_loop --once`
  - Logs to `/home/azureuser/atlas/logs/darwinian_cycle.log`
- Email briefings:
  - 12:15 and 20:15 UTC for autonomous
  - 12:20 and 20:20 UTC for darwinian
  - Logs to `/home/azureuser/atlas/logs/email.log`

### Freshness and Outputs

- Produce/refresh production state under `/home/azureuser/atlas/data/state/`, especially positions, decisions, agent views, agent weights, and execution logs.
- Current consumer is email and JSON state, plus the existing Flask dashboard where it reads those files.

## Systemd Services on Azure

Observed active services relevant to ATLAS:

- `atlas.service`: active/running
  - Runs `/home/azureuser/atlas/api/atlas_api.py`
  - Description: ATLAS AI Trading Dashboard
- `atlas-loop.service`: active/running
  - Runs `python3 -m agents.execution_loop --start`
  - Description: ATLAS Agent Execution Loop
- `atlas-tracker.service`: active/running
  - Runs `python3 -m tracker.main --log /var/log/atlas_tracker.log`
  - Description: ATLAS 13F + Congressional FD Filing Tracker
- `atlas-predict.service`: loaded but inactive/dead
  - Oneshot for `/home/azureuser/atlas-predict/live_paper_trading_v3.py`

Other infrastructure:

- `nginx.service`: active/running
- `postgresql@16-main.service`: active/running

## Readiness for Terminal Panels

### Clearly Wireable Now

- Portfolio F1:
  - Use production `/home/azureuser/atlas/data/state/positions.json`, `decisions.json`, `pnl_history.json`, `trades.json`
  - Local fallback under `data/state/`
- Agents F2:
  - Use production `agent_views.json`, `agent_weights.json`, `agent_scorecards.json` where available, and `execution_log.json`
- SHANNON F3:
  - Use local `SHANNON/queue/candidates.parquet`, `SHANNON/memos/`, `SHANNON/logs/`, caches, `data/state/recommendations_shannon.json`
  - Must mark audio integration as partially wired if shown
- SIMONS F4:
  - Use `simons/simons_patterns.json`, `simons/simons_backtest_results.json`, `simons/live_state.json`
- Tracker/Intel F8:
  - Use production tracker state, local `state/holdings/*.json`, tracker config, and tracker logs if accessible
- Kalshi F7:
  - Best source is production `/home/azureuser/atlas-predict/paper_trades/combined_summary.json` plus book histories

### Partially Wireable

- JANUS F5:
  - Local JSON exists but stale.
  - Production `janus_daily.json` was not present in the checked production state.
  - Should return `NOT_WIRED` or `STALE` unless the endpoint uses local fallback with explicit source/staleness.
- Backtest F6:
  - Existing results are wireable.
  - Ablation results were not found.
  - Darwin v2 generations/lineage are wireable from SQLite/files, but need a small read adapter.

### Not Yet Wireable Without Additional Work

- Live SHANNON ingestion freshness if no cron/service is added.
- JANUS live regime if production file remains missing.
- Backtest ablation results, because no ablation runner/output was found.
- Any dashboard claim of "24-agent swarm" should reconcile the exact production agent set, because local state has 20 weighted keys while backtest has 25 names including SIMONS and macro sub-agents.
