"""Centralized logging config."""
from __future__ import annotations

import logging
import logging.handlers
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
LOG_DIR = PROJECT_ROOT / "logs"


def setup_logger(name: str = "ccass", level: str = "INFO") -> logging.Logger:
    LOG_DIR.mkdir(exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    logfile = LOG_DIR / f"ccass_{today}.log"

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, level.upper()))

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler with rotation (30 日)
    fh = logging.handlers.TimedRotatingFileHandler(
        logfile, when="midnight", backupCount=30, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    fh._shared_logger = True  # tag so disable_file_handler can find it
    logger.addHandler(fh)

    # Console
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger


def disable_file_handler(name: str = "ccass") -> None:
    """Remove the shared TimedRotatingFileHandler from a logger.

    Call this in shard subprocesses to prevent midnight-rotation
    race conditions on Windows (where os.rename fails if another
    process has the file open).
    """
    logger = logging.getLogger(name)
    for h in list(logger.handlers):
        if isinstance(h, logging.handlers.TimedRotatingFileHandler):
            logger.removeHandler(h)
