"""Git history parsing for Darwin v3 gene pool seeding."""

from __future__ import annotations

from dataclasses import dataclass
import re
import subprocess
from pathlib import Path


@dataclass(frozen=True)
class GitAutoresearchEvent:
    commit: str
    date: str
    subject: str
    kind: str  # day | revert
    day_number: int | None
    agent_id: str | None


def run_git(args: list[str], cwd: Path) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def parse_autoresearch_history(repo_root: Path) -> list[GitAutoresearchEvent]:
    """Parse the real git log for autoresearch history."""
    output = run_git(
        ["log", "--all", "--date=iso-strict", "--format=%H\t%ad\t%s"],
        cwd=repo_root,
    )
    events: list[GitAutoresearchEvent] = []
    for line in output.splitlines():
        if "[autoresearch]" not in line:
            continue
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        commit, date, subject = parts
        kind = "revert" if "revert" in subject.lower() else "day" if "day" in subject.lower() else "other"
        day_number = None
        agent_id = None
        if kind == "day":
            day_match = re.search(r"day\s+(\d+)", subject, flags=re.IGNORECASE)
            if day_match:
                day_number = int(day_match.group(1))
            agent_match = re.search(r"modified\s+([a-z0-9_]+)", subject, flags=re.IGNORECASE)
            if agent_match:
                agent_id = agent_match.group(1).lower()
        elif kind == "revert":
            day_match = re.search(r"revert\s+day\s+(\d+)", subject, flags=re.IGNORECASE)
            if day_match:
                day_number = int(day_match.group(1))
        events.append(
            GitAutoresearchEvent(
                commit=commit,
                date=date,
                subject=subject,
                kind=kind,
                day_number=day_number,
                agent_id=agent_id,
            )
        )
    return events


def detect_prompt_files(repo_root: Path, commit: str, agent_id: str) -> list[Path]:
    """Find prompt files touched by a commit for a given agent."""
    try:
        changed = run_git(["diff-tree", "--no-commit-id", "--name-only", "-r", commit], cwd=repo_root)
    except subprocess.CalledProcessError:
        changed = ""

    candidates: list[Path] = []
    for rel in changed.splitlines():
        if rel.startswith("agents/prompts/") and agent_id in rel:
            candidates.append(repo_root / rel)

    if candidates:
        return candidates

    base = repo_root / "agents" / "prompts"
    fallback_names = [
        f"{agent_id}.md",
        f"{agent_id}_desk.md",
        f"{agent_id}_agent.md",
        f"{agent_id}.py",
        f"{agent_id}_agent.py",
    ]
    return [base / name for name in fallback_names if (base / name).exists()]


def read_git_file(repo_root: Path, commit: str, rel_path: Path) -> str | None:
    """Read a file at a specific commit if it exists there."""
    try:
        return run_git(["show", f"{commit}:{rel_path.as_posix()}"], cwd=repo_root)
    except subprocess.CalledProcessError:
        return None

