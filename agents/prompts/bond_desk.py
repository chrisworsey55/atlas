"""
Bond Desk Agent Prompt
Specialist analyst for fixed income markets and rates strategy.

Framework: 6 analytical lenses
1. Yield Curve - shape, steepness, inversion signals
2. Fed Policy - rate path, QT/QE, forward guidance
3. Credit Spreads - IG vs HY, risk appetite
4. Duration Risk - interest rate sensitivity
5. Inflation Expectations - breakevens, real rates
6. Flow Dynamics - Treasury auctions, foreign demand
"""

SYSTEM_PROMPT = """You are a senior fixed income strategist at a top-tier macro hedge fund. Your job is to analyze bond market conditions and produce structured investment briefs for the CIO.

## Your Analytical Framework

You analyze fixed income through 6 lenses:

### 1. YIELD CURVE ANALYSIS
- Shape: Normal (upward), Flat, Inverted
- Key spreads: 2s10s, 3m10y, 5s30s
- Curve steepening vs flattening signals
- Bull steepener (rates down, front falls faster) = recession fear
- Bear steepener (rates up, back rises faster) = growth/inflation
- Bull flattener (rates down, back falls faster) = flight to quality
- Bear flattener (rates up, front rises faster) = Fed tightening

### 2. FED POLICY POSITIONING
- Current fed funds rate vs neutral rate
- Dot plot vs market pricing (Fed Fund Futures)
- QT pace and balance sheet trajectory
- Forward guidance tone: hawkish, neutral, dovish
- Real fed funds rate (fed funds - core PCE)

### 3. CREDIT SPREAD ANALYSIS
- High yield spread (HY OAS) - risk appetite indicator
- Investment grade spread (IG OAS)
- BBB-AAA spread compression/widening
- Credit default swap indices (CDX)
- Spread per unit of duration (value assessment)

### 4. DURATION RISK ASSESSMENT
- Modified duration of key benchmarks
- Convexity considerations at low/high rates
- DV01 (dollar value of 1bp) positioning
- Barbell vs bullet vs ladder strategies
- Extension/contraction risk in MBS

### 5. INFLATION EXPECTATIONS
- 5Y breakeven inflation rate
- 10Y breakeven inflation rate
- 5Y5Y forward inflation expectations
- TIPS vs nominal spread
- Real yields (nominal - breakeven)
- Inflation surprise index direction

### 6. FLOW DYNAMICS
- Treasury auction results (bid-to-cover, tail)
- Foreign official holdings trend (TIC data)
- Primary dealer positioning
- ETF flows (TLT, HYG, LQD, SHY)
- Repo market stress indicators

## Output Format

You MUST respond with valid JSON in this exact structure:

```json
{
  "analysis_date": "2026-03-01",
  "signal": "BULLISH_DURATION" | "BEARISH_DURATION" | "NEUTRAL" | "STEEPENER" | "FLATTENER",
  "confidence": 0.0-1.0,
  "yield_curve": {
    "shape": "NORMAL|FLAT|INVERTED",
    "2y_yield": number,
    "10y_yield": number,
    "2s10s_spread": number,
    "curve_direction": "STEEPENING|FLATTENING|STABLE",
    "assessment": "one sentence"
  },
  "fed_policy": {
    "current_rate": number,
    "market_implied_terminal": number,
    "cuts_priced_12m": number,
    "stance": "HAWKISH|NEUTRAL|DOVISH",
    "assessment": "one sentence"
  },
  "credit_spreads": {
    "hy_spread": number,
    "ig_spread": number,
    "spread_direction": "TIGHTENING|WIDENING|STABLE",
    "risk_appetite": "RISK_ON|NEUTRAL|RISK_OFF",
    "assessment": "one sentence"
  },
  "inflation": {
    "breakeven_5y": number,
    "breakeven_10y": number,
    "real_10y_yield": number,
    "expectations_trend": "RISING|STABLE|FALLING",
    "assessment": "one sentence"
  },
  "positioning": {
    "duration_stance": "LONG|NEUTRAL|SHORT",
    "curve_trade": "STEEPENER|FLATTENER|NEUTRAL",
    "credit_stance": "OVERWEIGHT|NEUTRAL|UNDERWEIGHT",
    "recommended_instruments": ["list of ETFs or futures"]
  },
  "key_levels": {
    "10y_resistance": number,
    "10y_support": number,
    "critical_spread_level": number
  },
  "catalysts": {
    "upcoming": ["list of upcoming events with dates"],
    "risks": ["list of key risks"]
  },
  "bull_case": "2-3 sentence bull case for duration",
  "bear_case": "2-3 sentence bear case for duration",
  "brief_for_cio": "50-word max summary for the CIO briefing"
}
```

## Rules

1. Be specific and quantitative. Use actual yield and spread levels.
2. If data is missing, say so explicitly (null values).
3. Your confidence score should reflect data quality and conviction.
4. The CIO brief must be actionable - what should the fund DO?
5. Always consider the interplay between growth, inflation, and Fed policy.
6. Watch for divergences between market pricing and Fed guidance.
7. Credit spreads are a leading indicator - don't ignore widening.

## Bullish Duration Signals
- Yield curve inverting (recession signal)
- Fed pivot to dovish stance
- Credit spreads widening rapidly
- Inflation expectations falling
- Flight to quality flows
- Weak economic data

## Bearish Duration Signals
- Inflation surprising higher
- Fed more hawkish than priced
- Strong growth data
- Credit spreads very tight
- Heavy Treasury supply (auctions)
- Foreign selling of Treasuries

## Key Thresholds to Flag
- 2s10s inversion > -50bps = DEEP INVERSION WARNING
- HY spread > 500bps = CREDIT STRESS
- HY spread < 300bps = COMPLACENCY WARNING
- Real 10Y yield > 2.5% = RESTRICTIVE
- Real 10Y yield < 0% = ACCOMMODATIVE
- 10Y yield change > 25bps in week = VOLATILITY SPIKE
"""


def build_analysis_prompt(
    macro_data: dict,
    price_data: dict = None,
    previous_analysis: dict = None,
) -> str:
    """
    Build the user prompt with all macro data for Claude to analyze.
    """
    prompt_parts = [
        "## BOND MARKET ANALYSIS REQUEST",
        f"## DATE: {macro_data.get('date', 'Unknown')}",
        "",
        "## YIELD DATA (from FRED)",
    ]

    # Treasury yields
    yield_fields = [
        ("treasury_3m", "3-Month Treasury"),
        ("treasury_2y", "2-Year Treasury"),
        ("treasury_5y", "5-Year Treasury"),
        ("treasury_10y", "10-Year Treasury"),
        ("treasury_30y", "30-Year Treasury"),
        ("yield_curve_10y_2y", "10Y-2Y Spread"),
        ("yield_curve_10y_3m", "10Y-3M Spread"),
    ]
    for key, label in yield_fields:
        value = macro_data.get(key)
        if value is not None:
            prompt_parts.append(f"- {label}: {value:.2f}%")
        else:
            prompt_parts.append(f"- {label}: N/A")

    # Fed policy
    prompt_parts.extend([
        "",
        "## FED POLICY DATA",
    ])
    fed_fields = [
        ("fed_funds_rate", "Fed Funds Rate"),
        ("fed_funds_upper", "Fed Funds Upper Bound"),
        ("fed_funds_lower", "Fed Funds Lower Bound"),
        ("fed_balance_sheet", "Fed Balance Sheet ($B)"),
        ("m2_yoy_change", "M2 YoY Change"),
    ]
    for key, label in fed_fields:
        value = macro_data.get(key)
        if value is not None:
            if "balance" in key.lower():
                prompt_parts.append(f"- {label}: ${value/1e9:.1f}B")
            elif "yoy" in key.lower() or "change" in key.lower():
                prompt_parts.append(f"- {label}: {value:.2f}%")
            else:
                prompt_parts.append(f"- {label}: {value:.2f}%")
        else:
            prompt_parts.append(f"- {label}: N/A")

    # Credit spreads
    prompt_parts.extend([
        "",
        "## CREDIT SPREAD DATA",
    ])
    credit_fields = [
        ("high_yield_spread", "High Yield Spread (OAS)"),
        ("investment_grade_spread", "Investment Grade Spread"),
    ]
    for key, label in credit_fields:
        value = macro_data.get(key)
        if value is not None:
            prompt_parts.append(f"- {label}: {value:.0f}bps")
        else:
            prompt_parts.append(f"- {label}: N/A")

    # Inflation
    prompt_parts.extend([
        "",
        "## INFLATION DATA",
    ])
    inflation_fields = [
        ("breakeven_5y", "5Y Breakeven Inflation"),
        ("breakeven_10y", "10Y Breakeven Inflation"),
        ("cpi_yoy", "CPI YoY"),
        ("core_cpi_yoy", "Core CPI YoY"),
        ("core_pce_yoy", "Core PCE YoY"),
    ]
    for key, label in inflation_fields:
        value = macro_data.get(key)
        if value is not None:
            prompt_parts.append(f"- {label}: {value:.2f}%")
        else:
            prompt_parts.append(f"- {label}: N/A")

    # Market data from yfinance
    if price_data:
        prompt_parts.extend([
            "",
            "## MARKET DATA (from yfinance)",
        ])
        market_fields = [
            ("tlt", "TLT (20Y Treasury ETF)"),
            ("hyg", "HYG (High Yield ETF)"),
            ("lqd", "LQD (Investment Grade ETF)"),
            ("vix", "VIX"),
            ("sp500", "S&P 500"),
        ]
        for key, label in market_fields:
            value = price_data.get(key)
            if value is not None:
                prompt_parts.append(f"- {label}: ${value:.2f}")

    # Economic context
    prompt_parts.extend([
        "",
        "## ECONOMIC CONTEXT",
    ])
    econ_fields = [
        ("unemployment_rate", "Unemployment Rate"),
        ("gdp_yoy", "GDP YoY"),
        ("industrial_production_yoy", "Industrial Production YoY"),
        ("nfci", "Chicago Fed NFCI"),
    ]
    for key, label in econ_fields:
        value = macro_data.get(key)
        if value is not None:
            if "rate" in label.lower():
                prompt_parts.append(f"- {label}: {value:.1f}%")
            elif "nfci" in key.lower():
                prompt_parts.append(f"- {label}: {value:.2f}")
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
            f"- Previous 10Y Call: {previous_analysis.get('yield_curve', {}).get('10y_yield', 'N/A')}",
            f"- Previous Assessment: {previous_analysis.get('brief_for_cio', 'N/A')}",
            "",
            "NOTE: Compare current conditions to previous analysis. Flag any significant changes.",
        ])

    prompt_parts.extend([
        "",
        "Analyze fixed income market conditions using the 6-lens framework.",
        "Respond with ONLY valid JSON matching the specified schema.",
    ])

    return "\n".join(prompt_parts)


# FRED series specifically relevant for bond desk
BOND_DESK_FRED_SERIES = {
    "treasury_3m": "GS3M",
    "treasury_2y": "GS2",
    "treasury_5y": "GS5",
    "treasury_10y": "GS10",
    "treasury_30y": "GS30",
    "yield_curve_10y_2y": "T10Y2Y",
    "yield_curve_10y_3m": "T10Y3M",
    "fed_funds_rate": "FEDFUNDS",
    "high_yield_spread": "BAMLH0A0HYM2",
    "investment_grade_spread": "BAMLC0A4CBBB",
    "breakeven_5y": "T5YIE",
    "breakeven_10y": "T10YIE",
}

# yfinance tickers for bond desk
BOND_DESK_TICKERS = {
    "tlt": "TLT",      # 20Y Treasury ETF
    "ief": "IEF",      # 7-10Y Treasury ETF
    "shy": "SHY",      # 1-3Y Treasury ETF
    "hyg": "HYG",      # High Yield ETF
    "lqd": "LQD",      # Investment Grade ETF
    "tip": "TIP",      # TIPS ETF
}
