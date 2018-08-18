from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from utils.path_utils import LOGS_DIR, ensure_directories


def setup_logging() -> logging.Logger:
    # Suppress noisy third-party loggers (uvicorn, httptools, websockets, etc.)
    for noisy in ("uvicorn", "uvicorn.access", "uvicorn.error",
                  "httptools", "websockets", "asyncio"):
        lg = logging.getLogger(noisy)
        lg.setLevel(logging.WARNING)
        lg.handlers.clear()

    # Root logger: collect everything, let handlers decide
    root = logging.getLogger()
    root.setLevel(logging.WARNING)

    logger = logging.getLogger("agnes_client")
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        try:
            ensure_directories()
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
        except Exception:
            # Best-effort: console fallback in frozen/unexpected envs
            try:
                handler = logging.StreamHandler(sys.stderr)
                handler.setFormatter(formatter)
                logger.addHandler(handler)
            except Exception:
                pass

    return logger


LOGGER = setup_logging()

