"""Variant definitions for the Darwin v3 backtest."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VariantConfig:
    use_multidim_scorer: bool
    use_breeding: bool
    use_judge: bool
    use_informed_spawning: bool
    scorer_window: int


VARIANT_A = VariantConfig(
    use_multidim_scorer=False,
    use_breeding=False,
    use_judge=False,
    use_informed_spawning=False,
    scorer_window=5,
)

VARIANT_C = VariantConfig(
    use_multidim_scorer=True,
    use_breeding=True,
    use_judge=False,
    use_informed_spawning=False,
    scorer_window=20,
)

VARIANT_E = VariantConfig(
    use_multidim_scorer=True,
    use_breeding=True,
    use_judge=True,
    use_informed_spawning=True,
    scorer_window=20,
)

VARIANTS = {
    "A": VARIANT_A,
    "C": VARIANT_C,
    "E": VARIANT_E,
}
