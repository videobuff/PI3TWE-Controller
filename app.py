#!/usr/bin/env python3
# ======================================================
# File: /srv/pi3twe/app/app.py
# Generated: 2026-01-06 (Europe/Amsterdam)
# Description: PI3TWE Controller backend
#  - SQLite users + audit log + settings
#  - Login (ident OR username OR email), sessions
#  - 2FA (TOTP)
#  - Admin: users list/create/deactivate/activate + SUPERADMIN: hard delete (purge) + Alarm settings
#  - Repeater control + cooldown
#  - LAN/WAN + monitor.db (cpu/int/ext) + band
#  - Fail2ban status endpoint
#  - JSON errors (no HTML error pages for API)
#  - New user: email temp password via msmtp (config in secrets)
#
# Notes (important):
#  - /api/admin/users/<id>/delete is kept as BACKWARD COMPAT alias for "deactivate"
#    because the current UI calls /delete.
#  - /api/admin/users/<id>/purge is HARD delete (weg = weg). It NULLs audit_log.user_id first.
# ======================================================

from flask import Flask, jsonify, request, abort, session
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
import RPi.GPIO as GPIO
import atexit
from fastapi import Response

# ---------------------
# Config
# ---------------------
DB_PATH = "/srv/pi3twe/app/pi3twe.db"
MONITOR_DB_PATH = "/srv/pi3twe/data/monitor.db"

# monitor sources (match monitor.db)
SRC_CPU = "cpu"
SRC_INT = "int"
SRC_EXT = "ext"

RELAY_GPIO = 17
COOLDOWN_SECONDS = 30

DEFAULT_ALARM_ENABLED = True
DEFAULT_ALARM_TRIP_C = 55.0
DEFAULT_ALARM_CLEAR_C = 43.0

# WAN lookup
WAN_LOOKUP_URL = "https://api.ipify.org"
WAN_CACHE_SECONDS = 60
_WAN_CACHE = {"ip": "", "ts": 0.0}

# msmtp (config in secrets)
MSMTP_BIN = "/usr/bin/msmtp"
MSMTP_CONF = "/srv/pi3twe/app/secrets/msmtprc"
MAIL_FROM = "no-reply@pi3twe.nl"

# Persist secret so sessions survive service restarts
APP_SECRET_FILE = "/srv/pi3twe/app/secrets/flask_secret.key"

# ---------------------
# Helpers
# ---------------------
def utc_ts() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")


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


def send_mail(to_addr: str, subject: str, body: str) -> None:
    """
    Send mail via msmtp using MSMTP_CONF.
    Failures are logged in audit_log but do not hard-fail the API call.
    """
    msg = (
        f"From: {MAIL_FROM}\n"
        f"To: {to_addr}\n"
        f"Subject: {subject}\n"
        f"Content-Type: text/plain; charset=utf-8\n"
        f"\n{body}\n"
    )

    # sanity: config must exist
    if not os.path.exists(MSMTP_BIN):
        audit("MAIL_FAIL", current_user_id(), f"msmtp binary ontbreekt: {MSMTP_BIN}")
        return
    if not os.path.exists(MSMTP_CONF):
        audit("MAIL_FAIL", current_user_id(), f"msmtprc ontbreekt: {MSMTP_CONF}")
        return

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
    Leest laatste meting uit monitor.db voor een source.
    Verwacht tabel: measurements(ts NUM, source TEXT, temp REAL, hum REAL)
    """
    if not os.path.exists(MONITOR_DB_PATH):
        return None
    try:
        conn = sqlite3.connect(MONITOR_DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT ts, source, temp, hum FROM measurements WHERE source=? ORDER BY ts DESC LIMIT 1",
            (source,),
        ).fetchone()
        conn.close()
        if not row:
            return None
        temp = row["temp"]
        hum = row["hum"]
        return {
            "ts": row["ts"],
            "temp": (round(float(temp), 1) if temp is not None else None),
            "hum": (round(float(hum), 1) if hum is not None else None),
        }
    except Exception:
        return None


def fail2ban_status():
    """
    Returns {"total": int|None, "jails": {name:int}, "error"?: str}

    Uses sudo (NOPASSWD) because fail2ban socket is root-only.
    Will NEVER raise; failures become {"error": "..."}.
    """
    import subprocess

    SUDO = "/usr/bin/sudo"
    F2B  = "/usr/bin/fail2ban-client"

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

    # 1) global status
    rc, out, err = run([SUDO, "-n", F2B, "status"], timeout=2)

    if rc != 0:
        msg = err or out or f"fail2ban status rc={rc}"
        return {"total": None, "jails": {}, "error": msg[:300]}

    # Parse jail list
    jails = []
    for line in out.splitlines():
        if "Jail list:" in line:
            part = line.split("Jail list:", 1)[1].strip()
            if part:
                jails = [x.strip() for x in part.split(",") if x.strip()]
            break

    counts = {}
    total = 0

    # 2) per-jail status
    for jail in jails:
        rc2, out2, err2 = run([SUDO, "-n", F2B, "status", jail], timeout=2)
        if rc2 != 0 or not out2:
            # do not fail entire endpoint; just skip this jail
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
# GPIO
# ---------------------
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
GPIO.setup(RELAY_GPIO, GPIO.OUT)
GPIO.output(RELAY_GPIO, GPIO.LOW)

STATE = {
    "repeater_on": False,
    "last_switch": 0.0,
}

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
# Cooldown
# ---------------------
def cooldown_seconds() -> int:
    try:
        return int(float(setting_get("cooldown_seconds", str(COOLDOWN_SECONDS))))
    except Exception:
        return COOLDOWN_SECONDS


def in_cooldown():
    return (time.time() - STATE["last_switch"]) < cooldown_seconds()


def cooldown_left():
    return max(0, int(cooldown_seconds() - (time.time() - STATE["last_switch"])))


def set_repeater(on):
    GPIO.output(RELAY_GPIO, GPIO.HIGH if on else GPIO.LOW)
    STATE["repeater_on"] = bool(on)
    STATE["last_switch"] = time.time()


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
    body = (
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
    send_mail(email, subject, body)

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

        # Detach audit_log references to avoid FK issues
        c.execute("UPDATE audit_log SET user_id=NULL WHERE user_id=?", (user_id,))

        # Delete user (hard delete)
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

    cpu = read_monitor_latest(SRC_CPU)
    it = read_monitor_latest(SRC_INT)
    ex = read_monitor_latest(SRC_EXT)

    return jsonify({
        "repeater": STATE["repeater_on"],
        "cooldown": cooldown_left(),
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "client_ip": client_ip(),

        "lan_ip": lan,
        "wan_ip": wan,
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
    try:
        GPIO.output(RELAY_GPIO, GPIO.LOW)
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
        send_mail(
            SUPER_EMAIL,
            "PI3TWE - superadmin aangemaakt",
            f"Superadmin user aangemaakt:\n\nuser: {SUPER_USERNAME}\nmail: {SUPER_EMAIL}\n"
            f"tijdelijk wachtwoord: {temp_pw}\n\nLog in en wijzig direct het wachtwoord en zet 2FA aan.\n"
        )
    except Exception:
        pass


# ======================================================
# Main
# ======================================================
def main():
    db_init()
    ensure_superadmin_exists()
    app.run(host="127.0.0.1", port=3000)


if __name__ == "__main__":
    main()