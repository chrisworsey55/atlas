"""Prompt YAML load/save/validation utilities."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from darwin_v2.config import DEFAULT_TICKERS
from darwin_v2.schema import ForecastBatch, PROMPT_SECTIONS, PromptSpec


FIXED_OUTPUT_SCHEMA: dict[str, Any] = {
    "forecasts": [
        {
            "ticker": "str",
            "direction": "up|down",
            "prob": "float_gt_0_lt_1",
            "horizon_days": "1|5|10|21",
            "rationale": "str",
        }
    ]
}


def parse_prompt_yaml(text: str) -> PromptSpec:
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("Prompt YAML must parse to a mapping.")
    keys = set(data.keys())
    expected = set(PROMPT_SECTIONS)
    if keys != expected:
        raise ValueError(f"Prompt YAML must contain exactly {PROMPT_SECTIONS}; got {sorted(keys)}")
    return PromptSpec.model_validate(data)


def dump_prompt_yaml(prompt: PromptSpec) -> str:
    data = prompt.model_dump(mode="json")
    ordered = {key: data[key] for key in PROMPT_SECTIONS}
    return yaml.safe_dump(ordered, sort_keys=False, allow_unicode=False)


def load_prompt(path: Path) -> PromptSpec:
    return parse_prompt_yaml(path.read_text())


def save_prompt(path: Path, prompt: PromptSpec) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_prompt_yaml(prompt))


def validate_agent_output(payload: str | dict[str, Any], ticker_universe: set[str] | frozenset[str] = DEFAULT_TICKERS) -> ForecastBatch:
    if isinstance(payload, str):
        data = yaml.safe_load(payload)
    else:
        data = payload
    batch = ForecastBatch.model_validate(data)
    invalid = [forecast.ticker for forecast in batch.forecasts if forecast.ticker not in ticker_universe]
    if invalid:
        raise ValidationError.from_exception_data(
            "ForecastBatch",
            [
                {
                    "type": "value_error",
                    "loc": ("forecasts", "ticker"),
                    "msg": f"Unknown tickers: {invalid}",
                    "input": invalid,
                    "ctx": {"error": ValueError(f"Unknown tickers: {invalid}")},
                }
            ],
        )
    return batch


def build_prompt(
    role: str,
    framework: str,
    heuristics: list[str],
    examples: list[dict[str, Any]],
    output_schema: dict[str, Any] | None = None,
) -> PromptSpec:
    return PromptSpec(
        role=role,
        framework=framework,
        heuristics=heuristics,
        examples=examples,
        output_schema=output_schema or FIXED_OUTPUT_SCHEMA,
    )
