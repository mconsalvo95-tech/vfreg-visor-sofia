from __future__ import annotations

import csv
import json
import os
import queue
import sqlite3
import threading
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Optional


@dataclass
class Measurement:
    timestamp: str
    source: str
    sequence: Optional[int]
    voltage_v: Optional[float]
    current_ma: Optional[float]
    frequency_hz: Optional[float]
    device_timestamp: str = ""
    protocol: str = "unknown"
    source_ip: str = ""
    source_port: Optional[int] = None
    line_status: str = "RUNNING"
    connection_status: str = "CONNECTED"
    alarm_status: str = "NORMAL"
    status: str = "OK"
    payload_size: int = 0
    payload_sha256: str = ""
    batch_id: str = ""
    shift: str = ""
    raw_payload: str = ""


CSV_FIELDS = list(Measurement.__dataclass_fields__)

MANAGER_EXPORT_COLUMNS = [
    ("Time", "timestamp"),
    ("Volts", "voltage_v"),
    ("mAmp", "current_ma"),
    ("Frec", "frequency_hz"),
    ("Status", "connection_status"),
]


def format_manager_timestamp(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        return datetime.fromisoformat(str(value)).strftime("%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError):
        return str(value)

MEASUREMENT_COLUMNS = {
    "timestamp": "TEXT NOT NULL",
    "source": "TEXT NOT NULL",
    "sequence": "INTEGER",
    "voltage_v": "REAL",
    "current_ma": "REAL",
    "frequency_hz": "REAL",
    "device_timestamp": "TEXT NOT NULL DEFAULT ''",
    "protocol": "TEXT NOT NULL DEFAULT 'unknown'",
    "source_ip": "TEXT NOT NULL DEFAULT ''",
    "source_port": "INTEGER",
    "line_status": "TEXT NOT NULL DEFAULT 'RUNNING'",
    "connection_status": "TEXT NOT NULL DEFAULT 'CONNECTED'",
    "alarm_status": "TEXT NOT NULL DEFAULT 'NORMAL'",
    "status": "TEXT NOT NULL DEFAULT 'OK'",
    "payload_size": "INTEGER NOT NULL DEFAULT 0",
    "payload_sha256": "TEXT NOT NULL DEFAULT ''",
    "batch_id": "TEXT NOT NULL DEFAULT ''",
    "shift": "TEXT NOT NULL DEFAULT ''",
    "raw_payload": "TEXT NOT NULL DEFAULT ''",
}


def ensure_parent(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def connect_sqlite(path: str) -> sqlite3.Connection:
    ensure_parent(path)
    connection = sqlite3.connect(path, timeout=10)
    connection.execute("PRAGMA busy_timeout=10000")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    return connection


def init_sqlite(path: str) -> None:
    with closing(connect_sqlite(path)) as con:
        definitions = ",\n".join(
            ["id INTEGER PRIMARY KEY AUTOINCREMENT"]
            + [f"{name} {definition}" for name, definition in MEASUREMENT_COLUMNS.items()]
        )
        con.execute(f"CREATE TABLE IF NOT EXISTS measurements ({definitions})")

        existing = {
            row[1] for row in con.execute("PRAGMA table_info(measurements)").fetchall()
        }
        for name, definition in MEASUREMENT_COLUMNS.items():
            if name not in existing:
                con.execute(f"ALTER TABLE measurements ADD COLUMN {name} {definition}")

        con.execute(
            """
            CREATE TABLE IF NOT EXISTS collector_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                source TEXT NOT NULL,
                details TEXT NOT NULL
            )
            """
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_measurements_timestamp "
            "ON measurements(timestamp)"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_measurements_source_timestamp "
            "ON measurements(source_ip, timestamp)"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_measurements_alarm_timestamp "
            "ON measurements(alarm_status, timestamp) WHERE alarm_status = 'ALARM'"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_timestamp "
            "ON collector_events(timestamp)"
        )
        con.execute("PRAGMA optimize")
        con.commit()


def insert_measurements(con: sqlite3.Connection, rows: list[Measurement]) -> None:
    if not rows:
        return
    placeholders = ",".join("?" for _ in CSV_FIELDS)
    columns = ",".join(CSV_FIELDS)
    con.executemany(
        f"INSERT INTO measurements ({columns}) VALUES ({placeholders})",
        [tuple(asdict(row)[field] for field in CSV_FIELDS) for row in rows],
    )


def insert_events(con: sqlite3.Connection, events: list[dict[str, str]]) -> None:
    if not events:
        return
    con.executemany(
        """
        INSERT INTO collector_events
        (timestamp, event_type, severity, source, details)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (
                event["timestamp"],
                event["event_type"],
                event["severity"],
                event["source"],
                event["details"],
            )
            for event in events
        ],
    )


def append_sqlite(path: str, row: Measurement) -> None:
    init_sqlite(path)
    with closing(connect_sqlite(path)) as con:
        insert_measurements(con, [row])
        con.commit()


def append_csv(path: str, row: Measurement) -> None:
    ensure_parent(path)
    exists = os.path.exists(path) and os.path.getsize(path) > 0
    with open(path, "a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow(asdict(row))


class StorageWriter:
    def __init__(
        self,
        sqlite_path: str,
        raw_journal_path: str,
        queue_size: int = 10000,
        batch_size: int = 100,
        raw_journal_max_bytes: int = 104857600,
        raw_journal_backups: int = 5,
    ) -> None:
        self.sqlite_path = sqlite_path
        self.raw_journal_path = raw_journal_path
        self.batch_size = batch_size
        self.raw_journal_max_bytes = max(0, int(raw_journal_max_bytes))
        self.raw_journal_backups = max(0, int(raw_journal_backups))
        self._queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=queue_size)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._stats: dict[str, Any] = {
            "stored_measurements": 0,
            "stored_events": 0,
            "raw_packets": 0,
            "storage_errors": 0,
            "last_error": "",
        }
        init_sqlite(sqlite_path)
        ensure_parent(raw_journal_path)
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="vfreg-storage-writer",
        )
        self._thread.start()

    def submit_measurement(self, row: Measurement) -> None:
        self._queue.put(("measurement", row), timeout=5)

    def submit_raw(self, envelope: dict[str, Any]) -> None:
        self._queue.put(("raw", envelope), timeout=5)

    def submit_event(
        self,
        event_type: str,
        source: str,
        details: str,
        severity: str = "INFO",
    ) -> None:
        event = {
            "timestamp": now_iso(),
            "event_type": event_type,
            "severity": severity,
            "source": source,
            "details": details,
        }
        self._queue.put(("event", event), timeout=5)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            result = dict(self._stats)
        result["queue_depth"] = self._queue.qsize()
        result["writer_alive"] = self._thread.is_alive()
        result["raw_journal_path"] = self.raw_journal_path
        result["raw_journal_bytes"] = (
            os.path.getsize(self.raw_journal_path)
            if os.path.exists(self.raw_journal_path)
            else 0
        )
        return result

    def close(self, timeout: float = 5) -> None:
        self._stop.set()
        self._queue.put(("stop", None), timeout=timeout)
        self._thread.join(timeout=timeout)

    def _record_error(self, error: Exception) -> None:
        with self._lock:
            self._stats["storage_errors"] += 1
            self._stats["last_error"] = str(error)

    def _rotate_raw_journal(self) -> None:
        if (
            not self.raw_journal_max_bytes
            or not os.path.exists(self.raw_journal_path)
            or os.path.getsize(self.raw_journal_path) < self.raw_journal_max_bytes
        ):
            return
        if self.raw_journal_backups == 0:
            os.replace(self.raw_journal_path, self.raw_journal_path + ".discarded")
            return
        oldest = f"{self.raw_journal_path}.{self.raw_journal_backups}"
        if os.path.exists(oldest):
            os.remove(oldest)
        for number in range(self.raw_journal_backups - 1, 0, -1):
            source = f"{self.raw_journal_path}.{number}"
            if os.path.exists(source):
                os.replace(source, f"{self.raw_journal_path}.{number + 1}")
        os.replace(self.raw_journal_path, self.raw_journal_path + ".1")

    def _run(self) -> None:
        with closing(connect_sqlite(self.sqlite_path)) as con:
            while not self._stop.is_set() or not self._queue.empty():
                items: list[tuple[str, Any]] = []
                try:
                    items.append(self._queue.get(timeout=0.25))
                except queue.Empty:
                    continue
                while len(items) < self.batch_size:
                    try:
                        items.append(self._queue.get_nowait())
                    except queue.Empty:
                        break

                measurements = [item for kind, item in items if kind == "measurement"]
                events = [item for kind, item in items if kind == "event"]
                raw_packets = [item for kind, item in items if kind == "raw"]
                try:
                    if raw_packets:
                        self._rotate_raw_journal()
                        with open(self.raw_journal_path, "a", encoding="utf-8") as handle:
                            for envelope in raw_packets:
                                handle.write(json.dumps(envelope, separators=(",", ":")) + "\n")
                            handle.flush()
                    insert_measurements(con, measurements)
                    insert_events(con, events)
                    con.commit()
                    with self._lock:
                        self._stats["stored_measurements"] += len(measurements)
                        self._stats["stored_events"] += len(events)
                        self._stats["raw_packets"] += len(raw_packets)
                except (OSError, sqlite3.Error) as error:
                    con.rollback()
                    self._record_error(error)
                finally:
                    for _item in items:
                        self._queue.task_done()


def _measurement_filter(
    start_time: str | None = None,
    end_time: str | None = None,
) -> tuple[str, list[str]]:
    clauses: list[str] = []
    parameters: list[str] = []
    if start_time:
        clauses.append("timestamp >= ?")
        parameters.append(start_time)
    if end_time:
        clauses.append("timestamp <= ?")
        parameters.append(end_time)
    return (f" WHERE {' AND '.join(clauses)}" if clauses else "", parameters)


def fetch_recent(
    path: str,
    limit: int = 180,
    start_time: str | None = None,
    end_time: str | None = None,
) -> list[dict[str, Any]]:
    init_sqlite(path)
    safe_limit = max(1, min(int(limit), 5000))
    columns = ",".join(["id"] + CSV_FIELDS)
    where, parameters = _measurement_filter(start_time, end_time)
    with closing(connect_sqlite(path)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            f"SELECT {columns} FROM measurements{where} ORDER BY id DESC LIMIT ?",
            (*parameters, safe_limit),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def fetch_summary(
    path: str,
    start_time: str | None = None,
    end_time: str | None = None,
) -> dict[str, Any]:
    init_sqlite(path)
    where, parameters = _measurement_filter(start_time, end_time)
    with closing(connect_sqlite(path)) as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            f"""
            SELECT
                COUNT(*) AS count,
                SUM(CASE WHEN alarm_status = 'ALARM' THEN 1 ELSE 0 END) AS alarm_count,
                SUM(CASE WHEN status = 'RAW_ONLY' THEN 1 ELSE 0 END) AS raw_only_count,
                SUM(CASE WHEN status = 'PARTIAL' THEN 1 ELSE 0 END) AS partial_count,
                COUNT(DISTINCT source_ip) AS source_count,
                MIN(timestamp) AS first_timestamp,
                MAX(timestamp) AS last_timestamp
            FROM measurements
            {where}
            """,
            parameters,
        ).fetchone()
    return dict(row)


def fetch_events(path: str, limit: int = 50) -> list[dict[str, Any]]:
    init_sqlite(path)
    safe_limit = max(1, min(int(limit), 500))
    with closing(connect_sqlite(path)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM collector_events ORDER BY id DESC LIMIT ?",
            (safe_limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def iter_events(path: str):
    init_sqlite(path)
    con = connect_sqlite(path)
    con.row_factory = sqlite3.Row
    try:
        cursor = con.execute("SELECT * FROM collector_events ORDER BY id")
        for row in cursor:
            yield dict(row)
    finally:
        con.close()


def iter_measurements(
    path: str,
    start_time: str | None = None,
    end_time: str | None = None,
):
    init_sqlite(path)
    con = connect_sqlite(path)
    con.row_factory = sqlite3.Row
    columns = ",".join(CSV_FIELDS)
    where, parameters = _measurement_filter(start_time, end_time)
    try:
        cursor = con.execute(
            f"SELECT {columns} FROM measurements{where} ORDER BY id",
            parameters,
        )
        for row in cursor:
            yield dict(row)
    finally:
        con.close()


def export_csv(
    path: str,
    destination: str,
    start_time: str | None = None,
    end_time: str | None = None,
) -> str:
    ensure_parent(destination)
    with open(destination, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([heading for heading, _field in MANAGER_EXPORT_COLUMNS])
        for row in iter_measurements(path, start_time, end_time):
            writer.writerow(
                [
                    format_manager_timestamp(row.get(field))
                    if field == "timestamp"
                    else row.get(field)
                    for _heading, field in MANAGER_EXPORT_COLUMNS
                ]
            )
    return destination
