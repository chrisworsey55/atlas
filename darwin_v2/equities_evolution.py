"""One-generation Darwin v2 evolution loop for equities."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from darwin_v2.config import DarwinConfig
from darwin_v2.embeddings import cosine_distance
from darwin_v2.equities_adapter import EquitiesAdapter, EquityForecast, ResolvedEquityForecast
from darwin_v2.fitness import AgentFitness
from darwin_v2.lineage import LineageStore
from darwin_v2.mutation import SectionMutator
from darwin_v2.population import Population
from darwin_v2.prompt import parse_prompt_yaml
from darwin_v2.selection import select_generation


DEFAULT_UNIVERSE = ["NVDA", "AMD", "AVGO", "MSFT", "GOOGL", "AMZN", "META", "TSM", "AAPL", "V"]


@dataclass(frozen=True)
class EquitiesEvolutionResult:
    start_date: str
    end_date: str
    requested_universe: list[str]
    available_universe: list[str]
    missing_universe: list[str]
    roles_run: list[str]
    forecasts_scored: int
    agents_mutated: int
    children_created: int
    scorecard_path: str


def _score_to_fitness(agent, scores: list[float], population, config: DarwinConfig) -> AgentFitness:
    mean_score = sum(scores) / len(scores) if scores else None
    neighbours = [other for other in population if other.id != agent.id and other.embedding]
    novelty = 0.0
    if agent.embedding and neighbours:
        distances = sorted(cosine_distance(agent.embedding, other.embedding) for other in neighbours)
        nearest = distances[: min(5, len(distances))]
        novelty = sum(nearest) / len(nearest) if nearest else 0.0
    raw = -mean_score if mean_score is not None else None
    effective = raw + config.novelty_lambda * novelty if raw is not None else None
    return AgentFitness(
        agent_id=agent.id,
        role=agent.role,
        generation=agent.generation,
        n_forecasts=len(scores),
        brier=mean_score,
        brier_per_regime={},
        novelty=novelty,
        raw_fitness=raw,
        effective_fitness=effective,
        eligible=len(scores) >= config.min_scored_forecasts,
        failed_outputs=agent.failed_output_count,
    )


def _forecast_kind(agent_id: str, ticker: str, date: str) -> str:
    kinds = ("binary", "threshold_binary", "multi_class")
    digest = hashlib.sha256(f"{agent_id}:{ticker}:{date}".encode("utf-8")).hexdigest()
    return kinds[int(digest[:8], 16) % len(kinds)]


def _forecast_for(agent, ticker: str, date: str, context: dict[str, object]) -> EquityForecast:
    trailing = float(context.get("trailing_return") or 0.0)
    base_prob = min(0.72, max(0.28, 0.52 + trailing * 1.5))
    kind = _forecast_kind(agent.id, ticker, date)
    digest = hashlib.sha256(f"{agent.id}:{ticker}:horizon".encode("utf-8")).hexdigest()
    horizon_days = 1 + (int(digest[:8], 16) % 4)
    if kind == "threshold_binary":
        return EquityForecast(
            agent_id=agent.id,
            role=agent.role,
            ticker=ticker,
            issued_date=date,
            horizon_days=horizon_days,
            kind="threshold_binary",
            probability=base_prob,
            threshold_pct=2.0,
            rationale="Deterministic Darwin equities threshold forecast from cached OHLCV context.",
        )
    if kind == "multi_class":
        up_weight = base_prob
        down_weight = 1.0 - base_prob
        return EquityForecast(
            agent_id=agent.id,
            role=agent.role,
            ticker=ticker,
            issued_date=date,
            horizon_days=horizon_days,
            kind="multi_class",
            bucket_probabilities={
                "down_gt_3pct": down_weight * 0.35,
                "down_0_3pct": down_weight * 0.65,
                "up_0_3pct": up_weight * 0.65,
                "up_gt_3pct": up_weight * 0.35,
            },
            rationale="Deterministic Darwin equities bucket forecast from cached OHLCV context.",
        )
    return EquityForecast(
        agent_id=agent.id,
        role=agent.role,
        ticker=ticker,
        issued_date=date,
        horizon_days=horizon_days,
        kind="binary",
        probability=base_prob,
        rationale="Deterministic Darwin equities binary forecast from cached OHLCV context.",
    )


def _rewrite(section: str, directive: str, request: str) -> str:
    marker = "Return only the new section, valid YAML, no commentary.\n\n"
    data = yaml.safe_load(request.split(marker, 1)[1])
    current = data[section]
    mutation_note = f"Equities evolution mutation: {directive}; add cached OHLCV base-rate validation."
    if section == "heuristics":
        current = list(current) + [mutation_note]
    elif section == "examples":
        current = list(current) + [{"input": "cached equities OHLCV context", "forecast": {"ticker": "NVDA", "direction": "up", "prob": 0.57}}]
    elif section == "output_schema":
        current = current
    else:
        current = f"{current}\n{mutation_note}"
    return yaml.safe_dump({section: current}, sort_keys=False)


class EquitiesEvolution:
    def __init__(
        self,
        config: DarwinConfig | None = None,
        adapter: EquitiesAdapter | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.config = config or DarwinConfig()
        self.adapter = adapter or EquitiesAdapter()
        self.store = LineageStore(self.config)
        self.rng = rng or random.Random(7)

    def run_one_generation(
        self,
        start_date: str,
        end_date: str,
        universe: list[str] | None = None,
        fetch_missing: bool = False,
    ) -> EquitiesEvolutionResult:
        requested = [ticker.upper() for ticker in (universe or DEFAULT_UNIVERSE)]
        failed_fetch: list[str] = []
        if fetch_missing:
            failed_fetch = self.adapter.fetch_missing_with_atlas_cache(requested, start_date, end_date)
        available = self.adapter.available_tickers(requested, start_date, end_date)
        missing = sorted(set(requested) - set(available) | set(failed_fetch))
        if not available:
            raise RuntimeError("No equities OHLCV data available for requested window")

        scorecard_dir = self.config.lineage_dir / "scorecards"
        scorecard_dir.mkdir(parents=True, exist_ok=True)
        scorecards: dict[str, object] = {
            "start_date": start_date,
            "end_date": end_date,
            "requested_universe": requested,
            "available_universe": available,
            "missing_universe": missing,
            "roles": {},
        }

        total_scored = 0
        total_children = 0
        roles_run: list[str] = []
        mutator = SectionMutator(_rewrite, self.rng)
        dates = self.adapter.trading_dates(available, start_date, end_date)

        for role in self.config.roles:
            population = Population(role, self.store, self.config, rng=self.rng)
            agents = population.alive()
            if len(agents) != self.config.agents_per_role:
                continue
            roles_run.append(role)
            role_cards: dict[str, object] = {}
            fitnesses: list[AgentFitness] = []
            for agent in agents:
                resolved: list[ResolvedEquityForecast] = []
                for date in dates:
                    for ticker in available:
                        try:
                            context = self.adapter.format_context(ticker, date)
                            outcome = self.adapter.resolve_forecast(_forecast_for(agent, ticker, date, context))
                        except Exception:
                            outcome = None
                        if outcome is not None:
                            resolved.append(outcome)
                scores = [item.score for item in resolved]
                total_scored += len(scores)
                fitnesses.append(_score_to_fitness(agent, scores, agents, self.config))
                role_cards[agent.id] = {
                    "generation": agent.generation,
                    "n_forecasts": len(scores),
                    "mean_score": sum(scores) / len(scores) if scores else None,
                    "forecast_type_counts": {
                        kind: sum(1 for item in resolved if item.forecast.kind == kind)
                        for kind in ("binary", "threshold_binary", "multi_class")
                    },
                    "sample": [asdict(item) for item in resolved[:3]],
                }
            selection = select_generation(fitnesses, self.config)
            for fit in fitnesses:
                self.store.append_fitness(fit.agent_id, fit.snapshot())
            children = population.evolve(fitnesses, mutator, selection)
            total_children += len(children)
            scorecards["roles"][role] = {
                "agents": role_cards,
                "elites": [fit.agent_id for fit in selection.elites],
                "culled": [fit.agent_id for fit in selection.culled],
                "children": [child.id for child in children],
            }

        scorecard_path = scorecard_dir / f"equities_{start_date}_{end_date}.json"
        scorecard_path.write_text(json.dumps(scorecards, indent=2, default=str))
        return EquitiesEvolutionResult(
            start_date=start_date,
            end_date=end_date,
            requested_universe=requested,
            available_universe=available,
            missing_universe=missing,
            roles_run=roles_run,
            forecasts_scored=total_scored,
            agents_mutated=total_children,
            children_created=total_children,
            scorecard_path=str(scorecard_path),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one Darwin v2 equities generation")
    parser.add_argument("--start-date", default="2026-01-01")
    parser.add_argument("--end-date", default="2026-01-31")
    parser.add_argument("--universe", nargs="*", default=DEFAULT_UNIVERSE)
    parser.add_argument("--fetch-missing", action="store_true")
    args = parser.parse_args()
    result = EquitiesEvolution().run_one_generation(args.start_date, args.end_date, args.universe, args.fetch_missing)
    print(json.dumps(asdict(result), indent=2))


if __name__ == "__main__":
    main()
