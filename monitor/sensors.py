"""
File: monitor/sensors.py
Generated: 2026-01-04
Description: Sensor readouts: CPU temp, interne temp (BMP280 optioneel), externe temp/hum (DHT placeholder).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Reading:
    temp: Optional[float]
    hum: Optional[float]


def read_cpu_temp() -> Reading:
    """
    CPU temperatuur via sysfs.
    """
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r", encoding="utf-8") as f:
            milli = float(f.read().strip())
        return Reading(temp=milli / 1000.0, hum=None)
    except Exception:
        return Reading(temp=None, hum=None)


def read_internal_bmp280(i2c_address: int = 0x76) -> Reading:
    """
    Interne temperatuur via BMP280 (optioneel; vereist libraries).
    Als libs/hardware ontbreken -> (None, None).
    """
    try:
        import board  # type: ignore
        import busio  # type: ignore
        import adafruit_bmp280  # type: ignore

        i2c = busio.I2C(board.SCL, board.SDA)
        bmp = adafruit_bmp280.Adafruit_BMP280_I2C(i2c, address=i2c_address)
        t = float(bmp.temperature)
        return Reading(temp=t, hum=None)
    except Exception:
        return Reading(temp=None, hum=None)


def read_external_dht() -> Reading:
    """
    Externe DHT sensor placeholder.
    Later implementeren zonder DB schema changes.
    JSON keys blijven temp/hum.
    """
    return Reading(temp=None, hum=None)
