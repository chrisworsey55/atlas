from __future__ import annotations

import os
from pathlib import Path


GRAHAM_DIR = Path(__file__).resolve().parent
ATLAS_DIR = GRAHAM_DIR.parent
CACHE_DIR = GRAHAM_DIR / "cache"
OUTPUT_DIR = GRAHAM_DIR / "output"
MEMO_OUTPUT_DIR = OUTPUT_DIR / "memos"
MEMO_CACHE_DIR = CACHE_DIR / "memos"

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "Z50G_fKhrQmUWZ_9gCpN2XYeaNI99MYW")

MIN_AVG_DAILY_VOLUME_DOLLARS = 25_000
ACTIVE_FILING_MONTHS = 18
STALE_FILING_DAYS = 183
NCAV_THRESHOLD = 0.67

EXCLUDED_SIC_CODES = {"6770"}
SHELL_REVIEW_SIC_CODES = {"6199", "6726"}


def ensure_dirs() -> None:
    for path in [
        CACHE_DIR,
        OUTPUT_DIR,
        MEMO_OUTPUT_DIR,
        MEMO_CACHE_DIR,
        CACHE_DIR / "submissions",
        CACHE_DIR / "companyfacts",
        CACHE_DIR / "filings",
    ]:
        path.mkdir(parents=True, exist_ok=True)

