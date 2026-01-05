"""
File: monitor/db.py
Generated: 2026-01-04
Description: SQLite helper (init, insert, queries, retention).
"""

import sqlite3
from pathlib import Path
from time import time
from typing import Dict, List, Optional, Tuple

from monitor.config import CONFIG


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path), timeout=30, isolation_level=None)  # autocommit
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA temp_store=MEMORY;")
    return con


def init_db(db_path: Optional[Path] = None) -> None:
    path = db_path or CONFIG.db_path
    with _connect(path) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS measurements (
              id     INTEGER PRIMARY KEY AUTOINCREMENT,
              ts     INTEGER NOT NULL,
              source TEXT    NOT NULL,    -- cpu | int | ext
              temp   REAL,
              hum    REAL
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_measurements_ts ON measurements(ts)")
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_measurements_source_ts ON measurements(source, ts)"
        )


def insert_measurement(source: str, temp: Optional[float], hum: Optional[float], db_path: Optional[Path] = None) -> None:
    path = db_path or CONFIG.db_path
    now = int(time())
    with _connect(path) as con:
        con.execute(
            "INSERT INTO measurements (ts, source, temp, hum) VALUES (?, ?, ?, ?)",
            (now, source, temp, hum),
        )


def delete_older_than(days: int, db_path: Optional[Path] = None) -> int:
    """
    Verwijder rijen ouder dan N dagen. Retourneert aantal verwijderde rijen.
    """
    path = db_path or CONFIG.db_path
    cutoff = int(time()) - int(days) * 86400
    with _connect(path) as con:
        cur = con.execute("DELETE FROM measurements WHERE ts < ?", (cutoff,))
        return cur.rowcount if cur.rowcount is not None else 0


def fetch_range(hours: int = 24, db_path: Optional[Path] = None) -> List[Tuple[int, str, Optional[float], Optional[float]]]:
    """
    Haal metingen op van laatste N uur.
    """
    path = db_path or CONFIG.db_path
    since = int(time()) - int(hours) * 3600
    with _connect(path) as con:
        cur = con.execute(
            "SELECT ts, source, temp, hum FROM measurements WHERE ts >= ? ORDER BY ts",
            (since,),
        )
        return cur.fetchall()


def fetch_as_series(hours: int = 24, db_path: Optional[Path] = None) -> Dict[str, List[Dict]]:
    """
    Output geschikt voor dashboard/API:
    {
      "cpu": [{"ts":..., "temp":..., "hum":...}, ...],
      "int": [...],
      "ext": [...]
    }
    """
    rows = fetch_range(hours=hours, db_path=db_path)
    data: Dict[str, List[Dict]] = {"cpu": [], "int": [], "ext": []}
    for ts, source, temp, hum in rows:
        if source not in data:
            data[source] = []
        data[source].append({"ts": ts, "temp": temp, "hum": hum})
    return data


def db_stats(db_path: Optional[Path] = None) -> Dict[str, object]:
    """
    Kleine health/stats endpoint helper.
    """
    path = db_path or CONFIG.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    size_bytes = path.stat().st_size if path.exists() else 0

    with _connect(path) as con:
        cur = con.execute("SELECT COUNT(*) FROM measurements")
        total_rows = int(cur.fetchone()[0])

        cur2 = con.execute("SELECT MIN(ts), MAX(ts) FROM measurements")
        min_ts, max_ts = cur2.fetchone()

    return {
        "db_path": str(path),
        "size_bytes": size_bytes,
        "rows": total_rows,
        "min_ts": min_ts,
        "max_ts": max_ts,
    }
