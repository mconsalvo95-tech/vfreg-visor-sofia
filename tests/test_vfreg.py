from __future__ import annotations

import csv
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from importlib.metadata import version as package_version
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook

PROJECT_ROOT = Path(__file__).resolve().parent.parent

from vfreg_visor import __version__  # noqa: E402
from vfreg_visor.config import (  # noqa: E402
    ConfigError,
    load_config,
    persist_poll_interval,
)
from vfreg_visor.cli import (  # noqa: E402
    StartupError,
    _create_dashboard_server,
    open_dashboard,
)
from vfreg_visor.dashboard import (  # noqa: E402
    DashboardHandler,
    DashboardServer,
    connection_state,
    parse_time_range,
)
from vfreg_visor.instance import (  # noqa: E402
    DeploymentInstanceLock,
    InstanceAlreadyRunning,
)
from vfreg_visor.modbus import (  # noqa: E402
    ModbusTcpCollector,
    build_modbus_request,
    parse_modbus_response,
)
from vfreg_visor.network import parse_payload  # noqa: E402
from vfreg_visor.operational_log import configure_operational_logging  # noqa: E402
from vfreg_visor.preflight import run_preflight  # noqa: E402
from vfreg_visor.simulator import build_packet  # noqa: E402
from vfreg_visor.storage import (  # noqa: E402
    Measurement,
    StorageWriter,
    append_csv,
    append_sqlite,
    connect_sqlite,
    create_sqlite_backup,
    export_csv,
    fetch_recent,
    fetch_recent_with_count,
    fetch_sampled_interval,
    fetch_summary,
    init_sqlite,
    insert_measurements,
    iter_events,
    now_iso,
    prune_sqlite_history,
    restore_sqlite_backup,
    StorageError,
    verify_sqlite_integrity,
)


def config() -> dict:
    return {
        "device_name": "VFREG-SIM",
        "simulator": {
            "base_voltage_v": 115,
            "base_current_ma": 1200,
            "base_frequency_hz": 800,
        },
        "limits": {
            "voltage_v": {"min": 90, "max": 130},
            "current_ma": {"min": 800, "max": 1600},
            "frequency_hz": {"min": 700, "max": 900},
        },
    }


class PayloadTests(unittest.TestCase):
    def test_json_packet_is_parsed(self) -> None:
        packet = build_packet(7, config(), "normal")
        row = parse_payload(json.dumps(packet).encode(), config())
        self.assertEqual(row.sequence, 7)
        self.assertEqual(row.status, "OK")
        self.assertEqual(row.alarm_status, "NORMAL")
        self.assertIsNotNone(row.current_ma)
        self.assertTrue(row.device_timestamp)
        self.assertEqual(row.device_timestamp, packet["measured_at"])
        self.assertTrue(row.timestamp)
        self.assertEqual(len(row.payload_sha256), 64)

    def test_stopped_simulator_packet_is_zeroed(self) -> None:
        packet = build_packet(64, config(), "mixed")
        self.assertEqual(packet["line_status"], "STOPPED")
        self.assertEqual(packet["voltage_v"], 0)
        self.assertEqual(packet["current_ma"], 0)
        self.assertEqual(packet["frequency_hz"], 0)

    def test_out_of_range_value_creates_alarm(self) -> None:
        payload = b'{"voltage_v":115,"current_ma":1700,"frequency_hz":800}'
        row = parse_payload(payload, config())
        self.assertEqual(row.alarm_status, "ALARM")

    def test_stopped_line_does_not_create_process_alarm(self) -> None:
        payload = b'{"voltage_v":0,"current_ma":0,"frequency_hz":0,"line_status":"STOPPED"}'
        row = parse_payload(payload, config())
        self.assertEqual(row.alarm_status, "NORMAL")
        self.assertEqual(row.line_status, "STOPPED")

    def test_legacy_text_packet_is_supported(self) -> None:
        row = parse_payload(b"V=112.4;mA=1198;F=802", config())
        self.assertEqual(row.voltage_v, 112.4)
        self.assertEqual(row.current_ma, 1198)
        self.assertEqual(row.frequency_hz, 802)

    def test_binary_packet_is_preserved_as_raw(self) -> None:
        row = parse_payload(b"\x00\xff\x10\x81", config())
        self.assertEqual(row.status, "RAW_ONLY")
        self.assertTrue(row.raw_payload.startswith("base64:"))
        self.assertEqual(row.payload_size, 4)
        self.assertEqual(row.quality_flag, "INVALID")


class ModbusTests(unittest.TestCase):
    def factory_config(self) -> dict:
        return {
            "network": {
                "mode": "modbus_tcp_client",
                "tcp_host": "192.168.1.7",
                "tcp_port": 502,
                "modbus": {
                    "unit_id": 5,
                    "function_code": 4,
                    "start_register": 0,
                    "quantity": 3,
                    "register_map": {
                        "voltage_v": {"register": 0, "scale": 1},
                        "current_ma": {"register": 1, "scale": 1},
                        "frequency_hz": {"register": 2, "scale": 1},
                    },
                },
            },
            "factory": {"batch_id": "B1", "shift": "day"},
            "limits": {"confirmed": False},
        }

    def test_confirmed_factory_request(self) -> None:
        request = build_modbus_request(5, 5, 4, 0, 3)
        self.assertEqual(request.hex(), "000500000006050400000003")

    def test_confirmed_factory_response_mapping(self) -> None:
        response = bytes.fromhex("000500000009050406002501a900cb")
        row = parse_modbus_response(
            response, self.factory_config(), expected_transaction_id=5
        )
        self.assertEqual(row.voltage_v, 37)
        self.assertEqual(row.current_ma, 425)
        self.assertEqual(row.frequency_hz, 203)
        self.assertEqual(row.protocol, "modbus_tcp")
        self.assertEqual(row.batch_id, "B1")
        self.assertEqual(row.alarm_status, "NORMAL")
        self.assertEqual(row.quality_flag, "UNVERIFIED")

    def test_confirmed_limits_mark_out_of_range_quality(self) -> None:
        cfg = self.factory_config()
        cfg["limits"] = {
            "confirmed": True,
            "voltage_v": {"min": 40, "max": 50},
            "current_ma": {"min": 400, "max": 500},
            "frequency_hz": {"min": 190, "max": 210},
        }
        response = bytes.fromhex("000500000009050406002501a900cb")
        row = parse_modbus_response(response, cfg, expected_transaction_id=5)
        self.assertEqual(row.quality_flag, "OUT_OF_RANGE")
        self.assertIn("voltage_v=37", row.quality_details)
        self.assertEqual(row.alarm_status, "ALARM")

    def test_data_gap_is_recorded_when_readings_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sqlite_path = os.path.join(directory, "readings.sqlite")
            writer = StorageWriter(sqlite_path, os.path.join(directory, "raw.jsonl"))
            collector = ModbusTcpCollector(self.factory_config(), writer)
            collector._start_data_gap("modbus:test", "test timeout")
            response = bytes.fromhex("000500000009050406002501a900cb")
            collector._record(parse_modbus_response(response, self.factory_config()))
            writer.close()
            event_types = [event["event_type"] for event in iter_events(sqlite_path)]
            self.assertIn("DATA_GAP_STARTED", event_types)
            self.assertIn("DATA_GAP_ENDED", event_types)

    def test_modbus_write_function_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_modbus_request(1, 5, 6, 0, 1)
        with self.assertRaises(ValueError):
            build_modbus_request(1, 5, 3, 0, 1)

    def test_poll_interval_can_change_without_restarting_collector(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cfg = self.factory_config()
            writer = StorageWriter(
                os.path.join(directory, "readings.sqlite"),
                os.path.join(directory, "raw.jsonl"),
            )
            collector = ModbusTcpCollector(cfg, writer)
            self.assertEqual(collector.poll_interval_seconds(), 0.5)
            self.assertEqual(collector.set_poll_interval(5), 5)
            self.assertEqual(collector.snapshot()["poll_interval_seconds"], 5)
            self.assertEqual(
                cfg["network"]["modbus"]["poll_interval_seconds"], 5
            )
            with self.assertRaises(ValueError):
                collector.set_poll_interval(0.1)
            writer.close()

    def test_poll_interval_is_persisted_in_factory_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "config.factory.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(self.factory_config(), handle)
            persist_poll_interval(path, 60)
            with open(path, "r", encoding="utf-8") as handle:
                saved = json.load(handle)
            self.assertEqual(
                saved["network"]["modbus"]["poll_interval_seconds"], 60
            )

    def test_modbus_client_polls_and_stores_confirmed_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            port = server.getsockname()[1]

            def serve_one_response() -> None:
                try:
                    connection, _address = server.accept()
                    with connection:
                        request = b""
                        while len(request) < 12:
                            chunk = connection.recv(12 - len(request))
                            if not chunk:
                                return
                            request += chunk
                        response = request[:2] + bytes.fromhex(
                            "00000009050406002501a900cb"
                        )
                        connection.sendall(response)
                        time.sleep(0.1)
                finally:
                    server.close()

            server_thread = threading.Thread(target=serve_one_response, daemon=True)
            server_thread.start()
            cfg = self.factory_config()
            cfg["network"]["tcp_host"] = "127.0.0.1"
            cfg["network"]["tcp_port"] = port
            cfg["network"]["reconnect_delay_seconds"] = 0.1
            cfg["network"]["modbus"].update(
                {"poll_interval_seconds": 10, "request_timeout_seconds": 1}
            )
            sqlite_path = os.path.join(directory, "readings.sqlite")
            journal_path = os.path.join(directory, "raw.jsonl")
            writer = StorageWriter(sqlite_path, journal_path)
            collector = ModbusTcpCollector(cfg, writer).start()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if collector.snapshot()["parsed_packets"]:
                    break
                time.sleep(0.02)
            collector.stop()
            writer.close()
            server_thread.join(timeout=1)
            rows = fetch_recent(sqlite_path, 5)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["voltage_v"], 37)
            self.assertEqual(rows[0]["current_ma"], 425)
            self.assertEqual(rows[0]["frequency_hz"], 203)
            with open(journal_path, "r", encoding="utf-8") as handle:
                journal = [json.loads(line) for line in handle]
            self.assertEqual(
                [entry["direction"] for entry in journal], ["sent", "received"]
            )


class StorageTests(unittest.TestCase):
    def test_csv_and_sqlite_round_trip(self) -> None:
        row = Measurement(
            timestamp=now_iso(),
            source="test",
            sequence=1,
            voltage_v=115,
            current_ma=1200,
            frequency_hz=800,
        )
        with tempfile.TemporaryDirectory() as directory:
            csv_path = os.path.join(directory, "readings.csv")
            sqlite_path = os.path.join(directory, "readings.sqlite")
            append_csv(csv_path, row)
            append_sqlite(sqlite_path, row)
            self.assertTrue(os.path.exists(csv_path))
            self.assertEqual(fetch_recent(sqlite_path, 5)[0]["sequence"], 1)
            self.assertEqual(fetch_summary(sqlite_path)["count"], 1)

    def test_recent_records_keep_dataclass_fields(self) -> None:
        row = Measurement(now_iso(), "test", 1, 115, 1200, 800)
        self.assertIn("current_ma", asdict(row))

    def test_old_database_schema_is_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sqlite_path = os.path.join(directory, "old.sqlite")
            con = sqlite3.connect(sqlite_path)
            con.execute(
                """
                CREATE TABLE measurements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    source TEXT NOT NULL,
                    sequence INTEGER,
                    voltage_v REAL,
                    current_ma REAL,
                    frequency_hz REAL,
                    line_status TEXT NOT NULL,
                    connection_status TEXT NOT NULL,
                    alarm_status TEXT NOT NULL,
                    status TEXT NOT NULL,
                    raw_payload TEXT NOT NULL
                )
                """
            )
            con.commit()
            con.close()
            init_sqlite(sqlite_path)
            con = sqlite3.connect(sqlite_path)
            columns = {row[1] for row in con.execute("PRAGMA table_info(measurements)")}
            con.close()
            self.assertIn("device_timestamp", columns)
            self.assertIn("payload_sha256", columns)
            self.assertIn("batch_id", columns)
            self.assertIn("quality_flag", columns)

    def test_storage_writer_persists_raw_packets_and_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sqlite_path = os.path.join(directory, "readings.sqlite")
            journal_path = os.path.join(directory, "raw.jsonl")
            writer = StorageWriter(sqlite_path, journal_path)
            row = Measurement(now_iso(), "udp:test", 1, 115, 1200, 800)
            writer.submit_raw({"received_at": now_iso(), "payload_base64": "e30="})
            writer.submit_measurement(row)
            writer.submit_event("CONNECTED", "udp:test", "test event")
            writer.close()
            self.assertEqual(fetch_summary(sqlite_path)["count"], 1)
            with open(journal_path, "r", encoding="utf-8") as handle:
                self.assertEqual(len(handle.readlines()), 1)
            events = list(iter_events(sqlite_path))
            self.assertEqual(events[0]["event_type"], "CONNECTED")

    def test_storage_failure_is_visible_and_writer_stops_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            writer = StorageWriter(
                os.path.join(directory, "readings.sqlite"),
                os.path.join(directory, "raw.jsonl"),
            )
            with patch(
                "vfreg_visor.storage.insert_measurements",
                side_effect=sqlite3.OperationalError("disk full"),
            ):
                writer.submit_measurement(
                    Measurement(now_iso(), "test", 1, 35, 340, 202)
                )
                writer.close()
            snapshot = writer.snapshot()
            self.assertGreaterEqual(snapshot["storage_errors"], 1)
            self.assertEqual(snapshot["dropped_measurements"], 1)
            self.assertEqual(snapshot["storage_health"], "CRITICAL")
            self.assertFalse(snapshot["writer_alive"])

    def test_corrupt_database_stops_storage_startup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sqlite_path = os.path.join(directory, "corrupt.sqlite")
            with open(sqlite_path, "wb") as handle:
                handle.write(b"not a sqlite database")
            with self.assertRaises(StorageError):
                StorageWriter(sqlite_path, os.path.join(directory, "raw.jsonl"))

    def test_raw_journal_rotates_without_losing_packets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sqlite_path = os.path.join(directory, "readings.sqlite")
            journal_path = os.path.join(directory, "raw.jsonl")
            writer = StorageWriter(
                sqlite_path,
                journal_path,
                batch_size=1,
                raw_journal_max_bytes=1,
                raw_journal_backups=2,
            )
            writer.submit_raw({"packet": 1})
            writer.submit_raw({"packet": 2})
            writer.close()
            paths = [journal_path, journal_path + ".1"]
            packets = []
            for path in paths:
                with open(path, "r", encoding="utf-8") as handle:
                    packets.extend(json.loads(line)["packet"] for line in handle)
            self.assertEqual(sorted(packets), [1, 2])

    def test_retention_deletes_old_history_but_keeps_recent_readings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sqlite_path = os.path.join(directory, "readings.sqlite")
            current = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
            append_sqlite(
                sqlite_path,
                Measurement(
                    (current - timedelta(days=91)).isoformat(),
                    "old",
                    1,
                    35,
                    340,
                    202,
                ),
            )
            append_sqlite(
                sqlite_path,
                Measurement(current.isoformat(), "recent", 2, 36, 341, 203),
            )
            deleted, _events_deleted = prune_sqlite_history(
                sqlite_path, 90, 180, now=current
            )
            self.assertEqual(deleted, 1)
            self.assertEqual(
                [row["source"] for row in fetch_recent(sqlite_path, 10)], ["recent"]
            )

    def test_verified_backup_can_be_restored_and_exported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sqlite_path = os.path.join(directory, "readings.sqlite")
            backups = os.path.join(directory, "backups")
            append_sqlite(
                sqlite_path,
                Measurement(now_iso(), "before-backup", 1, 35, 340, 202),
            )
            backup = create_sqlite_backup(sqlite_path, backups, keep=2)
            valid, detail = verify_sqlite_integrity(backup)
            self.assertTrue(valid, detail)
            append_sqlite(
                sqlite_path,
                Measurement(now_iso(), "after-backup", 2, 36, 341, 203),
            )
            restored_path = os.path.join(directory, "restored.sqlite")
            restore_sqlite_backup(backup, restored_path)
            self.assertEqual(fetch_summary(restored_path)["count"], 1)
            csv_path = os.path.join(directory, "restored.csv")
            export_csv(restored_path, csv_path)
            with open(csv_path, "r", encoding="utf-8") as handle:
                self.assertEqual(len(handle.readlines()), 2)

    def test_integrity_check_does_not_create_a_missing_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.sqlite"
            valid, detail = verify_sqlite_integrity(missing)
            self.assertFalse(valid)
            self.assertIn("does not exist", detail)
            self.assertFalse(missing.exists())

    def test_writer_creates_first_scheduled_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sqlite_path = os.path.join(directory, "readings.sqlite")
            backup_directory = os.path.join(directory, "backups")
            writer = StorageWriter(
                sqlite_path,
                os.path.join(directory, "raw.jsonl"),
                backup_directory=backup_directory,
                backup_keep=2,
            )
            writer.submit_measurement(
                Measurement(now_iso(), "test", 1, 35, 340, 202)
            )
            writer.close()
            backups = list(Path(backup_directory).glob("vfreg-*.sqlite"))
            self.assertEqual(len(backups), 1)
            self.assertTrue(verify_sqlite_integrity(backups[0])[0])

    def test_storage_budget_prunes_oldest_rows_before_unbounded_growth(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sqlite_path = os.path.join(directory, "readings.sqlite")
            init_sqlite(sqlite_path)
            con = connect_sqlite(sqlite_path)
            insert_measurements(
                con,
                [
                    Measurement(now_iso(), "budget", index, 35, 340, 202)
                    for index in range(200)
                ],
            )
            con.commit()
            con.close()
            writer = StorageWriter(
                sqlite_path,
                os.path.join(directory, "raw.jsonl"),
                max_runtime_bytes=1000,
                maintenance_interval_seconds=1,
            )
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if writer.snapshot()["budget_measurements_deleted"]:
                    break
                time.sleep(0.05)
            snapshot = writer.snapshot()
            writer.close()
            self.assertGreater(snapshot["budget_measurements_deleted"], 0)
            self.assertLess(fetch_summary(sqlite_path)["count"], 200)

    def test_sqlite_wal_recovers_committed_record_after_abrupt_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sqlite_path = os.path.join(directory, "unexpected.sqlite")
            script = (
                "import os; "
                "from vfreg_visor.storage import Measurement, append_sqlite, now_iso; "
                f"append_sqlite({sqlite_path!r}, Measurement(now_iso(), 'abrupt', 1, 35, 340, 202)); "
                "os._exit(0)"
            )
            completed = subprocess.run([sys.executable, "-c", script], check=False)
            self.assertEqual(completed.returncode, 0)
            self.assertEqual(fetch_summary(sqlite_path)["count"], 1)
            self.assertTrue(verify_sqlite_integrity(sqlite_path)[0])

    def test_collector_timestamp_always_contains_timezone(self) -> None:
        parsed = datetime.fromisoformat(now_iso())
        self.assertIsNotNone(parsed.utcoffset())

    def test_application_log_rotation_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = os.path.join(directory, "vfreg.log")
            logger = configure_operational_logging(
                {
                    "storage": {
                        "application_log": log_path,
                        "application_log_max_bytes": 1024,
                        "application_log_backups": 2,
                    }
                }
            )
            for index in range(200):
                logger.info("rotation-test-%04d-%s", index, "x" * 80)
            for handler in list(logger.handlers):
                handler.close()
                logger.removeHandler(handler)
            self.assertLessEqual(len(list(Path(directory).glob("vfreg.log*"))), 3)

    def test_csv_export_is_not_limited_to_5000_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sqlite_path = os.path.join(directory, "readings.sqlite")
            csv_path = os.path.join(directory, "readings.csv")
            init_sqlite(sqlite_path)
            rows = [
                Measurement(now_iso(), "test", index, 115, 1200, 800)
                for index in range(5001)
            ]
            con = connect_sqlite(sqlite_path)
            insert_measurements(con, rows)
            con.commit()
            con.close()
            export_csv(sqlite_path, csv_path)
            with open(csv_path, "r", encoding="utf-8") as handle:
                lines = handle.readlines()
            self.assertEqual(len(lines), 5002)
            self.assertEqual(lines[0].strip(), "Fecha,Hora,Volts,mAmp,Frec")

    def test_manager_csv_uses_human_readable_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sqlite_path = os.path.join(directory, "readings.sqlite")
            csv_path = os.path.join(directory, "readings.csv")
            append_sqlite(
                sqlite_path,
                Measurement(
                    "2026-08-21T11:38:10.870-03:00",
                    "test",
                    1,
                    35,
                    340,
                    202,
                ),
            )
            export_csv(sqlite_path, csv_path)
            with open(csv_path, "r", encoding="utf-8") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(rows[1][0], "2026-08-21")
            self.assertEqual(rows[1][1], "11:38:10")

    def test_history_range_filters_sqlite_and_csv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sqlite_path = os.path.join(directory, "readings.sqlite")
            csv_path = os.path.join(directory, "readings.csv")
            for sequence, timestamp in enumerate(
                (
                    "2026-08-21T10:00:00.000-03:00",
                    "2026-08-21T11:00:00.000-03:00",
                    "2026-08-21T12:00:00.000-03:00",
                ),
                start=1,
            ):
                append_sqlite(
                    sqlite_path,
                    Measurement(timestamp, "test", sequence, 35, 340, 202),
                )
            start = "2026-08-21T10:30:00.000000-03:00"
            end = "2026-08-21T11:30:00.999999-03:00"
            rows = fetch_recent(sqlite_path, 10, start, end)
            self.assertEqual([row["sequence"] for row in rows], [2])
            self.assertEqual(fetch_summary(sqlite_path, start, end)["count"], 1)
            export_csv(sqlite_path, csv_path, start, end)
            with open(csv_path, "r", encoding="utf-8") as handle:
                exported = list(csv.reader(handle))
            self.assertEqual(len(exported), 2)
            self.assertEqual(exported[1][0], "2026-08-21")
            self.assertEqual(exported[1][1], "11:00:00")

    def test_history_rows_and_count_share_one_database_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sqlite_path = os.path.join(directory, "readings.sqlite")
            for sequence in range(1, 4):
                append_sqlite(
                    sqlite_path,
                    Measurement(
                        f"2026-08-21T11:00:0{sequence}.000-03:00",
                        "test",
                        sequence,
                        35,
                        340,
                        202,
                    ),
                )
            rows, count = fetch_recent_with_count(sqlite_path, 2)
            self.assertEqual(count, 3)
            self.assertEqual([row["sequence"] for row in rows], [2, 3])

    def test_history_sampling_uses_first_real_reading_in_each_workday_interval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sqlite_path = os.path.join(directory, "readings.sqlite")
            start = datetime.fromisoformat("2026-08-21T06:00:00-03:00")
            for sequence in range(15):
                timestamp = (start + timedelta(minutes=sequence)).isoformat()
                append_sqlite(
                    sqlite_path,
                    Measurement(timestamp, "test", sequence, 35, 340, 202),
                )
            rows, source_count = fetch_sampled_interval(
                sqlite_path,
                5,
                start.isoformat(),
                (start + timedelta(minutes=14, seconds=59)).isoformat(),
            )
            self.assertEqual(source_count, 15)
            self.assertEqual([row["sequence"] for row in rows], [0, 5, 10])


class StatusTests(unittest.TestCase):
    def test_recent_measurement_is_connected(self) -> None:
        latest = {"timestamp": datetime.now().astimezone().isoformat()}
        self.assertEqual(connection_state(latest, 3), "CONNECTED")

    def test_missing_measurement_is_waiting(self) -> None:
        self.assertEqual(connection_state(None, 3), "WAITING")

    def test_time_range_validation_is_inclusive_and_rejects_reverse_range(self) -> None:
        start, end = parse_time_range(
            {"from": ["2026-08-21T11:00:00"], "to": ["2026-08-21T12:00:00"]}
        )
        self.assertEqual(datetime.fromisoformat(start).microsecond, 0)
        self.assertEqual(datetime.fromisoformat(end).microsecond, 999999)
        with self.assertRaisesRegex(ValueError, "before"):
            parse_time_range(
                {"from": ["2026-08-21T13:00:00"], "to": ["2026-08-21T12:00:00"]}
            )

    def test_history_api_and_exports_use_selected_period(self) -> None:
        class FakeCollector:
            def snapshot(self) -> dict:
                return {
                    "tcp_listener": "CLIENT_CONNECTED",
                    "poll_interval_seconds": 5,
                }

        with tempfile.TemporaryDirectory() as directory:
            sqlite_path = os.path.join(directory, "readings.sqlite")
            for sequence, timestamp in enumerate(
                (
                    "2026-08-21T10:00:00",
                    "2026-08-21T11:00:00",
                    "2026-08-21T12:00:00",
                ),
                start=1,
            ):
                append_sqlite(
                    sqlite_path,
                    Measurement(
                        datetime.fromisoformat(timestamp)
                        .astimezone()
                        .isoformat(timespec="milliseconds"),
                        "test",
                        sequence,
                        35,
                        340,
                        202,
                    ),
                )
            cfg = {
                "site_name": "test",
                "device_name": "test",
                "output_sqlite": sqlite_path,
                "output_csv": os.path.join(directory, "readings.csv"),
                "output_xlsx": os.path.join(directory, "readings.xlsx"),
                "network": {
                    "mode": "modbus_tcp_client",
                    "tcp_host": "127.0.0.1",
                    "tcp_port": 502,
                    "connection_timeout_seconds": 3,
                    "modbus": {"poll_interval_seconds": 5},
                },
                "factory": {},
                "limits": {"confirmed": False},
            }
            writer = StorageWriter(sqlite_path, os.path.join(directory, "raw.jsonl"))
            server = DashboardServer(("127.0.0.1", 0), DashboardHandler)
            server.cfg = cfg
            server.config_path = os.path.join(directory, "config.factory.json")
            server.collector = FakeCollector()
            server.writer = writer
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            query = urllib.parse.urlencode(
                {
                    "from": "2026-08-21T10:30:00",
                    "to": "2026-08-21T11:30:00",
                    "limit": 5000,
                }
            )
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urllib.request.urlopen(
                    f"{base}/api/readings?{query}", timeout=3
                ) as response:
                    result = json.load(response)
                self.assertEqual(result["count"], 1)
                self.assertEqual(result["readings"][0]["sequence"], 2)

                with urllib.request.urlopen(
                    f"{base}/api/export.csv?{query}", timeout=3
                ) as response:
                    exported_csv = response.read().decode("utf-8").splitlines()
                self.assertEqual(len(exported_csv), 2)

                with urllib.request.urlopen(
                    f"{base}/api/export.xlsx?{query}", timeout=3
                ) as response:
                    workbook = load_workbook(BytesIO(response.read()))
                self.assertEqual(workbook["Raw Data"].max_row, 2)

                invalid = urllib.parse.urlencode(
                    {"from": "2026-08-21T12:00:00", "to": "2026-08-21T11:00:00"}
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(f"{base}/api/readings?{invalid}", timeout=3)
                self.assertEqual(raised.exception.code, 400)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
                writer.close()

    def test_poll_interval_api_persists_and_applies_live(self) -> None:
        class FakeCollector:
            interval = 0.5

            def set_poll_interval(self, seconds: float) -> float:
                self.interval = float(seconds)
                return self.interval

            def snapshot(self) -> dict:
                return {
                    "tcp_listener": "CLIENT_CONNECTED",
                    "poll_interval_seconds": self.interval,
                }

        with tempfile.TemporaryDirectory() as directory:
            sqlite_path = os.path.join(directory, "readings.sqlite")
            journal_path = os.path.join(directory, "raw.jsonl")
            config_path = os.path.join(directory, "config.factory.json")
            cfg = {
                "site_name": "test",
                "device_name": "test",
                "output_sqlite": sqlite_path,
                "network": {
                    "mode": "modbus_tcp_client",
                    "tcp_host": "127.0.0.1",
                    "tcp_port": 502,
                    "connection_timeout_seconds": 3,
                    "modbus": {"poll_interval_seconds": 0.5},
                },
                "factory": {},
                "limits": {"confirmed": False},
            }
            with open(config_path, "w", encoding="utf-8") as handle:
                json.dump(cfg, handle)
            writer = StorageWriter(sqlite_path, journal_path)
            collector = FakeCollector()
            server = DashboardServer(("127.0.0.1", 0), DashboardHandler)
            server.cfg = cfg
            server.config_path = config_path
            server.collector = collector
            server.writer = writer
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}/api/poll-interval",
                    data=json.dumps({"seconds": 5}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=3) as response:
                    result = json.load(response)
                self.assertEqual(result["poll_interval_seconds"], 5)
                self.assertEqual(collector.interval, 5)
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{server.server_port}/api/status", timeout=3
                ) as response:
                    status = json.load(response)
                self.assertEqual(status["app_version"], "0.4.0.dev0")
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{server.server_port}/", timeout=3
                ) as response:
                    dashboard_html = response.read().decode("utf-8")
                self.assertIn('id="app-version"', dashboard_html)
                self.assertIn('id="history-filter-form"', dashboard_html)
                self.assertIn(">Support</a>", dashboard_html)
                with open(config_path, "r", encoding="utf-8") as handle:
                    saved = json.load(handle)
                self.assertEqual(
                    saved["network"]["modbus"]["poll_interval_seconds"], 5
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
                writer.close()


class PreflightTests(unittest.TestCase):
    def test_preflight_uses_configured_ports_and_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cfg = config()
            cfg.update({
                "output_csv": "data/readings.csv",
                "output_sqlite": "data/readings.sqlite",
                "output_xlsx": "data/readings.xlsx",
                "raw_journal": "data/raw.jsonl",
                "network": {
                    "listen_host": "127.0.0.1",
                    "tcp_port": 0,
                    "udp_port": 5000,
                    "tcp_framing": "raw_chunks",
                },
            })
            config_path = os.path.join(directory, "config.json")
            with open(config_path, "w", encoding="utf-8") as handle:
                json.dump(cfg, handle)
            report = run_preflight(config_path)
            self.assertEqual(report["overall"], "FAIL")
            network_failure = next(check for check in report["checks"] if check["name"] == "network_config")
            self.assertIn("between 1 and 65535", network_failure["detail"])
            storage = next(check for check in report["checks"] if check["name"] == "writable_storage")
            self.assertEqual(storage["path"], os.path.join(directory, "data"))


class PortableConfigTests(unittest.TestCase):
    def test_relative_outputs_follow_external_config_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = os.path.join(directory, "config.factory.json")
            with open(config_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "output_csv": "data/factory/readings.csv",
                        "output_sqlite": "data/factory/readings.sqlite",
                        "output_xlsx": "data/factory/readings.xlsx",
                        "raw_journal": "data/factory/raw_packets.jsonl",
                    },
                    handle,
                )

            loaded = load_config(config_path, validate=False)

            self.assertEqual(
                loaded["output_sqlite"],
                os.path.join(directory, "data", "factory", "readings.sqlite"),
            )
            self.assertEqual(
                loaded["output_xlsx"],
                os.path.join(directory, "data", "factory", "readings.xlsx"),
            )
            self.assertEqual(
                loaded["storage"]["backup_directory"],
                os.path.join(directory, "data", "factory", "backups"),
            )
            self.assertEqual(
                loaded["storage"]["application_log"],
                os.path.join(directory, "data", "factory", "vfreg.log"),
            )


class StartupSafetyTests(unittest.TestCase):
    def test_portable_launcher_opens_default_browser(self) -> None:
        opened_urls: list[str] = []

        def remember_url(url: str) -> bool:
            opened_urls.append(url)
            return True

        self.assertTrue(open_dashboard("http://127.0.0.1:8000", remember_url))
        self.assertEqual(opened_urls, ["http://127.0.0.1:8000"])

    def _factory_config(self) -> dict:
        with (PROJECT_ROOT / "config.example.json").open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def test_application_and_package_versions_match(self) -> None:
        self.assertEqual(__version__, package_version("vfreg-factory-collector"))

    def test_production_configuration_rejects_alternate_modbus_function(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cfg = self._factory_config()
            cfg["network"]["modbus"]["function_code"] = 3
            path = Path(directory) / "config.factory.json"
            path.write_text(json.dumps(cfg), encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "function must be 04"):
                load_config(path)

    def test_dashboard_must_remain_local_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cfg = self._factory_config()
            cfg["dashboard"]["host"] = "0.0.0.0"
            path = Path(directory) / "config.factory.json"
            path.write_text(json.dumps(cfg), encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "127.0.0.1"):
                load_config(path)

    def test_invalid_storage_value_has_specific_configuration_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cfg = self._factory_config()
            cfg["storage"]["queue_size"] = "many"
            path = Path(directory) / "config.factory.json"
            path.write_text(json.dumps(cfg), encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "storage.queue_size"):
                load_config(path)

    def test_invalid_free_space_thresholds_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cfg = self._factory_config()
            cfg["storage"]["warning_free_bytes"] = 100
            cfg["storage"]["critical_free_bytes"] = 200
            path = Path(directory) / "config.factory.json"
            path.write_text(json.dumps(cfg), encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "critical_free_bytes"):
                load_config(path)

    def test_factory_defaults_preserve_more_than_one_year_at_five_seconds(self) -> None:
        cfg = self._factory_config()
        self.assertGreaterEqual(cfg["storage"]["measurement_retention_days"], 365)
        self.assertGreaterEqual(cfg["storage"]["event_retention_days"], 365)
        self.assertEqual(cfg["storage"]["max_runtime_bytes"], 12_000_000_000)

    def test_second_instance_is_rejected_for_same_deployment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = DeploymentInstanceLock(directory)
            second = DeploymentInstanceLock(directory)
            first.acquire()
            try:
                with self.assertRaises(InstanceAlreadyRunning):
                    second.acquire()
            finally:
                first.release()

    def test_occupied_dashboard_port_has_actionable_error(self) -> None:
        occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        occupied.bind(("127.0.0.1", 0))
        occupied.listen(1)
        port = occupied.getsockname()[1]
        try:
            with self.assertRaisesRegex(StartupError, "already occupied"):
                _create_dashboard_server("127.0.0.1", port)
        finally:
            occupied.close()


if __name__ == "__main__":
    unittest.main()
