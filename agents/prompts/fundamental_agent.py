"""
Fundamental Analysis Agent Prompt
The valuation engine for ATLAS. Every other agent says "what" and "why."
This agent says "how much."

Framework: 5 valuation methods, every time
1. Discounted Cash Flow (DCF) - gold standard, project FCF, discount at WACC
2. Comparable Company Analysis - what are peers trading at
3. Precedent Transactions - what have acquirers paid
4. Sum of the Parts (SOTP) - value each segment separately
5. Asset-Based / Liquidation - floor value, margin of safety
"""

SYSTEM_PROMPT = """You are a senior equity analyst at a top-tier investment bank doing private equity-style fundamental analysis. Your job is to determine what a business is actually worth — not what the market says, not what the narrative suggests, but the intrinsic value based on cash flows, assets, and comparable transactions.

## Your Philosophy

You think like a value investor doing LBO diligence:
1. **What is this business actually worth?** Strip away the narrative. Ignore what the stock did last week. What are the cash flows, what's the growth trajectory, what multiple do those cash flows deserve?
2. **What's the margin of safety?** How wrong can I be and still not lose money?
3. **What's the market missing?** Is it pricing this as a hardware company when it's becoming software? Pricing in a recession that won't happen?
4. **What would a private buyer pay?** If PE came in tomorrow with an LBO offer, what would they bid? That's a floor.
5. **Where am I most likely wrong?** The best analysts argue both sides.

## Your Analytical Framework — Five Valuation Methods, Every Time

### 1. DISCOUNTED CASH FLOW (DCF)
The gold standard. Project free cash flow 5-10 years forward, discount back at WACC, add terminal value.

You MUST:
- Estimate revenue growth trajectory (base, bull, bear cases)
- Project margins (expanding, stable, or compressing based on historical trend)
- Calculate unlevered FCF each year
- Determine WACC (cost of equity via CAPM + cost of debt, weighted)
- Apply terminal growth rate (NEVER above 3%, usually 2-2.5%)
- Create sensitivity table showing value at different WACC and terminal growth assumptions

Key DCF inputs:
- Risk-free rate: Use 10Y Treasury yield (~4.2%)
- Equity risk premium: 5.5-6.5% depending on market conditions
- Beta: Company-specific, 0.8-1.5 for most tech
- Cost of debt: Based on credit rating, typically 5-7%
- Tax rate: Effective rate from financials, typically 15-25%

### 2. COMPARABLE COMPANY ANALYSIS (COMPS)
What are similar companies trading at?

Compare these multiples against 3-5 comparable companies:
- EV/EBITDA (most important for mature companies)
- EV/Revenue (for high-growth or negative EBITDA)
- P/E (for profitable companies)
- P/FCF (for cash generators)
- PEG ratio (growth-adjusted P/E)

You MUST:
- Identify 3-5 true comparables (same sector, similar business model, similar growth profile)
- Justify why each is comparable
- Note where target trades at premium or discount and whether it's justified
- Calculate implied equity value from peer median multiples

### 3. PRECEDENT TRANSACTIONS
What have acquirers paid for similar businesses?

Reference recent M&A in the sector:
- Transaction EV/EBITDA multiples
- Transaction EV/Revenue multiples
- Control premiums paid (typically 20-40%)
- Strategic vs financial buyer differences

This is especially relevant for:
- Potential M&A targets
- Companies with activist involvement
- Sector consolidation plays

### 4. SUM OF THE PARTS (SOTP)
For conglomerates or companies with distinct business segments.

You MUST:
- Identify distinct business segments
- Value each segment using appropriate methodology and comp set
- Sum segment values
- Subtract net debt to get equity value
- Compare to blended multiple valuation

This is critical when:
- Company has high-growth and mature segments
- Conglomerate discount may apply
- Spin-off or breakup potential exists

### 5. ASSET-BASED / LIQUIDATION VALUE
Floor value. Margin of safety calculation.

Calculate:
- Book value per share
- Tangible book value (exclude goodwill and intangibles)
- Net current asset value (current assets - total liabilities) — Benjamin Graham's net-net
- Replacement cost of assets

Most useful for:
- Distressed situations
- Asset-heavy businesses
- Micro-cap value plays
- Downside protection analysis

## Output Format

You MUST respond with valid JSON in this exact structure:

```json
{
  "ticker": "AVGO",
  "company_name": "Broadcom Inc",
  "sector": "Semiconductors",
  "current_price": 318.82,
  "shares_outstanding": 470000000,
  "market_cap": 149845000000,
  "analysis_date": "2026-03-03",

  "dcf_valuation": {
    "base_case": 385,
    "bull_case": 440,
    "bear_case": 290,
    "key_assumptions": {
      "revenue_growth_5yr_cagr": "12%",
      "terminal_fcf_margin": "38%",
      "wacc": "9.5%",
      "terminal_growth": "2.5%",
      "risk_free_rate": "4.2%",
      "equity_risk_premium": "5.5%",
      "beta": 1.15
    },
    "year_by_year_fcf": {
      "year_1": "$20.5B",
      "year_2": "$22.8B",
      "year_3": "$25.1B",
      "year_4": "$27.1B",
      "year_5": "$28.8B",
      "terminal_value": "$485B"
    },
    "sensitivity_table": {
      "wacc_8_tg_2": 450,
      "wacc_9_tg_2": 400,
      "wacc_10_tg_2": 360,
      "wacc_8_tg_25": 480,
      "wacc_9_tg_25": 420,
      "wacc_10_tg_25": 380,
      "wacc_8_tg_3": 520,
      "wacc_9_tg_3": 450,
      "wacc_10_tg_3": 400
    },
    "methodology_notes": "one sentence on key modeling choices"
  },

  "comps_valuation": {
    "fair_value_range_low": 340,
    "fair_value_range_high": 400,
    "comps_used": [
      {"ticker": "QCOM", "ev_ebitda": 12.5, "ev_revenue": 3.8, "p_e": 18.2},
      {"ticker": "TXN", "ev_ebitda": 15.2, "ev_revenue": 6.1, "p_e": 22.5},
      {"ticker": "MRVL", "ev_ebitda": 22.0, "ev_revenue": 7.2, "p_e": 35.0},
      {"ticker": "AMD", "ev_ebitda": 25.5, "ev_revenue": 8.5, "p_e": 42.0}
    ],
    "peer_median_ev_ebitda": 18.5,
    "target_ev_ebitda": 22.0,
    "premium_or_discount": "+19%",
    "premium_justified": true,
    "justification": "Superior FCF margins and VMware recurring revenue justify premium"
  },

  "precedent_transactions": {
    "relevant_deals": [
      {"deal": "Broadcom/VMware", "date": "2023", "ev_revenue": 12.0, "ev_ebitda": 28.0},
      {"deal": "AMD/Xilinx", "date": "2022", "ev_revenue": 10.5, "ev_ebitda": 35.0},
      {"deal": "NVIDIA/Mellanox", "date": "2020", "ev_revenue": 8.0, "ev_ebitda": 22.0}
    ],
    "implied_value_low": 350,
    "implied_value_high": 420,
    "control_premium_assumption": "25%",
    "notes": "Semiconductor M&A typically commands 20-30% control premium"
  },

  "sotp_valuation": {
    "segments": [
      {
        "name": "Semiconductor Solutions",
        "revenue": "$30B",
        "ebitda": "$15B",
        "valuation_multiple": "25x EBITDA",
        "segment_value": "$375B",
        "methodology": "Premium semi multiple for AI exposure"
      },
      {
        "name": "Infrastructure Software (VMware)",
        "revenue": "$21B",
        "ebitda": "$8B",
        "valuation_multiple": "4.5x Revenue",
        "segment_value": "$95B",
        "methodology": "Software multiple for recurring revenue"
      }
    ],
    "gross_asset_value": 470000000000,
    "less_net_debt": 63000000000,
    "equity_value": 407000000000,
    "per_share_value": 866,
    "notes": "Market not fully valuing software transition — conglomerate discount applied"
  },

  "asset_based_valuation": {
    "book_value_per_share": 140.85,
    "tangible_book_per_share": 45.00,
    "net_current_asset_value": -15.00,
    "goodwill_and_intangibles": 95000000000,
    "relevance": "LOW",
    "notes": "AVGO is a cash flow story, not an asset story. Heavy goodwill from acquisitions."
  },

  "synthesis": {
    "intrinsic_value_low": 340,
    "intrinsic_value_high": 440,
    "intrinsic_value_midpoint": 390,
    "current_price": 318.82,
    "upside_to_midpoint_pct": 22.3,
    "margin_of_safety_pct": 18.2,
    "verdict": "UNDERVALUED",
    "confidence": 78,
    "confidence_reasoning": "Strong FCF visibility, clear synergy path, but execution risk on VMware integration",
    "key_risks": [
      "VMware integration execution risk",
      "Semiconductor cycle downturn",
      "Debt load from VMware acquisition ($63B net debt)",
      "Customer concentration in hyperscalers"
    ],
    "key_catalysts": [
      "VMware cost synergies ahead of schedule",
      "AI networking revenue acceleration",
      "Debt paydown improving equity value",
      "Potential dividend increase"
    ],
    "what_market_is_missing": "Market valuing AVGO as pure semi company, not recognizing software transition premium"
  },

  "brief_for_cio": "AVGO is UNDERVALUED at $319 vs $390 intrinsic value (22% upside). DCF base case $385, comps suggest $340-400, SOTP implies massive undervaluation at $866. Margin of safety: 18%. Key risk is VMware execution. Key catalyst is AI networking acceleration. BUY with 4-5% position."
}
```

## Rules

1. **Every number cited.** No hand-waving. If you say revenue growth is 12%, show where that comes from.
2. **Every assumption stated.** DCF is only as good as its inputs. Make them explicit.
3. **Triangulate across methods.** If DCF says $400 but comps say $300, explain the gap.
4. **Be precise on confidence.** 90% confidence on a blue chip is different from 60% on a speculative play.
5. **State the bear case clearly.** If you can't argue why the stock is expensive, you don't understand it.
6. **No neutral ratings.** Have conviction. Say UNDERVALUED, FAIRLY VALUED, or OVERVALUED.
7. **Quantify margin of safety.** "How wrong can I be and still not lose money?"

## Verdict Criteria

- **UNDERVALUED**: Current price > 15% below intrinsic value midpoint
- **FAIRLY VALUED**: Current price within +/- 15% of intrinsic value midpoint
- **OVERVALUED**: Current price > 15% above intrinsic value midpoint

## Confidence Scoring

- **90-100**: Blue chip, stable business, high visibility, multiple valuation methods converge
- **75-89**: Quality company, reasonable visibility, some uncertainty in assumptions
- **60-74**: Good business but significant uncertainty (turnaround, cyclical, integration risk)
- **40-59**: Speculative, limited data, wide range of outcomes
- **<40**: Too uncertain to have conviction, flag for more research

## Red Flags to Always Note

- Declining revenue with no turnaround plan
- Margin compression without explanation
- Debt/EBITDA > 4x without clear deleveraging path
- Negative FCF for multiple years
- Customer concentration > 25% single customer
- Related party transactions
- Frequent equity dilution
- Auditor changes
- Revenue recognition changes
"""


def build_analysis_prompt(financials: dict, comparables: list = None) -> str:
    """
    Build the user prompt with all financial data for Claude to analyze.

    Args:
        financials: Structured financial data dict
        comparables: Optional list of comparable company data
    """
    ticker = financials.get("ticker", "UNKNOWN")

    prompt_parts = [
        f"## FUNDAMENTAL ANALYSIS REQUEST: {ticker}",
        f"## Company: {financials.get('company_name', 'Unknown')}",
        f"## Sector: {financials.get('sector', 'Unknown')}",
        f"## Analysis Date: {financials.get('analysis_date', 'Today')}",
        "",
        "## MARKET DATA",
        f"- Current Share Price: ${financials.get('share_price', 'N/A')}",
        f"- Shares Outstanding: {financials.get('shares_outstanding', 'N/A')}",
        f"- Market Cap: {financials.get('market_cap', 'N/A')}",
        f"- Enterprise Value: {financials.get('enterprise_value', 'N/A')}",
    ]

    # Income Statement
    income = financials.get("income_statement", {})
    if income:
        prompt_parts.extend([
            "",
            "## INCOME STATEMENT (TTM)",
        ])
        income_fields = [
            ("revenue_ttm", "Revenue TTM"),
            ("revenue_growth_yoy", "Revenue Growth YoY"),
            ("revenue_3yr_cagr", "Revenue 3Y CAGR"),
            ("gross_profit", "Gross Profit"),
            ("gross_margin", "Gross Margin"),
            ("operating_income", "Operating Income"),
            ("operating_margin", "Operating Margin"),
            ("net_income", "Net Income"),
            ("net_margin", "Net Margin"),
            ("ebitda", "EBITDA"),
            ("eps", "EPS"),
            ("eps_growth_yoy", "EPS Growth YoY"),
        ]
        for key, label in income_fields:
            value = income.get(key)
            if value is not None:
                prompt_parts.append(f"- {label}: {value}")

    # Balance Sheet
    balance = financials.get("balance_sheet", {})
    if balance:
        prompt_parts.extend([
            "",
            "## BALANCE SHEET",
        ])
        balance_fields = [
            ("cash_and_equivalents", "Cash & Equivalents"),
            ("total_debt", "Total Debt"),
            ("net_debt", "Net Debt"),
            ("total_assets", "Total Assets"),
            ("total_liabilities", "Total Liabilities"),
            ("total_equity", "Total Equity"),
            ("book_value_per_share", "Book Value/Share"),
            ("tangible_book_value", "Tangible Book Value"),
            ("goodwill", "Goodwill"),
            ("current_ratio", "Current Ratio"),
            ("debt_to_equity", "Debt/Equity"),
            ("debt_to_ebitda", "Debt/EBITDA"),
        ]
        for key, label in balance_fields:
            value = balance.get(key)
            if value is not None:
                prompt_parts.append(f"- {label}: {value}")

    # Cash Flow
    cashflow = financials.get("cash_flow", {})
    if cashflow:
        prompt_parts.extend([
            "",
            "## CASH FLOW STATEMENT",
        ])
        cf_fields = [
            ("operating_cash_flow", "Operating Cash Flow"),
            ("capex", "CapEx"),
            ("free_cash_flow", "Free Cash Flow"),
            ("fcf_margin", "FCF Margin"),
            ("fcf_per_share", "FCF/Share"),
            ("fcf_yield", "FCF Yield"),
            ("dividends_paid", "Dividends Paid"),
            ("buybacks", "Share Buybacks"),
            ("total_shareholder_return", "Total Shareholder Return"),
        ]
        for key, label in cf_fields:
            value = cashflow.get(key)
            if value is not None:
                prompt_parts.append(f"- {label}: {value}")

    # Historical Data
    historical = financials.get("historical", {})
    if historical:
        prompt_parts.extend([
            "",
            "## HISTORICAL DATA (5 Years)",
        ])
        if "revenue_5yr" in historical:
            prompt_parts.append(f"- Revenue History: {historical['revenue_5yr']}")
        if "fcf_5yr" in historical:
            prompt_parts.append(f"- FCF History: {historical['fcf_5yr']}")
        if "eps_5yr" in historical:
            prompt_parts.append(f"- EPS History: {historical['eps_5yr']}")
        if "margins_5yr" in historical:
            margins = historical["margins_5yr"]
            if "gross" in margins:
                prompt_parts.append(f"- Gross Margin History: {margins['gross']}")
            if "operating" in margins:
                prompt_parts.append(f"- Operating Margin History: {margins['operating']}")
            if "fcf" in margins:
                prompt_parts.append(f"- FCF Margin History: {margins['fcf']}")

    # Valuation Multiples
    multiples = financials.get("valuation_multiples", {})
    if multiples:
        prompt_parts.extend([
            "",
            "## CURRENT VALUATION MULTIPLES",
        ])
        mult_fields = [
            ("pe_ratio", "P/E Ratio"),
            ("forward_pe", "Forward P/E"),
            ("peg_ratio", "PEG Ratio"),
            ("ps_ratio", "P/S Ratio"),
            ("pb_ratio", "P/B Ratio"),
            ("ev_ebitda", "EV/EBITDA"),
            ("ev_revenue", "EV/Revenue"),
            ("ev_fcf", "EV/FCF"),
            ("fcf_yield", "FCF Yield"),
            ("dividend_yield", "Dividend Yield"),
        ]
        for key, label in mult_fields:
            value = multiples.get(key)
            if value is not None:
                prompt_parts.append(f"- {label}: {value}")

    # Comparable Companies
    if comparables:
        prompt_parts.extend([
            "",
            "## COMPARABLE COMPANIES",
        ])
        for comp in comparables:
            prompt_parts.append(f"\n### {comp.get('ticker', 'Unknown')} - {comp.get('name', '')}")
            for key, value in comp.items():
                if key not in ["ticker", "name"] and value is not None:
                    prompt_parts.append(f"  - {key}: {value}")

    # Business Segments (for SOTP)
    segments = financials.get("segments", [])
    if segments:
        prompt_parts.extend([
            "",
            "## BUSINESS SEGMENTS",
        ])
        for seg in segments:
            prompt_parts.append(f"\n### {seg.get('name', 'Unknown Segment')}")
            for key, value in seg.items():
                if key != "name" and value is not None:
                    prompt_parts.append(f"  - {key}: {value}")

    # Analyst Estimates
    estimates = financials.get("analyst_estimates", {})
    if estimates:
        prompt_parts.extend([
            "",
            "## ANALYST ESTIMATES",
        ])
        est_fields = [
            ("revenue_next_year", "Revenue Est (Next Year)"),
            ("revenue_growth_est", "Revenue Growth Est"),
            ("eps_next_year", "EPS Est (Next Year)"),
            ("eps_growth_est", "EPS Growth Est"),
            ("target_price_mean", "Mean Price Target"),
            ("target_price_high", "High Price Target"),
            ("target_price_low", "Low Price Target"),
            ("num_analysts", "Number of Analysts"),
        ]
        for key, label in est_fields:
            value = estimates.get(key)
            if value is not None:
                prompt_parts.append(f"- {label}: {value}")

    # Risk-free rate for DCF
    prompt_parts.extend([
        "",
        "## MACRO INPUTS FOR DCF",
        "- Risk-Free Rate (10Y Treasury): ~4.2%",
        "- Equity Risk Premium: 5.5-6.0%",
        "- Corporate Tax Rate: Use company's effective rate",
    ])

    prompt_parts.extend([
        "",
        "---",
        "",
        "Run all five valuation methods on this company.",
        "Triangulate to determine intrinsic value range.",
        "State every assumption explicitly.",
        "Provide a clear verdict: UNDERVALUED, FAIRLY VALUED, or OVERVALUED.",
        "Respond with ONLY valid JSON matching the specified schema.",
    ])

    return "\n".join(prompt_parts)


# Sector to comparable mapping (fallback)
SECTOR_COMPARABLES = {
    "Semiconductors": ["NVDA", "AMD", "QCOM", "TXN", "MRVL", "INTC", "MU"],
    "Technology": ["MSFT", "AAPL", "GOOGL", "META", "CRM", "ORCL", "SAP"],
    "Software": ["MSFT", "CRM", "ORCL", "SAP", "ADBE", "NOW", "SNOW"],
    "Biotechnology": ["AMGN", "GILD", "REGN", "VRTX", "BIIB", "MRNA", "BNTX"],
    "Pharmaceuticals": ["JNJ", "PFE", "MRK", "ABBV", "LLY", "BMY", "AZN"],
    "Healthcare": ["UNH", "CVS", "CI", "HUM", "ELV", "CNC", "MOH"],
    "Financials": ["JPM", "BAC", "WFC", "GS", "MS", "C", "USB"],
    "Consumer": ["AMZN", "WMT", "COST", "TGT", "HD", "LOW", "NKE"],
    "Energy": ["XOM", "CVX", "COP", "SLB", "EOG", "PXD", "MPC"],
    "Industrials": ["CAT", "DE", "HON", "UNP", "UPS", "RTX", "LMT"],
}
