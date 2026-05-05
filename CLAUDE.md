# ATLAS AI Trading System — Control Center

## What This Is
ATLAS is an AI-native hedge fund with 20+ autonomous agents that source, analyse, debate, and execute trades. The system runs on Azure at meetvalis.com/atlas.

## Quick Commands (Skills)

### Trading Operations
- `/graham` — Run or inspect GRAHAM OTC net-net screen
  `python3 graham/run.py --mode status`
  `python3 graham/run.py --mode test`
  `python3 graham/run.py --mode full`
- `/screen` — Run full universe fundamental screen (4000+ tickers)
  `python3 -m agents.fundamental_batch --universe data/state/us_universe.json --resume`
- `/screen-sp500` — Run S&P 500 only screen
  `python3 -m agents.fundamental_batch --resume`
- `/gauntlet TICKER` — Run a ticker through full CRO gauntlet (fundamental → sector desk → CRO → CIO)
  `python3 -m agents.gauntlet --ticker TICKER`
- `/cycle` — Run one full agent execution cycle (news → prices → desks → superinvestors → adversarial → CIO)
  `python3 -m agents.execution_loop --once`
- `/briefing` — Generate morning briefing
  `python3 -m agents.daily_briefing --save`
- `/pnl` — Update all prices and show current P&L
  `python3 -m agents.update_prices`

### Portfolio Management
- `/positions` — Show current portfolio with live P&L
- `/trade BUY/SELL TICKER SHARES PRICE` — Execute a paper trade (updates positions.json + decisions.json + trade journal)
  `python3 -m agents.execute_trade BUY TICKER SHARES PRICE --agent manual --thesis "Reason"`
- `/journal TICKER` — Show trade journal for a position
- `/watchlist` — Show current watchlist with agent views
- `/stress` — Run portfolio stress test scenarios
  `python3 -m agents.stress_test`

### System Operations
- `/deploy` — Push to GitHub and deploy to Azure
  `git add -A && git commit -m "update" && git push && ssh azureuser@51.104.239.35 "cd ~/atlas && git pull && sudo systemctl restart atlas && sudo systemctl restart atlas-loop"`
- `/status` — Check all services on Azure
  `ssh azureuser@51.104.239.35 "sudo systemctl status atlas && sudo systemctl status atlas-loop"`
- `/logs` — Check execution loop logs
  `ssh azureuser@51.104.239.35 "tail -50 /var/log/atlas_loop.log"`
- `/test` — Run full system audit
  `python3 -m tests.full_audit`

## Investment Philosophy
- Multi-agent swarm with structured debate
- Every trade goes through: Fundamental → Sector Desk → CRO → CIO
- Adversarial agent challenges every position
- Autonomous execution only when: CIO confidence > 80% AND adversarial risk < 0.6
- Position limits: 15% max single name, 50% min cash during first 6 months
- Stop losses on every position

## Agent Hierarchy

### Active Traders (make trade recommendations)
- Druckenmiller Macro — top-down macro, rates, currencies. Owns: TLT short
- Aschenbrenner AI Infra — AI power/compute bottleneck thesis. Owns: BE
- Baker Deep Tech — deep semiconductor/AI hardware knowledge
- Ackman Quality Compounder — concentrated quality with macro hedges
- Fundamental Valuation — DCF/comps screening. Owns: AVGO, ADBE, GOOG, APO, CRM, UNH, STX

### Sector Desks (generate signals, don't trade directly)
- Bond Desk — rates, credit spreads, Fed policy
- Currency Desk — G10 and EM FX
- Commodities Desk — energy, agriculture
- Metals Desk — precious and industrial metals
- Semiconductor Desk — chip cycle, AI demand
- Biotech Desk — FDA catalysts, pipeline
- Microcap Desk — sub-$500M discovery

### Risk & Decision Layer
- News Agent — RSS scanning, urgency scoring
- Adversarial/CRO — attacks every thesis, historical analogues
- CIO — synthesises all views, final decision maker

## File Structure
```
atlas/
├── CLAUDE.md              # This file — read first every session
├── SYSTEM.md              # Detailed technical documentation
├── api/atlas_api.py       # Flask app, all routes
├── agents/
│   ├── execution_loop.py  # Autonomous 30-min cycle
│   ├── daily_briefing.py  # Morning briefing generator
│   ├── fundamental_batch.py # Universe screening
│   ├── gauntlet.py        # CRO gauntlet runner
│   ├── update_prices.py   # P&L update skill
│   ├── execute_trade.py   # Trade execution skill
│   ├── stress_test.py     # Scenario stress testing
│   ├── chat_mixin.py      # Base class for agent chat
│   ├── news_agent.py      # RSS/news scanning
│   └── prompts/           # Agent system prompts
├── data/state/
│   ├── positions.json     # SOURCE OF TRUTH for portfolio
│   ├── decisions.json     # Trade log
│   ├── pnl_history.json   # Daily P&L snapshots
│   ├── agents.json        # Agent statuses
│   ├── desk_briefs.json   # Latest desk signals
│   ├── cio_synthesis.json # Latest CIO stance
│   ├── news_briefs.json   # Latest news alerts
│   ├── risk_assessment.json # Latest adversarial review
│   ├── agent_views.json   # Latest superinvestor views
│   ├── activity_timeline.json # Agent activity feed
│   ├── sp500_valuations.json  # S&P 500 screen results
│   └── gauntlet/          # CRO gauntlet results per ticker
├── data/trade_journal/
│   ├── open/              # Active position journals
│   └── closed/            # Closed position journals
├── data/evidence/         # LP-facing documentation
├── graham/                # OTC net-net screener and diligence engine
├── templates/             # Flask/Jinja2 HTML templates
└── config/settings.py     # Environment and path config
```

## Azure Deployment
- Dashboard: meetvalis.com/atlas (user: chris, pass: GICdemo2026!)
- VM: azureuser@51.104.239.35
- Services: atlas.service (dashboard), atlas-loop.service (agent loop)
- .env on Azure has API keys

## Current Portfolio (as of last update)
BIL 52.5% | BE 15% | TLT SHORT 10% | AVGO 5% | UNH 3.5% | CRM 3% | ADBE 3% | GOOG 3% | APO 3% | STX SHORT 2%

## Data Sources
- **Primary:** Finnhub free tier, 60 req/min, real-time quotes. Key in .env as FINNHUB_API_KEY
- **Secondary:** FMP (Financial Modeling Prep) free tier, 250 req/day, real-time quotes. Key in .env as FMP_API_KEY
- **Tertiary:** Massive/Polygon.io free tier, 5 req/min, end-of-day data. Key in .env as POLYGON_API_KEY
  - Note: Polygon.io rebranded to Massive.com — same API
  - Use as third price validator and for previous day close, corporate actions, technical indicators
- All market data functions in agents/market_data.py

## Alpaca MCP Server (Trade Execution)

Two Alpaca accounts configured via MCP for paper trading:

### Accounts
- **alpaca-atlas-a** — ATLAS-A account (uses ALPACA_A_KEY/ALPACA_A_SECRET from .env)
- **alpaca-atlas-b** — ATLAS-B account (uses ALPACA_B_KEY/ALPACA_B_SECRET from .env)

### Configuration
- Wrapper scripts: `scripts/alpaca-mcp-a.sh`, `scripts/alpaca-mcp-b.sh`
- API keys stored in `.env` as ALPACA_A_KEY, ALPACA_A_SECRET, ALPACA_B_KEY, ALPACA_B_SECRET
- Paper trading mode controlled by ALPACA_PAPER=true in .env

### MCP Tools Available
When API keys are configured, these tools become available in Claude Code:
- `get_account` — Get account info (buying power, equity, cash)
- `get_positions` — List all open positions
- `get_position` — Get specific position details
- `place_order` — Submit market/limit orders
- `cancel_order` — Cancel pending orders
- `get_orders` — List order history
- `get_watchlist` — Manage watchlists
- `get_bars` — Historical price data
- `get_quotes` — Real-time quotes

### Setup Status
1. API keys NOT yet filled in .env (waiting for account approval/funding)
2. ALPACA_PAPER=true (paper trading mode, DO NOT change until confirmed)
3. MCP servers registered in Claude Code user config

### To Activate
1. Fill in API keys in `~/Desktop/atlas/.env`:
   ```
   ALPACA_A_KEY=your_key_here
   ALPACA_A_SECRET=your_secret_here
   ALPACA_B_KEY=your_key_here
   ALPACA_B_SECRET=your_secret_here
   ```
2. Restart Claude Code session
3. Verify with `claude mcp list` — should show green checkmarks

### Commands
```bash
# Check MCP server status
claude mcp list

# Test connection (after keys filled)
# Just ask Claude: "Check my Alpaca account balance"
```

## Kalshi API (Prediction Markets)

Kalshi credentials for prediction market trading:

### Credentials
- **API Key ID:** `93378d93-8aa4-407a-962f-3405a784c054`
- **Private Key:** Stored in `.env` as `KALSHI_PRIVATE_KEY` (RSA PEM format)

### Setup
Add to `.env`:
```
KALSHI_API_KEY_ID=93378d93-8aa4-407a-962f-3405a784c054
KALSHI_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA39VvGnHdmntUtf6f7oKzDEfn2CiD38n1SZMmlQwhkXSnHvNF
6s53OtPpFQh2IPLN0LnR7AlEszjbMa0JvJacN+H0Xbhjxgkpbjj7v+iRk7Zz7H0D
+2qWrcoa3WRhh3UUPwz8gAfK5RQ/m7dn7FvzkQghjGqcyQAuKLfZfxpk0n+2Kmab
3J4efOetH7oX+mbRbjyZpBFcc4FK726Pn79FXYoVBwiX5TDJLr8ucWLexXnwHokF
TvLsuJkaco4YupFdZXzbtiA9kazvoJ1nj6WEHpt0f+x1KhmuQ1qJi4Sce2mfH1w9
74edFkWuci6yv3sMH+Bn09Q/fvyQu85Hpzt2UwIDAQABAoIBAFvIf94GqfmSMArO
xdL+OiBDjgC3oFfQTyoj0nLUviEQhgTteZKOphpz0cRjq1jYZ2f7Amb45/hbzJoC
nBb+ZUGPAG670QHgOOJvMGAhpCw/aSqkmtDqBK5vzPNSmaF7c1llYFa5m0uzMWAP
ZWhozif+/w6+mtrbHZJpzSBO+N/NZRXpPqhtptX/8aJP2HPhtbOqkDEjOQGY0uMM
NQzQ6NXOQrnV2XS7cmWjgL7n1TzLXnnjC2+IjKh9YTaUWCclD3jK5P4ZRlqLp2aG
SgesiK9Eq+Akn5J/1U2nyXyxKyyb3wUanz9jUqsivwNzbhSi913e/a/YZ5TKHhu1
thSzssECgYEA/D61lPv3wpt+8bmjucjdsrxQa92Hk+eu8JyNhacUePWIMsm1kZSK
l8j9UV0Rm0nPvbePGa+qp+zFZ/NarGLs11FlQQVatOKf9Z7oH6/r+gqqqvXKxH+f
sP8a0ookmTaUKuuHrT3/eCwcUR/Ryt9Ge/G8jYH/ERZDAnCraZ4qQEECgYEA4ypz
fz47PqmXy2U8J8+/n21k2im169eW2R4W1jTL4F73VonGgcg+5mvg9nLCMb6F2PCp
ZxICm3ICdrnFiYt1OvFSuumj1LuCwgn/sYdE+XRO4BSDP+7Hl0Z/Bih1jq5Prqep
aJfc74L+nVvxJCzrLcNDX8ltbaauRyPMwg2kUZMCgYB4jxREd8UsCxu6NqrNEfb8
BUs+squpAlO3hmuRlJCRW3DULVoNkXxIHXUNXTkcCkQy/bd0ZGRhTCXxj/snZ0Sh
iLKnSALZb3Nadq+k7XUQleaKPV3DWugdNWBBfmsNm2tntBitsXMXoaWLFHU1zE8o
0Bn5XEdniEdQtD8JBOJWwQKBgQC0FYkuDDWHPYbadUy0+tqcFmrnED3p0yUAxfuw
oHYnTuGhNuOpKwfCPy898EfGi5UsH80LqplqhX0yhZ71pRqwOXMuPd3k3SmRjb+o
CuZBI1UMCvbpje+oGvjD9vsKu2DrwnpoMkuxjBUwxhxqYzmlM7CLlPEtBgAO4XCH
Pa1QBQKBgHN+mJCttU16by0JU6ZpaPhiQRO4fm3mA2GXliB4AgYxSxJCt+3StBnB
poQ6g8xA8ElNzW+t0ShFxI9jyMopOPadsysTtqzYgODqp9MY7HXFOW+C8IDDgjOb
qBkUzxi948iJnzcCvfx0ZgOJuqKheYFn649Un5x8/V28otjs5Y/5
-----END RSA PRIVATE KEY-----"
```

### API Documentation
- Base URL: `https://trading-api.kalshi.com/trade-api/v2`
- Auth: RSA signature-based (sign timestamp + method + path with private key)
- Docs: https://trading-api.kalshi.com/docs

### Price Validation Rules
- NEVER use yfinance — it returns stale/incorrect prices
- Every price must be cross-validated from multiple sources
- Three-source validation logic:
  - FMP + Finnhub agree within 3% → "verified", use FMP price
  - FMP + Finnhub disagree → fetch Polygon prev close as tiebreaker → use whichever is closest to Polygon
  - Any source returns $0 or null → ignore it, use the others
  - All three disagree → flag "unverified", log all three prices, use Finnhub
- Data quality flags: "verified" (FMP/Finnhub agree), "tiebreaker" (Polygon resolved conflict), "unverified" (all disagree), "single_source"
- DON'T use Polygon for batch quotes (5/min rate limit) — only for tiebreaker conflicts
- Log warnings when conflicts occur

## Personal Shortcuts
- **"open default Chrome"** — Open Chrome with Chris's personal profile (has passwords, saved tabs):
  `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --profile-directory="Default" --new-window &`

## Rules
1. ALWAYS read this file at the start of every session
2. ALWAYS read SYSTEM.md before making code changes
3. NEVER modify positions.json without also updating decisions.json and the trade journal
4. NEVER deploy without testing locally first
5. NEVER overwrite templates with a different design — the current dark theme is final
6. API keys are in .env — make sure dotenv loads it from the project root
7. NEVER use yfinance — use dual-source validation via agents/market_data.py

## Autonomous Mode

ATLAS runs fully autonomously. It trades, learns, and self-improves without human input. Adapted from Karpathy's autoresearch concept.

### The Daily Loop (4:30pm ET weekdays)
1. **MARKET DATA** — fetch from FMP + Finnhub + Polygon
2. **DEBATE** — 20 agents argue, CIO synthesises (weighted by agent performance)
3. **TRADE** — CIO decisions auto-executed if confidence >70%
4. **LEARN** — scorecards updated, P&L attributed to agents, weights adjusted
5. **IMPROVE** — worst agent's prompt modified, tested next cycle, kept or reverted
6. **REPEAT** — sleep until tomorrow

### Key Files
- `agents/autonomous_loop.py` — master loop
- `agents/autoresearch_program.md` — self-improvement rules (human-editable)
- `agents/prompts/*.md` — agent prompts (auto-modified by the system)
- `agents/scorecard.py` — tracks agent performance
- `data/state/agent_weights.json` — Darwinian weights (winners louder, losers quieter)
- `data/state/agent_scorecards.json` — per-agent performance data
- `data/state/autoresearch_results.tsv` — experiment log (untracked)

### Autonomous Rules
- Portfolio starts as 100% cash. Agents earn their way into positions.
- Only `agents/prompts/*.md` gets auto-modified. Everything else is fixed.
- One prompt experiment per cycle. Improvements kept, failures reverted.
- Position limits: 15% max single name, 15% min cash always
- **NEVER STOPS. NEVER ASKS.** Runs until manually killed.

### Autonomous Commands
```bash
# Start the loop (production)
python3 -m agents.autonomous_loop

# Test one cycle
python3 -m agents.autonomous_loop --once

# Check portfolio
cat data/state/positions.json

# Check agent weights
cat data/state/agent_weights.json

# Check agent scores
cat data/state/agent_scorecards.json

# Check experiments
cat data/state/autoresearch_results.tsv

# Stop the loop
Ctrl+C or kill process
```

### Dashboards
- Main: meetvalis.com/atlas
- Autonomous: meetvalis.com/atlas/autonomous

### Weight Evolution
Agents are weighted by Sharpe ratio (10-day rolling):
- Sharpe > 0 → weight × 1.1 (agent gets louder)
- Sharpe ≤ 0 → weight × 0.9 (agent gets quieter)
- Floor: 0.3 (triggers mandatory prompt rewrite)
- Ceiling: 2.5 (prevents over-concentration)

### Autoresearch Protocol
1. After 5 trading days of data, identify worst agent by Sharpe
2. Analyze that agent's losing recommendations
3. Call Claude API to suggest ONE targeted prompt modification
4. Apply the change, git commit
5. On the NEXT cycle, check if Sharpe improved:
   - YES → keep the commit (improvement survives)
   - NO → git reset HEAD~1 (revert to previous)
6. Log result to autoresearch_results.tsv

After 3 failed attempts on one agent, move to next worst.

## Darwin v3

Darwin v3 is the standalone prompt-evolution layer that sits alongside the live ATLAS loop and feeds JANUS with judge output instead of raw cohort accuracy.

### Entry Point
- `darwin_v3/runtime.py` — phase 9 runtime orchestrator

### Runtime Placement
- Runs inside `agents/execution_loop.py` as a non-blocking pass-through step
- Continues to preserve the existing v2 loop and decision flow

### Key Outputs
- `data/state/judge_daily.json`
- `data/state/janus_daily.json`
- `data/state/decisions_v2.json`
- `data/state/decisions_v3.json`

### Gene Pool
- `darwin_v3/gene_pool.db`
- Seeded from real `autoresearch/` git history
- PRISM/spawn seeding remains TODO unless commit `170aadb` is available

### Supporting Modules
- `darwin_v3/gene_pool.py`
- `darwin_v3/postmortem_engine.py`
- `darwin_v3/breeding.py`
- `darwin_v3/config.py`
- `darwin_v3/utils/`

## SHANNON — Unstructured Intelligence Layer

SHANNON is the reading-and-listening desk that sits upstream of SIMONS/JANUS, sourcing trade ideas from unstructured text and audio: SEC filings, earnings transcripts, news, and earnings call audio.

### What SHANNON Does
1. **Ingest** — Pulls data from SEC EDGAR (8-K, 10-Q, 10-K), FMP transcripts, Finnhub news
2. **Filter** — Haiku-powered catalyst detection (cheap, fast first-pass)
3. **Analyze** — Opus-powered thesis generation and adversarial contra analysis
4. **Audio** — Transcription + acoustic analysis for word/voice mismatch detection
5. **Output** — Markdown research memos + parquet queue for JANUS

### Directory Structure
```
SHANNON/
├── ingest/
│   ├── filings.py          # SEC EDGAR ingestion
│   ├── transcripts.py      # FMP earnings call transcripts
│   ├── news.py             # Finnhub company news
│   └── audio/              # Audio ingestion (earnings, podcasts, Fed)
├── processing/
│   ├── transcribe.py       # faster-whisper / OpenAI whisper
│   ├── acoustic.py         # Pitch, pause, speech rate analysis
│   └── diarize.py          # Speaker separation (pyannote)
├── scouts/
│   ├── catalyst.py         # Haiku catalyst filter
│   ├── thesis.py           # Opus thesis generation
│   ├── contra.py           # Opus red-team analysis
│   └── vocal.py            # Opus word/voice mismatch detection
├── memos/                  # Generated research memos
├── queue/
│   └── candidates.parquet  # Structured output for JANUS
├── cache/                  # Raw data cache
├── logs/                   # Logging + cost tracking
├── shannon.py              # Main orchestrator
├── janus_integration.py    # JANUS connector
└── README.md               # Desk documentation
```

### SHANNON Commands
```bash
# Run single ticker analysis
python3 -m SHANNON.shannon --ticker AAPL

# Run test universe (5 tickers)
python3 -m SHANNON.shannon --universe test --once

# Run full S&P 100 universe
python3 -m SHANNON.shannon --universe sp100 --once

# Check SHANNON output for JANUS
python3 -m SHANNON.janus_integration
```

### JANUS Integration
SHANNON candidates with conviction >= 7 are automatically included in JANUS blending:
- Weight: 0.15 (tunable in `SHANNON/janus_integration.py`)
- File: `data/state/recommendations_shannon.json`
- JANUS reads this alongside other cohort recommendations

### Cost Controls
- Daily cap: $50/day across all SHANNON LLM calls
- Haiku (catalyst): ~$0.0003/call
- Opus (thesis/contra/vocal): ~$0.03-0.05/call
- Cost log: `SHANNON/logs/daily_cost_YYYYMMDD.txt`

### Cron Schedule (for production)
```
# Pre-market (07:00 ET)
0 7 * * 1-5 cd ~/atlas && python3 -m SHANNON.shannon --universe sp100 --once

# Midday (12:30 ET)
30 12 * * 1-5 cd ~/atlas && python3 -m SHANNON.shannon --universe sp100 --once

# Post-close (17:00 ET)
0 17 * * 1-5 cd ~/atlas && python3 -m SHANNON.shannon --universe sp100 --once
```

## API Keys Reference

All API keys stored in `.env` at project root:

### Market Data APIs
```bash
# Financial Modeling Prep (primary market data, transcripts)
FMP_API_KEY=ZTvemA5AKSI3e7DnITVXs3RyLY46G2Wx

# Finnhub (price validation, company news)
FINNHUB_API_KEY=d6ml6rpr01qi0ajmm7t0d6ml6rpr01qi0ajmm7tg

# Polygon/Massive (tiebreaker, historical data)
POLYGON_API_KEY=Z50G_fKhrQmUWZ_9gCpN2XYeaNI99MYW
```

### AI/ML APIs
```bash
# Anthropic (Claude for all agents)
ANTHROPIC_API_KEY=sk-ant-api03-...  # Already configured

# OpenAI (whisper fallback for transcription)
OPENAI_API_KEY=  # Optional, leave blank to use local faster-whisper

# Hugging Face (pyannote diarization)
HUGGINGFACE_TOKEN=  # Optional, for speaker diarization
```

### Rate Limits
| API | Rate Limit | Notes |
|-----|------------|-------|
| FMP | 250/day (free) | Primary market data |
| Finnhub | 60/min (free) | Real-time quotes |
| Polygon | 5/min (free) | Tiebreaker only |
| SEC EDGAR | 10/sec | User-Agent required |
| Anthropic | Per model | See docs |

### SEC EDGAR User-Agent
Required for SEC requests: `Chris Adams chris@gic-fund.com`
