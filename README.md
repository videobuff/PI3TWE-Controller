# PI3TWE Controller

**Platform:** Raspberry Pi 4+  
**Versie:** v3.1.0  
**Status:** Operationeel, productie geschikt  
**Doel:** Stand-alone controller voor repeater beheer met lokale UI, web frontend, monitoring en beveiliging

![front-2026](https://github.com/user-attachments/assets/3cc46376-42ee-4468-aa1d-5b9d58eb03b0)

---

## Inhoudsopgave

1. [Projectdoel](#1-projectdoel)
2. [Architectuuroverzicht](#2-architectuuroverzicht)
3. [Services](#3-services)
4. [Backend (Flask)](#4-backend-flask)
5. [Frontend (Web UI)](#5-frontend-web-ui)
6. [TFT-scherm (Framebuffer UI)](#6-tft-scherm-framebuffer-ui)
7. [Monitoring & Database](#7-monitoring--database)
8. [Grafana Dashboard](#8-grafana-dashboard)
9. [Kalibratie Systeem](#9-kalibratie-systeem)
10. [Multi-Network Toegang](#10-multi-network-toegang)
11. [Gebruikersbeheer & Authenticatie](#11-gebruikersbeheer--authenticatie)
12. [Hardware-integratie](#12-hardware-integratie)
13. [Beveiliging & Hardening](#13-beveiliging--hardening)
14. [Installatie & Configuratie](#14-installatie--configuratie)
15. [Bestandsstructuur](#15-bestandsstructuur)
16. [Onderhoud](#16-onderhoud)

---

## 1. Projectdoel

Het PI3TWE-project realiseert een **betrouwbare, veilige en autonome controller** voor een repeaterinstallatie op locatie, met:

- Lokale en externe bediening via web en fysieke knop
- Multi-network toegang (thuisnetwerk, MiFi, Hamnet)
- Gebruikersauthenticatie met optionele 2FA (TOTP)
- Relaisbesturing met cooldown-bescherming
- Continue sensormonitoring met kalibratie
- Real-time Grafana dashboards met kiosk mode
- Lokale visuele feedback via TFT-scherm
- Minimale afhankelijkheid van externe diensten

Het systeem is ontworpen voor **onbemande werking** met automatische crash recovery en werkt op meerdere netwerken zonder herconfiguratie.

---

## 2. Architectuuroverzicht
```
┌─────────────────────────────────────────────────────────────────┐
│                        Raspberry Pi 4                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │    Nginx     │    │    Flask     │    │ DHT Logger   │      │
│  │   :80/:443   │───▶│   :3001      │    │  (service)   │      │
│  │ (HTTP/HTTPS) │    │ (localhost)  │    │              │      │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘      │
│         │                   │                   │               │
│         │                   ▼                   ▼               │
│         │            ┌──────────────────────────────┐           │
│         │            │        SQLite Databases      │           │
│         │            │  - pi3twe.db (users/audit)   │           │
│         │            │  - monitor.db (sensor data)  │           │
│         │            └──────────────────────────────┘           │
│         │                          │                            │
│         ▼                          ▼                            │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │  Grafana     │    │   DHT11 x2   │    │    Relais    │      │
│  │  :3000       │    │  INT / EXT   │    │   (GPIO27)   │      │
│  │  (kiosk)     │    │  (GPIO26/20) │    │              │      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
│                                                                 │
│  ┌──────────────┐                                               │
│  │  TFT 3.5"    │                                               │
│  │  (SPI/FB)    │◀───── /api/state ──────────┘                 │
│  └──────────────┘                                               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

External Access:
  https://repeater.pi3twe.nl/          → Main interface
  https://repeater.pi3twe.nl/grafana/  → Grafana dashboards

Local Access (any network):
  http://[local-ip]/                   → Main interface  
  http://[local-ip]/grafana/           → Grafana dashboards
```

### Architectuur v2.1.1

**Belangrijkste kenmerken:**
- 🌐 **Multi-network support** - Werkt op thuisnetwerk, MiFi, Hamnet zonder aanpassing
- 📊 **Grafana dashboards** - SQLite datasource met real-time visualisatie
- 🔐 **Kiosk mode** - Anonymous Grafana access voor publieke displays
- ⚡ **Snelle monitoring** - 15 seconden sensor interval
- 🔄 **Auto-failover** - WiFi neemt over bij ethernet disconnect

| Component | Functie | Data Flow |
|-----------|---------|-----------|
| **dht_logger.py** | Sensor monitoring + kalibratie | GPIO → SQLite |
| **app.py** | Web API + relay control | SQLite → JSON API |
| **tft_app_fb.py** | Lokale display | API → Framebuffer |
| **Nginx** | Multi-network routing | HTTP(S) → Reverse Proxy |
| **Grafana** | Visualisatie + dashboards | SQLite → Web UI |

---

## 3. Services

Het systeem bestaat uit **4 onafhankelijke systemd services**:

### 3.1 dht-logger.service

**Functie:** Continue sensor monitoring met kalibratie  
**Interval:** 15 seconden  
**Restart:** Automatisch bij crash  

**Wat wordt gemonitord:**
- DHT11 INT (GPIO 26) - Binnentemperatuur en luchtvochtigheid
- DHT11 EXT (GPIO 20) - Buitentemperatuur en luchtvochtigheid  
- CPU temperatuur en load average
- Repeater status (ON AIR / STAND BY)

**Database writes:**
```
Elke 15 sec → 4 records naar monitor.db:
- int:  temp=17.9°C, hum=40%
- ext:  temp=17.3°C, hum=39%
- cpu:  temp=46.3°C, hum=0.4 (load avg)
- status: 0 (STAND BY) of 1 (ON AIR)
```

### 3.2 pi3twe.service

**Functie:** Flask web API + relay control  
**Poort:** 127.0.0.1:3001 (localhost only)  
**Restart:** Automatisch bij crash  

**Functionaliteit:**
- JSON API endpoints
- Gebruikersauthenticatie
- Relay control (GPIO 27)
- Kalibratie API
- WAN IP detection (zonder errors bij offline)

### 3.3 pi3twe-tft.service

**Functie:** TFT display UI  
**Device:** `/dev/fb1` (480×320 framebuffer)  
**Restart:** Automatisch bij crash  

**Weergave:**
- Logo en titel
- INT/EXT sensor waarden (GEKALIBREERD)
- CPU temp/load
- Repeater status
- Uptime of cooldown timer

### 3.4 grafana-server.service

**Functie:** Data visualisatie en monitoring  
**Poort:** 127.0.0.1:3000 (localhost only)  
**Access:** Via nginx reverse proxy op `/grafana/`

**Features:**
- Real-time dashboards met 15s refresh
- SQLite datasource (frser-sqlite-datasource plugin)
- Anonymous access in kiosk mode
- TV mode voor publieke displays

---

## 4. Backend (Flask)

### 4.1 Kenmerken
- Luistert alleen op `127.0.0.1:3001`
- JSON-only API responses
- Gunicorn WSGI server (1 worker, 4 threads)
- Sessies via secure cookies
- **SCHRIJFT NIET naar monitor.db** (alleen lezen)
- Error-resilient WAN IP detection

### 4.2 Databases

**pi3twe.db** - Applicatie data:
- `users` - Gebruikersbeheer
- `settings` - Configuratie + **kalibratie offsets**
- `audit_log` - Audit trail

**monitor.db** - Sensor data (ALLEEN LEZEN):
- `measurements` - Sensor metingen van dht_logger.py

### 4.3 API Endpoints

| Endpoint | Methode | Functie |
|----------|---------|---------|
| `/api/state` | GET | Systeem status (leest monitor.db) |
| `/api/repeater/on` | POST | Repeater aan |
| `/api/repeater/off` | POST | Repeater uit |
| `/api/login` | POST | Authenticatie |
| `/api/logout` | POST | Sessie beëindigen |
| `/api/admin/users` | GET/POST | Gebruikersbeheer |
| `/api/admin/calibration` | GET/POST | Kalibratie beheer |
| `/api/fail2ban` | GET | Fail2ban status |

---

## 5. Frontend (Web UI)

### 5.1 Locatie
```
/var/www/pi3twe/
└── index.html  (58KB, relatieve URLs)
```

### 5.2 Functie
- Responsive webinterface
- Login/logout met 2FA ondersteuning
- Repeater bediening
- Status weergave (real-time via `/api/state`)
- **Admin kalibratie interface**
- **Relatieve Grafana links** - Werken op elk netwerk

### 5.3 Multi-Network Support

**Automatische URL aanpassing:**
```html
<!-- Relatieve URL - werkt overal -->
<a href="/grafana/d/pi3twe-monitor?kiosk">Monitor</a>
```

**Toegang via:**
- `https://repeater.pi3twe.nl/` (extern)
- `http://192.168.2.92/` (thuisnetwerk ethernet)
- `http://192.168.1.102/` (MiFi WiFi)
- `http://44.137.69.132/` (Hamnet - toekomstig)

---

## 6. TFT-scherm (Framebuffer UI)

### 6.1 Hardware
- 3.5 inch TFT (480×320)
- SPI interface  
- Geen X11, direct framebuffer (`/dev/fb1`)

### 6.2 Software
- `tft/tft_app_fb.py`
- Systemd service: `pi3twe-tft.service`
- Haalt data via `/api/state` (localhost)
- Refresh: 2.5 seconden
- **Geen curl errors meer bij offline**

### 6.3 Weergave
- PI3TWE logo en titel
- **Gekalibreerde** INT/EXT temp en humidity
- CPU temperatuur en load percentage
- Uptime of cooldown timer
- Kleurcodering (groen/oranje/rood)
- Repeater status (ON AIR / STAND BY)
- External IP (of leeg bij offline)

---

## 7. Monitoring & Database

### 7.1 Database Schema

**monitor.db** (`/srv/pi3twe/app/monitor.db`):
```sql
CREATE TABLE measurements (
    ts     INTEGER NOT NULL,  -- Unix timestamp (UTC)
    source TEXT NOT NULL,      -- int, ext, cpu, status
    temp   REAL,               -- Temperatuur (1 decimaal) of NULL
    hum    REAL,               -- Humidity/load (1 decimaal) of NULL  
    status INTEGER             -- 0=STAND BY, 1=ON AIR (alleen voor source=status)
);

CREATE INDEX idx_measurements_src_ts ON measurements(source, ts);
```

**Data per source:**

| Source | temp | hum | status | Beschrijving |
|--------|------|-----|--------|--------------|
| int | 17.9°C | 40% | NULL | INT sensor (GEKALIBREERD) |
| ext | 17.3°C | 39% | NULL | EXT sensor (GEKALIBREERD) |
| cpu | 46.3°C | 0.4 | NULL | CPU temp + load average |
| status | NULL | NULL | 0 of 1 | Repeater status |

**Retentie:** 3 maanden (automatische cleanup bij dht_logger start)

### 7.2 Query Voorbeelden
```bash
# Laatste metingen
sqlite3 /srv/pi3twe/app/monitor.db \
  "SELECT source, datetime(ts,'unixepoch','localtime'), 
   round(temp,1), round(hum,1), status 
   FROM measurements ORDER BY ts DESC LIMIT 20;"

# Metingen laatste uur
sqlite3 /srv/pi3twe/app/monitor.db \
  "SELECT COUNT(*) FROM measurements 
   WHERE ts > strftime('%s','now','-1 hour');"

# Database grootte
ls -lh /srv/pi3twe/app/monitor.db
du -h /srv/pi3twe/app/monitor.db*
```

---

## 8. Grafana Dashboard

### 8.1 Configuratie

**Datasource:** SQLite (`frser-sqlite-datasource` plugin v3.8.2)  
**Database:** `/srv/pi3twe/app/monitor.db`  
**Access:** Read-only voor grafana user

**Datasource setup:**
```yaml
# /etc/grafana/provisioning/datasources/sqlite-monitor.yaml
apiVersion: 1
datasources:
  - name: PI3TWE Monitor SQLite
    type: frser-sqlite-datasource
    access: direct
    isDefault: true
    jsonData:
      path: /srv/pi3twe/app/monitor.db
```

### 8.2 Dashboard: PI3TWE Monitor

**UID:** `pi3twe-monitor`  
**Panels:** 9 totaal (3 stat + 6 time series)  
**Refresh:** 15 seconden (synced met sensor interval)

**Panel overzicht:**

| Panel | Type | Query | Beschrijving |
|-------|------|-------|--------------|
| Repeater Status | Stat | `SELECT status FROM measurements WHERE source='status' ORDER BY ts DESC LIMIT 1` | ON AIR (groen) / STAND BY (oranje) |
| CPU Temperature | Stat | `SELECT temp FROM measurements WHERE source='cpu' AND temp IS NOT NULL ORDER BY ts DESC LIMIT 1` | Actuele CPU temp |
| CPU Load | Stat | `SELECT hum FROM measurements WHERE source='cpu' AND hum IS NOT NULL ORDER BY ts DESC LIMIT 1` | Load average |
| INT Temperature | Stat | `SELECT temp FROM measurements WHERE source='int' AND temp IS NOT NULL ORDER BY ts DESC LIMIT 1` | INT sensor temp |
| INT Humidity | Stat | `SELECT hum FROM measurements WHERE source='int' AND hum IS NOT NULL ORDER BY ts DESC LIMIT 1` | INT sensor humidity |
| EXT Temperature | Stat | `SELECT temp FROM measurements WHERE source='ext' AND temp IS NOT NULL ORDER BY ts DESC LIMIT 1` | EXT sensor temp |
| EXT Humidity | Stat | `SELECT hum FROM measurements WHERE source='ext' AND hum IS NOT NULL ORDER BY ts DESC LIMIT 1` | EXT sensor humidity |
| CPU Metrics | Time Series (dual axis) | 2 queries voor temp + load | CPU temp en load history |
| Environmental | Time Series (dual axis) | 4 queries voor int/ext | INT/EXT temp en humidity history |

**Query template voor time series:**
```sql
SELECT 
  ts as time,
  temp as value
FROM measurements
WHERE source = 'int'
  AND temp IS NOT NULL
  AND ts >= $__from / 1000
  AND ts <= $__to / 1000
ORDER BY ts
```

**Grafana variabelen:**
- `$__from` - Dashboard start tijd (milliseconds)
- `$__to` - Dashboard eind tijd (milliseconds)
- Delen door 1000: conversie ms → seconds voor SQLite timestamps

### 8.3 Anonymous Access (Kiosk Mode)

**Configuratie:** `/etc/grafana/grafana.ini`
```ini
[auth.anonymous]
enabled = true
org_name = Main Org.
org_role = Viewer
hide_version = true
```

**Kiosk URLs:**
```
# Met Grafana menu
http://[ip]/grafana/d/pi3twe-monitor?kiosk

# Volledig scherm (TV mode)
http://[ip]/grafana/d/pi3twe-monitor?kiosk=tv

# Met auto-refresh en theme
http://[ip]/grafana/d/pi3twe-monitor?kiosk&refresh=30s&theme=dark
```

**Use cases:**
- iPad als permanent status display
- TV scherm in shack
- Publieke monitoring zonder login

### 8.4 Troubleshooting

**Grafana niet bereikbaar:**
```bash
# Check service
sudo systemctl status grafana-server

# Check poort
sudo netstat -tlnp | grep 3000

# Test lokaal
curl -I http://localhost:3000/grafana/

# Check logs
sudo journalctl -u grafana-server -f
```

**Geen data in panels:**
```bash
# Check datasource
curl -I http://localhost:3000/api/datasources

# Test query direct
sqlite3 /srv/pi3twe/app/monitor.db \
  "SELECT COUNT(*) FROM measurements WHERE ts > strftime('%s','now','-1 hour');"

# Check Grafana permissions
sudo ls -la /srv/pi3twe/app/monitor.db
# grafana user moet in pi3twegrp group zitten
```

---

## 9. Kalibratie Systeem

### 9.1 Overzicht

DHT11 sensoren kunnen onderling verschillen vertonen. Het kalibratie systeem corrigeert deze verschillen.

**Opslag:** `pi3twe.db` → `settings` tabel

| Setting Key | Waarde | Bereik | Eenheid |
|-------------|--------|--------|---------|
| cal_int_temp_offset | -0.5 | ±10 | °C |
| cal_int_hum_offset | 0.0 | ±20 | % |
| cal_ext_temp_offset | +0.5 | ±10 | °C |
| cal_ext_hum_offset | 0.0 | ±20 | % |

**Formule:**
```
Gekalibreerde waarde = Ruwe sensor waarde + offset
```

### 9.2 Via Web Interface

1. Login als admin
2. Navigeer naar **Admin** → **Sensor kalibratie**
3. Pas offsets aan
4. Klik **Opslaan**
5. Wacht max 30 seconden voor toepassing

### 9.3 Via CLI
```bash
# Bekijk huidige offsets
sqlite3 /srv/pi3twe/app/pi3twe.db \
  "SELECT * FROM settings WHERE key LIKE 'cal_%';"

# Wijzig INT temp offset
sqlite3 /srv/pi3twe/app/pi3twe.db \
  "UPDATE settings SET value='-0.6' 
   WHERE key='cal_int_temp_offset';"

# Reset alle offsets
sqlite3 /srv/pi3twe/app/pi3twe.db \
  "UPDATE settings SET value='0.0' 
   WHERE key LIKE 'cal_%';"
```

---

## 10. Multi-Network Toegang

### 10.1 Overzicht

Het systeem ondersteunt **meerdere netwerken simultaan** zonder herconfiguratie:

| Netwerk | Interface | IP Voorbeeld | Gebruik |
|---------|-----------|--------------|---------|
| Thuisnetwerk | end0 (ethernet) | 192.168.2.92 | Primair, altijd actief |
| MiFi WiFi | wlan0 | 192.168.1.102 | Backup, portable operatie |
| Hamnet | end0/wlan0 | 44.137.69.132 | Radioamateur netwerk |
| Internet | WAN | 81.207.216.66 | Externe toegang via DNS |

### 10.2 NetworkManager Configuratie

**Auto-connect priorities:**
```bash
# Ethernet hoogste prioriteit (999)
nmcli connection modify "Wired connection 1" \
  connection.autoconnect-priority 999

# MiFi WiFi tweede (100)
nmcli connection modify "DNA-Mokkula-0D06" \
  connection.autoconnect-priority 100

# Thuisnetwerk WiFi derde (20)
nmcli connection modify "HomeWiFi" \
  connection.autoconnect-priority 20

# Bekijk prioriteiten
nmcli -f NAME,AUTOCONNECT-PRIORITY connection show
```

**Gedrag:**
- Ethernet actief → WiFi uit (dispatcher script)
- Ethernet uit → WiFi aan (hoogste prioriteit eerst)
- Automatische failover binnen 30 seconden

### 10.3 Nginx Multi-Network Routing

**Configuratie:**

**/etc/nginx/sites-available/repeater-complete** (externe HTTPS):
```nginx
# HTTP redirect
server {
    listen 80;
    server_name repeater.pi3twe.nl;
    return 301 https://$host$request_uri;
}

# HTTPS server
server {
    listen 443 ssl;
    http2 on;
    server_name repeater.pi3twe.nl;
    
    ssl_certificate /etc/letsencrypt/live/repeater.pi3twe.nl/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/repeater.pi3twe.nl/privkey.pem;
    
    root /var/www/pi3twe;
    index index.html;
    
    location / {
        try_files $uri $uri/ =404;
    }
    
    location /api/ {
        proxy_pass http://127.0.0.1:3001;
        proxy_set_header Host $host;
    }
    
    location /grafana/ {
        proxy_pass http://127.0.0.1:3000/grafana/;
        proxy_set_header Host $host;
    }
}
```

**/etc/nginx/sites-available/local-http** (lokale HTTP):
```nginx
server {
    listen 80;
    server_name 192.168.2.92 192.168.2.94 192.168.1.102 44.137.69.132 test1.pi2non-ebt;
    
    root /var/www/pi3twe;
    index index.html;
    
    location / {
        try_files $uri $uri/ =404;
    }
    
    location /api/ {
        proxy_pass http://127.0.0.1:3001;
        proxy_set_header Host $host;
    }
    
    location /grafana/ {
        proxy_pass http://127.0.0.1:3000/grafana/;
        proxy_set_header Host $host;
    }
}
```

**Actieve configs:**
```bash
ls -la /etc/nginx/sites-enabled/
# repeater-complete -> Externe HTTPS
# local-http        -> Lokale HTTP (alle IPs)
```

### 10.4 Known Issues & Workarounds

**WireGuard Routing Conflict (OPGELOST):**
- **Probleem:** WireGuard VPN kaapte externe HTTPS responses
- **Symptoom:** Externe toegang timeout, lokaal werkt wel
- **Oplossing:** WireGuard disabled (`systemctl disable wg-quick@wg0`)
- **Impact:** Geen VPN naar Hamnet/MiFi momenteel

**NAT Loopback:**
- Van binnen lokaal netwerk kun je NIET naar publiek IP
- Test externe toegang ALLEEN via 4G/andere locatie
- Lokaal altijd via direct IP gebruiken

### 10.5 Testing Multi-Network

**Test script:**
```bash
#!/bin/bash
# Test alle toegangspunten

echo "=== PI3TWE Multi-Network Test ==="

# Lokaal ethernet
curl -I http://192.168.2.92/ 2>&1 | head -5

# MiFi WiFi (als actief)
curl -I http://192.168.1.102/ 2>&1 | head -5

# Extern (alleen via 4G/andere locatie!)
# curl -I https://repeater.pi3twe.nl/

# Grafana
curl -I http://localhost:3000/grafana/ 2>&1 | head -5

echo "Done!"
```

---

## 11. Gebruikersbeheer & Authenticatie

### 11.1 Login
- Gebruikersnaam/email + wachtwoord
- Persistente sessies
- Optionele 2FA (TOTP)

### 11.2 Rollen
- **Superadmin** - Volledige toegang, kan users verwijderen
- **Admin** - Gebruikersbeheer + kalibratie
- **User** - Basis bediening

### 11.3 2FA (TOTP)
- Per gebruiker instelbaar
- Google Authenticator compatible
- Admin kan 2FA resetten voor andere users

---

## 12. Hardware-integratie

### 12.1 GPIO Pinout

| Functie | GPIO (BCM) | Physical Pin | Richting |
|---------|------------|--------------|----------|
| Relais | 27 | 13 | OUT (HIGH=AAN) |
| Button | 23 | 16 | IN (pull-up, active-low) |
| DHT11 INT | 26 | 37 | IN (met 4.7kΩ pull-up) |
| DHT11 EXT | 20 | 38 | IN (met 4.7kΩ pull-up) |

### 12.2 Relais
- Active-high schakeling (HIGH = repeater AAN)
- Cooldown bescherming (standaard 30s, configureerbaar)
- Fail-safe: AAN bij boot/herstart
- Status via web, API en TFT

### 12.3 DHT11 Sensoren
- **INT:** Binnentemperatuur (kasttemperatuur)
- **EXT:** Buitentemperatuur (omgevingstemperatuur)
- Pull-up weerstand: 4.7kΩ tussen data pin en VCC
- Best-effort: geen crash bij ontbrekende sensor
- **Alleen dht_logger.py raakt de sensoren aan!**

### 12.4 TFT Display
- SPI interface (CE0)
- Framebuffer: `/dev/fb1`
- Resolutie: 480×320
- Driver: `fbtft_device`

### 12.5 Button
- Fysieke pushbutton tussen GPIO 23 en GND
- Interne pull-up enabled
- Debounce: 150ms hardware + 300ms software
- Respecteert cooldown
- Werkt onafhankelijk van webinterface

---

## 13. Beveiliging & Hardening

### 13.1 Fail2ban

**Actieve jails:**
- `sshd` - SSH brute force bescherming
- `nginx-bad-request` - Malformed requests
- `nginx-botsearch` - Bot scanning
- `nginx-http-auth` - Auth failures  
- `nginx-limit-req` - Rate limiting

**Whitelist:**
- `127.0.0.1/8` (localhost)
- `::1` (IPv6 localhost)
- `192.168.2.0/24` (lokaal LAN)

### 13.2 Netwerk
- Flask **alleen** op localhost (127.0.0.1:3001)
- Grafana **alleen** op localhost (127.0.0.1:3000)
- Nginx als enige externe toegang (HTTP/HTTPS)
- Geen directe toegang tot databases
- Alle services internal only

### 13.3 Secrets Management

**Locatie:** `/srv/pi3twe/app/secrets/`
```
secrets/
├── flask_secret.key       # Flask session secret
├── tft_token.txt          # TFT auth token
└── msmtprc                # Mail config (optioneel)
```

**Permissies:** `600` (owner read/write only)  
**⚠️ NOOIT committen naar git!**

### 13.4 Service Isolation

- Elke service draait als `pi3twe` user
- Grafana draait als `grafana` user (in `pi3twegrp` group)
- Geen root rechten nodig (behalve GPIO setup)
- Separate restart policies
- Crashes beïnvloeden andere services niet

---

## 14. Installatie & Configuratie

### 14.1 Prerequisites

**OS:** Raspberry Pi OS Bookworm (Debian 12)

**System packages:**
```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv \
                 nginx sqlite3 fail2ban git curl \
                 grafana
```

**Enable interfaces:**
```bash
sudo raspi-config
# Interface Options → SPI: Enable
```

### 14.2 Python Environment
```bash
cd /srv/pi3twe/app
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 14.3 Database Initialisatie
```bash
# Applicatie database
python3 init_db.py

# Monitoring database (wordt automatisch aangemaakt door dht_logger)
```

### 14.4 Grafana Setup
```bash
# Install SQLite datasource plugin
sudo grafana-cli plugins install frser-sqlite-datasource

# Configure datasource
sudo cp grafana/datasource.yaml \
        /etc/grafana/provisioning/datasources/

# Add grafana user to pi3twegrp
sudo usermod -a -G pi3twegrp grafana

# Set database permissions
sudo chmod 644 /srv/pi3twe/app/monitor.db

# Enable anonymous access
sudo nano /etc/grafana/grafana.ini
# [auth.anonymous]
# enabled = true
# org_role = Viewer

# Restart Grafana
sudo systemctl restart grafana-server
```

### 14.5 Services Activeren
```bash
# DHT Logger (EERST starten)
sudo systemctl enable dht-logger
sudo systemctl start dht-logger

# Backend API
sudo systemctl enable pi3twe  
sudo systemctl start pi3twe

# TFT Display
sudo systemctl enable pi3twe-tft
sudo systemctl start pi3twe-tft

# Grafana (already enabled bij apt install)
sudo systemctl enable grafana-server
sudo systemctl start grafana-server

# Verify
sudo systemctl status dht-logger pi3twe pi3twe-tft grafana-server
```

### 14.6 Nginx Multi-Network Setup
```bash
# Disable default site
sudo rm /etc/nginx/sites-enabled/default

# Enable PI3TWE configs
sudo ln -s /etc/nginx/sites-available/repeater-complete \
           /etc/nginx/sites-enabled/
sudo ln -s /etc/nginx/sites-available/local-http \
           /etc/nginx/sites-enabled/

# Test en reload
sudo nginx -t
sudo systemctl reload nginx
```

### 14.7 NetworkManager Auto-Connect
```bash
# Set priorities
sudo nmcli connection modify "Wired connection 1" \
  connection.autoconnect-priority 999
sudo nmcli connection modify "DNA-Mokkula-0D06" \
  connection.autoconnect-priority 100
sudo nmcli connection modify "HomeWiFi" \
  connection.autoconnect-priority 20

# Verify
nmcli -f NAME,AUTOCONNECT-PRIORITY connection show
```

---

## 15. Bestandsstructuur
```
/srv/pi3twe/
├── app/
│   ├── app.py                    # Flask backend
│   ├── dht_logger.py             # Sensor monitoring service
│   ├── wsgi.py                   # Gunicorn entry point
│   ├── init_db.py                # Database setup
│   ├── requirements.txt          # Python dependencies
│   ├── git_all.sh                # Git helper
│   ├── cleanup_old_files.sh      # Maintenance script
│   ├── README.md                 # Deze file
│   ├── PI3TWE_MONITORING_SYSTEM.md  # Tech docs
│   ├── .venv/                    # Python virtual environment
│   ├── secrets/                  # Keys en tokens (NIET in git!)
│   │   ├── flask_secret.key
│   │   ├── tft_token.txt
│   │   └── msmtprc
│   ├── tft/
│   │   └── tft_app_fb.py         # TFT display app
│   ├── tools/
│   │   └── dht_test.py           # DHT11 troubleshooting tool
│   ├── webroot/
│   │   └── index.html            # Fallback page
│   ├── img/
│   │   └── logo.png              # PI3TWE logo
│   ├── pi3twe.db                 # Applicatie database
│   └── monitor.db                # Monitoring database

/var/www/pi3twe/
└── index.html                    # Main web interface (58KB)

/etc/nginx/sites-available/
├── repeater-complete             # Externe HTTPS
└── local-http                    # Lokale HTTP (alle IPs)

/etc/grafana/
├── grafana.ini                   # Grafana config
└── provisioning/
    └── datasources/
        └── sqlite-monitor.yaml   # SQLite datasource

/etc/systemd/system/
├── dht-logger.service            # DHT monitoring
├── pi3twe.service                # Flask backend
└── pi3twe-tft.service            # TFT display
```

---

## 16. Onderhoud

### 16.1 Logs Bekijken
```bash
# DHT Logger
sudo journalctl -u dht-logger -f

# Backend API
sudo journalctl -u pi3twe -f

# TFT Display
sudo journalctl -u pi3twe-tft -f

# Grafana
sudo journalctl -u grafana-server -f

# Nginx
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log

# Alle services combined
sudo journalctl -u dht-logger -u pi3twe -u pi3twe-tft -u grafana-server -f
```

### 16.2 Service Management
```bash
# Status check
sudo systemctl status dht-logger pi3twe pi3twe-tft grafana-server

# Restart
sudo systemctl restart dht-logger
sudo systemctl restart pi3twe
sudo systemctl restart pi3twe-tft
sudo systemctl restart grafana-server

# Stop (voor onderhoud)
sudo systemctl stop dht-logger pi3twe pi3twe-tft
```

### 16.3 Database Onderhoud
```bash
# Database grootte
ls -lh /srv/pi3twe/app/*.db
du -h /srv/pi3twe/app/monitor.db*

# Vacuum (compressie na cleanup)
sqlite3 /srv/pi3twe/app/monitor.db "VACUUM;"

# Check integrity
sqlite3 /srv/pi3twe/app/monitor.db "PRAGMA integrity_check;"

# Export data
sqlite3 /srv/pi3twe/app/monitor.db \
  ".mode csv" \
  ".output export_$(date +%Y%m%d).csv" \
  "SELECT * FROM measurements WHERE ts > strftime('%s','now','-7 days');"
```

### 16.4 Network Diagnostics
```bash
# Check actieve interfaces
ip addr show | grep -E "^[0-9]:|inet "

# Check routes
ip route show

# Check NetworkManager
nmcli device status
nmcli connection show

# Test toegang
curl -I http://192.168.2.92/
curl -I http://localhost:3000/grafana/
curl -I https://repeater.pi3twe.nl/  # Alleen via 4G!

# Check nginx
sudo nginx -t
sudo netstat -tlnp | grep nginx
```

### 16.5 Grafana Maintenance
```bash
# Check datasource
curl http://localhost:3000/api/datasources

# Test query
sqlite3 /srv/pi3twe/app/monitor.db \
  "SELECT COUNT(*) FROM measurements WHERE ts > strftime('%s','now','-1 hour');"

# Check permissions
sudo ls -la /srv/pi3twe/app/monitor.db
groups grafana  # Should include pi3twegrp

# Restart Grafana
sudo systemctl restart grafana-server
```

### 16.6 Git Workflow
```bash
cd /srv/pi3twe/app

# Quick commit + push
./git_all.sh "Beschrijving van wijzigingen"

# Of handmatig
git status
git add -A
git commit -m "Beschrijving"
git push origin main

# Tag release
git tag v2.1.1
git push --tags
```

---

## Changelog

### v2.1.1 (2026-02-02) - Multi-Network & Grafana Integration

**🌐 Multi-Network Support:**
- ✅ **Lokale toegang** - HTTP op elk IP (thuisnetwerk, MiFi, Hamnet)
- ✅ **Externe toegang** - HTTPS via repeater.pi3twe.nl
- ✅ **Relatieve URLs** - Grafana links werken op elk netwerk
- ✅ **NetworkManager priorities** - Auto-failover ethernet → WiFi
- ✅ **WireGuard disabled** - Oplossing voor routing conflict (blokkeerde externe HTTPS)

**📊 Grafana Dashboards:**
- ✅ **SQLite datasource** - frser-sqlite-datasource plugin
- ✅ **PI3TWE Monitor dashboard** - 9 panels met real-time data
- ✅ **Anonymous access** - Kiosk mode zonder login
- ✅ **15s refresh** - Synced met sensor interval
- ✅ **Dual-axis charts** - CPU metrics en environmental data

**🛠️ Bugfixes:**
- ✅ **TFT error handling** - Geen curl errors meer bij offline (_run_cmd fix)
- ✅ **Nginx multi-config** - Gescheiden externe en lokale toegang
- ✅ **File cleanup** - Oude backups en obsolete InfluxDB scripts verwijderd

**Nginx Configuratie:**
- `repeater-complete` - Externe HTTPS met SSL
- `local-http` - Lokale HTTP voor alle IPs (192.168.x.x, 44.137.69.132)

**Known Issues:**
- WireGuard VPN disabled (routing conflict met externe toegang)
- NAT loopback werkt niet (test extern alleen via 4G)

---

### v2.1.0 (2026-01-28) - DHT Logger Refactor

**🚀 Major Changes:**
- ✅ **Standalone dht_logger.py service** - Dedicated monitoring service
- ✅ **GPIO conflict opgelost** - Alleen dht_logger raakt sensoren aan
- ✅ **Kalibratie systeem** - Web + CLI interface voor sensor offsets
- ✅ **Auto-restart policies** - Alle services herstarten automatisch bij crash
- ✅ **15 sec monitoring interval** - 4x sneller dan voorheen
- ✅ **Database schema uitbreiding** - Status kolom voor repeater state
- ✅ **Gescheiden verantwoordelijkheden** - Logger schrijft, app.py leest

**Database:**
- SQLite only (InfluxDB verwijderd)
- `monitor.db` bevat alleen gekalibreerde waarden
- 3 maanden retentie met automatische cleanup

**Services:**
- `dht-logger.service` - Hardware monitoring (NIEUW)
- `pi3twe.service` - Web API (geen DHT code meer)
- `pi3twe-tft.service` - Display UI

---

### v2.0.x (2026-01-25)

- InfluxDB 3 Core integratie (verwijderd in v2.1.0)
- CPU load moving average

---

### v1.x (2026-01-17 - 2026-01-24)

- Initiële release
- DHT11 dual sensor support
- TFT framebuffer UI
- Basis monitoring

---

**Auteur:** PA0ESH  
**Callsign:** PI3TWE  
**Licentie:** MIT  
**Repository:** https://github.com/pa0esh/pi3twe-controller (private)  
**Tech Docs:** [PI3TWE_MONITORING_SYSTEM.md](PI3TWE_MONITORING_SYSTEM.md)  
**Website:** https://repeater.pi3twe.nl/
