# ATLAS Cost Structure

## API Costs

### Claude API (Anthropic)

| Operation | Cost | Frequency |
|-----------|------|-----------|
| Fundamental screen (1 company) | ~$0.15 | Per company |
| Sector desk analysis | ~$0.25 | Per analysis |
| CRO gauntlet review | ~$0.50 | Per trade |
| CIO decision | ~$0.10 | Per decision |

### Examples

**S&P 500 Screen (522 companies):**
- API calls: ~$80
- Time: 7 hours (autonomous)
- Human equivalent: 50+ analyst hours
- Traditional cost: $100,000+

**Full CRO Gauntlet (9 positions):**
- 4 steps × 9 tickers = 36 API calls
- Total cost: ~$15
- Time: 8 minutes
- Human equivalent: 4+ hours of risk committee

**Single Trade (full process):**
- Fundamental: $0.15
- Catalyst: $0.25
- CRO: $0.50
- CIO: $0.10
- **Total: ~$1.00 per trade**

## Data Costs

| Source | Cost | Notes |
|--------|------|-------|
| SEC EDGAR | Free | Public API, no key required |
| yfinance | Free | Yahoo Finance wrapper |
| 13F data | Free | Via edgartools library |

**Total data cost: $0**

## Infrastructure

### Azure VM

| Item | Cost |
|------|------|
| B2s VM (2 vCPU, 4GB) | ~$30/month |
| Storage (128GB) | ~$5/month |
| **Total** | ~$35/month |

### GitHub

| Item | Cost |
|------|------|
| Repository | Free |
| Actions (if used) | Free tier |

## Monthly Operating Cost

Assuming:
- 50 trades analysed per month
- 10 trades executed
- 1 full S&P 500 screen per month
- Daily portfolio monitoring

| Item | Monthly Cost |
|------|--------------|
| Trade analysis (50 × $1) | $50 |
| S&P 500 screen | $80 |
| Daily monitoring (30 × $2) | $60 |
| Azure infrastructure | $35 |
| **Total** | ~$225/month |

## Cost Comparison

### Traditional Hedge Fund

| Item | Annual Cost |
|------|-------------|
| Bloomberg terminal (2 seats) | $48,000 |
| Research subscriptions | $50,000+ |
| Analyst salary (1 FTE) | $200,000+ |
| Risk management systems | $100,000+ |
| **Total** | $400,000+ |

### ATLAS

| Item | Annual Cost |
|------|-------------|
| API costs | ~$2,000 |
| Infrastructure | ~$400 |
| **Total** | ~$2,400 |

**Cost reduction: 99.4%**

## Scaling Economics

### At $1M AUM
- Monthly cost: $225
- Cost as % of AUM: 0.027% annually
- Equivalent to: 0.27 bps

### At $10M AUM
- Monthly cost: ~$500 (more trades)
- Cost as % of AUM: 0.006% annually
- Equivalent to: 0.6 bps

### At $100M AUM
- Monthly cost: ~$2,000
- Cost as % of AUM: 0.002% annually
- Equivalent to: 0.24 bps

The cost structure is largely fixed, making it highly scalable.

## Key Insight

> "Screening 522 companies costs $80. A single Goldman Sachs research report costs $10,000+. The 125x cost advantage is why this works."

## Files

- API configuration: `config/settings.py`
- Usage tracking: (future) `data/state/api_usage.json`
