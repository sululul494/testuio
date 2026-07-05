from __future__ import annotations

import signal
import sys
import threading
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.autodj.manager import autodj_manager
from app.config.settings import settings
from app.icecast.connector import icecast_connector
from app.logger.setup import get_logger, setup_logging
from app.player.controller import player
from app.services.watchdog import watchdog
from app.utils.startup import run_startup_checks

try:
    setup_logging(
        log_dir=settings.log_dir,
        log_level=settings.log_level,
        max_bytes=settings.log_max_bytes,
        backup_count=settings.log_backup_count,
    )
except Exception:
    import logging
    logging.basicConfig(level=logging.INFO)

logger = get_logger("startup")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Application startup sequence beginning")
    try:
        run_startup_checks()
    except RuntimeError as exc:
        logger.critical(f"Startup verification failed: {exc}")
        sys.exit(1)

    threading.Thread(target=icecast_connector.check_connection, daemon=True).start()
    autodj_manager.start()
    player.start()
    watchdog.start()

    logger.info("All services started successfully")
    yield

    logger.info("Application shutdown sequence beginning")
    watchdog.stop()
    player.stop()
    autodj_manager.stop()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Icecast Radio Backend",
    description=(
        "Production-grade internet radio backend. "
        "Streams audio from YouTube to Icecast via FFmpeg. "
        "Never downloads files — all streaming in-memory."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


def _handle_signal(sig: int, frame: object) -> None:
    logger.info(f"Received signal {sig} — initiating graceful shutdown")
    sys.exit(0)


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
        access_log=True,
        workers=1,
    )
