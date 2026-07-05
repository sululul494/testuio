from __future__ import annotations

import threading
import time
from typing import Optional

from app.config.settings import settings
from app.logger.setup import get_logger

logger = get_logger("watchdog")


class WatchdogService:
    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_activity: float = time.monotonic()
        self._restart_count: int = 0

    def start(self) -> None:
        logger.info("Watchdog starting")
        self._thread = threading.Thread(
            target=self._watch_loop,
            daemon=True,
            name="watchdog",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def ping(self) -> None:
        self._last_activity = time.monotonic()

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _watch_loop(self) -> None:
        from app.player.controller import player
        from app.icecast.connector import icecast_connector
        from app.autodj.manager import autodj_manager

        interval = settings.watchdog_interval
        max_silence = settings.watchdog_max_silence

        while not self._stop_event.wait(timeout=interval):
            try:
                self._check_player(player, max_silence)
                self._check_icecast(icecast_connector)
            except Exception as exc:
                logger.error(f"Watchdog error: {exc}", exc_info=True)

    def _check_player(self, player: object, max_silence: int) -> None:
        from app.player.controller import PlayerController
        assert isinstance(player, PlayerController)

        if not player.is_alive():
            logger.warning("Player thread is dead — restarting")
            try:
                player.start()
                self._restart_count += 1
                logger.info(f"Player restarted (total restarts: {self._restart_count})")
            except Exception as exc:
                logger.error(f"Failed to restart player: {exc}", exc_info=True)
            return

        if not player.is_playing():
            elapsed_since_last = time.monotonic() - self._last_activity
            logger.debug(
                f"Player not playing; silence for {elapsed_since_last:.0f}s "
                f"(max {max_silence}s)"
            )

    def _check_icecast(self, connector: object) -> None:
        from app.icecast.connector import IcecastConnector
        assert isinstance(connector, IcecastConnector)
        connected = connector.check_connection()
        if not connected:
            logger.warning("Icecast connection check failed")
        else:
            logger.debug("Icecast connection OK")


watchdog = WatchdogService()
