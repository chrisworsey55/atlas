# ATLAS Decision Process

## The 4-Step Gauntlet

Every trade must pass through four stages before execution:

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│ FUNDAMENTAL │ -> │   SECTOR    │ -> │     CRO     │ -> │     CIO     │
│   CHECK     │    │  CATALYST   │    │   REVIEW    │    │   SIZING    │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

## Stage 1: Fundamental Check

**Purpose:** Confirm or refute valuation thesis at current prices

**Inputs:**
- Current price
- Financial statements
- Historical performance
- Peer comparisons

**Outputs:**
- Intrinsic value estimate
- Upside/downside percentage
- Confidence level (0-100)
- Key risks and catalysts

**Example:**
```json
{
  "ticker": "CRM",
  "current_price": 201.39,
  "intrinsic_value": 280,
  "upside_pct": 39.0,
  "confidence": 82,
  "verdict": "UNDERVALUED"
}
```

## Stage 2: Sector Catalyst

**Purpose:** Identify specific catalyst with timing

**Inputs:**
- Fundamental thesis
- Sector dynamics
- Upcoming events (earnings, conferences, regulatory)

**Outputs:**
- Primary catalyst description
- Expected timing
- Probability of catalyst materialising
- Expected price impact

**Example:**
```json
{
  "primary_catalyst": "Q4 FY25 earnings showing Agentforce adoption",
  "catalyst_timing": "March 2025",
  "expected_impact": "15-20% upward move",
  "catalyst_probability": 75
}
```

## Stage 3: CRO Review

**Purpose:** Find every way the trade loses money

**Process:**
1. Steelman the bull/bear case
2. Identify specific, dated loss scenarios
3. Find historical analogue
4. Assess correlation with existing positions
5. Make verdict: APPROVE / CONDITIONAL / BLOCK

**Key Questions:**
- What does the market know that we're ignoring?
- How did similar setups end historically?
- What happens if we're wrong about everything?

**Example:**
```json
{
  "steelman": "Salesforce at $201 represents compelling value...",
  "specific_risks": [
    {
      "scenario": "Agentforce adoption below 15%",
      "probability": "35%",
      "impact": "18-22% loss"
    }
  ],
  "historical_analogue": "CRM 2018 Tableau acquisition",
  "verdict": "CONDITIONAL",
  "conditions": "Size at 3% not 5-6%"
}
```

## Stage 4: CIO Sizing

**Purpose:** Determine position size given portfolio context

**Constraints:**
- Max single position: 10%
- Max sector: 30%
- Min cash buffer: 10%
- Must honour CRO verdict

**Inputs:**
- Fundamental case
- Catalyst
- CRO verdict and conditions
- Current portfolio composition

**Outputs:**
- Approved (yes/no)
- Position size (%)
- Entry strategy
- Stop loss level
- Rebalancing requirements

**Example:**
```json
{
  "approved": true,
  "position_size_pct": 3.0,
  "entry_strategy": "wait for pullback",
  "stop_loss_pct": -15,
  "rebalancing_required": "Trim BIL from 61% to 58%"
}
```

## Decision Outcomes

### APPROVE
Trade executed immediately at specified size.

### CONDITIONAL
Trade approved with modifications:
- Reduced size
- Stop loss required
- Hedges required
- Wait for catalyst

### BLOCK
Trade rejected entirely. Documented for future reference.

### REJECT
Trade rejected due to:
- Stale catalyst timing
- Conflict with existing positions
- Constraint violations

## Memory Integration

Before making any decision, agents review:

1. **Open positions** in `data/trade_journal/open/`
   - Current thesis status
   - Performance to date
   - Correlation considerations

2. **Closed positions** in `data/trade_journal/closed/`
   - Lessons learned
   - Mistakes to avoid
   - Similar setups that failed

## Example: GLD Block

The GLD hedge was blocked because:

1. **CRO found correlation trap:**
   > "71% in bonds + gold short = both lose in crisis"

2. **Historical analogue:**
   > "Gold 2011 peak took 3 years to mean revert"

3. **Trade journal reference:**
   > "GLD_LONG_20260302 lost $6,024 panic buying"

Result: BLOCK. No position entered.
