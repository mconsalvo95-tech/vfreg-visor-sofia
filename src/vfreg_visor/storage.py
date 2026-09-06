from __future__ import annotations

import csv
import json
import logging
import os
import queue
import shutil
import sqlite3
import sys
import threading
import time
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional


LOGGER = logging.getLogger("vfreg.storage")


class StorageError(RuntimeError):
    """Raised when the authoritative SQLite history is unusable."""


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
    quality_flag: str = "UNVERIFIED"
    quality_details: str = ""
    payload_size: int = 0
    payload_sha256: str = ""
    batch_id: str = ""
    shift: str = ""
    raw_payload: str = ""


CSV_FIELDS = list(Measurement.__dataclass_fields__)

MANAGER_EXPORT_COLUMNS = [
    ("Fecha", "timestamp_date"),
    ("Hora", "timestamp_time"),
    ("Volts", "voltage_v"),
    ("mAmp", "current_ma"),
    ("Frec", "frequency_hz"),
]


def format_manager_timestamp(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        return datetime.fromisoformat(str(value)).strftime("%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError):
        return str(value)


def manager_timestamp_parts(value: Any) -> tuple[str, str]:
    """Return sortable management-export date and time values with seconds."""
    formatted = format_manager_timestamp(value)
    try:
        parsed = datetime.strptime(formatted, "%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError):
        return formatted, ""
    return parsed.strftime("%Y-%m-%d"), parsed.strftime("%H:%M:%S")


def manager_export_values(row: dict[str, Any]) -> list[Any]:
    date_value, time_value = manager_timestamp_parts(row.get("timestamp"))
    return [
        date_value,
        time_value,
        row.get("voltage_v"),
        row.get("current_ma"),
        row.get("frequency_hz"),
    ]

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
    "quality_flag": "TEXT NOT NULL DEFAULT 'UNVERIFIED'",
    "quality_details": "TEXT NOT NULL DEFAULT ''",
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
    try:
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.Error:
        connection.close()
        raise
    return connection


def init_sqlite(path: str) -> None:
    try:
        con = connect_sqlite(path)
    except sqlite3.Error as error:
        raise StorageError(f"SQLite history could not be opened: {path}: {error}") from error
    with closing(con):
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


def verify_sqlite_integrity(path: str | Path) -> tuple[bool, str]:
    """Run SQLite's quick integrity check without modifying the database."""
    database = Path(path).resolve()
    if not database.is_file():
        return False, f"Database file does not exist: {database}"
    try:
        with closing(
            sqlite3.connect(database.as_uri() + "?mode=ro", timeout=10, uri=True)
        ) as con:
            result = str(con.execute("PRAGMA quick_check").fetchone()[0])
    except sqlite3.Error as error:
        return False, str(error)
    return result.lower() == "ok", result


def restore_sqlite_backup(backup_path: str | Path, destination: str | Path) -> str:
    """Restore a verified SQLite backup using an atomic destination replacement."""
    source = Path(backup_path).resolve()
    target = Path(destination).resolve()
    valid, detail = verify_sqlite_integrity(source)
    if not valid:
        raise StorageError(f"Backup failed SQLite integrity verification: {source}: {detail}")
    ensure_parent(str(target))
    temporary = target.with_suffix(target.suffix + ".restore.tmp")
    temporary.unlink(missing_ok=True)
    try:
        with closing(sqlite3.connect(str(source), timeout=10)) as source_con:
            with closing(sqlite3.connect(str(temporary), timeout=10)) as target_con:
                source_con.backup(target_con)
        restored, restored_detail = verify_sqlite_integrity(temporary)
        if not restored:
            raise StorageError(
                f"Restored database failed integrity verification: {restored_detail}"
            )
        os.replace(temporary, target)
        Path(str(target) + "-wal").unlink(missing_ok=True)
        Path(str(target) + "-shm").unlink(missing_ok=True)
    finally:
        temporary.unlink(missing_ok=True)
    return str(target)


def directory_size(path: str | Path) -> int:
    root = Path(path)
    if not root.exists():
        return 0
    total = 0
    for entry in root.rglob("*"):
        try:
            if entry.is_file():
                total += entry.stat().st_size
        except OSError:
            continue
    return total


def create_sqlite_backup(
    source_path: str | Path,
    backup_directory: str | Path,
    *,
    keep: int = 7,
    created_at: datetime | None = None,
) -> str:
    """Create and verify a SQLite online backup, then enforce backup retention."""
    source = Path(source_path).resolve()
    init_sqlite(str(source))
    backup_root = Path(backup_directory).resolve()
    backup_root.mkdir(parents=True, exist_ok=True)
    timestamp = (created_at or datetime.now().astimezone()).strftime("%Y%m%d-%H%M%S")
    destination = backup_root / f"vfreg-{timestamp}.sqlite"
    suffix = 1
    while destination.exists():
        destination = backup_root / f"vfreg-{timestamp}-{suffix}.sqlite"
        suffix += 1
    temporary = destination.with_suffix(".sqlite.tmp")
    temporary.unlink(missing_ok=True)
    try:
        with closing(connect_sqlite(str(source))) as source_con:
            with closing(sqlite3.connect(str(temporary), timeout=10)) as backup_con:
                source_con.backup(backup_con)
        valid, detail = verify_sqlite_integrity(temporary)
        if not valid:
            raise StorageError(f"New backup failed integrity verification: {detail}")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    backups = sorted(
        backup_root.glob("vfreg-*.sqlite"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for expired in backups[max(1, int(keep)) :]:
        expired.unlink(missing_ok=True)
    return str(destination)


def _delete_expired(
    con: sqlite3.Connection,
    measurement_retention_days: int,
    event_retention_days: int,
    *,
    now: datetime | None = None,
) -> tuple[int, int]:
    current = now or datetime.now().astimezone()
    measurement_cutoff = (
        current - timedelta(days=max(1, int(measurement_retention_days)))
    ).isoformat()
    event_cutoff = (
        current - timedelta(days=max(1, int(event_retention_days)))
    ).isoformat()
    measurement_cursor = con.execute(
        "DELETE FROM measurements WHERE timestamp < ?", (measurement_cutoff,)
    )
    event_cursor = con.execute(
        "DELETE FROM collector_events WHERE timestamp < ?", (event_cutoff,)
    )
    return max(0, measurement_cursor.rowcount), max(0, event_cursor.rowcount)


def prune_sqlite_history(
    path: str | Path,
    measurement_retention_days: int,
    event_retention_days: int,
    *,
    now: datetime | None = None,
) -> tuple[int, int]:
    """Delete records older than the configured policy and checkpoint the WAL."""
    init_sqlite(str(path))
    with closing(connect_sqlite(str(path))) as con:
        deleted = _delete_expired(
            con,
            measurement_retention_days,
            event_retention_days,
            now=now,
        )
        con.commit()
        if any(deleted):
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return deleted


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
        measurement_retention_days: int = 400,
        event_retention_days: int = 400,
        maintenance_interval_seconds: int = 3600,
        max_runtime_bytes: int = 12_000_000_000,
        warning_free_bytes: int = 5_000_000_000,
        critical_free_bytes: int = 2_000_000_000,
        backup_directory: str | None = None,
        backup_interval_hours: float = 24,
        backup_keep: int = 7,
    ) -> None:
        self.sqlite_path = sqlite_path
        self.raw_journal_path = raw_journal_path
        self.runtime_root = str(Path(sqlite_path).resolve().parent)
        self.batch_size = batch_size
        self.raw_journal_max_bytes = max(0, int(raw_journal_max_bytes))
        self.raw_journal_backups = max(0, int(raw_journal_backups))
        self.measurement_retention_days = max(1, int(measurement_retention_days))
        self.event_retention_days = max(1, int(event_retention_days))
        self.maintenance_interval_seconds = max(1, int(maintenance_interval_seconds))
        self.max_runtime_bytes = max(1, int(max_runtime_bytes))
        self.warning_free_bytes = max(0, int(warning_free_bytes))
        self.critical_free_bytes = max(0, int(critical_free_bytes))
        self.backup_directory = str(
            Path(backup_directory or Path(self.runtime_root) / "backups").resolve()
        )
        self.backup_interval_seconds = max(1.0, float(backup_interval_hours) * 3600)
        self.backup_keep = max(1, int(backup_keep))
        self._queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=queue_size)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._next_maintenance = 0.0
        self._storage_failure_active = False
        self._stats: dict[str, Any] = {
            "stored_measurements": 0,
            "stored_events": 0,
            "raw_packets": 0,
            "storage_errors": 0,
            "dropped_measurements": 0,
            "dropped_events": 0,
            "dropped_raw_packets": 0,
            "retention_measurements_deleted": 0,
            "retention_events_deleted": 0,
            "budget_measurements_deleted": 0,
            "budget_files_deleted": 0,
            "last_error": "",
            "last_maintenance_at": "",
            "last_backup_at": "",
            "last_backup_path": "",
            "storage_health": "STARTING",
        }
        init_sqlite(sqlite_path)
        valid, detail = verify_sqlite_integrity(sqlite_path)
        if not valid:
            raise StorageError(
                f"SQLite integrity check failed for {sqlite_path}: {detail}. "
                "Stop the collector and restore the latest verified backup."
            )
        ensure_parent(raw_journal_path)
        Path(self.backup_directory).mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="vfreg-storage-writer",
        )
        self._thread.start()

    def submit_measurement(self, row: Measurement) -> None:
        self._enqueue("measurement", row)

    def submit_raw(self, envelope: dict[str, Any]) -> None:
        self._enqueue("raw", envelope)

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
        self._enqueue("event", event)

    def _enqueue(self, kind: str, item: Any) -> None:
        try:
            self._queue.put((kind, item), timeout=5)
        except queue.Full:
            label = {
                "measurement": "dropped_measurements",
                "event": "dropped_events",
                "raw": "dropped_raw_packets",
            }[kind]
            error = StorageError(f"Storage queue is full; one {kind} record was dropped")
            with self._lock:
                self._stats[label] += 1
            self._record_error(error)

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
        try:
            result["runtime_bytes"] = directory_size(self.runtime_root)
            result["free_bytes"] = shutil.disk_usage(self.runtime_root).free
        except OSError as error:
            result["runtime_bytes"] = None
            result["free_bytes"] = None
            result["last_error"] = str(error)
        result["max_runtime_bytes"] = self.max_runtime_bytes
        return result

    def close(self, timeout: float = 5) -> None:
        self._stop.set()
        try:
            self._queue.put(("stop", None), timeout=timeout)
        except queue.Full:
            self._record_error(StorageError("Storage queue remained full during shutdown"))
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            self._record_error(StorageError("Storage writer did not stop within the timeout"))

    def _record_error(self, error: Exception) -> None:
        with self._lock:
            self._stats["storage_errors"] += 1
            self._stats["last_error"] = str(error)
            self._stats["storage_health"] = "CRITICAL"
        self._storage_failure_active = True
        message = f"VFREG STORAGE ERROR: {error}"
        print(message, file=sys.stderr)
        LOGGER.error("%s", error)

    def _backup_is_due(self) -> bool:
        backups = sorted(Path(self.backup_directory).glob("vfreg-*.sqlite"))
        if not backups:
            return True
        try:
            newest = max(path.stat().st_mtime for path in backups)
        except OSError:
            return True
        return time.time() - newest >= self.backup_interval_seconds

    def _create_backup(self, con: sqlite3.Connection) -> Path | None:
        count = int(con.execute("SELECT COUNT(*) FROM measurements").fetchone()[0])
        if count == 0 or not self._backup_is_due():
            return None
        return Path(
            create_sqlite_backup(
                self.sqlite_path,
                self.backup_directory,
                keep=self.backup_keep,
            )
        )

    def _apply_retention(self, con: sqlite3.Connection) -> tuple[int, int]:
        return _delete_expired(
            con,
            self.measurement_retention_days,
            self.event_retention_days,
        )

    def _storage_health(self) -> tuple[str, int, int]:
        runtime_bytes = directory_size(self.runtime_root)
        free_bytes = shutil.disk_usage(self.runtime_root).free
        if self._storage_failure_active:
            return "CRITICAL", runtime_bytes, free_bytes
        if free_bytes <= self.critical_free_bytes or runtime_bytes >= self.max_runtime_bytes:
            return "CRITICAL", runtime_bytes, free_bytes
        if (
            free_bytes <= self.warning_free_bytes
            or runtime_bytes >= int(self.max_runtime_bytes * 0.8)
        ):
            return "WARNING", runtime_bytes, free_bytes
        return "HEALTHY", runtime_bytes, free_bytes

    def _enforce_storage_budget(self, con: sqlite3.Connection) -> tuple[int, int]:
        """Bound growth by pruning oldest disposable evidence before the hard limit."""
        target = int(self.max_runtime_bytes * 0.9)
        runtime_bytes = directory_size(self.runtime_root)
        if runtime_bytes < target:
            return 0, 0

        files_deleted = 0
        backups = sorted(
            Path(self.backup_directory).glob("vfreg-*.sqlite"),
            key=lambda path: path.stat().st_mtime,
        )
        while runtime_bytes >= target and len(backups) > 1:
            backups.pop(0).unlink(missing_ok=True)
            files_deleted += 1
            runtime_bytes = directory_size(self.runtime_root)

        raw_backups = sorted(
            Path(self.raw_journal_path).parent.glob(
                Path(self.raw_journal_path).name + ".*"
            ),
            key=lambda path: path.stat().st_mtime,
        )
        while runtime_bytes >= target and raw_backups:
            raw_backups.pop(0).unlink(missing_ok=True)
            files_deleted += 1
            runtime_bytes = directory_size(self.runtime_root)

        measurements_deleted = 0
        if runtime_bytes >= target:
            page_count = int(con.execute("PRAGMA page_count").fetchone()[0])
            free_pages = int(con.execute("PRAGMA freelist_count").fetchone()[0])
            page_size = int(con.execute("PRAGMA page_size").fetchone()[0])
            reusable_bytes = free_pages * page_size
            desired_reusable = max(10_000_000, int(page_count * page_size * 0.1))
            if reusable_bytes < desired_reusable:
                row_count = int(
                    con.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]
                )
                delete_count = min(max(0, row_count - 100), max(1000, row_count // 10))
                if delete_count:
                    cursor = con.execute(
                        "DELETE FROM measurements WHERE id IN "
                        "(SELECT id FROM measurements ORDER BY id LIMIT ?)",
                        (delete_count,),
                    )
                    measurements_deleted = max(0, cursor.rowcount)
                    con.commit()
                    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return measurements_deleted, files_deleted

    def _run_maintenance(self, con: sqlite3.Connection) -> None:
        now_monotonic = time.monotonic()
        if now_monotonic < self._next_maintenance:
            return
        self._next_maintenance = now_monotonic + self.maintenance_interval_seconds
        try:
            measurements_deleted, events_deleted = self._apply_retention(con)
            con.commit()
            if measurements_deleted or events_deleted:
                con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            backup = self._create_backup(con)
            budget_measurements_deleted, budget_files_deleted = (
                self._enforce_storage_budget(con)
            )
            health, runtime_bytes, free_bytes = self._storage_health()
            timestamp = now_iso()
            with self._lock:
                previous_health = self._stats["storage_health"]
                self._stats["retention_measurements_deleted"] += measurements_deleted
                self._stats["retention_events_deleted"] += events_deleted
                self._stats["budget_measurements_deleted"] += budget_measurements_deleted
                self._stats["budget_files_deleted"] += budget_files_deleted
                self._stats["last_maintenance_at"] = timestamp
                self._stats["storage_health"] = health
                self._stats["runtime_bytes"] = runtime_bytes
                self._stats["free_bytes"] = free_bytes
                if backup is not None:
                    self._stats["last_backup_at"] = timestamp
                    self._stats["last_backup_path"] = str(backup)
            maintenance_events: list[dict[str, str]] = []
            if backup is not None:
                maintenance_events.append(
                    {
                        "timestamp": timestamp,
                        "event_type": "DATABASE_BACKUP_CREATED",
                        "severity": "INFO",
                        "source": "storage",
                        "details": str(backup),
                    }
                )
                LOGGER.info("Database backup created: %s", backup)
            if budget_measurements_deleted or budget_files_deleted:
                maintenance_events.append(
                    {
                        "timestamp": timestamp,
                        "event_type": "STORAGE_BUDGET_PRUNED",
                        "severity": "WARN",
                        "source": "storage",
                        "details": (
                            f"oldest_measurements={budget_measurements_deleted}; "
                            f"expired_evidence_files={budget_files_deleted}; "
                            f"budget_bytes={self.max_runtime_bytes}"
                        ),
                    }
                )
                LOGGER.warning(
                    "Storage budget pruning measurements=%s files=%s",
                    budget_measurements_deleted,
                    budget_files_deleted,
                )
            if health != previous_health and health in {"WARNING", "CRITICAL"}:
                maintenance_events.append(
                    {
                        "timestamp": timestamp,
                        "event_type": "STORAGE_HEALTH_CHANGED",
                        "severity": "ERROR" if health == "CRITICAL" else "WARN",
                        "source": "storage",
                        "details": (
                            f"health={health}; runtime_bytes={runtime_bytes}; "
                            f"free_bytes={free_bytes}; budget_bytes={self.max_runtime_bytes}"
                        ),
                    }
                )
                LOGGER.warning(
                    "Storage health %s runtime_bytes=%s free_bytes=%s budget_bytes=%s",
                    health,
                    runtime_bytes,
                    free_bytes,
                    self.max_runtime_bytes,
                )
            insert_events(con, maintenance_events)
            con.commit()
        except (OSError, sqlite3.Error, StorageError) as error:
            con.rollback()
            self._record_error(error)

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
                    self._run_maintenance(con)
                    continue
                while len(items) < self.batch_size:
                    try:
                        items.append(self._queue.get_nowait())
                    except queue.Empty:
                        break

                measurements = [item for kind, item in items if kind == "measurement"]
                events = [item for kind, item in items if kind == "event"]
                raw_packets = [item for kind, item in items if kind == "raw"]
                failure_was_active = self._storage_failure_active
                raw_succeeded = True
                try:
                    if raw_packets:
                        self._rotate_raw_journal()
                        with open(self.raw_journal_path, "a", encoding="utf-8") as handle:
                            for envelope in raw_packets:
                                handle.write(json.dumps(envelope, separators=(",", ":")) + "\n")
                            handle.flush()
                except OSError as error:
                    raw_succeeded = False
                    with self._lock:
                        self._stats["dropped_raw_packets"] += len(raw_packets)
                    self._record_error(error)
                try:
                    insert_measurements(con, measurements)
                    insert_events(con, events)
                    con.commit()
                    if failure_was_active and raw_succeeded:
                        recovered = {
                            "timestamp": now_iso(),
                            "event_type": "STORAGE_RECOVERED",
                            "severity": "INFO",
                            "source": "storage",
                            "details": "Storage writes resumed after an error",
                        }
                        insert_events(con, [recovered])
                        con.commit()
                        self._storage_failure_active = False
                        LOGGER.info("Storage writes recovered")
                    with self._lock:
                        self._stats["stored_measurements"] += len(measurements)
                        self._stats["stored_events"] += len(events)
                except sqlite3.Error as error:
                    con.rollback()
                    with self._lock:
                        self._stats["dropped_measurements"] += len(measurements)
                        self._stats["dropped_events"] += len(events)
                    self._record_error(error)
                finally:
                    if raw_succeeded:
                        with self._lock:
                            self._stats["raw_packets"] += len(raw_packets)
                    for _item in items:
                        self._queue.task_done()
                self._run_maintenance(con)


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
    safe_limit = max(1, min(int(limit), 10000))
    columns = ",".join(["id"] + CSV_FIELDS)
    where, parameters = _measurement_filter(start_time, end_time)
    with closing(connect_sqlite(path)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            f"SELECT {columns} FROM measurements{where} ORDER BY id DESC LIMIT ?",
            (*parameters, safe_limit),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def fetch_recent_with_count(
    path: str,
    limit: int = 180,
    start_time: str | None = None,
    end_time: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Return rows and their total from one SQLite read snapshot."""
    init_sqlite(path)
    safe_limit = max(1, min(int(limit), 10000))
    columns = ",".join(["id"] + CSV_FIELDS)
    where, parameters = _measurement_filter(start_time, end_time)
    with closing(connect_sqlite(path)) as con:
        con.row_factory = sqlite3.Row
        con.execute("BEGIN")
        total = int(
            con.execute(
                f"SELECT COUNT(*) FROM measurements{where}", parameters
            ).fetchone()[0]
        )
        rows = con.execute(
            f"SELECT {columns} FROM measurements{where} ORDER BY id DESC LIMIT ?",
            (*parameters, safe_limit),
        ).fetchall()
        con.rollback()
    return [dict(row) for row in reversed(rows)], total


def fetch_sampled_interval(
    path: str,
    interval_minutes: int,
    start_time: str,
    end_time: str,
) -> tuple[list[dict[str, Any]], int]:
    """Select the first real reading in each interval aligned to start_time."""
    interval_seconds = int(interval_minutes) * 60
    if interval_seconds <= 0:
        raise ValueError("interval_minutes must be positive")
    init_sqlite(path)
    columns = ",".join(["id"] + CSV_FIELDS)
    where, parameters = _measurement_filter(start_time, end_time)
    with closing(connect_sqlite(path)) as con:
        con.row_factory = sqlite3.Row
        con.execute("BEGIN")
        source_count = int(
            con.execute(
                f"SELECT COUNT(*) FROM measurements{where}", parameters
            ).fetchone()[0]
        )
        rows = con.execute(
            f"""
            WITH bucketed AS (
                SELECT {columns},
                    CAST((unixepoch(timestamp) - unixepoch(?)) / ? AS INTEGER)
                    AS sample_bucket
                FROM measurements
                {where}
            ), ranked AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY sample_bucket ORDER BY timestamp ASC, id ASC
                ) AS sample_rank
                FROM bucketed
            )
            SELECT {columns}
            FROM ranked
            WHERE sample_rank = 1
            ORDER BY id ASC
            LIMIT 10000
            """,
            (start_time, interval_seconds, *parameters),
        ).fetchall()
        con.rollback()
    return [dict(row) for row in rows], source_count


def _fetch_summary(
    con: sqlite3.Connection,
    start_time: str | None = None,
    end_time: str | None = None,
) -> dict[str, Any]:
    where, parameters = _measurement_filter(start_time, end_time)
    row = con.execute(
        f"""
        SELECT
            COUNT(*) AS count,
            SUM(CASE WHEN alarm_status = 'ALARM' THEN 1 ELSE 0 END) AS alarm_count,
            SUM(CASE WHEN status = 'RAW_ONLY' THEN 1 ELSE 0 END) AS raw_only_count,
            SUM(CASE WHEN status = 'PARTIAL' THEN 1 ELSE 0 END) AS partial_count,
            SUM(CASE WHEN quality_flag IN ('INVALID', 'INCOMPLETE', 'OUT_OF_RANGE')
                THEN 1 ELSE 0 END) AS quality_issue_count,
            SUM(CASE WHEN quality_flag = 'UNVERIFIED' THEN 1 ELSE 0 END)
                AS unverified_count,
            COUNT(DISTINCT source_ip) AS source_count,
            MIN(timestamp) AS first_timestamp,
            MAX(timestamp) AS last_timestamp
        FROM measurements
        {where}
        """,
        parameters,
    ).fetchone()
    return dict(row)


def fetch_summary(
    path: str,
    start_time: str | None = None,
    end_time: str | None = None,
) -> dict[str, Any]:
    init_sqlite(path)
    with closing(connect_sqlite(path)) as con:
        con.row_factory = sqlite3.Row
        return _fetch_summary(con, start_time, end_time)


@contextmanager
def measurement_snapshot(
    path: str,
    start_time: str | None = None,
    end_time: str | None = None,
):
    """Yield report metadata and rows from one consistent SQLite read snapshot."""
    init_sqlite(path)
    con = connect_sqlite(path)
    con.row_factory = sqlite3.Row
    where, parameters = _measurement_filter(start_time, end_time)
    try:
        con.execute("BEGIN")
        summary = _fetch_summary(con, start_time, end_time)
        cursor = con.execute(
            f"SELECT {','.join(CSV_FIELDS)} FROM measurements{where} ORDER BY id",
            parameters,
        )
        yield summary, (dict(row) for row in cursor)
    finally:
        con.rollback()
        con.close()


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
            writer.writerow(manager_export_values(row))
    return destination
