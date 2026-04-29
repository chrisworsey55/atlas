from __future__ import annotations

import random
from pathlib import Path

from darwin_v2.config import DarwinConfig
from darwin_v2.lineage import LineageStore
from darwin_v2.loop import DarwinLoop
from darwin_v2.mutation import SectionMutator
from darwin_v2.population import Population
from darwin_v2.prompt import build_prompt, dump_prompt_yaml
from darwin_v2.schema import ForecastRecord, LineageRecord


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
            role=f"A calibrated risk analyst variant {i}.",
            framework=f"Use base rates, regime context, and uncertainty variant {i}.",
            heuristics=["Avoid certainty.", f"Variant rule {i}."],
            examples=[{"input": "market context", "forecast": {"ticker": "AAPL", "direction": "up", "prob": 0.55}}],
        )
    )


def test_loop_end_to_end_generation_with_mocked_llm(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    store = LineageStore(cfg)
    Population("risk_cio", store, cfg, rng=random.Random(1)).seed([_prompt(i) for i in range(16)])

    def forecast_provider(agent: LineageRecord, context: str) -> dict:
        return {
            "forecasts": [
                {
                    "ticker": "AAPL",
                    "direction": "up",
                    "prob": 0.6,
                    "horizon_days": 5,
                    "rationale": f"mock {i}",
                }
                for i in range(30)
            ]
        }

    def outcome_provider(forecast: ForecastRecord) -> int:
        return 1

    def rewrite(section: str, directive: str, request: str) -> str:
        return "framework: Mutated dry-run framework with calibrated base-rate anchoring.\n"

    loop = DarwinLoop(
        store=store,
        mutator=SectionMutator(rewrite, random.Random(2)),
        forecast_provider=forecast_provider,
        outcome_provider=outcome_provider,
        config=cfg,
    )
    result = loop.run_role_cycle("risk_cio", "same market context for every agent")

    assert result.forecasts_logged == 16 * 30
    assert result.scored == 16 * 30
    assert result.generation_ran is True
    assert result.children_created == 4
    assert len(Population("risk_cio", store, cfg).alive()) == 16
