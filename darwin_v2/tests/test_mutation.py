from __future__ import annotations

import random

from darwin_v2.mutation import SectionMutator
from darwin_v2.prompt import build_prompt


def _prompt():
    return build_prompt(
        role="A calibrated analyst for liquid US equities.",
        framework="Anchor forecasts to base rates and current market context before adjusting probabilities.",
        heuristics=["Avoid certainty.", "Prefer modest probabilities when evidence is weak."],
        examples=[{"input": "AAPL beats earnings", "forecast": {"ticker": "AAPL", "direction": "up", "prob": 0.58}}],
    )


def test_mutation_accepts_valid_section_yaml() -> None:
    def llm(section: str, directive: str, request: str) -> str:
        assert "Return only the new section" in request
        return "framework: Use explicit base-rate anchors before interpreting fresh news.\n"

    mutator = SectionMutator(llm, random.Random(1))
    new_prompt, event, changed = mutator.mutate_section(_prompt(), "framework", "add base-rate anchoring")

    assert changed is True
    assert event.accepted is True
    assert "base-rate" in new_prompt.framework


def test_mutation_retries_then_skips_invalid_yaml() -> None:
    calls = {"n": 0}

    def llm(section: str, directive: str, request: str) -> str:
        calls["n"] += 1
        return "not: the requested section\n"

    prompt = _prompt()
    mutator = SectionMutator(llm)
    new_prompt, event, changed = mutator.mutate_section(prompt, "heuristics", "add a contrarian rule")

    assert calls["n"] == 2
    assert changed is False
    assert event.accepted is False
    assert new_prompt == prompt


def test_output_schema_mutation_cannot_change_fields() -> None:
    def llm(section: str, directive: str, request: str) -> str:
        return "output_schema:\n  forecasts: []\n"

    prompt = _prompt()
    mutator = SectionMutator(llm)
    new_prompt, event, changed = mutator.mutate_section(prompt, "output_schema", "clarify formatting only without changing fields")

    assert changed is False
    assert event.accepted is False
    assert new_prompt.output_schema == prompt.output_schema
