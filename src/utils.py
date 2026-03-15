"""Logging setup and utility helpers."""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure application-wide logging with console + rotating file output."""
    logger = logging.getLogger("visa_scheduler")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Prevent duplicate handlers on re-init
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    # File handler with rotation
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    file_handler = RotatingFileHandler(
        logs_dir / "scheduler.log",
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def format_date(d: datetime | str) -> str:
    """Format a date for display."""
    if isinstance(d, str):
        d = datetime.strptime(d, "%Y-%m-%d")
    return d.strftime("%B %d, %Y (%A)")


def days_until(target: str, from_date: str | None = None) -> int:
    """Calculate days between two dates."""
    target_dt = datetime.strptime(target, "%Y-%m-%d").date()
    if from_date:
        from_dt = datetime.strptime(from_date, "%Y-%m-%d").date()
    else:
        from_dt = datetime.now().date()
    return (target_dt - from_dt).days
