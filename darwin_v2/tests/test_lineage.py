from __future__ import annotations

from pathlib import Path

from darwin_v2.config import DarwinConfig
from darwin_v2.lineage import LineageStore
from darwin_v2.schema import FitnessSnapshot, ForecastRecord, LineageRecord, ScoredForecast


def test_lineage_round_trip(tmp_path: Path) -> None:
    config = DarwinConfig(
        lineage_dir=tmp_path,
        lineage_db=tmp_path / "lineage.sqlite",
        prompt_dir=tmp_path / "prompts",
        embedding_dir=tmp_path / "embeddings",
    )
    store = LineageStore(config)
    record = LineageRecord(
        role="news_flow",
        prompt_yaml="role: test\nframework: test",
        embedding=[0.1, 0.2],
    )

    store.add_record(record)
    loaded = store.get_record(record.id)
    assert loaded.id == record.id
    assert loaded.embedding == [0.1, 0.2]

    store.append_fitness(record.id, FitnessSnapshot(generation=0, n_forecasts=30, brier=0.2, raw_fitness=-0.2))
    updated = store.get_record(record.id)
    assert updated.fitness_history[0].n_forecasts == 30


def test_lineage_status_query(tmp_path: Path) -> None:
    config = DarwinConfig(
        lineage_dir=tmp_path,
        lineage_db=tmp_path / "lineage.sqlite",
        prompt_dir=tmp_path / "prompts",
        embedding_dir=tmp_path / "embeddings",
    )
    store = LineageStore(config)
    alive = LineageRecord(role="risk_cio", prompt_yaml="x", embedding=[])
    culled = LineageRecord(role="risk_cio", prompt_yaml="y", embedding=[], status="culled")
    store.bulk_add([alive, culled])

    records = store.list_alive("risk_cio")
    assert [r.id for r in records] == [alive.id]


def test_forecast_persistence(tmp_path: Path) -> None:
    config = DarwinConfig(
        lineage_dir=tmp_path,
        lineage_db=tmp_path / "lineage.sqlite",
        prompt_dir=tmp_path / "prompts",
        embedding_dir=tmp_path / "embeddings",
    )
    store = LineageStore(config)
    forecast = ForecastRecord(
        agent_id="agent-1",
        role="news_flow",
        generation=0,
        regime="bull_low_vol",
        ticker="AAPL",
        direction="up",
        prob=0.6,
        horizon_days=5,
        rationale="test",
    )
    store.add_forecast(forecast)
    assert len(store.list_forecasts(agent_id="agent-1", scored=False)) == 1

    scored = ScoredForecast(**forecast.model_dump(exclude={"scored"}), scored=True, outcome=1, brier=0.16)
    store.add_forecast(scored)
    assert len(store.list_scored_forecasts("agent-1")) == 1
