#!/usr/bin/env python3
"""
ATLAS Prompt Loader
Loads agent prompts from .md files and agent weights from JSON.
This enables the autoresearch loop to iterate on prompts independently.
"""

import json
from pathlib import Path
from typing import Dict, Optional

PROMPTS_DIR = Path(__file__).parent / "prompts"
STATE_DIR = Path(__file__).parent.parent / "data" / "state"
WEIGHTS_FILE = STATE_DIR / "agent_weights.json"

# Agent name mappings (handle variations)
AGENT_ALIASES = {
    # Superinvestors
    'druckenmiller': ['druckenmiller', 'druck', 'macro'],
    'aschenbrenner': ['aschenbrenner', 'leopold', 'ai_infra'],
    'baker': ['baker', 'gavin', 'deep_tech'],
    'ackman': ['ackman', 'bill', 'quality'],
    # Desks
    'bond': ['bond', 'bond_desk', 'rates', 'fixed_income'],
    'currency': ['currency', 'currency_desk', 'fx'],
    'commodities': ['commodities', 'commodities_desk', 'commod'],
    'metals': ['metals', 'metals_desk', 'gold'],
    'semiconductor': ['semiconductor', 'semiconductor_desk', 'semi', 'semis'],
    'biotech': ['biotech', 'biotech_desk', 'healthcare'],
    'energy': ['energy', 'energy_desk', 'oil'],
    'consumer': ['consumer', 'consumer_desk', 'retail'],
    'industrials': ['industrials', 'industrials_desk', 'industrial'],
    'microcap': ['microcap', 'microcap_desk', 'smallcap'],
    # Risk/Decision
    'cro': ['cro', 'adversarial', 'risk'],
    'cio': ['cio', 'synthesis', 'chief'],
}


def normalize_agent_name(name: str) -> str:
    """Normalize agent name to canonical form."""
    name_lower = name.lower().strip()
    for canonical, aliases in AGENT_ALIASES.items():
        if name_lower in aliases:
            return canonical
    return name_lower


def load_prompt(agent_name: str) -> str:
    """
    Load prompt for an agent from its .md file.
    Falls back to a default prompt if file doesn't exist.
    """
    canonical_name = normalize_agent_name(agent_name)

    # Try different filename patterns
    patterns = [
        f"{canonical_name}.md",
        f"{canonical_name}_desk.md",
        f"{canonical_name}_agent.md",
    ]

    for pattern in patterns:
        prompt_file = PROMPTS_DIR / pattern
        if prompt_file.exists():
            with open(prompt_file) as f:
                return f.read()

    # Default fallback prompt
    return f"""You are the {agent_name} agent for ATLAS hedge fund.
Provide your analysis and recommendations based on the market data provided.
Be specific with tickers, directions, and confidence levels."""


def load_all_prompts() -> Dict[str, str]:
    """Load all agent prompts from .md files."""
    prompts = {}
    for canonical_name in AGENT_ALIASES.keys():
        prompts[canonical_name] = load_prompt(canonical_name)
    return prompts


def load_weights() -> Dict[str, float]:
    """Load agent weights from JSON file."""
    if WEIGHTS_FILE.exists():
        with open(WEIGHTS_FILE) as f:
            data = json.load(f)
            # Filter out metadata fields
            return {k: v for k, v in data.items()
                    if isinstance(v, (int, float)) and k not in ['initialized', 'last_updated']}
    return {name: 1.0 for name in AGENT_ALIASES.keys()}


def get_agent_weight(agent_name: str) -> float:
    """Get the weight for a specific agent."""
    canonical_name = normalize_agent_name(agent_name)
    weights = load_weights()
    return weights.get(canonical_name, 1.0)


def get_weighted_prompt(agent_name: str) -> tuple[str, float]:
    """
    Get prompt and weight for an agent.
    Returns (prompt_text, weight).
    """
    prompt = load_prompt(agent_name)
    weight = get_agent_weight(agent_name)
    return prompt, weight


def build_weighted_system_prompt(agent_name: str, base_instruction: str = "") -> str:
    """
    Build a system prompt that includes the agent's weight context.
    Higher weight agents are instructed to be more confident.
    Lower weight agents are instructed to be more cautious.
    """
    prompt, weight = get_weighted_prompt(agent_name)

    weight_instruction = ""
    if weight > 1.5:
        weight_instruction = """
Your recommendations have historically been strong performers.
Be confident in your convictions while maintaining risk discipline."""
    elif weight < 0.7:
        weight_instruction = """
Your recent recommendations have underperformed.
Be especially rigorous in your analysis and conservative in position sizing.
Consider what you might be missing in your framework."""
    elif weight < 0.5:
        weight_instruction = """
WARNING: Your recent performance requires a prompt rewrite.
Focus on identifying where your analysis framework is breaking down.
Be very cautious with any recommendations until performance improves."""

    return f"""{prompt}

{weight_instruction}

{base_instruction}"""


def get_cio_weighted_instructions() -> str:
    """
    Generate instructions for CIO about how to weight each agent.
    """
    weights = load_weights()

    lines = ["## Agent Weights for Synthesis", ""]
    lines.append("When synthesizing agent views, weight them according to these performance-based scores:")
    lines.append("")

    # Sort by weight descending
    sorted_weights = sorted(weights.items(), key=lambda x: x[1], reverse=True)

    for agent, weight in sorted_weights:
        if weight > 1.5:
            status = "HIGH INFLUENCE"
        elif weight < 0.5:
            status = "NEEDS REWRITE - USE CAUTION"
        elif weight < 0.7:
            status = "UNDERPERFORMING"
        elif weight > 1.2:
            status = "OUTPERFORMING"
        else:
            status = "NORMAL"

        lines.append(f"- **{agent}**: {weight:.2f} ({status})")

    lines.append("")
    lines.append("Prioritize recommendations from high-weight agents.")
    lines.append("Be skeptical of recommendations from low-weight agents.")

    return "\n".join(lines)


def list_available_prompts() -> list[str]:
    """List all available prompt files."""
    prompts = []
    for f in PROMPTS_DIR.glob("*.md"):
        prompts.append(f.stem)
    return sorted(prompts)


if __name__ == '__main__':
    # Test the loader
    print("Available prompts:", list_available_prompts())
    print("\nWeights:")
    for agent, weight in load_weights().items():
        print(f"  {agent}: {weight}")

    print("\nCIO weighted instructions:")
    print(get_cio_weighted_instructions())
