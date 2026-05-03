# ATLAS TERMINAL ARCHITECTURE

Generated: 2026-05-03

Scope: Phase 2 architecture for the ATLAS Terminal. This document does not implement the terminal, change services, or modify deployment state.

## Executive Choice

Build a parallel FastAPI service under `terminal/`, deployed on the Azure host next to the canonical production state at `/home/azureuser/atlas`.

Production on Azure is canonical. Local repo state is development-only and must not be treated as live truth for operator panels. The production terminal reads directly from Azure files, databases, and process state on the same host; local development uses an explicit read-only snapshot sync from Azure into `terminal/dev_state/` with a metadata file showing snapshot time and source host.

## Backend Decision

Run a parallel FastAPI service on a separate localhost port behind nginx, instead of extending `api/atlas_api.py`.

The existing Flask app in `api/atlas_api.py` is already production-critical and mixes browser routes, PostgreSQL reads, state-file reads, yfinance calls, and existing `/api/...` behavior. A parallel FastAPI service lets the terminal enforce stricter contracts around provenance, freshness, timeouts, auth, streaming, and `NOT_WIRED` responses without destabilising the current `/atlas` dashboard. FastAPI is already in `requirements.txt` and `web/api.py`, so this adds no new framework dependency and keeps the terminal isolated enough to restart independently under `atlas-terminal.service`.

## Canonical Data Model

Every terminal endpoint returns:

```json
{
  "status": "OK",
  "as_of": "2026-05-03T12:00:00Z",
  "source": "/home/azureuser/atlas/data/state/positions.json",
  "stale": false,
  "staleness_seconds": 42,
  "data": {}
}
```

If a panel cannot be wired honestly:

```json
{
  "status": "NOT_WIRED",
  "as_of": "2026-05-03T12:00:00Z",
  "source": null,
  "reason": "production janus_daily.json missing - local file stale 2026-04-24"
}
```

If a source is slow or temporarily unreadable, the endpoint returns the last cached value with:

```json
{
  "status": "STALE_CACHE",
  "stale": true,
  "reason": "source read timed out after 5 seconds"
}
```

## Production State Access

### Production

The terminal runs on Azure as:

- Working directory: `/home/azureuser/atlas`
- Service module: `terminal.app:app`
- State root: `/home/azureuser/atlas`
- Kalshi state root: `/home/azureuser/atlas-predict`
- Database: existing `ATLAS_DATABASE_URL`
- URL: `https://meetvalis.com/terminal`

This avoids SSH reads, remote file polling, and cross-host clock ambiguity in production.

### Local Development

Local development can read either:

- Local repo files under `/Users/chrisworsey/Desktop/atlas`, labelled `development_state`
- A read-only Azure snapshot copied into `terminal/dev_state/azure_snapshot/`

The snapshot sync should be explicit, never automatic inside request handlers. The snapshot should include a `snapshot_manifest.json` containing `source_host`, `source_path`, `created_at`, file list, and mtimes so local screens visibly show that they are not live production.

## Freshness Policy

All wired data sources have an expected refresh interval. `/api/health` computes freshness centrally, and the persistent header shows a single red dot if any wired source is stale beyond threshold.

| Source | Expected Refresh | Stale Threshold | Notes |
| --- | ---: | ---: | --- |
| Portfolio positions | Weekdays 12:00 and 20:00 UTC plus live loop | 14 hours on weekdays | From production `data/state/positions.json` |
| Portfolio decisions | Weekdays 12:00 and 20:00 UTC | 14 hours on weekdays | From production `data/state/decisions.json` |
| Agent views | Active loop plus cron | 2 hours | From production `agent_views.json` |
| Agent weights | Active loop plus cron | 14 hours on weekdays | Numeric agent count and weights are read live |
| Agent scorecards | Daily or loop-driven | 24 hours | Rolling Sharpe/conviction where available |
| SHANNON queue | No cron found | 24 hours | Must show prominent stale banner; observed latest output 2026-04-24 |
| SHANNON recommendation adapter | No cron found | 24 hours | `recommendations_shannon.json` |
| SIMONS patterns | On demand | 7 days | Pattern count read from `simons_patterns.json`, never hardcoded |
| SIMONS backtest results | On demand | 30 days | Sharpe/return read from results file |
| JANUS daily | Daily expected, production missing | Always `NOT_WIRED` until production file exists | Reason fixed below |
| Darwin v2 scorecards | On demand | 7 days | Read lineage scorecards and sqlite metadata |
| Backtest summary | On demand | 30 days | Read `data/backtest/results/summary.json` |
| Kalshi Book A/B | Daily cron around 22:00 UTC | 26 hours | Win rates and settled counts read live, never hardcoded |
| Filing tracker | Active service | 2 hours | Read tracker state and systemd status |
| Cron inventory | Crontab and systemd timers | 24 hours | Parsed by health endpoint |

## Health Endpoint

`GET /api/health` returns one object covering every wired source and every cron job listed in Phase 1.

```json
{
  "status": "DEGRADED",
  "as_of": "2026-05-03T12:00:00Z",
  "host": "atlas-azure",
  "red_dot": true,
  "sources": [
    {
      "name": "portfolio.positions",
      "status": "OK",
      "source": "/home/azureuser/atlas/data/state/positions.json",
      "as_of": "2026-05-01T15:37:00Z",
      "stale": false,
      "threshold_seconds": 50400
    }
  ],
  "cron": [
    {
      "name": "autonomous_loop_noon",
      "schedule": "0 12 * * 1-5",
      "command": "python3 -m agents.autonomous_loop --once",
      "status": "PRESENT",
      "last_observed": null,
      "source": "crontab -l"
    }
  ]
}
```

Cron status is computed from the production crontab plus log-file mtimes where logs exist. A missing expected cron entry returns `MISSING`; an entry present with stale output logs returns `STALE`; an entry present but without a known output log returns `PRESENT_UNVERIFIED`.

Expected cron jobs from inventory:

- `agents.autonomous_loop --once` at 12:00 UTC weekdays
- `agents.darwinian_loop --once` at 12:05 UTC weekdays
- Email briefing at 12:15 UTC weekdays
- Email briefing deliver at 12:20 UTC weekdays
- `agents.autonomous_loop --once` at 20:00 UTC weekdays
- `agents.darwinian_loop --once` at 20:05 UTC weekdays
- Email briefing at 20:15 UTC weekdays
- Email briefing deliver at 20:20 UTC weekdays
- Weekly briefing Sunday
- ATLAS Predict integrity at 21:55 UTC
- ATLAS Predict trading at 22:00 UTC
- ATLAS Predict backup at 22:30 UTC
- ATLAS Predict flag clear at 23:05 UTC
- ATLAS Predict contract scan at 09:00 UTC

## Endpoint Map

All terminal endpoints live under `/terminal/api/...` externally through nginx and `/api/...` internally in the FastAPI app.

| Workspace | Panel | Route | Primary Sources | Update Model |
| --- | --- | --- | --- | --- |
| Header | Clock/session/PnL/cash/health dot | `/api/header` | positions, market calendar logic, `/api/health` summary | SSE every 5s |
| Footer | Command status | `/api/commands/status` | command runner cache | SSE |
| F1 Portfolio | Summary | `/api/portfolio/summary` | `data/state/positions.json`, `pnl_history.json` | Poll 15s |
| F1 Portfolio | Positions | `/api/portfolio/positions` | `data/state/positions.json` | Poll 15s |
| F1 Portfolio | PnL history | `/api/portfolio/pnl` | `data/state/pnl_history.json` | Poll 60s |
| F1 Portfolio | Decisions log | `/api/portfolio/decisions` | `data/state/decisions.json` | Poll 30s |
| F1 Portfolio | Risk metrics | `/api/portfolio/risk` | positions, portfolio risk helpers if importable | Poll 60s |
| F2 Agents | Agent table | `/api/agents/overview` | `agent_views.json`, `agent_weights.json`, `agent_scorecards.json` | Poll 15s |
| F2 Agents | Execution log | `/api/agents/execution-log` | `execution_log.json` | Poll 30s |
| F2 Agents | Prompt rewrite state | `/api/agents/prompts` | `agents/prompts/`, scorecards where available | Manual/poll 5m |
| F3 SHANNON | Queue stats | `/api/shannon/queue` | `SHANNON/queue/candidates.parquet` | Poll 60s |
| F3 SHANNON | Last items | `/api/shannon/items` | queue parquet, cache directories, memos | Poll 60s |
| F3 SHANNON | Scout/memo counts | `/api/shannon/scouts` | `SHANNON/memos/`, scout outputs, logs | Poll 5m |
| F3 SHANNON | Staleness banner | `/api/shannon/status` | queue mtimes, recommendation file, `/api/health` | Poll 30s |
| F4 SIMONS | Pattern counts | `/api/simons/patterns` | `simons/simons_patterns.json` | Poll 5m |
| F4 SIMONS | Signal counts | `/api/simons/signals` | SIMONS state/output files if present | Poll 5m |
| F4 SIMONS | Backtest stats | `/api/simons/backtest` | `simons/simons_backtest_results.json` | Manual/poll 5m |
| F5 JANUS | Regime | `/api/janus/regime` | production `data/state/janus_daily.json` | Returns `NOT_WIRED` until file exists |
| F5 JANUS | Weights | `/api/janus/weights` | `agent_weights.json`, JANUS output if present | Poll 60s or `NOT_WIRED` |
| F5 JANUS | Last reweight | `/api/janus/reweighting` | JANUS state/log files if present | Poll 5m or `NOT_WIRED` |
| F6 Backtest | Darwin generations | `/api/backtest/darwin` | `darwin_v2/lineage/lineage.sqlite`, scorecards | Manual/poll 5m |
| F6 Backtest | Fitness scores | `/api/backtest/fitness` | Darwin scorecards | Manual |
| F6 Backtest | Equity curves | `/api/backtest/equity` | `data/backtest/results/`, checkpoints | Manual |
| F6 Backtest | Ablations | `/api/backtest/ablations` | ablation outputs if found | `NOT_WIRED` until output exists |
| F7 Kalshi | Book A/B stats | `/api/kalshi/summary` | `/home/azureuser/atlas-predict/paper_trades/combined_summary.json` | Poll 60s |
| F7 Kalshi | Recent trades | `/api/kalshi/trades` | Book A/B history files | Poll 60s |
| F7 Kalshi | Position sizes | `/api/kalshi/positions` | live Book A/B files | Poll 60s |
| F8 Intel | Tracker summary | `/api/intel/tracker` | tracker state files, tracker config | Poll 5m |
| F8 Intel | Deadline countdown | `/api/intel/deadline` | tracker config, current UTC date | Poll 1h |
| F8 Intel | Fund/person status | `/api/intel/entities` | tracker config/state | Poll 5m |
| F8 Intel | News/geopolitical output | `/api/intel/news` | news agent outputs where present | Poll 5m or `NOT_WIRED` |
| Global | Health | `/api/health` | all wired sources, crontab, systemd/log mtimes | Poll 15s |
| Global | Command dispatch | `/api/commands/run` | subprocess/import allowlist | On submit |
| Global | Command stream | `/api/commands/stream/{id}` | command stdout cache | SSE |

## JANUS Policy

F5 JANUS ships as `NOT_WIRED` unless `/home/azureuser/atlas/data/state/janus_daily.json` exists in production and passes freshness checks.

The exact reason string is:

```text
production janus_daily.json missing - local file stale 2026-04-24
```

The terminal must not infer a current JANUS regime from local files, agent weights, or historical outputs.

## SHANNON Policy

F3 SHANNON is wired to real SHANNON files, but it must render staleness prominently when the queue or recommendation output exceeds threshold.

Observed Phase 1 state:

- Queue: `SHANNON/queue/candidates.parquet`
- Latest observed queue timestamp: `2026-04-24 20:33:26 UTC`
- Recommendation adapter output: `data/state/recommendations_shannon.json`
- No SHANNON cron found on Azure

The panel header should show queue row count, newest `as_of`, and stale age from live file metadata. It must not imply the ingestion pipeline is healthy solely because a parquet file exists.

## No Hardcoded Operational Numbers

Panel headers must derive metrics from live state files on every request or cache refresh.

Examples:

- SIMONS pattern count comes from `simons/simons_patterns.json`
- SIMONS Sharpe and return come from `simons/simons_backtest_results.json`
- Kalshi Book A/B win rates and settled counts come from production summary/history files
- Agent count comes from the merged live keys in `agent_views.json`, `agent_weights.json`, and `agent_scorecards.json`
- Portfolio PnL, cash percent, exposure, and positions come from production portfolio state

Constants are allowed only for display labels, route names, expected source paths, and freshness thresholds.

## Frontend Choice

Use server-rendered HTML with HTMX plus small Alpine.js islands for command history, focus handling, and function-key workspace switching. The terminal is a dense operator UI with fixed panels, partial updates, and server-owned data contracts, so HTMX maps cleanly to `/api/...` fragments and avoids a build pipeline. This also keeps deployment simple on Azure: static assets, Jinja templates, and one FastAPI process with no Next.js or frontend build step.

## Update Model

- SSE:
  - Header health dot, UTC clock, command output stream, service status ticker
- Polling:
  - Portfolio, agents, SHANNON, Kalshi, health, tracker
- Manual refresh:
  - Backtest results, Darwin lineage, ablations, expensive summaries
- Command-triggered refresh:
  - `/pnl`, `/cycle`, `/briefing`, `/backtest run`, `/screen TICKER`

Each source read has a 5-second timeout. Endpoint handlers use a small process-local cache keyed by route and source mtime; timeout or parse failure returns the last cached value with staleness metadata instead of blocking the UI.

## Authentication

Use single-user shared-secret auth for Phase 1 terminal deployment.

- Env var: `ATLAS_TERMINAL_SECRET`
- Accepted mechanisms:
  - `Authorization: Bearer <secret>` for API/SSE
  - Secure HTTP-only session cookie after entering the secret on `/terminal/login`
- No user table, roles, OAuth, or hosted auth vendor.

Nginx basic auth is acceptable as an outer layer, but the FastAPI app should still enforce the shared secret so direct port access is not trusted.

## Command Bar Architecture

Commands are routed through `/api/commands/run` and executed only through an explicit allowlist.

| Command | Backend Action |
| --- | --- |
| `TICKER` | Set active ticker context; fetch cross-panel source data already available locally |
| `/screen TICKER` | Run existing gauntlet entry point |
| `/cycle` | Run one existing agent execution cycle |
| `/briefing` | Run existing briefing generator |
| `/pnl` | Refresh price/PnL path using existing portfolio code |
| `/status` | Return `/api/health` plus systemd summary |
| `/shannon` | UI workspace switch to F3 |
| `/janus` | UI workspace switch to F5 |
| `/backtest run` | Start existing Darwin/backtest command only after final implementation review |
| `/trade BUY|SELL TICKER QTY PRICE` | Record paper trade through existing trade journal path |
| `/help` | Render command allowlist |

Each command result has a command id. Stdout and stderr are streamed into the terminal status panel through `/api/commands/stream/{id}`.

## File Layout

```text
terminal/
  README.md
  __init__.py
  app.py
  auth.py
  settings.py
  cache.py
  freshness.py
  sources/
    __init__.py
    base.py
    portfolio.py
    agents.py
    shannon.py
    simons.py
    janus.py
    backtest.py
    kalshi.py
    intel.py
    cron.py
    systemd.py
  commands/
    __init__.py
    registry.py
    runner.py
  templates/
    terminal.html
    login.html
    fragments/
      header.html
      footer.html
      portfolio.html
      agents.html
      shannon.html
      simons.html
      janus.html
      backtest.html
      kalshi.html
      intel.html
      not_wired.html
  static/
    terminal.css
    terminal.js
  dev_state/
    README.md
    azure_snapshot/
      snapshot_manifest.json
  tests/
    test_freshness.py
    test_sources.py
    test_health.py
```

## Deployment Shape

The terminal will run as a separate service:

- systemd unit: `atlas-terminal.service`
- bind: `127.0.0.1:8010`
- ASGI: `uvicorn terminal.app:app`
- nginx route: `/terminal`
- health check: `/terminal/health` and `/terminal/api/health`
- logs: `/var/log/atlas_terminal.log`

The existing Flask service remains responsible for `/atlas` and current `/api/...` behavior.

## Phase 3 Readiness

The next phase can produce the fixed 12-column layout spec against the endpoint map above.

Phase 3 should preserve these architecture constraints:

- No mocked values
- Production Azure state is canonical
- `NOT_WIRED` is rendered honestly with source-specific reasons
- Header health dot is driven by `/api/health`
- Numeric header metrics are live reads, not constants
- F1 Portfolio and F2 Agents are the first fully wired workspaces
