"""
File: monitor/logger.py
Generated: 2026-01-04
Description: 60s logger loop + dagelijkse retentie cleanup.
"""

from __future__ import annotations

import time
from datetime import date
from typing import Optional

from monitor.config import CONFIG
from monitor.db import delete_older_than, init_db, insert_measurement
from monitor.sensors import read_cpu_temp, read_external_dht, read_internal_bmp280


def run_logger_forever(interval_seconds: Optional[int] = None) -> None:
    """
    Start de logger als oneindige loop:
    - Elke interval: CPU + INT + EXT meten (EXT is placeholder)
    - 1x per dag: retentie delete (365 dagen)
    """
    init_db(CONFIG.db_path)

    interval = int(interval_seconds or CONFIG.interval_seconds)
    last_purge_day: Optional[date] = None

    while True:
        cpu = read_cpu_temp()
        insert_measurement("cpu", temp=cpu.temp, hum=cpu.hum)

        internal = read_internal_bmp280()
        insert_measurement("int", temp=internal.temp, hum=internal.hum)

        ext = read_external_dht()
        insert_measurement("ext", temp=ext.temp, hum=ext.hum)

        today = date.today()
        if last_purge_day != today:
            delete_older_than(CONFIG.retention_days, CONFIG.db_path)
            last_purge_day = today

        time.sleep(interval)


if __name__ == "__main__":
    run_logger_forever()
