from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


LOGGER_NAME = "vfreg"


class StructuredLogFormatter(logging.Formatter):
    """Emit one JSON object per line for machine-parseable operational logs."""

    def format(self, record: logging.LogRecord) -> str:
        component = record.name
        if component.startswith(f"{LOGGER_NAME}."):
            component = component[len(LOGGER_NAME) + 1 :]
        payload: dict[str, Any] = {
            "format_version": 1,
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            )
            .astimezone()
            .isoformat(timespec="milliseconds"),
            "severity": record.levelname,
            "logger": record.name,
            "component": component,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_operational_logging(cfg: dict[str, Any]) -> logging.Logger:
    """Configure a bounded UTF-8 application log for the active deployment."""
    storage = cfg.get("storage", {})
    path = Path(str(storage["application_log"]))
    path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)

    handler = RotatingFileHandler(
        path,
        maxBytes=int(storage.get("application_log_max_bytes", 10_485_760)),
        backupCount=int(storage.get("application_log_backups", 5)),
        encoding="utf-8",
    )
    handler.setFormatter(StructuredLogFormatter())
    logger.addHandler(handler)
    return logger


def get_logger(component: str) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{component}")
