from __future__ import annotations

import argparse
import errno
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .config import (
    ConfigError,
    default_config_path,
    ensure_runtime_paths_writable,
    load_config,
)
from .dashboard import DashboardHandler, DashboardServer
from .instance import DeploymentInstanceLock, InstanceAlreadyRunning
from .network import start_network_servers
from .storage import StorageWriter


class StartupError(RuntimeError):
    pass


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the VFREG collector and dashboard")
    parser.add_argument("--config", default=str(default_config_path()))
    parser.add_argument("--version", action="version", version=f"VFREG Visor {__version__}")
    return parser.parse_args(argv)


def _create_dashboard_server(host: str, port: int) -> DashboardServer:
    try:
        return DashboardServer((host, port), DashboardHandler)
    except OSError as error:
        if error.errno in {errno.EACCES, errno.EADDRINUSE} or getattr(
            error, "winerror", None
        ) in {10013, 10048}:
            raise StartupError(
                f"Dashboard port {port} on {host} is already occupied or blocked. "
                "Close the other VFREG window or application using that port, "
                "then retry. If no application is using it, ask IT to check Windows permissions."
            ) from error
        raise StartupError(f"Dashboard could not bind to {host}:{port}: {error}") from error


def run(config_path: str | Path) -> None:
    resolved_config = Path(config_path).resolve()
    cfg = load_config(resolved_config)
    ensure_runtime_paths_writable(cfg)
    lock = DeploymentInstanceLock(resolved_config.parent)

    with lock:
        host = str(cfg["dashboard"]["host"])
        port = int(cfg["dashboard"]["port"])
        server = _create_dashboard_server(host, port)
        writer: StorageWriter | None = None
        collector = None
        try:
            storage_cfg = cfg.get("storage", {})
            writer = StorageWriter(
                cfg["output_sqlite"],
                cfg["raw_journal"],
                queue_size=int(storage_cfg.get("queue_size", 10000)),
                batch_size=int(storage_cfg.get("batch_size", 100)),
                raw_journal_max_bytes=int(
                    storage_cfg.get("raw_journal_max_bytes", 104857600)
                ),
                raw_journal_backups=int(storage_cfg.get("raw_journal_backups", 5)),
            )
            collector = start_network_servers(cfg, writer)
            server.cfg = cfg
            server.config_path = str(resolved_config)
            server.collector = collector
            server.writer = writer

            print(f"VFREG Visor {__version__}")
            print(f"Dashboard: http://{host}:{port}")
            if cfg["network"].get("mode") == "modbus_tcp_client":
                modbus = cfg["network"]["modbus"]
                first_register = int(modbus["start_register"])
                last_register = first_register + int(modbus["quantity"]) - 1
                print(
                    f"Collector: Modbus TCP client {cfg['network']['tcp_host']}:"
                    f"{cfg['network']['tcp_port']} unit {modbus['unit_id']} "
                    f"function {modbus['function_code']:02d} registers "
                    f"{first_register}-{last_register}"
                )
            else:
                print(
                    f"Collector: UDP {cfg['network']['udp_port']} / "
                    f"TCP {cfg['network']['tcp_port']} "
                    f"({'confirmed' if cfg['network'].get('port_confirmed') else 'test port, unconfirmed'})"
                )
            print("Runtime data:", Path(cfg["output_sqlite"]).parent)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                print("\nStopping VFREG dashboard.")
        finally:
            if collector is not None:
                collector.stop()
            if writer is not None:
                writer.close()
            server.server_close()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        run(args.config)
    except (ConfigError, InstanceAlreadyRunning, StartupError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"ERROR: VFREG could not start: {error}", file=sys.stderr)
        return 2
    return 0
