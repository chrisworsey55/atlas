"""
Fundamental Analysis Batch Runner
Runs the fundamental agent across any universe of stocks.
Saves progress incrementally and produces ranked summaries.

Usage:
  python -m agents.fundamental_batch --universe data/state/us_universe.json --resume
  python -m agents.fundamental_batch --full  # S&P 500 only
"""
import json
import logging
import time
import argparse
from typing import Optional, List, Dict
from datetime import datetime
from pathlib import Path
from collections import defaultdict

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.fundamental_agent import FundamentalAgent, format_large_number

logger = logging.getLogger(__name__)

# File paths
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STATE_DIR = DATA_DIR / "state"

# Rate limiting
API_DELAY_SECONDS = 2  # Delay between API calls
BATCH_SIZE = 50  # Print progress every N tickers
SAVE_INTERVAL = 10  # Save progress every N tickers


class UniverseScreener:
    """Screens any universe of stocks using the fundamental agent."""

    def __init__(self, universe_file: str = None, universe_name: str = "sp500"):
        """
        Initialize the screener.

        Args:
            universe_file: Path to JSON file containing universe (or None for S&P 500)
            universe_name: Name for output files (e.g., "sp500", "full_universe")
        """
        self.universe_name = universe_name
        self.universe_file = Path(universe_file) if universe_file else None

        # Set output file paths based on universe name
        self.valuations_file = STATE_DIR / f"{universe_name}_valuations.json"
        self.progress_file = STATE_DIR / f"{universe_name}_progress.json"
        self.tickers_file = DATA_DIR / f"{universe_name}_tickers.txt"

        # Initialize agent
        self.agent = FundamentalAgent()

    def load_tickers(self) -> List[str]:
        """Load tickers from universe file or S&P 500 list."""
        if self.universe_file and self.universe_file.exists():
            logger.info(f"Loading universe from {self.universe_file}")
            with open(self.universe_file, "r") as f:
                data = json.load(f)

            # Handle different formats
            if isinstance(data, dict) and "stocks" in data:
                tickers = [s["ticker"] for s in data["stocks"]]
            elif isinstance(data, list):
                if data and isinstance(data[0], dict):
                    tickers = [s.get("ticker") or s.get("symbol") for s in data]
                else:
                    tickers = data
            else:
                raise ValueError(f"Unknown universe file format: {self.universe_file}")

            logger.info(f"Loaded {len(tickers)} tickers from universe file")
            return tickers

        # Fall back to S&P 500 tickers file
        sp500_file = DATA_DIR / "sp500_tickers.txt"
        if sp500_file.exists():
            with open(sp500_file, "r") as f:
                tickers = [line.strip() for line in f if line.strip()]
            logger.info(f"Loaded {len(tickers)} S&P 500 tickers")
            return tickers

        raise FileNotFoundError("No universe file or S&P 500 tickers found")

    def load_progress(self) -> Dict:
        """Load progress from previous run."""
        if self.progress_file.exists():
            try:
                with open(self.progress_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {
            "completed": [],
            "failed": [],
            "last_ticker": None,
            "started_at": None,
            "universe_name": self.universe_name,
        }

    def save_progress(self, progress: Dict):
        """Save progress to file."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(self.progress_file, "w") as f:
            json.dump(progress, f, indent=2, default=str)

    def load_valuations(self) -> List[Dict]:
        """Load existing valuations."""
        if self.valuations_file.exists():
            try:
                with open(self.valuations_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return []

    def save_valuations(self, valuations: List[Dict]):
        """Save valuations to file."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(self.valuations_file, "w") as f:
            json.dump(valuations, f, indent=2, default=str)

    def run(
        self,
        resume: bool = False,
        max_tickers: int = None,
        sector_filter: str = None,
    ) -> List[Dict]:
        """
        Run fundamental analysis on the universe.

        Args:
            resume: If True, resume from where previous run left off
            max_tickers: Maximum number of tickers to process
            sector_filter: Only process tickers from this sector

        Returns:
            List of valuation results
        """
        # Load tickers
        tickers = self.load_tickers()
        total_tickers = len(tickers)

        # Load progress and valuations
        progress = self.load_progress()
        valuations = self.load_valuations()
        existing_tickers = {v.get("ticker"): v for v in valuations}

        # Filter based on resume
        if resume:
            completed = set(progress.get("completed", []))
            tickers = [t for t in tickers if t not in completed]
            logger.info(f"Resuming: {len(completed)} completed, {len(tickers)} remaining")
        else:
            progress = {
                "completed": [],
                "failed": [],
                "last_ticker": None,
                "started_at": datetime.now().isoformat(),
                "universe_name": self.universe_name,
                "total_tickers": total_tickers,
            }

        # Apply sector filter
        if sector_filter:
            logger.info(f"Filtering for sector: {sector_filter}")
            filtered = []
            for t in tickers:
                try:
                    import yfinance as yf
                    stock = yf.Ticker(t)
                    sector = (stock.info or {}).get("sector", "")
                    if sector_filter.lower() in sector.lower():
                        filtered.append(t)
                except:
                    pass
            tickers = filtered
            logger.info(f"Found {len(tickers)} tickers in {sector_filter} sector")

        # Apply max limit
        if max_tickers:
            tickers = tickers[:max_tickers]

        # Process tickers
        results = []
        batch_start_time = time.time()

        for i, ticker in enumerate(tickers):
            try:
                # Progress logging
                if i > 0 and i % BATCH_SIZE == 0:
                    elapsed = time.time() - batch_start_time
                    rate = BATCH_SIZE / elapsed if elapsed > 0 else 0
                    remaining = len(tickers) - i
                    eta_minutes = remaining / rate / 60 if rate > 0 else 0
                    logger.info(f"\n{'='*60}")
                    logger.info(f"PROGRESS: {i}/{len(tickers)} ({i*100/len(tickers):.1f}%)")
                    logger.info(f"Rate: {rate:.1f} tickers/sec | ETA: {eta_minutes:.0f} minutes")
                    logger.info(f"Completed: {len(progress['completed'])} | Failed: {len(progress['failed'])}")
                    logger.info(f"{'='*60}\n")
                    batch_start_time = time.time()

                logger.info(f"[{i+1}/{len(tickers)}] Analyzing {ticker}...")

                # Skip if recently analyzed
                if ticker in existing_tickers:
                    existing = existing_tickers[ticker]
                    analyzed_at = existing.get("analyzed_at", "")
                    try:
                        analysis_time = datetime.fromisoformat(analyzed_at)
                        age_hours = (datetime.utcnow() - analysis_time).total_seconds() / 3600
                        if age_hours < 24:
                            logger.info(f"  Skipping {ticker} - analyzed {age_hours:.1f}h ago")
                            results.append(existing)
                            if ticker not in progress["completed"]:
                                progress["completed"].append(ticker)
                            continue
                    except (ValueError, TypeError):
                        pass

                # Run analysis
                valuation = self.agent.analyze(ticker, persist=False)

                if valuation:
                    results.append(valuation)

                    # Update valuations list
                    if ticker in existing_tickers:
                        valuations = [v for v in valuations if v.get("ticker") != ticker]
                    valuations.append(valuation)

                    progress["completed"].append(ticker)
                    progress["last_ticker"] = ticker

                    # Log result
                    synthesis = valuation.get("synthesis", {})
                    logger.info(f"  {ticker}: {synthesis.get('verdict')} | "
                               f"Upside: {synthesis.get('upside_to_midpoint_pct', 0):+.1f}% | "
                               f"Confidence: {synthesis.get('confidence', 0)}%")
                else:
                    logger.warning(f"  {ticker}: Analysis failed")
                    progress["failed"].append(ticker)

                # Save incrementally
                if i > 0 and i % SAVE_INTERVAL == 0:
                    self.save_valuations(valuations)
                    self.save_progress(progress)

                # Rate limit
                if i < len(tickers) - 1:
                    time.sleep(API_DELAY_SECONDS)

            except KeyboardInterrupt:
                logger.info("\nInterrupted by user. Saving progress...")
                self.save_valuations(valuations)
                self.save_progress(progress)
                break
            except Exception as e:
                logger.error(f"  {ticker}: Error - {e}")
                progress["failed"].append(ticker)

        # Final save
        progress["finished_at"] = datetime.now().isoformat()
        self.save_valuations(valuations)
        self.save_progress(progress)

        return results

    def generate_summary(self, valuations: List[Dict] = None) -> str:
        """Generate a ranked summary of valuations."""
        if valuations is None:
            valuations = self.load_valuations()

        if not valuations:
            return "No valuations found."

        # Parse valuations
        parsed = []
        for v in valuations:
            synthesis = v.get("synthesis", {})
            ticker = v.get("ticker")
            upside = synthesis.get("upside_to_midpoint_pct")

            if upside is None:
                continue

            parsed.append({
                "ticker": ticker,
                "company": v.get("company_name", ""),
                "sector": v.get("sector", "Unknown"),
                "price": v.get("current_price"),
                "intrinsic_mid": synthesis.get("intrinsic_value_midpoint"),
                "upside": upside,
                "confidence": synthesis.get("confidence", 0),
                "verdict": synthesis.get("verdict", "UNKNOWN"),
            })

        # Sort
        undervalued = sorted([p for p in parsed if p["upside"] > 0],
                             key=lambda x: x["upside"], reverse=True)
        overvalued = sorted([p for p in parsed if p["upside"] < 0],
                            key=lambda x: x["upside"])

        # Build summary
        lines = []
        date_str = datetime.now().strftime("%Y-%m-%d")

        lines.append(f"\n{self.universe_name.upper()} FUNDAMENTAL SCREEN — {date_str}")
        lines.append("=" * 80)
        lines.append(f"\nTotal Companies Analyzed: {len(parsed)}")
        lines.append(f"Undervalued: {len([p for p in parsed if p['verdict'] == 'UNDERVALUED'])}")
        lines.append(f"Fairly Valued: {len([p for p in parsed if p['verdict'] == 'FAIRLY VALUED'])}")
        lines.append(f"Overvalued: {len([p for p in parsed if p['verdict'] == 'OVERVALUED'])}")

        # High conviction buys
        high_conf = [p for p in undervalued if p["confidence"] >= 75 and p["upside"] > 25]
        lines.append(f"\nHigh Conviction Buys (>25% upside, >75% conf): {len(high_conf)}")

        # Top 30 undervalued
        lines.append("\n\nTOP 30 MOST UNDERVALUED")
        lines.append("-" * 80)
        lines.append(f"{'Rank':<5} {'Ticker':<8} {'Price':>10} {'Intrinsic':>12} {'Upside':>10} {'Conf':>6} {'Sector':<20}")
        lines.append("-" * 80)

        for i, p in enumerate(undervalued[:30], 1):
            price_str = f"${p['price']:.2f}" if p['price'] else "N/A"
            intrinsic_str = f"${p['intrinsic_mid']:.0f}" if p['intrinsic_mid'] else "N/A"
            sector = (p['sector'] or 'Unknown')[:18]
            lines.append(f"{i:<5} {p['ticker']:<8} {price_str:>10} {intrinsic_str:>12} "
                        f"{p['upside']:>+9.1f}% {p['confidence']:>5}% {sector:<20}")

        # Top 20 overvalued
        lines.append("\n\nTOP 20 MOST OVERVALUED")
        lines.append("-" * 80)
        lines.append(f"{'Rank':<5} {'Ticker':<8} {'Price':>10} {'Intrinsic':>12} {'Downside':>10} {'Conf':>6}")
        lines.append("-" * 80)

        for i, p in enumerate(overvalued[:20], 1):
            price_str = f"${p['price']:.2f}" if p['price'] else "N/A"
            intrinsic_str = f"${p['intrinsic_mid']:.0f}" if p['intrinsic_mid'] else "N/A"
            lines.append(f"{i:<5} {p['ticker']:<8} {price_str:>10} {intrinsic_str:>12} "
                        f"{p['upside']:>+9.1f}% {p['confidence']:>5}%")

        # Sector summary
        sector_stats = defaultdict(lambda: {"count": 0, "total_upside": 0})
        for p in parsed:
            sector = p["sector"] or "Unknown"
            sector_stats[sector]["count"] += 1
            sector_stats[sector]["total_upside"] += p["upside"]

        lines.append("\n\nSECTOR SUMMARY")
        lines.append("-" * 80)
        lines.append(f"{'Sector':<30} {'Count':>8} {'Avg Upside':>12}")
        lines.append("-" * 80)

        for sector, stats in sorted(sector_stats.items(),
                                    key=lambda x: x[1]["total_upside"]/x[1]["count"] if x[1]["count"] > 0 else 0,
                                    reverse=True)[:15]:
            avg_upside = stats["total_upside"] / stats["count"] if stats["count"] > 0 else 0
            lines.append(f"{sector[:28]:<30} {stats['count']:>8} {avg_upside:>+11.1f}%")

        # Market aggregate
        if parsed:
            median_upside = sorted([p["upside"] for p in parsed])[len(parsed)//2]
            avg_upside = sum(p["upside"] for p in parsed) / len(parsed)

            lines.append("\n\nMARKET AGGREGATE")
            lines.append("-" * 80)
            lines.append(f"Median Upside/Downside: {median_upside:+.1f}%")
            lines.append(f"Average Upside/Downside: {avg_upside:+.1f}%")

        return "\n".join(lines)

    def show_progress(self):
        """Show current progress."""
        progress = self.load_progress()
        valuations = self.load_valuations()

        print(f"\nUniverse: {self.universe_name}")
        print(f"Started: {progress.get('started_at', 'N/A')}")
        print(f"Finished: {progress.get('finished_at', 'Not finished')}")
        print(f"Completed: {len(progress.get('completed', []))}")
        print(f"Failed: {len(progress.get('failed', []))}")
        print(f"Valuations: {len(valuations)}")

        if valuations:
            print(self.generate_summary(valuations))


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    parser = argparse.ArgumentParser(description="ATLAS Fundamental Batch Runner")
    parser.add_argument("--universe", help="Path to universe JSON file")
    parser.add_argument("--name", help="Universe name for output files (default: auto)")
    parser.add_argument("--full", action="store_true", help="Run full screen (no resume)")
    parser.add_argument("--resume", action="store_true", help="Resume from previous run")
    parser.add_argument("--results", action="store_true", help="Show latest results")
    parser.add_argument("--sector", help="Filter by sector")
    parser.add_argument("--max", type=int, help="Max tickers to process")
    parser.add_argument("--tickers", help="Comma-separated list of specific tickers")
    args = parser.parse_args()

    # Determine universe name
    if args.name:
        universe_name = args.name
    elif args.universe:
        # Extract name from file path
        universe_name = Path(args.universe).stem.replace("_universe", "").replace("universe_", "")
        if not universe_name or universe_name == "us":
            universe_name = "full_universe"
    else:
        universe_name = "sp500"

    print("\n" + "=" * 80)
    print(f"ATLAS Fundamental Batch Runner - {universe_name.upper()}")
    print("=" * 80 + "\n")

    # Initialize screener
    screener = UniverseScreener(
        universe_file=args.universe,
        universe_name=universe_name,
    )

    if args.results:
        screener.show_progress()

    elif args.full or args.resume:
        # Handle specific tickers
        if args.tickers:
            tickers = [t.strip() for t in args.tickers.split(",")]
            # Create temporary universe
            screener.universe_file = None
            screener.tickers = tickers

        print("Starting batch analysis...")
        print(f"  Universe: {args.universe or 'S&P 500'}")
        print(f"  Output: {screener.valuations_file}")
        print(f"  Resume: {args.resume}")
        print(f"  Sector filter: {args.sector or 'None'}")
        print(f"  Max tickers: {args.max or 'All'}")
        print(f"  Rate limit: {API_DELAY_SECONDS}s between API calls")
        print()

        results = screener.run(
            resume=args.resume,
            max_tickers=args.max,
            sector_filter=args.sector,
        )

        print("\n" + "=" * 80)
        print("BATCH COMPLETE")
        print("=" * 80)
        print(f"Processed: {len(results)} tickers")
        print(screener.generate_summary(results))

    else:
        print("Usage:")
        print("  # S&P 500 screen")
        print("  python -m agents.fundamental_batch --full")
        print("  python -m agents.fundamental_batch --resume")
        print()
        print("  # Full US universe screen")
        print("  python -m agents.fundamental_batch --universe data/state/us_universe.json --full")
        print("  python -m agents.fundamental_batch --universe data/state/us_universe.json --resume")
        print()
        print("  # View results")
        print("  python -m agents.fundamental_batch --results")
        print("  python -m agents.fundamental_batch --universe data/state/us_universe.json --results")
        print()
        print("  # Other options")
        print("  python -m agents.fundamental_batch --sector Technology --max 50")


if __name__ == "__main__":
    main()
