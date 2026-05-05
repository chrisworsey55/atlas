"""Breeding selector for Darwin v3."""

from __future__ import annotations

from dataclasses import dataclass, asdict
import json
from pathlib import Path
from datetime import datetime, timedelta, UTC

from .gene_pool import GenePool


@dataclass(frozen=True)
class RewriteStrategy:
    type: str
    reason: str
    donor: str | None = None
    restore_version: int | None = None
    gap_description: str | None = None
    confidence: float | None = None


class BreedingSelector:
    """Choose rewrite strategy from post-mortems and gene pool."""

    def __init__(
        self,
        gene_pool: GenePool,
        postmortem_dir: Path,
        log_path: Path,
    ) -> None:
        self.gene_pool = gene_pool
        self.postmortem_dir = postmortem_dir
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def select_rewrite_strategy(
        self,
        agent_id: str,
        current_version: int,
        current_regime: str = "unknown",
        current_score: float | None = None,
    ) -> RewriteStrategy:
        postmortems = self._load_recent_postmortems(agent_id, days=20)
        if not postmortems:
            return self._log(
                RewriteStrategy(
                    type="blind_mutation",
                    reason="No recent post-mortems found.",
                    confidence=0.1,
                )
            )

        weakness_tags = sorted({tag for pm in postmortems for tag in pm.get("knowledge_gaps", [])})
        donor_pool = self.gene_pool.find_donors(weakness_tags, current_regime, exclude_agent=agent_id)
        if donor_pool:
            donor = donor_pool[0]
            return self._log(
                RewriteStrategy(
                    type="targeted_splice",
                    reason=f"Donor {donor.agent_id}:{donor.version} covers weakness tags {weakness_tags}.",
                    donor=donor.agent_id,
                    confidence=0.9,
                    gap_description=", ".join(weakness_tags) or None,
                )
            )

        historical = self.gene_pool.find_best_for_regime(agent_id, current_regime, top_n=1)
        if historical and current_score is not None and historical[0].composite_score is not None:
            if historical[0].composite_score > current_score:
                return self._log(
                    RewriteStrategy(
                        type="regime_restoration",
                        reason=f"Historical version {historical[0].version} outperforms current score {current_score:.3f}.",
                        restore_version=historical[0].version,
                        confidence=0.8,
                    )
                )

        spawn_candidates = [
            pm
            for pm in postmortems
            if pm.get("spawn_candidate")
            and self._pm_days_ago(pm) <= 7
        ]
        if len(spawn_candidates) >= 3 and not donor_pool and not self.gene_pool.get_extinct(current_regime):
            description = spawn_candidates[-1].get("spawn_description")
            return self._log(
                RewriteStrategy(
                    type="trigger_spawn",
                    reason="Three spawn candidates accumulated and no donor/extinct coverage exists.",
                    gap_description=description,
                    confidence=0.95,
                )
            )

        return self._log(
            RewriteStrategy(
                type="blind_mutation",
                reason="No donor, restoration, or spawn condition satisfied.",
                confidence=0.2,
            )
        )

    def _load_recent_postmortems(self, agent_id: str, days: int) -> list[dict]:
        if not self.postmortem_dir.exists():
            return []
        cutoff = datetime.now(tz=UTC) - timedelta(days=days)
        items: list[dict] = []
        for path in sorted(self.postmortem_dir.glob(f"{agent_id}_*.json")):
            try:
                payload = json.loads(path.read_text())
            except json.JSONDecodeError:
                continue
            date_str = str(payload.get("date", ""))
            try:
                parsed = datetime.fromisoformat(date_str)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
            except ValueError:
                continue
            if parsed >= cutoff:
                items.append(payload)
        return items

    def _pm_days_ago(self, payload: dict) -> int:
        date_str = str(payload.get("date", ""))
        try:
            parsed = datetime.fromisoformat(date_str)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return max(0, (datetime.now(tz=UTC) - parsed).days)
        except ValueError:
            return 9999

    def _log(self, strategy: RewriteStrategy) -> RewriteStrategy:
        entry = asdict(strategy)
        entry["timestamp"] = datetime.now(tz=UTC).isoformat()
        existing: list[dict] = []
        if self.log_path.exists():
            try:
                existing = json.loads(self.log_path.read_text())
            except json.JSONDecodeError:
                existing = []
        existing.append(entry)
        self.log_path.write_text(json.dumps(existing, indent=2, sort_keys=True))
        return strategy

