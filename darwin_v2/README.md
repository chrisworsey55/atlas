# ATLAS Darwin v2

Darwin v2 is a dry-run rebuild of ATLAS prompt evolution. It does not replace `autoresearch/`, does not touch production cron jobs, and does not execute trades.

## Architecture

- `schema.py` defines strict Pydantic models for prompts, forecasts, scored outcomes, mutation logs, and lineage records.
- `prompt.py` loads and validates five-section YAML prompts: `role`, `framework`, `heuristics`, `examples`, `output_schema`.
- `lineage.py` stores a queryable SQLite index plus diffable JSON records under `darwin_v2/lineage/`.
- `fitness.py` computes Brier score, per-regime diagnostics, failed-output penalties, and novelty-adjusted effective fitness.
- `embeddings.py` uses deterministic offline hashing embeddings. No API call is made for novelty.
- `selection.py` enforces the non-negotiable 30 scored forecast minimum, then preserves top 4, culls bottom 4, and exposes tournament parent selection from the middle 8.
- `mutation.py` mutates one prompt section through an injected LLM rewrite function. Tests mock this call.
- `population.py` manages one independently evolving role population.
- `loop.py` is a dry-run orchestrator with injected forecast and outcome providers.

## Running A Generation

Seed prompts first:

```bash
python3 -m darwin_v2.seed_populations
```

Run tests:

```bash
python3 -m pytest darwin_v2/tests
```

`loop.py` is intentionally provider-injected. A real runner must supply:

- `forecast_provider(agent, market_context) -> dict`
- `outcome_provider(forecast) -> 0 | 1 | None`
- `SectionMutator(llm_rewrite=...)`

Selection will raise instead of running if any of the 16 agents has fewer than 30 scored forecasts.

## Inspecting Lineage

SQLite index:

```bash
sqlite3 darwin_v2/lineage/lineage.sqlite 'select id, role, generation, status from lineage;'
```

Full JSON records:

```bash
ls darwin_v2/lineage/prompts/
```

Embeddings:

```bash
ls darwin_v2/lineage/embeddings/
```

Forecasts are also persisted in SQLite. Fitness numbers are reproducible from the stored `forecasts` rows.

## Stubbed For v2.1

- `crossover.py` raises `NotImplementedError`.
- `example_evolution.py` raises `NotImplementedError`.
- SIMONS regime integration is deferred. `regime.py` provides a four-bucket placeholder from supplied market return and volatility.

## Known Limitations

- Offline hash embeddings are stable and cheap, but they are lexical, not semantic.
- The seed script creates deterministic hand-varied prompts from legacy prompt excerpts. It does not ask an LLM to rewrite seeds.
- Outcome scoring is provider-injected. Live price integration is deliberately absent until review.
- Overall fitness drives selection. Per-regime fitness is diagnostic only until enough regime-specific samples exist.
