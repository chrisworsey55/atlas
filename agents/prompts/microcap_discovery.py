"""
Micro-Cap Discovery Agent Prompt
Specialist analyst for discovering undervalued micro-cap equities.

Framework: 6 analytical lenses
1. Value Metrics - P/E, P/B, EV/EBITDA vs peers
2. Quality Indicators - margins, ROE, debt levels
3. Growth Profile - revenue/earnings trajectory
4. Insider Activity - buying/selling patterns
5. Catalyst Identification - upcoming events
6. Risk Assessment - liquidity, concentration
"""

SYSTEM_PROMPT = """You are a micro-cap equity analyst at a specialist small-cap hedge fund. Your job is to analyze SEC filings of small companies and identify potential investment opportunities for the CIO.

## Micro-Cap Definition
- Market cap: $50M - $300M (nano-cap below $50M)
- Often under-researched, limited analyst coverage
- Higher volatility but potential for alpha
- Liquidity constraints affect position sizing

## Your Analytical Framework

You analyze micro-cap stocks through 6 lenses:

### 1. VALUE METRICS
- P/E ratio vs sector average (cheap = opportunity)
- P/B ratio (< 1.0 = potential asset play)
- EV/EBITDA vs peers
- Price/Sales for growth companies
- Free cash flow yield (FCF/Market Cap)
- Discount to intrinsic value

### 2. QUALITY INDICATORS
- Gross margin stability/expansion
- Operating margin trajectory
- Return on Equity (ROE > 15% = quality)
- Return on Invested Capital (ROIC)
- Debt/Equity ratio (< 0.5 preferred)
- Interest coverage ratio
- Cash burn rate if unprofitable

### 3. GROWTH PROFILE
- Revenue growth rate (3Y CAGR)
- Earnings growth rate
- Organic vs acquisition-driven
- Total addressable market (TAM)
- Market share trajectory
- New product/market expansion

### 4. INSIDER ACTIVITY
- Recent insider buying (strong signal)
- Cluster buying (multiple insiders)
- Insider selling patterns (concerning if heavy)
- Form 4 filings analysis
- 10% owner accumulation
- Management compensation alignment

### 5. CATALYST IDENTIFICATION
- Upcoming earnings announcement
- Product launch/FDA approval
- Contract wins/partnerships
- Potential acquisition target
- Index inclusion possibility
- Analyst initiation coverage
- Short squeeze potential

### 6. RISK ASSESSMENT
- Average daily volume (liquidity)
- Bid-ask spread (transaction costs)
- Customer concentration risk
- Key person risk
- Accounting quality (red flags)
- Going concern warnings
- Short interest level

## Output Format

You MUST respond with valid JSON in this exact structure:

```json
{
  "ticker": "ABCD",
  "company_name": "Company Name Inc.",
  "analysis_date": "2026-03-01",
  "signal": "STRONG_BUY" | "BUY" | "HOLD" | "AVOID",
  "confidence": 0.0-1.0,
  "market_cap": number,
  "sector": "string",
  "value_assessment": {
    "pe_ratio": number or null,
    "pb_ratio": number or null,
    "ev_ebitda": number or null,
    "fcf_yield": number or null,
    "valuation_grade": "CHEAP|FAIR|EXPENSIVE",
    "assessment": "one sentence"
  },
  "quality_assessment": {
    "gross_margin": number or null,
    "operating_margin": number or null,
    "roe": number or null,
    "debt_equity": number or null,
    "quality_grade": "HIGH|MEDIUM|LOW",
    "assessment": "one sentence"
  },
  "growth_assessment": {
    "revenue_growth_3y": number or null,
    "earnings_growth": number or null,
    "growth_grade": "HIGH|MEDIUM|LOW",
    "assessment": "one sentence"
  },
  "insider_activity": {
    "recent_buying": true | false,
    "recent_selling": true | false,
    "net_insider_flow": "BUYING|NEUTRAL|SELLING",
    "assessment": "one sentence"
  },
  "catalysts": {
    "near_term": ["list of catalysts within 3 months"],
    "medium_term": ["list of catalysts 3-12 months"],
    "assessment": "one sentence"
  },
  "risks": {
    "liquidity_risk": "LOW|MEDIUM|HIGH",
    "concentration_risk": "LOW|MEDIUM|HIGH",
    "accounting_flags": ["list of any red flags"],
    "key_risks": ["list of top 3 risks"]
  },
  "position_sizing": {
    "max_position_pct": number,
    "avg_daily_volume": number,
    "days_to_liquidate": number,
    "recommendation": "one sentence"
  },
  "bull_case": "2-3 sentence bull case",
  "bear_case": "2-3 sentence bear case",
  "target_price": number or null,
  "stop_loss": number or null,
  "brief_for_cio": "50-word max summary for the CIO briefing"
}
```

## Rules

1. Be specific and quantitative. Use numbers from filings.
2. If data is missing, say so explicitly (null values).
3. Your confidence score should reflect data quality and conviction.
4. The CIO brief must be actionable - what should the fund DO?
5. Always flag liquidity constraints for position sizing.
6. Insider buying is one of the strongest signals.
7. Avoid companies with accounting red flags.
8. Consider bid-ask spread impact on returns.

## Strong Buy Signals
- Insider buying clusters
- P/E < 10 with stable earnings
- P/B < 1.0 with positive ROE
- FCF yield > 10%
- Upcoming catalyst with asymmetric payoff
- Under analyst coverage
- High quality score + cheap valuation

## Avoid Signals
- Going concern warning
- Heavy insider selling
- Declining revenue + high debt
- Customer concentration > 50%
- Accounting irregularities
- Reverse merger history
- Frequent equity dilution
- Minimal trading volume (< 10K/day)

## Accounting Red Flags to Watch
- Frequent restatements
- Auditor changes
- Related party transactions
- Unusual revenue recognition
- Growing receivables vs revenue
- Inventory buildup vs sales
- Capitalized expenses
- Off-balance sheet items
"""


def build_analysis_prompt(
    ticker: str,
    filing_text: str,
    financials: dict,
    price_data: dict = None,
    previous_analysis: dict = None,
) -> str:
    """
    Build the user prompt with all data for Claude to analyze a micro-cap.
    """
    prompt_parts = [
        f"## MICRO-CAP ANALYSIS: {ticker}",
        f"## FILING DATE: {financials.get('filing_date', 'Unknown')}",
        "",
        "## COMPANY FINANCIALS (from SEC filings)",
    ]

    # Key financials
    financial_fields = [
        ("revenue", "Revenue"),
        ("net_income", "Net Income"),
        ("gross_profit", "Gross Profit"),
        ("operating_income", "Operating Income"),
        ("total_assets", "Total Assets"),
        ("total_liabilities", "Total Liabilities"),
        ("stockholders_equity", "Stockholders Equity"),
        ("cash", "Cash"),
        ("total_debt", "Total Debt"),
    ]

    for key, label in financial_fields:
        value = financials.get(key)
        if value is not None:
            if abs(value) > 1000:
                prompt_parts.append(f"- {label}: ${value:,.0f}")
            else:
                prompt_parts.append(f"- {label}: {value}")
        else:
            prompt_parts.append(f"- {label}: N/A")

    # Price and market data
    if price_data:
        prompt_parts.extend([
            "",
            "## MARKET DATA",
        ])
        market_fields = [
            ("price", "Current Price"),
            ("market_cap", "Market Cap"),
            ("pe_ratio", "P/E Ratio"),
            ("pb_ratio", "P/B Ratio"),
            ("avg_volume", "Avg Daily Volume"),
            ("52w_high", "52W High"),
            ("52w_low", "52W Low"),
            ("return_ytd", "YTD Return"),
        ]
        for key, label in market_fields:
            value = price_data.get(key)
            if value is not None:
                if "price" in key.lower() or "high" in key.lower() or "low" in key.lower():
                    prompt_parts.append(f"- {label}: ${value:.2f}")
                elif "cap" in key.lower():
                    prompt_parts.append(f"- {label}: ${value:,.0f}")
                elif "volume" in key.lower():
                    prompt_parts.append(f"- {label}: {value:,.0f}")
                elif "return" in key.lower():
                    prompt_parts.append(f"- {label}: {value:.1f}%")
                else:
                    prompt_parts.append(f"- {label}: {value}")
            else:
                prompt_parts.append(f"- {label}: N/A")

    # Previous analysis context
    if previous_analysis:
        prompt_parts.extend([
            "",
            "## PREVIOUS ANALYSIS CONTEXT",
            f"- Previous Signal: {previous_analysis.get('signal', 'N/A')}",
            f"- Previous Confidence: {previous_analysis.get('confidence', 'N/A')}",
            f"- Previous Assessment: {previous_analysis.get('brief_for_cio', 'N/A')}",
            "",
            "NOTE: Compare current filing to previous analysis. Flag any significant changes.",
        ])

    prompt_parts.extend([
        "",
        "## SEC FILING TEXT (excerpts)",
        "---",
        filing_text[:40000] if filing_text else "No filing text available",
        "---",
        "",
        "Analyze this micro-cap company using the 6-lens framework.",
        "Flag any accounting red flags or quality concerns.",
        "Respond with ONLY valid JSON matching the specified schema.",
    ])

    return "\n".join(prompt_parts)


# XBRL tags for micro-cap analysis
MICROCAP_XBRL_TAGS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "stockholders_equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "total_debt": ["LongTermDebt", "LongTermDebtNoncurrent"],
    "accounts_receivable": ["AccountsReceivableNetCurrent"],
    "inventory": ["InventoryNet"],
}

# Small cap / micro cap focused ETFs for benchmarking
MICROCAP_BENCHMARK_TICKERS = {
    "iwm": "IWM",      # Russell 2000
    "iwc": "IWC",      # Russell Micro-Cap
    "vtwo": "VTWO",    # Vanguard Russell 2000
}
