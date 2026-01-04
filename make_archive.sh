#!/usr/bin/env bash
# =============================================================================
# File: make_archive.sh
# Generated: 2026-01-01 (Europe/Amsterdam)
# Description:
#   Creates a full PI3TWE project archive including:
#   - Flask backend (/srv/pi3twe/app)
#   - TFT application
#   - Apache HTML frontend (/var/www/pi3twe)
#   - systemd service files
#   Secrets are excluded by default.
# =============================================================================

set -euo pipefail

PROJECT_DIR="/srv/pi3twe"
APP_DIR="${PROJECT_DIR}/app"
WWW_DIR="/var/www/pi3twe"
OUT_DIR="${PROJECT_DIR}/archive"
TS="$(date +%Y%m%d_%H%M%S)"
ARCHIVE="${OUT_DIR}/pi3twe_full_archive_${TS}.tar.gz"

mkdir -p "${OUT_DIR}"

# Include database snapshot? (set to "no" if DB contains secrets)
INCLUDE_DB="yes"

TMP_LIST="$(mktemp)"
trap 'rm -f "${TMP_LIST}"' EXIT

add_if_exists () {
  local p="$1"
  if [ -e "$p" ]; then
    echo "${p#/}" >> "${TMP_LIST}"
  fi
}

# --- Backend ---
add_if_exists "${APP_DIR}/app.py"
add_if_exists "${APP_DIR}/tft_app_fb.py"
add_if_exists "${APP_DIR}/requirements.txt"
add_if_exists "${APP_DIR}/README_project_overzicht.md"
add_if_exists "${APP_DIR}/schema.sql"
add_if_exists "${APP_DIR}/config.py"
add_if_exists "${APP_DIR}/wsgi.py"

if [ "${INCLUDE_DB}" = "yes" ]; then
  add_if_exists "${APP_DIR}/db.sqlite3"
fi

# --- Frontend (Apache HTML) ---
if [ -d "${WWW_DIR}" ]; then
  echo "var/www/pi3twe" >> "${TMP_LIST}"
fi

# --- systemd services ---
add_if_exists "/etc/systemd/system/pi3twe.service"
add_if_exists "/etc/systemd/system/pi3twe-tft.service"

# Create archive
tar -C "/" \
  --exclude="srv/pi3twe/app/secrets/*" \
  --exclude="**/*.key" \
  --exclude="**/*.pem" \
  --exclude="**/__pycache__/**" \
  --exclude="**/*.pyc" \
  -czf "${ARCHIVE}" -T "${TMP_LIST}"

echo
echo "Archive created:"
echo "  ${ARCHIVE}"
echo
echo "Included paths:"
sed 's/^/  - \//' "${TMP_LIST}"
echo
echo "Secrets excluded by default."
