# ======================================================
# File        : /srv/pi3twe/app/monitor/web.py
# Generated   : 2026-01-06 14:56 (Europe/Amsterdam)
# Description : PI3TWE Monitor Web (FastAPI)
#               - Dashboard: /monitor (en /monitor/)
#               - API (historisch): /monitor/api/data, /monitor/api/health
#               - API (live): /monitor/api/live  (INT/EXT direct sensors)
#               - HEAD support voor curl -I
# ======================================================

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from monitor.db import db_stats, fetch_as_series, init_db
from monitor.sensors import read_internal_bmp280, read_external_dht


app = FastAPI()

# Static + templates
app.mount("/monitor/static", StaticFiles(directory="monitor/static"), name="monitor_static")
templates = Jinja2Templates(directory="monitor/templates")


# ======================================================
# Monitor dashboard (HTML)
# ======================================================
@app.get("/monitor", response_class=HTMLResponse)
def monitor_dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("monitor.html", {"request": request})


@app.get("/monitor/", response_class=HTMLResponse)
def monitor_dashboard_slash(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("monitor.html", {"request": request})


@app.head("/monitor")
def monitor_dashboard_head() -> Response:
    return Response(status_code=200)


@app.head("/monitor/")
def monitor_dashboard_slash_head() -> Response:
    return Response(status_code=200)


# ======================================================
# Health (JSON) - historisch/db
# ======================================================
def _health_payload() -> dict:
    init_db()
    return db_stats()


@app.get("/monitor/api/health", response_class=JSONResponse)
def monitor_api_health() -> JSONResponse:
    try:
        return JSONResponse(_health_payload())
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/monitor/api/health/", response_class=JSONResponse)
def monitor_api_health_slash() -> JSONResponse:
    try:
        return JSONResponse(_health_payload())
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.head("/monitor/api/health")
def monitor_api_health_head() -> Response:
    return Response(status_code=200)


@app.head("/monitor/api/health/")
def monitor_api_health_slash_head() -> Response:
    return Response(status_code=200)


# ======================================================
# Data (JSON) - historisch/db
# ======================================================
@app.get("/monitor/api/data", response_class=JSONResponse)
def monitor_api_data(hours: int = 24) -> JSONResponse:
    init_db()
    return JSONResponse(fetch_as_series(hours=hours))


@app.get("/monitor/api/data/", response_class=JSONResponse)
def monitor_api_data_slash(hours: int = 24) -> JSONResponse:
    init_db()
    return JSONResponse(fetch_as_series(hours=hours))


# ======================================================
# Live (JSON) - direct sensors (INT/EXT), geen DB
# ======================================================
def _live_payload() -> dict:
    """
    Live uitlezing van sensors.
    Let op: als BMP280/DHT libs/hardware ontbreken, geven sensors.py functies None terug.
    """
    it = read_internal_bmp280()
    ex = read_external_dht()

    return {
        "ok": True,
        "int": {"temp": it.temp, "hum": it.hum},
        "ext": {"temp": ex.temp, "hum": ex.hum},
    }


@app.get("/monitor/api/live", response_class=JSONResponse)
def monitor_api_live() -> JSONResponse:
    try:
        return JSONResponse(_live_payload())
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/monitor/api/live/", response_class=JSONResponse)
def monitor_api_live_slash() -> JSONResponse:
    try:
        return JSONResponse(_live_payload())
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.head("/monitor/api/live")
def monitor_api_live_head() -> Response:
    return Response(status_code=200)


@app.head("/monitor/api/live/")
def monitor_api_live_slash_head() -> Response:
    return Response(status_code=200)

# ======================================================
# Live dashboard (HTML) - INT/EXT live, geen DB
# ======================================================
@app.get("/monitor/live", response_class=HTMLResponse)
def monitor_live_dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("monitor_live.html", {"request": request})


@app.get("/monitor/live/", response_class=HTMLResponse)
def monitor_live_dashboard_slash(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("monitor_live.html", {"request": request})


@app.head("/monitor/live")
def monitor_live_dashboard_head() -> Response:
    return Response(status_code=200)


@app.head("/monitor/live/")
def monitor_live_dashboard_slash_head() -> Response:
    return Response(status_code=200)