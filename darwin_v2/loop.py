"""Dry-run generation loop for Darwin v2.

This module does not call production data services or live API keys. Forecast
and outcome providers are injected so tests can prove the loop closure without
touching live market data.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from darwin_v2.config import DarwinConfig
from darwin_v2.fitness import compute_agent_fitness, score_forecast_probability
from darwin_v2.lineage import LineageStore
from darwin_v2.mutation import SectionMutator
from darwin_v2.population import Population
from darwin_v2.prompt import validate_agent_output
from darwin_v2.regime import tag_regime
from darwin_v2.schema import ForecastRecord, LineageRecord, ScoredForecast
from darwin_v2.selection import select_generation


ForecastProvider = Callable[[LineageRecord, str], dict]
OutcomeProvider = Callable[[ForecastRecord], int | None]


@dataclass(frozen=True)
class LoopResult:
    role: str
    forecasts_logged: int
    outputs_failed: int
    scored: int
    generation_ran: bool
    children_created: int


class DarwinLoop:
    """Orchestrates dry-run forecast logging, scoring, and generation."""

    def __init__(
        self,
        store: LineageStore,
        mutator: SectionMutator,
        forecast_provider: ForecastProvider,
        outcome_provider: OutcomeProvider,
        config: DarwinConfig | None = None,
    ) -> None:
        self.config = config or DarwinConfig()
        self.store = store
        self.mutator = mutator
        self.forecast_provider = forecast_provider
        self.outcome_provider = outcome_provider

    def run_role_cycle(self, role: str, market_context: str, market_return_21d: float = 0.0, realized_vol_21d: float = 0.15) -> LoopResult:
        forecasts_logged, outputs_failed = self.issue_forecasts(role, market_context, market_return_21d, realized_vol_21d)
        scored = self.score_pending()
        generation_ran = False
        children_created = 0

        population = Population(role, self.store, self.config)
        if population.generation_due():
            fitnesses = [
                compute_agent_fitness(agent, self.store.list_scored_forecasts(agent.id), population.alive(), self.config)
                for agent in population.alive()
            ]
            selection = select_generation(fitnesses, self.config)
            for fit in fitnesses:
                self.store.append_fitness(fit.agent_id, fit.snapshot())
            children = population.evolve(fitnesses, self.mutator, selection)
            generation_ran = True
            children_created = len(children)

        return LoopResult(
            role=role,
            forecasts_logged=forecasts_logged,
            outputs_failed=outputs_failed,
            scored=scored,
            generation_ran=generation_ran,
            children_created=children_created,
        )

    def issue_forecasts(self, role: str, market_context: str, market_return_21d: float, realized_vol_21d: float) -> tuple[int, int]:
        regime = tag_regime(market_return_21d, realized_vol_21d)
        logged = 0
        failed = 0
        for agent in Population(role, self.store, self.config).alive():
            try:
                payload = self.forecast_provider(agent, market_context)
                batch = validate_agent_output(payload, self.config.ticker_universe)
            except Exception:  # noqa: BLE001 - failed output is an explicit fitness penalty.
                agent.failed_output_count += 1
                self.store.update_record(agent)
                failed += 1
                continue

            for forecast in batch.forecasts:
                record = ForecastRecord(
                    agent_id=agent.id,
                    role=agent.role,
                    generation=agent.generation,
                    regime=regime,
                    ticker=forecast.ticker,
                    direction=forecast.direction,
                    prob=forecast.prob,
                    horizon_days=forecast.horizon_days,
                    rationale=forecast.rationale,
                )
                self.store.add_forecast(record)
                logged += 1
            agent.new_forecasts_since_generation += len(batch.forecasts)
            self.store.update_record(agent)
        return logged, failed

    def score_pending(self) -> int:
        scored_count = 0
        for forecast in self.store.list_forecasts(scored=False):
            if not isinstance(forecast, ForecastRecord):
                continue
            outcome = self.outcome_provider(forecast)
            if outcome is None:
                continue
            scored = ScoredForecast(
                **forecast.model_dump(exclude={"scored"}),
                scored=True,
                outcome=outcome,
                brier=score_forecast_probability(forecast.prob, outcome),
            )
            self.store.add_forecast(scored)
            scored_count += 1
        return scored_count
