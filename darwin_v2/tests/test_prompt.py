from __future__ import annotations

import pytest

from darwin_v2.prompt import build_prompt, dump_prompt_yaml, parse_prompt_yaml, validate_agent_output


def test_prompt_round_trip_requires_exact_sections() -> None:
    prompt = build_prompt(
        role="A calibrated news-flow analyst for liquid US equities.",
        framework="Forecast directional moves from news while anchoring to base rates and avoiding certainty.",
        heuristics=["Prefer modest probabilities.", "Downgrade stale information."],
        examples=[{"input": "AAPL beats earnings", "forecast": {"ticker": "AAPL", "direction": "up", "prob": 0.58}}],
    )
    text = dump_prompt_yaml(prompt)
    parsed = parse_prompt_yaml(text)
    assert parsed.role == prompt.role


def test_prompt_rejects_extra_section() -> None:
    text = """
role: A calibrated analyst for liquid US equities.
framework: Forecast carefully with base rates and uncertainty.
heuristics:
  - Avoid certainty.
examples:
  - input: test
    forecast:
      ticker: AAPL
      direction: up
      prob: 0.55
output_schema:
  forecasts:
    - ticker: str
extra: nope
"""
    with pytest.raises(ValueError):
        parse_prompt_yaml(text)


def test_agent_output_validation_no_regex_recovery() -> None:
    valid = {
        "forecasts": [
            {
                "ticker": "aapl",
                "direction": "up",
                "prob": 0.61,
                "horizon_days": 5,
                "rationale": "fresh earnings revision",
            }
        ]
    }
    assert validate_agent_output(valid).forecasts[0].ticker == "AAPL"

    with pytest.raises(Exception):
        validate_agent_output("BUY AAPL with 90% confidence")
