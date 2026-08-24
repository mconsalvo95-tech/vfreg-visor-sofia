from __future__ import annotations

import base64
import hashlib
import math
import socket
import struct
import threading
import time
from typing import Any, Optional

from storage import Measurement, StorageWriter, now_iso


def build_modbus_request(
    transaction_id: int,
    unit_id: int,
    function_code: int,
    start_register: int,
    quantity: int,
) -> bytes:
    if function_code not in (3, 4):
        raise ValueError("Only read functions 03 and 04 are supported")
    if not 1 <= unit_id <= 247:
        raise ValueError("Modbus unit_id must be between 1 and 247")
    if not 0 <= start_register <= 65535:
        raise ValueError("Modbus start_register must be between 0 and 65535")
    if not 1 <= quantity <= 125:
        raise ValueError("Modbus quantity must be between 1 and 125")
    return struct.pack(
        "!HHHBBHH",
        transaction_id & 0xFFFF,
        0,
        6,
        unit_id,
        function_code,
        start_register,
        quantity,
    )


def _alarm_for(values: dict[str, float], cfg: dict[str, Any]) -> str:
    limits_cfg = cfg.get("limits", {})
    if limits_cfg.get("confirmed", True) is False:
        return "NORMAL"
    for field, value in values.items():
        limits = limits_cfg.get(field)
        if limits and (value < float(limits["min"]) or value > float(limits["max"])):
            return "ALARM"
    return "NORMAL"


def parse_modbus_response(
    payload: bytes,
    cfg: dict[str, Any],
    *,
    expected_transaction_id: Optional[int] = None,
    received_at: Optional[str] = None,
) -> Measurement:
    network = cfg["network"]
    modbus = network["modbus"]
    if len(payload) < 9:
        raise ValueError("Modbus response is shorter than 9 bytes")
    transaction_id, protocol_id, length, unit_id = struct.unpack("!HHHB", payload[:7])
    if protocol_id != 0:
        raise ValueError(f"Unexpected Modbus protocol ID {protocol_id}")
    if length != len(payload) - 6:
        raise ValueError(f"Modbus length field {length} does not match payload")
    if expected_transaction_id is not None and transaction_id != expected_transaction_id:
        raise ValueError(
            f"Transaction mismatch: expected {expected_transaction_id}, got {transaction_id}"
        )
    expected_unit = int(modbus["unit_id"])
    if unit_id != expected_unit:
        raise ValueError(f"Unit mismatch: expected {expected_unit}, got {unit_id}")
    function_code = payload[7]
    if function_code & 0x80:
        raise ValueError(f"Modbus exception {payload[8]}")
    expected_function = int(modbus["function_code"])
    if function_code != expected_function:
        raise ValueError(
            f"Function mismatch: expected {expected_function}, got {function_code}"
        )
    byte_count = payload[8]
    if byte_count % 2 or len(payload) != 9 + byte_count:
        raise ValueError("Invalid Modbus register byte count")
    registers = [
        struct.unpack("!H", payload[position : position + 2])[0]
        for position in range(9, 9 + byte_count, 2)
    ]
    start_register = int(modbus["start_register"])
    register_map = modbus["register_map"]
    values: dict[str, float] = {}
    for field in ("voltage_v", "current_ma", "frequency_hz"):
        mapping = register_map[field]
        offset = int(mapping["register"]) - start_register
        if not 0 <= offset < len(registers):
            raise ValueError(f"Mapped {field} register is absent from response")
        values[field] = registers[offset] * float(mapping.get("scale", 1))

    received_at = received_at or now_iso()
    host = str(network["tcp_host"])
    port = int(network["tcp_port"])
    factory = cfg.get("factory", {})
    return Measurement(
        timestamp=received_at,
        source=f"modbus_tcp:{host}:{port}",
        protocol="modbus_tcp",
        source_ip=host,
        source_port=port,
        sequence=transaction_id,
        voltage_v=values["voltage_v"],
        current_ma=values["current_ma"],
        frequency_hz=values["frequency_hz"],
        line_status="RUNNING",
        alarm_status=_alarm_for(values, cfg),
        status="OK",
        payload_size=len(payload),
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        batch_id=str(factory.get("batch_id", "")),
        shift=str(factory.get("shift", "")),
        raw_payload="base64:" + base64.b64encode(payload).decode("ascii"),
    )


class ModbusTcpCollector:
    def __init__(self, cfg: dict[str, Any], writer: StorageWriter) -> None:
        self.cfg = cfg
        self.writer = writer
        self.stop_event = threading.Event()
        self._settings_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="vfreg-modbus-tcp-client"
        )
        self._lock = threading.Lock()
        configured_interval = float(
            cfg["network"]["modbus"].get("poll_interval_seconds", 0.5)
        )
        self._poll_interval_seconds = self._validate_poll_interval(
            configured_interval
        )
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
            "tcp_listener": "CLIENT_STARTING",
            "udp_listener": "DISABLED",
            "last_error": "",
        }

    def start(self) -> "ModbusTcpCollector":
        self._thread.start()
        return self

    def stop(self, timeout: float = 3) -> None:
        self.stop_event.set()
        self._settings_event.set()
        self._thread.join(timeout=timeout)

    @staticmethod
    def _validate_poll_interval(seconds: float) -> float:
        value = float(seconds)
        if not math.isfinite(value) or not 0.5 <= value <= 3600:
            raise ValueError("Polling interval must be between 0.5 and 3600 seconds")
        return value

    def poll_interval_seconds(self) -> float:
        with self._lock:
            return self._poll_interval_seconds

    def set_poll_interval(self, seconds: float) -> float:
        value = self._validate_poll_interval(seconds)
        with self._lock:
            self._poll_interval_seconds = value
            self.cfg["network"]["modbus"]["poll_interval_seconds"] = value
        self._settings_event.set()
        return value

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            result = dict(self._stats)
        network = self.cfg["network"]
        result.update(
            {
                "threads_alive": int(self._thread.is_alive()),
                "mode": "modbus_tcp_client",
                "target_host": network["tcp_host"],
                "tcp_port": int(network["tcp_port"]),
                "udp_port": None,
                "tcp_framing": "modbus_tcp",
                "poll_interval_seconds": self.poll_interval_seconds(),
            }
        )
        return result

    def _update(self, **values: Any) -> None:
        with self._lock:
            self._stats.update(values)

    def _increment(self, key: str, amount: int = 1) -> None:
        with self._lock:
            self._stats[key] += amount

    def _journal(
        self, payload: bytes, received_at: str, direction: str, kind: str
    ) -> None:
        network = self.cfg["network"]
        envelope = {
            "received_at": received_at,
            "protocol": "modbus_tcp",
            "source_ip": network["tcp_host"] if direction == "received" else "collector",
            "source_port": int(network["tcp_port"]) if direction == "received" else None,
            "destination_ip": network["tcp_host"] if direction == "sent" else "collector",
            "destination_port": int(network["tcp_port"]) if direction == "sent" else None,
            "direction": direction,
            "kind": kind,
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "payload_base64": base64.b64encode(payload).decode("ascii"),
        }
        self.writer.submit_raw(envelope)
        self._increment("raw_chunks")

    def _recv_exact(self, connection: socket.socket, size: int, deadline: float) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            if self.stop_event.is_set():
                raise InterruptedError("Collector stopping")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Timed out waiting for Modbus response")
            connection.settimeout(min(0.5, remaining))
            try:
                chunk = connection.recv(size - len(chunks))
            except socket.timeout:
                continue
            if not chunk:
                raise ConnectionError("NT1-B closed the TCP connection")
            chunks.extend(chunk)
        return bytes(chunks)

    def _read_response(self, connection: socket.socket, timeout: float) -> bytes:
        deadline = time.monotonic() + timeout
        header = self._recv_exact(connection, 7, deadline)
        _transaction, _protocol, length, _unit = struct.unpack("!HHHB", header)
        remaining = length - 1
        if not 2 <= remaining <= 254:
            raise ValueError(f"Invalid Modbus response length {length}")
        return header + self._recv_exact(connection, remaining, deadline)

    def _record(self, row: Measurement) -> None:
        self.writer.submit_measurement(row)
        self._increment("packets_received")
        self._increment("parsed_packets")
        self._increment("bytes_received", row.payload_size)
        if row.alarm_status == "ALARM":
            self._increment("alarm_packets")
        self._update(last_packet_at=row.timestamp, last_source=row.source)

    def _wait_for_next_poll(self) -> bool:
        """Wait using the latest interval; return True when stopping."""
        while not self.stop_event.is_set():
            self._settings_event.clear()
            interval = self.poll_interval_seconds()
            if not self._settings_event.wait(interval):
                return False
        return True

    def _run(self) -> None:
        network = self.cfg["network"]
        modbus = network["modbus"]
        host = str(network["tcp_host"])
        port = int(network["tcp_port"])
        request_timeout = float(modbus.get("request_timeout_seconds", 2))
        reconnect_delay = float(network.get("reconnect_delay_seconds", 2))
        transaction_id = 0
        source = f"modbus_tcp:{host}:{port}"

        while not self.stop_event.is_set():
            try:
                self._update(tcp_listener="CLIENT_CONNECTING")
                with socket.create_connection((host, port), timeout=request_timeout) as connection:
                    self._increment("tcp_connections")
                    self._increment("active_tcp_connections")
                    self._update(tcp_listener="CLIENT_CONNECTED", last_error="")
                    self.writer.submit_event(
                        "CONNECTED", source, "Connected to NT1-B Modbus TCP server"
                    )
                    try:
                        while not self.stop_event.is_set():
                            transaction_id = transaction_id % 65535 + 1
                            request = build_modbus_request(
                                transaction_id,
                                int(modbus["unit_id"]),
                                int(modbus["function_code"]),
                                int(modbus["start_register"]),
                                int(modbus["quantity"]),
                            )
                            connection.sendall(request)
                            sent_at = now_iso()
                            self._journal(request, sent_at, "sent", "modbus_request")
                            response = self._read_response(connection, request_timeout)
                            received_at = now_iso()
                            self._journal(
                                response, received_at, "received", "modbus_response"
                            )
                            row = parse_modbus_response(
                                response,
                                self.cfg,
                                expected_transaction_id=transaction_id,
                                received_at=received_at,
                            )
                            self._record(row)
                            if self._wait_for_next_poll():
                                break
                    finally:
                        self._increment("active_tcp_connections", -1)
                        self._increment("disconnects")
                        self.writer.submit_event(
                            "DISCONNECTED", source, "Modbus TCP client disconnected"
                        )
            except InterruptedError:
                break
            except (OSError, TimeoutError, ValueError, ConnectionError) as error:
                message = str(error)
                self._update(tcp_listener="CLIENT_RETRYING", last_error=message)
                self.writer.submit_event("MODBUS_CLIENT_ERROR", source, message, "ERROR")
                if self.stop_event.wait(reconnect_delay):
                    break
        self._update(tcp_listener="STOPPED")
