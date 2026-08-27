from __future__ import annotations

import json
import mimetypes
import sys
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__
from .config import (
    ALLOWED_POLL_INTERVALS,
    persist_factory_session,
    persist_poll_interval,
)
from .network import NetworkCollector
from .storage import (
    StorageWriter,
    export_csv,
    fetch_events,
    fetch_recent,
    fetch_recent_with_count,
    fetch_sampled_interval,
    fetch_summary,
)


if getattr(sys, "frozen", False):
    STATIC_ROOT = Path(getattr(sys, "_MEIPASS")) / "dashboard"
else:
    STATIC_ROOT = Path(__file__).resolve().parents[2] / "dashboard"


def connection_state(latest: dict | None, timeout_seconds: float) -> str:
    if not latest:
        return "WAITING"
    try:
        timestamp = datetime.fromisoformat(latest["timestamp"])
        age = (datetime.now().astimezone() - timestamp).total_seconds()
    except (TypeError, ValueError):
        return "UNKNOWN"
    return "CONNECTED" if age <= timeout_seconds else "DISCONNECTED"


def parse_time_range(query: dict[str, list[str]]) -> tuple[str | None, str | None]:
    """Validate browser date/time filters and normalize them to local ISO time."""

    def parse_bound(name: str, *, end: bool) -> datetime | None:
        raw = query.get(name, [""])[0].strip()
        if not raw:
            return None
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"Invalid {name} date/time") from error
        value = value.astimezone()
        value = value.replace(microsecond=999999 if end else 0)
        return value

    start_value = parse_bound("from", end=False)
    end_value = parse_bound("to", end=True)
    if start_value and end_value and start_value > end_value:
        raise ValueError("From date/time must be before To date/time")
    return (
        start_value.isoformat(timespec="microseconds") if start_value else None,
        end_value.isoformat(timespec="microseconds") if end_value else None,
    )


class DashboardServer(ThreadingHTTPServer):
    cfg: dict
    config_path: str
    collector: NetworkCollector
    writer: StorageWriter


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = f"VFREGVisor/{__version__}"

    @property
    def app_server(self) -> DashboardServer:
        return self.server  # type: ignore[return-value]

    def log_message(self, format: str, *args: object) -> None:
        return

    def send_bytes(self, body: bytes, content_type: str, filename: str | None = None) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, data: object) -> None:
        self.send_bytes(
            json.dumps(data, separators=(",", ":")).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def send_not_found(self) -> None:
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def send_error_json(self, status: HTTPStatus, message: str) -> None:
        body = json.dumps({"ok": False, "error": message}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json_payload(self) -> dict | None:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        if content_length <= 0 or content_length > 4096:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Invalid request size")
            return None
        try:
            payload = json.loads(self.rfile.read(content_length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Invalid JSON")
            return None
        if not isinstance(payload, dict):
            self.send_error_json(HTTPStatus.BAD_REQUEST, "JSON object required")
            return None
        return payload

    def status_payload(self) -> dict:
        cfg = self.app_server.cfg
        readings = fetch_recent(cfg["output_sqlite"], 180)
        latest = readings[-1] if readings else None
        network_snapshot = self.app_server.collector.snapshot()
        mode = cfg["network"].get("mode", "listener")
        if mode == "modbus_tcp_client":
            tcp_state = network_snapshot.get("tcp_listener")
            if tcp_state == "CLIENT_CONNECTED":
                current_connection_state = "CONNECTED"
            elif not latest and tcp_state in {"CLIENT_STARTING", "CLIENT_CONNECTING"}:
                current_connection_state = "WAITING"
            else:
                current_connection_state = "DISCONNECTED"
        else:
            current_connection_state = connection_state(
                latest,
                float(cfg["network"]["connection_timeout_seconds"]),
            )
        return {
            "app_version": __version__,
            "site_name": cfg["site_name"],
            "device_name": cfg["device_name"],
            "connection_state": current_connection_state,
            "latest": latest,
            "readings": readings,
            "summary": fetch_summary(cfg["output_sqlite"]),
            "events": fetch_events(cfg["output_sqlite"], 12),
            "diagnostics": {
                "network": network_snapshot,
                "storage": self.app_server.writer.snapshot(),
            },
            "network": {
                "mode": cfg["network"].get("mode", "listener"),
                "tcp_port": cfg["network"]["tcp_port"],
                "udp_port": cfg["network"].get("udp_port"),
                "tcp_host": cfg["network"].get("tcp_host"),
                "port_confirmed": cfg["network"].get("port_confirmed", False),
                "poll_interval_seconds": network_snapshot.get(
                    "poll_interval_seconds",
                    cfg["network"].get("modbus", {}).get("poll_interval_seconds"),
                ),
                "allowed_poll_intervals": ALLOWED_POLL_INTERVALS,
            },
            "factory": cfg.get("factory", {}),
            "limits": cfg["limits"],
        }

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        cfg = self.app_server.cfg
        if parsed.path == "/api/status":
            self.send_json(self.status_payload())
            return

        if parsed.path == "/api/readings":
            query = parse_qs(parsed.query)
            try:
                limit = int(query.get("limit", ["180"])[0])
            except ValueError:
                limit = 180
            try:
                start_time, end_time = parse_time_range(query)
            except ValueError as error:
                self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
                return
            sample_minutes_raw = query.get("sample_minutes", [None])[0]
            if sample_minutes_raw is not None:
                try:
                    sample_minutes = int(sample_minutes_raw)
                except ValueError:
                    self.send_error_json(
                        HTTPStatus.BAD_REQUEST, "sample_minutes must be 5, 15, 30, or 60"
                    )
                    return
                if sample_minutes not in (5, 15, 30, 60):
                    self.send_error_json(
                        HTTPStatus.BAD_REQUEST, "sample_minutes must be 5, 15, 30, or 60"
                    )
                    return
                if not start_time or not end_time:
                    self.send_error_json(
                        HTTPStatus.BAD_REQUEST, "sampled history requires from and to"
                    )
                    return
                readings, source_count = fetch_sampled_interval(
                    cfg["output_sqlite"], sample_minutes, start_time, end_time
                )
                self.send_json(
                    {
                        "readings": readings,
                        "count": len(readings),
                        "source_count": source_count,
                        "sample_minutes": sample_minutes,
                        "from": start_time,
                        "to": end_time,
                    }
                )
                return
            readings, count = fetch_recent_with_count(
                cfg["output_sqlite"], limit, start_time, end_time
            )
            self.send_json(
                {
                    "readings": readings,
                    "count": count,
                    "from": start_time,
                    "to": end_time,
                }
            )
            return

        if parsed.path == "/api/events":
            self.send_json(fetch_events(cfg["output_sqlite"], 100))
            return

        if parsed.path == "/api/export.csv":
            try:
                start_time, end_time = parse_time_range(parse_qs(parsed.query))
            except ValueError as error:
                self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
                return
            path = Path(
                export_csv(
                    cfg["output_sqlite"],
                    cfg["output_csv"],
                    start_time,
                    end_time,
                )
            )
            self.send_bytes(path.read_bytes(), "text/csv; charset=utf-8", "vfreg-readings.csv")
            return

        if parsed.path == "/api/export.xlsx":
            try:
                start_time, end_time = parse_time_range(parse_qs(parsed.query))
            except ValueError as error:
                self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
                return
            try:
                from .exports import build_xlsx
            except ModuleNotFoundError:
                self.send_error_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "XLSX export requires openpyxl; run install_dependencies.bat",
                )
                return
            except ImportError as error:
                self.send_error_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    f"Collector modules changed; restart the collector before exporting XLSX: {error}",
                )
                return
            try:
                path = Path(build_xlsx(cfg, start_time=start_time, end_time=end_time))
            except Exception as error:
                self.send_error_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    f"XLSX generation failed: {error}",
                )
                return
            self.send_bytes(
                path.read_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "vfreg-readings.xlsx",
            )
            return

        static_files = {
            "/": "index.html",
            "/index.html": "index.html",
            "/styles.css": "styles.css",
            "/app.js": "app.js",
        }
        filename = static_files.get(parsed.path)
        if not filename:
            self.send_not_found()
            return
        path = STATIC_ROOT / filename
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type == "application/javascript":
            content_type += "; charset=utf-8"
        self.send_bytes(path.read_bytes(), content_type)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in {"/api/session", "/api/poll-interval"}:
            self.send_not_found()
            return
        payload = self.read_json_payload()
        if payload is None:
            return

        if path == "/api/poll-interval":
            self.update_poll_interval(payload)
            return

        batch_id = str(payload.get("batch_id", "")).strip()
        shift = str(payload.get("shift", "")).strip()
        if len(batch_id) > 80 or len(shift) > 40:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Session labels are too long")
            return
        try:
            persist_factory_session(self.app_server.config_path, batch_id, shift)
        except (OSError, json.JSONDecodeError) as error:
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(error))
            return
        factory = self.app_server.cfg.setdefault("factory", {})
        factory["batch_id"] = batch_id
        factory["shift"] = shift
        self.app_server.writer.submit_event(
            "SESSION_UPDATED",
            "dashboard",
            f"batch={batch_id or '(empty)'}; shift={shift or '(empty)'}",
        )
        self.send_json({"ok": True, "batch_id": batch_id, "shift": shift})

    def update_poll_interval(self, payload: dict) -> None:
        try:
            seconds = float(payload["seconds"])
        except (KeyError, TypeError, ValueError):
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Invalid polling interval")
            return
        if seconds not in ALLOWED_POLL_INTERVALS:
            allowed = ", ".join(str(value) for value in ALLOWED_POLL_INTERVALS)
            self.send_error_json(
                HTTPStatus.BAD_REQUEST,
                f"Polling interval must be one of: {allowed} seconds",
            )
            return
        setter = getattr(self.app_server.collector, "set_poll_interval", None)
        if not callable(setter):
            self.send_error_json(
                HTTPStatus.CONFLICT,
                "Live polling control is available only in Modbus client mode",
            )
            return
        try:
            persist_poll_interval(self.app_server.config_path, seconds)
            applied = float(setter(seconds))
        except (OSError, json.JSONDecodeError, ValueError) as error:
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(error))
            return
        self.app_server.writer.submit_event(
            "POLL_INTERVAL_UPDATED",
            "dashboard",
            f"Modbus polling interval changed to {applied:g} seconds",
        )
        self.send_json({"ok": True, "poll_interval_seconds": applied})
