# ATLAS Agent Swarm Overview

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         CIO AGENT                           │
│              (synthesises briefs → portfolio decisions)     │
└─────────────────────────────────────────────────────────────┘
                              ▲
    ┌─────────────────────────┼─────────────────────────┐
    │                         │                         │
    ▼                         ▼                         ▼
┌─────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  SECTOR     │     │   SPECIALIST    │     │   ADVERSARIAL   │
│  DESKS      │     │   AGENTS        │     │   REVIEW        │
└─────────────┘     └─────────────────┘     └─────────────────┘
    │                         │                         │
    ├── Semiconductor         ├── Aschenbrenner         └── CRO
    ├── Biotech              ├── Druckenmiller
    ├── Financials           ├── Fundamental
    ├── Energy               └── 13F Institutional
    ├── Consumer
    └── Industrials
                              ▲
                              │
┌─────────────────────────────────────────────────────────────┐
│                      DATA LAYER                             │
│         SEC EDGAR │ yfinance │ 13F Holdings                 │
└─────────────────────────────────────────────────────────────┘
```

## Agent Types

### Sector Desks
Analyse companies through sector-specific frameworks:
- **Semiconductor:** Cycle position, AI demand, pricing power, inventory
- **Biotech:** FDA catalysts, pipeline, patent cliff, cash runway
- **Financials:** NIM, credit quality, capital ratios, loan growth
- **Energy:** Supply/demand, reserves, capex discipline, commodity prices
- **Consumer:** Same-store sales, pricing power, brand strength
- **Industrials:** Backlog, capacity utilisation, input costs

### Specialist Agents
Replicate specific investment approaches:
- **Aschenbrenner:** AI infrastructure thesis (power, compute, data)
- **Druckenmiller:** Macro positioning (rates, currencies, cycles)
- **Fundamental:** DCF/comps valuation across all sectors
- **13F Institutional:** Track hedge fund positioning changes

### Adversarial Agents
Challenge every investment thesis:
- **CRO:** 25 years experience, finds every way to lose money

### Decision Agent
Synthesises all inputs into portfolio decisions:
- **CIO:** Position sizing, correlation management, risk budgeting

## Data Flow

1. **Data Collection**
   - SEC EDGAR: Filings, XBRL financials
   - yfinance: Prices, market data, company info
   - 13F: Institutional holdings

2. **Analysis**
   - Relevant sector desk analyses company
   - Specialist agents provide thesis
   - Fundamental agent provides valuation

3. **Risk Review**
   - CRO steelmans thesis
   - Identifies specific loss scenarios
   - Historical analogue comparison
   - APPROVE / CONDITIONAL / BLOCK

4. **Execution**
   - CIO sizes position given constraints
   - Documents thesis, stops, targets
   - Updates positions.json

5. **Memory**
   - Trade journal updated
   - Evidence base documented
   - Future decisions reference past outcomes

## Key Design Principles

### 1. Structured Output
All agents return JSON with required fields:
- signal (BULLISH/BEARISH/NEUTRAL)
- confidence (0-100)
- brief_for_cio (one paragraph)
- key_risks (array)
- key_catalysts (array)

### 2. Adversarial by Default
Every trade thesis gets challenged. No confirmation bias.

### 3. Documented Decisions
Every trade has:
- Entry thesis
- Agent views
- Key levels
- Invalidation criteria
- Performance log

### 4. Memory System
Trade journal serves as AI memory:
- Open positions: current status
- Closed positions: lessons learned
- Agents read journal before new decisions

## Files

- Sector desk: `agents/sector_desk.py`
- Agent prompts: `agents/prompts/`
- CRO gauntlet: `agents/cro_gauntlet.py`
- Trade journal: `data/trade_journal/`
