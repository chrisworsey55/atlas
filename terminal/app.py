from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from terminal.settings import settings


BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="ATLAS Terminal", version="0.1.0")
app.mount("/terminal/static", StaticFiles(directory=str(BASE_DIR / "static")), name="terminal-static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


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

