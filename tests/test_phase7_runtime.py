from __future__ import annotations

import json
import logging
import os
import re
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PORTABLE_DIR = PROJECT_ROOT / "portable"
SCHEDULER_SCRIPT = PORTABLE_DIR / "Install-VFREGScheduledTask.ps1"
OPERATOR_RUNBOOK = PORTABLE_DIR / "GUIA-OPERADOR-INICIO-AUTOMATICO.txt"
BUILD_PORTABLE_SCRIPT = PROJECT_ROOT / "build_portable.ps1"

from vfreg_visor.dashboard import (
    DashboardHandler,
    DashboardServer,
    build_health_payload,
)
from vfreg_visor.modbus import ModbusTcpCollector
from vfreg_visor.operational_log import (
    StructuredLogFormatter,
    configure_operational_logging,
)
from vfreg_visor.storage import (
    Measurement,
    StorageError,
    StorageWriter,
    connect_sqlite,
    fetch_recent,
    fetch_summary,
    now_iso,
)


def _recv_exact(connection: socket.socket, size: int) -> bytes | None:
    chunks = bytearray()
    while len(chunks) < size:
        try:
            chunk = connection.recv(size - len(chunks))
        except (ConnectionResetError, ConnectionAbortedError, OSError):
            return None
        if not chunk:
            return None
        chunks.extend(chunk)
    return bytes(chunks)


def _modbus_read_response(request: bytes) -> bytes:
    if len(request) < 8:
        raise ValueError("Modbus request is too short")
    if request[7] != 4:
        raise ValueError(f"unexpected Modbus function {request[7]}")
    return request[:2] + bytes.fromhex("00000009050406002501a900cb")


class ModbusDropServer:
    """Mock NT1-B server that drops the TCP session after N function-04 reads."""

    def __init__(self, responses_before_drop: int = 2) -> None:
        self.responses_before_drop = responses_before_drop
        self._stop = threading.Event()
        self._ready = threading.Event()
        self.port = 0
        self.requests: list[bytes] = []
        self.connections = 0
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()
        if not self._ready.wait(timeout=5):
            raise RuntimeError("mock Modbus server did not start")

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=3)

    def _run(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(5)
        self.port = server.getsockname()[1]
        self._ready.set()
        server.settimeout(0.5)
        try:
            while not self._stop.is_set():
                try:
                    connection, _address = server.accept()
                except socket.timeout:
                    continue
                self.connections += 1
                with connection:
                    served = 0
                    while not self._stop.is_set():
                        request = _recv_exact(connection, 12)
                        if request is None:
                            break
                        self.requests.append(request)
                        connection.sendall(_modbus_read_response(request))
                        served += 1
                        if served >= self.responses_before_drop:
                            break
        finally:
            server.close()


def _factory_config(host: str, port: int) -> dict:
    return {
        "network": {
            "mode": "modbus_tcp_client",
            "tcp_host": host,
            "tcp_port": port,
            "connection_timeout_seconds": 3,
            "reconnect_delay_seconds": 0.1,
            "modbus": {
                "unit_id": 5,
                "function_code": 4,
                "start_register": 0,
                "quantity": 3,
                "poll_interval_seconds": 0.5,
                "request_timeout_seconds": 1,
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


class ModbusReconnectTests(unittest.TestCase):
    def test_collector_reconnects_after_mock_server_drops_connection(self) -> None:
        server = ModbusDropServer(responses_before_drop=2)
        server.start()
        with tempfile.TemporaryDirectory() as directory:
            sqlite_path = os.path.join(directory, "readings.sqlite")
            journal_path = os.path.join(directory, "raw.jsonl")
            writer = StorageWriter(sqlite_path, journal_path)
            collector = ModbusTcpCollector(
                _factory_config("127.0.0.1", server.port), writer
            ).start()
            deadline = time.monotonic() + 8
            try:
                while time.monotonic() < deadline:
                    snapshot = collector.snapshot()
                    if snapshot["parsed_packets"] >= 3 and snapshot["disconnects"] >= 1:
                        break
                    time.sleep(0.05)
                snapshot = collector.snapshot()
                self.assertGreaterEqual(snapshot["parsed_packets"], 3)
                self.assertGreaterEqual(snapshot["disconnects"], 1)
                self.assertGreaterEqual(server.connections, 2)
                self.assertTrue(server.requests)
                self.assertTrue(all(request[7] == 4 for request in server.requests))
                self.assertFalse(any(request[7] in {5, 6, 15, 16} for request in server.requests))
            finally:
                collector.stop()
                writer.close()
            rows = fetch_recent(sqlite_path, 10)
            self.assertGreaterEqual(len(rows), 3)
            self.assertEqual(rows[-1]["voltage_v"], 37)
            self.assertEqual(rows[-1]["current_ma"], 425)
            self.assertEqual(rows[-1]["frequency_hz"], 203)
        server.stop()


class StorageShutdownTests(unittest.TestCase):
    def test_close_drains_queued_records_before_returning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sqlite_path = os.path.join(directory, "readings.sqlite")
            journal_path = os.path.join(directory, "raw.jsonl")
            writer = StorageWriter(sqlite_path, journal_path, batch_size=1)
            for index in range(25):
                writer.submit_measurement(
                    Measurement(now_iso(), "test", index, 35, 340, 202)
                )
            writer.close()
            self.assertEqual(fetch_summary(sqlite_path)["count"], 25)
            self.assertFalse(writer.snapshot()["writer_alive"])

    def test_close_performs_wal_checkpoint_on_clean_shutdown(self) -> None:
        from contextlib import closing

        with tempfile.TemporaryDirectory() as directory:
            sqlite_path = os.path.join(directory, "readings.sqlite")
            journal_path = os.path.join(directory, "raw.jsonl")
            writer = StorageWriter(sqlite_path, journal_path)
            writer.submit_measurement(
                Measurement(now_iso(), "test", 1, 35, 340, 202)
            )
            writer.close()
            wal_path = Path(str(sqlite_path) + "-wal")
            with closing(connect_sqlite(sqlite_path)) as con:
                busy, log_frames, checkpointed = con.execute(
                    "PRAGMA wal_checkpoint"
                ).fetchone()
            self.assertEqual(log_frames, 0)
            if wal_path.exists():
                self.assertEqual(wal_path.stat().st_size, 0)
            self.assertIn(busy, (0, 1))

    def test_close_raises_when_writer_thread_does_not_stop(self) -> None:
        from contextlib import closing

        with tempfile.TemporaryDirectory() as directory:
            sqlite_path = os.path.join(directory, "readings.sqlite")
            journal_path = os.path.join(directory, "raw.jsonl")
            writer = StorageWriter(sqlite_path, journal_path)
            with (
                patch.object(writer._thread, "join"),
                patch.object(writer._thread, "is_alive", return_value=True),
            ):
                with self.assertRaisesRegex(StorageError, "did not stop"):
                    writer.close(timeout=0.2)
            writer._stop.set()
            writer._thread.join(timeout=2)
            with closing(connect_sqlite(sqlite_path)) as con:
                con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            writer._closed = True


class HealthStatusTests(unittest.TestCase):
    def test_build_health_payload_reports_collector_storage_and_readings(self) -> None:
        latest = {
            "timestamp": datetime.now(timezone.utc).astimezone().isoformat(
                timespec="milliseconds"
            ),
            "status": "OK",
            "quality_flag": "GOOD",
        }
        health = build_health_payload(
            {
                "network": {
                    "mode": "modbus_tcp_client",
                    "connection_timeout_seconds": 3,
                }
            },
            latest,
            {
                "tcp_listener": "CLIENT_CONNECTED",
                "threads_alive": 1,
                "last_error": "",
            },
            {
                "writer_alive": True,
                "storage_health": "HEALTHY",
                "queue_depth": 0,
                "last_error": "",
            },
            "CONNECTED",
        )
        self.assertEqual(health["collector"]["state"], "CONNECTED")
        self.assertEqual(health["storage"]["health"], "HEALTHY")
        self.assertTrue(health["readings"]["valid_reading"])
        self.assertIsNotNone(health["readings"]["age_seconds"])

    def test_status_api_includes_stable_health_object(self) -> None:
        class FakeCollector:
            def snapshot(self) -> dict:
                return {
                    "tcp_listener": "CLIENT_CONNECTED",
                    "threads_alive": 1,
                    "poll_interval_seconds": 0.5,
                    "last_error": "",
                }

        with tempfile.TemporaryDirectory() as directory:
            sqlite_path = os.path.join(directory, "readings.sqlite")
            journal_path = os.path.join(directory, "raw.jsonl")
            writer = StorageWriter(sqlite_path, journal_path)
            writer.submit_measurement(
                Measurement(now_iso(), "test", 1, 35, 340, 202)
            )
            writer.close()
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
            server = DashboardServer(("127.0.0.1", 0), DashboardHandler)
            server.cfg = cfg
            server.config_path = os.path.join(directory, "config.factory.json")
            server.collector = FakeCollector()
            server.writer = StorageWriter(
                sqlite_path, os.path.join(directory, "raw-live.jsonl")
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{server.server_port}/api/status", timeout=3
                ) as response:
                    status = json.load(response)
                self.assertIn("connection_state", status)
                self.assertIn("diagnostics", status)
                health = status["health"]
                self.assertEqual(
                    set(health),
                    {"collector", "storage", "readings"},
                )
                self.assertEqual(health["collector"]["mode"], "modbus_tcp_client")
                self.assertIn("writer_alive", health["storage"])
                self.assertIn("valid_reading", health["readings"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
                server.writer.close()


class StructuredLogTests(unittest.TestCase):
    def test_structured_formatter_emits_one_json_object_per_line(self) -> None:
        formatter = StructuredLogFormatter()
        record = logging.LogRecord(
            name="vfreg.storage",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="Storage writes recovered",
            args=(),
            exc_info=None,
        )
        payload = json.loads(formatter.format(record))
        self.assertEqual(payload["format_version"], 1)
        self.assertIn("timestamp", payload)
        self.assertEqual(payload["severity"], "INFO")
        self.assertEqual(payload["logger"], "vfreg.storage")
        self.assertEqual(payload["component"], "storage")
        self.assertEqual(payload["message"], "Storage writes recovered")

    def test_operational_log_file_lines_are_json_objects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = os.path.join(directory, "vfreg.log")
            logger = configure_operational_logging(
                {
                    "storage": {
                        "application_log": log_path,
                        "application_log_max_bytes": 4096,
                        "application_log_backups": 1,
                    }
                }
            )
            logger.info("phase7 structured log smoke test")
            for handler in list(logger.handlers):
                handler.flush()
                handler.close()
                logger.removeHandler(handler)
            line = Path(log_path).read_text(encoding="utf-8").strip()
            payload = json.loads(line)
            self.assertEqual(payload["format_version"], 1)
            self.assertEqual(payload["severity"], "INFO")
            self.assertEqual(payload["component"], "vfreg")
            self.assertIn("structured log smoke test", payload["message"])


def _run_powershell_script(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCHEDULER_SCRIPT),
        *args,
    ]
    return subprocess.run(
        command,
        cwd=str(cwd or PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


class ScheduledTaskScriptTests(unittest.TestCase):
    def test_scheduler_script_exists_and_declares_contract(self) -> None:
        source = SCHEDULER_SCRIPT.read_text(encoding="utf-8")
        self.assertIn('DailyStartTime = "05:50"', source)
        self.assertIn('MultipleInstancesPolicy = "IgnoreNew"', source)
        self.assertIn("-LogonType Interactive", source)
        self.assertIn("-RunLevel Limited", source)
        self.assertIn("New-ScheduledTaskTrigger -AtLogOn", source)
        self.assertIn("StartWhenAvailable = $true", source)
        self.assertIn("WakeToRun = $true", source)
        self.assertIn("--no-browser", source)
        self.assertIn("[switch]$Remove", source)
        self.assertIn("[switch]$ValidateOnly", source)
        self.assertIn("VFREG-VISOR-SOFIA.exe", source)
        self.assertIn("config.factory.json", source)

    def test_validate_only_reports_portable_paths_and_quoting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe_path = root / "VFREG-VISOR-SOFIA.exe"
            config_path = root / "config.factory.json"
            exe_path.write_bytes(b"MZ")
            config_path.write_text(
                json.dumps({"dashboard": {"host": "127.0.0.1", "port": 8000}}),
                encoding="utf-8",
            )
            result = _run_powershell_script(
                "-ValidateOnly",
                "-DeploymentRoot",
                str(root),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
            payload = json.loads(result.stdout.strip())
            self.assertEqual(payload["mode"], "validate")
            self.assertEqual(payload["daily_start"], "05:50")
            self.assertEqual(payload["multiple_instances"], "IgnoreNew")
            self.assertEqual(payload["executable"], str(exe_path.resolve()))
            self.assertEqual(payload["config"], str(config_path.resolve()))
            self.assertIn("--no-browser", payload["arguments"])
            self.assertIn(f'--config "{config_path.resolve()}"', payload["arguments"])

    def test_validate_only_with_remove_is_non_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe_path = root / "VFREG-VISOR-SOFIA.exe"
            config_path = root / "config.factory.json"
            exe_path.write_bytes(b"MZ")
            config_path.write_text(
                json.dumps({"dashboard": {"host": "127.0.0.1", "port": 8000}}),
                encoding="utf-8",
            )
            result = _run_powershell_script(
                "-ValidateOnly",
                "-Remove",
                "-DeploymentRoot",
                str(root),
            )
            self.assertNotEqual(result.returncode, 0, msg=result.stderr or result.stdout)
            combined = re.sub(r"\s+", " ", f"{result.stdout} {result.stderr}")
            self.assertIn("ValidateOnly", combined)
            self.assertIn("Remove", combined)

    def test_validate_only_fails_for_missing_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.factory.json").write_text("{}", encoding="utf-8")
            result = _run_powershell_script(
                "-ValidateOnly",
                "-DeploymentRoot",
                str(root),
            )
            self.assertNotEqual(result.returncode, 0)
            combined = re.sub(r"\s+", " ", f"{result.stdout} {result.stderr}")
            self.assertIn("Collector executable not found", combined)

    def test_build_portable_includes_scheduler_assets(self) -> None:
        build_source = BUILD_PORTABLE_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("Install-VFREGScheduledTask.ps1", build_source)
        self.assertIn("GUIA-OPERADOR-INICIO-AUTOMATICO.txt", build_source)


class OperatorRunbookTests(unittest.TestCase):
    def test_runbook_covers_operator_workflows_without_unsafe_steps(self) -> None:
        text = OPERATOR_RUNBOOK.read_text(encoding="utf-8").lower()
        required = (
            "05:50",
            "install-vfregscheduledtask.ps1",
            "-validateonly",
            "-remove",
            "win+l",
            "ctrl+c",
            "/api/status",
            "http://127.0.0.1:8000",
            "vfreg.log",
            "another vfreg collector is already using",
            "escalamiento",
        )
        for phrase in required:
            self.assertIn(phrase, text)
        forbidden = (
            "eliminar el archivo de bloqueo",
            "borrar el archivo de bloqueo",
            ".vfreg-collector.lock",
            "taskkill",
            "matar sqlite",
            "eliminar sqlite",
            "wal",
        )
        for phrase in forbidden:
            self.assertNotIn(phrase, text)


class CliShutdownOrderingTests(unittest.TestCase):
    def test_graceful_shutdown_stops_server_before_storage_close(self) -> None:
        from vfreg_visor.cli import _graceful_shutdown

        events: list[str] = []

        class FakeCollector:
            def stop(self) -> None:
                events.append("collector.stop")

        class FakeServer:
            def shutdown(self) -> None:
                events.append("server.shutdown")

            def server_close(self) -> None:
                events.append("server.server_close")

        class FakeWriter:
            def close(self, timeout: float = 5) -> None:
                events.append("writer.close")

        class FakeLogger:
            def info(self, *args: object, **kwargs: object) -> None:
                events.append("logger.info")

            def error(self, *args: object, **kwargs: object) -> None:
                events.append("logger.error")

        serve_thread = threading.Thread(target=lambda: time.sleep(10), daemon=True)
        serve_thread.start()
        try:
            _graceful_shutdown(
                collector=FakeCollector(),
                server=FakeServer(),  # type: ignore[arg-type]
                writer=FakeWriter(),  # type: ignore[arg-type]
                logger=FakeLogger(),  # type: ignore[arg-type]
                serve_thread=serve_thread,
            )
        finally:
            serve_thread.join(timeout=0.1)

        self.assertLess(events.index("server.shutdown"), events.index("writer.close"))
        self.assertLess(events.index("server.server_close"), events.index("writer.close"))
        self.assertEqual(events[-1], "logger.info")

    def test_graceful_shutdown_still_closes_server_and_logs_when_storage_fails(
        self,
    ) -> None:
        from vfreg_visor.cli import _graceful_shutdown

        events: list[str] = []

        class FakeServer:
            def shutdown(self) -> None:
                events.append("server.shutdown")

            def server_close(self) -> None:
                events.append("server.server_close")

        class FakeWriter:
            def close(self, timeout: float = 5) -> None:
                events.append("writer.close")
                raise StorageError("WAL checkpoint failed during shutdown")

        class FakeLogger:
            def info(self, *args: object, **kwargs: object) -> None:
                events.append("logger.info")

            def error(self, *args: object, **kwargs: object) -> None:
                events.append("logger.error")

        serve_thread = threading.Thread(target=lambda: None, daemon=True)
        with self.assertRaises(StorageError):
            _graceful_shutdown(
                collector=None,
                server=FakeServer(),  # type: ignore[arg-type]
                writer=FakeWriter(),  # type: ignore[arg-type]
                logger=FakeLogger(),  # type: ignore[arg-type]
                serve_thread=serve_thread,
            )
        self.assertIn("server.server_close", events)
        self.assertIn("logger.info", events)
        self.assertLess(events.index("server.server_close"), events.index("writer.close"))


class NoBrowserStartupTests(unittest.TestCase):
    def test_no_browser_flag_is_available_on_cli(self) -> None:
        from vfreg_visor.cli import parse_args

        args = parse_args(["--config", "config.factory.json", "--no-browser"])
        self.assertTrue(args.no_browser)

    def test_main_honors_no_browser_when_launcher_requests_browser(self) -> None:
        from vfreg_visor.cli import main

        with patch("vfreg_visor.cli.run") as run_mock:
            main(["--config", "config.factory.json", "--no-browser"], open_browser=True)
        run_mock.assert_called_once()
        self.assertFalse(run_mock.call_args.kwargs["open_browser"])


if __name__ == "__main__":
    unittest.main()
