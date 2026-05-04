from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from darwin_v3.breeding import RewriteStrategy
from darwin_v3.runtime import DarwinV3Runtime


@dataclass
class _DummyPMResult:
    path: Path
    cached: bool = False


class _DummyGenePool:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs


class _DummyPostMortemEngine:
    def __init__(self, repo_root: Path, *args, **kwargs) -> None:
        self.repo_root = repo_root
        self.kwargs = kwargs
        self.output_dir = repo_root / "darwin_v3" / "postmortems"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run_from_default_sources(self):
        path = self.output_dir / "manual_2026-03-02_single_trade_loss_over_3pct.json"
        path.write_text(
            json.dumps(
                {
                    "agent_id": "manual",
                    "agent_version": 1,
                    "regime": "bull",
                    "date": "2026-03-02",
                    "knowledge_gaps": ["credit_spread"],
                    "spawn_candidate": False,
                },
                indent=2,
            )
        )
        return [_DummyPMResult(path=path)]


class _DummyBreedingSelector:
    def __init__(self, gene_pool, postmortem_dir, log_path, *args, **kwargs) -> None:
        self.gene_pool = gene_pool
        self.postmortem_dir = postmortem_dir
        self.log_path = log_path
        self.kwargs = kwargs

    def select_rewrite_strategy(self, agent_id: str, current_version: int, current_regime: str = "unknown", current_score: float | None = None):
        return RewriteStrategy(
            type="blind_mutation",
            reason=f"stub for {agent_id}",
            confidence=0.2,
        )


def test_runtime_writes_judge_and_janus_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_dir = tmp_path / "data" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "scored_outcomes.json").write_text(
        json.dumps(
            [
                {
                    "cohort": "18month",
                    "date": "2026-03-01",
                    "ticker": "GLD",
                    "direction": "LONG",
                    "conviction": 70,
                    "actual_return": -0.02,
                    "is_hit": False,
                    "weighted_return": -0.014,
                    "agents": ["manual"],
                },
                {
                    "cohort": "10year",
                    "date": "2026-03-01",
                    "ticker": "TLT",
                    "direction": "LONG",
                    "conviction": 70,
                    "actual_return": 0.03,
                    "is_hit": True,
                    "weighted_return": 0.021,
                    "agents": ["manual"],
                },
            ],
            indent=2,
        )
    )
    (state_dir / "agent_views.json").write_text(json.dumps({"views": {"cio": "HOLD"}}))
    (state_dir / "cio_synthesis.json").write_text(json.dumps({"summary": "CIO stub"}))

    from agents import janus as janus_module

    monkeypatch.setattr(janus_module, "STATE_DIR", state_dir)
    monkeypatch.setattr("darwin_v3.runtime.GenePool", _DummyGenePool)
    monkeypatch.setattr("darwin_v3.runtime.PostMortemEngine", _DummyPostMortemEngine)
    monkeypatch.setattr("darwin_v3.runtime.BreedingSelector", _DummyBreedingSelector)
    monkeypatch.setattr(
        "darwin_v3.runtime.load_scorecards",
        lambda: {
            "recommendations": [],
            "agent_metrics": {"manual": {"sharpe_ratio": 0.0}},
            "last_updated": "2026-03-01T00:00:00",
        },
    )

    runtime = DarwinV3Runtime(repo_root=tmp_path)
    result = runtime.run_once()

    judge_file = state_dir / "judge_daily.json"
    janus_file = state_dir / "janus_daily.json"
    v3_decisions_file = state_dir / "decisions_v3.json"

    assert judge_file.exists()
    assert janus_file.exists()
    assert v3_decisions_file.exists()
    assert result["steps"]["judge"]["status"] == "ok"
    assert result["steps"]["janus"]["status"] == "ok"
    assert result["steps"]["janus"]["details"]["input_source"] == "judge_daily.json"

    judge_payload = json.loads(judge_file.read_text())
    assert set(judge_payload["cohorts"]) == {"18month", "10year"}

    janus_payload = json.loads(janus_file.read_text())
    assert janus_payload["input_source"] == "judge_daily.json"
    assert janus_payload["judge_input"]["cohorts"]["18month"]["hit_rate"] < 0.6
