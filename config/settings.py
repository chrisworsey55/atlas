"""
ATLAS Configuration
AI Trading, Logic & Analysis System
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from parent directory (gic-underwriting)
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data_store"
DATA_DIR.mkdir(exist_ok=True)

# SEC EDGAR API (free, no key needed)
EDGAR_BASE_URL = "https://data.sec.gov"
EDGAR_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"
EDGAR_USER_AGENT = "General Intelligence Capital chris@generalintelligencecapital.com"
EDGAR_RATE_LIMIT = 10  # requests per second max

# Claude API for agent reasoning (reuse from VALIS .env)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-20250514"  # Cost-efficient for high-volume scanning
CLAUDE_MODEL_PREMIUM = "claude-sonnet-4-20250514"  # For CIO synthesis & adversarial review (using sonnet for now)

# PostgreSQL - new for ATLAS
DATABASE_URL = os.getenv("ATLAS_DATABASE_URL", "postgresql://atlas:atlas@localhost:5432/atlas")

# FMP API for analyst data (free tier available)
FMP_API_KEY = os.getenv("FMP_API_KEY", "")

# FRED API for macro data (free, requires key)
FRED_API_KEY = os.getenv("FRED_API_KEY", "")

# Paper Portfolio Settings
STARTING_CAPITAL = 1_000_000
MAX_POSITIONS = 20
MAX_SINGLE_POSITION_PCT = 0.10  # 10% of portfolio
MAX_SECTOR_CONCENTRATION_PCT = 0.30  # 30%
MIN_THESIS_CONFIDENCE = 0.70
STOP_LOSS_PCT = -0.08  # -8% per position
TAKE_PROFIT_PCT = 0.20  # +20% triggers reassessment
MIN_CASH_BUFFER_PCT = 0.10  # Always hold 10% cash
MAX_SHORT_PCT = 0.30  # Max 30% gross short
MAX_DRAWDOWN_PCT = -0.10  # Hard stop at -10% total portfolio

# Scanning intervals
FILING_SCAN_INTERVAL_HOURS = 6
FULL_RISK_REVIEW_INTERVAL_HOURS = 24
THIRTEENF_SCAN_INTERVAL_HOURS = 24  # 13Fs only update quarterly but check daily
ANALYST_SCAN_INTERVAL_HOURS = 12

# SMTP Configuration for email briefings
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
BRIEFING_FROM = os.getenv("BRIEFING_FROM", "atlas@generalintelligence.capital")
BRIEFING_TO = os.getenv("BRIEFING_TO", "chris@generalintelligencecapital.com")

# State directories
STATE_DIR = BASE_DIR / "data" / "state"
BRIEFINGS_DIR = STATE_DIR / "briefings"
STATE_DIR.mkdir(parents=True, exist_ok=True)
BRIEFINGS_DIR.mkdir(parents=True, exist_ok=True)
