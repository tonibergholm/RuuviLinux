"""Transactional local SQLite storage; all access belongs to the GUI thread."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import sqlite3
from .protocol import Reading


def data_path() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "ruuvilinux/sensors.sqlite3"


class Store:
    def __init__(self, path: Path | str | None = None):
        path = path if path is not None else data_path()
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS sensors (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, favorite INTEGER NOT NULL DEFAULT 0,
                last_seen REAL NOT NULL, rssi INTEGER NOT NULL, latest TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY, sensor_id TEXT NOT NULL REFERENCES sensors(id),
                time REAL NOT NULL, sequence INTEGER, temperature REAL, humidity REAL, pressure REAL
            );
            CREATE INDEX IF NOT EXISTS readings_sensor_time ON readings(sensor_id, time);
        """)

    def receive(self, address: str, reading: Reading, rssi: int, now: float) -> str:
        identity = reading.mac or address.upper()
        with self.db:
            self.db.execute("""INSERT INTO sensors(id,name,last_seen,rssi,latest)
                VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                last_seen=excluded.last_seen, rssi=excluded.rssi, latest=excluded.latest""",
                (identity, f"Ruuvi {identity[-5:]}", now, rssi, json.dumps(asdict(reading))))
            previous = self.db.execute(
                "SELECT time,sequence FROM readings WHERE sensor_id=? ORDER BY time DESC,id DESC LIMIT 1", (identity,)).fetchone()
            if previous is None or (now - previous["time"] >= 60 and
                    (reading.sequence is None or reading.sequence != previous["sequence"])):
                self.db.execute("""INSERT INTO readings(sensor_id,time,sequence,temperature,humidity,pressure)
                    VALUES(?,?,?,?,?,?)""", (identity, now, reading.sequence, reading.temperature, reading.humidity, reading.pressure))
            self.db.execute("DELETE FROM readings WHERE time < ?", (now - 86400,))
            self.db.execute("""DELETE FROM readings WHERE sensor_id=? AND id NOT IN
                (SELECT id FROM readings WHERE sensor_id=? ORDER BY time DESC,id DESC LIMIT 1440)""", (identity, identity))
        return identity

    def sensors(self, favorites_only: bool = False) -> list[dict]:
        rows = self.db.execute("SELECT * FROM sensors WHERE (?=0 OR favorite=1) ORDER BY favorite DESC,name COLLATE NOCASE,id", (int(favorites_only),))
        return [dict(row) | {"latest": json.loads(row["latest"])} for row in rows]

    def sensor(self, identity: str) -> dict | None:
        row = self.db.execute("SELECT * FROM sensors WHERE id=?", (identity,)).fetchone()
        return dict(row) | {"latest": json.loads(row["latest"])} if row else None

    def rename(self, identity: str, name: str):
        name = name.strip()[:80]
        if not name:
            raise ValueError("Please enter a sensor name.")
        with self.db:
            self.db.execute("UPDATE sensors SET name=? WHERE id=?", (name, identity))

    def favorite(self, identity: str, enabled: bool):
        with self.db:
            self.db.execute("UPDATE sensors SET favorite=? WHERE id=?", (int(enabled), identity))

    def history(self, identity: str, now: float) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM readings WHERE sensor_id=? AND time>=? ORDER BY time,id", (identity, now - 86400))]

    def close(self):
        self.db.close()
