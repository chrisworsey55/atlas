"""Configuration for Darwin v2.

All tunable parameters live here so experiments are reproducible and
selection events can be audited against the exact thresholds used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent


DEFAULT_ROLES: tuple[str, ...] = (
    "news_flow",
    "sector_desk_bond",
    "sector_desk_currency",
    "sector_desk_commodities",
    "sector_desk_metals",
    "sector_desk_semiconductor",
    "sector_desk_biotech",
    "sector_desk_energy",
    "sector_desk_consumer",
    "sector_desk_industrials",
    "sector_desk_microcap",
    "superinvestor",
    "risk_cio",
)


DEFAULT_TICKERS: frozenset[str] = frozenset(
    {
        "AAPL",
        "MSFT",
        "AMZN",
        "NVDA",
        "GOOG",
        "GOOGL",
        "META",
        "BRK-B",
        "UNH",
        "JNJ",
        "JPM",
        "V",
        "PG",
        "MA",
        "HD",
        "CVX",
        "MRK",
        "ABBV",
        "LLY",
        "AVGO",
        "XOM",
        "PFE",
        "KO",
        "PEP",
        "COST",
        "TMO",
        "ABT",
        "WMT",
        "MCD",
        "CSCO",
        "ACN",
        "DHR",
        "ADBE",
        "CRM",
        "NKE",
        "LIN",
        "TXN",
        "NEE",
        "PM",
        "UNP",
        "ORCL",
        "AMD",
        "INTC",
        "QCOM",
        "IBM",
        "HON",
        "UPS",
        "CAT",
        "LOW",
        "BA",
        "GS",
        "MS",
        "BLK",
        "SCHW",
        "AXP",
        "C",
        "WFC",
        "USB",
        "PNC",
        "TFC",
        "COF",
        "SPY",
        "QQQ",
        "TLT",
        "SMH",
        "BIL",
    }
)


@dataclass(frozen=True)
class DarwinConfig:
    """Runtime parameters for Darwin v2."""

    agents_per_role: int = 16
    elites_per_generation: int = 4
    culled_per_generation: int = 4
    tournament_size: int = 3
    min_scored_forecasts: int = 30
    min_new_forecasts_per_generation: int = 30
    max_generation_days: int = 30
    novelty_lambda: float = 0.05
    mutation_rate_two_sections: float = 0.15
    embedding_dim: int = 128
    lineage_dir: Path = PACKAGE_DIR / "lineage"
    lineage_db: Path = PACKAGE_DIR / "lineage" / "lineage.sqlite"
    prompt_dir: Path = PACKAGE_DIR / "lineage" / "prompts"
    embedding_dir: Path = PACKAGE_DIR / "lineage" / "embeddings"
    roles: tuple[str, ...] = DEFAULT_ROLES
    ticker_universe: frozenset[str] = field(default_factory=lambda: DEFAULT_TICKERS)

    def validate(self) -> None:
        if self.agents_per_role != 16:
            raise ValueError("Darwin v2 requires exactly 16 agents per role.")
        if self.min_scored_forecasts < 30:
            raise ValueError("Minimum sample size must be at least 30.")
        if self.elites_per_generation + self.culled_per_generation > self.agents_per_role:
            raise ValueError("Elite and cull counts exceed population size.")
