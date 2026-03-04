"""
Stock Universe and Tracked Funds for ATLAS
50 high-liquidity names across sectors for proof of concept.
16 top-performing hedge funds tracked via 13F.
"""

UNIVERSE = {
    # Technology (10)
    "AAPL": {"sector": "Technology", "name": "Apple Inc."},
    "MSFT": {"sector": "Technology", "name": "Microsoft Corp."},
    "NVDA": {"sector": "Technology", "name": "NVIDIA Corp."},
    "GOOGL": {"sector": "Technology", "name": "Alphabet Inc."},
    "META": {"sector": "Technology", "name": "Meta Platforms Inc."},
    "AMZN": {"sector": "Technology", "name": "Amazon.com Inc."},
    "TSM": {"sector": "Technology", "name": "Taiwan Semiconductor"},
    "AVGO": {"sector": "Technology", "name": "Broadcom Inc."},
    "CRM": {"sector": "Technology", "name": "Salesforce Inc."},
    "AMD": {"sector": "Technology", "name": "Advanced Micro Devices"},
    # Financials (7)
    "JPM": {"sector": "Financials", "name": "JPMorgan Chase & Co."},
    "V": {"sector": "Financials", "name": "Visa Inc."},
    "MA": {"sector": "Financials", "name": "Mastercard Inc."},
    "BAC": {"sector": "Financials", "name": "Bank of America Corp."},
    "GS": {"sector": "Financials", "name": "Goldman Sachs Group"},
    "MS": {"sector": "Financials", "name": "Morgan Stanley"},
    "BLK": {"sector": "Financials", "name": "BlackRock Inc."},
    # Healthcare (7)
    "UNH": {"sector": "Healthcare", "name": "UnitedHealth Group"},
    "JNJ": {"sector": "Healthcare", "name": "Johnson & Johnson"},
    "LLY": {"sector": "Healthcare", "name": "Eli Lilly & Co."},
    "PFE": {"sector": "Healthcare", "name": "Pfizer Inc."},
    "ABBV": {"sector": "Healthcare", "name": "AbbVie Inc."},
    "MRK": {"sector": "Healthcare", "name": "Merck & Co."},
    "TMO": {"sector": "Healthcare", "name": "Thermo Fisher Scientific"},
    # Consumer (8)
    "WMT": {"sector": "Consumer", "name": "Walmart Inc."},
    "COST": {"sector": "Consumer", "name": "Costco Wholesale Corp."},
    "PG": {"sector": "Consumer", "name": "Procter & Gamble Co."},
    "KO": {"sector": "Consumer", "name": "Coca-Cola Co."},
    "PEP": {"sector": "Consumer", "name": "PepsiCo Inc."},
    "MCD": {"sector": "Consumer", "name": "McDonald's Corp."},
    "NKE": {"sector": "Consumer", "name": "Nike Inc."},
    "SBUX": {"sector": "Consumer", "name": "Starbucks Corp."},
    # Industrials (6)
    "CAT": {"sector": "Industrials", "name": "Caterpillar Inc."},
    "GE": {"sector": "Industrials", "name": "GE Aerospace"},
    "HON": {"sector": "Industrials", "name": "Honeywell International"},
    "UPS": {"sector": "Industrials", "name": "United Parcel Service"},
    "BA": {"sector": "Industrials", "name": "Boeing Co."},
    "RTX": {"sector": "Industrials", "name": "RTX Corp."},
    # Energy (3)
    "XOM": {"sector": "Energy", "name": "Exxon Mobil Corp."},
    "CVX": {"sector": "Energy", "name": "Chevron Corp."},
    "COP": {"sector": "Energy", "name": "ConocoPhillips"},
    # Communications (3)
    "DIS": {"sector": "Communications", "name": "Walt Disney Co."},
    "NFLX": {"sector": "Communications", "name": "Netflix Inc."},
    "CMCSA": {"sector": "Communications", "name": "Comcast Corp."},
    # Real Estate / Utilities (2)
    "AMT": {"sector": "Real Estate", "name": "American Tower Corp."},
    "NEE": {"sector": "Utilities", "name": "NextEra Energy Inc."},
    # Materials (2)
    "LIN": {"sector": "Materials", "name": "Linde PLC"},
    "FCX": {"sector": "Materials", "name": "Freeport-McMoRan Inc."},
    # Additional Semiconductors (3)
    "INTC": {"sector": "Technology", "name": "Intel Corp."},
    "MU": {"sector": "Technology", "name": "Micron Technology"},
    "QCOM": {"sector": "Technology", "name": "Qualcomm Inc."},
}

# Semiconductor desk extended universe
SEMICONDUCTOR_UNIVERSE = [
    "NVDA", "AMD", "INTC", "AVGO", "QCOM", "MU", "TSM", "MRVL",
    "LRCX", "AMAT", "KLAC", "TXN", "ADI", "ON", "NXPI", "MCHP",
    "ASML", "ARM", "SMCI", "DELL",
]

# Biotech desk extended universe
BIOTECH_UNIVERSE = [
    "LLY", "PFE", "ABBV", "MRK", "JNJ", "TMO", "UNH",
    "AMGN", "GILD", "REGN", "VRTX", "BIIB", "MRNA", "BMY",
    "ISRG", "DXCM", "ILMN", "ZTS",
]

# Hedge funds to track via 13F filings
TRACKED_FUNDS = {
    "Duquesne (Druckenmiller)":    {"cik": "1536411", "style": "Macro/concentrated"},
    "Berkshire Hathaway (Buffett)": {"cik": "1067983", "style": "Value/concentrated"},
    "Pershing Square (Ackman)":     {"cik": "1336528", "style": "Activist/concentrated"},
    "Appaloosa (Tepper)":           {"cik": "1656456", "style": "Macro/event-driven"},
    "Soros Fund Management":        {"cik": "1029160", "style": "Macro"},
    "Bridgewater Associates":       {"cik": "1350694", "style": "Systematic macro"},
    "Renaissance Technologies":     {"cik": "1037389", "style": "Quant"},
    "Citadel Advisors":             {"cik": "1423053", "style": "Multi-strategy"},
    "Point72 (Cohen)":              {"cik": "1603466", "style": "Multi-strategy"},
    "Tiger Global":                 {"cik": "1167483", "style": "Tech/growth"},
    "Coatue Management":            {"cik": "1535392", "style": "Tech/growth"},
    "Lone Pine Capital":            {"cik": "1061165", "style": "Growth"},
    "Viking Global":                {"cik": "1103804", "style": "Growth"},
    "Third Point (Loeb)":           {"cik": "1040273", "style": "Event-driven"},
    "Baupost Group (Klarman)":      {"cik": "1061768", "style": "Deep value"},
    "Greenlight Capital (Einhorn)": {"cik": "1079114", "style": "Value/short"},
}

# CIK lookup populated dynamically from SEC tickers file
TICKER_TO_CIK = {}
