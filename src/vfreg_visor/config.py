from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


ALLOWED_POLL_INTERVALS = (0.5, 1.0, 5.0, 15.0, 30.0, 60.0)
OUTPUT_KEYS = ("output_csv", "output_sqlite", "output_xlsx", "raw_journal")


class ConfigError(ValueError):
    """Raised when a deployment configuration is missing or unsafe."""


def application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def default_config_path() -> Path:
    root = application_root()
    factory_config = root / "config.factory.json"
    if getattr(sys, "frozen", False) and factory_config.exists():
        return factory_config
    return root / "config.json"


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ConfigError(f"{label} must be an integer") from error
    if not minimum <= parsed <= maximum:
        raise ConfigError(f"{label} must be between {minimum} and {maximum}")
    return parsed


def _number(value: Any, label: str, minimum: float, *, allow_zero: bool = False) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise ConfigError(f"{label} must be numeric") from error
    if parsed < minimum or (not allow_zero and parsed == 0):
        comparison = "zero or greater" if allow_zero else f"greater than {minimum:g}"
        raise ConfigError(f"{label} must be {comparison}")
    return parsed


def validate_config(cfg: dict[str, Any]) -> None:
    for key in ("site_name", "device_name", *OUTPUT_KEYS):
        if not isinstance(cfg.get(key), str) or not str(cfg[key]).strip():
            raise ConfigError(f"Missing or invalid configuration value: {key}")

    dashboard = cfg.get("dashboard")
    if not isinstance(dashboard, dict):
        raise ConfigError("Missing dashboard configuration")
    if dashboard.get("host") != "127.0.0.1":
        raise ConfigError("dashboard.host must remain 127.0.0.1 for local-only access")
    _integer(dashboard.get("port"), "dashboard.port", 1, 65535)

    storage = cfg.get("storage", {})
    if not isinstance(storage, dict):
        raise ConfigError("storage must be a JSON object")
    _integer(storage.get("queue_size", 10000), "storage.queue_size", 1, 10_000_000)
    _integer(storage.get("batch_size", 100), "storage.batch_size", 1, 100_000)
    _integer(
        storage.get("raw_journal_max_bytes", 104857600),
        "storage.raw_journal_max_bytes",
        0,
        10_000_000_000,
    )
    _integer(storage.get("raw_journal_backups", 5), "storage.raw_journal_backups", 0, 1000)

    limits = cfg.get("limits")
    if not isinstance(limits, dict):
        raise ConfigError("Missing limits configuration")
    for field in ("voltage_v", "current_ma", "frequency_hz"):
        field_limits = limits.get(field)
        if not isinstance(field_limits, dict):
            raise ConfigError(f"Missing limits for {field}")
        try:
            minimum = float(field_limits.get("min"))
            maximum = float(field_limits.get("max"))
        except (TypeError, ValueError) as error:
            raise ConfigError(f"Limits for {field} must be numeric") from error
        if minimum > maximum:
            raise ConfigError(f"Minimum limit exceeds maximum for {field}")

    network = cfg.get("network")
    if not isinstance(network, dict):
        raise ConfigError("Missing network configuration")
    mode = network.get("mode", "listener")
    if mode == "modbus_tcp_client":
        if not isinstance(network.get("tcp_host"), str) or not network["tcp_host"].strip():
            raise ConfigError("network.tcp_host is required in Modbus client mode")
        _integer(network.get("tcp_port"), "network.tcp_port", 1, 65535)
        _number(
            network.get("reconnect_delay_seconds", 2),
            "network.reconnect_delay_seconds",
            0,
        )
        modbus = network.get("modbus")
        if not isinstance(modbus, dict):
            raise ConfigError("Missing network.modbus configuration")
        _integer(modbus.get("unit_id"), "network.modbus.unit_id", 1, 247)
        function_code = _integer(
            modbus.get("function_code"), "network.modbus.function_code", 1, 127
        )
        if function_code != 4:
            raise ConfigError(
                "Production Modbus function must be 04 (Read Input Registers); "
                "write and alternate functions are not allowed"
            )
        start_register = _integer(
            modbus.get("start_register"), "network.modbus.start_register", 0, 65535
        )
        quantity = _integer(modbus.get("quantity"), "network.modbus.quantity", 1, 125)
        if start_register + quantity - 1 > 65535:
            raise ConfigError("Configured Modbus register range exceeds 65535")
        try:
            poll_interval = float(modbus.get("poll_interval_seconds"))
        except (TypeError, ValueError) as error:
            raise ConfigError("network.modbus.poll_interval_seconds must be numeric") from error
        if poll_interval not in ALLOWED_POLL_INTERVALS:
            allowed = ", ".join(str(value) for value in ALLOWED_POLL_INTERVALS)
            raise ConfigError(f"Polling interval must be one of: {allowed} seconds")
        _number(
            modbus.get("request_timeout_seconds", 2),
            "network.modbus.request_timeout_seconds",
            0,
        )
        register_map = modbus.get("register_map")
        if not isinstance(register_map, dict):
            raise ConfigError("Missing network.modbus.register_map")
        for field in ("voltage_v", "current_ma", "frequency_hz"):
            mapping = register_map.get(field)
            if not isinstance(mapping, dict):
                raise ConfigError(f"Missing register mapping for {field}")
            register = _integer(
                mapping.get("register"), f"register_map.{field}.register", 0, 65535
            )
            if not start_register <= register < start_register + quantity:
                raise ConfigError(f"Register mapping for {field} is outside the read range")
            try:
                float(mapping.get("scale"))
            except (TypeError, ValueError) as error:
                raise ConfigError(f"Register scale for {field} must be numeric") from error
    elif mode == "listener":
        if not isinstance(network.get("listen_host"), str):
            raise ConfigError("network.listen_host is required in listener mode")
        _integer(network.get("tcp_port"), "network.tcp_port", 1, 65535)
        _integer(network.get("udp_port"), "network.udp_port", 1, 65535)
        _number(
            network.get("connection_timeout_seconds", 3),
            "network.connection_timeout_seconds",
            0,
        )
        if network.get("tcp_framing", "newline") not in {"newline", "raw_chunks"}:
            raise ConfigError("network.tcp_framing must be newline or raw_chunks")
    else:
        raise ConfigError(f"Unsupported network.mode: {mode}")


def load_config(path: str | Path, *, validate: bool = True) -> dict[str, Any]:
    config_path = Path(path).resolve()
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            cfg = json.load(handle)
    except FileNotFoundError as error:
        raise ConfigError(
            f"Configuration file not found: {config_path}. "
            "Create it from config.example.json before starting."
        ) from error
    except json.JSONDecodeError as error:
        raise ConfigError(
            f"Configuration JSON is invalid at line {error.lineno}, column {error.colno}: "
            f"{config_path}"
        ) from error
    if not isinstance(cfg, dict):
        raise ConfigError("The configuration root must be a JSON object")
    if validate:
        validate_config(cfg)
    for key in OUTPUT_KEYS:
        if key not in cfg:
            continue
        value = Path(str(cfg[key]))
        if not value.is_absolute():
            cfg[key] = str((config_path.parent / value).resolve())
    return cfg


def ensure_runtime_paths_writable(cfg: dict[str, Any]) -> None:
    checked: set[Path] = set()
    for key in OUTPUT_KEYS:
        parent = Path(str(cfg[key])).resolve().parent
        if parent in checked:
            continue
        checked.add(parent)
        try:
            parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix=".vfreg-write-test-", dir=parent):
                pass
        except OSError as error:
            raise ConfigError(f"Runtime data directory is not writable: {parent}: {error}") from error


def _update_config(config_path: str | Path, update: Any) -> None:
    path = Path(config_path).resolve()
    with path.open("r", encoding="utf-8") as handle:
        cfg = json.load(handle)
    update(cfg)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(cfg, handle, indent=2)
        handle.write("\n")
    os.replace(temporary, path)


def persist_factory_session(config_path: str | Path, batch_id: str, shift: str) -> None:
    def update(cfg: dict[str, Any]) -> None:
        factory = cfg.setdefault("factory", {})
        factory["batch_id"] = batch_id
        factory["shift"] = shift

    _update_config(config_path, update)


def persist_poll_interval(config_path: str | Path, seconds: float) -> None:
    def update(cfg: dict[str, Any]) -> None:
        cfg.setdefault("network", {}).setdefault("modbus", {})[
            "poll_interval_seconds"
        ] = float(seconds)

    _update_config(config_path, update)
