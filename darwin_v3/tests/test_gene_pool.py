from __future__ import annotations

from pathlib import Path

import pytest

from darwin_v3.gene_pool import GenePool, seed_default_gene_pool


@pytest.fixture()
def seeded_pool(tmp_path: Path) -> GenePool:
    db_path = tmp_path / "gene_pool.db"
    pool = GenePool(db_path=db_path, seed=False, reset=True)
    summary = pool.seed_from_repo()
    assert summary.git_day_commits > 0
    assert summary.git_revert_commits > 0
    return pool


def test_db_seeded_from_git_history(seeded_pool: GenePool) -> None:
    entries = seeded_pool.list_entries()
    assert entries
    assert seeded_pool.db_path.exists()


def test_find_best_for_regime_runs_cleanly(seeded_pool: GenePool) -> None:
    results = seeded_pool.find_best_for_regime("volatility_desk", "bull")
    assert isinstance(results, list)


def test_find_donors_runs_cleanly(seeded_pool: GenePool) -> None:
    results = seeded_pool.find_donors(["credit_spread"], "tightening")
    assert isinstance(results, list)


def test_find_analogues_runs_cleanly(seeded_pool: GenePool) -> None:
    results = seeded_pool.find_analogues("tightening", lookback_days=30)
    assert isinstance(results, list)


def test_get_extinct_returns_list(seeded_pool: GenePool) -> None:
    results = seeded_pool.get_extinct()
    assert isinstance(results, list)


def test_search_runs_cleanly(seeded_pool: GenePool) -> None:
    results = seeded_pool.search(["volatility"])
    assert isinstance(results, list)


def test_seed_default_gene_pool_creates_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Smoke test the module-level convenience entrypoint without touching the shared DB.
    from darwin_v3 import gene_pool as gene_pool_module

    monkeypatch.setattr(gene_pool_module, "DEFAULT_DB_PATH", tmp_path / "gene_pool.db")
    summary = seed_default_gene_pool(reset=True)
    assert summary.git_day_commits > 0
