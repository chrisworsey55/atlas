"""
Fundamental Analysis Batch Runner
Runs the fundamental agent across S&P 500 or any ticker list.
Saves progress incrementally and produces ranked summaries.
"""
import json
import logging
import time
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
SP500_TICKERS_FILE = DATA_DIR / "sp500_tickers.txt"
SP500_VALUATIONS_FILE = STATE_DIR / "sp500_valuations.json"
SP500_PROGRESS_FILE = STATE_DIR / "sp500_progress.json"

# Rate limiting
API_DELAY_SECONDS = 5  # Delay between API calls to avoid rate limits


def load_sp500_tickers() -> List[str]:
    """Load S&P 500 tickers from file."""
    if not SP500_TICKERS_FILE.exists():
        raise FileNotFoundError(f"S&P 500 ticker file not found: {SP500_TICKERS_FILE}")

    with open(SP500_TICKERS_FILE, "r") as f:
        tickers = [line.strip() for line in f if line.strip()]

    return tickers


def load_progress() -> Dict:
    """Load progress from previous run."""
    if SP500_PROGRESS_FILE.exists():
        try:
            with open(SP500_PROGRESS_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"completed": [], "failed": [], "last_ticker": None, "started_at": None}


def save_progress(progress: Dict):
    """Save progress to file."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(SP500_PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2, default=str)


def load_valuations() -> List[Dict]:
    """Load existing valuations."""
    if SP500_VALUATIONS_FILE.exists():
        try:
            with open(SP500_VALUATIONS_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return []


def save_valuations(valuations: List[Dict]):
    """Save valuations to file."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(SP500_VALUATIONS_FILE, "w") as f:
        json.dump(valuations, f, indent=2, default=str)


def get_sector_for_ticker(ticker: str) -> str:
    """Get sector for a ticker using yfinance."""
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        info = stock.info or {}
        return info.get("sector", "Unknown")
    except:
        return "Unknown"


def run_batch(
    tickers: List[str] = None,
    resume: bool = False,
    max_tickers: int = None,
    sector_filter: str = None,
) -> List[Dict]:
    """
    Run fundamental analysis on a batch of tickers.

    Args:
        tickers: List of tickers to analyze (defaults to S&P 500)
        resume: If True, resume from where previous run left off
        max_tickers: Maximum number of tickers to process (for testing)
        sector_filter: Only process tickers from this sector

    Returns:
        List of valuation results
    """
    # Load tickers
    if tickers is None:
        tickers = load_sp500_tickers()

    total_tickers = len(tickers)
    logger.info(f"Loaded {total_tickers} tickers for analysis")

    # Load progress and valuations
    progress = load_progress()
    valuations = load_valuations()

    # Create lookup for existing valuations
    existing_tickers = {v.get("ticker"): v for v in valuations}

    # Filter tickers based on resume or existing
    if resume:
        completed = set(progress.get("completed", []))
        failed = set(progress.get("failed", []))
        # Only skip completed tickers, retry failed ones
        tickers = [t for t in tickers if t not in completed]
        # Clear failed list so they can be retried
        failed_to_retry = [t for t in tickers if t in failed]
        if failed_to_retry:
            logger.info(f"Retrying {len(failed_to_retry)} previously failed tickers")
            progress["failed"] = []  # Clear failed list for retry
        logger.info(f"Resuming: {len(completed)} completed, {len(tickers)} remaining to process")

    # Apply sector filter if specified
    if sector_filter:
        logger.info(f"Filtering for sector: {sector_filter}")
        filtered = []
        for t in tickers:
            sector = get_sector_for_ticker(t)
            if sector_filter.lower() in sector.lower():
                filtered.append(t)
        tickers = filtered
        logger.info(f"Found {len(tickers)} tickers in {sector_filter} sector")

    # Apply max limit
    if max_tickers:
        tickers = tickers[:max_tickers]

    # Initialize progress if new run
    if not resume:
        progress = {
            "completed": [],
            "failed": [],
            "last_ticker": None,
            "started_at": datetime.now().isoformat(),
        }

    # Initialize agent
    agent = FundamentalAgent()

    # Process tickers
    results = []
    for i, ticker in enumerate(tickers):
        try:
            logger.info(f"[{i+1}/{len(tickers)}] Analyzing {ticker}...")

            # Check if we already have a recent valuation
            if ticker in existing_tickers:
                existing = existing_tickers[ticker]
                analyzed_at = existing.get("analyzed_at", "")
                try:
                    analysis_time = datetime.fromisoformat(analyzed_at)
                    age_hours = (datetime.utcnow() - analysis_time).total_seconds() / 3600
                    if age_hours < 24:
                        logger.info(f"  Skipping {ticker} - already analyzed {age_hours:.1f} hours ago")
                        results.append(existing)
                        progress["completed"].append(ticker)
                        continue
                except (ValueError, TypeError):
                    pass

            # Run analysis
            valuation = agent.analyze(ticker, persist=False)

            if valuation:
                # Add to results
                results.append(valuation)

                # Update valuations list
                if ticker in existing_tickers:
                    # Remove old valuation
                    valuations = [v for v in valuations if v.get("ticker") != ticker]
                valuations.append(valuation)

                # Save incrementally
                save_valuations(valuations)

                progress["completed"].append(ticker)
                progress["last_ticker"] = ticker

                # Log result
                synthesis = valuation.get("synthesis", {})
                logger.info(f"  {ticker}: {synthesis.get('verdict')} | "
                           f"Upside: {synthesis.get('upside_to_midpoint_pct', 0):.1f}% | "
                           f"Confidence: {synthesis.get('confidence', 0)}%")
            else:
                logger.warning(f"  {ticker}: Analysis failed")
                progress["failed"].append(ticker)

            # Save progress
            save_progress(progress)

            # Rate limit
            if i < len(tickers) - 1:
                logger.debug(f"  Waiting {API_DELAY_SECONDS}s before next ticker...")
                time.sleep(API_DELAY_SECONDS)

        except KeyboardInterrupt:
            logger.info("Interrupted by user. Progress saved.")
            save_progress(progress)
            break
        except Exception as e:
            logger.error(f"  {ticker}: Error - {e}")
            progress["failed"].append(ticker)
            save_progress(progress)

    # Final save
    progress["finished_at"] = datetime.now().isoformat()
    save_progress(progress)

    return results


def generate_summary(valuations: List[Dict] = None) -> str:
    """
    Generate a ranked summary of valuations.

    Args:
        valuations: List of valuations (loads from file if not provided)

    Returns:
        Formatted summary string
    """
    if valuations is None:
        valuations = load_valuations()

    if not valuations:
        return "No valuations found."

    # Parse and sort valuations
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
            "intrinsic_low": synthesis.get("intrinsic_value_low"),
            "intrinsic_high": synthesis.get("intrinsic_value_high"),
            "intrinsic_mid": synthesis.get("intrinsic_value_midpoint"),
            "upside": upside,
            "mos": synthesis.get("margin_of_safety_pct", 0),
            "confidence": synthesis.get("confidence", 0),
            "verdict": synthesis.get("verdict", "UNKNOWN"),
        })

    # Sort by upside
    undervalued = sorted([p for p in parsed if p["upside"] > 0],
                         key=lambda x: x["upside"], reverse=True)
    overvalued = sorted([p for p in parsed if p["upside"] < 0],
                        key=lambda x: x["upside"])

    # Build summary
    lines = []
    date_str = datetime.now().strftime("%Y-%m-%d")

    lines.append(f"\nS&P 500 FUNDAMENTAL SCREEN — {date_str}")
    lines.append("═" * 70)
    lines.append(f"\nTotal Companies Analyzed: {len(parsed)}")
    lines.append(f"Undervalued: {len([p for p in parsed if p['verdict'] == 'UNDERVALUED'])}")
    lines.append(f"Fairly Valued: {len([p for p in parsed if p['verdict'] == 'FAIRLY VALUED'])}")
    lines.append(f"Overvalued: {len([p for p in parsed if p['verdict'] == 'OVERVALUED'])}")

    # Top 20 undervalued
    lines.append("\n\nTOP 20 MOST UNDERVALUED")
    lines.append("─" * 70)
    lines.append(f"{'Rank':<5} {'Ticker':<8} {'Price':>10} {'Intrinsic':>12} {'Upside':>8} {'MoS':>6} {'Conf':>6}")
    lines.append("─" * 70)

    for i, p in enumerate(undervalued[:20], 1):
        price_str = f"${p['price']:.2f}" if p['price'] else "N/A"
        intrinsic_str = f"${p['intrinsic_mid']:.0f}" if p['intrinsic_mid'] else "N/A"
        lines.append(f"{i:<5} {p['ticker']:<8} {price_str:>10} {intrinsic_str:>12} "
                    f"{p['upside']:>+7.1f}% {p['mos']:>5.1f}% {p['confidence']:>5}%")

    # Top 20 overvalued
    lines.append("\n\nTOP 20 MOST OVERVALUED")
    lines.append("─" * 70)
    lines.append(f"{'Rank':<5} {'Ticker':<8} {'Price':>10} {'Intrinsic':>12} {'Downside':>10} {'Conf':>6}")
    lines.append("─" * 70)

    for i, p in enumerate(overvalued[:20], 1):
        price_str = f"${p['price']:.2f}" if p['price'] else "N/A"
        intrinsic_str = f"${p['intrinsic_mid']:.0f}" if p['intrinsic_mid'] else "N/A"
        lines.append(f"{i:<5} {p['ticker']:<8} {price_str:>10} {intrinsic_str:>12} "
                    f"{p['upside']:>+9.1f}% {p['confidence']:>5}%")

    # Sector summary
    sector_stats = defaultdict(lambda: {"count": 0, "total_upside": 0})
    for p in parsed:
        sector = p["sector"]
        sector_stats[sector]["count"] += 1
        sector_stats[sector]["total_upside"] += p["upside"]

    lines.append("\n\nSECTOR SUMMARY")
    lines.append("─" * 70)
    lines.append(f"{'Sector':<30} {'Count':>6} {'Avg Upside':>12}")
    lines.append("─" * 70)

    for sector, stats in sorted(sector_stats.items(),
                                key=lambda x: x[1]["total_upside"]/x[1]["count"] if x[1]["count"] > 0 else 0,
                                reverse=True):
        avg_upside = stats["total_upside"] / stats["count"] if stats["count"] > 0 else 0
        status = "undervalued" if avg_upside > 0 else "overvalued"
        lines.append(f"{sector:<30} {stats['count']:>6} {avg_upside:>+11.1f}%")

    # Market aggregate
    if parsed:
        median_upside = sorted([p["upside"] for p in parsed])[len(parsed)//2]
        avg_upside = sum(p["upside"] for p in parsed) / len(parsed)

        lines.append("\n\nMARKET AGGREGATE")
        lines.append("─" * 70)
        lines.append(f"S&P 500 Median Upside/Downside: {median_upside:+.1f}%")
        lines.append(f"S&P 500 Average Upside/Downside: {avg_upside:+.1f}%")

    # High confidence picks
    high_conf_under = [p for p in undervalued if p["confidence"] >= 75][:10]
    if high_conf_under:
        lines.append("\n\nHIGH CONVICTION BUYS (≥75% confidence)")
        lines.append("─" * 70)
        for p in high_conf_under:
            lines.append(f"  {p['ticker']}: {p['upside']:+.1f}% upside, {p['confidence']}% confidence")

    return "\n".join(lines)


def show_results():
    """Show the latest results summary."""
    progress = load_progress()
    valuations = load_valuations()

    print(f"\nLast run started: {progress.get('started_at', 'N/A')}")
    print(f"Last run finished: {progress.get('finished_at', 'Not finished')}")
    print(f"Completed: {len(progress.get('completed', []))}")
    print(f"Failed: {len(progress.get('failed', []))}")

    if valuations:
        print(generate_summary(valuations))
    else:
        print("\nNo valuations found. Run --full to start the screen.")


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    parser = argparse.ArgumentParser(description="ATLAS Fundamental Batch Runner")
    parser.add_argument("--full", action="store_true", help="Run full S&P 500 screen")
    parser.add_argument("--resume", action="store_true", help="Resume from previous run")
    parser.add_argument("--results", action="store_true", help="Show latest results")
    parser.add_argument("--sector", help="Filter by sector (e.g., Technology)")
    parser.add_argument("--max", type=int, help="Max tickers to process (for testing)")
    parser.add_argument("--tickers", help="Comma-separated list of specific tickers")
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("ATLAS Fundamental Batch Runner - S&P 500 Screen")
    print("=" * 70 + "\n")

    if args.results:
        show_results()

    elif args.full or args.resume:
        tickers = None
        if args.tickers:
            tickers = [t.strip() for t in args.tickers.split(",")]

        print("Starting batch analysis...")
        print(f"  Resume: {args.resume}")
        print(f"  Sector filter: {args.sector or 'None'}")
        print(f"  Max tickers: {args.max or 'All'}")
        print(f"  Rate limit: {API_DELAY_SECONDS}s between API calls")
        print()

        results = run_batch(
            tickers=tickers,
            resume=args.resume,
            max_tickers=args.max,
            sector_filter=args.sector,
        )

        print("\n" + "=" * 70)
        print("BATCH COMPLETE")
        print("=" * 70)
        print(f"Processed: {len(results)} tickers")

        # Show summary
        print(generate_summary(results))

    else:
        print("Usage:")
        print("  python -m agents.fundamental_batch --full        # Run full S&P 500 screen")
        print("  python -m agents.fundamental_batch --resume      # Resume from where it left off")
        print("  python -m agents.fundamental_batch --results     # Show latest results")
        print("  python -m agents.fundamental_batch --sector Technology  # Filter by sector")
        print("  python -m agents.fundamental_batch --max 10      # Process max 10 tickers (testing)")
        print("  python -m agents.fundamental_batch --tickers AAPL,MSFT,GOOGL  # Specific tickers")
