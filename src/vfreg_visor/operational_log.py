from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


LOGGER_NAME = "vfreg"


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
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    logger.addHandler(handler)
    return logger


def get_logger(component: str) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{component}")
