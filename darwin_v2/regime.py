"""Placeholder market regime tagging.

SIMONS integration is deliberately deferred. The placeholder uses supplied
market return and volatility inputs so tests and dry-runs stay offline.
"""

from __future__ import annotations

from darwin_v2.schema import RegimeTag


def tag_regime(market_return_21d: float = 0.0, realized_vol_21d: float = 0.15) -> RegimeTag:
    trend = "bull" if market_return_21d >= 0 else "bear"
    vol = "high_vol" if realized_vol_21d >= 0.25 else "low_vol"
    return f"{trend}_{vol}"  # type: ignore[return-value]
