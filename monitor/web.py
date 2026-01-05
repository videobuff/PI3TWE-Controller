"""
File: monitor/web.py
Generated: 2026-01-04
Description: FastAPI webapp: dashboard + API endpoints.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from monitor.config import CONFIG
from monitor.db import db_stats, fetch_as_series, init_db

app = FastAPI(title="PI3TWE Monitor", version="1.0.0")

app.mount("/monitor/static", StaticFiles(directory="monitor/static"), name="monitor_static")
templates = Jinja2Templates(directory="monitor/templates")


@app.on_event("startup")
def _startup() -> None:
    init_db(CONFIG.db_path)


@app.get("/monitor", response_class=HTMLResponse)
def monitor_dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("monitor.html", {"request": request})


@app.get("/monitor/api/data", response_class=JSONResponse)
def monitor_api_data(hours: int = 24) -> JSONResponse:
    data = fetch_as_series(hours=hours, db_path=CONFIG.db_path)
    return JSONResponse(content=data)


@app.get("/monitor/api/health", response_class=JSONResponse)
def monitor_api_health() -> JSONResponse:
    return JSONResponse(content=db_stats(CONFIG.db_path))
