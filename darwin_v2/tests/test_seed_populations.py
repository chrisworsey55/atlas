from __future__ import annotations

from darwin_v2.prompt import parse_prompt_yaml
from darwin_v2.seed_populations import build_seed_prompts


def test_seed_prompts_are_varied_and_valid() -> None:
    prompts = build_seed_prompts("news_flow")
    assert len(prompts) == 16
    assert len(set(prompts)) == 16
    parsed = [parse_prompt_yaml(prompt) for prompt in prompts]
    assert all("calibrated" in prompt.role for prompt in parsed)
