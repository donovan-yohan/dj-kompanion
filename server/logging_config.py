from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from server.config import CONFIG_DIR

LOG_DIR = CONFIG_DIR / "logs"
LOG_FILE = LOG_DIR / "server.log"

# 500 KB max per file, keep 2 backups (1.5 MB total max)
_MAX_BYTES = 500_000
_BACKUP_COUNT = 2

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(*, level: int = logging.DEBUG) -> None:
    """Configure root logger with console + rotating file output.

    Call once at server startup. Sets the root logger to the given level.
    The file handler captures everything at DEBUG level so claude raw output
    and enrichment details are always available for debugging.
    Safe to call multiple times -- subsequent calls are no-ops.
    """
    root = logging.getLogger()
    if root.handlers:
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    root.setLevel(level)
    root.addHandler(file_handler)
    root.addHandler(console_handler)
