# PI3TWE-Controller

# PI3TWE Controller & TFT-integratie  
**Projectarchief – Raspberry Pi 3**

**Periode:** Najaar–Winter 2025  
**Platform:** Raspberry Pi 3  
**Stack:** Python 3, Flask, SQLite, GPIO, framebuffer-TFT  

---

## Inhoudsopgave

1. [Projectdoel](#1-projectdoel)  
2. [Systeemoverzicht](#2-systeemoverzicht)  
3. [Backend applicatie (Flask)](#3-backend-applicatie-flask)  
4. [Authenticatie & beveiliging](#4-authenticatie--beveiliging)  
5. [Gebruikersbeheer – handleiding](#5-gebruikersbeheer--handleiding)  
6. [Hardware-integratie](#6-hardware-integratie)  
7. [TFT-scherm integratie](#7-tft-scherm-integratie)  
8. [Problemen & oplossingen](#8-problemen--oplossingen)  
9. [Huidige status](#9-huidige-status)  
10. [Aanbevolen archiefstructuur](#10-aanbevolen-archiefstructuur)

---

## 1. Projectdoel

Het doel van dit project is het realiseren van een **stand-alone embedded controller** voor PI3TWE met:

- Veilige lokale web-API (localhost-only)
- Gebruikersbeheer met login en optionele 2FA
- Relaisbesturing voor repeater enable/disable
- Sensor- en systeemmonitoring
- Lokaal TFT-scherm voor statusweergave
- Volledige werking zonder cloud-afhankelijkheden

---

## 2. Systeemoverzicht

Het systeem bestaat uit twee hoofdcomponenten:

### 2.1 Backend (Flask)
- Draait op `127.0.0.1`
- JSON-only API
- SQLite database
- Hardware- en logica-afhandeling

### 2.2 TFT applicatie
- Aparte Python applicatie
- Tekent direct op framebuffer (`/dev/fb*`)
- Communiceert via token-protected API
- Geen X11, geen touch

---

## 3. Backend applicatie (Flask)

### 3.1 Algemene kenmerken

- Alleen lokaal toegankelijk
- Modulaire opzet
- Duidelijke scheiding tussen:
  - authenticatie
  - autorisatie
  - hardware-logica
  - TFT-endpoints

### 3.2 Database

SQLite tabellen:
- `users`
- `audit_log`
- `settings`

---

## 4. Authenticatie & beveiliging

### 4.1 Login & sessies

- Login via `/api/login`
- Sessies gebaseerd op Flask cookies
- Sessies blijven geldig na reboot

### 4.2 Persistente secret key

- Secret key wordt opgeslagen in bestand:
  - voorkomt sessieverlies na service restart
- Essentieel voor stabiele werking

### 4.3 Audit logging

- Kritische acties worden vastgelegd:
  - login
  - gebruikersbeheer
  - relais-acties
  - 2FA wijzigingen

---

## 5. Gebruikersbeheer – handleiding

### 5.1 Inloggen

1. Ga naar de webinterface
2. Voer gebruikersnaam en wachtwoord in
3. Indien 2FA actief:
   - voer de TOTP-code in
4. Na succesvolle login wordt een sessie gestart

---

### 5.2 Gebruiker aanmaken (Admin)

1. Log in als admin
2. Ga naar **Gebruikersbeheer**
3. Kies **Nieuwe gebruiker**
4. Vul in:
   - gebruikersnaam
   - initiëel wachtwoord
   - rol (admin / user)
5. Sla op

➡️ De gebruiker kan nu inloggen  
➡️ 2FA staat standaard **uit**

---

### 5.3 Gebruiker wijzigen (Admin)

Admin kan wijzigen:
- wachtwoord resetten
- rol aanpassen
- account (de)activeren

**Procedure:**
1. Selecteer gebruiker
2. Pas gewenste velden aan
3. Opslaan

Wijzigingen zijn direct actief.

---

### 5.4 Gebruiker verwijderen (Admin)

1. Selecteer gebruiker
2. Kies **Verwijderen**
3. Bevestig actie

⚠️ Deze actie is definitief  
⚠️ Historische logs blijven behouden

---

### 5.5 2FA beheren – gebruiker

Een gebruiker kan zelf:

1. Inloggen
2. Naar **Accountinstellingen**
3. Kies:
   - 2FA inschakelen
   - 2FA uitschakelen
4. Bij inschakelen:
   - QR-code scannen met authenticator
   - Eerste TOTP-code bevestigen

---

### 5.6 2FA resetten – admin

Indien gebruiker geen toegang meer heeft:

1. Log in als admin
2. Ga naar **Gebruikersbeheer**
3. Selecteer gebruiker
4. Kies **Reset 2FA**

➡️ Gebruiker kan opnieuw inloggen zonder TOTP  
➡️ 2FA kan daarna opnieuw worden ingesteld

---

## 6. Hardware-integratie

### 6.1 Relaisbesturing

- GPIO gestuurd (default GPIO26)
- Cooldown voorkomt snel schakelen
- Status zichtbaar via web en TFT

### 6.2 Sensoren

- BMP280 / BME280 (indien aanwezig)
- CPU temperatuur
- Fouttolerant: geen crash bij ontbrekende sensor

---

## 7. TFT-scherm integratie

### 7.1 Hardware

- 3.5 inch TFT
- Resolutie: 480 × 320
- Framebuffer-based
- Touchcontroller niet gebruikt

### 7.2 Software

- `tft_app_fb.py`
- Tekent direct op framebuffer
- Geen GUI-frameworks

### 7.3 API-koppeling

Token-protected endpoints:
- `/api/tft/state`
- `/api/tft/toggle`
- `/api/tft/reboot`

Geen login of cookies nodig.

---

## 8. Problemen & oplossingen

### 8.1 Sessies verloren na reboot

**Oplossing:**  
Persistente Flask secret key via bestand.

---

### 8.2 2FA flexibiliteit

**Oplossing:**  
2FA per gebruiker i.p.v. globaal.

---

### 8.3 TFT ontkoppeling

**Oplossing:**  
Aparte applicatie + token-based API.

---

## 9. Huidige status

- Backend: stabiel
- Sessies: persistent
- 2FA: per gebruiker
- Relais & sensoren: operationeel
- TFT: functioneel en referentieversie vastgelegd

---

## 10. Aanbevolen archiefstructuur
