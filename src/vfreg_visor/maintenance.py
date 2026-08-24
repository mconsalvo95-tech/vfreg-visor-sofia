from __future__ import annotations

import argparse
from pathlib import Path

from .config import ConfigError, default_config_path, load_config
from .instance import DeploymentInstanceLock, InstanceAlreadyRunning
from .storage import (
    StorageError,
    create_sqlite_backup,
    restore_sqlite_backup,
    verify_sqlite_integrity,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="VFREG offline database maintenance")
    parser.add_argument("--config", default=str(default_config_path()))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("backup", help="Create and verify a backup now")
    verify = commands.add_parser("verify", help="Verify a SQLite database or backup")
    verify.add_argument("path")
    restore = commands.add_parser("restore", help="Restore a verified backup offline")
    restore.add_argument("path")
    restore.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm replacement of the configured SQLite history",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config_path = Path(args.config).resolve()
        cfg = load_config(config_path)
        storage = cfg["storage"]
        if args.command == "verify":
            valid, detail = verify_sqlite_integrity(Path(args.path).resolve())
            print(f"{'PASS' if valid else 'FAIL'}: {detail}")
            return 0 if valid else 2
        with DeploymentInstanceLock(config_path.parent):
            if args.command == "backup":
                destination = create_sqlite_backup(
                    cfg["output_sqlite"],
                    storage["backup_directory"],
                    keep=int(storage.get("backup_keep", 7)),
                )
                print("Verified backup created:", destination)
                return 0
            if not args.confirm:
                print("Restore cancelled: rerun with --confirm after stopping VFREG.")
                return 2
            destination = restore_sqlite_backup(args.path, cfg["output_sqlite"])
            print("Verified backup restored:", destination)
            return 0
    except (ConfigError, InstanceAlreadyRunning, OSError, StorageError) as error:
        print(f"ERROR: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
