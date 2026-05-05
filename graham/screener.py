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
        self.rejection_counts: dict[str, int] = {}
        self.rejections: list[dict] = []
        self.closest_misses: list[NCAVResult] = []

    def screen(self, ncav_results: list[NCAVResult], min_discount_pct: float = 33.0, verbose: bool = False) -> list[NCAVResult]:
        max_ratio = 1 - (min_discount_pct / 100.0)
        threshold = min(max_ratio, NCAV_THRESHOLD)
        screened: list[NCAVResult] = []
        self.rejection_counts = {
            "liquidity": 0,
            "ncav_threshold": 0,
            "stale": 0,
            "data_quality": 0,
            "negative_ncav": 0,
        }
        self.rejections = []
        self.closest_misses = []
        for result in ncav_results:
            if result.is_stale:
                self._reject("stale", result, f"FAIL stale: {result.ticker} — filing: {result.filing_date}", verbose)
                continue
            if result.data_quality_flag == "MANUAL_REVIEW":
                self._reject("data_quality", result, f"FAIL data_quality: {result.ticker}", verbose)
                continue
            if not result.current_price or result.current_price <= 0:
                self._reject("liquidity", result, f"FAIL liquidity: {result.ticker} — vol: ${result.avg_daily_volume or 0:,.0f}", verbose)
                continue
            if not result.avg_daily_volume or result.avg_daily_volume < MIN_AVG_DAILY_VOLUME_DOLLARS:
                self._reject("liquidity", result, f"FAIL liquidity: {result.ticker} — vol: ${result.avg_daily_volume or 0:,.0f}", verbose)
                continue
            if result.ncav is None or result.ncav <= 0:
                self._reject("negative_ncav", result, f"FAIL negative_ncav: {result.ticker}", verbose)
                continue
            if result.price_to_ncav is None or result.price_to_ncav >= threshold:
                ratio = "N/A" if result.price_to_ncav is None else f"{result.price_to_ncav:.4f}x"
                self._reject("ncav_threshold", result, f"FAIL ncav_threshold: {result.ticker} — ratio: {ratio}", verbose)
                if result.price_to_ncav is not None and result.price_to_ncav > 0:
                    self.closest_misses.append(result)
                continue
            if verbose:
                print(f"PASS: {result.ticker} — price_to_ncav: {result.price_to_ncav:.4f}")
            screened.append(result)
        self.closest_misses = sorted(self.closest_misses, key=lambda result: result.price_to_ncav or 999)[:10]
        self._write_rejection_report(len(ncav_results), len(screened), threshold)
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

    def _reject(self, category: str, result: NCAVResult, message: str, verbose: bool) -> None:
        self.rejection_counts[category] = self.rejection_counts.get(category, 0) + 1
        self.rejections.append(
            {
                "category": category,
                "ticker": result.ticker,
                "cik": result.cik,
                "company_name": result.company_name,
                "filing_date": result.filing_date,
                "price_to_ncav": result.price_to_ncav,
                "ncav": result.ncav,
                "avg_daily_volume": result.avg_daily_volume,
                "data_quality_flag": result.data_quality_flag,
            }
        )
        if verbose:
            print(message)

    def _write_rejection_report(self, processed_count: int, passing_count: int, threshold: float) -> Path:
        date = datetime.now(timezone.utc).date().isoformat()
        path = CACHE_DIR / f"screener_rejections_{date}.json"
        payload = {
            "date": date,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "processed_count": processed_count,
            "passing_count": passing_count,
            "threshold": threshold,
            "rejection_counts": self.rejection_counts,
            "closest_misses": [result.to_dict() for result in self.closest_misses],
            "rejections": self.rejections,
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True))
        return path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run GRAHAM screen on cached NCAV results")
    parser.add_argument("path", help="Path to ncav_YYYY-MM-DD.json")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    results = [NCAVResult.from_dict(row) for row in json.loads(Path(args.path).read_text())]
    screener = GrahamScreener()
    ranked = screener.rank(screener.screen(results, verbose=args.verbose))
    print(f"screened={len(ranked)}")
