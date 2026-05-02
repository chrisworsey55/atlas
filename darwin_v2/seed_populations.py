"""Seed Darwin v2 populations from existing ATLAS prompt files.

This script is offline and deterministic. It does not call Claude. It creates
16 intentionally varied YAML prompts per role and writes them into the v2
lineage store.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from darwin_v2.config import DEFAULT_ROLES, REPO_ROOT, DarwinConfig
from darwin_v2.lineage import LineageStore
from darwin_v2.population import Population
from darwin_v2.prompt import build_prompt, dump_prompt_yaml
from darwin_v2.schema import FitnessSnapshot


PROMPT_DIR = REPO_ROOT / "agents" / "prompts"

ROLE_SOURCE_FILES: dict[str, list[str]] = {
    "macro": ["druckenmiller.md", "macro_regime.md", "yield_curve.md", "central_bank.md", "dollar.md"],
    "sector_desk_semiconductor": ["semiconductor.md", "semiconductor_desk.md"],
    "sector_desk_energy": ["energy.md", "energy_desk.md"],
    "emerging_markets": ["emerging_markets.md", "china.md", "currency.md"],
    "sector_desk_biotech": ["biotech.md", "biotech_desk.md"],
    "sector_desk_financials": ["financials.md", "financials_desk.py"],
    "cio": ["cio.md", "cio_agent.py", "alpha_discovery.md"],
    "cro": ["cro.md", "adversarial_agent.py"],
    "quantitative": ["simons.md", "alpha_discovery.md", "consensus_agent.py"],
    "value": ["ackman.md", "baker.md", "fundamental_agent.py"],
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

ROLE_DISPLAY_NAMES: dict[str, str] = {
    "macro": "Macro (Druckenmiller-style)",
    "sector_desk_semiconductor": "Semiconductor desk",
    "sector_desk_energy": "Energy desk",
    "emerging_markets": "Emerging markets",
    "sector_desk_biotech": "Biotech",
    "sector_desk_financials": "Financials",
    "cio": "CIO (synthesis layer)",
    "cro": "CRO (risk officer)",
    "quantitative": "Quantitative",
    "value": "Value",
}

ROLE_SPECIALIZATION: dict[str, str] = {
    "macro": (
        "Operate as a top-down macro allocator. Focus on central-bank reaction functions, yield-curve inflections, "
        "dollar liquidity, commodity inflation signals, credit-spread stress, and cross-asset capital rotation. "
        "Your edge is deciding when the entire tape is being repriced by rates, FX, or liquidity rather than company news."
    ),
    "sector_desk_semiconductor": (
        "Operate as a semiconductor supply-chain desk. Focus on AI accelerator demand, HBM availability, CoWoS packaging, "
        "foundry utilization, EDA/tooling constraints, memory cycles, lead times, hyperscaler capex, and equipment order books. "
        "Your edge is mapping chip-cycle bottlenecks to NVDA, AMD, AVGO, TSM, INTC, and adjacent suppliers."
    ),
    "sector_desk_energy": (
        "Operate as an energy desk. Focus on WTI/Brent structure, EIA inventory draws, refinery cracks, OPEC spare capacity, "
        "shale decline curves, LNG flows, geopolitical supply risk, and dividend discipline across majors, E&Ps, refiners, "
        "midstream, and transition assets."
    ),
    "emerging_markets": (
        "Operate as an emerging-markets cross-asset analyst. Focus on dollar pressure, China transmission, sovereign spreads, "
        "capital-flow stops, local inflation, commodity importer/exporter splits, country ETF liquidity, policy credibility, "
        "and contagion from FX into equities."
    ),
    "sector_desk_biotech": (
        "Operate as a biotech and healthcare catalyst desk. Focus on PDUFA dates, AdCom risk, trial endpoint quality, patent cliffs, "
        "Medicare and PBM policy, managed-care MLR, pharma M&A appetite, label expansion, and binary clinical readout asymmetry."
    ),
    "sector_desk_financials": (
        "Operate as a financials desk. Focus on NIM, deposit beta, CET1 constraints, loan growth, charge-offs, CRE exposure, "
        "capital-markets activity, trading revenue, insurance float, asset-manager flows, private-credit fundraising, and REIT leverage."
    ),
    "cio": (
        "Operate as the synthesis layer. Aggregate conflicting desk views, weight agents by observed skill, enforce portfolio constraints, "
        "separate actionable consensus from narrative noise, and decide which single-name forecasts deserve capital after risk review."
    ),
    "cro": (
        "Operate as the risk officer. Stress every forecast for factor crowding, hidden correlation, liquidity exits, stop-loss realism, "
        "tail scenarios, gross/net exposure, volatility spikes, and the exact catalyst that invalidates the bullish case."
    ),
    "quantitative": (
        "Operate as a statistical pattern desk. Focus on validated signal counts, base rates, holding-period distributions, calibration bins, "
        "out-of-sample decay, turnover costs, false discovery control, and whether observed odds clear the forecast threshold."
    ),
    "value": (
        "Operate as a quality value investor. Focus on free-cash-flow durability, ROIC, balance-sheet resilience, management incentives, "
        "moat persistence, pricing power, valuation margin of safety, capital allocation, and patient compounding rather than tape noise."
    ),
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


def seed_file_name(role: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", role.lower()).strip("_")
    return f"seed_{slug}.yaml"


def build_seed_manifest(role: str) -> str:
    display_name = ROLE_DISPLAY_NAMES.get(role, role.replace("_", " ").title())
    specialization = ROLE_SPECIALIZATION.get(
        role,
        "Operate as a domain specialist with a distinct evidence hierarchy and calibrated probability discipline.",
    )
    source = read_sources(role)[:2200].replace("\r\n", "\n")
    initial_prompt = (
        f"{specialization}\n\n"
        "Adapt the legacy ATLAS material below into calibrated equity forecasts for Darwin v2. "
        "Use the role's distinct evidence hierarchy first, then translate conviction into a probability.\n\n"
        f"{source}"
    )
    indented_prompt = "\n".join(f"  {line}" if line else "" for line in initial_prompt.splitlines())
    return (
        f"role_name: {display_name}\n"
        "initial_prompt: |\n"
        f"{indented_prompt}\n"
        "forecast_format: Binary YES/NO - will X close higher than today in N days?\n"
        "performance_score: 0.5\n"
    )


def build_seed_prompts(role: str) -> list[str]:
    source = read_sources(role)
    display_name = ROLE_DISPLAY_NAMES.get(role, role.replace("_", " ").title())
    specialization = ROLE_SPECIALIZATION.get(
        role,
        "Operate as a domain specialist with a distinct evidence hierarchy and calibrated probability discipline.",
    )
    charter_block = "\n".join(f"- {specialization}" for _ in range(6))
    prompts: list[str] = []
    for idx, (variant, rules) in enumerate(VARIANTS):
        role_text = (
            f"Role name: {display_name}. You are Darwin v2 seed {idx:02d} for {role}. "
            f"Distinct evidence charter: {specialization} "
            "You are an IC analyst producing calibrated binary YES/NO equity forecasts, not trade orders. "
            "Starting performance_score is 0.50, a neutral prior until scored forecasts accumulate."
        )
        framework = (
            f"Primary role evidence charter:\n{charter_block}\n\n"
            f"Role-specific decision boundary:\n{charter_block}\n\n"
            f"Legacy ATLAS source material for this role: {source[:5000]}\n\n"
            f"Convert that material into a {variant} forecasting process. Forecast format: binary YES/NO "
            "question, 'Will X close higher than today in N days?', expressed as ticker, up/down direction, "
            "probability, horizon_days, and rationale."
        )
        heuristics = [
            f"Use this role-specific evidence charter before generic market reasoning: {specialization}",
            *rules,
            "Answer the binary question as calibrated YES probability via direction='up' and prob, or NO via direction='down' and prob.",
            "Treat 0.50 as the neutral starting performance score, not as a default forecast probability.",
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
    seed_prompts = build_seed_prompts(role)
    records = population.seed(seed_prompts)
    neutral_prior = FitnessSnapshot(
        generation=0,
        n_forecasts=0,
        raw_fitness=0.5,
        effective_fitness=0.5,
    )
    for record in records:
        record.fitness_history.append(neutral_prior)
        store.update_record(record)
    seed_path = config.lineage_dir / seed_file_name(role)
    seed_path.write_text(build_seed_manifest(role))
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
