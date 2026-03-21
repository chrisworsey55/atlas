# ATLAS Autoresearch Protocol

Autonomous prompt optimization for 25-agent investment swarm.

## Overview

This system implements Karpathy's autoresearch pattern for continuous self-improvement of trading agent prompts. The loop runs indefinitely, mutating prompts, evaluating performance, and keeping improvements.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    IMMUTABLE LAYER                          │
│  backtest.py — scoring against actual market outcomes       │
│  eod_cycle.py — agent orchestration (DO NOT MODIFY)         │
│  prompt_loader.py — prompt loading (DO NOT MODIFY)          │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                    MUTABLE LAYER                            │
│  agents/prompts/*.md — 68 trained prompts                   │
│  These are the ONLY files the loop modifies                 │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                    METRICS                                  │
│  sharpe_30d — primary keep/revert decision metric           │
│  hit_rate — % of profitable recommendations                 │
│  rolling_sharpe — per-agent performance tracking            │
└─────────────────────────────────────────────────────────────┘
```

## Files

| File | Purpose |
|------|---------|
| `loop.py` | Main autonomous loop |
| `fast_cycle.py` | Speed-optimized agent runner (3-5 API calls vs 20) |
| `backtest.py` | Immutable scorer |
| `attribution.py` | Per-agent performance tracking |
| `mutator.py` | Prompt mutation engine |
| `experiments.tsv` | Experiment log |
| `alerts.log` | Safety alerts |
| `results/agent_scores.json` | Agent performance data |

## The Loop

```
SETUP:
1. Create git branch: autoresearch/{date_tag}
2. Run full baseline cycle
3. Score baseline
4. Record in experiments.tsv

LOOP FOREVER:
1. Identify worst agent by rolling Sharpe
2. Generate prompt mutation
3. Git commit the change
4. Run fast cycle (only reruns mutated agent + decision layer)
5. Score with backtest
6. If sharpe improved: KEEP commit
   Else: git reset --hard HEAD~1
7. Log result
8. Repeat
```

## Mutation Types

The mutator cycles through these strategies:

| Type | Description |
|------|-------------|
| `refine` | Adjust thresholds, criteria, analytical focus |
| `restructure` | Reorder sections, change reasoning flow |
| `simplify` | Make prompt shorter while preserving intent |
| `expand` | Add analytical dimension that's missing |
| `combine` | Incorporate approach from successful experiments |

## Speed Optimization

The fast_cycle reduces API calls by caching layer outputs:

| Scenario | Full Cycle | Fast Cycle |
|----------|------------|------------|
| Layer 2 mutation | 20 calls | 5 calls |
| Layer 3 mutation | 20 calls | 4 calls |

Layer outputs are cached per session. Only the mutated agent and Layer 4 (decision) are rerun.

## Agent Layers

- **Layer 1 Data (2):** news_sentiment, institutional_flow
- **Layer 2 Sector (10):** bond, currency, commodities, metals, semiconductor, biotech, energy, consumer, industrials, microcap
- **Layer 3 Superinvestor (4):** druckenmiller, aschenbrenner, baker, ackman
- **Layer 4 Decision (4):** cro, alpha_discovery, autonomous_execution, cio

## Constraints

- Prompts must preserve JSON output format
- Prompts must preserve conviction scoring (0-100)
- Prompts must preserve agent identity section
- Maximum 2000 tokens per prompt
- Agent weights: min 0.3, max 2.5

## Alerts

The loop writes to `alerts.log` (but doesn't stop) when:
- 50 consecutive experiments with no improvement
- Any backtest shows sharpe below -1.0
- Any prompt exceeds 2000 tokens after mutation
- Any agent's weight drops below 0.3

## Running

```bash
# Start the autonomous loop (runs forever)
python3 -m autoresearch.loop

# Run one experiment only (for testing)
python3 -m autoresearch.loop --once

# Run baseline only
python3 -m autoresearch.fast_cycle --baseline

# Run fast cycle for specific agent
python3 -m autoresearch.fast_cycle semiconductor

# Run backtest on current views
python3 -m autoresearch.backtest

# Check agent rankings
python3 -m autoresearch.attribution
```

## Experiment Log Format

`experiments.tsv` columns:
```
commit    sharpe_30d    agent    mutation_type    status    description    prompt_tokens    timestamp
```

Status values:
- `baseline` — initial baseline measurement
- `keep` — improvement, commit kept
- `discard` — no improvement, commit reverted
- `crash` — error occurred, commit reverted

## Design Principles

1. **Immutable evaluation**: backtest.py never changes. This is the ground truth.

2. **Atomic experiments**: Each mutation is a single git commit. Easy to revert.

3. **Session consistency**: Same evaluation window within a session. Experiments are comparable.

4. **Darwinian selection**: Bad prompts get reverted. Good prompts survive.

5. **Continuous operation**: Loop runs until killed. No human approval needed.

See `loop.py` for implementation.
See `experiments.tsv` for full history.
