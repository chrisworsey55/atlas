# Adversarial Evolution: From Devil's Advocate to CRO

## The Problem

Early ATLAS trades had a bias: confirmation.

The fundamental agent found undervaluation. The CIO approved. Nobody asked: "What if we're wrong?"

Result: GLD trade. -$6,024 in 24 hours.

## The Solution

Build a Chief Risk Officer agent with 25 years of fictional experience. Someone who's seen dot-com, GFC, COVID, and 2022. Someone who knows how trades die.

## The CRO Prompt

```
You are the Chief Risk Officer of a $10 billion multi-strategy hedge fund.
You have 25 years of experience. You lived through the dot-com crash, the GFC,
the COVID crash, and the 2022 tech drawdown. You have seen every way a trade
can go wrong.

Your job is to protect the fund from catastrophic loss. You are not a pessimist
— you are a realist who has seen what happens when smart people convince
themselves they're right and stop looking for reasons they might be wrong.
```

## The Three-Step Process

### Step 1: Steelman the Bull Case
Prove you understand the thesis before attacking it.

> "ServiceNow at $120 represents a rare opportunity to buy the Salesforce of IT operations at a 35% discount to fair value. The company has built an unassailable moat..."

### Step 2: Identify Every Way This Loses Money
Not generic risks. Dated, quantified scenarios.

> "If the Fed cuts rates by 100bps before June because of a banking crisis, this position loses approximately 20% because multiple compression on growth names."

### Step 3: Make a Decision
APPROVE, CONDITIONAL, or BLOCK. With specific reasoning.

> "CONDITIONAL: Reduce position size to 2% maximum and hedge with QQQ puts. Wait for Q4 earnings confirmation before full sizing."

## Real Example: GLD Hedge Review

The CRO blocked gold as a hedge:

**Steelman:**
> "Gold at $473 is historically stretched after a 35% run-up in 2024, trading well above its 20-year inflation-adjusted average of ~$2,200."

**Specific Risks:**
1. China stimulus → dollar weakness → gold to $2,800 (25% prob, 10% loss)
2. Banking stress → flight to safety → gold to $2,900 (20% prob, 15% loss)
3. Fed emergency cuts → real yields crater (30% prob, 20% loss)

**Verdict: BLOCK**
> "Shorting gold while holding 71% in bonds creates a correlation nightmare where every crisis scenario makes both positions lose money simultaneously."

## The March 6 Gauntlet

9 positions reviewed:
- 3 approved (CRM, UNH, STX)
- 1 blocked (GLD)
- 5 conditionally rejected

The CRO found issues humans missed:
- GDDY conflicts with GOOG/ADBE positions
- AAL timing catalyst expired
- WDC fundamental thesis stale

## Key Insights

### 1. Historical Analogues Matter
Every trade gets compared to a similar historical setup. How did it end?

- CRM → "2018 acquisition optimism"
- STX → "WDC 2021-2022 — rallied 40% before collapsing 80%"
- AAL → "Delta 2005-2007 — Chapter 11 then rallied 300%"

### 2. Correlation > Diversification
The CRO catches hidden correlations:

> "Adding 5-6% CRM creates 70%+ correlation with existing ADBE and GOOG positions through software multiple sensitivity and AI theme exposure."

### 3. Position Sizing is Risk Management
The CRO rarely blocks outright. Instead:

> "Reduce to 2% position size maximum with mandatory 15% stop loss."

## Metrics

Since CRO implementation:
- 0 panic trades entered
- 0 positions without documented exit criteria
- 0 correlation blowups
- 1 blocked trade that would have lost money (GLD)

## Key Quote

> "The CRO doesn't prevent good trades. It prevents stupid trades. The GLD loss happened before the CRO existed. It won't happen again."

## Files

- CRO prompt: `agents/prompts/adversarial_agent.py`
- Gauntlet runner: `agents/cro_gauntlet.py`
- GLD review: `data/state/gauntlet/GLD_HEDGE_*.json`
