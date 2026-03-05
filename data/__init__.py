"""
ATLAS Data Layer
AI Trading, Logic & Analysis System

All data clients for market intelligence:

TIER 1 - FREE, BUILD NOW:
- EdgarClient: SEC EDGAR API for filings and XBRL financials
- EDGARRealtimeClient: Real-time EDGAR feed and RSS monitoring
- EarningsClient: Earnings dates, estimates, surprises
- NewsSentimentClient: News with AI sentiment scoring
- OptionsClient: Options chains, unusual activity, max pain
- ShortInterestClient: Short interest, squeeze candidates
- TechnicalClient: Technical indicators (RSI, MACD, etc.)
- EconCalendarClient: Economic calendar and releases
- CongressionalClient: Congressional stock trades
- SocialSentimentClient: Reddit, StockTwits, WSB activity
- ETFFlowClient: Sector ETF flows and rotation signals
- MacroClient: FRED macro data for Druckenmiller-style analysis

TIER 2 - PAID (stubs ready):
- premium_data_stubs: Credit card, satellite, foot traffic, etc.
"""

from .edgar_client import EdgarClient
from .price_client import PriceClient
from .insider_client import InsiderClient
from .events_client import EventsClient
from .macro_client import MacroClient

# New data intelligence clients
from .edgar_realtime_client import EDGARRealtimeClient
from .earnings_client import EarningsClient
from .news_sentiment_client import NewsSentimentClient
from .options_client import OptionsClient
from .short_interest_client import ShortInterestClient
from .technical_client import TechnicalClient
from .econ_calendar_client import EconCalendarClient
from .congressional_client import CongressionalClient
from .social_sentiment_client import SocialSentimentClient
from .etf_flow_client import ETFFlowClient

# Premium data stubs (for when AUM hits $50M)
from .premium_data_stubs import (
    get_premium_clients,
    get_premium_status,
    CreditCardDataClient,
    WebTrafficClient,
    AppDataClient,
    SatelliteDataClient,
    FootTrafficClient,
    JobPostingClient,
    PatentDataClient,
    SupplyChainClient,
    ExpertNetworkClient,
)

__all__ = [
    # Core data clients
    "EdgarClient",
    "PriceClient",
    "InsiderClient",
    "EventsClient",
    "MacroClient",

    # Real-time data intelligence
    "EDGARRealtimeClient",
    "EarningsClient",
    "NewsSentimentClient",
    "OptionsClient",
    "ShortInterestClient",
    "TechnicalClient",
    "EconCalendarClient",
    "CongressionalClient",
    "SocialSentimentClient",
    "ETFFlowClient",

    # Premium data
    "get_premium_clients",
    "get_premium_status",
    "CreditCardDataClient",
    "WebTrafficClient",
    "AppDataClient",
    "SatelliteDataClient",
    "FootTrafficClient",
    "JobPostingClient",
    "PatentDataClient",
    "SupplyChainClient",
    "ExpertNetworkClient",
]
