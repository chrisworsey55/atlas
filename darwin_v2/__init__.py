"""ATLAS Darwin v2 prompt evolution package.

This package is intentionally isolated from the legacy ``autoresearch``
module. Nothing here is wired into production trading.
"""

__all__ = [
    "config",
    "schema",
    "prompt",
    "fitness",
    "selection",
    "mutation",
    "population",
    "lineage",
    "loop",
]
