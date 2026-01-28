#!/usr/bin/env python3
# ======================================================
# File: /srv/pi3twe/app/tools/dht_to_influx_test.py
# GENERATED_AT = "2026-01-27 09:55 (Europe/Amsterdam)"
#
# Minimale CLI-test (single-file, geen imports buiten stdlib + adafruit_dht):
#  - leest DHT11 INT + EXT (BCM pins)
#  - toont waarden in terminal (incl. per-sample)
#  - schrijft beide als 1 write_lp request naar InfluxDB 3 (measurement: measurements)
#
# Opmerking:
#  - InfluxDB 3 Core kan WAL-concurrency fouten geven bij meerdere gelijktijdige writers.
#    Daarom: 1 HTTP write met 2 lines (int + ext) en optionele retry/backoff.
# ======================================================

import os
import time
import argparse
import urllib.request
import urllib.error

# ---------------------
# Optional: DHT11 (adafruit)
# ---------------------
try:
    import adafruit_dht  # type: ignore
except Exception:
    adafruit_dht = None


def load_token() -> str:
    env = os.environ.get("PI3TWE_INFLUXDB_TOKEN", "").strip()
    if env:
        return env
    p = "/srv/pi3twe/app/secrets/influxdb_token.txt"
    with open(p, "r", encoding="utf-8") as f:
        return f.read().strip()


def influx_write_lp(url: str, db: str, token: str, body: str, timeout_s: float = 3.0) -> tuple[bool, str]:
    endpoint = f"{url.rstrip('/')}/api/v3/write_lp?db={db}"
    req = urllib.request.Request(
        endpoint,
        data=body.encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "text/plain; charset=utf-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            if getattr(resp, "status", 200) in (200, 204):
                return True, ""
            return False, f"HTTP {getattr(resp,'status','?')}"
    except urllib.error.HTTPError as e:
        try:
            b = e.read().decode("utf-8", errors="replace")
        except Exception:
            b = ""
        return False, f"HTTP {e.code} {e.reason} | body={b!r}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def influx_write_with_retry(url: str, db: str, token: str, body: str, retries: int = 6) -> bool:
    for i in range(max(1, int(retries))):
        ok, err = influx_write_lp(url, db, token, body)
        if ok:
            return True
        print(f"INFLUX WRITE ERROR: {err}", flush=True)
        time.sleep(min(3.2, 0.2 * (2 ** i)))
    return False


class _DHTSingle:
    def __init__(self, bcm_pin: int, use_pulseio: bool):
        self.bcm_pin = int(bcm_pin)
        self.use_pulseio = bool(use_pulseio)
        self.dev = None

        if adafruit_dht is None:
            raise RuntimeError("adafruit_dht niet beschikbaar (pip install adafruit-circuitpython-dht)")

        self.dev = adafruit_dht.DHT11(self.bcm_pin, use_pulseio=self.use_pulseio)

    def read_one(self, timeout_s: float = 2.0) -> tuple[bool, float | None, float | None, str | None]:
        out = {"ok": False, "t": None, "h": None, "err": None}

        def _worker():
            try:
                t = self.dev.temperature
                h = self.dev.humidity
                if t is None or h is None:
                    raise RuntimeError("no data")
                out["ok"] = True
                out["t"] = float(t)
                out["h"] = float(h)
            except Exception as e:
                out["err"] = f"{type(e).__name__}: {e}"

        import threading
        th = threading.Thread(target=_worker, daemon=True)
        th.start()
        th.join(timeout_s)
        if th.is_alive():
            return False, None, None, f"TimeoutError: DHT read > {timeout_s:.1f}s"
        if out["ok"]:
            return True, out["t"], out["h"], None
        return False, None, None, out["err"] or "error"

    def close(self):
        try:
            if self.dev is not None:
                self.dev.exit()
        except Exception:
            pass


class DHTPair:
    def __init__(self, int_bcm: int, ext_bcm: int, use_pulseio: bool):
        self._int = _DHTSingle(int(int_bcm), bool(use_pulseio))
        self._ext = _DHTSingle(int(int(ext_bcm)), bool(use_pulseio))

    def read_samples(self, which: str, samples: int = 5, retry_delay_s: float = 0.6) -> dict:
        which = which.lower().strip()
        dev = self._int if which == "int" else self._ext
        pin = dev.bcm_pin

        success = 0
        best_t = None
        best_h = None

        for i in range(1, max(1, int(samples)) + 1):
            ok, t, h, err = dev.read_one(timeout_s=2.0)
            if ok and t is not None and h is not None:
                success += 1
                best_t = float(t)
                best_h = float(h)
                print(f"BCM{pin} [{i}/{samples}]: {best_t:.1f}C {best_h:.0f}%", flush=True)
            else:
                print(f"BCM{pin} [{i}/{samples}]: ERROR {err}", flush=True)
            time.sleep(float(retry_delay_s))

        print(f"BCM{pin}: klaar. succes={success}/{samples}", flush=True)
        return {"temp": best_t, "hum": best_h, "success": success, "total": int(samples)}

    def read_pair(self, samples: int = 5) -> dict:
        r_int = self.read_samples("int", samples=samples)
        print("", flush=True)
        r_ext = self.read_samples("ext", samples=samples)
        print("", flush=True)

        total_ok = int(r_int.get("success", 0)) + int(r_ext.get("success", 0))
        total = int(r_int.get("total", 0)) + int(r_ext.get("total", 0))
        print(f"TOTAAL: succes={total_ok}/{total}", flush=True)

        return {"int": r_int, "ext": r_ext}

    def close(self):
        self._int.close()
        self._ext.close()


def _numeric_pair(d: dict) -> tuple[float | None, float | None]:
    t = d.get("temp")
    h = d.get("hum")
    try:
        t = float(t) if t is not None else None
    except Exception:
        t = None
    try:
        h = float(h) if h is not None else None
    except Exception:
        h = None
    return t, h


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--int", dest="int_bcm", type=int, default=int(os.environ.get("PI3TWE_DHT_INT_GPIO", "26")))
    ap.add_argument("--ext", dest="ext_bcm", type=int, default=int(os.environ.get("PI3TWE_DHT_EXT_GPIO", "20")))
    ap.add_argument("--use-pulseio", dest="use_pulseio", action="store_true",
                    default=(os.environ.get("PI3TWE_DHT_USE_PULSEIO", "0").strip().lower() not in {"0","false","no","off"}))
    ap.add_argument("--influx-url", default=os.environ.get("PI3TWE_INFLUXDB_URL", "http://127.0.0.1:8181"))
    ap.add_argument("--db", default=os.environ.get("PI3TWE_INFLUXDB_DATABASE", "pi3twe"))
    ap.add_argument("--retries", type=int, default=6)
    args = ap.parse_args()

    print(f"InfluxDB: {args.influx_url}  db={args.db}", flush=True)
    print(f"DHT: INT=BCM{args.int_bcm}  EXT=BCM{args.ext_bcm}  use_pulseio={bool(args.use_pulseio)}", flush=True)

    try:
        token = load_token()
    except Exception as e:
        print(f"FATAL: kan Influx token niet laden: {type(e).__name__}: {e}", flush=True)
        return 2

    try:
        dht = DHTPair(int_bcm=args.int_bcm, ext_bcm=args.ext_bcm, use_pulseio=bool(args.use_pulseio))
    except Exception as e:
        print(f"FATAL: kan DHT niet initialiseren: {type(e).__name__}: {e}", flush=True)
        return 3

    try:
        data = dht.read_pair(samples=args.samples)
        t_int, h_int = _numeric_pair(data["int"])
        t_ext, h_ext = _numeric_pair(data["ext"])

        ts_ns = int(time.time() * 1_000_000_000)

        lines = []
        if t_int is not None and h_int is not None:
            lines.append(f"measurements,source=int temp={round(t_int,1)},hum={int(round(h_int,0))} {ts_ns}")
        if t_ext is not None and h_ext is not None:
            lines.append(f"measurements,source=ext temp={round(t_ext,1)},hum={int(round(h_ext,0))} {ts_ns}")

        if not lines:
            print("WRITE: SKIP (geen geldige meting voor INT/EXT)", flush=True)
            return 4

        body = "\n".join(lines) + "\n"

        ok = influx_write_with_retry(args.influx_url, args.db, token, body, retries=args.retries)
        if ok:
            print("WRITE: OK", flush=True)
            return 0
        print("WRITE: FAIL", flush=True)
        return 5

    finally:
        try:
            dht.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
