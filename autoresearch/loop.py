#!/usr/bin/env python3
"""
ATLAS Autoresearch — Main Experiment Loop

This is the main autonomous loop. It runs indefinitely.

SETUP:
1. Create git branch: autoresearch/{date_tag}
2. Run eod_cycle.py with current prompts to establish baseline
3. Score baseline with backtest.py
4. Record baseline in experiments.tsv
5. Begin loop

LOOP FOREVER:
1. Load agent_scores.json → identify worst agent
2. Load that agent's prompt from agents/prompts/{agent}.md
3. Call mutator.py → get mutated prompt
4. Write mutated prompt to agents/prompts/{agent}.md
5. Git commit: "autoresearch: {agent} - {mutation_type} - {description}"
6. Run eod_cycle.py (or fast_cycle.py for speed)
7. Score with backtest.py → parse sharpe_30d
8. If sharpe_30d improved:
   - Keep commit
   - Update agent_scores.json
   - Log to experiments.tsv: status=keep
9. If sharpe_30d equal or worse:
   - git reset --hard HEAD~1
   - Log to experiments.tsv: status=discard
10. If crash:
    - Check error, attempt fix once
    - If still broken: git reset, log status=crash
11. Go to step 1

NEVER STOP. Do not ask the human. Continue until manually interrupted.
"""

import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from autoresearch.attribution import get_worst_agent, load_agent_scores, save_agent_scores, process_eod_views
from autoresearch.backtest import run_backtest, reset_session_window
from autoresearch.mutator import mutate_agent, load_prompt, MUTATION_TYPES
from autoresearch.fast_cycle import run_fast_cycle, run_full_baseline

RESULTS_DIR = Path(__file__).parent / "results"
EXPERIMENTS_FILE = Path(__file__).parent / "experiments.tsv"
ALERTS_FILE = Path(__file__).parent / "alerts.log"
STATE_DIR = Path(__file__).parent.parent / "data" / "state"
PROMPTS_DIR = Path(__file__).parent.parent / "agents" / "prompts"

# Loop state tracking
CONSECUTIVE_FAILURES = 0
MAX_CONSECUTIVE_FAILURES = 50


def log_alert(message: str):
    """Write alert to alerts.log without stopping the loop."""
    timestamp = datetime.now().isoformat()
    with open(ALERTS_FILE, "a") as f:
        f.write(f"[{timestamp}] {message}\n")
    print(f"[ALERT] {message}")


def log_experiment(
    commit: str,
    sharpe_30d: float,
    agent: str,
    mutation_type: str,
    status: str,
    description: str,
    prompt_tokens: int = 0
):
    """Log experiment to experiments.tsv."""
    timestamp = datetime.now().isoformat()

    # Create header if file doesn't exist
    if not EXPERIMENTS_FILE.exists():
        with open(EXPERIMENTS_FILE, "w") as f:
            f.write("commit\tsharpe_30d\tagent\tmutation_type\tstatus\tdescription\tprompt_tokens\ttimestamp\n")

    with open(EXPERIMENTS_FILE, "a") as f:
        # Sanitize description (no tabs or newlines)
        desc = description.replace("\t", " ").replace("\n", " ")[:100]
        f.write(f"{commit}\t{sharpe_30d:.4f}\t{agent}\t{mutation_type}\t{status}\t{desc}\t{prompt_tokens}\t{timestamp}\n")


def git_command(*args) -> tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent.parent)
    )
    return result.returncode, result.stdout, result.stderr


def create_autoresearch_branch() -> str:
    """Create and checkout autoresearch branch."""
    date_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    branch_name = f"autoresearch/{date_tag}"

    # Check if we're already on an autoresearch branch
    code, current_branch, _ = git_command("branch", "--show-current")
    if code == 0 and current_branch.strip().startswith("autoresearch/"):
        print(f"[loop] Already on autoresearch branch: {current_branch.strip()}")
        return current_branch.strip()

    # Create new branch
    code, _, err = git_command("checkout", "-b", branch_name)
    if code != 0:
        print(f"[loop] Warning: Could not create branch: {err}")
        # Try to continue on current branch
        return current_branch.strip()

    print(f"[loop] Created branch: {branch_name}")
    return branch_name


def git_commit(message: str) -> str:
    """Stage changes and commit. Returns commit hash or empty string on failure."""
    # Stage all prompt changes
    git_command("add", "agents/prompts/")

    # Commit
    code, stdout, stderr = git_command("commit", "-m", message)
    if code != 0:
        print(f"[loop] Commit failed: {stderr}")
        return ""

    # Get commit hash
    code, stdout, _ = git_command("rev-parse", "--short", "HEAD")
    return stdout.strip() if code == 0 else ""


def git_reset():
    """Reset to previous commit."""
    code, _, stderr = git_command("reset", "--hard", "HEAD~1")
    if code != 0:
        print(f"[loop] Reset failed: {stderr}")
        return False
    print("[loop] Reset to previous commit")
    return True


def check_agent_weight(agent_name: str) -> float:
    """Get current weight for an agent."""
    weights_file = STATE_DIR / "agent_weights.json"
    if weights_file.exists():
        with open(weights_file) as f:
            weights = json.load(f)
        return weights.get(agent_name, 1.0)
    return 1.0


def update_agent_weight(agent_name: str, new_weight: float):
    """Update weight for an agent."""
    weights_file = STATE_DIR / "agent_weights.json"
    if weights_file.exists():
        with open(weights_file) as f:
            weights = json.load(f)
    else:
        weights = {}

    weights[agent_name] = max(0.3, min(2.5, new_weight))
    weights["last_updated"] = datetime.now().isoformat()

    with open(weights_file, "w") as f:
        json.dump(weights, f, indent=2)


def run_experiment(session_id: str, baseline_sharpe: float) -> dict:
    """
    Run a single experiment iteration.

    Returns dict with:
    - success: bool
    - agent: str
    - mutation_type: str
    - sharpe_30d: float
    - status: "keep" | "discard" | "crash"
    """
    global CONSECUTIVE_FAILURES

    result = {
        "success": False,
        "agent": None,
        "mutation_type": None,
        "sharpe_30d": 0.0,
        "status": "crash"
    }

    try:
        # 1. Identify worst agent
        worst_agent, agent_data = get_worst_agent()
        result["agent"] = worst_agent

        print(f"\n{'='*60}")
        print(f"EXPERIMENT: Mutating {worst_agent}")
        print(f"Current Sharpe: {agent_data.get('rolling_sharpe', 0):.2f}")
        print(f"Baseline Sharpe: {baseline_sharpe:.2f}")
        print(f"{'='*60}")

        # Check weight threshold
        weight = check_agent_weight(worst_agent)
        if weight <= 0.3:
            log_alert(f"Agent {worst_agent} weight at floor (0.3)")

        # 2. Load current prompt (for backup)
        original_prompt = load_prompt(worst_agent)
        prompt_tokens = len(original_prompt) // 4 if original_prompt else 0

        # 3. Mutate the prompt
        mutation_result = mutate_agent(worst_agent)
        result["mutation_type"] = mutation_result["mutation_type"]

        # Check token limit
        if mutation_result["new_tokens"] > 2000:
            log_alert(f"Prompt for {worst_agent} exceeds 2000 tokens ({mutation_result['new_tokens']})")

        # 4. Git commit
        commit_msg = f"autoresearch: {worst_agent} - {mutation_result['mutation_type']} - {mutation_result['description']}"
        commit_hash = git_commit(commit_msg)

        if not commit_hash:
            print("[loop] No changes to commit, skipping experiment")
            return result

        # 5. Run fast cycle
        views = run_fast_cycle(worst_agent, session_id=session_id)

        # 6. Process attribution
        process_eod_views(views)

        # 7. Run backtest
        backtest_results = run_backtest(cio_output=views.get("cio", ""))
        result["sharpe_30d"] = backtest_results.get("sharpe_30d", 0.0)

        # 8. Keep or revert decision
        if result["sharpe_30d"] > baseline_sharpe:
            # IMPROVEMENT - keep the commit
            result["status"] = "keep"
            result["success"] = True
            CONSECUTIVE_FAILURES = 0

            # Update agent weight (small boost for improvement)
            new_weight = min(weight * 1.05, 2.5)
            update_agent_weight(worst_agent, new_weight)

            print(f"\n[KEEP] Sharpe improved: {baseline_sharpe:.2f} -> {result['sharpe_30d']:.2f}")

        else:
            # NO IMPROVEMENT - revert
            result["status"] = "discard"
            CONSECUTIVE_FAILURES += 1

            # Revert the commit
            git_reset()

            # Slight weight reduction for failure
            new_weight = max(weight * 0.98, 0.3)
            update_agent_weight(worst_agent, new_weight)

            print(f"\n[DISCARD] No improvement: {baseline_sharpe:.2f} -> {result['sharpe_30d']:.2f}")

        # Log experiment
        log_experiment(
            commit=commit_hash,
            sharpe_30d=result["sharpe_30d"],
            agent=worst_agent,
            mutation_type=result["mutation_type"],
            status=result["status"],
            description=mutation_result["description"],
            prompt_tokens=mutation_result["new_tokens"]
        )

        # Check for alert conditions
        if CONSECUTIVE_FAILURES >= MAX_CONSECUTIVE_FAILURES:
            log_alert(f"50 consecutive experiments with no improvement")

        if result["sharpe_30d"] < -1.0:
            log_alert(f"Backtest sharpe below -1.0: {result['sharpe_30d']:.2f}")

    except Exception as e:
        # Crash handling
        error_msg = f"{type(e).__name__}: {str(e)}"
        print(f"\n[CRASH] {error_msg}")
        traceback.print_exc()

        result["status"] = "crash"
        log_experiment(
            commit="",
            sharpe_30d=0.0,
            agent=result["agent"] or "unknown",
            mutation_type=result["mutation_type"] or "unknown",
            status="crash",
            description=error_msg[:100],
            prompt_tokens=0
        )

        # Try to reset on crash
        git_reset()
        CONSECUTIVE_FAILURES += 1

    return result


def run_loop(once: bool = False):
    """
    Main autoresearch loop.

    Args:
        once: If True, run only one experiment (for testing)
    """
    print("\n" + "=" * 80)
    print("ATLAS AUTORESEARCH LOOP — STARTING")
    print("=" * 80)

    # Setup
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Create autoresearch branch
    branch = create_autoresearch_branch()

    # Reset session window
    reset_session_window()
    session_id = datetime.now().strftime("%Y%m%d")

    # Run baseline
    print("\n[loop] Establishing baseline...")
    baseline_views = run_full_baseline(session_id)

    # Score baseline
    process_eod_views(baseline_views)
    baseline_results = run_backtest(cio_output=baseline_views.get("cio", ""))
    baseline_sharpe = baseline_results.get("sharpe_30d", 0.0)

    # Log baseline
    log_experiment(
        commit="baseline",
        sharpe_30d=baseline_sharpe,
        agent="baseline",
        mutation_type="baseline",
        status="baseline",
        description=f"Initial baseline for session {session_id}",
        prompt_tokens=0
    )

    print(f"\n[loop] Baseline Sharpe: {baseline_sharpe:.2f}")
    print(f"[loop] Beginning experiment loop...")

    experiment_count = 0
    improvements = 0

    # LOOP FOREVER
    while True:
        experiment_count += 1

        print(f"\n{'#'*60}")
        print(f"# EXPERIMENT {experiment_count}")
        print(f"# Baseline Sharpe: {baseline_sharpe:.2f}")
        print(f"# Improvements: {improvements}")
        print(f"# Consecutive Failures: {CONSECUTIVE_FAILURES}")
        print(f"{'#'*60}")

        result = run_experiment(session_id, baseline_sharpe)

        if result["status"] == "keep":
            # Update baseline for next comparison
            baseline_sharpe = result["sharpe_30d"]
            improvements += 1

        # Print progress
        print(f"\n[loop] Experiment {experiment_count} complete: {result['status']}")
        print(f"[loop] Agent: {result['agent']}, Mutation: {result['mutation_type']}")
        print(f"[loop] Sharpe: {result['sharpe_30d']:.2f}")

        if once:
            print("\n[loop] --once flag set, exiting after one experiment")
            break

        # Small delay between experiments
        time.sleep(2)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ATLAS Autoresearch Loop")
    parser.add_argument("--once", action="store_true", help="Run only one experiment")
    args = parser.parse_args()

    try:
        run_loop(once=args.once)
    except KeyboardInterrupt:
        print("\n\n[loop] Interrupted by user")
        print("[loop] Progress saved. Run again to continue.")
