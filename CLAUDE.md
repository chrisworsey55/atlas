# ATLAS — AI Trading, Logic & Analysis System

An AI-native hedge fund built on Claude. Sector desk agents analyze SEC filings, 13F tracking monitors hedge fund flows, and a CIO agent synthesizes it all into portfolio decisions.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Test biotech desk on Eli Lilly
python3 -m agents.sector_desk --desk biotech --ticker LLY

# Test semiconductor desk on NVIDIA
python3 -m agents.sector_desk --desk semiconductor --ticker NVDA

# Pull Berkshire's 13F holdings
python3 -c "from data.thirteenf_client import ThirteenFClient; print(ThirteenFClient().get_fund_holdings('Berkshire Hathaway (Buffett)').nlargest(10, 'value')[['ticker', 'name', 'value']])"

# Run full test suite
python3 test_phase2.py
```

## What's Built (Phase 1 + 2)

### Data Layer (`data/`)
- **edgar_client.py** — SEC EDGAR API (filings, XBRL financials, no API key needed)
- **price_client.py** — yfinance for prices and market data
- **thirteenf_client.py** — 13F parsing via edgartools library

### Agents (`agents/`)
- **sector_desk.py** — Generic runner that pairs prompts with data and calls Claude
- **SemiconductorDesk** — 6-lens framework: cycle, AI demand, pricing, capex, inventory, competitive
- **BiotechDesk** — 6-lens framework: FDA catalysts, pipeline, patent cliff, cash runway, commercial, M&A
- **institutional_flow_agent.py** — Analyzes 13F holdings for consensus/crowding signals

### Prompts (`agents/prompts/`)
- **semiconductor_desk.py** — System prompt + user prompt builder for semis
- **biotech_desk.py** — System prompt + user prompt builder for pharma/biotech
- **institutional_flow.py** — System prompt for hedge fund flow analysis

### Database (`database/`)
- **models.py** — SQLAlchemy models (7 tables, all prefixed `atlas_`)
- **session.py** — Connection management
- **Alembic migrations** in `alembic/versions/`

### Config (`config/`)
- **settings.py** — API keys, model selection, portfolio parameters
- **universe.py** — 50 stocks, 16 tracked hedge funds

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         CIO AGENT                           │
│              (synthesizes briefs → portfolio)               │
└─────────────────────────────────────────────────────────────┘
                              ▲
           ┌──────────────────┼──────────────────┐
           ▼                  ▼                  ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│  SEMICONDUCTOR  │ │     BIOTECH     │ │ INSTITUTIONAL   │
│      DESK       │ │      DESK       │ │     FLOW        │
└─────────────────┘ └─────────────────┘ └─────────────────┘
           ▲                  ▲                  ▲
           └──────────────────┼──────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      DATA LAYER                             │
│         SEC EDGAR │ yfinance │ 13F Holdings                 │
└─────────────────────────────────────────────────────────────┘
```

## Key Design Decisions

1. **Same runner, different prompts** — `SectorDeskAgent` is generic; swap prompts to get specialist analysis
2. **Structured JSON output** — All desks output identical schema for CIO consumption
3. **No paid APIs for core data** — SEC EDGAR is free, yfinance is free
4. **PostgreSQL for persistence** — Briefs, theses, trades all stored for backtesting

## What Needs Building (Phase 3)

### CIO Agent (`agents/cio_agent.py`)
- Receives briefs from all desks
- Synthesizes into portfolio-level view
- Generates investment theses
- Decides position sizing

### Risk Manager (`agents/risk_manager.py`)
- Validates CIO decisions against rules
- Correlation checks
- Sector concentration limits
- Stop loss enforcement

### Portfolio Engine (`portfolio/`)
- Paper trading execution
- P&L tracking
- Daily snapshots
- Performance analytics

### Daily Scanner (`scanner.py`)
- Overnight batch: scan universe for new filings
- Run relevant desks on new data
- Generate morning briefing

## Environment Variables

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Optional (for database persistence)
ATLAS_DATABASE_URL=postgresql://user:pass@localhost:5432/atlas
```

## Universe

**Tracked Stocks (50):** AAPL, MSFT, NVDA, GOOGL, META, AMZN, TSM, AVGO, AMD, LLY, PFE, ABBV, MRK, JPM, V, MA, etc.

**Tracked Hedge Funds (16):**
- Duquesne (Druckenmiller)
- Berkshire (Buffett)
- Pershing Square (Ackman)
- Appaloosa (Tepper)
- Soros Fund Management
- Bridgewater Associates
- Renaissance Technologies
- Citadel Advisors
- Point72 (Cohen)
- Tiger Global
- Coatue Management
- Lone Pine Capital
- Viking Global
- Third Point (Loeb)
- Baupost (Klarman)
- Greenlight (Einhorn)

## Output Examples

### Semiconductor Brief (NVDA)
```json
{
  "signal": "BULLISH",
  "confidence": 0.85,
  "cycle_position": {"phase": "MID", "assessment": "AI demand extending cycle"},
  "brief_for_cio": "Strong AI datacenter demand offsetting China risk..."
}
```

### Biotech Brief (LLY)
```json
{
  "signal": "BULLISH", 
  "confidence": 0.85,
  "fda_catalysts": {"next_event": "Tirzepatide obesity label expansion"},
  "brief_for_cio": "GLP-1 franchise driving exceptional growth..."
}
```

### Institutional Flow
```json
{
  "consensus_builds": [{"ticker": "AVGO", "funds": ["Druckenmiller", "Tepper"]}],
  "crowding_warnings": [{"ticker": "NVDA", "funds_holding": 14}],
  "contrarian_signals": [{"ticker": "PFE", "fund": "Baupost", "portfolio_pct": 8.2}]
}
```

## File Structure

```
atlas/
├── agents/
│   ├── prompts/
│   │   ├── semiconductor_desk.py
│   │   ├── biotech_desk.py
│   │   └── institutional_flow.py
│   ├── sector_desk.py
│   └── institutional_flow_agent.py
├── data/
│   ├── edgar_client.py
│   ├── price_client.py
│   └── thirteenf_client.py
├── database/
│   ├── models.py
│   └── session.py
├── config/
│   ├── settings.py
│   └── universe.py
├── alembic/
│   └── versions/001_initial_schema.py
├── requirements.txt
└── test_phase2.py
```

## Testing

```bash
# Full test suite
python3 test_phase2.py

# Individual desk
python3 -m agents.sector_desk --desk biotech --ticker MRK

# 13F data
python3 -m agents.institutional_flow_agent --test
```
