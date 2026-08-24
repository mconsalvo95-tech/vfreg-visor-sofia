from __future__ import annotations

import base64
import hashlib
import json
import re
import socket
import threading
from collections.abc import Callable
from typing import Any, Optional

from .storage import Measurement, StorageWriter, now_iso


VALUE_PATTERNS = {
    "voltage_v": re.compile(
        r"(?:V|volt|voltage|voltaje)\s*[:=]\s*(-?\d+(?:[\.,]\d+)?)", re.I
    ),
    "current_ma": re.compile(
        r"(?:mA|milliamps?|current_ma|current|corriente|I)\s*[:=]\s*(-?\d+(?:[\.,]\d+)?)",
        re.I,
    ),
    "frequency_hz": re.compile(
        r"(?:F|freq|frequency|frecuencia|hz)\s*[:=]\s*(-?\d+(?:[\.,]\d+)?)", re.I
    ),
}


def to_float(value: object) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def value_from(data: dict[str, Any], *names: str) -> Optional[float]:
    for name in names:
        if name in data:
            return to_float(data[name])
    return None


def payload_text(payload: bytes) -> str:
    try:
        text = payload.decode("utf-8")
        printable = sum(character.isprintable() or character in "\r\n\t" for character in text)
        if text and printable / len(text) >= 0.85:
            return text.strip()
    except UnicodeDecodeError:
        pass
    return "base64:" + base64.b64encode(payload).decode("ascii")


def alarm_for(values: dict[str, Optional[float]], cfg: dict, line_status: str) -> str:
    if line_status != "RUNNING":
        return "NORMAL"
    for field, value in values.items():
        limits = cfg.get("limits", {}).get(field)
        if value is None or not limits:
            continue
        if value < float(limits["min"]) or value > float(limits["max"]):
            return "ALARM"
    return "NORMAL"


def parse_payload(
    payload: bytes,
    cfg: Optional[dict] = None,
    *,
    received_at: Optional[str] = None,
    protocol: str = "unknown",
    source_ip: str = "",
    source_port: Optional[int] = None,
) -> Measurement:
    cfg = cfg or {}
    received_at = received_at or now_iso()
    text = payload_text(payload)
    data: dict[str, Any] = {}
    if not text.startswith("base64:"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                data = parsed
        except json.JSONDecodeError:
            pass

    if data:
        values = {
            "voltage_v": value_from(data, "voltage_v", "voltage", "V"),
            "current_ma": value_from(data, "current_ma", "current", "mA", "I"),
            "frequency_hz": value_from(data, "frequency_hz", "frequency", "F"),
        }
        device_timestamp = str(data.get("measured_at") or data.get("timestamp") or "")
        sequence_value = data.get("sequence")
        try:
            sequence = int(sequence_value) if sequence_value is not None else None
        except (TypeError, ValueError):
            sequence = None
        line_status = str(data.get("line_status", "RUNNING")).upper()
    else:
        values = {}
        for key, pattern in VALUE_PATTERNS.items():
            match = pattern.search(text)
            values[key] = to_float(match.group(1)) if match else None
        device_timestamp = ""
        sequence = None
        line_status = "RUNNING"

    present = sum(value is not None for value in values.values())
    status = "OK" if present == 3 else "PARTIAL" if present else "RAW_ONLY"
    alarm_status = alarm_for(values, cfg, line_status)
    if status == "RAW_ONLY":
        quality_flag, quality_details = "INVALID", "No measurement values decoded"
    elif status == "PARTIAL":
        quality_flag, quality_details = "INCOMPLETE", "One or more values are missing"
    elif cfg.get("limits", {}).get("confirmed", True) is False:
        quality_flag, quality_details = (
            "UNVERIFIED",
            "Operating limits have not been confirmed",
        )
    elif alarm_status == "ALARM":
        quality_flag, quality_details = "OUT_OF_RANGE", "Value outside configured limits"
    else:
        quality_flag, quality_details = "GOOD", ""
    source = f"{protocol}:{source_ip}:{source_port}" if source_ip else protocol
    factory = cfg.get("factory", {})
    return Measurement(
        timestamp=received_at,
        device_timestamp=device_timestamp,
        source=source,
        protocol=protocol,
        source_ip=source_ip,
        source_port=source_port,
        sequence=sequence,
        voltage_v=values["voltage_v"],
        current_ma=values["current_ma"],
        frequency_hz=values["frequency_hz"],
        line_status=line_status,
        alarm_status=alarm_status,
        status=status,
        quality_flag=quality_flag,
        quality_details=quality_details,
        payload_size=len(payload),
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        batch_id=str(factory.get("batch_id", "")),
        shift=str(factory.get("shift", "")),
        raw_payload=text,
    )


class NetworkCollector:
    def __init__(
        self,
        cfg: dict,
        writer: StorageWriter,
        on_measurement: Optional[Callable[[Measurement], None]] = None,
    ) -> None:
        self.cfg = cfg
        self.writer = writer
        self.on_measurement = on_measurement
        self.stop_event = threading.Event()
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()
        self._sequences: dict[tuple[str, str], int] = {}
        self._stats: dict[str, Any] = {
            "started_at": now_iso(),
            "packets_received": 0,
            "raw_chunks": 0,
            "bytes_received": 0,
            "parsed_packets": 0,
            "partial_packets": 0,
            "raw_only_packets": 0,
            "alarm_packets": 0,
            "tcp_connections": 0,
            "active_tcp_connections": 0,
            "disconnects": 0,
            "sequence_gaps": 0,
            "duplicate_sequences": 0,
            "last_packet_at": "",
            "last_source": "",
            "tcp_listener": "STARTING",
            "udp_listener": "STARTING",
            "last_error": "",
        }

    def start(self) -> "NetworkCollector":
        self._threads = [
            threading.Thread(target=self._tcp_server, daemon=True, name="vfreg-tcp-listener"),
            threading.Thread(target=self._udp_server, daemon=True, name="vfreg-udp-listener"),
        ]
        for thread in self._threads:
            thread.start()
        return self

    def stop(self, timeout: float = 3) -> None:
        self.stop_event.set()
        for thread in self._threads:
            thread.join(timeout=timeout)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            result = dict(self._stats)
        result["threads_alive"] = sum(thread.is_alive() for thread in self._threads)
        result["listen_host"] = self.cfg["network"]["listen_host"]
        result["tcp_port"] = int(self.cfg["network"]["tcp_port"])
        result["udp_port"] = int(self.cfg["network"]["udp_port"])
        result["tcp_framing"] = self.cfg["network"].get("tcp_framing", "newline")
        return result

    def _update(self, **values: Any) -> None:
        with self._lock:
            self._stats.update(values)

    def _increment(self, key: str, amount: int = 1) -> None:
        with self._lock:
            self._stats[key] += amount

    def _listener_error(self, listener: str, error: Exception) -> None:
        message = f"{listener} listener failed: {error}"
        self._update(**{f"{listener}_listener": "ERROR", "last_error": message})
        self.writer.submit_event("LISTENER_ERROR", listener, message, "ERROR")

    def _journal_raw(
        self,
        payload: bytes,
        protocol: str,
        address: tuple[str, int],
        received_at: str,
        kind: str,
    ) -> None:
        envelope = {
            "received_at": received_at,
            "protocol": protocol,
            "source_ip": address[0],
            "source_port": address[1],
            "kind": kind,
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "payload_base64": base64.b64encode(payload).decode("ascii"),
        }
        self.writer.submit_raw(envelope)
        self._increment("raw_chunks")

    def _track_sequence(self, row: Measurement) -> None:
        if row.sequence is None:
            return
        key = (row.protocol, row.source_ip)
        previous = self._sequences.get(key)
        self._sequences[key] = row.sequence
        if previous is None:
            return
        if row.sequence <= previous:
            self._increment("duplicate_sequences")
            self.writer.submit_event(
                "SEQUENCE_DUPLICATE",
                row.source,
                f"Received sequence {row.sequence} after {previous}",
                "WARN",
            )
        elif row.sequence > previous + 1:
            missing = row.sequence - previous - 1
            self._increment("sequence_gaps", missing)
            self.writer.submit_event(
                "SEQUENCE_GAP",
                row.source,
                f"Missing {missing} sequence values between {previous} and {row.sequence}",
                "WARN",
            )

    def _handle_frame(
        self,
        payload: bytes,
        protocol: str,
        address: tuple[str, int],
        received_at: Optional[str] = None,
    ) -> None:
        if not payload:
            return
        received_at = received_at or now_iso()
        row = parse_payload(
            payload,
            self.cfg,
            received_at=received_at,
            protocol=protocol,
            source_ip=address[0],
            source_port=address[1],
        )
        self._track_sequence(row)
        self.writer.submit_measurement(row)
        self._increment("packets_received")
        self._increment("bytes_received", len(payload))
        if row.status == "OK":
            self._increment("parsed_packets")
        elif row.status == "PARTIAL":
            self._increment("partial_packets")
        else:
            self._increment("raw_only_packets")
        if row.alarm_status == "ALARM":
            self._increment("alarm_packets")
        self._update(last_packet_at=received_at, last_source=row.source)
        if self.on_measurement:
            self.on_measurement(row)

    def _tcp_server(self) -> None:
        network = self.cfg["network"]
        host = network["listen_host"]
        port = int(network["tcp_port"])
        framing = network.get("tcp_framing", "newline")
        max_buffer = int(network.get("max_buffer_bytes", 1048576))
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.bind((host, port))
                server.listen()
                server.settimeout(0.5)
                self._update(tcp_listener="LISTENING")
                self.writer.submit_event("LISTENER_STARTED", "tcp", f"Listening on {host}:{port}")
                while not self.stop_event.is_set():
                    try:
                        connection, address = server.accept()
                    except socket.timeout:
                        continue
                    self._increment("tcp_connections")
                    self._increment("active_tcp_connections")
                    self.writer.submit_event("CONNECTED", f"tcp:{address[0]}:{address[1]}", "TCP client connected")
                    try:
                        with connection:
                            connection.settimeout(0.5)
                            buffer = b""
                            while not self.stop_event.is_set():
                                try:
                                    chunk = connection.recv(65535)
                                except socket.timeout:
                                    continue
                                if not chunk:
                                    break
                                received_at = now_iso()
                                self._journal_raw(chunk, "tcp", address, received_at, "tcp_chunk")
                                if framing == "raw_chunks":
                                    self._handle_frame(chunk, "tcp", address, received_at)
                                    continue
                                buffer += chunk
                                while b"\n" in buffer:
                                    frame, buffer = buffer.split(b"\n", 1)
                                    self._handle_frame(frame.strip(), "tcp", address, received_at)
                                if len(buffer) > max_buffer:
                                    self._handle_frame(buffer[:max_buffer], "tcp", address, received_at)
                                    buffer = buffer[max_buffer:]
                            if buffer.strip():
                                self._handle_frame(buffer.strip(), "tcp", address)
                    finally:
                        self._increment("active_tcp_connections", -1)
                        self._increment("disconnects")
                        self.writer.submit_event("DISCONNECTED", f"tcp:{address[0]}:{address[1]}", "TCP client disconnected")
        except OSError as error:
            self._listener_error("tcp", error)

    def _udp_server(self) -> None:
        network = self.cfg["network"]
        host = network["listen_host"]
        port = int(network["udp_port"])
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
                server.bind((host, port))
                server.settimeout(0.5)
                self._update(udp_listener="LISTENING")
                self.writer.submit_event("LISTENER_STARTED", "udp", f"Listening on {host}:{port}")
                while not self.stop_event.is_set():
                    try:
                        payload, address = server.recvfrom(65535)
                    except socket.timeout:
                        continue
                    received_at = now_iso()
                    self._journal_raw(payload, "udp", address, received_at, "udp_datagram")
                    self._handle_frame(payload, "udp", address, received_at)
        except OSError as error:
            self._listener_error("udp", error)


def start_network_servers(
    cfg: dict,
    writer: StorageWriter,
    on_measurement: Optional[Callable[[Measurement], None]] = None,
) -> NetworkCollector:
    if cfg.get("network", {}).get("mode") == "modbus_tcp_client":
        from .modbus import ModbusTcpCollector

        return ModbusTcpCollector(cfg, writer).start()  # type: ignore[return-value]
    return NetworkCollector(cfg, writer, on_measurement).start()
