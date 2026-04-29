"""Lineage persistence for Darwin v2.

SQLite is the queryable index. JSON files store full prompt records and
embeddings so prompt diffs stay readable in git.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from darwin_v2.config import DarwinConfig
from darwin_v2.schema import FitnessSnapshot, ForecastRecord, LineageRecord, LineageStatus, ScoredForecast


class LineageStore:
    """SQLite + JSON persistence for prompt lineage."""

    def __init__(self, config: DarwinConfig | None = None) -> None:
        self.config = config or DarwinConfig()
        self.db_path = self.config.lineage_db
        self.prompt_dir = self.config.prompt_dir
        self.embedding_dir = self.config.embedding_dir
        self.config.lineage_dir.mkdir(parents=True, exist_ok=True)
        self.prompt_dir.mkdir(parents=True, exist_ok=True)
        self.embedding_dir.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS lineage (
                    id TEXT PRIMARY KEY,
                    role TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    birth_timestamp TEXT NOT NULL,
                    parent_ids_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    prompt_path TEXT NOT NULL,
                    embedding_path TEXT NOT NULL,
                    n_fitness_entries INTEGER NOT NULL,
                    new_forecasts_since_generation INTEGER NOT NULL,
                    failed_output_count INTEGER NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_lineage_role_status ON lineage(role, status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_lineage_role_generation ON lineage(role, generation)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS forecasts (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    issued_at TEXT NOT NULL,
                    horizon_days INTEGER NOT NULL,
                    regime TEXT NOT NULL,
                    scored INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_forecasts_agent_scored ON forecasts(agent_id, scored)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_forecasts_role_generation ON forecasts(role, generation)")

    def add_record(self, record: LineageRecord) -> None:
        self._write_json(record)
        self._upsert_index(record)

    def update_record(self, record: LineageRecord) -> None:
        self.add_record(record)

    def get_record(self, agent_id: str) -> LineageRecord:
        prompt_path = self.prompt_dir / f"{agent_id}.json"
        if not prompt_path.exists():
            raise KeyError(f"No lineage record for {agent_id}")
        return LineageRecord.model_validate_json(prompt_path.read_text())

    def list_records(self, role: str | None = None, status: LineageStatus | None = None) -> list[LineageRecord]:
        clauses: list[str] = []
        params: list[str] = []
        if role is not None:
            clauses.append("role = ?")
            params.append(role)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as conn:
            rows = conn.execute(f"SELECT id FROM lineage {where} ORDER BY generation, birth_timestamp", params).fetchall()
        return [self.get_record(row["id"]) for row in rows]

    def list_alive(self, role: str) -> list[LineageRecord]:
        return self.list_records(role=role, status="alive") + self.list_records(role=role, status="elite")

    def update_status(self, agent_id: str, status: LineageStatus) -> LineageRecord:
        record = self.get_record(agent_id)
        record.status = status
        self.update_record(record)
        return record

    def append_fitness(self, agent_id: str, snapshot: FitnessSnapshot) -> LineageRecord:
        record = self.get_record(agent_id)
        record.fitness_history.append(snapshot)
        self.update_record(record)
        return record

    def bulk_add(self, records: Iterable[LineageRecord]) -> None:
        for record in records:
            self.add_record(record)

    def add_forecast(self, forecast: ForecastRecord | ScoredForecast) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO forecasts (
                    id, agent_id, role, generation, issued_at, horizon_days, regime, scored, payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    scored=excluded.scored,
                    payload_json=excluded.payload_json
                """,
                (
                    forecast.id,
                    forecast.agent_id,
                    forecast.role,
                    forecast.generation,
                    forecast.issued_at.isoformat(),
                    forecast.horizon_days,
                    forecast.regime,
                    1 if isinstance(forecast, ScoredForecast) or forecast.scored else 0,
                    forecast.model_dump_json(),
                ),
            )

    def get_forecast(self, forecast_id: str) -> ForecastRecord | ScoredForecast:
        with self.connect() as conn:
            row = conn.execute("SELECT payload_json, scored FROM forecasts WHERE id = ?", (forecast_id,)).fetchone()
        if row is None:
            raise KeyError(f"No forecast record for {forecast_id}")
        if row["scored"]:
            return ScoredForecast.model_validate_json(row["payload_json"])
        return ForecastRecord.model_validate_json(row["payload_json"])

    def list_forecasts(self, agent_id: str | None = None, scored: bool | None = None) -> list[ForecastRecord | ScoredForecast]:
        clauses: list[str] = []
        params: list[object] = []
        if agent_id is not None:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if scored is not None:
            clauses.append("scored = ?")
            params.append(1 if scored else 0)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as conn:
            rows = conn.execute(f"SELECT id FROM forecasts {where} ORDER BY issued_at", params).fetchall()
        return [self.get_forecast(row["id"]) for row in rows]

    def list_scored_forecasts(self, agent_id: str) -> list[ScoredForecast]:
        return [f for f in self.list_forecasts(agent_id=agent_id, scored=True) if isinstance(f, ScoredForecast)]

    def _write_json(self, record: LineageRecord) -> None:
        prompt_path = self.prompt_dir / f"{record.id}.json"
        embedding_path = self.embedding_dir / f"{record.id}.json"
        prompt_path.write_text(record.model_dump_json(indent=2))
        embedding_path.write_text(json.dumps({"id": record.id, "embedding": record.embedding}, indent=2))

    def _upsert_index(self, record: LineageRecord) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO lineage (
                    id, role, generation, birth_timestamp, parent_ids_json, status,
                    prompt_path, embedding_path, n_fitness_entries,
                    new_forecasts_since_generation, failed_output_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    role=excluded.role,
                    generation=excluded.generation,
                    birth_timestamp=excluded.birth_timestamp,
                    parent_ids_json=excluded.parent_ids_json,
                    status=excluded.status,
                    prompt_path=excluded.prompt_path,
                    embedding_path=excluded.embedding_path,
                    n_fitness_entries=excluded.n_fitness_entries,
                    new_forecasts_since_generation=excluded.new_forecasts_since_generation,
                    failed_output_count=excluded.failed_output_count
                """,
                (
                    record.id,
                    record.role,
                    record.generation,
                    record.birth_timestamp.isoformat(),
                    json.dumps(record.parent_ids),
                    record.status,
                    str(self.prompt_dir / f"{record.id}.json"),
                    str(self.embedding_dir / f"{record.id}.json"),
                    len(record.fitness_history),
                    record.new_forecasts_since_generation,
                    record.failed_output_count,
                ),
            )
