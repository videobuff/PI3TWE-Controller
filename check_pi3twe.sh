#!/bin/bash
# PI3TWE Backend Health Check
# Gebruik: sudo ./check_pi3twe.sh

echo "=== PI3TWE Backend Status Check ==="
echo ""

# 1. Service status
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "1. SERVICE STATUS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
systemctl status pi3twe-backend.service --no-pager -l | head -20
echo ""

# 2. Process check
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "2. RUNNING PROCESSES"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
ps aux | grep -E "(gunicorn|python.*app\.py)" | grep -v grep || echo "⚠ Geen processen gevonden"
echo ""

# 3. Port check
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "3. LISTENING PORTS (3000/3001)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
ss -tlnp 2>/dev/null | grep -E ":(3000|3001)" || echo "⚠ Geen listeners"
echo ""

# 4. Database check
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "4. MAIN DATABASE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ -f "/srv/pi3twe/app/pi3twe.db" ]; then
    ls -lh /srv/pi3twe/app/pi3twe.db
    echo ""
    echo "Tables:"
    sqlite3 /srv/pi3twe/app/pi3twe.db "SELECT name FROM sqlite_master WHERE type='table';" | sed 's/^/  - /'
    echo ""
    echo "Users:"
    sqlite3 /srv/pi3twe/app/pi3twe.db "SELECT id, username, email, is_admin, is_superadmin, is_active FROM users;" | column -t -s '|'
else
    echo "⚠ Database niet gevonden"
fi
echo ""

# 5. Monitor DB
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "5. MONITOR DATABASE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ -f "/srv/pi3twe/data/monitor.db" ]; then
    ls -lh /srv/pi3twe/data/monitor.db
    echo ""
    echo "Laatste metingen per sensor:"
    sqlite3 /srv/pi3twe/data/monitor.db << 'SQL'
SELECT 
    source,
    COUNT(*) as total_records,
    datetime(MAX(ts), 'unixepoch') as last_measurement,
    CASE 
        WHEN source IN ('int','ext') THEN printf('temp=%.1f°C hum=%d%%', 
            (SELECT temp FROM measurements WHERE source=m.source ORDER BY ts DESC LIMIT 1),
            (SELECT hum FROM measurements WHERE source=m.source ORDER BY ts DESC LIMIT 1))
        WHEN source = 'cpu' THEN printf('temp=%.1f°C load=%.1f%%',
            (SELECT temp FROM measurements WHERE source=m.source ORDER BY ts DESC LIMIT 1),
            (SELECT hum FROM measurements WHERE source=m.source ORDER BY ts DESC LIMIT 1))
        ELSE printf('value=%.2f',
            (SELECT temp FROM measurements WHERE source=m.source ORDER BY ts DESC LIMIT 1))
    END as last_value
FROM measurements m
GROUP BY source
ORDER BY source;
SQL
else
    echo "⚠ Monitor DB niet gevonden"
fi
echo ""

# 6. DHT sensors check
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "6. DHT11 SENSORS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Expected GPIO pins:"
echo "  INT: GPIO26 (BCM) = Physical Pin 37"
echo "  EXT: GPIO20 (BCM) = Physical Pin 38"
echo ""
if [ -f "/srv/pi3twe/data/monitor.db" ]; then
    echo "Recent INT/EXT readings:"
    sqlite3 /srv/pi3twe/data/monitor.db << 'SQL'
SELECT 
    source,
    datetime(ts, 'unixepoch', 'localtime') as timestamp,
    CASE WHEN temp IS NULL THEN 'xx.x' ELSE printf('%.1f', temp) END as temp_c,
    CASE WHEN hum IS NULL THEN 'xx' ELSE printf('%d', CAST(hum as INTEGER)) END as hum_pct
FROM measurements 
WHERE source IN ('int', 'ext')
ORDER BY ts DESC
LIMIT 10;
SQL
fi
echo ""

# 7. GPIO status
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "7. GPIO STATUS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Relay (GPIO27): $(gpio -g read 27 2>/dev/null || echo 'N/A') (1=ON, 0=OFF)"
echo "Button (GPIO23): $(gpio -g read 23 2>/dev/null || echo 'N/A') (0=PRESSED, 1=RELEASED)"
echo ""

# 8. Recent audit log
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "8. RECENT EVENTS (audit log)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ -f "/srv/pi3twe/app/pi3twe.db" ]; then
    sqlite3 /srv/pi3twe/app/pi3twe.db << 'SQL'
SELECT ts, event, details 
FROM audit_log 
ORDER BY id DESC 
LIMIT 15;
SQL
fi
echo ""

# 9. Systemd logs (laatste 30 regels)
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "9. RECENT LOGS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
journalctl -u pi3twe-backend.service -n 30 --no-pager
echo ""

# 10. API test
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "10. API REACHABILITY TEST"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if curl -s -m 2 http://localhost:3000/ >/dev/null 2>&1; then
    echo "✓ Backend antwoordt op http://localhost:3000/"
    echo ""
    echo "API /state response:"
    curl -s http://localhost:3000/api/state | python3 -m json.tool 2>/dev/null || echo "JSON parse error"
else
    echo "✗ Backend niet bereikbaar"
fi
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Check completed: $(date)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
