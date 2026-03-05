"""
Options Flow & Unusual Activity Client for ATLAS
Tracks options chains, unusual activity, put/call ratios, and max pain.

Unusual options activity often signals institutional positioning 24-48 hours
before it shows up in price action. This client calculates all metrics
locally from yfinance options chain data.

Key Signals:
- Volume > 3x Open Interest = Unusual activity (potential institutional bet)
- Large block trades
- Put/call ratio shifts (extreme readings signal sentiment)
- Max pain (where options market makers want stock to settle)
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd
import numpy as np

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    yf = None

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.universe import UNIVERSE

logger = logging.getLogger(__name__)


class OptionsClient:
    """
    Client for options flow analysis and unusual activity detection.
    """

    # Thresholds for unusual activity detection
    VOLUME_OI_THRESHOLD = 3.0  # Volume > 3x OI is unusual
    BLOCK_TRADE_THRESHOLD = 500  # Contracts for a block trade
    HIGH_IV_PERCENTILE = 80  # High IV threshold
    EXTREME_PCR_LOW = 0.5  # Extremely bullish P/C ratio
    EXTREME_PCR_HIGH = 1.5  # Extremely bearish P/C ratio

    def __init__(self):
        """Initialize options client."""
        self._cache = {}
        self._cache_expiry = {}
        self._cache_ttl = timedelta(minutes=5)  # Short TTL for options data

        if not YFINANCE_AVAILABLE:
            logger.warning("yfinance not available - options data will be limited")

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

    def get_options_chain(self, ticker: str) -> dict:
        """
        Get full options chain for a ticker.

        Args:
            ticker: Stock ticker symbol

        Returns:
            Dict with keys: calls, puts, expirations, current_price, expiry_date
        """
        if not YFINANCE_AVAILABLE:
            return {"error": "yfinance not available"}

        cache_key = f"chain_{ticker}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            stock = yf.Ticker(ticker)

            # Get current price
            hist = stock.history(period="1d")
            current_price = float(hist["Close"].iloc[-1]) if not hist.empty else None

            # Get available expirations
            expirations = stock.options
            if not expirations:
                return {
                    "ticker": ticker,
                    "current_price": current_price,
                    "error": "No options available"
                }

            # Get nearest expiration
            nearest_expiry = expirations[0]
            chain = stock.option_chain(nearest_expiry)

            # Process calls
            calls_df = chain.calls.copy()
            calls_df["type"] = "call"
            calls_df["moneyness"] = (calls_df["strike"] - current_price) / current_price if current_price else 0

            # Process puts
            puts_df = chain.puts.copy()
            puts_df["type"] = "put"
            puts_df["moneyness"] = (puts_df["strike"] - current_price) / current_price if current_price else 0

            result = {
                "ticker": ticker,
                "current_price": current_price,
                "expiry_date": nearest_expiry,
                "expirations": list(expirations),
                "calls": calls_df.to_dict("records"),
                "puts": puts_df.to_dict("records"),
                "total_call_volume": int(calls_df["volume"].sum()) if "volume" in calls_df.columns else 0,
                "total_put_volume": int(puts_df["volume"].sum()) if "volume" in puts_df.columns else 0,
                "total_call_oi": int(calls_df["openInterest"].sum()) if "openInterest" in calls_df.columns else 0,
                "total_put_oi": int(puts_df["openInterest"].sum()) if "openInterest" in puts_df.columns else 0,
            }

            self._set_cached(cache_key, result)
            return result

        except Exception as e:
            logger.error(f"Error getting options chain for {ticker}: {e}")
            return {"ticker": ticker, "error": str(e)}

    def get_unusual_activity(self, ticker: str) -> list:
        """
        Flag options with unusual activity signals.

        Unusual activity indicators:
        - Volume > 3x Open Interest
        - Large block trades (>500 contracts)
        - Significant put/call ratio shifts

        Args:
            ticker: Stock ticker symbol

        Returns:
            List of unusual options activity dicts
        """
        chain = self.get_options_chain(ticker)
        if "error" in chain:
            return []

        unusual = []
        current_price = chain.get("current_price", 0)

        # Process calls
        for option in chain.get("calls", []):
            signal = self._check_unusual_signal(option, current_price, "call")
            if signal:
                unusual.append(signal)

        # Process puts
        for option in chain.get("puts", []):
            signal = self._check_unusual_signal(option, current_price, "put")
            if signal:
                unusual.append(signal)

        # Sort by signal strength
        unusual.sort(key=lambda x: x.get("signal_strength", 0), reverse=True)

        logger.info(f"{ticker}: Found {len(unusual)} unusual options activities")
        return unusual

    def _check_unusual_signal(self, option: dict, current_price: float, option_type: str) -> Optional[dict]:
        """Check if an option has unusual activity signals."""
        volume = option.get("volume", 0) or 0
        oi = option.get("openInterest", 0) or 0
        strike = option.get("strike", 0)
        bid = option.get("bid", 0) or 0
        ask = option.get("ask", 0) or 0
        iv = option.get("impliedVolatility", 0) or 0

        signals = []
        signal_strength = 0

        # Volume > 3x OI
        if oi > 0 and volume > oi * self.VOLUME_OI_THRESHOLD:
            vol_oi_ratio = volume / oi
            signals.append(f"Vol/OI: {vol_oi_ratio:.1f}x")
            signal_strength += min(vol_oi_ratio / 3, 3)  # Cap contribution

        # Block trade size
        if volume >= self.BLOCK_TRADE_THRESHOLD:
            signals.append(f"Block: {volume:,} contracts")
            signal_strength += volume / 1000  # Scale by size

        # High implied volatility (if we can calculate percentile)
        if iv > 0.5:  # 50%+ IV is generally high
            signals.append(f"High IV: {iv:.1%}")
            signal_strength += 1

        if not signals:
            return None

        # Calculate notional value
        mid_price = (bid + ask) / 2 if bid and ask else option.get("lastPrice", 0)
        notional = volume * mid_price * 100  # 100 shares per contract

        # Determine if bullish or bearish
        if current_price:
            if option_type == "call":
                if strike > current_price * 1.05:  # OTM call
                    bias = "BULLISH"
                elif strike < current_price * 0.95:  # ITM call
                    bias = "BULLISH_HEDGE"
                else:
                    bias = "BULLISH"
            else:  # put
                if strike < current_price * 0.95:  # OTM put
                    bias = "BEARISH"
                elif strike > current_price * 1.05:  # ITM put
                    bias = "BEARISH_HEDGE"
                else:
                    bias = "BEARISH"
        else:
            bias = "UNKNOWN"

        return {
            "strike": strike,
            "type": option_type.upper(),
            "expiry": option.get("contractSymbol", "")[-6:] if option.get("contractSymbol") else "",
            "volume": volume,
            "open_interest": oi,
            "vol_oi_ratio": volume / oi if oi > 0 else None,
            "implied_volatility": iv,
            "bid": bid,
            "ask": ask,
            "mid_price": mid_price,
            "notional_value": notional,
            "signals": signals,
            "signal_strength": signal_strength,
            "bias": bias,
        }

    def get_put_call_ratio(self, ticker: str) -> dict:
        """
        Calculate equity put/call ratio.

        Extreme readings signal sentiment:
        - < 0.5: Extremely bullish (contrarian bearish)
        - 0.5-0.7: Bullish
        - 0.7-1.0: Neutral
        - 1.0-1.5: Bearish
        - > 1.5: Extremely bearish (contrarian bullish)

        Args:
            ticker: Stock ticker symbol

        Returns:
            Dict with put/call ratios and interpretation
        """
        chain = self.get_options_chain(ticker)
        if "error" in chain:
            return {"ticker": ticker, "error": chain.get("error")}

        total_call_volume = chain.get("total_call_volume", 0)
        total_put_volume = chain.get("total_put_volume", 0)
        total_call_oi = chain.get("total_call_oi", 0)
        total_put_oi = chain.get("total_put_oi", 0)

        # Calculate ratios
        pcr_volume = total_put_volume / total_call_volume if total_call_volume > 0 else None
        pcr_oi = total_put_oi / total_call_oi if total_call_oi > 0 else None

        # Interpret
        if pcr_volume is not None:
            if pcr_volume < self.EXTREME_PCR_LOW:
                interpretation = "EXTREMELY_BULLISH"
                contrarian = "BEARISH_SIGNAL"
            elif pcr_volume < 0.7:
                interpretation = "BULLISH"
                contrarian = "NEUTRAL"
            elif pcr_volume < 1.0:
                interpretation = "NEUTRAL"
                contrarian = "NEUTRAL"
            elif pcr_volume < self.EXTREME_PCR_HIGH:
                interpretation = "BEARISH"
                contrarian = "NEUTRAL"
            else:
                interpretation = "EXTREMELY_BEARISH"
                contrarian = "BULLISH_SIGNAL"
        else:
            interpretation = "UNKNOWN"
            contrarian = "UNKNOWN"

        return {
            "ticker": ticker,
            "expiry_date": chain.get("expiry_date"),
            "put_call_ratio_volume": pcr_volume,
            "put_call_ratio_oi": pcr_oi,
            "total_call_volume": total_call_volume,
            "total_put_volume": total_put_volume,
            "total_call_oi": total_call_oi,
            "total_put_oi": total_put_oi,
            "interpretation": interpretation,
            "contrarian_signal": contrarian,
        }

    def get_max_pain(self, ticker: str) -> dict:
        """
        Calculate max pain price for nearest expiry.

        Max pain is the strike price where options market makers would have
        to pay out the least amount to options holders. Stocks often gravitate
        toward max pain near expiration.

        Args:
            ticker: Stock ticker symbol

        Returns:
            Dict with max pain strike and analysis
        """
        chain = self.get_options_chain(ticker)
        if "error" in chain:
            return {"ticker": ticker, "error": chain.get("error")}

        current_price = chain.get("current_price", 0)
        calls = chain.get("calls", [])
        puts = chain.get("puts", [])

        if not calls or not puts:
            return {"ticker": ticker, "error": "Insufficient options data"}

        # Get all unique strikes
        call_strikes = {opt.get("strike") for opt in calls if opt.get("strike")}
        put_strikes = {opt.get("strike") for opt in puts if opt.get("strike")}
        all_strikes = sorted(call_strikes | put_strikes)

        if not all_strikes:
            return {"ticker": ticker, "error": "No strikes found"}

        # Build OI lookup
        call_oi = {opt["strike"]: opt.get("openInterest", 0) or 0 for opt in calls if opt.get("strike")}
        put_oi = {opt["strike"]: opt.get("openInterest", 0) or 0 for opt in puts if opt.get("strike")}

        # Calculate total pain at each strike
        pain_by_strike = {}

        for test_strike in all_strikes:
            total_pain = 0

            # Calculate call pain (calls ITM if price > strike)
            for strike, oi in call_oi.items():
                if test_strike > strike:  # Call is ITM
                    intrinsic = test_strike - strike
                    total_pain += intrinsic * oi * 100  # 100 shares per contract

            # Calculate put pain (puts ITM if price < strike)
            for strike, oi in put_oi.items():
                if test_strike < strike:  # Put is ITM
                    intrinsic = strike - test_strike
                    total_pain += intrinsic * oi * 100

            pain_by_strike[test_strike] = total_pain

        # Find max pain (minimum total payout)
        max_pain_strike = min(pain_by_strike, key=pain_by_strike.get)
        max_pain_value = pain_by_strike[max_pain_strike]

        # Calculate distance from current price
        if current_price:
            distance_pct = ((max_pain_strike - current_price) / current_price) * 100
            direction = "above" if max_pain_strike > current_price else "below"
        else:
            distance_pct = None
            direction = None

        # Find key pain levels (local minima)
        pain_levels = []
        sorted_strikes = sorted(pain_by_strike.keys())
        for i, strike in enumerate(sorted_strikes):
            if i == 0 or i == len(sorted_strikes) - 1:
                continue
            prev_pain = pain_by_strike[sorted_strikes[i-1]]
            curr_pain = pain_by_strike[strike]
            next_pain = pain_by_strike[sorted_strikes[i+1]]
            if curr_pain < prev_pain and curr_pain < next_pain:
                pain_levels.append({
                    "strike": strike,
                    "total_pain": curr_pain,
                })

        return {
            "ticker": ticker,
            "current_price": current_price,
            "expiry_date": chain.get("expiry_date"),
            "max_pain_strike": max_pain_strike,
            "max_pain_total": max_pain_value,
            "distance_pct": distance_pct,
            "direction": direction,
            "key_pain_levels": sorted(pain_levels, key=lambda x: x["total_pain"])[:5],
        }

    def get_options_summary(self, ticker: str) -> dict:
        """
        Get comprehensive options analysis for a ticker.

        Args:
            ticker: Stock ticker symbol

        Returns:
            Dict with all options metrics combined
        """
        summary = {
            "ticker": ticker,
            "timestamp": datetime.now().isoformat(),
        }

        # Get chain basics
        chain = self.get_options_chain(ticker)
        if "error" not in chain:
            summary["current_price"] = chain.get("current_price")
            summary["nearest_expiry"] = chain.get("expiry_date")
            summary["total_expirations"] = len(chain.get("expirations", []))

        # Get put/call ratio
        pcr = self.get_put_call_ratio(ticker)
        if "error" not in pcr:
            summary["put_call_ratio_volume"] = pcr.get("put_call_ratio_volume")
            summary["put_call_ratio_oi"] = pcr.get("put_call_ratio_oi")
            summary["pcr_interpretation"] = pcr.get("interpretation")
            summary["contrarian_signal"] = pcr.get("contrarian_signal")

        # Get max pain
        max_pain = self.get_max_pain(ticker)
        if "error" not in max_pain:
            summary["max_pain_strike"] = max_pain.get("max_pain_strike")
            summary["max_pain_distance_pct"] = max_pain.get("distance_pct")
            summary["max_pain_direction"] = max_pain.get("direction")

        # Get unusual activity
        unusual = self.get_unusual_activity(ticker)
        summary["unusual_activity_count"] = len(unusual)
        summary["unusual_activity"] = unusual[:5]  # Top 5

        # Determine overall bias from signals
        bullish_signals = 0
        bearish_signals = 0

        for activity in unusual:
            if "BULLISH" in activity.get("bias", ""):
                bullish_signals += activity.get("signal_strength", 1)
            elif "BEARISH" in activity.get("bias", ""):
                bearish_signals += activity.get("signal_strength", 1)

        if bullish_signals > bearish_signals * 1.5:
            summary["options_bias"] = "BULLISH"
        elif bearish_signals > bullish_signals * 1.5:
            summary["options_bias"] = "BEARISH"
        else:
            summary["options_bias"] = "NEUTRAL"

        summary["bullish_signal_strength"] = bullish_signals
        summary["bearish_signal_strength"] = bearish_signals

        return summary

    def scan_universe_unusual_activity(self) -> list:
        """
        Scan all universe tickers for unusual options activity.

        Returns:
            List of tickers with unusual activity, sorted by signal strength
        """
        results = []

        for ticker in UNIVERSE.keys():
            try:
                unusual = self.get_unusual_activity(ticker)
                if unusual:
                    total_strength = sum(u.get("signal_strength", 0) for u in unusual)
                    results.append({
                        "ticker": ticker,
                        "company": UNIVERSE[ticker].get("name", ticker),
                        "sector": UNIVERSE[ticker].get("sector", ""),
                        "unusual_count": len(unusual),
                        "total_signal_strength": total_strength,
                        "top_signals": unusual[:3],
                    })
            except Exception as e:
                logger.debug(f"Error scanning options for {ticker}: {e}")
                continue

        # Sort by signal strength
        results.sort(key=lambda x: x["total_signal_strength"], reverse=True)

        logger.info(f"Found {len(results)} tickers with unusual options activity")
        return results


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    print("\n" + "="*60)
    print("ATLAS Options Flow Client")
    print("="*60 + "\n")

    client = OptionsClient()

    # Test options chain
    print("--- NVDA Options Chain ---")
    chain = client.get_options_chain("NVDA")
    print(f"  Current Price: ${chain.get('current_price', 'N/A'):,.2f}")
    print(f"  Nearest Expiry: {chain.get('expiry_date', 'N/A')}")
    print(f"  Total Expirations: {len(chain.get('expirations', []))}")
    print(f"  Call Volume: {chain.get('total_call_volume', 0):,}")
    print(f"  Put Volume: {chain.get('total_put_volume', 0):,}")

    # Test put/call ratio
    print("\n--- NVDA Put/Call Ratio ---")
    pcr = client.get_put_call_ratio("NVDA")
    print(f"  P/C Ratio (Volume): {pcr.get('put_call_ratio_volume', 'N/A'):.2f}" if pcr.get('put_call_ratio_volume') else "  P/C Ratio: N/A")
    print(f"  P/C Ratio (OI): {pcr.get('put_call_ratio_oi', 'N/A'):.2f}" if pcr.get('put_call_ratio_oi') else "  P/C Ratio OI: N/A")
    print(f"  Interpretation: {pcr.get('interpretation', 'N/A')}")
    print(f"  Contrarian Signal: {pcr.get('contrarian_signal', 'N/A')}")

    # Test max pain
    print("\n--- NVDA Max Pain ---")
    mp = client.get_max_pain("NVDA")
    print(f"  Max Pain Strike: ${mp.get('max_pain_strike', 'N/A')}")
    print(f"  Current Price: ${mp.get('current_price', 'N/A'):,.2f}" if mp.get('current_price') else "  Current: N/A")
    print(f"  Distance: {mp.get('distance_pct', 'N/A'):.1f}% {mp.get('direction', '')}" if mp.get('distance_pct') else "  Distance: N/A")

    # Test unusual activity
    print("\n--- NVDA Unusual Activity ---")
    unusual = client.get_unusual_activity("NVDA")
    for u in unusual[:5]:
        print(f"  {u['type']} ${u['strike']} | Vol: {u['volume']:,} | OI: {u['open_interest']:,} | {u['bias']}")
        print(f"    Signals: {', '.join(u['signals'])}")

    # Test summary
    print("\n--- NVDA Options Summary ---")
    summary = client.get_options_summary("NVDA")
    print(f"  Options Bias: {summary.get('options_bias', 'N/A')}")
    print(f"  Bullish Strength: {summary.get('bullish_signal_strength', 0):.1f}")
    print(f"  Bearish Strength: {summary.get('bearish_signal_strength', 0):.1f}")
    print(f"  Unusual Activity Count: {summary.get('unusual_activity_count', 0)}")
