"""Centralized logging config."""
from __future__ import annotations

import logging
import logging.handlers
import os
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
LOG_DIR = PROJECT_ROOT / "logs"


def setup_logger(name: str = "holdings", level: str = "INFO") -> logging.Logger:
    LOG_DIR.mkdir(exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    logfile = LOG_DIR / f"holdings_{today}.log"

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
    # P2-3: Windows — midnight rotate may fail if file locked (tail -f, etc.)
    # Fall back silently instead of crashing the process
    def _safe_rotator(source, dest):
        try:
            os.rename(source, dest)
        except OSError:
            logger.warning("Log rotation failed (file locked?): %s -> %s", source, dest)
    fh.rotator = _safe_rotator
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # Console
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger
