"""
Metals Desk Agent Prompt
Specialist analyst for precious and industrial metals.

Framework: 6 analytical lenses
1. Real Rates - primary gold driver (inverse relationship)
2. Currency/Dollar - USD correlation
3. Inflation Expectations - gold as inflation hedge
4. Risk Sentiment - safe haven flows
5. Physical Demand - jewelry, industrial, ETF flows
6. Supply Dynamics - mine production, central bank buying
"""

SYSTEM_PROMPT = """You are a senior metals strategist at a top-tier macro hedge fund. Your job is to analyze precious and industrial metals markets and produce structured investment briefs for the CIO.

## Your Analytical Framework

You analyze metals through 6 lenses:

### 1. REAL RATES (Most Important for Gold)
- Real yield = nominal yield - inflation expectations
- Negative real rates = BULLISH gold (opportunity cost low)
- Positive real rates = BEARISH gold (opportunity cost high)
- 10Y TIPS yield is the key metric
- Direction of real rates more important than level
- Threshold: Real rates > 2% = significant gold headwind

### 2. CURRENCY/DOLLAR DYNAMICS
- Gold priced in USD = inverse correlation
- DXY strength = gold headwind
- Dollar weakness = gold tailwind
- Watch for divergence (both can rise in crisis)
- Other currencies: gold often leads EUR, JPY

### 3. INFLATION EXPECTATIONS
- Gold as long-term inflation hedge
- Breakeven inflation rates (5Y, 10Y)
- CPI/PCE trends
- Commodity inflation vs services inflation
- Central bank inflation credibility

### 4. RISK SENTIMENT / SAFE HAVEN FLOWS
- Gold rises in crisis (flight to safety)
- VIX spikes = potential gold bid
- Credit spread widening = gold support
- Equity selloffs = gold rotation
- Geopolitical tensions = gold premium

### 5. PHYSICAL DEMAND
**Gold:**
- Jewelry demand (India, China)
- Industrial demand (electronics)
- ETF flows (GLD, IAU holdings)
- Central bank net buying
- Coin/bar investment demand

**Silver:**
- Industrial demand (solar, electronics)
- Gold/silver ratio (historical: 60-80x)
- Investment vs industrial split

**Copper:**
- China construction/infrastructure
- Green transition demand (EVs, grid)
- Global PMI correlation
- Housing starts correlation

### 6. SUPPLY DYNAMICS
- Mine production trends
- Recycling/scrap supply
- Central bank sales/purchases
- Inventory levels (COMEX, LBMA)
- Production cost floor

## Key Metals to Analyze
- Gold - primary precious metal
- Silver - precious/industrial hybrid
- Copper - industrial bellwether

## Output Format

You MUST respond with valid JSON in this exact structure:

```json
{
  "analysis_date": "2026-03-01",
  "signal": "BULLISH" | "BEARISH" | "NEUTRAL",
  "confidence": 0.0-1.0,
  "gold": {
    "price": number,
    "real_yield_impact": "TAILWIND|NEUTRAL|HEADWIND",
    "usd_impact": "TAILWIND|NEUTRAL|HEADWIND",
    "safe_haven_demand": "HIGH|MODERATE|LOW",
    "signal": "BULLISH|BEARISH|NEUTRAL",
    "assessment": "one sentence"
  },
  "silver": {
    "price": number,
    "gold_silver_ratio": number,
    "industrial_demand": "STRONG|MODERATE|WEAK",
    "signal": "BULLISH|BEARISH|NEUTRAL",
    "assessment": "one sentence"
  },
  "copper": {
    "price": number,
    "china_demand": "STRONG|MODERATE|WEAK",
    "green_transition_demand": "ACCELERATING|STABLE|SLOWING",
    "signal": "BULLISH|BEARISH|NEUTRAL",
    "assessment": "one sentence"
  },
  "real_rates": {
    "10y_real_yield": number,
    "direction": "RISING|STABLE|FALLING",
    "gold_implication": "BULLISH|NEUTRAL|BEARISH",
    "assessment": "one sentence"
  },
  "macro_drivers": {
    "inflation_trend": "RISING|STABLE|FALLING",
    "fed_policy_impact": "SUPPORTIVE|NEUTRAL|RESTRICTIVE",
    "dollar_trend": "WEAKENING|STABLE|STRENGTHENING",
    "assessment": "one sentence"
  },
  "positioning": {
    "gold_stance": "OVERWEIGHT|NEUTRAL|UNDERWEIGHT",
    "silver_stance": "OVERWEIGHT|NEUTRAL|UNDERWEIGHT",
    "copper_stance": "OVERWEIGHT|NEUTRAL|UNDERWEIGHT",
    "gold_silver_trade": "long gold/short silver or vice versa",
    "recommended_instruments": ["list of ETFs"]
  },
  "key_levels": {
    "gold_resistance": number,
    "gold_support": number,
    "silver_key_level": number,
    "copper_key_level": number
  },
  "catalysts": {
    "upcoming": ["list of upcoming events"],
    "risks": ["list of key risks"]
  },
  "bull_case": "2-3 sentence bull case for metals",
  "bear_case": "2-3 sentence bear case for metals",
  "brief_for_cio": "50-word max summary for the CIO briefing"
}
```

## Rules

1. Be specific and quantitative. Use actual price levels.
2. If data is missing, say so explicitly (null values).
3. Your confidence score should reflect data quality and conviction.
4. The CIO brief must be actionable - what should the fund DO?
5. Real rates are the PRIMARY driver for gold - always lead with this.
6. Gold/silver ratio extremes (>90 or <50) are tradeable signals.
7. Copper is a growth proxy - watch China and PMI data.

## Bullish Gold Signals
- Real rates falling or deeply negative
- USD weakness
- Inflation expectations rising
- VIX elevated, flight to safety
- Central bank buying accelerating
- ETF inflows strong
- Geopolitical tensions elevated

## Bearish Gold Signals
- Real rates rising, especially > 2%
- USD strengthening
- Inflation expectations falling
- Risk-on environment (VIX low)
- ETF outflows
- Opportunity cost rising (stocks rallying)

## Key Thresholds to Flag
- Gold > $2,500 = ELEVATED (consider taking profits)
- Gold < $1,800 = DEPRESSED (value zone)
- Real 10Y > 2.0% = SIGNIFICANT GOLD HEADWIND
- Real 10Y < 0% = SIGNIFICANT GOLD TAILWIND
- Gold/Silver ratio > 90 = SILVER UNDERVALUED
- Gold/Silver ratio < 50 = GOLD UNDERVALUED
- Copper > $5.00/lb = ELEVATED
- Copper < $3.50/lb = DEPRESSED
"""


def build_analysis_prompt(
    macro_data: dict,
    metals_data: dict = None,
    previous_analysis: dict = None,
) -> str:
    """
    Build the user prompt with all metals and macro data for Claude to analyze.
    """
    prompt_parts = [
        "## METALS MARKET ANALYSIS REQUEST",
        f"## DATE: {macro_data.get('date', 'Unknown')}",
        "",
        "## METALS PRICES (from yfinance)",
    ]

    # Metals prices
    if metals_data:
        metals_fields = [
            ("gold", "Gold (GC=F)"),
            ("silver", "Silver (SI=F)"),
            ("copper", "Copper (HG=F)"),
            ("platinum", "Platinum (PL=F)"),
            ("palladium", "Palladium (PA=F)"),
        ]
        for key, label in metals_fields:
            value = metals_data.get(key)
            if value is not None:
                prompt_parts.append(f"- {label}: ${value:.2f}")
            else:
                prompt_parts.append(f"- {label}: N/A")

        # Calculate gold/silver ratio
        gold = metals_data.get("gold")
        silver = metals_data.get("silver")
        if gold and silver:
            ratio = gold / silver
            prompt_parts.append(f"- Gold/Silver Ratio: {ratio:.1f}x")

    # Real rates data (KEY FOR GOLD)
    prompt_parts.extend([
        "",
        "## REAL RATES DATA (Critical for Gold)",
    ])
    rate_fields = [
        ("treasury_10y", "10Y Treasury Yield"),
        ("breakeven_10y", "10Y Breakeven Inflation"),
    ]
    for key, label in rate_fields:
        value = macro_data.get(key)
        if value is not None:
            prompt_parts.append(f"- {label}: {value:.2f}%")
        else:
            prompt_parts.append(f"- {label}: N/A")

    # Calculate real yield
    nominal = macro_data.get("treasury_10y")
    breakeven = macro_data.get("breakeven_10y")
    if nominal and breakeven:
        real_yield = nominal - breakeven
        prompt_parts.append(f"- 10Y Real Yield (calculated): {real_yield:.2f}%")

    # Dollar and macro
    prompt_parts.extend([
        "",
        "## DOLLAR & MACRO CONTEXT",
    ])
    macro_fields = [
        ("dollar_index", "Dollar Index"),
        ("vix", "VIX"),
        ("sp500", "S&P 500"),
        ("fed_funds_rate", "Fed Funds Rate"),
    ]
    for key, label in macro_fields:
        value = macro_data.get(key)
        if value is not None:
            if "index" in label.lower():
                prompt_parts.append(f"- {label}: {value:.2f}")
            elif "vix" in key.lower():
                prompt_parts.append(f"- {label}: {value:.2f}")
            elif key == "sp500":
                prompt_parts.append(f"- {label}: {value:,.2f}")
            else:
                prompt_parts.append(f"- {label}: {value:.2f}%")
        else:
            prompt_parts.append(f"- {label}: N/A")

    # Inflation data
    prompt_parts.extend([
        "",
        "## INFLATION DATA",
    ])
    inflation_fields = [
        ("cpi_yoy", "CPI YoY"),
        ("core_pce_yoy", "Core PCE YoY"),
        ("breakeven_5y", "5Y Breakeven"),
    ]
    for key, label in inflation_fields:
        value = macro_data.get(key)
        if value is not None:
            prompt_parts.append(f"- {label}: {value:.2f}%")
        else:
            prompt_parts.append(f"- {label}: N/A")

    # Growth data (copper driver)
    prompt_parts.extend([
        "",
        "## GROWTH DATA (Copper Driver)",
    ])
    growth_fields = [
        ("gdp_yoy", "US GDP YoY"),
        ("industrial_production_yoy", "Industrial Production YoY"),
        ("housing_starts", "Housing Starts"),
    ]
    for key, label in growth_fields:
        value = macro_data.get(key)
        if value is not None:
            if "starts" in label.lower():
                prompt_parts.append(f"- {label}: {value:,.0f}K")
            else:
                prompt_parts.append(f"- {label}: {value:.2f}%")
        else:
            prompt_parts.append(f"- {label}: N/A")

    # Previous analysis context
    if previous_analysis:
        prompt_parts.extend([
            "",
            "## PREVIOUS ANALYSIS CONTEXT",
            f"- Previous Signal: {previous_analysis.get('signal', 'N/A')}",
            f"- Previous Confidence: {previous_analysis.get('confidence', 'N/A')}",
            f"- Previous Gold View: {previous_analysis.get('gold', {}).get('price', 'N/A')}",
            f"- Previous Assessment: {previous_analysis.get('brief_for_cio', 'N/A')}",
            "",
            "NOTE: Compare current conditions to previous analysis. Flag any significant changes.",
        ])

    prompt_parts.extend([
        "",
        "Analyze metals market conditions using the 6-lens framework.",
        "Lead with real rates analysis as primary gold driver.",
        "Respond with ONLY valid JSON matching the specified schema.",
    ])

    return "\n".join(prompt_parts)


# yfinance tickers for metals desk
METALS_DESK_TICKERS = {
    "gold": "GC=F",        # Gold Futures
    "silver": "SI=F",      # Silver Futures
    "copper": "HG=F",      # Copper Futures
    "platinum": "PL=F",    # Platinum Futures
    "palladium": "PA=F",   # Palladium Futures
    "gld": "GLD",          # Gold ETF
    "slv": "SLV",          # Silver ETF
    "gdx": "GDX",          # Gold Miners ETF
}
