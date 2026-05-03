from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    repo_root: Path
    state_root: Path
    kalshi_root: Path
    production: bool
    secret: str


def load_settings() -> Settings:
    repo_root = Path(__file__).resolve().parent.parent
    production = os.getenv("ATLAS_TERMINAL_ENV", "").lower() == "production"
    state_root = Path(os.getenv("ATLAS_STATE_ROOT", "/home/azureuser/atlas" if production else str(repo_root)))
    kalshi_root = Path(
        os.getenv(
            "ATLAS_KALSHI_ROOT",
            "/home/azureuser/atlas-predict" if production else str(repo_root / "predict"),
        )
    )
    return Settings(
        repo_root=repo_root,
        state_root=state_root,
        kalshi_root=kalshi_root,
        production=production,
        secret=os.getenv("ATLAS_TERMINAL_SECRET", "dev-terminal-secret"),
    )


settings = load_settings()

