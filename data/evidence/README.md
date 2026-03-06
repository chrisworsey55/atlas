# ATLAS Evidence Base

This is the LP-facing evidence base. Clean, formatted, designed to be shared.

## Purpose

Provide concrete evidence that ATLAS works:
- System finds mispriced securities before catalysts
- Risk management prevents catastrophic losses
- Autonomous execution scales without human intervention
- Cost structure is sustainable at scale

## Structure

```
evidence/
├── sp500_screen_results.md       # Full S&P 500 valuation screen
├── agent_gauntlet_examples/      # Real-time agent decision examples
├── portfolio_performance/        # Returns, attribution, equity curve
├── system_architecture/          # How ATLAS works
└── key_moments/                  # Highlight trades that prove the system
```

## Key Evidence Pieces

### 1. AVGO: The Trade That Proved the System
Fundamental agent screened 162 companies, ranked AVGO #1, autonomous agent executed, two days later Broadcom reported biggest earnings beat of the quarter. Agent didn't know earnings were coming. It found the mispricing.

### 2. GLD: The Lesson That Shaped the System
Manual trade entered without agent swarm. Lost $6,024 in one day. Now used as counter-example: "Here's what happens without the system vs with the system."

### 3. S&P 500 Complete Screen
522 companies analysed. 179 undervalued, 248 fairly valued, 95 overvalued. Cost: ~$80 in API calls. Time: 7 hours. Human equivalent: 50+ analyst hours.

### 4. CRO Gauntlet
9 positions reviewed through 4-step adversarial process. 3 approved, 1 blocked, 5 conditionally rejected. System catches what humans miss.

## How to Use

- **For LPs:** Start with key_moments/ for highlight reel
- **For technical due diligence:** See system_architecture/
- **For performance:** See portfolio_performance/
- **For methodology:** See agent_gauntlet_examples/
