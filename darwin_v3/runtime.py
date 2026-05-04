"""Phase 9 integration runtime for Darwin v3."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import statistics
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from agents.janus import Janus
from agents.scorecard import load_scorecards

from .breeding import BreedingSelector
from .config import REPO_ROOT
from .gene_pool import GenePool
from .postmortem_engine import PostMortemEngine


@dataclass(frozen=True)
class DarwinV3StepResult:
    status: str
    details: dict[str, Any]


class DarwinV3Runtime:
    """
    Non-blocking Darwin v3 integration layer for the live daily loop.

    This does not replace the v2 loop. It passively consumes the existing
    daily state files, writes v3 artifacts, and returns a structured summary.
    """

    def __init__(self, repo_root: Path | None = None, simulation_date: date | None = None) -> None:
        self.repo_root = repo_root or REPO_ROOT
        self.simulation_date = simulation_date or datetime.now(tz=UTC).date()
        self.state_dir = self.repo_root / "data" / "state"
        self.v3_dir = self.repo_root / "darwin_v3"
        self.judge_file = self.state_dir / "judge_daily.json"
        self.v3_decisions_file = self.state_dir / "decisions_v3.json"
        self.v3_log_file = self.v3_dir / "phase9_daily.json"
        self.agent_views_file = self.state_dir / "agent_views.json"
        self.cio_file = self.state_dir / "cio_synthesis.json"
        self.scored_outcomes_file = self.state_dir / "scored_outcomes.json"
        self.breeding_log_file = self.v3_dir / "breeding_log.json"
        self.postmortem_dir = self.v3_dir / "postmortems"
        self.gene_pool = GenePool(seed=False, repo_root=self.repo_root, simulation_date=self.simulation_date)
        self.postmortem_engine = PostMortemEngine(repo_root=self.repo_root, simulation_date=self.simulation_date)
        self.breeding_selector = BreedingSelector(
            gene_pool=self.gene_pool,
            postmortem_dir=self.postmortem_dir,
            log_path=self.breeding_log_file,
            simulation_date=self.simulation_date,
        )
        self.janus = Janus(cohorts=["18month", "10year"])

    def run_once(self, simulation_date: date | None = None) -> dict[str, Any]:
        """
        Run the Darwin v3 pass-through stack once.

        Returns:
            Structured summary of the v3 step outputs.
        """
        effective_date = simulation_date or self.simulation_date
        started_at = datetime.now(tz=UTC).isoformat()
        summary: dict[str, Any] = {
            "started_at": started_at,
            "repo_root": str(self.repo_root),
            "steps": {},
            "simulation_date": effective_date.isoformat(),
        }

        scorer_result = self._run_scorer()
        summary["steps"]["scorer"] = scorer_result

        postmortem_result = self._run_postmortems(simulation_date=effective_date)
        summary["steps"]["postmortem"] = postmortem_result

        breeding_result = self._run_breeding(postmortem_result, simulation_date=effective_date)
        summary["steps"]["breeding"] = breeding_result

        agent_debate_result = self._load_state_snapshot(self.agent_views_file)
        summary["steps"]["agent_debate"] = {
            "status": "ok" if agent_debate_result else "missing",
            "details": {
                "has_agent_views": bool(agent_debate_result),
                "has_cio": self.cio_file.exists(),
            },
        }

        judge_payload = self._build_judge_payload(
            scorer_result,
            postmortem_result,
            breeding_result,
            agent_debate_result,
            simulation_date=effective_date,
        )
        self._write_json(self.judge_file, judge_payload)
        summary["steps"]["judge"] = {
            "status": "ok",
            "details": {
                "path": str(self.judge_file),
                "cohorts": list(judge_payload.get("cohorts", {}).keys()),
            },
        }

        try:
            janus_result = self.janus.run_daily(judge_payload=judge_payload)
            summary["steps"]["janus"] = {
                "status": "ok",
                "details": {
                    "path": str(self.janus.daily_file),
                    "input_source": janus_result.get("input_source"),
                    "regime": janus_result.get("regime"),
                },
            }
        except Exception as exc:
            summary["steps"]["janus"] = {
                "status": "error",
                "details": {"error": str(exc)},
            }

        cio_snapshot = self._load_state_snapshot(self.cio_file)
        summary["steps"]["cio"] = {
            "status": "ok" if cio_snapshot else "missing",
            "details": {
                "has_cio": bool(cio_snapshot),
                "janus_file": str(self.janus.daily_file),
            },
        }

        summary["ended_at"] = datetime.now(tz=UTC).isoformat()
        self._write_json(self.v3_decisions_file, summary)
        self._write_json(self.v3_log_file, summary)
        return summary

    def _run_scorer(self) -> dict[str, Any]:
        try:
            scorecards = load_scorecards()
            recommendations = scorecards.get("recommendations", [])
            agent_metrics = scorecards.get("agent_metrics", {})
            return {
                "status": "ok",
                "details": {
                    "recommendation_count": len(recommendations),
                    "agent_count": len(agent_metrics),
                    "last_updated": scorecards.get("last_updated"),
                },
            }
        except Exception as exc:
            return {"status": "error", "details": {"error": str(exc)}}

    def _run_postmortems(self, simulation_date: date | None = None) -> dict[str, Any]:
        try:
            results = self.postmortem_engine.run_from_default_sources(simulation_date=simulation_date)
            return {
                "status": "ok",
                "details": {
                    "count": len(results),
                    "paths": [str(result.path) for result in results],
                    "cached": sum(1 for result in results if result.cached),
                },
            }
        except Exception as exc:
            return {"status": "error", "details": {"error": str(exc)}}

    def _run_breeding(self, postmortem_result: dict[str, Any], simulation_date: date | None = None) -> dict[str, Any]:
        try:
            postmortem_paths = postmortem_result.get("details", {}).get("paths", [])
            strategies: list[dict[str, Any]] = []
            for path_text in postmortem_paths:
                path = Path(path_text)
                try:
                    payload = json.loads(path.read_text())
                except Exception:
                    continue
                agent_id = str(payload.get("agent_id", "unknown"))
                strategy = self.breeding_selector.select_rewrite_strategy(
                    agent_id=agent_id,
                    current_version=int(payload.get("agent_version") or 0),
                    current_regime=str(payload.get("regime") or "unknown"),
                    current_score=None,
                    simulation_date=simulation_date,
                )
                strategies.append(asdict(strategy))

            return {
                "status": "ok",
                "details": {
                    "strategy_count": len(strategies),
                    "strategies": strategies,
                },
            }
        except Exception as exc:
            return {"status": "error", "details": {"error": str(exc)}}

    def _build_judge_payload(
        self,
        scorer_result: dict[str, Any],
        postmortem_result: dict[str, Any],
        breeding_result: dict[str, Any],
        agent_debate_result: dict[str, Any] | None,
        simulation_date: date | None = None,
    ) -> dict[str, Any]:
        outcomes = self._load_scored_outcomes()
        cohorts: dict[str, dict[str, Any]] = {}

        grouped: dict[str, list[dict[str, Any]]] = {}
        for outcome in outcomes:
            cohort = str(outcome.get("cohort", "unknown"))
            grouped.setdefault(cohort, []).append(outcome)

        for cohort, cohort_outcomes in grouped.items():
            hits = sum(1 for item in cohort_outcomes if bool(item.get("is_hit")))
            weighted_returns = [float(item.get("weighted_return", 0.0) or 0.0) for item in cohort_outcomes]
            if len(weighted_returns) >= 2:
                mean_return = sum(weighted_returns) / len(weighted_returns)
                std_dev = statistics.stdev(weighted_returns)
                sharpe = mean_return / std_dev if std_dev else 0.0
            else:
                sharpe = weighted_returns[0] if weighted_returns else 0.0
            cohorts[cohort] = {
                "hit_rate": hits / len(cohort_outcomes) if cohort_outcomes else 0.5,
                "sharpe": sharpe,
                "judge_confidence": min(1.0, len(cohort_outcomes) / 20.0),
                "sample_size": len(cohort_outcomes),
            }

        if not cohorts:
            cohorts = {
                "18month": {"hit_rate": 0.5, "sharpe": 0.0, "judge_confidence": 0.5, "sample_size": 0},
                "10year": {"hit_rate": 0.5, "sharpe": 0.0, "judge_confidence": 0.5, "sample_size": 0},
            }

        regime = self._derive_regime(cohorts)
        effective_date = simulation_date or self.simulation_date
        return {
            "date": effective_date.isoformat(),
            "generated_at": datetime.now(tz=UTC).isoformat(),
            "input_source": "scored_outcomes.json",
            "cohorts": cohorts,
            "regime": regime,
            "scorer": scorer_result,
            "postmortems": postmortem_result,
            "breeding": breeding_result,
            "agent_debate": {
                "has_agent_views": bool(agent_debate_result),
                "has_cio": self.cio_file.exists(),
            },
        }

    def _derive_regime(self, cohorts: dict[str, dict[str, Any]]) -> str:
        short = float(cohorts.get("18month", {}).get("sharpe", 0.0) or 0.0)
        long = float(cohorts.get("10year", {}).get("sharpe", 0.0) or 0.0)
        delta = short - long
        if delta > 0.15:
            return "NOVEL_REGIME"
        if delta < -0.15:
            return "HISTORICAL_REGIME"
        return "MIXED"

    def _load_scored_outcomes(self) -> list[dict[str, Any]]:
        if not self.scored_outcomes_file.exists():
            return []
        try:
            data = json.loads(self.scored_outcomes_file.read_text())
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _load_state_snapshot(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))
