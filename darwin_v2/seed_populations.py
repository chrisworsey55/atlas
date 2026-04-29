"""Seed Darwin v2 populations from existing ATLAS prompt files.

This script is offline and deterministic. It does not call Claude. It creates
16 intentionally varied YAML prompts per role and writes them into the v2
lineage store.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from darwin_v2.config import DEFAULT_ROLES, REPO_ROOT, DarwinConfig
from darwin_v2.lineage import LineageStore
from darwin_v2.population import Population
from darwin_v2.prompt import build_prompt, dump_prompt_yaml


PROMPT_DIR = REPO_ROOT / "agents" / "prompts"

ROLE_SOURCE_FILES: dict[str, list[str]] = {
    "news_flow": ["news_sentiment.md", "institutional_flow.md"],
    "sector_desk_bond": ["bond.md", "bond_desk.md"],
    "sector_desk_currency": ["currency.md", "currency_desk.md"],
    "sector_desk_commodities": ["commodities.md", "commodities_desk.md"],
    "sector_desk_metals": ["metals.md", "metals_desk.md"],
    "sector_desk_semiconductor": ["semiconductor.md", "semiconductor_desk.md"],
    "sector_desk_biotech": ["biotech.md", "biotech_desk.md"],
    "sector_desk_energy": ["energy.md", "energy_desk.md"],
    "sector_desk_consumer": ["consumer.md", "consumer_desk.md"],
    "sector_desk_industrials": ["industrials.md", "industrials_desk.md"],
    "sector_desk_microcap": ["microcap.md", "microcap_desk.md"],
    "superinvestor": ["druckenmiller.md", "aschenbrenner.md", "baker.md", "ackman.md"],
    "risk_cio": ["cro.md", "cio.md", "alpha_discovery.md"],
}

VARIANTS: tuple[tuple[str, list[str]], ...] = (
    ("base-rate anchored", ["Start from historical directional base rates.", "Move probability only when evidence is fresh."]),
    ("downside asymmetric", ["Penalize crowded upside when downside gap risk is visible.", "Require extra evidence above 0.65 probability."]),
    ("mean-reversion aware", ["Look for overreaction and exhaustion after sharp moves.", "Prefer 5d/10d horizons for reversal forecasts."]),
    ("trend-following aware", ["Respect persistent momentum when breadth and revisions agree.", "Avoid fading strong multi-day confirmation."]),
    ("regime conditional", ["Condition every forecast on bull/bear and vol regime.", "Lower confidence when current regime is unclear."]),
    ("contrarian", ["Ask what consensus is missing before forecasting.", "Fade narratives only when price confirms exhaustion."]),
    ("quality filtered", ["Upgrade forecasts backed by resilient balance sheets or cash flows.", "Downgrade weak quality in high-vol regimes."]),
    ("liquidity focused", ["Treat liquidity tightening as a probability headwind.", "Respect rate and dollar shocks."]),
    ("earnings revision focused", ["Anchor short-horizon forecasts to estimate revisions.", "Discount stale earnings reactions."]),
    ("risk-first", ["Identify the disconfirming evidence before assigning probability.", "Keep ambiguous setups near 0.50."]),
    ("catalyst focused", ["Separate hard catalysts from narrative drift.", "Prefer near horizons only when catalyst timing is explicit."]),
    ("cross-asset aware", ["Use rates, vol, dollar, and sector ETF confirmation.", "Reduce probability when cross-asset signals conflict."]),
    ("valuation sensitive", ["Distinguish good company from good forward return.", "Downgrade stretched valuation without catalyst support."]),
    ("sentiment calibrated", ["Treat extreme sentiment as unstable evidence.", "Avoid extrapolating a single headline."]),
    ("breadth aware", ["Check whether signal is single-name or sector-wide.", "Upgrade broad confirmation and downgrade isolated noise."]),
    ("uncertainty explicit", ["Write rationales that explain uncertainty, not certainty.", "Never emit 0 or 1 probabilities."]),
)


def read_sources(role: str) -> str:
    chunks: list[str] = []
    for filename in ROLE_SOURCE_FILES.get(role, []):
        path = PROMPT_DIR / filename
        if path.exists():
            chunks.append(path.read_text()[:1200])
    if not chunks:
        chunks.append(f"{role} analyst prompt source unavailable.")
    return "\n\n".join(chunks)


def build_seed_prompts(role: str) -> list[str]:
    source = read_sources(role)
    prompts: list[str] = []
    for idx, (variant, rules) in enumerate(VARIANTS):
        role_text = (
            f"You are Darwin v2 seed {idx:02d} for {role}. "
            "You are an IC analyst producing calibrated probability forecasts, not trade orders."
        )
        framework = (
            f"Use the legacy ATLAS prompt material as domain context, but convert it into a {variant} "
            f"forecasting process. Source excerpt: {source[:700]}"
        )
        heuristics = [
            *rules,
            "Emit only JSON matching the fixed forecast schema.",
            "Keep probabilities strictly between 0 and 1.",
            "Prefer calibrated probabilities over persuasive prose.",
        ]
        examples = [
            {
                "input": f"{role} context with mixed evidence under {variant} lens",
                "forecast": {
                    "ticker": "AAPL",
                    "direction": "up" if idx % 2 == 0 else "down",
                    "prob": round(0.54 + (idx % 5) * 0.03, 2),
                    "horizon_days": [1, 5, 10, 21][idx % 4],
                    "rationale": "Short rationale tied to evidence and uncertainty.",
                },
            }
        ]
        prompts.append(dump_prompt_yaml(build_prompt(role_text, framework, heuristics, examples)))
    return prompts


def seed_role(role: str, config: DarwinConfig, force: bool = False) -> int:
    store = LineageStore(config)
    population = Population(role, store, config)
    existing = population.alive()
    if existing and not force:
        return 0
    if force:
        for record in existing:
            store.update_status(record.id, "culled")
    population.seed(build_seed_prompts(role))
    return config.agents_per_role


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Darwin v2 populations")
    parser.add_argument("--role", choices=DEFAULT_ROLES, help="Seed one role only")
    parser.add_argument("--force", action="store_true", help="Cull existing alive records before reseeding")
    args = parser.parse_args()

    config = DarwinConfig()
    config.validate()
    roles = [args.role] if args.role else list(config.roles)
    for role in roles:
        created = seed_role(role, config, force=args.force)
        print(f"{role}: created {created} seed prompts")


if __name__ == "__main__":
    main()
