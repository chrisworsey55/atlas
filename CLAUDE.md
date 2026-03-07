# ATLAS AI Trading System — Control Center

## What This Is
ATLAS is an AI-native hedge fund with 20+ autonomous agents that source, analyse, debate, and execute trades. The system runs on Azure at meetvalis.com/atlas.

## Quick Commands (Skills)

### Trading Operations
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

## Rules
1. ALWAYS read this file at the start of every session
2. ALWAYS read SYSTEM.md before making code changes
3. NEVER modify positions.json without also updating decisions.json and the trade journal
4. NEVER deploy without testing locally first
5. NEVER overwrite templates with a different design — the current dark theme is final
6. API key is in .env — make sure dotenv loads it from the project root
