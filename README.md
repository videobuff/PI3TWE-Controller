# PI3TWE Controller – Projectarchief

**Platform:** Raspberry Pi 3  
**Periode:** Najaar–Winter 2025 / Januari 2026  
**Status:** Operationeel, productiegeschikt  
**Doel:** Stand-alone controller voor repeaterbeheer met lokale UI, webfrontend en beveiliging

---

## Inhoudsopgave

1. Projectdoel  
2. Architectuuroverzicht  
3. Backend (Flask)  
4. Frontend (Apache HTML)  
5. TFT-scherm (Framebuffer UI)  
6. Gebruikersbeheer & Authenticatie  
7. Hardware-integratie  
8. Beveiliging & Hardening (Fail2ban)  
9. Prerequisites & Installatie-eisen  
10. Archiefstructuur  
11. Huidige status  

---

## 1. Projectdoel

Het PI3TWE-project heeft als doel het realiseren van een **betrouwbare, veilige en autonome controller** voor een repeaterinstallatie op locatie, met:

- lokale en externe bediening
- gebruikersauthenticatie met optionele 2FA
- relaisbesturing
- status- en sensormonitoring
- lokale visuele feedback via TFT
- minimale afhankelijkheid van externe diensten

Het systeem is ontworpen voor **onbemande werking**.

---

## 2. Architectuuroverzicht

Het systeem bestaat uit drie strikt gescheiden lagen:

### 2.1 Backend
- Python 3 + Flask
- Draait uitsluitend op `127.0.0.1`
- JSON-API
- Hardware- en logica-afhandeling

### 2.2 Frontend
- Apache webserver
- HTML / CSS / JavaScript
- Communiceert met backend via localhost-API

### 2.3 TFT-UI
- Aparte Python applicatie
- Framebuffer-based (`/dev/fb*`)
- Geen X11, geen touch
- Communiceert via token-protected API

---

## 3. Backend (Flask)

### 3.1 Algemene kenmerken
- Luistert alleen op localhost
- Geen directe internet-exposure
- Sessies via Flask cookies
- Persistente secret key (bestand)

### 3.2 Database
SQLite met o.a.:
- `users`
- `settings`
- `audit_log`

### 3.3 API-eigenschappen
- JSON-only
- Duidelijke scheiding tussen:
  - auth
  - gebruikersbeheer
  - hardware
  - TFT-endpoints

---

## 4. Frontend (Apache HTML)

### 4.1 Locatie
/var/www/pi3twe

### 4.2 Functie
- Webinterface voor gebruikers en beheer
- Draait onder Apache
- Enige internet-exposed component

### 4.3 Communicatie
- `fetch()` / AJAX naar Flask backend
- Backend alleen via `127.0.0.1`

---

## 5. TFT-scherm (Framebuffer UI)

### 5.1 Hardware
- 3.5 inch TFT
- Resolutie: 480 × 320
- XPT2046 touchcontroller niet gebruikt

### 5.2 Software
- `tft_app_fb.py`
- Tekent direct op framebuffer
- Geen GUI-frameworks

### 5.3 Functie
- Repeater status
- Sensorwaarden
- Netwerk/statusinformatie
- Bediening via fysieke omgeving

---

## 6. Gebruikersbeheer & Authenticatie

### 6.1 Login
- Gebruikersnaam + wachtwoord
- Sessies persistent over reboot

### 6.2 Rollen
- Admin
- Gebruiker

### 6.3 2FA (TOTP)
- Per gebruiker instelbaar
- Niet globaal verplicht
- Admin kan 2FA resetten
- Mixed omgevingen toegestaan

---

## 7. Hardware-integratie

### 7.1 Relais
- GPIO-gestuurd
- Cooldown ter bescherming
- Status zichtbaar via web en TFT

### 7.2 Sensoren
- BMP280 / BME280 (indien aanwezig)
- CPU temperatuur
- Best-effort detectie
- Geen crash bij ontbrekende hardware
- Pin conector aanlsuitinten 6 - pins.
- Groen     -  4    VCC
- Groen Wit  - 5    GND
- Oranje     - 1    SCL
- Oranje wit - 2    SDA

---

## 8. Beveiliging & Hardening (Fail2ban)

### 8.1 Doel
Bescherming tegen:
- brute-force aanvallen
- bots en scanners
- misbruik van Apache en SSH

### 8.2 Actieve jails
Actief per 2026-01-01:

- `sshd`
- `apache-auth`
- `apache-badbots`
- `apache-noscript`
- `apache-nohome`
- `apache-overflows`

Geen andere jails zijn actief.

### 8.3 Whitelistingbeleid

Gewhitelist:
- `127.0.0.1/8`
- `::1`
- lokaal LAN (`192.168.2.0/24`)

Niet gewhitelist:
- publieke IPv4-adressen
- publieke IPv6-adressen

Voorbeelden (niet gewhitelist):
- IPv4: `81.207.216.66`
- IPv6: `2a02:a454:16e2:0:342e:9a48:1e06:6648`

**Reden:**
- Publieke adressen zijn exact wat Fail2ban moet kunnen blokkeren
- IPv6 kan wijzigen
- Beveiliging gaat vóór gemak

### 8.4 Backend-afbakening
- Flask backend draait alleen op localhost
- Niet gemonitord door Fail2ban
- Apache is enige internet-exposed laag

---

## 9. Prerequisites & Installatie-eisen

### 9.1 OS
- Raspberry Pi OS (Debian Trixie)

### 9.2 System packages
- python3, pip, venv
- apache2
- sqlite3
- fail2ban
- git, curl

### 9.3 Interfaces
- SPI (TFT)
- I2C (sensoren)
- GPIO

### 9.4 Python libraries
- flask
- pyotp
- pillow
- requests
- adafruit-blinka (indien BME/BMP280)

---

## 10. Archiefstructuur

/archive/
├─ README_PI3TWE_Projectarchief.md
├─ app.py
├─ tft_app_fb.py
├─ requirements.txt
├─ FAIL2BAN_NOTES.md (optioneel, samengevoegd in dit document)
├─ www/
│   └─ pi3twe/
├─ systemd/
│   ├─ pi3twe.service
│   └─ pi3twe-tft.service

Secrets, keys en tokens worden **niet** gearchiveerd.

---

## 11. Huidige status

- Backend stabiel
- Frontend operationeel
- TFT-UI functioneel
- Gebruikersbeheer en 2FA correct
- Fail2ban actief en getest
- Geschikt voor langdurige onbemande inzet

---

**Einde document**
