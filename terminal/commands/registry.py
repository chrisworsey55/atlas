from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandSpec:
    name: str
    description: str
    argv: tuple[str, ...] | None = None
    ui_action: str | None = None


COMMANDS: dict[str, CommandSpec] = {
    "/screen": CommandSpec("/screen TICKER", "Run the existing gauntlet for ticker"),
    "/cycle": CommandSpec("/cycle", "Run one agent execution cycle", ("python3", "-m", "agents.execution_loop", "--once")),
    "/briefing": CommandSpec("/briefing", "Generate morning briefing", ("python3", "-m", "agents.daily_briefing")),
    "/pnl": CommandSpec("/pnl", "Refresh prices and PnL", ("python3", "-m", "portfolio.performance")),
    "/status": CommandSpec("/status", "Show terminal health"),
    "/shannon": CommandSpec("/shannon", "Switch to SHANNON workspace", ui_action="F3"),
    "/janus": CommandSpec("/janus", "Switch to JANUS workspace", ui_action="F5"),
    "/backtest run": CommandSpec(
        "/backtest run",
        "Kick off a Darwin v2 generation",
        ("python3", "-m", "darwin_v2.equities_evolution"),
    ),
    "/trade": CommandSpec("/trade BUY|SELL TICKER QTY PRICE", "Record paper trade through existing journal path"),
    "/help": CommandSpec("/help", "List commands"),
}


def command_help() -> list[dict[str, str]]:
    return [{"command": spec.name, "description": spec.description} for spec in COMMANDS.values()]

