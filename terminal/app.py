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


BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="ATLAS Terminal", version="0.1.0")
app.mount("/terminal/static", StaticFiles(directory=str(BASE_DIR / "static")), name="terminal-static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


class CommandRequest(BaseModel):
    command: str


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


@app.get("/terminal/api/commands/help")
@app.get("/api/commands/help")
async def commands_help():
    return {"status": "OK", "as_of": datetime.now(timezone.utc).isoformat(), "commands": command_help()}


@app.get("/terminal/health")
@app.get("/terminal/api/health")
@app.get("/api/health")
async def health():
    return JSONResponse(
        {
            "status": "BOOTSTRAP",
            "as_of": datetime.now(timezone.utc).isoformat(),
            "red_dot": True,
            "sources": [],
            "cron": [],
            "message": "Terminal layout is installed; source wiring lands in phase 6.",
        }
    )
