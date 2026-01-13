#!/usr/bin/env python3
# ======================================================
# File: /srv/pi3twe/app/wsgi.py
# Generated: 2026-01-06 (Europe/Amsterdam)
# Description: WSGI entrypoint for Gunicorn (imports Flask app)
# ======================================================

from app import app, init_for_gunicorn

init_for_gunicorn()