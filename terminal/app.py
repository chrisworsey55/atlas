from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from terminal.commands.registry import command_help
from terminal.commands.runner import RUNS, run_command
from terminal.settings import settings
from terminal.sources import core as sources


BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="ATLAS Terminal", version="0.1.0")
app.mount("/terminal/static", StaticFiles(directory=str(BASE_DIR / "static")), name="terminal-static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


class CommandRequest(BaseModel):
    command: str


async def source_call(func):
    import asyncio

    try:
        return await asyncio.wait_for(asyncio.to_thread(func), timeout=5)
    except TimeoutError:
        return sources.response("STALE_CACHE", None, {}, stale=True, reason="source read timed out after 5 seconds")
    except Exception as exc:
        return sources.response("ERROR", None, {}, stale=True, reason=f"{type(exc).__name__}: {exc}")


@app.get("/terminal", response_class=HTMLResponse)
async def terminal_home(request: Request):
    return templates.TemplateResponse(
        "terminal.html",
        {
            "request": request,
            "production": settings.production,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


@app.get("/terminal/api/header")
@app.get("/api/header")
async def header():
    portfolio = await source_call(sources.portfolio_summary)
    health_payload = await source_call(build_health)
    return {
        "status": "OK",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "production": settings.production,
        "snapshot": sources.snapshot_age(),
        "health": health_payload,
        "portfolio": portfolio,
    }


@app.post("/terminal/api/commands/run")
@app.post("/api/commands/run")
async def command_run(payload: CommandRequest):
    run = await run_command(payload.command)
    return JSONResponse(
        {
            "id": run.id,
            "command": run.command,
            "status": run.status,
            "created_at": run.created_at,
            "output": run.output,
            "ui_action": run.ui_action,
        }
    )


@app.get("/terminal/api/commands/status")
@app.get("/api/commands/status")
async def command_status():
    recent = list(RUNS.values())[-10:]
    return {
        "status": "OK",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "commands": [
            {"id": run.id, "command": run.command, "status": run.status, "created_at": run.created_at}
            for run in recent
        ],
    }


@app.get("/terminal/api/commands/help")
@app.get("/api/commands/help")
async def commands_help():
    return {"status": "OK", "as_of": datetime.now(timezone.utc).isoformat(), "commands": command_help()}


@app.get("/terminal/api/commands/{command_id}")
@app.get("/api/commands/{command_id}")
async def command_get(command_id: str):
    run = RUNS.get(command_id)
    if not run:
        return JSONResponse({"status": "NOT_FOUND", "reason": "command id not found"}, status_code=404)
    return {
        "id": run.id,
        "command": run.command,
        "status": run.status,
        "created_at": run.created_at,
        "output": run.output,
        "ui_action": run.ui_action,
    }


@app.get("/terminal/health")
@app.get("/terminal/api/health")
@app.get("/api/health")
async def health():
    return JSONResponse(await source_call(build_health))


def build_health():
    source_rows = sources.health_sources()
    cron_rows = sources.cron_status()
    red_dot = any(row.get("stale") or row.get("status") in {"MISSING", "NOT_WIRED"} for row in source_rows)
    return {
        "status": "DEGRADED" if red_dot else "OK",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "red_dot": red_dot,
        "sources": source_rows,
        "cron": cron_rows,
    }


ROUTES = {
    "portfolio/summary": sources.portfolio_summary,
    "portfolio/positions": sources.portfolio_positions,
    "portfolio/pnl": sources.portfolio_pnl,
    "portfolio/decisions": sources.portfolio_decisions,
    "portfolio/risk": sources.portfolio_risk,
    "agents/overview": sources.agents_overview,
    "agents/execution-log": sources.agents_execution_log,
    "agents/prompts": sources.agents_prompts,
    "kalshi/summary": sources.kalshi_summary,
    "kalshi/trades": sources.kalshi_trades,
    "kalshi/positions": sources.kalshi_positions,
    "shannon/status": sources.shannon_status,
    "shannon/queue": sources.shannon_queue,
    "shannon/items": sources.shannon_items,
    "shannon/scouts": sources.shannon_scouts,
    "intel/tracker": sources.intel_tracker,
    "intel/deadline": sources.intel_deadline,
    "intel/entities": sources.intel_entities,
    "intel/news": sources.intel_news,
    "simons/patterns": sources.simons_patterns,
    "simons/signals": sources.simons_signals,
    "simons/backtest": sources.simons_backtest,
    "backtest/darwin": sources.backtest_darwin,
    "backtest/fitness": sources.backtest_fitness,
    "backtest/equity": sources.backtest_equity,
    "backtest/ablations": sources.backtest_ablations,
    "janus/regime": sources.janus_regime,
    "janus/weights": sources.janus_weights,
    "janus/reweighting": sources.janus_reweighting,
}


@app.get("/terminal/api/{section}/{name}")
@app.get("/api/{section}/{name}")
async def source_endpoint(section: str, name: str):
    key = f"{section}/{name}"
    func = ROUTES.get(key)
    if not func:
        return JSONResponse({"status": "NOT_FOUND", "reason": f"unknown endpoint {key}"}, status_code=404)
    return JSONResponse(await source_call(func))
