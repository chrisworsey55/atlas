#!/bin/bash
# ATLAS Autonomous Mode Startup Script
# This script initializes and starts the autonomous trading system

set -e

ATLAS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ATLAS_DIR"

echo "=============================================="
echo "ATLAS AUTONOMOUS MODE STARTUP"
echo "=============================================="
echo "Directory: $ATLAS_DIR"
echo ""

# Check for required environment variables
if [ ! -f .env ]; then
    echo "ERROR: .env file not found"
    exit 1
fi

source .env

if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "ERROR: ANTHROPIC_API_KEY not set in .env"
    exit 1
fi

echo "[1/5] Checking dependencies..."
python3 -c "import anthropic; import pytz" 2>/dev/null || {
    echo "Installing dependencies..."
    pip3 install anthropic pytz
}

echo "[2/5] Initializing directories..."
mkdir -p logs data/trade_journal data/state

echo "[3/5] Initializing portfolio (100% cash)..."
if [ ! -f data/state/positions.json ] || [ "$1" == "--reset" ]; then
    cat > data/state/positions.json << 'EOF'
{
  "portfolio_value": 1000000,
  "starting_value": 1000000,
  "last_updated": "2026-03-09 12:30",
  "mode": "AUTONOMOUS",
  "execution_status": "LIVE",
  "positions": [
    {
      "ticker": "BIL",
      "direction": "LONG",
      "shares": 10941,
      "entry_price": 91.39,
      "current_price": 91.39,
      "allocation_pct": 100,
      "thesis": "Cash equivalent - dry powder for agent-identified opportunities",
      "agent_source": "system",
      "conviction": 100,
      "stop_loss": null,
      "target": null,
      "date_opened": "2026-03-09",
      "status": "OPEN",
      "category": "CASH"
    }
  ]
}
EOF
    echo "  Portfolio initialized: \$1,000,000 in BIL"
else
    echo "  Portfolio already exists - skipping (use --reset to reinitialize)"
fi

echo "[4/5] Initializing agent weights..."
if [ ! -f data/state/agent_weights.json ] || [ "$1" == "--reset" ]; then
    cat > data/state/agent_weights.json << 'EOF'
{
  "news": 1.0,
  "flow": 1.0,
  "bond": 1.0,
  "currency": 1.0,
  "commodities": 1.0,
  "metals": 1.0,
  "semiconductor": 1.0,
  "biotech": 1.0,
  "energy": 1.0,
  "consumer": 1.0,
  "industrials": 1.0,
  "financials": 1.0,
  "microcap": 1.0,
  "druckenmiller": 1.0,
  "aschenbrenner": 1.0,
  "baker": 1.0,
  "ackman": 1.0,
  "cro": 1.0,
  "alpha": 1.0,
  "autonomous": 1.0,
  "cio": 1.0,
  "initialized": "2026-03-09"
}
EOF
    echo "  Agent weights initialized (all at 1.0)"
fi

echo "[5/5] Initializing autoresearch log..."
if [ ! -f data/state/autoresearch_results.tsv ]; then
    echo -e "date\tagent\tcommit\tsharpe_10d\tweight\tstatus\tdescription" > data/state/autoresearch_results.tsv
    echo "  Autoresearch log initialized"
fi

echo ""
echo "=============================================="
echo "ATLAS AUTONOMOUS MODE READY"
echo "=============================================="
echo ""
echo "Commands:"
echo "  Test one cycle:  python3 -m agents.autonomous_loop --once"
echo "  Start loop:      python3 -m agents.autonomous_loop"
echo "  Check portfolio: cat data/state/positions.json"
echo "  Check weights:   cat data/state/agent_weights.json"
echo "  Check scores:    cat data/state/agent_scorecards.json"
echo ""
echo "Dashboard: meetvalis.com/atlas/autonomous"
echo ""

# If --start flag is passed, start the loop
if [ "$1" == "--start" ]; then
    echo "Starting autonomous loop..."
    python3 -m agents.autonomous_loop
fi
