# ATLAS System Documentation

**READ THIS FIRST before making any changes.**

ATLAS (AI Trading, Logic & Analysis System) is an AI-native hedge fund built on Claude. This document describes how the system works.

---

## Quick Start

```bash
# Start the dashboard (Flask)
cd ~/Desktop/atlas
python -m api.atlas_api

# Dashboard available at:
# http://localhost:8003/atlas          - Portfolio dashboard
# http://localhost:8003/atlas/agents   - Agent swarm view
# http://localhost:8003/atlas/decisions - CIO decisions
# http://localhost:8003/atlas/chat     - Chat interface
# http://localhost:8003/atlas/briefing - Daily briefing

# Alternative: FastAPI server (web/api.py) for chat-only API
# python -m web.api  # Runs on port 8003
```

---

## App Entry Points

### Primary: `api/atlas_api.py` (Flask)

The main dashboard server. Serves:
- HTML templates via Jinja2
- REST API endpoints
- Loads data from `data/state/*.json` files

```python
# Run with:
python -m api.atlas_api  # Port 8003
```

### Secondary: `web/api.py` (FastAPI)

A FastAPI server for agent chat. Simpler, chat-focused.

```python
# Run with:
uvicorn web.api:app --port 8003
```

### Analysis Scripts

| Script | Purpose |
|--------|---------|
| `run_gauntlet.py` | Runs stocks through 4-agent analysis (Fundamental → Sector → CRO → CIO) |
| `run_hedge_review.py` | CRO review of hedge positions (GLD, shorts) |
| `scanner.py` | Batch scanning of universe |

---

## Data Architecture

### State Directory: `data/state/`

All portfolio state and agent outputs are stored as JSON files:

```
data/state/
├── positions.json            # CURRENT PORTFOLIO - source of truth
├── portfolio_meta.json       # Inception date, hurdle rate, etc.
├── pnl_history.json          # Historical P&L snapshots
├── trades.json               # Trade log with signals
├── decisions.json            # CIO decisions
├── bond_desk_briefs.json     # Bond desk analysis
├── currency_desk_briefs.json # Currency desk analysis
├── commodities_desk_briefs.json
├── metals_desk_briefs.json
├── druckenmiller_briefs.json # Macro agent briefs
├── microcap_briefs.json      # Microcap discovery
├── fundamental_valuations.json
├── sp500_valuations.json     # Batch S&P 500 DCF/comps (~1.3MB local, ~3MB Azure)
├── consensus_briefs.json
├── filing_alerts.json        # SEC filing alerts
├── news_briefs.json          # News summaries
├── execution_log.json
├── insider_trades.json
├── gauntlet/                 # Gauntlet run outputs
│   ├── {TICKER}.json
│   └── gauntlet_summary.json
├── briefings/                # Daily briefing JSONs
│   └── {YYYY-MM-DD}.json
└── conversations/            # Chat history per agent
    └── {agent}_chat.json
```

### positions.json Structure

This is the **source of truth** for the portfolio:

```json
{
  "portfolio_value": 1000000,
  "last_updated": "2026-03-06",
  "positions": [
    {
      "ticker": "AVGO",
      "direction": "LONG",           // LONG or SHORT
      "shares": 47,
      "entry_price": 318.82,
      "current_price": 317.53,       // Updated by yfinance on API call
      "allocation_pct": 5.0,
      "thesis": "Most undervalued stock in S&P 500...",
      "agent_source": "fundamental", // Which agent opened this
      "conviction": 85,              // 0-100
      "stop_loss": 271.00,
      "target": 446.35,
      "invalidation": "ASIC demand slows...",
      "date_opened": "2026-02-20"
    }
  ]
}
```

**Position Types (inferred by `api/atlas_api.py`):**
- `ACTIVE_TRADE`: Agent-driven positions
- `AUTONOMOUS`: Auto-trading positions
- `CASH_MANAGEMENT`: BIL (T-Bill ETF) holdings

---

## Price Updates

### How Prices Get Updated

Prices are fetched **live via yfinance** when the dashboard loads:

**`api/atlas_api.py`** - `fetch_live_prices()` function:
```python
def fetch_live_prices(tickers: list) -> dict:
    """Fetch live prices from yfinance for a list of tickers."""
    tickers_to_fetch = [t for t in tickers if t and t != 'BIL']
    data = yf.download(tickers_to_fetch, period='1d', progress=False)
    # Returns dict mapping ticker -> price
```

**Called by:**
- `dashboard_portfolio()` in `api/atlas_api.py` - fetches live prices before rendering
- SPY price: `get_spy_current()` for dashboard header

**Important:** The `positions.json` file stores `current_price` but this is a snapshot. The dashboard always fetches LIVE prices from yfinance, ignoring the stored value.

### SPY Benchmark

SPY price is fetched live for the dashboard header:
- Endpoint: `/api/market/spy`
- Implementation: `get_spy_current()` in `api/atlas_api.py`

---

## Agent System

### Agent Types

| Agent | File | Purpose |
|-------|------|---------|
| **Druckenmiller** | `agents/druckenmiller_agent.py` | Macro-focused (rates, liquidity, Fed) |
| **Aschenbrenner** | `agents/aschenbrenner_agent.py` | AI infrastructure thesis |
| **Baker** | `agents/baker_agent.py` | Deep tech / biotech |
| **Ackman** | `agents/ackman_agent.py` | Quality compounders |
| **Fundamental** | `agents/fundamental_agent.py` | DCF/comps valuation |
| **Adversarial** | `agents/adversarial_agent.py` | Risk review / devil's advocate |
| **CIO** | `agents/cio_agent.py` | Final portfolio decisions |
| **News** | `agents/news_agent.py` | News monitoring |
| **Institutional Flow** | `agents/institutional_flow_agent.py` | 13F analysis |
| **Sector Desks** | `agents/sector_desk.py` | Semiconductor, Biotech, Financials, Energy, Consumer, Industrials |
| **Bond Desk** | `agents/bond_desk_agent.py` | Rates, credit, Fed policy |
| **Currency Desk** | `agents/currency_desk_agent.py` | FX analysis |
| **Commodities Desk** | `agents/commodities_desk_agent.py` | Energy, agriculture |
| **Metals Desk** | `agents/metals_desk_agent.py` | Gold, silver, precious metals |
| **Microcap** | `agents/microcap_agent.py` | Small cap discovery |
| **Autonomous** | `agents/autonomous_agent.py` | Auto-trading sleeve |
| **Consensus** | `agents/consensus_agent.py` | Analyst consensus tracking |
| **Earnings Call** | `agents/earnings_call_agent.py` | Transcript analysis |
| **Filing Monitor** | `agents/filing_monitor_agent.py` | SEC filing alerts |

### Agent Prompts

System prompts are in `agents/prompts/`:
```
agents/prompts/
├── druckenmiller_agent.py
├── bond_desk.py
├── currency_desk.py
├── commodities_desk.py
├── metals_desk.py
├── semiconductor_desk.py
├── biotech_desk.py
├── financials_desk.py
├── energy_desk.py
├── consumer_desk.py
├── industrials_desk.py
├── fundamental_agent.py
├── adversarial_agent.py
├── cio_agent.py
├── microcap_discovery.py
├── autonomous_agent.py
├── institutional_flow.py
├── news_agent.py
├── earnings_call_agent.py
├── consensus_agent.py
├── baker_agent.py
├── aschenbrenner_agent.py
├── ackman_agent.py
└── alpha_discovery_agent.py
```

### Agent Loading (Chat Router)

The chat router (`api/chat_router.py`) lazy-loads agents:

```python
def _get_agent(self, agent_key: str):
    if agent_key == 'druckenmiller':
        from agents.druckenmiller_agent import DruckenmillerAgent
        self.agents[agent_key] = DruckenmillerAgent()
    elif agent_key == 'bond':
        from agents.bond_desk_agent import BondDeskAgent
        self.agents[agent_key] = BondDeskAgent()
    # ... etc
```

### Chat Mixin

All agents inherit `ChatMixin` from `agents/chat_mixin.py`:
- Provides `chat()` method for conversational interface
- Loads portfolio state and valuations for context
- Persists conversation history to `data/state/conversations/`

---

## API Endpoints

### Flask API (`api/atlas_api.py`)

#### HTML Routes
| Route | Template | Description |
|-------|----------|-------------|
| `/atlas` | `portfolio.html` | Main dashboard |
| `/atlas/agents` | `agents.html` | Agent swarm status |
| `/atlas/decisions` | `decisions.html` | Trade decisions |
| `/atlas/chat` | `chat.html` | Chat interface |
| `/atlas/briefing` | `briefing.html` | Daily briefing |
| `/atlas/company/<ticker>` | `company.html` | Company deep dive |

#### JSON API Routes
| Route | Method | Description |
|-------|--------|-------------|
| `/api/portfolio/summary` | GET | Portfolio summary stats (DB) |
| `/api/portfolio/chart` | GET | Equity curve data (DB) |
| `/api/portfolio/positions` | GET | Open positions (DB) |
| `/api/briefs` | GET | Recent desk briefs (DB) |
| `/api/trades` | GET | Trade decisions (DB) |
| `/api/holdings` | GET | Institutional holdings (DB) |
| `/api/company/<ticker>` | GET | Company deep dive (DB) |
| `/api/chat` | POST | Chat with agents (DB-backed) |
| `/api/market/spy` | GET | SPY price (yfinance) |
| `/api/health` | GET | Health check |

#### JSON State API Routes (File-backed)
| Route | Method | Description |
|-------|--------|-------------|
| `/api/atlas/portfolio` | GET | Portfolio from positions.json |
| `/api/atlas/positions` | GET | Positions with filter |
| `/api/atlas/pnl` | GET | P&L history |
| `/api/atlas/hurdle` | GET | Hurdle rate tracking |
| `/api/atlas/desks` | GET | All desk briefs summary |
| `/api/atlas/desks/<desk_name>` | GET | Specific desk briefs |
| `/api/atlas/macro` | GET | Macro environment |
| `/api/atlas/autonomous` | GET | Autonomous sleeve |
| `/api/atlas/microcap` | GET | Microcap briefs |
| `/api/atlas/valuations` | GET | Fundamental valuations |
| `/api/atlas/trades` | GET | Trades from trades.json |
| `/api/atlas/agents` | GET | Agent statuses |
| `/api/atlas/briefing/latest` | GET | Latest briefing JSON |
| `/api/atlas/briefing/<date>` | GET | Briefing by date |
| `/api/atlas/briefing/list` | GET | Available briefing dates |
| `/api/atlas/briefing/generate` | POST | Trigger briefing generation |

#### Chat Endpoints (via `api/chat_endpoints.py` blueprint)
| Route | Method | Description |
|-------|--------|-------------|
| `/api/atlas/chat` | POST | CIO unified chat |
| `/api/atlas/chat/<agent>` | POST | Direct agent chat |
| `/api/atlas/chat/<agent>/history` | GET | Get conversation history |
| `/api/atlas/chat/<agent>/history` | DELETE | Clear conversation |
| `/api/atlas/agents/status` | GET | All agent statuses |
| `/api/atlas/chat/debate` | POST | Agent debate mode |
| `/api/atlas/chat/whatif` | POST | What-if scenarios |
| `/api/atlas/chat/cross-examine/<agent>` | POST | Cross-examination mode |

---

## Templates

All templates are in `templates/` and extend `base.html`.

### base.html
- Tailwind CSS via CDN
- Chart.js for visualizations
- Navigation bar (Portfolio, Agents, Decisions, Chat, Briefing)
- SPY price indicator (fetches from `/api/market/spy`)
- Mobile-responsive navigation

### Template Variables

**portfolio.html expects:**
```python
render_template('portfolio.html',
    active_page='portfolio',
    positions=[...],      # List of position dicts with computed P&L
    meta={...},           # Portfolio metadata
    pnl_history=[...],    # Historical snapshots
    summary={...},        # Computed totals
    hurdle={...}          # Hurdle/alpha tracking
)
```

**agents.html expects:**
```python
render_template('agents.html',
    active_page='agents',
    agents={...},         # Dict of agent statuses
    counts={...},         # Agent counts by status
    desks={...}           # Desk brief summaries
)
```

**decisions.html expects:**
```python
render_template('decisions.html',
    active_page='decisions',
    trades=[...],         # Trade list with P&L
    trades_summary={...}  # Summary stats
)
```

---

## Database (PostgreSQL)

### Connection
```python
DATABASE_URL = os.getenv("ATLAS_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/valis")
```

### Tables (prefixed `atlas_`)
| Table | Purpose |
|-------|---------|
| `atlas_portfolio_snapshots` | Daily portfolio values |
| `atlas_trades` | Trade history |
| `atlas_theses` | Investment theses |
| `atlas_companies` | Company info |
| `atlas_desk_briefs` | Agent analysis |
| `atlas_institutional_holdings` | 13F holdings |

### Migrations
```bash
alembic upgrade head  # Run migrations
```

---

## Azure vs Local

**Azure VM:** `azureuser@51.104.239.35`

### Azure has additional files:
```
data/state/
├── full_universe_progress.json   # Larger universe scan progress
├── full_universe_valuations.json # Full universe valuations (~12MB)
├── us_tickers.txt                # US ticker list
├── us_universe.json              # US universe data
└── sp500_valuations.json         # Larger (~3MB vs 1.3MB local)
```

### Azure briefings are generated:
```
data/state/briefings/
└── {YYYY-MM-DD}.json
```

### Sync state from Azure:
```bash
scp -r azureuser@51.104.239.35:~/atlas/data/state/* ~/Desktop/atlas/data/state/
```

---

## Configuration

### config/settings.py

```python
# API Keys
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
FRED_API_KEY = os.getenv("FRED_API_KEY")
FMP_API_KEY = os.getenv("FMP_API_KEY")

# Models
CLAUDE_MODEL = "claude-sonnet-4-20250514"
CLAUDE_MODEL_PREMIUM = "claude-sonnet-4-20250514"

# Portfolio Rules
STARTING_CAPITAL = 1_000_000
MAX_POSITIONS = 20
MAX_SINGLE_POSITION_PCT = 0.10
MAX_SECTOR_CONCENTRATION_PCT = 0.30
MIN_THESIS_CONFIDENCE = 0.70
STOP_LOSS_PCT = -0.08
MIN_CASH_BUFFER_PCT = 0.10

# State Directories
STATE_DIR = BASE_DIR / "data" / "state"
BRIEFINGS_DIR = STATE_DIR / "briefings"
```

### Environment Variables
```bash
ANTHROPIC_API_KEY=sk-ant-...
ATLAS_DATABASE_URL=postgresql://...
FRED_API_KEY=...
FMP_API_KEY=...
SMTP_HOST=smtp.gmail.com
SMTP_USER=...
SMTP_PASS=...
```

---

## Data Clients

| Client | File | Data Source |
|--------|------|-------------|
| EDGAR | `data/edgar_client.py` | SEC filings (free) |
| Prices | yfinance | Stock prices (free) |
| 13F | `data/thirteenf_client.py` | edgartools library |
| FRED | `data/macro_client.py` | Federal Reserve data |
| Options | `data/options_client.py` | Options data |
| Technical | `data/technical_client.py` | Technical indicators |
| Earnings | `data/earnings_client.py` | Earnings data |
| Events | `data/events_client.py` | Corporate events |
| Consensus | `data/consensus_client.py` | Analyst estimates |
| Short Interest | `data/short_interest_client.py` | Short data |

---

## Run the Gauntlet

The gauntlet (`run_gauntlet.py`) runs stocks through 4 agents:

```
Fundamental Agent → Sector Desk → CRO (Adversarial) → CIO
```

**Output:** `data/state/gauntlet/{TICKER}.json`

```bash
python run_gauntlet.py  # Runs default tickers
```

---

## Common Issues

### 1. Prices not updating
- Prices are fetched on-demand via yfinance
- Check network connectivity
- BIL is excluded from price updates (cash equivalent)

### 2. Database tables don't exist
- Run `alembic upgrade head`
- Check DATABASE_URL environment variable

### 3. Agents not loading
- Check `ANTHROPIC_API_KEY` is set
- Agents are lazy-loaded on first use

### 4. Template errors
- Templates expect specific variable structures
- Check the `render_template()` calls in `api/atlas_api.py`

### 5. Azure sync
```bash
# Check Azure state
ssh azureuser@51.104.239.35 "ls -la ~/atlas/data/state/"

# Sync positions
scp azureuser@51.104.239.35:~/atlas/data/state/positions.json ~/Desktop/atlas/data/state/
```

---

## File Index

```
atlas/
├── SYSTEM.md                    # THIS FILE
├── CLAUDE.md                    # Original development notes
├── requirements.txt
├── alembic.ini
├── api/
│   ├── atlas_api.py             # Main Flask server
│   ├── chat_api.py              # Standalone chat API
│   ├── chat_endpoints.py        # Chat blueprint
│   └── chat_router.py           # Agent routing logic
├── web/
│   ├── api.py                   # FastAPI server
│   └── static/index.html
├── agents/
│   ├── chat_mixin.py            # Chat capability for agents
│   ├── druckenmiller_agent.py
│   ├── cio_agent.py
│   ├── adversarial_agent.py
│   ├── fundamental_agent.py
│   ├── sector_desk.py
│   ├── bond_desk_agent.py
│   ├── [... all other agents]
│   └── prompts/                 # Agent system prompts
├── config/
│   ├── settings.py              # Configuration
│   └── universe.py              # Tracked stocks/funds
├── data/
│   ├── state/                   # JSON state files
│   │   ├── positions.json       # PORTFOLIO SOURCE OF TRUTH
│   │   ├── [... all state files]
│   │   └── conversations/
│   ├── edgar_client.py
│   ├── thirteenf_client.py
│   └── [... all data clients]
├── database/
│   ├── models.py                # SQLAlchemy models
│   └── session.py
├── templates/
│   ├── base.html
│   ├── portfolio.html
│   ├── agents.html
│   ├── decisions.html
│   ├── chat.html
│   ├── briefing.html
│   └── company.html
├── portfolio/
│   ├── paper_portfolio.py
│   ├── performance.py
│   └── risk_manager.py
├── scripts/
│   ├── build_universe.py
│   └── build_universe_v2.py
├── run_gauntlet.py              # 4-agent analysis pipeline
├── run_hedge_review.py          # CRO hedge review
├── scanner.py                   # Universe scanning
└── alembic/
    └── versions/
        └── 001_initial_schema.py
```

---

**Last updated:** 2026-03-06
