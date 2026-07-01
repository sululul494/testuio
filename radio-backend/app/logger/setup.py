from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _ensure_log_dir(log_dir: str) -> Path:
    path = Path(log_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _make_handler(
    filepath: Path,
    max_bytes: int,
    backup_count: int,
    formatter: logging.Formatter,
) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        filepath,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(formatter)
    return handler


def setup_logging(
    log_dir: str,
    log_level: str = "INFO",
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)
    log_path = _ensure_log_dir(log_dir)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    console.setLevel(level)

    loggers_files: list[tuple[str, str]] = [
        ("radio.player", "player.log"),
        ("radio.api", "api.log"),
        ("radio.error", "errors.log"),
        ("radio.ffmpeg", "ffmpeg.log"),
        ("radio.ytdlp", "ytdlp.log"),
        ("radio.startup", "startup.log"),
        ("radio.autodj", "autodj.log"),
        ("radio.watchdog", "watchdog.log"),
    ]

    for logger_name, filename in loggers_files:
        logger = logging.getLogger(logger_name)
        logger.setLevel(level)
        logger.addHandler(console)
        logger.addHandler(
            _make_handler(log_path / filename, max_bytes, backup_count, fmt)
        )
        logger.propagate = False

    error_logger = logging.getLogger("radio.error")
    error_logger.setLevel(logging.ERROR)

    root = logging.getLogger("radio")
    root.setLevel(level)
    if not root.handlers:
        root.addHandler(console)
        root.addHandler(
            _make_handler(log_path / "radio.log", max_bytes, backup_count, fmt)
        )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"radio.{name}")
