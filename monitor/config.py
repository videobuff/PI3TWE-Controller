"""
File: monitor/config.py
Generated: 2026-01-04
Description: Centrale configuratie voor monitor logging + web.
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MonitorConfig:
    # Storage
    db_path: Path = Path("/srv/pi3twe/data/monitor.db")

    # Logging
    interval_seconds: int = 60

    # Retention
    retention_days: int = 365

    # Web
    web_host: str = "0.0.0.0"
    web_port: int = 3010  # default: 3010 (vermijdt conflict met hoofdapp)


CONFIG = MonitorConfig()
