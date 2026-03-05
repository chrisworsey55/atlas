"""
Analyst Consensus Client for ATLAS
Tracks Wall Street consensus data: ratings, price targets, estimate revisions.

Data Sources:
1. yfinance: Analyst recommendations, price targets, estimates
2. Financial Modeling Prep (FMP): Detailed estimates, upgrades/downgrades
3. Finviz (scraping): Recommendation scores, targets

Knowing the consensus is how you bet against it.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from pathlib import Path
import requests
from bs4 import BeautifulSoup

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    yf = None

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import FMP_API_KEY
from config.universe import UNIVERSE

logger = logging.getLogger(__name__)


class ConsensusClient:
    """
    Client for fetching analyst consensus data.

    Provides:
    - Rating distribution (buy/hold/sell)
    - Price target range (low/mean/high)
    - Estimate revisions (direction over 30/60/90 days)
    - Recent rating changes (upgrades/downgrades)
    - Earnings history (beat/miss patterns)
    """

    FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"
    FINVIZ_URL = "https://finviz.com/quote.ashx?t={ticker}"

    def __init__(self, fmp_api_key: str = None):
        self.fmp_api_key = fmp_api_key or FMP_API_KEY
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        })
        self._cache = {}
        self._cache_expiry = {}
        self._cache_ttl = timedelta(minutes=30)

    def _get_cached(self, key: str) -> Optional[any]:
        """Get value from cache if not expired."""
        if key in self._cache:
            if datetime.now() < self._cache_expiry.get(key, datetime.min):
                return self._cache[key]
        return None

    def _set_cached(self, key: str, value: any) -> None:
        """Set value in cache with expiry."""
        self._cache[key] = value
        self._cache_expiry[key] = datetime.now() + self._cache_ttl

    def get_consensus_snapshot(self, ticker: str) -> Dict:
        """
        Get complete consensus snapshot for a ticker.

        Returns:
            Dict with:
            - analyst_count: Number of analysts covering
            - rating_distribution: buy/hold/sell counts
            - consensus_rating: STRONG_BUY/BUY/HOLD/SELL/STRONG_SELL
            - price_target: low/mean/median/high
            - current_price: Latest price
            - upside_to_target: Percentage upside to mean target
        """
        cache_key = f"consensus_{ticker}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        result = {
            "ticker": ticker,
            "company_name": UNIVERSE.get(ticker, {}).get("name", ticker),
            "sector": UNIVERSE.get(ticker, {}).get("sector", ""),
            "timestamp": datetime.utcnow().isoformat(),
        }

        try:
            stock = yf.Ticker(ticker)

            # Current price
            info = stock.info or {}
            current_price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
            result["current_price"] = current_price

            # Price targets
            targets = stock.analyst_price_targets
            if targets:
                if isinstance(targets, dict):
                    result["price_target"] = {
                        "low": targets.get("low"),
                        "mean": targets.get("mean") or targets.get("current"),
                        "median": targets.get("median"),
                        "high": targets.get("high"),
                    }
                else:
                    # Try as DataFrame
                    try:
                        result["price_target"] = {
                            "low": float(targets.loc["targetLowPrice"]) if "targetLowPrice" in targets.index else None,
                            "mean": float(targets.loc["targetMeanPrice"]) if "targetMeanPrice" in targets.index else None,
                            "median": float(targets.loc["targetMedianPrice"]) if "targetMedianPrice" in targets.index else None,
                            "high": float(targets.loc["targetHighPrice"]) if "targetHighPrice" in targets.index else None,
                        }
                    except:
                        pass

            # Calculate upside
            if result.get("price_target", {}).get("mean") and current_price:
                result["upside_to_target_pct"] = round(
                    (result["price_target"]["mean"] / current_price - 1) * 100, 1
                )

            # Recommendations summary
            rec_summary = stock.recommendations_summary
            if rec_summary is not None and not rec_summary.empty:
                try:
                    # Most recent period
                    period = rec_summary.iloc[0] if len(rec_summary) > 0 else {}

                    strong_buy = int(period.get("strongBuy", 0))
                    buy = int(period.get("buy", 0))
                    hold = int(period.get("hold", 0))
                    sell = int(period.get("sell", 0))
                    strong_sell = int(period.get("strongSell", 0))

                    total = strong_buy + buy + hold + sell + strong_sell

                    result["rating_distribution"] = {
                        "strong_buy": strong_buy,
                        "buy": buy,
                        "hold": hold,
                        "sell": sell,
                        "strong_sell": strong_sell,
                        "total": total,
                    }

                    # Derive consensus rating
                    buy_pct = (strong_buy + buy) / total * 100 if total > 0 else 0
                    sell_pct = (sell + strong_sell) / total * 100 if total > 0 else 0

                    if buy_pct >= 80:
                        result["consensus_rating"] = "STRONG_BUY"
                    elif buy_pct >= 60:
                        result["consensus_rating"] = "BUY"
                    elif sell_pct >= 60:
                        result["consensus_rating"] = "SELL"
                    elif sell_pct >= 80:
                        result["consensus_rating"] = "STRONG_SELL"
                    else:
                        result["consensus_rating"] = "HOLD"

                    result["buy_pct"] = round(buy_pct, 1)
                    result["analyst_count"] = total

                except Exception as e:
                    logger.debug(f"Error parsing recommendations for {ticker}: {e}")

            # Analyst count from recommendations
            recs = stock.recommendations
            if recs is not None and not recs.empty:
                # Count unique firms in last 90 days
                recent = recs.tail(100)
                if "Firm" in recent.columns:
                    result["analyst_count"] = recent["Firm"].nunique()

        except Exception as e:
            logger.error(f"Error getting yfinance data for {ticker}: {e}")

        # Supplement with FMP if available
        if self.fmp_api_key:
            try:
                fmp_data = self._get_fmp_targets(ticker)
                if fmp_data:
                    result.update(fmp_data)
            except:
                pass

        self._set_cached(cache_key, result)
        return result

    def get_estimate_revisions(self, ticker: str) -> Dict:
        """
        Get EPS/revenue estimate revisions over 30/60/90 days.

        Returns:
            Dict with estimate revision trends
        """
        cache_key = f"revisions_{ticker}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        result = {
            "ticker": ticker,
            "revision_trend": "STABLE",  # IMPROVING, STABLE, DETERIORATING
        }

        try:
            stock = yf.Ticker(ticker)

            # EPS estimates
            eps_est = stock.earnings_estimate
            if eps_est is not None and not eps_est.empty:
                try:
                    # Current quarter estimates
                    current_q = eps_est.iloc[0] if len(eps_est) > 0 else {}

                    result["eps_current_q"] = {
                        "avg": current_q.get("avg"),
                        "low": current_q.get("low"),
                        "high": current_q.get("high"),
                        "num_analysts": current_q.get("numberOfAnalysts"),
                    }

                    # Growth rates
                    result["eps_growth_current_y"] = current_q.get("growth")

                except Exception as e:
                    logger.debug(f"Error parsing EPS estimates: {e}")

            # Revenue estimates
            rev_est = stock.revenue_estimate
            if rev_est is not None and not rev_est.empty:
                try:
                    current_q = rev_est.iloc[0] if len(rev_est) > 0 else {}

                    result["revenue_current_q"] = {
                        "avg": current_q.get("avg"),
                        "low": current_q.get("low"),
                        "high": current_q.get("high"),
                        "num_analysts": current_q.get("numberOfAnalysts"),
                    }

                except Exception as e:
                    logger.debug(f"Error parsing revenue estimates: {e}")

            # Get revision direction from recommendations
            recs = stock.recommendations
            if recs is not None and not recs.empty:
                recent_30d = recs.tail(30)

                upgrades = 0
                downgrades = 0

                for _, row in recent_30d.iterrows():
                    action = str(row.get("Action", "")).lower()
                    if "up" in action or "reiterate" in action.lower() and "buy" in str(row.get("To Grade", "")).lower():
                        upgrades += 1
                    elif "down" in action:
                        downgrades += 1

                result["upgrades_30d"] = upgrades
                result["downgrades_30d"] = downgrades

                if upgrades > downgrades * 1.5:
                    result["revision_trend"] = "IMPROVING"
                elif downgrades > upgrades * 1.5:
                    result["revision_trend"] = "DETERIORATING"

        except Exception as e:
            logger.error(f"Error getting revisions for {ticker}: {e}")

        self._set_cached(cache_key, result)
        return result

    def get_recent_rating_changes(self, ticker: str, days: int = 30) -> List[Dict]:
        """
        Get recent analyst rating changes.

        Returns:
            List of rating change dicts
        """
        changes = []

        try:
            stock = yf.Ticker(ticker)
            recs = stock.recommendations

            if recs is None or recs.empty:
                return changes

            # Filter to recent
            cutoff = datetime.now() - timedelta(days=days)

            for idx, row in recs.tail(50).iterrows():
                try:
                    # Parse date from index
                    if hasattr(idx, "date"):
                        rec_date = idx
                    else:
                        rec_date = datetime.now()  # Fallback

                    changes.append({
                        "date": rec_date.strftime("%Y-%m-%d") if hasattr(rec_date, "strftime") else str(rec_date),
                        "firm": row.get("Firm", "Unknown"),
                        "to_grade": row.get("To Grade"),
                        "from_grade": row.get("From Grade"),
                        "action": row.get("Action"),
                    })
                except:
                    continue

            # Most recent first
            changes.reverse()
            return changes[:20]

        except Exception as e:
            logger.error(f"Error getting rating changes for {ticker}: {e}")
            return []

    def get_earnings_history(self, ticker: str, quarters: int = 8) -> Dict:
        """
        Get earnings beat/miss history.

        Returns:
            Dict with beat rate and history
        """
        try:
            stock = yf.Ticker(ticker)
            earnings_hist = stock.earnings_history

            if earnings_hist is None or earnings_hist.empty:
                return {"ticker": ticker, "history": [], "beat_rate": None}

            history = []
            beats = 0
            misses = 0

            for idx, row in earnings_hist.tail(quarters).iterrows():
                eps_actual = row.get("epsActual")
                eps_estimate = row.get("epsEstimate")

                beat = None
                surprise_pct = None

                if eps_actual is not None and eps_estimate is not None:
                    beat = eps_actual > eps_estimate
                    if beat:
                        beats += 1
                    else:
                        misses += 1

                    if eps_estimate != 0:
                        surprise_pct = round((eps_actual - eps_estimate) / abs(eps_estimate) * 100, 1)

                history.append({
                    "date": idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx),
                    "eps_actual": eps_actual,
                    "eps_estimate": eps_estimate,
                    "beat": beat,
                    "surprise_pct": surprise_pct,
                })

            total = beats + misses
            beat_rate = round(beats / total * 100, 1) if total > 0 else None

            # Most recent first
            history.reverse()

            return {
                "ticker": ticker,
                "quarters_analyzed": total,
                "beats": beats,
                "misses": misses,
                "beat_rate": beat_rate,
                "average_surprise_pct": round(
                    sum(h.get("surprise_pct", 0) or 0 for h in history) / len(history), 1
                ) if history else None,
                "pattern": "CONSISTENT_BEATER" if beat_rate and beat_rate >= 75 else "MIXED" if beat_rate and beat_rate >= 50 else "UNDERPERFORMER",
                "history": history,
            }

        except Exception as e:
            logger.error(f"Error getting earnings history for {ticker}: {e}")
            return {"ticker": ticker, "history": [], "beat_rate": None}

    def _get_fmp_targets(self, ticker: str) -> Optional[Dict]:
        """Get data from FMP API."""
        if not self.fmp_api_key:
            return None

        try:
            # Price targets
            url = f"{self.FMP_BASE_URL}/price-target/{ticker}"
            params = {"apikey": self.fmp_api_key}

            resp = self.session.get(url, params=params, timeout=10)
            if resp.status_code != 200:
                return None

            data = resp.json()
            if not data:
                return None

            # Get latest targets
            recent = data[:10]

            result = {
                "fmp_targets": recent,
                "recent_target_changes": len(recent),
            }

            # Get analyst estimates
            est_url = f"{self.FMP_BASE_URL}/analyst-estimates/{ticker}"
            est_resp = self.session.get(est_url, params=params, timeout=10)
            if est_resp.status_code == 200:
                est_data = est_resp.json()
                if est_data:
                    latest = est_data[0]
                    result["fmp_estimates"] = {
                        "estimated_revenue_avg": latest.get("estimatedRevenueAvg"),
                        "estimated_eps_avg": latest.get("estimatedEpsAvg"),
                        "number_analysts": latest.get("numberAnalystsEstimatedRevenue"),
                    }

            return result

        except Exception as e:
            logger.debug(f"FMP error for {ticker}: {e}")
            return None

    def get_portfolio_consensus(self, tickers: List[str]) -> List[Dict]:
        """
        Get consensus data for multiple tickers.

        Args:
            tickers: List of tickers

        Returns:
            List of consensus snapshots
        """
        results = []
        for ticker in tickers:
            try:
                snapshot = self.get_consensus_snapshot(ticker)
                if snapshot:
                    results.append(snapshot)
            except Exception as e:
                logger.error(f"Error getting consensus for {ticker}: {e}")
                continue
        return results

    def find_contrarian_signals(self, tickers: List[str] = None) -> List[Dict]:
        """
        Find stocks where analysts might be wrong.

        Looks for:
        - Extreme consensus (>90% buy or sell)
        - Large upside/downside to targets
        - Recent revision momentum

        Returns:
            List of contrarian opportunities
        """
        if tickers is None:
            tickers = list(UNIVERSE.keys())

        contrarian = []

        for ticker in tickers:
            try:
                snapshot = self.get_consensus_snapshot(ticker)

                if not snapshot:
                    continue

                buy_pct = snapshot.get("buy_pct", 0)
                upside = snapshot.get("upside_to_target_pct", 0)

                # Flag extreme consensus (crowded trades)
                if buy_pct >= 90:
                    contrarian.append({
                        "ticker": ticker,
                        "signal": "CROWDED_LONG",
                        "buy_pct": buy_pct,
                        "upside_pct": upside,
                        "risk": "Crowded long - any disappointment causes violent selloff",
                    })
                elif buy_pct <= 20:
                    contrarian.append({
                        "ticker": ticker,
                        "signal": "CROWDED_SHORT",
                        "buy_pct": buy_pct,
                        "upside_pct": upside,
                        "opportunity": "Unloved stock - any positive surprise could cause squeeze",
                    })

                # Flag large divergences
                if upside and abs(upside) > 30:
                    contrarian.append({
                        "ticker": ticker,
                        "signal": "LARGE_GAP" if upside > 0 else "LARGE_DOWNSIDE",
                        "upside_pct": upside,
                        "note": f"Price {abs(upside):.1f}% {'below' if upside > 0 else 'above'} analyst target",
                    })

            except Exception as e:
                logger.debug(f"Error checking {ticker}: {e}")
                continue

        return contrarian


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    print("\n" + "="*60)
    print("ATLAS Consensus Client")
    print("="*60 + "\n")

    client = ConsensusClient()

    # Test NVDA
    print("--- NVDA Consensus Snapshot ---")
    snapshot = client.get_consensus_snapshot("NVDA")
    print(f"Rating: {snapshot.get('consensus_rating')}")
    print(f"Analyst Count: {snapshot.get('analyst_count')}")
    print(f"Buy %: {snapshot.get('buy_pct')}%")
    print(f"Price Target (Mean): ${snapshot.get('price_target', {}).get('mean')}")
    print(f"Upside to Target: {snapshot.get('upside_to_target_pct')}%")

    print("\n--- NVDA Estimate Revisions ---")
    revisions = client.get_estimate_revisions("NVDA")
    print(f"Trend: {revisions.get('revision_trend')}")
    print(f"Upgrades (30d): {revisions.get('upgrades_30d', 'N/A')}")
    print(f"Downgrades (30d): {revisions.get('downgrades_30d', 'N/A')}")

    print("\n--- NVDA Earnings History ---")
    history = client.get_earnings_history("NVDA")
    print(f"Beat Rate: {history.get('beat_rate')}%")
    print(f"Pattern: {history.get('pattern')}")
    print(f"Avg Surprise: {history.get('average_surprise_pct')}%")

    print("\n--- Recent Rating Changes ---")
    changes = client.get_recent_rating_changes("NVDA")
    for c in changes[:5]:
        print(f"  {c.get('date')} | {c.get('firm', 'N/A')[:20]} | {c.get('action')}: {c.get('to_grade')}")
