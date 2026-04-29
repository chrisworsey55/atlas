"""Pydantic schemas for Darwin v2."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


PROMPT_SECTIONS: tuple[str, ...] = (
    "role",
    "framework",
    "heuristics",
    "examples",
    "output_schema",
)

Direction = Literal["up", "down"]
HorizonDays = Literal[1, 5, 10, 21]
RegimeTag = Literal["bull_low_vol", "bull_high_vol", "bear_low_vol", "bear_high_vol"]
LineageStatus = Literal["alive", "elite", "culled"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Forecast(BaseModel):
    """Validated agent probability forecast."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    direction: Direction
    prob: float = Field(gt=0.0, lt=1.0)
    horizon_days: HorizonDays
    rationale: str = Field(min_length=1, max_length=500)

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        ticker = value.strip().upper()
        if not ticker:
            raise ValueError("ticker cannot be empty")
        return ticker

    @field_validator("prob")
    @classmethod
    def reject_certainty(cls, value: float) -> float:
        if value in (0.0, 1.0):
            raise ValueError("probability cannot be exactly 0 or 1")
        return value


class ForecastBatch(BaseModel):
    """The only accepted JSON payload shape from agents."""

    model_config = ConfigDict(extra="forbid")

    forecasts: list[Forecast]


class PromptSpec(BaseModel):
    """Canonical five-section prompt YAML schema."""

    model_config = ConfigDict(extra="forbid")

    role: str = Field(min_length=10)
    framework: str = Field(min_length=20)
    heuristics: list[str] = Field(min_length=1)
    examples: list[dict[str, Any]] = Field(min_length=1)
    output_schema: dict[str, Any]

    @model_validator(mode="after")
    def validate_output_schema(self) -> "PromptSpec":
        required = {"forecasts"}
        if set(self.output_schema.keys()) != required:
            raise ValueError("output_schema must contain only 'forecasts'")
        fields = self.output_schema.get("forecasts")
        if not isinstance(fields, list) or not fields:
            raise ValueError("output_schema.forecasts must describe forecast fields")
        return self


class ForecastRecord(BaseModel):
    """Persisted forecast before outcome is known."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    agent_id: str
    role: str
    generation: int
    issued_at: datetime = Field(default_factory=utc_now)
    regime: RegimeTag
    ticker: str
    direction: Direction
    prob: float = Field(gt=0.0, lt=1.0)
    horizon_days: HorizonDays
    rationale: str
    scored: bool = False


class ScoredForecast(ForecastRecord):
    """Forecast with realized outcome."""

    outcome: Literal[0, 1]
    brier: float = Field(ge=0.0, le=1.0)
    outcome_timestamp: datetime = Field(default_factory=utc_now)


class FitnessSnapshot(BaseModel):
    """Fitness audit entry for one agent and generation."""

    model_config = ConfigDict(extra="forbid")

    generation: int
    n_forecasts: int
    brier: float | None = None
    brier_per_regime: dict[RegimeTag, float] = Field(default_factory=dict)
    novelty: float = 0.0
    raw_fitness: float | None = None
    effective_fitness: float | None = None
    failed_outputs: int = 0


class MutationEvent(BaseModel):
    """Inspectable prompt mutation event."""

    model_config = ConfigDict(extra="forbid")

    section: Literal["role", "framework", "heuristics", "examples", "output_schema"]
    directive: str
    timestamp: datetime = Field(default_factory=utc_now)
    accepted: bool = True
    error: str | None = None


class LineageRecord(BaseModel):
    """Complete prompt lineage record."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    role: str
    parent_ids: list[str] = Field(default_factory=list, max_length=2)
    generation: int = 0
    birth_timestamp: datetime = Field(default_factory=utc_now)
    mutation_log: list[MutationEvent] = Field(default_factory=list)
    fitness_history: list[FitnessSnapshot] = Field(default_factory=list)
    embedding: list[float] = Field(default_factory=list)
    prompt_yaml: str
    status: LineageStatus = "alive"
    new_forecasts_since_generation: int = 0
    failed_output_count: int = 0

    @field_validator("parent_ids")
    @classmethod
    def validate_parent_count(cls, value: list[str]) -> list[str]:
        if len(value) > 2:
            raise ValueError("parent_ids supports seed, mutation, or crossover only")
        return value
