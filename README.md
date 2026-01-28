# PI3TWE Controller

**Platform:** Raspberry Pi 4+  
**Versie:** v2.1.0  
**Status:** Operationeel, productie geschikt  
**Doel:** Stand-alone controller voor repeater beheer met lokale UI, web frontend, monitoring en beveiliging

![front-2026](https://github.com/user-attachments/assets/3cc46376-42ee-4468-aa1d-5b9d58eb03b0)

---

## Inhoudsopgave

1. [Projectdoel](#1-projectdoel)
2. [Architectuuroverzicht](#2-architectuuroverzicht)
3. [Services](#3-services)
4. [Backend (Flask)](#4-backend-flask)
5. [Frontend (Apache HTML)](#5-frontend-apache-html)
6. [TFT-scherm (Framebuffer UI)](#6-tft-scherm-framebuffer-ui)
7. [Monitoring & Database](#7-monitoring--database)
8. [Kalibratie Systeem](#8-kalibratie-systeem)
9. [Gebruikersbeheer & Authenticatie](#9-gebruikersbeheer--authenticatie)
10. [Hardware-integratie](#10-hardware-integratie)
11. [Beveiliging & Hardening](#11-beveiliging--hardening)
12. [Installatie & Configuratie](#12-installatie--configuratie)
13. [Bestandsstructuur](#13-bestandsstructuur)
14. [Onderhoud](#14-onderhoud)

---

## 1. Projectdoel

Het PI3TWE-project realiseert een **betrouwbare, veilige en autonome controller** voor een repeaterinstallatie op locatie, met:

- Lokale en externe bediening via web en fysieke knop
- Gebruikersauthenticatie met optionele 2FA (TOTP)
- Relaisbesturing met cooldown-bescherming
- Continue sensormonitoring met kalibratie
- Real-time status via web, TFT en API
- Lokale visuele feedback via TFT-scherm
- Minimale afhankelijkheid van externe diensten

Het systeem is ontworpen voor **onbemande werking** met automatische crash recovery.

---

## 2. Architectuuroverzicht
```
┌─────────────────────────────────────────────────────────────────┐
│                        Raspberry Pi 3B+                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │   Apache     │    │    Flask     │    │ DHT Logger   │      │
│  │   :443       │───▶│   :3001      │    │  (service)   │      │
│  │  (HTTPS)     │    │ (localhost)  │    │              │      │
│  └──────────────┘    └──────┬───────┘    └──────┬───────┘      │
│                             │                   │               │
│                             ▼                   ▼               │
│                      ┌──────────────────────────────┐           │
│                      │        SQLite Databases      │           │
│                      │  - pi3twe.db (users/audit)   │           │
│                      │  - monitor.db (sensor data)  │           │
│                      └──────────────────────────────┘           │
│                                    │                            │
│                                    ▼                            │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │  TFT 3.5"    │    │   DHT11 x2   │    │    Relais    │      │
│  │  (SPI/FB)    │◀───│  INT / EXT   │    │   (GPIO27)   │      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Nieuwe Architectuur (v2.1.0)

**Belangrijkste wijziging:** Scheiding van concernsen - dedicated monitoring service

| Component | Functie | Data Flow |
|-----------|---------|-----------|
| **dht_logger.py** | Sensor monitoring + kalibratie | GPIO → SQLite |
| **app.py** | Web API + relay control | SQLite → JSON API |
| **tft_app_fb.py** | Lokale display | API → Framebuffer |
| **Apache** | HTTPS frontend | HTML → Reverse Proxy |

**Voordelen:**
- ✅ Geen GPIO conflicts meer
- ✅ Logger crasht niet de webserver
- ✅ Onafhankelijke restart policies
- ✅ Eenvoudiger debugging

---

## 3. Services

Het systeem bestaat uit **3 onafhankelijke systemd services**:

### 3.1 dht-logger.service ⭐ NIEUW v2.1.0

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

**Commando's:**
```bash
sudo systemctl status dht-logger
sudo systemctl restart dht-logger
sudo journalctl -u dht-logger -f
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
- Alarm monitoring

**Opmerking:** Schrijft NIET meer naar database - alleen lezen!

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

---

## 4. Backend (Flask)

### 4.1 Kenmerken
- Luistert alleen op `127.0.0.1:3001`
- JSON-only API responses
- Gunicorn WSGI server (1 worker, 4 threads)
- Sessies via secure cookies
- **SCHRIJFT NIET naar monitor.db** (alleen lezen)

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
| `/api/admin/calibration` | GET/POST | Kalibratie beheer ⭐ NIEUW |
| `/api/fail2ban` | GET | Fail2ban status |

---

## 5. Frontend (Apache HTML)

### 5.1 Locatie
```
/var/www/pi3twe/
└── index.html
```

### 5.2 Functie
- Responsive webinterface
- Login/logout met 2FA ondersteuning
- Repeater bediening
- Status weergave (real-time via `/api/state`)
- **Admin kalibratie interface** ⭐ NIEUW

### 5.3 Communicatie
- AJAX/fetch naar Flask backend via localhost proxy
- Apache als reverse proxy naar `:3001`
- Poll interval: ~2-3 seconden

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

### 6.3 Weergave
- PI3TWE logo en titel
- **Gekalibreerde** INT/EXT temp en humidity
- CPU temperatuur en load percentage
- Uptime of cooldown timer
- Kleurcodering (groen/oranje/rood)
- Repeater status (ON AIR / STAND BY)

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
```

### 7.3 Grafana (Toekomstig)

⚠️ **Status:** Nog te configureren

**Geplande features:**
- SQLite datasource plugin
- Real-time dashboards
- Historische trends
- Export mogelijkheden

---

## 8. Kalibratie Systeem ⭐ NIEUW v2.1.0

### 8.1 Overzicht

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

**Voorbeeld:**
```
Raw INT: 18.3°C → Offset: -0.5°C → Gecalibreerd: 17.8°C
Raw EXT: 16.8°C → Offset: +0.5°C → Gecalibreerd: 17.3°C
```

### 8.2 Via Web Interface

1. Login als admin op https://repeater.pi3twe.nl
2. Navigeer naar **Admin** → **Sensor kalibratie**
3. Pas offsets aan
4. Klik **Opslaan**
5. Wacht max 30 seconden voor toepassing:
   - 15s: dht_logger herlaadt offsets
   - 15s: nieuwe meting met nieuwe offsets

### 8.3 Via CLI
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

**Reload tijd:** Max 15 seconden (automatisch door dht_logger)

### 8.4 Implementatie Details

**In dht_logger.py:**
- Leest offsets uit `pi3twe.db` elke 15 seconden
- Past offsets toe **voor** database write
- Database bevat altijd gekalibreerde waarden

**In app.py:**
- API endpoints voor kalibratie beheer
- Leest gekalibreerde waarden uit `monitor.db`
- Schrijft NIET naar `monitor.db`

---

## 9. Gebruikersbeheer & Authenticatie

### 9.1 Login
- Gebruikersnaam/email + wachtwoord
- Persistente sessies
- Optionele 2FA (TOTP)

### 9.2 Rollen
- **Superadmin** - Volledige toegang, kan users verwijderen
- **Admin** - Gebruikersbeheer + kalibratie
- **User** - Basis bediening

### 9.3 2FA (TOTP)
- Per gebruiker instelbaar
- Google Authenticator compatible
- Admin kan 2FA resetten voor andere users

---

## 10. Hardware-integratie

### 10.1 GPIO Pinout

| Functie | GPIO (BCM) | Physical Pin | Richting |
|---------|------------|--------------|----------|
| Relais | 27 | 13 | OUT (HIGH=AAN) |
| Button | 23 | 16 | IN (pull-up, active-low) |
| DHT11 INT | 26 | 37 | IN (met 4.7kΩ pull-up) |
| DHT11 EXT | 20 | 38 | IN (met 4.7kΩ pull-up) |

### 10.2 Relais
- Active-high schakeling (HIGH = repeater AAN)
- Cooldown bescherming (standaard 30s, configureerbaar)
- Fail-safe: AAN bij boot/herstart
- Status via web, API en TFT

### 10.3 DHT11 Sensoren
- **INT:** Binnentemperatuur (kasttemperatuur)
- **EXT:** Buitentemperatuur (omgevingstemperatuur)
- Pull-up weerstand: 4.7kΩ tussen data pin en VCC
- Best-effort: geen crash bij ontbrekende sensor
- **Alleen dht_logger.py raakt de sensoren aan!**

### 10.4 TFT Display
- SPI interface (CE0)
- Framebuffer: `/dev/fb1`
- Resolutie: 480×320
- Driver: `fbtft_device`

### 10.5 Button
- Fysieke pushbutton tussen GPIO 23 en GND
- Interne pull-up enabled
- Debounce: 150ms hardware + 300ms software
- Respecteert cooldown
- Werkt onafhankelijk van webinterface

---

## 11. Beveiliging & Hardening

### 11.1 Fail2ban

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

### 11.2 Netwerk
- Flask **alleen** op localhost (127.0.0.1:3001)
- Apache/Nginx als enige externe toegang (HTTPS)
- Geen directe toegang tot databases
- Alle services internal only

### 11.3 Secrets Management

**Locatie:** `/srv/pi3twe/app/secrets/`
```
secrets/
├── flask_secret.key       # Flask session secret
├── tft_token.txt          # TFT auth token
└── msmtprc                # Mail config (optioneel)
```

**Permissies:** `600` (owner read/write only)  
**⚠️ NOOIT committen naar git!**

### 11.4 Service Isolation

- Elke service draait als `pi3twe` user
- Geen root rechten nodig (behalve GPIO setup)
- Separate restart policies
- Crashes beïnvloeden andere services niet

---

## 12. Installatie & Configuratie

### 12.1 Prerequisites

**OS:** Raspberry Pi OS Bookworm (Debian 12)

**System packages:**
```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv \
                 nginx sqlite3 fail2ban git curl
```

**Enable interfaces:**
```bash
sudo raspi-config
# Interface Options → SPI: Enable
# Interface Options → I2C: Enable (voor toekomstig gebruik)
```

### 12.2 Python Environment
```bash
cd /srv/pi3twe/app
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 12.3 Database Initialisatie
```bash
# Applicatie database
python3 init_db.py

# Monitoring database (wordt automatisch aangemaakt door dht_logger)
# Eerste run maakt tabel + indexes
```

### 12.4 Services Activeren
```bash
# DHT Logger (EERST starten - monitort hardware)
sudo systemctl enable dht-logger
sudo systemctl start dht-logger

# Backend API
sudo systemctl enable pi3twe  
sudo systemctl start pi3twe

# TFT Display
sudo systemctl enable pi3twe-tft
sudo systemctl start pi3twe-tft

# Verify
sudo systemctl status dht-logger pi3twe pi3twe-tft
```

### 12.5 Auto-Restart Configuratie

**Alle services hebben:**
- `Restart=always`
- `RestartSec=10`
- `StartLimitBurst=5` (max 5 crashes per minuut)

**Test crash recovery:**
```bash
# Kill een service
sudo systemctl kill -s KILL dht-logger

# Check auto-restart (gebeurt binnen 10 seconden)
sleep 12
sudo systemctl status dht-logger
```

---

## 13. Bestandsstructuur
```
/srv/pi3twe/
├── app/
│   ├── app.py                    # Flask backend
│   ├── dht_logger.py             # ⭐ Sensor monitoring service
│   ├── wsgi.py                   # Gunicorn entry point
│   ├── init_db.py                # Database setup
│   ├── requirements.txt          # Python dependencies
│   ├── git_all.sh                # Git helper
│   ├── check_pi3twe.sh           # Diagnostic script
│   ├── PI3TWE_MONITORING_SYSTEM.md  # ⭐ Volledige tech docs
│   ├── .venv/                    # Python virtual environment
│   ├── secrets/                  # Keys en tokens (NIET in git!)
│   │   ├── flask_secret.key
│   │   ├── tft_token.txt
│   │   └── msmtprc
│   ├── tft/
│   │   └── tft_app_fb.py         # TFT display app
│   ├── webroot/
│   │   └── index.html            # Redirect/fallback
│   ├── img/
│   │   └── logo.png              # PI3TWE logo
│   ├── pi3twe.db                 # Applicatie database
│   └── monitor.db                # ⭐ Monitoring database
└── data/                         # Legacy directory (niet meer gebruikt)
```

### Systemd Service Files
```
/etc/systemd/system/
├── dht-logger.service      # ⭐ DHT monitoring service
├── pi3twe.service          # Flask backend
└── pi3twe-tft.service      # TFT display
```

---

## 14. Onderhoud

### 14.1 Logs Bekijken
```bash
# DHT Logger
sudo journalctl -u dht-logger -f

# Backend API
sudo journalctl -u pi3twe -f

# TFT Display
sudo journalctl -u pi3twe-tft -f

# Alle services combined
sudo journalctl -u dht-logger -u pi3twe -u pi3twe-tft -f
```

### 14.2 Service Management
```bash
# Status check
sudo systemctl status dht-logger pi3twe pi3twe-tft

# Restart
sudo systemctl restart dht-logger
sudo systemctl restart pi3twe
sudo systemctl restart pi3twe-tft

# Stop (voor onderhoud)
sudo systemctl stop dht-logger pi3twe pi3twe-tft
```

### 14.3 Database Onderhoud
```bash
# Database grootte
ls -lh /srv/pi3twe/app/*.db

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

### 14.4 Kalibratie Wijzigen

**Via web:** Admin → Sensor kalibratie

**Via CLI:**
```bash
# Voorbeeld: INT sensor leest 0.5°C te hoog
sqlite3 /srv/pi3twe/app/pi3twe.db \
  "UPDATE settings SET value='-0.5' 
   WHERE key='cal_int_temp_offset';"

# Verify
sqlite3 /srv/pi3twe/app/pi3twe.db \
  "SELECT * FROM settings WHERE key LIKE 'cal_%';"

# Wacht 15 sec, check nieuw getal
sleep 20
sqlite3 /srv/pi3twe/app/monitor.db \
  "SELECT datetime(ts,'unixepoch','localtime'), temp 
   FROM measurements WHERE source='int' 
   ORDER BY ts DESC LIMIT 5;"
```

### 14.5 Backup
```bash
# Stop services
sudo systemctl stop dht-logger pi3twe pi3twe-tft

# Backup databases
sudo cp /srv/pi3twe/app/pi3twe.db \
        /backup/pi3twe_$(date +%Y%m%d).db
sudo cp /srv/pi3twe/app/monitor.db \
        /backup/monitor_$(date +%Y%m%d).db

# Restart
sudo systemctl start dht-logger pi3twe pi3twe-tft
```

### 14.6 Git Workflow
```bash
cd /srv/pi3twe/app

# Commit + push
./git_all.sh "v2.1.0: Beschrijving van wijzigingen"

# Of handmatig
git add -A
git commit -m "Beschrijving"
git push origin main
```

---

## Changelog

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
- SQLite only (InfluxDB verwijderd uit app.py)
- `monitor.db` bevat alleen gekalibreerde waarden
- 3 maanden retentie met automatische cleanup

**Services:**
- `dht-logger.service` - Hardware monitoring (NIEUW)
- `pi3twe.service` - Web API (geen DHT code meer)
- `pi3twe-tft.service` - Display UI

**Bugfixes:**
- DHT sensor crashes beïnvloeden webserver niet meer
- CPU load correcte weergave (0.x ipv 18.x)
- Alle decimalen gelimiteerd tot 1 decimaal

---

### v2.0.x (2026-01-25)

- InfluxDB 3 Core integratie (verwijderd in v2.1.0)
- Grafana dashboards (nog te herconfigureren)
- CPU load moving average

---

### v1.x (2026-01-17 - 2026-01-24)

- Initiële release
- DHT11 dual sensor support
- TFT framebuffer UI
- Basis monitoring

---

**Auteur:** PA0ESH  
**Licentie:** GPL-3.0  
**Repository:** (private)  
**Documentatie:** [PI3TWE_MONITORING_SYSTEM.md](PI3TWE_MONITORING_SYSTEM.md)
