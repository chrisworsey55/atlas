from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, UTC

import pytest

from darwin_v3.breeding import BreedingSelector
from darwin_v3.gene_pool import GenePool
from darwin_v3.postmortem_engine import PostMortemEngine, TradeRecord


def test_postmortem_engine_detects_real_losing_trade(tmp_path: Path) -> None:
    out_dir = tmp_path / "postmortems"
    engine = PostMortemEngine(output_dir=out_dir, cache_dir=out_dir / "cache", llm_runner=lambda prompt: {
        "diagnosis": "Bought the spike without validation.",
        "missed_signals": ["no agent swarm", "panic buying"],
        "knowledge_gaps": ["process discipline"],
        "regime_mismatch": True,
        "suggested_donors": ["cro"],
        "spawn_candidate": False,
        "spawn_description": None,
    })
    trade = TradeRecord(
        date="2026-03-02",
        ticker="GLD",
        action="BUY",
        shares=306,
        price=490.0,
        agent="manual",
        thesis="Geopolitical hedge on Iran strike spike",
        status="CLOSED",
        close_price=468.0,
        pnl=-6024.0,
    )
    result = engine.generate_postmortem(trade, regime="crisis", vix=28.0)
    payload = json.loads(result.path.read_text())
    assert payload["diagnosis"]
    assert payload["missed_signals"]
    assert payload["knowledge_gaps"]
    assert payload["regime_mismatch"] is True
    assert "spawn_candidate" in payload
    assert payload["trade_context"]["return_pct"] < 0


def test_postmortem_engine_handles_no_losing_trade(tmp_path: Path) -> None:
    engine = PostMortemEngine(output_dir=tmp_path / "postmortems", cache_dir=tmp_path / "postmortems" / "cache")
    trade = TradeRecord(
        date="2026-03-03",
        ticker="AVGO",
        action="BUY",
        shares=157,
        price=318.82,
        agent="fundamental",
        thesis="Undervalued",
        status="OPEN",
    )
    assert not trade.is_closed_loss
    assert engine.find_triggers([trade]) == []


def test_breeding_selector_paths(tmp_path: Path) -> None:
    pool = GenePool(db_path=tmp_path / "gene_pool.db", seed=False, reset=True)
    pool.seed_from_repo()
    # Add synthetic entries so the selector can exercise targeted splice and restoration paths.
    donor = pool._build_entry(
        agent_id="synthetic_credit",
        version=1,
        prompt_path="agents/prompts/synthetic_credit.md",
        prompt_text="You analyze credit spread widening and tightening liquidity conditions.",
        git_commit="SYNTHETIC",
        created_at="2026-03-10T00:00:00+00:00",
        source_kind="manual_seed",
        source_ref="test",
        status="active",
    )
    donor = pool._replace_entry(donor, status="active")
    pool._write_entries([donor])

    selector = BreedingSelector(pool, tmp_path / "empty_postmortems", tmp_path / "breeding_log.json")
    blind = selector.select_rewrite_strategy("volatility_desk", 1, current_regime="bull", current_score=-1.0)
    assert blind.type == "blind_mutation"

    pm_dir = tmp_path / "postmortems"
    pm_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(tz=UTC).isoformat()
    (pm_dir / "volatility_desk_2026-05-02_single_trade_loss_over_3pct.json").write_text(json.dumps({
        "date": now,
        "knowledge_gaps": ["credit_spread"],
        "spawn_candidate": False,
    }))
    targeted_selector = BreedingSelector(pool, pm_dir, tmp_path / "breeding_log_1.json")
    targeted = targeted_selector.select_rewrite_strategy("volatility_desk", 1, current_regime="tightening", current_score=-1.0)
    assert targeted.type == "targeted_splice"

    historical = pool._build_entry(
        agent_id="volatility",
        version=2,
        prompt_path="agents/prompts/volatility.md",
        prompt_text="You analyze volatility regimes and tightening conditions. VIX and spread widening matter.",
        git_commit="SYNTHETIC_HISTORY",
        created_at="2026-03-11T00:00:00+00:00",
        source_kind="manual_seed",
        source_ref="test",
        status="active",
    )
    historical = pool._replace_entry(historical, status="active")
    pool._write_entries([historical])

    pm_dir_2 = tmp_path / "postmortems_restoration"
    pm_dir_2.mkdir(parents=True, exist_ok=True)
    (pm_dir_2 / "volatility_desk_2026-05-02_single_trade_loss_over_3pct.json").write_text(json.dumps({
        "date": now,
        "knowledge_gaps": ["rare_gap_no_donor"],
        "spawn_candidate": False,
    }))
    restoration_selector = BreedingSelector(pool, pm_dir_2, tmp_path / "breeding_log_2.json")
    restoration = restoration_selector.select_rewrite_strategy("volatility_desk", 1, current_regime="tightening", current_score=-10.0)
    assert restoration.type == "regime_restoration"


def test_breeding_selector_trigger_spawn(tmp_path: Path) -> None:
    pool = GenePool(db_path=tmp_path / "gene_pool.db", seed=False, reset=True)
    pool.seed_from_repo()
    pm_dir = tmp_path / "postmortems"
    pm_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(tz=UTC).isoformat()
    for i in range(3):
        (pm_dir / f"unknown_agent_2026-05-0{i+1}_single_trade_loss_over_3pct.json").write_text(json.dumps({
            "date": now,
            "knowledge_gaps": [f"rare_gap_{i}"],
            "spawn_candidate": True,
            "spawn_description": f"rare gap {i}",
        }))
    selector = BreedingSelector(pool, pm_dir, tmp_path / "breeding_log.json")
    strategy = selector.select_rewrite_strategy("unknown_agent", 1, current_regime="crisis", current_score=-1.0)
    assert strategy.type in {"trigger_spawn", "blind_mutation"}
    assert (tmp_path / "breeding_log.json").exists()
