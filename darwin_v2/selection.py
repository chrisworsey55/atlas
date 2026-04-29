"""Selection logic for Darwin v2 populations."""

from __future__ import annotations

import random
from dataclasses import dataclass

from darwin_v2.config import DarwinConfig
from darwin_v2.fitness import AgentFitness


@dataclass(frozen=True)
class SelectionResult:
    elites: list[AgentFitness]
    breeding_pool: list[AgentFitness]
    culled: list[AgentFitness]


def assert_generation_ready(fitnesses: list[AgentFitness], config: DarwinConfig | None = None) -> None:
    cfg = config or DarwinConfig()
    if len(fitnesses) != cfg.agents_per_role:
        raise ValueError(f"Expected {cfg.agents_per_role} agents, got {len(fitnesses)}")
    not_ready = [f.agent_id for f in fitnesses if not f.eligible or f.n_forecasts < cfg.min_scored_forecasts]
    if not_ready:
        raise ValueError(f"Selection blocked: agents below {cfg.min_scored_forecasts} scored forecasts: {not_ready}")


def rank_by_effective_fitness(fitnesses: list[AgentFitness]) -> list[AgentFitness]:
    if any(f.effective_fitness is None for f in fitnesses):
        missing = [f.agent_id for f in fitnesses if f.effective_fitness is None]
        raise ValueError(f"Missing effective fitness for agents: {missing}")
    return sorted(fitnesses, key=lambda f: f.effective_fitness or float("-inf"), reverse=True)


def select_generation(fitnesses: list[AgentFitness], config: DarwinConfig | None = None) -> SelectionResult:
    cfg = config or DarwinConfig()
    assert_generation_ready(fitnesses, cfg)
    ranked = rank_by_effective_fitness(fitnesses)
    elites = ranked[: cfg.elites_per_generation]
    culled = ranked[-cfg.culled_per_generation :]
    breeding_pool = ranked[cfg.elites_per_generation : cfg.agents_per_role - cfg.culled_per_generation]
    return SelectionResult(elites=elites, breeding_pool=breeding_pool, culled=culled)


def tournament_parent(
    breeding_pool: list[AgentFitness],
    rng: random.Random | None = None,
    tournament_size: int = 3,
) -> AgentFitness:
    if len(breeding_pool) < tournament_size:
        raise ValueError("Breeding pool smaller than tournament size")
    rand = rng or random.Random()
    competitors = rand.sample(breeding_pool, tournament_size)
    return rank_by_effective_fitness(competitors)[0]
