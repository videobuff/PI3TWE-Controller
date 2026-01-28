#!/usr/bin/env python3 -u -u -u
import time
import sqlite3
import board
import adafruit_dht
import subprocess

DB_PATH = "/srv/pi3twe/app/monitor.db"
SETTINGS_DB = "/srv/pi3twe/app/pi3twe.db"
INTERVAL_SEC = 15
CAL_RELOAD_SEC = 15  # Reload kalibratie elke 60 sec

dht_int = adafruit_dht.DHT11(board.D26)
dht_ext = adafruit_dht.DHT11(board.D20)

# Calibration cache
cal_cache = {'int_temp': 0.0, 'int_hum': 0.0, 'ext_temp': 0.0, 'ext_hum': 0.0}
cal_last_load = 0

def load_calibration():
    """Laad kalibratie offsets uit settings database"""
    global cal_cache, cal_last_load
    try:
        with sqlite3.connect(SETTINGS_DB) as conn:
            cur = conn.cursor()
            cur.execute("SELECT key, value FROM settings WHERE key LIKE 'cal_%_offset'")
            for key, val in cur.fetchall():
                if key == 'cal_int_temp_offset':
                    cal_cache['int_temp'] = float(val)
                elif key == 'cal_int_hum_offset':
                    cal_cache['int_hum'] = float(val)
                elif key == 'cal_ext_temp_offset':
                    cal_cache['ext_temp'] = float(val)
                elif key == 'cal_ext_hum_offset':
                    cal_cache['ext_hum'] = float(val)
        cal_last_load = time.time()
        print(f"Kalibratie geladen: INT({cal_cache['int_temp']:.1f}°C, {cal_cache['int_hum']:.0f}%) EXT({cal_cache['ext_temp']:.1f}°C, {cal_cache['ext_hum']:.0f}%)")
    except Exception as e:
        print(f"Kalibratie load error: {e}")

def read_cpu_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return round(float(f.read().strip()) / 1000.0, 1)
    except:
        return None

def read_cpu_load():
    try:
        with open("/proc/loadavg") as f:
            return round(float(f.read().split()[0]), 2)
    except:
        return None

def read_repeater_status():
    try:
        r = subprocess.run(['curl', '-s', 'http://127.0.0.1:3001/api/state'], 
                         capture_output=True, text=True, timeout=2)
        return 1 if '"repeater":true' in r.stdout else 0
    except:
        return None

# Maak tabel
with sqlite3.connect(DB_PATH) as conn:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS measurements (
            ts INTEGER NOT NULL,
            source TEXT NOT NULL,
            temp REAL,
            hum REAL,
            status INTEGER
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_measurements_src_ts ON measurements(source, ts)")
    # Cleanup > 3 maanden
    conn.execute("DELETE FROM measurements WHERE ts < ?", (int(time.time()) - 7776000,))

# Laad kalibratie
load_calibration()
print(f"Logger started → {DB_PATH}")

while True:
    ts = int(time.time())
    
    # Reload kalibratie elke 60 sec
    if time.time() - cal_last_load >= CAL_RELOAD_SEC:
        load_calibration()
    
    # INT/EXT met kalibratie
    for name, sensor, cal_t, cal_h in [
        ('int', dht_int, cal_cache['int_temp'], cal_cache['int_hum']),
        ('ext', dht_ext, cal_cache['ext_temp'], cal_cache['ext_hum'])
    ]:
        try:
            for _ in range(3):
                try:
                    t_raw, h_raw = sensor.temperature, sensor.humidity
                    if t_raw and h_raw:
                        # Pas kalibratie toe
                        t = round(float(t_raw) + cal_t, 1)
                        h = int(round(float(h_raw) + cal_h, 0))
                        
                        with sqlite3.connect(DB_PATH) as conn:
                            conn.execute("INSERT INTO measurements(ts,source,temp,hum) VALUES(?,?,?,?)", 
                                       (ts, name, t, h))
                        print(f"{name.upper()}: {t}°C {h}% (raw: {t_raw}°C {h_raw}%)")
                        break
                except RuntimeError:
                    time.sleep(2)
        except Exception as e:
            print(f"{name.upper()} error: {e}")
        time.sleep(2)
    
    # CPU
    cpu_t = read_cpu_temp()
    cpu_l = read_cpu_load()
    if cpu_t or cpu_l:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("INSERT INTO measurements(ts,source,temp,hum) VALUES(?,?,?,?)", 
                       (ts, 'cpu', cpu_t, cpu_l))
        print(f"CPU: {cpu_t}°C {cpu_l}%")
    
    # Status
    status = read_repeater_status()
    if status is not None:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("INSERT INTO measurements(ts,source,status) VALUES(?,?,?)", 
                       (ts, 'status', status))
        print(f"Status: {'ON AIR' if status else 'STAND BY'}")
    
    time.sleep(INTERVAL_SEC - 8)
