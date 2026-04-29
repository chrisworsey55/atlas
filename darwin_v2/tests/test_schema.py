from __future__ import annotations

import pytest
from pydantic import ValidationError

from darwin_v2.prompt import FIXED_OUTPUT_SCHEMA
from darwin_v2.schema import ForecastBatch, LineageRecord, PromptSpec


def test_forecast_schema_rejects_extra_and_certainty() -> None:
    with pytest.raises(ValidationError):
        ForecastBatch.model_validate(
            {
                "forecasts": [
                    {
                        "ticker": "AAPL",
                        "direction": "up",
                        "prob": 1.0,
                        "horizon_days": 5,
                        "rationale": "certain",
                        "junk": True,
                    }
                ]
            }
        )


def test_prompt_schema_requires_fixed_sections() -> None:
    prompt = PromptSpec(
        role="A calibrated analyst for semiconductors.",
        framework="Use base rates, current context, and uncertainty to forecast prices.",
        heuristics=["Anchor probabilities away from certainty."],
        examples=[{"input": "NVDA demand shock", "forecast": {"ticker": "NVDA", "direction": "up", "prob": 0.62}}],
        output_schema=FIXED_OUTPUT_SCHEMA,
    )
    assert prompt.output_schema["forecasts"]


def test_lineage_parent_limit() -> None:
    with pytest.raises(ValidationError):
        LineageRecord(
            role="news_flow",
            parent_ids=["a", "b", "c"],
            prompt_yaml="role: test",
        )
