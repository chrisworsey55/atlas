#!/usr/bin/env python3
"""
ATLAS Autoresearch — Mutation Engine

Generates prompt mutations using Claude API.

Input:
- Current prompt text (from agents/prompts/{agent}.md)
- Agent's recent performance data (from agent_scores.json)
- Experiment log of previous mutations on this agent
- Mutation type instruction

Process:
- Call Claude with a meta-prompt that optimizes the trading agent's prompt

Mutation types (cycled through):
- refine: Adjust thresholds, criteria, analytical focus
- restructure: Reorder sections, change reasoning flow
- simplify: Make prompt shorter while preserving intent
- expand: Add analytical dimension that's missing
- combine: Incorporate approach from a near-miss experiment

Constraints:
- Output must be a complete valid prompt (not a diff)
- Must preserve the JSON output format downstream layers expect
- Must preserve conviction: 1-100 scoring convention
- Must preserve agent identity section
- Maximum 2000 tokens per prompt
"""

import json
import os
import anthropic
from datetime import datetime
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load environment
load_dotenv(Path(__file__).parent.parent / ".env")

PROMPTS_DIR = Path(__file__).parent.parent / "agents" / "prompts"
RESULTS_DIR = Path(__file__).parent / "results"
EXPERIMENTS_FILE = Path(__file__).parent / "experiments.tsv"
SCORES_FILE = RESULTS_DIR / "agent_scores.json"

MAX_PROMPT_TOKENS = 2000
MUTATION_TYPES = ["refine", "restructure", "simplify", "expand", "combine"]

client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))


def load_prompt(agent_name: str) -> str:
    """Load an agent's current prompt from its .md file."""
    patterns = [
        f"{agent_name}.md",
        f"{agent_name}_desk.md",
        f"{agent_name}_agent.md",
    ]

    for pattern in patterns:
        path = PROMPTS_DIR / pattern
        if path.exists():
            with open(path) as f:
                return f.read()

    return None


def get_prompt_path(agent_name: str) -> Optional[Path]:
    """Get the path to an agent's prompt file."""
    patterns = [
        f"{agent_name}.md",
        f"{agent_name}_desk.md",
        f"{agent_name}_agent.md",
    ]

    for pattern in patterns:
        path = PROMPTS_DIR / pattern
        if path.exists():
            return path

    return None


def save_prompt(agent_name: str, prompt_text: str) -> bool:
    """Save a modified prompt to the agent's .md file."""
    path = get_prompt_path(agent_name)
    if path is None:
        # Create new file
        path = PROMPTS_DIR / f"{agent_name}.md"

    with open(path, "w") as f:
        f.write(prompt_text)

    return True


def load_agent_performance(agent_name: str) -> dict:
    """Load performance data for an agent."""
    if not SCORES_FILE.exists():
        return {}

    with open(SCORES_FILE) as f:
        scores = json.load(f)

    return scores.get("agents", {}).get(agent_name, {})


def load_experiment_history(agent_name: str) -> list:
    """Load previous mutation experiments for this agent."""
    if not EXPERIMENTS_FILE.exists():
        return []

    experiments = []
    with open(EXPERIMENTS_FILE) as f:
        header = f.readline()  # Skip header
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) >= 6:
                if parts[2] == agent_name:
                    experiments.append({
                        "commit": parts[0],
                        "sharpe_30d": float(parts[1]) if parts[1] else 0,
                        "agent": parts[2],
                        "mutation_type": parts[3],
                        "status": parts[4],
                        "description": parts[5]
                    })

    return experiments[-10:]  # Last 10 experiments on this agent


def get_next_mutation_type(agent_name: str) -> str:
    """
    Determine the next mutation type to try.
    Cycles through mutation types, skipping types that have failed recently.
    """
    history = load_experiment_history(agent_name)

    if not history:
        return MUTATION_TYPES[0]

    # Count recent failures by type
    recent = history[-5:]
    failed_types = {}
    for exp in recent:
        if exp.get("status") == "discard":
            mt = exp.get("mutation_type", "")
            failed_types[mt] = failed_types.get(mt, 0) + 1

    # Find last mutation type used
    last_type = history[-1].get("mutation_type", MUTATION_TYPES[0])
    last_idx = MUTATION_TYPES.index(last_type) if last_type in MUTATION_TYPES else 0

    # Cycle to next type, skipping types with 2+ recent failures
    for i in range(len(MUTATION_TYPES)):
        next_idx = (last_idx + 1 + i) % len(MUTATION_TYPES)
        next_type = MUTATION_TYPES[next_idx]
        if failed_types.get(next_type, 0) < 2:
            return next_type

    # All types have failed recently, just use the next one anyway
    return MUTATION_TYPES[(last_idx + 1) % len(MUTATION_TYPES)]


def count_tokens(text: str) -> int:
    """Rough token count (4 chars per token approximation)."""
    return len(text) // 4


def generate_mutation(
    agent_name: str,
    mutation_type: str = None,
    force_simplify: bool = False
) -> tuple[str, str, str]:
    """
    Generate a mutated prompt for an agent.

    Args:
        agent_name: The agent to mutate
        mutation_type: Type of mutation (or auto-select)
        force_simplify: Force simplify mutation if prompt too long

    Returns:
        Tuple of (new_prompt, mutation_type, description)
    """
    current_prompt = load_prompt(agent_name)
    if current_prompt is None:
        raise ValueError(f"No prompt found for agent: {agent_name}")

    performance = load_agent_performance(agent_name)
    history = load_experiment_history(agent_name)

    # Check if prompt is too long
    if count_tokens(current_prompt) > MAX_PROMPT_TOKENS:
        force_simplify = True

    # Determine mutation type
    if force_simplify:
        mutation_type = "simplify"
    elif mutation_type is None:
        mutation_type = get_next_mutation_type(agent_name)

    # Build performance summary
    perf_summary = f"""
Recent Performance for {agent_name}:
- Rolling Sharpe: {performance.get('rolling_sharpe', 0):.2f}
- Hit Rate: {performance.get('rolling_hit_rate', 0) * 100:.1f}%
- Total Recommendations: {performance.get('total_recommendations', 0)}
- CIO Adoption Rate: {performance.get('cio_adoption_rate', 0) * 100:.1f}%

Recent Recommendations:
"""
    recs = performance.get("recommendations", [])[-5:]
    for rec in recs:
        ret = rec.get("return_5d")
        ret_str = f"{ret:+.1f}%" if ret is not None else "pending"
        perf_summary += f"- {rec['ticker']} {rec['direction']}: {ret_str}\n"

    # Build history summary
    history_summary = "Previous mutation attempts on this agent:\n"
    for exp in history[-5:]:
        history_summary += f"- {exp['mutation_type']}: {exp['status']} (sharpe: {exp['sharpe_30d']:.2f}) - {exp['description']}\n"

    if not history:
        history_summary = "No previous mutations on this agent.\n"

    # Build mutation instructions based on type
    mutation_instructions = {
        "refine": """
MUTATION TYPE: REFINE
- Adjust numerical thresholds (e.g., conviction scores, risk limits)
- Sharpen analytical criteria
- Focus the agent more narrowly on what's working
- Tighten or loosen risk parameters based on performance
""",
        "restructure": """
MUTATION TYPE: RESTRUCTURE
- Reorder sections to prioritize what matters most
- Change the reasoning flow (e.g., risk-first vs opportunity-first)
- Reorganize output format for clarity
- Move important instructions earlier in the prompt
""",
        "simplify": """
MUTATION TYPE: SIMPLIFY
- Remove redundant instructions
- Condense verbose sections
- Eliminate examples if the agent understands the pattern
- Keep ONLY what's essential for good performance
- Target: reduce to under 1500 tokens while preserving effectiveness
""",
        "expand": """
MUTATION TYPE: EXPAND
- Add an analytical dimension the agent is missing
- Include a new data source or signal to consider
- Add a checklist or framework for edge cases
- Expand on areas where the agent has been weak
""",
        "combine": """
MUTATION TYPE: COMBINE
- Incorporate a successful approach from another agent
- Blend in techniques from high-performing sectors
- Add cross-pollination from recent successful experiments
- Maintain this agent's identity while adding new capabilities
"""
    }

    meta_prompt = f"""You are an AI researcher optimizing trading agent prompts for a hedge fund.

CURRENT PROMPT FOR {agent_name.upper()} AGENT:
```
{current_prompt}
```

{perf_summary}

{history_summary}

{mutation_instructions.get(mutation_type, mutation_instructions['refine'])}

CONSTRAINTS:
1. Output a COMPLETE, working prompt (not a diff or partial changes)
2. PRESERVE the agent's identity section at the top
3. PRESERVE any JSON output format specifications (downstream systems depend on this)
4. PRESERVE the conviction scoring convention (0-100)
5. Maximum length: 1800 tokens (to stay under 2000 limit)
6. The prompt must work standalone with no external references

TASK:
Generate ONE targeted modification to improve this agent's Sharpe ratio.
Focus on the specific performance weaknesses shown above.
Return the complete modified prompt, nothing else.

After the prompt, add a single line starting with "DESCRIPTION:" briefly explaining what you changed (max 100 characters).

BEGIN MODIFIED PROMPT:
"""

    print(f"[mutator] Generating {mutation_type} mutation for {agent_name}...")

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=3000,
        messages=[{"role": "user", "content": meta_prompt}]
    )

    result_text = response.content[0].text

    # Parse out the prompt and description
    if "DESCRIPTION:" in result_text:
        parts = result_text.rsplit("DESCRIPTION:", 1)
        new_prompt = parts[0].strip()
        description = parts[1].strip()[:100]
    else:
        new_prompt = result_text.strip()
        description = f"{mutation_type} mutation"

    # Strip any markdown code block markers
    if new_prompt.startswith("```"):
        lines = new_prompt.split("\n")
        new_prompt = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    # Validate token count
    if count_tokens(new_prompt) > MAX_PROMPT_TOKENS:
        print(f"[mutator] Warning: Mutation still too long ({count_tokens(new_prompt)} tokens), will need simplify")

    return new_prompt, mutation_type, description


def mutate_agent(agent_name: str, mutation_type: str = None) -> dict:
    """
    Mutate an agent's prompt and save it.

    Returns dict with mutation details for logging.
    """
    # Load current prompt for backup
    current_prompt = load_prompt(agent_name)
    prompt_path = get_prompt_path(agent_name)

    # Generate mutation
    new_prompt, used_mutation_type, description = generate_mutation(
        agent_name,
        mutation_type=mutation_type
    )

    # Save the new prompt
    save_prompt(agent_name, new_prompt)

    return {
        "agent": agent_name,
        "mutation_type": used_mutation_type,
        "description": description,
        "original_tokens": count_tokens(current_prompt) if current_prompt else 0,
        "new_tokens": count_tokens(new_prompt),
        "prompt_path": str(prompt_path),
        "timestamp": datetime.now().isoformat()
    }


def revert_mutation(agent_name: str):
    """
    Revert the last mutation by doing git reset.
    This should be called from the main loop, not directly.
    """
    # This function is a placeholder - actual git operations happen in loop.py
    print(f"[mutator] Revert requested for {agent_name} - use git reset in loop.py")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python mutator.py <agent_name> [mutation_type]")
        print(f"Mutation types: {', '.join(MUTATION_TYPES)}")
        sys.exit(1)

    agent_name = sys.argv[1]
    mutation_type = sys.argv[2] if len(sys.argv) > 2 else None

    result = mutate_agent(agent_name, mutation_type)
    print(f"\n[mutator] Mutation complete:")
    print(f"  Agent: {result['agent']}")
    print(f"  Type: {result['mutation_type']}")
    print(f"  Description: {result['description']}")
    print(f"  Tokens: {result['original_tokens']} -> {result['new_tokens']}")
