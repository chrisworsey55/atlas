#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graham.config import CACHE_DIR, OUTPUT_DIR, ensure_dirs
from graham.memo_agent import GrahamMemoAgent
from graham.ncav import NCAVCalculator
from graham.output_generator import GrahamOutputGenerator
from graham.screener import GrahamScreener
from graham.universe import GrahamUniverse


def run_full(test: bool = False, verbose: bool = False) -> dict:
    ensure_dirs()
    universe_builder = GrahamUniverse()
    if test:
        companies = _test_universe(universe_builder)
    else:
        companies = universe_builder.build()
    ciks = [company.cik for company in companies]
    ncav_results = NCAVCalculator(edgar=universe_builder.edgar, price_client=universe_builder.price_client).batch_calculate(ciks)
    screener = GrahamScreener()
    ranked = screener.rank(screener.screen(ncav_results, verbose=verbose))
    memos = GrahamMemoAgent().batch_generate(screener.top_n(ranked, 50))
    outputs = GrahamOutputGenerator().generate(ranked, universe_count=len(companies))
    status = {
        "status": "OK",
        "mode": "test" if test else "full",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "universe_count": len(companies),
        "ncav_count": len(ncav_results),
        "passing_count": len(ranked),
        "memo_count": len(memos),
        "outputs": outputs,
    }
    _write_run_status(status)
    return status


def run_refresh(verbose: bool = False) -> dict:
    ensure_dirs()
    universe_builder = GrahamUniverse()
    companies = universe_builder.get_cached() or universe_builder.build()
    ncav_results = NCAVCalculator(edgar=universe_builder.edgar, price_client=universe_builder.price_client).batch_calculate([c.cik for c in companies])
    screener = GrahamScreener()
    ranked = screener.rank(screener.screen(ncav_results, verbose=verbose))
    memos = GrahamMemoAgent().batch_generate(screener.top_n(ranked, 50))
    outputs = GrahamOutputGenerator().generate(ranked, universe_count=len(companies))
    status = {
        "status": "OK",
        "mode": "refresh",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "universe_count": len(companies),
        "ncav_count": len(ncav_results),
        "passing_count": len(ranked),
        "memo_count": len(memos),
        "outputs": outputs,
    }
    _write_run_status(status)
    return status


def run_memos() -> dict:
    ensure_dirs()
    ranked = GrahamScreener().load_latest()
    memos = GrahamMemoAgent().batch_generate(ranked[:50])
    status = {"status": "OK", "mode": "memos", "as_of": datetime.now(timezone.utc).isoformat(), "memo_count": len(memos)}
    _write_run_status(status)
    return status


def run_status() -> dict:
    path = OUTPUT_DIR / "latest_status.json"
    run_path = OUTPUT_DIR / "run_status.json"
    if run_path.exists():
        return json.loads(run_path.read_text())
    if path.exists():
        return json.loads(path.read_text())
    return {"status": "NOT_RUN", "reason": "No GRAHAM output exists yet"}


def _test_universe(universe_builder: GrahamUniverse) -> list:
    companies = universe_builder._seed_otc_companies()
    random.seed(1956)
    shuffled = random.sample(companies, len(companies))
    selected = []
    for offset in range(0, len(shuffled), 10):
        batch = shuffled[offset : offset + 10]
        batch = universe_builder.filter_active(batch)
        batch = universe_builder.filter_shells(batch)
        batch = universe_builder.filter_liquidity(batch)
        selected.extend(batch)
        if len(selected) >= 10:
            break
    selected = selected[:10]
    universe_builder._write_cache(selected)
    return selected


def _write_run_status(status: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "run_status.json").write_text(json.dumps(status, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description="GRAHAM OTC net-net screener")
    parser.add_argument("--mode", choices=["full", "refresh", "memos", "status", "test"], default="status")
    parser.add_argument("--verbose", action="store_true", help="Print screener pass/fail reasons")
    args = parser.parse_args()
    if args.mode == "full":
        payload = run_full(test=False, verbose=args.verbose)
    elif args.mode == "refresh":
        payload = run_refresh(verbose=args.verbose)
    elif args.mode == "memos":
        payload = run_memos()
    elif args.mode == "test":
        payload = run_full(test=True, verbose=args.verbose)
    else:
        payload = run_status()
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("status") in {"OK", "NOT_RUN"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
