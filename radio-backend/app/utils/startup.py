from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from app.config.settings import settings
from app.logger.setup import get_logger

logger = get_logger("startup")

REQUIRED_ENV_VARS = [
    "ICECAST_HOST",
    "ICECAST_PORT",
    "ICECAST_USER",
    "ICECAST_PASSWORD",
    "ICECAST_MOUNT",
]


def verify_python_version() -> None:
    major, minor = sys.version_info[:2]
    logger.info(f"Python version: {major}.{minor}.{sys.version_info.micro}")
    if (major, minor) < (3, 10):
        raise RuntimeError(f"Python 3.10+ required, got {major}.{minor}")
    logger.info("✓ Python version OK")


def verify_ffmpeg() -> None:
    path = shutil.which(settings.ffmpeg_path)
    if path is None:
        raise RuntimeError(
            f"FFmpeg not found at {settings.ffmpeg_path!r}. "
            "Install ffmpeg or set FFMPEG_PATH."
        )
    try:
        result = subprocess.run(
            [path, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        version_line = result.stdout.splitlines()[0] if result.stdout else "unknown"
        logger.info(f"✓ FFmpeg found: {version_line}")
    except Exception as exc:
        raise RuntimeError(f"FFmpeg version check failed: {exc}") from exc


def verify_ytdlp() -> None:
    try:
        import yt_dlp
        logger.info(f"✓ yt-dlp version: {yt_dlp.version.__version__}")
    except ImportError as exc:
        raise RuntimeError("yt-dlp is not installed") from exc


def verify_env_vars() -> None:
    checks = {
        "ICECAST_HOST": settings.icecast_host,
        "ICECAST_PORT": str(settings.icecast_port),
        "ICECAST_USER": settings.icecast_user,
        "ICECAST_PASSWORD": settings.icecast_password,
        "ICECAST_MOUNT": settings.icecast_mount,
    }
    missing = [k for k, v in checks.items() if not v]
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Set them in .env or environment."
        )
    logger.info("✓ Required environment variables present")


def verify_icecast_reachable() -> None:
    host = settings.icecast_host
    port = settings.icecast_port
    logger.info(f"Checking Icecast reachability at {host}:{port}")
    try:
        with socket.create_connection((host, port), timeout=10):
            pass
        logger.info(f"✓ Icecast reachable at {host}:{port}")
    except Exception as exc:
        logger.warning(
            f"⚠ Icecast not reachable at {host}:{port}: {exc}. "
            "Starting anyway; player will retry."
        )


def verify_log_dir() -> None:
    log_path = Path(settings.log_dir)
    try:
        log_path.mkdir(parents=True, exist_ok=True)
        test_file = log_path / ".write_test"
        test_file.write_text("ok")
        test_file.unlink()
        logger.info(f"✓ Log directory writable: {log_path}")
    except Exception as exc:
        raise RuntimeError(f"Cannot write to log directory {log_path}: {exc}") from exc


def verify_internet() -> None:
    try:
        with socket.create_connection(("8.8.8.8", 53), timeout=5):
            pass
        logger.info("✓ Internet connectivity OK")
    except Exception as exc:
        logger.warning(f"⚠ Internet connectivity check failed: {exc}")


def detect_environment() -> None:
    env_type = "Unknown"
    if os.environ.get("RAILWAY_ENVIRONMENT"):
        env_type = f"Railway ({os.environ.get('RAILWAY_ENVIRONMENT')})"
    elif os.path.exists("/.dockerenv"):
        env_type = "Docker"
    else:
        env_type = f"Local ({platform.system()})"
    logger.info(f"✓ Environment: {env_type}")


def run_startup_checks() -> None:
    logger.info("=" * 60)
    logger.info("  Icecast Radio Backend — Startup Verification")
    logger.info("=" * 60)
    checks = [
        ("Python version", verify_python_version),
        ("FFmpeg", verify_ffmpeg),
        ("yt-dlp", verify_ytdlp),
        ("Environment variables", verify_env_vars),
        ("Log directory", verify_log_dir),
        ("Icecast reachability", verify_icecast_reachable),
        ("Internet connectivity", verify_internet),
        ("Deployment environment", detect_environment),
    ]
    for name, check_fn in checks:
        try:
            check_fn()
        except RuntimeError as exc:
            logger.error(f"✗ {name}: {exc}")
            raise
        except Exception as exc:
            logger.error(f"✗ {name}: unexpected error: {exc}", exc_info=True)
            raise RuntimeError(f"Startup check failed: {name}") from exc
    logger.info("=" * 60)
    logger.info("  All startup checks passed. Starting server.")
    logger.info("=" * 60)
