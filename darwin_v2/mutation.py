"""Section mutation operator for Darwin v2."""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import yaml

from darwin_v2.prompt import dump_prompt_yaml, parse_prompt_yaml
from darwin_v2.schema import MutationEvent, PromptSpec


SectionName = Literal["role", "framework", "heuristics", "examples", "output_schema"]
LLMRewrite = Callable[[str, str, str], str]


SECTION_WEIGHTS: dict[SectionName, float] = {
    "framework": 0.30,
    "heuristics": 0.30,
    "examples": 0.25,
    "role": 0.10,
    "output_schema": 0.05,
}


DIRECTIVES: dict[SectionName, list[str]] = {
    "framework": [
        "emphasise downside asymmetry",
        "add base-rate anchoring",
        "shift toward mean-reversion bias",
        "shift toward trend-following bias",
        "add explicit uncertainty acknowledgment",
    ],
    "heuristics": [
        "add a contrarian rule",
        "tighten a threshold",
        "remove the weakest rule",
        "add a regime-conditional rule",
        "add a calibration rule that avoids 0 and 1 probabilities",
    ],
    "examples": [
        "replace lowest-quality example",
        "add an edge-case example",
        "swap an example for opposite-direction case",
        "add a low-conviction forecast example",
    ],
    "role": [
        "sharpen the persona",
        "broaden domain",
        "make calibration responsibility explicit",
    ],
    "output_schema": [
        "clarify formatting only without changing fields",
    ],
}


@dataclass(frozen=True)
class MutationResult:
    prompt: PromptSpec
    events: list[MutationEvent]
    changed: bool


def build_mutation_request(section: SectionName, directive: str, section_value: Any) -> str:
    section_yaml = yaml.safe_dump({section: section_value}, sort_keys=False, allow_unicode=False)
    return (
        f"Here is the current {section} section.\n"
        f"Rewrite it to {directive}.\n"
        "Return only the new section, valid YAML, no commentary.\n\n"
        f"{section_yaml}"
    )


class SectionMutator:
    """Mutates one or two prompt sections through an injected LLM rewrite function."""

    def __init__(self, llm_rewrite: LLMRewrite, rng: random.Random | None = None) -> None:
        self.llm_rewrite = llm_rewrite
        self.rng = rng or random.Random()

    def mutate(self, prompt: PromptSpec, sections_to_mutate: int = 1) -> MutationResult:
        current = prompt
        events: list[MutationEvent] = []
        changed = False
        for _ in range(sections_to_mutate):
            section = self.pick_section()
            directive = self.pick_directive(section)
            current, event, did_change = self.mutate_section(current, section, directive)
            events.append(event)
            changed = changed or did_change
        return MutationResult(prompt=current, events=events, changed=changed)

    def mutate_section(self, prompt: PromptSpec, section: SectionName, directive: str) -> tuple[PromptSpec, MutationEvent, bool]:
        original_data = prompt.model_dump(mode="json")
        original_section = original_data[section]
        error: str | None = None

        for _attempt in range(2):
            request = build_mutation_request(section, directive, original_section)
            output = self.llm_rewrite(section, directive, request)
            try:
                section_data = yaml.safe_load(output)
                if not isinstance(section_data, dict) or set(section_data.keys()) != {section}:
                    raise ValueError("LLM response must be a YAML mapping containing only the mutated section")
                candidate_data = dict(original_data)
                candidate_data[section] = section_data[section]

                if section == "output_schema" and candidate_data[section] != original_data[section]:
                    raise ValueError("output_schema field set is immutable in v2")

                candidate = parse_prompt_yaml(yaml.safe_dump(candidate_data, sort_keys=False))
                return candidate, MutationEvent(section=section, directive=directive, accepted=True), True
            except Exception as exc:  # noqa: BLE001 - mutation validation must log all failures.
                error = str(exc)

        return (
            prompt,
            MutationEvent(section=section, directive=directive, accepted=False, error=error),
            False,
        )

    def pick_section(self) -> SectionName:
        sections = list(SECTION_WEIGHTS.keys())
        weights = [SECTION_WEIGHTS[s] for s in sections]
        return self.rng.choices(sections, weights=weights, k=1)[0]

    def pick_directive(self, section: SectionName) -> str:
        return self.rng.choice(DIRECTIVES[section])


def prompt_to_yaml(prompt: PromptSpec) -> str:
    return dump_prompt_yaml(prompt)
