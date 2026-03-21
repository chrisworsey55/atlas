#!/usr/bin/env python3
"""
ATLAS Autoresearch — Fast Cycle

A stripped version of eod_cycle that accepts cached layer outputs
and only reruns what changed.

Speed Optimization:
- When mutating a Layer 2 agent (e.g. semiconductor), don't rerun
  Layer 1 data agents. Cache their outputs.
- When mutating a superinvestor agent, cache Layers 1+2.
- Only rerun the mutated agent + Layer 4 (CRO + CIO) to get a
  new final recommendation.
- This cuts each experiment from 20 API calls to ~3-5.

Layer Architecture:
- Layer 1 Data (2): news_sentiment, institutional_flow
- Layer 2 Sector (10): bond, currency, commodities, metals,
  semiconductor, biotech, energy, consumer, industrials, microcap
- Layer 3 Superinvestor (4): druckenmiller, aschenbrenner,
  baker, ackman
- Layer 4 Decision (4): cro, alpha_discovery, autonomous_execution, cio
"""

import anthropic
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load environment
load_dotenv(Path(__file__).parent.parent / ".env")

STATE_DIR = Path(__file__).parent.parent / "data" / "state"
PROMPTS_DIR = Path(__file__).parent.parent / "agents" / "prompts"
CACHE_DIR = Path(__file__).parent / "results" / "cache"

client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

# Layer definitions
LAYER_1_AGENTS = ["news", "flow"]
LAYER_2_AGENTS = [
    "bond", "currency", "commodities", "metals", "semiconductor",
    "biotech", "energy", "consumer", "industrials", "microcap"
]
LAYER_3_AGENTS = ["druckenmiller", "aschenbrenner", "baker", "ackman"]
LAYER_4_AGENTS = ["cro", "alpha", "autonomous", "cio"]

# Agent name mappings for prompt files
AGENT_PROMPT_MAP = {
    "news": "news_sentiment",
    "flow": "institutional_flow",
    "alpha": "alpha_discovery",
    "autonomous": "autonomous_execution"
}


def load_prompt(agent_name: str) -> str:
    """Load an agent's system prompt from its .md file."""
    # Map to actual prompt filename
    prompt_name = AGENT_PROMPT_MAP.get(agent_name, agent_name)

    patterns = [
        f"{prompt_name}.md",
        f"{prompt_name}_desk.md",
        f"{prompt_name}_agent.md",
    ]

    for pattern in patterns:
        path = PROMPTS_DIR / pattern
        if path.exists():
            with open(path) as f:
                return f.read()

    # Fallback
    return f"You are the {agent_name} agent. Provide your analysis based on the data provided."


def call_agent(system_prompt: str, user_message: str, max_tokens: int = 1000) -> str:
    """Call an agent via Claude API."""
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}]
    )
    return response.content[0].text


def get_agent_layer(agent_name: str) -> int:
    """Return the layer number (1-4) for an agent."""
    if agent_name in LAYER_1_AGENTS:
        return 1
    elif agent_name in LAYER_2_AGENTS:
        return 2
    elif agent_name in LAYER_3_AGENTS:
        return 3
    elif agent_name in LAYER_4_AGENTS:
        return 4
    return 0


def load_cache(session_id: str = None) -> Optional[dict]:
    """Load cached layer outputs from previous run."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if session_id:
        cache_file = CACHE_DIR / f"{session_id}_cache.json"
    else:
        # Find most recent cache
        cache_files = sorted(CACHE_DIR.glob("*_cache.json"), reverse=True)
        cache_file = cache_files[0] if cache_files else None

    if cache_file and cache_file.exists():
        with open(cache_file) as f:
            return json.load(f)

    return None


def save_cache(cache: dict, session_id: str):
    """Save layer outputs to cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{session_id}_cache.json"
    cache["session_id"] = session_id
    cache["timestamp"] = datetime.now().isoformat()
    with open(cache_file, "w") as f:
        json.dump(cache, f, indent=2)


def load_market_context() -> str:
    """Load current market context from positions and P&L."""
    try:
        with open(STATE_DIR / "positions.json") as f:
            data = json.load(f)
    except:
        return "No portfolio data available."

    positions = data.get("positions", [])
    today = datetime.now().strftime('%Y-%m-%d')

    portfolio_lines = []
    for p in positions:
        t = p["ticker"]
        entry = p.get('entry_price', 0)
        current = p.get('current_price', entry)
        shares = p.get('shares', 0)
        direction = p.get('direction', 'LONG')

        if entry and current and shares:
            if direction == 'SHORT':
                pnl = (entry - current) * shares
            else:
                pnl = (current - entry) * shares
            pnl_pct = (pnl / (entry * shares) * 100) if entry * shares > 0 else 0

            portfolio_lines.append(
                f"  {t}: {direction} {shares} shares @ ${entry:.2f} "
                f"-> ${current:.2f} | P&L: ${pnl:,.2f} ({pnl_pct:.2f}%) | "
                f"Thesis: {p.get('thesis', '')[:80]}"
            )

    context = f"""
TODAY: {today} — Market analysis session.
PORTFOLIO VALUE: $1,000,000 base

CURRENT POSITIONS:
{chr(10).join(portfolio_lines)}

Provide your analysis. Be specific about what you see and what action you recommend.
"""
    return context


def run_layer_1(context: str) -> dict:
    """Run Layer 1 data agents."""
    views = {}

    print("[fast_cycle] Running Layer 1: Data Agents...")

    # News Agent
    views['news'] = call_agent(
        load_prompt("news"),
        f"What are the most important market events? How do they affect our portfolio?\n\n{context}"
    )
    print(f"  [1/2] news: {views['news'][:80]}...")

    # Flow Agent
    views['flow'] = call_agent(
        load_prompt("flow"),
        f"What institutional flow signals are relevant today?\n\n{context}"
    )
    print(f"  [2/2] flow: {views['flow'][:80]}...")

    return views


def run_layer_2(context: str, agent_to_rerun: str = None, cached_views: dict = None) -> dict:
    """
    Run Layer 2 sector desks.
    If agent_to_rerun specified, only rerun that agent and use cache for others.
    """
    views = {}

    print("[fast_cycle] Running Layer 2: Sector Desks...")

    for i, agent in enumerate(LAYER_2_AGENTS):
        # Use cache if available and not the target agent
        if cached_views and agent != agent_to_rerun and agent in cached_views:
            views[agent] = cached_views[agent]
            print(f"  [{i+1}/10] {agent}: [CACHED]")
            continue

        # Run the agent
        views[agent] = call_agent(
            load_prompt(agent),
            context,
            max_tokens=1000
        )
        print(f"  [{i+1}/10] {agent}: {views[agent][:80]}...")

    return views


def run_layer_3(context: str, agent_to_rerun: str = None, cached_views: dict = None) -> dict:
    """
    Run Layer 3 superinvestor agents.
    If agent_to_rerun specified, only rerun that agent and use cache for others.
    """
    views = {}

    print("[fast_cycle] Running Layer 3: Superinvestors...")

    for i, agent in enumerate(LAYER_3_AGENTS):
        # Use cache if available and not the target agent
        if cached_views and agent != agent_to_rerun and agent in cached_views:
            views[agent] = cached_views[agent]
            print(f"  [{i+1}/4] {agent}: [CACHED]")
            continue

        # Run the agent
        views[agent] = call_agent(
            load_prompt(agent),
            context,
            max_tokens=1500
        )
        print(f"  [{i+1}/4] {agent}: {views[agent][:80]}...")

    return views


def run_layer_4(all_views: dict, context: str) -> dict:
    """
    Run Layer 4 decision agents.
    Always reruns because these synthesize the mutated outputs.
    """
    views = {}

    print("[fast_cycle] Running Layer 4: Risk & Decision...")

    # Build summary of all previous views
    all_views_summary = "\n\n".join([
        f"=== {name.upper()} ===\n{view[:500]}"
        for name, view in all_views.items()
    ])

    # Load agent weights for CIO
    weights = {}
    weights_file = STATE_DIR / "agent_weights.json"
    if weights_file.exists():
        with open(weights_file) as f:
            weights = json.load(f)
    weights_summary = json.dumps(weights, indent=2)

    # CRO
    views['cro'] = call_agent(
        load_prompt("cro"),
        f"FULL AGENT DEBATE:\n{all_views_summary}\n\nPORTFOLIO:\n{context}",
        max_tokens=2000
    )
    print(f"  [1/4] cro: {views['cro'][:80]}...")

    # Alpha Discovery
    views['alpha'] = call_agent(
        load_prompt("alpha"),
        f"FULL AGENT DEBATE:\n{all_views_summary}\n\n{context}",
        max_tokens=1500
    )
    print(f"  [2/4] alpha: {views['alpha'][:80]}...")

    # Autonomous Execution
    views['autonomous'] = call_agent(
        load_prompt("autonomous"),
        f"FULL DEBATE:\n{all_views_summary}\n\nCRO:\n{views['cro']}\n\n{context}",
        max_tokens=1000
    )
    print(f"  [3/4] autonomous: {views['autonomous'][:80]}...")

    # CIO
    views['cio'] = call_agent(
        load_prompt("cio"),
        f"AGENT WEIGHTS:\n{weights_summary}\n\nFULL 20-AGENT DEBATE:\n{all_views_summary}\n\nCRO REVIEW:\n{views['cro']}\n\nALPHA DISCOVERY:\n{views['alpha']}\n\n{context}",
        max_tokens=2500
    )
    print(f"  [4/4] cio: {views['cio'][:80]}...")

    return views


def run_fast_cycle(
    mutated_agent: str,
    session_id: str = None,
    use_cache: bool = True
) -> dict:
    """
    Run a fast cycle that only reruns what's necessary.

    Args:
        mutated_agent: The agent that was mutated
        session_id: Session ID for cache lookup
        use_cache: Whether to use cached layer outputs

    Returns:
        Dict of all agent views including the CIO synthesis
    """
    if session_id is None:
        session_id = datetime.now().strftime("%Y%m%d")

    print(f"\n{'='*60}")
    print(f"ATLAS FAST CYCLE — Mutated: {mutated_agent}")
    print(f"{'='*60}")

    # Load market context
    context = load_market_context()

    # Determine what to cache/rerun based on mutated agent's layer
    agent_layer = get_agent_layer(mutated_agent)

    # Load existing cache
    cached = load_cache(session_id) if use_cache else None
    all_views = {}

    if agent_layer == 2:
        # Layer 2 mutation: cache Layer 1, rerun mutated agent, rerun Layer 4
        if cached and "layer_1" in cached:
            all_views.update(cached["layer_1"])
            print("[fast_cycle] Using cached Layer 1")
        else:
            layer_1 = run_layer_1(context)
            all_views.update(layer_1)
            cached = cached or {}
            cached["layer_1"] = layer_1

        # Run Layer 2 with only the mutated agent
        layer_2 = run_layer_2(context, agent_to_rerun=mutated_agent, cached_views=cached.get("layer_2"))
        all_views.update(layer_2)
        cached["layer_2"] = layer_2

        # Use cached Layer 3 if available
        if cached and "layer_3" in cached:
            all_views.update(cached["layer_3"])
            print("[fast_cycle] Using cached Layer 3")
        else:
            layer_3 = run_layer_3(context)
            all_views.update(layer_3)
            cached["layer_3"] = layer_3

    elif agent_layer == 3:
        # Layer 3 mutation: cache Layers 1+2, rerun mutated agent, rerun Layer 4
        if cached and "layer_1" in cached:
            all_views.update(cached["layer_1"])
            print("[fast_cycle] Using cached Layer 1")
        else:
            layer_1 = run_layer_1(context)
            all_views.update(layer_1)
            cached = cached or {}
            cached["layer_1"] = layer_1

        if cached and "layer_2" in cached:
            all_views.update(cached["layer_2"])
            print("[fast_cycle] Using cached Layer 2")
        else:
            layer_2 = run_layer_2(context)
            all_views.update(layer_2)
            cached["layer_2"] = layer_2

        # Run Layer 3 with only the mutated agent
        layer_3 = run_layer_3(context, agent_to_rerun=mutated_agent, cached_views=cached.get("layer_3"))
        all_views.update(layer_3)
        cached["layer_3"] = layer_3

    else:
        # Unknown layer or Layer 1/4: run everything
        print(f"[fast_cycle] Agent {mutated_agent} not in optimizable layer, running full cycle")
        layer_1 = run_layer_1(context)
        all_views.update(layer_1)

        layer_2 = run_layer_2(context)
        all_views.update(layer_2)

        layer_3 = run_layer_3(context)
        all_views.update(layer_3)

        cached = {
            "layer_1": layer_1,
            "layer_2": layer_2,
            "layer_3": layer_3
        }

    # Always rerun Layer 4 (decision layer)
    layer_4 = run_layer_4(all_views, context)
    all_views.update(layer_4)

    # Save cache
    save_cache(cached, session_id)

    # Save views to state
    views_file = STATE_DIR / "eod_agent_views.json"
    with open(views_file, "w") as f:
        json.dump({
            "date": datetime.now().strftime('%Y-%m-%d'),
            "timestamp": datetime.now().isoformat(),
            "mutated_agent": mutated_agent,
            "views": all_views
        }, f, indent=2)

    print(f"\n{'='*60}")
    print(f"FAST CYCLE COMPLETE — {datetime.now().strftime('%H:%M')}")
    print(f"{'='*60}")

    return all_views


def run_full_baseline(session_id: str = None) -> dict:
    """
    Run a full cycle with no caching to establish baseline.
    """
    if session_id is None:
        session_id = datetime.now().strftime("%Y%m%d")

    print(f"\n{'='*60}")
    print("ATLAS FULL BASELINE CYCLE")
    print(f"{'='*60}")

    context = load_market_context()

    # Run all layers
    all_views = {}

    layer_1 = run_layer_1(context)
    all_views.update(layer_1)

    layer_2 = run_layer_2(context)
    all_views.update(layer_2)

    layer_3 = run_layer_3(context)
    all_views.update(layer_3)

    layer_4 = run_layer_4(all_views, context)
    all_views.update(layer_4)

    # Save everything as baseline cache
    cache = {
        "layer_1": layer_1,
        "layer_2": layer_2,
        "layer_3": layer_3,
        "is_baseline": True
    }
    save_cache(cache, session_id)

    # Save views
    views_file = STATE_DIR / "eod_agent_views.json"
    with open(views_file, "w") as f:
        json.dump({
            "date": datetime.now().strftime('%Y-%m-%d'),
            "timestamp": datetime.now().isoformat(),
            "is_baseline": True,
            "views": all_views
        }, f, indent=2)

    print(f"\n{'='*60}")
    print(f"BASELINE COMPLETE — {datetime.now().strftime('%H:%M')}")
    print(f"{'='*60}")

    return all_views


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        if sys.argv[1] == "--baseline":
            run_full_baseline()
        else:
            # Run fast cycle with specified mutated agent
            mutated_agent = sys.argv[1]
            run_fast_cycle(mutated_agent)
    else:
        print("Usage:")
        print("  python fast_cycle.py --baseline    # Run full baseline")
        print("  python fast_cycle.py <agent_name>  # Run fast cycle for mutated agent")
