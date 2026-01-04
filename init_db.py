#!/usr/bin/env python3
"""
File: init_db.py
Generated: 2025-12-24 (Europe/Amsterdam)
Description: Initialiseert SQLite DB voor PI3TWE controller (users, audit_log, settings).
"""

import os
import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash
import secrets

DB_PATH = "/var/lib/pi3twe/pi3twe.db"
SUPER_EMAIL = "erik@pa0esh.nl"
SUPER_USERNAME = "erik"

def main():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    cur = conn.cursor()

    cur.executescript("""
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

    # Defaults
    defaults = {
        "alarm_enabled": "1",
        "alarm_trip": "50.0",
        "alarm_clear": "45.0",
        "cooldown_seconds": "30",
        "smtp_host": "mail.pi3twe.nl",
        "smtp_user": "locatie@pi3twe.nl",
        "smtp_from": "locatie@pi3twe.nl",
        "smtp_tls": "1",
        "smtp_port": "587",
    }
    for k, v in defaults.items():
        cur.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))

    # Superadmin user (als nog niet bestaat)
    cur.execute("SELECT id FROM users WHERE email=?", (SUPER_EMAIL,))
    row = cur.fetchone()
    if not row:
        temp_pw = secrets.token_urlsafe(16)
        pw_hash = generate_password_hash(temp_pw)
        cur.execute("""
            INSERT INTO users(username,email,pw_hash,is_admin,is_superadmin,notify_enabled,created_at)
            VALUES(?,?,?,?,?,?,?)
        """, (SUPER_USERNAME, SUPER_EMAIL, pw_hash, 1, 1, 1, datetime.now().isoformat(timespec="seconds")))
        conn.commit()
        print("Superadmin aangemaakt:")
        print(f"  user: {SUPER_USERNAME}")
        print(f"  mail: {SUPER_EMAIL}")
        print(f"  tijdelijk wachtwoord: {temp_pw}")
        print("Log direct in en wijzig het wachtwoord + zet 2FA aan.")
    else:
        print("DB bestaat al; superadmin bestaat al (of is eerder aangemaakt).")

    conn.close()

if __name__ == "__main__":
    main()
