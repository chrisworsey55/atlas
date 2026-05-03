"""Configuration for Darwin v3 standalone modules."""

from __future__ import annotations

from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent
DEFAULT_DB_PATH = PACKAGE_DIR / "gene_pool.db"
DEFAULT_PROMPTS_DIR = REPO_ROOT / "agents" / "prompts"


AGENT_ALIASES: dict[str, str] = {
    "volatility_desk": "volatility",
    "bond_desk": "bond",
    "currency_desk": "currency",
    "commodities_desk": "commodities",
    "metals_desk": "metals",
    "semiconductor_desk": "semiconductor",
    "biotech_desk": "biotech",
    "energy_desk": "energy",
    "consumer_desk": "consumer",
    "industrials_desk": "industrials",
    "microcap_desk": "microcap",
    "macro_regime": "macro",
    "central_bank": "macro",
    "yield_curve": "macro",
    "credit_spread": "bond",
    "credit": "bond",
    "rates": "bond",
    "fixed_income": "bond",
    "risk": "cro",
    "adversarial": "cro",
    "synthesis": "cio",
    "chief": "cio",
}


def normalize_agent_id(agent_id: str) -> str:
    return AGENT_ALIASES.get(agent_id.lower().strip(), agent_id.lower().strip())

