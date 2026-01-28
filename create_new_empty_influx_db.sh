#!/usr/bin/env bash
set -euo pipefail

# ==============================
# Bestandsnaam : /srv/pi3twe/app/reset_influx_db.sh
# Gegenereerd  : 2026-01-25 23:55 (Europe/Amsterdam)
# Beschrijving : Reset InfluxDB v3 Core database naar vaste naam (standaard: pi3twe).
#                - Stop pi3twe.service (optioneel)
#                - Delete DB (als bestaat)
#                - Create DB opnieuw
#                - Smoke test: write_lp + query_sql
# ==============================

DB_NAME="${1:-pi3twe}"
INFLUX_URL="${INFLUX_URL:-http://127.0.0.1:8181}"
TOKEN_FILE="${TOKEN_FILE:-/srv/pi3twe/app/secrets/influxdb_token.txt}"
STOP_SERVICE="${STOP_SERVICE:-1}"   # 1 = stop/start pi3twe.service, 0 = niet doen

TOKEN="$(cat "$TOKEN_FILE" 2>/dev/null || true)"
if [[ -z "${TOKEN}" ]]; then
  echo "ERROR: Token leeg. Check: $TOKEN_FILE" >&2
  exit 1
fi

echo "Target DB: $DB_NAME"
echo "Influx URL: $INFLUX_URL"

if [[ "$STOP_SERVICE" == "1" ]]; then
  echo "Stopping pi3twe.service..."
  sudo systemctl stop pi3twe.service || true
fi

echo "List databases (before):"
curl -sS -X GET "$INFLUX_URL/api/v3/configure/database?format=pretty&show_deleted=true" \
  -H "Authorization: Bearer $TOKEN" || true
echo

echo "Deleting DB (if exists): $DB_NAME"
# InfluxDB v3 Core: delete via query param ?db=
curl -sS -X DELETE "$INFLUX_URL/api/v3/configure/database?db=$DB_NAME" \
  -H "Authorization: Bearer $TOKEN" || true
echo
echo "Waiting until DB is gone (max 20s)..."

# Poll: database list until DB is either absent or marked deleted=true
deadline=$((SECONDS+20))
while (( SECONDS < deadline )); do
  out="$(curl -sS -X GET "$INFLUX_URL/api/v3/configure/database?show_deleted=true" -H "Authorization: Bearer $TOKEN" || true)"
  # If DB name not present at all -> OK
  if ! echo "$out" | grep -q "\"$DB_NAME\""; then
    break
  fi
  # If present but marked deleted true -> OK
  if echo "$out" | grep -A2 "\"$DB_NAME\"" | grep -q "true"; then
    break
  fi
  sleep 1
done

echo "Creating DB: $DB_NAME"
curl -sS -X POST "$INFLUX_URL/api/v3/configure/database" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"db\":\"$DB_NAME\"}"
echo

echo "Smoke test: write one point"
ns="$(date +%s)000000000"
curl -sS -X POST "$INFLUX_URL/api/v3/write_lp?db=$DB_NAME" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: text/plain" \
  --data-binary "measurements,source=smoketest temp=21.5,hum=55 $ns" >/dev/null
echo "OK"

echo "Smoke test: query it back"
curl -sS -X POST "$INFLUX_URL/api/v3/query_sql" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"db\":\"$DB_NAME\",\"q\":\"SELECT time, source, temp, hum FROM measurements WHERE source='smoketest' ORDER BY time DESC LIMIT 5\"}"
echo

echo "List tables (should include iox.measurements + system tables):"
curl -sS -X POST "$INFLUX_URL/api/v3/query_sql" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"db\":\"$DB_NAME\",\"q\":\"SELECT table_schema, table_name FROM information_schema.tables WHERE table_type='BASE TABLE' ORDER BY table_schema, table_name\"}"
echo

if [[ "$STOP_SERVICE" == "1" ]]; then
  echo "Starting pi3twe.service..."
  sudo systemctl start pi3twe.service
fi

echo
echo "DONE. Active DB name stays: $DB_NAME"
