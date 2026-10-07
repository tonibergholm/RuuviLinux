"""Transactional local SQLite storage; all access belongs to the GUI thread."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import sqlite3
from .protocol import Reading
from .history_limits import RETENTION, MAX_SAMPLES


def data_path() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "ruuvilinux/sensors.sqlite3"


class Store:
    def __init__(self, path: Path | str | None = None):
        path = path if path is not None else data_path()
        self.path = path
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
        return self.record(address, reading, rssi, now)[0]

    def record(self, address: str, reading: Reading, rssi: int, now: float) -> tuple[str, bool]:
        """Store a reading; also report whether it was newer than the saved one."""
        identity = reading.mac or address.upper()
        existing=self.db.execute("SELECT last_seen FROM sensors WHERE id=?",(identity,)).fetchone()
        if existing and now<=existing["last_seen"]:
            return identity, False  # stale / repeated retained messages never refresh freshness
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
            self.db.execute("DELETE FROM readings WHERE time < ?", (now - RETENTION,))
            self.db.execute("""DELETE FROM readings WHERE sensor_id=? AND id NOT IN
                (SELECT id FROM readings WHERE sensor_id=? ORDER BY time DESC,id DESC LIMIT 14400)""", (identity, identity))
        return identity, True

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

    def history(self, identity: str, now: float, seconds: float = 86400) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM readings WHERE sensor_id=? AND time>? ORDER BY time,id", (identity, now - seconds))]

    def merge_logs(self, identity, samples, now):
        if self.sensor(identity) is None: raise ValueError("Select a discovered sensor first.")
        rows={int(r["time"]//60):dict(r) for r in self.db.execute("SELECT * FROM readings WHERE sensor_id=?",(identity,))}
        added=0
        with self.db:
            for sample in samples:
                if not now-RETENTION < sample.time <= now: continue
                key=sample.time//60; previous=rows.get(key)
                if previous:
                    values=[previous[f] if previous[f] is not None else getattr(sample,f) for f in ("temperature","humidity","pressure")]
                    self.db.execute("UPDATE readings SET temperature=?,humidity=?,pressure=? WHERE id=?",(*values,previous["id"]))
                    previous.update(zip(("temperature","humidity","pressure"),values))
                else:
                    cursor=self.db.execute("INSERT INTO readings(sensor_id,time,temperature,humidity,pressure) VALUES(?,?,?,?,?)",
                        (identity,sample.time,sample.temperature,sample.humidity,sample.pressure))
                    rows[key]={"id":cursor.lastrowid,"temperature":sample.temperature,"humidity":sample.humidity,"pressure":sample.pressure};added+=1
            self.db.execute("DELETE FROM readings WHERE sensor_id=? AND time<=?",(identity,now-RETENTION))
            self.db.execute("DELETE FROM readings WHERE sensor_id=? AND id NOT IN (SELECT id FROM readings WHERE sensor_id=? ORDER BY time DESC,id DESC LIMIT 14400)",(identity,identity))
        return added

    def close(self):
        self.db.close()
