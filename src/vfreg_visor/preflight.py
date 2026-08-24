from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import socket
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import ConfigError, default_config_path, load_config
from .storage import directory_size, verify_sqlite_integrity


def result(name: str, status: str, detail: str, **data: Any) -> dict[str, Any]:
    return {"name": name, "status": status, "detail": detail, **data}


def resolve_path(config_path: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else config_path.parent / path


def check_storage(config_path: Path, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    destinations = {
        key: resolve_path(config_path, str(cfg[key]))
        for key in ("output_sqlite", "output_csv", "output_xlsx", "raw_journal")
    }
    parents = sorted({path.parent for path in destinations.values()}, key=str)
    for parent in parents:
        try:
            parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=parent, prefix=".vfreg-preflight-", delete=True):
                pass
            free = shutil.disk_usage(parent).free
            warning_free = int(cfg.get("storage", {}).get("warning_free_bytes", 5_000_000_000))
            status = "PASS" if free >= warning_free else "WARN"
            checks.append(result("writable_storage", status, f"{parent} ({free / 1_000_000_000:.1f} GB free)", path=str(parent), free_bytes=free))
        except OSError as error:
            checks.append(result("writable_storage", "FAIL", f"{parent}: {error}", path=str(parent)))
    sqlite_path = destinations["output_sqlite"]
    if sqlite_path.exists():
        valid, detail = verify_sqlite_integrity(sqlite_path)
        checks.append(
            result(
                "sqlite_integrity",
                "PASS" if valid else "FAIL",
                detail,
                path=str(sqlite_path),
            )
        )
    storage = cfg.get("storage", {})
    runtime_root = destinations["output_sqlite"].parent
    runtime_bytes = directory_size(runtime_root)
    free_bytes = shutil.disk_usage(runtime_root).free
    max_runtime_bytes = int(storage.get("max_runtime_bytes", 12_000_000_000))
    critical_free_bytes = int(storage.get("critical_free_bytes", 2_000_000_000))
    available_capacity = runtime_bytes + free_bytes
    required_capacity = max_runtime_bytes + critical_free_bytes
    checks.append(
        result(
            "storage_capacity",
            "PASS" if available_capacity >= required_capacity else "WARN",
            (
                f"{available_capacity / 1_000_000_000:.1f} GB available to VFREG; "
                f"{required_capacity / 1_000_000_000:.1f} GB recommended for "
                "the configured retention budget"
            ),
            available_capacity_bytes=available_capacity,
            required_capacity_bytes=required_capacity,
        )
    )
    checks.append(
        result(
            "retention_policy",
            "PASS",
            (
                f"measurements={int(storage.get('measurement_retention_days', 400))} days; "
                f"events={int(storage.get('event_retention_days', 400))} days; "
                f"backups={int(storage.get('backup_keep', 7))}; "
                f"budget={int(storage.get('max_runtime_bytes', 12_000_000_000))} bytes"
            ),
        )
    )
    return checks


def check_socket(host: str, port: int, sock_type: int, label: str) -> dict[str, Any]:
    try:
        with socket.socket(socket.AF_INET, sock_type) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind((host, port))
        return result(f"{label}_port", "PASS", f"Can bind {host}:{port}", host=host, port=port)
    except OSError as error:
        return result(f"{label}_port", "FAIL", f"Cannot bind {host}:{port}: {error}", host=host, port=port)


def local_ipv4_addresses() -> list[str]:
    addresses = {"127.0.0.1"}
    try:
        for entry in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addresses.add(entry[4][0])
    except OSError:
        pass
    return sorted(addresses)


def run_preflight(config_path: str | Path) -> dict[str, Any]:
    path = Path(config_path).resolve()
    cfg = load_config(path, validate=False)
    checks: list[dict[str, Any]] = []
    now = datetime.now().astimezone()
    checks.append(result("clock", "PASS" if now.utcoffset() is not None else "WARN", now.isoformat(timespec="seconds"), timestamp=now.isoformat()))

    for module in ("openpyxl",):
        installed = importlib.util.find_spec(module) is not None
        checks.append(result(f"dependency_{module}", "PASS" if installed else "WARN", "Installed" if installed else "Missing; collection and CSV still work, but XLSX export requires install_dependencies.bat"))

    network = cfg.get("network", {})
    mode = str(network.get("mode", "listener"))
    if mode == "modbus_tcp_client":
        try:
            target = str(network["tcp_host"])
            tcp_port = int(network["tcp_port"])
            modbus = network["modbus"]
            unit_id = int(modbus["unit_id"])
            function_code = int(modbus["function_code"])
            start_register = int(modbus["start_register"])
            quantity = int(modbus["quantity"])
            if not 1 <= tcp_port <= 65535:
                raise ValueError("TCP port must be between 1 and 65535")
            if not 1 <= unit_id <= 247 or function_code != 4:
                raise ValueError("invalid Modbus unit or production function (must be 04)")
            if not 0 <= start_register <= 65535 or not 1 <= quantity <= 125:
                raise ValueError("invalid Modbus register range")
            checks.append(result("modbus_target", "PASS", f"{target}:{tcp_port}, unit {unit_id}, function {function_code}, registers {start_register}-{start_register + quantity - 1}"))
        except (KeyError, TypeError, ValueError) as error:
            checks.append(result("network_config", "FAIL", f"Invalid Modbus client configuration: {error}"))
    else:
        host = str(network.get("listen_host", "0.0.0.0"))
        try:
            tcp_port = int(network["tcp_port"])
            udp_port = int(network["udp_port"])
            if not (1 <= tcp_port <= 65535 and 1 <= udp_port <= 65535):
                raise ValueError("ports must be between 1 and 65535")
            checks.append(check_socket(host, tcp_port, socket.SOCK_STREAM, "tcp"))
            checks.append(check_socket(host, udp_port, socket.SOCK_DGRAM, "udp"))
        except (KeyError, TypeError, ValueError) as error:
            checks.append(result("network_config", "FAIL", f"Invalid configured ports: {error}"))

        framing = str(network.get("tcp_framing", "newline"))
        checks.append(result("tcp_framing", "PASS" if framing in {"newline", "raw_chunks"} else "FAIL", framing))
    addresses = local_ipv4_addresses()
    expected = str(cfg.get("factory", {}).get("expected_collector_ip", "")).strip()
    address_status = "PASS" if not expected or expected in addresses else "WARN"
    address_detail = f"Local IPv4: {', '.join(addresses)}"
    if expected and expected not in addresses:
        address_detail += f"; expected factory address {expected} is not currently assigned"
    checks.append(result("network_addresses", address_status, address_detail, addresses=addresses, expected=expected))
    firewall_detail = "Confirm Windows Firewall allows Python to reach the NT1-B on Ethernet." if mode == "modbus_tcp_client" else "Confirm Windows Firewall allows Python on the Ethernet network; bind tests do not prove inbound reachability."
    checks.append(result("firewall", "MANUAL", firewall_detail))
    checks.extend(check_storage(path, cfg))

    counts = {status: sum(check["status"] == status for check in checks) for status in ("PASS", "WARN", "FAIL", "MANUAL")}
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "config_path": str(path),
        "port_confirmed": bool(network.get("port_confirmed", False)),
        "overall": "FAIL" if counts["FAIL"] else "READY_WITH_WARNINGS" if counts["WARN"] or counts["MANUAL"] else "READY",
        "counts": counts,
        "checks": checks,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check the VFREG notebook before a factory session")
    parser.add_argument("--config", default=str(default_config_path()))
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument("--output", help="Also save the JSON report to this path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = run_preflight(args.config)
    except (ConfigError, OSError, json.JSONDecodeError) as error:
        print(f"Preflight failed: {error}")
        return 2
    encoded = json.dumps(report, indent=2)
    if args.output:
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded + "\n", encoding="utf-8")
    if args.json:
        print(encoded)
    else:
        print(f"VFREG PREFLIGHT: {report['overall']}")
        for check in report["checks"]:
            print(f"[{check['status']:<6}] {check['name']}: {check['detail']}")
        if not report["port_confirmed"]:
            print("[NOTICE] The configured listener ports remain unconfirmed for the real VFREG.")
    return 1 if report["overall"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
