#!/usr/bin/env python3
# ======================================================
# File: /srv/pi3twe/app/tools/dht_test.py
# Generated: 2026-01-26 (Europe/Amsterdam)
# Description:
#   CLI-testtool voor DHT11 op Raspberry Pi (Adafruit library).
#   - Test 1 of meerdere BCM pins
#   - Standaard 5 metingen per pin, stopt daarna
#   - Voorkomt “blijven hangen” door:
#       * bounded samples
#       * bounded retries per sample
#       * dev.exit() altijd in finally
#
# Examples:
#   source /srv/pi3twe/app/.venv/bin/activate
#   python /srv/pi3twe/app/tools/dht_test.py --pin 26
#   python /srv/pi3twe/app/tools/dht_test.py --pin 20
#   python /srv/pi3twe/app/tools/dht_test.py --pin 26 --pin 20
#   python /srv/pi3twe/app/tools/dht_test.py --samples 5 --sleep 2 --retries 2
# ======================================================

import argparse
import time
from typing import Optional, Tuple

import board  # type: ignore
import adafruit_dht  # type: ignore


def _make_dev(bcm: int):
    pin_name = f"D{int(bcm)}"
    if not hasattr(board, pin_name):
        raise RuntimeError(f"board heeft geen attribuut {pin_name} (BCM{bcm})")
    pin = getattr(board, pin_name)
    return adafruit_dht.DHT11(pin)


def _read_once(dev, retries: int, retry_delay_s: float) -> Tuple[Optional[float], Optional[float], Optional[Exception]]:
    last_err: Optional[Exception] = None
    attempts = max(1, int(retries) + 1)

    for _ in range(attempts):
        try:
            t = dev.temperature
            h = dev.humidity
            if t is None or h is None:
                raise RuntimeError("no data")
            return float(t), float(h), None
        except Exception as e:
            last_err = e
            time.sleep(float(retry_delay_s))

    return None, None, last_err


def test_pin(bcm: int, samples: int, sleep_s: float, retries: int, retry_delay_s: float) -> Tuple[int, int]:
    """
    Returns (ok_count, sample_count)
    """
    dev = None
    ok = 0
    try:
        dev = _make_dev(bcm)

        for i in range(1, samples + 1):
            t, h, err = _read_once(dev, retries=retries, retry_delay_s=retry_delay_s)
            if err is None and t is not None and h is not None:
                ok += 1
                print(f"BCM{bcm} [{i}/{samples}]: {t:.1f}C {h:.0f}%")
            else:
                print(f"BCM{bcm} [{i}/{samples}]: ERROR {type(err).__name__}: {err}")

            if i < samples:
                time.sleep(float(sleep_s))

    finally:
        # Cruciaal om “lockups” bij herhaald testen te voorkomen
        try:
            if dev is not None:
                dev.exit()
        except Exception:
            pass

    print(f"BCM{bcm}: klaar. succes={ok}/{samples}")
    return ok, samples


def main() -> int:
    ap = argparse.ArgumentParser(description="PI3TWE DHT11 testtool (bounded, no-hang).")
    ap.add_argument("--pin", action="append", type=int, help="BCM pin, bv 26 of 20. Mag meerdere keren.")
    ap.add_argument("--samples", type=int, default=5, help="Aantal metingen per pin (default 5)")
    ap.add_argument("--sleep", type=float, default=2.0, help="Wachttijd tussen metingen (default 2.0s)")
    ap.add_argument("--retries", type=int, default=2, help="Retries per meting (default 2)")
    ap.add_argument("--retry-delay", type=float, default=0.2, help="Delay tussen retries (default 0.2s)")
    args = ap.parse_args()

    pins = args.pin or [26, 20]  # default jouw INT/EXT
    samples = max(1, int(args.samples))

    total_ok = 0
    total_samples = 0

    for bcm in pins:
        try:
            ok, n = test_pin(
                bcm=bcm,
                samples=samples,
                sleep_s=float(args.sleep),
                retries=int(args.retries),
                retry_delay_s=float(args.retry_delay),
            )
            total_ok += ok
            total_samples += n
        except KeyboardInterrupt:
            print("Afgebroken (CTRL-C).")
            return 130
        except Exception as e:
            # per pin falen mag, maar we gaan door met de rest
            print(f"BCM{bcm}: FATAAL {type(e).__name__}: {e}")
            total_samples += samples

    print(f"TOTAAL: succes={total_ok}/{total_samples}")

    # Exitcode:
    # 0 = minimaal 1 succes
    # 2 = alles fail
    return 0 if total_ok > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
