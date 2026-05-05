from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Company:
    ticker: str
    cik: str
    company_name: str
    sic_code: str | None = None
    sic_description: str | None = None
    last_filing_date: str | None = None
    last_filing_type: str | None = None
    last_accession: str | None = None
    filing_url: str | None = None
    exchange: str = "OTC"
    market_cap: float | None = None
    current_price: float | None = None
    avg_daily_volume: float | None = None
    avg_daily_volume_shares: float | None = None
    days_to_build_500k_position: int | None = None
    data_quality_flags: list[str] = field(default_factory=list)
    alternate_tickers: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Company":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class NCAVResult:
    cik: str
    ticker: str
    company_name: str
    filing_date: str | None
    filing_type: str | None
    current_assets: float | None = None
    total_liabilities: float | None = None
    shares_outstanding: float | None = None
    ncav: float | None = None
    ncav_per_share: float | None = None
    current_price: float | None = None
    price_to_ncav: float | None = None
    ncav_discount_pct: float | None = None
    is_stale: bool = False
    data_source: str = "UNKNOWN"
    data_quality_flag: str = "UNKNOWN"
    ncav_quality: str = "LOW"
    market_cap: float | None = None
    avg_daily_volume: float | None = None
    days_to_build_500k_position: int | None = None
    sic_code: str | None = None
    sic_description: str | None = None
    filing_url: str | None = None
    cash: float | None = None
    receivables: float | None = None
    inventory: float | None = None
    current_liabilities: float | None = None
    long_term_debt: float | None = None
    revenue: float | None = None
    revenue_history: list[float] = field(default_factory=list)
    business_description: str | None = None
    risk_factors: str | None = None
    employee_count: int | None = None
    rank: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NCAVResult":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

