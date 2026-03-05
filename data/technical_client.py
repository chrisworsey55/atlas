"""
Technical Signals Client for ATLAS
Calculates basic technical indicators that every market participant watches.

Not to trade on directly, but to understand what technicians and algos see.

Indicators calculated:
- Price vs 50-day and 200-day moving averages
- RSI (14-day) — overbought > 70, oversold < 30
- MACD signal line crossovers
- Volume vs 20-day average
- 52-week high/low proximity
- Support and resistance levels
- Bollinger Band position

All calculated locally from yfinance price data using pandas/numpy.
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

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.universe import UNIVERSE

logger = logging.getLogger(__name__)


class TechnicalClient:
    """
    Client for calculating technical analysis indicators.
    """

    # RSI thresholds
    RSI_OVERBOUGHT = 70
    RSI_OVERSOLD = 30

    # Volume thresholds
    VOLUME_SURGE_MULTIPLIER = 2.0  # Volume > 2x average = institutional activity

    def __init__(self):
        """Initialize technical client."""
        self._cache = {}
        self._cache_expiry = {}
        self._cache_ttl = timedelta(minutes=5)

        if not YFINANCE_AVAILABLE:
            logger.warning("yfinance not available - technical analysis will be limited")

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

    def _get_price_data(self, ticker: str, period: str = "1y") -> Optional[pd.DataFrame]:
        """Get price history from yfinance."""
        if not YFINANCE_AVAILABLE:
            return None

        cache_key = f"price_data_{ticker}_{period}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            stock = yf.Ticker(ticker)
            df = stock.history(period=period)
            if df is not None and not df.empty:
                self._set_cached(cache_key, df)
                return df
            return None
        except Exception as e:
            logger.error(f"Error fetching price data for {ticker}: {e}")
            return None

    def _calculate_sma(self, prices: pd.Series, window: int) -> pd.Series:
        """Calculate Simple Moving Average."""
        return prices.rolling(window=window).mean()

    def _calculate_ema(self, prices: pd.Series, window: int) -> pd.Series:
        """Calculate Exponential Moving Average."""
        return prices.ewm(span=window, adjust=False).mean()

    def _calculate_rsi(self, prices: pd.Series, window: int = 14) -> float:
        """Calculate Relative Strength Index."""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()

        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1]) if not rsi.empty else None

    def _calculate_macd(self, prices: pd.Series) -> dict:
        """Calculate MACD (12, 26, 9)."""
        ema12 = self._calculate_ema(prices, 12)
        ema26 = self._calculate_ema(prices, 26)
        macd_line = ema12 - ema26
        signal_line = self._calculate_ema(macd_line, 9)
        histogram = macd_line - signal_line

        return {
            "macd_line": float(macd_line.iloc[-1]) if not macd_line.empty else None,
            "signal_line": float(signal_line.iloc[-1]) if not signal_line.empty else None,
            "histogram": float(histogram.iloc[-1]) if not histogram.empty else None,
            "crossover": "BULLISH" if histogram.iloc[-1] > 0 and histogram.iloc[-2] <= 0 else
                        "BEARISH" if histogram.iloc[-1] < 0 and histogram.iloc[-2] >= 0 else
                        "NONE" if len(histogram) >= 2 else None,
        }

    def _calculate_bollinger_bands(self, prices: pd.Series, window: int = 20, std_dev: float = 2.0) -> dict:
        """Calculate Bollinger Bands."""
        sma = self._calculate_sma(prices, window)
        rolling_std = prices.rolling(window=window).std()

        upper = sma + (rolling_std * std_dev)
        lower = sma - (rolling_std * std_dev)

        current_price = prices.iloc[-1]
        band_width = (upper.iloc[-1] - lower.iloc[-1]) / sma.iloc[-1] * 100

        # Position within bands (0 = lower band, 1 = upper band)
        position = (current_price - lower.iloc[-1]) / (upper.iloc[-1] - lower.iloc[-1])

        return {
            "upper_band": float(upper.iloc[-1]),
            "middle_band": float(sma.iloc[-1]),
            "lower_band": float(lower.iloc[-1]),
            "band_width_pct": float(band_width),
            "position_in_bands": float(position),
            "signal": "OVERBOUGHT" if position > 0.95 else
                     "OVERSOLD" if position < 0.05 else
                     "NEAR_UPPER" if position > 0.8 else
                     "NEAR_LOWER" if position < 0.2 else
                     "NEUTRAL",
        }

    def _find_support_resistance(self, df: pd.DataFrame, lookback: int = 60) -> dict:
        """Find support and resistance levels from recent swing highs/lows."""
        if len(df) < lookback:
            lookback = len(df)

        recent = df.tail(lookback)
        highs = recent["High"]
        lows = recent["Low"]
        current = float(df["Close"].iloc[-1])

        # Find local maxima and minima using a simple approach
        resistance_levels = []
        support_levels = []

        window = 5  # Look at 5-day windows for pivots

        for i in range(window, len(recent) - window):
            # Check for local maximum
            if highs.iloc[i] == highs.iloc[i-window:i+window+1].max():
                resistance_levels.append(float(highs.iloc[i]))

            # Check for local minimum
            if lows.iloc[i] == lows.iloc[i-window:i+window+1].min():
                support_levels.append(float(lows.iloc[i]))

        # Get nearest levels to current price
        resistances_above = [r for r in resistance_levels if r > current]
        supports_below = [s for s in support_levels if s < current]

        nearest_resistance = min(resistances_above) if resistances_above else None
        nearest_support = max(supports_below) if supports_below else None

        # Also get 52-week high/low as major levels
        high_52w = float(highs.max())
        low_52w = float(lows.min())

        return {
            "nearest_resistance": nearest_resistance,
            "nearest_support": nearest_support,
            "resistance_levels": sorted(set(resistances_above))[:3] if resistances_above else [],
            "support_levels": sorted(set(supports_below), reverse=True)[:3] if supports_below else [],
            "high_52w": high_52w,
            "low_52w": low_52w,
            "pct_from_52w_high": ((current - high_52w) / high_52w) * 100,
            "pct_from_52w_low": ((current - low_52w) / low_52w) * 100,
        }

    def get_technical_summary(self, ticker: str) -> dict:
        """
        Get comprehensive technical analysis for a ticker.

        Args:
            ticker: Stock ticker symbol

        Returns:
            Dict with all technical indicators
        """
        cache_key = f"technical_{ticker}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        result = {
            "ticker": ticker,
            "company_name": UNIVERSE.get(ticker, {}).get("name", ticker),
            "sector": UNIVERSE.get(ticker, {}).get("sector", ""),
            "timestamp": datetime.now().isoformat(),
        }

        df = self._get_price_data(ticker, period="1y")
        if df is None or df.empty:
            result["error"] = "Unable to fetch price data"
            return result

        close = df["Close"]
        volume = df["Volume"]
        current_price = float(close.iloc[-1])

        result["current_price"] = current_price

        # Moving Averages
        sma20 = self._calculate_sma(close, 20)
        sma50 = self._calculate_sma(close, 50)
        sma200 = self._calculate_sma(close, 200)

        result["sma_20"] = float(sma20.iloc[-1]) if not sma20.empty else None
        result["sma_50"] = float(sma50.iloc[-1]) if not sma50.empty and not pd.isna(sma50.iloc[-1]) else None
        result["sma_200"] = float(sma200.iloc[-1]) if not sma200.empty and not pd.isna(sma200.iloc[-1]) else None

        # Price vs MAs
        if result["sma_50"]:
            result["pct_above_sma50"] = ((current_price - result["sma_50"]) / result["sma_50"]) * 100
            result["above_sma50"] = current_price > result["sma_50"]

        if result["sma_200"]:
            result["pct_above_sma200"] = ((current_price - result["sma_200"]) / result["sma_200"]) * 100
            result["above_sma200"] = current_price > result["sma_200"]

        # Golden/Death Cross
        if result["sma_50"] and result["sma_200"]:
            if result["sma_50"] > result["sma_200"]:
                result["ma_trend"] = "BULLISH"  # Golden cross territory
            else:
                result["ma_trend"] = "BEARISH"  # Death cross territory

        # RSI
        result["rsi_14"] = self._calculate_rsi(close, 14)
        if result["rsi_14"]:
            if result["rsi_14"] > self.RSI_OVERBOUGHT:
                result["rsi_signal"] = "OVERBOUGHT"
            elif result["rsi_14"] < self.RSI_OVERSOLD:
                result["rsi_signal"] = "OVERSOLD"
            else:
                result["rsi_signal"] = "NEUTRAL"

        # MACD
        macd_data = self._calculate_macd(close)
        result["macd"] = macd_data

        # Volume Analysis
        avg_volume_20 = volume.rolling(window=20).mean().iloc[-1]
        current_volume = volume.iloc[-1]

        result["current_volume"] = int(current_volume)
        result["avg_volume_20"] = int(avg_volume_20) if not pd.isna(avg_volume_20) else None
        if result["avg_volume_20"]:
            result["volume_ratio"] = current_volume / avg_volume_20
            result["volume_surge"] = result["volume_ratio"] >= self.VOLUME_SURGE_MULTIPLIER

        # Bollinger Bands
        result["bollinger"] = self._calculate_bollinger_bands(close)

        # Support/Resistance
        result["support_resistance"] = self._find_support_resistance(df)

        # 52-week stats
        result["high_52w"] = result["support_resistance"]["high_52w"]
        result["low_52w"] = result["support_resistance"]["low_52w"]
        result["pct_from_52w_high"] = result["support_resistance"]["pct_from_52w_high"]
        result["pct_from_52w_low"] = result["support_resistance"]["pct_from_52w_low"]

        # Calculate trend strength
        result["trend_strength"] = self._calculate_trend_strength(result)

        # Overall technical signal
        result["overall_signal"] = self._determine_overall_signal(result)

        self._set_cached(cache_key, result)
        return result

    def _calculate_trend_strength(self, data: dict) -> str:
        """Calculate overall trend strength."""
        bullish_signals = 0
        bearish_signals = 0

        # MA analysis
        if data.get("above_sma50"):
            bullish_signals += 1
        else:
            bearish_signals += 1

        if data.get("above_sma200"):
            bullish_signals += 1
        else:
            bearish_signals += 1

        if data.get("ma_trend") == "BULLISH":
            bullish_signals += 1
        elif data.get("ma_trend") == "BEARISH":
            bearish_signals += 1

        # RSI
        rsi_signal = data.get("rsi_signal", "NEUTRAL")
        if rsi_signal == "OVERBOUGHT":
            bearish_signals += 1  # Contrarian
        elif rsi_signal == "OVERSOLD":
            bullish_signals += 1  # Contrarian

        # MACD
        macd = data.get("macd", {})
        if macd.get("crossover") == "BULLISH":
            bullish_signals += 2
        elif macd.get("crossover") == "BEARISH":
            bearish_signals += 2
        elif macd.get("histogram", 0) > 0:
            bullish_signals += 1
        else:
            bearish_signals += 1

        # 52-week position
        pct_from_high = data.get("pct_from_52w_high", 0)
        if pct_from_high > -5:  # Near 52w high
            bullish_signals += 1
        elif pct_from_high < -20:  # More than 20% off high
            bearish_signals += 1

        total = bullish_signals + bearish_signals
        if total == 0:
            return "NEUTRAL"

        if bullish_signals > bearish_signals + 2:
            return "STRONG_BULLISH"
        elif bullish_signals > bearish_signals:
            return "BULLISH"
        elif bearish_signals > bullish_signals + 2:
            return "STRONG_BEARISH"
        elif bearish_signals > bullish_signals:
            return "BEARISH"
        else:
            return "NEUTRAL"

    def _determine_overall_signal(self, data: dict) -> str:
        """Determine overall technical signal."""
        trend = data.get("trend_strength", "NEUTRAL")

        # Adjust for extremes
        rsi_signal = data.get("rsi_signal", "NEUTRAL")
        bollinger = data.get("bollinger", {}).get("signal", "NEUTRAL")

        if trend in ["STRONG_BULLISH", "BULLISH"]:
            if rsi_signal == "OVERBOUGHT" or bollinger == "OVERBOUGHT":
                return "BULLISH_BUT_EXTENDED"
            return "BULLISH"
        elif trend in ["STRONG_BEARISH", "BEARISH"]:
            if rsi_signal == "OVERSOLD" or bollinger == "OVERSOLD":
                return "BEARISH_BUT_OVERSOLD"
            return "BEARISH"
        else:
            return "NEUTRAL"

    def scan_universe_technicals(self) -> dict:
        """
        Scan all universe for technical signals.

        Returns:
            Dict with categorized stocks by signal
        """
        results = {
            "bullish": [],
            "bearish": [],
            "overbought": [],
            "oversold": [],
            "volume_surge": [],
            "near_52w_high": [],
            "near_52w_low": [],
        }

        for ticker in UNIVERSE.keys():
            try:
                tech = self.get_technical_summary(ticker)
                if "error" in tech:
                    continue

                signal = tech.get("overall_signal", "NEUTRAL")

                if "BULLISH" in signal:
                    results["bullish"].append({"ticker": ticker, "signal": signal, "rsi": tech.get("rsi_14")})
                if "BEARISH" in signal:
                    results["bearish"].append({"ticker": ticker, "signal": signal, "rsi": tech.get("rsi_14")})
                if tech.get("rsi_signal") == "OVERBOUGHT":
                    results["overbought"].append({"ticker": ticker, "rsi": tech.get("rsi_14")})
                if tech.get("rsi_signal") == "OVERSOLD":
                    results["oversold"].append({"ticker": ticker, "rsi": tech.get("rsi_14")})
                if tech.get("volume_surge"):
                    results["volume_surge"].append({"ticker": ticker, "volume_ratio": tech.get("volume_ratio")})
                if tech.get("pct_from_52w_high", -100) > -5:
                    results["near_52w_high"].append({"ticker": ticker, "pct": tech.get("pct_from_52w_high")})
                if tech.get("pct_from_52w_low", 0) < 10:
                    results["near_52w_low"].append({"ticker": ticker, "pct": tech.get("pct_from_52w_low")})

            except Exception as e:
                logger.debug(f"Error scanning {ticker}: {e}")
                continue

        # Sort each category
        results["bullish"].sort(key=lambda x: x.get("rsi", 50), reverse=True)
        results["bearish"].sort(key=lambda x: x.get("rsi", 50))
        results["overbought"].sort(key=lambda x: x.get("rsi", 50), reverse=True)
        results["oversold"].sort(key=lambda x: x.get("rsi", 50))
        results["volume_surge"].sort(key=lambda x: x.get("volume_ratio", 0), reverse=True)

        return results


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    print("\n" + "="*60)
    print("ATLAS Technical Signals Client")
    print("="*60 + "\n")

    client = TechnicalClient()

    # Test NVDA technical summary
    print("--- NVDA Technical Summary ---")
    tech = client.get_technical_summary("NVDA")

    print(f"  Current Price: ${tech.get('current_price', 'N/A'):,.2f}")
    print(f"  50-day SMA: ${tech.get('sma_50', 'N/A'):,.2f}" if tech.get('sma_50') else "  50-day SMA: N/A")
    print(f"  200-day SMA: ${tech.get('sma_200', 'N/A'):,.2f}" if tech.get('sma_200') else "  200-day SMA: N/A")
    print(f"  Above 50-day: {tech.get('above_sma50', 'N/A')}")
    print(f"  Above 200-day: {tech.get('above_sma200', 'N/A')}")
    print(f"  MA Trend: {tech.get('ma_trend', 'N/A')}")

    print(f"\n  RSI (14): {tech.get('rsi_14', 'N/A'):.1f}" if tech.get('rsi_14') else "\n  RSI: N/A")
    print(f"  RSI Signal: {tech.get('rsi_signal', 'N/A')}")

    macd = tech.get('macd', {})
    print(f"\n  MACD: {macd.get('macd_line', 'N/A'):.2f}" if macd.get('macd_line') else "\n  MACD: N/A")
    print(f"  Signal Line: {macd.get('signal_line', 'N/A'):.2f}" if macd.get('signal_line') else "  Signal: N/A")
    print(f"  MACD Crossover: {macd.get('crossover', 'N/A')}")

    print(f"\n  Volume Surge: {tech.get('volume_surge', False)}")
    print(f"  Volume Ratio: {tech.get('volume_ratio', 'N/A'):.2f}x" if tech.get('volume_ratio') else "  Volume Ratio: N/A")

    bb = tech.get('bollinger', {})
    print(f"\n  Bollinger Signal: {bb.get('signal', 'N/A')}")
    print(f"  Band Position: {bb.get('position_in_bands', 'N/A'):.1%}" if bb.get('position_in_bands') else "  Band Position: N/A")

    print(f"\n  52-week High: ${tech.get('high_52w', 'N/A'):,.2f}" if tech.get('high_52w') else "\n  52w High: N/A")
    print(f"  % from 52w High: {tech.get('pct_from_52w_high', 'N/A'):.1f}%" if tech.get('pct_from_52w_high') else "  % from High: N/A")

    print(f"\n  Trend Strength: {tech.get('trend_strength', 'N/A')}")
    print(f"  Overall Signal: {tech.get('overall_signal', 'N/A')}")

    # Test universe scan
    print("\n--- Universe Technical Scan ---")
    scan = client.scan_universe_technicals()
    print(f"  Bullish: {len(scan['bullish'])} stocks")
    print(f"  Bearish: {len(scan['bearish'])} stocks")
    print(f"  Overbought: {len(scan['overbought'])} stocks")
    print(f"  Oversold: {len(scan['oversold'])} stocks")
    print(f"  Volume Surge: {len(scan['volume_surge'])} stocks")

    if scan["oversold"]:
        print("\n  Oversold stocks:")
        for s in scan["oversold"][:3]:
            print(f"    {s['ticker']} - RSI: {s['rsi']:.1f}")
