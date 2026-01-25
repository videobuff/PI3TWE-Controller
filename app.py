#!/usr/bin/env python3
# ======================================================
# File: /srv/pi3twe/app/app.py
# DATUM_TIJD_APP_GENEREREN = "2026-01-25 13:00 (Europe/Amsterdam)"
# Description: PI3TWE Controller backend
#  - SQLite users + audit log + settings
#  - Login (ident OR username OR email), sessions
#  - 2FA (TOTP)
#  - Admin: users list/create/deactivate/activate + SUPERADMIN: hard delete (purge)
#  - Repeater control + cooldown
#  - Hardware pushbutton (GPIO23 active-low) toggles repeater with debounce + respects cooldown
#  - LAN/WAN + monitor.db (cpu/int/ext) + band
#  - Fail2ban status endpoint
#  - JSON errors (no HTML error pages for API)
#  - New user: email temp password via msmtp (config in secrets)
#  - Boot/selftest mail via msmtp to INTERNAL_MAIL_TO (for reboot/crash visibility)
#  - Prepared: INT/EXT temperature alarms > 50C (with hysteresis + anti-spam)
#
# Added (requested, without changing existing behaviour/UI except values):
#  - DHT11 support for INT/EXT (safe: missing sensor => temp="xx.x", hum="xx" in /api/state)
#  - monitor.db logging now writes CPU temp+load% and DHT INT/EXT temp+hum + load averages
#  - Prometheus metrics endpoint (/metrics) in parallel (optional; runs if prometheus_client installed)
#  - InfluxDB 3 Core support: dual-write to SQLite AND InfluxDB for Grafana stability
#
# Notes:
#  - /api/admin/users/<id>/delete is kept as BACKWARD COMPAT alias for "deactivate"
#    because the current UI calls /delete.
#  - /api/admin/users/<id>/purge is HARD delete (weg = weg). It NULLs audit_log.user_id first.
# ======================================================

from zoneinfo import ZoneInfo
from flask import Flask, jsonify, request, abort, session, has_request_context
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash
import sqlite3
import os
import time
from datetime import datetime
import secrets
import pyotp
import qrcode
import io
import base64
import subprocess
import socket
import re
import atexit
import threading
import queue
from typing import Optional, Dict, Any, Tuple

import RPi.GPIO as GPIO

# ---------------------
# Optional: DHT11 (adafruit)
# ---------------------
try:
    import board  # type: ignore
    import adafruit_dht  # type: ignore
except Exception:
    board = None
    adafruit_dht = None

# ---------------------
# Optional: Prometheus
# ---------------------
try:
    from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST  # type: ignore
    _PROM_OK = True
except Exception:
    Gauge = None
    generate_latest = None
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4"
    _PROM_OK = False

# ---------------------
# Optional: InfluxDB 3 (via HTTP line protocol)
# ---------------------
import urllib.request
import urllib.error

INFLUXDB_ENABLED = os.environ.get("PI3TWE_INFLUXDB_ENABLED", "1") == "1"
INFLUXDB_URL = os.environ.get("PI3TWE_INFLUXDB_URL", "http://127.0.0.1:8181")
INFLUXDB_DATABASE = os.environ.get("PI3TWE_INFLUXDB_DATABASE", "pi3twe")

# Token from environment or secrets file (never hardcode!)
def _load_influxdb_token():
    token = os.environ.get("PI3TWE_INFLUXDB_TOKEN")
    if token:
        return token
    token_file = "/srv/pi3twe/app/secrets/influxdb_token.txt"
    try:
        with open(token_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""

INFLUXDB_TOKEN = _load_influxdb_token()

# Set to "0" to disable SQLite monitor writes (InfluxDB only)
SQLITE_MONITOR_ENABLED = os.environ.get("PI3TWE_SQLITE_MONITOR_ENABLED", "0") == "1"

# ---------------------
# Config
# ---------------------
DB_PATH = "/srv/pi3twe/app/pi3twe.db"
MONITOR_DB_PATH = "/srv/pi3twe/data/monitor.db"
MONITOR_LOG_INTERVAL_S = 60.0

SRC_CPU = "cpu"
SRC_INT = "int"
SRC_EXT = "ext"
SRC_LOAD1 = "load1"
SRC_LOAD5 = "load5"
SRC_LOAD15 = "load15"

# GPIO mapping (BCM)
RELAY_GPIO = 27          # SSR active HIGH = AAN
BUTTON_GPIO = 23         # Pushbutton active LOW naar GND (physical pin 16)

# DHT GPIOs (BCM) – afgestemd op bewezen werkende test
# - BCM26 = physical pin 37  (INT)
# - BCM20 = physical pin 38  (EXT)
# physical pin 7 (GPIO4) wordt NIET gebruikt
DHT_INT_GPIO = int(os.environ.get("PI3TWE_DHT_INT_GPIO", "26"))
DHT_EXT_GPIO = int(os.environ.get("PI3TWE_DHT_EXT_GPIO", "20"))
# Debounce
BUTTON_BOUNCE_MS = 150       # RPi.GPIO bouncetime
BUTTON_MIN_INTERVAL_MS = 300 # extra software guard (anti-double trigger)

COOLDOWN_SECONDS = 30

DEFAULT_ALARM_ENABLED = True
DEFAULT_ALARM_TRIP_C = 55.0
DEFAULT_ALARM_CLEAR_C = 43.0

# Prepared: temperature alarms for INT/EXT
DEFAULT_TEMP_ALERT_ENABLED = True
DEFAULT_TEMP_INT_TRIP_C = 50.0
DEFAULT_TEMP_INT_CLEAR_C = 48.0
DEFAULT_TEMP_EXT_TRIP_C = 50.0
DEFAULT_TEMP_EXT_CLEAR_C = 48.0
DEFAULT_TEMP_ALERT_MIN_INTERVAL_SECONDS = 900  # 15 minutes anti-spam

# WAN lookup
WAN_LOOKUP_URL = "https://api.ipify.org"
WAN_CACHE_SECONDS = 60
_WAN_CACHE = {"ip": "", "ts": 0.0}

# msmtp (config in secrets)
MSMTP_BIN = "/usr/bin/msmtp"
MSMTP_CONF = "/srv/pi3twe/app/secrets/msmtprc"
MAIL_FROM = "no-reply@pi3twe.nl"
INTERNAL_MAIL_TO = "info@pi3twe.nl"
MAIL_HEADER_IMAGE_PATH = "/srv/pi3twe/app/img/storingsmelding_pi3twe.jpg"
MAIL_HEADER_IMAGE_CID = "pi3twe_header"

# Persist secret so sessions survive service restarts
APP_SECRET_FILE = "/srv/pi3twe/app/secrets/flask_secret.key"

# Internal monitor thread
_MONITOR_THREAD: Optional[threading.Thread] = None
_MONITOR_STOP = threading.Event()

# ---------------------
# Helpers
# ---------------------
def utc_ts() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")


def read_uptime_seconds() -> Optional[int]:
    try:
        with open("/proc/uptime", "r", encoding="utf-8") as f:
            txt = f.read().strip().split()
        if not txt:
            return None
        return int(float(txt[0]))
    except Exception:
        return None


def format_uptime(secs: Optional[int]) -> str:
    if secs is None or secs < 0:
        return "—"
    days = secs // 86400
    rem = secs % 86400
    h = rem // 3600
    rem %= 3600
    m = rem // 60
    s = rem % 60
    if days > 0:
        return f"{days}d {h:02d}:{m:02d}:{s:02d}"
    return f"{h:02d}:{m:02d}:{s:02d}"


def ensure_parent_dir(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


def load_or_create_secret() -> str:
    ensure_parent_dir(APP_SECRET_FILE)
    if os.path.exists(APP_SECRET_FILE):
        try:
            with open(APP_SECRET_FILE, "r", encoding="utf-8") as f:
                s = f.read().strip()
                if s:
                    return s
        except Exception:
            pass

    s = secrets.token_hex(32)
    try:
        with open(APP_SECRET_FILE, "w", encoding="utf-8") as f:
            f.write(s + "\n")
        try:
            os.chmod(APP_SECRET_FILE, 0o640)
        except Exception:
            pass
    except Exception:
        return secrets.token_hex(32)
    return s


def client_ip() -> str:
    if not has_request_context():
        return "-"
    ip = request.remote_addr
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        ip = xff.split(",")[0].strip()
    return ip or "-"


def current_user_id():
    return session.get("uid")


def _run_cmd(cmd, timeout=2) -> str:
    try:
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
            text=True,
        )
        out = (p.stdout or "").strip()
        if out:
            return out
        return (p.stderr or "").strip()
    except Exception:
        return ""


def _b64_lines(data: bytes, width: int = 76) -> str:
    s = base64.b64encode(data).decode("ascii")
    return "\n".join(s[i:i + width] for i in range(0, len(s), width))


def _html_escape(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------
# CPU temperature read (no external monitor needed)
# ---------------------
def read_cpu_temp_c() -> Optional[float]:
    # Raspberry Pi typical path
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r", encoding="utf-8") as f:
            raw = f.read().strip()
        if not raw:
            return None
        v = float(raw)
        if v > 1000.0:
            v = v / 1000.0
        return round(v, 1)
    except Exception:
        return None


# ---------------------
# DHT11 logic (safe: missing => placeholders)
# ---------------------
_DHT_INT = None
_DHT_EXT = None

_DHT_CACHE_LOCK = threading.Lock()
_DHT_CACHE = {
    "t": 0.0,
    "int": {"temp": "xx.x", "hum": "xx"},
    "ext": {"temp": "xx.x", "hum": "xx"},
}
_DHT_MIN_INTERVAL_S = 2.0  # avoid hammering DHT11


def _bcm_to_board_pin(bcm: int):
    # board.Dxx is present for most BCM pins on Raspberry Pi
    if board is None:
        return None
    attr = f"D{int(bcm)}"
    return getattr(board, attr, None)


def dht_init_once() -> None:
    global _DHT_INT, _DHT_EXT
    if adafruit_dht is None or board is None:
        return
    if _DHT_INT is None:
        bp = _bcm_to_board_pin(DHT_INT_GPIO)
        if bp is not None:
            try:
                _DHT_INT = adafruit_dht.DHT11(bp)
            except Exception:
                _DHT_INT = None
    if _DHT_EXT is None:
        bp = _bcm_to_board_pin(DHT_EXT_GPIO)
        if bp is not None:
            try:
                _DHT_EXT = adafruit_dht.DHT11(bp)
            except Exception:
                _DHT_EXT = None


def read_dht_safe(dht_device) -> Dict[str, Any]:
    """
    Returns always:
      {"temp": float(1dp) or "xx.x", "hum": int(0dp) or "xx"}
    """
    try:
        if dht_device is None:
            raise RuntimeError("no device")
        temp = dht_device.temperature
        hum = dht_device.humidity
        if temp is None or hum is None:
            raise RuntimeError("no data")
        return {
            "temp": round(float(temp), 1),
            "hum": int(round(float(hum), 0)),
        }
    except Exception:
        return {"temp": "xx.x", "hum": "xx"}


def _dht_to_db_values(v: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    """
    Convert cached DHT reading to DB numeric values (REAL/NULL).
    hum is stored as REAL too; we store integer as float (Grafana ok) or NULL.
    """
    t = v.get("temp")
    h = v.get("hum")
    temp_f: Optional[float] = None
    hum_f: Optional[float] = None
    try:
        if isinstance(t, (int, float)):
            temp_f = float(t)
    except Exception:
        temp_f = None
    try:
        if isinstance(h, (int, float)):
            hum_f = float(h)
    except Exception:
        hum_f = None
    return temp_f, hum_f


# ---------------------
# Prometheus metrics (optional)
# ---------------------
if _PROM_OK:
    PROM_CPU_TEMP_C = Gauge("pi3twe_cpu_temp_c", "CPU temperature (C)")
    PROM_CPU_LOAD_PCT = Gauge("pi3twe_cpu_load_pct", "CPU load percentage (0..100)")
    PROM_LOADAVG_1 = Gauge("pi3twe_loadavg_1", "Load average 1m")
    PROM_LOADAVG_5 = Gauge("pi3twe_loadavg_5", "Load average 5m")
    PROM_LOADAVG_15 = Gauge("pi3twe_loadavg_15", "Load average 15m")

    PROM_DHT_TEMP_C = Gauge("pi3twe_dht_temp_c", "DHT temperature (C)", ["where"])
    PROM_DHT_HUM_PCT = Gauge("pi3twe_dht_hum_pct", "DHT humidity (%)", ["where"])
    PROM_DHT_OK = Gauge("pi3twe_dht_ok", "DHT sensor OK (1=ok,0=missing/error)", ["where"])


def prom_set_dht(where: str, v: Dict[str, Any]) -> None:
    if not _PROM_OK:
        return
    t = v.get("temp")
    h = v.get("hum")
    if isinstance(t, (int, float)) and isinstance(h, (int, float)):
        PROM_DHT_OK.labels(where=where).set(1)
        PROM_DHT_TEMP_C.labels(where=where).set(float(t))
        PROM_DHT_HUM_PCT.labels(where=where).set(float(h))
    else:
        PROM_DHT_OK.labels(where=where).set(0)
        # keep last numeric values; do not force to 0 (would look like real data)
        # so: do nothing for TEMP/HUM when missing


# ---------------------
# Monitor DB logging (in-app)
# ---------------------
_MONITOR_DB_LOCK = threading.Lock()
_MONITOR_DB_THREAD: Optional[threading.Thread] = None
_MONITOR_DB_STOP = threading.Event()


def monitor_db_ensure_tables() -> None:
    try:
        os.makedirs(os.path.dirname(MONITOR_DB_PATH), exist_ok=True)
        with sqlite3.connect(MONITOR_DB_PATH) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout = 10000;")
            conn.execute("PRAGMA busy_timeout = 10000;")  # ← DEZE REGEL TOEVOEGEN
            conn.execute("""
                CREATE TABLE IF NOT EXISTS measurements (
                    ts     INTEGER NOT NULL,
                    source TEXT    NOT NULL,
                    temp   REAL,
                    hum    REAL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_measurements_src_ts ON measurements(source, ts)")
            conn.commit()
    except Exception:
        pass


# ---------------------
# InfluxDB 3 write (line protocol over HTTP)
# ---------------------
def influxdb_write(measurement: str, tags: Dict[str, str], fields: Dict[str, Any], timestamp_ns: Optional[int] = None) -> bool:
    """
    Write a single point to InfluxDB 3 using line protocol.
    Returns True on success, False on failure.
    All numeric values are written as floats for consistency.
    """
    if not INFLUXDB_ENABLED:
        return False
    
    try:
        # Build line protocol: measurement,tag1=val1,tag2=val2 field1=val1,field2=val2 timestamp
        tag_str = ",".join(f"{k}={v}" for k, v in tags.items()) if tags else ""
        field_parts = []
        for k, v in fields.items():
            if v is None:
                continue
            if isinstance(v, bool):
                field_parts.append(f"{k}={str(v).lower()}")
            elif isinstance(v, (int, float)):
                # Always write as float to avoid type conflicts
                field_parts.append(f"{k}={float(v)}")
            elif isinstance(v, str):
                field_parts.append(f'{k}="{v}"')
            else:
                field_parts.append(f"{k}={v}")
        
        if not field_parts:
            return False
        
        field_str = ",".join(field_parts)
        
        if tag_str:
            line = f"{measurement},{tag_str} {field_str}"
        else:
            line = f"{measurement} {field_str}"
        
        if timestamp_ns:
            line += f" {timestamp_ns}"
        
        # Send to InfluxDB
        url = f"{INFLUXDB_URL}/api/v3/write_lp?db={INFLUXDB_DATABASE}"
        data = line.encode("utf-8")
        
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "text/plain; charset=utf-8",
                "Authorization": f"Bearer {INFLUXDB_TOKEN}",
            }
        )
        
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return resp.status in (200, 204)
    
    except Exception:
        return False


def influxdb_write_measurement(ts: int, source: str, temp, hum) -> bool:
    """
    Write a measurement to InfluxDB, matching the SQLite schema.
    Rounds values appropriately:
    - temp: 1 decimal place
    - hum (int/ext): integer (0 decimals) for humidity percentage
    - hum (cpu): 1 decimal for CPU load percentage
    - temp (load1/load5/load15): 2 decimals for load averages
    """
    fields = {}
    
    if temp is not None:
        if source in (SRC_LOAD1, SRC_LOAD5, SRC_LOAD15):
            # Load averages: 2 decimals
            fields["temp"] = round(float(temp), 2)
        else:
            # Temperature: 1 decimal
            fields["temp"] = round(float(temp), 1)
    
    if hum is not None:
        if source in (SRC_INT, SRC_EXT):
            # Humidity: integer
            fields["hum"] = int(round(float(hum), 0))
        else:
            # CPU load percentage: 1 decimal
            fields["hum"] = round(float(hum), 1)
    
    if not fields:
        return False
    
    # Convert unix timestamp (seconds) to nanoseconds
    timestamp_ns = int(ts) * 1_000_000_000
    
    return influxdb_write(
        measurement="measurements",
        tags={"source": source},
        fields=fields,
        timestamp_ns=timestamp_ns
    )


def monitor_db_insert(ts: int, source: str, temp, hum) -> None:
    """
    Insert measurement into SQLite AND/OR InfluxDB.
    Controlled by SQLITE_MONITOR_ENABLED and INFLUXDB_ENABLED.
    """
    # SQLite write (if enabled)
    if SQLITE_MONITOR_ENABLED:
        try:
            with _MONITOR_DB_LOCK:
                with sqlite3.connect(MONITOR_DB_PATH) as conn:
                    conn.execute("PRAGMA busy_timeout = 5000;")
                    conn.execute(
                        "INSERT INTO measurements(ts, source, temp, hum) VALUES(?,?,?,?)",
                        (int(ts), str(source), temp, hum),
                    )
                    conn.commit()
        except Exception:
            pass
    
    # InfluxDB write (if enabled)
    if INFLUXDB_ENABLED:
        try:
            influxdb_write_measurement(ts, source, temp, hum)
        except Exception:
            pass


def _read_load_averages():
    # /proc/loadavg: 1m 5m 15m ...
    try:
        with open("/proc/loadavg", "r", encoding="utf-8") as f:
            parts = f.read().strip().split()
        if len(parts) >= 3:
            return float(parts[0]), float(parts[1]), float(parts[2])
    except Exception:
        pass
    return None, None, None


def read_dht_cached() -> Dict[str, Any]:
    """
    Read DHT sensors with caching to avoid hammering them.
    Returns cached values if called too frequently.
    """
    global _DHT_CACHE
    
    with _DHT_CACHE_LOCK:
        now = time.time()
        
        # Return cached if too recent
        if (now - _DHT_CACHE["t"]) < _DHT_MIN_INTERVAL_S:
            return {
                "int": _DHT_CACHE["int"].copy(),
                "ext": _DHT_CACHE["ext"].copy(),
            }
        
        # Read fresh values
        int_data = read_dht_safe(_DHT_INT)
        ext_data = read_dht_safe(_DHT_EXT)
        
        # Update cache
        _DHT_CACHE["t"] = now
        _DHT_CACHE["int"] = int_data
        _DHT_CACHE["ext"] = ext_data
        
        return {
            "int": int_data.copy(),
            "ext": ext_data.copy(),
        }



def _monitor_db_loop() -> None:
    monitor_db_ensure_tables()
    dht_init_once()

    while not _MONITOR_DB_STOP.is_set():
        try:
            ts = int(time.time())

            # CPU
            cpu_temp = read_cpu_temp_c()
            cpu_load_pct = cpu_load_percent_cached()

            if _PROM_OK:
                if cpu_temp is not None:
                    PROM_CPU_TEMP_C.set(float(cpu_temp))
                if cpu_load_pct is not None:
                    PROM_CPU_LOAD_PCT.set(float(cpu_load_pct))

            if cpu_temp is not None or cpu_load_pct is not None:
                monitor_db_insert(
                    ts,
                    SRC_CPU,
                    float(cpu_temp) if cpu_temp is not None else None,
                    float(cpu_load_pct) if cpu_load_pct is not None else None,
                )

            # DHT (INT/EXT)
            d = read_dht_cached()
            int_temp, int_hum = _dht_to_db_values(d["int"])
            ext_temp, ext_hum = _dht_to_db_values(d["ext"])

            monitor_db_insert(ts, SRC_INT, int_temp, int_hum)
            monitor_db_insert(ts, SRC_EXT, ext_temp, ext_hum)

            if _PROM_OK:
                prom_set_dht("int", d["int"])
                prom_set_dht("ext", d["ext"])

            # Load averages as separate sources
            l1, l5, l15 = _read_load_averages()
            if l1 is not None:
                monitor_db_insert(ts, SRC_LOAD1, float(l1), None)
                if _PROM_OK:
                    PROM_LOADAVG_1.set(float(l1))
            if l5 is not None:
                monitor_db_insert(ts, SRC_LOAD5, float(l5), None)
                if _PROM_OK:
                    PROM_LOADAVG_5.set(float(l5))
            if l15 is not None:
                monitor_db_insert(ts, SRC_LOAD15, float(l15), None)
                if _PROM_OK:
                    PROM_LOADAVG_15.set(float(l15))

        except Exception:
            pass

        _MONITOR_DB_STOP.wait(MONITOR_LOG_INTERVAL_S)


def start_monitor_db_logger_once() -> None:
    global _MONITOR_DB_THREAD
    if _MONITOR_DB_THREAD is not None and _MONITOR_DB_THREAD.is_alive():
        return
    _MONITOR_DB_STOP.clear()
    _MONITOR_DB_THREAD = threading.Thread(
        target=_monitor_db_loop,
        name="monitor-db-logger",
        daemon=True
    )
    _MONITOR_DB_THREAD.start()


# ---------------------
# Mail helpers
# ---------------------
def _build_mime_message(
    to_addr: str,
    subject: str,
    text_body: str,
    html_body: str,
    inline_image_path: Optional[str] = None,
    inline_image_cid: Optional[str] = None,
) -> str:
    boundary_rel = "PI3TWE_REL_9b1c2d7f"
    boundary_alt = "PI3TWE_ALT_a18e44c3"

    has_inline = bool(inline_image_path and inline_image_cid and os.path.exists(inline_image_path))

    headers = [
        f"From: {MAIL_FROM}",
        f"To: {to_addr}",
        f"Subject: {subject}",
        "MIME-Version: 1.0",
    ]

    if has_inline:
        headers.append(f'Content-Type: multipart/related; boundary="{boundary_rel}"')
    else:
        headers.append(f'Content-Type: multipart/alternative; boundary="{boundary_alt}"')

    msg = "\n".join(headers) + "\n\n"

    if has_inline:
        msg += f"--{boundary_rel}\n"
        msg += f'Content-Type: multipart/alternative; boundary="{boundary_alt}"\n\n'

    # plain
    msg += f"--{boundary_alt}\n"
    msg += "Content-Type: text/plain; charset=utf-8\n"
    msg += "Content-Transfer-Encoding: 8bit\n\n"
    msg += (text_body or "").rstrip() + "\n\n"

    # html
    msg += f"--{boundary_alt}\n"
    msg += "Content-Type: text/html; charset=utf-8\n"
    msg += "Content-Transfer-Encoding: 8bit\n\n"
    msg += (html_body or "").rstrip() + "\n\n"

    msg += f"--{boundary_alt}--\n"

    if has_inline:
        try:
            with open(inline_image_path, "rb") as f:
                img_bytes = f.read()
            img_b64 = _b64_lines(img_bytes)

            msg += f"\n--{boundary_rel}\n"
            msg += "Content-Type: image/jpeg\n"
            msg += "Content-Transfer-Encoding: base64\n"
            msg += f"Content-ID: <{inline_image_cid}>\n"
            msg += 'Content-Disposition: inline; filename="storingsmelding_pi3twe.jpg"\n\n'
            msg += img_b64 + "\n"
            msg += f"--{boundary_rel}--\n"
        except Exception:
            msg += f"\n--{boundary_rel}--\n"

    return msg


def send_mail(to_addr: str, subject: str, body_text: str, body_html: str) -> None:
    """
    HTML + text mail via msmtp (using MSMTP_CONF) with optional inline header image.
    Failures are logged in audit_log but do not hard-fail the API call.
    """
    if not os.path.exists(MSMTP_BIN):
        audit("MAIL_FAIL", current_user_id(), f"msmtp binary ontbreekt: {MSMTP_BIN}")
        return
    if not os.path.exists(MSMTP_CONF):
        audit("MAIL_FAIL", current_user_id(), f"msmtprc ontbreekt: {MSMTP_CONF}")
        return

    msg = _build_mime_message(
        to_addr=to_addr,
        subject=subject,
        text_body=body_text,
        html_body=body_html,
        inline_image_path=MAIL_HEADER_IMAGE_PATH,
        inline_image_cid=MAIL_HEADER_IMAGE_CID,
    )

    try:
        p = subprocess.run(
            [MSMTP_BIN, "-C", MSMTP_CONF, "-t"],
            input=msg.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
            check=False,
        )
        if p.returncode != 0:
            audit("MAIL_FAIL", current_user_id(), (p.stderr.decode("utf-8", errors="replace") or "")[:500])
    except Exception as e:
        audit("MAIL_FAIL", current_user_id(), f"{type(e).__name__}: {e}")


def _status_reason_from_event(event: str, details: str) -> str:
    e = (event or "").strip()
    d = (details or "").strip()

    mapping = {
        "BOOT_INIT_OK": "Reboot / startup (Gunicorn import)",
        "BOOT_INIT_FAIL": "Startup fout (Gunicorn import)",
        "MAIL_SELFTEST_OK": "Startup selftest",
        "MAIL_SELFTEST_FAIL": "Startup selftest fout",
        "REPEATER_TOGGLE": "Repeater status change (button/system)",
        "REPEATER_TOGGLE_IGNORED": "Repeater toggle genegeerd (cooldown)",
        "TEMP_ALARM_INT_HIGH": "Alarm: INT temperatuur te hoog",
        "TEMP_ALARM_INT_CLEAR": "Alarm: INT temperatuur weer normaal",
        "TEMP_ALARM_EXT_HIGH": "Alarm: EXT temperatuur te hoog",
        "TEMP_ALARM_EXT_CLEAR": "Alarm: EXT temperatuur weer normaal",
    }
    if e in mapping:
        return mapping[e] if not d else f"{mapping[e]} — {d}"
    return d or e or "Onbekend"


def _make_status_mail(ts_utc: str, event: str, details: str) -> Dict[str, str]:
    """
    Build subject + plain + html for internal status/alarm mails.
    """
    # --- UTC parsing ---
    try:
        dt_utc = datetime.strptime(ts_utc.replace(" UTC", ""), "%Y-%m-%d %H:%M:%S")
    except Exception:
        dt_utc = datetime.utcnow()

    # --- Formats ---
    date_utc_str = dt_utc.strftime("%d-%m-%Y")
    time_utc_str = dt_utc.strftime("%H:%M:%S")

    # --- NL time ---
    dt_nl = dt_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("Europe/Amsterdam"))
    date_nl_str = dt_nl.strftime("%d-%m-%Y")
    time_nl_str = dt_nl.strftime("%H:%M")
    tz_nl = dt_nl.tzname()  # CET / CEST

    reason = _status_reason_from_event(event, details)
    subject = "Melding status change PI3TWE"

    # ---------- TEXT ----------
    text = (
        f"Datum      : {date_utc_str}\n"
        f"Tijd UTC   : {time_utc_str}\n"
        f"Reden      : {reason}\n"
        f"Event      : {event}\n"
    )

    # ---------- HTML ----------
    header_img_html = ""
    if os.path.exists(MAIL_HEADER_IMAGE_PATH):
        header_img_html = (
            f"<div style='margin:0 0 14px 0;'>"
            f"<img src='cid:{MAIL_HEADER_IMAGE_CID}' alt='PI3TWE' "
            f"style='max-width:100%;height:auto;border-radius:10px;display:block;'>"
            f"</div>"
        )

    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_html_escape(subject)}</title>
</head>
<body style="margin:0;padding:0;background:#f4f6f8;">
<div style="max-width:640px;margin:0 auto;padding:18px;">
  <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:14px;
              box-shadow:0 6px 18px rgba(0,0,0,0.06);">
    <div style="padding:18px;">
      {header_img_html}

      <div style="font-family:Arial,Helvetica,sans-serif;">
        <div style="font-size:18px;font-weight:700;color:#111827;margin-bottom:6px;">
          {_html_escape(subject)}
        </div>

        <div style="font-size:13px;color:#6b7280;margin-bottom:14px;">
          Automatische melding van PI3TWE controller
        </div>

        <table style="width:100%;border-collapse:separate;border-spacing:0 8px;font-size:14px;">
          <tr>
            <td style="width:120px;font-weight:600;color:#374151;">Datum</td>
            <td>{date_utc_str}</td>
          </tr>
          <tr>
            <td style="font-weight:600;color:#374151;">Tijd UTC</td>
            <td>{time_utc_str}</td>
          </tr>
          <tr>
            <td style="font-weight:600;color:#374151;">Reden</td>
            <td>{_html_escape(reason)}</td>
          </tr>
          <tr>
            <td style="font-weight:600;color:#374151;">Event</td>
            <td>{_html_escape(event)}</td>
          </tr>
        </table>

        <div style="margin-top:18px;padding-top:12px;border-top:1px solid #e5e7eb;
                    font-size:12px;color:#6b7280;">
          PI3TWE Controller • {date_nl_str} {time_nl_str} {tz_nl}
        </div>
      </div>
    </div>
  </div>
</div>
</body>
</html>
"""
    return {"subject": subject, "text": text, "html": html}


def _send_internal_status_mail(ts_utc: str, event: str, details: str) -> None:
    mail = _make_status_mail(ts_utc, event, details)
    send_mail(INTERNAL_MAIL_TO, mail["subject"], mail["text"], mail["html"])


def get_lan_ip() -> str:
    """
    Best-effort LAN IP.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        pass

    try:
        out = _run_cmd(["hostname", "-I"], timeout=1)
        if out:
            parts = [p.strip() for p in out.split() if p.strip()]
            for p in parts:
                if re.match(r"^\d+\.\d+\.\d+\.\d+$", p):
                    return p
    except Exception:
        pass
    return ""


def get_wan_ip() -> str:
    now = time.time()
    if _WAN_CACHE["ip"] and (now - _WAN_CACHE["ts"]) < WAN_CACHE_SECONDS:
        return _WAN_CACHE["ip"]

    out = _run_cmd(["curl", "-sS", "--max-time", "2", WAN_LOOKUP_URL], timeout=3).strip()
    if out and len(out) < 64:
        _WAN_CACHE["ip"] = out
        _WAN_CACHE["ts"] = now
        return out
    return _WAN_CACHE["ip"] or ""


def read_monitor_latest(source: str):
    """
    Leest de laatste meting uit monitor.db voor een gegeven source.

    Tabel:
      measurements(
        ts     INTEGER,
        source TEXT,
        temp   REAL,
        hum    REAL
      )

    Regels:
      - Bestaat monitor.db niet → return None
      - Geen records voor deze source → return None
      - temp:
          * altijd 1 decimaal (float) of None
      - hum:
          * source == 'int' of 'ext' → integer (0 decimalen) of None
          * overige sources (bv cpu/load) → 1 decimaal of None
    """
    if not os.path.exists(MONITOR_DB_PATH):
        return None

    try:
        conn = sqlite3.connect(MONITOR_DB_PATH)
        conn.row_factory = sqlite3.Row

        row = conn.execute(
            """
            SELECT ts, temp, hum
            FROM measurements
            WHERE source = ?
            ORDER BY ts DESC
            LIMIT 1
            """,
            (source,),
        ).fetchone()

        conn.close()

        if row is None:
            return None

        # --- temp ---
        if row["temp"] is None:
            temp_out = None
        else:
            temp_out = round(float(row["temp"]), 1)

        # --- hum ---
        if row["hum"] is None:
            hum_out = None
        else:
            if source in ("int", "ext"):
                # DHT: humidity altijd 0 decimalen
                hum_out = int(round(float(row["hum"]), 0))
            else:
                # cpu/load/etc
                hum_out = round(float(row["hum"]), 1)

        return {
            "ts": row["ts"],
            "temp": temp_out,
            "hum": hum_out,
        }

    except Exception:
        return None


def fail2ban_status():
    """
    Returns {"total": int|None, "jails": {name:int}, "error"?: str}
    Uses sudo (NOPASSWD) because fail2ban socket is root-only.
    """
    SUDO = "/usr/bin/sudo"
    F2B = "/usr/bin/fail2ban-client"

    def run(args, timeout=2):
        try:
            p = subprocess.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
                check=False,
            )
            out = (p.stdout or "").strip()
            err = (p.stderr or "").strip()
            return p.returncode, out, err
        except Exception as e:
            return 999, "", f"{type(e).__name__}: {e}"

    rc, out, err = run([SUDO, "-n", F2B, "status"], timeout=2)
    if rc != 0:
        msg = err or out or f"fail2ban status rc={rc}"
        return {"total": None, "jails": {}, "error": msg[:300]}

    jails = []
    for line in out.splitlines():
        if "Jail list:" in line:
            part = line.split("Jail list:", 1)[1].strip()
            if part:
                jails = [x.strip() for x in part.split(",") if x.strip()]
            break

    counts = {}
    total = 0

    for jail in jails:
        rc2, out2, err2 = run([SUDO, "-n", F2B, "status", jail], timeout=2)
        if rc2 != 0 or not out2:
            continue

        banned = None
        for ln in out2.splitlines():
            if "Currently banned:" in ln:
                try:
                    banned = int(ln.split("Currently banned:", 1)[1].strip())
                except Exception:
                    banned = None
                break

        if banned is None:
            continue

        counts[jail] = banned
        total += banned

    return {"total": total, "jails": counts}


# ---------------------
# Flask
# ---------------------
app = Flask(__name__)
app.secret_key = load_or_create_secret()
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

# ---------------------
# GPIO + state
# ---------------------
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)

GPIO.setup(RELAY_GPIO, GPIO.OUT)
GPIO.output(RELAY_GPIO, GPIO.HIGH)  # Fail-safe default: repeater AAN na (re)start

GPIO.setup(BUTTON_GPIO, GPIO.IN, pull_up_down=GPIO.PUD_UP)  # Button: active-low to GND, internal pull-up

STATE = {
    "repeater_on": True,
    "last_switch": 0.0,
}
_STATE_LOCK = threading.Lock()

# Button infra (callback must be non-blocking)
_BUTTON_Q: "queue.Queue[float]" = queue.Queue(maxsize=20)
_BUTTON_THREAD: Optional[threading.Thread] = None
_LAST_BUTTON_TS = 0.0

# ---------------------
# Database
# ---------------------
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def db_init():
    ensure_parent_dir(DB_PATH)
    with db() as c:
        c.execute("PRAGMA journal_mode=WAL;")
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            username        TEXT UNIQUE NOT NULL,
            email           TEXT UNIQUE NOT NULL,
            pw_hash         TEXT NOT NULL,
            totp_secret     TEXT,
            totp_enabled    INTEGER NOT NULL DEFAULT 0,
            is_admin        INTEGER NOT NULL DEFAULT 1,
            is_superadmin   INTEGER NOT NULL DEFAULT 0,
            is_active       INTEGER NOT NULL DEFAULT 1,
            notify_enabled  INTEGER NOT NULL DEFAULT 1,
            created_at      TEXT NOT NULL,
            last_login_at   TEXT,
            last_login_ip   TEXT
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            ts         TEXT NOT NULL,
            event      TEXT NOT NULL,
            user_id    INTEGER,
            ip         TEXT,
            user_agent TEXT,
            details    TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """)

        defaults = {
            "alarm_enabled": "1" if DEFAULT_ALARM_ENABLED else "0",
            "alarm_trip": str(DEFAULT_ALARM_TRIP_C),
            "alarm_clear": str(DEFAULT_ALARM_CLEAR_C),
            "cooldown_seconds": str(COOLDOWN_SECONDS),
            "band": "unknown",

            # prepared temp alarms
            "temp_alert_enabled": "1" if DEFAULT_TEMP_ALERT_ENABLED else "0",
            "temp_int_trip": str(DEFAULT_TEMP_INT_TRIP_C),
            "temp_int_clear": str(DEFAULT_TEMP_INT_CLEAR_C),
            "temp_ext_trip": str(DEFAULT_TEMP_EXT_TRIP_C),
            "temp_ext_clear": str(DEFAULT_TEMP_EXT_CLEAR_C),
            "temp_alert_min_interval_seconds": str(DEFAULT_TEMP_ALERT_MIN_INTERVAL_SECONDS),
        }
        for k, v in defaults.items():
            c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))


def setting_get(key: str, default: str) -> str:
    with db() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def setting_set(key: str, value: str) -> None:
    with db() as c:
        c.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def audit(event, user_id=None, detail=""):
    ua = request.headers.get("User-Agent", "-")
    with db() as c:
        c.execute("""
            INSERT INTO audit_log(ts,event,user_id,ip,user_agent,details)
            VALUES(?,?,?,?,?,?)
        """, (
            utc_ts(),
            event,
            user_id,
            client_ip(),
            ua,
            detail or ""
        ))


def audit_system(event: str, detail: str = "") -> None:
    """
    Audit for background threads (no Flask request context).
    """
    try:
        with db() as c:
            c.execute("""
                INSERT INTO audit_log(ts,event,user_id,ip,user_agent,details)
                VALUES(?,?,?,?,?,?)
            """, (
                utc_ts(),
                event,
                None,
                "-",
                "SYSTEM",
                detail or ""
            ))
    except Exception:
        pass


# ---------------------
# Auth helpers
# ---------------------
def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    with db() as c:
        return c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


def login_required():
    if not current_user():
        abort(401, "Niet ingelogd.")


def admin_required():
    u = current_user()
    if not u or not u["is_admin"]:
        abort(403, "Geen admin-rechten.")


def superadmin_required():
    u = current_user()
    if not u or not u["is_superadmin"]:
        abort(403, "Alleen superadmin toegestaan.")


# ---------------------
# Cooldown + relay
# ---------------------
def cooldown_seconds() -> int:
    try:
        return int(float(setting_get("cooldown_seconds", str(COOLDOWN_SECONDS))))
    except Exception:
        return COOLDOWN_SECONDS


def in_cooldown() -> bool:
    with _STATE_LOCK:
        return (time.time() - STATE["last_switch"]) < cooldown_seconds()


def cooldown_left() -> int:
    with _STATE_LOCK:
        return max(0, int(cooldown_seconds() - (time.time() - STATE["last_switch"])))


def set_repeater(on: bool) -> None:
    GPIO.output(RELAY_GPIO, GPIO.HIGH if on else GPIO.LOW)
    with _STATE_LOCK:
        STATE["repeater_on"] = bool(on)
        STATE["last_switch"] = time.time()


def toggle_repeater(source: str) -> bool:
    """
    Toggle repeater state; respects cooldown; logs as SYSTEM.
    """
    if in_cooldown():
        audit_system("REPEATER_TOGGLE_IGNORED", f"source={source} reason=cooldown left={cooldown_left()}")
        return False

    with _STATE_LOCK:
        new_state = not STATE["repeater_on"]

    set_repeater(new_state)
    audit_system("REPEATER_TOGGLE", f"source={source} state={'on' if new_state else 'off'}")
    return True


# ---------------------
# Button implementation
# ---------------------
def _button_gpio_callback(channel: int) -> None:
    """
    GPIO interrupt callback: must stay extremely fast.
    We push a timestamp into a queue; worker thread does the toggle/logging.
    """
    global _LAST_BUTTON_TS
    now = time.time()

    # extra software guard
    if (now - _LAST_BUTTON_TS) * 1000.0 < float(BUTTON_MIN_INTERVAL_MS):
        return
    _LAST_BUTTON_TS = now

    try:
        # Only react when actually pressed (active-low)
        if GPIO.input(BUTTON_GPIO) == GPIO.LOW:
            try:
                _BUTTON_Q.put_nowait(now)
            except queue.Full:
                pass
    except Exception:
        pass


def _button_worker() -> None:
    audit_system("BUTTON_THREAD_START", f"gpio={BUTTON_GPIO}")
    while True:
        _ = _BUTTON_Q.get()
        try:
            toggle_repeater(source="button")
        except Exception as e:
            audit_system("BUTTON_THREAD_ERROR", f"{type(e).__name__}: {e}")


def _button_poll_worker() -> None:
    audit_system("BUTTON_POLL_THREAD_START", f"gpio={BUTTON_GPIO}")
    last = GPIO.input(BUTTON_GPIO)
    last_change = time.time()
    while True:
        try:
            v = GPIO.input(BUTTON_GPIO)
            if v != last:
                last = v
                last_change = time.time()

            # active-low: pressed == LOW
            # trigger on stable LOW for >50ms
            if v == GPIO.LOW and (time.time() - last_change) > 0.05:
                audit_system("BUTTON_POLL_PRESS", "pressed")
                toggle_repeater(source="button_poll")
                # wait until released to avoid repeat
                while GPIO.input(BUTTON_GPIO) == GPIO.LOW:
                    time.sleep(0.02)
                time.sleep(0.10)  # small guard
        except Exception as e:
            audit_system("BUTTON_POLL_THREAD_ERROR", f"{type(e).__name__}: {e}")
            time.sleep(0.5)
        
        time.sleep(0.02)  # 50Hz polling - prevent busy loop


def start_button_listener_once() -> None:
    """
    Start button handling robustly:
      1) Try edge-detect
      2) If edge-detect fails, fall back to polling thread
    """
    global _BUTTON_THREAD

    # Ensure no double-detect (if reloaded)
    try:
        GPIO.remove_event_detect(BUTTON_GPIO)
    except Exception:
        pass

    try:
        GPIO.add_event_detect(
            BUTTON_GPIO,
            GPIO.FALLING,
            callback=_button_gpio_callback,
            bouncetime=int(BUTTON_BOUNCE_MS),
        )
        audit_system("BUTTON_LISTENER_STARTED", f"mode=edge gpio={BUTTON_GPIO} bounce_ms={BUTTON_BOUNCE_MS}")
    except Exception as e:
        # Fallback: polling
        audit_system("BUTTON_LISTENER_FALLBACK", f"mode=poll reason={type(e).__name__}: {e}")

        if _BUTTON_THREAD is None or not _BUTTON_THREAD.is_alive():
            _BUTTON_THREAD = threading.Thread(target=_button_poll_worker, name="button-poll-worker", daemon=True)
            _BUTTON_THREAD.start()
        return

    # Edge-detect ok → start queue worker
    if _BUTTON_THREAD is None or not _BUTTON_THREAD.is_alive():
        _BUTTON_THREAD = threading.Thread(target=_button_worker, name="button-worker", daemon=True)
        _BUTTON_THREAD.start()


# Start listener at import time (Gunicorn / wsgi)
try:
    start_button_listener_once()
except Exception:
    pass


# ---------------------
# Temperature alarm worker (INT/EXT)
# ---------------------
def _temp_alarm_enabled() -> bool:
    return setting_get("temp_alert_enabled", "1") == "1"


def _temp_alarm_min_interval() -> int:
    try:
        return int(float(setting_get("temp_alert_min_interval_seconds", str(DEFAULT_TEMP_ALERT_MIN_INTERVAL_SECONDS))))
    except Exception:
        return DEFAULT_TEMP_ALERT_MIN_INTERVAL_SECONDS


def _temp_thresholds() -> Dict[str, float]:
    def f(key: str, default: float) -> float:
        try:
            return float(setting_get(key, str(default)))
        except Exception:
            return default

    return {
        "int_trip": f("temp_int_trip", DEFAULT_TEMP_INT_TRIP_C),
        "int_clear": f("temp_int_clear", DEFAULT_TEMP_INT_CLEAR_C),
        "ext_trip": f("temp_ext_trip", DEFAULT_TEMP_EXT_TRIP_C),
        "ext_clear": f("temp_ext_clear", DEFAULT_TEMP_EXT_CLEAR_C),
    }


_TEMP_STATE = {
    "int_high": False,
    "ext_high": False,
    "last_mail_ts": 0.0,
}


def _maybe_send_temp_alarm(source: str, temp_c: float, trip: float, clear: float) -> None:
    """
    Hysteresis:
      - if not high and temp >= trip => HIGH event
      - if high and temp <= clear => CLEAR event
    Anti-spam: minimum interval between any alarm mails.
    """
    now = time.time()
    min_int = _temp_alarm_min_interval()

    if source == SRC_INT:
        high_key = "int_high"
        ev_high = "TEMP_ALARM_INT_HIGH"
        ev_clear = "TEMP_ALARM_INT_CLEAR"
    else:
        high_key = "ext_high"
        ev_high = "TEMP_ALARM_EXT_HIGH"
        ev_clear = "TEMP_ALARM_EXT_CLEAR"

    is_high = bool(_TEMP_STATE.get(high_key, False))

    def can_mail() -> bool:
        return (now - float(_TEMP_STATE.get("last_mail_ts", 0.0))) >= float(min_int)

    if not is_high and temp_c >= trip:
        _TEMP_STATE[high_key] = True
        detail = f"{source} temp={temp_c:.1f}C trip={trip:.1f}C"
        audit_system(ev_high, detail)
        if can_mail():
            _TEMP_STATE["last_mail_ts"] = now
            _send_internal_status_mail(utc_ts(), ev_high, detail)

    elif is_high and temp_c <= clear:
        _TEMP_STATE[high_key] = False
        detail = f"{source} temp={temp_c:.1f}C clear={clear:.1f}C"
        audit_system(ev_clear, detail)
        if can_mail():
            _TEMP_STATE["last_mail_ts"] = now
            _send_internal_status_mail(utc_ts(), ev_clear, detail)


def _monitor_temp_loop() -> None:
    audit_system("TEMP_MONITOR_THREAD_START", "int/ext temp alarm loop started")
    while not _MONITOR_STOP.is_set():
        try:
            if _temp_alarm_enabled():
                thr = _temp_thresholds()

                it = read_monitor_latest(SRC_INT)
                ex = read_monitor_latest(SRC_EXT)

                if it and it.get("temp") is not None:
                    _maybe_send_temp_alarm(SRC_INT, float(it["temp"]), thr["int_trip"], thr["int_clear"])
                if ex and ex.get("temp") is not None:
                    _maybe_send_temp_alarm(SRC_EXT, float(ex["temp"]), thr["ext_trip"], thr["ext_clear"])
        except Exception as e:
            audit_system("TEMP_MONITOR_THREAD_ERROR", f"{type(e).__name__}: {e}")

        _MONITOR_STOP.wait(10.0)


def start_monitor_thread_once() -> None:
    global _MONITOR_THREAD
    if _MONITOR_THREAD is not None and _MONITOR_THREAD.is_alive():
        return
    _MONITOR_STOP.clear()
    _MONITOR_THREAD = threading.Thread(target=_monitor_temp_loop, name="temp-monitor", daemon=True)
    _MONITOR_THREAD.start()


# ---------------------
# JSON errors (no HTML)
# ---------------------
@app.errorhandler(400)
def _err_400(e):
    msg = getattr(e, "description", "Ongeldige aanvraag.")
    return jsonify({"ok": False, "error": {"status": 400, "message": msg}}), 400


@app.errorhandler(401)
def _err_401(e):
    msg = getattr(e, "description", "Niet ingelogd.")
    return jsonify({"ok": False, "error": {"status": 401, "message": msg}}), 401


@app.errorhandler(403)
def _err_403(e):
    msg = getattr(e, "description", "Geen rechten voor deze actie.")
    return jsonify({"ok": False, "error": {"status": 403, "message": msg}}), 403


@app.errorhandler(404)
def _err_404(e):
    msg = getattr(e, "description", "Endpoint niet gevonden.")
    return jsonify({"ok": False, "error": {"status": 404, "message": msg}}), 404


@app.errorhandler(405)
def _err_405(e):
    return jsonify({"ok": False, "error": {"status": 405, "message": "Verkeerde HTTP-methode (405)."}}), 405


@app.errorhandler(429)
def _err_429(e):
    msg = getattr(e, "description", "Te snel achter elkaar.")
    return jsonify({"ok": False, "error": {"status": 429, "message": msg}}), 429


# ======================================================
# AUTH API
# ======================================================
@app.post("/api/login")
def api_login():
    data = request.get_json(silent=True) or {}

    ident = (data.get("ident") or "").strip()
    if not ident:
        ident = (data.get("username") or "").strip()
    if not ident:
        ident = (data.get("email") or "").strip()

    pw = data.get("password") or ""
    otp = data.get("otp")

    if not ident or not pw:
        audit("LOGIN_FAIL", None, f"missing ident/pw | keys={sorted(list(data.keys()))}")
        abort(401, "Invalid credentials")

    ident_norm = ident.strip()
    ident_lower = ident_norm.lower()

    with db() as c:
        user = c.execute(
            """
            SELECT * FROM users
            WHERE is_active=1
              AND (
                   username = ?
                OR lower(trim(email)) = ?
              )
            """,
            (ident_norm, ident_lower),
        ).fetchone()

    if not user or not check_password_hash(user["pw_hash"], pw):
        audit("LOGIN_FAIL", None, f"ident={ident_norm!r} keys={sorted(list(data.keys()))}")
        abort(401, "Invalid credentials")

    if user["totp_enabled"]:
        if not otp:
            audit("LOGIN_OTP_REQUIRED", user["id"])
            abort(403, "OTP required")
        totp = pyotp.TOTP(user["totp_secret"])
        if not totp.verify(str(otp).strip()):
            audit("LOGIN_OTP_FAIL", user["id"])
            abort(403, "Invalid OTP")

    session.clear()
    session["uid"] = user["id"]

    with db() as c:
        c.execute(
            "UPDATE users SET last_login_at=?, last_login_ip=? WHERE id=?",
            (utc_ts(), client_ip(), user["id"]),
        )

    audit("LOGIN_OK", user["id"])
    return jsonify({"ok": True})


@app.post("/api/logout")
def api_logout():
    u = current_user()
    if u:
        audit("LOGOUT", u["id"])
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/me")
def api_me():
    u = current_user()
    if not u:
        return jsonify({"logged_in": False})
    return jsonify({
        "logged_in": True,
        "id": u["id"],
        "username": u["username"],
        "email": u["email"],
        "is_admin": bool(u["is_admin"]),
        "is_superadmin": bool(u["is_superadmin"]),
        "notify_enabled": bool(u["notify_enabled"]),
        "totp_enabled": bool(u["totp_enabled"]),
    })


@app.get("/api/auth-check")
def api_auth_check():
    """
    Lightweight auth check for nginx auth_request.
    Returns 200 if logged in, 401 if not.
    Used to protect Grafana and other internal services.
    """
    if current_user():
        return "", 200
    return "", 401


# ======================================================
# 2FA
# ======================================================
@app.get("/api/2fa/setup")
def api_2fa_setup():
    login_required()
    u = current_user()

    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name=u["email"], issuer_name="PI3TWE")

    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    session["2fa_tmp"] = secret
    return jsonify({"secret": secret, "qr": f"data:image/png;base64,{qr_b64}"})


@app.post("/api/2fa/enable")
def api_2fa_enable():
    login_required()
    data = request.get_json(silent=True) or {}
    code = str(data.get("code") or "").strip()
    secret = session.get("2fa_tmp")

    if not secret:
        abort(400, "Geen setup actief.")
    if not code:
        abort(400, "Code ontbreekt.")

    totp = pyotp.TOTP(secret)
    if not totp.verify(code):
        abort(403, "Invalid OTP")

    with db() as c:
        c.execute("UPDATE users SET totp_secret=?, totp_enabled=1 WHERE id=?", (secret, session["uid"]))

    audit("2FA_ENABLED", session["uid"])
    session.pop("2fa_tmp", None)
    return jsonify({"ok": True})


# ======================================================
# USER: CHANGE PASSWORD
# ======================================================
@app.post("/api/user/password")
def api_user_password():
    login_required()
    u = current_user()
    if not u:
        abort(401, "Not logged in")

    data = request.get_json(silent=True) or {}
    old_pw = (data.get("old_password") or "")
    new_pw = (data.get("new_password") or "")

    if not old_pw or not new_pw:
        abort(400, "old_password en new_password zijn verplicht")

    if len(new_pw) < 10:
        abort(400, "Nieuw wachtwoord is te kort (minimaal 10 tekens)")

    if not check_password_hash(u["pw_hash"], old_pw):
        audit("PW_CHANGE_FAIL", u["id"], "wrong old password")
        abort(403, "Oud wachtwoord is onjuist")

    with db() as c:
        c.execute(
            "UPDATE users SET pw_hash=? WHERE id=?",
            (generate_password_hash(new_pw), u["id"])
        )

    audit("PW_CHANGE_OK", u["id"])
    return jsonify({"ok": True})


# ======================================================
# FAIL2BAN API
# ======================================================
@app.get("/api/fail2ban")
def api_fail2ban():
    login_required()
    return jsonify(fail2ban_status())


# ======================================================
# ADMIN: users
# ======================================================
@app.get("/api/admin/users")
def api_admin_users_get():
    admin_required()
    with db() as c:
        rows = c.execute("""
            SELECT id, username, email, is_admin, is_superadmin, is_active, notify_enabled, totp_enabled,
                   created_at, last_login_at, last_login_ip
            FROM users
            ORDER BY is_superadmin DESC, id ASC
        """).fetchall()
    return jsonify({"users": [dict(r) for r in rows]})


@app.post("/api/admin/users")
def api_admin_users_create():
    admin_required()
    me = current_user()

    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip()
    is_admin = bool(data.get("is_admin", True))
    notify_enabled = bool(data.get("notify_enabled", True))

    if not username or not email:
        abort(400, "username en email zijn verplicht.")

    temp_pw = secrets.token_urlsafe(16)
    pw_hash = generate_password_hash(temp_pw)

    with db() as c:
        try:
            c.execute("""
                INSERT INTO users(username,email,pw_hash,is_admin,is_superadmin,is_active,notify_enabled,created_at)
                VALUES(?,?,?,?,?,?,?,?)
            """, (
                username,
                email,
                pw_hash,
                1 if is_admin else 0,
                0,
                1,
                1 if notify_enabled else 0,
                datetime.utcnow().isoformat(timespec="seconds"),
            ))
        except sqlite3.IntegrityError:
            abort(400, "Username of email bestaat al.")

    audit("USER_CREATED", me["id"], f"user={username} email={email} is_admin={is_admin} notify={notify_enabled}")

    subject = "PI3TWE - account aangemaakt"
    body_text = (
        f"Hallo {username},\n\n"
        f"Je PI3TWE account is aangemaakt.\n\n"
        f"Inloggen:\n"
        f"  Gebruiker/email: {username} / {email}\n"
        f"  Tijdelijk wachtwoord: {temp_pw}\n\n"
        f"Belangrijk:\n"
        f"- Wijzig bij de eerste login direct je wachtwoord.\n"
        f"- Zet daarna 2FA aan.\n\n"
        f"Groet,\nPI3TWE Controller\n"
    )
    body_html = "<pre style='font-family:Arial,Helvetica,sans-serif;white-space:pre-wrap;'>" + _html_escape(body_text) + "</pre>"
    send_mail(email, subject, body_text, body_html)

    return jsonify({"ok": True})


def _deactivate_user(user_id: int):
    superadmin_required()
    me = current_user()

    if int(me["id"]) == int(user_id):
        abort(400, "Je kunt jezelf niet deactiveren.")

    with db() as c:
        u = c.execute(
            "SELECT id, username, email, is_superadmin, is_active FROM users WHERE id=?",
            (user_id,),
        ).fetchone()
        if not u:
            abort(404, "Gebruiker niet gevonden.")
        if int(u["is_superadmin"]) == 1:
            abort(400, "Superadmin kan niet gedeactiveerd worden.")
        if int(u["is_active"]) == 0:
            return jsonify({"ok": True})

        c.execute("UPDATE users SET is_active=0 WHERE id=?", (user_id,))

    audit("USER_DEACTIVATED", me["id"], f"user_id={user_id} username={u['username']} email={u['email']}")
    return jsonify({"ok": True})


# BACKWARD COMPAT: UI used to call /delete (but it was actually deactivate)
@app.post("/api/admin/users/<int:user_id>/delete")
def api_admin_user_delete_alias(user_id: int):
    return _deactivate_user(user_id)


@app.post("/api/admin/users/<int:user_id>/deactivate")
def api_admin_user_deactivate(user_id: int):
    return _deactivate_user(user_id)


@app.post("/api/admin/users/<int:user_id>/activate")
def api_admin_user_activate(user_id: int):
    superadmin_required()
    me = current_user()

    with db() as c:
        u = c.execute(
            "SELECT id, username, email, is_superadmin, is_active FROM users WHERE id=?",
            (user_id,),
        ).fetchone()
        if not u:
            abort(404, "Gebruiker niet gevonden.")
        if int(u["is_superadmin"]) == 1:
            abort(400, "Superadmin kan niet (her)geactiveerd worden.")
        if int(u["is_active"]) == 1:
            return jsonify({"ok": True})

        c.execute("UPDATE users SET is_active=1 WHERE id=?", (user_id,))

    audit("USER_ACTIVATED", me["id"], f"user_id={user_id} username={u['username']} email={u['email']}")
    return jsonify({"ok": True})


@app.post("/api/admin/users/<int:user_id>/purge")
def api_admin_user_purge(user_id: int):
    """
    HARD delete: echt uit users verwijderen (weg = weg).
    Voor veiligheid: alleen superadmin, nooit self, nooit superadmin.

    Belangrijk:
    - audit_log heeft een FK naar users(id) zonder ON DELETE SET NULL.
      Daarom zetten we audit_log.user_id eerst op NULL.
    """
    superadmin_required()
    me = current_user()

    if int(me["id"]) == int(user_id):
        abort(400, "Je kunt jezelf niet verwijderen.")

    with db() as c:
        u = c.execute(
            "SELECT id, username, email, is_superadmin FROM users WHERE id=?",
            (user_id,),
        ).fetchone()
        if not u:
            abort(404, "Gebruiker niet gevonden.")
        if int(u["is_superadmin"]) == 1:
            abort(400, "Superadmin kan niet verwijderd worden.")

        c.execute("UPDATE audit_log SET user_id=NULL WHERE user_id=?", (user_id,))
        c.execute("DELETE FROM users WHERE id=?", (user_id,))

    audit("USER_PURGED", me["id"], f"user_id={user_id} username={u['username']} email={u['email']}")
    return jsonify({"ok": True})


# ======================================================
# ADMIN: alarm settings
# ======================================================
@app.get("/api/admin/alarm")
def api_admin_alarm_get():
    admin_required()
    enabled = setting_get("alarm_enabled", "1") == "1"
    try:
        trip = float(setting_get("alarm_trip", str(DEFAULT_ALARM_TRIP_C)))
    except Exception:
        trip = DEFAULT_ALARM_TRIP_C
    try:
        clear = float(setting_get("alarm_clear", str(DEFAULT_ALARM_CLEAR_C)))
    except Exception:
        clear = DEFAULT_ALARM_CLEAR_C

    return jsonify({"enabled": enabled, "trip_c": trip, "clear_c": clear})


@app.post("/api/admin/alarm")
def api_admin_alarm_set():
    admin_required()
    data = request.get_json(silent=True) or {}

    enabled = bool(data.get("enabled", True))
    try:
        trip = float(data.get("trip_c", DEFAULT_ALARM_TRIP_C))
        clear = float(data.get("clear_c", DEFAULT_ALARM_CLEAR_C))
    except Exception:
        abort(400, "Ongeldige trip/clear waarde.")

    if clear >= trip:
        abort(400, "clear_c moet lager zijn dan trip_c.")

    setting_set("alarm_enabled", "1" if enabled else "0")
    setting_set("alarm_trip", str(trip))
    setting_set("alarm_clear", str(clear))

    audit("ALARM_SETTINGS", current_user_id(), f"enabled={enabled} trip={trip} clear={clear}")
    return jsonify({"ok": True})


# ======================================================
# REPEATER API
# ======================================================


# ------------------------------
# CPU load % (lightweight, cached with moving average)
# ------------------------------
_CPU_STAT_LAST = {"t": 0.0, "idle": None, "total": None, "pct": None}
_CPU_LOAD_HISTORY = []  # Last N samples for moving average
_CPU_LOAD_HISTORY_SIZE = 5  # Number of samples to average

def cpu_load_percent_cached(min_interval_s: float = 1.0):
    """
    Returns CPU load percentage (0..100) based on /proc/stat deltas.
    Uses a moving average of the last 5 samples to smooth out spikes.
    Cached to avoid overhead when /api/state is polled frequently.
    """
    global _CPU_LOAD_HISTORY
    now = time.time()
    if _CPU_STAT_LAST["pct"] is not None and (now - _CPU_STAT_LAST["t"]) < min_interval_s:
        return _CPU_STAT_LAST["pct"]

    try:
        with open("/proc/stat", "r", encoding="utf-8") as f:
            line = f.readline().strip()
        # cpu  user nice system idle iowait irq softirq steal guest guest_nice
        parts = line.split()
        if len(parts) < 5 or parts[0] != "cpu":
            return _CPU_STAT_LAST["pct"]

        nums = [int(x) for x in parts[1:]]
        idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
        total = sum(nums)

        prev_idle = _CPU_STAT_LAST["idle"]
        prev_total = _CPU_STAT_LAST["total"]

        _CPU_STAT_LAST["idle"] = idle
        _CPU_STAT_LAST["total"] = total
        _CPU_STAT_LAST["t"] = now

        if prev_idle is None or prev_total is None:
            # first sample; need a second sample for a delta
            return _CPU_STAT_LAST["pct"]

        didle = idle - prev_idle
        dtotal = total - prev_total
        if dtotal <= 0:
            return _CPU_STAT_LAST["pct"]

        usage = 1.0 - (didle / float(dtotal))
        raw_pct = max(0.0, min(100.0, usage * 100.0))
        
        # Add to history and compute moving average
        _CPU_LOAD_HISTORY.append(raw_pct)
        if len(_CPU_LOAD_HISTORY) > _CPU_LOAD_HISTORY_SIZE:
            _CPU_LOAD_HISTORY = _CPU_LOAD_HISTORY[-_CPU_LOAD_HISTORY_SIZE:]
        
        # Return moving average
        pct = sum(_CPU_LOAD_HISTORY) / len(_CPU_LOAD_HISTORY)
        _CPU_STAT_LAST["pct"] = pct
        return pct
    except Exception:
        return _CPU_STAT_LAST["pct"]


# ------------------------------
# Uplink label (WLAN0 / ETH0 / HAMNET), cached
# ------------------------------
_UPLINK_LAST = {"t": 0.0, "label": None}

def uplink_label_cached(wan_ip: str, min_interval_s: float = 5.0) -> str:
    """
    Best effort uplink label:
      - If WAN is 44.* => HAMNET
      - else based on default route dev => WLAN0/ETH0/<dev>
    Cached to keep /api/state cheap.
    """
    now = time.time()
    if _UPLINK_LAST["label"] and (now - _UPLINK_LAST["t"]) < min_interval_s:
        return _UPLINK_LAST["label"]

    label = "WAN"
    try:
        if isinstance(wan_ip, str) and wan_ip.strip().startswith("44."):
            label = "HAMNET"
        else:
            out = subprocess.check_output(["ip", "route", "show", "default"], text=True, timeout=0.5)
            # typical: "default via 192.168.2.1 dev wlan0 proto dhcp src ... metric ..."
            dev = None
            for tok_i, tok in enumerate(out.split()):
                if tok == "dev" and tok_i + 1 < len(out.split()):
                    dev = out.split()[tok_i + 1]
                    break
            if dev:
                if dev.lower().startswith("wlan"):
                    label = dev.upper()  # WLAN0
                elif dev.lower().startswith("eth"):
                    label = dev.upper()  # ETH0
                else:
                    label = dev
    except Exception:
        pass

    _UPLINK_LAST["label"] = label
    _UPLINK_LAST["t"] = now
    return label
    
@app.get("/api/state")
def api_state():
    enabled = setting_get("alarm_enabled", "1") == "1"
    try:
        trip = float(setting_get("alarm_trip", str(DEFAULT_ALARM_TRIP_C)))
    except Exception:
        trip = DEFAULT_ALARM_TRIP_C
    try:
        clear = float(setting_get("alarm_clear", str(DEFAULT_ALARM_CLEAR_C)))
    except Exception:
        clear = DEFAULT_ALARM_CLEAR_C

    band = setting_get("band", "unknown")
    lan = get_lan_ip()
    wan = get_wan_ip()

    # NEW: uplink label + cpu load %
    uplink = uplink_label_cached(wan)
    cpu_load = cpu_load_percent_cached()

    cpu = read_monitor_latest(SRC_CPU)
    it = read_monitor_latest(SRC_INT)
    ex = read_monitor_latest(SRC_EXT)

    # NEW: attach cpu_load into cpu monitor dict (if dict)
    try:
        if cpu is None:
            cpu = {}
        if isinstance(cpu, dict):
            # keep it small; percent as float (e.g. 18.3)
            cpu["load"] = cpu_load
    except Exception:
        pass

    with _STATE_LOCK:
        rep = bool(STATE["repeater_on"])

    up_s = read_uptime_seconds()
    up_txt = format_uptime(up_s)
    
    return jsonify({
        "repeater": rep,
        "cooldown": cooldown_left(),
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "uptime_s": up_s,
        "uptime": up_txt,
        "client_ip": client_ip(),

        "lan_ip": lan,
        "wan_ip": wan,
        "wan_uplink": uplink,   # NEW
        "band": band,

        "monitor": {
            "cpu": cpu,
            "int": it,
            "ext": ex,
        },

        "alarm": {"enabled": enabled, "trip_c": trip, "clear_c": clear}
    })


@app.post("/api/repeater/on")
def api_on():
    login_required()
    with _STATE_LOCK:
        if STATE["repeater_on"]:
            return jsonify({"ok": True})
    if in_cooldown():
        abort(429, "Cooldown actief")
    set_repeater(True)
    audit("REPEATER_ON", session["uid"], "manual")
    return jsonify({"ok": True})


@app.post("/api/repeater/off")
def api_off():
    login_required()
    with _STATE_LOCK:
        if not STATE["repeater_on"]:
            return jsonify({"ok": True})
    if in_cooldown():
        abort(429, "Cooldown actief")
    set_repeater(False)
    audit("REPEATER_OFF", session["uid"], "manual")
    return jsonify({"ok": True})


# ======================================================
# LOG API
# ======================================================
@app.get("/api/log")
def api_log():
    login_required()
    try:
        limit = int(request.args.get("limit", "10"))
    except ValueError:
        limit = 10
    limit = max(1, min(200, limit))

    with db() as c:
        rows = c.execute("""
            SELECT ts AS ts_utc, ip, event, details
            FROM audit_log
            ORDER BY id DESC
            LIMIT ?
        """, (limit,)).fetchall()

    return jsonify({"entries": [dict(r) for r in rows]})


# ======================================================
# Root (health)
# ======================================================
@app.get("/")
def root():
    return "Backend OK"


# ======================================================
# Cleanup
# ======================================================
@atexit.register
def cleanup():
    # Fail-safe: laat repeater AAN bij exit (crash/restart scenario wens)
    try:
        GPIO.output(RELAY_GPIO, GPIO.HIGH)
    except Exception:
        pass
    try:
        _MONITOR_STOP.set()
    except Exception:
        pass
    try:
        GPIO.cleanup()
    except Exception:
        pass


def ensure_superadmin_exists():
    SUPER_EMAIL = "erik@pa0esh.nl"
    SUPER_USERNAME = "erik"

    with db() as c:
        row = c.execute("SELECT id FROM users WHERE is_superadmin=1 LIMIT 1").fetchone()
        if row:
            return

        temp_pw = secrets.token_urlsafe(16)
        c.execute("""
            INSERT INTO users(username,email,pw_hash,is_admin,is_superadmin,is_active,notify_enabled,created_at)
            VALUES(?,?,?,?,?,?,?,?)
        """, (
            SUPER_USERNAME,
            SUPER_EMAIL,
            generate_password_hash(temp_pw),
            1, 1, 1, 1,
            datetime.utcnow().isoformat(timespec="seconds"),
        ))

    try:
        subject = "PI3TWE - superadmin aangemaakt"
        body_text = (
            f"Superadmin user aangemaakt:\n\n"
            f"user: {SUPER_USERNAME}\n"
            f"mail: {SUPER_EMAIL}\n"
            f"tijdelijk wachtwoord: {temp_pw}\n\n"
            f"Log in en wijzig direct het wachtwoord en zet 2FA aan.\n"
        )
        body_html = "<pre style='font-family:Arial,Helvetica,sans-serif;white-space:pre-wrap;'>" + _html_escape(body_text) + "</pre>"
        send_mail(SUPER_EMAIL, subject, body_text, body_html)
    except Exception:
        pass


# ======================================================
# Main / Gunicorn init
# ======================================================
def init_for_gunicorn() -> None:
    """
    Init that MUST run under Gunicorn (wsgi import).
    Keep it idempotent; safe to call more than once.
    """
    try:
        db_init()
        ensure_superadmin_exists()
        start_monitor_thread_once()
        start_monitor_db_logger_once()

        audit_system("MAIL_SELFTEST_START", "gunicorn_import")

        # Startup selftest mail (formatted; header image inline when present)
        try:
            _send_internal_status_mail(utc_ts(), "MAIL_SELFTEST_OK", "Startup selftest")
            audit_system("MAIL_SELFTEST_OK", f"sent to {INTERNAL_MAIL_TO}")
        except Exception as e:
            audit_system("MAIL_SELFTEST_FAIL", f"{type(e).__name__}: {e}")

        # Reboot/crash/startup visibility
        audit_system("BOOT_INIT_OK", "gunicorn_import completed")
        _send_internal_status_mail(utc_ts(), "BOOT_INIT_OK", "gunicorn_import completed")

    except Exception as e:
        try:
            audit_system("BOOT_INIT_FAIL", f"init_exception {type(e).__name__}: {e}")
        except Exception:
            pass
        try:
            _send_internal_status_mail(utc_ts(), "BOOT_INIT_FAIL", f"{type(e).__name__}: {e}")
        except Exception:
            pass


def main():
    db_init()
    ensure_superadmin_exists()
    start_monitor_thread_once()
    app.run(host="127.0.0.1", port=3001)


if __name__ == "__main__":
    main()