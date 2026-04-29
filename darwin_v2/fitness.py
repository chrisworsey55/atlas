"""Fitness, Brier scoring, and novelty calculations."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from darwin_v2.config import DarwinConfig
from darwin_v2.embeddings import cosine_distance
from darwin_v2.schema import FitnessSnapshot, LineageRecord, RegimeTag, ScoredForecast


@dataclass(frozen=True)
class AgentFitness:
    agent_id: str
    role: str
    generation: int
    n_forecasts: int
    brier: float | None
    brier_per_regime: dict[RegimeTag, float]
    novelty: float
    raw_fitness: float | None
    effective_fitness: float | None
    eligible: bool
    failed_outputs: int

    def snapshot(self) -> FitnessSnapshot:
        return FitnessSnapshot(
            generation=self.generation,
            n_forecasts=self.n_forecasts,
            brier=self.brier,
            brier_per_regime=self.brier_per_regime,
            novelty=self.novelty,
            raw_fitness=self.raw_fitness,
            effective_fitness=self.effective_fitness,
            failed_outputs=self.failed_outputs,
        )


def brier_score(scored: list[ScoredForecast]) -> float | None:
    if not scored:
        return None
    return sum(item.brier for item in scored) / len(scored)


def score_forecast_probability(prob: float, outcome: int) -> float:
    if outcome not in (0, 1):
        raise ValueError("outcome must be 0 or 1")
    return (prob - outcome) ** 2


def brier_by_regime(scored: list[ScoredForecast]) -> dict[RegimeTag, float]:
    grouped: dict[RegimeTag, list[ScoredForecast]] = defaultdict(list)
    for item in scored:
        grouped[item.regime].append(item)
    return {regime: brier_score(items) or 0.0 for regime, items in grouped.items()}


def novelty(agent: LineageRecord, population: list[LineageRecord], k: int = 5) -> float:
    neighbours = [other for other in population if other.id != agent.id and other.embedding]
    if not agent.embedding or not neighbours:
        return 0.0
    distances = sorted(cosine_distance(agent.embedding, other.embedding) for other in neighbours)
    nearest = distances[: min(k, len(distances))]
    return sum(nearest) / len(nearest) if nearest else 0.0


def compute_agent_fitness(
    agent: LineageRecord,
    scored_forecasts: list[ScoredForecast],
    population: list[LineageRecord],
    config: DarwinConfig | None = None,
) -> AgentFitness:
    cfg = config or DarwinConfig()
    n = len(scored_forecasts)
    brier = brier_score(scored_forecasts)
    novelty_value = novelty(agent, population)
    raw = -brier if brier is not None else None
    effective = raw + cfg.novelty_lambda * novelty_value if raw is not None else None
    if effective is not None and agent.failed_output_count:
        effective -= agent.failed_output_count / max(cfg.min_scored_forecasts, n or 1)

    return AgentFitness(
        agent_id=agent.id,
        role=agent.role,
        generation=agent.generation,
        n_forecasts=n,
        brier=brier,
        brier_per_regime=brier_by_regime(scored_forecasts),
        novelty=novelty_value,
        raw_fitness=raw,
        effective_fitness=effective,
        eligible=n >= cfg.min_scored_forecasts,
        failed_outputs=agent.failed_output_count,
    )
