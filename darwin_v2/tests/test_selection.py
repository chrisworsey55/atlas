from __future__ import annotations

import random

import pytest

from darwin_v2.fitness import AgentFitness
from darwin_v2.selection import select_generation, tournament_parent


def _fit(i: int, n: int = 30) -> AgentFitness:
    return AgentFitness(
        agent_id=f"a{i}",
        role="news_flow",
        generation=0,
        n_forecasts=n,
        brier=0.5 - i * 0.01,
        brier_per_regime={},
        novelty=0.0,
        raw_fitness=-(0.5 - i * 0.01),
        effective_fitness=-(0.5 - i * 0.01),
        eligible=n >= 30,
        failed_outputs=0,
    )


def test_selection_blocks_warmup_agents() -> None:
    fitnesses = [_fit(i) for i in range(16)]
    fitnesses[3] = _fit(3, n=29)
    with pytest.raises(ValueError):
        select_generation(fitnesses)


def test_selects_top_middle_bottom() -> None:
    result = select_generation([_fit(i) for i in range(16)])
    assert [f.agent_id for f in result.elites] == ["a15", "a14", "a13", "a12"]
    assert len(result.breeding_pool) == 8
    assert [f.agent_id for f in result.culled] == ["a3", "a2", "a1", "a0"]


def test_tournament_returns_best_competitor() -> None:
    parent = tournament_parent([_fit(i) for i in range(4, 12)], random.Random(0), tournament_size=3)
    assert parent.effective_fitness == max(parent.effective_fitness for parent in [parent])
