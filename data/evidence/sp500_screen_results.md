# S&P 500 Fundamental Screen Results

**Date:** March 5-6, 2026
**Coverage:** 522 companies analysed
**Cost:** ~$80 in API calls
**Time:** 7 hours (autonomous)

## Summary Statistics

| Category | Count | % of Total |
|----------|-------|------------|
| **Undervalued** | 179 | 34% |
| **Fairly Valued** | 248 | 48% |
| **Overvalued** | 95 | 18% |
| **Total Analysed** | 522 | 100% |

## Top 15 Most Undervalued

| Rank | Ticker | Price | Fair Value | Upside | Confidence |
|------|--------|-------|------------|--------|------------|
| 1 | AVGO | $318 | $500 | +59.3% | 85% |
| 2 | NOW | $120 | $185 | +53.7% | 82% |
| 3 | APO | $111 | $163 | +52.2% | 82% |
| 4 | GDDY | $93 | $125 | +40.1% | 82% |
| 5 | CRM | $201 | $280 | +39.0% | 82% |
| 6 | ADBE | $282 | $385 | +36.7% | 70% |
| 7 | GOOGL | $168 | $222 | +32.1% | 85% |
| 8 | GOOG | $169 | $223 | +31.9% | 82% |
| 9 | ANET | $104 | $134 | +29.4% | 82% |
| 10 | UNH | $289 | $373 | +29.2% | 82% |
| 11 | META | $592 | $750 | +26.7% | 78% |
| 12 | MSFT | $412 | $515 | +25.0% | 80% |
| 13 | ORCL | $168 | $205 | +22.0% | 75% |
| 14 | COP | $108 | $130 | +20.4% | 72% |
| 15 | CVX | $154 | $185 | +20.1% | 70% |

## Top 15 Most Overvalued

| Rank | Ticker | Price | Fair Value | Downside | Confidence |
|------|--------|-------|------------|----------|------------|
| 1 | STX | $367 | $105 | -71.4% | 92% |
| 2 | TSLA | $285 | $158 | -44.5% | 85% |
| 3 | GLW | $135 | $85 | -42.4% | 85% |
| 4 | AAL | $12 | $7 | -40.2% | 85% |
| 5 | WDC | $259 | $163 | -37.1% | 85% |
| 6 | NFLX | $925 | $650 | -29.7% | 78% |
| 7 | PLTR | $82 | $58 | -29.3% | 72% |
| 8 | COIN | $245 | $175 | -28.6% | 70% |
| 9 | SNOW | $168 | $125 | -25.6% | 68% |
| 10 | CRWD | $365 | $280 | -23.3% | 72% |
| 11 | MSTR | $295 | $230 | -22.0% | 65% |
| 12 | SHOP | $108 | $85 | -21.3% | 70% |
| 13 | DDOG | $132 | $105 | -20.5% | 68% |
| 14 | NET | $118 | $95 | -19.5% | 65% |
| 15 | ZS | $205 | $168 | -18.0% | 68% |

## Methodology

Each company analysed through:

1. **DCF Valuation**
   - 5-year revenue projections
   - Margin expansion/contraction analysis
   - WACC calculation (risk-free + equity risk premium + beta)
   - Terminal value (perpetuity growth method)
   - Three scenarios: bull, base, bear

2. **Comparable Analysis**
   - EV/EBITDA multiples
   - P/E ratios
   - EV/Revenue for high-growth companies
   - Peer group selection by sector and size

3. **Synthesis**
   - Weight DCF 60%, comps 40%
   - Confidence based on:
     - Data quality
     - Business model predictability
     - Analyst coverage depth
     - Historical accuracy of projections

## Key Insights

### 1. AI Infrastructure Undervalued
AVGO, ANET, and AMD screen as undervalued despite AI rally. Market pricing in competition risk that may not materialise.

### 2. Enterprise Software Cheap
NOW, CRM, ADBE all show 30%+ upside. Market sceptical of AI monetisation timelines.

### 3. Storage Overvalued
STX (+71% overvalued) and WDC (+37% overvalued) trading at cyclical peak multiples. Memory/storage cycle turning.

### 4. Healthcare Underappreciated
UNH screens as undervalued. Market treating as insurance play, missing Optum transformation.

## Positions Taken

From this screen, ATLAS entered:
- AVGO: 5% (rank #1, +59% upside)
- CRM: 3% (rank #5, +39% upside)
- UNH: 3.5% (rank #10, +29% upside)
- STX SHORT: 2% (rank #1 overvalued, -71% downside)

## Cost Analysis

| Item | Cost |
|------|------|
| API calls (522 companies) | ~$80 |
| Time (autonomous) | 7 hours |
| Human equivalent | 50+ analyst hours |
| Traditional research cost | $100,000+ |

**Cost per company analysed:** $0.15

## Files

- Raw results: `data/state/sp500_valuations.json`
- Ticker list: `data/sp500_tickers.txt`
- Fundamental agent: `agents/fundamental_agent.py`
