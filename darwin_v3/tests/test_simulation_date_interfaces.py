from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

from darwin_v3.breeding import BreedingSelector, RewriteStrategy
from darwin_v3.gene_pool import GenePool
from darwin_v3.postmortem_engine import PostMortemEngine
from darwin_v3.runtime import DarwinV3Runtime


def test_modules_accept_simulation_date(tmp_path: Path) -> None:
    sim_date = date(2025, 4, 15)

    pool = GenePool(db_path=tmp_path / "gene_pool.db", seed=False, reset=True, simulation_date=sim_date)
    assert pool.simulation_date == sim_date

    pm_engine = PostMortemEngine(output_dir=tmp_path / "postmortems", cache_dir=tmp_path / "postmortems" / "cache", simulation_date=sim_date)
    assert pm_engine.simulation_date == sim_date

    selector = BreedingSelector(pool, tmp_path / "postmortems", tmp_path / "breeding_log.json", simulation_date=sim_date)
    assert selector.simulation_date == sim_date


@dataclass
class _DummyPMResult:
    path: Path
    cached: bool = False


class _DummyGenePool:
    def __init__(self, *args, **kwargs) -> None:
        self.kwargs = kwargs


class _DummyPostMortemEngine:
    def __init__(self, *args, **kwargs) -> None:
        self.kwargs = kwargs
        self.output_dir = Path(kwargs.get("repo_root", Path.cwd())) / "darwin_v3" / "postmortems"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run_from_default_sources(self, simulation_date=None, **kwargs):
        path = self.output_dir / "manual_2025-04-15_single_trade_loss_over_3pct.json"
        path.write_text(
            json.dumps(
                {
                    "agent_id": "manual",
                    "agent_version": 1,
                    "regime": "bull",
                    "date": "2025-04-15",
                    "knowledge_gaps": ["credit_spread"],
                    "spawn_candidate": False,
                },
                indent=2,
            )
        )
        return [_DummyPMResult(path=path)]


class _DummyBreedingSelector:
    def __init__(self, *args, **kwargs) -> None:
        self.kwargs = kwargs

    def select_rewrite_strategy(self, *args, **kwargs):
        return RewriteStrategy(type="blind_mutation", reason="stub", confidence=0.2)


class _DummyJanus:
    def __init__(self, *args, **kwargs) -> None:
        self.daily_file = Path.cwd() / "janus_daily.json"

    def run_daily(self, judge_payload):
        self.daily_file.write_text(json.dumps({"input_source": "judge_daily.json"}))
        return {"input_source": "judge_daily.json", "regime": "bull"}


def test_runtime_passes_simulation_date_through_wrappers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_dir = tmp_path / "data" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "scored_outcomes.json").write_text(json.dumps([{"cohort": "18month", "weighted_return": 0.0, "is_hit": False}]))
    (state_dir / "agent_views.json").write_text(json.dumps({"views": {"cio": "HOLD"}}))
    (state_dir / "cio_synthesis.json").write_text(json.dumps({"summary": "CIO stub"}))

    monkeypatch.setattr("darwin_v3.runtime.GenePool", _DummyGenePool)
    monkeypatch.setattr("darwin_v3.runtime.PostMortemEngine", _DummyPostMortemEngine)
    monkeypatch.setattr("darwin_v3.runtime.BreedingSelector", _DummyBreedingSelector)
    monkeypatch.setattr("darwin_v3.runtime.Janus", _DummyJanus)
    monkeypatch.setattr("darwin_v3.runtime.load_scorecards", lambda: {"recommendations": [], "agent_metrics": {}, "last_updated": "2025-04-15"})

    runtime = DarwinV3Runtime(repo_root=tmp_path, simulation_date=date(2025, 4, 15))
    result = runtime.run_once(simulation_date=date(2025, 4, 15))

    assert result["simulation_date"] == "2025-04-15"
    assert result["steps"]["postmortem"]["status"] == "ok"
    assert result["steps"]["breeding"]["status"] == "ok"
