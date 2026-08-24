from __future__ import annotations

import argparse
import errno
import sys
import threading
import webbrowser
from collections.abc import Callable
from datetime import datetime
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
from .operational_log import configure_operational_logging
from .storage import StorageError, StorageWriter


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


def open_dashboard(
    url: str,
    browser_opener: Callable[[str], bool] = webbrowser.open_new_tab,
) -> bool:
    """Open the local dashboard without making browser failure fatal."""
    try:
        opened = bool(browser_opener(url))
    except (OSError, webbrowser.Error):
        opened = False
    if not opened:
        print(f"Browser did not open automatically. Open {url} manually.")
    return opened


def run(
    config_path: str | Path,
    *,
    open_browser: bool = False,
    browser_opener: Callable[[str], bool] = webbrowser.open_new_tab,
) -> None:
    resolved_config = Path(config_path).resolve()
    cfg = load_config(resolved_config)
    ensure_runtime_paths_writable(cfg)
    logger = configure_operational_logging(cfg)
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
                measurement_retention_days=int(
                    storage_cfg.get("measurement_retention_days", 400)
                ),
                event_retention_days=int(storage_cfg.get("event_retention_days", 400)),
                maintenance_interval_seconds=int(
                    storage_cfg.get("maintenance_interval_seconds", 3600)
                ),
                max_runtime_bytes=int(storage_cfg.get("max_runtime_bytes", 12_000_000_000)),
                warning_free_bytes=int(
                    storage_cfg.get("warning_free_bytes", 5_000_000_000)
                ),
                critical_free_bytes=int(
                    storage_cfg.get("critical_free_bytes", 2_000_000_000)
                ),
                backup_directory=str(storage_cfg["backup_directory"]),
                backup_interval_hours=float(storage_cfg.get("backup_interval_hours", 24)),
                backup_keep=int(storage_cfg.get("backup_keep", 7)),
            )
            collector = start_network_servers(cfg, writer)
            server.cfg = cfg
            server.config_path = str(resolved_config)
            server.collector = collector
            server.writer = writer

            dashboard_url = f"http://{host}:{port}"
            print(f"VFREG Visor {__version__}")
            print(f"Dashboard: {dashboard_url}")
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
            print("Backups:", storage_cfg["backup_directory"])
            logger.info(
                "VFREG Visor %s started config=%s dashboard=%s timezone=%s",
                __version__,
                resolved_config,
                dashboard_url,
                datetime.now().astimezone().tzinfo,
            )
            if open_browser:
                browser_timer = threading.Timer(
                    0.5,
                    open_dashboard,
                    args=(dashboard_url, browser_opener),
                )
                browser_timer.daemon = True
                browser_timer.start()
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
            logger.info("VFREG Visor stopped")


def main(
    argv: Sequence[str] | None = None,
    *,
    open_browser: bool = False,
) -> int:
    args = parse_args(argv)
    try:
        run(args.config, open_browser=open_browser)
    except (ConfigError, InstanceAlreadyRunning, StartupError, StorageError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"ERROR: VFREG could not start: {error}", file=sys.stderr)
        return 2
    return 0
