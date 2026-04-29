from __future__ import annotations

import random
from pathlib import Path

from darwin_v2.config import DarwinConfig
from darwin_v2.fitness import AgentFitness
from darwin_v2.lineage import LineageStore
from darwin_v2.mutation import SectionMutator
from darwin_v2.population import Population
from darwin_v2.prompt import build_prompt, dump_prompt_yaml


def _config(tmp_path: Path) -> DarwinConfig:
    return DarwinConfig(
        lineage_dir=tmp_path,
        lineage_db=tmp_path / "lineage.sqlite",
        prompt_dir=tmp_path / "prompts",
        embedding_dir=tmp_path / "embeddings",
    )


def _prompt(i: int) -> str:
    return dump_prompt_yaml(
        build_prompt(
            role=f"A calibrated news-flow analyst variant {i}.",
            framework=f"Use base rates and context variant {i} to forecast directional moves.",
            heuristics=[f"Rule {i}: avoid certainty.", "Keep probabilities calibrated."],
            examples=[{"input": f"event {i}", "forecast": {"ticker": "AAPL", "direction": "up", "prob": 0.55}}],
        )
    )


def _fit(agent_id: str, i: int) -> AgentFitness:
    return AgentFitness(
        agent_id=agent_id,
        role="news_flow",
        generation=0,
        n_forecasts=30,
        brier=0.4 - i * 0.001,
        brier_per_regime={},
        novelty=0.0,
        raw_fitness=-(0.4 - i * 0.001),
        effective_fitness=-(0.4 - i * 0.001),
        eligible=True,
        failed_outputs=0,
    )


def test_population_seed_and_evolve(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    store = LineageStore(cfg)
    population = Population("news_flow", store, cfg, rng=random.Random(2))
    seeded = population.seed([_prompt(i) for i in range(16)])
    assert len(seeded) == 16

    def llm(section: str, directive: str, request: str) -> str:
        return "framework: Mutated framework with explicit uncertainty and base-rate anchoring.\n"

    fitnesses = [_fit(record.id, i) for i, record in enumerate(seeded)]
    children = population.evolve(fitnesses, SectionMutator(llm, random.Random(3)))
    assert len(children) == 4
    assert all(child.parent_ids for child in children)
    assert len(population.alive()) == 16
