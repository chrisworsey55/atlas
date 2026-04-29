"""Population management for Darwin v2."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Callable

from darwin_v2.config import DarwinConfig
from darwin_v2.embeddings import HashEmbeddingModel
from darwin_v2.fitness import AgentFitness
from darwin_v2.lineage import LineageStore
from darwin_v2.mutation import SectionMutator, prompt_to_yaml
from darwin_v2.prompt import parse_prompt_yaml
from darwin_v2.schema import LineageRecord
from darwin_v2.selection import SelectionResult, select_generation, tournament_parent


class Population:
    """One independently evolving role population."""

    def __init__(
        self,
        role: str,
        store: LineageStore,
        config: DarwinConfig | None = None,
        embedding_model: HashEmbeddingModel | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.role = role
        self.store = store
        self.config = config or DarwinConfig()
        self.embedding_model = embedding_model or HashEmbeddingModel(self.config)
        self.rng = rng or random.Random()

    def alive(self) -> list[LineageRecord]:
        return [record for record in self.store.list_alive(self.role) if record.status in {"alive", "elite"}]

    def seed(self, prompt_yamls: list[str]) -> list[LineageRecord]:
        if len(prompt_yamls) != self.config.agents_per_role:
            raise ValueError(f"Seed requires exactly {self.config.agents_per_role} prompts")
        records: list[LineageRecord] = []
        for prompt_yaml in prompt_yamls:
            parse_prompt_yaml(prompt_yaml)
            record = LineageRecord(
                role=self.role,
                parent_ids=[],
                generation=0,
                prompt_yaml=prompt_yaml,
                embedding=self.embedding_model.embed(prompt_yaml),
                status="alive",
            )
            self.store.add_record(record)
            records.append(record)
        return records

    def generation_due(self, now: datetime | None = None) -> bool:
        records = self.alive()
        if len(records) != self.config.agents_per_role:
            return False
        if all(r.new_forecasts_since_generation >= self.config.min_new_forecasts_per_generation for r in records):
            return True
        current_time = now or datetime.now(timezone.utc)
        oldest_birth = min(r.birth_timestamp for r in records)
        return current_time - oldest_birth >= timedelta(days=self.config.max_generation_days)

    def evolve(
        self,
        fitnesses: list[AgentFitness],
        mutator: SectionMutator,
        selection: SelectionResult | None = None,
    ) -> list[LineageRecord]:
        selection = selection or select_generation(fitnesses, self.config)
        records_by_id = {record.id: record for record in self.alive()}

        children: list[LineageRecord] = []
        next_generation = max(record.generation for record in records_by_id.values()) + 1

        for elite_fit in selection.elites:
            elite = records_by_id[elite_fit.agent_id]
            elite.status = "elite"
            elite.new_forecasts_since_generation = 0
            self.store.update_record(elite)

        for culled_fit in selection.culled:
            culled = records_by_id[culled_fit.agent_id]
            culled.status = "culled"
            self.store.update_record(culled)

        for _ in selection.culled:
            parent_fit = tournament_parent(selection.breeding_pool, self.rng, self.config.tournament_size)
            parent = records_by_id[parent_fit.agent_id]
            parent_prompt = parse_prompt_yaml(parent.prompt_yaml)
            sections = 2 if self.rng.random() < self.config.mutation_rate_two_sections else 1
            mutation = mutator.mutate(parent_prompt, sections_to_mutate=sections)
            child_yaml = prompt_to_yaml(mutation.prompt)
            child = LineageRecord(
                role=self.role,
                parent_ids=[parent.id],
                generation=next_generation,
                mutation_log=mutation.events,
                prompt_yaml=child_yaml,
                embedding=self.embedding_model.embed(child_yaml),
                status="alive",
            )
            self.store.add_record(child)
            children.append(child)

        return children


def build_mock_rewrite(rewrite: Callable[[str], str]) -> Callable[[str, str, str], str]:
    def _llm(section: str, directive: str, request: str) -> str:
        return rewrite(section)

    return _llm
