from __future__ import annotations

import csv
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
import sqlite3
import urllib.request
from dataclasses import asdict
from datetime import datetime


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, PROJECT_ROOT)

from app import (  # noqa: E402
    DashboardHandler,
    DashboardServer,
    connection_state,
    load_config,
    persist_poll_interval,
)
from modbus_client import (  # noqa: E402
    ModbusTcpCollector,
    build_modbus_request,
    parse_modbus_response,
)
from network_listener import parse_payload  # noqa: E402
from preflight import run_preflight  # noqa: E402
from simulator_sender import build_packet  # noqa: E402
from storage import (  # noqa: E402
    Measurement,
    StorageWriter,
    append_csv,
    append_sqlite,
    connect_sqlite,
    export_csv,
    fetch_recent,
    fetch_summary,
    init_sqlite,
    insert_measurements,
    iter_events,
    now_iso,
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

    def test_modbus_write_function_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_modbus_request(1, 5, 6, 0, 1)

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
            self.assertEqual(lines[0].strip(), "Time,Volts,mAmp,Frec,Status")

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
            self.assertEqual(rows[1][0], "2026-08-21T11:38:10")


class StatusTests(unittest.TestCase):
    def test_recent_measurement_is_connected(self) -> None:
        latest = {"timestamp": datetime.now().astimezone().isoformat()}
        self.assertEqual(connection_state(latest, 3), "CONNECTED")

    def test_missing_measurement_is_waiting(self) -> None:
        self.assertEqual(connection_state(None, 3), "WAITING")

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

            loaded = load_config(config_path)

            self.assertEqual(
                loaded["output_sqlite"],
                os.path.join(directory, "data", "factory", "readings.sqlite"),
            )
            self.assertEqual(
                loaded["output_xlsx"],
                os.path.join(directory, "data", "factory", "readings.xlsx"),
            )


if __name__ == "__main__":
    unittest.main()
