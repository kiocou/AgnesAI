from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from utils.path_utils import LOGS_DIR, ensure_directories


def setup_logging() -> logging.Logger:
    ensure_directories()
    logger = logging.getLogger("agnes_client")
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        log_path = LOGS_DIR / "app.log"
        handler = RotatingFileHandler(
            log_path,
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


LOGGER = setup_logging()

