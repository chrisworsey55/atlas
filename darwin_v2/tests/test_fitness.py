from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from darwin_v2.config import DarwinConfig
from darwin_v2.embeddings import HashEmbeddingModel, cosine_distance
from darwin_v2.fitness import compute_agent_fitness, score_forecast_probability
from darwin_v2.schema import LineageRecord, ScoredForecast


def _scored(agent_id: str, n: int, prob: float = 0.6, outcome: int = 1) -> list[ScoredForecast]:
    return [
        ScoredForecast(
            agent_id=agent_id,
            role="news_flow",
            generation=0,
            issued_at=datetime.now(timezone.utc),
            regime="bull_low_vol",
            ticker="AAPL",
            direction="up",
            prob=prob,
            horizon_days=5,
            rationale="test",
            outcome=outcome,
            brier=score_forecast_probability(prob, outcome),
        )
        for _ in range(n)
    ]


def test_brier_and_min_sample_gate() -> None:
    agent = LineageRecord(role="news_flow", prompt_yaml="x", embedding=[1.0, 0.0])
    other = LineageRecord(role="news_flow", prompt_yaml="y", embedding=[0.0, 1.0])
    warm = compute_agent_fitness(agent, _scored(agent.id, 29), [agent, other])
    ready = compute_agent_fitness(agent, _scored(agent.id, 30), [agent, other])

    assert warm.eligible is False
    assert ready.eligible is True
    assert round(ready.brier or 0, 4) == 0.16
    assert round(ready.raw_fitness or 0, 4) == -0.16


def test_failed_outputs_penalize_effective_fitness() -> None:
    agent = LineageRecord(role="news_flow", prompt_yaml="x", embedding=[1.0, 0.0], failed_output_count=3)
    other = LineageRecord(role="news_flow", prompt_yaml="y", embedding=[0.0, 1.0])
    fit = compute_agent_fitness(agent, _scored(agent.id, 30), [agent, other], DarwinConfig(novelty_lambda=0.0))
    assert fit.effective_fitness is not None
    assert fit.effective_fitness < fit.raw_fitness


def test_offline_embeddings_are_stable(tmp_path: Path) -> None:
    config = DarwinConfig(embedding_dir=tmp_path)
    model = HashEmbeddingModel(config)
    first = model.embed("base-rate anchored semiconductor analyst")
    second = model.embed("base-rate anchored semiconductor analyst")
    third = model.embed("macro risk cio")

    assert first == second
    assert cosine_distance(first, third) >= 0
