from __future__ import annotations

import asyncio
import shlex
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from terminal.commands.registry import COMMANDS, command_help
from terminal.settings import settings


@dataclass
class CommandRun:
    id: str
    command: str
    status: str
    created_at: str
    output: list[str] = field(default_factory=list)
    ui_action: str | None = None


RUNS: dict[str, CommandRun] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_run(command: str, status: str = "RUNNING") -> CommandRun:
    run = CommandRun(id=str(uuid.uuid4()), command=command, status=status, created_at=_now())
    RUNS[run.id] = run
    return run


async def run_command(raw_command: str) -> CommandRun:
    command = raw_command.strip()
    run = _new_run(command)
    if not command:
        run.status = "ERROR"
        run.output.append("empty command")
        return run

    if not command.startswith("/"):
        run.status = "OK"
        run.ui_action = "ticker"
        run.output.append(f"ticker context set: {command.upper()}")
        return run

    if command == "/help":
        run.status = "OK"
        run.output.extend(f"{item['command']} - {item['description']}" for item in command_help())
        return run

    if command == "/status":
        run.status = "OK"
        run.output.append("open /terminal/api/health for full source freshness and cron status")
        return run

    for key, spec in COMMANDS.items():
        if command == key or command.startswith(key + " "):
            if spec.ui_action:
                run.status = "OK"
                run.ui_action = spec.ui_action
                run.output.append(f"workspace switch: {spec.ui_action}")
                return run
            if key == "/screen":
                parts = shlex.split(command)
                if len(parts) != 2:
                    run.status = "ERROR"
                    run.output.append("usage: /screen TICKER")
                    return run
                argv = ("python3", "run_gauntlet.py", parts[1].upper())
                return await _run_subprocess(run, argv)
            if key == "/trade":
                run.status = "NOT_WIRED"
                run.output.append("trade recording requires final trade journal adapter wiring")
                return run
            if spec.argv:
                return await _run_subprocess(run, spec.argv)

    run.status = "ERROR"
    run.output.append(f"unknown command: {command}")
    return run


async def _run_subprocess(run: CommandRun, argv: tuple[str, ...]) -> CommandRun:
    run.output.append("$ " + " ".join(shlex.quote(part) for part in argv))
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(settings.state_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
        except asyncio.TimeoutError:
            proc.kill()
            run.status = "TIMEOUT"
            run.output.append("command timed out after 300 seconds")
            return run
        if stdout:
            run.output.extend(stdout.decode(errors="replace").splitlines()[-200:])
        run.status = "OK" if proc.returncode == 0 else f"EXIT_{proc.returncode}"
    except FileNotFoundError as exc:
        run.status = "ERROR"
        run.output.append(str(exc))
    except Exception as exc:
        run.status = "ERROR"
        run.output.append(f"{type(exc).__name__}: {exc}")
    return run

