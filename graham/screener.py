from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from graham.config import CACHE_DIR, MIN_AVG_DAILY_VOLUME_DOLLARS, NCAV_THRESHOLD, ensure_dirs
from graham.models import NCAVResult


QUALITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


class GrahamScreener:
    def __init__(self):
        ensure_dirs()

    def screen(self, ncav_results: list[NCAVResult], min_discount_pct: float = 33.0) -> list[NCAVResult]:
        max_ratio = 1 - (min_discount_pct / 100.0)
        screened: list[NCAVResult] = []
        for result in ncav_results:
            if result.is_stale:
                continue
            if result.data_quality_flag == "MANUAL_REVIEW":
                continue
            if not result.current_price or result.current_price <= 0:
                continue
            if not result.avg_daily_volume or result.avg_daily_volume < MIN_AVG_DAILY_VOLUME_DOLLARS:
                continue
            if result.price_to_ncav is None or result.price_to_ncav >= min(max_ratio, NCAV_THRESHOLD):
                continue
            if result.ncav is None or result.ncav <= 0:
                continue
            screened.append(result)
        return screened

    def rank(self, screened: list[NCAVResult]) -> list[NCAVResult]:
        ranked = sorted(
            screened,
            key=lambda result: (
                -(result.ncav_discount_pct or -999),
                QUALITY_ORDER.get(result.ncav_quality, 9),
                -(result.avg_daily_volume or 0),
            ),
        )
        for index, result in enumerate(ranked, start=1):
            result.rank = index
        self._write_cache(ranked)
        return ranked

    def top_n(self, ranked: list[NCAVResult], n: int = 50) -> list[NCAVResult]:
        return ranked[:n]

    def load_latest(self) -> list[NCAVResult]:
        files = sorted(CACHE_DIR.glob("screener_*.json"))
        if not files:
            return []
        return [NCAVResult.from_dict(row) for row in json.loads(files[-1].read_text())]

    def _write_cache(self, ranked: list[NCAVResult]) -> Path:
        date = datetime.now(timezone.utc).date().isoformat()
        path = CACHE_DIR / f"screener_{date}.json"
        path.write_text(json.dumps([result.to_dict() for result in ranked], indent=2, sort_keys=True))
        return path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run GRAHAM screen on cached NCAV results")
    parser.add_argument("path", help="Path to ncav_YYYY-MM-DD.json")
    args = parser.parse_args()
    results = [NCAVResult.from_dict(row) for row in json.loads(Path(args.path).read_text())]
    screener = GrahamScreener()
    ranked = screener.rank(screener.screen(results))
    print(f"screened={len(ranked)}")
