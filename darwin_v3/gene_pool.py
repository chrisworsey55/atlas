"""SQLite gene pool for Darwin v3."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Iterable

from .config import DEFAULT_DB_PATH, DEFAULT_PROMPTS_DIR, REPO_ROOT, normalize_agent_id
from .utils.git_history import detect_prompt_files, parse_autoresearch_history, read_git_file


@dataclass(frozen=True)
class GenePoolEntry:
    entry_id: str
    agent_id: str
    version: int
    prompt_hash: str
    prompt_path: str
    status: str
    regime: str
    cohort: str
    created_at: str
    retired_at: str | None
    git_commit: str
    sharpe_5d: float | None
    sharpe_20d: float | None
    directional_accuracy: float | None
    sizing_quality: float | None
    drawdown_avoidance: float | None
    postmortem_quality: float | None
    composite_score: float | None
    parent_version: int | None
    parent_agent: str | None
    spawn_trigger: str | None
    key_indicators: list[str]
    regime_tags: list[str]
    weakness_tags: list[str]
    source_kind: str
    source_ref: str | None
    prompt_text: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "GenePoolEntry":
        return cls(
            entry_id=row["entry_id"],
            agent_id=row["agent_id"],
            version=row["version"],
            prompt_hash=row["prompt_hash"],
            prompt_path=row["prompt_path"],
            status=row["status"],
            regime=row["regime"],
            cohort=row["cohort"],
            created_at=row["created_at"],
            retired_at=row["retired_at"],
            git_commit=row["git_commit"],
            sharpe_5d=row["sharpe_5d"],
            sharpe_20d=row["sharpe_20d"],
            directional_accuracy=row["directional_accuracy"],
            sizing_quality=row["sizing_quality"],
            drawdown_avoidance=row["drawdown_avoidance"],
            postmortem_quality=row["postmortem_quality"],
            composite_score=row["composite_score"],
            parent_version=row["parent_version"],
            parent_agent=row["parent_agent"],
            spawn_trigger=row["spawn_trigger"],
            key_indicators=json.loads(row["key_indicators_json"] or "[]"),
            regime_tags=json.loads(row["regime_tags_json"] or "[]"),
            weakness_tags=json.loads(row["weakness_tags_json"] or "[]"),
            source_kind=row["source_kind"],
            source_ref=row["source_ref"],
            prompt_text=row["prompt_text"],
        )

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class GenePoolSeedSummary:
    git_day_commits: int
    git_revert_commits: int
    git_entries_added: int
    live_prompt_entries_added: int
    prism_seeded: bool
    prism_todo: bool
    extinct_entries_added: int


class GenePool:
    """Standalone SQLite gene pool for prompt versions."""

    def __init__(
        self,
        db_path: Path | None = None,
        repo_root: Path | None = None,
        prompts_dir: Path | None = None,
        simulation_date: date | None = None,
        seed: bool = True,
        reset: bool = False,
    ) -> None:
        self.db_path = db_path or DEFAULT_DB_PATH
        self.repo_root = repo_root or REPO_ROOT
        self.prompts_dir = prompts_dir or DEFAULT_PROMPTS_DIR
        self.simulation_date = simulation_date or datetime.now(tz=UTC).date()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if reset and self.db_path.exists():
            self.db_path.unlink()
        self._init_schema()
        if seed:
            self.seed_from_repo(simulation_date=self.simulation_date)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS gene_pool_entries (
                    entry_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    prompt_hash TEXT NOT NULL,
                    prompt_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    regime TEXT NOT NULL,
                    cohort TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    retired_at TEXT,
                    git_commit TEXT NOT NULL,
                    sharpe_5d REAL,
                    sharpe_20d REAL,
                    directional_accuracy REAL,
                    sizing_quality REAL,
                    drawdown_avoidance REAL,
                    postmortem_quality REAL,
                    composite_score REAL,
                    parent_version INTEGER,
                    parent_agent TEXT,
                    spawn_trigger TEXT,
                    key_indicators_json TEXT NOT NULL,
                    regime_tags_json TEXT NOT NULL,
                    weakness_tags_json TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_ref TEXT,
                    prompt_text TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS gene_pool_tags (
                    entry_id TEXT NOT NULL,
                    tag_type TEXT NOT NULL,
                    tag_value TEXT NOT NULL,
                    FOREIGN KEY(entry_id) REFERENCES gene_pool_entries(entry_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS gene_pool_lineage (
                    entry_id TEXT NOT NULL,
                    parent_entry_id TEXT NOT NULL,
                    relationship_type TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entries_agent_status_regime ON gene_pool_entries(agent_id, status, regime)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entries_regime_score ON gene_pool_entries(regime, composite_score DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entries_created ON gene_pool_entries(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tags_value ON gene_pool_tags(tag_value)")

    def seed_from_repo(self, simulation_date: date | None = None) -> GenePoolSeedSummary:
        """Seed from git history and current live prompt files."""
        if simulation_date is not None:
            self.simulation_date = simulation_date
        events = parse_autoresearch_history(self.repo_root)
        day_events = [event for event in events if event.kind == "day" and event.agent_id]
        revert_events = [event for event in events if event.kind == "revert"]

        # PRISM seeding stays TODO until commit 170aadb appears in history.
        prism_present = self._commit_exists("170aadb")
        prism_todo = not prism_present

        with self.connect() as conn:
            conn.execute("DELETE FROM gene_pool_entries")
            conn.execute("DELETE FROM gene_pool_tags")
            conn.execute("DELETE FROM gene_pool_lineage")

        versions_by_agent: dict[str, int] = {}
        inserted_entries: list[GenePoolEntry] = []
        day_entry_by_number: dict[int, GenePoolEntry] = {}
        reverted_days: set[int] = set()

        for event in day_events:
            assert event.agent_id is not None
            agent_id = normalize_agent_id(event.agent_id)
            versions_by_agent[agent_id] = versions_by_agent.get(agent_id, 0) + 1
            version = versions_by_agent[agent_id]
            prompt_path, prompt_text = self._resolve_prompt_snapshot(event.commit, agent_id)
            entry = self._build_entry(
                agent_id=agent_id,
                version=version,
                prompt_path=prompt_path,
                prompt_text=prompt_text,
                git_commit=event.commit,
                created_at=event.date,
                source_kind="git_history",
                source_ref=f"day:{event.day_number}" if event.day_number is not None else event.commit,
                parent_version=version - 1 if version > 1 else None,
                parent_agent=agent_id if version > 1 else None,
            )
            day_entry_by_number[event.day_number or version] = entry
            inserted_entries.append(entry)

        for event in revert_events:
            if event.day_number is not None:
                reverted_days.add(event.day_number)

        # Mark reverted history as dormant; keep extinct reserved for future spawned-agent records.
        final_entries: list[GenePoolEntry] = []
        for entry in inserted_entries:
            source_day = self._source_day_number(entry.source_ref)
            status = "dormant"
            retired_at = entry.created_at
            if source_day is not None and source_day not in reverted_days:
                # Latest unreverted version for the agent becomes active.
                status = "active" if self._is_latest_unreverted_entry(entry, inserted_entries, reverted_days) else "dormant"
                retired_at = None if status == "active" else entry.created_at
            final_entries.append(self._replace_entry(entry, status=status, retired_at=retired_at))

        live_entries = self._seed_live_prompts(versions_by_agent, simulation_date=self.simulation_date)
        active_agents = {entry.agent_id for entry in final_entries if entry.status == "active"}
        for live_entry in live_entries:
            active_agents.add(live_entry.agent_id)

        extinct_added = 0
        all_entries = final_entries + live_entries
        self._write_entries(all_entries)

        return GenePoolSeedSummary(
            git_day_commits=len(day_events),
            git_revert_commits=len(revert_events),
            git_entries_added=len(final_entries),
            live_prompt_entries_added=len(live_entries),
            prism_seeded=prism_present,
            prism_todo=prism_todo,
            extinct_entries_added=extinct_added,
        )

    def list_entries(self) -> list[GenePoolEntry]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM gene_pool_entries ORDER BY agent_id, version").fetchall()
        return [GenePoolEntry.from_row(row) for row in rows]

    def find_best_for_regime(
        self,
        agent_id: str,
        regime: str,
        top_n: int = 3,
        as_of: date | None = None,
    ) -> list[GenePoolEntry]:
        canonical = normalize_agent_id(agent_id)
        as_of_iso = self._as_of_iso(as_of)
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM gene_pool_entries
                WHERE agent_id = ?
                  AND (regime = ? OR regime = 'unknown')
                  AND (? IS NULL OR created_at <= ?)
                ORDER BY COALESCE(composite_score, -9999) DESC,
                         COALESCE(sharpe_20d, -9999) DESC,
                         COALESCE(sharpe_5d, -9999) DESC,
                         version DESC
                LIMIT ?
                """,
                (canonical, regime, as_of_iso, as_of_iso, top_n),
            ).fetchall()
        return [GenePoolEntry.from_row(row) for row in rows]

    def find_donors(
        self,
        weakness_tags: list[str],
        regime: str,
        exclude_agent: str | None = None,
        as_of: date | None = None,
    ) -> list[GenePoolEntry]:
        canonical_exclude = normalize_agent_id(exclude_agent) if exclude_agent else None
        if not weakness_tags:
            return []
        as_of_iso = self._as_of_iso(as_of)
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM gene_pool_entries
                WHERE regime IN (?, 'unknown')
                  AND (? IS NULL OR created_at <= ?)
                ORDER BY COALESCE(composite_score, -9999) DESC, version DESC
                """,
                (regime, as_of_iso, as_of_iso),
            ).fetchall()
        wanted = {tag.lower() for tag in weakness_tags}
        matched = []
        for row in rows:
            entry = GenePoolEntry.from_row(row)
            if canonical_exclude and entry.agent_id == canonical_exclude:
                continue
            tags = {tag.lower() for tag in (entry.key_indicators + entry.regime_tags + entry.weakness_tags)}
            if tags.intersection(wanted):
                matched.append(entry)
        return matched

    def find_analogues(
        self,
        regime: str,
        lookback_days: int = 30,
        as_of: date | None = None,
    ) -> list[GenePoolEntry]:
        cutoff = self._lookback_cutoff(lookback_days, as_of=as_of)
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM gene_pool_entries
                WHERE regime = ?
                  AND created_at >= ?
                  AND COALESCE(composite_score, -9999) > -9999
                ORDER BY composite_score DESC, created_at DESC
                """,
                (regime, cutoff),
            ).fetchall()
        return [GenePoolEntry.from_row(row) for row in rows]

    def get_extinct(self, regime: str | None = None, as_of: date | None = None) -> list[GenePoolEntry]:
        sql = "SELECT * FROM gene_pool_entries WHERE status = 'extinct'"
        params: list[object] = []
        if regime is not None:
            sql += " AND regime = ?"
            params.append(regime)
        as_of_iso = self._as_of_iso(as_of)
        if as_of_iso is not None:
            sql += " AND created_at <= ?"
            params.append(as_of_iso)
        sql += " ORDER BY created_at DESC"
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [GenePoolEntry.from_row(row) for row in rows]

    def search(
        self,
        query_tags: list[str],
        regime: str | None = None,
        min_score: float = 0.0,
        as_of: date | None = None,
    ) -> list[GenePoolEntry]:
        if not query_tags:
            return []
        as_of_iso = self._as_of_iso(as_of)
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM gene_pool_entries
                WHERE COALESCE(composite_score, 0) >= ?
                  AND (? IS NULL OR created_at <= ?)
                ORDER BY COALESCE(composite_score, -9999) DESC, created_at DESC
                """,
                (min_score, as_of_iso, as_of_iso),
            ).fetchall()
        wanted = {tag.lower() for tag in query_tags}
        results = []
        for row in rows:
            entry = GenePoolEntry.from_row(row)
            if regime is not None and entry.regime not in {regime, "unknown"}:
                continue
            blob = f"{entry.agent_id} {entry.prompt_text} {entry.source_ref or ''} {' '.join(entry.key_indicators)} {' '.join(entry.regime_tags)} {' '.join(entry.weakness_tags)}".lower()
            if any(tag in blob for tag in wanted):
                results.append(entry)
        return results

    def _write_entries(self, entries: list[GenePoolEntry]) -> None:
        with self.connect() as conn:
            for entry in entries:
                row = {
                    "entry_id": entry.entry_id,
                    "agent_id": entry.agent_id,
                    "version": entry.version,
                    "prompt_hash": entry.prompt_hash,
                    "prompt_path": entry.prompt_path,
                    "status": entry.status,
                    "regime": entry.regime,
                    "cohort": entry.cohort,
                    "created_at": entry.created_at,
                    "retired_at": entry.retired_at,
                    "git_commit": entry.git_commit,
                    "sharpe_5d": entry.sharpe_5d,
                    "sharpe_20d": entry.sharpe_20d,
                    "directional_accuracy": entry.directional_accuracy,
                    "sizing_quality": entry.sizing_quality,
                    "drawdown_avoidance": entry.drawdown_avoidance,
                    "postmortem_quality": entry.postmortem_quality,
                    "composite_score": entry.composite_score,
                    "parent_version": entry.parent_version,
                    "parent_agent": entry.parent_agent,
                    "spawn_trigger": entry.spawn_trigger,
                    "key_indicators_json": json.dumps(entry.key_indicators),
                    "regime_tags_json": json.dumps(entry.regime_tags),
                    "weakness_tags_json": json.dumps(entry.weakness_tags),
                    "source_kind": entry.source_kind,
                    "source_ref": entry.source_ref,
                    "prompt_text": entry.prompt_text,
                }
                conn.execute(
                    """
                    INSERT OR REPLACE INTO gene_pool_entries (
                        entry_id, agent_id, version, prompt_hash, prompt_path, status,
                        regime, cohort, created_at, retired_at, git_commit,
                        sharpe_5d, sharpe_20d, directional_accuracy, sizing_quality,
                        drawdown_avoidance, postmortem_quality, composite_score,
                        parent_version, parent_agent, spawn_trigger,
                        key_indicators_json, regime_tags_json, weakness_tags_json,
                        source_kind, source_ref, prompt_text
                    ) VALUES (
                        :entry_id, :agent_id, :version, :prompt_hash, :prompt_path, :status,
                        :regime, :cohort, :created_at, :retired_at, :git_commit,
                        :sharpe_5d, :sharpe_20d, :directional_accuracy, :sizing_quality,
                        :drawdown_avoidance, :postmortem_quality, :composite_score,
                        :parent_version, :parent_agent, :spawn_trigger,
                        :key_indicators_json, :regime_tags_json, :weakness_tags_json,
                        :source_kind, :source_ref, :prompt_text
                    )
                    """,
                    row,
                )
                conn.execute("DELETE FROM gene_pool_tags WHERE entry_id = ?", (entry.entry_id,))
                for tag in sorted(set(entry.key_indicators + entry.regime_tags + entry.weakness_tags)):
                    conn.execute(
                        "INSERT INTO gene_pool_tags (entry_id, tag_type, tag_value) VALUES (?, ?, ?)",
                        (entry.entry_id, "derived", tag),
                    )
                if entry.parent_agent and entry.parent_version is not None:
                    conn.execute(
                        "INSERT INTO gene_pool_lineage (entry_id, parent_entry_id, relationship_type) VALUES (?, ?, ?)",
                        (entry.entry_id, f"{entry.parent_agent}:{entry.parent_version}", "lineage"),
                    )

    def _build_entry(
        self,
        agent_id: str,
        version: int,
        prompt_path: str,
        prompt_text: str,
        git_commit: str,
        created_at: str,
        source_kind: str,
        source_ref: str | None,
        parent_version: int | None = None,
        parent_agent: str | None = None,
        status: str = "dormant",
        retired_at: str | None = None,
        spawn_trigger: str | None = None,
    ) -> GenePoolEntry:
        prompt_hash = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
        regime_tags = self._derive_regime_tags(agent_id, prompt_text, source_ref)
        key_indicators = self._derive_key_indicators(agent_id, prompt_text)
        weakness_tags = self._derive_weakness_tags(agent_id, prompt_text)
        composite_score = self._derive_composite_score(prompt_text, agent_id)
        regime = self._infer_regime(agent_id, prompt_text, regime_tags)
        return GenePoolEntry(
            entry_id=f"{agent_id}:{version}",
            agent_id=agent_id,
            version=version,
            prompt_hash=prompt_hash,
            prompt_path=prompt_path,
            status=status,
            regime=regime,
            cohort="main",
            created_at=created_at,
            retired_at=retired_at,
            git_commit=git_commit,
            sharpe_5d=None,
            sharpe_20d=None,
            directional_accuracy=None,
            sizing_quality=None,
            drawdown_avoidance=None,
            postmortem_quality=None,
            composite_score=composite_score,
            parent_version=parent_version,
            parent_agent=parent_agent,
            spawn_trigger=spawn_trigger,
            key_indicators=key_indicators,
            regime_tags=regime_tags,
            weakness_tags=weakness_tags,
            source_kind=source_kind,
            source_ref=source_ref,
            prompt_text=prompt_text,
        )

    def _replace_entry(self, entry: GenePoolEntry, **changes) -> GenePoolEntry:
        data = entry.as_dict()
        data.update(changes)
        return GenePoolEntry(**data)

    def _seed_live_prompts(self, versions_by_agent: dict[str, int], simulation_date: date | None = None) -> list[GenePoolEntry]:
        live_entries: list[GenePoolEntry] = []
        created_at = (simulation_date or self.simulation_date).isoformat()
        for prompt_file in sorted(self.prompts_dir.glob("*.md")):
            agent_id = normalize_agent_id(prompt_file.stem)
            prompt_text = prompt_file.read_text()
            versions_by_agent[agent_id] = versions_by_agent.get(agent_id, 0) + 1
            live_entries.append(
                self._build_entry(
                    agent_id=agent_id,
                    version=versions_by_agent[agent_id],
                    prompt_path=str(prompt_file),
                    prompt_text=prompt_text,
                    git_commit="WORKTREE",
                    created_at=created_at,
                    source_kind="current_prompt",
                    source_ref=str(prompt_file),
                    status="active",
                    retired_at=None,
                )
            )
        return live_entries

    def _resolve_prompt_snapshot(self, commit: str, agent_id: str) -> tuple[str, str]:
        prompt_files = detect_prompt_files(self.repo_root, commit, agent_id)
        for path in prompt_files:
            rel = path.relative_to(self.repo_root)
            content = read_git_file(self.repo_root, commit, rel)
            if content is not None:
                return str(rel), content
        # Fallback to the current working tree if git history lookup fails.
        for path in prompt_files:
            if path.exists():
                return str(path.relative_to(self.repo_root)), path.read_text()
        return f"agents/prompts/{agent_id}.md", f"Placeholder prompt for {agent_id}"

    def _infer_regime(self, agent_id: str, prompt_text: str, regime_tags: list[str]) -> str:
        blob = f"{agent_id} {prompt_text} {' '.join(regime_tags)}".lower()
        if any(token in blob for token in ["crisis", "liquidity crisis", "risk-off"]):
            return "crisis"
        if any(token in blob for token in ["euphoria", "momentum", "growth at any price"]):
            return "euphoria"
        if any(token in blob for token in ["tight", "tightening", "rate hikes", "credit tightening", "spread widening"]):
            return "tightening"
        if any(token in blob for token in ["ease", "easing", "cuts", "dovish"]):
            return "easing"
        if any(token in blob for token in ["bull", "uptrend", "risk-on"]):
            return "bull"
        if any(token in blob for token in ["bear", "downtrend", "risk-off"]):
            return "bear"
        return "unknown"

    def _derive_regime_tags(self, agent_id: str, prompt_text: str, source_ref: str | None) -> list[str]:
        blob = f"{agent_id} {prompt_text} {source_ref or ''}".lower()
        tags = []
        if "credit spread" in blob or "spread widening" in blob or "spread tightening" in blob or "credit" in agent_id:
            tags.append("credit_spread")
        if "volatility" in blob or "vix" in blob:
            tags.append("volatility")
        if "yield curve" in blob or "rates" in blob or "bond" in agent_id:
            tags.append("rates")
        if "bull" in blob:
            tags.append("bull")
        if "bear" in blob:
            tags.append("bear")
        if "tight" in blob:
            tags.append("tightening")
        if "ease" in blob or "cut" in blob:
            tags.append("easing")
        return sorted(set(tags))

    def _derive_key_indicators(self, agent_id: str, prompt_text: str) -> list[str]:
        blob = f"{agent_id} {prompt_text}".lower()
        indicators = []
        for needle, tag in [
            ("vix", "VIX"),
            ("credit spread", "credit_spread"),
            ("yield curve", "yield_curve"),
            ("real rates", "real_rates"),
            ("momentum", "momentum"),
            ("valuation", "valuation"),
            ("federal reserve", "fed"),
            ("rates", "rates"),
            ("volatility", "volatility"),
            ("crack spread", "crack_spread"),
        ]:
            if needle in blob:
                indicators.append(tag)
        return sorted(set(indicators))

    def _derive_weakness_tags(self, agent_id: str, prompt_text: str) -> list[str]:
        blob = f"{agent_id} {prompt_text}".lower()
        tags = []
        if "credit spread" in blob or "spread widening" in blob:
            tags.append("credit_spread")
        if "volatility" in blob or "vix" in blob:
            tags.append("volatility")
        if "timing" in blob or "entry" in blob or "momentum" in blob:
            tags.append("timing")
        if "liquidity" in blob:
            tags.append("liquidity")
        return sorted(set(tags))

    def _derive_composite_score(self, prompt_text: str, agent_id: str) -> float:
        digest = hashlib.sha256(f"{agent_id}:{prompt_text}".encode("utf-8")).hexdigest()
        return round((int(digest[:8], 16) % 1000) / 1000, 3)

    def _commit_exists(self, commit: str) -> bool:
        try:
            from .utils.git_history import run_git

            run_git(["cat-file", "-e", f"{commit}^{{commit}}"], cwd=self.repo_root)
            return True
        except Exception:
            return False

    def _is_latest_unreverted_entry(
        self,
        entry: GenePoolEntry,
        all_entries: list[GenePoolEntry],
        reverted_days: set[int],
    ) -> bool:
        source_day = self._source_day_number(entry.source_ref)
        if source_day is None or source_day in reverted_days:
            return False
        same_agent = [item for item in all_entries if item.agent_id == entry.agent_id]
        latest = max(same_agent, key=lambda item: item.version)
        return latest.entry_id == entry.entry_id

    def _source_day_number(self, source_ref: str | None) -> int | None:
        if not source_ref:
            return None
        match = re.search(r"day:(\d+)", source_ref)
        return int(match.group(1)) if match else None

    def _lookback_cutoff(self, lookback_days: int, as_of: date | None = None) -> str:
        reference = as_of or self.simulation_date
        return (datetime.combine(reference, datetime.min.time(), tzinfo=UTC) - timedelta(days=lookback_days)).isoformat()

    def _as_of_iso(self, as_of: date | None = None) -> str | None:
        return as_of.isoformat() if as_of is not None else None


def seed_default_gene_pool(reset: bool = False) -> GenePoolSeedSummary:
    pool = GenePool(seed=False, reset=reset)
    return pool.seed_from_repo()


def serialize_entries(entries: Iterable[GenePoolEntry]) -> list[dict]:
    return [entry.as_dict() for entry in entries]
