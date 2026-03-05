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

# Macro ETFs for the Autonomous Agent
# These provide exposure to asset classes beyond individual stocks
MACRO_ETFS = {
    # Equity Indices
    "SPY":  {"sector": "Index", "name": "SPDR S&P 500 ETF", "asset_class": "equity"},
    "QQQ":  {"sector": "Index", "name": "Invesco QQQ Trust (Nasdaq 100)", "asset_class": "equity"},
    "IWM":  {"sector": "Index", "name": "iShares Russell 2000 ETF", "asset_class": "equity"},
    "DIA":  {"sector": "Index", "name": "SPDR Dow Jones Industrial Average ETF", "asset_class": "equity"},

    # International
    "EEM":  {"sector": "International", "name": "iShares MSCI Emerging Markets ETF", "asset_class": "equity"},
    "EFA":  {"sector": "International", "name": "iShares MSCI EAFE ETF", "asset_class": "equity"},
    "FXI":  {"sector": "International", "name": "iShares China Large-Cap ETF", "asset_class": "equity"},
    "EWJ":  {"sector": "International", "name": "iShares MSCI Japan ETF", "asset_class": "equity"},
    "EWZ":  {"sector": "International", "name": "iShares MSCI Brazil ETF", "asset_class": "equity"},

    # Fixed Income
    "TLT":  {"sector": "Fixed Income", "name": "iShares 20+ Year Treasury Bond ETF", "asset_class": "bonds"},
    "IEF":  {"sector": "Fixed Income", "name": "iShares 7-10 Year Treasury Bond ETF", "asset_class": "bonds"},
    "SHY":  {"sector": "Fixed Income", "name": "iShares 1-3 Year Treasury Bond ETF", "asset_class": "bonds"},
    "TIP":  {"sector": "Fixed Income", "name": "iShares TIPS Bond ETF", "asset_class": "bonds"},
    "HYG":  {"sector": "Fixed Income", "name": "iShares iBoxx High Yield Corporate Bond ETF", "asset_class": "bonds"},
    "LQD":  {"sector": "Fixed Income", "name": "iShares iBoxx Investment Grade Corporate Bond ETF", "asset_class": "bonds"},

    # Commodities
    "GLD":  {"sector": "Commodities", "name": "SPDR Gold Shares", "asset_class": "commodity"},
    "SLV":  {"sector": "Commodities", "name": "iShares Silver Trust", "asset_class": "commodity"},
    "USO":  {"sector": "Commodities", "name": "United States Oil Fund", "asset_class": "commodity"},
    "UNG":  {"sector": "Commodities", "name": "United States Natural Gas Fund", "asset_class": "commodity"},
    "DBA":  {"sector": "Commodities", "name": "Invesco DB Agriculture Fund", "asset_class": "commodity"},

    # Currency
    "UUP":  {"sector": "Currency", "name": "Invesco DB US Dollar Index Bullish Fund", "asset_class": "currency"},
    "FXE":  {"sector": "Currency", "name": "Invesco CurrencyShares Euro Trust", "asset_class": "currency"},
    "FXY":  {"sector": "Currency", "name": "Invesco CurrencyShares Japanese Yen Trust", "asset_class": "currency"},

    # Volatility
    "VXX":  {"sector": "Volatility", "name": "iPath Series B S&P 500 VIX Short-Term Futures ETN", "asset_class": "volatility"},
    "SVXY": {"sector": "Volatility", "name": "ProShares Short VIX Short-Term Futures ETF", "asset_class": "volatility"},

    # Sector ETFs
    "XLF":  {"sector": "Financials", "name": "Financial Select Sector SPDR Fund", "asset_class": "equity"},
    "XLE":  {"sector": "Energy", "name": "Energy Select Sector SPDR Fund", "asset_class": "equity"},
    "XLK":  {"sector": "Technology", "name": "Technology Select Sector SPDR Fund", "asset_class": "equity"},
    "XLV":  {"sector": "Healthcare", "name": "Health Care Select Sector SPDR Fund", "asset_class": "equity"},
    "XLI":  {"sector": "Industrials", "name": "Industrial Select Sector SPDR Fund", "asset_class": "equity"},
    "XLP":  {"sector": "Consumer Staples", "name": "Consumer Staples Select Sector SPDR Fund", "asset_class": "equity"},
    "XLY":  {"sector": "Consumer Discretionary", "name": "Consumer Discretionary Select Sector SPDR Fund", "asset_class": "equity"},
    "XLB":  {"sector": "Materials", "name": "Materials Select Sector SPDR Fund", "asset_class": "equity"},
    "XLU":  {"sector": "Utilities", "name": "Utilities Select Sector SPDR Fund", "asset_class": "equity"},
    "XLRE": {"sector": "Real Estate", "name": "Real Estate Select Sector SPDR Fund", "asset_class": "equity"},

    # Thematic
    "SMH":  {"sector": "Thematic", "name": "VanEck Semiconductor ETF", "asset_class": "equity"},
    "IBB":  {"sector": "Thematic", "name": "iShares Biotechnology ETF", "asset_class": "equity"},
    "XBI":  {"sector": "Thematic", "name": "SPDR S&P Biotech ETF (Equal Weight)", "asset_class": "equity"},
    "ARKK": {"sector": "Thematic", "name": "ARK Innovation ETF", "asset_class": "equity"},
}

# Combined universe for the Autonomous Agent (stocks + ETFs)
AUTONOMOUS_UNIVERSE = {**UNIVERSE, **MACRO_ETFS}

# CIK lookup populated dynamically from SEC tickers file
TICKER_TO_CIK = {}
