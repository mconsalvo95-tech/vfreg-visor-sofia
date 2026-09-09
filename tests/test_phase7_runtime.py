from __future__ import annotations

import json
import logging
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
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
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SCHEDULER_SCRIPT = PORTABLE_DIR / "Install-VFREGScheduledTask.ps1"
START_BAT = PORTABLE_DIR / "Start VFREG Visor.bat"
OPERATOR_RUNBOOK = PORTABLE_DIR / "GUIA-OPERADOR-INICIO-AUTOMATICO.txt"
WAKE_TIMER_SCRIPT = PORTABLE_DIR / "Enable-VFREGWakeTimers.ps1"
WAKE_TIMER_BAT = PORTABLE_DIR / "Configurar despertar del PC.bat"
BUILD_PORTABLE_SCRIPT = PROJECT_ROOT / "build_portable.ps1"
MOCK_BAT_POWERSHELL = FIXTURES_DIR / "Mock-BatPowerShell.cmd"
STUB_WAKE_TIMER_SCRIPT = FIXTURES_DIR / "Stub-Enable-VFREGWakeTimers.ps1"

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


def _build_wake_timer_bat_layout(root: Path) -> Path:
    bat_path = root / WAKE_TIMER_BAT.name
    shutil.copy(WAKE_TIMER_BAT, bat_path)
    shutil.copy(STUB_WAKE_TIMER_SCRIPT, root / "Enable-VFREGWakeTimers.ps1")
    shutil.copy(MOCK_BAT_POWERSHELL, root / "Mock-BatPowerShell.cmd")
    shutil.copy(
        FIXTURES_DIR / "Mock-BatPowerShell.ps1",
        root / "Mock-BatPowerShell.ps1",
    )
    return bat_path


def _patch_wake_timer_bat_exit_file(bat_path: Path, exit_file: Path) -> None:
    source = bat_path.read_text(encoding="utf-8")
    patched = source.replace(
        'set "VFREG_WAKE_EXITFILE=%TEMP%\\vfreg-wake-exit-%RANDOM%.txt"',
        f'set "VFREG_WAKE_EXITFILE={exit_file}"',
    )
    if patched == source:
        raise AssertionError("Could not patch wake timer BAT exit file path")
    bat_path.write_text(patched, encoding="utf-8")


def _run_wake_timer_bat(
    bat_path: Path,
    *,
    test_mode: str,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["VFREG_BAT_NO_PAUSE"] = "1"
    env["VFREG_BAT_TEST_MODE"] = test_mode
    env["VFREG_BAT_POWERSHELL"] = str(cwd / "Mock-BatPowerShell.cmd")
    return subprocess.run(
        ["cmd.exe", "/c", str(bat_path)],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _run_wake_timer_script(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(WAKE_TIMER_SCRIPT),
        *args,
    ]
    return subprocess.run(
        command,
        cwd=str(cwd or PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def _write_mock_powercfg(root: Path, ac: int = 2, dc: int = 2) -> Path:
    state_path = root / "mock-powercfg-state.json"
    state_path.write_text(
        json.dumps(
            {
                "scheme": "381b4222-f694-41f0-9685-ff5bb260df2e",
                "ac": ac,
                "dc": dc,
            }
        ),
        encoding="utf-8",
    )
    mock_script = root / "Mock-PowerCfg.ps1"
    mock_script.write_text(
        rf"""
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
$statePath = '{state_path.as_posix()}'
$state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
$command = $Args[0]
switch ($command) {{
    '/getactivescheme' {{
        Write-Output ("Power Scheme GUID: {{0}}  (Balanced)" -f $state.scheme)
        exit 0
    }}
    '/query' {{
        if ($Args.Count -ge 4 -and $Args[2] -match '(?i)sleep' -and $Args[3] -match '(?i)rtcwake') {{
            Write-Output "  Power Setting GUID: bd3b718a-0680-4d9d-8ab2-e1d2b4ac806d  (Allow wake timers)"
            Write-Output ("    Current AC Power Setting Index: 0x{{0:x8}}" -f [int]$state.ac)
            Write-Output ("    Current DC Power Setting Index: 0x{{0:x8}}" -f [int]$state.dc)
            exit 0
        }}
        Write-Error "unsupported mock powercfg query: $($Args -join ' ')"
        exit 9
    }}
    '/setacvalueindex' {{
        if ($Args.Count -lt 5) {{ throw "missing setac args" }}
        if ($Args[2] -notmatch '(?i)sleep' -or $Args[3] -notmatch '(?i)rtcwake') {{
            Write-Error "mock powercfg rejected non-RTCWAKE mutation"
            exit 9
        }}
        $state.ac = [int]$Args[4]
        $json = $state | ConvertTo-Json -Compress
        [System.IO.File]::WriteAllText($statePath, $json, [System.Text.UTF8Encoding]::new($false))
        exit 0
    }}
    '/setactive' {{
        exit 0
    }}
    default {{
        Write-Error "unsupported mock powercfg command: $command"
        exit 9
    }}
}}
""",
        encoding="utf-8",
    )
    return mock_script


class ScheduledTaskScriptTests(unittest.TestCase):
    def test_scheduler_script_exists_and_declares_contract(self) -> None:
        source = SCHEDULER_SCRIPT.read_text(encoding="utf-8")
        self.assertIn('[string]$DailyStartTime = "05:50"', source)
        self.assertIn("Test-VFREGDailyStartTime", source)
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

    def test_validate_only_accepts_custom_daily_start_time(self) -> None:
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
                "-DailyStartTime",
                "08:30",
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
            payload = json.loads(result.stdout.strip())
            self.assertEqual(payload["daily_start"], "08:30")

    def test_validate_only_rejects_invalid_daily_start_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe_path = root / "VFREG-VISOR-SOFIA.exe"
            config_path = root / "config.factory.json"
            exe_path.write_bytes(b"MZ")
            config_path.write_text(
                json.dumps({"dashboard": {"host": "127.0.0.1", "port": 8000}}),
                encoding="utf-8",
            )
            for invalid_time in ("25:00", "7:30", "05:60", "noon"):
                with self.subTest(invalid_time=invalid_time):
                    result = _run_powershell_script(
                        "-ValidateOnly",
                        "-DeploymentRoot",
                        str(root),
                        "-DailyStartTime",
                        invalid_time,
                    )
                    self.assertNotEqual(
                        result.returncode, 0, msg=result.stderr or result.stdout
                    )
                    combined = re.sub(
                        r"\s+", " ", f"{result.stdout} {result.stderr}"
                    )
                    self.assertIn("DailyStartTime", combined)
                    self.assertIn("HH:mm", combined)

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
        self.assertIn("Enable-VFREGWakeTimers.ps1", build_source)
        self.assertIn("Configurar despertar del PC.bat", build_source)
        self.assertIn("GUIA-OPERADOR-INICIO-AUTOMATICO.txt", build_source)


class StartBatTests(unittest.TestCase):
    def test_start_bat_registers_daily_task_before_launching_exe(self) -> None:
        source = START_BAT.read_text(encoding="utf-8")
        install_idx = source.lower().find("install-vfregscheduledtask.ps1")
        exe_idx = source.lower().find("vfreg-visor-sofia.exe")
        self.assertNotEqual(install_idx, -1)
        self.assertNotEqual(exe_idx, -1)
        self.assertLess(install_idx, exe_idx)
        self.assertIn("-DeploymentRoot", source)
        self.assertNotIn("Enable-VFREGWakeTimers", source)
        self.assertNotIn("-Verb RunAs", source)

    def test_start_bat_continues_collector_launch_when_install_fails(self) -> None:
        source = START_BAT.read_text(encoding="utf-8")
        self.assertRegex(source, r"(?i)if errorlevel 1")
        self.assertIn("ADVERTENCIA", source)
        warning_idx = source.find("ADVERTENCIA")
        exe_idx = source.lower().find("vfreg-visor-sofia.exe")
        self.assertLess(warning_idx, exe_idx)

    def test_operator_runbook_documents_start_bat_task_registration(self) -> None:
        runbook = OPERATOR_RUNBOOK.read_text(encoding="utf-8")
        self.assertIn("Start VFREG Visor.bat", runbook)
        self.assertIn("05:50", runbook)
        self.assertRegex(runbook, r"(?i)PC personal|personal o de prueba")


class WakeTimerScriptTests(unittest.TestCase):
    def test_wake_timer_script_exists_and_declares_contract(self) -> None:
        source = WAKE_TIMER_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("[switch]$ValidateOnly", source)
        self.assertIn("[switch]$Restore", source)
        self.assertIn("[string]$PowerCfgCommand = \"powercfg\"", source)
        self.assertIn("SUB_SLEEP", source)
        self.assertIn("RTCWAKE", source)
        self.assertIn("/setacvalueindex", source)
        self.assertIn("/setactive", source)
        self.assertIn("vfreg-wake-timer-backup.json", source)
        self.assertIn("vfreg-wake-timer-audit.jsonl", source)
        self.assertNotIn("setdcvalueindex", source.lower())
        self.assertNotIn("/setdcvalueindex", source.lower())

    def test_validate_only_reports_active_scheme_and_intended_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mock = _write_mock_powercfg(root, ac=2, dc=1)
            result = _run_wake_timer_script(
                "-ValidateOnly",
                "-DeploymentRoot",
                str(root),
                "-PowerCfgCommand",
                str(mock),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
            payload = json.loads(result.stdout.strip())
            self.assertEqual(payload["mode"], "validate")
            self.assertEqual(payload["rtc_wake_ac"], 2)
            self.assertEqual(payload["rtc_wake_dc"], 1)
            self.assertEqual(payload["intended_ac"], 1)
            self.assertTrue(payload["dc_unchanged"])
            self.assertFalse(payload["idempotent"])

    @unittest.skipUnless(sys.platform == "win32", "ValidateOnly uses local powercfg")
    def test_validate_only_against_real_powercfg_is_non_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = _run_wake_timer_script("-ValidateOnly", "-DeploymentRoot", str(root))
            self.assertEqual(before.returncode, 0, msg=before.stderr or before.stdout)
            before_payload = json.loads(before.stdout.strip())
            after = _run_wake_timer_script("-ValidateOnly", "-DeploymentRoot", str(root))
            self.assertEqual(after.returncode, 0, msg=after.stderr or after.stdout)
            after_payload = json.loads(after.stdout.strip())
            self.assertEqual(
                before_payload["rtc_wake_ac"],
                after_payload["rtc_wake_ac"],
            )
            self.assertEqual(
                before_payload["rtc_wake_dc"],
                after_payload["rtc_wake_dc"],
            )
            self.assertFalse((root / "data" / "vfreg-wake-timer-backup.json").exists())

    def test_validate_only_with_restore_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mock = _write_mock_powercfg(root)
            result = _run_wake_timer_script(
                "-ValidateOnly",
                "-Restore",
                "-DeploymentRoot",
                str(root),
                "-PowerCfgCommand",
                str(mock),
            )
            self.assertNotEqual(result.returncode, 0, msg=result.stderr or result.stdout)
            combined = re.sub(r"\s+", " ", f"{result.stdout} {result.stderr}")
            self.assertIn("ValidateOnly", combined)
            self.assertIn("Restore", combined)

    def test_enable_is_idempotent_and_preserves_original_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mock = _write_mock_powercfg(root, ac=2, dc=2)
            common = [
                "-DeploymentRoot",
                str(root),
                "-PowerCfgCommand",
                str(mock),
                "-SkipAdminCheck",
            ]
            first = _run_wake_timer_script(*common)
            self.assertEqual(first.returncode, 0, msg=first.stderr or first.stdout)
            backup_path = root / "data" / "vfreg-wake-timer-backup.json"
            self.assertTrue(backup_path.exists())
            original_backup = json.loads(backup_path.read_text(encoding="utf-8"))
            self.assertEqual(original_backup["previous_ac"], 2)
            self.assertEqual(original_backup["previous_dc"], 2)
            self.assertEqual(original_backup["new_ac"], 1)

            second = _run_wake_timer_script(*common)
            self.assertEqual(second.returncode, 0, msg=second.stderr or second.stdout)
            preserved = json.loads(backup_path.read_text(encoding="utf-8"))
            self.assertEqual(preserved, original_backup)

            state = json.loads((root / "mock-powercfg-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["ac"], 1)
            self.assertEqual(state["dc"], 2)

    def test_restore_uses_validated_backup_and_leaves_dc_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mock = _write_mock_powercfg(root, ac=2, dc=3)
            enable = _run_wake_timer_script(
                "-DeploymentRoot",
                str(root),
                "-PowerCfgCommand",
                str(mock),
                "-SkipAdminCheck",
            )
            self.assertEqual(enable.returncode, 0, msg=enable.stderr or enable.stdout)

            state_path = root / "mock-powercfg-state.json"
            mutated = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(mutated["ac"], 1)
            self.assertEqual(mutated["dc"], 3)

            restore = _run_wake_timer_script(
                "-Restore",
                "-DeploymentRoot",
                str(root),
                "-PowerCfgCommand",
                str(mock),
                "-SkipAdminCheck",
            )
            self.assertEqual(restore.returncode, 0, msg=restore.stderr or restore.stdout)
            restored = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(restored["ac"], 2)
            self.assertEqual(restored["dc"], 3)

    def test_restore_fails_without_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mock = _write_mock_powercfg(root)
            result = _run_wake_timer_script(
                "-Restore",
                "-DeploymentRoot",
                str(root),
                "-PowerCfgCommand",
                str(mock),
                "-SkipAdminCheck",
            )
            self.assertNotEqual(result.returncode, 0)
            combined = re.sub(r"\s+", " ", f"{result.stdout} {result.stderr}")
            self.assertIn("backup not found", combined.lower())

    def test_enable_without_admin_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mock = _write_mock_powercfg(root)
            result = _run_wake_timer_script(
                "-DeploymentRoot",
                str(root),
                "-PowerCfgCommand",
                str(mock),
            )
            if result.returncode == 0:
                self.skipTest("shell already elevated; admin rejection not observable")
            combined = re.sub(r"\s+", " ", f"{result.stdout} {result.stderr}")
            self.assertIn("Administrator rights are required", combined)


class WakeTimerBatTests(unittest.TestCase):
    def test_wake_timer_bat_quotes_paths_and_handles_uac_exit_codes(self) -> None:
        source = WAKE_TIMER_BAT.read_text(encoding="utf-8")
        self.assertIn('cd /d "%~dp0"', source)
        self.assertIn("VFREG_WAKE_SCRIPT", source)
        self.assertIn("VFREG_DEPLOY_ROOT", source)
        self.assertIn("VFREG_WAKE_EXITFILE", source)
        self.assertIn("-Verb RunAs", source)
        self.assertIn("-ArgumentList $argLine", source)
        self.assertIn("[char]34", source)
        self.assertIn("-DeploymentRoot", source)
        self.assertIn("-ExitFile", source)
        self.assertIn("1223", source)
        self.assertIn(":validate_sentinel", source)
        self.assertIn(":err_elevation", source)
        self.assertIn("No se pudo completar la elevacion de administrador", source)
        self.assertIn("UAC cancelado o acceso denegado", source)
        self.assertIn(":maybe_pause", source)
        self.assertIn("VFREG_BAT_NO_PAUSE", source)
        self.assertIn("VFREG_BAT_POWERSHELL", source)
        self.assertIn('call "%VFREG_PS%"', source)
        self.assertNotIn("ArgumentList @(", source)
        self.assertNotIn("exit $p.ExitCode", source)
        self.assertNotIn("196608", source)
        self.assertNotIn("FFFD0000", source)
        self.assertNotIn("(codigo", source.lower())
        self.assertNotIn("setx", source.lower())
        self.assertNotIn("powercfg", source.lower())

    @unittest.skipUnless(sys.platform == "win32", "Windows-only BAT wrapper")
    def test_wake_timer_bat_end_to_end_success_without_uac(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vfreg bat ok ") as directory:
            root = Path(directory)
            bat_path = _build_wake_timer_bat_layout(root)
            result = _run_wake_timer_bat(bat_path, test_mode="success", cwd=root)
            combined = f"{result.stdout}\n{result.stderr}"
            self.assertEqual(result.returncode, 0, msg=combined)
            self.assertIn("Listo: despertador RTC habilitado", combined)
            self.assertNotIn("No se esperaba", combined)

    @unittest.skipUnless(sys.platform == "win32", "Windows-only BAT wrapper")
    def test_wake_timer_bat_end_to_end_failure_without_parser_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vfreg bat fail ") as directory:
            root = Path(directory)
            bat_path = _build_wake_timer_bat_layout(root)
            result = _run_wake_timer_bat(bat_path, test_mode="fail", cwd=root)
            combined = f"{result.stdout}\n{result.stderr}"
            self.assertEqual(result.returncode, 9, msg=combined)
            self.assertIn("Codigo 9", combined)
            self.assertNotIn("No se esperaba", combined)

    @unittest.skipUnless(sys.platform == "win32", "Windows-only BAT wrapper")
    def test_wake_timer_bat_end_to_end_uac_cancel(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vfreg bat uac ") as directory:
            root = Path(directory)
            bat_path = _build_wake_timer_bat_layout(root)
            result = _run_wake_timer_bat(bat_path, test_mode="cancel", cwd=root)
            combined = f"{result.stdout}\n{result.stderr}"
            self.assertEqual(result.returncode, 1223, msg=combined)
            self.assertIn("UAC cancelado o acceso denegado", combined)
            self.assertNotIn("No se esperaba", combined)

    @unittest.skipUnless(sys.platform == "win32", "Windows-only BAT wrapper")
    def test_wake_timer_bat_elevation_argument_list_quotes_paths_with_spaces(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vfreg bat args ") as directory:
            root = Path(directory)
            bat_path = _build_wake_timer_bat_layout(root)
            result = _run_wake_timer_bat(bat_path, test_mode="inspect_args", cwd=root)
            combined = f"{result.stdout}\n{result.stderr}"
            self.assertEqual(result.returncode, 0, msg=combined)
            argline_path = root / "mock-elevated-argline.txt"
            self.assertTrue(argline_path.is_file(), msg=combined)
            argline = argline_path.read_text(encoding="utf-8")
            quoted_script = f'"{root / "Enable-VFREGWakeTimers.ps1"}"'
            quoted_root = f'"{root}"'
            self.assertIn(quoted_script, argline)
            self.assertIn(quoted_root, argline)
            self.assertIn("-ExitFile", argline)

    @unittest.skipUnless(sys.platform == "win32", "Windows-only BAT wrapper")
    def test_wake_timer_bat_bad_process_exit_with_fresh_sentinel_succeeds(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vfreg bat sentinel ok ") as directory:
            root = Path(directory)
            bat_path = _build_wake_timer_bat_layout(root)
            result = _run_wake_timer_bat(bat_path, test_mode="bad_exit_ok", cwd=root)
            combined = f"{result.stdout}\n{result.stderr}"
            self.assertEqual(result.returncode, 0, msg=combined)
            self.assertIn("Listo: despertador RTC habilitado", combined)
            self.assertNotIn("-196608", combined)
            self.assertNotIn("196608", combined)

    @unittest.skipUnless(sys.platform == "win32", "Windows-only BAT wrapper")
    def test_wake_timer_bat_missing_sentinel_reports_clear_elevation_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vfreg bat no sentinel ") as directory:
            root = Path(directory)
            bat_path = _build_wake_timer_bat_layout(root)
            result = _run_wake_timer_bat(bat_path, test_mode="missing_sentinel", cwd=root)
            combined = f"{result.stdout}\n{result.stderr}"
            self.assertEqual(result.returncode, 1259, msg=combined)
            self.assertIn("No se pudo completar la elevacion de administrador", combined)
            self.assertNotIn("-196608", combined)
            self.assertNotIn("196608", combined)
            self.assertNotIn("FFFD0000", combined)

    @unittest.skipUnless(sys.platform == "win32", "Windows-only BAT wrapper")
    def test_wake_timer_bat_removes_stale_sentinel_before_launch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vfreg bat stale ") as directory:
            root = Path(directory)
            bat_path = _build_wake_timer_bat_layout(root)
            exit_file = root / "vfreg-wake-exit-stale.txt"
            _patch_wake_timer_bat_exit_file(bat_path, exit_file)
            exit_file.write_text("0", encoding="utf-8")
            result = _run_wake_timer_bat(bat_path, test_mode="missing_sentinel", cwd=root)
            combined = f"{result.stdout}\n{result.stderr}"
            self.assertEqual(result.returncode, 1259, msg=combined)
            self.assertIn("No se pudo completar la elevacion de administrador", combined)
            self.assertNotIn("Listo: despertador RTC habilitado", combined)

    @unittest.skipUnless(sys.platform == "win32", "Windows-only BAT wrapper")
    def test_wake_timer_bat_launches_elevation_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vfreg bat once ") as directory:
            root = Path(directory)
            bat_path = _build_wake_timer_bat_layout(root)
            result = _run_wake_timer_bat(bat_path, test_mode="success", cwd=root)
            combined = f"{result.stdout}\n{result.stderr}"
            self.assertEqual(result.returncode, 0, msg=combined)
            counter_path = root / "mock-launch-count.txt"
            self.assertEqual(counter_path.read_text(encoding="utf-8").strip(), "1")

    def test_wake_timer_bat_parses_powershell_ast(self) -> None:
        ps1 = WAKE_TIMER_SCRIPT.read_text(encoding="utf-8")
        parse_cmd = (
            "$errs = $null; "
            f"$null = [System.Management.Automation.Language.Parser]::ParseFile('{WAKE_TIMER_SCRIPT}', [ref]$null, [ref]$errs); "
            "if ($errs) { $errs | ForEach-Object { $_.ToString() }; exit 1 }"
        )
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                parse_cmd,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
        self.assertIn("ValidateOnly", ps1)
        self.assertIn("Restore", ps1)


class OperatorRunbookTests(unittest.TestCase):
    def test_runbook_covers_operator_workflows_without_unsafe_steps(self) -> None:
        text = OPERATOR_RUNBOOK.read_text(encoding="utf-8").lower()
        required = (
            "05:50",
            "dailystarttime",
            "install-vfregscheduledtask.ps1",
            "enable-vfregwaketimers.ps1",
            "configurar despertar del pc.bat",
            "-validateonly",
            "-restore",
            "vfreg-wake-timer-backup.json",
            "uac",
            "solo con corriente ac",
            "-remove",
            "pruebas en casa",
            "vfreg-prueba-casa",
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
            def __init__(self) -> None:
                self._stop = threading.Event()

            def shutdown(self) -> None:
                events.append("server.shutdown")
                self._stop.set()

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

        fake_server = FakeServer()
        serve_thread = threading.Thread(
            target=lambda: fake_server._stop.wait(10),
            daemon=True,
        )
        serve_thread.start()
        try:
            _graceful_shutdown(
                collector=FakeCollector(),
                server=fake_server,  # type: ignore[arg-type]
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


class WindowsConsoleCloseShutdownTests(unittest.TestCase):
    def test_handle_console_control_event_is_noop_for_unrelated_events(self) -> None:
        from vfreg_visor.windows_console import handle_console_control_event

        shutdown_requested = threading.Event()
        cleanup_complete = threading.Event()
        self.assertFalse(
            handle_console_control_event(
                0,
                shutdown_requested=shutdown_requested,
                cleanup_complete=cleanup_complete,
                wait_timeout=0.01,
            )
        )
        self.assertFalse(shutdown_requested.is_set())

    def test_handle_console_control_event_sets_request_for_close_logoff_shutdown(
        self,
    ) -> None:
        from vfreg_visor.windows_console import (
            CTRL_CLOSE_EVENT,
            CTRL_LOGOFF_EVENT,
            CTRL_SHUTDOWN_EVENT,
            handle_console_control_event,
        )

        for ctrl_type in (CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT):
            with self.subTest(ctrl_type=ctrl_type):
                shutdown_requested = threading.Event()
                cleanup_complete = threading.Event()
                cleanup_complete.set()
                self.assertTrue(
                    handle_console_control_event(
                        ctrl_type,
                        shutdown_requested=shutdown_requested,
                        cleanup_complete=cleanup_complete,
                        wait_timeout=0.05,
                    )
                )
                self.assertTrue(shutdown_requested.is_set())

    def test_handle_console_control_event_waits_for_cleanup_completion(self) -> None:
        from vfreg_visor.windows_console import CTRL_CLOSE_EVENT, handle_console_control_event

        shutdown_requested = threading.Event()
        cleanup_complete = threading.Event()
        started = time.monotonic()

        def _complete_later() -> None:
            time.sleep(0.05)
            cleanup_complete.set()

        threading.Thread(target=_complete_later, daemon=True).start()
        self.assertTrue(
            handle_console_control_event(
                CTRL_CLOSE_EVENT,
                shutdown_requested=shutdown_requested,
                cleanup_complete=cleanup_complete,
                wait_timeout=1.0,
            )
        )
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, 0.04)
        self.assertLess(elapsed, 0.5)

    def test_install_windows_console_shutdown_handler_is_noop_off_windows(
        self,
    ) -> None:
        from vfreg_visor.windows_console import (
            install_windows_console_shutdown_handler,
            uninstall_windows_console_shutdown_handler,
        )

        with patch("vfreg_visor.windows_console.sys.platform", "linux"):
            install_windows_console_shutdown_handler(
                threading.Event(),
                threading.Event(),
            )
            uninstall_windows_console_shutdown_handler()

    @unittest.skipUnless(sys.platform == "win32", "Windows-only console handler")
    def test_install_and_uninstall_console_shutdown_handler(self) -> None:
        from vfreg_visor.windows_console import (
            install_windows_console_shutdown_handler,
            uninstall_windows_console_shutdown_handler,
        )

        shutdown_requested = threading.Event()
        cleanup_complete = threading.Event()
        install_windows_console_shutdown_handler(shutdown_requested, cleanup_complete)
        uninstall_windows_console_shutdown_handler()

    def test_run_observes_console_shutdown_request_during_dashboard_join(
        self,
    ) -> None:
        from vfreg_visor.cli import run

        events: list[str] = []
        shutdown_requested = threading.Event()
        cleanup_complete = threading.Event()
        real_join = threading.Thread.join

        class FakeCollector:
            def stop(self) -> None:
                events.append("collector.stop")

        class FakeWriter:
            def close(self, timeout: float = 5) -> None:
                events.append("writer.close")

        class FakeServer:
            def __init__(self) -> None:
                self._stop = threading.Event()
                self.cfg = {}
                self.config_path = "config.json"
                self.collector = None
                self.writer = None

            def serve_forever(self) -> None:
                self._stop.wait(30)

            def shutdown(self) -> None:
                events.append("server.shutdown")
                self._stop.set()

            def server_close(self) -> None:
                events.append("server.server_close")

        class FakeLogger:
            def info(self, *args: object, **kwargs: object) -> None:
                events.append("logger.info")

            def error(self, *args: object, **kwargs: object) -> None:
                events.append("logger.error")

        fake_server = FakeServer()

        def tracking_join(self, timeout: float | None = None) -> None:
            if timeout == 0.5 and not shutdown_requested.is_set():
                shutdown_requested.set()
            return real_join(self, timeout)

        cfg = {
            "dashboard": {"host": "127.0.0.1", "port": 8000},
            "output_sqlite": "data/readings.sqlite",
            "raw_journal": "data/raw.jsonl",
            "storage": {"backup_directory": "data/backups"},
            "network": {"mode": "udp_tcp", "udp_port": 5000, "tcp_port": 5000},
        }

        with (
            patch("vfreg_visor.cli.load_config", return_value=cfg),
            patch("vfreg_visor.cli.ensure_runtime_paths_writable"),
            patch("vfreg_visor.cli.configure_operational_logging", return_value=FakeLogger()),
            patch("vfreg_visor.cli.DeploymentInstanceLock"),
            patch("vfreg_visor.cli._create_dashboard_server", return_value=fake_server),
            patch("vfreg_visor.cli.StorageWriter", return_value=FakeWriter()),
            patch("vfreg_visor.cli.start_network_servers", return_value=FakeCollector()),
            patch.object(threading.Thread, "join", tracking_join),
        ):
            run(
                "config.factory.json",
                open_browser=False,
                shutdown_requested=shutdown_requested,
                cleanup_complete=cleanup_complete,
            )

        self.assertTrue(cleanup_complete.is_set())
        self.assertLess(events.index("server.shutdown"), events.index("writer.close"))
        self.assertEqual(events[-1], "logger.info")

    def test_graceful_shutdown_records_dashboard_timeout_and_still_closes_storage(
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

        class FakeLogger:
            def info(self, *args: object, **kwargs: object) -> None:
                events.append("logger.info")

            def error(self, *args: object, **kwargs: object) -> None:
                events.append("logger.error")

        serve_thread = threading.Thread(target=lambda: time.sleep(10), daemon=True)
        serve_thread.start()
        cleanup_complete = threading.Event()
        with self.assertRaises(TimeoutError):
            _graceful_shutdown(
                collector=None,
                server=FakeServer(),  # type: ignore[arg-type]
                writer=FakeWriter(),  # type: ignore[arg-type]
                logger=FakeLogger(),  # type: ignore[arg-type]
                serve_thread=serve_thread,
                cleanup_budget_seconds=0.05,
                cleanup_complete=cleanup_complete,
            )
        self.assertTrue(cleanup_complete.is_set())
        self.assertIn("server.server_close", events)
        self.assertIn("writer.close", events)
        self.assertIn("logger.info", events)
        self.assertLess(events.index("server.server_close"), events.index("writer.close"))

    def test_main_returns_nonzero_on_shutdown_timeout(self) -> None:
        from vfreg_visor.cli import main

        with (
            patch("vfreg_visor.cli._install_windows_shutdown_handlers"),
            patch("vfreg_visor.cli.uninstall_windows_console_shutdown_handler"),
            patch(
                "vfreg_visor.cli.run",
                side_effect=TimeoutError(
                    "Dashboard thread did not stop within 5.0s cleanup budget during shutdown"
                ),
            ),
        ):
            exit_code = main(["--config", "config.factory.json", "--no-browser"])
        self.assertEqual(exit_code, 1)

    def test_graceful_shutdown_passes_remaining_time_to_later_stages(self) -> None:
        from vfreg_visor.cli import _graceful_shutdown

        join_timeouts: list[float] = []
        writer_timeouts: list[float] = []
        real_join = threading.Thread.join

        class FakeServer:
            def shutdown(self) -> None:
                pass

            def server_close(self) -> None:
                pass

        class FakeWriter:
            def close(self, timeout: float = 5) -> None:
                writer_timeouts.append(timeout)

        class FakeLogger:
            def info(self, *args: object, **kwargs: object) -> None:
                pass

            def error(self, *args: object, **kwargs: object) -> None:
                pass

        serve_thread = threading.Thread(target=lambda: time.sleep(0.12), daemon=True)
        serve_thread.start()

        def tracking_join(self, timeout: float | None = None) -> None:
            if timeout is not None and timeout <= 0.25:
                join_timeouts.append(timeout)
            return real_join(self, timeout)

        with patch.object(threading.Thread, "join", tracking_join):
            _graceful_shutdown(
                collector=None,
                server=FakeServer(),  # type: ignore[arg-type]
                writer=FakeWriter(),  # type: ignore[arg-type]
                logger=FakeLogger(),  # type: ignore[arg-type]
                serve_thread=serve_thread,
                cleanup_budget_seconds=0.2,
            )

        self.assertEqual(len(join_timeouts), 1)
        self.assertEqual(len(writer_timeouts), 1)
        self.assertLess(writer_timeouts[0], join_timeouts[0])
        self.assertGreaterEqual(writer_timeouts[0], 0.0)

    def test_run_uses_native_console_cleanup_budget_when_shutdown_requested(
        self,
    ) -> None:
        from vfreg_visor.cli import (
            _NATIVE_CONSOLE_CLEANUP_BUDGET_SECONDS,
            _SHUTDOWN_CLEANUP_TIMEOUT_SECONDS,
            run,
        )

        cleanup_budgets: list[float] = []
        shutdown_requested = threading.Event()
        cleanup_complete = threading.Event()
        real_join = threading.Thread.join

        class FakeCollector:
            def stop(self) -> None:
                pass

        class FakeWriter:
            def close(self, timeout: float = 5) -> None:
                pass

        class FakeServer:
            def __init__(self) -> None:
                self._stop = threading.Event()
                self.cfg = {}
                self.config_path = "config.json"
                self.collector = None
                self.writer = None

            def serve_forever(self) -> None:
                self._stop.wait(30)

            def shutdown(self) -> None:
                self._stop.set()

            def server_close(self) -> None:
                pass

        class FakeLogger:
            def info(self, *args: object, **kwargs: object) -> None:
                pass

            def error(self, *args: object, **kwargs: object) -> None:
                pass

        fake_server = FakeServer()

        def tracking_join(self, timeout: float | None = None) -> None:
            if timeout == 0.5 and not shutdown_requested.is_set():
                shutdown_requested.set()
            return real_join(self, timeout)

        def capture_shutdown(**kwargs: object) -> None:
            cleanup_budgets.append(float(kwargs["cleanup_budget_seconds"]))

        cfg = {
            "dashboard": {"host": "127.0.0.1", "port": 8000},
            "output_sqlite": "data/readings.sqlite",
            "raw_journal": "data/raw.jsonl",
            "storage": {"backup_directory": "data/backups"},
            "network": {"mode": "udp_tcp", "udp_port": 5000, "tcp_port": 5000},
        }

        with (
            patch("vfreg_visor.cli.load_config", return_value=cfg),
            patch("vfreg_visor.cli.ensure_runtime_paths_writable"),
            patch("vfreg_visor.cli.configure_operational_logging", return_value=FakeLogger()),
            patch("vfreg_visor.cli.DeploymentInstanceLock"),
            patch("vfreg_visor.cli._create_dashboard_server", return_value=fake_server),
            patch("vfreg_visor.cli.StorageWriter", return_value=FakeWriter()),
            patch("vfreg_visor.cli.start_network_servers", return_value=FakeCollector()),
            patch.object(threading.Thread, "join", tracking_join),
            patch("vfreg_visor.cli._graceful_shutdown", side_effect=capture_shutdown),
        ):
            run(
                "config.factory.json",
                open_browser=False,
                shutdown_requested=shutdown_requested,
                cleanup_complete=cleanup_complete,
            )

        self.assertEqual(cleanup_budgets, [_NATIVE_CONSOLE_CLEANUP_BUDGET_SECONDS])
        self.assertLess(
            _NATIVE_CONSOLE_CLEANUP_BUDGET_SECONDS,
            _SHUTDOWN_CLEANUP_TIMEOUT_SECONDS,
        )

    def test_handle_console_control_event_returns_before_slow_cleanup_finishes(
        self,
    ) -> None:
        from vfreg_visor.windows_console import CTRL_CLOSE_EVENT, handle_console_control_event

        shutdown_requested = threading.Event()
        cleanup_complete = threading.Event()
        handler_wait = 0.12

        def _complete_later() -> None:
            time.sleep(handler_wait + 0.5)
            cleanup_complete.set()

        threading.Thread(target=_complete_later, daemon=True).start()
        started = time.monotonic()
        self.assertTrue(
            handle_console_control_event(
                CTRL_CLOSE_EVENT,
                shutdown_requested=shutdown_requested,
                cleanup_complete=cleanup_complete,
                wait_timeout=handler_wait,
            )
        )
        elapsed = time.monotonic() - started
        self.assertTrue(shutdown_requested.is_set())
        self.assertGreaterEqual(elapsed, handler_wait * 0.8)
        self.assertLess(elapsed, handler_wait + 0.15)
        cleanup_complete.wait(timeout=1.0)
        self.assertTrue(cleanup_complete.is_set())

    def test_graceful_shutdown_runs_every_stage_and_sets_cleanup_complete(self) -> None:
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
        cleanup_complete = threading.Event()
        with self.assertRaises(TimeoutError):
            _graceful_shutdown(
                collector=FakeCollector(),
                server=FakeServer(),  # type: ignore[arg-type]
                writer=FakeWriter(),  # type: ignore[arg-type]
                logger=FakeLogger(),  # type: ignore[arg-type]
                serve_thread=serve_thread,
                cleanup_budget_seconds=0.05,
                cleanup_complete=cleanup_complete,
            )
        self.assertTrue(cleanup_complete.is_set())
        self.assertEqual(events[0], "collector.stop")
        self.assertIn("server.shutdown", events)
        self.assertIn("server.server_close", events)
        self.assertIn("writer.close", events)
        self.assertEqual(events[-1], "logger.info")
        self.assertLess(events.index("server.server_close"), events.index("writer.close"))


class WindowsConsoleInterruptTests(unittest.TestCase):
    def test_install_windows_console_interrupt_handlers_is_noop_off_windows(
        self,
    ) -> None:
        from vfreg_visor.cli import _install_windows_console_interrupt_handlers

        with patch("vfreg_visor.cli.sys.platform", "linux"):
            _install_windows_console_interrupt_handlers()

    @unittest.skipUnless(sys.platform == "win32", "Windows-only signal semantics")
    def test_install_windows_console_interrupt_handlers_sets_sigbreak(self) -> None:
        from vfreg_visor.cli import _install_windows_console_interrupt_handlers

        previous = signal.getsignal(signal.SIGBREAK)
        try:
            _install_windows_console_interrupt_handlers()
            self.assertIs(
                signal.getsignal(signal.SIGBREAK),
                signal.default_int_handler,
            )
            self.assertIs(
                signal.getsignal(signal.SIGINT),
                signal.default_int_handler,
            )
        finally:
            signal.signal(signal.SIGBREAK, previous)

    def test_main_installs_windows_handlers_before_run(self) -> None:
        from vfreg_visor.cli import main

        call_order: list[str] = []

        def _install(*args: object, **kwargs: object) -> None:
            call_order.append("install")

        def _run(*args: object, **kwargs: object) -> None:
            call_order.append("run")

        def _uninstall() -> None:
            call_order.append("uninstall")

        with (
            patch(
                "vfreg_visor.cli._install_windows_shutdown_handlers",
                side_effect=_install,
            ),
            patch("vfreg_visor.cli.uninstall_windows_console_shutdown_handler", side_effect=_uninstall),
            patch("vfreg_visor.cli.run", side_effect=_run),
        ):
            main(["--config", "config.factory.json", "--no-browser"])
        self.assertEqual(call_order, ["install", "run", "uninstall"])

    def test_run_keyboard_interrupt_uses_interruptible_join_and_graceful_shutdown(
        self,
    ) -> None:
        from vfreg_visor.cli import run

        events: list[str] = []
        join_timeouts: list[float | None] = []

        class FakeCollector:
            def stop(self) -> None:
                events.append("collector.stop")

        class FakeWriter:
            def close(self, timeout: float = 5) -> None:
                events.append("writer.close")

        class FakeServer:
            def __init__(self) -> None:
                self._stop = threading.Event()
                self.cfg = {}
                self.config_path = "config.json"
                self.collector = None
                self.writer = None

            def serve_forever(self) -> None:
                self._stop.wait(30)

            def shutdown(self) -> None:
                events.append("server.shutdown")
                self._stop.set()

            def server_close(self) -> None:
                events.append("server.server_close")

        class FakeLogger:
            def info(self, *args: object, **kwargs: object) -> None:
                events.append("logger.info")

            def error(self, *args: object, **kwargs: object) -> None:
                events.append("logger.error")

        fake_server = FakeServer()
        real_join = threading.Thread.join

        def tracking_join(self, timeout: float | None = None) -> None:
            join_timeouts.append(timeout)
            if timeout == 0.5:
                raise KeyboardInterrupt
            return real_join(self, timeout)

        cfg = {
            "dashboard": {"host": "127.0.0.1", "port": 8000},
            "output_sqlite": "data/readings.sqlite",
            "raw_journal": "data/raw.jsonl",
            "storage": {"backup_directory": "data/backups"},
            "network": {"mode": "udp_tcp", "udp_port": 5000, "tcp_port": 5000},
        }

        with (
            patch("vfreg_visor.cli.load_config", return_value=cfg),
            patch("vfreg_visor.cli.ensure_runtime_paths_writable"),
            patch("vfreg_visor.cli.configure_operational_logging", return_value=FakeLogger()),
            patch("vfreg_visor.cli.DeploymentInstanceLock"),
            patch("vfreg_visor.cli._create_dashboard_server", return_value=fake_server),
            patch("vfreg_visor.cli.StorageWriter", return_value=FakeWriter()),
            patch("vfreg_visor.cli.start_network_servers", return_value=FakeCollector()),
            patch.object(threading.Thread, "join", tracking_join),
        ):
            run("config.factory.json", open_browser=False)

        self.assertEqual(join_timeouts[0], 0.5)
        shutdown_join_timeouts = [t for t in join_timeouts if t not in (None, 0.5)]
        self.assertEqual(len(shutdown_join_timeouts), 1)
        self.assertGreater(shutdown_join_timeouts[0], 4.9)
        self.assertLessEqual(shutdown_join_timeouts[0], 5.0)
        self.assertLess(events.index("server.shutdown"), events.index("writer.close"))
        self.assertEqual(events[-1], "logger.info")


if __name__ == "__main__":
    unittest.main()
